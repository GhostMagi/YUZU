# NEXT SESSION — YUZU, as of Sept 23 2026

**This file expires.** It is a snapshot of where the project is
standing RIGHT NOW, written so a fresh session can be useful in five
minutes instead of forty. **`CLAUDE.md` is the real record** — every
finding, every measurement, every thing that went wrong and why, is in
there, and where the two disagree, CLAUDE.md wins.

Do not grow this file. A second long doc that goes stale is the exact
fault this repo keeps deleting (`--show shiro_deck` sat wrong in a doc
for eleven days; a hardcoded cast in a doc is worse than one in a page,
because a page has a test). If something here is worth keeping, it
belongs in CLAUDE.md under a dated heading.

**`HANDOFF.md` is a different file for a different reader.** That one
is what GHOST pastes into a fresh DESIGN chat that has nothing —
product level, no engineering, no repo. This one is for a session that
already has CLAUDE.md in front of it. **His is stale** (rewritten
Sept 10; it still names Saya as the character and describes a cast of
five, which the Sept 20 cut ended). Worth offering to refresh it; do
not quietly rewrite it, because its audience is not you.

---

## Who you are working with

**Ghost.** He runs this project **from a phone** (Z Flip 6, Pydroid +
PocketPal), the deck's only shell is a **serial cable**, and he is
often doing this in the gaps of a polyphasic sleep schedule. His own
words, recorded: *"i dont understand this stuff much yet."* That is
vocabulary and spare attention, not capability — the record of this
project is mostly his findings.

So:

- **Give the command, not the explanation of the command.**
- **State the decision, then the reason, in one sentence.**
- **Never make him choose between options he has no basis to judge.**
  Pick the better one, say which, say why, move. He told me twice in
  one session that my two options *"sounded very similar"* — that was
  my phrasing, not his reading.
- **No new commands.** *"Plz dont add new commands i cant actually
  remember any except /wiki."* The cheapest command is the one he
  already types (`~/YUZU/pull`, `~/YUZU/deck`, `~/YUZU/face`).
- **Anything he has to type a path or an argument into is a dead end.**
  Give him text he can paste, or a no-argument script he can tap Run
  on.

---

## The state of the board today

    LIVE_PERSONA   four        (yuzu_personas.py — the MEASUREMENT pointer)
    FRONT          four        (yuzu_face.py     — who GREETS you)
    roster         Yuzu, Four  (Cait, Mimi, Saya are `retired: yes`)
    Four's prompt  5446 chars
    tests          734, ~95s,  `python YUZU_TESTER.py`
    tree           clean, pushed to main

