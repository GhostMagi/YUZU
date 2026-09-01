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

## What's actually been measured

Being straight with you about this, because the repo is otherwise
careful about it:

- Yuzu v1: **20%** action hit rate. Measured, by you.
- Yuzu v2: **78–83%**. Measured, by you.
- **Coco: nothing. Zero live rounds.** She's built on v2's structure
  and carries its fixes, but that's an argument, not a number.

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

## One wart worth knowing about

The shared body file teaches "sounds are speech, not movement" with
these examples: *Ehehe~, Haha!, Pfft, Ugh, Ooh*.

Those are **Yuzu's** voice, not facts about a hexapod — but they live in
the shared file, so they land in Coco's prompt too and pull her toward
gyaru noises.

I left it alone on purpose: editing that file would change yuzu2's
composed prompt while you're mid-A/B on it, and that would throw away
your 78–83% measurement. Instead Coco's own EXAMPLES carry her register
(`Hm.`, `...`), which a 3B weights more heavily than a word list in a
rule anyway.

**After your v2 A/B closes**, the clean fix is to move those five sound
words out of the shared body file and let each persona demonstrate its
own. There's a test pinning the current behaviour so it can't drift
silently in the meantime.
