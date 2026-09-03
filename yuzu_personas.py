"""
Swappable personas.

A persona is one file in personas/ describing a CHARACTER. The rules
about what the BODY can do live separately, in personas/_hardware_*.txt,
and get composed in at load time.

That split is the whole point. The bracket format, the action
vocabulary, the "always say something out loud" rule -- those aren't
Yuzu's personality, they're facts about a Yahboom Muto S2. Copying them
into every persona file would mean five copies drifting apart, and one
day fixing an action rule in four places and missing the fifth. Write
the character once, reference the body once.

It also means Saya's quadruped gets its own _hardware_ file (four legs,
an OLED face, no camera gimbal) and every persona can run on either
robot without being rewritten.

    python yuzu_personas.py                 # list personas
    python yuzu_personas.py --show yuzu     # print the composed prompt
    python yuzu_personas.py --check         # validate all of them
    python yuzu_personas.py --new saki      # scaffold a new one

FILE FORMAT -- plain text, editable on a phone:

    name: Yuzu
    archetype: Gyaru
    hardware: muto_s2
    temperature: 0.8
    led_idle: #FF69B4
    ---
    You are Yuzu, ...
    2. HARDWARE ACTION PARSING: {HARDWARE}

Everything above `---` is settings, everything below is the prompt.
{HARDWARE} and {DIALOGUE_RULE} are replaced from the hardware file.
"""

import argparse
import re
import sys
from pathlib import Path

HERE = Path(__file__).parent
PERSONA_DIR = HERE / "personas"

# The archive. yuzu.persona is v1, frozen, byte-pinned to
# _golden_yuzu_v1.txt by a test, and measured at a 20% action hit rate.
# It keeps the plain "yuzu" name because Modelfile.yuzu and the Ollama
# model called "yuzu" are named off it; renaming those would break every
# setup that already ran build_yuzu_model.py.
DEFAULT_PERSONA = "yuzu"

# The one that actually boots -- the robot loop, yuzu_brain --chat, and
# the eval all start here unless told otherwise.
#
# CLAUDE.md's promotion rule: the measured winner becomes the base. That
# is yuzu4 today (yuzu2 + the bare-command example; held live 4/4). When
# an A/B says something else won, THIS LINE is the only one that moves.
# It is separate from DEFAULT_PERSONA on purpose: booting the frozen 20%
# archive because it happens to own the short name is how the lineage
# quietly regresses.
LIVE_PERSONA = "yuzu4"

# Numbers get parsed as numbers; everything else stays a string.
_NUMERIC = {"temperature", "top_p", "top_k", "min_p", "repeat_penalty",
            "num_predict", "num_ctx", "piper_length_scale"}


class PersonaError(RuntimeError):
    """Raised with a message that says which file and what to fix."""


class Persona:
    def __init__(self, key, settings, prompt, path):
        self.key = key
        self.settings = settings
        self.prompt = prompt
        self.path = path

    @property
    def name(self):
        return self.settings.get("name", self.key.title())

    @property
    def archetype(self):
        return self.settings.get("archetype", "")

    @property
    def description(self):
        return self.settings.get("description", "")

    @property
    def hardware(self):
        return self.settings.get("hardware", "muto_s2")

    def options(self):
        """Sampling overrides for this persona, in Ollama's option names.
        A colder character can want a lower temperature than a hype
        gyaru; anything not set here falls back to yuzu_brain's defaults."""
        return {k: v for k, v in self.settings.items()
                if k in _NUMERIC and not k.startswith("piper_")}

    def led_states(self):
        """Per-persona LED colors, as {state: hex}. A tsundere shouldn't
        glow the same pink as a gyaru."""
        return {k[len("led_"):]: v for k, v in self.settings.items()
                if k.startswith("led_")}

    def __repr__(self):
        return f"<Persona {self.key} ({self.archetype})>"


def _parse_hardware(name):
    path = PERSONA_DIR / f"_hardware_{name}.txt"
    if not path.exists():
        available = sorted(p.stem[len("_hardware_"):]
                           for p in PERSONA_DIR.glob("_hardware_*.txt"))
        raise PersonaError(
            f"No hardware file '{path.name}'.\n"
            f"  Available: {', '.join(available) or '(none)'}\n"
            f"  Fix the 'hardware:' line in the persona, or add that file."
        )
    # A section header is a bare [UPPER_SNAKE] line and nothing else.
    # This has to be strict: an action menu line reads
    #     [walks forward] [walks backward] ... [spins]
    # which also starts with '[' and ends with ']'. A loose check
    # swallowed the whole menu as a header and silently dropped the
    # body's action list from the composed prompt -- a prompt that looks
    # fine and quietly tells the model nothing about what it can do.
    header = re.compile(r'^\[([A-Z][A-Z0-9_]*)\]$')
    blocks, current = {}, None
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("#") and current is None:
            continue
        match = header.match(line.strip())
        if match:
            current = match.group(1)
            blocks[current] = []
        elif current is not None:
            blocks[current].append(line)
    return {k: "\n".join(v).strip() for k, v in blocks.items()}