**Context headroom is the number to know before you build anything
that rides on every turn:**

    num_ctx 8192 | history_turns 8   (yuzu_brain.py)
    num_predict 600                  (every persona's settings block)

    worst character (Four), facts store FULL, inventory at its cap:
    7991 of 8192 tokens.  201 SPARE.

That was 879 two sessions ago. Three features each took a slice — the
facts line, the deck inventory, the lookup example — and not one was
large on its own. **The next thing that rides on the system prompt is a
`num_ctx` decision before it is anything else**, and
`test_the_reply_ceiling_and_the_CONTEXT_agree` will say so out loud.
Going over is **silent**: nothing raises, tokens are dropped, and she
comes back having forgotten the start of the conversation.

---

## The working loop

1. Build it.
2. `python YUZU_TESTER.py` — 734 tests, ~19s on his board, ~95s here.
3. **Break-verify every new or changed test.** Break the thing it
   guards and watch it go red. A test that has not been broken is a
   test you are guessing about. Read the failure KIND: `errors=1` means
   it did not load; `failures=1` means it ran and disagreed.
4. **If it touches a page: render it at 1024x600 and LOOK.** ~32 times
   now, rendering has found what assertions could not. Re-check the ⌂
   exit at 412. Tooling:
   - chromium `/opt/pw-browsers/chromium`, node `/opt/node22/bin/node`,
     playwright-core under `/opt/node22/lib/node_modules/playwright/`
   - serve with
     `python3 -c "import yuzu_face; yuzu_face.serve(PORT,'127.0.0.1')"`
   - **never `pkill -f <script>`** — it matches the shell running it
     and kills your own compound command (exit 144). `setsid ... &`.
5. **Write the CLAUDE.md entry** — dated heading, what he asked in his
   own words, what was built, what went wrong, what is UNMEASURED.
6. Commit and push to **`main`**. No feature branches unless he asks.
7. **Shuffle runs go LAST, on an untouched tree.**
   `python3 YUZU_TESTER.py --shuffle 47`. A red seed gets
   **REPRODUCED in a clone** before it is explained — I gave a
   confident wrong cause twice in one session and wrote one of them
   into CLAUDE.md. The real bug was a test that only passed because the
   checkout is named `YUZU`.

**If her prompt changed, paste the full composed prompt into the chat
as a copy-paste block, without being asked.** He tests in PocketPal on
a phone, so a file path is useless to him.

    python yuzu_personas.py --show live

(`live` names the POINTER, never a key.)

---

## The rules that are not negotiable

- **`/launch/`, `/pull`, `/icons` take no arguments, ever.**
  The server binds 0.0.0.0. Allowlists of NAMES only; nothing from a
  request reaches a shell.
- **A destructive route gets no defaults.** `/forget` and
  `/unremember` refuse an empty name.
- **Every screen has a way out.** Two power cycles paid for that.
  `--start-fullscreen`, never `--kiosk`.
- **Absent rather than wrong.** A missing reading shows nothing; it
  never shows a guess.
- **The verdict goes first**, above the evidence.
- **Prompt REDUCES, code GUARANTEES.** Keep the code net under every
  prompt rule.
- **On this project a bracket means an ACTION**, and deck characters
  are never told brackets exist.
- **Tests must never write to his real `~/.yuzu/`.** The suite once
  shredded five real memory files.
- **Don't record the chassis paint scheme anywhere.** (Her liking hot
  pink is character and stays — the rule is about the CASE.)
- **Keep the `sudo nvpmodel -m 0` reminder** in the README above the
  fold, `yuzu_doctor.py`'s SUMMARY, and the robot's boot line. Tests
  pin all three.

## The findings that keep paying

- **Examples beat rules.** Measured six times: the bare command
  (yuzu4, 4/4), the warm statement, the technical question (markdown
  manual → two plain sentences, categorical), "good boy", the `User:`
  label, the lookup shape. **A turn shape she has never been shown is a
  turn shape the base model answers for her.** That is the single most
  reused lever here and it costs ~200 characters.
- **Pink elephant.** Naming a token in her prompt is how she learns to
  emit it — `[winks]` in 3 of 4 replies while named as forbidden, the
  asterisk ban that printed an asterisk, rule 5 recited back verbatim.
  Phrase restraint clauses POSITIVELY.
- **A check that cannot observe its own failure is not a check.** The
  oldest line in the file, and it gets broken in the round that quotes
  it roughly every other time.
- **A check that derives its threshold from the constant under test is
  not a check.** Two of my own tests passed their break-checks while
  measuring the number they were testing.
- **Grep-as-proxy**, ~14 instances. Assert on behaviour, not spelling;
  strip comments first — a comment explaining an absence reads as that
  thing being present.
- **Check what the layer BELOW actually received.** Stale processes,
  cached prompts, loopback binds, `gnome-extensions list` on a fresh
  install — every one reported healthy while broken.

---

## Standing reminders — bring these UP, don't wait to be asked

