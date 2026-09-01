# Yuzu-Spider-V1

A Yahboom Muto S2 hexapod (18-DOF, 6 legs) running a local Llama-3.2-3B
persona named Yuzu on a Jetson Orin Nano. Fully offline: local STT, local
LLM, local TTS, no cloud.

Neon lime-green chassis, hot-pink leg struts, pink underglow. Cyberpunk
watermelon.

## Try it right now (no hardware needed)

```
python yuzu_all_in_one.py     # talk to Yuzu, watch the fake robot move
python test_yuzu.py           # 31 tests, ~2 seconds
python muto_leg_control.py    # dry-run every gait, no robot required
python yuzu_led_controller.py # dump the LED zone config
```

All stdlib. No pip installs. Runs in Pydroid on a phone.

## What's here

| File | What it does |
|---|---|
| `yuzu_all_in_one.py` | Reply pipeline + main loop. **Start here.** |
| `muto_leg_control.py` | Leg wrapper, tripod gaits, `DummyBot` simulator |
| `yuzu_led_manager.py` | The one LED config loader (zones + states) |
| `yuzu_led_controller.py` | Zone dump, front-end over `LEDManager` |
| `yuzu_robot_config.json` | The one config file |
| `readtest.py` | Smoke test that the config loads |
| `test_yuzu.py` | Test suite |
| `Yuzu_Full_Technical_Context_Dump.md` | Full project context and reasoning |
| `Claude_Memory_Export_StackchanBuild.md` | Project history, Stackchan → now |
| `paintstepslol.txt` | Paint prep steps for the chassis |

## How a turn flows

```
mic -> listen_and_transcribe()      [STUB: swap in Whisper]
    -> LED "thinking"
    -> ask_yuzu_brain()             [STUB: swap in Ollama]
    -> normalize_actions()          stray *asterisks* -> [brackets]
    -> split_reply()                ordered speech/action parts
         speech -> LED "speaking" -> speak()   [STUB: swap in Piper]
         action -> LED "moving"   -> whitelist -> muto_leg_control gait
    -> LED "idle"
```

Three STUBs are the only fake parts. Everything between them is real.

## The action whitelist

Yuzu writes movements as `[squats]`. Each is matched against a whitelist
after light stemming, then run in order with a settle pause between —
sequential, because her prompt intentionally chains actions, and paused,
because firing a new servo target mid-move risks conflicting trajectories.

Anything not on the whitelist does **nothing**. There is no fallback
action, deliberately: a 3B model that writes `[winks]` at a robot with no
face should produce silence, not a random movement.

## Hardware status

Nothing here has run on a real Muto S2. The gaits are structurally sound
and range-safe, but every angle is a guess. Before walking it, run the
calibration order in Section 8 of the context dump:
`calibrate_leg()` → `check_mirroring()` → `check_tripods()` → `walk()`.

Swap `DummyBot` for the real object in `yuzu_all_in_one.py`:

```python
from muto_lib import Muto_Bot   # confirm the real import name
g_bot = Muto_Bot()
```
