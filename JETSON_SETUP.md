# Getting Yuzu's brain running

Goal: Llama-3.2-3B Heretic-abliterated answering as Yuzu, through
Ollama, fully offline. Written to be done in two stages — **stage 1
needs no Jetson at all**, so the prompt can be tuned before the money
is spent.

---

## Stage 1 — before the Jetson arrives

Everything in this repo except the servo code runs on any x86 machine.
Do the prompt work here, on hardware you already own, so the Jetson
arrives to a finished brain instead of a blank one.

### 1. Install Ollama on a normal PC or laptop

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama serve          # leave running in one terminal
```

**On the Steam Deck specifically:** SteamOS has a read-only root
filesystem, so the install script may not be able to write where it
wants, and anything in `/usr` gets wiped by a SteamOS update anyway.
The clean way is a `distrobox` container (ships with SteamOS) and
installing Ollama inside it. I couldn't test this from here — if the
Deck fights you, any other PC works just as well for stage 1, and the
Deck stays what your notes already say it is: the flashing and SSH
workstation.

### 2. Prove the pipeline with stock Llama first

Do this before hunting down the abliterated weights. It separates
"my setup works" from "my model works":

```bash
ollama pull llama3.2:3b
python build_yuzu_model.py --all --create  # one model per persona
python yuzu_brain.py                       # one-shot smoke test
python yuzu_brain.py --chat                # talk to her
```

If she answers in character, the whole chain is good — prompt,
Modelfile, client, parser.

### 2b. A note if you're testing in PocketPal first

PocketPal supplies its own chat template and system prompt on top of
whatever is in the GGUF. So when you test there, you are testing
**PocketPal's** template, not necessarily the model's. Two things to
confirm in the app's per-model settings before blaming the prompt:

- the **system prompt** field actually contains Yuzu's prompt
  (`yuzu_system_prompt.txt`), not a leftover default
- the **chat template** is a Llama 3 / Llama 3.2 one, not ChatML or
  Mistral

A mismatch here produces exactly the "she ignores her personality"
symptom, and no amount of prompt rewriting fixes it. Ollama on the
Jetson reads the template from the GGUF instead, so the two setups can
behave differently on the same file — worth knowing when a reply that
was fine on the phone gets weird on the robot.

### 3. Measure the prompt

```bash
python yuzu_prompt_eval.py --runs 3
```

12 prompts × 3 runs, scored against every mechanically-checkable rule
in the system prompt: does she always speak, does she use brackets and
never asterisks, are her actions ones this body can do, does she write
the user's turn. Deliberately includes the cases that broke before —
"Do a stretch" (the all-actions freeze) and "Wave at me!" (bait for
body parts the chassis doesn't have).

Change one thing, re-run, compare. That's the loop. Chasing prompt
quirks by eyeballing three replies is how you end up fixing a problem
that was never there.

### 4. Then swap in the abliterated model

**CONFIRMED — the file already exists and Ghost already has it:**

```
Llama-3.2-3B-Instruct-heretic-ablitered-uncensored.Q4_K_M.gguf
```

Source model is
`DavidAU/Llama-3.2-3B-Instruct-heretic-ablitered-uncensored`
(the "ablitered" misspelling is in the real repo name, not a typo here).
The `.Q4_K_M` naming — a **dot** before the quant rather than a hyphen —
is mradermacher's convention, so the GGUF almost certainly comes from
`mradermacher/...-GGUF`. Bartowski names his `-Q4_K_M`.

**No conversion needed.** An earlier draft of this file walked through
converting safetensors with llama.cpp; that's unnecessary. A GGUF was
already published, it's ~2GB, and it's already on the phone. Copy that
same file to the Jetson — no re-download, no llama.cpp build.

```bash
python build_yuzu_model.py \
  --base ./Llama-3.2-3B-Instruct-heretic-ablitered-uncensored.Q4_K_M.gguf \
  --create
