# The Nano arrived. Do this.

One page, top to bottom, no decisions. Read it off your phone while
you're at the board.

Everything else in this repo is reference. This is the runbook.

> ## ⚡ THE ONE THING
> ```
> sudo nvpmodel -m 0
> sudo jetson_clocks
> ```
> The board ships **throttled**. There is no error, no warning, no
> symptom — everything is just slow, forever, for no visible reason.
> It's step 5 below. Don't skip it.

---

## What you need on the desk

- The Orin Nano Super dev kit + its power supply
- The microSD (JetPack goes on this)
- The NVMe SSD (fitted into slot **J11** under the board)
- A **USB-C cable** from the Steam Deck to the Jetson
- The Deck, in Desktop Mode

No monitor needed. No keyboard needed. The Deck is your terminal.

---

## 1 — Flash JetPack to the microSD

On the Deck: download the **Jetson Orin Nano Developer Kit** SD image
from NVIDIA, write it to the card with **Impression** (or Etcher).

Card into the Jetson. Don't power on yet.

## 2 — Get a terminal over USB-C

Plug USB-C from the Deck to the Jetson, **then** power the Jetson on.

On the Deck:

```bash
pip install --user pyserial
python3 -m serial.tools.miniterm /dev/ttyACM0 115200
```

Nothing there? See what did appear:

```bash
ls /dev/ttyACM* /dev/ttyUSB*
```

Still nothing is almost always the cable. Swap it.

*(To quit miniterm later: **Ctrl-]**)*

## 3 — First boot, in the terminal

Ubuntu's setup wizard appears as text. Work through it:

- Licence, language, keyboard, timezone
- **Username and password — write these down**
- **Join your wifi.** This is the step that matters. Get it on the
  network now and everything after is just SSH.

It reboots at the end. Reconnect with the same miniterm command and
log in.

## 4 — SSH in, ditch the cable

At the serial prompt:

```bash
ip addr show wlan0 | grep 'inet '
```

Note the address. Then from a normal Deck terminal:

```bash
ssh yourname@192.168.1.x
```

That's the last time you need the serial cable.

*(Fallback if wifi went wrong: the Jetson is always at
`192.168.55.1` over the USB-C link.)*

## 5 — ⚡ UNTHROTTLE IT

```bash
sudo nvpmodel -q          # what mode is it in now?
sudo nvpmodel -m 0        # MAXN / MAXN SUPER
sudo jetson_clocks        # pin the clocks high
```

`nvpmodel -q` should list a MAXN / Super mode. If the only options are
the old 7W/15W ones, the QSPI firmware is pre-Super and you'd need the
SDK Manager route to add it. **Better to find that out now** than after
you've built everything on top.

## 6 — Root filesystem onto the NVMe

The card is slow and swap will kill it. Move the real work to the SSD:

```bash
git clone https://github.com/jetsonhacks/rootOnNVMe.git
cd rootOnNVMe
./copy-rootfs-ssd.sh
./setup-service.sh
sudo reboot
```

After it comes back, confirm:

```bash
df -h /
```

Then swap, also on the SSD:

```bash
sudo fallocate -l 16G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

## 7 — Ollama and the model

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull hf.co/mradermacher/Llama-3.2-3B-Instruct-heretic-ablitered-uncensored-GGUF:Q4_K_M
```

That's a ~2GB download. Go make a drink.

**Check it's on the GPU, not the CPU:**

```bash
ollama ps
```

The processor column should say GPU. CPU-only works but is noticeably
slower, and it looks exactly like the code being broken.

## 8 — Her brain

```bash
sudo apt install -y git python3
git clone https://github.com/GhostMagi/YUZU.git
cd YUZU
python3 YUZU_TESTER.py
```

**297 tests, ~18 seconds.** If they pass, the software made the trip
intact. Nothing to install — the whole thing is standard library.

## 9 — Talk to her

```bash
MODEL=$(ollama list | grep -i heretic | awk '{print $1}' | head -1)
YUZU_MODEL="$MODEL" python3 yuzu_all_in_one.py
```

Type at her. `/persona coco` to switch characters. `quit` to stop.

**That's the goal for day one.** Everything below is a bonus.

---

## 10 — Her voice (bonus)

```bash
pip install piper-tts
sudo apt install -y alsa-utils
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

```bash
mkdir -p ~/YUZU/voices && cd ~/YUZU/voices
BASE=https://huggingface.co/rhasspy/piper-voices/resolve/main/en/en_US/amy/medium
wget $BASE/en_US-amy-medium.onnx
wget $BASE/en_US-amy-medium.onnx.json
cd ~/YUZU && python3 yuzu_voice.py --check
```

**Heads up:** `piper-tts` ships x86 wheels for certain. Whether there's
an arm64 one is unverified — if `pip install` fails here, that's the
known risk, not something you did. She still runs and prints; only the
audio is missing. Say so and we'll sort it.

## 11 — The 8GB settings (bonus)

The Orin has ONE pool of memory shared between CPU and GPU. Ollama's
defaults assume a desktop with its own graphics card.

```bash
sudo systemctl edit ollama
```

Paste:

```ini
[Service]
Environment="OLLAMA_NUM_PARALLEL=1"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_KEEP_ALIVE=-1"
Environment="OLLAMA_FLASH_ATTENTION=1"
Environment="OLLAMA_KV_CACHE_TYPE=q8_0"
```

```bash
sudo systemctl daemon-reload && sudo systemctl restart ollama
```

Why each of those, in **JETSON_SETUP.md §5b**. The short version: they
stop Ollama reserving memory for concurrent requests a robot with one
mouth will never make, and keep her loaded so the first thing anyone
says after a quiet spell isn't the slowest reply she ever gives.

## 12 — Check your work

```bash
python3 yuzu_doctor.py
```

On a Jetson it adds a section: power mode, RAM, what the swap sits on,
and which of those Ollama settings actually took. Screenshot the
SUMMARY and send it.

*(That section has never run on real hardware — I wrote it from file
paths. If it says something daft, that's my bug, not your board.)*

---

## If it goes wrong

| Looks like | Actually is |
|---|---|
| Everything is slow | You skipped step 5. `sudo nvpmodel -m 0` |
| No `/dev/ttyACM0` | The cable. Swap it |
| `Can't reach Ollama` | `ollama serve` isn't running |
| `no model named 'yuzu'` | Use step 9's `MODEL=` line — the model is named after the HF path, not "yuzu" |
| Replies take forever | `ollama ps` — if it says CPU, it's not using the GPU |
| Tests fail | Send me the output. That's a real bug, not your setup |
| `pip install piper-tts` fails | Known arm64 risk. She runs fine without it |

---

## Where the other docs went

Nothing was deleted; this page just goes first.

| Doc | When you'd open it |
|---|---|
| **NANO_DAY_ONE.md** | ← you are here |
| `JETSON_SETUP.md` | Reference. §5b memory tuning, §6 voices |
| `HEADLESS_SETUP.md` | The long version of steps 1–6, with the reasoning |
| `DEPLOY.md` | Why the brain is this portable |
| `UBUNTU_LAPTOP.md` | The laptop. History now — it was the stopgap |
| `CLAUDE.md` | Every measured result and why things are the way they are |
