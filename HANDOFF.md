# Yuzu-Spider-V1 — handoff

**Paste this whole file into a fresh AI chat to bring it up to speed.**
Written Sept 3, 2026. Repo: github.com/GhostMagi/YUZU

---

## What this is

Ghost is building a companion robot. A Yahboom Muto S2 hexapod (six
legs, 18 serial-bus servos, a 2-DOF camera on a swivel) with a local
LLM brain — no cloud, everything runs on the robot. The persona is
**Yuzu**, a gyaru character who talks and moves.

The trick that makes it work: Yuzu writes movements in `[square
brackets]`. Code strips them out of her speech, checks each one against
a whitelist of things the body can actually do, and runs the real gait.
Everything else she says goes to text-to-speech.

---

## Catch-up: where things actually stand

**Hardware**
- Jetson Orin Nano Super Dev Kit — **ordered**, $399 direct from NVIDIA
- 512GB M.2 2280 NVMe (KingSpec, Gen3 x4) — **ordered**
- Muto S2 chassis — **not yet bought**, deliberately later
- Acer Aspire VN7-592G on Ubuntu 22.04 — **working**, this is the eval
  machine. Model runs 100% on its GTX 960M.
- Testing day-to-day happens in **PocketPal on a Z Flip 6**

**Software — all of this works today**
- Full reply pipeline: listen → think → parse → move → speak
- Real Ollama client (stdlib only, no pip installs anywhere)
- Tripod gait library + a `DummyBot` simulator, so gaits run with no
  hardware attached
- Swappable personas: character text and body rules are separate files,
  composed at load time
- 271 tests, ~18 seconds, all passing

**Model:** `Llama-3.2-3B-Instruct-heretic-ablitered-uncensored` Q4_K_M
(the "ablitered" misspelling is genuinely in the repo name), pulled via
`ollama pull hf.co/mradermacher/Llama-3.2-3B-Instruct-heretic-ablitered-uncensored-GGUF:Q4_K_M`

**Measured prompt quality**, scored by machine against the real parser:
- v1 → 20% of her movements actually ran
- v2 → 78–91% depending on the round
- Latest cold-run: `moves_at_all` 80.6%, `has_dialogue` 94.4%

---

## Ghost's own progress — worth knowing

He had **never written a line of Python** when this started. Facts,
not flattery:

- Wrote a working regex bracket-action parser himself, on his phone,
  in Pydroid, unaided. That parser is still the core of the project.
- Learned what an LLM was about a week before this repo existed.
- Got Ubuntu booting on a laptop with **locked NVRAM** — a genuinely
  nasty problem that needed a firmware-registered trusted file and
  Secure Boot toggled on, then off. That took a night and it's all
  written up in `UBUNTU_LAPTOP.md`.
- Ran the first machine-scored prompt evals himself.
- **Caught a mistake that would have invalidated a whole round of
  results:** PocketPal renders `*asterisks*` as italics without showing
  the markers, so the AI scoring his screenshots was reading asterisk
  actions as plain text. He flagged it unprompted.

His working method — A/B test in PocketPal, screenshot, score it
against the real parser — is the reason the numbers above exist. It
works. Don't replace it with theory.

---

## What's left, in order

**1. Score `yuzu5` against `yuzu4` on the laptop**
```
cd YUZU && git pull
python3 YUZU_AB.py          # yuzu4 vs yuzu5, 12 replies each, one table
```
`yuzu4` is `yuzu2` plus one bare-command example, and it is what boots
today (`LIVE_PERSONA` in `yuzu_personas.py`). It fixed a reproducible
bug — told "Walk forward." she used to *narrate* walking instead of
doing it, because every example in the prompt was a question or a
polite request and none was a flat order. It held live, 4/4 replies
moved.

`yuzu5` is `yuzu4` trimmed 17% for latency, with the three character
rules cut because the examples already demonstrate them. It has never
been run against a model. If it wins, move `LIVE_PERSONA` and note it
in `CLAUDE.md`; if it loses, `yuzu4` stays and yuzu5 is the record of
what the trim cost.

