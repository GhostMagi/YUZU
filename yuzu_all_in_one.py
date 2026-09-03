"""
Yuzu, all in one file -- combines the reply pipeline (fix/extract/run/
strip/speak) with the main loop (listen -> think -> respond) so there's
nothing to import and nothing to accidentally save in the wrong folder.

listen_and_transcribe() is still a STUB -- swap it for real Whisper
once a mic is hooked up. The brain is real: it talks to Ollama via
yuzu_brain.py, and falls back to an echo stub when Ollama isn't up.

This file will run anywhere, including Pydroid on the phone, with no
hardware and no other files present. If muto_leg_control.py IS sitting
next to it, bracketed actions drive real gaits; if yuzu_voice.py and
Piper are there, she speaks out loud. Missing either one falls back to
printing, exactly like it always did.
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
    from yuzu_brain import BrainError, YuzuBrain
except ImportError:
    YuzuBrain = None
    BrainError = Exception

try:
    import yuzu_personas
except ImportError:
    yuzu_personas = None

# Piper lives behind its own module for the same reason the gaits do:
# it is the one real dependency in the project, and the phone has
# neither the binary nor a voice file. Missing = she prints, exactly as
# she did before there was a voice.
try:
    import yuzu_voice
except ImportError:
    yuzu_voice = None


# ============================================================================
# PART 0: HARDWARE BINDING
# ============================================================================

# Simulation vs real servos is an EXPLICIT choice, never auto-detected:
#
#     python yuzu_all_in_one.py                 # simulation
#     YUZU_HARDWARE=1 python yuzu_all_in_one.py # real servos
#
# Auto-detecting by probing a serial port sounds convenient and is a
# trap: a loose cable then looks exactly like working code, and you
# spend an evening debugging a gait that was never reaching a motor.
# Asking for hardware and not getting it is a hard failure here.
USE_HARDWARE = os.environ.get("YUZU_HARDWARE", "").lower() in (
    "1", "true", "yes", "real", "on")

g_bot = None
BOT_MODE = "no muto_leg_control.py"
if legs:
    try:
        g_bot, BOT_MODE = legs.connect(USE_HARDWARE)
    except legs.HardwareError as exc:
        print(f"\n{exc}\n")
        raise SystemExit(1)

voice = yuzu_voice.Voice() if yuzu_voice else None


# ============================================================================
# PART 1: THE REPLY PIPELINE
# ============================================================================

# Each robot function calls the real gait when muto_leg_control is
# importable, and otherwise prints -- so the pipeline is testable on a
# phone and correct on the Jetson without touching this file again.
# Counts hardware faults so a flaky serial bus is visible rather than
# mysterious. Reset per session; surfaced by /health.
motor_faults = []


def _gait(name, printed, **kwargs):
    def run():
        if not (legs and g_bot):
            print(f"ROBOT: {printed}")
            return
        try:
            getattr(legs, name)(g_bot, **kwargs)
        except Exception as exc:                # noqa: BLE001
            # A servo bus hiccup must not end the conversation. She
            # keeps talking; the robot just doesn't move that beat.
            # Bare Exception is deliberate -- the Yahboom library's
            # error types aren't documented, and a serial timeout
            # killing the whole loop mid-sentence is worse than any
            # error we might swallow here.
            motor_faults.append((name, repr(exc)))
            print(f"[robot] '{name}' failed: {exc} (continuing)")
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
    # "turn around" is deliberately NOT here. _stem_phrase drops
    # "around" as filler, so it arrives as "turn" and the whitelist
    # answers first -- which is the closer motion anyway (a half turn,
    # not four steps of spin). An entry here would look like it worked
    # and never once fire. test_no_alias_is_shadowed_by_the_whitelist
    # keeps that from being reintroduced.
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
    # "Stop" is one of the most natural things to say to a robot and
    # there was NO way to say it -- no stop, halt, wait or stand still
    # anywhere in the whitelist. Told to stop walking, Yuzu reached for
    # [centers camera] because it was the closest thing on the menu.
    # stand() calls stance(): feet planted, body level, motion over.
    # That IS stopping, so these all point at it.
    "stop":              "stand",
    "stop walking":      "stand",
    "stop moving":       "stand",
    "stand still":       "stand",
    "hold still":        "stand",
    "halt":              "stand",
    "freeze":            "stand",
    "wait":              "stand",
    "stay":              "stand",
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
    r"""
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


