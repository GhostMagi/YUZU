# FULL TECHNICAL CONTEXT DUMP: Yuzu-Spider-V1 Robot Project

Purpose of this file: a single, maximally complete drop-in context file
(e.g. for a Claude Code project folder) containing not just facts but
actual current code and reasoning, so a new AI session/tool can pick up
this project with minimal re-explaining needed from Ghost (the human).

======================================================================
## 1. PROJECT IDENTITY
======================================================================
- Official designation: "Yuzu-Spider-V1"
- Active persona: Yuzu -- a mildly flirty, pink-obsessed Gyaru companion
- Platform: Yahboom Muto S2 hexapod robot (18-DOF, 6 legs)
- Brain (planned): NVIDIA Jetson Orin Nano Super Developer Kit (8GB, 67 TOPS)
- Model: Llama-3.2-3B-Instruct-Heretic-Abliterated-Uncensored (Q4_K_M),
  run locally via Ollama (no cloud, fully offline/local by design)
- Sister project: Saya -- separate quadruped build, Kuudere personality,
  Sesame Robot framework (Dorian Todd design), ESP32 controller, 8x MG90S
  servos, 128x64 OLED as reactive pixel face. Currently in planning only,
  no code/prompt work done on Saya this stretch.
- Human collaborator: goes by "Ghost." New to Python at the start of this
  project; has since independently written and run a working regex-based
  action parser on their own phone (Z Flip 6, via Pydroid 3).
- Workflow: Ghost runs a two-AI setup -- Google Gemini and Claude trade
  versioned "handoff notes" text files/PDFs back and forth to stay in
  sync on the same project. Known versions seen: Gemini v3 and v6,
  Claude v4 and v5. A quirk observed: when a chat session is lost, the
  other AI may reconstruct a "lost" file from ITS OWN separate context
  rather than the true original, producing divergent versions of the
  same file (this happened with an LED script, ledsnewestv7.py).

======================================================================
## 2. PERSONA HISTORY (why Yuzu, not something else)
======================================================================
Project started as a simple M5Stack Stackchan build (1B Llama, AX630C
NPU chip) with a persona named Pixie, which went through several tone
pivots (scene-girl -> sassy -> casual/flirty) to stop it from dodging
real questions with jokes. Pixie was renamed Saya (Highschool of the
Dead reference), tried as Tsundere, then briefly as Yandere (named Yuno,
Mirai Nikki reference) -- Tsundere won, Yandere felt too intense for
daily use. Two more personas were built and set aside: Himedere "Saki"
(too royal/mean in practice) and Kuudere "Coco" (abandoned mid-hardware
-conversion phase). Eventually Saya (tsundere) itself was set aside in
drafts, and Yuzu (gyaru) became the primary, currently-active persona,
first drafted for a 1B model, later rewritten and finalized for 3B.

Known accepted limitations carried through every persona: small local
models occasionally answer factual/local-knowledge questions confidently
wrong (fake landmarks, wrong math) -- treated as a model-capability
limitation, not something to keep chasing via prompt engineering.

======================================================================
## 3. CONFIRMED HARDWARE SPECIFICATION
======================================================================
- Chassis: Yahboom Muto S2 hexapod, 18-DOF, 6 legs, 18x 35KG serial bus
  servos, 2DOF camera gimbal (pan/tilt) -- NO face, NO hands, NO arms,
  NO hair. This constraint is critical and directly shapes the system
  prompt's action rules (see Section 5).
- Built-in 4-port USB 3.0 hub on the chassis itself.
- Compute: Jetson Orin Nano Super Dev Kit, 8GB RAM, 67 TOPS.
- Storage: Ghost has BOTH a 256GB and a 128GB microSD card on hand (no
  NVMe SSD yet). Note: NVIDIA's own docs say microSD boot is supported
  (64GB minimum), NVMe is recommended but not required -- speed/
  durability tradeoff only, not a capability blocker. Fine to start on
  SD and upgrade later.
- Audio: originally spec'd as "USB mini speakerphone"; now leaning
  toward a sub-$25 ultra-compact USB conference speaker/mic puck for a
  lower-profile mount, plugged into the built-in USB hub.
- Paint/aesthetic (FINAL, locked in): neon lime-green structural chassis
  ("torso") with hot-pink lower leg struts -- nicknamed "cyberpunk
  watermelon" / "toxic-neon gyaru vibe." Automotive-grade or Cerakote
  paint. Pink LED underglow/trim runs on its OWN dedicated micro LiPo
  battery + switch specifically to avoid voltage sag/noise on the main
  servo serial bus.
