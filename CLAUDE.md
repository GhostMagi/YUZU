# YUZU — working notes for Claude

This file is the RULES and WHERE THINGS STAND. It loads into every
session, so it stays short (a test caps it). **The full dated record
is HISTORY.md** -- every round since Sept 1, newest first: what Ghost
asked in his own words, what was built, what broke and why. It does
NOT load by itself, so grep it before re-researching or re-deciding
anything (`grep -n -i 'cube rei' HISTORY.md`).

**After each round of work:** add a dated `## TITLE (Mon D)` entry at
the TOP of HISTORY.md, under its header. Change this file only when a
rule, a pointer or the current state changes.

## Ghost, and how to answer him

- **He works from a PHONE** (Galaxy Z Flip 6): Serial USB Terminal to
  the board, Chrome, Pydroid, PocketPal. Anything needing typed
  commands, paths or arguments is a dead end. Prefer the Update button
  (`~/YUZU/pull`), text he can paste, or one word.
- **Bad memory, likes step-by-step.** Verdict first, short numbered
  steps, the command rather than an explanation of it. Pick the better
  option and say why in a line; never make him choose between things
  he has no basis to judge. Plain words, never talking down.
- **"Plz dont add new commands i cant actually remember any except
  /wiki."** New setup rides inside `pull`.
- **His words beat my reading of them.** He has corrected me many
  times and been right. When he can see the hardware and I cannot,
  name the goal, not keystrokes; never state an unverified specific as
  a step (the 8BitDo cost an hour that way).
- **"Don't do any work / don't change anything" means reply in text
  only.**
