# Yuzu-Spider-V1 — working notes for Claude

## Conventions

- **Work on `main`.** No feature branches unless Ghost asks.
- **Whenever Yuzu's prompt changes, paste the full composed prompt into
  the chat as a copy-paste block**, without being asked. Ghost tests in
  PocketPal on a phone, so a file path or a command is useless to him —
  he needs the text itself. Get it with:
      python yuzu_personas.py --show yuzu4
  (that key is `yuzu_personas.LIVE_PERSONA`; `python yuzu_personas.py`
  on its own marks which one is live.)
- **Ghost works from a phone** (Z Flip 6, Pydroid + PocketPal). Anything
  requiring typed commands, file paths, or arguments is a dead end.
  Prefer: text he can paste, or a no-argument script he can tap Run on.
- Run `python YUZU_TESTER.py` before committing. 291 tests, ~18 seconds.

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
(that repo path is confirmed working). 291 tests pass on it. Getting it
to boot took a night and the whole story is in UBUNTU_LAPTOP.md —
**locked NVRAM**, so it only boots via a firmware-registered trusted
file, and only from **F12 → entry 3 `ubuntu`**. **RESOLVED: a Bluetooth keyboard is
paired to it now and typing is normal.** The built-in keyboard is still
missing **k, l, m, Enter and up-arrow**, so if the Bluetooth one is ever
flat or absent: numpad Enter works, `Ctrl+P` is up-arrow in a terminal,
and Tab completion covers the dead letters.

**Don't record the chassis paint scheme anywhere.** Ghost has changed
it repeatedly and asked (Sept 3) that it stay out of the repo, because
every doc naming a colour goes stale the next time he changes his mind.
paintstepslol.txt keeps the PREP PROCESS, which works for any colours.
(The LED trim that used to be recorded here is gone with the rest of
the LED work -- see "LEDs are removed" below.)

This does NOT mean stripping pink from Yuzu. Her liking hot pink is
character, it lives in the persona files, and removing it would gut
her. The rule is about the CHASSIS FINISH, not her taste.

## Prompt work

`personas/yuzu.persona` is the ORIGINAL, extensively tested by Ghost.
Do not edit it — a test asserts it stays byte-identical to
`personas/_golden_yuzu_v1.txt`.

**Promotion rule: the measured winner becomes the base.** Ghost's call,
Sept 3, and it should stay the policy. Build the next variant on
whichever version last scored best, don't keep forking from an old one.
That instruction used to say "iterate on yuzu2" and was already stale
by two versions -- following it would have forked the lineage.

Current lineage and status:

    yuzu    ORIGINAL, frozen, byte-pinned by a test. Never edit.
    yuzu2   measured base. 36 + 12 replies. moves_at_all 80.6-83.3%.
    yuzu3   asterisk experiment. CLOSED, no effect. Keep as the record.
    yuzu4   yuzu2 + bare-command example. LIVE. Beat yuzu5 head to head.
    yuzu5   the 17% trim. Scored 7/12. CLOSED.
    yuzu6   the trim with v4's body back. Scored 9/12. CLOSED.

THE TRIM LINE IS CLOSED. Not because the trims were proven harmful --
they weren't, see the noise floor below -- but because the thing they
existed to buy, they don't buy. Both spoke MORE per reply than yuzu4.

So the base to build on is **yuzu4**. It has now outscored both
challengers and nothing is queued against it. Losing arms stay as the record
of what was tried -- that is what stopped yuzu5 being re-attempted from
scratch and what will stop yuzu6 being mis-read later.

**The promotion rule now has one line to move: `LIVE_PERSONA` in
`yuzu_personas.py`.** It is `yuzu4`. The robot loop, `yuzu_brain
--chat` and the eval all boot from it.

It is separate from `DEFAULT_PERSONA` (still `"yuzu"`) on purpose, and
that separation fixed a live bug: everything with no `--persona`
argument was booting the FROZEN v1 archive, measured at a 20% action
hit rate, purely because that file owns the short name that
`Modelfile.yuzu` and the Ollama model `yuzu` are built off. Renaming
those would break every setup that already ran `build_yuzu_model.py`,
so the pointer moved instead. A test asserts `LIVE_PERSONA` is never
the frozen archive, that it loads, and that it is what an un-argued
brain picks up.

**Run A/Bs with `python YUZU_AB.py`.** No arguments needed -- it runs
`LIVE_PERSONA` against the candidate in `YUZU_AB.ARMS`, 12 prompts
each, and prints ONE table instead of two runs to hand-transcribe.
`moves_at_all` is forced to the top row, and it prints what one reply
is worth in points, because every difference in the yuzu2-vs-yuzu3
round was a single reply and read like a result until it was counted.
Tests cover the arithmetic and the "that's a coin flip" verdict.

Ghost's method is A/B testing in PocketPal and sending screenshots.
It works. Score them against the real parser rather than eyeballing —
`yuzu_all_in_one.lookup_actions()` is the ground truth for whether a
bracketed action would actually move the robot.

Measured so far: v1 20% action hit rate → v2 78–83%.

`personas/coco.persona` (kuudere). First live round (9 replies, Sept 1):
**11/11 actions ran**, has_dialogue 89% — one all-actions freeze, which
was the predicted #1 risk for the archetype. Small sample; treat it as
promising, not proven.

