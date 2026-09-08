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
- Run `python YUZU_TESTER.py` before committing. 329 tests, ~18 seconds.

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
(that repo path is confirmed working). 329 tests pass on it. Getting it
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

**Worth measuring rather than assuming: what ES-DE plus a running X
session leave for Ollama.** Nobody has looked. `free -h` with the VNC
session up, before and after her first reply, answers it in ten
seconds and would catch a swap problem before it looks like her being
slow.

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

**Not verified: the button combos.** `START + A` for D-input and
`START + B` for Switch mode are what the script tells him to use, taken
from the standard 8BitDo convention rather than from this pad in his
hands. The mode turned out NOT to be the problem (see below), so they
have still never been tested.

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

Not proof, and the original "transient, retry worked" is consistent
with both readings. But it fits better than nothing, and the practical
rule is the same either way: **a TLS failure on a freshly booted board
is the clock. Wait thirty seconds and retry rather than debugging it.**

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
    display   7" 1024x600 IPS capacitive touch, HDMI in ($46.99) ~$56
              BENFEI 4K DisplayPort->HDMI, PASSIVE ($8.99)
    audio     USB sound card, mic in + amplified 8ohm/5W out     ~$31
              on one JST header, driver-free ($18.99)
              Waveshare 8ohm 5W dual-driver speaker ($11.99)
    keyboard  Arteck Bluetooth. OWNED. Measured 10" x 6.5".       $0
    case      HUL 18" two-tone aluminium, Pick-N-Pluck foam      ~$55
    mounting  Jiahezhi 440pc nylon standoff/screw kit, M2.5+M3   ~$10
    cables    ZIIYAN 163pc sleeve/clip/strap kit                 ~$10
                                                        total  ~$222

**MEASUREMENTS TAKEN. Do not re-ask for these.**

    Arteck keyboard              10" x 6.5"
    devkit height, fan+heatsink  ~1.9-2"
    case interior                17.3" x 12.4" x 4.3"
    case exterior                17.9" x 14.4" x 5.1"

The 4.3" interior depth clears the devkit with real room to spare, and
17.3 x 12.4 swallows a 10" keyboard and a 7" panel side by side. **This
is a big deck** -- that was a looks-prioritised choice and it is his.

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
