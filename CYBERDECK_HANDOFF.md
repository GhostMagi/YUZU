# YUZU cyberdeck — handoff for idea/design discussion

**Paste this whole file into a fresh Claude chat.** It exists so the
build/hardware/capability conversation happens somewhere other than
Claude Code, which is being saved for actually writing the software.

**Your job in that chat: ideas, sourcing, tradeoffs, feasibility,
"what could she do".** Not writing code. Code goes back to Claude Code
with a summary of whatever gets decided.

---

## What this is

Ghost is building a **handheld cyberdeck** whose whole point is a
fully-offline AI character living on it. No cloud, ever.

The character is **Shiro** — yami kawaii, sweet sing-song surface,
genuinely unsettling underneath. There are four others (Yuzu the gyaru,
Coco the kuudere, Byte the netrunner, Saya the tsundere) and switching
is one config line.

The software already works. The deck itself does not exist yet — that
is the conversation.

---

## Hardware IN HAND, confirmed working

| thing | state |
|---|---|
| **Jetson Orin Nano Super devkit, 8GB** | flashed, running Ubuntu, unthrottled (`nvpmodel -m 0` + `jetson_clocks`), 16GB swap |
| **512GB NVMe SSD** | installed, cloned, booting from it, microSD removed |
| **A keyboard** | he owns one, spec not yet stated — ask |
| Z Flip 6 phone | his main terminal, via USB serial + a serial terminal app |
| Steam Deck | works as a serial console too |
| Acer Aspire VN7-592G laptop | Ubuntu 22.04, second console, the eval machine |
| JBL Go 3 bluetooth speaker | **Bluetooth pairing to the Jetson FAILED**, abandoned for now |
| 64GB SanDisk USB-A (130MB/s), 2× microSD | spare |

Three independent consoles into the board already exist (phone, Steam
Deck, laptop) plus `ssh ghost@192.168.55.1` over USB networking. WiFi
is connected and auto-reconnects.

---

## Software state — DO NOT REDESIGN THIS

Working today, on the actual board:

- **Local LLM**: Llama-3.2-3B (heretic-abliterated, Q4_K_M) via Ollama
- **Five personas**, swappable, Shiro is live
- **Piper TTS** — the code works; there is no speaker attached to hear it
- **301 automated tests**, ~2 min on the board
- Ollama tuned for 8GB shared memory (single model, single parallel
  slot, flash attention, q8_0 KV cache, model kept resident)
- Whole project is Python **standard library only**, except Piper

**Known gaps in software:** the mic (Whisper) is a stub and unbuilt.
Nothing about vision exists.

---

## THE ACTUAL DISCUSSION — what the deck needs that he doesn't have

**1. Power. This is the hard one and it should be discussed first.**

The Orin Nano devkit is not a Raspberry Pi. It wants **19V via a barrel
jack**, and draws up to ~25W in its top power mode. So:

- USB-C power banks output 5–20V over PD, so the usual cyberdeck answer
  is a **USB-C PD trigger board** set to 20V (or 19V if available) into
  the barrel jack. Worth confirming the Orin tolerates 20V.
- Rough runtime maths: a 20,000mAh / 74Wh bank at 25W is **~2.5–3
  hours**, less conversion losses. At the 15W mode, more like 4–5.
- Whether he wants it to run unthrottled on battery is a real choice —
  `nvpmodel` mode is the dial between runtime and speed.

**2. Screen — DisplayPort only, and that shapes the build.**
Ghost confirms the Orin Nano Super devkit is **DisplayPort out, no
HDMI.**

To be clear about what kind of problem this is: it is a PORT problem,
not a power one. The Orin is far stronger than the Raspberry Pi most
cyberdecks are built around. But the Pi has HDMI, so the whole cheap
portable-panel ecosystem grew up around HDMI, and the Orin does not get
to use it directly. Being faster does not help.

The trap to check before buying: a **passive** DP-to-HDMI adapter only
works if the source is dual-mode (DP++). If the Orin's port is not
DP++, a passive adapter gives no picture at all and reads as a dead
screen. An **active** adapter works either way for a few dollars more —
buying active removes the variable entirely.

Also worth checking rather than assuming: whether the devkit's USB-C
port carries DisplayPort Alt Mode. If it does, USB-C portable monitors
open up and this gets easy. If it is data/flashing only, they are out.

Native-DisplayPort panels in small sizes exist but are rarer and dearer.
Size, resolution and touch all still open.

**3. Audio out — she has a voice and nothing to speak through.**
This is arguably the highest-value missing piece, because the TTS
already works. Bluetooth to the JBL failed. Options worth discussing:
a USB audio dongle + small speaker, an I2S amp+speaker, or retrying
Bluetooth. Cheap and it makes her real.

**4. Mic in.** Needed later for Whisper. Might as well be chosen at the
same time as audio out — some USB dongles do both.

**5. Enclosure.** Nothing decided. The Orin devkit carrier is roughly
10×9cm plus a fan and a heatsink, so "handheld" is optimistic —
"lunchbox" is more honest. Thermals matter; it has an active fan and
needs airflow.

**6. Keyboard mounting** — he has a keyboard, spec unknown.

---

## Constraints that shape every answer

- **8GB is shared between everything.** Today: the 3B LLM + Piper.
  Adding Whisper makes three. Vision would make four and probably will
  not fit. Any "could she also…" idea should be checked against this.
- **Offline is the point.** Suggestions requiring an API call defeat
  the project.
- **He works from his phone most of the time.** Long typed commands and
  file paths are a dead end; he wants things he can paste or tap.
- **He is about a month into Python and hardware**, self-taught, and
  moving fast. He had never written a line of Python when this started
  and wrote the working action parser himself. Explain the *why*, don't
  dumb things down, don't assume prior knowledge of a tool.
- **He is decisive but changes direction.** In four days the target
  went hexapod → Hiwonder ROSpider → cyberdeck. Treat the cyberdeck as
  the current build, not necessarily the last one.
- Budget: he was working to about **$500** for a robot body, and a
  ~$1100 ROSpider is a "saving up for it" item. No stated cyberdeck
  budget — worth asking.

---

## Settled — don't re-litigate

- **Offline only.** No cloud LLM.
- **Shiro is the main character.** Switching is trivial if that changes.
- **The hexapod robot is retired.** ROSpider is "someday potentially".
  She controls no hardware — she is a resident AI you talk to.
- **The chassis/deck paint scheme stays undocumented** — he changes his
  mind and every doc naming a colour goes stale.
- The repo is `github.com/GhostMagi/YUZU`, and the codebase keeps the
  name YUZU even though Shiro is the lead.

---

## Good opening questions for him

1. What's the budget and the timeline for the deck?
2. Handheld, or desk/lunchbox sized? That changes everything downstream.
3. What is the keyboard, exactly?
4. Does he want it battery-powered at all, or mains-first for v1?
5. **Audio first?** It is cheap, it is the biggest missing capability,
   and it turns a text box into a character with a voice.