**Coco is caught up to yuzu4 as of Sept 3.** Ghost lifted her hold
("im ready for coco"). She was built on v2's structure and Yuzu then
had three more measured rounds, so she had drifted TWO wins behind:

- **the always-MOVE rule** (`{MOVEMENT_RULE_V2}`) -- 50% -> 100% on
  moves_at_all, the single biggest measured win in the project, and she
  did not have it at all. A terse low-affect character is the one most
  likely to talk without moving, so she needed it more than Yuzu did.
- **the bare-command example.** All eight of her examples were
  questions or social requests -- exactly the shape that produced ZERO
  brackets in both yuzu2 and yuzu3 when handed a flat imperative. Hers
  is in her own register: `Coco: Walking. [walks forward] Say when to
  stop.` A test asserts it has no exclamation marks, no "cutie", no
  "bestie" -- teaching Yuzu's voice to a kuudere is the same drift that
  made persona switching clear history in the first place.

A third flag, "brevity rule", was a false positive from a literal
needle. Her rule "Short is fine. Silent is not. One or two calm
sentences is a normal reply for you." IS the brevity rule in her idiom.
Left alone.

She is 4058 chars against yuzu4's 3785. **Deliberately not trimmed to
compensate** -- the trim line is closed, and both attempts at shortening
Yuzu made her wordier. Adding a measured win is the change this repo
sanctions; shortening to pay for it is the one it doesn't.

`test_coco_carries_every_measured_win_the_live_persona_has` reuses
`TestYuzu5.MEASURED_WINS`, so a win added there is automatically
required of her too and she cannot silently fall behind again.

**To score her: `python3 YUZU_AB.py yuzu4 coco`.** Both arms in one
process under identical conditions, which after the noise-floor finding
is the only honest way to compare -- yuzu4 alone swung three replies
between two separate runs. Every check is a hardware rule, so scoring a
gyaru against a kuudere is fair. The tool now notices the arms are
different CHARACTERS (different persona `name`) and drops the "move
LIVE_PERSONA to the winner" advice, which is nonsense when nobody is
replacing Coco with Yuzu -- it says fix the loser's prompt instead.

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

**CLOSED — the asterisk hypothesis is NOT supported. Sept 2, measured.**
yuzu3 was yuzu2 with one line changed: the bracket rule rewritten to
forbid asterisks without displaying one. 12 replies each on the laptop.

    check              yuzu2    yuzu3    counts      diff
    no_asterisks       58.3%    50.0%    7/12 vs 6/12   -1 reply
    moves_at_all       83.3%    75.0%   10/12 vs 9/12   -1 reply
    one_per_bracket    91.7%   100.0%   11/12 vs 12/12  +1 reply
    has_dialogue       91.7%    91.7%   identical
    actions_runnable   66.7%    66.7%   identical
    not_an_assistant  100.0%   100.0%   identical
    brackets_balanced 100.0%   100.0%   identical

Every difference is ONE reply. At n=12 a single reply is 8.3 points, so
58.3 vs 50.0 is a coin flip. Pooling yuzu2 across both its runs gives
26/48 = 54.2% on no_asterisks, and yuzu3's 50.0% sits inside that
spread. **No detectable effect. Don't re-run it, don't re-theorise it.**

Same verdict as `[winks]`: asterisks are a prior the 3B brings with it,
not something the prompt teaches. And they cost nothing on the robot --
`normalize_actions` rescues `*spins*` to `[spins]` and it runs. Three
of yuzu3's six "no_asterisks failures" moved perfectly well.

Keep the anti-asterisk rule anyway: removing it entirely (not just
rewording it) DID measurably regress, back in the PocketPal rounds.
Rewording it is what does nothing.

**Follow-on, Sept 3: the drift monitor was acting on that finding
backwards.** `ReplyHealth.ok` failed any reply containing an asterisk,
and two failures in a row trim the conversation. But pooled yuzu2 is
54.2% on no_asterisks while moving on 80-83% of replies, so about a
third of replies were asterisked AND completely fine -- and at a ~46%
per-reply rate, two in a row lands roughly every fifth turn. She was
being made to feel amnesiac by a metric, not by a fault.

The asterisk veto is gone. `_canonicalise` already rewrites them to
brackets before they enter history, which is what actually stops the
snowball; the veto was a second guard on a risk already handled. What
still fails a reply is unchanged and robot-facing: said nothing at all,
or moved only in ways this body can't. Asterisks are still counted and
still show in `last_health` and `/health`.

**THE REAL FINDING FROM THAT RUN — a bare command produces no
movement, reproducibly, in BOTH arms:**

    ask: "Walk forward."
    yuzu2: "I'm heading straight for the mall, wanna come with?"
    yuzu3: "I'm literally walking towards you right now! Ehehe~"

Zero brackets in either. Told to move, she NARRATES moving instead.
This is the one failure that repeated across arms, so it is signal
rather than noise, and it is worse than the statue case: it's ignoring
a direct instruction.