Watch `moves_at_all` and ignore a difference of one or two replies —
at 12 replies each, one reply is 8.3 percentage points, and that is
what made the yuzu2-vs-yuzu3 round look like a result when it wasn't.
`YUZU_AB.py` prints that number under the table.

**2. When the Jetson arrives** — follow `DEPLOY.md`. It's a `git clone`;
the whole repo is standard library, nothing to install.
⚠️ Run `sudo nvpmodel -m 0` — the board ships throttled and forgetting
it makes everything slow with no visible cause.

**3. When the chassis arrives** — run `muto_firstcontact.py` BEFORE any
gait. Six stages, a yes/no after every movement, starting at a 15°
limit. Every angle in the gait library is an educated guess that has
never touched hardware.

**4. Audio (Whisper + Piper)** — deliberately deferred. The whole
pipeline runs on typed input, so audio bought now would sit in a drawer.

**5. Vision / follow-me** — see the constraints in `CLAUDE.md` first.
The gait functions block for 2–5 seconds each, so a vision controller
cannot be layered on top of them without a non-blocking API underneath.

---

## Open curiosities Ghost has raised

**"Can I run multiple LLMs?"** — Answered. He doesn't need to: a
persona is just a different system prompt, so every character shares
one loaded model for free. Two 3B models won't fit in 8GB alongside
Whisper and Piper anyway. A small 1B specialist alongside the 3B would
fit, if a real use for one appears.

**"What's the SSD for then?"** — Ollama unloads the model after ~5
minutes idle. Reloading 2.7GB off microSD is ~45 seconds; off NVMe it's
1–3. That's the difference between a robot that answers and one that
doesn't. Plus swap headroom on 8GB, and microSD cards die from
sustained writes.

**Saya (quadruped)** — a second robot, kuudere personality, ESP32, 8×
MG90S, OLED face. `personas/_hardware_saya_quad.txt` is a DRAFT guessed
from notes. It needs Ghost's real action list before it means anything.

**Humanoid body** — long-term want. White with gold trim.

---

## Settled. Don't re-litigate these.

- **Chassis paint colours stay out of the repo.** He's changed the
  scheme repeatedly. `paintstepslol.txt` keeps the prep process, which
  works for any colours. (Yuzu *herself* still loves hot pink — that's
  character, it stays.)
- **The asterisk hypothesis is closed.** Rewording the anti-asterisk
  rule so it doesn't display an asterisk changed nothing, measured.
  Keep the rule; deleting it entirely did regress.
- **`[winks]` and `[laughs]` are accepted.** The whitelist drops them
  safely. They're a 3B ceiling, not a prompt bug.
- **Skipping ROS2** on purpose — direct Python serial calls instead.
- **`personas/yuzu.persona` is frozen.** A test asserts it stays
  byte-identical to the version Ghost tested. Iterate on `yuzu2`.

---

## Notes for whoever picks this up

**He works from a phone most of the time.** File paths and terminal
commands are often useless to him. Give him text he can paste, or a
script he can tap Run on.

**Paste the actual prompt text when it changes.** Not a path, not a
command — the text.

**One step at a time.** He's said plainly that keeping everything
organised in his head is hard. That's what this file and the repo docs
are for. Don't hand him a ten-step plan; hand him step one and wait.

**Check things before asserting them.** This project has been bitten
repeatedly by confident guesses — a stale doc, a parser bug nobody
tested, a hypothesis that felt obviously right and measured as noise.
Run the code. Score the output. `python YUZU_TESTER.py` is 18 seconds.

**Where the detail lives**
| File | What's in it |
|---|---|
| `CLAUDE.md` | Every measured finding, in detail |
| `Yuzu_Full_Technical_Context_Dump.md` | Full technical background |
| `DEPLOY.md` | Moving the brain to the Jetson |
| `HEADLESS_SETUP.md` | Jetson setup with no monitor |
| `UBUNTU_LAPTOP.md` | The laptop's boot saga |
| `PERSONA_SWITCHING.md` | How characters swap |
