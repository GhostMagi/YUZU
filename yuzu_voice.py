"""
Yuzu's voice -- Piper TTS, isolated behind its own module.

    python3 yuzu_voice.py            # say a few real replies out loud
    python3 yuzu_voice.py --check    # just report what's installed
    python3 yuzu_voice.py --say "PFFT! hey cutie"   # test any line
    python3 yuzu_voice.py --raw "pfft"              # skip the cleanup
    python3 yuzu_voice.py --tryout pfft             # audition spellings
    python3 yuzu_voice.py --list                    # every voice installed
    python3 yuzu_voice.py --use lessac              # switch to one, for good

THE DEPENDENCY BOUNDARY LIVES HERE, DELIBERATELY.

Everything else in this project is standard library, which is why it
runs in Pydroid on a phone with nothing installed. Piper is a real
binary and a real model file, and neither exists on the phone. So this
module is the only thing that knows about them, `yuzu_all_in_one.py`
imports it in a try/except like it does the gaits, and
with Piper absent she prints exactly as she always did.

Nothing here imports Piper as a Python package either. It shells out to
the `piper` binary with `subprocess`, which is stdlib, so this file
adds no pip dependency to the project at all -- you install Piper the
program, not a library this code links against.

WHAT IS AND ISN'T VERIFIED

Verified by machine: the text that reaches TTS (see for_speech below,
and TestVoice, which replays the whole historical reply corpus), the
command construction, the flag detection, and that every failure path
falls back to printing instead of raising into the conversation loop.

NOT verified from here: how any of it SOUNDS. There is no audio device
and no Piper on the machine this was written on. The demo at the bottom
exists so that takes thirty seconds to find out rather than being
guessed at -- run it and listen, the same way every prompt claim in
this repo got settled.
"""

import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

HERE = Path(__file__).parent

# Point at a specific .onnx to skip the search:  export YUZU_VOICE=/path/to.onnx
VOICE_ENV = "YUZU_VOICE"

# Where a downloaded Piper voice usually lands. A voice is TWO files
# with the same stem -- model.onnx and model.onnx.json -- and Piper
# fails confusingly if the .json is missing, so the search insists on
# both being present before calling a voice usable.
VOICE_DIRS = (
    HERE,
    HERE / "voices",
    Path.home() / ".local/share/piper",
    Path.home() / "piper",
    Path.home() / "Downloads",
    Path("/usr/share/piper-voices"),
    Path("/opt/piper"),
)

# Players, in preference order. aplay is on any ALSA box including the
# Jetson; paplay is PulseAudio; afplay is macOS; ffplay is the catch-all
# that comes with ffmpeg.
PLAYERS = (
    ("aplay", ("-q",)),
    ("paplay", ()),
    ("afplay", ()),
    ("ffplay", ("-nodisp", "-autoexit", "-loglevel", "quiet")),
)

# How long to wait on one utterance before giving up and printing. A
# sentence is a second or two; a minute means something is wedged, and
# a wedged robot that has stopped talking is worse than a silent one.
TIMEOUT = int(os.environ.get("YUZU_VOICE_TIMEOUT", "60"))


class VoiceError(RuntimeError):
    """Piper or a voice file is missing. Carries what to do about it."""


# ---------------------------------------------------------------------
# The part that matters most, and the only part that can be tested
# without a speaker: what text actually reaches the synthesiser.
# ---------------------------------------------------------------------