python yuzu_prompt_eval.py --runs 3          # compare to stock's score
```

Q4_K_M is the right pick for a 3B: ~2GB, and small models lose real
coherence below Q4.

Before building a model from any GGUF you didn't produce yourself,
check its header:

```bash
python gguf_inspect.py yuzu-Q4_K_M.gguf
python gguf_inspect.py yuzu-Q4_K_M.gguf --template    # print it in full
python gguf_inspect.py yuzu-Q4_K_M.gguf --json        # paste-friendly
```

It reads only the front of the file, so it's instant even on a 20GB
model, and it answers the question that actually causes trouble: is a
**chat template** present, and does it handle a system role?

This matters more than it sounds. Ollama reads the template out of GGUF
metadata. If it's missing or wrong, the model still loads and still
generates — it just ignores the system prompt, or starts writing your
turn as well as hers. That looks exactly like a bad persona prompt, and
isn't. If `gguf_inspect` flags it, add an explicit Llama 3.2 `TEMPLATE`
block to the Modelfile rather than rewriting the prompt.

Cross-check what Ollama actually ended up with:

```bash
ollama show yuzu --template
ollama show yuzu --system
```

Q4_K_M is the right quant: ~2GB, and a 3B is small enough that heavier
quantization starts costing real coherence.

---

## Stage 2 — on the Jetson

### 0. What to actually buy

**Board: order from NVIDIA's own marketplace, not Amazon.** Direct was
$399 when Ghost checked; the Amazon listing for the identical kit was
$508 and Amazon's own page flagged it "High price". Same product, same
box. Prices move, so compare both, but check NVIDIA first.

**In the box:** the module on its carrier board, a 19V power supply and
regional cords. That's it.

**NOT in the box, and needed for first boot:**

- Boot storage — the NVMe below, or a microSD (64GB min)
- **A DisplayPort cable, or a DP-to-HDMI adapter.** The dev kit outputs
  DisplayPort. This is the classic gotcha: everyone has HDMI cables and
  none of them fit. Order it at the same time.
- USB keyboard and mouse, and a monitor
- Ethernet is optional but makes setup much easier

There is also a headless path — initial config over USB-C from another
machine — which would suit the Steam Deck and skip the DP adapter
entirely. Worth checking before buying the adapter.

**Audio: buy it later, not now.** Everything through Stage 2 works with
no microphone and no speaker, because listen_and_transcribe() is a
plain input() and speak() is a print(). You can flash the board, run
the model, score the prompt and drive the whole pipeline by typing.
Buying audio up front means it sits in a drawer during the part of the
project most likely to take a week. When the brain half is proven, a
USB speakerphone puck is the right category: mic and speaker in one
device, one USB port, one thing to configure instead of two competing
for ALSA.

**Budget check:** $399 board + ~$80 SSD is already ~$477 against a $450
cap, before audio or the adapter. Not fatal, worth watching.

### 0b. Storage — get the NVMe

The dev kit carrier board has two M.2 Key M slots on the underside.
**J11 is the one you want**: M.2 2280, PCIe Gen3 x4, and it's the boot
slot. (J24 is 2280 as well but only Gen3 x2. The Key E slot is already
occupied by the Wi-Fi module — don't put an SSD there.)

So **M.2 2280 Key M NVMe** is exactly the right part to buy. Notes:

- Gen4 drives work fine but run at Gen3 speeds here, so there's no
  reason to pay the Gen4 premium. Any reliable Gen3 x4 drive is the
  sweet spot.
- 500GB is plenty; don't get talked into 1TB. The 3B Q4_K_M is ~2GB.
- Budget-brand drives (KingSpec and similar) work and the form factor
  is what matters, but compare against a WD SN570 or Crucial P3 at the
  same capacity — often similar money for a better-known controller.
  Swap is sustained writes, which is exactly where cheap drives
  struggle.
- **The real reason this matters isn't boot speed.** It's swap. With
  8GB shared between CPU and GPU, and eventually Whisper + the 3B +
  Piper all wanting a piece, you will lean on swap. Swap on NVMe is
  usable; swap on microSD is miserable, and the sustained writes will
  wear the card out. This purchase turns the memory ceiling from a hard
  wall into a soft one.

microSD boot does work (64GB minimum) if the SSD is delayed — start
there and migrate later, nothing is blocked.

### 1. Flash JetPack

Steam Deck in Desktop Mode, NVIDIA SDK Manager or the SD card image.
If the NVMe is installed before you flash, SDK Manager can install
straight to it, which is cleaner than installing to SD and migrating.

### 2. Unlock the performance modes

The Orin Nano ships throttled. This is the single biggest free speedup:

```bash
sudo nvpmodel -m 0     # MAXN / MAXN SUPER — max power mode
sudo jetson_clocks     # pin clocks to maximum
sudo pip3 install jetson-stats && jtop     # watch RAM, GPU, temps
```

`nvpmodel -m 0` is the mode you want for inference. Check `nvpmodel -q`
to confirm what it landed on.

### 3. Install Ollama

```bash
curl -fsSL https://ollama.com/install.sh | sh
```

Ollama supports arm64 and detects JetPack CUDA. Confirm it's on the GPU
and not CPU — watch `jtop` during a reply, or check `ollama ps` for the
processor column. CPU-only on a 3B is usable but noticeably slower.

### 4. Copy this repo over and build the model

```bash
python3 build_yuzu_model.py --base <your model> --create
python3 yuzu_brain.py --chat
python3 yuzu_all_in_one.py        # full loop
```

### 5. Memory — the thing that will actually bite you

8GB shared between CPU and GPU, and eventually three things want it at
once: Whisper (STT), the 3B (LLM), Piper (TTS). Rough budget:

| Component | Approx |
|---|---|
| Llama 3.2 3B Q4_K_M @ 4096 ctx | ~2.5–3 GB |
| whisper.cpp base/small | ~0.5–1 GB |
| Piper TTS | ~0.1 GB |
| JetPack desktop + OS | ~1.5–2.5 GB |

It fits, but not with room to spare. Two things that help:

- **Run headless.** `sudo systemctl set-default multi-user.target` and
  SSH in from the Deck. The desktop is the biggest easy win.
- **Swap.** Jetson defaults to zram, which trades CPU for RAM. For LLM
  work a real swapfile on the SD card is usually the better trade.

Bring them up one at a time — Ollama alone, then add Whisper, then add
Piper — as your own notes already say. Loading all three on day one
means an OOM with no idea which one caused it.

`num_ctx` in `yuzu_brain.py` is the dial that most directly trades
memory for conversation length. 4096 is a starting point, not a law.

### 6. Piper

Piper needs **both** files per voice in the same folder — `.onnx` and
`.onnx.json` — or it silently won't load. Voice speed is `length_scale`
in the json; lower is faster. 0.85–0.9 suits the gyaru energy.

---

## When something's wrong

| Symptom | Where to look |
|---|---|
| `Can't reach Ollama` | `ollama serve` not running, or `OLLAMA_HOST` wrong |
| `no model named 'yuzu'` | `python build_yuzu_model.py --create` |
| She sounds like ChatGPT | Run `gguf_inspect.py` on the model — a template that drops the system role is the usual cause. Then check `ollama show yuzu --system` |
| `Not a GGUF file` | You got an LFS pointer or an HTML error page, not the model. Re-download |
| Actions do nothing | Run the eval — `actions_runnable` shows exactly which phrasings got dropped |
| Replies too long, TTS drags | Lower `num_predict` in `yuzu_brain.py`, rebuild the Modelfile |
| She writes your lines | `no_puppeteering`; the `stop` params in the Modelfile catch most of it |
| Very slow on Jetson | Confirm GPU not CPU; `nvpmodel -m 0`; check thermals in `jtop` |

Sources for the model:
[DavidAU/Llama-3.2-3B-Instruct-heretic-ablitered-uncensored](https://huggingface.co/DavidAU/Llama-3.2-3B-Instruct-heretic-ablitered-uncensored)
· [bartowski GGUF quants](https://huggingface.co/bartowski/Llama-3.2-3B-Instruct-uncensored-GGUF)
· [QuantFactory abliterated GGUF](https://huggingface.co/QuantFactory/Llama-3.2-3B-Instruct-abliterated-GGUF)
