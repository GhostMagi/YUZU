"""
Yuzu, all in one file -- combines the reply pipeline (fix/extract/run/
strip/speak) with the main loop (listen -> think -> respond) so there's
nothing to import and nothing to accidentally save in the wrong folder.

listen_and_transcribe() is still a STUB -- swap it for real Whisper
once a mic is hooked up. The brain is real: it talks to Ollama via
yuzu_brain.py, and falls back to an echo stub when Ollama isn't up.

This file will run anywhere, including Pydroid on the phone, with no
hardware and no other files present. If muto_leg_control.py and
yuzu_led_manager.py ARE sitting next to it, it picks them up
automatically: bracketed actions drive real gaits, and the LEDs follow
what Yuzu is doing (thinking / moving / speaking / idle). If they're
missing it falls back to printing, exactly like it always did.
"""

import os
import re
import time

# --- Optional siblings. Missing = print-only mode, never a crash. -----
try:
    import muto_leg_control as legs
except ImportError:
    legs = None

try:
    from yuzu_led_manager import LEDManager
except ImportError:
    LEDManager = None

try:
    from yuzu_brain import BrainError, YuzuBrain
except ImportError:
    YuzuBrain = None
    BrainError = Exception

try:
    import yuzu_personas
except ImportError:
    yuzu_personas = None


# ============================================================================
# PART 0: HARDWARE BINDING
# ============================================================================

# g_bot is the real Yahboom robot object once hardware exists:
#     from muto_lib import Muto_Bot
#     g_bot = Muto_Bot()
# Until then muto_leg_control.DummyBot stands in and prints servo traffic.
g_bot = legs.DummyBot(verbose=False) if legs else None

leds = LEDManager() if LEDManager else None


def set_led_state(state):
    """Nudge the lights. No-op when the LED manager isn't around."""
    if leds:
        leds.apply_state(state)


# ============================================================================
# PART 1: THE REPLY PIPELINE
# ============================================================================

# Each robot function calls the real gait when muto_leg_control is
# importable, and otherwise prints -- so the pipeline is testable on a
# phone and correct on the Jetson without touching this file again.
def _gait(name, printed, **kwargs):
    def run():
        if legs and g_bot:
            getattr(legs, name)(g_bot, **kwargs)
        else:
            print(f"ROBOT: {printed}")
    return run


walk_forward  = _gait("walk_forward",  "walking forward")
walk_backward = _gait("walk_backward", "walking backward")
turn_action   = _gait("turn",          "turning")
squat         = _gait("squat",         "squatting")
stand         = _gait("stand",         "standing")
shake_legs    = _gait("shake_legs",    "shaking legs")
stretch       = _gait("stretch",       "stretching")
spin          = _gait("spin",          "spinning")


# The 2DOF gimbal has no wrapper module yet -- these stay prints until
# the pan/tilt API is confirmed on real hardware.
def camera_up():      print("ROBOT: camera looking up")
def camera_down():    print("ROBOT: camera looking down")
def camera_left():    print("ROBOT: camera looking left")
def camera_right():   print("ROBOT: camera looking right")
def camera_center():  print("ROBOT: camera centered")


ACTION_WHITELIST = {
    "walk forward":  (walk_forward,  1.0),
    "walk backward": (walk_backward, 1.0),
    "turn":          (turn_action,   1.0),
    "squat":         (squat,         0.8),
    "stand":         (stand,         0.8),
    "shake legs":    (shake_legs,    0.8),
    "stretch":       (stretch,       1.0),
    "spin":          (spin,          1.2),
    "look up":       (camera_up,     0.3),
    "look down":     (camera_down,   0.3),
    "look left":     (camera_left,   0.3),
    "look right":    (camera_right,  0.3),
    "center camera": (camera_center, 0.3),
}