# Derived from the real reply corpus in YUZU_TESTER.py, not imagined.
# Replaying all 26 captured replies through the pipeline, exactly two
# kinds of non-plain character survive into speech:
#
#   '*'  x2   from "it's 2 * 3 * 4 babe" -- normalize_actions leaves a
#             bare multiplication sign alone on purpose, because the
#             version that didn't ate the middle of the sentence.
#   '~'  x1   from "Ehehe~", which is her signature laugh.
#
# Both would be handed to Piper today. Neither is a word.
# CONFIRMED Sept 3, en_US-amy-medium, by direct A/B on one word:
#
#     "SIX legs"  -> spelled out, letter by letter
#     "six legs"  -> said properly
#
# Same word, same sentence, only the case changed. So capitals really
# do trigger spelling-out, independently of the vowel-less problem that
# "pfft" turned out to have. Two separate mechanisms; this is the one
# lowercasing actually fixes.
#
# Blanket-lowercasing is still wrong, because two different things wear
# capitals in her voice:
#
#   OMG, OG   -- genuine initialisms. "oh em gee" IS how you say them,
#                and lowercasing would break what currently works.
#   PFFT, HAHA, GOSH, SIX, DANCE, MY, SUPER
#             -- shouted words. Spelling them is nonsense.
#
# So: keep the initialisms capitalised, lowercase everything else. The
# caps carried no sound anyway -- Piper takes no emphasis from them --
# so nothing is lost by dropping them, and speak() prints the ORIGINAL
# text, so her transcript still shows her shouting.
SPOKEN_INITIALISMS = {
    "OMG", "OG", "IDK", "TBH", "LOL", "LMAO", "BRB", "BFF",
    "AF", "FR", "DIY", "DJ", "TV", "PC", "AI", "OK",
}
_SHOUTED = re.compile(r'\b[A-Z]{2,}\b')
_TILDE_RUN = re.compile(r'~+')
_ASTERISK = re.compile(r'\*+')
_EMOJI_AND_SYMBOLS = re.compile(
    "[" "\U0001F000-\U0001FAFF" "☀-➿" "️" "←-⇿" "]"
)
_WHITESPACE = re.compile(r'\s+')


# Vowel-less noises espeak-ng cannot phonemise, so it falls back to
# spelling them letter by letter. MEASURED Sept 3: "PFFT!" came back
# "Pee Eff Eff Tee" -- and it STILL did after being lowercased, which
# is what ruled out capitalisation as the cause. A token with no vowel
# has nothing for the letter-to-sound rules to bite on.
#
# The values here are spellings that DO have something to bite on. They
# are the one thing in this file nobody has listened to yet:
#     python3 yuzu_voice.py --tryout pfft
# speaks the candidates so the right one gets picked by ear instead of
# by me guessing twice in a row.
# Noises espeak simply cannot make. MEASURED Sept 3, three rounds:
#
#   "PFFT!"                     -> "Pee Eff Eff Tee"
#   lowercased to "pfft"        -> still "pee eff eff tee"
#   respelled puft/pift/puh/... -> none of them worked either
#
# A speech synthesiser says WORDS. A bilabial raspberry is not one, and
# no spelling of it is going to become one. The third round is where
# that stopped being worth another guess.
#
# So they are DROPPED, which is the same call the action whitelist
# already makes: an action this body can't do produces silence, never a
# substitute movement. A noise this voice can't make produces silence
# too, and the rest of the sentence survives intact. "PFFT! My camera
# is shaking!" becomes "My camera is shaking!" -- her transcript still
# prints the PFFT, because speak() prints the original.
#
# Ghost's call, Sept 3: Pfft is also GONE FROM THE PROMPT, which is the
# better fix and the one that actually reduces how often it shows up.
# This stays as the net, for the same reason the action whitelist stays
# even though the prompt lists the legal moves: the prompt REDUCES,
# code GUARANTEES. [winks] is named as forbidden and still turned up in
# 3 of 4 live replies -- "Pfft" is ordinary English the base model
# knows with or without being taught it. Say the word and I'll pull
# these four lines; nothing else depends on them.
UNSAYABLE = ("pfft", "pft")
_UNSAYABLE = re.compile(
    r'\b(?:' + "|".join(UNSAYABLE) + r')\b[!?.,]*\s*', re.IGNORECASE)

# Kept only to audition alternatives if dropping ever feels too lossy.
# Nothing here is applied.
SAYABLE = {}

