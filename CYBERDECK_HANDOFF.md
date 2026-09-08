# YUZU cyberdeck — handoff v2 (Sept 9)

**Paste this into a fresh Claude chat.** It exists so build/hardware
talk happens somewhere other than Claude Code, which is reserved for
writing the software.

**Your job: ideas, sourcing, tradeoffs, feasibility.** Not code.
Decisions come back to Claude Code as a summary.

**The live question right now is THE CASE.** Everything else is either
decided or bought. Skip to §4 if you want the actual task.

---

## 1. What this is

Ghost is building a **cyberdeck** — a handmade portable computer —
whose entire purpose is a **fully offline AI character living on it**.
No cloud, ever.

The character is **Shiro**: yami kawaii, sweet sing-song surface,
genuinely unsettling underneath. She runs today on the real board, with
a local LLM and working text-to-speech. Four other characters exist and
switching is one config line.

**He saw his first cyberdeck two days ago.** Sharp, learns fast, but
assume no prior exposure to the hobby's conventions or vendors.
Explain the *why*; don't dumb it down.

---

## 2. Hardware — OWNED vs PLANNED

**OWNED and working right now:**
- **Jetson Orin Nano Super devkit, 8GB** — flashed, Ubuntu, unthrottled,
  16GB swap, running the LLM and TTS today
- **512GB NVMe SSD** — installed, booting from it
- **Arteck Bluetooth keyboard** — confirmed, this is the real one

**SELECTED but NOT BOUGHT (~20 days out, may hustle sooner):**
- Power: Xiwai USB-C PD 65W trigger → 5.5×2.5mm barrel, centre positive;
  JSAUX 20,000mAh 65W PD bank
- Display: 7" 1024×600 IPS capacitive touch, HDMI in, USB 5V power;
  BENFEI **passive** DisplayPort→HDMI adapter
- Audio: USB sound card (Waveshare-compatible) doing **mic in AND
  amplified speaker out** on one JST header, driver-free; Waveshare
  8Ω 5W dual-driver speaker, **no soldering**

~$147 planned against a ~$300–350 allotment. **Plus ~$50 for the case**,
which is new budget he's willing to spend.

Resolved and not worth re-raising: the Orin devkit is **DisplayPort
out, no HDMI**, and NVIDIA's docs confirm it drives both active and
passive DP→HDMI adapters, so the cheap passive one is fine.

---

## 3. Form factor — DECIDED

He was shown two options and picked deliberately:

- **A. Case-that-closes** ✅ **CHOSEN.** Everything lives inside a rugged
  case. Open it, use it, close it. Screen mounts in the lid or props up.
- B. Clamshell laptop-style hinge — rejected for now. Can't be bought
  premade; it's a hinge you fabricate. Possible v2 or v3.

He wants it to **latch shut, ideally lockable.**

---

## 4. THE ACTUAL TASK: pick a Pelican-style case, ~$50

**Direction is settled: plastic Pelican-style hard case with pluck
foam.** Help him choose a specific one and get the sizing right.

**Why this class:** hinged, latching, sturdy, usually weather-sealed,
and the **pluck foam is the real feature** — he lays parts out, plucks
the cubes, and can redo the layout three times with zero fabrication.
Vendors worth comparing: Apache (Harbor Freight), Monoprice, Nanuk
clones, Casematix, Pelican's own cheaper lines.

Search terms that matter: **"padlock hasps"** if he wants it lockable,
and **interior dimensions** — never the marketing size, which is always
the exterior.

**A REAL TRAP, worth stating plainly:** don't go full metal. An
all-metal enclosure is a Faraday cage, and his keyboard is **Bluetooth**
while the board needs **WiFi**. Lid-open in use it matters much less,
but a sealed metal box around the board will attenuate both. Ammo cans
look incredible and are exactly this trap. Plastic Pelican-style
sidesteps it entirely; if he falls for a metal case, budget an
external antenna.

**Three measurements he needs before buying anything.** The binding
dimension is almost certainly the KEYBOARD, not the board:

1. **Arteck keyboard** — length × width
2. **Orin devkit height WITH the fan and heatsink on** — the fan makes
   it tall, and depth is what kills shallow cases
3. **7" panel outer dimensions with bezel** — not the 7" diagonal

Add slack, shop to interior dimensions. He has not taken these yet —
**ask him for them, don't estimate.**

**Worth asking him:** does it need to RUN while closed? If yes, power
has to get in through a drilled pass-through or cable gland, which
changes the pick. The assumption so far is closed = transport, open =
use, so probably no — but confirm rather than assume.

---

## 5. Constraints that shape every answer

- **8GB is shared between EVERYTHING**, GPU and CPU both. Today: the 3B
  LLM + Piper TTS. Whisper makes three. Vision would make four and
  probably will not fit. Sanity-check every "could she also…" idea.
- **Offline is the entire point.** Any suggestion needing an API call
  defeats the project.
- **He works from his phone most of the time** — favour things he can
  paste or tap over long typed commands.
- **~1 month into Python and hardware**, self-taught, fast. He'd written
  no Python when this started and wrote the working action parser
  himself, on his phone. Don't condescend; don't assume he knows a
  given tool exists.
- **Prior hardware experience**: modding a Game Boy Advance, and the
  Jetson bring-up. Soldering skill unknown — **ask** before suggesting
  anything needing an iron. (The chosen audio parts deliberately need
  none.)
- **He changes direction, and says so.** In five days: hexapod →
  Hiwonder ROSpider → cyberdeck. Treat the deck as current, not final.
- **Decks are iterative.** v1 should be ugly and working. Planning for
  v1 to be the final object is how people stall out.
- **Thermals**: the devkit has an *active fan* and needs airflow.
  Sealing it in a tidy box undoes the unthrottling that was set up
  deliberately. Vents and fan clearance are design inputs.

---

## 6. Settled — don't re-litigate

- **Offline only.** No cloud LLM, no API fallback.
- **Shiro is the main character.** Switching is trivial if that changes.
- The hexapod robot is **retired**. She controls no hardware — she is a
  resident AI you talk to.
- **Case = Option A, Pelican-style, latching, ~$50.**
- The deck's paint/finish stays undocumented — he changes his mind and
  every doc naming a colour goes stale.
- Repo: `github.com/GhostMagi/YUZU`. The codebase keeps the name YUZU
  even though Shiro is the lead — a band keeping its first name.