def speaker_name():
    """Whoever is actually talking, for the transcript.

    Hardcoding "YUZU" here meant a whole conversation with the kuudere
    scrolled past labelled YUZU SAYS. Same class as the eval prompt that
    opened "Hey Yuzu, what's up?" for every persona and the error that
    said `ollama create yuzu` whatever model was missing -- the name
    leaking out of the character it belongs to. This one hid longer
    because it is a print, not logic.
    """
    if current_persona is not None:
        return current_persona.name.upper()
    return "ROBOT"


def speak(text: str):
    """Say one line out loud, and always print it.

    The print stays even with Piper working. On a robot you are SSH'd
    into from another room, the transcript is how you know what she
    said when the speaker is out of earshot or the audio failed -- and
    say() returning False is silent by design, because a conversation
    that stops when the speaker breaks is worse than a silent one.
    """
    heard = voice.say(text) if (voice and voice.ready) else False
    tail = "" if heard else " (text only)"
    print(f"{speaker_name()} SAYS{tail}: \"{text}\"")


def handle_yuzu_reply(raw_llm_output: str, interleave=True):
    """
    interleave=True  -> speak and move in the order Yuzu wrote them
    interleave=False -> old behaviour: all movement first, then all speech
    """
    cleaned = normalize_actions(raw_llm_output)

    if not interleave:
        run_actions_in_order(extract_actions(cleaned))
        speech = strip_actions(cleaned)
        if speech:
            speak(speech)
        return

    for kind, value in split_reply(cleaned):
        if kind == "speech":
            speak(value)
        else:
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

# Which character boots by default. Override with:  export YUZU_PERSONA=coco
# Unset means yuzu_personas.LIVE_PERSONA -- the measured winner, not the
# frozen v1 archive that happens to own the "yuzu" key.
PERSONA = os.environ.get("YUZU_PERSONA")


def apply_persona_voice(persona):
    """Let the loaded character set her own speaking speed.

    Every persona file has carried piper_length_scale since the format
    was written -- yuzu4 asks for 0.88, Coco for 1.08 -- and until
    there was a voice, nothing read it. A kuudere should not talk at a
    gyaru's pace.
    """
    if voice is None or persona is None:
        return
    scale = persona.settings.get("piper_length_scale")
    if scale is not None:
        voice.length_scale = scale


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
    brain.on_recover = _announce_recovery
    current_persona = candidate.persona
    apply_persona_voice(current_persona)
    who = current_persona.name if current_persona else "custom prompt"
    return f"{who} via Ollama, model '{brain.model}'"


def _announce_recovery(kind, health):
    """Say out loud when the drift monitor trims history, so a weird
    stretch of conversation has a visible cause instead of looking like
    the robot randomly forgot things."""
    what = ("kept the last exchange" if kind == "soft"
            else "cleared the conversation")
    print(f"   ~ format drifting ({health}); {what}. "
          f"She still knows who she is.")


def switch_persona(key):
    """Swap character mid-conversation. History is dropped on purpose --
    carrying a gyaru's banter into a kuudere's context makes the new
    persona imitate the old one for several turns."""
    global brain, current_persona
    if yuzu_personas is None or YuzuBrain is None:
        print("Persona switching needs yuzu_personas.py and yuzu_brain.py.")
        return False
    try:
        # Keep whatever model/host the running brain is on. When the
        # brain never came up these are None, which YuzuBrain reads as
        # "use the defaults" -- switching characters must not depend on
        # Ollama having been reachable at boot.
        candidate = YuzuBrain(model=brain.model if brain else None,
                              host=brain.host if brain else None,
                              persona=key)
    except BrainError as exc:
        print(f"{exc}")
        return False
    brain = candidate
    brain.on_recover = _announce_recovery
    current_persona = candidate.persona
    apply_persona_voice(current_persona)
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