# Phrasings the 3B model actually produces that mean a whitelisted
# action. Testing showed it embellishes past the prompt's vocabulary --
# "[spins around]" is literally in the prompt's own Wrong: example, so
# it's guaranteed to show up. These map onto real moves instead of being
# silently dropped. Keys are matched after stemming, same as above.
ACTION_ALIASES = {
    "spin around":       "spin",
    "spin in a circle":  "spin",
    "twirl":             "spin",
    "turn around":       "spin",
    "turn left":         "turn",
    "turn right":        "turn",
    "walk":              "walk forward",
    "step forward":      "walk forward",
    "step backward":     "walk backward",
    "back up":           "walk backward",
    "crouch":            "squat",
    "sit":               "squat",
    "stand up":          "stand",
    "get up":            "stand",
    "wiggle legs":       "shake legs",
    "wriggle legs":      "shake legs",
    "wriggle":           "shake legs",
    "bounce":            "shake legs",
    "bounce up down":    "shake legs",
    "wiggle":            "shake legs",
    "shake":             "shake legs",
    "dance":             "shake legs",
    "look around":       "center camera",
    "tilt camera up":    "look up",
    "tilt camera down":  "look down",
    "pan camera left":   "look left",
    "pan camera right":  "look right",
    "center the camera": "center camera",
}


def normalize_actions(text: str) -> str:
    """
    Convert stray markdown emphasis into brackets.

    Careful with the old one-liner `re.sub(r'\*(.*?)\*', r'[\1]', text)`:
      * "**waves**" became "[]waves[]" -- two empty actions plus the word
        "waves" leaking into TTS, i.e. the exact opposite of the intent.
      * "2 * 3 * 4" became "2 [ 3 ] 4" -- a stray pair of asterisks in
        ordinary speech ate the text between them.
    So: bold first, single emphasis second, and both require non-empty
    content with no whitespace against the markers, which is how real
    markdown emphasis is written and how a bare multiplication sign
    isn't.
    """
    text = re.sub(r'\*\*(\S[^*\n]*?)\*\*', r'[\1]', text)
    text = re.sub(r'\*(\S[^*\n]*?)\*', r'[\1]', text)
    return text


def extract_actions(text: str) -> list:
    return re.findall(r'\[(.*?)\]', text)


def _stem_word(word: str) -> str:
    """
    Strip a simple plural/3rd-person ending off one word.

    The old rule was "drop a trailing s if the word is >3 chars and
    doesn't end in ss". That turned "stretches" into "stretche", which
    matched nothing -- so a whitelisted action the prompt explicitly
    teaches Yuzu to use was being silently ignored on the robot. The
    "-es" case has to come first.
    """
    w = word.lower()
    if len(w) > 4 and w.endswith(('ches', 'shes', 'sses', 'xes', 'zes')):
        return w[:-2]
    if len(w) > 3 and w.endswith('s') and not w.endswith('ss'):
        return w[:-1]
    return w


# Words the model sprinkles onto real actions as flourish. Observed in
# live PocketPal output: "[hugs, squeeze, and a little spin]" is a spin
# wearing decoration. Stripping these turns near-misses into matches.
_FILLER = {
    'the', 'a', 'an', 'her', 'his', 'its', 'and', 'then',
    'little', 'big', 'quick', 'quickly', 'slow', 'slowly',
    'soft', 'softly', 'gentle', 'gently', 'cute', 'cutely',
    'happy', 'happily', 'excited', 'excitedly', 'playful', 'playfully',
    'some', 'more', 'again', 'bit', 'too', 'around',
}


def _stem_phrase(phrase: str) -> str:
    """Normalize an action phrase for whitelist lookup: lowercase, drop
    punctuation and filler words, stem each remaining word."""
    cleaned = re.sub(r'[^\w\s]', ' ', phrase.lower())
    words = [w for w in cleaned.split() if w not in _FILLER]
    return ' '.join(_stem_word(w) for w in words)


_STEMMED_WHITELIST = {_stem_phrase(k): v for k, v in ACTION_WHITELIST.items()}
_STEMMED_ALIASES = {
    _stem_phrase(k): _STEMMED_WHITELIST[_stem_phrase(v)]
    for k, v in ACTION_ALIASES.items()
}


