# Two characters, one robot

You were right — the Muto S2 + Orin can absolutely hold more than one
persona. What matters is *which of two very different mechanisms* you
use to switch, because one of them is free and one of them costs you
RAM on an 8GB board that's already running Whisper and Piper.

You already have both. This is just naming them.

---

## The short version

| | one model per persona | one model, swap the prompt |
|---|---|---|
| how you switch | `ollama run coco` | `/persona coco` |
| extra disk | kilobytes | zero |
| extra RAM | **another full model loaded** | zero |
| switch speed | model load (seconds) | instant |
| use it for | testing from a terminal | **the robot** |

**Use the second one on the robot.** Use the first one when you want to
poke at a character from a terminal without the robot running.

---

## Way 1 — one Ollama model per persona

```
python build_yuzu_model.py --all --create
```

That writes `Modelfile.yuzu` and `Modelfile.coco` and registers both
with Ollama. Then `ollama run yuzu` and `ollama run coco` are two
separate models you can talk to.

**Disk is not the problem.** Both Modelfiles start with the same line:

```
FROM llama3.2:3b
```

Ollama stores models as content-addressed layers, so those multi-gig
weights are stored **once** and both models point at the same blob. The
only new bytes are the SYSTEM text and the PARAMETER lines. Ten personas
would still be one copy of the weights.

**RAM is the problem.** `yuzu` and `coco` are different model *names*,
so Ollama loads and keeps each one resident separately, and by default
it holds a model in memory for about five minutes after the last message.
So right after you switch, you can have **both** sitting in memory at
once. On the Orin, with Whisper and Piper also loaded, that's the thing
that will bite you first.

Check it any time with:

```
ollama ps
```

That lists what's actually loaded right now and how much it's using. If
you see two 3Bs in there, that's this.

You can lean on it if you want to — `OLLAMA_KEEP_ALIVE=30s ollama serve`
makes it drop the old one faster — but the second way avoids the whole
question.

## Way 2 — one model, swap the system prompt

This is what the robot already does, and it's the cheap one.

Ollama's `/api/chat` takes the system prompt **as part of every single
request**. `yuzu_brain.py` re-sends it on every turn. So a persona isn't
baked into anything — it's just the first message in the list, and
swapping characters means sending different text next turn.

Nothing loads. Nothing unloads. No second copy of anything.

Three ways to drive it, all already wired up:

```
# while the robot is running — this is the one you want
/personas              list them, * marks who's talking
/persona coco          switch, right now, mid-conversation

# from a terminal, brain only, no robot and no audio
python yuzu_brain.py --persona coco --chat

# pick who boots by default
export YUZU_PERSONA=coco
```

### What a switch actually changes

- the system prompt (her whole character)
- her sampling — Coco runs at temperature 0.7, Yuzu at 0.8
- her LED colours — Coco's states go cold, Yuzu's stay pink
- the conversation history, which is **cleared on purpose**

That last one is deliberate and it matters. If you carry Yuzu's banter
into Coco's context, Coco spends the next several turns imitating a
gyaru, because a 3B follows its own recent output over a system prompt
sitting further back. That's the same drift the auto-recovery in
`yuzu_brain.py` exists to catch. Clearing on a switch just avoids
starting in the hole.

### The one gotcha

The `PARAMETER stop "User:"` lines only exist in the **Modelfile**. They
are what stop the model writing your half of the conversation, and a 3B
respects them a lot more reliably than it respects the no-puppeteering
rule in the prompt.

Runtime persona switching sends the prompt and the sampling, but it does
**not** send stop tokens — those come from whichever model you loaded.

So: run the robot against `yuzu` or `coco` (either one — the persona
system overrides the system prompt and the sampling anyway), **not**
against bare `llama3.2:3b`. Against the bare model you lose the stop
tokens and she starts writing your lines.

If you'd rather have a neutral host to switch personas on top of, make
one Modelfile with the stop tokens and no SYSTEM block, call it `base`,
and run everything against that. Not necessary — just tidier.

---

## Pivoting the main character

Bored of Yuzu? Want someone else to be the one who boots? It is two
steps, and neither of them touches code you'd have to understand.

```
python yuzu_personas.py --new saki     # writes personas/saki.persona
# ...edit that file, it's plain text and phone-editable...
python yuzu_personas.py --show saki    # read the composed prompt
```

Then one line in `yuzu_personas.py`:

```python
LIVE_PERSONA = "saki"
```

That's it. The robot loop, `yuzu_brain --chat`, the eval and the A/B
all boot her. No model to rebuild — Ollama takes the system prompt as
part of every request, so a persona is just the first message.

### What you keep

Everything that isn't her personality, which is most of the project:

- the bracket parser, the whitelist, the aliases, the stemmer
- every gait, the simulator, the bring-up script, the safety machinery
- the brain, the drift recovery, the history canonicalisation
- the eval, the A/B runner, all 242 tests

Those are facts about a Yahboom Muto S2 and about a 3B model. None of
them know or care who is driving.

### What a new persona inherits for free

`--new` scaffolds from the **measured** prompt, not a blank page. A
fresh character starts with all nine wins already in place: the
self-concept block, the anti-asterisk rule, the sounds rule, always
speak, always move, brevity, answer-first, no-puppeteering, and the
bare-command example. `TestPersonas.test_a_new_persona_starts_from_the_
measured_prompt` reuses `TestYuzu5.MEASURED_WINS` to check it, so the
two can't drift apart.

This was NOT true until Sept 3. The scaffold was built on the v1 body
blocks — the 20% action hit rate, no movement rule at all, and a
`Wrong: [winks]` example that measurably taught `[winks]` in 3 of 4
live replies. Anyone pivoting would have had to rediscover the whole
lineage. Same shape as the `LIVE_PERSONA` bug: the oldest thing owning
the friendliest entry point.