# Candidate spellings to audition for a noise, when the default is
# wrong. Order is roughly "closest to the written form" first.
# Candidates to audition. Nothing here is applied -- it exists so a
# noise gets judged by ear before anything is done to it. If espeak
# already says "tsk" correctly, the right change is no change.
#
# "pfft" is SETTLED: none of these worked, which is what moved it to
# UNSAYABLE. Kept so the finding can be re-heard rather than re-argued.
TRYOUTS = {
    "pfft": ["pfft", "puft", "pift", "puh", "pfff", "pshh"],
    "psh": ["psh", "pish", "pshh", "pssh"],
    "hmph": ["hmph", "humph", "hmmph"],
    "tsk": ["tsk", "tisk", "tut"],
    "shh": ["shh", "shush", "shhh"],
    "grr": ["grr", "gurr", "grrr"],
}

_WORD = re.compile(r"[A-Za-z']+")


def sayable(text: str) -> str:
    """Drop noises this voice cannot make.

    Fails the same way the action whitelist does: silence, never a
    mangled substitute. The sentence around it is untouched.
    """
    return _UNSAYABLE.sub("", text)


def unshout(text: str) -> str:
    """Lowercase shouted words, keep real initialisms capitalised.

    See SPOKEN_INITIALISMS. This exists because someone listened, which
    is the only way anything in this project gets decided.
    """
    return _SHOUTED.sub(
        lambda m: m.group(0) if m.group(0) in SPOKEN_INITIALISMS
        else m.group(0).lower(),
        text)


def for_speech(text: str) -> str:
    """Clean one line of dialogue for the synthesiser.

    Runs AFTER strip_actions, so the brackets are already gone and
    what's left is meant to be said out loud. The job is to remove
    things that aren't words and fix things that would be mispronounced
    -- never to rewrite her voice.
    """
    if not text:
        return ""
    text = _TILDE_RUN.sub("", text)       # Ehehe~ -> Ehehe
    text = _ASTERISK.sub(" ", text)       # a bare * is never a word
    text = _EMOJI_AND_SYMBOLS.sub(" ", text)
    text = unshout(text)                  # PFFT -> pfft, OMG stays OMG
    text = sayable(text)                  # pfft -> something with a vowel
    return _WHITESPACE.sub(" ", text).strip()


# ---------------------------------------------------------------------
# Finding Piper and a voice
# ---------------------------------------------------------------------

# Where pip puts a script when it does a --user install, which is what
# it silently falls back to whenever site-packages isn't writable. It
# prints a warning about PATH in the middle of thirty lines of download
# output, so in practice nobody sees it and the binary looks missing
# when it is sitting right there.
EXTRA_BIN_DIRS = (
    Path.home() / ".local/bin",
    Path("/usr/local/bin"),
    Path("/opt/piper"),
)


def find_piper():
    """The piper executable, or None.

    PATH first, then the places a --user pip install actually lands.
    Telling someone piper isn't installed when it is, is a worse
    failure than not looking hard enough.
    """
    found = shutil.which("piper")
    if found:
        return found
    for directory in EXTRA_BIN_DIRS:
        candidate = directory / "piper"
        try:
            if candidate.is_file() and os.access(candidate, os.X_OK):
                return str(candidate)
        except OSError:
            continue
    return None


# Remembers which voice was picked, so a second download doesn't
# silently change who she sounds like. One line of plain text holding a
# filename -- no config format, editable from a phone, and deleting it
# just falls back to the first voice found.
ACTIVE_FILE = HERE / "voices" / "ACTIVE"


def list_voices():
    """Every usable voice on this machine, in search order.

    A voice is TWO files with the same stem -- model.onnx AND
    model.onnx.json. Piper's error when the json is missing does not
    mention the json, which is a genuinely miserable half hour, so a
    voice missing its json is not listed as usable at all.
    """
    found, seen = [], set()
    for directory in VOICE_DIRS:
        try:
            if not directory.is_dir():
                continue
            for onnx in sorted(directory.glob("*.onnx")):
                real = onnx.resolve()
                if real in seen:
                    continue
                seen.add(real)
                if onnx.with_suffix(".onnx.json").is_file():
                    found.append(onnx)
        except (OSError, PermissionError):
            continue
    return found


def remembered_voice():
    """The voice named in voices/ACTIVE, if it still exists."""
    try:
        name = ACTIVE_FILE.read_text(encoding="utf-8").strip()
    except (OSError, PermissionError):
        return None
    if not name:
        return None
    for voice in list_voices():
        if voice.name == name:
            return voice
    return None