- **THE APT INSTALLS.** His exact words: *"we will do the apt installs
  when i wake just pls remind me about it when i come back."* The repo
  side is DONE. **The first thing to do is have him run
  `~/YUZU/deck --check` and read it** — it asks HIS board which systems
  it can play and prints the exact package beside anything missing.
  **Do not paste a package list from here**; a list typed into a doc
  goes stale against his actual Ubuntu, and an unverified specific
  stated as a step cost an hour on the 8BitDo. Two things already
  settled so they don't get re-litigated: **Game Boy Color needs
  nothing** (mGBA plays GB/GBC/GBA — folder only), and **PlayStation
  is OFF the list, his call Sept 23** (*"Too lazy to fw bios"*) —
  `deck --check` no longer offers it or makes a `psx` folder.
- **Offline maps.** *"the maps thing is a later thing as well remind me
  sometime."*
- **The right-angle adapters.** *"maybe remind me soon ill forget that
  bit."* The 5.5x2.5mm right-angle DC adapter is the one that matters —
  a barrel jack leaving a rigid metal case is pure leverage.

## Queued, in his own words

- **Multi-ZIM `/wiki` (#1)** — later, keep in mind. iFixit, WikiMed,
  WikiHow, Wikivoyage, Appropedia, Gutenberg are already on the board.
  The rank-and-extract code exists and is scoped to one book; widening
  it adds **no new command**, which makes it the cheapest big win.
- **Her answering from his own files (#13)** — someday, same machinery.
- **Whisper (#15)** — waiting, and the shape is decided:
  **push-to-talk, never a wake word.** *"like a walkie talkie."*
- **A power-mode tile (#20)** — he called it important. MAXN and quiet
  from a button. **Needs a sudo rule**, which is the one thing on this
  board that must be written carefully while the server binds 0.0.0.0:
  a fixed pair of modes, no argument from the request.
- **The D&D DM persona — PARKED, his call.** *"The DM thing can be put
  aside for now."* Thinking worth keeping: a 3B cannot hold rules, so
  dice/HP/inventory live in CODE and she only narrates what she is
  handed; solo-oracle rather than a party DM; the register risk is
  assistant collapse in a cloak.

## UNMEASURED — nobody has asked her yet

Everything from the last session is built, tested and unproven on the
real board:

- **She knows his name** (the `User:` label was teaching her to say
  "User" — 11 occurrences against 0 of "Ghost").
- **She knows she is offline**, and a derived test keeps that claim
  true (every URL in her turn path must be loopback).
- **She keeps what he tells her to** (`~/.yuzu/facts/`, FIFO, capped —
  `FACTS_BUDGET` 1200, `FACT_MAX` 200).
- **She offers, he picks.** She ends a reply with `REMEMBER: the thing`,
  the code lifts it out before anything sees it, and it appears as a
  chip he taps. Two per reply at most. **The confirm step is what makes
  it safe** — assume she over-offers, because that is measured three
  times.
- **She knows what is on the board with her** — archives and ROM
  counts, read live, cached 120s, capped at 400 chars.
- **She has a shape for a lookup** — one example, because handed 700
  characters of encyclopedia with no demonstration she answered
  *"I'm not going to try to summarize this information again."*

The round that decides any of these is the next time he talks to her.

---

## Two more things worth knowing

- **The 8BitDo never worked.** CLAUDE.md was wrong about that from
  Sept 9 until he corrected it: the kernel seeing the pad was real, a
  working controller in a game was never confirmed. That matters
  because **gamepad navigation of the deck's pages (#12) was costed as
  free on the assumption the pad works.**
- **The laptop is the eval machine** (Acer VN7-592G, Ubuntu 22.04.5,
  GTX 960M). It only boots from **F12 → entry 3 `ubuntu`** (locked
  NVRAM). A Bluetooth keyboard is paired to it now and typing is
  normal; the built-in keyboard is still missing **k, l, m, Enter and
  up-arrow**, so if the BT one is flat: numpad Enter works, `Ctrl+P` is
  up-arrow in a terminal, and Tab completion covers the dead letters.