Diagnosis: every example in the prompt is a question or a social
request ("what's up?", "do a little robot dance for me!", "can I have
a hug?"). Not one is a bare imperative. Given a flat command with no
social content, she supplies the missing conversation and describes
the action in prose.

`personas/yuzu4.persona` is the test: yuzu2 plus ONE example,

    User: Walk forward.
    Yuzu: On it! [walks forward] Where are we headed, cutie?

+78 chars, one variable. Run `--persona yuzu2` vs `--persona yuzu4`
and watch `moves_at_all` and that specific prompt.

**yuzu4 HELD — Sept 3, PocketPal, 4 replies.** Not the clean bare-command
test (the commands got wrapped in greetings), but the thing it was built
for worked anyway: **4/4 replies moved**, including "Hii! Whats up girl?
Walk forward." — the exact shape that produced zero brackets in both
earlier arms. Actions run 9/17 = 53%, dragged down by vocalizations.

Two new findings from that round:

1. **Wrong direction, not no direction.** "Walk forward" got
   `[walks backward]`; "Turn around" got `[looks right]`. She now
   reliably reaches for the menu but grabs the wrong item off it. This
   is a different failure class from the old one and probably a 3B
   comprehension limit rather than a prompt bug -- weigh carefully
   before spending prompt budget on it, see the latency note below.

2. **There was NO way to say stop.** No stop, halt, wait, stand still
   or freeze anywhere in the whitelist. Told to "stop walking" she used
   `[centers camera]`, the closest thing available. FIXED: those nine
   phrasings now alias to `stand`, which calls `stance()` -- feet
   planted, body level, motion over. That IS stopping.

**LATENCY IS THE URGENT PROBLEM ON THE PHONE.** Time-to-first-token
across that one four-turn conversation:

    turn 1   51s
    turn 2   73s
    turn 3   98s
    turn 4  107s

Climbing every turn as history accumulates on top of a 3797-char
prompt. Nearly two minutes before she starts speaking. The Jetson will
be far better (GPU, and `history_turns=8` caps the growth), but this is
now the strongest argument against adding ANY further prompt rules.
Every new line costs seconds on every turn, forever. If something must
be added, take something else out.

**yuzu5 — the trim, built Sept 3. SCORED AND LOST; see below.**
3797 -> 3134 chars, a 17% cut, motivated entirely by the latency wall
above. What changed:

- Rules 5, 7 and 8 (playful/flirty, loves pink, the mall) are GONE as
  rules. They are cut only because the EXAMPLES already demonstrate all
  three -- "cutie"/"bestie", "nails in hot pink"/"Pink is my whole
  personality", "unreal shopping, I'd go tomorrow". That is the pattern
  this repo proved twice: examples teach character better than rules.
  A test asserts each trait still appears in an example AND no longer
  appears as a rule, so rewording an example can't silently delete a
  trait.
- The body prose is tightened, same meaning, fewer words.
- Added one example: `User: Stop.` -- the stop aliases fix the parser,
  but she also needs to see the word.
- Eight rules became five.

Every one of the nine measured wins is kept and pinned by
`TestYuzu5.MEASURED_WINS`: self-concept, anti-asterisk, sounds naming
both wrappers, always-speak, always-move, brevity, answer-first,
no-puppeteering, bare-command example.

**yuzu5 SCORED AND LOST — Sept 3, laptop, 12 replies each. The trim
took one sentence too many.**

    check              yuzu4    yuzu5    counts        diff
    moves_at_all       75.0%    58.3%    9/12 vs 7/12   -2 replies
    actions_runnable   83.3%    33.3%   10/12 vs 4/12   -6 replies
    no_asterisks       50.0%    25.0%    6/12 vs 3/12   -3 replies
    one_per_bracket   100.0%    91.7%   12/12 vs 11/12  -1 reply
    not_an_assistant   91.7%   100.0%   11/12 vs 12/12  +1 reply
    has_dialogue      100.0%   100.0%   identical
    brackets_balanced 100.0%   100.0%   identical
    no_puppeteering   100.0%   100.0%   identical
    spoken length      24w      26w

**Do not read this the way yuzu3 was read.** There the whole result was
ONE reply on one check and it was correctly called a coin flip. Here
FOUR checks all move the same way, and there is a mechanism in the
dropped-action list rather than just a number:

    yuzu5 dropped: [giggles] x2, [pauses], [shrugs], [wink],
                   [bounces up slightly], [jiggles legs back and forth]

**The cause is one sentence.** HARDWARE_MENU_V5 rewrote the sounds rule
and dropped its closing line:

    "Brackets are only ever for the movements listed above."

Giggling is named in that very rule as a sound. Without the closing
line she bracketed it anyway, twice. `[pauses]` and `[shrugs]` are the
same class: brackets used for things that are not movements.

The trim was three separate cuts and only one was harmful. Of the 663
characters, 493 came out of the RULES (the flirty / pink / mall rules,
cut because the examples already teach them) and 259 out of the BODY.
Nothing suggests the rule cut hurt. The body rewrite is the suspect and
it is the only thing yuzu6 changes back.

**REVISES AN EARLIER "SETTLED" CALL.** `[laughs]` / `[giggles]` in
brackets was written up above as "a vocalization... judged to be at the
3B ceiling and deliberately NOT chased further". That is now wrong. The
rate is prompt-controllable: one sentence suppresses it, and removing
that sentence roughly doubled it. Do not re-shelve this as a model
limit.

**yuzu6 — built and scored Sept 3. CLOSED.** `sed` of yuzu5 with
`{HARDWARE_MENU_V5}` swapped back to `{HARDWARE_MENU}`. Literally one
token, so it differs from yuzu5 in the body block and nothing else, and
a test asserts exactly that. 3393 chars: still an 11% cut on yuzu4, so
404 of the 663 characters of latency win survive.

It scored 9/12 against yuzu4's 12/12 -- see the round below. The
hypothesis did not survive: restoring the sentence did not restore the
score. yuzu4 stands as the end of the line.

**yuzu6 SCORED — Sept 3, same session. It lost too, and that is what
exposed the real problem: THE HARNESS CANNOT SEE A 3-REPLY DIFFERENCE.**

    check              yuzu4    yuzu6    counts        diff
    moves_at_all      100.0%    75.0%   12/12 vs 9/12   -3 replies
    no_asterisks       66.7%    33.3%    8/12 vs 4/12   -4 replies
    actions_runnable   75.0%    41.7%    9/12 vs 5/12   -4 replies
    one_per_bracket   100.0%    91.7%   12/12 vs 11/12  -1 reply
    has_dialogue       91.7%    91.7%   identical
    spoken length       24w      30w

Now put yuzu4's TWO runs side by side. Same laptop, same model, same
12 prompts, same everything -- the only thing that changed is which
challenger it happened to be paired against:

    check              run 1    run 2    swing
    moves_at_all        9/12    12/12    3 replies  <-- the headline
    no_asterisks        6/12     8/12    2 replies
    actions_runnable   10/12     9/12    1 reply
    has_dialogue       12/12    11/12    1 reply

**An unchanged prompt swings three replies at n=12.** That is the same
size as the gap we spent two rounds calling a result. So:

- yuzu5's -2 replies: inside the noise.
- yuzu6's -3 replies: exactly the noise floor.
- Neither trim is PROVEN worse. Neither is proven equal either. At this
  sample size the harness simply cannot tell, and no amount of staring
  at the tables will change that.

**CORRECTION to the yuzu5 entry above.** It says "Do not read this the
way yuzu3 was read... FOUR checks all move the same way, and there is a
mechanism". The mechanism reasoning was fair and the sentence
hypothesis was worth testing -- but the confidence was not earned, and
yuzu6 then restored that exact sentence and still scored 9/12. The
sounds-sentence hypothesis is NOT SUPPORTED. Leave the yuzu5 numbers
where they are; they are real. It is the reading of them that was
overconfident.

**WHAT ACTUALLY CLOSES THE TRIM LINE: spoken length, the one metric
that does not wobble.**

    yuzu4   run 1  24w      run 2  24w      <- identical across runs
    yuzu5   26w
    yuzu6   30w

yuzu4 came back 24 and 24 while its headline swung three replies. That
stability is what makes the length numbers worth something the movement
numbers aren't. Both trims dropped the tail of the brevity rule --
"You're talking to someone, not writing a post." -- and both got
wordier, yuzu6 by a quarter.

And that kills the whole point. The trim existed to cut latency. It
saves 404 prompt characters, paid ONCE per turn and prefilled in a
batch. It costs +6 generated words, paid ONE TOKEN AT A TIME, every
turn. Generation is the expensive half. **A shorter prompt that
produces longer replies is a latency loss wearing a latency win's
clothes.**

Add to that: the phone latency wall was the entire motivation, and the
Orin removes it. Chasing 400 characters on a box that is about to be an
order of magnitude faster is the wrong place to spend eval time.

**So: yuzu4 stands. Don't build yuzu7 out of a smaller yuzu4.** If a
future prompt change is worth testing, it should be one that adds or
fixes a behaviour, not one that shortens.

**Three fixes to YUZU_AB.py from this round:**

- **The noise floor is now measured, not assumed.** It was declaring a
  winner at 1.5 replies. `NOISE_FLOOR_REPLIES = 3`, cited to the two
  yuzu4 runs, and stated in REPLIES so `--runs 3` genuinely lowers it
  instead of just printing smaller numbers.
- **Spoken length gets its own verdict.** If the arm with the shorter
  prompt also has the longer replies, it says so and explains why that
  is not a latency win. That is the check that would have closed this
  line after ONE round instead of two.
- Both arms' dropped-action lists print (was challenger-only).

**A loss needs no confirmation run.** The promotion rule says confirm
before PROMOTING. yuzu4 already boots, so the outcome here is "change
nothing" and a `--runs 3` confirm would spend 72 replies proving the
status quo. YUZU_AB.py said "confirm before promoting" anyway when the
live arm won; that was a bug in the tool and it is fixed.

**Two tool bugs this round exposed, both fixed:**

- Only the CHALLENGER's dropped-action list was printed, so yuzu5's
  `[giggles]` had nothing to be compared against. A comparison tool
  with a one-sided view is the exact failure this file exists to
  prevent. Both arms now print, with totals.
- The scaffold for new personas pointed at `{HARDWARE_MENU_V5}` -- the
  block that just lost. Every character created with `--new` would have
  inherited the regression. Repointed at `{HARDWARE_MENU}`, and the
  scaffold test now pins the sounds sentence. `HARDWARE_MENU_V5` itself
  is left untouched in the hardware file: yuzu5.persona is the RECORD
  of this experiment and editing it would corrupt the evidence.

**What "tested in a sim" does and does not mean here.** Verified by
machine: every example both speaks and moves, every phrase offered
actually runs, all 13 whitelist entries are exposed, no impossible
action is named in the rules, and the whole historical corpus -- 23
real replies spanning v1 to v4 plus five pathological cases -- runs
through the pipeline with zero crashes and zero markup reaching TTS.
NOT verified: how the model responds. Only the laptop or the Jetson
can answer that -- and when it did, v5 lost. Every one of those
machine checks passed on v5 and it still dropped 2 replies of movement,
because none of them can see what a sentence's ABSENCE does to a 3B.
That is the standing limit of "tested in a sim" here.

**Eval cost on the laptop is real.** 36 replies took long enough that
Ghost abandoned a run. Use `--runs 1` (12 replies) for direction; the
12-reply numbers tracked the 36-reply ones closely (58.3 vs 52.8 on
no_asterisks, 83.3 vs 80.6 on moves_at_all). Save `--runs 3` for
confirming something that already looks real.

**Superseded note, kept for the reasoning:**
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

## Pivoting the main character

Ghost asked (Sept 3) how hard it would be to swap Yuzu out for a
different main persona. Answer: one new file plus one line
(`LIVE_PERSONA`), and PERSONA_SWITCHING.md walks it through. Checked by
reading every runtime reference to the name, not by assuming.

The check found the entry point was rotten. `yuzu_personas.TEMPLATE` --
what `--new saki` writes -- was built on `{HARDWARE}` and
`{DIALOGUE_RULE}`, the v1 blocks: 20% action hit rate, NO movement rule
(the rule that took moves_at_all from 50% to 100%), and a
`Wrong: [winks]` example, which is the exact pink-elephant pattern this
repo measured putting `[winks]` in 3 of 4 live replies. Anyone pivoting
would have restarted the lineage from the worst prompt in the repo.

Fixed: the scaffold is now the measured shape (`{HARDWARE_MENU_V5}`,
the five rules that each fixed something, the four tested example
shapes), and `TestPersonas.test_a_new_persona_starts_from_the_measured
_prompt` asserts a fresh scaffold carries every entry in
`TestYuzu5.MEASURED_WINS` -- reusing that dict, so adding a win there
automatically guards the scaffold too.

Two other places the name leaked into BEHAVIOUR, both fixed:

- `yuzu_prompt_eval.TEST_PROMPTS` opened with the literal "Hey Yuzu,
  what's up?", so every Coco run was scored on a turn calling her Yuzu
  -- while that file's docstring claims it is a fair way to compare
  personas. `prompts_for(persona)` substitutes the real name now.
- `YuzuBrain.check()` hardcoded `ollama create yuzu -f Modelfile.yuzu`
  as the fix instruction, which points at the wrong thing the moment
  the main character changes, at exactly the moment someone is stuck.

Everything else carrying "Yuzu" -- `YuzuBrain`, `handle_yuzu_reply`,
`run_yuzu_forever`, the filenames -- is a NAME, not character logic.
Coco already runs through all of it unchanged. Don't rename them: it
would be cosmetic, and it would break every doc path, DEPLOY.md, and
Ghost's muscle memory for no behavioural gain.

## Her voice

`yuzu_voice.py`, Sept 3. Piper TTS, and **the project's only dependency
boundary**. Everything else is stdlib so it runs in Pydroid; Piper is a
real binary and a real model file and neither exists on a phone. So the
dep lives in one module, `yuzu_all_in_one.py` imports it in a
try/except exactly like the gaits, and with Piper absent
she prints as she always did. A test asserts that import stays guarded.

It shells out to the `piper` binary with `subprocess` rather than
importing a Python package, so the project still `pip install`s
nothing.

**`piper_length_scale` finally does something.** It has been in every
persona file since the format was written and NOTHING read it. yuzu4
runs 0.88, Coco 1.08. `apply_persona_voice()` runs wherever a persona is
loaded or switched, so changing character changes her voice with her,
and a test asserts the kuudere speaks slower than the gyaru.

**Piper's flag names are detected, not guessed.** It has shipped both
`--output_file` and `--output-file`, and both `--length_scale` and
`--length-scale`. Getting it wrong is an unrecognized-arguments error
and silence. `detect_flags()` reads `piper --help` once and picks. When
piper fails, its OWN stderr is surfaced -- it names a missing json or a
bad model far better than anything guessed from here.

**What the sanitiser does, derived from real data not imagination.**
Replaying all 26 captured replies through the pipeline, exactly two
non-word characters survive into speech, and `for_speech()` removes
both:

    'Ehehe~! DANCE DANCE!'  ->  'Ehehe! DANCE DANCE!'
    "it's 2 * 3 * 4 babe"   ->  "it's 2 3 4 babe"

The asterisks are from the multiplication case `normalize_actions`
deliberately leaves alone, because the version that didn't ate the
middle of the sentence.

**SHE SPEAKS. Heard Sept 3, en_US-amy-medium, Ghost's laptop.** The
tilde strip works -- "Ehehe~" came out as a laugh, not a symbol.

**ALL-CAPS was left untouched with a test saying "change this when
someone listens". Someone listened, twice, and the FIRST reading was
wrong.**

**THERE ARE TWO INDEPENDENT MECHANISMS. Round 1 confounded them and
diagnosed the wrong one.**

Round 1: "PFFT!" -> "Pee Eff Eff Tee". Blamed ALL-CAPS. Wrote
`unshout()`.
Round 2, lowercased: still "pee eff eff tee". So capitals were not the
cause OF THAT ONE.
Round 3, respelled puft / pift / puh / pfff / pshh: none worked either.

Then the clean A/B that separated them, on a single word:

    "SIX legs"  ->  spelled out, letter by letter
    "six legs"  ->  said properly

**Both mechanisms are real:**

1. **ALL-CAPS gets spelled out.** CONFIRMED by SIX vs six, same word,
   same sentence, only the case changed. `unshout()` is the fix and is
   now MEASURED, not the lucky guess it looked like an hour ago.
2. **Vowel-less tokens get spelled out regardless of case.** "pfft" has
   nothing for espeak's letter-to-sound rules to bite on. No spelling
   of a raspberry becomes a word, because a synthesiser says words.

**"pfft" is DROPPED, not respelled.** Three rounds was enough to stop
guessing. It fails exactly the way the action whitelist already fails:
an action this body can't do produces silence, never a substitute
movement -- so a noise this voice can't make produces silence too, and
the sentence around it survives. "PFFT! My camera is shaking!" is
spoken as "My camera is shaking!". Her transcript still prints the
PFFT, because `speak()` prints the original.

Nothing else is dropped. tsk / shh / grr / hmph / psh have never been
heard and a test pins that they are untouched -- deleting character
from a noise espeak says perfectly well would be the same mistake in
the other direction. `--tryout <noise>` auditions them.

**Pfft is now GONE FROM THE PROMPT. Ghost's call, and the right one:**
fix it at the source instead of handling the symptom downstream. It was
taught in TWO places -- the shared sounds rule, and the "Say something
silly!" example. The EXAMPLE is the stronger teacher; this repo has
twice measured that examples beat rules.

**Removing it from one place broke two archived A/Bs, and that is worth
remembering.** The first pass edited `[HARDWARE_MENU]` and yuzu4's
example only. Immediately, `test_v2_and_v3_differ_by_exactly_one_line`
failed (2 lines differed) and `test_v4_is_otherwise_identical_to_v2`
failed. The lineage's one-variable property depends on every arm
sharing identical body text apart from its own deliberate variable, and
a one-sided edit destroys it.

`_hardware_muto_s2.txt`'s own header already said this: a body fix
should "land on all of them at once instead of needing five identical
edits". **A vocabulary fix is a body fix. It goes everywhere** -- all
three menu blocks and all five persona examples. Then every archived
comparison holds again, and a test now asserts NO persona anywhere
teaches an unsayable sound.

Prompt sizes after: yuzu4 3797 -> 3785.

**The code drop stays too, as the net.** Same reasoning as the action
whitelist surviving alongside a prompt that lists the legal moves: the
prompt REDUCES, code GUARANTEES. `[winks]` is named as forbidden and
still turned up in 3 of 4 live replies, and "Pfft" is ordinary English
the base model knows whether or not it is taught. Four lines, no other
dependency; drop them if Ghost would rather.

**Audition spellings instead of guessing across round trips:**

    python3 yuzu_voice.py --say "PFFT! hey cutie"   # through for_speech
    python3 yuzu_voice.py --raw "pfft"              # exactly as typed
    python3 yuzu_voice.py --tryout pfft             # speak the candidates

The `--raw` / `--say` pair is the diagnostic: same string, one through
the cleanup and one around it. That is how you tell a for_speech bug
from an espeak limit, and it costs ten seconds instead of a commit.

If ALL-CAPS ever DOES turn out to matter, the fix is not blanket
lowercasing, because two different things wear capitals in her voice:

    OMG, OG                          real initialisms. "oh em gee" IS
                                     how you say them. Keep the caps.
    PFFT HAHA GOSH SIX DANCE MY      shouted words. Spelling them is
                                     nonsense. Lowercase them.

Both lists come from words she has actually produced. `unshout()` keeps
`SPOKEN_INITIALISMS` capitalised and lowercases the rest. Nothing is
lost by dropping the caps -- Piper takes no emphasis from them -- and
`speak()` prints the ORIGINAL text, so her transcript still shouts.

If a new ALL-CAPS word shows up in a future round,
`test_every_all_caps_word_she_has_ever_said_is_classified` is the thing
that forces someone to decide which kind it is.

**Still unheard: OMG and OG.** Ghost reported PFFT and the tilde; he
did not say how the initialisms came out. They stay capitalised on the
reasoning above, and the demo now exercises both classes explicitly.
If "OMG" is mush, the allowlist is what's wrong.

**Verified by machine, not by ear:** the text reaching the synthesiser,
the command construction, flag detection, and every failure path
falling back to printing. Setup is JETSON_SETUP.md §6 and works on any
laptop -- no Jetson needed, Piper is software.

**pip hides piper in `~/.local/bin`** when site-packages isn't
writable, and warns about PATH in the middle of thirty lines of
download output. `find_piper()` looks there, because reporting "not
installed" about a binary sitting right there is the worse failure.

**Choosing a voice: `--list` and `--use`.** `find_voice()` used to
take the first `.onnx` ALPHABETICALLY, which is a live footgun the
moment there are two: download `en_GB-alba` alongside `en_US-amy` and
she quietly changes accent, and downloading a nicer voice and still
hearing the old one looks like nothing happened. `--use <fragment>`
remembers a choice in `voices/ACTIVE` (one line of plain text, no
config format, phone-editable), `--list` marks which is live and says
so when nothing is chosen. `YUZU_VOICE` still wins over both, for
one-offs. Ambiguous input is refused rather than guessed; a remembered
voice that was deleted falls back instead of going mute. `voices/` is
gitignored -- a model is 60MB and a personal taste call.

Preview voices at rhasspy.github.io/piper-samples BEFORE downloading.
Names decode as language-speaker-quality; stick to `medium` (`high` is
bigger and slower for nothing you'd hear over a robot speaker, and on
the Orin the voice shares 8GB with the LLM).

**The remaining STUB is the mic.** Whisper is worth waiting for the
Orin; TTS was not, because it cost nothing and needed nothing.

## NANO_DAY_ONE.md is the runbook now

Ghost, Sept 3, plainly: *"i dont read thru the project alot"* and
*"can we streamline this for the nanoorinsuperdevkit specifically?
thats legit her brain -- i only used the laptop cuz its what i had."*

Both are true and the docs did not reflect either. Getting a board
running meant picking between four files totalling 1229 lines, and
`JETSON_SETUP.md` opened with **"Stage 1 -- before the Jetson
arrives"**, a stage that expires the day the box lands.

`NANO_DAY_ONE.md` is one linear page, box to talking, no decisions.
Written to be read off a phone at the board. Steps 1-9 get her
answering; 10-12 (voice, the 8GB settings, the doctor) are marked
bonus so a bad evening still ends with a working robot.

The other docs keep everything and lose nothing -- README, DEPLOY and
JETSON_SETUP now point at the runbook first, and JETSON_SETUP carries a
banner saying its Stage 1 is history and §5b/§6 are the parts still
worth reading.

**`TestDayOneRunbook` keeps it honest**, because he will not
cross-check it: every file it names must exist, the test count it
promises must be the real one (self-referential on purpose -- adding a
test fails it until the doc is updated), it must use the `grep -i
heretic` model line rather than a hardcoded `yuzu`, and it must keep
saying which parts are unverified. The throttle reminder is asserted to
sit in the FIRST HALF of the page, not buried in troubleshooting.

That reminder now lives in four places. This is the one he will
actually open.

**When Ghost says the Nano has arrived, LEAD WITH `nvpmodel -m 0`.**
He asked for that directly -- *"i think ill remember to Un-Throttle it
but mention it when i text all excited with the nano"*. Do not bury it
under congratulations. First line.

**Two things in that runbook have never touched real hardware** and are
labelled as such in it: `piper-tts` on arm64 (the wheel he installed
was x86; whether an aarch64 one exists is unknown), and the doctor's
Jetson section (written from file paths, fixture-tested only). Both are
flagged so a failure there reads as a known risk rather than as
something he did.

## The transcript now names who is speaking

`speak()` hardcoded `"YUZU SAYS"`, so Ghost's first real conversation
with Coco scrolled past entirely labelled YUZU. Fixed: `speaker_name()`
reads `current_persona`, falling back to `ROBOT` on the echo stub.

**Third instance of one class of bug** -- the name leaking out of the
character it belongs to. The other two were the eval opening "Hey Yuzu,
what's up?" for every persona, and `check()` saying
`ollama create yuzu` whatever model was missing. This one survived the
audit that caught those because it is a `print`, not logic. If a fourth
turns up, grep for the string, not the code path.

The heard-vs-printed distinction is kept as a `(text only)` suffix. On
a robot you are SSH'd into, that is how you tell a silent speaker from
a silent robot.

## OPEN: the servo file hands every persona a gyaru's sounds

Found Sept 3 in Coco's first live conversation. She produced
`[Ehehe~]` (bracketed, so the whitelist dropped it) and spoke "Haha!".
Both are Yuzu's register, and her own rule says she does not shout or
stack exclamation marks.

The mechanism is visible in the prompt, not inferred:

    body block hands BOTH of them : Ehehe~, Haha!, Ugh, Ooh
    yuzu4's own examples use      : Ehehe~        (consistent)
    coco's own examples use       : Hm.           (never shown to her)

`_hardware_muto_s2.txt` is the file CLAUDE.md already says is "for
servos" and must not carry character stances. The sounds RULE (sounds
are words, not brackets) is a body fact and belongs there. The sound
EXAMPLES are character and do not.

