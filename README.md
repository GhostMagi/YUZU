# Yuzu-Spider-V1

A Yahboom Muto S2 hexapod (18-DOF, 6 legs) running a local Llama-3.2-3B
persona named Yuzu on a Jetson Orin Nano. Fully offline: local STT, local
LLM, local TTS, no cloud.

Paint scheme is Ghost's call and deliberately not pinned down in this
repo -- see `paintstepslol.txt` for the prep process, which works for
any colours.

**Status:** brain works today on any PC. Chassis and LEDs are later.

> ### On a fresh Jetson, run this FIRST
> ```
> sudo nvpmodel -m 0     # MAXN / MAXN SUPER -- the board ships throttled
> sudo jetson_clocks     # lock the clocks at maximum
> ```
> Biggest free speedup on the box, and easy to forget after a flash —
> at which point everything just feels slow for no visible reason.
> `yuzu_doctor.py` and the robot's own boot message both reprint it when
> they detect a Jetson. More in [JETSON_SETUP.md](JETSON_SETUP.md).

## Moving it to the Jetson?

**[DEPLOY.md](DEPLOY.md)** — `git clone`, run the tests, done. The whole repo is standard library; there is nothing to install.

## On your phone?

**[PHONE_START.md](PHONE_START.md)** — download one file, open it in
Pydroid, press Run. No commands.

## Try it right now (no hardware needed)

```
python yuzu_all_in_one.py     # talk to Yuzu, watch the fake robot move
python YUZU_TESTER.py           # 193 tests, ~18 seconds
python muto_leg_control.py    # dry-run every gait, no robot required
python yuzu_led_controller.py # dump the LED zone config
```

All stdlib. No pip installs, not even for Ollama. Runs in Pydroid on a phone.

## Getting the brain running

Full runbook in **[JETSON_SETUP.md](JETSON_SETUP.md)**. Short version,
on any PC — no Jetson needed:

```
ollama pull llama3.2:3b
python build_yuzu_model.py --create    # bake the persona into a model
python yuzu_brain.py --chat            # talk to her
python yuzu_prompt_eval.py --runs 3    # score how well she follows the prompt
```

Before building a model from a GGUF you didn't make yourself:

```
python gguf_inspect.py path/to/model.gguf
```

Reads only the header — instant on a 20GB file — and reports the quant,
context length, and most importantly whether the **chat template** is
present and handles a system role. A missing or wrong template is the
top reason a converted GGUF loads fine but ignores the persona entirely.

The eval is the important one. It runs 12 prompts through the real
model and scores every mechanically-checkable rule in the system
prompt — does she always speak, brackets never asterisks, are her
actions ones this body can do, does she write your lines. Change one
thing, re-run, compare. Tune the prompt on a laptop before spending
$400.

## What's here

| File | What it does |
|---|---|
| `yuzu_all_in_one.py` | Reply pipeline + main loop. **Start here.** |
| `yuzu_brain.py` | Ollama client. Stdlib only, streaming, history |
| `UBUNTU_LAPTOP.md` | Putting Ubuntu on the laptop, phone-readable |
| `personas/` | One file per character; body rules shared |
| `yuzu_personas.py` | Persona loader and composer |
| `build_yuzu_model.py` | Generates `Modelfile.yuzu` from that prompt |
| `yuzu_prompt_eval.py` | Scores prompt compliance against the model |
| `gguf_inspect.py` | Reads a GGUF header — quant, context, chat template |
| `yuzu_doctor.py` | Tap-to-run checkup. Standalone, no arguments |
| `PHONE_START.md` | Phone instructions, no terminal needed |
| `DEPLOY.md` | Moving the brain onto the Jetson |
| `JETSON_SETUP.md` | Setup runbook, PC and Jetson |
| `HEADLESS_SETUP.md` | Jetson setup from a Steam Deck, no monitor |
| `muto_leg_control.py` | Leg wrapper, tripod gaits, `DummyBot` simulator |
| `yuzu_led_manager.py` | The one LED config loader (zones + states) |
| `yuzu_led_controller.py` | Zone dump, front-end over `LEDManager` |
| `yuzu_robot_config.json` | The one config file |
| `readtest.py` | Smoke test that the config loads |
| `YUZU_TESTER.py` | Test suite |
| `Yuzu_Full_Technical_Context_Dump.md` | Full project context and reasoning |
| `Claude_Memory_Export_StackchanBuild.md` | Project history, Stackchan → now |
| `paintstepslol.txt` | Paint prep steps for the chassis |

## Swappable personas

Each character is one file in `personas/`. The rules about what the
*body* can do live separately and get composed in:

```
python yuzu_personas.py                 # list them
python yuzu_personas.py --new saki      # scaffold a new one
python yuzu_personas.py --show yuzu     # see the composed prompt
python build_yuzu_model.py --all --create   # one Ollama model each
python yuzu_brain.py --persona saya --chat
```

In the main loop, `/personas` lists and `/persona coco` switches live.

Two characters are built on the Muto S2 today: **Yuzu** (gyaru, hot
pink, hype) and **Coco** (kuudere, cold blue, deadpan). Switching
between them at runtime costs nothing — the system prompt is re-sent
every turn, so a persona is just the first message. Baking one model
per persona instead costs a second model resident in RAM. Which to use
when is in **[PERSONA_SWITCHING.md](PERSONA_SWITCHING.md)**.

**Why the split.** The bracket format, the action vocabulary, the
"always say something out loud" rule — none of that is personality,
it's facts about a Yahboom Muto S2. Copy it into five persona files and
you get five copies that drift, and one day you fix an action rule in
four of them and miss the fifth. So a persona file says
`{HARDWARE}` and the real text comes from
`personas/_hardware_muto_s2.txt`.

It also means a persona can move between robots. Saya's quadruped has
four legs and an OLED face — different body file, same character file,
no rewriting. `personas/_hardware_saya_quad.txt` is a draft of that.

## How a turn flows

```
mic -> listen_and_transcribe()      [STUB: swap in Whisper]
    -> LED "thinking"
    -> ask_yuzu_brain()             REAL: yuzu_brain.py -> Ollama
    -> normalize_actions()          stray *asterisks* -> [brackets]
    -> split_reply()                ordered speech/action parts
         speech -> LED "speaking" -> speak()   [STUB: swap in Piper]
         action -> LED "moving"   -> whitelist -> muto_leg_control gait
    -> LED "idle"
```

Two STUBs left: mic in, audio out. The brain is real. If Ollama isn't
running, the loop still boots and says so instead of crashing.

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