### The names in the code are just names

`YuzuBrain`, `yuzu_all_in_one.py`, `handle_yuzu_reply`,
`yuzu_personas.py` — those are module and function names, not
character logic. Coco already runs through every one of them unchanged.
Renaming them would be a cosmetic afternoon and would break every doc,
every path in `DEPLOY.md`, and Ghost's muscle memory. Not worth it; the
project is named Yuzu-Spider-V1 the way a band keeps its first name.

The two places the name genuinely leaked into behaviour were found and
fixed: the eval's opening prompt was the literal "Hey Yuzu, what's
up?", so scoring Coco called her Yuzu, and the "model not found" error
hardcoded `ollama create yuzu -f Modelfile.yuzu`. Both now use whoever
is actually loaded.

### If you want a different ROBOT, not a different character

That's `personas/_hardware_*.txt`. A persona names its body with one
line (`hardware: muto_s2`), so the same character can move to a
different chassis by changing that word — `_hardware_saya_quad.txt` is
a draft of a four-legged one with an OLED face and no gimbal. You'd
also need a gait module for it; `muto_leg_control.py` is Muto-specific
below the whitelist.

## What's actually been measured

Being straight with you about this, because the repo is otherwise
careful about it:

- Yuzu v1: **20%** action hit rate. Measured, by you.
- Yuzu v2: **78–83%** — but that number is now **stale**. The shared
  body file changed when we took the "stuck in a room" framing out, so
  v2's composed prompt is no longer the one you measured. Re-run it.
- Coco, first round, 9 replies: **11/11 actions ran.** Every check at
  100% except has_dialogue at 89% — one reply that was pure
  `[walks backward]` with nothing said, which is the freeze this
  archetype was always going to walk into. Nine replies is a small
  sample. Promising, not proven.

Score her the same way you scored v2:

```
python yuzu_prompt_eval.py --persona coco
python yuzu_prompt_eval.py --persona yuzu2      # same body rules, warm
```

Both run against the same hardware checks, so the numbers are directly
comparable — that comparison is a real finding about which *speech
style* survives the format constraints, not a matter of taste.

## What to watch for in her first live round

A kuudere walks into different failure modes than a gyaru, and these are
the ones I'd expect first. Worth screenshotting specifically:

1. **Silent replies.** A reply of `[squats]` and nothing else is
   perfectly in character for her and completely broken for the robot —
   it just looks frozen. This is her single biggest risk. Her prompt
   states the rule twice for that reason ("Short is fine. Silent is
   not.").
2. **Help-desk drift.** Flat + helpful is one short step from "How can I
   help you today?". If she starts sounding like a stock assistant,
   *raise* her temperature toward 0.8 before you touch the prompt — the
   flatness cliff is around 0.6 and she's deliberately sitting at 0.7.
3. **Face moves.** A kuudere's whole register is facial — the flat
   stare, the glance away, the raised eyebrow — and this chassis has no
   face. If you see `[stares]`, `[looks away]`, `[tilts head]`,
   `[shrugs]`, `[blinks]` in the logs, that's the empty channel. Her
   prompt hands her the camera as the replacement instead.
4. **Sounds as movements.** `[sighs]` and `[scoffs]` are very her, and
   both are sounds — they belong in the sentence as plain words, not in
   brackets. Sounds were 8 of 9 dropped actions in the last live round
   for Yuzu, so expect this one.

Anything in that list that shows up *repeatedly* and is a real move
phrased oddly belongs in `ACTION_ALIASES` in `yuzu_all_in_one.py`.
Anything genuinely impossible on this body (`[stares]`) is **supposed**
to be dropped — that's the whitelist working, not failing.

I deliberately added **no** new aliases for her. Your method is measure
first, then add, and guessing at aliases before a live round would put
made-up phrasings next to the ones you actually observed.

---

## The room thing (fixed)

Her first round had her saying "My world is this room" and refusing to
say where Berlin was. That came from one sentence in the *shared* body
file, which meant both v2 characters inherited it.

It was the wrong kind of rule in the wrong file. The body file's job is
to bound what she can **do** — six legs, a camera, no hands. Bounding
what she can **know, want, or picture** is not a servo fact, and it cost
the gyaru the thing that made her fun.

Two halves of that fix carry very different risk, so they're placed
differently:

- **What she wants and knows** — Berlin, the mall, snow. Zero action
  risk: no want can produce a bracket. This lives in the rules at full
  strength, and it's the half that actually fixes the dodge.
- **What she looks like** — hair, lashes, nails. This is where the risk
  is, because it's one token from `[flips hair]`. It lives only in a
  worked example, never in a rule — the same position rule that made
  the hug example work and the "never wink" rule backfire.

Now: she's a person driving a chassis. She knows exactly what she is and
won't claim arms she hasn't got, but she has a self, a look she pictures
herself with, and places she'd like to go. Movement is still whitelisted
to the same thirteen phrases. Imagination goes in the sentence, never in
brackets.

## One wart worth knowing about

The shared body file teaches "sounds are speech, not movement" with
these examples: *Ehehe~, Haha!, Pfft, Ugh, Ooh*.

Those are **Yuzu's** voice, not facts about a hexapod — but they live in
the shared file, so they land in Coco's prompt too and pull her toward
gyaru noises.

Still not fixed, and now for a different reason. The room change above
already touched that file, so the "don't disturb the A/B" argument is
spent — but changing two things at once means that when the next round
comes back you can't tell which one moved the number. One change per
round is your whole method and it works.

So: fix it next, on its own. There's a test pinning the current
behaviour so it can't drift silently in the meantime. Coco's live round
used "Pfft." well and showed no gyaru leakage, so it isn't urgent.
