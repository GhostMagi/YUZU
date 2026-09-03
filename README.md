# Yuzu-Spider-V1

A Yahboom Muto S2 hexapod (18-DOF, 6 legs) running a local Llama-3.2-3B
persona named Yuzu on a Jetson Orin Nano. Fully offline: local STT, local
LLM, local TTS, no cloud.

Paint scheme is Ghost's call and deliberately not pinned down in this
repo -- see `paintstepslol.txt` for the prep process, which works for
any colours.

**Status:** brain and voice work today on any PC. Chassis is later.

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
python YUZU_TESTER.py         # 278 tests, ~18 seconds
python muto_leg_control.py    # dry-run every gait, no robot required
```

All stdlib. No pip installs, not even for Ollama. Runs in Pydroid on a phone.

## Getting the brain running

Full runbook in **[JETSON_SETUP.md](JETSON_SETUP.md)**. Short version,
on any PC — no Jetson needed:

```
ollama pull llama3.2:3b
python build_yuzu_model.py --create    # bake the persona into a model
python yuzu_brain.py --chat            # talk to her
python yuzu_prompt_eval.py             # score how well she follows the prompt
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
| **Talk to her** | |
| `yuzu_all_in_one.py` | Reply pipeline + main loop. **Start here.** |
| `yuzu_brain.py` | Ollama client. Stdlib only, streaming, history |
| `yuzu_personas.py` | Persona loader and composer |
| `personas/` | One file per character; body rules shared |
| **Measure her** | |
| `YUZU_TESTER.py` | Test suite. 278 tests, ~18s |
| `yuzu_prompt_eval.py` | Scores prompt compliance against the real model |
| `YUZU_AB.py` | Runs two personas head to head and prints one table |
| `yuzu_doctor.py` | Tap-to-run checkup. Standalone, no arguments |
| `gguf_inspect.py` | Reads a GGUF header — quant, context, chat template |
| `build_yuzu_model.py` | Generates a `Modelfile` per persona |
| **The body** | |
| `muto_firstcontact.py` | **Run this before any gait.** Guided bring-up, one joint at a time |
| `muto_leg_control.py` | Leg wrapper, tripod gaits, `DummyBot` simulator |
| `yuzu_voice.py` | Piper TTS. The project's one dependency boundary |
| **Read these** | |
| `PHONE_START.md` | Phone instructions, no terminal needed |
| `DEPLOY.md` | Moving the brain onto the Jetson |
| `JETSON_SETUP.md` | Setup runbook, PC and Jetson, plus the 8GB tuning |
| `HEADLESS_SETUP.md` | Jetson setup from a Steam Deck, no monitor |
| `UBUNTU_LAPTOP.md` | Putting Ubuntu on the laptop, phone-readable |
| `PERSONA_SWITCHING.md` | Two characters on one robot, and the tradeoffs |
| `HANDOFF.md` | Pasteable catch-up for a fresh AI chat |
| `CLAUDE.md` | Working notes: every measured result, and what's settled |
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

### Which prompt is actually running

`yuzu_personas.LIVE_PERSONA` — one line, currently `yuzu4`. That is what
the robot, `yuzu_brain --chat` and the eval all boot with when nothing
says otherwise.

It is deliberately *not* `yuzu.persona`. That file is v1: frozen, pinned
byte-for-byte by a test, and measured at a 20% action hit rate. It keeps
the short `yuzu` name because `Modelfile.yuzu` and the Ollama model
called `yuzu` are named off it — but booting the worst-measured prompt
because it owns the nicest filename is exactly the regression the
promotion rule exists to stop.

**The promotion rule: the measured winner becomes the base.** To try a
new variant against the live one:

```
python YUZU_AB.py               # runs LIVE_PERSONA vs the candidate
python YUZU_AB.py yuzu4 yuzu5   # or name both arms
```

Twelve prompts through each arm, scored with the robot's own parser,
printed as one table with `moves_at_all` at the top — the honest
robot-facing number. It also prints what one reply is worth in
percentage points, because every difference in the yuzu2-vs-yuzu3 round
turned out to be a single reply and looked like a result until it was
counted. If a candidate wins, move `LIVE_PERSONA` and record it in
`CLAUDE.md`.

**Pivoting to a different main character** is `python yuzu_personas.py
--new <name>`, edit the file it writes, then move `LIVE_PERSONA`. The
scaffold starts from the measured prompt, so a new character inherits
all nine proven wins instead of restarting the lineage. Full walkthrough
of what you keep and what you rewrite is in
[PERSONA_SWITCHING.md](PERSONA_SWITCHING.md).

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
    -> ask_yuzu_brain()             REAL: yuzu_brain.py -> Ollama
    -> normalize_actions()          stray *asterisks* -> [brackets]
    -> split_reply()                ordered speech/action parts
         speech -> speak()               REAL: yuzu_voice.py -> Piper
         action -> whitelist -> muto_leg_control gait
```

One STUB left: the mic. The brain is real, and so is her voice — Piper
if it's installed, printing if it isn't. If Ollama isn't running the
loop still boots and says so instead of crashing.

```
python3 yuzu_voice.py --check   # what's installed
python3 yuzu_voice.py           # hear her say real captured replies
python3 yuzu_voice.py --list    # every voice you have, and which is live
python3 yuzu_voice.py --use amy # switch voices, permanently
```

Browse and preview voices at **rhasspy.github.io/piper-samples** before
downloading — they're ~60MB each.

Setup is in [JETSON_SETUP.md](JETSON_SETUP.md) §6 and works on any
laptop — Piper is software, no Jetson needed.

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
and range-safe, but every angle is a guess.

**Real servos are an environment variable, not a code edit.** There is
nothing to swap in `yuzu_all_in_one.py` — `muto_leg_control.connect()`
picks the simulator or the real bus, and asking for hardware and not
getting it is a hard failure rather than a silent fall back to the
simulator.

```
python yuzu_all_in_one.py                  # simulation
YUZU_HARDWARE=1 python yuzu_all_in_one.py  # 18 real servos
```

Before the first `YUZU_HARDWARE=1` of the robot's life:

```
python muto_firstcontact.py                # rehearse the whole thing dry
YUZU_HARDWARE=1 python muto_firstcontact.py
```

Six stages — comms, each joint alone, mirroring, standing, tripods, one
walk cycle — with a yes/no after every movement and the angle limit
starting at 15°. You cannot reach a walk cycle without having watched
every leg move by itself first. Record what you learn into `LEG_OFFSETS`
and `LEG_SIGN` in `muto_leg_control.py`.