def use_voice(fragment):
    """Remember a voice by any part of its name. Returns the path."""
    matches = [v for v in list_voices() if fragment.lower() in v.name.lower()]
    if not matches:
        raise VoiceError(
            f"No installed voice matches '{fragment}'.\n"
            f"  Installed: "
            f"{', '.join(v.name for v in list_voices()) or '(none)'}\n"
            f"  Download more into {HERE / 'voices'} -- see "
            f"JETSON_SETUP.md section 6."
        )
    if len(matches) > 1:
        raise VoiceError(
            f"'{fragment}' matches {len(matches)} voices:\n  " +
            "\n  ".join(v.name for v in matches) +
            "\n  Be more specific."
        )
    ACTIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    ACTIVE_FILE.write_text(matches[0].name + "\n", encoding="utf-8")
    return matches[0]


def find_voice():
    """A usable .onnx voice, or None.

    Order: YUZU_VOICE for a one-off, then whatever --use remembered,
    then the first voice found. That last fallback is why the other two
    exist -- with two voices in the folder it silently picks
    alphabetically, so downloading a nicer one and hearing the old one
    would look like nothing happened.
    """
    override = os.environ.get(VOICE_ENV)
    if override:
        path = Path(override).expanduser()
        if path.is_file() and path.with_suffix(".onnx.json").is_file():
            return path
        raise VoiceError(
            f"{VOICE_ENV} points at {path}, but that isn't a usable voice.\n"
            f"  A voice is TWO files: model.onnx AND model.onnx.json.\n"
            f"  Both have to sit in the same folder."
        )
    remembered = remembered_voice()
    if remembered:
        return remembered
    installed = list_voices()
    return installed[0] if installed else None


def find_player():
    """(command, extra_args) for the first audio player present."""
    for name, args in PLAYERS:
        found = shutil.which(name)
        if found:
            return found, args
    return None, ()


# ---------------------------------------------------------------------
# Piper's flag names differ between builds -- ask, don't guess
# ---------------------------------------------------------------------

def detect_flags(help_text):
    """Pick the flag spellings this Piper build actually accepts.

    Piper has shipped both `--output_file` and `--output-file`, and both
    `--length_scale` and `--length-scale`, depending on version. Getting
    it wrong is an unrecognized-arguments error and silence. Reading its
    own --help is cheap, happens once, and cannot be out of date the way
    a hardcoded guess can.
    """
    def pick(*candidates):
        for flag in candidates:
            if flag in help_text:
                return flag
        return candidates[0]

    return {
        "output": pick("--output_file", "--output-file"),
        "length": pick("--length_scale", "--length-scale"),
        "model": pick("--model", "-m"),
    }


# ---------------------------------------------------------------------
# The voice itself
# ---------------------------------------------------------------------

