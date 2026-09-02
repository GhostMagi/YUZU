# Yuzu-Spider-V1 — working notes for Claude

## Conventions

- **Work on `main`.** No feature branches unless Ghost asks.
- **Whenever Yuzu's prompt changes, paste the full composed prompt into
  the chat as a copy-paste block**, without being asked. Ghost tests in
  PocketPal on a phone, so a file path or a command is useless to him —
  he needs the text itself. Get it with:
      python yuzu_personas.py --show yuzu2
- **Ghost works from a phone** (Z Flip 6, Pydroid + PocketPal). Anything
  requiring typed commands, file paths, or arguments is a dead end.
  Prefer: text he can paste, or a no-argument script he can tap Run on.
- Run `python test_yuzu.py` before committing. 154 tests, ~9 seconds.

**Ghost has to remember `sudo nvpmodel -m 0`.** The Orin ships
throttled and forgetting it makes everything slow with no visible cause.
He asked to be reminded, and a chat reminder dies with the session, so
it lives in three places he actually lands: the README above the fold,
`yuzu_doctor.py`'s SUMMARY, and the robot's own boot line — the last two
gated on Jetson detection so they stay quiet on the phone. Tests pin all
three. If you touch any of them, keep the reminder.

**The laptop works now and it is the eval machine.** Acer Aspire
VN7-592G, Ubuntu 22.04.5, i7-6700HQ, 16GB, GTX 960M, heretic GGUF pulled
via `ollama pull hf.co/mradermacher/Llama-3.2-3B-Instruct-heretic-ablitered-uncensored-GGUF:Q4_K_M`
(that repo path is confirmed working). 154 tests pass on it. Getting it
to boot took a night and the whole story is in UBUNTU_LAPTOP.md —
**locked NVRAM**, so it only boots via a firmware-registered trusted
file, and only from **F12 → entry 3 `ubuntu`**. Its keyboard has no
**k, l, m, Enter or up-arrow**; numpad Enter works, `Ctrl+P` is up-arrow
in a terminal, and Tab completion covers the dead letters.

## Prompt work

`personas/yuzu.persona` is the ORIGINAL, extensively tested by Ghost.
Do not edit it — a test asserts it stays byte-identical to
`personas/_golden_yuzu_v1.txt`. Iterate on `personas/yuzu2.persona`.

Ghost's method is A/B testing in PocketPal and sending screenshots.
It works. Score them against the real parser rather than eyeballing —
`yuzu_all_in_one.lookup_actions()` is the ground truth for whether a
bracketed action would actually move the robot.

Measured so far: v1 20% action hit rate → v2 78–83%.

`personas/coco.persona` (kuudere) is built on v2's structure and carries
its fixes. First live round (9 replies, Sept 1): **11/11 actions ran**,
has_dialogue 89% — one all-actions freeze, which was the predicted #1
risk for the archetype. Small sample; treat it as promising, not proven.

**FIRST MACHINE-SCORED RUN — Sept 2, on Ghost's own laptop.** Not
PocketPal screenshots: `yuzu_prompt_eval.py --persona yuzu2`, 36 replies,
heretic-abliterated Q4_K_M via Ollama on a GTX 960M.

    moves_at_all      80.6%   <- the number that matters
    has_dialogue      94.4%
    one_per_bracket   94.4%
    brackets_balanced 97.2%
    not_an_assistant  100%
    no_puppeteering   100%
    actions_runnable  55.6%   <- see below, misleading
    no_asterisks      52.8%   <- see below, misleading
    spoken length     26w avg (brevity rule holding)

Two reasons this is NOT comparable to the 91% from the PocketPal round,
and both matter:

1. **The eval is harsher.** It calls `brain.reset()` before every prompt,
   so each of the 36 turns is cold. In a real chat Ghost's own earlier
   bracketed replies accumulate and act as extra examples — the format
   reinforces itself. This measures the prompt standing alone.
2. **`no_asterisks` and `actions_runnable` overstate the damage.**
   `normalize_actions` rescues `*shakes legs*` → `[shakes legs]` → runs.
   Only impossible actions actually fail, and `actions_runnable` is an
   `all()`, so a single `*wink*` fails a reply where three real moves
   ran. `moves_at_all` is the honest robot-facing number.

**OPEN LEAD, not yet tested: the asterisk rule is written in asterisks.**
`_hardware_muto_s2.txt` line 31 says *"Never write a movement between
\*asterisks\*"* — the ban demonstrates the format, which is the exact
pattern already measured in this repo when naming "hugging, waving,
winking" put `[winks]` in 3 of 4 live replies. `[wink]` is still the top
drop here (3 of 21). The experiment: a `yuzu3` identical to yuzu2 except
that one line rewritten to forbid the format without showing it, then
`--persona yuzu2` vs `--persona yuzu3`. One variable, minutes not
screenshots. **Ghost has not green-lit this yet.**

**yuzu2 v2.1** (self-concept + movement + length fixes) measured Sept 1,
4 replies: **action hit rate 10/11 = 91%**, moves_at_all 100% (was 50%
before the movement rule), spoken length 38w avg (was 62w, under the
45w TTS warning). The old 78–83% is stale — different composed prompt.

Two residuals, both judged to be at the 3B ceiling and deliberately NOT
chased further:
- `[laughs]` — a vocalization in brackets. Known category, fails safe
  (dropped silently, speech survives). ~1 in 4 replies.
- "Where's Berlin?" gets vibes, not a location. She produces correct
  Berlin specifics (Spree, Kreuzberg, techno), so it's a "where"→"tell
  me about" reading, not missing knowledge. The reported bug — "my
  world is this room" — is gone.

**The prompt grew 2404 → 3719 chars (+55%) over three fixes this
session.** TTFT on Ghost's phone hit 47s. Every further rule costs
latency on the Jetson too; weigh that before adding another.
Her predicted failure modes and what to watch for are in
PERSONA_SWITCHING.md.

**Speaking was guaranteed; moving was not.** The prompt had a dialogue
rule and no movement rule, and once Yuzu got her wants back she
monologued about the mall in 84-word replies with zero brackets. Every
eval check read 100% — `actions_runnable` is an `all()` over the actions
present, so a reply with none passes vacuously. `moves_at_all` now
scores it. When a whole round looks perfect, suspect the harness.

**Wants go in the rules; the body picture goes in an example.** A want
("I'd live at the mall") cannot produce a bracket, so it's free. A
concrete body part ("long bleached hair") in the RULES is one token
from `[flips hair]` — and that position is the one that measurably
backfired before, when naming "hugging, waving, winking" as don'ts put
`[winks]` in 3 of 4 live replies. Shown in an example instead, it
teaches the recovery.

**The body bounds what she can DO, never what she can know or want.**
"Your whole world is the room you're standing in" lived in the shared
hardware file and collared every persona that composed the menu in —
Coco answered "Where's Berlin?" with "I don't know what you're talking
about. My world is this room," and the gyaru stopped wanting to go to
the mall. Movement stays whitelisted; imagination is free and belongs
in the sentence, never in brackets. Don't put character stances in
`_hardware_*.txt` — that file is for servos.

Watch for: PocketPal renders `*asterisks*` as italics WITHOUT showing
the markers, so an italicised word in a screenshot is an asterisk
action, not plain text. Ask before scoring if it's ambiguous.
