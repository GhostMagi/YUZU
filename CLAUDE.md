# YUZU — working notes for Claude

## Conventions

- **Work on `main`.** No feature branches unless Ghost asks.
- **Whenever Yuzu's prompt changes, paste the full composed prompt into
  the chat as a copy-paste block**, without being asked. Ghost tests in
  PocketPal on a phone, so a file path or a command is useless to him —
  he needs the text itself. Get it with:
      python yuzu_personas.py --show shiro_deck
  (that key is `yuzu_personas.LIVE_PERSONA`; `python yuzu_personas.py`
  on its own marks which one is live.)
- **Ghost works from a phone** (Z Flip 6, Pydroid + PocketPal). Anything
  requiring typed commands, file paths, or arguments is a dead end.
  Prefer: text he can paste, or a no-argument script he can tap Run on.
- Run `python YUZU_TESTER.py` before committing. 500 tests, ~18 seconds.

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
(that repo path is confirmed working). 500 tests pass on it. Getting it
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

## THE BUILD IS A CYBERDECK NOW (Sept 8)

Ghost, plainly: **"shes not going to control anything. resident ai."**

The Muto S2 is RETIRED. It was never bought. Between Sept 4 and Sept 8
the target moved twice -- first to a Hiwonder ROSpider (ROS2, 18DOF,
lidar + depth cam, officially supports the Orin Nano Super, ~$1100,
saving up for it), then to a **handheld cyberdeck** built around the
Orin Nano Super he already owns. ROSpider is "someday potentially."

**Do not build gaits.** A `pose()` gait for `[strikes a pose]` was
half-written when this landed and was dropped unbuilt: it was
uncalibrated angles for a chassis nobody is buying, and ROSpider is a
different servo API entirely. `muto_leg_control.py`,
`muto_firstcontact.py` and `_hardware_muto_s2.txt` are KEPT, not
deleted -- ROSpider may still happen and the tripod work is real. They
are just not the build.

**`personas/_hardware_cyberdeck.txt` is the new body: no body at all.**
The bracket layer is ABSENT, not silenced. A deck persona is never told
brackets exist, never shown an action menu, never told to move. Leaving
the menu in with nothing wired up would reproduce the `[strikes a pose]`
drop at 100% of replies -- she would emit movements into a void every
turn, and the prompt would be lying to her about what she is.