class Voice:
    """A Piper voice. Construct it once; call say() per line.

    say() NEVER raises. A conversation that stops because the speaker
    failed is worse than one that carries on silently -- the same
    reasoning as the motor-fault handling in the gait wrapper.
    """

    def __init__(self, model=None, length_scale=None, piper=None):
        self.piper = piper or find_piper()
        self.model = Path(model) if model else None
        self.length_scale = length_scale
        self.player, self.player_args = find_player()
        self.failures = []
        self._flags = None
        if self.model is None:
            self.model = find_voice()

    @property
    def ready(self):
        return bool(self.piper and self.model and self.player)

    def why_not(self):
        """One line saying what's missing, and how to get it."""
        if not self.piper:
            return ("piper isn't installed, or isn't anywhere findable. "
                    "Try:  pip install piper-tts  "
                    "(then check ~/.local/bin is on your PATH)")
        if not self.model:
            return (f"no Piper voice found. Download one (.onnx AND "
                    f".onnx.json) into {HERE / 'voices'}, or set "
                    f"{VOICE_ENV}=/path/to/voice.onnx")
        if not self.player:
            names = ", ".join(name for name, _ in PLAYERS)
            return f"no audio player found. Install one of: {names}"
        return ""

    def flags(self):
        if self._flags is None:
            try:
                result = subprocess.run([self.piper, "--help"],
                                        capture_output=True, text=True,
                                        timeout=20)
                self._flags = detect_flags(result.stdout + result.stderr)
            except (OSError, subprocess.SubprocessError):
                self._flags = detect_flags("")
            except Exception:                       # noqa: BLE001
                self._flags = detect_flags("")
        return self._flags

    def command(self, wav_path):
        """The piper invocation for one utterance."""
        flags = self.flags()
        argv = [self.piper, flags["model"], str(self.model),
                flags["output"], str(wav_path)]
        if self.length_scale is not None:
            argv += [flags["length"], str(self.length_scale)]
        return argv

    def say(self, text, clean=True):
        """Speak one line. Returns True if audio actually played.

        clean=False speaks the string exactly as given, which is how
        `--raw` and `--tryout` audition a spelling without for_speech
        rewriting it first.
        """
        spoken = for_speech(text) if clean else text.strip()
        if not spoken or not self.ready:
            return False
        wav = None
        try:
            handle, wav = tempfile.mkstemp(suffix=".wav", prefix="yuzu-")
            os.close(handle)
            result = subprocess.run(
                self.command(wav), input=spoken, text=True,
                capture_output=True, timeout=TIMEOUT)
            if result.returncode != 0:
                # Surface Piper's OWN message. It names the real problem
                # -- a missing json, a bad flag, an incompatible model --
                # far better than anything guessed from here.
                self.failures.append(
                    (result.returncode,
                     (result.stderr or "").strip().splitlines()[-1:] or ["?"]))
                return False
            if not os.path.getsize(wav):
                self.failures.append((0, ["piper produced an empty wav"]))
                return False
            subprocess.run([self.player, *self.player_args, wav],
                           capture_output=True, timeout=TIMEOUT)
            return True
        except (OSError, subprocess.SubprocessError) as exc:
            self.failures.append((None, [str(exc)]))
            return False
        finally:
            if wav:
                try:
                    os.unlink(wav)
                except OSError:
                    pass


# ---------------------------------------------------------------------
# Demo -- the fastest way to find out how any of this actually sounds
# ---------------------------------------------------------------------

# Real captured model output, chosen for the things most likely to come
# out wrong. Every one of these has been through the pipeline; this is
# the text as Piper receives it.
DEMO_LINES = [
    "Not much, just vibing! What's good with you?",
    "Ehehe~ okay okay, I'm a kitty cat on six legs!",     # the tilde
    "PFFT! My camera is shaking!",                        # shouted word
    "MY. GOSH. SIX legs!",                                # more shouting
    "OMG, like, hi! My OG granddad!",                     # real initialisms
    "Aw, no arms on this chassis, cutie! That wiggle is a hug in robot.",
    "Paris! North of the country, big pointy tower, unreal shopping.",
]

LISTEN_FOR = """
Listen for these three things. The line under each is what Piper
actually receives -- if the sound doesn't match the text, that's a bug
worth reporting.

  1. "PFFT!"      -- SETTLED. Three rounds: spelled out, still spelled
                     out lowercased, and no respelling worked either. A
                     synthesiser says words and a raspberry isn't one,
                     so it is DROPPED. You should hear "My camera is
                     shaking!" with no noise in front of it.
  2. "OMG"/"OG"   -- the opposite case, and still unheard. They stay
                     capitalised on purpose: "oh em gee" and "oh gee"
                     IS how you say them. If they come out as mush, the
                     allowlist in SPOKEN_INITIALISMS is wrong.
  3. Speed        -- yuzu4 asks for length_scale 0.88, slightly faster
                     than default. Coco runs 1.08, slower. If she sounds
                     rushed or sedated, that dial is one line in her
                     .persona file.
"""