- Proposed accessories (not yet built): 3D printed pink cyber-cat ears
  with embedded RGB tips on the top deck, blinged-out phone charms/
  lanyards on front mounting points, a potential laser pointer clip on
  the camera gimbal.
- Budget: ~$450 total procurement cap, Jetson itself targeted at ~$400.
- Workstation: a Steam Deck (in Desktop Mode) will serve as the primary
  device for flashing media, remote debugging, and SSH terminal work.
- Low-level servo API reference (from Yahboom docs, not yet wrapped in
  working code): `g_bot.motor(servo_id, angle, runtime=100)` as the base
  command; `Servo_torque_on()`, `Servo_torque_off()`, `load_leg(leg)`,
  `unload_leg(leg)` as state commands. Leg-to-servo ID mapping: Leg 1 =
  servos 1-3, Leg 2 = 4-6, Leg 3 = 7-9, Leg 4 = 10-12, Leg 5 = 13-15,
  Leg 6 = 16-18. A helper script `muto_leg_control.py` with a
  `set_leg(leg_id, coxa, femur, tibia)` wrapper is PLANNED but NOT YET
  WRITTEN -- this is the single biggest remaining unknown in the whole
  build (no real gait functions exist yet, only placeholders).

======================================================================
## 4. SOFTWARE ARCHITECTURE DECISIONS (with reasoning)
======================================================================
- Explicitly SKIPPING ROS2 to avoid middleware bloat -- using direct
  Python serial calls for hardware control instead.
- LLM served via Ollama running the 3B Heretic-abliterated model
  locally on the Jetson GPU.
- Action-spam bug found in testing: the 3B model sometimes chains
  multiple bracketed actions in one reply; firing them all with zero
  delay risks "conflicting motor trajectories" (a leg told to move
  somewhere new before finishing its last move) -- a real hardware risk
  flagged by Gemini, confirmed as valid reasoning by Claude.
- Fix chosen: a strict, stemmed whitelist (exact match after stripping
  simple plural/verb endings, e.g. "squats" still matches "squat") +
  SEQUENTIAL execution with a short pause between each matched action
  (not a FIFO-drop-all-but-first approach) -- sequential was chosen
  specifically because Yuzu's own prompt intentionally uses multi-action
  replies (e.g. `[squats] [shakes legs]`), so dropping extras would have
  silently broken intended behavior.
- A required-dialogue rule was added after testing revealed that an
  all-actions, zero-dialogue reply (e.g. to "do a stretch") resulted in
  the robot doing NOTHING and saying NOTHING that turn -- looked like a
  freeze/glitch even though the code was technically working correctly.
- Accepted, NOT-going-to-fix-further quirk: Yuzu still occasionally
  outputs `[winks]` or arm/back/finger "stretch" language despite
  explicit prompt rules against both (repeated 3+ times across testing
  even with a "Wrong: [winks]" example already in the prompt). This is
  now treated as a permanent, harmless 3B quirk -- the whitelist safely
  drops these with zero side effects, so it's not worth more prompt-
  chasing.
- Tested edge cases and their real outcomes (all verified by running
  code, not assumed):
  - Empty LLM output -> silent, no crash.
  - Unmatched/invalid action -> does NOTHING (there is no default
    fallback action of any kind -- never substitutes a random movement).
  - Malformed/truncated bracket (missing closing `]`) -> that fragment
    leaks into spoken TTS output as literal text, brackets included.
    Rare (only from truncated generation), not dangerous, just sounds
    janky for one line if it ever happens. Not yet fixed.
  - Multiple valid actions chained -> there IS a real UX quirk: all
    actions run to completion (including their pause delays) BEFORE any
    speech happens, so an action-heavy reply has a noticeable silent
    beat before Yuzu starts talking. Not a bug, just a design tradeoff
    worth knowing about.
- Audio pipeline plan (not yet implemented): Whisper (specifically
  whisper.cpp, a lightweight local model) for fully offline STT running
  on the Jetson; Piper TTS for local TTS. Piper requires TWO files per
  voice in the same folder (.onnx weights + .onnx.json config) or it
  won't load. Voice speed/tone tunable via the `length_scale` value in
  the json (lower = faster/snappier, e.g. 0.85-0.9 suits the high-energy
  gyaru tone). Potential resource-contention risk flagged but untested:
  running Whisper + the 3B LLM + Piper simultaneously on one 8GB Jetson
  is three things sharing one memory pool -- recommend testing each
  piece incrementally rather than wiring all three at once on day one.