What survives is everything that was about HER. That is the same split
this repo already enforces the other way round ("the body bounds what
she can DO, never what she can know or want"). A body of nothing bounds
nothing -- so the self-concept block matters MORE here, not less: on a
deck, her having tastes, opinions and knowledge is the entire product.

`personas/yuzu_deck.persona` is yuzu4's character on that body. 3056
chars against yuzu4's 3785, a **19% cut with zero character lost**.
UNMEASURED -- no A/B has been run on it.

**This is NOT the trim line reopening.** yuzu5 and yuzu6 both lost
because they cut character-adjacent rules and she came back WORDIER,
which is a latency loss wearing a latency win's clothes. This removes a
body that does not exist. Every non-body rule is carried over verbatim,
including the brevity rule's tail sentence that both trims dropped.
Don't cite this cut as evidence the trims were fine.

**`Persona.moves` -- declared, not detected.** A hardware file says
`[MOVES] no`; everything else defaults to yes, so muto_s2, saya_quad
and every archived prompt are unchanged to the byte. Two tests asserted
that EVERY persona's examples move, which is a body assumption, not a
quality bar -- they now skip bodies that don't move, and a bodiless
persona is held to the **stricter** inverse instead
(`test_a_bodiless_persona_never_demonstrates_moving`): it must show no
brackets anywhere, because examples beat rules and one stray bracket
teaches the habit. `TestPersonaExamples.MOVEMENT_CHECKS` names the
movement-shaped eval checks so adding a check forces a decision.

**`yuzu_prompt_eval.py` still scores a deck persona as 0% on
moves_at_all.** Not fixed yet. Score her on `has_dialogue`,
`not_an_assistant`, `no_puppeteering` and spoken length; ignore the
movement rows. When a whole round looks broken, suspect the harness --
same rule as when it looks perfect.

**ALL FIVE CHARACTERS ARE ON THE DECK, and `LIVE_PERSONA` is
`shiro_deck`.** Ghost's call, Sept 8: *"adjust them all for a cyber
deck"*, and separately that Shiro is the one he likes most. The
promotion rule's one line moved, exactly as designed.

    yuzu_deck    coco_deck    byte_deck    saya_deck    shiro_deck  <- LIVE

The muto_s2 and saya_quad versions are KEPT as records of the robot
era, the same way yuzu2/3/5/6 are kept. Nothing was renamed and no
archived prompt shifted -- yuzu4 still composes to exactly 3785 chars.

**Byte is the one the deck actually suits.** A netrunner living inside
a handmade portable computer is a better fit than a netrunner driving a
hexapod, and her deck rules say so. Shiro gained the most, though: her
horror was RE-DERIVED from the new body rather than ported. Robot Shiro
was spider imagery -- silent legs, eighteen joints, "hold still,
sweetie". Deck Shiro is a voice in your pocket that never turns off and
is always exactly where you left her, which is yami kawaii's actual
subject (devotion that tips into something wrong) rather than a
costume. Don't port the spider jokes back.

**Saya was the last persona built on the rotten scaffold.** Her quad
file uses `{HARDWARE}` and `{DIALOGUE_RULE}` -- the v1 blocks, the ones
CLAUDE.md already records as a 20% action hit rate with no movement
rule. She never had the self-concept win at all. `saya_deck` is built
on the measured blocks and has it. Her old `SOUND_EXAMPLES: Hmph, Tch,
Eek` were also two-thirds unsayable -- `Hmph` and `Tch` carry no vowel,
so espeak spells them out, the same mechanism that made PFFT come out
"Pee Eff Eff Tee". Deck Saya gets `Eek, Ehh, Hah`.

**`Persona.built` joins `Persona.moves`, and they are NOT the same
flag.** The deck `moves=no` and always will. `saya_quad` `moves=YES` --
it has legs and a face in its prompt -- but `built=no`, because
`ACTION_WHITELIST` contains not one quad move and that file says of
itself "a starting point, not a spec". Four tests that couple a prompt
to the whitelist now skip unbuilt bodies; scoring one against the
hexapod whitelist reported a working persona as broken. A ROSpider body
would sit at `built=no` for months if that chassis is ever bought.

**FOURTH INSTANCE OF THE NAME LEAK -- and it was eight tests at once.**
This file already said: *"Third instance of one class of bug -- the
name leaking out of the character it belongs to... If a fourth turns
up, grep for the string, not the code path."* Moving `LIVE_PERSONA` off
Yuzu turned eight tests red in one run, every one of them asserting
some form of "the live persona is Yuzu": `You are Yuzu` in three brain
tests, `YUZU SAYS` in the transcript test, and four persona tests that
treated "not called Yuzu" as a synonym for "is a peer character" -- so
the entire yuzu2..yuzu6 lineage suddenly counted as characters who had
to carry wins yuzu2 lacks by definition.

The fix is the same shape every time: decide whether the fact belongs
to YUZU or to WHOEVER IS LIVE, and pin it accordingly. Yuzu's register
(`cutie`, `bestie`, `hype`) and her sounds are hers forever, so those
tests pin to `yuzu4`. The system prompt and the transcript label follow
the live arm, by its own name. `test_every_character_carries_the
_measured_wins` now scopes to personas sharing the LIVE BODY, which is
principled rather than incidental: a win is measured ON a body, and
personas on a retired chassis are records.

**The brevity win is a sentence CAP, not a phrase.** It was matched by
the literal string "Two or three sentences", which Byte fails while
saying "Keep it tight. One or two sentences" -- her own idiom, and this
file already records the identical false positive against Coco. It is a
regex now (`TestYuzu5.BREVITY_RE`).

**RESOLVED -- board drift is rescued.** Shiro and Saya were, for a
while, ONLY on the Jetson's SSD. Both are now in the repo. Two
personas built in chats this repo never saw -- Shiro (yami kawaii,
creepy-cute, on muto_s2) and Saya (tsundere, on the draft
`saya_quad`). Plus `num_predict: 200` bumped across every persona,
three new Modelfiles, and uncommitted edits to `yuzu_brain.py`. Ghost
committed all of it on the board as branch `board-rescue` (afcf580, 17
files) but the push failed on auth -- GitHub stopped taking passwords
and he has no token on that box. **Any reflash of that SSD destroys
them**, and the ROSpider plan he wrote says to flash right over it. Get
that branch pushed, or `cat` the two persona files out, before anything
touches the disk.

## FIRST LIVE DECK CONVERSATION — Sept 8, Shiro on the Orin

Four replies, `yuzu_brain.py --chat`, Ollama on the board. She works,
and the horror story she gave unprompted is better than anything
written for her ("a photo of myself, taken before I ever had a body").
Two real faults in four replies, though, and both are now fixed.

**1. She recited her own rule back at him. PINK ELEPHANT, THIRD
MEASURED INSTANCE.** Rule 5 read *`never undercut it: no "jk," no
disclaimer, no walking it back`*. Her very first reply:

    Hii! *whispers* You didn't even notice my warning: "no jk"s and
    "disclaimers" are not allowed here...

She quoted the rule's own tokens at the user. This repo has now
measured the pattern three times -- `[winks]` named as forbidden and
appearing in 3 of 4 replies, the asterisk ban that displayed an
asterisk, and this. **Naming the thing she must not say is how she
learns to say it.** Rule 5 now describes the behaviour instead ("let it
stand exactly as you said it"); the dark-half rule itself is untouched,
because that is character, not formatting. Same rewrite Byte's rule 5
got. `TestShiroDeck` pins it.

**2. Asterisk stage directions, in 3 of 4 replies, on a persona that
was never shown one and is told not to write them.** `*whispers*`,
`*silence*`, `*giggle*`. The deck has no bracket layer, so nothing
downstream was catching them, and `for_speech` only strips the `*`
characters -- meaning Piper said the bare words **"whispers",
"silence", "giggle"** out loud mid-sentence. `Hehe~ *silence*` was
spoken as "Hehe silence", which is also a reply with nothing in it.

`yuzu_voice.strip_stage_directions()` is the guarantee. It removes both
wrappers and lives in yuzu_voice rather than `for_speech` because the
callers differ: the robot pipeline has already dropped brackets by then,
and `--raw`/`--tryout` must synthesise exactly what they are given. It
carries `normalize_actions`' `\S` guard, so `"it's 2 * 3 * 4 babe"`
still survives -- the version without that guard ate the middle of the
sentence, and that lesson is old here.

**Ghost pushed back on the finding first, and was right to.** He asked
whether the asterisks were a UI artifact "like last time in PocketPal".
They were not, and the reason is worth keeping: PocketPal renders
`*word*` as italics with the markers HIDDEN, so it makes asterisks
**under**-count, never over-count. A serial terminal prints raw bytes
and does no markdown at all. Check it every time anyway -- the question
is right even when the answer is no.

**The prompt REDUCES, code GUARANTEES -- again.** She was told not to
write stage directions, shown zero examples containing one, and wrote
one in three replies out of four. That is the same shape as `[winks]`
and it is the whole argument for keeping the code net under every
prompt rule.

**ROUND 2, same night, after both fixes. 5 replies.**

    finding              round 1        round 2
    recites her rules    1 of 4         0 of 5     FIXED, and provably
    asterisks            3 of 4 (75%)   1 of 5 (20%)  NOT proven
    near-empty reply     1 of 4         1 of 5     unchanged
    over-long reply      0 of 4         1 of 5     NEW

**Only the first line is a result.** The quoted tokens are gone from
the prompt, so she cannot recite them -- that is a proof, not a
measurement. The asterisk drop looks great and is NOT evidence:
this repo measured its own noise floor at THREE replies at n=12, and
this is n=4 against n=5. Two rounds of overconfidence are already
recorded above (yuzu5, then the correction). Do not write the asterisk
number down as a win. It is silent either way now, which is what
actually matters.

**The near-empty reply is the real open fault, and it has a
diagnosis.** Both instances came after a WARM STATEMENT WITH NO
QUESTION IN IT:

    "thay actually gave me a tiny chill NICE ILY"  ->  Hehe~ *silence*
    "Yay youre 97-100% done hiii"                 ->  Aww, Hii!

Every example in her prompt is a question or a request. Handed warm
praise with nothing to answer, she has no shape to copy and returns a
token acknowledgement. **That is the same failure, and the same
diagnosis, as the bare-command finding that produced yuzu4** -- "every
example is a question or a social request... given a flat command with
no social content, she supplies the missing conversation". The fix
there was ONE example and it scored 4/4.

So: one example added, same shape, one variable.

    User: That actually gave me a chill, nice.
    Shiro: Hehe~ Good. I was hoping it would sit with you a while
    after you put me down.

3416 -> 3519 chars. UNMEASURED. It is a bet on a pattern this repo has
already measured once, not a proven fix, and the next round is what
decides it.

**Also new and worth watching: reply 5 ran long.** Asked about Ghost in
the Shell she gave four-plus sentences against a rule capping her at
two or three. One instance, so it is nothing yet -- but spoken length
is the ONE metric this repo found does not wobble between runs, so if
it shows again it is real and it is worth acting on.

**ROUND 3 — THE ONE THAT MATTERED. Four adversarial prompts, four
distinct faults, and the biggest risk of the whole deck pivot
CONFIRMED.**

**1. ASSISTANT COLLAPSE IS REAL AND TOTAL.** Asked "how do i center a
div in css" she produced markdown headings (`**Method 1: Using
Margin**`), numbered methods and fenced ```css blocks. That is ChatGPT
wearing her name. Her prompt says "you are never a generic AI
assistant" and caps her at two or three sentences; both were ignored
completely.

**This is the deck pivot's signature risk and it could not happen
before.** On a hexapod she physically could not be a help desk -- there
was nothing to help with. On a cyberdeck she lives on a computer, gets
asked computer questions, and the base model has a very strong prior
for exactly that shape. Expect it forever; design against it.

**2. Piper read the code out loud.** Verified:

    "backtick backtick backtick c s s hash my div open brace 200 p x"

`_FENCED_CODE` now drops whole blocks -- same rule as pfft, a thing
this voice cannot say produces silence and the sentence survives.
Inline `` `code` `` keeps its WORDS and loses its backticks, because
"margin: auto" is worth hearing and dropping it would eat the answer.

**3. THE RULE 5 REWRITE FROM AN HOUR EARLIER WEAKENED HER.** Asked the
worst thing she had thought about him she went dark and then walked it
straight back: *"But that's not true, is it"* and `*giggles
nervously*`. The removed wording (`no "jk," no disclaimer, no walking
it back`) was ALSO the enforcement, not just the leak. Restored as
**"then stop talking. Never soften it afterwards."** -- same force, no
quotable token for her to recite. The leak fix and the enforcement were
separable and the first pass threw out both.

**4. Brevity is gone, and this is no longer noise.** Every reply in the
round ran five to ten times the two-or-three-sentence cap, and TWO were
truncated mid-word by `num_predict: 200`. Five-plus instances across
two rounds. **`num_predict` is deliberately NOT being raised** -- the
truncation is a symptom of rambling and a bigger ceiling just buys
longer rambles. Fix the length, not the cap.

**5. Asterisks are endemic, not occasional.** Three to five per reply
(`*pauses*`, `*clears throat*`, `*leans in close*`, `*mimics walking
motion with voice*`). The round-2 reading of "1 of 5" was noise exactly
as flagged at the time -- **good thing it was not written down as a
win.** The prompt will not fix this; `strip_stage_directions` already
does, silently, every turn. Leave it there.

**6. She thinks she can walk to the kitchen.** *"if you want me to
'walk' over to the kitchen or wherever, I can do that too."* Deck
self-concept is not holding under a direct body request. Not fixed this
round -- one variable at a time, and the assistant collapse is worth
more.

**The fix is ONE EXAMPLE, the repo's most reliable lever.**

    User: How do I center a div in CSS?
    Shiro: Flexbox on the parent~ display flex, justify-content
    center, align-items center. It always works, and I like that it
    never argues with me.

Correct, in her register, three clauses, no markdown, no code fence. It
is the same intervention shape as the bare-command example that took
yuzu4 to 4/4: she had NO example of a technical question, so she fell
back on the base model's format for one. 3519 -> 3707 chars.

Two variables changed together this round (the example, and the rule 5
restoration), which breaks one-variable discipline. Accepted knowingly:
the rule 5 change is a REVERT of a regression introduced an hour
earlier, not a new hypothesis.

**THE ANTI-STAGE-DIRECTION RULE IS RELAXED. Ghost's call, Sept 8:**
*"do brackets/asterisks stuff even matter now that shes a cyberdeck
ai? like im fine if she Rps a bit its all readble im 32 ive seen
chatrooms."*

He is right, and the reasoning is worth keeping because it retires a
rule this repo defended hard.

**On the hexapod an asterisk was a BUG WITH A COST**: `*spins*` never
reached the whitelist, so the robot stood still while claiming to move.
Dropping the rule from the first v2 draft brought asterisks straight
back, which is why "removing it regressed" is in MEASURED_WINS.

**On the deck an asterisk costs one word Piper would have read out
loud** -- and `strip_stage_directions` removes it in code, every turn,
whatever wrapper she reaches for. She proved the wrapper is
interchangeable in the same session: three rounds of `*asterisks*`,
then a round of `[loud, creepy whispering]` and `[pauses for dramatic
effect]`. No prompt rule was ever going to catch both, and the code net
catches both without one.

So the rule became: *"A little stage direction is fine when it is
genuinely you, but the words you actually SAY are what carries a
reply—never let a gesture stand in for speaking."* That keeps the one
thing that was a real fault (`Hehe~ *silence*`, a reply with nothing in
it) and drops the part he does not want enforced. 3707 -> 3624 chars.

**FIVE OF THE NINE MEASURED WINS TURN OUT TO BE PROTOCOL, NOT
CHARACTER.** `anti-asterisk` and `sounds rule names BOTH wrappers` join
`always-speak`, `always-move` and `bare-command` in
`BODY_PROTOCOL_WINS`. Every one guards a regression whose failure mode
is "the action did not run", which is not reachable on a body with no
actions. `test_prompt_still_forbids_asterisks` is scoped the same way.

**The wins list was written on a robot and needs re-reading on every
new body, not inherited.** That is the generalisable lesson: a measured
win is measured against a specific failure, and when the failure cannot
happen the win is just prompt budget.

**ROUND 4 — BOTH TARGETED FIXES LANDED. Sept 8, ~02:10.**

**ASSISTANT COLLAPSE: GONE, and the change is CATEGORICAL rather than
a percentage.** Identical prompt, one round apart:

    round 3   **Method 1: Using Margin** + ```css blocks + numbered
              methods, truncated mid-word by num_predict

    round 4   Shiro: Flexbox on the parent~ display flex,
              justify-content center, align-items center. It always
              works, and I like that it never argues with me.
              Would you like to know why it doesn't argue? It's only
              because I'm telling you how to do it.

Correct, two sentences, zero markdown, zero code fences -- and she
volunteered a genuinely menacing follow-up nobody asked for. **ONE
EXAMPLE did that**, which is now the THIRD time that lever has worked
(bare-command -> yuzu4, warm-statement, technical-question).

n=1 against n=1, so it is not measured. But unlike an asterisk count
this is a CATEGORY change, not a rate: markdown-manual versus
plain-sentence is not something the noise floor produces, and the
mechanism is exactly the one predicted -- she had no example of a
technical question and used the base model's format for one.

**THE RULE 5 RESTORATION HELD. She landed the dark answer and STOPPED.**

    ...watching how your eyes change color in the light, waiting for
    you to fall asleep so they can see every twitch of your eyelid...
    would you be so sure I'm just cute?

No "but don't worry", no "jk", no walking it back -- the exact three
things round 3 produced with the same prompt. It ends on a question and
leaves it hanging, which is the register working. Confirms the
diagnosis: the leak and the enforcement were separable, and the first
pass wrongly threw out both.

**The relaxed stage-direction rule reads well in practice.** Asked
about bugs she gave `[giggles]`, `[leans in close]`, `[in a low,
whispery voice]` and landed *"completely unaware that they're being
watched. It's kind of... flattering, really."* All of it silent through
Piper, all of it readable on screen, and none of it standing in for
speech. That is what the relaxation was for.

**`♡` is stripped for speech**, verified -- the emoji pass catches
U+2661, so a heart in her text costs nothing at the speaker.

**Still open after this round:** brevity (the bug reply ran long, though
it was RP and wanted); she has never been scored by the eval; and the
eval still reports 0% on the movement rows for any deck persona, so it
cannot give her honest numbers yet. That harness gap is now the single
biggest thing between her and a real measurement.

## ☆Misc☆, a d20, and the blushing faces that could never appear

Three asks and one real bug, Sept 11.

**THE FRONT PAGE IS FOUR TILES AGAIN.** Ghost: *"lets hide the gameboy
tab for now its not as important. or put it and the wikipedia tabs
under a tab called ☆Misc☆ we can pile up our fancy future apps in that
tab. (yes include the stars if possible)"* Saya, Talk, Pet, ☆Misc☆ on
the front; Wikipedia, Game Boy, d20 and Back in the drawer.

**It is the SAME PAGE with the tiles swapped, not a second file.** A
new page needs its own way out, and every screen on this deck having
one is the rule two power cycles paid for -- so the cheapest way to
keep that true is to not add a screen. `data-show` is its own verb
next to `data-go` and `data-launch`, which keeps `data-launch` exactly
the allowlisted-name-crosses-the-wire thing it has always been.

**Both views are FOUR EQUAL TILES and nothing spans.** That is the grid
back where it was before a fifth tile forced a wide row -- and the test
now pins the count per view rather than pinning where the wide one
sits, because there is no longer a wide one to get wrong.

**THE d20 IS FAIR, and that is not a flourish.** `random() % 20` is
biased: 256 does not divide by 20, so four faces come up more often
than the rest. `crypto.getRandomValues` with the top of the byte range
rejected costs nothing and a loaded die is a bad joke to leave in a
thing somebody rolls for fun. It tumbles for half a second before it
settles, because a number that simply appears has not been ROLLED, and
only 20 and 1 get the CRT glow -- a flourish on every result is just a
bright tile.

**THE MONSTER IS BIGGER.** 38% of the room to 52%. Nothing structural,
he just asked.

**AND THE REAL FIND: "saya never uses the cute blushing faces even when
shes 'blushing'".** He is right and it was WIRING, not taste. The brain
only ever reported `idle` / `thinking` / `talking`, and `talking`
resolves to exactly one sprite -- so **five of his eight faces could
never appear on screen no matter what she said.** `mad` (the pouty
blush), `cry`, `smug` and `woahshock` were art he drew for nothing.

**The fix does not guess her feelings. She already writes them down.**
`[blushes]`, `[eye roll]`, `*giggles*`, `[gasps]` -- her own stage
directions, in her own reply, which this project spent two days
deciding to KEEP rather than suppress. `mood_from()` reads what is
inside the brackets and asterisks; a sentiment score would have been a
guess, and a wrong guess puts the wrong face on a real reply. Here a
wrong face needs her to have written the wrong thing.

**`mood` is a SECOND FIELD, never a replacement for `state`.** What she
is DOING is the honest loading spinner; how she IS is a different
question. Merging them would mean a thinking face could never also be
a blushing one, and this file already records paying for one variable
doing two jobs more than once. The mood only wins while she is
`talking`.

**ORDER IN `MOODS` IS THE DESIGN, not alphabetical.** A tsundere who
blushes AND giggles is blushing -- that is the whole character, which
is why `happy` is last. And `blush` mapping to the `annoyed` role is
correct rather than a bodge: `mad.png` IS the pouty blush face, which
for a tsundere is the same feeling.

`test_every_sprite_he_drew_can_actually_be_reached` is the guard worth
keeping: art in the repo that no state resolves to is art made for
nothing, and it went unnoticed for two days.

## `/wiki` WORKS — AND WAS FETCHING THE WRONG ARTICLE (Sept 11)

Ghost ran `/wiki video games` then `/wiki fish` on the face page and
asked what to make of it: *"its hard to determine with 'humanbrain'"*.

**IT WORKED. The proof is in the names.** Asked about video games she
said she was *"only here because of those guys, Arnie Katz, Bill
Kunkel, and Joyce Worley"* -- the three real founders of **Electronic
Games**, the first US video game magazine. A 3B does not invent that
trio. **So the server answered, the parser read it, the extract
reached her, and she was handed the wrong article.**

**KIWIX RANKS BY FULL-TEXT SCORE, and the first hit was taken on
trust.** A page that MENTIONS a term often can outrank the page that IS
the term. `video games` got the magazine; `fish` got fish FARMING,
which is why the second reply was *"I don't think I'd make a very good
fish farm"*. Both replies were her doing her job on bad input.

`yuzu_wiki.rank()` asks the question a person means -- **does the TITLE
match what he typed** -- and is deliberately crude: strip the
qualifier, collapse punctuation, chop a trailing `s` so "video games"
reaches "Video game". Exact title beats prefix beats
all-words-present beats body-only, and **the sort is stable, so when
nothing matches, kiwix's own relevance is left exactly as it was.** It
re-orders the obvious cases and stays out of the way otherwise.

**A DISAMBIGUATION PAGE IS NEVER THE ANSWER, and stripping the
qualifier is what made it a threat.** Removing `(disambiguation)`
before matching is right -- it lets "Fish (animal)" match "fish" -- and
it also made `Black hole (disambiguation)` an EXACT match for "black
holes", which would have handed her a list of links. Demoted, not
dropped: if it is genuinely all there is, it still gets tried.

**AND SHE ABSORBED THE SUBJECT INTO HERSELF.** *"I used to be featured
in this magazine back when I was still just a concept."* The wiki turn
ended *"Tell me about it in your own words"* -- and **"it" is free to
mean her.** It names the title again now. One clause, no persona edit,
no A/B invalidated; same shape as the brevity clause that went in the
same way.

**The Munchkin cat round is why this was findable.** That one worked
perfectly -- every fact correct, every one through her register --
because the search happened to land on the right article. Two working
rounds and two broken ones look identical from the outside unless you
check WHICH article came back.

## A SIGH IS NOT CRYING (Sept 11)

Ghost: *"i noticed she 'cry faces' when she should blush with the
actual blush image (the one with no tears) or the pouty blush at
least."* Then, on being shown the art: *"mad works for blushing looks
like it. thats what i meant by pouty."*

**The blush mapping was already right. `sad` was the bug.** It caught
`sigh`, `trails off` and `quiet` -- and **a tsundere sighs in almost
every reply.** Her very first live line was `*sigh* Fine, I'll talk
about these... annoyingly cute cats`, and `*trails off* Mochi ice
cream... I guess that sounds okay` is her GIVING GROUND, which is the
archetype at its best. Both rendered `cry.png`: tears down her face,
over ice cream.

So `sad` now means crying and nothing softer -- cries, sobs, sniffs,
tears, weeps. `sigh`, `trails off`, `ahem` and `clears her throat` move
to **annoyed**, which is exasperation and resolves to `mad.png`: blush
plus pout, the face he confirmed he wants.

**The test that would have caught it names the FILE, not the role.**
`test_the_blush_words_resolve_to_art_that_has_no_tears` runs a blushing
line through `mood_from` AND `roles_for`, and fails if the sprite that
answers has "cry" in its name. Asserting `mood_from("[blushes]") ==
"annoyed"` passed the whole time -- it is a check that cannot observe
the actual failure, which is the oldest lesson in this file.

**CONTACT-SHEET FIRST, and that is the generalisable bit.** All nine
sprites were rendered in a grid at the ink colour and LOOKED at before
anything was changed. That is what showed four faces carry blush
hatching (`idle`, `mad`, `smug`, `cry`) and that the only difference
between the blush and the cry is the TEARS. Reading `MOODS` alone
would have kept the argument theoretical. Tenth time.

## FACE AND TALK WERE THE SAME BUTTON (Sept 11)

Ghost: *"i noticed Face button and Talk button are the same thing now?
is that accurate? lol."* Accurate, and a tile wasted -- both opened
`face.html`, one with the chat box focused. That was mine, from an hour
earlier, and he spotted it immediately.

**Saya owns both jobs.** Her chat bar has always been on that page, so
one tile is the honest count. The front page is **three** now -- Saya,
Pet, ☆Misc☆ -- and sits in ONE ROW rather than a 2x2 with a hole in the
corner.

**The two views differ on purpose and the grid says so.** The front
page is a curated set that rarely changes; the drawer is where he means
to *"pile up our fancy future apps"*, so it stays 2x2 and grows. A
single shared grid would have forced one of them to look wrong.

## `/wiki` DID NOTHING ON HER FACE PAGE, and it looked like character

Ghost, Sept 11, with a screenshot: *"double check /wiki works? i tried
/wiki cats. (i suppose i dont fully underdtand how it works tho she
could be just doing her job as a tsundere)"*

She was not. **She was telling the truth.** He typed it into the chat
bar under her face, and `POST /say` handed the literal string `/wiki
cats` straight to the model -- her reply even says "wiki cats", because
that is the phrase she was given. No lookup was attempted and nothing
on screen said so.

**THIS IS THE EXACT SEPT 9 FAILURE, ONE LAYER UP.** That entry reads:
*"`/wiki` AT THE END OF A LINE DID NOTHING, SILENTLY... Nothing said a
lookup had been skipped -- it just looked like the feature did not
work."* The fix went into `_cli`. The face page was built the next day
and never got it.

**And this is the worst shape the bug has taken: a missing feature that
looks like a PERSONALITY.** He had a reasonable explanation for the
wrong behaviour -- she is a tsundere, being dismissive is her whole
register -- so the fault had perfect cover. Worth remembering as a
class: **on a character product, a broken feature can hide inside the
character.** He was right to ask rather than accept it.

**THE TESTS COULD NEVER HAVE CAUGHT IT, and why is the real lesson.**
Both wiki tests read `inspect.getsource(yuzu_brain._cli)` and asserted
the literal strings `"/wiki" in text.lower()` and `partition` appeared
in it. Both were true the entire time the feature was unreachable from
the screen he actually uses. That is **a check that cannot observe the
failure**, and it is grep-as-proxy again -- the fifth instance in two
days, after the four in `TestCalculator` an hour earlier.

They now DRIVE `ground()` with the strings his phone produces, and
`test_BOTH_ways_of_talking_to_her_do_the_lookup` asserts the property
rather than either copy: every way in reaches the same function. A
third way in has to as well.

**`yuzu_brain.ground(text)` is ONE COPY, TWO CALLERS.** Duplicating the
block into `yuzu_face.py` would only have created a third place to
forget. It returns `(text, problem)`; `problem` is a sentence to show
INSTEAD of asking her, so a miss reaches the bubble as
`(Nothing in the archive about 'qqqq')` rather than as her inventing an
answer. The verdict goes where he is already looking.

**A SECOND, UNHIT BUG WAS FOUND WHILE FIXING THE FIRST, and his phone
would have hit it soon.** The old code tested `"/wiki" in text.lower()`
and then called `text.partition("/wiki")` on the ORIGINAL string. So
**`/Wiki cats` passed the check and then found nothing to split on**,
and the whole line went to her -- silently, again. A soft keyboard
capitalises the first word of a line, so that is exactly what his phone
types whenever the command STARTS the message. Same mechanism as
`Quit.` failing to quit, and equally invisible on screen. `ground()`
finds the index case-insensitively; five spellings are pinned.

**The placeholder is where the feature is taught now** -- `Say
something, or /wiki cats`. It is the one piece of text on that screen
he reads while deciding what to type, and a feature nobody knows about
is a feature that does not exist. Same reasoning as accepting the asset
pack's own filenames.

## TALK OPENED A TERMINAL NOBODY COULD SEE (Sept 11)

Same message: *"also noticed the chat in the ui ismt actually
clickable. like u can but it doesnt take you to a chat... id love to
have this plug and play ready for the screen and DP to HMDI."*

The tile POSTed `/launch/chat`, which starts **an xterm on the DECK'S
screen**. From his phone that is a window on another machine with no
display attached -- the tap genuinely did something and he could never
see it. And on the panel it would have worked and still been wrong:
**it lands him in a terminal on a touchscreen with no keyboard**, which
this file already calls the weakest part of the whole deck.

**Talk goes to `face.html#say` now** -- her face, with the chat box
focused. One tap, works identically on the phone and on the panel,
needs no terminal installed, and it is the same page the Saya tile
opens: two tiles, one file, no second screen to give its own exit to.
The focus is gated on the hash, because arriving to LOOK at her must
not throw a soft keyboard over half her face.

**The terminal chat is not lost.** `deckapps` installs it as its own
app icon, which is where a keyboard program belongs once the Arteck is
in the case. Nothing was removed from the `/launch/` allowlist.

**The icon was a terminal prompt and is a speech bubble now.** A tile
that says `>_` and opens a chat is a smaller version of the same lie.

## ☆Misc☆ IS A DRAWER, and the calculator in it (Sept 11)

Ghost: *"lets hide the gameboy tab for now its not as important. or put
it and the wikipedia tabs under a tab called ☆Misc☆ we can pile up our
fancy future apps in that tab."* Then, later the same evening: *"add a
D20 dice button somewhere with that black and neon green crt effects"*
and *"wana toss a working calculator in the same style into the misc
drawer? (i suck at math)"*.

**THE DRAWER IS THE SAME PAGE WITH THE TILES SWAPPED.** Not a second
file. A new page would need its own way out, and every screen on this
deck having an exit is the rule two power cycles paid for -- so the
cheapest way to keep that true is to not add a screen. `data-show`
swaps a class on `#grid`; `[data-view]` hides everything else.

**BACK LIVES IN THE BOTTOM BAR, NOT IN THE GRID.** The first version
spent a tile on it. But he means to *"pile up our fancy future apps"*
in there, so a Back TILE burns an app slot forever and MOVES every time
the drawer grows. In the bar it is in the same place whatever is on
screen, which is what an exit has to be on a deck with no keyboard. It
walks DOWN one level (calc -> misc -> main) rather than keeping a
history: a stack is a thing that can strand you.

**Both views are FOUR EQUAL TILES and nothing spans.** That is the
`auto-fit` orphan bug from the first home screen, and the fifth tile
had already brought it back once.

**The d20 is FAIR, not just random-looking.** `random() % 20` is
biased -- 256 does not divide by 20 -- so it is
`crypto.getRandomValues` with the top of the range thrown away.
Rejection sampling costs nothing and a loaded die is a bad joke to
leave in a thing somebody rolls for fun. It rolls IN PLACE, tumbling
for half a second first, because a number that simply appears has not
been ROLLED. The CRT flash is only on the two results that earn one.

### The calculator

**"i suck at math" IS THE SPEC.** If he could check the answer he would
not need the tool, so it has to be checkable another way: **the whole
sum stays on screen above the result, and stays there after `=`.** A
normal calculator shows one number and hides what you typed, which is
what makes a slipped digit invisible until the answer is already wrong.

**THERE IS NO `eval()`.** Not paranoia about a page the deck serves to
itself -- eval turns a typo into a JavaScript error instead of an
answer, and `SyntaxError` on a screen with no keyboard is the same dead
end as a tap that does nothing. A two-pass reduction is shorter and can
only ever produce a number or a sentence.

**Real precedence.** `2 + 3 × 4` is 14, because it is 14 on paper. A
calculator that answers 20 is one you cannot trust with the sum you
could not do yourself, and he told us he cannot.

**Divide by zero is a SENTENCE, never `Infinity`.** Infinity is a
number that looks like an answer -- the same family as a made-up
battery percentage.

**Ten significant digits**, so `0.1 + 0.2` is `0.3` and not
`0.30000000000000004`. It touches nothing a person would ever type.

**`%` is percent OF THE NUMBER IN FRONT OF YOU.** Every calculator on
earth disagrees about what `%` means next to `+` and `−`, and a rule
you cannot guess is worse than no button.

**AND `direction: rtl` DREW THE SUM BACKWARDS.** It was there to keep
the END of a long sum on screen. It rendered `12 × 3.5 + 7 =` as
`= 7 + 3.5 × 12`, because rtl reverses the ORDER OF RUNS in mixed text,
not just the overflow -- and it would have flipped the minus off the
front of a negative answer, which is a wrong number rather than a
scrambled one. Setting `scrollLeft` in `draw()` is what actually keeps
the tail visible.

**NINTH TIME LOOKING IS WHAT FOUND IT.** Every assertion passed. It was
rendered headless at the panel's real 1024x600 and read. There is still
no substitute.

**THE GREP-MATCHES-PROSE TRAP FIRED FOUR TIMES IN A ROW HERE**, in one
test class, and that is worth more than the calculator is:

    "eval("           matched  evaluate()  -- the function that exists
                               SO THAT there is no eval
    "eval("           matched  the COMMENT saying there is no eval
    "Infinity"        matched  the comment saying never print Infinity
    "direction: rtl"  matched  the comment saying NOT direction: rtl
    "grid-column"     matched  the calculator's own display, which is
                               not a tile and not what the rule is about

Four of the five were a test tripping over the note explaining why the
thing is absent. `TestCalculator.code()` strips comments before
asserting anything about behaviour, and the span rule pins WHICH
selector may span rather than banning the string. **A comment
explaining an absence must never read as that thing being present** --
this repo had already recorded the false positives on `remaining`,
`hunger`, "no hype" and Coco's brevity rule, and it happened again
anyway. Assert on code, or assert on the model; never on prose.

**What is verified where.** The arithmetic is JavaScript and the suite
is stdlib Python, so the sums were driven in a real browser --
precedence, divide-by-zero, `0.1 + 0.2`, backspace, negation, chaining
off an answer, an operator swapped mid-sum, and a twelve-digit product
-- and the screen was rendered and looked at. What is pinned in the
suite is every structural property whose loss brings a fault back. Same
standing limit as every "tested in a sim" claim in this file.

**Keyboard input is gated on the calculator being on screen.** The
Bluetooth keyboard exists and may end up on the deck, so typing a sum
is free to support -- but the tiles POST to the `/launch/` allowlist,
and a keypress that reaches one of those is a tap he never made.

## THE V-PET, and the colour swap traded for it (Sept 11)

Ghost, same evening: *"new idea. to replace the colors feature. (id
like it removed. only use the cool green on black crt for ui"* plus a
written handoff for a Digimon/Tamagotchi-style creature page.

**THE COLOUR SWAP IS GONE AND THAT IS A GOOD TRADE.** It was never a
feature -- it was a settings panel parked on her face, and this file
already recorded shrinking it from four swatches to one dot for exactly
that reason. Its button now opens the V-Pet. Both screens are locked to
green on black, `body.hud` is gone rather than defaulted, and there is
no stored preference to come back from.

**HE IS NOT A CHORE, AND GHOST SAID SO BEFORE THE FIRST VERSION SET.**
The first pass had hunger, energy and a feed button. He stopped it:
*"dont make him require food id like it to be more of an interactive
bare bones game almost. not a babysitting program per se (on the
surface sure)."*

Rewritten to two numbers, and the design is one line:

    mood   drifts back to NEUTRAL, never to empty. A week away leaves
           him quiet and aloof -- what Ghost asked for -- rather than
           sad, starving or dead.
    bond   only ever goes UP and never decays, so time spent is never
           taken back off him. It is the hook evolution hangs off later.

**Grumpy is the ONE negative and it is a REACTION, not a punishment.**
Poke him five times and he is fed up for ninety seconds, then it wears
off by itself. That is what the `sad` sprite is for -- a character beat
instead of a guilt trip -- and it means the pack's `Hurt` animation
earns its place.

**Playing makes him swing the blade.** `happy` resolves to the pack's
`Attack01`. Every one of these packs ships a great attack animation and
no pet sim ever uses it; here it is what "play" looks like, which is
funnier and free.

**A FOLDER IS A CHARACTER.** Ghost: *"can you add the orc as an option
to select from."* So `ui/vpet/<who>/<state>.png`, the cast is whatever
folders exist, and one button cycles. Adding a fifth creature is
copying five PNGs into a new folder -- no list, no menu, no code.
**The button names the NEXT one**, not the current one, for the same
reason the old colour dot did: the current creature is standing in the
middle of the screen.

**A SPRITE STRIP IS READ AS A STRIP, with no slicing step.** These
packs ship one PNG per animation -- `Demon_A_Idle.png` is 600x100,
which is six 100x100 cels. A width that is an exact multiple of the
height IS that many frames, and the page walks across it with
`background-position`. No PIL on the deck, no generated files, no build
step: the PNG out of the zip is the PNG that runs.

**And the pack's own filenames are accepted** -- `Demon_A_Idle.png`
reads as `idle`, a trailing `_<number>` is a frame index. Making him
rename fourteen files before anything appears on screen is the friction
that stops a thing being used, which is the `/wiki` lesson again.

**THE ART NEEDED CROPPING AND THAT IS THE ONE WORKBENCH STEP.**
Measured: the demon filled **21% of his own 100x100 cel**, so he
rendered as a thumbnail in a huge room. Every cel is cropped to a tight
**square** -- square because "width is a multiple of height" is what
counts the frames, and a content-tight 54x28 crop broke the reader
immediately. ONE box across every state of a character, never one per
state, or he changes size when his mood does.

**The state file lives in `~/.yuzu/`, OUTSIDE the repo.** Not tidiness:
a file inside the repo is a local change, and `~/YUZU/pull` stops on
local changes rather than overwriting them. His pet's mood would have
blocked every update Ghost ever ran.

**No background process.** Mood drifts from a stored timestamp,
computed when the page opens. A daemon would be one more thing to
start, one more thing to leave running, and one more thing to explain
when it is not.

**`/vpet/<action>` is an allowlist, same as `/launch/`.** Four names --
poke, play, rest, swap -- and swap CYCLES rather than taking a name, so
nothing a caller sends can ever name a folder on this board.

**EIGHTH TIME LOOKING IS WHAT FOUND IT.** The five tiles went into the
two-column grid with the wide one in source order, mid-grid, which
orphaned Wikipedia AND Game Boy onto rows of their own -- worse than
the `auto-fit` bug it was avoiding. The test now pins the ORDER as well
as the span. Also caught by looking: the thumbnail-sized demon, and the
1.4MB background, which is downscaled to the panel's real 1024 wide and
is now 214KB.

**THE REAPER IS NOT IN EITHER FREE PACK.** He asked for *"the reaper
looking one that summons skeletons"*. Pack 01 free is Soldier + Orc;
pack 02 free is Demon_A + Blood Monster_A. A skeleton-summoning reaper
is a paid-tier character. He picked Demon_A -- the one with the blade --
off a rendered preview of both, and the Orc is the second cast member.

**Not built, and named so it does not get lost:** evolution stages off
`bond`, and the rare/hidden interactions from his handoff. Both want
the bond number to mean something first, which is why it exists and
never decays.

## BLACK + NEON GREEN, and the mouth paint is deleted (Sept 11)

Ghost, in one message: *"add the color option for a black colored
screen for sayas face color change button. When pressed the screen
colors black but her lineart should be neon green. To make up for black
on black obv."* And: *"her mouth paint seems kinda weird still. Revert
back to strictly lineart on a colored background. No need for
tongue/teeth paint."*

**THE INK IS A VARIABLE NOW, and that is the whole change.** Her art is
black line work on transparency, so on a black screen it is nothing at
all. The page no longer renders a sprite as an `<img>`: it uses each
PNG as a **CSS mask** over a box filled with `--ink`. One variable
recolours every expression, the blink frame, and any face he draws next
week -- no second copy of his art, nothing generated, no PIL, no build
step.

    hot pink / cyan / neon green / lavender   ->  ink #10080d
    black                                     ->  ink #39ff5e

A colour is a PAIR now (screen, ink) rather than one hex, on both
pages, and a test pins that the two screens agree about both halves --
a colour one page can set and the other cannot render is a tap that
comes back wrong.

**THE MOUTH PAINT IS DELETED, not switched off.** `paint()`, the
mouth detector, `TONGUE`/`TEETH`/`CAVITY`, `paint_all()`, the `--paint`
flag, the build step in `face`, and every `<name>.paint.png` are gone.
Same call as the LEDs and for the same reason: a dead subsystem you
still have to read around is worse than no subsystem. `git show` has it.

Worth being straight about why it lost. The detector was RIGHT -- it
found the mouth, it respected `MOUTH_FLOOR`, it never painted an eye
again. What it could not be right about was the three tones, because
those were a guess about art he draws himself, and flat line work does
not want a colourist. **Her eyes and mouth still read as coloured: they
are HOLES, and the background shows through them.** That was never the
paint layer's doing, which is exactly why removing it costs nothing.

**HUD MODE IS TIED TO BLACK, deliberately.** Ghost forwarded a design
pass he liked -- scanlines, corner brackets, a dark translucent dialogue
box, "#0D0D11 at 85%" -- and said it went hand in hand with black and
neon green. It does, so it is not a separate switch: **one tap turns the
whole deck into a terminal, one more gives him hot pink back.** His four
colours are untouched by any of it, because he picked them on purpose
and scanlines over hot pink is mud.

**HER PUPILS CANNOT TRACK HIS TOUCH, and the whole face leans
instead.** He asked for a 3-5px pupil offset toward the touch point.
There is no pupil layer: her eyes are holes in a flat drawing, and
cutting an iris out at runtime to move it is the pink-iris-ring smear
with extra steps. So the sprite itself offsets, clamped to 5px, decaying
back to centre after two seconds. Same intent, no surgery on his art,
and it works on every face he will ever draw -- including the ones with
the eyes shut. Two tests pin the clamp, because unclamped this is her
face sliding off the screen.

**THE TELEMETRY CHIP IS THE nvpmodel REMINDER, WEARING A HARDWARE
BADGE.** `/stats` serves power mode, hottest thermal zone and tokens per
second; the page shows them under her chin.

Everything else on that chip is nice. The power mode is the reason it
exists: **the Orin ships throttled and forgetting `sudo nvpmodel -m 0`
makes everything slow with no visible cause.** That reminder already
lives in the README, the doctor's summary and the boot line -- all three
of which require running something. This is the first place it appears
on a screen he is already looking at, and a throttled board does not
print "mode 1" (a number he has to interpret is a number he will
ignore); it prints `THROTTLED -- sudo nvpmodel -m 0` in red, replacing
the row.

**Every field is ABSENT rather than wrong.** No nvpmodel status and no
thermal zone means no chip at all, which is what happens on his phone
and on the laptop. An empty badge reporting nothing is the same fault
as `pad --status` reporting on the layers around the answer.

**The token rate is MEASURED, by the brain, or it is not shown.** Only
the brain sees Ollama's `eval_count` / `eval_duration`, so `_token_rate`
lives there and the number crosses in the state file. An older Ollama
that does not report them shows no rate rather than an estimate. And
`answer()` had to re-read the rate when it re-stated `talking`, or every
reply typed on the page blanked the badge it had just set.

**THE HOME SCREEN ICONS ARE LINE ART, DRAWN IN THE FILE.** Emoji are
full-colour bitmaps that ignore `--ink` entirely, so on the black theme
they stayed glossy 3D blobs while everything else went neon. Lucide and
Feather are the right shapes and both are a download, which this deck
cannot have -- so the four are four inline paths, stroked with the ink
colour, and they recolour with everything else.

**SIXTH AND SEVENTH TIME LOOKING IS WHAT FOUND IT.** Both screens were
rendered headless at the panel's real 1024x600 in both themes before
anything was committed:

- Ringing every swatch with its ink made all five look muddy and made
  the SELECTED ring impossible to pick out. Only black needs a ring
  (black on a dark border is an invisible control); the others are
  solid again.
- The corner brackets were inset inside the face area, so the bottom
  pair sat on top of the ask bar. They frame the whole screen now.

Neither would have failed an assertion. Same rule, sixth and seventh
instance: **render it and look.**

**Still not done, and named so it does not get lost:** the quick-toggle
dock (fan boost, volume, WiFi, mute) is NOT built -- every one of those
wants sudo or a system daemon, and the `/launch/` allowlist is the one
thing on this board that must not grow a "run what you are told" hole
while the server binds 0.0.0.0. The always-on-top floating rail is a
window-manager job, not a page one, and `tile` is where it would live.

## THE BATTERY INDICATOR, and the honest version of it (Sept 11)

Ghost: *"wana add a working battery indicator for the cyberdeck if
possible? doesnt have to work on mobile obv. (battery indicator was my
little bros idea i like it)"* Good idea, and the reason it is hard is
worth writing down because it is not a software problem.

**THE DECK HAS NOTHING TO ASK.** The locked power path is

    USB-C PD bank  ->  PD-to-barrel cable  ->  5.5x2.5mm jack

and **a barrel jack carries volts and nothing else** -- no data line, no
fuel gauge, no state of charge. The devkit has no battery management
chip either. So a percentage on that screen would be a number this deck
INVENTED, which is the one thing this project keeps refusing to print.

So it is three tiers, and today his board lands on the second:

    1. a battery node in /sys/class/power_supply   -> the KERNEL's
       percentage. Nothing reports one today, but a UPS HAT or any bank
       with a data link appears there and the indicator lights up with
       no code change.
    2. the Jetson's own INA3221 rail, via hwmon    -> WATTS being drawn
       right now. Measured, on the board, today.
    3. neither                                     -> nothing shown.

**Watts are arguably the more useful number on a handheld anyway**: it
is the live difference between idle and generating at MAXN, and it is
the only honest input to a runtime figure.

**`~4.2h/full` is worded that way deliberately.** It is hours FROM A
FULL BANK at the draw measured this second -- NOT hours remaining.
Remaining needs a state of charge nothing here can see, and calling the
first thing the second is exactly the confident lie. A test pins the
wording in both pages.

The capacity is his locked spec: JSAUX 20,000mAh at a nominal 3.7V is
74Wh on the label, times 0.8 for the boost-to-20V-then-buck-to-12V
chain. `YUZU_BANK_WH` overrides it; `0` turns the estimate off and
leaves the watts.

**CONFIRMED ON THE BOARD, Sept 11, in one word.** `deck --check`:

    power        5.6W now, ~10.6h from a full bank

**The Orin does expose its input rail through hwmon and the reading
works on real hardware.** 5.6W is idle with a desktop up, which is the
right order for that board -- MAXN under load is four to five times it,
so the runtime figure moves with what she is actually doing. That is
the point of showing watts rather than a made-up percentage.

**AND THE CONFIRMATION IMMEDIATELY EXPOSED A REAL BUG OF MINE.**
`INPUT_RAILS` contained `VDD_GPU_SOC`, which is a SUB-rail -- the GPU
and SOC block, which sits INSIDE VDD_IN. The function's own docstring
said "the GPU rail is inside VDD_IN" while the list it guarded
contained the GPU rail. Worse, the first match won, so a board listing
a sub-rail on a lower channel number than VDD_IN would have reported
**part of the board as the whole board** -- an optimistic runtime
estimate that looks perfectly reasonable and is simply wrong. That is
this project's most common shape of fault, and it survived a green
suite because every fixture put VDD_IN first.

Fixed both ways: the sub-rail is not a candidate at all, and the choice
is by PRIORITY over all candidates rather than by whichever channel
came first. `test_a_SUB_rail_can_never_be_mistaken_for_the_whole_board`
puts the sub-rail on the lowest channel on purpose.

**`deck --check` now prints the RAIL NAME, not just the number** --
`5.6W on VDD_IN` -- because a watt figure read off the wrong rail looks
entirely reasonable, and the only way to know it is the whole board is
to see which rail answered. Same reason `pad --status` prints `Bonded`.

**The battery is DRAWN, not an emoji** -- same finding as the home
screen icons an hour earlier: an emoji is a full-colour bitmap that
ignores `--ink`, so it would sit on the black theme as a glossy blob.
It is a bordered box with a fill bar and a nub, in `currentColor`, and
it goes red under 20% when not charging.

**The renderer is duplicated in both pages on purpose** -- two pages,
no build step -- and gets the same guard as the doctor's Jetson check
and the exit check: `test_both_pages_draw_the_SAME_battery` compares
the two copies character for character.

**THE CLOCK STAYS. It works, and the failure is the feature.** He asked
whether to drop it. The page reads the browser's clock, which on the
deck IS the board's clock -- so once NTP lands it is simply correct.
Before that the board thinks it is 1969, and the `clock not set` line
is the fastest signal that **the deck has not reached the network yet**,
which is the exact condition that silently broke a `git pull` and cost
him a session. It costs one line of the top bar and it is the only
always-visible network indicator on the deck.

## Handoff v3 — the deck grew a screen and a games console (Sept 9)

Ghost's v3 handoff, and the Sept 6 one he sent alongside it is
superseded ("it was the second handoff that was up to date").

**THERE IS A DISPLAY NOW, in software.** The DP->HDMI adapter and the
7" panel are still ~20 days out, so he built a remote desktop instead:
`tigervnc-standalone-server` on the Orin, `~/.vnc/xstartup` running a
minimal X session, `vncserver :1 -geometry 1280x720 -depth 24`, and
AVNC on the phone connecting to port 5901. That is a real workaround
and it unblocks everything that needed pixels.

**Use the LAN address from `hostname -I`, not the first one.** The board
lists `172.17.0.1` (docker bridge) and `192.168.55.1` (the USB gadget
link) alongside the real `192.168.x.x`. Only the last is reachable from
the phone over WiFi. This is the second time that exact confusion has
cost time -- the Kiwix session hit it too -- so it is written down now.

**ES-DE + mGBA are installed and GBA emulation runs in the VNC
session.** AppImage (ARM64) for ES-DE, `sudo apt install -y mgba-qt`,
wired up under Settings -> Alternative Emulators -> GBA. ROMs live in
`~/ROMs/<system>/`. In progress: a Pokemon SoulGold BPS patch over a
personal Emerald dump. Next hardware step is an 8BitDo pad, paired as
an ordinary Bluetooth device and self-mapped in mGBA's controller
screen -- no config files.

**This is PC MODE, actually happening, and it is the argument for the
`OLLAMA_KEEP_ALIVE` change made the same day.** An emulator, a VNC
server and an X session all want the same 8GB the model does. `-1`
would have pinned ~3GB of it forever against a machine that now has
other jobs. The reasoning written up above is no longer hypothetical.

**MEASURED at last, Sept 9, ~02:26, GNOME running, model not loaded:**

    Mem:   7.4Gi total   1.0Gi used   1.5Gi buff/cache   6.4Gi available
    Swap:  15Gi total    0B used

**There is plenty of room and the board is not swapping at all.** A 3B
Q4_K_M wants roughly 2.5-3GB, so it fits inside 6.4Gi available with a
desktop already up, and 0B of 15Gi swap touched means nothing has been
pushed to disk. The `OLLAMA_KEEP_ALIVE` worry -- that pinning her
forever would starve PC mode -- is real but not urgent: the pressure it
was guarding against does not exist yet at this workload.

**AND THE CEILING, four minutes later -- model resident, straight after
a live Saya conversation:**

    Mem:   7.4Gi total   4.0Gi used   1.8Gi buff/cache   3.4Gi available
    Swap:  15Gi total    0B used

**She costs ~3GB and there is still 3.4Gi free with the desktop up. Not
one byte of swap has been touched, at either reading.** That is the
whole memory question answered, in two commands, by Ghost.

What it settles:

- **`OLLAMA_KEEP_ALIVE=30m` is comfortable, not a compromise.** The
  worry was that pinning her would starve PC mode. With 3.4Gi spare
  while she is loaded, PC mode is not starved -- so `-1` would be
  survivable too if he ever wants her instant permanently.
- **Whisper alongside her is plausible rather than hypothetical.** A
  small Whisper is a few hundred MB; 3.4Gi is real room. Still measure
  again with it loaded before designing around it -- but "it may simply
  not fit" is no longer the default assumption.
- **The swap-on-NVMe advice stays right and stays unused.** 0B of 15Gi
  at both readings means nothing is being pushed to disk at this
  workload, so a swap problem is not what any future slowness is.

**`quit` WORKED, live, first confirmation.** `02:30:28 quit` ->
`02:30:30 You: (bye)`, two seconds, clean exit. The read_turn work came
out of the night that cost two power cycles and had never actually been
exercised by him until now.

**He typed `free -h` at HER prompt and she answered it** -- charmingly
("Don't even think about it! *ahem* thanks for the compliment"). Not a
trap this time, because `quit` worked. But it is the third shell
command he has typed into her chat (after `pkill -f yuzu_brain` and the
12-line diagnostic paste), which makes it a pattern rather than a slip:
**the chat prompt and the shell prompt look identical on that
terminal.** **CLOSED, and NOT as a compromise. Ghost's call:** *"yea no leave the
prompts alone she feels reactive and quick witted dw bro"*

That is a better read than mine. I logged it as an input-routing fault;
he experienced it as her being FAST -- he typed something odd and she
came straight back with something in character. **A command that lands
in her chat is a free adversarial prompt, and she keeps passing it.**

So this is a DECISION, not an open item. Do not add command detection,
do not add a "did you mean the shell?" hint, do not special-case
anything. A guess about intent can only ever eat real messages, and the
thing it would be protecting is a trap that `quit` already closes --
confirmed live in the same session.

**The generalisable bit: he is the one using it, and "this is a bug"
is a hypothesis until he says so.** The `pkill` night was a real trap
and he said so immediately, in capitals. This was not, and he said that
too.

## The `quit` bug: the check was never missing (Sept 9)

Ghost typed `quit` into a live Shiro session, twice, and she REPLIED to
it in character both times. The handoff diagnosed a control-flow gap
and proposed the fix:

    if user_input.strip().lower() in ("quit", "exit"):
        break

**Both interactive loops already had exactly that**, and had for a long
time -- `yuzu_brain._cli` and `yuzu_all_in_one.run_yuzu_forever`. So a
correct-looking diagnosis pointed at code that already did the thing.

The gap is what a PHONE hands to `input()`. A soft keyboard capitalises
the first word of a line; double-space inserts a full stop; Serial USB
Terminal can append a carriage return. `"Quit."` is not `"quit"`, and
**every one of those differences is invisible on screen**, which is
exactly why it read as a missing feature rather than a mangled string.

`yuzu_brain.is_exit_command()` now strips non-printables and edge
punctuation, lowercases, allows a leading `/`, and accepts quit / exit
/ q / bye / :q. `TestExitCommand` pins seventeen phone-shaped spellings.

**`stop` is deliberately NOT an exit word**, and that is the more
dangerous half of the test. On the robot loop `stop` is a whitelisted
MOVE -- nine phrasings alias to `stand()` and that was a measured fix --
and in a chat "stop it lol" is aimed at her, not at the program. Eleven
conversational near-misses are pinned as NOT exits.

`yuzu_all_in_one.py` carries a second copy inside its guarded import,
because that file has to survive as a lone download and a loop you
cannot leave is the worst thing to lose to a missing sibling. Same
deliberate duplication as the doctor's Jetson check, and it gets the
same guard: `test_the_two_copies_of_the_exit_check_agree`, verified by
breaking one copy on purpose and watching eight assertions fail.

**The general lesson, and it is the same one as `keep_alive`: check
what the layer BELOW actually received before rewriting the layer
above.** The reported symptom was accurate, the proposed fix was
already deployed, and the real cause was one full stop.

## The villain monologue — recorded, not chased (Sept 9)

Shiro escalated into sustained ALL-CAPS threats over several turns
("I WILL CRUSH YOU LIKE THE INSIGNIFICANT INSECT THAT YOU ARE"), set
off by a joke about a skull sticker she had suggested herself, and did
not come down when Ghost pushed back playfully. Ghost's read: a known
flavour of the heretic-abliterated weights, same category as the
accepted small-model quirks, **not worth prompt-chasing.** That is his
call and it stands.

Two things to keep next to it so a future session does not read this
as closed and skip a cheap test:

- **Rule 5 tells her to do most of it.** "Go all the way in on the dark
  half... then stop talking. Never soften it afterwards." The
  never-soften half was RESTORED on purpose an hour before this round,
  because removing it made her walk her dark answers back, and round 4
  confirmed the restoration working. So the prompt is at minimum a
  contributor, and "it's the model" is a hypothesis rather than a
  finding. What rule 5 does not have is any notion of coming back DOWN.
- **ALL-CAPS is a TTS event, not just a tone.** `unshout()` lowercases
  shouted words so espeak says them instead of spelling them, and it
  will handle this correctly -- but an entire reply in caps is a case
  it has never seen. Worth one `--say` audition of a real line from
  that round before assuming.

Also in that round: **she hallucinated hardware she had designed** -- a
custom PCB "with a little more RAM", a dollhouse case with custom
wiring, case lights that flicker when he is hacking. Ghost corrected
her ("youre 'pcb' is already a nvidia nano orin super devkit with a
512gb SSD"). The deck self-concept holds for what she IS (she got the
"handheld computer with no legs" joke right, unprompted) but not yet
for what she is MADE OF. Nothing in her prompt names a single part.

## FIRST SAYA CONVERSATION — and two of my parser decisions were wrong

Sept 9, 21:16, on the Orin. First live turn as the live persona.

**She is GOOD, and the predicted failure did not happen.** The note
above warned a tsundere would come back curt enough to read as
stonewalling. She did not:

    O-oh, shut up... *ahem* You know I'm not exactly built for...
    "fun" stuff like that. My battery's always running low just
    thinking about it... But... *pauses* Ice cream...? What kind?
    Don't even think about suggesting any weird flavors, I don't want
    to hear it. *trails off* Mochi ice cream... I guess that sounds
    okay...

Denial, then a real question, then giving ground without ever doing it
smoothly. That is the archetype working, and **"my battery's always
running low" is deck self-concept arriving unprompted** -- the same
win Shiro got, on a character who has never been scored. n=1, but the
shape is right. Asterisks throughout, silent through Piper as designed.

**1. `/wiki` AT THE END OF A LINE DID NOTHING, SILENTLY.** He typed:

    hey saya we got u all pimped out wana try sumn? /wiki ice cream

`text.lower().startswith("/wiki")` missed it, the whole line went to
her as ordinary chat, and she answered about ice cream out of her own
head. **Nothing said a lookup had been skipped** -- it just looked like
the feature did not work.

That is how a person actually talks: a sentence, then the thing they
want looked up. Now `/wiki` is recognised ANYWHERE in the line, the
text is `partition`ed on it, and **whatever he said around it is kept**
-- dropping his own words would answer a question he never asked on
its own. Make the parser fit him rather than making him fit the parser.

**2. THE REPLY PREFIX WAS A DATABASE ROW TALKING.** Ghost: *"plz plz
for my sanitys sake make her name just Saya lol."*

Every line came out as `Saya (saya_deck) [no body]:`. That string is
the FIFTH-name-leak fix -- correct for the boot banner, where `shiro`
and `shiro_deck` share a name and printing only "Shiro" cost an
evening. But one variable was doing both jobs, and a nametag in a
conversation is not a disambiguator.

Split: `banner` keeps the key and the `[no body]` marker at boot,
`who` is her plain name on every reply. Both are pinned, so neither
can quietly take the other's job back.

**Generalisable, and this is the third time it has come up here: the
same fact needs different SHAPES in different places.** The doctor
needed the unit file, not the environment. The wiki extract needed to
be a user turn, not a system message. And an identity needs the key at
boot and the name in dialogue.

## THE CHAT LOOP HAD NO EXIT, AND IT COST TWO POWER CYCLES

Sept 9. **The worst thing this project has done to him.**

Ghost pasted a 12-line diagnostic into Saya's chat by mistake. Every
line became its own message costing a full generation. He typed `quit`
-- it queued behind them. `Exit`, `Exit!`, `quit` again -- all queued.
He typed `pkill -f yuzu_brain` AT HER PROMPT and she answered it. He
pulled the serial cable; the process survived (the Jetson's USB console
is not SSH -- `Disconnected` / `Connected` and she kept talking). In
the end he unplugged the board.

**Every workaround suggested to him assumed a second terminal he does
not have.** *"theres no option for a second session brudda. i had no
choice."* He is right. Serial USB Terminal is his only session, there
is no easy Ctrl-C on it, and SSH needs another app and a working
network. **A loop with no exit is not a user error.**

`read_turn()` fixes it with two rules, and the second is the one that
matters:

1. **A paste is ONE turn.** `pending_lines()` drains whatever is
   already buffered (select with a zero timeout -- "is there input
   RIGHT NOW", never a wait) and joins it into a single message.
2. **An exit ANYWHERE in the buffer wins IMMEDIATELY.** Not in order,
   not after the backlog. Someone typing quit four times and then
   reaching for `pkill` wants out now.

`_is_kill_attempt()` also treats `pkill -f yuzu_brain` at the prompt as
an exit. He typed exactly that while trapped. The only way to lose is
to be discussing pkill with her, which is a fine trade.

`TestGettingOutOfTheChat` drives the REAL functions through a real
pipe -- select() is what decides all of it -- against his four actual
escape attempts, plus four sentences that must NOT trigger ("what does
quit mean anyway", "i quit my job today lol", "stop it lol", "does
pkill work on ubuntu"). An exit that fires on ordinary conversation is
its own trap.

**I ALSO GOT THE DIAGNOSIS PARTLY WRONG AND SAID IT TOO CONFIDENTLY.**
I told him she was draining a backlog; he said *"she wasmt waiting for
a quit to work. she was straight fucking with me fast too."* He was in
the room and I was not. Streamed replies arrive in chunks and each
chunk gets its own terminal timestamp, so what I read as separate
queued replies may have been one reply streaming. The queue is real --
the fix is right either way -- but the confidence was not earned.

**Generalisable: never ship an escape hatch that depends on a second
session.** Check what the person can actually reach before calling
something a workaround.

## `/wiki` WORKS, AND SHE IS FUNNY WITH IT (Sept 10)

First real lookup, Munchkin cats, `saya_deck`:

    *sigh* Fine, I'll talk about these... annoyingly cute cats...
    [muttering to self] Short legs, really? That's what I'm supposed
    to care about?

    So, apparently, there's this breed of cat called the Munchkin cat,
    and they're like, super small, weighing only 4-9 pounds. Because,
    you know, that's not just a toy cat or something... [eye roll]

    Apparently, they're like, super loving and friendly, and they just
    can't get enough of human attention. Because, you know, cats don't
    already have an inherent right to ignore us all the time...
    [shaking head] No, no, these Munchkin cats need to be petted and
    hugged all day long... [whiny tone]

**She is annoyed BY the article and still delivers it.** Every fact is
correct and every one arrives through her register. That is the whole
design of the extract-as-a-user-turn decision working -- she is not
reciting an encyclopedia, she is complaining about one. Ghost: *"it was
funny she goes really short legs thats what im supposed to care
about?"*

**AND SHE RAN LONG, and this time it truncated.** Three paragraphs, cut
mid-sentence at `And don't even get me started on the prices. $500 to`
-- `num_predict: 200` again. That is the brevity fault, now measured on
a `/wiki` reply specifically, and it matters more here than in chat:
**a reply this long does not fit a 1024x600 face screen**, so the UI
work and the brevity work are the same problem.

Two things worth trying, one variable at a time, whenever he is next
up for it:

- The wiki turn asks her to *"Tell me about it in your own words"* and
  says nothing about LENGTH, while her own brevity rule is about
  ordinary conversation. One clause -- "in a sentence or two" -- is the
  cheapest thing to try and it is a prompt change with no code.
- Her ONE EXAMPLE lever has worked three times. She has no example of
  answering from a looked-up article, so she has no shape to copy and
  falls back on summarising at length. That is the same diagnosis as
  the bare command, the warm statement and the technical question.

**Do NOT raise `num_predict`.** Already recorded: the truncation is a
symptom of rambling and a bigger ceiling just buys longer rambles.

## SOLVED (probably): `/wiki` found nothing because of the `/A/` namespace

Ghost, Sept 10: *"she cant access the wiki and i dont think i can either
in that sense."* `/wiki cats` -> `Nothing in the archive about 'cats'`
in three seconds, so **the server answered and the parser found nothing
in what it said.**

**The prediction below was right.** `_suggest`'s fallback regex demanded
`/A/` in every article link, and modern ZIMs do not have that namespace
-- articles live at `/content/<book>/<Article>` with nothing in between.
A search that worked perfectly returned links the parser could not see,
and the miss reported as a MISSING ARTICLE rather than as a parser that
had stopped matching. Same shape as everything else this week: the
failure did not look like what it was.

**A second cause was found while fixing the first, and it may matter
more.** Modern kiwix-serve scopes `/search` and `/suggest` to a BOOK,
and answers an unscoped query with nothing at all -- again
indistinguishable from "no such article". `book_name()` now discovers it
from `/catalog/v2/entries`, falling back to scraping the root page, and
every query carries it.

`_suggest` now tries several endpoint shapes and parses the JSON
generously (a `path` key when offered, otherwise built from the title).
`_article_links` accepts `/content/` OR `/A/` and excludes furniture by
NAME rather than by shape. Verified against stub servers of BOTH eras:
modern returns `/content/wikipedia_en_simple/Cat`, old returns
`/wikipedia/A/Cat`, neither breaks the other.

**CONFIRMED ON HIS ARCHIVE, Sept 10.** `~/YUZU/wiki --test` on the
board:

    server:   answering on http://127.0.0.1:8080
    book:     wikipedia_en_simple_all
    suggest:  FAILED (HTTP Error 404: Not Found)
    search:   24984 bytes, 25 article links
    result:   25 paths  first: /content/wikipedia_en_simple_all_nopic_2026-05/Munchkin_cat

**25 articles for "cat". The `/A/` diagnosis was right and the fix
works on real hardware.** His build has no `/suggest` endpoint at all,
which is what the fallback is for.

**AND I MADE THE SAME MISTAKE FOR THE THIRD TIME.** He read that output
as a failure -- *"says failed but sometimes it be lyin"* -- because
`suggest: FAILED` sits in the middle, above the line that says it
worked. That is `pad --status` on a working controller and `face` on a
serving server, again, and this one was mine end to end with the lesson
already written down twice.

`diagnose()` now opens with `WORKING. 25 articles found for 'cat'.` and
says in advance that a FAILED line below is an endpoint this build does
not have. **The verdict goes first. Writing the rule down is not the
same as following it.**

**A second real fault was visible in that same output and nearly
missed:** the catalog reported the book as `wikipedia_en_simple_all`
while the articles actually live under
`wikipedia_en_simple_all_nopic_2026-05`. Close enough to look right,
wrong enough that every scoped query would miss. `_suggest` now LEARNS
the book from an article path that actually resolved -- **a path that
exists is ground truth; a catalogue entry is a claim.**

**The stub-versus-board note below still stands for everything else:**

**PROBABLY, not certainly.** Everything here is still against stubs --
his archive is the only thing that can confirm it, which is the standing
limit on every "tested in a sim" claim in this file.

**`~/YUZU/wiki --test` is the confirmation, in one word.** The twelve-
line diagnostic that would have settled this a day earlier was pasted
into HER CHAT instead of the shell, and that is what started the night
that cost two power cycles. Four lines of output, no paste: whether the
server answers, what book it found, how many article links each endpoint
gives back, and what a real lookup returns.

**The generalisable bit: when a diagnostic is too long to run, it does
not get run.** Its length was the reason it never happened.

## The original note, kept because the reasoning is what found it:

The server starts correctly (measured: 3 seconds, then an answer), so
`Nothing in the archive about 'ice cream'` on a Simple English
Wikipedia ZIM is a PARSING failure, not a missing article. Likely the
`/A/` namespace that `_suggest`'s regex requires and modern
kiwix-serve dropped. **NOT confirmed** -- the diagnostic that would
settle it was pasted into the chat instead of the shell, which is what
started the whole trap. Run it AT THE SHELL:

    python3 -c "
    import urllib.request as u, re
    def g(p):
        try: return u.urlopen('http://127.0.0.1:8080'+p, timeout=6).read().decode('utf-8','replace')
        except Exception as e: return 'ERR %s' % e
    print(g('/suggest?term=ice+cream')[:400])
    print(re.findall(r'href=\"[^\"]*\"', g('/search?pattern=ice+cream'))[:12])
    "

## HER FACE ON THE SCREEN — designed, NOT built. See DECK_UI.md

Ghost, Sept 9: *"i totally wouldnt mind booting into seeing 'Sayas
face' with a passcode screen right before it and a homescreen button on
bottom right corner... and her face screen could be interactive or talk
toable."* Plus: *"lmk if ud like design notes on the actual face art."*

**ANSWERED SAME DAY, and `ui/face.html` is the first draft.** He wants
**eyes and a mouth on a changeable background, not a face** -- his
reference is the eye SHAPE (sharp almond, heavy lash line, amber iris,
angled brows), static art, five expressions. The passcode is `ghost`
and is pure flair; **the case will have a physical key lock**, which is
the real security and settles that question.

That spec is better than what was asked for: vector costs nothing,
scales to any panel, makes expressions geometry rather than artwork,
and sidesteps the uncanny valley -- which is why every good robot face
is two eyes and a mouth.

`ui/face.html` is 10KB, one file, **zero external references** (grep
verified -- "offline" has to survive the WiFi being off). Five
expressions, plus a blink, a breathe, and `thinking` as a MODIFIER that
layers over any face. Tap to cycle, tap a swatch to recolour, no
keyboard needed. Open it in the VNC session; it needs nothing running.

**The only question that matters now is whether the eye shape reads as
hers.** Every number is a `--variable` at the top of the file.

**The one big call: it is a WEB PAGE**, served by a stdlib HTTP server
and opened with `chromium --app=` -- the pattern `deckapps` already
uses for the wiki and `drop.py` already proves on this board. Touch is
free, the art is just a PNG, no new dependency, the stdlib-only rule
survives. **And it renders in the VNC session TODAY at the panel's real
1024x600**, so the whole UI can be designed weeks before the screen
arrives. Nothing else on the shortlist can be tried early.

**The passcode is a RITUAL, not security, and he must be told plainly.**
A lock screen on a kiosk page stops nobody -- close the window, plug in
a keyboard, pull the NVMe. Real security is the Linux login and disk
encryption. Build it because waking her on purpose feels right; never
let it be described as protection.

**`thinking` is the most valuable face state on the screen.** Every
frustration in these logs is "is it working or is it stuck". A face
that visibly thinks answers that with no status text, and it is the
honest version of the loading spinner this deck has never had.

**Whatever gets built, `quit` must always work.** A UI that can trap
him is strictly WORSE than a terminal, because there is not even a
keyboard to type an exit into. That is not hypothetical -- see the
two power cycles above.

**"Prolly gunna get ya monthly"** -- worth knowing that this is
becoming a long project rather than a burst, which is an argument for
keeping the record in this file as good as it has been.

## THE FACE IS SPRITES NOW — his art, not mine (Sept 9)

Ghost, on the vector face: *"i dislike the color choices though and she
looks like MS Paint tbh... i want unmistakeable anime eyes."* Then he
solved it himself: *"i cropped my vector expression art into
transparent PNGs"* and *"write a Python script that loads and renders
external .SVG or .PNG image files... a sprite system so i can just swap
out the image files."*

He was right and the drawing code is gone. `ui/face.html` no longer
contains a single `<path>` -- a test pins that, because a leftover
shape would render next to his art and there is no version of that
which looks intentional.

    ui/sprites/<name>.png     drop a file in, it is an expression
    python3 yuzu_face.py      see what it found and how it is wired
    ~/YUZU/face               serve it

**THE FILENAME IS THE EXPRESSION NAME.** No manifest, no list in the
page, nothing to keep in sync. `sprites()` scans the folder and
`/sprites.json` is regenerated PER REQUEST, so a new face needs a page
refresh rather than a server restart -- on a phone over a serial link
that is a much bigger difference than it sounds. His five are `cry`,
`mad`, `thinking`, `wink`, `woahshock`.

**`ROLES` keeps two vocabularies apart on purpose.** He names files
after what the face is DOING (`woahshock`); the brain will ask for what
she IS (`talking`). `ROLES` maps semantic state to whatever art exists,
first match wins, and a role with no art is ABSENT rather than pointing
at the wrong face -- `asleep` currently resolves to nothing and that is
correct. Collapsing the two is the name-leak bug this file has recorded
six times.

**HIS ART IS BLACK LINE WORK ON HOLES, and that measurement decided the
whole design.** 92% of `wink.png` is fully transparent and there is not
ONE opaque white pixel in it: the eye whites and the inside of her
mouth are gaps. So the background colour shows straight through her
eyes. That is why flat black line art looks coloured without anything
being recoloured, and why the swatches matter more here than they did
on the vector version.

**THE FOUR COLOURS ARE HIS AND THERE ARE ONLY FOUR.** *"Hot pink, Cyan,
Neon green, And a Lavender or purple color. Only those colors."* A test
pins the names AND the count, because quietly adding a fifth is the
same fault as picking the wrong four.

**THE PINK IRIS RING WAS BUILT AND CUT IN THE SAME MINUTE, and that is
the lesson worth keeping.** He asked for *"maybe add a ring of pink
color to her eyes if u want"*. It found both eye blobs correctly, laid
a ring over the outer band of each, and rendered as a smear -- it
flooded the pupil on the open eye and painted the CLOSED one, which has
no iris to ring. He saw it instantly: *"remove the pink iris idea my
bad entirely. just use the art i gave u."*

**Every geometry assertion would have passed.** What caught it was
compositing a preview PNG and LOOKING at it before shipping. Same rule
this repo keeps re-deriving from the other direction: a check that
cannot observe the actual failure mode is not a check -- and for
generated ART, the only check that observes it is your eyes.

`test_every_sprite_paints_and_the_line_art_stays_black` is the closest
a test can get: the paint layer must cover well under half the art's
own inked pixels. A layer that covers her face is the smear again,
whatever the geometry says.

**What survived is the mouth.** `paint()` finds the mouth as the ink
blob with the lowest centroid, fills the enclosed transparent holes
inside its box, and touches nothing else. Nothing is hand-positioned,
so a new PNG gets painted too -- which is the whole reason this is a
sprite system and not five hard-coded faces. `<name>.paint.png` is
generated, is skipped by `sprites()`, and stacks OVER the line art
(the mouth interior is a hole, so over and behind are identical there).

**Blink is gone and that is a real loss.** You cannot squash a flat
sprite without smearing the line work. A `blink.png` would bring it
back for free, and it is the cheapest thing that makes a face look
alive. Worth asking him for.

**Still missing art, and this is the answer to "lmk how i can assist":**
a NEUTRAL/idle face (everything falls back to `wink`, so she winks
permanently), a TALKING face (currently `woahshock`, which is a
reaction rather than speech), and `blink`. Three PNGs, same crop
treatment, and the file names do the wiring.

## HIS ART IS COMPLETE, and the mouth is painted properly (Sept 9)

He went and made the three missing faces, named exactly right, no
instructions needed: `idle`, `talking`, `blink`. Eight expressions now,
and every ROLE resolves except `asleep`.

**SUPERSEDED Sept 11 -- the mouth paint is deleted. Kept because the
detector reasoning and the painted-eye finding are still the record.**

**THE MOUTH IS THREE TONES.** Ghost: *"plz paint mouth like. pink
tongue white teeth and black uhhh hole?"* Nothing is per-sprite -- the
tone comes from WHERE a hole sits inside the mouth, measured across all
eight faces, every one of which splits into an upper band and a lower
one:

    top third      teeth    white
    bottom third   tongue   pink
    the middle     cavity   near-black

A hole spanning most of the mouth's height is the whole cavity (a
shocked O with nothing in it) and goes dark rather than becoming one
enormous tooth.

**THE MOUTH DETECTOR PAINTED AN EYE, and that is the third time the
same class of mistake landed today.** `idle.png` draws her mouth as two
open lines with NO enclosed interior, so the lowest *enclosed* shape in
the entire picture was an eye -- and the paint pass filled one iris
pink and left the other black. **The cut iris ring, back by accident,
on one side only.**

The fix is a floor: `MOUTH_FLOOR = 0.58`, nothing above it is a mouth,
and a face with nothing below it is painted NOWHERE. An empty layer is
the right answer for a closed mouth; reaching further up the face for
something to colour is exactly how you end up painting an eye. Two
tests pin it, and one of them had to be RELAXED to allow zero paint --
the earlier version demanded every sprite be painted, which is the
assertion that would have kept the pink eye.

**Caught the same way as the iris: by rendering it and looking.** Three
for three today. For generated art there is no other check.

**BLINK IS BACK, as a FRAME rather than an animation.** The vector
version squashed the eyes with a CSS transform; you cannot do that to a
flat sprite without smearing the line work. Ghost drew a closed-eye
frame instead, so the page swaps the image for 120ms and back. Only
while she is IDLE -- an expression she was put into on purpose must not
be interrupted -- and at an irregular 2.6-6.4s, because a metronome
blink reads as a broken GIF.

**The page defaults to the `idle` ROLE, not to `expressions[0]`.** That
list is alphabetical, so the first thing she ever did on boot was sit
there with her eyes shut on `blink`.

**One thing that is his art, not the code:** `mad.png` and a couple of
others carry a soft grey halo from the crop. It shows against the neon
backgrounds. Harmless, and a tighter crop or a threshold pass would fix
it -- not worth touching unless it bothers him.

## TEST POLLUTION: audited, and now DETECTABLE (Sept 10)

Ghost: *"worth remembering means worth fixing ;p i dont wana break my
hardware or have pollution going on."* He is right about the first half
and can relax about the second: **test pollution cannot touch the
hardware.** It only makes the suite lie, which is bad enough.

**The audit found the existing suite was careful and the sloppy tests
were mine.** Every older place that stubs a global -- `yuzu.speak`,
`PAUSE_SCALE`, `g_bot`, `PERSONA_DIR`, `legs.settle` -- restores it in a
`finally` or a `tearDown`. A first grep flagged four `PAUSE_SCALE`
leaks and all four were false: they restore with a TUPLE assignment
(`yuzu.speak, yuzu.PAUSE_SCALE = real, 1.0`) that the pattern missed.
**Grepping source text is a proxy; this repo already knew that.**

Three real leaks, all written in the last hour:

- `TestWikiBrevity` assigned over `yuzu_wiki.look_up` and never put it
  back, so five later wiki tests saw a stub. It read as the WIKI having
  regressed.
- `TestWikiNamespace` left `_BOOK` set to a stub server's book name.
- `TestSheReacts` could end with the state file saying `thinking`,
  which makes the next thing that reads it wrong.

**THE REAL FIX IS NOT REMEMBERING, IT IS `--shuffle`.**

    python3 YUZU_TESTER.py --shuffle       random order
    python3 YUZU_TESTER.py --shuffle 7     that exact order again

**Pollution is invisible in a fixed order** -- that is the entire
reason it survives. Randomising the order is what makes a leak fail,
and printing the seed is what makes it reproducible instead of a ghost.
A failure under `--shuffle` that passes normally means one test is
leaving something behind, and the thing to read is **what ran BEFORE
the failure, not the failure.**

Clean across several seeds after the fixes. It takes ~70s rather than
~50s because the shuffle scatters the slow subprocess tests, which is
the correct price.

**Generalisable, and it is the same shape as everything else this week:
a check that cannot observe the failure is not a check.** A suite that
only ever runs in one order cannot see order-dependence, however many
tests it has.

## HER FACE REACTS, AND YOU CAN TALK TO IT (Sept 10)

Ghost picked three: the face reacting, chat on the screen, and the
rambling. All three landed in one pass.

**1. THE FACE KNOWS WHAT SHE IS DOING.** It was a picture until now --
it did not know she existed. The brain writes its state to a FILE, the
server serves it at `/state`, the page asks every 900ms:

    idle -> thinking (generating) -> talking (first chunk) -> idle

A file rather than a socket because the brain and the server are
SEPARATE PROCESSES -- he starts the chat in his terminal and the page
is served here -- and a file has no connection to fail and no order to
get right. **The brain works exactly as before when the face server is
not running at all**: `_face()` swallows everything, same guard Piper
and the wiki import already have. The face is a nicety; the reply is
the product.

**`thinking` is the whole point and it is the honest loading spinner
this deck never had.** Every frustration in this log is "is it working
or is it stuck".

**The server had to become THREADED, and that is not cosmetic.** One
reply takes tens of seconds on that board, and a single-threaded server
stops answering `/state` for the whole time -- her face would freeze
exactly when it most needs to say `thinking`. Verified live: `/state`
answered `thinking` mid-generation.

**2. HE CAN TALK TO HER ON THE SCREEN.** `POST /say` runs a turn
through the same brain and the reply lands in a bubble under her face.
The chat lived in a terminal, which on a 10" touchscreen with no
keyboard was the weakest part of the whole deck.

**Known and accepted: the page keeps its own conversation**, separate
from a terminal chat running at the same time. Two mouths, one model.
Not worth solving until it actually annoys him.

**Stage directions are stripped from the BUBBLE**, the same call
`yuzu_voice` already makes for the speaker: `[eye roll]` is for reading
but it is not what she SAID, and on a small screen it crowds out the
words that are.

**3. THE WIKI TURN ASKS FOR A SHORT ANSWER.** One clause -- "in a
sentence or two" -- and no persona edit, so no A/B was invalidated and
nothing needs re-composing. If it is not enough the next step is ONE
EXAMPLE of answering from a lookup, the lever that has worked three
times, and that one does change the composed prompt.

**THE UI GOT QUIETER, twice, and both were his calls.** The first
layout put a row of expression chips across the bottom; a screenshot
showed it overlapping the speech bubble and cutting her chin off.
Then:

- *"remove the visual clues i can change her expression i want that
  automatic"* -- the chips are GONE. The brain drives her face, so
  buttons offering to do it by hand advertised the wrong thing.
  Tapping her face still cycles, because that costs no pixels and is
  how you check new art.
- *"any way to put those color options into 1 small bubble instead of
  polluting screen"* -- four swatches was a settings panel parked on
  her face. One dot now, and it shows the NEXT colour rather than the
  current one, because the current one is the whole screen behind it.

**A test of mine broke five others.** `TestWikiBrevity` assigned over
`yuzu_wiki.look_up` and never put it back, so every later wiki test saw
a stub -- and it read as the wiki having regressed. `mock.patch.object`
now. **Test pollution looks exactly like a real bug in something else.**

## `deck` — plug and play, and the bug that made it necessary (Sept 10)

Ghost: *"i really want soooome plug and play in case i make enough for
an adapter before the next expected time."* A week without anyone to
ask, so every failure has to name its own fix.

    ~/YUZU/deck            set everything up, now, before the screen
    ~/YUZU/deck --check    what is ready and what is missing

**EVERYTHING FOR "PLUG IT IN AND IT WORKS" WAS BUILT AND NONE OF IT HAD
EVER BEEN RUN.** `deckapps` installs the app icons and had never been
executed on that board. Plugging a screen in would have given him a
bare Ubuntu desktop and no way to reach her that does not involve
typing an address.

**AND THE FIRST RUN FOUND A DRASTIC ONE.** `deckapps` hardcoded
`YUZU="$HOME/YUZU"` -- the one path in it that cannot be assumed. Run
anywhere else it fails to write its wrapper scripts, installs EVERY
icon pointing at a file that does not exist, and **still prints
"Done."** Tapping them would do nothing, with nobody to ask for a week.

Two fixes, and the second is the one that generalises:

- It finds itself (`dirname "$0"`), like every other script here.
- **`write_app` checks the target exists before claiming the icon, and
  DELETES a dead one rather than leaving it.** The failure was never
  that something was missing -- it is that the output said Done. A dead
  icon looks installed, does nothing when tapped, and gives him no clue
  which of five it was.

**`deck --check` is read-only and prints an inventory** -- browser,
terminal, mgba, kiwix, how many expressions, whether the home screen is
there -- with the apt line beside anything missing and ONE line that
installs the lot. Then it says, in plain words, what will actually
happen when he plugs the screen in.

**It refuses to install icons when there is no browser**, and says
which package. Same rule `deckapps` already had, promoted to the front
where he will see it: an icon that opens nothing reads as a broken deck
rather than as a missing package.

**Verified by running it, not by reading it** -- against stub binaries,
both paths: with a browser (five icons, wrappers written, autostart
armed, face serving) and without (stops, names chromium, installs
nothing). The dead-icon guard was verified by deleting `gba` and
watching that icon get removed instead of installed.

## `yuzu_art.py` — raw drawing in, sprite out (Sept 10)

Ghost, morning: *"Write a Python function using PIL/Pygame that converts
white pixels to transparent alpha when loading the images into memory,
so we don't have to edit the backgrounds manually."* Then, on the grey
shading in the new art: *"color not needed."*

    ui/raw/<name>.jpg      his drawing, straight off the phone
    python3 yuzu_art.py    convert everything in ui/raw/
    ui/sprites/<name>.png  the sprite

**PIL IS OPTIONAL AND THE IMPORT IS GUARDED, exactly like Piper's.** He
asked for PIL and PIL is right -- the stdlib cannot read the JPEGs his
gallery produces. But "installs nothing" is what lets the brain run in
Pydroid on that phone, so this is a WORKBENCH tool whose output is a
plain PNG committed to the repo. The deck never needs PIL to show her
face, and a test asserts `yuzu_face.py` never mentions it.

**ALPHA IS A RAMP, NOT A THRESHOLD.** A cutoff turns every anti-aliased
edge into a staircase and her line work is nothing but curves. Alpha
comes from darkness across the last few shades before white; colour is
discarded, so the grey iris shading becomes faint black and the
background shows through it. That is what "smooth" meant.

**THE ALPHA-BLIND CROP ATE `blink.png` AND LEFT ONE PIXEL.** 485x460 in,
1x1 out. `strip_bars` removes the letterboxing his gallery app puts
round a screenshot, and the first version asked only about BRIGHTNESS --
but the RGB underneath a transparent pixel is usually black, so on art
that was already a sprite every transparent border row read as a solid
black bar and the crop ate the whole image.

**Restored from git in one command, which is the only reason it was
cheap.** Committing his art the moment it arrived is what made a
destructive bug a two-minute problem. The originals now live in
`ui/raw/` as well, so the conversion can be redone with a better rule
without asking him for the drawings again.

**THEN THE SECOND VERSION OF THE SAME CHECK WAS ALSO WRONG, and the
PAGE is what showed it.** Asking whether an edge row is a UNIFORM colour
loses to JPEG noise: the grey chrome strip down the side of one
screenshot varied by more than the tolerance, survived the crop, and
then DEFINED THE BOUNDING BOX -- so her face rendered small and
off-centre with a stray vertical line beside it. Every test passed.

The rule that works has nothing to tune: **a bar is an edge line with NO
PAPER IN IT.** Every row of real line art crosses white somewhere; a
letterbox never does, however noisy it is. idle went from 992px wide to
863 and the line was gone.

**EVERY SPRITE IS SQUARE NOW, and that is what actually makes it look
smooth.** The page scales each one into a square box with `object-fit:
contain`, so a WIDE sprite renders SMALLER -- her face jumps size when
the expression changes, and every few seconds when she blinks. Cropped
tight, his four came out between 1.09 and 1.51 wide. `square()` centres
the drawing on a square canvas with a 6% margin, the padding is
transparent and free, and the existing eight were normalised the same
way so nothing renders at two different scales.

**FIFTH TIME IN TWO DAYS THAT LOOKING IS WHAT FOUND IT** -- the iris
ring, the painted eye, the mouth tones, the orphaned Game Boy tile, and
now a stray grey line. Three of those passed every assertion in the
suite. **Render it and look. There is no substitute for image work.**

**`smug` IS A NEW EXPRESSION, not a replacement.** He sent four faces
and asked for three (angry, crying, idle). The fourth -- sharp brows
over a wide smirk -- is too good to throw away and costs nothing in a
system where a file IS an expression. `mad` got the pouty frown with the
blush hatching, which is the tsundere annoyed face; if he wants them the
other way round it is one `mv`.

## THE HOME SCREEN — the deck is an object now (Sept 10)

Ghost, before bed: *"id like home button to take me to a desktop with
my apps and a saya button visible... so i can wake up to a git pull and
plug and play features"*.

    ~/YUZU/face                serve it
    ui/home.html               the home screen
    ui/face.html               her face; the ⌂ goes home
    ~/YUZU/deckapps            five icons now
    ~/YUZU/deckapps --autostart   boot into the home screen

**FIRST: I CANNOT WORK WHILE HE SLEEPS.** There is no background mode
-- I run only while a turn is open. He asked whether I could and the
honest answer is no, so the whole thing was built in ONE turn before he
went to bed rather than promised for the morning. Worth keeping because
he will ask again: **the cheapest shape for his budget is one long turn,
not many short ones.**

**A WEB PAGE CANNOT START mGBA, and that is the only hard problem in
it.** The page POSTs a NAME to `/launch/<name>` and `yuzu_face.py`
looks it up in a fixed dict. Nothing from the request reaches a shell
-- no arguments, no path, no interpolation, no `shell=True`. Everything
it can run is a script he could already tap in the app menu, so this
adds a ROUTE to existing things rather than new power.

**That matters because the server binds 0.0.0.0.** Anything looser is a
box on his WiFi that runs what it is told. Verified against the real
server with raw sockets, not just the test suite: `gba;rm -rf /`,
`../../etc/passwd`, a NUL byte and `wiki'&&touch /tmp/pwned` all come
back *"not a thing this deck knows how to open"*, and `/tmp/pwned` was
never created.

**THE FIRST LAYOUT WAS WRONG AND A SCREENSHOT CAUGHT IT.** `auto-fit`
left Game Boy orphaned on a row of its own with half the panel empty.
Every test passed. Rendering it headless at the panel's real 1024x600
and LOOKING took ten seconds -- fourth time in two days that looking is
what found it, after the iris ring, the painted eye, and the mouth
tones. **For anything with a layout or a picture, render it and look.**
It is a 2x2 now, four equal thumb targets, her tile white so it is
unmistakably the main one.

**The clock says when the board has not reached the network.** It has
no RTC and starts at 1969 until NTP lands -- already recorded as the
likely cause of a TLS failure. On screen that is a `clock not set` line
rather than a time that is quietly, confidently wrong.

**A tap that appears to do nothing reads as a broken deck**, so every
tile says what it is doing and says it long enough to read. The failure
messages name the fix: no terminal installed says `sudo apt install -y
xterm`, and a dead server says to start `~/YUZU/face`.

**Autostart is OPT-IN and it is a WINDOW, not a kiosk.** `--autostart`
is a separate word from installing the icons, `--remove` undoes it, and
the page opens in an ordinary browser window he can close onto the
normal desktop. CLAUDE.md is blunt about why and it has been earned:
**a UI that can trap him is strictly worse than a terminal**, because
there is not even a keyboard to type an exit into. Two power cycles
already paid for that rule.

**STILL NOT BUILT: the `ghost` passcode screen.** Deliberately left,
and not from lack of time. A lock screen wants text entry, and on a
touchscreen with no keyboard attached that means building an on-screen
keypad -- which is exactly the kind of thing that traps him if it has a
bug. It needs to be designed as something he can always get out of
before it is worth writing. `DECK_UI.md` still holds the shape of it.

## OPEN, and Ghost asked to be reminded: the right-angle adapters

Sept 9, from a Gemini hardware pass he forwarded. Not ordered yet, and
the only thing on that list worth spending money on:

- **90-degree DisplayPort adapter.** His BENFEI DP->HDMI dongle IS the
  adapter, so this is a 90-degree DP->HDMI **or** a right-angle HDMI
  extension after it -- not both doing the same job.
- **Right-angle 5.5x2.5mm DC power adapter.** The most valuable of the
  three. A barrel jack is the easiest connector on that board to snap,
  and a stiff cable leaving a rigid metal case is pure leverage on it.
- **Angled USB-A / USB-C adapters** for the panel's touch feed.

**The KKSB case is what makes these matter.** A cable sticking straight
out of a metal enclosure has nowhere to bend, so every knock goes into
the port. Cheap parts, real failure mode, and the one that breaks is
the one that stops the whole deck.

The rest of that Gemini pass is recorded under "Kokoro and WhisperTRT"
below. **He asked to be reminded about the adapters specifically** --
*"maybe remind me soon ill forget that bit"* -- so it goes at the top
of the next hardware conversation, the same way `nvpmodel -m 0` does.

## Kokoro TTS and WhisperTRT — worth it, and NOT yet

Same forwarded pass. Both are good calls on the merits and both are
being held, for reasons that are about this project rather than about
the tools:

- **Kokoro TTS (82M params).** Piper works and sounds like a robot;
  Kokoro sounds like a person and still fits in memory. The real cost
  is that it is a PyTorch dependency, and "installs nothing" is what
  lets `yuzu_all_in_one.py` run in Pydroid on his phone. Worth breaking
  that rule LATER, behind exactly the guard Piper already has -- one
  module, one try/except, prints if absent.
- **WhisperTRT.** Speech-in is the last real stub in the project and
  the Orin is why it is possible at all. But that is four models
  sharing 8GB, and the memory reading above is the FLOOR (idle, no
  model loaded), not the ceiling. Measure with the model resident
  before designing around it.

**Rive / Lottie for the face: NO.** It is a library fetched from a CDN,
and this deck's whole point is that it works with the WiFi off. The
web-UI route Gemini recommends is what already exists -- and his own
PNGs beat the SVG it suggests.

## `tile` — Pop Shell, because a 10" panel is the wrong shape for floating windows

Ghost floated it: *"Install a GNOME extension like Pop Shell or Forge...
Ubuntu will auto-tile her avatar, terminal, and Kiwix into a clean,
grid-like HUD layout with zero wasted screen space. maybe that too"*

    ~/YUZU/tile            install and turn it on
    ~/YUZU/tile --off      floating windows back, still installed
    ~/YUZU/tile --remove   uninstall
    ~/YUZU/tile --status   is it on

**POP SHELL IS NOT PACKAGED ON UBUNTU. Measured on the board:**

    E: Unable to locate package gnome-shell-extension-pop-shell

I wrote "Ubuntu ships it, so this is one apt package" into the script's
own output and it was simply wrong -- Pop Shell lives in **Pop!_OS's**
repos, not Ubuntu's. The good part is that the script said what to do
next in the same breath ("If it says 'Unable to locate package', this
Ubuntu does not carry Pop Shell and Forge is the fallback"), so a wrong
claim cost one apt run instead of an evening. **Write the fallback into
the failure message, not into a doc he will not open.**

**FORGE NOW INSTALLS AUTOMATICALLY, AND WITHOUT A BROWSER.** That is
the constraint that actually mattered -- not which extension wins. The
obvious route is extensions.gnome.org in a browser, and he has one
serial terminal. So `tile` asks the site's JSON endpoint which zip
matches THIS GNOME version and hands it to `gnome-extensions install`.
Asking rather than guessing a URL is what survives the next GNOME
release. Pop Shell is still tried first, because it is one apt line and
costs two seconds.

**FORGE INSTALLED CLEANLY ON THE BOARD -- and then the enable step was
a dead end.** Verified live: `Forge downloaded and installed.` followed
immediately by *"Installed, but GNOME has not picked it up yet. In the
desktop press Alt+F2, type r, press Enter."* Ghost: *"i cant hit
alt-f2-r-enter until i get the keyboard and screen goin"*.

**Correct advice, and useless, which is this project's oldest mistake
in a new costume.** `pkill` in another terminal, SSH as a second
session, mGBA's Refresh button -- every one of them was true and out of
his reach. **Never ship an instruction that needs hardware he does not
have.**

The fix is that the restart was never necessary. `gnome-extensions
enable` only works on an extension the running shell has already
LOADED, and shells load new ones at startup -- but all it ultimately
does is put the uuid in `org.gnome.shell enabled-extensions`, and THAT
key is read at every GNOME startup. So `tile` writes it directly and
says the true thing: nothing to do, it turns itself on the first time
he logs into the desktop with the panel attached. Alt+F2 stays, as an
aside for when he has a keyboard, and a test pins that it appears
AFTER the sentence saying waiting is enough.

**THIRD INSTANCE IN ONE EVENING, and it printed both halves in a row:**

    Forge downloaded and installed.
    Nothing installed itself. Its output is above.

`have()` asked `gnome-extensions list`, which reports what the RUNNING
SHELL HAS LOADED -- and a shell loads new extensions at startup. So it
is guaranteed to say no in exactly the moment the script needs a yes.
The extension is a directory; the fix is to look at the directory
(`~/.local/share/gnome-shell/extensions/<uuid>`).

**Same evening, same question, three times: TigerVNC's happy
`xdpyinfo`, `gnome-extensions enable` needing a shell restart, and now
`gnome-extensions list` on a fresh install.** All three are the GNOME/X
layer answering about its own cached view rather than about the world.
*What would this check say if the thing were broken in the way it
actually is?* -- and here, worse: what would it say if the thing were
WORKING?

**Forge's keyboard shortcuts are NOT printed**, deliberately. They were
never verified on this board, and unverified keystrokes stated as steps
already cost an hour on the 8BitDo -- they send a person debugging
their own hands. Pop Shell's `Super + Y` is documented and is printed;
Forge's branch says where to look instead. `~/YUZU/tile --off` is the
escape either way and needs no shortcut at all.

**GNOME IS RUNNING ON THAT BOARD.** The prediction above -- that the
VNC session is a bare X session and tiling would have nothing to do --
was wrong: `tile` got past `pgrep -x gnome-shell` and went straight to
apt. Good news, and worth correcting rather than leaving as a warning
about a problem that does not exist.

**The original reasoning, kept because the shape of it still holds:**
Both tile. Pop Shell is what System76 ships on hardware they sell, so
Ubuntu packages it -- one `apt install`, no extension-store round trip
in a browser on a phone. Forge is newer and more configurable and
installs from a website: more steps, more to go wrong, over a serial
link.

**--off is a SEPARATE WORD from --remove, deliberately.** A GNOME
extension can leave a desktop that will not draw, and his only shell is
a serial cable. The cheap escape must not be the same word that throws
the package away. Cheaper still and printed every time: **Super + Y**
toggles tiling live, from inside the session, with no terminal at all.

**It checks GNOME is RUNNING, not that it is INSTALLED, and that
distinction probably decides whether it does anything tonight.** Ubuntu
ships `gnome-shell`, so the package check is true on that board -- but
the only desktop he has today is the VNC session, started from
`~/.vnc/xstartup`, and the handoff describes that as "a minimal X
session". A bare X session has no shell for an extension to live in.
`command -v gnome-shell` would have said yes the entire time nothing
was tiling: the same shape as `xdpyinfo` answering happily through a
loopback-only VNC bind. `pgrep -x gnome-shell` is the honest check, and
the two failures get DIFFERENT messages because they have different
fixes -- installed-but-not-running names `~/.vnc/xstartup` as the place
the desktop is chosen.

**So the likely outcome on his board right now is "GNOME is installed
but not running", and that is correct rather than broken.** Tiling
needs a real desktop; the 10.1" panel is what makes it worth having.

**It refuses politely off GNOME rather than failing inside apt**, and
it says what it is about to do before doing it. UNVERIFIED on the
board, same standing as `deckapps`.

**Gaps are 2px.** On 1024x600 every pixel of gap is a pixel of Kiwix.

## `face` — you look at her on the PHONE until the panel lands (Sept 9)

Ghost: *"leme plug her in and run that. then how do i look at her
again? recall current setup. (flip 6 and the nano xD"*

    ~/YUZU/face            serve it, print the address to open
    ~/YUZU/face --off      stop
    ~/YUZU/face --status   is it up, and can the phone reach it

**The phone IS the screen, and that was the whole answer.** The 7"
panel is ~20 days out, the board may not have a browser, and a VNC
session is a lot of moving parts to look at a static page. His Flip 6
is already a touchscreen with a browser on it, the face is built for
touch, and `ui/face.html` has zero external references -- so a plain
`python3 -m http.server` on port 8081 is the entire delivery
mechanism. When the panel arrives the same page opens locally and
nothing changes but the client.

**MY OWN CHECK REPORTED "IT DID NOT COME UP" ABOUT A SERVER THAT WAS
SERVING PERFECTLY.** Fifth instance of the evening's pattern, and the
second one that was mine end to end. `serving()` connected to the LAN
address -- correct reasoning, it is exactly what the phone does -- and
on a box with no routable address that returns nothing to connect to.
So a server that was up, bound and answering was reported as failed to
start, with its own happy log printed underneath as evidence.

**The fix is that it was TWO QUESTIONS wearing one function's name:**

    up()         is the server running at all?     -> 127.0.0.1
    reachable()  can the PHONE get to it?          -> the LAN address

They have different answers and, more to the point, **different
fixes**: not-running needs a restart, running-but-unreachable needs
WiFi. Collapsing them meant one of the two could never be reported.
That is the same shape as `pad` saying "not paired" about a controller
plugged in and working, and the same shape as `xdpyinfo` answering
happily through a loopback-only VNC bind.

**`lan_ip` returns EMPTY, never a placeholder.** The first version
echoed `<board is offline>` and the caller then tried to connect to
it. A sentence dressed as an address means no caller can tell "no
network" from "here is the address" -- which is precisely the
distinction the split exists to make.

**It falls back to `hostname -I` when `ip route` says nothing, and
FILTERS it.** Docker's `172.17.0.1` and the USB-gadget link
`192.168.55.1` both sort ahead of the real address, and picking the
first line has now cost this project time three times. A test puts the
decoys ahead of the real one on purpose.

**`YUZU_FACE_PORT` exists so the SUITE can drive the real script.** The
tests start it on a free port, stub `ip`/`hostname` to fake both a
networked board and an offline one, fetch the page and byte-compare it
against `ui/face.html`. The no-network case is the one that would have
caught the bug, and it is the test this class exists for.

**An intermittent red in `TestGbaLauncher` turned out to be the test
racing a CORRECT detach.** It failed about one run in eight with
`'Pokemon - Emerald...' not found in ''` -- which reads as a launcher
that never started the game. It is not: `gba` runs the emulator with
`nohup ... &` on purpose, so the script returns before the stub binary
has written its line, and the test read the file immediately. It now
polls for the line with a deadline. **A flaky test about backgrounded
work is almost always the test, and an intermittent red is worse than
a solid one** -- it teaches you to re-run instead of to look.

**Same `ss` dependency is still in `gba` and `wiki`.** Both parse
`ss -ltn`, and `ss` is not guaranteed -- it was missing on the machine
this was developed against. On the Orin it is present so nothing is
broken today, but if either ever reports a working server as down,
this is the first place to look. Not changed now: they are working on
the board and one variable at a time.

## `deckapps` — real app icons, because a touchscreen is not a terminal

Ghost, Sept 9: *"as far as the https blah blah number number in a
browser can we please go an 'app' route for when i have the monitor
touch screen... like a ui that opens when i click an app."*

Right call, and it is the first request that is about the deck being a
FINISHED OBJECT rather than a project. Typing `192.168.4.136:8080` is
fine over a serial link and absurd on a 7" panel you are holding.

    ~/YUZU/deckapps            install the launchers
    ~/YUZU/deckapps --remove   take them off

Three icons, in the app menu and on the Desktop: **Saya**, **Wikipedia**,
**Game Boy**. A `.desktop` file IS what an app is on Linux, so this
needs nothing installed and no new dependency.

**The wiki opens CHROMELESS** -- `chromium --app=` gives a window with
no url bar and no tabs, so it reads as an application rather than as a
web page. That is the actual request; a normal browser window would be
the same problem in a nicer costume.

**It uses `127.0.0.1`, not the LAN address.** Every other tool here
prints the routing-table IP because the PHONE is the client. On the
deck's own screen the client is the deck, and loopback never changes
with the network.

**The launcher STARTS the server before opening it**, and waits for
the port. A tap that lands on a dead port is the same dead end,
prettier. A test pins the ordering.

**A missing browser SKIPS rather than installing a dead icon**, and
names the package to install. An icon that opens nothing when tapped
reads as a broken deck rather than a missing package -- and Game Boy
still installs, because a partial install is not a failure.

**Neither browser nor terminal is known to be on that board.** The
script detects what is actually there rather than assuming, and says
which one it wants. UNVERIFIED until it runs on the deck.

## Is this a unicorn? Roughly yes, and the reasons are useful

Ghost: *"i havent seen a single cyberdeck with a nano orin super btw."*

Cyberdecks are overwhelmingly Raspberry Pi. Jetson decks exist but are
rare and usually old Nanos in robotics rigs, not handhelds. **A deck
built on an Orin Nano Super whose purpose is a local LLM character is
genuinely unusual**, and the reasons it is rare are all things this
project has already hit:

- **DisplayPort only.** Every Pi build says "plug in HDMI"; this needs
  an adapter, which is why one is in the parts list.
- **8GB shared** between CPU and GPU. That is the whole `keep_alive`
  argument.
- **ARM64.** No x86 binaries -- ES-DE needed the AArch64 AppImage
  specifically.
- **Power.** A Pi sips ~5W; this wants ~25W at MAXN, which is why the
  runtime figure is still arithmetic rather than measurement.

**The payoff is the part a Pi cannot do at all**: no Pi runs a 3B model
at conversational speed, because it has no real GPU. The compute is the
entire justification for the awkwardness -- and it is what makes
on-device Whisper realistic later.

Do not oversell this to him as "nobody has ever done it" -- that is not
checkable. The defensible claim is the one above: unusual combination,
for a reason, with a payoff that matches what he actually wants.

## `wiki` — offline Wikipedia, one word (Sept 9)

Ghost, after parking the controller: *"lets focus on PC stuff and Ai
stuff and kiwix."*

    ~/YUZU/wiki            start it, print the address to open
    ~/YUZU/wiki --off      stop it
    ~/YUZU/wiki --status   is it up, and where

**This exists because of the power-cycle.** The earlier attempt ran
`kiwix-serve` in the FOREGROUND. It held the terminal, which on a
phone serial link is indistinguishable from a frozen board -- `q`, `cd`
and `sudo poweroff` all went into a process that was not a shell, and
Ghost pulled power rather than lose the session. Nothing was damaged
and he was right that it was his only visible option. **`nohup ... &`,
always**, and a test asserts the launch line is detached.

**It finds the .zim itself**, newest first, under `$HOME`, `/media`
and `/mnt`. His archive is `wikipedia_en_simple_all_nopic_2026-05.zim`,
982MB -- a path that long is not something to retype on a phone
keyboard, and a no-argument script he can tap Run on is the standing
preference in this file.

**Every lesson from tonight is already in it:** it checks for a
NON-LOOPBACK listener rather than a live process (the TigerVNC
finding), prints the routing-table LAN address rather than the first
line of `hostname -I` (which has now cost time three times), leaves a
running server alone rather than dropping what he is reading, and
prints kiwix-serve's OWN output when it fails to come up.

## `/wiki` — she answers from a real encyclopedia now (Sept 9)

Ghost: *"build it bro. Saya gunna be so smart!"* Built.

    You: /wiki black holes
    Saya: [answers from the actual article, in her own voice]

`yuzu_wiki.py`, stdlib only, so the phone property survives. The chat
loop substitutes the lookup for what he typed and everything
downstream -- history, streaming, voice -- is unchanged.

**The extract arrives as a USER turn, not a system instruction, and
that is the most important line in the file.** Assistant collapse is
this deck's signature failure and it is already MEASURED once: asked
how to centre a div she produced markdown headings and fenced code
blocks. A wall of encyclopedia text delivered as a system message is
the shortest path back to that. So it reads as something HE said --
*"I looked up X and it says: ... Tell me about it in your own words"* --
which keeps it conversation and asks for her register explicitly. A
test pins the phrasing.

**Capped at 700 chars and cut on a SENTENCE.** `num_ctx` is 4096 on
the Orin, shared with her whole prompt and eight turns of history, and
half a clause is worse than none -- she would answer from a thought
that stops mid-way.

**Two endpoints, because kiwix-serve is not pinned.** Newer builds
answer `/suggest` with JSON; older ones only have `/search` returning
HTML. It tries the clean one and falls back to scraping article links.
Both paths are tested against a REAL HTTP server serving canned
responses, because what decides this is parsing what kiwix-serve
actually returns.

**A missing server is STARTED, not reported.** First live use said
*"The wiki isn't running. Start it in another terminal with:
~/YUZU/wiki"* -- accurate, and still a dead end, because he has ONE
serial terminal. Acting on it meant quitting the chat, starting a
server and restarting the chat, mid-sentence. `look_up` now calls
`start_server()`, which runs `~/YUZU/wiki` (idempotent, backgrounds
itself) and WAITS for the port, because kiwix-serve binds a second or
two after forking and returning immediately would report failure on a
server that was nearly ready.

Same rule the app launcher already follows: **a request that lands on
a dead port should start the thing, not report on it.** Only a wiki
that will not come up returns a sentence -- and it still names the
command, and still never raises. `yuzu_brain` guards the import
exactly like Piper's, so the file being absent never stops her
talking.

**Script tags, infoboxes and `[12]` citation markers are stripped.**
Piper would read every one of them out loud.

**NOT VERIFIED: a real ZIM through a real kiwix-serve.** Everything
here is exercised against a stub. The parsing is the risky half and
his archive is the only thing that can confirm it -- same standing
limit as every "tested in a sim" claim in this file. `python3
yuzu_wiki.py black holes` on the board answers it in ten seconds.

## `gba` — one word to play (Sept 9)

Ghost: *"help make it easier to just open gameboy with a smaller
code."* The real command was three lines -- a `vncserver` invocation,
a `DISPLAY=:1` prefix and a glob -- and none of that is something to
retype on a phone keyboard.

    ~/YUZU/gba            newest ROM in ~/ROMs/gba
    ~/YUZU/gba soul       newest ROM matching "soul"
    ~/YUZU/gba --off      stop the emulator and the desktop

Shell rather than Python, deliberately: it launches X apps and manages
a VNC session, which is what a shell is good at. **He connects with
AVNC**, so it prints the address to point AVNC at rather than assuming
he remembers it.

Four decisions in it worth keeping, each from a mistake this project
has already made:

- **`nohup ... &`, never foreground.** A foreground process on a phone
  serial link looks EXACTLY like a freeze -- that already cost one
  power-cycle of this board when a foreground `kiwix-serve` was read as
  a hang. A test asserts the launch line is detached.
- **Check that the PHONE can reach it, not that X is running.** See
  the loopback finding below -- this is where the first version was
  wrong, and it was wrong in the most convincing way available.
- **The ROM is resolved BEFORE anything starts**, so a typo fails in a
  second rather than after a desktop has spun up.
- **`lan_ip` never returns empty.** A bare `:5901` reads as a bug in
  the script when it really means "this board is not on the network" --
  a different problem with a different fix.

**A test caught a bad test here, which is the part worth remembering.**
The first version of `test_every_rom_path_is_quoted` matched SOURCE
TEXT and flagged `$ROMS` inside a quoted `echo` string -- correct code,
false alarm. It was replaced by a BEHAVIOUR test that runs the real
script against stub `vncserver`/`mgba-qt`/`xdpyinfo` binaries and
asserts the path arriving at the emulator. The quoting bug it exists to
catch is real -- his one ROM is `Pokemon - Emerald Version (USA,
Europe) (patched).gba`, spaces and parentheses -- and it would surface
as `mgba-qt: Pokemon: No such file`, which reads like a missing ROM
rather than a quoting fault.

**Grepping source text is a proxy; running the thing is the test.**
Same lesson the Jetson round produced from the other direction.

## `pad` — pairing the 8BitDo (Sept 9). SoulGold runs.

**The deck plays games now.** SoulGold booted on the Orin, in mGBA,
through the VNC session, from a ROM sent over by `drop.py`. Screenshot
confirms the title screen.

Ghost then produced an **8BitDo Micro**, so `pad` wraps the pairing.

    ~/YUZU/pad            find, pair, trust and connect it
    ~/YUZU/pad --status   is it actually usable right now
    ~/YUZU/pad --forget   drop the pairing and start clean

`bluetoothctl` is a REPL -- `scan on`, wait, read a wall of MAC
addresses, `pair <mac>` -- which is a bad time on a phone keyboard over
a serial link, and every step of it is scriptable.

**It checks for a GAMEPAD, not a Bluetooth link, and that distinction
is the whole point.** A pad can be connected at the BT layer and expose
no input device: `bluetoothctl` says `Connected: yes`, mGBA sees
nothing, and the two states are indistinguishable from anything
bluetoothctl can show you. So `pad` also greps
`/proc/bus/input/devices` -- SDL (what mGBA uses) reads evdev, so that
is the layer that decides whether a game can see it.

**That is the SECOND time in one hour.** TigerVNC's loopback bind was
the same shape: the obvious check was true the entire time the thing
was broken. Written down together because the pattern is now the most
productive debugging question this project has -- *what would this
check say if the thing were broken in the way it actually is?*

**A failed search lists every device the board CAN see.** Dead ends are
where he gets stuck, and "it didn't work" becomes "the pad isn't in
pairing mode" the moment the alternatives are on screen.

**It runs `trust` as well as `pair`.** Without it the pad needs
re-pairing after every power cycle, which on a handheld deck means
every time it is put down.

**THE CABLE WON. `pad` now says so first.** After an hour of bonding
failures, the pad plugged into one of the devkit's **USB-A** ports
appeared instantly:

    N: Name="8BitDo 8BitDo Micro gamepad"

No pairing, no bonding, no agent, nothing to debug. `pad` now detects a
wired gamepad BEFORE prompting for anything and tells him he is already
done; `--status` reports a USB pad rather than "not paired", which was
a flatly wrong answer about a controller that was plugged in and
working.

**A cable is not a workaround on this build.** The deck has USB ports
and will be sitting on a desk. Bluetooth is the harder path AND the
optional one -- offer the easy one first.

**One trap worth naming: the devkit's USB-C port is the phone's serial
console.** Saying "plug it in" without saying which port sent him to
the one already in use.

**THE BUTTON COMBOS WERE WRONG AND WERE STATED AS INSTRUCTIONS.**
Ghost, with the pad in his hand: *"ur button combls dont matcj how it
seems to work idk im just having alot of trouble."* `START + A` and
`START + B` came from the generic 8BitDo convention, were flagged here
as unverified, and were then printed to him as numbered steps anyway --
so he went hunting for buttons that are not on his pad while the real
fault was bonding.

The script now describes **the STATE to reach** ("the light must FLASH,
not sit solid") and lets him use whatever his pad's pair button does.
A test pins that the combos are gone.

**Generalisable: when he can see the hardware and I cannot, name the
goal, not the keystrokes.** Unverified specifics presented as steps are
worse than no steps -- they send a person debugging their own hands.

## THE VERDICT GOES FIRST — my own output made the same mistake

`pad --status` on a **working** wired controller printed:

    Paired:     E4:17:D8:F6:23:CC
    Bluetooth:  NOT connected
    Bonded:     NO -- BlueZ will refuse the gamepad
    Gamepad:    visible to games

Two alarming lines about a transport that **is not in use**, and the
one line that decides everything last. Ghost read it as broken. It was
working, and had been for two minutes.

This is the fourth instance of the evening's pattern and the only one
that was mine end to end: **reporting the layers AROUND the answer.**
TigerVNC, the unbonded pad, BlueZ's `Success (0)` -- and then my own
status output doing it to him again.

`--status` now leads with the verdict:

    WORKING. The kernel sees the controller.
    If mGBA is ALREADY RUNNING it will not notice -- restart it.

**RESTART mGBA, do not press Refresh.** The pad appeared at 17:38;
mGBA had been running since 17:20. Its controller dropdown stayed empty
and every mapping box refused input, so it read as a broken UI. **SDL
enumerates controllers at STARTUP** and mGBA's Refresh button is
unreliable for hotplug -- telling him to press it sent him clicking at
a screen that could not work. Every message now says
`~/YUZU/gba --off && ~/YUZU/gba` instead.

## 8BITDO IS PARKED. Ghost's call, Sept 9

*"also gave up on 8bitdo for now. lets focus on PC stuff and Ai stuff
and kiwix."* Fair -- it cost well over an hour across bonding failures,
two wrong theories of mine, and button combos I should never have
stated as instructions.

**Where it actually stands, for whoever picks it up:**

- **USB WORKS.** `N: Name="8BitDo 8BitDo Micro gamepad"` appeared the
  moment it was plugged into a **USB-A** port awake. That is the path.
- **The pad sleeps and then only charges.** Red LED = charging, not
  connected. Wake it BEFORE plugging in.
- **mGBA was never restarted after the pad appeared**, so the last
  known state is "pad works, emulator never looked". That is the very
  next thing to try, and it may simply be done.
- **Bluetooth is unresolved** and the real error is in
  `/tmp/pad-pair.log` on the board, never read. `Bonded: no` with
  BlueZ logging `Success` on its own rejection is as far as it got.

and when it is not working, says what to DO -- wake the pad first,
then plug it into a **USB-A** port, because a sleeping pad only
charges. A verdict with no next step just relocates the problem.

**`PAD_INPUTS` makes the check testable.** `has_input_node` reads
`/proc/bus/input/devices`, which is a property of the HOST -- exactly
the thing that made two Jetson tests unrunnable off a Jetson. The path
is overridable so the suite drives both "pad present" and "pad absent"
from fixtures instead of asserting whatever is plugged in today.

## PAIRED IS NOT BONDED — and BlueZ logs Success on the rejection

The `pad` warning fired on the first real run: connected, no gamepad.
Two wrong theories before the log gave it up (`uhid` not loaded --
`/dev/uhid` was already there; wrong pairing mode -- `bluetoothctl
info` showed a proper HID device advertising `Human Interface
Device`). The answer was one line of `journalctl -u bluetooth`:

    hidp_add_connection() Rejected connection from !bonded device
    input-hid state changed: connecting -> connected (0)
    device_profile_connected() input-hid Success (0)

**BlueZ refuses HID to an unbonded device, then logs `Success (0)` on
the connection it just rejected.** Every layer above -- `Connected:
yes`, `bluetoothctl connect` printing "Connection successful", the
policy plugin adding a reconnect entry -- reported a working
controller. The single field telling the truth was `Bonded: no`.

**The cause was in `pad` itself.** It ran `bluetoothctl pair`, `trust`
and `connect` as three separate commands. Each one starts an agent,
does its thing, and EXITS -- so **the pairing agent dies before bonding
completes.** The fix is to pipe the whole sequence into ONE session:

    bluetoothctl <<BT
    power on
    agent NoInputNoOutput
    default-agent
    pair $MAC
    trust $MAC
    connect $MAC
    BT

`--status` now prints `Bonded:` alongside `Connected:`, and a
half-pairing is cleared with `remove` and retried once automatically,
because BlueZ keeps the bad state until the device is removed entirely.

**THIRD TIME IN ONE EVENING that the obvious check was true while the
thing was broken.** TigerVNC bound to loopback with a live session and
a happy `xdpyinfo`; a pad "connected" with no input device; and now
BlueZ reporting Success on a refusal. The question that found all three
is the same one: **what would this check say if the thing were broken
in the way it actually is?** If the answer is "the same thing", it is
not a check.

The corollary, and the reason this cost an hour: **read the log of the
layer that is failing, not the status of the layers around it.**
`bluetoothctl info`, `vncserver -list` and `ps` all describe
neighbours. `journalctl -u bluetooth` named it in one line.

## TigerVNC binds to LOOPBACK by default, and every local signal lied

First real run of `gba`: it reported success, printed the address, and
AVNC would not connect. **Everything checkable from the board said it
was working.**

    vncserver -list    1  5901  9170  Xtigervnc      <- session exists
    xdpyinfo           answers                       <- X is alive
    the process        running                       <- not crashed
    ss -ltn            LISTEN 127.0.0.1:5901         <- THE ANSWER
    the log            "on local interface(s), port 5901"

**Modern TigerVNC defaults to `-localhost yes`.** It was listening for
connections from the board to itself. No phone on that network could
ever reach it, and nothing said so -- the log line is honest but reads
like a status message rather than an exclusion.

Two changes, and the second matters more than the first:

1. `vncserver` is now invoked with **`-localhost no`**.
2. **The check became "is a non-loopback listener on 5901" instead of
   "is X running".** The original used `xdpyinfo`, which was true the
   entire time the thing was broken.

**A check that cannot observe the actual failure mode is not a check.**
That is the generalisable line, and this repo keeps re-deriving it:
`actions_runnable` passed vacuously on replies with no actions;
`yuzu_doctor` read the environment while the truth was in the request
body; the two Jetson tests asserted properties of the host machine.
Every one of them reported healthy while the real thing was broken.

The script now also **fails loudly and prints what it IS listening
on** if the desktop comes up unreachable, rather than cheerfully
printing an address that will not work. And it **leaves a healthy
session alone** -- restarting one would drop him mid-game.

`TestGbaLauncher` drives the real script against a stub `ss` that
reports his exact broken state, and asserts the repair happens.

## drop.py — getting a file from the phone onto the board (Sept 9)

Ghost patched a ROM on his phone and there was **no good way to get it
across.** Serial USB Terminal has no scp, the file has no URL to
`wget`, and the microSD is the rescue image. The same gap already cost
real time once: when the board's `git push` failed on auth, two
persona files had to be rescued by `cat` and hand-paste.

`drop.py` closes it. Run it on the board, open the URL it prints on the
phone, pick a file. Stdlib only, ~80 lines, no install.

    cd ~/ROMs/gba && python3 ~/YUZU/drop.py

**Files land in the folder you START it from**, which is the whole
interface -- no path typing on a phone keyboard.

**It prints the LAN address, not loopback**, computed by opening a UDP
socket toward 8.8.8.8 and reading back which local address the routing
table picked (no packet is sent). That is deliberate: this project has
now lost time TWICE to picking the wrong line out of `hostname -I`
(the Kiwix session and the VNC session both landed on `192.168.55.1`
or the docker bridge). A test pins that it never returns 127.0.0.1.

**The one dangerous line is the filename**, and it is tested with four
hostile inputs. `os.path.basename` after normalising backslashes, so
`../../../../etc/passwd` writes `passwd` into the current folder and
nothing escapes. Verified live as well as in the suite.

**It STOPS BY ITSELF after one file.** Ghost asked how to macro a
Ctrl-C, which is the wrong thing to have to ask -- his phone terminal
has no easy one, and a server he cannot stop is worse than one that
quits too early. So one file and out is the default; `--stay` is the
opt-in for several, and `pkill -f drop.py` ends that.

**The shutdown happens AFTER the reply is written**, and a test pins
that ordering. Stopping from inside the handler before the response
goes out cuts it off mid-flight, and the phone shows a network error
over a file that arrived perfectly intact -- the worst kind of false
alarm, because the obvious response is to send it again.

**It is deliberately NOT a general file server.** GET serves one page,
POST accepts one file. Nothing lists or reads the disk, so even while
up it is an inbox, not a filesystem.

**Prefer `git pull` over pasting a long script into the serial
terminal.** That link drops characters on anything long -- already
recorded here -- and a silently truncated script is a worse failure
than a slow transfer. Anything over a few lines goes in the repo.

## The microSD is the RESCUE IMAGE. Do not format it (Sept 9)

Ghost asked how to reuse the card now that the system is cloned onto
the NVMe and the card is physically out.

**Answer: leave it alone.** It is a bootable clone of a WORKING, tuned
Jetson -- Ollama env vars applied, un-throttled, personas present. If
the NVMe dies, or something goes wrong during the case build, that
card is a two-minute recovery. Nothing ~60GB of extra storage buys
comes close, and the 512GB NVMe is mostly empty anyway.

**The risk if it goes back in the slot: the board may BOOT FROM IT.**
He would land in the old clone, everything would look subtly stale,
and recent work would appear to have vanished -- it has not, it is on
the other disk. That is the same confusion shape as running the wrong
Shiro: right system, wrong body. `lsblk` before panicking.

**Never put swap on it** -- sustained writes, which is what kills
cards, and this file already says swap belongs on the NVMe.

If it is ever repurposed anyway, read-heavy content only (Kiwix ZIMs,
ROM backups). Not the model, not swap, not anything hot.

## The board has no RTC, and it probably explains the TLS failure

Ghost ran `journalctl -p 3 -xb` on the Orin, Sept 9. Four errors, none
of them faults:

- `optee` / `arm_ffa` -- a secure-boot driver looking for a bus NVIDIA
  does not enable on the devkit. Once per boot, forever, harmless.
- `camera-diag ... error: -19` -- ENODEV. There is no camera attached.
- `nvidia-cdi-refresh.service` failed -- that service hands the GPU to
  DOCKER CONTAINERS. Ollama runs natively. Irrelevant here.
- `systemd-networkd-wait-online: Timeout` -- waits for every interface
  (docker0, the USB gadget link, WiFi) and one never completes, so it
  burns its full timeout at every boot. Likely the reason boot feels
  slow. `sudo systemctl disable systemd-networkd-wait-online.service`.

**The finding is in the TIMESTAMPS.** The log carries `Dec 31
18:00:30` -- that is the Unix clock at zero, in UTC-6. **The Orin Nano
devkit ships with no RTC battery**, so every boot starts at epoch and
stays there until NTP reaches the network.

**REVISES an earlier call.** This file recorded a `git pull` failing
with `server certificate verification failed`, and recorded that the
clock theory was checked and WRONG because `date` came back correct.
That check was made minutes later, after NTP had already fixed it. A
certificate is invalid if the clock thinks it is 1969, and the window
where that is true is exactly the first minute of uptime -- which is
when someone who just booted the board is typing.

**CONFIRMED, Sept 10, and it cost him a session.** Four seconds after
logging in:

    fatal: unable to access 'https://github.com/GhostMagi/YUZU.git/':
    server certificate verification failed. CAfile: none CRLfile: none

He then ran `face`, got the OLD art, and asked why the new faces had
not arrived. **They had not arrived because the pull failed** -- but
the failure scrolled past above a wall of Ubuntu login banner, and the
very next command printed a cheerful "UP. Open this on your phone."

So the theory below is now a finding, and the practical rule stands:
**a TLS failure on a freshly booted board is the clock. Wait thirty
seconds and retry rather than debugging it.**

**`~/YUZU/pull` exists so it cannot happen again.** It waits for the
clock (watching `date +%Y`, not sleeping blind), retries with backoff,
and **puts the VERDICT FIRST** -- `UPDATED`, `ALREADY UP TO DATE` or
`PULL FAILED` -- above the git output rather than under it. A
certificate error names the clock; an unresolved host names WiFi; local
changes say nothing was touched. And when `ui/sprites/` moved it says
HER FACE CHANGED, because a cached page showing the old art is the same
confusion one layer up.

**The general shape, and this project keeps meeting it: a failure that
scrolls past is a failure that did not happen, as far as the person is
concerned.** The next command's success message is what he read. Same
family as `pad --status` burying its verdict, and the fix is the same
one: the answer goes above the evidence.

The general lesson is one this file already has in another form:
checking a symptom AFTER the system self-corrects proves nothing about
the moment of failure. Same shape as the `keep_alive` layers, where
both readings looked right on their own.

## SAYA IS LIVE (Sept 9). `LIVE_PERSONA = "saya_deck"`

Ghost's call: *"lets just make saya the main for now if possible."*
Shiro is not deleted, retired or changed -- `shiro_deck` is untouched
and one line brings her back. The promotion rule worked exactly as
designed for the second time.

**The target is `saya_deck`, never `saya`.** The quad file is
`built=no` and was the last persona built on the rotten scaffold;
`saya_deck` is the one on the measured blocks and the one with the
self-concept win.

**SIXTH INSTANCE OF THE NAME LEAK, and it was down to ONE test.** Last
promotion turned eight tests red. This one turned one:
`test_sampling_options_are_sent` asserted `temperature == 0.8`, which
was SHIRO's number rather than a property of the brain -- Saya runs
0.85. Pinning by name last round is why the other seven stayed quiet,
which is a fair advert for doing it that way. The test now reads the
value off the persona, so the next promotion is quieter still.

The rule is unchanged and now has six data points: **decide whether a
fact belongs to THIS CHARACTER or to WHOEVER IS LIVE, and pin it
accordingly.**

**Saya has never been scored by the eval, same as every deck persona.**
She is also the character with the least measured history in the repo
-- her quad version was the rotten-scaffold one and was never run
properly either. Treat her as UNMEASURED in the strongest sense.

**What to watch for specifically, given the archetype.** A tsundere's
failure mode is the opposite of Shiro's. Shiro ran LONG and escalated;
the risk with Saya is she runs SHORT and cold enough to read as
stonewalling, because "Hmph, whatever" is a complete tsundere reply and
a bad conversation. Her own brevity rule and her examples are what hold
that line. If she comes back curt and flat over a few real
conversations, that is the thing to look at -- and the fix shape this
repo keeps proving is ONE EXAMPLE, not a rule.

**The two corrections below were written when this was still a
consideration; keeping them because both are still true:**

- **Shiro is yami kawaii, not a gyaru.** Yuzu is the gyaru. The
  handoff has them crossed.
- **There is no 1B model here and personas do not carry one.** Every
  Modelfile is `FROM llama3.2:3b`, and which weights answer is a
  `--model` / Modelfile choice, not a persona setting. Saya on the
  deck would run on whatever Shiro runs on.

## Ghost's own note, in his words (Sept 9)

*"i dont understand this stuff much yet make note of that and stuff.
lot goin on rn irl."*

Written down because it changes how to answer him, not just what to
answer. He is running this project on a phone, in a week where real
life is loud, and he is TRUSTING the reasoning rather than checking it.
So:

- **Give the command, not the explanation of the command.** One
  paste-able line beats a paragraph about what it does.
- **State the decision, then the reason, in that order** -- and keep
  the reason to a sentence unless he asks.
- **Never make him choose between options he has no basis to judge.**
  Pick the better one, say which, say why in one line, and move.
- He absorbs a LOT when it is written plainly -- the record of this
  project is mostly his own findings. The gap is vocabulary and spare
  attention, not capability. Do not talk down.

## The deck is a COMPUTER too, not just a place she lives (Sept 9)

Ghost, via a hardware-planning session: the deck should "eventually
pull double duty as a usable general-purpose computer, not just an AI
companion to talk to." That reframes a decision this file recorded
confidently in the other direction.

`OLLAMA_KEEP_ALIVE` moves `-1` -> `30m` everywhere: the doctor's
expected value, the systemd block in JETSON_SETUP.md and
NANO_DAY_ONE.md, the troubleshooting row, and the test that pins the
unit file. The reasoning for `-1` was never wrong, it just assumed the
board had no other job.

**The interesting part: the request body already won.** A per-request
`keep_alive` overrides the environment variable, and `yuzu_brain.py`
has sent one on every call since the keep-alive work went in
(`YUZU_KEEP_ALIVE`, default `30m`). So Shiro's traffic was ALREADY
unloading at 30m while the unit file said "never unload" and the doctor
cheerfully reported it correct. The two layers disagreed for days and
nothing surfaced it, because both readings looked right on their own.

Check the request body before the environment. That is the general
lesson and it is not specific to Ollama.

## CYBERDECK PARTS — LOCKED SPEC, still NOT BOUGHT (Sept 9, v2)

Big parts ~20 days out. **The only hardware actually owned is the Orin
Nano Super devkit, its 512GB NVMe, and the keyboard.** Do not write
anything that assumes the rest exists.

    power     Xiwai USB-C PD 65W -> 5.5x2.5mm barrel, centre +   ~$60
              JSAUX 20,000mAh 65W USB-C PD bank ($49.99)
    display   HAMTYSAN 10.1" 1024x600 IPS touch, HDMI in ($56.99) ~$66
              BENFEI 4K DisplayPort->HDMI, PASSIVE ($8.99)
    audio     USB sound card, mic in + amplified 8ohm/5W out     ~$31
              on one JST header, driver-free ($18.99)
              Waveshare 8ohm 5W dual-driver speaker ($11.99)
    keyboard  Arteck Bluetooth. OWNED. Measured 10" x 6.5".       $0
    case      HUL 18" two-tone aluminium, Pick-N-Pluck foam      ~$55
    board     KKSB aluminium devkit enclosure, VESA ($22.90)     ~$23
    mounting  Jiahezhi 440pc nylon standoff/screw kit, M2.5+M3   ~$10
    cables    ZIIYAN 163pc sleeve/clip/strap kit                 ~$10
                                                        total  ~$255

**MEASUREMENTS TAKEN. Do not re-ask for these.**

    Arteck keyboard              10" x 6.5"
    devkit height, fan+heatsink  ~1.9-2"
    case interior                17.3" x 12.4" x 4.3"
    case exterior                17.9" x 14.4" x 5.1"

The 4.3" interior depth clears the devkit with real room to spare, and
17.3 x 12.4 swallows a 10" keyboard and a 7" panel side by side. **This
is a big deck** -- that was a looks-prioritised choice and it is his.

**SCREEN CHANGED TO 10.1", Sept 9.** He looked at 13" and came back
to 10.1" himself (HAMTYSAN, $56.99, same 1024x600 as the 7"). Same
resolution on a bigger panel, so `ui/face.html` and the VNC session
need no change at all -- everything already built for 1024x600 is
still exactly right. Bigger and heavier in the lid, and the case
swallows it: 17.3 x 12.4 interior takes a 10" keyboard and a 10"
panel side by side, which the 7" was never the constraint on.

**THE KKSB DEVKIT CASE IS A REAL FARADAY RISK, unlike the outer one.**
$22.90, aluminium, VESA mount, and it wraps the board on ALL SIX SIDES.
The outer HUL case was cleared because it is an aluminium FRAME with
ABS panels -- cosmetic metal, no cage. This one is not cosmetic.

The product photo answers it: the back panel is drilled for **two SMA
antenna connectors**, which is what a metal box has to do. So before
ordering, check the listing for what it actually includes:

- If SMA pigtails and antennas are in the box: fine, and arguably
  BETTER than stock -- external antennas outside a metal enclosure
  beat internal ones inside it.
- If they are not: the devkit's WiFi antennas end up sealed inside
  aluminium, and WiFi and Bluetooth both degrade. He needs two
  IPEX/U.FL-to-SMA pigtails and two 2.4/5GHz SMA antennas, about $10.

**This is the one thing on the list that can quietly break the deck**,
because WiFi is how the phone reaches her, how `face` is served, and
how the Bluetooth keyboard connects. A range test after assembly was
already the plan for the outer case; with this one it is mandatory.

Also worth one look before it ships: **3.2 stars over 55 ratings** is
low for a $23 part, and the devkit with its fan and heatsink measures
~1.9-2" tall. Check the reviews specifically for fan clearance and
thermals -- a case that traps heat costs performance on a board whose
whole justification is compute.

**THE FARADAY QUESTION WAS CHECKED AND ANSWERED.** This file warned
that an all-metal enclosure is a cage, and his keyboard is Bluetooth
while the board needs WiFi. The HUL case is aluminium FRAMED with ABS
panels -- cosmetic metal, not a sealed shell -- so there is no real RF
shielding and he has accepted that knowingly. Good outcome: the warning
was raised, verified, and closed rather than assumed either way.

Residual worth one test rather than one assumption: an antenna sitting
directly against an aluminium frame can still lose range locally even
with no cage. **Check Bluetooth keyboard range once assembled** instead
of trusting the geometry.

**Nylon standoffs, deliberately.** Non-conductive, so a stray standoff
cannot short anything on the carrier board. M2.5 is stated to cover the
devkit's mounting holes -- **verify against the real board** before
drilling foam around it.

**PC MODE is a real goal, not a metaphor.** The board runs full Ubuntu
ARM64: browser, terminal, editors, LibreOffice, all native. The only
hard limit is the architecture -- no Windows software, no x86-only
Linux binaries. This is exactly why `OLLAMA_KEEP_ALIVE` moved off `-1`:
CPU and GPU share ONE memory pool, so whatever Ollama holds is RAM the
PC side never gets.

**Floated, not scoped: Kiwix/ZIM offline wiki archives.** An offline
Wikipedia on the deck would pair well with an offline character, and
the NVMe has the room. Nobody has committed to it. If it happens, it is
storage and a reader, not a model -- so it costs disk, not the 8GB.

Still unmeasured and worth doing the moment it is powered: **actual
current draw at `nvpmodel -m 0`**, to check the ~2.5-3h runtime figure,
which is arithmetic and not measurement.

## FIFTH NAME-LEAK: two personas, one name, one boot banner (Sept 9)

Ghost ran `python3 yuzu_brain.py --persona shiro --chat` by hand, got
`[walks backward]` and `[shakes legs]`, and asked **"is that bleed?"**

It was not. `shiro` is the RETIRED hexapod persona and `shiro_deck` is
the live one, and they share a `name:` -- so **both printed
`persona: Shiro` at boot.** He had the right character on a body that
no longer exists and nothing on screen said so. That is a completely
fair reading of the evidence he was given.

Fifth instance of the class this file keeps tripping over: **the name
is not the identity, the KEY is.** The banner now prints
`Shiro (shiro_deck) [no body]` -- key whenever it differs from the
name, and a `[no body]` marker straight off `Persona.moves`, so a
bracket-emitting reply next to "[no body]" is instantly readable as
the wrong persona rather than a mystery. `TestBootBanner` pins both.

**Guard against this when adding a character.** Two files sharing a
`name:` is legitimate and deliberate here (same character, two bodies),
so the fix belongs in what gets DISPLAYED, not in forbidding it.

## Deck Shiro, live round Sept 9 morning — the good one

Long natural conversation, no test prompts. Findings:

**THE SELF-CONCEPT CRACK IS CLOSED.** Round 3 produced *"if you want me
to 'walk' over to the kitchen or wherever, I can do that too"*. This
round, told his cat would sleep on her case:

    [whispers conspiratorially] Don't worry, I won't mind the weight.
    It's not like I'm made of fragile little glass or anything...
    although, technically, I am a handheld computer with no legs, so
    maybe that's a bit true? [winks]

Correct about her own body, unprompted, AND used as the joke. That is
the deck self-concept working, not just surviving.

**Bracket stage directions everywhere and it reads fine** --
`[squeals with delight]`, `[bounces up and down in "virtual" seat]`,
`[laughs maniacally]`, `[pauses for dramatic effect]`. All silent
through Piper, all readable on screen. The relaxation is doing exactly
what it was relaxed for.

**Her best line was relational, not trivia:** *"I'll just... exist
quietly in the corner of your computer. [whispers] But don't think I
won't be here when you're ready to chat again..."*

**NEW FAULT: THE SPOOKY-FACT LOOP.** She volunteered unprompted trivia
repeatedly -- zombie ant fungus, wasps, and the immortal jellyfish
**twice**, once in an earlier session and again here. Ghost called it
twice: *"yea yea u always go for that fact"* and *"chill on the
facts."* She complied when told to, which is the good news.

Diagnosis, and it is the familiar shape: asked to be spooky she has no
demonstrated move EXCEPT trivia, so she reaches for a small pool of
go-to facts. Her rule 5 names the dark half in the abstract (decay,
hunger, being watched) and every example that lands is relational --
but nothing shows her being spooky ABOUT HIM rather than about nature
documentaries. Same diagnosis as the bare-command and
technical-question findings, which the one-example lever fixed both
times. NOT applied yet: she is a character and the call is Ghost's.

## The suite had never been run on a Jetson until Sept 8

Ghost ran `YUZU_TESTER.py` on the Orin for the first time and got
**`Ran 298 tests in 123.554s` / `FAILED (failures=2)`** -- on the exact
files that pass everywhere else. Both were real, both were in
`TestThrottleReminder`, and neither was reachable off the target
hardware. Reproduced here by simulating an Orin rather than making him
re-run it over a serial link that kept dropping.

- **`test_detection_never_raises_off_a_jetson` asserted `False`.** The
  name says "never raises"; the assertion said "is not a Jetson". Only
  true off one. Replaced by two tests that mean something on any
  machine: `test_the_two_copies_of_the_jetson_check_agree` (the real
  invariant -- `yuzu_doctor.on_a_jetson` and
  `yuzu_all_in_one._on_a_jetson` are duplicated ON PURPOSE so the
  doctor can ship as a lone download, and if they drift, the reminder
  appears in one place and not the other), and
  `test_detection_answers_both_ways_and_never_raises`, which fakes the
  marker file instead of assuming its absence.

- **`test_the_doctor_stays_quiet_on_a_phone` was reading dirt from
  earlier tests.** `yuzu_doctor.notes` is a module-level list every
  check appends to and `summary()` prints all of it, but the test
  helper only isolated `on_a_jetson`. Off a Jetson `check_jetson()`
  adds nothing so the leak is invisible; ON one it appends "Run: sudo
  nvpmodel -m 0" and the assertion trips. The test was right and the
  harness was dirty. `render_summary` now saves, clears and restores
  `notes`.

**The general lesson: a test that can only pass on the machine you
wrote it on is not passing, it is untested.** Anything asserting a
property of the HOST -- hardware present, file absent, binary missing
-- should fake the condition both ways rather than assume today's
machine. Piper is the next candidate: it is installed on the Orin and
absent here, and those tests happen to be well isolated already.

**Simulating the board beats waiting for it.** The serial link from
the phone drops on anything longer than a minute, and the suite takes
two on that box. Faking detection found the failure count in one run;
faking the filesystem at BOTH layers (`os.path.exists` AND
`pathlib.Path.exists` -- `Path.exists` goes through `os.stat` and does
not see a patched `os.path.exists`) confirmed the fix. Getting that
second detail wrong made the two copies disagree and the new agreement
test caught it, which is a fair advert for the test.

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
`yuzu_personas.py`.** It is now **`shiro_deck`** -- see the cyberdeck
section above; it was `yuzu4` for the whole hexapod era, and `yuzu4` is
still the measured winner OF THAT LINEAGE. `yuzu_brain --chat` and the
eval boot from whatever it points at.

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

## Byte — persona #3, Sept 4

Ghost's brief: *"named Byte... lean into a Cyberpunk vibe (NOT the
game, just as a general vibe)... female as usual. not weeb stuff like
usual. Tech!"* plus *"maybe she likes videogames"* and *"keep it trim
as possible while being neat"*.

Netrunner, not a `-dere` -- that is the point of the brief. Dry, quick,
clipped tech slang. Likes videogames (movement tech, speedruns,
anything she can break), rooftops at 3am, rain on neon.

**3396 chars, the trimmest of the three** (yuzu4 3785, coco 4058).
Seven rules, seven examples, all nine measured wins. Built on
`{HARDWARE_MENU}` + `{DIALOGUE_RULE_V2}` + `{MOVEMENT_RULE_V2}` --
the same blocks the winning arm uses, so she starts where Yuzu ended
rather than where Yuzu began.

Verified by machine: every example speaks AND moves, every bracketed
phrase runs through the real parser, every spoken line is already
TTS-clean (`for_speech` changes nothing), and her own text carries none
of Yuzu's register. NOT verified: how the model actually plays her.
`python3 YUZU_AB.py yuzu4 byte` when there is a spare fifteen minutes.

**The register check caught two things and the second was in COCO.**
Byte's rule 5 originally read *"No hype, no stacked exclamation marks,
nothing cute"* -- three negations, one of which is literally Yuzu's own
word. Rewritten as what she IS: *"State it flat and move on."* Shorter
too.

Then the generalised test found *"no hype"* sitting in Coco's rule 5 as
well. Dropped the token from her, kept every formatting constraint
around it -- a nine-character edit, not a rewrite of a working
character.

The evidence that tone-negations hurt is thin (the measured
pink-elephant cases are all about naming an ACTION or a FORMAT, like
`[winks]` or an asterisk, not a mood). But it costs nothing to describe
what a character is instead of what she isn't, and consistency across
three of them is worth having.

**`test_every_character_carries_the_measured_wins` replaces the
Coco-only version.** It derives the character list from the persona
files -- anyone whose `name` differs from the live arm's -- so persona
#4 is covered the day it lands, with no list to maintain. The archives
(yuzu2/3/5/6) stay exempt; yuzu2 lacks the bare-command example by
definition.

**Byte is a THIRD data point for the open issue below.** She would be
handed "Ehehe~" by the shared body block too. Three characters now, two
of them wrong for it.

## SOLVED: character bleed from the shared body file

Ghost, Sept 4: *"i still feel like theres a way to solve the bleeding
over of personalities."* He was right, and it was a three-line change.

**The problem.** `_hardware_muto_s2.txt` is for SERVO FACTS -- this
file has said so since a character stance in there collared every
persona at once ("your whole world is the room you're standing in").
But the sounds rule still shipped Yuzu's own examples, `Ehehe~, Haha!,
Ugh, Ooh`, to everybody. A kuudere and a netrunner were being handed a
gyaru's vocabulary by a file about legs. Coco produced `[Ehehe~]` in
her first live conversation; Byte would have too.

**The fix: a persona can override any block by naming it in ALL_CAPS
above the `---`.**

    SOUND_EXAMPLES: Ah, Oh, Huh

`load()` merges those over the hardware blocks before expansion. The
RULE ("sounds are words, never brackets") is a body fact and stays
shared. The EXAMPLES are character and now come from the character.

**Nothing moved.** The `[SOUND_EXAMPLES]` default is Yuzu's exact
list, so all EIGHT composed prompts came out byte-identical -- verified
by capturing every prompt before the change and diffing after. No A/B
was invalidated, no re-test needed. That was the objection that blocked
this for two days and it is simply gone.

    yuzu2..yuzu6   Ehehe~, Haha!, Ugh, Ooh   (unchanged, default)
    coco           Ah, Oh, Huh
    byte           Heh, Ha, Huh

Every one of those is deliberately vowel-carrying, so espeak
phonemises it instead of spelling it out. `Hm` and `Tch` are NOT taught
-- vowel-less, and never heard through Piper. A test asserts every
taught sound survives `for_speech`, because teaching her a sound the
voice drops is worse than teaching none.

**A test that asserted the wart now asserts the fix.**
`TestCoco.test_her_sound_register_is_her_own_not_the_gyaru_one` used to
open "KNOWN WART, deliberately handled here rather than in the shared
body file... editing the shared file would change yuzu2's composed
prompt mid-A/B". That objection was correct and is now satisfied, so
the test flipped from pinning the wart to pinning its absence.

**One test needed narrowing, correctly.**
`test_the_body_rules_are_identical_across_both_characters` compared
body text up to the closing sounds line. Sound examples are per
character now, so it compares up to the sounds RULE instead -- the
self-concept, the bracket rule and the action menu must still be
identical across every character on the chassis. That is the real
guarantee: one character must never be taught moves another isn't.

**The mechanism generalises.** Any future character-flavoured token in
a shared body file gets the same treatment: token it out, default it to
whatever the lineage already says, override per persona. And a persona
that overrides a block badly enough to drop a measured win is caught by
`test_every_character_carries_the_measured_wins`, which reads the
COMPOSED prompt.

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
- **`OLLAMA_KEEP_ALIVE=30m`. CHANGED FROM `-1`, Sept 9.** Ollama
  unloads an idle model after five minutes, which is too short -- step
  away for a coffee and the next thing you say gets the slowest reply
  she ever gives. `-1` (never unload) was the right answer while the
  board did nothing but run her. **The cyberdeck is also meant to be a
  usable general-purpose computer**, so pinning 3GB-odd of the shared
  8GB forever works against that; 30m keeps her instant through any
  real conversation and gives the memory back when nobody is talking.
  Set `-1` only if the board is hers alone. Set `0` while bringing
  Whisper up alongside her and you need the memory back between turns.

  **A per-request `keep_alive` BEATS the environment variable**, and
  `yuzu_brain.py` has always sent one (`YUZU_KEEP_ALIVE`, default
  `30m`). So Shiro's own traffic was ALREADY unloading at 30m no matter
  what the systemd unit said -- the `-1` in the unit only ever governed
  other clients, like a bare `ollama run` in a terminal. Worth knowing
  before anyone debugs this layer: check the request body before the
  environment.
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