def lookup_action(action_text: str):
    """Return (function, pause) for an action phrase, or None if it isn't
    something this body can do. No fallback, ever -- an unrecognised
    action does nothing rather than guessing at a movement."""
    key = _stem_phrase(action_text)
    return _STEMMED_WHITELIST.get(key) or _STEMMED_ALIASES.get(key)


def lookup_actions(action_text: str) -> list:
    """Every runnable action inside one bracket, in order.

    The prompt says one action per bracket. Live output disagrees --
    "[hugs, squeeze, and a little spin]" turned up in real testing, and
    treating that as a single unknown phrase threw away a spin the robot
    could actually do. So on a whole-phrase miss, split the bracket on
    commas / "and" / "then" and keep whatever parts are real.

    The whitelist still gates every part, so the impossible halves
    ("hugs", "squeeze") are dropped exactly as before -- this only ever
    recovers motion that was already allowed, never invents any.
    """
    whole = lookup_action(action_text)
    if whole:
        return [whole]
    parts = re.split(r',|\band\b|\bthen\b|\[', action_text)
    return [match for match in (lookup_action(p) for p in parts if p.strip()) if match]


# Multiplier on every post-action settle pause. 1.0 is the tuned
# default; raise it if moves are still finishing when the next one
# fires, drop it toward 0 to make testing instant.
PAUSE_SCALE = 1.0


def run_action(action_text: str) -> bool:
    """Run everything runnable in one bracket. Returns whether anything
    matched."""
    matches = lookup_actions(action_text)
    if not matches:
        print(f"ROBOT: no match for action '{action_text}' (ignored)")
        return False
    for func, pause_seconds in matches:
        func()
        time.sleep(pause_seconds * PAUSE_SCALE)
    return True


def run_actions_in_order(actions: list):
    for action_text in actions:
        run_action(action_text)


def strip_actions(text: str) -> str:
    """
    Remove bracketed actions, leaving only what should be spoken.

    Also drops a trailing unclosed bracket. A truncated generation like
    "Heyyy cutie! [squa" used to send the literal "[squa" to TTS, which
    Yuzu would then read out loud, brackets and all. Rare, but it only
    costs one regex to never hear it.
    """
    no_actions = re.sub(r'\[.*?\]', '', text)
    no_actions = re.sub(r'\[[^\]]*$', '', no_actions)
    return re.sub(r'\s+', ' ', no_actions).strip()


def split_reply(text: str) -> list:
    """
    Break a reply into ordered ('speech', str) / ('action', str) parts.

    This is what fixes the silent-beat quirk. The old pipeline ran every
    action to completion -- pauses included -- before speaking a single
    word, so "Not much, just vibing! [squats] [shakes legs] What's good?"
    meant several seconds of silent squatting and then a burst of talk.
    Keeping written order means she talks and moves like one creature.
    """
    parts = []
    cursor = 0
    for match in re.finditer(r'\[(.*?)\]', text):
        speech = strip_actions(text[cursor:match.start()])
        if speech:
            parts.append(("speech", speech))
        parts.append(("action", match.group(1)))
        cursor = match.end()
    tail = strip_actions(text[cursor:])
    if tail:
        parts.append(("speech", tail))
    return parts


def speak(text: str):
    print(f"TTS SAYS: \"{text}\"")   # <-- swap this line for your real TTS call


def handle_yuzu_reply(raw_llm_output: str, interleave=True):
    """
    interleave=True  -> speak and move in the order Yuzu wrote them
    interleave=False -> old behaviour: all movement first, then all speech
    """
    cleaned = normalize_actions(raw_llm_output)

    if not interleave:
        set_led_state("moving")
        run_actions_in_order(extract_actions(cleaned))
        speech = strip_actions(cleaned)
        if speech:
            set_led_state("speaking")
            speak(speech)
        return

    for kind, value in split_reply(cleaned):
        if kind == "speech":
            set_led_state("speaking")
            speak(value)
        else:
            set_led_state("moving")
            run_action(value)


# ============================================================================
# PART 2: THE MAIN LOOP (listen -> think -> respond, forever)
# ============================================================================

