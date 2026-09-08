# YUZU cyberdeck — handoff for design & idea discussion

**Paste this whole file into a fresh Claude chat.** It exists so the
build / hardware / "what could she do" conversation happens somewhere
other than Claude Code, which is being saved for writing the software.

**Your job in that chat: ideas, sourcing, tradeoffs, feasibility.**
Not writing code. Decisions come back to Claude Code as a summary.

**Ghost saw his first cyberdeck yesterday.** He is sharp and learns
fast, but assume no prior exposure to the hobby's conventions, vendors
or vocabulary. Explain the *why*; don't dumb it down.

---

## 1. What this is

Ghost is building a **cyberdeck** — a handmade portable computer —
whose entire purpose is a **fully offline AI character living on it**.
No cloud, ever, at any point.

The character is **Shiro**: yami kawaii, sweet sing-song surface,
genuinely unsettling underneath. Four others exist and switching is one
config line (Yuzu the gyaru, Coco the kuudere, Byte the netrunner, Saya
the tsundere).

**The software already works on the real board.** The deck itself does
not exist yet. That gap is the conversation.

---

## 2. Hardware in hand — confirmed working

| thing | state |
|---|---|
| **Jetson Orin Nano Super devkit, 8GB** | flashed, Ubuntu, unthrottled (`nvpmodel -m 0` + `jetson_clocks`), 16GB swap |
| **512GB NVMe SSD** | installed, cloned, booting from it, microSD removed |
| **A keyboard** | he owns one — spec unknown, ask |
| Z Flip 6 phone | his main terminal, USB serial + a serial terminal app |
| Steam Deck | also works as a serial console |
| Acer Aspire VN7-592G laptop | Ubuntu 22.04, second console, the eval machine |
| JBL Go 3 BT speaker | **Bluetooth pairing to the Jetson FAILED**, abandoned |
| 64GB SanDisk USB-A, 2× microSD | spare |

Four ways into the board already work: phone, Steam Deck, laptop, and
`ssh ghost@192.168.55.1` over USB networking. WiFi connected and
auto-reconnects.

**Financially the expensive part is done.** The board and SSD are the
big-ticket items and they are bought. What remains is screen, power,
audio and enclosure.

---

## 3. Software state — DO NOT REDESIGN THIS

Running today, on the actual board:

- **Local LLM**: Llama-3.2-3B (heretic-abliterated, Q4_K_M) via Ollama
- **Five personas**, swappable, Shiro live
- **Piper TTS** — the code works. Nothing is attached to hear it.
- **301 automated tests**, ~2 min on the board
- Ollama tuned for 8GB shared memory (one model, one parallel slot,
  flash attention, q8_0 KV cache, model kept resident)
- Python **standard library only**, except Piper

**Software gaps:** the mic (Whisper) is a stub, unbuilt. No vision.

---

## 4. Context he probably doesn't have yet

**Almost every cyberdeck guide online assumes a Raspberry Pi.** His
board is dramatically more powerful and has *different ports and
different power needs*, so guides will mislead in specifics even when
the ideas transfer. Whenever a tutorial says "plug the HDMI in" or
"power it off a USB battery", stop and re-check against the Orin.

**Every deck build is really three problems: POWER, DISPLAY, CASE.**
Everything else — storage, input, software — is comparatively easy.
His board makes the first two harder than average and the third no
easier.

**Common routes to a case**, roughly cheapest-effort-first:
- Repurpose something: Pelican-style hard case, ammo can, vintage
  suitcase, old hardshell briefcase. Zero fabrication, very forgiving
  of a big board, and the classic cyberdeck look.
- Laser-cut acrylic or plywood panels (send a file to a service).
- 3D print (needs a printer or a print service; most published deck
  designs are printed and Pi-sized, so files will need adapting).
- Keyboard-first: mount everything to/behind the keyboard he already
  owns and let that be the chassis.

**Thermals will bite an enclosed build.** The Orin devkit has an
*active fan* and needs real airflow. Sealing it in a nice tidy box is
how you end up thermally throttled — which is exactly what
`nvpmodel -m 0` was set to avoid. Vents and fan clearance are design
inputs, not afterthoughts.

**Batteries are heavy and they dominate the weight budget.** A pack big
enough for a couple of hours will likely outweigh the board.

**Decks are iterative.** Nearly everyone builds a v1 that is ugly and
works, then a v2. Planning for v1 to be the final object is the usual
way people stall out.

**A tethered v1 is a legitimate, underrated move.** Mains-powered desk
unit first — screen, keyboard, audio, working — and battery later.
It removes the hardest problem from the critical path and gets him
talking to Shiro on her own screen far sooner. Worth pushing.

**r/cyberDeck** is the main community hub for reference builds.

---

## 5. The actual open questions

### 5a. Power — the hard one, discuss first