def _show_voices():
    installed = list_voices()
    if not installed:
        print(f"\nNo voices installed. Put a matching .onnx AND .onnx.json "
              f"into\n  {HERE / 'voices'}\nBrowse and LISTEN first at "
              f"rhasspy.github.io/piper-samples -- downloading a voice you "
              f"haven't\nheard is how you end up with three you don't want.")
        return 1
    try:
        active = find_voice()
    except VoiceError as exc:
        print(f"\n{exc}\n")
        active = None
    print(f"\n{len(installed)} voice(s) installed:\n")
    for voice in installed:
        size = voice.stat().st_size / 1e6
        mark = "  <- ACTIVE" if active and voice == active else ""
        print(f"  {voice.name:<34} {size:>5.0f} MB{mark}")
    if os.environ.get(VOICE_ENV):
        print(f"\n{VOICE_ENV} is set, and it wins over everything else.")
    elif ACTIVE_FILE.exists():
        print(f"\nRemembered in {ACTIVE_FILE}")
    elif len(installed) > 1:
        print("\nNothing is chosen, so the FIRST one alphabetically wins.")
        print("Pick deliberately:  python3 yuzu_voice.py --use <part of name>")
    print("\nSwitch:  python3 yuzu_voice.py --use <part of the name>")
    print("Hear it: python3 yuzu_voice.py")
    return 0


def _cli(argv):
    check_only = "--check" in argv
    if "--list" in argv:
        return _show_voices()
    if "--use" in argv:
        index = argv.index("--use")
        fragment = " ".join(argv[index + 1:]).strip()
        if not fragment:
            print("Which one? Try:  python3 yuzu_voice.py --list")
            return 1
        try:
            chosen = use_voice(fragment)
        except VoiceError as exc:
            print(f"\n{exc}\n")
            return 1
        print(f"Now using {chosen.name}")
        print("Hear it:  python3 yuzu_voice.py")
        return 0
    say_text = raw_text = tryout = None
    for flag, target in (("--say", "say"), ("--raw", "raw"),
                         ("--tryout", "tryout")):
        if flag in argv:
            index = argv.index(flag)
            value = " ".join(argv[index + 1:]) if index + 1 < len(argv) else ""
            if target == "say":
                say_text = value
            elif target == "raw":
                raw_text = value
            else:
                tryout = value.strip().lower()
    voice = Voice()

    print("PIPER   ", voice.piper or "NOT FOUND")
    print("VOICE   ", voice.model or "NOT FOUND")
    print("PLAYER  ", voice.player or "NOT FOUND")
    if not voice.ready:
        print(f"\n  {voice.why_not()}\n")
        print("Nothing is broken -- Yuzu falls back to printing her lines,")
        print("which is exactly what she did before this file existed.")
        return 1

    print("FLAGS   ", voice.flags())
    print("COMMAND ", " ".join(voice.command("/tmp/example.wav")))
    if check_only:
        return 0

    if tryout is not None:
        candidates = TRYOUTS.get(tryout, [tryout])
        print(f"\nAuditioning {len(candidates)} spellings of '{tryout}'.")
        print("Say which one sounded right -- that is the whole test.\n")
        for candidate in candidates:
            print(f"  {candidate}")
            voice.say(candidate, clean=False)
        print(f"\nCurrent mapping: {tryout} -> "
              f"{SAYABLE.get(tryout, '(unmapped, said as written)')}")
        return 0

    if raw_text is not None:
        print(f'raw (no cleanup): "{raw_text}"')
        voice.say(raw_text, clean=False)
        return 0

    if say_text is not None:
        cleaned = for_speech(say_text)
        print(f'wrote : "{say_text}"')
        print(f'saying: "{cleaned}"')
        voice.say(say_text)
        return 0

    print(LISTEN_FOR)
    for line in DEMO_LINES:
        cleaned = for_speech(line)
        if cleaned != line:
            print(f'  wrote : "{line}"')
            print(f'  saying: "{cleaned}"')
        else:
            print(f'  saying: "{cleaned}"')
        if not voice.say(line):
            print("     ...that one didn't play.")
    if voice.failures:
        print("\nFailures:")
        for code, lines in voice.failures:
            print(f"  exit {code}: {' '.join(lines)}")
        return 1
    print("\nIf you heard all of those, she has a voice. Wire it into the")
    print("robot with:  python3 yuzu_all_in_one.py")
    return 0


if __name__ == "__main__":
    import sys
    raise SystemExit(_cli(sys.argv[1:]))