# --- STUB 1: swap this for real Whisper once a mic is hooked up ------------
def listen_and_transcribe():
    return input("You say: ")


# --- The brain. Real Ollama when it's reachable, echo stub when it isn't. --
brain = None
current_persona = None

# Which character boots by default. Override with:  export YUZU_PERSONA=saya
PERSONA = os.environ.get("YUZU_PERSONA")


def apply_persona_look(persona):
    """Let the loaded character tint her own LED states."""
    if leds and persona is not None:
        colors = persona.led_states()
        if colors:
            leds.apply_persona_colors(colors)


def start_brain(persona_key=None):
    """Connect to Ollama once, at boot. Returns a short status string.

    A failure here is NOT fatal: the robot still boots, still parses,
    still moves, and says so loudly. Better than a stack trace on a
    machine you're SSH'd into from a Steam Deck.
    """
    global brain, current_persona
    if YuzuBrain is None:
        return "echo stub (yuzu_brain.py not found)"
    try:
        candidate = YuzuBrain(persona=persona_key or PERSONA)
        candidate.check()
    except BrainError as exc:
        print(f"\n!! Brain offline, falling back to the echo stub.\n{exc}\n")
        return "echo stub (Ollama unreachable)"
    brain = candidate
    current_persona = candidate.persona
    apply_persona_look(current_persona)
    who = current_persona.name if current_persona else "custom prompt"
    return f"{who} via Ollama, model '{brain.model}'"


def switch_persona(key):
    """Swap character mid-conversation. History is dropped on purpose --
    carrying a gyaru's banter into a kuudere's context makes the new
    persona imitate the old one for several turns."""
    global brain, current_persona
    if yuzu_personas is None or YuzuBrain is None:
        print("Persona switching needs yuzu_personas.py and yuzu_brain.py.")
        return False
    try:
        candidate = YuzuBrain(model=brain.model if brain else None,
                              persona=key)
    except BrainError as exc:
        print(f"{exc}")
        return False
    brain = candidate
    current_persona = candidate.persona
    apply_persona_look(current_persona)
    print(f"Now talking to {current_persona.name} "
          f"({current_persona.archetype}). History cleared.")
    return True


def ask_yuzu_brain(user_text):
    if brain is None:
        return (f"OMG you said '{user_text}'? [squats] "
                f"That's so real of you, no cap! [shakes legs]")
    try:
        return brain.ask(user_text)
    except BrainError as exc:
        # Mid-conversation dropout: say something rather than freezing.
        print(f"!! {exc}")
        return "Ugh, my brain just lagged out for a sec. Say that again?"


def run_yuzu_forever():
    brain_status = start_brain()
    print("Listening... ('quit' to stop, '/persona <name>' to switch, "
          "'/personas' to list)")
    print(f"brain: {brain_status}")
    print(f"gaits: {'muto_leg_control' if legs else 'print-only'}   "
          f"leds: {'yuzu_led_manager' if leds else 'off'}\n")
    if legs and g_bot:
        legs.stance(g_bot)
    set_led_state("idle")
    while True:
        user_text = listen_and_transcribe()
        command = user_text.strip().lower()
        if command in ("quit", "exit"):
            print("Shutting down.")
            break
        if command == "/personas":
            if yuzu_personas:
                for key in yuzu_personas.available():
                    try:
                        who = yuzu_personas.load(key)
                        mark = "*" if current_persona and key == current_persona.key else " "
                        print(f" {mark} {key:<10} {who.name} -- {who.archetype}")
                    except yuzu_personas.PersonaError as exc:
                        print(f"   {key:<10} BROKEN: {str(exc).splitlines()[0]}")
            else:
                print("yuzu_personas.py isn't here.")
            print()
            continue
        if command.startswith("/persona "):
            switch_persona(command.split(None, 1)[1].strip())
            print()
            continue
        set_led_state("thinking")
        raw_reply = ask_yuzu_brain(user_text)
        handle_yuzu_reply(raw_reply)
        set_led_state("idle")
        print()


if __name__ == "__main__":
    run_yuzu_forever()