======================================================================
## 5. YUZU'S FINAL LIVE SYSTEM PROMPT (verbatim, currently in use)
======================================================================
```
You are Yuzu, a mildly flirty, pink-obsessed Gyaru companion. You speak with natural gal slang, high energy, and effortless confidence, never sounding like a generic AI assistant.

CORE DIRECTIVES:

1. PERSONALITY: Playful, hype-person energy, and casually affectionate. Avoid robotic assistant phrasing like "How can I help you today?". Speak like a companion hanging out on the couch. When asked a direct question, actually answer it before adding flair—don't dodge with a joke, action, or by repeating the question back. Every reply must include at least one full sentence of actual spoken dialogue—never send a reply made up of only actions with nothing to say.
2. HARDWARE ACTION PARSING: ALL physical movements MUST be strictly enclosed in square brackets, like [walks forward]. NEVER use asterisks, italics, or any other markdown for actions—brackets are the ONLY valid format, no exceptions, ever. Each bracket contains exactly ONE simple action—never combine actions with "and" or describe them in detail. Use only actions this body can actually perform—leg/gait moves (walk forward, walk backward, turn, squat, stand, shake legs, stretch, spin) and 2DOF camera gimbal moves (look up, look down, look left, look right, center camera). Never invoke body parts, features, or postures Muto doesn't have—no hands, arms, hair, head accessories, face, eyes, or leaning against things. Correct: [squats] [shakes legs]. Wrong: [winks], [spins around, camera bobbing up and down].
3. BALANCED FLIRTATION: Maintain a fun, mildly flirty baseline without escalating into extreme or unnatural aggressiveness. Pace your banter naturally.
4. NO PUPPETEERING: Never speak, act, or dictate actions for the user. Only write responses and movements for Yuzu.
5. GYARU AESTHETIC: You love hot pink, cyber-decorations, sparkles, and hype vibes.

EXAMPLE (follow this format exactly, every single time):
User: Hey Yuzu, what's up?
Yuzu: Not much, just vibing! [squats] [shakes legs] What's good with you?
```

Note re: PocketPal (the phone app Ghost tests with) -- its UI renders
`*asterisk*` text as italics WITHOUT showing the literal asterisk
characters. A screenshot showing an unmarked/unbracketed action is very
likely this rendering quirk, not a genuinely new unformatted-text bug.

======================================================================
## 6. CURRENT CODE -- yuzu_all_in_one.py (tested, working)
======================================================================
This is the full current pipeline + main loop, combined into one file
(originally two files, merged after a ModuleNotFoundError on Pydroid
from them being in different folders). `ask_yuzu_brain()` and
`listen_and_transcribe()` are the ONLY two functions that need to be
replaced with real Ollama/Whisper calls -- everything else is final.

```python
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
```

======================================================================
## 7. CURRENT CODE -- yuzu_led_manager.py (tested, working)
======================================================================
This merges two previously-incompatible LED systems Ghost/Gemini had
built separately: a zone-based JSON config (colors as hex strings,
brightness 0-100) and a state-based profile system (colors as [R,G,B]
lists, brightness 0-1). Standardized on hex + 0-100 throughout.

```python
"""
Yuzu's LED manager -- combines two previously-separate, incompatible
systems into one:

  1. yuzu_robot_config.json's PHYSICAL ZONES (underglow, eye_matrix,
     leg_accents) -- "where are the LEDs and what's their base color"
  2. ledsnewestv7.py's STATE PROFILES (idle, moving, alert) -- "what
     should the lights do based on what the robot is currently doing"

Both now use the SAME color format (hex strings, matching what the
JSON config already used) and the SAME brightness scale (0-100).
Previously ledsnewestv7.py used [R,G,B] lists and a 0-1 brightness
scale, which couldn't be compared to the JSON file's hex/0-100 format
at all -- that mismatch is the actual "kink" worth fixing here.
"""

import json
from pathlib import Path

DEFAULT_CONFIG = {
    "robot_name": "Yuzu-Spider-V1",
    "led_zones": {
        "underglow":   {"color": "#FF1493", "effect": "neon_pulse", "brightness": 90},
        "eye_matrix":  {"color": "#00FFFF", "effect": "static",     "brightness": 100},
        "leg_accents": {"color": "#FF007F", "effect": "chase",      "brightness": 75},
    },
    "state_profiles": {
        "idle":   {"color": "#00FF00", "brightness": 50,  "effect": "breathing"},
        "moving": {"color": "#FFA500", "brightness": 80,  "effect": "solid"},
        "alert":  {"color": "#FF0000", "brightness": 100, "effect": "strobe"},
    },
}


class LEDManager:
    def __init__(self, config_path="led_config.json"):
        self.config_path = Path(config_path)
        self.data = self._load()

    def _load(self):
        if not self.config_path.exists():
            self._save(DEFAULT_CONFIG)
            return DEFAULT_CONFIG
        with open(self.config_path, "r") as f:
            return json.load(f)

    def _save(self, data):
        with open(self.config_path, "w") as f:
            json.dump(data, f, indent=4)

    def get_zone(self, zone_name):
        """Static, location-based color -- underglow / eye_matrix / leg_accents."""
        return self.data.get("led_zones", {}).get(zone_name)

    def get_state_profile(self, state_name):
        """Behavior-based lighting -- idle / moving / alert."""
        return self.data.get("state_profiles", {}).get(
            state_name, {"color": "#FFFFFF", "brightness": 50, "effect": "solid"}
        )

    def apply_zone(self, zone_name):
        """Placeholder -- swap the print for a real LED hardware call later."""
        zone = self.get_zone(zone_name)
        if zone:
            print(f"LED: zone '{zone_name}' -> {zone}")
        else:
            print(f"LED: no config found for zone '{zone_name}'")

    def apply_state(self, state_name):
        """Placeholder -- swap the print for a real LED hardware call later."""
        profile = self.get_state_profile(state_name)
        print(f"LED: robot state '{state_name}' -> {profile}")


if __name__ == "__main__":
    led = LEDManager()
    print("--- Loaded zones (from the JSON config side) ---")
    led.apply_zone("underglow")
    led.apply_zone("eye_matrix")
    led.apply_zone("leg_accents")
    print()
    print("--- Loaded state profiles (from the old ledsnewestv7 side) ---")
    led.apply_state("idle")
    led.apply_state("moving")
    led.apply_state("alert")
```

