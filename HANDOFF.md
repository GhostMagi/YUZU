# YUZU — paste this into a fresh chat

Rewritten Sept 10. This is the catch-up for a DESIGN conversation: what
the thing is, what already exists, and what is actually open. The full
engineering record is `CLAUDE.md` (very long, do not paste that).

---

## What I'm building

A **handheld cyberdeck** whose whole purpose is one AI character living
on it, fully offline. Not a robot — it controls nothing.

- **NVIDIA Jetson Orin Nano Super devkit**, 8GB shared CPU/GPU, 512GB NVMe
- **Llama 3.2 3B** (heretic-abliterated, Q4_K_M) via Ollama, on the board
- **Saya** — tsundere character. Four others exist and are one line away
- **Piper** for her voice, offline. Mic/speech-in not built yet
- **Offline Wikipedia** (Kiwix, Simple English, 982MB) she can read from
- Also a real Ubuntu ARM64 computer, and plays Game Boy games

**Everything works today.** She talks, has a face with expressions, reads
the encyclopedia, plays games. It is not a plan, it is running.

## The constraints — these decide most design answers

1. **Offline is the point.** No cloud model, no CDN, no web fonts, no
   library fetched at runtime. It must work with WiFi off.
2. **10.1" 1024x600 touchscreen** in the lid. Not bought yet, ~2 weeks out.
   Everything is designed for that resolution already.
3. **Touch-first, often no keyboard.** A Bluetooth keyboard exists but
   will not always be attached.
4. **Right now my only interface is a USB serial terminal on my phone**
   (Samsung Z Flip 6). One session. No SSH, no second window, no easy
   Ctrl-C. This has caused real problems — see the rules below.
5. **8GB shared.** She costs ~3GB resident; ~3.4GB stays free. Measured.
6. **Python stdlib only** for anything that runs on the deck. Piper is the
   one exception. This is deliberate: it keeps things runnable anywhere.

## What already exists (don't re-suggest these)

**Her face** — a web page served locally, opened in a browser or on the
phone. Nine hand-drawn expressions as transparent PNGs (idle, blink,
talking, thinking, mad, cry, smug, wink, woahshock). Black line art on a
colour I can change; the background shows through her eyes.

- She **blinks** on her own, and **breathes**
- The face **reacts to what she is doing**: idle → thinking while she
  generates → talking when words start. Driven by the brain, not by me
- I can **type to her right on that page** and her reply appears under
  her face
- Four background colours only: hot pink, cyan, neon green, lavender

**A home screen** — 2x2 tiles: Saya, Talk, Wikipedia, Game Boy. A clock
that says when the board hasn't reached the network. Her face has a ⌂
that goes there. It can boot straight into it.

**One-word commands**, because typing paths on a phone is a dead end:

    ~/YUZU/pull      update, and say plainly whether it worked
    ~/YUZU/face      serve her face
    ~/YUZU/deck      get ready for the screen; --check for an inventory
    ~/YUZU/wiki      offline Wikipedia; --test says why a lookup missed
    ~/YUZU/gba       play the newest ROM
    ~/YUZU/tile      auto-tiling windows
    drop.py          send a file from my phone to the board

**Art pipeline** — I draw/crop a face, drop the file in `ui/raw/`, run
one command, and it becomes a sprite: white background removed, squared,
mouth coloured. The filename becomes the expression name.

**446 tests** covering all of it, run in one command.

## Hard-won rules — please respect these in any design idea

These were each paid for. They are not preferences.

1. **Never build something I can get trapped in.** A chat loop with no
   exit once cost me two power cycles of the board. On a touchscreen with
   no keyboard, a UI I can't leave is worse than a terminal.
2. **The verdict goes first.** Any status output must lead with the
   answer, not the evidence. I have read working things as broken three
   separate times because an alarming line sat above the good news.
3. **Never suggest a fix that needs hardware I don't have.** "Open a
   second terminal", "press Alt+F2", "click Refresh" — all were correct
   and all were useless to me.
4. **A tap that appears to do nothing reads as a broken deck.** Anything
   touched must say what it's doing.
5. **Render it and look.** Five separate visual bugs passed every
   automated test and were only caught by looking at a screenshot.
6. **She is a character, not an assistant.** The biggest risk on this
   build is her collapsing into ChatGPT-with-a-name — markdown headings,
   numbered lists, code fences. It has happened once and was measured.

## Not built, on purpose

- **The `ghost` passcode / lock screen.** I want it as flair (the case
  will have a real key lock; the passcode is not security). Held because
  a lock screen needs typing, and an on-screen keypad is exactly the kind
  of thing that traps me if it's buggy. Needs designing around always
  being escapable.
- **Speech in (Whisper).** The last real stub. There is memory room for
  it. Not started.
- **A nicer voice (Kokoro TTS).** Would sound human instead of robotic.
  Held because it needs PyTorch, which breaks the installs-nothing rule.
- **An `asleep` face.** No art for it yet, so no idle/screensaver state.

## Where I actually want design help

1. **What should the deck DO when I'm not talking to her?** Right now it
   sits on one face. Idle behaviour, an ambient state, something that
   makes it feel alive on a desk — this is wide open.
2. **The lock/wake screen**, designed so it can never trap me.
3. **How she should look while thinking vs talking** beyond swapping a
   sprite — timing, motion, anything that isn't a spinner.
4. **What belongs on the home screen** when there are more than four
   things. And whether the clock earns its space.
5. **Physical layout.** 17.3" x 12.4" x 4.3" aluminium case, 10" keyboard
   and 10" panel side by side, board in a metal enclosure. Cable routing,
   what faces the user, where the speaker goes.
6. **Anything about her as a character** — how she should behave when
   idle, what she should notice, what would make her feel like she lives
   there rather than runs there.

## Please don't suggest

- Anything needing internet at runtime (CDN, web fonts, cloud API, Rive/
  Lottie pulled from a host)
- x86-only software — this is ARM64
- Anything assuming a mouse, a second monitor, or a spare terminal
- Rewriting what already works. I'd rather add than replace.

## How to answer me

I don't have a strong technical background yet and I'm running this from
a phone. Give me the decision and one line of reasoning, not a menu of
options I have no basis to choose between. Plain language. I take in a
lot when it's written clearly — the gap is vocabulary and spare time,
not capability.