**Proposed fix, NOT applied -- Ghost's call.** Drop the four tokens
from the shared line, keep the rule. Each persona's own examples
already carry her register: Yuzu has "Ehehe~", Coco has "Hm.". That is
the pattern this repo proved twice, examples over rules.

Cost: it changes the LIVE persona's prompt, so it wants an A/B round to
confirm nothing regressed. Against that, n=1 conversation -- two
register slips in four turns, and both failed safe. Worth doing when
something else justifies a round, not on its own.

## LEDs are removed

Ghost's call, Sept 3, after watching a real conversation scroll past:
five `[LED] state=...` lines wrapped around two lines of dialogue, for
hardware that does not exist and is "way down the line". Deleted
outright rather than silenced, because a dead subsystem you still have
to read around is worse than no subsystem.

Gone: `yuzu_led_manager.py`, `yuzu_led_controller.py`,
`yuzu_robot_config.json`, `LEDManager`, `set_led_state()`,
`apply_persona_look()`, `Persona.led_states()`, the `led_*` lines in
every persona file, and `TestLEDManager`.

**"Her awareness of it" was already nil** -- checked before touching
anything. No persona prompt has ever contained the words LED, light,
glow or neon. The `led_*` entries were hex colours in the settings
block, above the `---`, so they never reached a composed prompt. Her
prompt is byte-identical after this change and needs no re-test.