The Orin Nano devkit is not a Pi. It wants **19V via a barrel jack**
and draws up to ~25W in its top power mode.

- USB-C power banks deliver 5–20V over PD, so the usual answer is a
  **USB-C PD trigger board** set to 20V feeding the barrel jack.
  **Verify the Orin is happy at 20V** before buying.
- Rough runtime: a 20,000mAh / 74Wh bank at 25W is **~2.5–3 hours**,
  minus conversion losses. In the 15W mode, more like 4–5.
- `nvpmodel` mode is a real dial between runtime and speed. He does not
  have to run flat-out on battery.
- **Verify**: whether the devkit's own USB-C port can accept power
  input, which would be much tidier than the barrel jack if so.

### 5b. Screen — DisplayPort only, and it shapes the build

Ghost confirms: **DisplayPort out, no HDMI.**

To be clear what kind of problem this is: **a PORT problem, not a power
one.** The Orin is far stronger than the Pi most decks are built
around. But the Pi has HDMI, so the entire cheap portable-panel
ecosystem grew up around HDMI, and the Orin does not get to use it
directly. Being faster does not help.

**The trap:** a **passive** DP-to-HDMI adapter only works if the source
port is dual-mode (DP++). If it is not, a passive adapter produces *no
picture at all* — black screen, no error, looks like broken hardware.
An **active** adapter works either way for a few dollars more. Buying
active removes the variable entirely, and is the recommendation unless
someone confirms DP++.

**Verify**: whether the devkit's USB-C carries DisplayPort Alt Mode.
If it does, USB-C portable monitors open up and this gets easy.

Native-DisplayPort panels in small sizes exist but are rarer and
pricier. Size, resolution and touch are all still open.

### 5c. Audio out — she has a voice and nothing to speak through

**This is the highest value-per-dollar item on the list.** Piper
already works; there is simply no speaker. Bluetooth to the JBL failed.

Options worth weighing: a USB audio dongle plus a small powered
speaker, an I2S amp + speaker board, a small USB speaker, or another
run at Bluetooth. Likely $10–25.

Everything else on this list changes where she lives. **This changes
what she is** — a text box becomes a character with a voice.

### 5d. Mic in — buy it at the same time

Whisper (speech-to-text) is the next software feature, and it needs a
mic. Some USB dongles do input and output on one device, so choosing
audio-out without thinking about mic-in risks buying twice.

### 5e. Enclosure

Nothing decided. The devkit carrier is roughly 10×9cm plus fan and
heatsink, so "handheld" is optimistic — **"lunchbox" is more honest**,
and that is normal for this class of deck. **Verify** what mounting
holes the carrier board actually has before designing around it.

### 5f. Keyboard

He owns one. Spec unknown. Ask — size and interface (USB vs BT)
constrain the layout more than almost anything else.

---

## 6. Constraints that shape every answer

- **8GB is shared between EVERYTHING** — GPU and CPU both. Today:
  3B LLM + Piper. Whisper makes three. Vision would make four and
  probably will not fit. Sanity-check every "could she also…" idea
  against this ceiling.
- **Offline is the entire point.** Any suggestion needing an API call
  defeats the project.
- **He works from his phone most of the time.** Long typed commands and
  file paths are a dead end; favour things he can paste or tap.
- **~1 month into Python and hardware**, self-taught, fast. He had
  written no Python when this started and wrote the working action
  parser himself, on his phone. Do not condescend; do not assume he
  knows a given tool exists.
- **He changes direction.** In four days the target went hexapod →
  Hiwonder ROSpider → cyberdeck. Treat the deck as the current build,
  not necessarily the last.
- **Budget**: he was working to about $500 for a robot body; a ~$1100
  ROSpider is a "saving up" item. No stated deck budget — ask.
- **Prior hardware experience**: modding a Game Boy Advance, and this
  Jetson bring-up. He is not afraid of it, but soldering skill is
  unknown — worth asking before recommending I2S boards or anything
  needing a hot iron.

---

## 7. Settled — don't re-litigate

- **Offline only.** No cloud LLM, no API fallback.
- **Shiro is the main character.** Switching is trivial if that changes.
- **The hexapod robot is retired.** She controls no hardware. She is a
  resident AI you talk to. ROSpider is "someday potentially".
- **The deck's paint/finish stays undocumented** — he changes his mind
  and every doc naming a colour goes stale.
- Repo: `github.com/GhostMagi/YUZU`. The codebase keeps the name YUZU
  even though Shiro is the lead — it is a band keeping its first name.

---

## 8. Good opening questions

1. Budget and timeline for the deck?
2. Handheld, or desk/lunchbox? It changes everything downstream.
3. What keyboard, exactly — size and USB or Bluetooth?
4. Battery from the start, or **tethered v1** and battery later?
5. Can he solder, and does he want to?
6. **Audio first?** Cheapest thing on the list, biggest change in what
   she actually is.