def _on_a_jetson():
    """Deliberately duplicated from yuzu_doctor.py, which has to run as
    a lone download and so may not import anything from this project."""
    try:
        if os.path.exists("/etc/nv_tegra_release"):
            return True
        model = "/sys/firmware/devicetree/base/model"
        if os.path.exists(model):
            with open(model, "rb") as handle:
                name = handle.read().decode("utf-8", "replace").lower()
            return "jetson" in name or "orin" in name
    except OSError:
        pass
    return False


def run_yuzu_forever():
    if _on_a_jetson():
        print("\n!! Jetson ships THROTTLED -- if she feels slow, run:")
        print("     sudo nvpmodel -m 0 && sudo jetson_clocks\n")
    brain_status = start_brain()
    print("Listening... 'quit' to stop. Commands: /personas /persona <name> "
          "/reset /health")
    print(f"brain: {brain_status}")
    print(f"gaits: {'muto_leg_control' if legs else 'print-only'}")
    if voice and voice.ready:
        print(f"voice: piper, {voice.model.name}")
    else:
        reason = voice.why_not() if voice else "yuzu_voice.py not found"
        print(f"voice: printing only ({reason})")
    banner = "!" * 58 if USE_HARDWARE else ""
    if banner:
        print(banner)
        print(f"  MODE: {BOT_MODE}")
        print("  Clear the area. Ctrl-C parks the legs safely.")
        print(banner)
    else:
        print(f"mode:  {BOT_MODE}")
    print()
    if legs and g_bot:
        legs.stance(g_bot)
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
        if command in ("/reset", "/clear"):
            if brain:
                brain.reset()
                print("Conversation cleared. Personality untouched.\n")
            else:
                print("Nothing to reset -- running on the echo stub.\n")
            continue
        if command == "/health":
            # Motor faults are reported unconditionally. They used to be
            # printed only inside the "brain is up and has scored a
            # reply" branch, so on the echo stub -- which is exactly the
            # mode you use to shake down a new servo bus -- a flaky bus
            # was invisible in the one command that exists to show it.
            if brain and brain.last_health:
                print(f" last reply: {brain.last_health}")
                print(f" history: {len(brain.history)//2} exchanges, "
                      f"auto-recoveries so far: {brain.recoveries}")
            else:
                print(" no replies scored yet (echo stub, or nothing said)")
            print(f" motor faults: {len(motor_faults)}")
            if voice and voice.failures:
                print(f" voice failures: {len(voice.failures)}")
                for code, lines in voice.failures[-2:]:
                    print(f"   exit {code}: {' '.join(lines)}")
            for name, err in motor_faults[-3:]:
                print(f"   {name}: {err}")
            print()
            continue
        raw_reply = ask_yuzu_brain(user_text)
        handle_yuzu_reply(raw_reply)
        print()


def shutdown():
    """Park the robot and the lights. Safe to call twice."""
    if legs and g_bot:
        print("Parking legs...")
        legs.rest(g_bot)
    if motor_faults:
        print(f"({len(motor_faults)} motor fault(s) this session)")


def main():
    """Wrapper that guarantees shutdown() runs on EVERY exit path.

    Without this, Ctrl-C during a gait leaves 18 servos energised
    against a half-finished pose until someone pulls the power. The
    finally block is the only thing standing between a normal
    interruption and a stalled, overheating leg.
    """
    try:
        run_yuzu_forever()
    except KeyboardInterrupt:
        print("\nInterrupted.")
    finally:
        shutdown()


if __name__ == "__main__":
    main()