**It is all in git** -- `git show 9e1b4b4:yuzu_led_manager.py` brings
the manager back, and the same for the other two files. If the trim
ever gets built, restore them rather than rewriting: the merged
zones-plus-state-profiles design in there took a real bug to arrive at
(two incompatible colour formats and a config file nothing read).

## Bring-up safety

`muto_firstcontact.py` clamps every angle to 15 degrees while it checks
servos one at a time. Its cleanup used to restore the limit to 90
BEFORE parking, so aborting at stage 2 -- the stage that exists to
catch servo IDs wired differently from `LEG_SERVO_MAP` -- commanded 60
degrees into a chassis that had just proven it moves the wrong joints.
Measured on DummyBot: 60 before the fix, 15 after.

**Park first, restore the limit after.** A test drives a stage-2 abort
and asserts no servo was commanded past 15, parsing DummyBot's own
output, so it checks the whole process from the outside rather than
trusting the ordering to stay right.

If you touch that `finally` block, keep the order.

## Optimising the Nano Orin Super

`nvpmodel -m 0` is the headline and it already lives in three places.
Below it there is a second tier, all of it about the same fact: the
Orin has ONE pool of 8GB and everything shares it. Written up in
JETSON_SETUP.md 5b; the short version and the reasoning:

- **`OLLAMA_NUM_PARALLEL=1`.** Ollama sizes the KV cache as
  `num_ctx x num_parallel`. Left to choose for itself it reserves slots
  for concurrent requests a robot with one mouth will never make, and
  each slot is real memory out of the pool Whisper and Piper want next.