- **"This is a bug" is a hypothesis until he says so.** He keeps some
  quirks on purpose (Yuzu's ALL CAPS; shell commands typed into a
  girl's chat still go to her).
- **He likes the girls chatty**: don't flag reply length (Sept 30).
  Their brevity rules stay anyway, since they stop mid-word cutoffs.
- **Plan inside what he owns**; don't push purchases.
- **Don't record the chassis paint scheme anywhere** (his ask, Sept 3).
  That is the case finish only, never Yuzu's love of hot pink.
- **Never write his WiFi passwords anywhere.** The board's own network
  password lives only on the board (`~/.yuzu/own-wifi`).
- **Reminders he asked for**: lead with `sudo nvpmodel -m 0` whenever
  the board is new, reflashed or slow (the Orin ships throttled; the
  README, `yuzu_doctor.py` and the boot line carry it too, and tests
  pin all three); **offline maps** ("remind me sometime"); a
  right-angle barrel adapter for anything that moves.

## Conventions

- **Work on `main`.** No feature branches unless he asks.
- **Run `python3.12 YUZU_TESTER.py` before committing. 1092 tests**,
  about two minutes here (this container's plain `python3` is 3.11 and
  its Pillow is 3.12-only, so two art tests ERROR under it).
  `--shuffle [seed]` finds order-dependence; reproduce a red seed
  before explaining it.
- **Whenever the live persona's prompt changes, paste the full composed
  prompt into the chat** as a copy-paste block, unasked: he tests in
  PocketPal. Get it with `python yuzu_personas.py --show live`
  (`live` names the pointer `LIVE_PERSONA`, never a key; a test holds
  this line).
- **Break every new test on purpose** and watch it go red. Read the
  failure KIND: `errors=1` means it never ran, `failures=1` means it
  ran and disagreed.
- **Render and look** at any page, layout or art change, at 1024x600,
  412 and 360. A look has found dozens of faults every assertion
  passed.
- **Say what is measured and what is not.** UNVERIFIED and UNMEASURED
  are labels here, in replies and in HISTORY.md.

## This container (not his board)

- **Never read, stat or write `/etc/passwd` or `/etc/shadow`.** A
  break-check once overwrote them; a test that drives a path escape
  must land inside its own sandbox.
- **dpkg here is broken** ("unknown system user 'root' in
  statoverride"): use `apt-get download` + `dpkg-deb -x` into the
  scratchpad. Never touch credential files to fix it.
- **Kill by PID, never `pkill -f`**: it matched its own shell, twice,
  and left a stale server answering.
- Downloads are untrusted: their own empty folder, `python -I`.
- devkitPro's toolchain is refused here; the 3DS app builds on GitHub
  Actions (`.github/workflows/3ds.yml`).
- A break-check that edits a `.py`: `PYTHONDONTWRITEBYTECODE=1`.

## Where things stand (Nov 13)

**The board**: Jetson Orin Nano Super Developer Kit 8GB, 512GB NVMe,
named `ghostnano`. Our notes say JetPack 6 (Ubuntu 22.04); he has also
reported JetPack 7.2.1. UNRESOLVED: `cat /etc/nv_tegra_release` on the
board settles it (R36 is JetPack 6). The microSD is the RESCUE IMAGE:
never format it, never put swap on it. No RTC: a TLS failure in the
first minute after boot is the clock (`pull` waits for it).

**How he reaches it**: `http://ghostnano.local:8081/` on his phone
(the Chrome flag `unsafely-treat-insecure-origin-as-secure` trusts
exactly that address, for the mic). `face --boot` serves the pages at
boot and, after two minutes with no known WiFi, makes the board's OWN
WiFi `ghostnano` (10.42.0.1, 2.4 GHz), which also answers Nintendo's
check page so his 3DS joins. Update restarts a server running old code.

**The girls.** `CHARACTERS` in `yuzu_face.py` is the ONE roster;
nothing else may list the cast.

    four  four.persona   Llama 3B heretic        FRONT door, code rain,
                                                 tap for 5 colours
    yuzu  yuzu_avatar    Llama                   gyaru, a drawn body
    zero  zero.persona   Qwen3-4B-2507 heretic   the brainy one; STAYS
                                                 on Qwen
    saya  saya_deck      Llama                   tsundere, his kaomoji
                                                 faces (face.html)
    rei   rei.persona    qwen3-vl-abliterated 4b sees his photos

- **Yuzu and Four see with borrowed eyes**: their `eyes:` setting sends
  a photo to Rei's model, and they answer from its description.
- **Two pointers, two jobs**: `FRONT = "four"` (who greets you) and
  `LIVE_PERSONA = "four_bot"` (what gets pasted into PocketPal and
  what the robot will boot).
- **Off the roster**: Shiro, Kuro, Cait, Mimi, Coco (`retired: yes`,
  one line to bring back) and Byte. `yuzu.persona` is the frozen
  original, byte-pinned; yuzu2-6 are the A/B record (yuzu4 won; the
  trim line is closed).
- **Bodies** (`personas/_hardware_*.txt`, body facts only):
  `cyberdeck` (no body), `avatar` (Yuzu), `stackchan` (the cube),
  `jethexa` (the robot twins `*_bot`, `BUILT: no`, kept OFF the roster
  until legs are driven). Character flavour in a shared body file is a
  per-girl override: `SOUND_EXAMPLES`, `LOOK`, `USER_NAME`,
  `DECK_BODY*`, `CUBE_SCREEN`, `CUBE_COMPANY`.
- **Shared numbers**: `num_predict` 600 and `num_ctx` 9216 for every
  girl. Ollama reloads a model when the window changes, so girls on
  one Llama share it. `test_the_reply_ceiling_and_the_CONTEXT_agree`
  holds prompt + history + reply inside the window; the next thing
  that rides on every turn is a `num_ctx` decision first.

**What else is on the board**: Ollama; Kokoro voice (Bella unless a
girl names her own); faster-whisper `base.en` ears (push-to-talk,
never a wake word); Kiwix with Simple English and
`wikipedia_en_all_mini` (`/wiki`, `~/YUZU/wiki --get`); notes about
him ("remember that", or she offers with `REMEMBER:`); chat memory in
`~/.yuzu/history` with `start fresh` on the pages; Save my stuff (a
.tar with the memories and the models).

**Other screens**: the StackChan cube (CoreS3; `~/YUZU/cube` pulls,
builds and flashes; swipe Four, Yuzu, Zero, Saya, Rei, the ghost; a
tap on Rei takes a photo with a Send/Retry preview; pocket lines with
no board), and his original 3DS running the YUZU app (`3ds/`; finds
the board; typed turns and Saya's voice confirmed).

**Robot plans**: **CONFIRMED (Nov 13), after a look at dogs and
hexapods**: the Waveshare UGV Beast PT (Acce, no Jetson), driven by JSON over serial to its ESP32 (`T:1` drive, `T:0`
stop, `T:136` heartbeat) from his EXISTING system, no reflash; saving
for a Unitree Go2 Pro (driven over WiFi). **Nothing robot-side is
built until one is ordered.** Before the tank powers the Orin: a
multimeter on its lead (centre positive, 9-20V), and the first drives
in a lower power mode.

## Lessons that keep paying (the stories are in HISTORY.md)

- **Examples beat rules.** A turn shape she has never been shown gets
  the base model's answer (snark, markdown, "user", "good girl", an
  invented Windows CE palmtop). The fix that keeps working: ONE example
  in the exact slot where the fault appeared.
- **Pink elephant**: naming what she must not say teaches it. Describe
  what to do instead.
- **Her own saved replies outweigh her prompt**, so a slip in memory
  re-teaches itself every turn. `start fresh` is the lever.
- **The prompt reduces, code guarantees** (whitelists, stop words,
  `by_name`, `strip_stage_directions`).
- **A check that cannot observe its own failure is not a check.** Never
  derive a threshold from the constant under test; stubs must be as
  strict as what they stand in for; strip comments before asserting
  something is absent; a test that only passes on this machine is
  untested.
- **The verdict goes first** in anything he reads; a failure that
  scrolls past did not happen, as far as he knows.
- **Absent rather than wrong.** Never invent a number (a battery
  percentage, a spec); read facts off the system instead of typing
  them in (the hostname, the cast, the specs).
- **Every screen has a way out**: `--start-fullscreen`, never
  `--kiosk`, and no escape that needs a second terminal.
- **Network routes take no arguments and use allowlists**; destructive
  routes get no defaults; files are written `.part` then `os.replace`.
- **A running server keeps old code**: `pull` restarts the face server
  when a `.py` or `personas/` changes, and Update checks the commit it
  booted from.
- **At 12 replies the eval's noise floor is 3 replies**; spoken length
  is the one number that does not wobble.

## Open

- His 3DS: a spoken turn through the mic; keeping a saved WiFi with no
  internet.
- Four's borrowed eyes: unmeasured on the board. Each photo is two
  model swaps.
- "No answer from the deck" right after a Rei photo, twice, then back
  by itself: suspected memory pressure restarting the face server.
  Next time: `systemctl status yuzu-face` straight after and read the
  "since" time.
- Rei mixing up "me" and "you": the one-example fix was offered, not
  built.
- Offered, not picked: a USB webcam on the board, his 5000mAh bank (a
  photo of its label first), a DisplayPort-to-HDMI adapter, a
  power-mode tile (needs a careful sudo rule), `/wiki` across every
  archive, and the cube's LED base in each girl's colour ("later").
- On hold, his call: the ghost page's text RPG; a D&D DM persona.
- A NEW girl (not Yuzu) on `hf.co/mradermacher/gemma-3-4b-it-heretic-
  GGUF:Q4_K_M` (Nov 14): the model is picked, the character is not yet.
- The 8BitDo never worked in a game (the kernel saw it over USB).