def load(key=LIVE_PERSONA):
    """Load one persona and compose its full system prompt."""
    path = PERSONA_DIR / f"{key}.persona"
    if not path.exists():
        raise PersonaError(
            f"No persona '{key}'.\n"
            f"  Available: {', '.join(available()) or '(none)'}\n"
            f"  Make one:  python yuzu_personas.py --new {key}"
        )

    raw = path.read_text(encoding="utf-8")
    if "---" not in raw:
        raise PersonaError(
            f"{path.name} has no '---' line. Settings go above it, the "
            f"prompt below it."
        )
    head, _, body = raw.partition("\n---")

    settings = {}
    for number, line in enumerate(head.splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            raise PersonaError(
                f"{path.name} line {number}: '{line}' isn't a "
                f"'setting: value' pair. Prompt text goes below '---'."
            )
        field, value = line.split(":", 1)
        field, value = field.strip(), value.strip()
        if field in _NUMERIC:
            try:
                value = float(value) if "." in value else int(value)
            except ValueError:
                raise PersonaError(
                    f"{path.name} line {number}: {field} should be a "
                    f"number, got '{value}'."
                ) from None
        settings[field] = value

    prompt = body.strip()
    if not prompt:
        raise PersonaError(f"{path.name} has no prompt text below '---'.")

    body = settings.get("hardware", "muto_s2")
    blocks = _parse_hardware(body)

    # Blocks may reference other blocks, so substitute repeatedly until
    # the text stops changing. A single pass only worked while the
    # referenced block happened to be defined AFTER the one using it --
    # reordering the file would have silently left a raw {TOKEN} in the
    # prompt. The cap turns a circular reference into an error instead
    # of a hang.
    for _ in range(10):
        expanded = prompt
        for token, text in blocks.items():
            expanded = expanded.replace("{" + token + "}", text)
        if expanded == prompt:
            break
        prompt = expanded
    else:
        raise PersonaError(
            f"_hardware_{body}.txt: blocks reference each other in a loop."
        )

    leftover = sorted(set(re.findall(r'\{([A-Z][A-Z0-9_]*)\}', prompt)))
    if leftover:
        # A token that survived expansion but IS defined can only mean
        # the blocks reference each other in a cycle -- expansion
        # reaches a fixed point instead of running away, so the loop
        # above exits without ever hitting its cap.
        circular = [t for t in leftover if t in blocks]
        if circular:
            raise PersonaError(
                f"_hardware_{body}.txt: {', '.join(circular)} reference each "
                f"other in a loop, so they never expand."
            )
        raise PersonaError(
            f"{path.name} uses {', '.join('{' + t + '}' for t in leftover)} "
            f"but '_hardware_{body}.txt' doesn't define "
            f"{'them' if len(leftover) > 1 else 'it'}.\n"
            f"  Defined there: {', '.join(sorted(blocks)) or '(none)'}"
        )
    return Persona(key, settings, prompt, path)


def available():
    """Persona keys, alphabetical. Files starting with _ are internal."""
    if not PERSONA_DIR.exists():
        return []
    return sorted(p.stem for p in PERSONA_DIR.glob("*.persona")
                  if not p.stem.startswith("_"))


TEMPLATE = """name: {title}
archetype: (Tsundere / Kuudere / Himedere / Yandere / Gyaru ...)
hardware: muto_s2
description: one line, for the persona list
temperature: 0.8
led_idle: #FF69B4
led_speaking: #FF1493
led_thinking: #B026FF
piper_length_scale: 0.9
---
You are {title}, (one sentence: who she is and how she talks).

CORE DIRECTIVES:

1. PERSONALITY: (how she speaks, what she never sounds like. Say she
   answers direct questions before adding flair.) {{DIALOGUE_RULE}}
2. HARDWARE ACTION PARSING: {{HARDWARE}}
3. (a directive for her particular temperament)
4. NO PUPPETEERING: Never speak, act, or dictate actions for the user.
   Only write responses and movements for {title}.
5. (her aesthetic / what she likes)

EXAMPLE (follow this format exactly, every single time):
User: Hey {title}, what's up?
{title}: (a reply in her voice, with [one bracketed action] in it)
"""


def scaffold(key):
    path = PERSONA_DIR / f"{key}.persona"
    if path.exists():
        raise PersonaError(f"{path.name} already exists -- not overwriting.")
    PERSONA_DIR.mkdir(exist_ok=True)
    path.write_text(TEMPLATE.format(title=key.title()), encoding="utf-8")
    return path


def _cli(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--show", metavar="KEY",
                        help="print a persona's composed system prompt")
    parser.add_argument("--check", action="store_true",
                        help="validate every persona file")
    parser.add_argument("--new", metavar="KEY", help="scaffold a new persona")
    args = parser.parse_args(argv)

    if args.new:
        try:
            path = scaffold(args.new.lower())
        except PersonaError as exc:
            print(exc)
            return 1
        print(f"Created {path}\nEdit it, then:  python yuzu_personas.py "
              f"--show {args.new.lower()}")
        return 0

    if args.show:
        try:
            persona = load(args.show.lower())
        except PersonaError as exc:
            print(f"\n{exc}\n")
            return 1
        print(f"--- {persona.name} ({persona.archetype}) ---\n")
        print(persona.prompt)
        return 0

    keys = available()
    if not keys:
        print("No personas found in personas/")
        return 1

    failures = 0
    print(f"{len(keys)} persona(s):\n")
    for key in keys:
        try:
            persona = load(key)
        except PersonaError as exc:
            failures += 1
            print(f"  {key:<10} BROKEN -- {str(exc).splitlines()[0]}")
            continue
        marker = ("  <- LIVE, this is what boots" if key == LIVE_PERSONA
                  else "  (frozen archive)" if key == DEFAULT_PERSONA else "")
        print(f"  {key:<10} {persona.name} -- {persona.archetype}{marker}")
        if persona.description:
            print(f"             {persona.description}")
        if args.check:
            print(f"             body: {persona.hardware}, "
                  f"{len(persona.prompt)} chars, "
                  f"options {persona.options() or '(defaults)'}")

    if failures:
        print(f"\n{failures} persona(s) failed to load.")
        return 1
    print(f"\nUse one:  python yuzu_brain.py --persona <key> --chat")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
