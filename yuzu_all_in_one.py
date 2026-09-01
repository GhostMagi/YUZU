"""
Yuzu, all in one file -- combines the reply pipeline (fix/extract/run/strip/
speak) with the main loop (listen -> think -> respond) so there's nothing
to import and nothing to accidentally save in the wrong folder.

The two functions marked STUB are fakes for now -- swap them for real
Whisper and real Ollama once your hardware's ready. Everything else can
stay exactly as-is.
"""

import re
import time


# ============================================================================
# PART 1: THE REPLY PIPELINE (unchanged from before, just living here now)
# ============================================================================

# --- Placeholder robot functions -- swap for real Muto S2 SDK calls later ---
def walk_forward():   print("ROBOT: walking forward")
def walk_backward():  print("ROBOT: walking backward")
def turn_action():    print("ROBOT: turning")
def squat():          print("ROBOT: squatting")
def stand():          print("ROBOT: standing")
def shake_legs():     print("ROBOT: shaking legs")
def stretch():        print("ROBOT: stretching")
def spin():           print("ROBOT: spinning")
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


def normalize_actions(text: str) -> str:
    return re.sub(r'\*(.*?)\*', r'[\1]', text)


def extract_actions(text: str) -> list:
    return re.findall(r'\[(.*?)\]', text)


def _stem_phrase(phrase: str) -> str:
    words = phrase.lower().strip().split()
    stemmed = [w[:-1] if len(w) > 3 and w.endswith('s') and not w.endswith('ss') else w
               for w in words]
    return ' '.join(stemmed)


_STEMMED_WHITELIST = {_stem_phrase(k): v for k, v in ACTION_WHITELIST.items()}


def run_actions_in_order(actions: list):
    for action_text in actions:
        match = _STEMMED_WHITELIST.get(_stem_phrase(action_text))
        if match:
            func, pause_seconds = match
            func()
            time.sleep(pause_seconds)
        else:
            print(f"ROBOT: no match for action '{action_text}' (ignored)")


def strip_actions(text: str) -> str:
    no_actions = re.sub(r'\[.*?\]', '', text)
    return re.sub(r'\s+', ' ', no_actions).strip()


def speak(text: str):
    print(f"TTS SAYS: \"{text}\"")   # <-- swap this line for your real TTS call


def handle_yuzu_reply(raw_llm_output: str):
    cleaned = normalize_actions(raw_llm_output)
    actions = extract_actions(cleaned)
    run_actions_in_order(actions)
    speech_only = strip_actions(cleaned)
    speak(speech_only)


# ============================================================================
# PART 2: THE MAIN LOOP (listen -> think -> respond, forever)
# ============================================================================

# --- STUB 1: swap this for real Whisper once a mic is hooked up ------------
def listen_and_transcribe():
    return input("You say: ")


# --- STUB 2: swap this for a real Ollama call once it's running -----------
def ask_yuzu_brain(user_text):
    return f"OMG you said '{user_text}'? [squats] That's so real of you, no cap! [shakes legs]"


def run_yuzu_forever():
    print("Yuzu is listening... (type 'quit' to stop this test)\n")
    while True:
        user_text = listen_and_transcribe()
        if user_text.strip().lower() == "quit":
            print("Shutting down.")
            break
        raw_reply = ask_yuzu_brain(user_text)
        handle_yuzu_reply(raw_reply)
        print()


if __name__ == "__main__":
    run_yuzu_forever()