- **`OLLAMA_MAX_LOADED_MODELS=1`.** Two resident models on 8GB shared
  is how you land in swap.
- **`OLLAMA_KEEP_ALIVE=-1`.** Ollama unloads an idle model after five
  minutes. For a companion robot that is backwards: she sits quiet in a
  corner, someone walks up and speaks, and the 3B has to be read back
  off disk first -- so the very first thing anyone says to her is the
  slowest reply she ever gives. `yuzu_brain.py` now sends `keep_alive`
  on every request too (`YUZU_KEEP_ALIVE`, default `30m`), so this
  works even without editing the service. Set it to `0` while bringing
  Whisper up alongside her and you need the memory back between turns.
- **`OLLAMA_FLASH_ATTENTION=1` + `OLLAMA_KV_CACHE_TYPE=q8_0`.** Roughly
  halves what context costs in memory. The second needs the first.
- **Swap belongs on the NVMe, not the microSD.** Swap is sustained
  writes, which is where a card is slowest and what wears it out.
  JETSON_SETUP said "SD card" in one place and "get the NVMe" in
  another; the NVMe is right and it says so now.

**`python3 yuzu_doctor.py` on the Jetson checks all of it** -- power
mode (read from `/var/lib/nvpmodel/status`, so no `sudo` and nothing
that can hang), RAM, what the swap actually sits on, and which of those
settings are really set in the systemd unit. It reads the UNIT, not
`os.environ`: those variables are set for the ollama service and the
shell running the doctor does not inherit them, so checking the
environment would confidently report "not set" on a correctly tuned
box. The whole section is gated on Jetson detection and stays silent on
the phone. Fixtures for every parse are in `TestJetsonChecks`.