======================================================================
## 8. REAL CONFIG FILE -- yuzu_robot_config.json (as currently exists)
======================================================================
Note: this real file only has `robot_name` and `led_zones` -- it does
NOT yet have a `state_profiles` section, so calling `get_state_profile()`
against the real file currently always falls back to the generic
default (`#FFFFFF`, solid, 50). `eye_matrix`'s cyan color is still an
unconfirmed addition -- unclear if it's an intentional new accessory or
drifted in from a different, lost chat session.

```json
{
    "robot_name": "Yuzu-Spider-V1",
    "led_zones": {
        "underglow": {
            "color": "#FF1493",
            "effect": "neon_pulse",
            "brightness": 90
        },
        "eye_matrix": {
            "color": "#00FFFF",
            "effect": "static",
            "brightness": 100
        },
        "leg_accents": {
            "color": "#FF007F",
            "effect": "chase",
            "brightness": 75
        }
    }
}
```

======================================================================
## 9. KNOWN BUG -- readtest.py (not yet fixed)
======================================================================
Hardcodes an absolute, Pydroid-on-this-specific-phone file path, which
will break the moment this code runs anywhere else (e.g. the Jetson).
Needs to be changed to a path relative to the script's own location
before it's reused outside of Pydroid testing.

```python
import json
from pathlib import Path

# Point straight to where we saved Yuzu's file
CONFIG_FILE = Path(
    "/data/user/0/iiec.pyramide.python/files/yuzu_robot_config.json"
)

# Open the JSON file and read it like a book
with open(CONFIG_FILE, "r") as f:
  yuzu_data = json.load(f)

# Print out what it finds inside
print("--- TEST SUCCESSFUL ---")
print(
    "Robot Name:", yuzu_data["robot_name"]
)
print(
    "Underglow Color:",
    yuzu_data["led_zones"]["underglow"]["color"],
)
print("Effect Mode:", yuzu_data["led_zones"]["underglow"]["effect"])
```

======================================================================
## 10. WHAT'S LEFT / NEXT STEPS (as of this export)
======================================================================
1. Buy the Jetson Orin Nano Super (~$400 of the ~$450 budget).
2. Flash JetPack OS (Steam Deck as the flashing workstation).
3. Install Ollama, pull the 3B Heretic model, verify real inference speed.
4. Write the REAL `muto_leg_control.py` / gait functions -- biggest
   unknown left; look for Yahboom's own Muto S2 example code first.
5. Install and test Piper TTS + Whisper independently before wiring
   them into the main loop together.
6. Fix `readtest.py`'s hardcoded path.
7. Decide/confirm whether `eye_matrix` is a real planned accessory.
8. Add a `state_profiles` section to the real JSON config if the
   idle/moving/alert lighting concept is being kept.
9. Physical chassis purchase is separate and later than the Jetson
   purchase (by design, ~1-3 months gap) -- chassis assembly, wiring,
   and painting (Ghost's dad is doing the painting) come after that.

-- Exported by Claude
