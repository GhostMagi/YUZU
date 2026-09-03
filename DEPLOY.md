# Moving Yuzu's brain onto the Jetson

Short answer: **yes, you can just plop it on.** `git clone`, then run
it. No pip install, no build step, no config file to edit.

This is verified, not assumed — the whole repo was audited for
third-party imports and run from an empty directory on a bare `python3`
with nothing installed.

---

## What has to be on the Jetson

| Thing | How |
|---|---|
| Python 3 | Already on JetPack |
| This repo | `git clone` |
| Ollama | one install command |
| The model | `ollama pull` |
| Yahboom's `muto_lib` | Only when the chassis exists |

That's the whole list. **Nothing in this project needs pip.**

## The actual commands

```bash
git clone https://github.com/GhostMagi/YUZU.git
cd YUZU
python3 YUZU_TESTER.py          # 242 tests. If this passes, the code is fine.
python3 yuzu_all_in_one.py    # talk to her
```

The test suite is the deployment check. It exercises the parser, the
personas, the gait library against the simulator, the Ollama client
against a mock server, and the safety machinery. If it passes on the
Jetson, the software made the trip intact.

## Why it's this portable

Every dependency is standard library, on purpose:

- `yuzu_brain.py` talks to Ollama over HTTP with `urllib`, not the
  `ollama` package or `requests`
- `gguf_inspect.py` parses GGUF headers with `struct`, not the `gguf`
  package
- `YUZU_TESTER.py` is `unittest` with a hand-rolled mock Ollama server,
  not pytest
- `muto_leg_control.py` is arithmetic and `time.sleep`

The one exception is Yahboom's `muto_lib`, imported **lazily inside
`connect()`** and only reached when `YUZU_HARDWARE` is set. Until the
chassis exists, nothing tries to import it.

## The one switch that matters

```bash
python3 yuzu_all_in_one.py                  # simulation
YUZU_HARDWARE=1 python3 yuzu_all_in_one.py  # real servos
```

This is deliberately **not** auto-detected. Probing a serial port and
quietly falling back to simulation would make a loose cable look
identical to working code. Ask for hardware without hardware and it
stops with an explanation rather than pretending.

## Order of operations

**1. Jetson arrives, no chassis yet**

```bash
git clone ... && cd YUZU
python3 YUZU_TESTER.py
curl -fsSL https://ollama.com/install.sh | sh
ollama pull hf.co/mradermacher/Llama-3.2-3B-Instruct-heretic-ablitered-uncensored-GGUF:Q4_K_M
python3 build_yuzu_model.py --base hf.co/... --create
python3 yuzu_prompt_eval.py --persona yuzu2 --runs 3
python3 yuzu_all_in_one.py
```

That is the complete brain, running on the real hardware, talking to
you by keyboard. No robot needed.

**2. Chassis arrives — do NOT skip to step 3**

```bash
YUZU_HARDWARE=1 python3 muto_firstcontact.py
```

Six stages, a yes/no after every movement, starting at a 15-degree
limit. Comms, then each of the 18 joints alone, then mirroring, then
standing, then tripods, then one walk cycle. Any "no" stops and parks
the legs.

Every angle in the gait library is an educated guess that has never
touched hardware. Against the simulator a wrong sign is a wrong number
in a list; against eighteen 35KG servos it is a leg driving into the
frame at full torque and holding there.

**3. Only then**

```bash
YUZU_HARDWARE=1 python3 yuzu_all_in_one.py
```

## Things that will not follow you across

- **Ollama's models** live in `~/.ollama`, not in the repo. Pull them
  again on the Jetson (or copy the directory).
- **The laptop's eval scores** are laptop scores. The Jetson's GPU is
  different, so re-run `yuzu_prompt_eval.py` there. Sampling settings
  travel; results don't.
- **PocketPal's settings** are on the phone and unrelated to any of
  this.

## If something breaks on arrival

```bash
python3 yuzu_doctor.py    # one command, no arguments, prints a report
```