What is NOT worth tuning yet: `num_ctx`. 4096 with `history_turns=8`
fits comfortably and is the dial to reach for only once something
actually runs out.

## Before anyone adds vision / follow-me

Gemini gave Ghost a strategy note for this transition (Sept 2) and most
of it is right: build a DummyCamera before touching real hardware, keep
the PID as a pure numbers-in-numbers-out function, decide the
concurrency model before writing implementation, and define what
happens when the LLM and an autonomous vision loop disagree.

**The blocker it doesn't know about: the gait API is blocking, by
seconds.** Measured against DummyBot:

    walk_forward(steps=2)   2.53s
    turn(steps=2)           2.52s
    spin(steps=4)           4.69s

At 30fps that is 75-140 camera frames with no control input. `settle()`
sleeps on purpose -- it's the fix for the conflicting-motor-trajectory
risk -- so this is not a bug to remove. But it does mean a follow-me
controller CANNOT be layered on top of the current gait functions. They
are fire-and-forget animations, not a control interface. Vision needs a
step-level, non-blocking API underneath them (something like
`begin_step()` / `update()` polled from the control loop), with the
existing gaits rewritten as callers of it. Budget for that refactor;
don't discover it halfway in.

Three more constraints for that work:

- **Memory.** Vision makes it four models on 8GB shared: detector +
  3B LLM + Whisper + Piper. Check the budget before designing, not
  after. A detector may simply not fit alongside the rest.
- **Safety changes category.** A turn-based robot that moves only when
  spoken to is very different from one that walks at you on its own.
  An autonomous loop needs a watchdog that calls `rest()` when vision
  goes stale, plus a hard stop -- `Ctrl-C` is not enough once the thing
  moves without being asked.
- **Order.** Track with the 2DOF gimbal FIRST. Pan/tilt tracking needs
  the same PID, exercises the same DummyCamera, and the chassis never
  moves, so a wrong sign costs a twitchy camera instead of a hexapod
  walking into furniture. Body-follow only after that works and after
  the gaits are calibrated on real hardware.

The stdlib-only property ends when vision lands. Keep it anyway for the
brain: isolate camera and inference deps behind their own module so
`yuzu_all_in_one.py` still runs on a phone with nothing installed.

Watch for: PocketPal renders `*asterisks*` as italics WITHOUT showing
the markers, so an italicised word in a screenshot is an asterisk
action, not plain text. Ask before scoring if it's ambiguous.
