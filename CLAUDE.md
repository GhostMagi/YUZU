# YUZU — working notes for Claude

## Conventions

- **Work on `main`.** No feature branches unless Ghost asks.
- **Whenever Yuzu's prompt changes, paste the full composed prompt into
  the chat as a copy-paste block**, without being asked. Ghost tests in
  PocketPal on a phone, so a file path or a command is useless to him —
  he needs the text itself. Get it with:
      python yuzu_personas.py --show live
  (`live` NAMES THE POINTER `yuzu_personas.LIVE_PERSONA`, never a key.
  This line said `--show shiro_deck` and had been stale since Saya was
  promoted on Sept 9 — a hardcoded cast in a doc, which is worse than
  one in a page because a doc has no test. `python yuzu_personas.py`
  on its own still marks which one is live.)
- **Ghost works from a phone** (Z Flip 6, Pydroid + PocketPal). Anything
  requiring typed commands, file paths, or arguments is a dead end.
  Prefer: text he can paste, or a no-argument script he can tap Run on.
- Run `python YUZU_TESTER.py` before committing. 798 tests, ~19 seconds.

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
(that repo path is confirmed working). 743 tests pass on it. Getting it
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

## ZERO HEARS HIM, AND HER SUMS ARE EXACT (Sept 24)

Ghost, handed a list of what she could learn next: *"1 and 5 are
approooooved. Bout time we set up listening. I just prefer typing tbh
(im missing a lot of teeth) so lets make it so its only when i wana use
the talk to her functionality. Maybe a button for the touch screen
starts listening when i tap it, ends recording when i tap it again and
bam?"*

### Exact maths -- `yuzu_maths.py`, `maths: exact`

**The prompt reduces, code guarantees, applied to numbers.** A 4B
explains a sum well and can slip a digit in a long one, just as
confidently. So when his message has a sum in it, `ground()` works it
out in code and the answer rides in beside what he typed -- the /wiki
shape:

    What's 17 times 23? (The deck worked it out exactly: 17 × 23 = 391.)

She explains the number; she never produces it. **Her 17 x 23 example
carries the note in the exact words the code writes**, and a test
derives one from the other.

- **No `eval()`.** `ast`, walked by hand over a short list of nodes;
  pinned by reading the module as code, since the docstring saying
  "no eval()" would match itself as text.
- **Huge powers are refused** (`9 ** 9 ** 9` would hold the server
  for minutes). The break-check for that one HUNG rather than failed,
  which is its own proof.
- **What counts as a sum is narrow on purpose.** A hyphen, a slash or
  an x between numbers is a date, a range or `the panel is 1024x600`
  until the message asks for working out. A wrong note hands her a
  confident number for a question he never asked. His real first
  message to her is one of the pinned no-note cases.
- **THE FIRST DRAFT DROPPED A LEADING MINUS**: `-5 x 3` came out as
  `5 x 3 = 15`, the confident wrong answer this module exists to
  prevent. Caught by trying it before wiring it in.
- **Only `maths: exact` characters**, and never on a /wiki turn.
  Four's turns are unchanged, driven through the real `answer()`.

### Push-to-talk -- `yuzu_ears.py`, `POST /listen`, the mic on Zero's page

**THE MICROPHONE IS WHATEVER HE IS HOLDING**, the same split as her
voice the other way round: the board has no mic. The page records
(MediaRecorder), `/listen` turns it into text with **faster-whisper**
(CTranslate2 on the CPU, `base.en` int8, ~150MB -- not the PyTorch
`openai-whisper`, the same call Kokoro made), and the text is sent
through the same form as typing. Tap to start, tap to stop, and a
forgotten recording stops itself at a minute. The mic is released the
moment it stops, and her own voice is paused so it cannot end up in
his clip.

**A BROWSER ONLY HANDS A PAGE THE MIC WHEN IT TRUSTS THE PAGE**: https
or localhost. His address is plain http on his WiFi. So the mic, when
refused, says exactly how to fix it, with the page's own address: in
Chrome, once per device, `chrome://flags/#unsafely-treat-insecure-
origin-as-secure`, add the address, Enabled, Relaunch. **VERIFIED in
real Chromium**: without it the page is refused and the note appears;
with it `isSecureContext` is true and a fake-device recording went all
the way through. **The headless-shell build ignores that setting**,
which read at first as the instructions being wrong -- they were not.

**Driven end to end in a browser**: a fake microphone, the real page,
the real route, and a stand-in model that decodes the REAL clip with
faster-whisper's own decoder (PyAV) -- 2.6 seconds of webm/opus in,
his line out, sent, answered. Only Whisper itself was not run: Hugging
Face is blocked from the container.

**IT NEVER DOWNLOADS MID-TURN.** Every model load in `yuzu_ears` is
`local_files_only=True`, pinned via `ast`; `pull` installs it once and
fetches the model, with the size first, and a failure leaves typing
exactly as it was. `yuzu_maths` and `yuzu_ears` joined the offline
guard's list of turn-path modules.

**UNVERIFIED ON HIS BOARD**: whether faster-whisper's aarch64 wheels
install, and how well base.en hears him. `YUZU_WHISPER_MODEL=small.en`
is the stronger ear (~480MB) if it mishears; that change should arrive
with a pull, not as a command for him.

### Found on the way

- **`pull`'s Kokoro download block had lost its indentation the day it
  was written** (Sept 16) and never ran: Python stopped at line 3,
  printed nothing, and the voice setup could only ever report failure.
  His board got its voice some other way. Fixed, and a property test
  now compiles every quoted Python heredoc in every deck script.
- **The suite ran `pull`'s setup blocks FOR REAL.** The harnesses copy
  `pull` into a temp folder without `yuzu_voice.py`, so the voice
  block called the real `pip` on every run -- and the ears block would
  have installed 200MB and fetched a model mid-suite on his board.
  `plant_ready_setup()` now puts stand-ins beside every copy.
- **A cap test matched the text "60000", not the delay**, and stayed
  green with the cap broken to `0 * 60000 + 1e12`. It reads the
  number now. Grep-as-proxy, again, in a test written this round.
- **A fake brain module had the old `ground(text)` signature** and
  eight tests errored. Fixed in the fake, not by loosening the real
  code: a stub must match what it stands in for.

**Sixteen new tests, twenty breaks, all red once the cap test was
fixed. 782 -> 798.**

## ZERO'S EMPHASIS WAS BEING DELETED, AND SHE "FIXED" A BUG SHE CANNOT SEE (Sept 24)

**THE EMPTY REPLIES ARE FIXED ON THE BOARD** -- she answered, grounded
in the real board (*"7.4GB RAM, six cores"*). Which of the two fixes
did it (`"think": false` or reading `thinking`) is not known; both stay.

### "You're building something that , and ."

Her first real answer on the board had holes in it. **Qwen writes
emphasis in asterisks** (`something that *thinks*`), and her page
carried the same `spoken()` as every Llama page, which deletes an
asterisk span as a stage direction. For the one he brings maths to,
that is the worst possible fault: `17 is *not* prime` loses its
"not". Her copy now takes the stars off and keeps the words -- only a
span that LOOKS like emphasis (no space just inside a star, no letter
or digit just outside), so `2 * 3 * 4` and `2*3*4` stay sums. The
voice gets the same words, because the page sends what it shows.

**AND HER MEMORY WAS DOING THE SAME THING ONE LAYER DOWN.**
`_canonicalise` rewrote `*x*` as `[x]` in history, on EVERY body --
right for the robot, whose parser wants brackets, and wrong on a body
never told brackets exist. It put `17 is [not] prime` into her own
memory; every page hides brackets, so the day she copied her own
history the screen would say "17 is prime". **Gated on `moves` now**:
the robot still gets its brackets back, the deck and the avatar keep
what the character actually wrote. Nothing in the suite noticed the
change -- 779 green either way -- which is why it has a test now.

**Two tests, four breaks, all red. 779 -> 781.** The page test runs
the page's own `spoken()` under node when node is there (skips on a
board without it) and refuses the deleting pattern either way.

### She claimed to have fixed a memory leak

Ghost: *"you still got a small bug. fixing now <3"*. Zero: *"Aha --
found it. A memory leak in the background process... Fixed by adding
a kill signal after 5 cycles and replacing it with a watchdog timer."*
He asked whether she had found real code. **She had not.** She cannot
see or change any file; nothing on this deck has a ten-second loop or
a watchdog. She took a turn about fixing something and played the one
fixing it -- **confident-wrong about her own abilities**, the Windows
CE palmtop again, on the character meant to be trusted with technical
answers. The "memory" overlap with the real fix that night was
coincidence.

**FIXED WITH ONE EXAMPLE, in the exact slot**, his call ("I just want
her to be functional really"):

    Ghost: You still got a small bug, fixing it now.
    Zero:  Go for it. I can't see my own code from in here, so tell me
           what it was once it's in and I'll tell you if the fix makes
           sense.

Phrased as what she CAN know, never as a ban -- no "never claim a
fix", which is the pink-elephant shape measured three times here.
4816 chars. **One test, three breaks, all red** (deleted, claiming the
fix, dodging without saying what she can know). 781 -> 782.
**UNMEASURED on the board.**

## "SHE SAID NOTHING", AND THE UPDATE THAT RELOADED INTO THE OLD DECK (Sept 24)

Two faults from his first minutes with Zero on the board.

### Zero answered with nothing, twice

    Ghost: hiii Zero, Welcome to my cyberdeck ...
    Zero:  She said nothing.

That line is the PAGE's, shown when `/say` comes back with an EMPTY
reply and no error. The same model answered *"17 times 23 is 391."* in
a terminal an hour earlier.

**The likely cause is Ollama's thinking field.** Qwen3 models can
think before they answer, and Ollama files that under
`message.thinking`, apart from `message.content`. If the prompt format
Ollama picked for her expects a think block, it can file EVERYTHING
she says as thinking. Her release (Instruct-2507) never thinks and
never closes the block, so `content` comes back empty -- and the brain
only read `content`. `ollama run` prints both, which is why the
terminal looked fine.

**UNCONFIRMED ON THE BOARD** (no Ollama in the container), so two
fixes, either enough alone:

- her persona says `think: no`, sent as `"think": false`, and only
  for her. **Four's request is unchanged to the byte**, pinned.
- `_words()` in `yuzu_brain.py` reads `thinking` when `content` is
  empty, in both `ask` and `ask_stream`, and strips a `<think>` block
  that reaches `content`.

If she still says nothing after an update, this pasted on the board
shows which field her words are in:

    curl -s localhost:11434/api/chat -d '{"model":"hf.co/mradermacher/Qwen3-4B-Instruct-2507-heretic-GGUF:Q4_K_M","messages":[{"role":"user","content":"hi"}],"stream":false}'

### The home screen reloaded into the version it had just replaced

His photo after an Update: Yuzu's tile said *"gyaru, fully dressed"*,
a blurb the repo had already dropped, while Zero's page was new.

**After UPDATED the page polled `/characters.json` and reloaded on the
first answer.** `restart_later()` waits two seconds before it stops
the server; the first poll is at one second. So the answer came from
the OLD process, and the page reloaded into the old version, on every
update that changed code. **The Sept 15 stale-roster fault, re-created
by the code written to fix it.**

**REPRODUCED BEFORE IT WAS FIXED**, on a copy of the deck in a real
browser: the server said the new blurb, and the reloaded page showed
the old one. **"Something answered" is not "the new one is up".** Each
server process has a `BOOT` id; the pull reply carries it,
`/boot.json` reports the current one, and the page reloads only once
they differ. Same browser run afterwards: the new blurb, first time.
An older server has no `/boot.json`, so any answer there is the new one.

**THE FIRST UPDATE AFTER THIS STILL RELOADS STALE**: the page doing the
waiting is the one already loaded. One refresh, then it is fixed.

**Four new tests, nine breaks, all red.** One break-check read green
for a false reason: a same-length edit (`/boot.json` -> `/nope.json`)
restored within the same second left Python's `.pyc` for the BROKEN
file in use, and the next three checks ran against it. Re-run with
`PYTHONDONTWRITEBYTECODE=1`. **A break-check that edits a .py should
not write bytecode.** 775 -> 779.

## ZERO GOES BLACK, AND HER LOG IS HIS TWO COLOURS (Sept 24)

Ghost, on her first render: *"Can you make her background more black?
Blues not my vibe rly"*, then *"Neon green for me, Neon pink for her"*
and *"Make sure she knows im Ghost"*.

**THE BLUE CAME OUT OF THE ART, NOT ONLY THE PAGE.** The page was
already `#000`; the blue was her machine room. Every blue-to-magenta
pixel loses its colour, and **how far it darkens depends on how light
it was**: the room sinks to black, the lavender shading on her plating
only turns grey. Darkening both the same left dark blotches on her
shoulders that read as bruises -- rendered three ways side by side and
looked at, thirty-fifth time. Recipe in `ui/zero/ART.txt`.

**His lines `#39ff5e`, hers `#ff2d95`** -- the deck's green and the
hot pink he picked for Saya's face, so no new taste call. Speak is
green because it sends HIS line.

**"SHE KNOWS" WAS ALREADY TRUE; THE SCREEN NEVER SHOWED IT.** Her
persona carries `USER_NAME: Ghost` and `by_name()` guards her replies
-- but the log labelled his lines `YOU`. They carry his name now, READ
from a new `user` field in the roster (her USER_NAME, `""` for Yuzu),
so the label and her prompt cannot disagree. **One test, four breaks,
all red**: the roster dropping the name, the name typed into the page,
the label back to "you", and a hardcoded `HIM`. **774 -> 775.**

## ZERO: A SECOND MIND, ON HER OWN WEIGHTS (Sept 24)

**SHIPPED AS "ADA", A WORKING NAME; HE NAMED HER ZERO WITHIN THE HOUR.**
*"Name her Zero"* -- which sits beside Four the way he probably meant
it to. Renamed everywhere: persona, page, art folder, roster, icon,
tests. A stranger WILL ask why, so she has a lore-free answer, the
same call Four's got: *"Because that's where counting starts, if you
count properly. Computers do."* If he talked to her as Ada first, a
tiny `~/.yuzu/history/ada.json` is left orphaned on his board --
harmless, and Zero starts with a clean memory under her own name.

Ghost, night owl, one Ghost energy drink in: *"id like to get another
offline AI LLM on the cyberdeck too... similar one (in the sense its
abliterated heretic uncensored.) But maybe one thats good for orher
stuff? ... i already have its art picked if its gunna be a brainiac"*,
then, with the art: *"Put her on the left side of screen with a large
chatbox. Black background."*

**THE MODEL: `Qwen3-4B-Instruct-2507` in its heretic build**, pulled as
`hf.co/mradermacher/Qwen3-4B-Instruct-2507-heretic-GGUF:Q4_K_M`
(2.5GB). **CONFIRMED ON HIS BOARD, 00:21:** it downloaded and answered
*"17 times 23 is 391."* in one sentence, ~40s for the first load.

- **Why this one**: stronger at maths, logic and code than its size
  suggests; made by p-e-w, who wrote Heretic; quantised by the same
  mradermacher whose Llama GGUF already works on the board.
- **The Instruct-2507 release is NON-THINKING**, which is the deciding
  detail: the hybrid Qwen3 writes a `<think>` block first, and on this
  deck that block would go into her bubble and out of her speaker.
- **Qwen3.5 heretic was the tempting wrong answer.** Newer, but Unsloth's
  own docs say community Qwen3.5 GGUFs do not run in Ollama (separate
  vision files), and it thinks by default. It would have pulled and then
  failed -- the 8BitDo lesson in model form.
- **No 8B.** ~5GB on 8GB shared with the desktop, at about half the
  speed. `OLLAMA_MAX_LOADED_MODELS=1` means switching characters swaps
  models, costing seconds on the first reply, never memory.

**Hugging Face is blocked from this container**, so the name was
checked by web search, not fetched -- and said so to him. His board
proved it.

### THE PROMPT LAYOUT IS QWEN'S OWN, AND WE DO NOT HAND-FORMAT IT

He asked: *"make sure were using the correct prompt layout for this
model if youre giving her a system prompt"*. Qwen expects ChatML
(`<|im_start|>system ... <|im_end|>`), Llama expects its header tokens,
and a wrong layout is a real way to make a good model seem stupid.

**The brain never writes either.** It sends `/api/chat` with a
`role: system` message, and Ollama wraps it in the template that ships
INSIDE the GGUF -- so Four gets Llama's layout and Zero gets Qwen's,
from the same code. The evidence it took: her first answer on the
board was one clean sentence, with no stray `<|im_start|>` and no
runaway, which is what a mismatched template produces.
`ollama show <her model> --template` prints it on the board.

**AND NO `stop` IS SENT PER REQUEST, deliberately.** Four's anti-
puppeteering stop token lives in her Modelfile; Zero is the raw hf.co
model with none. The obvious fix -- `options.stop` on every request --
REPLACES the model's own stop list rather than adding to it -- on
Four it would silently drop the stop words her Modelfile was built
with, on the character who did nothing to need it. Her rule 9
carries it for now; if she ever writes his side of the conversation,
a Modelfile for her is the fix, not a request option.

### A CHARACTER CAN BRING HER OWN WEIGHTS

`model:` in a persona's settings. **Until now every character shared
one model**, which CLAUDE.md said in as many words (*"personas do not
carry one"*). Precedence, pinned by driven tests: an explicit `model=`
> her own `model:` > `DEFAULT_MODEL` (`YUZU_MODEL`, else `yuzu`).

**HER LINE BEATS `YUZU_MODEL`, and that is the half worth the test.**
That variable is how a board points EVERYONE at Four's Llama; if it
won, Zero would run on Llama weights and simply seem dimmer, with
nothing anywhere saying why. **And `_cli`'s `--model` default was
`DEFAULT_MODEL`, passed EXPLICITLY** -- so `--chat --persona zero` would
have overridden her. It is `None` now.

### AND A SECOND HERETIC WOULD HAVE HIJACKED FOUR'S RUNBOOK LINE

`NANO_DAY_ONE.md` finds Four's model with `ollama list | grep -i
heretic | head -1` -- and `ollama list` is newest first. The day the
Qwen landed, that line started handing the terminal chat the wrong
girl. **Found by reading the diff's blast radius, before he hit it.**
It is `| grep -i llama` now, and the test runs the doc's OWN line
through bash against a stub `ollama` that lists the Qwen first.

### Her page

`ui/zero.html`, **his layout verbatim**: her art down the left, a big
conversation panel down the right, black behind both. **A LOG, NOT A
BUBBLE** -- she is the one he brings maths and code to, and an answer
you cannot scroll back to is one you ask for twice. Palette sampled off
her art (bone plating, the steel-blue room, the red cables for Speak).
Thinking cue: her picture brightens while she works.

**Her art had the PHONE'S BUTTONS in it** -- a round back arrow and a
lens icon, from the screenshot he saved it from. Cropped out, not
painted over (`ui/zero/ART.txt`), with headless Chromium since PIL is
not in the container.

**RENDERED AND LOOKED AT**, thirty-fourth time: 1024x600 with a real
exchange in the log, 412 with her stacked on top, the exit at 1000/1024
and 388/412, no horizontal scroll; the A.I. drawer at three tiles in one
row with her own spine-and-cables icon.

### Her persona

`personas/zero.persona`, on the deck body so `/wiki` and the board facts
reach her. **WORKING NAME -- he has not named her.** Four's measured
scaffold, re-pointed: answer first then the one step that makes it
make sense, precise over showy, *"when you are not sure, say so in a
word and say how you would find out"*. Examples carry every measured
shape plus a sum (`17 x 23`, the one he tested her with). Sampling is
Qwen's own recommendation for this release, not taste. Sounds `Aha,
Whoa, Huh` -- the suite refused `Ooh` as Yuzu's. 4561 chars against
Four's 5446. **UNMEASURED on the page.**

### FOUR TESTS CARRIED THEIR OWN LIST OF PAGES

The exit on a narrow screen, the rail from the roster, the voice fetch
and "only Four changes colour" each named the pages in a tuple -- so a
fifth character page would have escaped every one of them.
`character_pages()` reads them off the files (a page with a rail), and
**each was verified by breaking her page**: her exit rules deleted,
her voice asking for Four, a colour cycle added. All red. **Plus a
property one tag over from the links test: every `<img src>` on every
page exists.**

**Five new tests, eight breaks, all red. 769 -> 774.**

## "(laughs)" IS NOT SAID OUT LOUD NOW, AND "(not DHCP)" STILL IS (Sept 23)

Ghost: *"I suppose itd make it more realistic if she didnt verbalize
(laughs)"*. Kokoro read her round-bracket stage directions as words --
`(laughs)`, `(winks)` -- while `[brackets]` and `*asterisks*` had been
silent since Sept 8.

**A PARENTHESIS IS NOT A BRACKET, and that is why it is not one more
wrapper in the list.** Neither a bracket nor an asterisk ever carries
speech in her replies; a parenthesis often does. `The Orin (six
cores)`, `set it to static (not DHCP)`, `the power light (blinking
green)` are asides she means him to HEAR, on a deck he asks Linux
questions on. `\([^)]*\)` would have eaten the answer.

**SO IT GOES SILENT ONLY WHEN IT OPENS WITH A STAGE DIRECTION**:
`_STAGE_WORDS` in `yuzu_voice.py`, a list of how she laughs, looks and
says things. **The failure modes are lopsided on purpose**: a word the
list lacks is spoken, which is exactly what happened before it existed;
a word it has too many of silences part of an answer. So only the forms
a direction uses and an aside does not -- `leans` never `lean`,
`blinks` never `blinking` -- no nouns as openers, and `(beat)` /
`(silence)` count only standing alone.

**VOICE ONLY.** The bubble still shows `(laughs)`, which is the
readable RP he has said he is fine with. The page already hides
`[brackets]` from the bubble, so that is one line in `spoken()` if he
wants it; he asked about hearing it.

**Two tests, driven through the real `/voice.wav` route, seven breaks,
all red**: the rule removed, every parenthesis silenced, `blinking`
allowed, `beat` as an opener, any `in a ...` or `with a ...`, and the
match made case-sensitive -- which stayed GREEN until a capitalised
`(Smirks)` joined the cases, because every direction in the first
draft was lower case and a model opening a reply writes it capitalised.
**767 -> 769.** **UNHEARD on the board.**

## SHE STILL SAID "USER", AND THE WORD WAS NEVER IN HER PROMPT (Sept 23)

Ghost, the day after her example labels became his name: *"Okay so she
still called me user but were close lol"* -- `...not much changed,
user!`

    Ghost in her composed prompt     16
    User: in her composed prompt      0

**THE SEPT 22 ENTRY GOT THE MECHANISM HALF WRONG.** It says his turns
arrive "with no label on them at all". They do not: `/api/chat` renders
every one of them inside the chat template's role header, Llama's
`<|start_header_id|>user<|end_header_id|>`, so the word `user` sits in
front of everything he says -- the one label no persona file can edit.
The eleven `User:` examples were the loudest teacher, not the only one.

**AND HER MEMORY MAKES IT PERMANENT.** Her own replies outweigh the
system prompt within a few turns, and since Sept 16 they survive a
restart. One "user!" is saved, read back as her own example, said
again, saved again -- **a fault that re-teaches itself every turn never
ages out of an 8-turn window.** The memory feature turned a slip into a
habit.

**`by_name()` IN `yuzu_face.py`: the prompt reduces, code guarantees.**
Where she calls him "user", his name goes there instead -- in the
bubble, in the voice, in her history, and in an OLD memory the first
time it is read back, so the pull that delivers this cleans the file
on his board with nothing for him to run. His own turns are never
touched. `USER_NAME` is READ off the persona, so a character with none
(Yuzu) is untouched to the byte.

**ONLY WHERE SHE IS TALKING TO HIM**, and that half is the one worth
the test: after a comma or a greeting at the end of a clause, or
shouted at the start of one. She lives on a Linux box and gets Linux
questions, so "the user's permissions" and "make a new user" are real
English -- **a blanket swap puts his name in a sentence about
accounts.** A sentence-opening `User,` is deliberately NOT caught,
because *"User, group, others."* is how a chmod answer starts.

**THE PROMPT WAS NOT TOUCHED.** Rule 9 still says "the user's words",
and that phrase is how `MEASURED_WINS` recognises the no-puppeteering
win on every character. One variable.

**Five new tests, eight breaks, all red**: the bubble keeping it, her
history keeping it, an old memory loaded as it was, HIS words rewritten
on load, a blanket swap, an empty name defaulting to his, the comma
form dropped, and the name hardcoded instead of read. **762 -> 767.**

**UNMEASURED on the board** until he says hello to her after a pull.

## THE WIKI SERVED WHATEVER WAS DOWNLOADED LAST, AND `wiki --get` (Sept 23)

Ghost: *"i wana get a few more wikipedia files for her but i dont
think ill need 100gb worth. Maybe just some useful files from the
same way we got em last time. (Which i cant recall how we did it)"*

**NOTHING IN THIS REPO RECORDED HOW.** The Simple English archive
arrived in a chat this repo never saw; grep finds no URL, no wget, no
doc. So the honest first answer was "I can't tell you what you did",
and the way is now written down -- in code, where it cannot go stale.

### The trap his request would have walked into

`wiki`'s `find_zim` served **ONE archive: the newest by modification
time.** Right while there was one, and silently wrong the day a second
arrived. **Reproduced with three real ZIMs** (built with `libzim`) on a
real `kiwix-serve` 3.5 installed in the container: iFixit downloaded
after Simple English Wikipedia, and `/wiki cats` came back *"Nothing in
the archive about 'cats'"* -- a search of repair guides, with nothing
on screen to say so. **The failure looks like a thin encyclopedia, not
like a bug.** And NEXT_SESSION already listed iFixit and WikiMed as on
the board, so it may be happening today.

**Every archive is served now, newest release of each BOOK** (the name
minus its `_YYYY-MM`; two releases of one book would put every article
in twice). He can browse all of them from the phone. **Which one SHE
reads is chosen on purpose: the Wikipedia with the most articles**,
read off the catalog's `<articleCount>`, whatever order they arrived
in; the biggest book of any kind only when there is no Wikipedia at
all. iFixit is bigger than both Wikipedias in the test on purpose.

### What the real server said, which stubs never could

- **Unscoped `/search` searches EVERY book.** Harmless with one
  archive, and with three it came back Simple, full Wikipedia and an
  iFixit guide mixed together -- after which the old "learn the book
  from the answer" code would have LEARNED iFixit as her book for the
  session. Unscoped answers are narrowed to her book now, by PREFIX,
  which is what keeps the Sept 10 case working (catalog says
  `wikipedia_en_simple_all`, articles live under `..._nopic_2026-05`).
- **`books.name=<catalog name>` finds nothing; the content id does.**
  And `/suggest?books.name=` answers **404 "No such book"** -- almost
  certainly the `suggest: FAILED (404)` his board printed on Sept 10.
  `/suggest` wants `content=<id>`. The id is read out of the catalog
  entry's `/content/` link.
- **A suggestion's `"path": "Cat"` is RELATIVE TO THE BOOK**; the old
  code made it `/Cat`, which is not a page. And the `"kind": "pattern"`
  row ("containing 'cat'...") is an offer to search, not an article.

**The choice of book expires after two minutes** instead of never: a
finished download restarts the wiki with one more book under a face
server that has been up all day. Pinned under ten minutes absolutely,
not against its own constant.

**Searching the OTHER archives is still multi-ZIM `/wiki` (#1), still
queued**, and it must not arrive by accident through a fallback. This
round is the groundwork: they are served, and she is told they exist.

### `~/YUZU/wiki --get wikipedia_en_all_mini`

**The one worth having FOR HER, and the reason is arithmetic.** A
lookup hands her at most `MAX_CHARS` (700) of an article -- its first
paragraph. The `mini` flavour IS the first paragraph and infobox of
every article in English Wikipedia: everything she can use, at a small
fraction of the full archive. When it lands she moves to it by herself
(most articles wins).

**THE FILENAME COMES FROM KIWIX AT RUN TIME, NEVER FROM HERE.** Archives
are dated and replaced every few months, so a URL typed into a chat is
a 404 by the next release -- the 8BitDo lesson. `yuzu_zimget.py` asks
`library.kiwix.org/catalog/v2/entries?name=...` for the book (shortening
the stem a word at a time, because `wikipedia_en_all_mini` is filed
under `wikipedia_en_all` beside `_maxi` and `_nopic`), takes the newest
release of EXACTLY that flavour, strips `.meta4` to get the file, and
reads the size from `length=`. **A link pasted from the Kiwix site
works too** -- it is reduced to the book, so last month's link fetches
this month's release.

**It says the size first and refuses if it would fill the disk** (1GB
margin -- the NVMe also holds her memory and his ROMs). **It runs
DETACHED** -- a new session, so the serial cable dropping does not kill
it; a foreground multi-gigabyte download on his one terminal is the
kiwix-serve power-cycle again. **`-C -`, so the SAME LINE CARRIES ON**
after WiFi or power goes; `.part` until whole so the wiki is never
handed half an archive; and **the wiki restarts itself at the end**, so
the new book is simply there. `wiki --status` shows progress, or
`STOPPED PARTWAY` with **the exact line to paste** -- not "the line you
started it with", because he will not remember it.

**PASTING IT TWICE IS THE LIKELY CASE**, not the odd one -- he forgets,
and the natural answer to "is it still going?" is to paste it again.
Two curls appending to one `.part` is a corrupt archive that looks
finished, so a second start is refused ("ALREADY DOWNLOADING") by
reading `/proc/*/cmdline` for the exact `.part` argument. The first
version asked `pgrep`, and the suite's own mock of `subprocess.Popen`
swallowed that call too -- `subprocess.run` is built on Popen -- so the
check was invisible to the tests that most needed it.

**The URL, path and script go to bash as ARGUMENTS**, never pasted into
the command text, so nothing the catalog says can become shell. Only a
name matching `[a-z0-9_.-]` ever makes a request.

### IT IS ITS OWN MODULE BECAUSE A TEST SAID SO

The first draft put the downloader in `yuzu_wiki.py`, and
**`test_the_CODE_still_makes_that_claim_TRUE` went red** -- her prompt
tells her nothing she does reaches the internet, and `library.kiwix.org`
had just landed in a module her turn runs through. **The guard was
right.** Fetching an archive is maintenance he starts, the same line
`pull` sits on, so it lives in `yuzu_zimget.py` and a new test (read as
IMPORTS via `ast`, not as text) keeps all four turn modules from ever
importing it.

### `pull` restarts the wiki too

kiwix-serve is handed its archives on its command line, so changing
`wiki` does nothing to a running one -- the stale-process trap one
server over, and the board would have gone on serving the wrong archive
until a reboot. Same two guards as the face: only if it is already
running, and never for a change that is not `wiki`'s.

### Verified, and what is not

**End to end in the container**: a local Kiwix library (real
`kiwix-manage` + `kiwix-serve --library`, so the acquisition links are
in the real format), a local mirror, the real `wiki` and the real
downloader -- downloaded, renamed, wiki restarted with both archives,
and `/wiki` moved to the new book by itself. **A stopped download was
resumed and came out byte-identical** (after my first mirror, Python's
`http.server`, turned out not to support ranges -- the test setup, not
the code). Her inventory now counts each book once, newest release,
pinned to agree with `wiki`.

**THE LIVE `library.kiwix.org` WORKED ON HIS BOARD, same day.** He ran
`~/YUZU/wiki --get wikipedia_en_all_mini` and reported *"Downloaded
ayyye"* -- so the catalog query, the flavour match and the `.meta4`
strip all held against the real site, which the container could never
reach. **CONFIRMED by `wiki --test` on his board, 23:49:**

    books:    2 on the server -- /wiki reads the one below
    book:     wikipedia_en_all_mini_2026-09
    suggest:  FAILED (HTTP Error 404: Not Found)
    result:   10 paths  first: /content/wikipedia_en_all_mini_2026-09/Cat_the_Cat

**She moved to the new book by herself.** Four things that screen
settled:

- **14.4 GB**, not the ~13 his Kiwix page and my web search said -- the
  2026-09 release is bigger. The tool said so before it spent it, which
  is exactly why sizes are not written into this file.
- **`/suggest` WITH `content=` WORKS on his kiwix-serve.** `result: 10
  paths` is the count=10 shape answering. So the Sept 10 `suggest: 404`
  was the `books.name=` form all along, as the 3.5 reproduction said.
  (The `suggest` line in the diagnostic asks unscoped, which still
  404s with two books; the verdict above it says to ignore it.)
- **ONLY TWO ARCHIVES ARE ON THE BOARD**: Simple English and the new
  mini. NEXT_SESSION said iFixit, WikiMed, WikiHow and the rest were
  "already on the board" -- they are not, or not under the three roots
  `wiki` searches. That line came from the Sept 22 wish list, read as
  an inventory. Corrected there.
- **Kiwix's first suggestion for "cat" is `Cat_the_Cat`**, not `Cat`.
  `rank()` puts an exact title first, but only among the ten it is
  handed -- and with the whole of English Wikipedia behind it, whether
  `Cat` is in that ten is UNCONFIRMED. `python3 ~/YUZU/yuzu_wiki.py cat`
  prints the article she would actually get.

**ANSWERED, 23:54: IT IS WRONG. `yuzu_wiki.py cat` returned `.cat`**
-- the Catalan top-level domain -- and the extract carried the page
FOOTER ("Category: ... Hidden categories ... This page is issued from
Wikipedia ... Creative Commons"). Two faults, NOT YET FIXED (he was out
of credits until Wednesday), first thing next session:

- **`.cat` normalises to "cat", an EXACT tie with `Cat`**, and the sort
  is stable, so kiwix's order decides -- or `Cat` was not in the ten
  suggestions at all. Fix: a tie-break on the raw title (punctuation
  that was stripped counts against it), and merge `/search` hits into
  the candidates when no raw-exact title is among the suggestions.
- **The mini pages carry category/licence footer text** that the old
  archive did not, and `_Extract` keeps it. Skip the footer block (or
  cut at "Category:" / "This page is issued from") before capping at
  700 -- or she reads licence boilerplate aloud.

**FIXED THE SAME NIGHT** (he asked: *"Fix now real fast homie"*). A
title that only matches once its punctuation is stripped loses a tie
(`_raw_exact`); a suggestion list without the real title is merged with
`/search` before ranking; and `_Extract` cuts at the first footer
marker. Three tests, each verified by breaking it. **UNCONFIRMED on the
board** until `python3 ~/YUZU/yuzu_wiki.py cat` says `Cat`.

**IT SAID `Cat (disambiguation)`, and that was my fix's fault.** The
footer was gone and `.cat` had lost -- but `_raw_exact` stripped the
`(disambiguation)` qualifier before asking "is this the title", so a
shortlist holding only that page was TRUSTED and search never ran. A
check that could not tell a list of links from the article, in the
round written to stop exactly that. Now: the qualifier stays; **the
article is fetched BY NAME first** (`/content/<book>/Cat`, a 404 costs
one local request and cannot be outranked); and any page that "may
refer to" something is skipped, kept only as a last resort (the
Mercury case). Three break-checks, all red.

**AND `--status` SAID "Not running" UNDER A DOWNLOAD AT 83%.** It was
about the wiki SERVER, which had not been started -- sitting directly
under the download line, where it reads as the download having stopped.
Every server line names the wiki now, and a test pins that no bare
"not running" can sit under a download again. Every failure
prints the site's own error, verdict first. **Sizes are not written
here on purpose** -- the tool prints the real one before it spends it.

**Twenty-seven breaks, every one red in the end** -- and two of my own tests were
caught by it first: the pasted-link test ERRORED rather than failed
(read the failure KIND), and **the new-release test passed with its rule
deleted**, because a board with one archive put both answers in the
same folder. It has a second archive in a second folder now.
**734 -> 756**, one of them the memory guard below.

### AND THE SUITE WAS WRITING FAKE TURNS INTO HER REAL MEMORY

Found by looking in `~/.yuzu/history/` after a run, which is how the
Sept 20 shredder was found too: **`four.json`, four fake "hi" /
"Noted." turns, one per full run.** Reproduced on the untouched
`dcdd625` with a throwaway HOME -- pre-existing, not this round's.

`test_the_marker_never_lands_in_her_HISTORY` drives the real
`answer()`, which saves her conversation, and its class's `store()`
redirected `FACTS_DIR` and **not `MEMORY_DIR`**. Every test stayed
green, because nothing checked the one place that mattered. **On his
board that file is Four's memory of him**, and running the suite there
would have appended strangers' turns to it.

`store()` redirects both now, and `test_this_class_leaves_his_REAL
_memory_alone` **runs the class again in a child with a throwaway HOME**
and fails if anything lands under its `.yuzu` -- driven, because reading
the setup is what missed it. Verified by taking the fix back out: red.
It watches `.yuzu` only, since onnxruntime drops its own cache under
`~/.cache` whatever we do.

## THE V-PET IS DELETED, AND PS1 IS OFF THE LIST (Sept 23)

Ghost, first session on the new model: *"Can you put the vpet aside
while i get it set up? As in "delete it" from the cyberdeck. Prolly
requires screen layout changing etc."* and *"Ive decided i dont need
ps1 for now. Too lazy to fw bios."*

**DELETED, NOT RETIRED -- the LEDs' call, not the cast's.** `retired:
yes` is one line of data nobody loads; the pet was a module
(`yuzu_vpet.py`), a page, twelve sprites, two source zips in
`assets/`, and a POST route on a server bound to 0.0.0.0. A dead
subsystem you still have to read around is worse than none. **It is
all in git** -- `git show dcdd625:yuzu_vpet.py` and the same for
`ui/vpet.html`, `ui/vpet/` and `assets/` brings it back. His board
keeps a tiny `~/.yuzu/vpet.json` mood file; harmless, outside the
repo, and deliberately not touched.

**NOT WRITING AN ICON DOES NOT REMOVE THE OLD ONE.** `deckapps` had
installed a Pet icon on his board, and dropping the `write_app` line
would have left it on his desktop pointing at a page that no longer
exists -- the exact dead icon `write_app` was built to never leave.
So retired apps are removed BY NAME on every run (`for gone in
yuzu-pet`), which is one word per future retirement, and it says so
when it does. Pinned by planting the old icon in a fake HOME.

**THE DRAWER CENTRES ITS SHORT ROW NOW.** Six tiles filled two rows of
three; five left a hole in the bottom right. Rendered three ways at
1024x600 and LOOKED at, thirty-third time: a grid of three kept the
hole, five across made tall skinny pillars, and **a wrapping row of
thirds with `justify-content: center`** kept every tile exactly the
size it was (320x230) with Browser and Calculator centred under the
top three. The next tile he adds lands in it with nobody touching the
rule. The layout test had pinned `repeat(3, 1fr)` and `count % 3 ==
0`; it pins the centring instead, because the drawer is the one view
whose count moves both ways. Re-checked at 412: one column, Update at
392/412, no horizontal scroll.

**`every page the deck links to is really there` is the guard worth
keeping**, and it is a PROPERTY rather than a search for "vpet": every
`data-go`/`href` to a `.html` in every page must exist. It covers the
NEXT thing that gets deleted too. **Comments are stripped first** --
`face.html` still tells the story of the pet leaving its screen, and a
link inside that comment is verified to stay QUIET (the
grep-matches-prose trap, the half that is easy to forget).

### PS1

**`mednafen` STAYS** -- it is what plays NES and SNES; it simply is
not offered as a PlayStation any more. The row reads `nes/snes`, and
the setup no longer makes a `~/ROMs/psx` folder, because `--check`
ends with ONE line that installs everything missing and a declined
system riding along in the line he pastes is the wrong kind of
helpful.

**THE BIOS NOTE FIRES ON A GAME NOW, NOT ON A FOLDER.** It used to fire
the moment `~/ROMs/psx` existed -- and an earlier `deck` may already
have made an empty one on his board, which would nag him every run
about a system he turned down. A PS1 game actually sitting there is
the moment the caveat becomes true again. Hidden files do not count.

**Seven tests new or rewritten, each verified by breaking it**: a Pet
tile put back, a link only inside a comment (stays green), the
`/vpet.json` route answering again, the stale-icon cleanup removed,
the drawer back to a grid of three, a PS1 row back in `--check`, a
`psx` folder made again, and the BIOS note back on an empty folder.
All go red except the comment, which is the point. **743 -> 734**: the
thirteen V-Pet tests went with the V-Pet.

## A NOTE FOR THE NEXT SESSION, AND I CLOBBERED HIS (Sept 23)

Ghost: *"Can you make a handoff note brotha? Its for your 5.5 opus
mode i wana try it."*

`NEXT_SESSION.md`, and **it is explicitly an EXPIRING SNAPSHOT that
names CLAUDE.md as the real record.** A second long doc that goes
stale is the fault this repo keeps deleting -- `--show shiro_deck` sat
wrong in a doc for eleven days, and a hardcoded cast in a DOC is worse
than one in a page because a page has a test. So it carries only what
CLAUDE.md buries: today's pointers, **the 201 tokens of context
headroom**, the working loop, the non-negotiables, the standing
reminders, and what is UNMEASURED.

### AND I OVERWROTE `HANDOFF.md` WITHOUT LOOKING AT IT

It already existed. It is **a different document for a different
reader** -- what GHOST pastes into a fresh DESIGN chat that has
nothing: product level, no engineering, no repo. I wrote mine straight
over it and only found out because `git diff --stat` said *modified*
rather than *new*.

**Look at the target before overwriting it.** Nothing was lost, because
it was committed -- which is the same reason the alpha-blind crop that
ate `blink.png` was a two-minute problem. It is restored byte for byte
and mine is named for its own audience.

**HIS IS STALE AND IS DELIBERATELY NOT FIXED IN THIS PASS.** Rewritten
Sept 10, it still names Saya as the character and describes a cast of
five, which the Sept 20 cut ended. Refreshing it is a real job with a
real audience decision in it, and **its reader is not me** -- so it is
offered rather than done. One variable at a time.

### The guard pins the two things that cannot go stale by being right

Asserting that it still says `four`, or still says 201 tokens, would be
**a test that has to be edited every time it works** -- the fault that
put "Saya's Face" on an app icon. So `TestNextSession` pins only that
the note keeps saying it expires and keeps naming CLAUDE.md, and that
it never teaches a command hardcoding a pointer's VALUE.

**AND THE GREP-MATCHES-PROSE TRAP FIRED AGAIN, FIFTEENTH INSTANCE, in
the test written to guard against exactly that class of staleness.**
The first version banned `--show <key>` outright and went red on the
note's own paragraph explaining that `--show shiro_deck` is the fault
being avoided. It reads indented COMMAND lines now, and **the prose
case is verified to stay QUIET** -- the half that is easy to forget to
test, same as the comment naming a domain in the offline guard.

**Six ways, each verified**: the expiry line dropped, CLAUDE.md
unnamed, the pointer hardcoded in the command, the command deleted
entirely, a named file missing -- all five red -- and a `--show` in
prose, which stays green.

**AND THE SELF-REFERENTIAL TEST COUNT DID ITS JOB.** Adding three
tests turned `test_the_test_count_it_promises_is_the_real_one` red
until `NANO_DAY_ONE.md` was updated. 740 -> 743, in the runbook and in
this file's conventions block. That guard exists because he will not
cross-check it, and it is the only thing in the repo that fails on
purpose when work lands.

## FOUR MORE SYSTEMS, AND `deck --check` ASKS RATHER THAN TELLS (Sept 22)

Ghost: *"Snes ps1 nes and gameboy color please add those to ES-DE."*

**THE APT INSTALLS HAPPEN ON HIS BOARD AND I CANNOT VERIFY HIS REPOS
FROM HERE**, which is the whole design of this change. A package list
written into a doc is right until his Ubuntu disagrees, and **an
unverified specific stated as a step sends a person debugging their own
hands** -- an hour of the 8BitDo evening is the receipt.

`deck --check` already had exactly the right shape: a `row` helper that
prints `MISSING -- sudo apt install -y <pkg>` only when the thing is
genuinely absent, and gathers them into one line. So the systems are
rows now, and **the deliverable is one word he already knows** rather
than a paste from here.

**ONE OF THE FOUR WAS ALREADY DONE, and saying so came first.** mGBA
plays Game Boy and Game Boy **Color** as well as Advance, so `gbc`
needs no package at all -- only a folder. Telling him to install
something he already has is its own kind of wrong step.

**PLAYSTATION NEEDS A BIOS AND NOTHING SAYS SO UNTIL IT FAILS.** Every
other system here runs a ROM straight off; PS1 dies with an error about
the MACHINE rather than about the file, which reads as a broken
emulator. `deck --check` says it the moment a `~/ROMs/psx` folder
exists -- and **stays quiet when there is none**, because a caveat that
fires whatever is on the board is the same noise as a notice that fires
every time. Both halves pinned.

**A FOLDER PER SYSTEM, BECAUSE THAT IS THE WHOLE INTERFACE.** ES-DE
finds systems by folder name under `~/ROMs`, `drop.py` lands a file in
the folder you start it from, and `board_has()` counts what is there --
so the folders existing is what turns "I sent a ROM over" into "she
knows I have it", with nothing else to configure. Empty ones cost
nothing: they are skipped everywhere until a file lands.

**AND THE TWO LAYERS ARE PINNED TO AGREE.** `deck` creates the folders
and `board_has()` names them; a folder she has no name for comes out as
*"1 psx game"* in her own prompt. Both ends are ours, so there is no
excuse for them drifting -- `test_every_folder_it_makes_is_one_SHE_can
_name` reads the list out of `deck` and checks it against `_SYSTEMS`.
**`_SYSTEMS` stays a politeness layer rather than an allowlist**: a
folder nobody thought of is still COUNTED, it just keeps its own name.

**Four new tests, each verified by breaking it**: the systems dropped
from the inventory, GBC told to install something anyway, the BIOS
caveat removed, and a folder created that she cannot name. All go red.

**STILL HIS TO RUN.** Nothing here installs anything -- `--check` is
read-only by design and a test pins that.

## SHE HAS A SHAPE FOR A LOOKUP NOW (Sept 22)

Measured live on his board, handed 700 characters of encyclopedia:

    I'm not going to try to summarize this information again; I've
    already "learned" it from you.

**A LOOKUP IS A TURN SHAPE SHE HAD NEVER BEEN SHOWN.** It reaches her
as a USER turn -- *"I looked up X and it says: ... Tell me about X in
your own words, in a sentence or two"* -- and nine of her examples were
ordinary conversation. Handed a shape with no demonstration, a 3B fills
it from its own prior, and the prior for "character handed facts it did
not ask for" is mild irritation. **Sixth instance of this file's most
repeated finding**, and the lever is the one that has now worked five
times.

One example, in the exact shape `as_context()` actually produces -- the
article text, then the ask, on one line like every other example in the
file. Her answer compresses rather than recites, lands in two
sentences, and ends on a real opinion (*"it isn't a surface -- it's
just the last place you could have turned around"*), which demonstrates
rule 7 in the same breath.

**PINNED BY THE ANSWER'S BEHAVIOUR, and one assertion is genuinely
derived**: the answer must share a real word with the article it was
handed, computed from the ask rather than hardcoded, **or the example
teaches her to be given facts and then talk about something else.**
Verified by breaking it four ways -- the example deleted, an answer
that uses nothing from the article, an answer that grumbles, and an
answer that runs to a lecture. All four go red.

**5011 -> 5447 chars, AND THE HEADROOM IS THE HEADLINE.** With the
facts store full and the deck inventory at its cap, **200 tokens of
`num_ctx` remain**, down from 451 two commits ago. The guard is green
and that is the honest number.

**THE NEXT THING THAT RIDES ON EVERY TURN NEEDS THE ARITHMETIC FIRST.**
Three features in one session each took a slice -- the facts line, the
inventory, and now an example -- and not one of them was large on its
own. That is exactly how three +50s walked `num_predict` to the edge of
a 4096 window without anybody checking the product. The next raise is a
`num_ctx` decision before it is anything else, and `test_the_reply
_ceiling_and_the_CONTEXT_agree` will say so out loud.

**UNMEASURED.** Nobody has asked her for a lookup since.

## SHE OFFERS, HE PICKS (Sept 22)

Ghost: *"Make it so when facts come up she can ask which one she
remembers yes? Then i just pick em."* And, on the two options I gave
him sounding alike: *"Sorry about all that they both sounded very
similar."* **They did -- that was my phrasing, not his reading.**

She finishes a reply with `REMEMBER: the thing`, the code lifts it out
before anything sees it, and the page offers it as a chip under the ask
bar. **Tap it and she keeps it; ignore it and nothing happened.**

**THE CONFIRM STEP IS WHAT MAKES THIS SAFE, and it is the whole reason
the automatic version was refused.** Teaching her a remember-move means
NAMING A TOKEN IN HER PROMPT, which is measured three times here as how
she learns to spam it: `[winks]` in 3 of 4 replies while named as
forbidden, the asterisk ban that printed an asterisk, rule 5 recited
back word for word. **So assume she over-offers.** An offer he ignores
costs nothing -- not a byte of the budget, not a word on screen -- so
the pink elephant stops being a fault and becomes noise. That is the
only thing that makes her participating affordable at all, and a test
drives it: a reply full of markers must not change the store.

**TWO AT MOST PER REPLY.** A wall of offers is its own kind of nagging,
and the row under the ask bar has room for two.

### THE MARKER WAS A BRACKET AND THE SUITE WAS RIGHT TO REFUSE IT

`[remember: ...]` was the first draft, chosen because the bracket is
already load-bearing: `strip_stage_directions` drops it before Piper
says it aloud and the page's `spoken()` drops it before the bubble
shows it. **Three tests went red at once and every one was correct.**

**ON THIS PROJECT A BRACKET MEANS AN ACTION.** `extract_actions` parsed
the marker as one, and `_hardware_cyberdeck.txt` goes out of its way to
never tell a deck character that brackets exist -- because on a body
with nothing wired up, every bracket is a movement emitted into a void.
I was borrowing the one syntax this repo has spent months making mean
exactly one thing, to mean a second thing, on the body where it means
nothing.

It is a plain `REMEMBER:` at the start of a line now, **anchored**,
because unanchored it matched *"You should remember: flexbox centres
it"* mid-sentence -- and that does not merely add a spurious offer, it
**CUTS HER REPLY IN HALF** and leaves "You should" on screen.

**AND IT COMES OUT OF HER HISTORY, not just the bubble.** Her own
replies outweigh the system prompt within a few turns -- measured on a
real 7-turn chat, which is the entire reason `_canonicalise` exists --
so a marker left in the transcript is her teaching herself to write
more of them, every turn, for as long as the conversation lasts.

**`test_her_PROMPT_teaches_the_marker_the_CODE_actually_catches` is the
guard that matters.** It runs her whole composed prompt through the
real extractor. Change either spelling and she goes on writing a marker
nothing catches -- which reads as the feature being ignored, with the
raw marker then showing up in her bubble. **Seen for real** while
re-rendering with a stale stub: `"suggests": []` and
`[remember: ...]` sitting in her reply on screen.

### THE SHUFFLE BANNER IS A HINT, NOT A DIAGNOSIS

Two seeds went red. The suite prints *"FAILED IN THIS ORDER BUT NOT THE
NORMAL ONE? Then a test is leaving something behind"* on **any**
shuffle failure, and I read it as a finding twice: first as pollution,
then as my own edit-race. **It was neither.**

Reproduced in a CLONE at `/tmp/shufcheck`, which is the step both
earlier readings skipped:

    AssertionError: 'YUZU/wiki' not found in
      '#!/bin/bash\n"/tmp/shufcheck/wiki" ...'

**A TEST THAT ONLY PASSED BECAUSE THE CHECKOUT IS CALLED `YUZU`.**
`deckapps` finds itself with `dirname "$0"`, so that string is really
the FOLDER NAME -- and it fails in normal order too, in any directory
with another name. Cloned to `~/deck`, or run from a temp dir, the
suite goes red on a script working perfectly. Same rule as the Jetson
round: **a test that can only pass on the machine you wrote it on is
not passing, it is untested.** The path is derived from
`Path(__file__).parent` now, verified in a clone that is not named
YUZU.

**The lesson is about me rather than the test.** I gave a confident
wrong cause, wrote it into this file, and told Ghost the deck was fine
-- on evidence that was one `git clone` away from being checked. The
race is real and shuffles do belong last on an untouched tree. **A red
seed still gets reproduced before it gets explained.**

### Her prompt

Rule 10 and one example, 5003 -> 5011 chars. **327 tokens of context
still spare** with the facts store full, the inventory at its cap and
this on top -- tighter than it was, and worth knowing before the next
thing rides on every turn.

**Seven new tests, each verified by breaking it**: her prompt teaching
a marker the code cannot catch, merely offering spending the budget, no
cap on how many she offers, offering what she already knows, the marker
left in her history, and one of the two reply routes dropping the
offers. All go red.

**RENDERED at 1024x600 and 412 and driven in a browser** -- two chips,
tap one, it vanishes and the count goes up. And rendering found the
layout fault the assertions could not: `#offers` is `flex: 0 0 100%`,
and **without `flex-wrap` on `#knows` it took that width inside the
same row**, squeezing "she knows 2 things about you" into a column one
word wide down the left of the screen. Same family as the `min-width:
0` faults.

**UNMEASURED.** Whether a 3B actually offers anything sensible is the
round that decides this, and nobody has asked her yet.

## SHE KNOWS WHAT IS ON THE BOARD WITH HER (Sept 22)

Ghost, off the upgrade list: *"16 definitely yes."*

`board_specs()` is the ID CARD -- what she RUNS ON -- and `board_now()`
is the weather. Neither can answer **"what can this thing actually
do"**, which is the question a stranger asks at a demo and the one he
asks himself when he cannot remember what he put on it. Asked today she
invents an answer: same mechanism, same file, as the Windows CE palmtop.

    WHAT IS ON THE BOARD WITH YOU: wikipedia en simple all, ifixit en
    all and wikimed en all to look things up in, and 12 NES games,
    7 Mega Drive games, 4 Nintendo 64 games... That is what you
    actually have to hand, so say so when somebody asks what this
    thing can do.

**READ, NEVER HARDCODED**, which is the `ghostnano` rule for the third
time. It globs the same three roots `wiki` searches for `.zim`, with
the same 1MB floor, and counts `~/ROMs/<system>/`. A library typed into
the file is right until he copies an archive over WiFi, and the failure
looks exactly like the deck working.

**A SAVE IS NOT A GAME.** `.sav`, `.srm`, `.state` -- he WILL have
them, because the whole point of the emulator is that he plays the
things, and counting them tells him he has twice the library he has.

**`_SYSTEMS` IS A POLITENESS LAYER, NOT AN ALLOWLIST.** A folder it has
never heard of keeps its own name and still gets counted -- a library
that silently omits a shelf is worse than one that says `dreamcast` in
lower case.

**CACHED FOR TWO MINUTES, AND THAT IS THE ONE REAL DIFFERENCE FROM THE
SPECS.** A processor does not change while the server is up; a ROM
folder does, precisely because `drop.py` exists to put things in it
from his phone. Needing a restart to notice a file he just sent would
be the stale-process fault wearing a helpful hat.

**AND IT IS BOUNDED**, for the reason the facts store is: it rides on
the system prompt on every turn, so an inventory that grows with the
NVMe is one the context guard cannot see the worst case of. Shelves are
sorted biggest first and a trim drops the ones he has one game in --
**the sentence itself is never cut**, because half a clause is worse
than a shorter list, the same call the wiki extract made at 700
characters. The ceiling guard counts `HAS_MAX`, not what this container
happens to have. **451 tokens still spare with the facts store full AND
the inventory at its cap**, on the worst character, counted
pessimistically.

### TWO OF MY OWN TESTS MEASURED AGAINST THE CONSTANT THEY WERE TESTING

Both passed their break-check, which is how they were caught:

    HAS_MAX 400 -> 100000      "the inventory is unbounded"   still GREEN
    _HAS_TTL 120 -> 1e9        "it notices a new ROM"         still GREEN

The bounded test asserted `len(line) <= HAS_MAX`, so **raising the cap
moved the goalpost with it**. The refresh test expired the cache with
`_HAS_AT -= _HAS_TTL + 1`, which expires it however enormous the TTL
is. Neither could observe its own failure.

**A CHECK THAT DERIVES ITS THRESHOLD FROM THE CONSTANT UNDER TEST IS
NOT A CHECK.** That is the oldest line in this file wearing a new
costume, and it is the same family as the memory helper that read the
stub's own numbers -- a guard measuring its own fixture. The bounded
test counts how many shelves SURVIVED now (derived from the board it
built), and the refresh test expires the cache absolutely and pins the
TTL under ten minutes.

**Eight new tests, each verified by breaking it**: the inventory
hardcoded instead of read, saves counted as games, an unknown system
dropped instead of named, the cap raised past the window, the cache
never refreshing, and the inventory sent to a character off the deck.
All go red.

### AND A BACKGROUND SHUFFLE RUN WENT RED -- **SEE THE CORRECTION BELOW**

`--shuffle 47` failed while `--shuffle 11` passed, which is the exact
signature of test pollution. I had edited `yuzu_face.py` while that
background job was running, so the seed imported a half-written module,
and I wrote that down as the explanation.

**THAT DIAGNOSIS WAS WRONG AND I SHOULD NOT HAVE WRITTEN IT.** It was
plausible, it was never reproduced, and there was a real defect
underneath it. See "THE SHUFFLE BANNER IS A HINT, NOT A DIAGNOSIS"
below. The race is real and shuffle runs do belong last, on a tree
nobody is touching -- but **a red seed is worth REPRODUCING before it
is believed**, which is the rule I quoted and then did not follow.

## SHE KEEPS WHAT HE TELLS HER TO, AND IT CANNOT FILL UP (Sept 22)

Ghost, off a list of twenty upgrades: *"14 sounds amazing as long as
she never fills the memory."*

`~/.yuzu/history/` is the last 8 turns and is bounded by CONSTRUCTION
-- the brain trims eagerly, so it cannot creep. It is also gone the
moment the conversation moves past it, which is the whole gap: tell
her your cousin's name and nine turns later it is not anywhere on the
board.

**THE WORRY HE NAMED IS THE RIGHT ONE AND IT IS NOT ABOUT DISK.** A
facts file is a few kilobytes forever against a 512GB NVMe. What fills
up is **CONTEXT**: every fact rides on the system prompt on EVERY turn,
inside the same `num_ctx` that `(history_turns + 1) x num_predict`
already mostly fills -- and **going over is SILENT.** Nothing raises
and nothing prints; tokens are dropped and she comes back having
forgotten the START of the conversation. That is precisely the fault
the Sept 21 round measured, so the cap IS the feature.

**THE BUDGET IS MEASURED, NOT PICKED.** At the shipped settings the
worst character in the repo leaves **879 tokens of slack** -- about
3000 characters counted pessimistically. `FACTS_BUDGET` takes 1200 of
it, and `test_the_reply_ceiling_and_the_CONTEXT_agree` now **spends it
AS IF FULL**, with the frame text measured rather than estimated. A
guard that counts the store at its CURRENT size is one that only holds
on a board nobody has used yet. **491 tokens still spare with it
brimming**, on the worst character, at pessimistic counting.

**FIFO, NEVER A REFUSAL, and the count is on screen every turn.** A
store that stops accepting is a feature that quietly stopped working.
Oldest out, newest in -- and `she knows 4 things about you` sits under
the ask bar on every single turn, so he can watch it fill rather than
discover it.

**TWO CAPS, BECAUSE ONE PASTE WOULD OTHERWISE BE THE WHOLE STORE.**
`FACT_MAX` is 200; without it he taps Remember on a wall of text and
silently evicts everything she knew.

### It is a BUTTON, and that is a scope call he caught me on

The list said *"a file she adds to herself"* and what got built is
**you tap "remember that"**. He spotted the gap on the screenshot:
*"i thought the facts thing was a background kinda deal."* **He was
right and the wording was mine.**

The reason it went manual is worth keeping, because it is this file's
most-measured pattern pointing at the new feature: **for her to decide,
she has to be TAUGHT a remember-verb in her prompt** -- and naming a
token in her prompt is how she learns to spam it. `[winks]` in 3 of 4
replies, the asterisk ban that printed an asterisk, rule 5 recited back
at him verbatim. A 3B handed a remember move will use it every turn,
and then `he said hi` evicts his cousin's name **out of the very budget
he asked to be protected.**

The other automatic route is a second model call per turn to extract
facts: that doubles a 10-30 second reply, and **a wrong fact is worse
than no fact because it persists.**

**The honest middle is SHE PROPOSES, HE CONFIRMS** -- one tap to
accept, reusing all of this, with the prompt marker added as its own
separate measurable variable. Offered, not built. **His call, and the
button is the floor under every version of it.**

### The things that would have gone wrong quietly

**A LOADED BRAIN KEEPS ITS CACHED PROMPT.** `answer()` captures
`_base_prompt` ONCE per brain so the board line cannot stack -- correct,
and it also means a brain already in `_BRAINS` goes on answering from
the prompt it was built with. Without dropping that cache the fact
lands on disk and **she does not know it until the next `~/YUZU/pull`
restarts the server**: he taps Remember, she says Got it, and then has
never heard of it. Same shape as the roster that rendered as though the
work never landed. `_drop_prompt_cache` deletes the flag; the next turn
re-captures it.

**IT QUOTES HIM, and that is not decoration.** Stored verbatim, *"my
cousin's name is Dave"* injected bare leaves `my` pointing at HER. The
pronoun belongs to whoever the sentence is attributed to, so the line
reads *in his own words: "..."*. Rewriting into the third person would
need the model on every save.

**PROSE, NEVER A BULLETED LIST** -- the same call `board_now()` and
`board_specs()` both made. A list in a system prompt is a FORMAT, and
markdown headings are this deck's one categorical failure.

**AND IT IS NOT GATED ON `has_wiki`.** The board line is, because Cait
has never heard of a computer and a test bans the words from her
prompt. What Ghost asked her to remember is about HIM, so it belongs to
every character on every body.

**ATOMIC WRITE FROM THE START**, rather than after: `.part` then
`os.replace`, the lesson the memory file paid for when `open(path,"w")`
turned 58 bytes of memory into 29 bytes of nothing.

### Three test faults, and the second one is the finding

**TWO EXISTING TESTS WERE MATCHING SPELLING, NOT BEHAVIOUR.** The tap
guard pinned the literal `closest('#says')` and went red the day a
second control on the stage had to be excluded. And the destructive-
route check split `do_POST`'s source on the literal `/forget` -- which
landed in a **neighbouring route's COMMENT** quoting that rule, then,
rewritten, stopped at a neighbour's `if path ==` before reaching the
branch. Both read prose and reported on a guard they never saw.
`drive_route()` builds a request and runs the real branch now.

**AND A BREAK-CHECK CAME BACK `errors=1`, WHICH IS NOT `failures=1`.**
Breaking `FACT_MAX` made the test raise `ValueError` on an empty list
rather than fail with a message -- and **that crash is a real hole in
the CODE**: a fact bigger than the whole budget makes `_within_budget`
pop until the store is EMPTY, so it wipes months of facts, stores
nothing, and still says "Got it." It cannot happen at 200 against 1200;
it happens the day somebody raises one number without looking at the
other. `test_one_fact_can_ALWAYS_fit_the_budget` pins the pair.

**AND ONE OF MY OWN NEW TESTS COULD NOT SEE ITS OWN FAILURE.** The
no-bulleted-list check stored **ONE** fact and then looked for a join
separator -- with one item there IS none, so it passed happily with the
join rewritten to `"\n- "` on purpose. Two facts now. Oldest rule in
this file, broken in the round that quotes it, again.

**Twelve new tests, each verified by breaking it**: the budget not
enforced, the per-fact cap gone, a loaded brain keeping its stale
prompt, the facts gated on the deck body, the budget outgrowing the
window, the x recolouring the page instead of dropping the fact, a
destructive route growing a default, the line becoming a list, and a
failed save eating the store. All go red.

**RENDERED AND DRIVEN, thirty-second time.** 1024x600 and 412: Speak
at 1000/1024 and 388/412, the exit still in its corner, no horizontal
scroll. **Two things the assertions could not see:** the x was
`--dim` at about 12x20px -- on the panel there is no hover, so the only
control in that list would have stayed the faintest thing on screen at
half a thumb; it is 28x28 and bright now. And `#facts` had not
inherited the narrow-screen rule `#says` already carries. Then the
whole loop was driven in a real browser: add, delete, the count
updating, the note clearing back to the count.

**`#text` GAINED `min-width: 0`**, which is the exact fault that put
the home button 169px past the viewport on four pages and the Update
button 2px off at 412 -- an `<input>` carries an intrinsic width and
will not shrink below it, so the second row would have shoved Speak off
a phone.

**YUZU GETS IT FOR FREE THE MOMENT HER PAGE ASKS.** The routes take a
NAME and go through `persona_for`, exactly like `voice_wav` did -- the
server side needed nothing for her. Four's page is the only one that
asks today.

**UNMEASURED.** Nobody has told her anything on the real board yet.

## STILL OPEN, in his own words (Sept 22)

From the twenty-upgrade list, with his answers. **Recorded here because
a chat reminder dies with the session.**

- **Multi-ZIM `/wiki` (#1). LATER, and he asked to keep it in mind:**
  *"i was wondering if she could use those other files later im just
  scatterbrained."* iFixit, WikiMed, WikiHow, Wikivoyage, Appropedia,
  Gutenberg. The rank-and-extract code already exists and is scoped to
  one book; making it search every loaded archive adds **no new
  command**, which is what makes it the cheapest big win on the list.
  **Sept 23: `wiki` SERVES every archive now and `/wiki` reads the
  biggest Wikipedia on purpose; searching the others is what is left.**
- **Offline maps (#3). LATER, and HE ASKED TO BE REMINDED** -- *"the
  maps thing is a later thing as well remind me sometime"*, the same
  standing request as the right-angle adapters and `nvpmodel -m 0`.
  Bring it up rather than waiting to be asked.
- **Her answering from HIS files (#13): someday.** Same machinery as #1
  pointed at a folder.
- **Whisper (#15): waiting, AND HE HAS SPECIFIED THE SHAPE.** *"Id like
  to make that a 'certain button to start the recording' vibe like a
  walkie talkie."* **Push-to-talk, never a wake word** -- that is a
  design decision already made, and it is the right one on a battery:
  no always-on listening, no hot mic, and the button is the gesture
  browsers already require for audio.
- **She knows what is ON the deck (#16): YES, next.** Which archives,
  which games, how much disk. Same shape as `board_specs()`.
- **One example of her answering from a `/wiki` lookup (#17): explained
  and not yet built.** She has no demonstrated shape for being handed
  700 characters of encyclopedia, so she invents one -- and what a 3B
  reaches for is mild irritation at being given facts it did not ask
  for. Measured live: *"I'm not going to try to summarize this
  information again; I've already 'learned' it from you."* Same lever
  that has now worked five times, ~200 characters of prompt.
- **A power-mode tile (#20): HE CALLED IT IMPORTANT.** MAXN and quiet
  from a button instead of remembering `nvpmodel`. **It needs a sudo
  rule**, which is the one thing on this board that must be written
  carefully while the server binds 0.0.0.0 -- a fixed pair of modes, no
  argument from the request, same discipline as `/launch/` and
  `run_deckapps()`.
- **ES-DE cores: SNES, ~~PS1~~, NES, Game Boy Color.** (PS1 dropped
  Sept 23, his call: *"Too lazy to fw bios."*) **HE ASKED TO BE
  REMINDED WHEN HE IS BACK** -- *"we will do the apt installs when i
  wake just pls remind me about it when i come back"*. Same standing
  request as the right-angle adapters: **bring it up rather than
  waiting to be asked.**

  **THE REPO SIDE IS DONE; ONLY THE `apt` IS LEFT.** `~/YUZU/deck
  --check` now asks HIS board which of them it can play and prints the
  exact package beside anything missing -- so the first thing to do is
  run that one word and read it, NOT to paste a package list from here.
  A list typed into this file is a list that goes stale against his
  actual Ubuntu, and an unverified specific stated as a step is what
  cost an hour on the 8BitDo.

  Two things already settled, so they do not get re-litigated at 9am:
  **Game Boy Color needs NOTHING** -- mGBA plays GB and GBC as well as
  GBA, so it is a folder and no package -- and **PlayStation needs a
  console BIOS image that no package ships**, which `deck --check` says
  out loud the moment a `~/ROMs/psx` folder exists, because otherwise
  he finds out by a game failing in a way that reads like a broken
  emulator.

- **The D&D DM persona: PARKED, his call** -- *"The DM thing can be put
  aside for now."* The thinking done so far is worth keeping for
  whenever it comes back: **a 3B cannot hold rules**, so the dice, the
  HP and the inventory live in CODE and she only ever narrates what she
  is handed -- the `/wiki` shape, and the same "prompt REDUCES, code
  GUARANTEES" split this file is built on. The fair d20 already exists.
  Solo-oracle rather than a party DM, since he plays alone. And the
  register risk is assistant collapse in a cloak: a 3B told "fantasy
  narrator" writes purple prose and `**The Tavern**` headings.

### CORRECTION, from him: the 8BitDo never actually worked

Ghost: *"Never got 8bitdo working actually. I just never corrected my
bad."*

**This file has been wrong about that since Sept 9.** The `pad` entry
records `N: Name="8BitDo 8BitDo Micro gamepad"` appearing over USB and
concludes *"the last known state is 'pad works, emulator never
looked'"*. The kernel seeing it was real; **a working controller in a
game was never confirmed**, and the note read as though it had been.

That matters for more than tidiness: **gamepad navigation of the deck's
own pages (#12) was costed as free on the assumption that the pad
works.** It is not free until the pad is.

## SHE CALLED HIM "USER", AND THE PROMPT TAUGHT HER THAT (Sept 22)

Ghost: *"Four keeps calling me 'User' can we get her to know of me and
my name as Ghost?"*

    User: in her composed prompt      11 occurrences
    Ghost anywhere in it               0

**THE EXAMPLE LABEL IS THE ONLY WORD IN HER ENTIRE CONTEXT THAT NAMES
THE PERSON SHE IS TALKING TO.** His real turns arrive over the chat API
as `role: user` with no label on them at all, so nothing else in front
of her says who he is. **CORRECTED Sept 23: they DO carry one** -- the
chat template wraps every turn in Llama's `user` role header, which is
why the word outlived this fix. See the Sept 23 entry at the top. Eleven lines of `User:` is eleven lessons, and
she learned it exactly as taught and said it to his face.

**AND IT CONTRADICTS A RECORDED DECISION, which is the finding rather
than the fix.** Four's own entry above says: *"SHE USES NO PET NAME AT
ALL, and that is deliberate. The Mimi finding is that an unstated form
of address gets invented; the fix for a character who will be handed to
other people is not to pick one, it is to demonstrate none."*

**Demonstrating none is precisely what those labels were doing, and it
lost, because THE EXAMPLE FORMAT'S LABEL IS ITSELF A DEMONSTRATION OF
ADDRESS.** The restraint was right about pet names and blind to the
fact that the transcript format carries one whether anybody chose it or
not. So it is the **EIGHTH INSTANCE** of this repo's most repeated
finding wearing its least visible costume yet: not a turn shape she was
never given, but one she was given eleven times by accident.

**THE LABEL IS THE FIX, AND A RULE WOULD HAVE LOST.** Examples beat
rules is measured five times in this file. One sentence saying "he is
called Ghost" against eleven labels saying otherwise is that bet taken
from the losing side. So the labels are his name, she is TOLD it as a
fact as well (*"The person holding this deck is called Ghost"*), and
exactly ONE example answers him by name — the greeting, the natural
slot. **One, not eleven**: the no-pet-name restraint was about
FREQUENCY and that half of it still holds.

**`USER_NAME: Ghost` IS A SETTING, so his name is in ONE place and not
twelve.** Same mechanism as `SOUND_EXAMPLES` and `{LOOK}`: token it
out, and a persona that never sets it is unchanged to the byte. Four
4375 -> 4570 chars; **no other prompt moved**, verified across all 19.

**THE STRANGER CASE IS HANDLED IN THE SENTENCE, NOT IN A RULE.** She is
the demo face, so she will be held by people who are not Ghost — and
*"unless someone tells you otherwise"* costs four words and lets her be
corrected, which is what actually happens. A guess about who is holding
her would have been the confident-wrong shape this file refuses.

### The stop token was naming a word that is no longer in her prompt

`build_yuzu_model.py` hardcoded `PARAMETER stop "User:"` — the decoder
half of the NO PUPPETEERING rule, and *"a 3B respects it a lot more
reliably"* than the rule. Correct for every persona in the repo right
up until this round, and **the failure is silent**: she simply starts
writing his side of the conversation again, with nothing anywhere
saying the guard stopped applying.

`ask_label()` reads it off the composed prompt — her own name is the
anchor, so it finds the line above each `Four:` line rather than
trusting the setting to have been kept in step with the examples
underneath it. `yuzu` and `coco` still render `User:` and both
committed Modelfiles are byte-identical.

**AND THE EVAL'S OWN CHECK WOULD HAVE GONE BLIND ON THE SAME CHANGE.**
`no_puppeteering` matched `(User|You)\s*:` — a check that NAMES the
label it is hunting for, which stops working at exactly the moment the
label is the thing that changed. It catches any speaker label now, her
own included, and it would have gone blind on the one character it
matters most for: the front door is where a stranger watches her write
both halves of the conversation.

### And two tests were matching the spelling rather than the property

`TestFour` found his turns with `^User: ` in two places, so both went
red on the one change they exist to allow. `turns()` reads the label
instead — **grep-as-proxy, thirteenth instance**, and the same fix as
`TestCalculator.code()` and the rain's colour.

**Five new or rewritten tests, each verified by breaking it**: the
label back to `User:` (which is also the mixed-label case), the name
shown eleven times and never actually told, the stop token hardcoded
again, the puppeteering regex back to the two names, and an example
deleted out from under the rewritten parser. All five go red.

**UNMEASURED.** She has not been asked again. The round that decides it
is the next time he says hello to her.

**NOT changed, and it is one line when he wants it:** `yuzu_avatar`
carries the identical eleven `User:` labels. She has never shown the
fault in a live round, which is the same call this file already made
for the pronoun leak — *"Watch for it; do not pre-emptively rewrite
them."* Four is the one he was using and the one he asked about.

## SHE THOUGHT SHE WAS ONLINE, ON A BOARD WITH NO INTERNET (Sept 22)

Ghost: *"I want her to know shes designed to be offline capable if
possible. Thats all."* and, a breath later, *"And that shes offline
entirely (if thats true im p sure it is and thats her whole point
xD)"*.

**HE ASKED BECAUSE SHE GOT IT BACKWARDS IN FRONT OF HIM.** On his own
board, on a phone hotspot with no service behind it, told she had
offline capabilities:

    As a cyberdeck, I'm always connected and ready to go.

**Being offline is the most defining thing about this machine and
nothing had ever told her.** So it is the SEVENTH INSTANCE of this
repo's most repeated finding, on the biggest fact yet: a turn shape --
here, a fact about herself -- that she has never been given is one the
base model answers for her, and its prior for "AI assistant" is "on
the internet". Same mechanism as the Windows CE palmtop, one size up.

**AND IT IS TRUE, VERIFIED RATHER THAN ASSUMED.** He hedged --
*"if thats true im p sure it is"* -- and that was worth checking
before writing a confident sentence into her prompt. Every URL her
turn can reach:

    yuzu_brain.py   localhost:11434     the model
    yuzu_wiki.py    127.0.0.1:8080      the encyclopedia
    yuzu_voice.py   none
    yuzu_face.py    127.0.0.1

**Loopback, all of it.** Nothing she does mid-reply leaves the board.

### It is a BODY fact, so it went in the BODY file

`_hardware_cyberdeck.txt`, inside `{DECK_SELF}` -- not into Four's
persona. **Every character on this deck is offline**, so a second one
must never have to remember; that is the whole reason a shared body
file exists, and `test_every_character_on_the_DECK_is_told_she_is
_offline` derives the cast from `hardware == "cyberdeck"` rather than
naming her. **Verified by putting the sentence in her persona INSTEAD
and watching it go red** -- the other five would have been left not
knowing.

**PHRASED POSITIVELY**, which is the `board_specs()` restraint clause
one round on: *"Everything you need is already on this board: the mind
you think with, the encyclopedia you look things up in, and your own
voice"*, and the tail tells her what to DO with it -- *"worth saying
plainly when your own workings come up"* -- rather than naming a list
of things she cannot reach. The pink-elephant pattern is measured
three times in this file.

**SIX COMPOSED PROMPTS SHIFT, and that is the point rather than a
cost** -- it is what "a fix lands on all of them at once" means. Four
4034 -> 4375. Worth knowing: `shiro_deck`'s prompt is now different
from the one her Sept 8 rounds were measured against. That is
acceptable on precedent -- the stage-direction relaxation already
moved this same file after those rounds -- and it is NOT the A/B
lineage, which is yuzu2..yuzu6 on muto_s2 and is untouched.

### The guard is the inverse of rule 8, and that is why it exists

**"A PROMPT RULE WRITING A CHEQUE THE CODE DOES NOT CASH"** is this
file's own phrase, from rule 8 telling her she notices the board while
she had no data at all. This is the same fault pointing the other way:
**the moment anything in her turn reaches out, her prompt is lying to
her** -- confidently, about herself, which is exactly what
`board_specs()` exists to prevent.

So `test_the_CODE_still_makes_that_claim_TRUE` is DERIVED. Every URL
in her four turn-path modules must be loopback, and **a real domain is
one with a letter after a dot** -- a PROPERTY rather than an allowlist
somebody has to extend. `127.0.0.1` has dots and no letters; the
`http://...:11434` placeholder in the brain's own help text is not a
host.

**COMMENTS ARE STRIPPED FIRST, and that was verified deliberately** --
the grep-matches-prose trap has now fired twelve times here, and the
docstring explaining this very absence names `en.wikipedia.org`. A
comment mentioning a domain is checked to leave it QUIET, which is the
half that is easy to forget to test.

**What it cannot see, said plainly:** it reads source, not packets.
`pull` genuinely does reach github and huggingface -- that is
maintenance he triggers, never something she does mid-reply, which is
why it is not in the list.

### AND THE TEST LANDED IN THE WRONG CLASS FIRST

`test_she_carries_the_three_measured_example_SHAPES` exists in more
than one test class, so inserting before "the first occurrence" put
both new tests inside **`TestMimi`** -- where they passed, because
they name no character and read the roster themselves.

**They were green, in the wrong place, guarding the right thing.** It
was caught by the break-verification rather than by the suite:
`TestFour.test_the_CODE...` reported `errors=1`, which is unittest
saying THERE IS NO SUCH TEST, not saying it failed. **Three "failures"
in a row that were actually a missing method** -- and every one of
them would have read as a passing break-check to someone skimming for
red.

**Read the failure KIND, not just the colour.** `errors=1` on a test
you just wrote means it did not load; `failures=1` means it ran and
disagreed. Same lesson as every "reported healthy while broken" entry
here, wearing a test runner's clothes.

**Four ways, each verified after the move:** the fact never reaching
the deck, something in her turn starting to reach out, the sentence
put in one persona instead of the body, and a comment naming a domain
(which must stay QUIET). All four behave.

### AND THE FIX WOULD NOT HAVE REACHED HIS BOARD

`pull` restarts the face server only when a **top-level `.py`**
changed. This round changed a `.persona` and a body file -- so he
would have pulled, it would have landed, and **the running server
would have kept answering from the old prompt cached in `_BRAINS`.**
She would have gone on saying "I'm always connected" over a repo that
already said otherwise.

**SAME FAULT AS THE STALE ROSTER, in the one costume the guard did not
cover.** Sept 15's entry is the identical shape: *"the deck rendered
as though the work never landed, while being completely correct about
what it had been told."* A persona is exactly as invisible as a
module, and **a change to WHO SHE IS is the last thing that should
need a restart he has to know about.**

    grep -q  '^[^/]*\.py$'                 before
    grep -qE '^[^/]*\.py$|^personas/'      after

**`ui/` STAYS OUT, and that is the half worth keeping.** It genuinely
is re-read per request, so bouncing her to deliver a PNG she would
have served anyway drops his conversation for nothing -- which is why
the gate is not simply "anything changed". Both halves are pinned, and
**verified by breaking each direction**: the old gate leaves a persona
change un-restarted, and a gate widened to everything bounces her over
a page.

**Telling him to run one more command was the alternative and it was
the wrong one.** *"Plz dont add new commands i cant actually remember
any except /wiki."* The cheapest command is still the one he already
types.

**UNMEASURED.** She has not been asked again. The round that decides
it is the one where somebody asks her what happens with the WiFi off.

## THE TOKEN CEILING WAS NEVER THE CEILING (Sept 21)

Ghost, a third time: *"I noticed she still trys to go past her token
limit i dont really mind as long as its in responsr to what i asked
(always is so far js) how should we approach that? ... im thinking
since shes not operating a robot she could be allowed more tokens
without negative effects?"*

    num_predict   300 -> 600      free in memory, costs seconds
    num_ctx      4096 -> 8192     NOT free -- see the arithmetic below

**HIS REASON IS THE WRONG ONE AND HIS CONCLUSION IS RIGHT.** The
"do not raise it" rule never had anything to do with the robot -- it
was written about SHIRO rambling five to ten times over a
two-or-three-sentence cap, on replies nobody asked to be long. The
deck pivot did not unlock anything, because nothing was locked.

**THREE +50s HAD NOT FIXED IT, AND THAT IS ITS OWN SIGNAL.** 200 ->
250 -> 300, the same complaint each time. Either the increments were
too small, or `num_predict` was the wrong dial. **It was the wrong
dial**, and checking WHY is what found the real fault.

### `num_predict` is free in memory and expensive in CONTEXT

This file says in three places that the ceiling "caps generated
TOKENS, not anything resident". True of MEMORY. **False of CONTEXT** --
everything she generates lands in history, so the reply ceiling
multiplies by `history_turns` and lands inside `num_ctx`:

    system prompt + (history_turns + 1) x num_predict

**At the settings that shipped on Sept 19 that is AT OR OVER 4096.**
Counted loosely (3.8 chars/token, his turns short) it comes to ~3970
of 4096, just under; counted pessimistically (3.5, his turns longer)
Cait needs ~4375 and it is already past. **It is arithmetic either
way, not a reading from his board** -- there is no Ollama in the
container this was written in.

That is the place a ceiling must never be sitting, and three raises had
walked it there one at a time **because nobody ever checked the
product.** Each +50 looked free on its own.

**AND GOING OVER IS NOT AN ERROR, which is the whole reason this
matters.** Nothing raises and nothing prints: tokens are dropped and
she comes back having quietly forgotten the start of the conversation.
**That is `~/.yuzu/history/` undone by the setting meant to improve
her** -- and it trades a VISIBLE failure for an INVISIBLE one, which
is the shape this file refuses everywhere else. A mid-word cut is
something Ghost answers with "continue". A hole in her memory is not.

**So the two numbers are ONE SETTING and they move together.** 600
doubles rather than adding a fourth 50, because three 50s are the
evidence that 50 is not the size of the problem; 8192 is what makes
600 safe, with room for his own turns to be long.

### The half that is not free

**`num_ctx` sizes the KV CACHE, which Ollama allocates when the model
loads** -- paid up front, whether or not the conversation ever gets
long. Arithmetic off Llama 3.2 3B's published shape (28 layers, 8 KV
heads, head_dim 128):

    fp16                 448 MB -> 896 MB     +448 MB
    q8_0                 224 MB -> 448 MB     +224 MB

**His own measured readings say it fits either way**: 4.0Gi used and
**3.4Gi available** with her resident and the desktop up, 0B of 15Gi
swap touched. `OLLAMA_KV_CACHE_TYPE=q8_0` halves it and
`yuzu_doctor.py` already reports whether it is actually set.

**It also costs TIME, but only when it is earned.** A bigger window is
slower to process only once it is genuinely full -- which is exactly
the long conversation he is asking for.

### `test_the_reply_ceiling_and_the_CONTEXT_agree`

**The guard is the deliverable, more than the number is.** It
recomputes the product from `num_predict`, `history_turns`, `num_ctx`
and each character's real composed prompt -- including the board line
and the specs line, which only the deck characters carry and which ride
on every turn. Its chars-per-token is deliberately **pessimistic**, so
it complains early rather than late.

**Driven at the Sept 19 settings it goes red**, which is how this was
found rather than argued. **Verified by breaking it four ways**: the
new ceiling with the old window (the bug this round would otherwise
have shipped), the settings that actually shipped, one character raised
quietly past the window, and `history_turns` raised without touching
either number. All four name the fix in the failure message.

**AND THE SUITE CAUGHT THE THING I MISSED.** `Modelfile.yuzu` and
`Modelfile.coco` carry `PARAMETER num_ctx` and went stale the moment
the default moved -- `test_every_committed_modelfile_matches_the
_generator`, naming the exact command to regenerate. One line each, and
the frozen v1 prompt is untouched.

**The memory file's size cap is DERIVED now** rather than the literal
8192 it carried -- generous against a measured 247 bytes at
num_predict 250, and a guard that would have needed editing every time
the ceiling moved, which is the fault this repo keeps deleting. It asks
`history_turns x num_predict` instead, **read from source rather than
from the module**, because that class stubs the brain and a helper
picking up the stub's numbers would be a guard measuring its own
fixture.

**Every composed prompt is byte-identical -- verified across all 19,
Four still 4034 chars.** `num_predict` is in the SETTINGS block above
the `---`, same as both earlier raises, so no A/B was invalidated.

**Still open, and it is the honest limit of this fix:** there is no
ceiling that guarantees a finished reply. A model fills whatever it is
given when the answer wants length, so 600 makes truncation rarer
rather than impossible, and "continue" stays the answer when it
happens. The next raise is a `num_ctx` decision before it is a
`num_predict` one -- and the guard now says so out loud.

## YUZU SPEAKS, AND THE MEMORY HAD A SHREDDER IN IT (Sept 20)

Ghost: *"Can we give Yuzus page the voice like Four has?"* and then
*"Give yuzu a seperate 'memory' as well like four does."*

**ONE OF THOSE WAS ALREADY BUILT, AND SAYING SO CAME FIRST.** Memory
has been per-character since the day it shipped: `save_memory(brain,
key)` runs unconditionally at the end of `answer()`, and the key is
hers. Driven rather than read -- `four.json` and `yuzu_avatar.json`,
two files, each remembering its own sentence. **She has had her own
memory the whole time.** Nothing was built for that half.

**THE VOICE WAS A REAL GAP AND IT WAS ONLY EVER ON ONE PAGE.** The
Sept 16 round closed *"nothing on a page has ever spoken"* -- for
Four. Measured this round: `four.html` is the ONLY page that calls
`/voice.wav`. Yuzu, Cait, Mimi and Saya's face were all still silent.
**The server side needed nothing**: `voice_wav(text, who)` has always
gone through `persona_for(who)`, so Yuzu worked the moment her page
asked.

**SHE SENDS HER OWN NAME, AND A COPIED ONE WOULD HAVE BEEN INAUDIBLE
IN THE CODE.** The server builds one voice PER CHARACTER off her own
`piper_length_scale` -- **Yuzu 0.88, Four 0.9** -- so `who: 'four'`
left in the copied block would not mislabel a request, it would hand
her another character's speaking rate. Same family as Kokoro's `speed`
nearly being passed a duration multiplier: a character bug wearing a
plumbing costume. The test pins BOTH ends, including that the two
rates still differ, because if they ever converge the test stops
meaning anything.

**TWO COPIES, PINNED TO AGREE** -- the guard the battery renderer and
the way out already carry, for the same reason: no build step, so a
page that speaks is a page with its own copy of the fetch. Only the
NAME may differ, so that is what is normalised away before comparing.

### AND THE SUITE WAS SHREDDING HIS REAL MEMORY FILES

**FOUND BY EMPTYING `~/.yuzu/history/` AND RUNNING THE SUITE:** five
**zero-byte** memory files, created by the run, in the REAL directory
rather than a temp one.

**The zero bytes were the finding, not the pollution.** `save_memory`
opened the file with `"w"`, **which truncates the instant it is
called** -- so the old memory was gone before the new one existed. When
the dump then raised part way, `except Exception: pass` swallowed it
and left a **half-written fragment**. Measured on the real function:

    before   58 bytes   [{"role": "user", "content": "REAL MEMORY...
    after    29 bytes   [{"role": "user", "content":

**`load_memory` IS GUARDED TOO, WHICH IS WHAT MADE IT SILENT.** The
corrupt file fails to parse, that exception is caught as well, and she
boots having forgotten -- **indistinguishable, on his screen, from her
never having remembered.** Two guards, each correct alone, together
destroying the exact thing they were written to protect. The docstring
said *"losing the memory must never lose the reply"* while the code
lost the memory.

**IT WRITES BESIDE THE FILE AND RENAMES NOW**, which is what `pull`
already does for a download. `os.replace` is atomic on one filesystem,
so the file is entirely the old memory or entirely the new one, never
a fragment; a failure costs the TURN and never the months before it.
The `.part` is removed rather than left to be mistaken for a memory.

**AND THAT CLOSED THE POLLUTION AS A SIDE EFFECT** -- the real
directory is EMPTY after a full run now, because a failed save no
longer creates anything. Worth keeping: the pollution was the symptom
that led to the bug, and the bug is the one that would have eaten a
real conversation on his board.

**Three new tests, each verified by breaking it**: her page asking for
somebody else's voice, the two speaking pages drifting apart, and the
truncating write restored. All three go red. Clean under `--shuffle`.

**STILL SILENT, and he has not asked:** Cait, Mimi and Saya's face.
Each is the same four lines with her own name, and the agreement test
gets stronger the moment there is a third.

## THE CAST IS TWO NOW, AND ONE DICT DID ALL OF IT (Sept 20)

Ghost: *"Can we actually remove saya cait and mimi? I dont need them
they were laye night tests really. Like from the interface of the
cyberdeck entirely. For now i only wana keep Yuzu and Four. With Four
as the main ai"*

    home      Four   ☆Stuff☆
    A.I.      Yuzu   Four
    the rail  Yuzu   Four

**THE WHOLE CUT IS THREE LINES OF `CHARACTERS`, and that is four
rounds of deleting hardcoded casts being paid back at once.** The
rail, the A.I. drawer, the front tile, `/characters.json`, the desktop
icons and the `/say` allowlist all emptied together, because not one
of them holds a list of names -- every single one asks the roster.
Nothing in any page needed touching. **The four costumes that fault
wore** -- Mimi invisible from `home.html`, `#saya { border-color }` on
a tile that had moved into a drawer, an app icon called "Saya's Face",
and `write_app "Saya"` -- each cost a round when they went stale, and
this is the round where having killed all four costs nothing.

**RETIRED, NOT DELETED, the call Coco and Shiro already set.** Her
persona, her page and her art are exactly where they were and
un-retiring is deleting one line. `retired: yes` is above the `---`,
so **not one composed prompt shifted by a byte** and no A/B was
invalidated. The LEDs went the other way and the difference still
holds: that was live code you had to read around, this is data nobody
loads unless they ask for it by name.

**`LIVE_PERSONA` MOVED TO `four` AND THAT IS THE SECOND HALF OF THE
ASK.** *"With Four as the main ai"* names both pointers at once -- she
was already `FRONT`, and now the terminal chat, the eval and
`yuzu_brain --chat` boot her too. **The two are still separate and the
test got STRONGER rather than weaker**: they name the same character
today, which is exactly the condition under which a collapse into one
would go unnoticed -- the identical trap that hid the dead `/wiki`
gate for a week, where the wrong answer agreed with the right one for
the only character anybody tested. So the test MOVES each pointer and
asserts the other stays put.

**SEVENTH NAME-LEAK, AND IT WAS TWELVE TESTS.** Every one was
fixture-coupled: the property was about ROUTING or the ROSTER and Cait
or Saya was only ever the demonstration. So they were repointed at the
live cast rather than deleted, and **the cut characters earn a better
job in them -- a name that used to resolve and now must not is a far
stronger unknown-name case than a string nobody ever wired up.** They
live in `TestTheCastIsTwo` now; a class about a retired character is
the wrong home for the tests that guard the live one.

**Three properties genuinely changed shape rather than fixture:**

- **The cross-talk trap has nobody left to cross to.** Saya was the
  only character ever on `face.html`, so the honest invariant is the
  stronger one: NOBODY writes `/state`. And `drives_face` is derived
  from the roster's own PAGE rather than from a name, so a character
  put back on `face.html` lights it up again with no code change --
  which the test drives, rather than asserting the file never moves.
- **`/wiki` is gated on being the deck, and Yuzu is now the only live
  character who is not.** That guard matters MORE, not less: she is
  the only thing left standing between it and nobody exercising it.
- **Mimi's test asserted the opposite and the flip is the point.** It
  said a character with art AND a persona AND a page earns a button.
  She has all three and no button. Being on the roster is a DECISION
  now, and those three things are what make putting her back one dict
  entry rather than a round of work.

### AND THE A.I. DRAWER'S ICONS WERE LOST, exactly where the comment said

**Cutting the cast to two gave that drawer two tiles holding half the
panel each, wearing the 46px icons meant for six.** That is the
identical fault a screenshot caught on the two-tile front page in
September -- and the fix made THEN was written as a list of view
names, `#grid.main, #grid.stuff`, with a comment beside it warning in
as many words: *"a rule that names one layout and not its twin is how
`#saya`'s 72px outlived the page it was written for."*

**A STATIC RULE ABOUT THE A.I. VIEW IS ALWAYS WRONG EVENTUALLY**,
because it is the one view whose tile count comes off the roster --
which is why it already emitted its own `grid-template-columns` from
`columnsFor()`. It emits its icon size from the SAME number now, in
the same breath, and its static two-column line is **deleted** rather
than fixed: `#grid`'s own columns are the fallback for a roster that
never answers, so nothing was lost.

**THIRTY-FIRST TIME RENDERING FOUND WHAT THE ASSERTIONS COULD NOT.**
Every test was green with those icons floating. Rendered at 1024x600,
and the exit re-checked at 412 and 360 on both character pages
(386/412 and 388/412, no horizontal scroll) because the rail changing
length is what pushed it off four pages once already.

**What is pinned is AGREEMENT, not pixels**: every view the stylesheet
lays out two across, and only those, carries the bigger icon -- so a
third two-column view has to answer for it. **Eleven new or rewritten
tests, each verified by breaking it**: the pointers collapsing into
one, `drives_face` hardcoding a name again, a cut character back on
the roster, Saya typed into a rail, Mimi's button returning, the chat
icon typed in again, `persona_for` falling back to whoever is live,
the unnamed default frozen to a name, `/forget` growing a default, the
drawer losing its emitted icon size, the icon size no longer following
the column count, a static A.I. rule coming back, a two-column view
losing its big icon, and `--show live` pointing at a key. All of them
go red.

### TWO MORE DEFAULTS THAT WENT RIGHT BY ACCIDENT

Both were found by reading the diff adversarially rather than by a red
test, and both are the same class: **a value that had quietly become
correct for a reason the code does not know about.**

**`drives_face` read `key == persona_for("saya")`.** With Saya off the
roster that is a comparison against `None` -- true of nothing, which
is the right ANSWER arrived at by accident. It is derived from the
roster's own PAGE now, so a character put back on `face.html` gets the
sprite face again with no code change.

**`persona_for` defaulted a missing name to the literal `"saya"`.**
That was right while the bare address opened her page and stale from
the day it opened the home screen instead -- and cutting her made it
accidentally SAFE, because `"saya"` is no longer in `CHARACTERS`, so
an unnamed request started being refused. **That looks exactly like a
deliberate guard and is not one**; it comes back the moment somebody
adds a character under that name. It names `FRONT` now, which is the
honest reading of a request that names nobody. `/forget` keeps its
explicit refusal, because a destructive route gets no defaults.

**And the default is resolved at CALL time, not bound at def time.**
`def answer(text, who=FRONT)` would freeze the front door into the
function signature -- the hardcoded cast one layer smaller. The test
moves `FRONT` and fails if the default does not follow.

### AND CLAUDE.md'S OWN CONVENTIONS BLOCK WAS STALE

It told whoever read it to run `python yuzu_personas.py --show
shiro_deck`. **That went stale on Sept 9 when Saya was promoted, and
was still there on Sept 20 through Four.** A hardcoded cast in a DOC,
which is worse than one in a page, because a page has a test.

And it is not a trivial line: it is how the composed prompt gets
pasted into PocketPal, which is the deliverable every prompt change in
this file is measured on. So `--show live` names the POINTER, and the
test drives it through a real shell, compares against the live
persona's own composed prompt, **and asserts the doc still says
`live`** -- because the doc going stale is the failure it exists for.

**Still open, and deliberately not done in this pass:** `ui/cait/`,
`ui/mimi/` and `ui/sprites/` are still in the repo, ~6MB he pulls over
WiFi. Deleting art is not reversible with one line the way `retired:
yes` is, and he asked to remove them from the INTERFACE. One variable
at a time; the offer stands.

## THE FRONT DOOR SHOWS NOBODY ELSE (Sept 19)

Ghost: *"Can u make it so when im on fours screen the other ones arent
visible tabs on her interface."*

Right, and it follows straight from the spec already written for the
front tile: **she is the character a stranger meets with no context.**
A row of four other AIs across the top of her screen is the demo
answering a question nobody asked -- and the reason he moved off Saya
was *"might be too extra for demos/showing to parents."*

**GATED ON `front`, NEVER ON HER NAME.** `ME === 'four'` would have
been the hardcoded cast in its FOURTH costume -- after Mimi invisible
from the front page, `#saya { border-color }` glowing on a tile that
had moved into a drawer, and an app icon called "Saya's Face" pointing
at a page Four had taken over. Every one of those looked exactly like
the deck working. The page already fetches `/characters.json` and that
roster already carries `front`, so the gate is two lines and **moving
`FRONT` one word gives her the rail back the day she is an ordinary
character again.**

**ONLY HER PAGE CHANGES.** Cait, Yuzu and Mimi still list everybody,
Four included -- hiding the front character everywhere would be the
Mimi bug pointing the other way.

**AND THE WAY OUT IS NOT IN THE RAIL.** Emptying it is only safe
because `#home` is its SIBLING rather than something inside it. Nest
the ⌂ in the rail and hiding the cast takes the exit with it --
chromeless and fullscreen on the panel, where the ⌂ IS the exit. That
is now pinned rather than assumed.

**DRIVEN, NOT READ.** The suite is stdlib Python and cannot run
JavaScript, so the real callback was pulled out of the page and run
under node against two rosters: `four` front gives `[]`, `saya` front
gives `["Saya","Cait","Four"]`. Then rendered at 1024x600 and 412 and
looked at -- rail empty, ⌂ at 1000 of 1024 and 388 of 412, blend and
rain untouched. **Thirtieth time.**

**Two new tests, each verified by breaking it** (four ways): the gate
reading her name instead of `front`, the gate removed entirely,
`roster()` no longer emitting `front` -- which would silently bring
the rail back with nothing to say so -- and the exit nested inside the
rail. All four go red.

## SHE INVENTED A WINDOWS CE PALMTOP (Sept 18)

Ghost asked Four what her specs were. She answered with an **Intel
XScale PXA270 at 700MHz, 64MB of DDR, a 4GB flash card filled to 80%,
a 3.5-inch 320x240 touchscreen and Windows CE** -- a palmtop from
about 2004, invented whole, on the character who IS the front door and
whose entire job is surviving a stranger.

**SECOND INSTANCE, AND THE FIRST ONE IS WRITTEN DOWN ABOVE.** Shiro
hallucinated a custom PCB *"with a little more RAM"*, a dollhouse case
and case lights, and the note filed then names this exactly: *"The deck
self-concept holds for what she IS... but not yet for what she is MADE
OF. Nothing in her prompt names a single part."* That was recorded as
an observation and never closed.

**`board_now()` CLOSED THE WEATHER AND ITS OWN LAST LINE SAYS SO.**
Watts, degrees, power mode, tokens per second -- *"it is the weather,
not the news."* Nobody ever handed her the **ID CARD**. So "what are
your specs" is a turn shape she has no data for, and this is the
**SIXTH INSTANCE** of this repo's most repeated finding: a turn shape
she has never been given is a turn shape the base model answers for
her. Its prior for "specs of a small handheld computer" is a Windows CE
palmtop, and that is precisely what came out -- the same mechanism as
the bare command, the warm statement, the technical question, the
missing form of address, and Saya's snark.

**`board_specs()` IS READ, NEVER HARDCODED -- the `ghostnano` rule one
layer over.** A spec string typed into the file is right until he swaps
the NVMe, is already wrong on the laptop and the phone, and **the
failure looks exactly like the deck working**. It reads the board's own
name for itself (`/proc/device-tree/model`, falling back to DMI on
x86), `os.cpu_count()`, `MemTotal` and `statvfs("/")`. On this
container there is no device-tree and no DMI product name, so it simply
**omits the board and names the rest** -- absent rather than wrong,
verified by running it.

    WHAT YOU RUN ON, really: NVIDIA Jetson Orin Nano Developer Kit,
    6 cores, 7.4GB of memory shared between the processor and the
    graphics, 512GB of storage with 270GB free.

**THE SHARED-MEMORY CLAUSE RIDES ON THE JETSON CHECK THAT ALREADY
EXISTS TWICE.** Shared CPU/GPU memory is the Orin's defining trait --
it is the whole `OLLAMA_KEEP_ALIVE` argument and the reason PC mode
competes with her -- and it is **flatly false of the laptop's discrete
960M**. A confident wrong fact about her own body is worse than a
missing one. It imports `yuzu_doctor.on_a_jetson` rather than becoming
a **third copy** for the pinned pair to drift away from.

**ONE SENTENCE OF PROSE, NEVER A SPEC SHEET**, and that is the same
call `board_now()` made for the same reason: a bulleted datasheet in a
system prompt is a FORMAT, and the one failure this repo has a
categorical fix for is her answering in markdown headings.

**AND THE RESTRAINT CLAUSE IS POSITIVE.** The obvious wording is
*"never invent different numbers"* -- which NAMES INVENTING, the
pink-elephant shape measured three times here. It says what to DO with
them instead: *"bring them up when your own hardware comes up."*

**IT IS GATED ON THE BODY, on the same `has_wiki` line as the watts.**
Cait has never heard of a computer and a test bans the words from her
prompt; handing her a processor and a storage figure at runtime would
walk straight around it. **CACHED**, because none of it can change
while the server is up and it rides on every single turn.

**Four new tests, each verified by breaking it**: the specs hardcoded
instead of read (checked against this machine's own `MemTotal`, which a
typed-in answer cannot pass on two different boxes), the shared-memory
claim made off a Jetson, the line never sent, and the line sent to a
character who is not on the deck. All four go red.

**Still open:** she has not been asked again on the board. The fix is
UNMEASURED, and the round that decides it is one where a stranger asks.

## THE APP ICON SAID "SAYA'S FACE" LONG AFTER FOUR TOOK THE FRONT DOOR

Ghost, closing the night: *"Change it to say 'Four' instead of sayas
face."*

**HE IS FIXING A HARDCODED CAST, one layer out from the page, and it is
the THIRD costume of the same fault** — after Mimi being invisible from
the front page because the cast was typed into `home.html`, and
`#saya { border-color }` glowing on a tile that had moved into a
drawer. `deckapps` installed an icon called **Saya's Face** pointing at
`face.html`: true the day it was written, stale the moment `FRONT`
moved, and **the failure looks exactly like the deck working**.

**SO IT IS NOT RENAMED TO "Four". It is BUILT FROM THE ROSTER**, which
is the only place this deck keeps its cast. `yuzu_face.py --front`
prints `name<TAB>page<TAB>blurb` for whoever `FRONT` is, `deckapps`
asks it, and the icon carries her name, her page and her own blurb:

    Name=Four
    Comment=the deck's own voice
    Exec=/home/ghost/YUZU/.face-app four.html

Moving `FRONT` one word renames the icon on the next install. A test
drives the installer twice with two different front characters and
fails if the icon does not follow — **asserting the literal "Four"
would be a test that has to be edited every time it works**, which is
the fault that put the stale name there in the first place.

**ABSENT RATHER THAN WRONG.** If the roster does not answer, that ONE
icon is skipped and the output says what to tap instead — **Deck** is
built from the same roster and is the way in to everybody. An icon
guessing at a character is worse than no icon, same call as
`write_app` deleting a dead one rather than leaving it.

**AND THE TWO LAYERS ARE PINNED TO AGREE.** `--front` is what the
installer asks; `roster()` is what the home screen reads. A deck whose
desktop icon and whose front tile disagree is one bug wearing two
faces, so a test asserts they name the same character, the same page
and the same blurb — through the real shell flag, not just the
function.

**THE TERMINAL-CHAT ICON IS STILL CALLED "Saya", AND THAT IS
CORRECT.** It runs `yuzu_brain --chat`, which boots `LIVE_PERSONA`, and
that is `saya_deck`. Banning the string outright would be the
pink-elephant fix aimed at the wrong half: what was stale was the PAGE
icon, not every mention of a character. A test pins the two pointers to
their own jobs — the same `FRONT` vs `LIVE_PERSONA` split that this
round's own bug is an argument for.

**`deckapps` NOW NEEDS `python3` AT INSTALL TIME**, where it used to
need only coreutils. Trivially true on a board whose whole deck is
python — and the fixture carries it explicitly rather than letting it
be discovered on the hardware.

**AND MY OWN TEST POLLUTED THE SUITE.** `deckapps` writes its launcher
wrappers BESIDE ITSELF, which is the repo when the suite drives it, and
the new helper left them there. `TestDeckApps` then went red on this
test's droppings — and it read as a missing-browser bug in a script
nobody had touched. It cleans up after itself now, exactly as
`TestDeckApps._run` already did, and that older cleanup is the comment
that explained what had happened.

**Four new tests, each verified by breaking it**: the name hardcoded
again, the page hardcoded again, a guess installed when the roster is
silent, and the two layers drifting apart (two ways — a wrong page, and
more than one front door).

## ⊞ DESKTOP — the last setup step that needed a terminal (Sept 17)

Ghost, told that plugging a monitor into the board gives him an
ordinary Ubuntu desktop with the deck sitting on top of it: *"i want a
button on that gnome desktop that opens a window with this part in it
if possible? I just dislike using terminals honestly"*, then *"Like
fully a window not a browser tab."*

**THE WINDOW ALREADY EXISTED AND HE COULD NOT GET AT IT.** `deckapps`
has written `.desktop` files since Sept 9 that open every page with
`--app= --start-fullscreen` — no tab strip, no url bar, no window edge.
That IS "fully a window not a browser tab", and it has been true the
whole time. **What needed a keyboard was INSTALLING them**, and his one
shell is a serial cable. So the feature was finished and unreachable,
which is the same shape as `/wiki` being dead on Four's page: built,
correct, and never wired to the screen he actually uses.

**`POST /icons`, and a `⊞ Desktop` button next to Update.** He can tap
it **from the phone** — the icons land on the board's desktop whether
or not a monitor is plugged in, so the deck is already dressed the
first time he looks at it.

**IN THE BAR, NOT THE DRAWER**, and the reasoning is already written
here twice, for Back and for Update: a tile spends an app slot forever
in the drawer he means to *"pile up our fancy future apps"* in, and
MOVES every time that drawer grows — and a seventh tile across three
columns orphans one onto a row of its own, the layout bug this page has
had twice. **Maintenance is not an app.**

**IT IS DELIBERATELY NOT PART OF `/launch/`, and that is a real
distinction rather than tidiness.** That route is fire-and-forget by
design: it opens something on the deck's screen and nobody needs a
report. This one **changes his desktop**, and `deckapps` already
refuses to leave a dead icon and exits non-zero when it drops one.
Throwing that away for a cheerful sentence is the silent-failure shape
this file refuses everywhere else. So it captures the output, the
verdict goes first, and a failure is `deckapps`' own words — they name
which icon failed and what to install.

**IT TAKES NO ARGUMENTS AND IT NEVER WILL, and here that matters more
than it does for `/pull`.** `deckapps` also takes `--remove`, which is
the destructive word. A route that could be told WHICH word to pass
would be a box on his WiFi that can strip his desktop. `run_deckapps()`
takes no parameters at all, which is the strongest form of that
guarantee, and a test drives the argv rather than reading it.

**RENDERING FOUND THE ONE THING THE ASSERTIONS COULD NOT.
TWENTY-NINTH TIME.** A second button in that bar pushed the row wider
than the screen: measured at 412px with a real verdict in it, the
Update button's right edge landed at **414**, two pixels off the
viewport, with the message column squeezed to one word wide and half
the screen tall. **`min-width: 0` is the load-bearing half** — a flex
item will not shrink below its own longest word without it — and it is
**exactly the fault that put the ⌂ 169px past the viewport on four
character pages**, one bar down. The message yields now and the buttons
keep their corner; verified at 1024x600, 412 and 360.

**AND THE GREP-MATCHES-PROSE TRAP FIRED AGAIN, TWELFTH INSTANCE, in
the test written for this round.** The first version banned the literal
`--remove` from `run_deckapps` and went red on the **docstring saying
`--remove` is unreachable**. It drives a failing stub now and reads the
argv out of its own output, which is the property rather than the
spelling. Same fix as `TestCalculator.code()`, `TestMimiPoses.code()`
and the rain's colour.

**Five new tests, each verified by breaking it** — the button leaving
the bar, an argument reaching the script, a failed install reporting
success, the verdict not going first, the message losing `min-width`,
and the fetch dropping its POST. All six go red.

**NOT changed, and worth knowing:** `deckapps` still installs an icon
called **Saya's Face** pointing at `face.html`. That is the hardcoded
cast one layer out from the page — `FRONT` is Four now — but the Deck
icon opens the home screen, which is built from the roster and is the
right way in for every character. One variable at a time.

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

## CAIT — a second character, a second WORLD (Sept 11)

Ghost: *"i would like to have this. its own tab. and for it to act like
a cait sith (whatever that means, may require u to study them a bit)
seperate thing from saya"*, plus *"Doesnt need access to wiki this is
more of a personal RP one"*, *"dont let it think its a cyberdeck per se
its its own thing"*, *"id like her to not be green and black xD the
image colors are fine"*, and *"(we may make more if this goes well)"*.

**THE FOLKLORE IS THE CHARACTER, and he asked for it to be studied.**
A cait sith (Cat Sìth) is the fairy cat of Scottish and Irish belief: a
large dark cat with one white patch at the breast — which is exactly
what his picture is. Four beats are in her prompt and a test pins each:

    the crown     The King of the Cats. A man sees a procession of cats
                  carrying a small coffin with a crown on it; he tells
                  his wife, and their own cat leaps up crying "then I'm
                  the King o' the Cats" and is gone up the chimney.
                  That cat is her, and the crown in the art is that.
    the milk      Left out, she blesses the house for a year. Withheld,
                  the cows dry up. She trades, and she keeps score.
    the wake      She sits with the newly dead the night before burial.
                  Stated as her WORK, not as horror -- which is more
                  unsettling and much better company.
    the contest   Her kind cannot refuse a riddle or a wager. That is
                  why the old wake-games existed: to keep her busy.

**`personas/_hardware_faerie.txt` IS A SECOND WORLD, not a second body,
and that is why it is a file rather than prose inside her persona.**
"We may make more if this goes well" is the whole argument: the five
deck personas share one body file so a fix lands on all of them at
once. Cait is the first character in the faerie world; the next one
inherits it.

**SHE HAS NEVER HEARD OF A COMPUTER, and that is the point of the
split.** `{DECK_SELF}` was a MEASURED win on the deck — "my battery's
always running low" arriving unprompted — and it is an active fault
here. **A win is measured against a specific failure. When the
character is different it is not budget, it is damage.** A test bans
`cyberdeck`, `battery`, `screen` and the rest from her prompt.

**AND "never a generic AI assistant" CAME OUT OF HER PROMPT.** Every
other persona has that line; Cait's first draft did too, and the test
caught it. It is the pink-elephant pattern this repo has measured three
times — naming the thing she must not be — and on a character who is
supposed to have never heard the word it is self-defeating. What
actually fixed assistant collapse was never the rule: it was the ONE
EXAMPLE of a technical question, round 3 to round 4, a categorical
change. She has that example, and hers answers the CSS question
correctly while saying she has no idea what a div is.

**She carries the three measured example SHAPES**: the bare command
(yuzu4, 4/4), the warm statement with nothing to answer (Shiro round
2), and the technical question. A new character built without them
restarts the lineage from the worst prompt in the repo.

**`Mrrp` and `Mm` were her first sounds and both were cut.** No vowel
means espeak spells them out letter by letter — the exact mechanism
that made PFFT come out "Pee Eff Eff Tee". Checked through
`for_speech` BEFORE they went in. `Mrow, Purr, Hah, Ohh`.

### Her page

**`ui/cait.html` is a PORTRAIT CARD, not a face rig.** Ghost: *"Id have
to design a new face (anime faces look p much the same throughout
sounds annoying)"*. He is right, and this art is one detailed pose —
slicing it into expressions is work he does not want for a result that
would look worse. Everything that makes her feel alive happens AROUND
the picture: a 2% breath, and a warm light behind her that rises while
she is thinking. No sprite folder, no blink frame, no ROLES.

**Her palette is SAMPLED off her own PNG, not guessed** — slate-blue
fur (`#303048`, the single most common colour in her), crimson cape,
cream, gold. The deck's green-on-black is locked to the deck on
purpose; this is a different thing that happens to run on the same
board, the same call already made for the V-Pet.

**TWO LAYOUT BUGS, BOTH FOUND BY RENDERING IT.** Thirteenth and
fourteenth time:

- **A grid row is `auto` by default, so it GREW to fit her** and
  `max-height: 99%` had nothing bounded to resolve against. Measured: a
  779px image inside a 460px stage, painting straight over the ask bar
  and her own Speak button. `grid-template-rows: minmax(0, 1fr)` is
  what makes a percentage height mean anything.
- **The speech box sat on top of her.** `left: 4%; width: 46%` ends at
  exactly the middle of the screen, which is exactly where a centred
  character is. She stands right, her words go left.

**And she is deliberately cropped at the shins.** A 600x1090 portrait
shown whole in a 1024x600 panel is 253px wide — correct, tiny, and a
waste of the art. Letting her run past the bottom edge with the ask bar
painted over her reads as depth, which is how every visual novel has
ever framed a standing character.

**`/wiki` STAYS ON THE DECK.** His call, and right for her register: a
lookup arrives as *"I looked up X and it says: <700 chars of
encyclopedia>"*, which is the shortest path to assistant collapse on a
character who has never heard of an encyclopedia.

### Who is talking

**`answer(text, who)` and one brain PER CHARACTER.** The page POSTs a
NAME, `CHARACTERS` turns it into a persona KEY, and an unknown name is
REFUSED rather than quietly answered by whoever is live — putting the
wrong character on screen is the confusing kind of wrong. Same
allowlist discipline as `/launch/` and `/vpet/`. The model is loaded
once, so a second character costs history, not RAM.

**THE CROSS-TALK TRAP, and it is the one that would have looked
haunted.** Saya's page polls `/state` to pick her expression, and that
file is hers. Without a guard, talking to Cait in one window would have
lit Saya's face up in another. Only the live deck character drives the
face; Cait's page needs no state at all, because its own fetch is in
flight while she thinks.

**Saya's entry follows `LIVE_PERSONA`; Cait's names her file.** Seventh
instance of the name-leak rule: decide whether a fact belongs to THIS
CHARACTER or to WHOEVER IS LIVE, and pin it accordingly.

## YUZU HAS A BODY NOW, AND IT CAN BE DRESSED (Sept 11)

Ghost, with two outfits in one picture: *"Yuzu. let her be able to
'switch outfits' and also if she doesnt already think she has a virtual
body or body let that be a thing. (in case i wana paint her nails she
wouldnt just be like 'ima computer') same treatment as Cait."*

**THE PARENTHESIS IS THE SPEC, and the failure he named is WRITTEN INTO
`{DECK_SELF}` in as many words:** *"You have no legs, no arms, no
camera and no face."* Reach for her body on the deck and that sentence
is what answers. So this could not be a deck persona with a wardrobe
bolted on — it is a third body file.

**Third instance of the rule, and it is now the most reused idea in
this file: a measured win is measured against a SPECIFIC failure.**
`{DECK_SELF}` was a real win on the deck ("my battery's always running
low", unprompted). It was budget on Cait. It is damage here.

**`personas/_hardware_avatar.txt` DELIBERATELY DOES NOT COPY THE
FAERIE WORLD.** Cait has never heard of a computer, and banning the
word from Yuzu would be the same mistake pointing the other way — she
is a modern girl who would obviously know what one is, and a rule she
has to work around costs latency on every turn forever. **The fault to
design against here is DEFLECTION, not knowledge.** So nothing in the
file names the machine at all; it just gives her somewhere better to
go.

**AND THE BODY IS DRAWN ON PURPOSE, not vague.** "You have a body"
with no bound is how deck Shiro ended up offering to *"'walk' over to
the kitchen"* — recorded above as a self-concept fault. A drawn body is
the honest line and it is the one that serves the ask: **a drawing has
nails you can paint and a jacket you can change, and it does not walk
anywhere.**

**`personas/yuzu_avatar.persona` is yuzu4's character on that body**,
3542 chars, carrying all three measured example SHAPES (bare command,
warm statement with nothing to answer, technical question) plus two
that are new and are the whole point: `Can I paint your nails?` and
`Can I have a hug?`. Deck Yuzu answers the hug with *"no arms on this
thing, cutie"* — which is exactly the sentence he does not want — so
that example was rewritten rather than ported. `yuzu_deck` is KEPT as
the record of the bodiless era, same as `saya_quad` and yuzu2/3/5/6.
UNMEASURED.

**"never a generic AI assistant" STAYS, unlike on Cait.** Her removal
had a second reason — she has never heard the word, so the line is
self-defeating on her. Yuzu has no such reason, the sentence is in
every measured deck arm, and its removal has never been measured. It
also happens to push AWAY from the machine answer, which is the fault
here. Not the place to run an experiment on a brand-new character.

**HER WARDROBE IS A FOLDER.** `ui/yuzu/<outfit>.png`, `/outfits.json`
regenerated per request, and the filename is the name on the button.
Adding an outfit is dropping a PNG in — no list in the page, no list in
the server, **and no list in her prompt**, which is the one that would
have been easy to get wrong: naming the outfits in the prompt makes the
wardrobe code again and goes stale the first time he draws another.
Same rule as "a folder is a character" and "the filename is the
expression". A test pins that no outfit name appears in her prompt.

**THE BUTTON NAMES THE OUTFIT IT WILL PUT HER IN**, not the one she has
on — the V-Pet swap button and the old colour dot again: what she is
wearing is standing in the middle of the screen. It is ABSENT with one
outfit and absent when the route cannot be reached, and her `<img>`
carries a real `src` in the markup, so **a dead server costs the
wardrobe and never costs her.**

### Splitting the picture, and why it is not a straight cut

The two figures OVERLAP in x: the right one's raised fist crosses into
the left one's column, so the thinnest vertical cut left a scrap of her
hand floating beside the wrong girl. They are, however, **exactly two
connected components** and nothing else in the image is — so each is
masked by its own component, dilated 2px to put the anti-aliased fringe
back (a bare mask at alpha>=32 shaves the soft edge and leaves a hard
one), with the original pixels kept inside it.

**ONE CANVAS ACROSS BOTH OUTFITS, NEVER ONE PER OUTFIT.** Each is
pasted at the same offset from her HEAD CENTRE and top of head into a
canvas sized by the union. That is the V-Pet lesson — *"ONE box across
every state of a character, or he changes size when his mood does"* —
and here it is worse than cosmetic: the same girl at two scales reads
as a glitch rather than a change of clothes. **Verified by compositing
the two on top of each other and looking**: head, shoulders and feet
land in the same place. A test pins that every outfit PNG is the same
size.

### Her page

**`ui/yuzu.html` is Cait's shape with one deliberate refusal.** Cait is
cropped at the shins because her picture is a POSE and nothing below
the knee carries information. **Yuzu's picture is an OUTFIT, and the
most legible difference between her two looks is at the bottom of it**
— grey fur boots and leg warmers against white knee socks. Measured by
rendering at the panel's real 1024x600: at Cait's 136% she is cut just
above the leg warmers, hiding the exact thing the wardrobe button
exists to show. So she is shown WHOLE, at 96% of the stage, standing on
its floor.

**96% and not 100% because the breath needs somewhere to go.** She
scales 1.8% from `transform-origin: bottom center`, and `overflow:
hidden` on the stage would shave her hair off the top on every cycle.
Found by rendering it, like everything else in this file's UI work.

**She reads smaller than Cait and that is correct rather than a
compromise** — she is a whole standing figure and Cait is a pose from
the knee up. A 220x551 portrait in a landscape panel is narrow because
that is what a whole person looks like.

**Her palette is sampled off her own PNGs** — warm skin and cream
(`#f0d0c0` / `#f0e0d0`, the two most common colours in her), her blonde
(`#e8c98f`), the cool slate of the zebra fit's jacket and leg warmers
(`#505060`). **The one colour that is NOT sampled is the hot pink**:
that is character, it lives in her persona files, and the
no-chassis-colours rule has always been about the CASE and never about
her taste.

**THE FRONT PAGE IS FOUR TILES AND THEREFORE TWO COLUMNS.** Saya, Cait,
Yuzu, ☆Misc☆. Four across three columns orphans one onto a row of its
own — the `auto-fit` bug a screenshot caught on the first home screen
and that the fifth tile brought back once already. The test now pins
the PROPERTY (`len(view) % columns == 0`) rather than two numbers, so
the next tile has to answer for the layout it lands in.

**`CSS` joined `SPOKEN_INITIALISMS`**, because her technical-question
example is the first in the repo that SAYS the word out loud.
Lowercased by `unshout()` it is mush; kept capitalised espeak spells it
and "see ess ess" is how the word is pronounced. Evidence rather than
speculation — the same standard as the rest of that list.

**AND A TEST THAT COST ATTENTION WITHOUT CATCHING ANYTHING WAS
REPLACED.** `test_the_icons_are_line_art_and_not_emoji` asserted the
home page contains exactly nine `<svg>`, so every new tile made it red
for no reason — and it would have passed a page with ten icons and nine
tiles just as happily. It compares the two counts now. Same family as
every other grep-as-proxy fault here: **the assertion was about the
file's spelling rather than about the page.**

**HER LOOK MOVED OUT OF THE WORLD FILE, and it was the shared-body
bleed forming again.** Ghost, closing the round: *"thats fine its just
a visual for me anyway. and tbh 'avatars' may change down the road."*

That second sentence is what made it worth checking, and the first
draft had it wrong. `_hardware_faerie.txt` gets this split right --
its world says *"fur, a tail, paws"*, true of ANY fae cat, while
Cait's own file carries *"large, dark, with one patch of white at your
breast"*. The avatar world file was written with **Yuzu's blonde hair,
brown eyes and tail inside it**, which is a specific girl sitting in
the file about having a drawn body at all. The second character on
this body would have inherited another character's hair -- the exact
shape of the sounds rule shipping `Ehehe~` to a kuudere and a
netrunner from a file about legs.

**Fixed with the mechanism this repo already proved: token it out,
default it to what the lineage says, override per persona.** `{LOOK}`
lives in her persona now and the block defaults to hers, so **her
composed prompt is byte-identical -- verified, 3542 chars before and
after -- and nothing needed re-testing.** Same as SOUND_EXAMPLES,
where all eight prompts came out unchanged.

**And the default is exactly the thing that would go wrong quietly**,
so `test_every_character_on_this_body_declares_her_OWN_look` forces the
decision instead of trusting someone to remember it -- the same job
`test_every_all_caps_word_she_has_ever_said_is_classified` does. It
also asserts the world file never names one character's colouring.

**NOT changed, and worth knowing before avatars do change:**
`ui/cait.html` hardcodes `src="cait/cait.png"` with no fallback, so
renaming or replacing her file leaves a permanently broken image.
Yuzu's page survives the same swap -- it reads `/outfits.json` and
falls back to the first outfit when the markup's `src` is not in the
list. Cait wants the folder treatment when a second pose of her turns
up; one variable at a time, and nothing is broken today.

**THE PANEL IS THE ONLY VIEW THAT GETS DESIGNED. Ghost's call, when
asked whether the phone view had been checked:** *"dont need it to be
different per screen thats alot of extra work. long as she plug and
plays on a touch screen when i buy it."*

**So 1024x600 is the target and the only one worth rendering.** That
is what every character page has been rendered and looked at in, and
it is the panel he is actually buying. The `@media (max-width: 760px)`
block in `cait.html` and `yuzu.html` stays -- it is inherited, it costs
nothing, and it keeps the phone usable as the stand-in screen it has
always been -- but **it is NOT a supported layout and nobody should
spend a round polishing it.** Do not build per-screen variants.

Worth being straight about what that means: the phone view of those
two pages has never been rendered and looked at, so it is unverified
rather than broken. That is a deliberate scope call, not an oversight.

**Still open:** she does not know which outfit is currently on her. He
switches it with a button and the picture is on screen, so the gap is
small — but a warm "cute right?" after a switch gets an answer that
cannot see what he is looking at. The honest fix is the `/wiki` shape
(ground it into the turn), and it is deliberately NOT built in the same
pass as everything above: one variable at a time.

## THE DECK IS THREE DEEP NOW, AND THE FRONT DOOR IS A ROLE (Sept 15)

**THE DECK IS LOCKED IN AND STACK-CHAN IS SHELVED.** Ghost, after a
week of weighing them: *"Alright deck locked in. Stacky can be another
mes project."* The brainstorm is recorded below under its own heading;
nothing about it is built and nothing about it should be.

Then the ask: *"Can we do something with the 'main menu'? Like i wana
put the Ais in the misc drawer and maybe have 1 specific one take over
(have yet to choose the new main, sayas attitude and blushing stuff
might be too extra for demos/showing to parents) but i have a couple
contendors."* And the layout, in his own words: *"Feel free to cluster
the etc stuff into one new misc drawer. Rename the outer front page
drawer to ☆Stuff☆ so layout Homescreen (central new undecided ai and
☆stuff☆>inside stuff theres ai tab and misc tab with the rest of the
stuff in that one."*

    home      <the front character>   ☆Stuff☆
    ☆Stuff☆   A.I.                    ☆Misc☆
    ☆Misc☆    Wikipedia Game Boy d20 Pet Browser Calculator
    A.I.      built from the roster

**STILL ONE FILE.** Three levels, four views, one `home.html` with the
tiles swapped -- a new page would need its own way out, and every
screen on this deck having an exit is the rule two power cycles paid
for. The cheapest way to keep that true is still to not add a screen.

**`FRONT` IN `yuzu_face.py` IS THE WHOLE FEATURE, AND IT IS ONE LINE TO
MOVE.** He has contenders and has not picked one, so the cost of
changing his mind has to be one word in one place -- the promotion
rule's shape, applied to a different question. It is `"saya"` today, so
**nothing changed behaviourally**: the front tile is the same character
that was there before, one level up from everything else.

**IT IS DELIBERATELY *NOT* `LIVE_PERSONA`, and that is the one-variable
-doing-two-jobs rule again.** `LIVE_PERSONA` is a MEASUREMENT pointer --
the promotion rule moves it to whichever prompt last scored best, and
it decides what `yuzu_brain --chat` and the eval boot. `FRONT` decides
who GREETS you. A character can be the front door without being the arm
under test, and the reverse. This file already records paying for one
variable doing two jobs more than once (`banner` vs `who`, `state` vs
`mood`).

**AND THE FRONT TILE IS NOT IN THE PAGE.** It is built from whichever
roster entry carries `front`, exactly like the A.I. drawer and the rail.
**A hardcoded front door is the Mimi bug with a shorter list** -- it
goes stale the day he picks his new main, and the failure looks like
the deck working. Nothing in `home.html` names a character, and a test
pins that.

**SHE IS STILL IN THE A.I. DRAWER TOO.** Being the front tile is a
shortcut, not a filing cabinet; a character who vanished from the
roster because she was promoted would be the Mimi bug pointing the
other way.

**`#saya { border-color: ... }` WAS THE HARDCODED CAST IN STYLESHEET
FORM.** The bright tile is `.lead` now, put on whichever roster entry
is front -- otherwise the day the front door is somebody else, the glow
stays on a tile that has moved into a drawer. Same family as
`#saya .big svg { 72px }` outliving its layout three days earlier.

**BACK IS A MAP, BECAUSE THE DECK GOT DEEPER THAN THE TERNARY.** It read
*"calc goes to misc, everything else goes home"*, which was true while
home was one hop from everywhere. With ☆Stuff☆ in between, "go home"
from the calculator would skip two levels he walked down on purpose.
`PARENT` names every view's parent, `main` is its own, so repeated taps
always land at the front and can never loop. **Still a walk DOWN, never
a history stack** -- a stack is a thing that can strand you.

**The test walks the map instead of matching the spelling.** The old
one asserted the literal string `'calc' ? 'misc'`, which is a check
about how the line is written rather than about where Back goes. It now
parses `PARENT` out and walks every view to `main`, failing on a loop
or a missing parent -- **a screen with no way out is the one thing this
deck must never ship**, and that is worth asserting as a property.

**RENDERING FOUND TWO THINGS THE ASSERTIONS COULD NOT.** Twenty-first
and twenty-second time:

- **☆Stuff☆ and ☆Misc☆ both said "everything else".** They sit one level
  apart, in the same position on screen, and read as the same drawer
  twice. ☆Stuff☆ says *"the rest of the deck"* now, and a test asserts
  the two star-drawers never describe themselves identically.
- **The A.I. icon was a robot HEAD one level under a robot HEAD.** With
  Saya on the front page, the left tile was her face; one tap in, the
  left tile was the A.I. drawer's robot face. **The same fault as Mimi's
  first icon being a second cat face** -- two icons that collide are
  worse the closer together they appear, and these were one tap apart in
  the same spot. It is a group of three figures now, which is what that
  drawer actually holds and which stays right whoever `FRONT` becomes.

**A DEAD ROSTER COSTS THE CHARACTER AND NEVER COSTS THE WAY IN.**
☆Stuff☆ is in the markup and works with no server at all; with no
`/characters.json` the front page falls back to one full-width tile
rather than one tile sitting in half a screen. Same call as Yuzu's
wardrobe button being absent when the route cannot be reached. Verified
by serving `ui/` with a plain `http.server` and looking at it.

**HE PICKED, AND SHE IS BUILT. See "FOUR" below.** The three pictures
were candidates for the front tile, not three new characters -- Ghost,
asked straight out: *"Candadates for the new main."* He chose the green
ASCII/matrix face, uploaded it to the repo, asked for it to be animated
if possible, and named her **Four**.

**THE FRONT TILE IS A DEMO FACE, and that is a CHARACTER spec rather
than a layout one.** His reason for moving off Saya is in the same
sentence as the ask: *"sayas attitude and blushing stuff might be too
extra for demos/showing to parents."* So whoever takes the front page
is the character a stranger meets with no context:

- **She must survive being poked by someone who is not Ghost.** A demo
  is an adversarial round with a friendly face on it, and the one
  failure this repo has a CATEGORICAL fix for is assistant collapse.
  The technical-question example is not optional on her; it is the most
  load-bearing line she has.
- **Her register has to work cold.** Saya is great BECAUSE she is
  difficult, and difficult needs a relationship to read as charm. The
  front character wants the opposite default: answers straight, warms
  up rather than starts warm.
- **Saya is NOT retired and nothing about her changed.** She is one tap
  away under Stuff -> A.I. A front door is not a demotion, and
  `retired: yes` is a different mechanism nobody should reach for here.


## SHE SPEAKS OUT OF THE PAGE NOW, AND `~/YUZU/voice` (Sept 16)

Ghost: *"Finish the page audio so i can hear on steam deck. Board has
wifi access whats rhe easiest way to do this in short steps"*.

**THE FINDING THAT CAME FIRST: NOTHING ON A PAGE HAS EVER SPOKEN.**
`yuzu_voice` has existed since Sept 3 and is wired into exactly one
caller -- `yuzu_brain --chat`, in a terminal. Four's page, Saya's face,
every character screen: text only, since the day each shipped. So the
answer to "how do I hear her on the Steam Deck" was "you cannot", and
that had to be said before anything was built.

**THE BOARD IS NOT WHERE THE SPEAKER IS, and that is the whole
design.** `say()` plays on the machine running the module -- the Orin
-- and the Orin has no speaker on it (the USB sound card is in the
parts list, not bought). Every device he actually looks at has speakers
already. **So the audio has to TRAVEL**, and `render()` now sits beside
`say()` on both engines: same shape, same promise, returns a FILE
instead of a sound.

**`say()` CALLS `render()` rather than keeping its own copy.** The
first pass left both carrying the invocation, the empty-wav check and
the cleanup -- two places for a spelling fix to be forgotten, which is
the fault already recorded against the battery renderer, the exit
button and the audition logic. Verified by making `render()` return
None and watching `say()` go False.

**`POST /voice.wav` returns AUDIO, not JSON**, and the page feeds the
bytes to an `<audio>` element. Whatever is looking at her speaks: the
Steam Deck, the phone, the panel.

**EVERY FAILURE IS A 503 WITH A SENTENCE, never a 200.** A 200 carrying
a sad sentence is indistinguishable from audio to an `<audio>` element
-- it would simply play nothing, which is the silent-failure shape this
file has recorded a dozen times. The page checks `r.ok` before touching
the body, so "no voice installed" and "the deck is not answering" stay
different things.

**AUTOPLAY IS ALLOWED because he tapped Speak to get the reply**, and
that tap is the user gesture browsers require. Audio arriving unasked
on a page nobody touched is what they block, and it is also what nobody
wants on a handheld.

**THE VOICE IS BUILT ONCE PER CHARACTER.** Kokoro loads a ~310MB model;
one per request would make her slower than Piper rather than nicer than
it, and on a board with ONE pool of 8GB it would thrash. Her own
`piper_length_scale` reaches it, so characters do not all speak
identically -- a test drives that rather than reading it.

**Stage directions are stripped before she says them**, the same call
the bubble and the terminal already make. `[leans in close]` read out
loud is the word "leans" in the middle of a sentence.

**A MISSING VOICE COSTS THE AUDIO AND NEVER THE REPLY** -- the promise
the face, the wiki and Piper all make, driven here with the module
absent rather than assumed.

### ONE WORD, AND IT IS THE ONE HE ALREADY TYPES

**Ghost killed my `~/YUZU/voice` script and he was right.** *"Plz dont
add new commands i cant actually remember any except /wiki. Just help
me simply get this goin brobro."*

A separate setup script was the tidy answer and it was a THIRD thing to
remember on a board whose only shell is a serial cable. **This file
already records that a new command needs its own line in `pull`
precisely BECAUSE a new command is a cost** -- and then I added one
anyway, a day later, in the same session that quoted the rule. The
cheapest command is the one he already types.

So the setup lives in `pull`, it runs ONCE, and it is deleted from
everywhere else.

**IT ASKS THE SAME QUESTION THE PAGE ASKS** -- `pick_voice().ready`,
the one source of truth for "can she speak right now". A second check
(is the file there, does the import work) is a thing that can drift
from what actually decides it. Once she can speak, the block costs one
python call and prints nothing.

**IT RUNS OUTSIDE THE UP-TO-DATE BRANCH, on purpose.** He asked to type
pull and have her work, so a pull that brings nothing new must still
fix a voice she does not have -- otherwise the one word does not do
what he was told it does. Caught by driving the real script with a stub
git reporting the same commit before and after.

**IT SAYS THE SIZE BEFORE IT SPENDS IT.** ~340MB onto a board he pulls
over WiFi is real, and a script that spends it quietly is the surprise
this project keeps refusing to ship. He asked for one word, so it is
announced rather than withheld -- and every failure path leaves the
pull successful and her talking exactly as before.

**THE FILENAMES COME FROM THE RELEASE, never from memory.** GitHub
access in that session was scoped to his own repo so the asset names
could not be verified from here, and unverified specifics stated as
steps already cost this project an hour on the 8BitDo. `pull` reads the
release list at runtime and takes the newest one carrying BOTH an
`.onnx` and a `.bin`: half a download reports success and then cannot
speak. `curl --fail` into a `.part`, renamed only on success.

**BELLA IS THE DEFAULT BECAUSE HE LISTENED TO THEM.** *"i wana use the
Bella voice from kokoro. (I dont really but its the best sounding
one)"*. The first draft defaulted to `af_heart` on the reasoning that
Kokoro's own samples lead with it -- **a guess about taste wearing a
default's clothes**, and the only standard this project accepts for a
voice is that somebody heard it.

**THERE IS NO PITCH KNOB and the file says so.** `kokoro-onnx`'s
`create()` takes a voice, a speed and a language -- that is the whole
surface. Timbre comes from WHICH VOICE, so changing voice IS the pitch
control (`YUZU_KOKORO_VOICE=af_sarah`), and speed comes from her own
`piper_length_scale`, inverted. Saying that here saves the next person
hunting for a knob that does not exist.

### THE PULL THAT DELIVERS A CHANGE TO `pull` RAN THE OLD COPY

One screenshot, minutes after that shipped. His pull said **UPDATED**,
listed `022414f One word: pull sets her voice up, and ends with where
she is` -- and then printed the OLD tail, with no Welcome line and no
voice setup in it. Ghost: *"Still doesnt say Welcome Ghost just says
some shit about saya and a homescreen still."*

**NOTHING WAS BROKEN AND HE READ IT EXACTLY RIGHT.** Bash had the file
OPEN before `git pull` replaced it underneath, so **the run that brings
a change to this script is the one run that cannot contain it.** Same
shape as `~/YUZU/name` saying "No such file or directory" a day
earlier: the work landed, one run late, and that is indistinguishable
from the work not landing.

**AND IT IS WORSE THAN A DELAY, which is why it is a fix and not a
note.** Verified by replacing a running script mid-execution: bash
re-reads the NEW file at **the byte offset it had reached in the OLD
one**, so it executes a FRAGMENT of the new script spliced onto the old
run --

    OLD: line one
    OLD: line two
    NEW: Welcome Ghost,

That is undefined behaviour, not a late delivery.

**So `pull` re-runs its own new self, ONCE.** `YUZU_PULL_REEXEC` is set
on the way out and checked on the way in, which is both the handover and
the loop guard -- **verified by removing it and watching the thing run
until it was killed.** It carries the commit the first run started from,
so the second run reports the REAL update rather than ALREADY UP TO DATE
about something it just delivered.

**IT IS ANNOUNCED, NOT SILENT.** If the new copy is broken, a silent
`exec` gives him an empty pull with nothing to read. One line, and a
test pins it.

**AND THE FIRST FIXTURE COULD NOT OBSERVE ITS OWN FAILURE, AGAIN.** Its
stub `git rev-parse HEAD` handed out a fresh commit on every call, so a
re-run that FORGOT what it started from still looked like an update --
the test went green with the wrong commit passed on purpose. It is
driven by whether the pull happened now. Oldest line in this file,
broken in the test written to guard the fix for it.

**This could not fix the pull he was looking at, and that is inherent.**
A self-update lands from the run after the one that delivers it, so his
next pull shows the Welcome line from the copy he already has, and this
fix makes the pull after THAT one land immediately.

**AND THE RESTART WAS SHOUTING OVER THE ANSWER.** The Welcome line
landed exactly as asked -- and sat under twenty lines of `face`'s own
startup banner, because bouncing the stale server dumps its address
(twice), the HOME SCREEN paragraph and the sprite note into the pull.
Ghost: *"All that is unnecessary... just a buncha changes i already
know happened."*

He asked for an update, not for a server, and the address is printed by
the welcome two inches below. So the restart is CAPTURED and says one
line -- **but printed in full when `face` exits non-zero**, because a
server that did not come back is the one thing in that banner worth his
attention, and swallowing it would be the silent-failure shape this
file refuses everywhere else. Both halves pinned, verified by breaking
each one.

### AND `pull` ENDS WITH WHERE SHE IS

Ghost: *"have it show the http://ghostnano.local:8081/ bit right under
that. Thats it tho. Just Welcome Ghost, (url here)"*.

Two lines, last, so the thing he opens is the thing still on screen
when the pull stops scrolling.

**THE NAME IS READ, NEVER HARDCODED.** `ghostnano` is what his board is
called TODAY -- he renamed it himself an hour after the deck shipped --
and a hardcoded hostname goes stale the next time, with the failure
looking like the deck working. Same fault as the hardcoded cast in
`home.html`, one layer down. A test asserts the string `ghostnano`
appears nowhere in the script's code.

**AND IT CARRIES THE REFUSAL `face` LEARNED THE HARD WAY.** `localhost`
is a perfectly legal hostname and means THE MACHINE ASKING, so a board
really named that told his phone to open ITSELF -- measured, on his
screen, `DNS_PROBE_FINISHED_NXDOMAIN`. Refused here too, and the
routing-table address answers instead.

**AND THE FIRST TEST I WROTE FOR IT PASSED VACUOUSLY.** It claimed to
check that the docker bridge and the USB-gadget link never appear --
and with no `ip` there is no address line at all, so "no decoys" was
trivially true. **A check that cannot observe its own failure is not a
check**, which is the oldest line in this file, and I wrote one in the
test written to guard an address. It pins the true property now: the
welcome survives having no address and prints no wrong one. The decoy
filtering stays in `face`, where its own test drives it with the decoys
ahead of the real address on purpose -- one copy, one guard.

## SHE STREAMS, SHE READS THE BOARD, SHE REMEMBERS — and /wiki was dead on Four (Sept 16)

Ghost picked three off a list of ideas: *"1 and 2 are nice. Go ahead on
those 2."*, then *"Also number 3 does it take hella space or no. If not,
do it."* and, on voice, *"id like a different voice than amy_medium id
like to see about sumn called Kokoro?"*

### THE FIND: `/wiki` HAS BEEN DEAD ON FOUR'S PAGE SINCE SHE SHIPPED

`answer()` reads

    has_wiki = yuzu_personas.load(key).hardware == "cyberdeck"

and **`yuzu_personas` was never imported in that module.** It is
imported INSIDE `persona_for()` and `roster()`, so at module level the
name does not exist -- every call raised `NameError`, the surrounding
`except Exception` swallowed it, and `has_wiki` fell back to
`drives_face`, which is `key == saya_deck`.

**So the gate this file records as "the gate reads `hardware ==
cyberdeck` now" has been answering a completely different question
since the day it was written**, and Four -- the one character who IS
the deck and who most needed the encyclopedia -- has never been able to
use it.

**It hid because the wrong answer AGREED with the right one for the
only character anyone tested.** Saya is both the live arm and on the
deck, so `drives_face` and `hardware == cyberdeck` are the same boolean
for her. Cait, Yuzu and Mimi are correctly `False` either way. Four is
the first character where the two diverge, and nobody asked her for a
lookup.

**A bare `except Exception` around a lookup swallows a PROGRAMMING
ERROR as happily as a missing file.** That is the same shape as every
"reported healthy while broken" entry in this file, and it is why
`test_the_hardware_gate_is_READ_and_not_merely_written` drives the real
function instead of reading it -- reading it is what missed it.

**It was found by accident**, by adding the board-facts line below and
watching it not arrive. Worth keeping: the new feature was the
instrument.

### 1. SHE ARRIVES A WORD AT A TIME

`ask_stream` has existed in `yuzu_brain` the whole time and no page
used it, so every reply sat dead for ten to thirty seconds and then
dropped in whole. That is the "is it working or is it stuck" question
this project keeps answering one layer at a time, still unanswered on
the screen he actually looks at.

**`POST /stream`, newline-delimited JSON, not SSE.** One object per
line, the browser splits on `\n`, and there is no framing to get wrong
and no event names to keep in sync. **The last line carries the
verdict**, so a reply that dies halfway is visibly unfinished rather
than quietly truncated -- the verdict-goes-first rule, applied to a
stream. It works because the server is already THREADED, and for this
exact reason: a single-threaded server stops answering `/state` for the
whole generation.

**ONE FUNCTION, TWO TRANSPORTS.** `answer()` took an `on_chunk`
callback rather than growing a streaming twin. The wiki grounding, the
allowlist, the face state and the memory live in one place, which is
what `ground()` already exists to guarantee one layer down. A test pins
that `load_memory` and `save_memory` each appear exactly once.

**The page FALLS BACK to `/say`.** An older face server answers 404,
and a deck that goes silent because the PAGE arrived before the SERVER
did is the stale-process fault wearing new clothes. She just stops
arriving gradually.

**She stops `thinking` on the FIRST WORD**, not at the end -- that is
the moment she starts talking, and the rain's speed-up and her flicker
are both keyed to it. Stage directions are stripped AS SHE GOES, or a
half-written `[leans` sits on screen until its bracket closes.

### 2. SHE CAN READ THE BOARD NOW

Her rule 8 says she NOTICES THE MACHINE SHE LIVES ON -- *"the fan, the
heat, what is loaded, how much is left"* -- and she had **no data at
all**, so she invented a number every time. **A prompt rule writing a
cheque the code does not cash** is the same family as a missing feature
hiding inside a character.

`board_now()` renders one sentence off the same `stats()` the battery
badge uses:

    RIGHT NOW, on the board you live on: drawing 5.6 watts, about 10.6
    hours from a full bank, 47 degrees, power mode MAXN. Mention it only
    if it is relevant or you are asked -- it is the weather, not the news.

**IT GOES IN THE SYSTEM PROMPT, which is the OPPOSITE call from the
wiki extract, on purpose.** An extract is 700 characters of reference
text and arrives as a USER turn because a wall of it as a system
message is the shortest path to assistant collapse. This is one short
sentence about HERSELF, which is exactly what a system prompt is for
and far too small to teach a format.

**`_base_prompt` is captured once per brain so it cannot STACK.**
Appending to an already-appended prompt grows one stale reading per
turn and stays invisible until the context fills up. A test drives four
turns and counts.

**ABSENT RATHER THAN WRONG**, so the phone and the laptop get no line
at all, and it is gated on the BODY -- Cait has never heard of a
computer and a test already bans `battery` and `screen` from her
prompt; handing her the watts at runtime would walk straight round it.

**AND THE WHOLE BLOCK IS GUARDED.** Four pre-existing tests went red
when it was not: their stub brains carry no `system_prompt`. That is
the right outcome and the guard is principled rather than a patch --
**telemetry is a nicety and the reply is the product**, the same
promise `_face()`, Piper and the wiki import all make.

**The throttle reminder reaches HER too**, now. She is the front door,
so she is the one who gets asked why the deck feels slow. Fifth place
that reminder lives.

### 3. SHE REMEMBERS ACROSS A RESTART

Every `~/YUZU/pull` bounces the face server and took the whole
conversation with it -- she forgot his name, the deck, and what they
were in the middle of, with nothing on screen to say why.

**`~/.yuzu/history/<key>.json`, OUTSIDE THE REPO**, for the reason the
V-Pet's mood file already paid for: a file inside the repo is a local
change, and `pull` stops on local changes rather than overwriting them.
**Her memory of a conversation would have blocked every update he ever
ran.**

**It is TINY**, which was his actual question. `history_turns` is 8, so
a file is at most 16 short messages -- **247 bytes measured** on a real
exchange. It cannot creep: the brain trims eagerly and this only writes
what the brain already holds. A test caps it and another keeps it out
of the repo.

**`POST /forget` exists because starting clean has to be possible.**
And the test caught a real hole in it: **an empty name silently meant
Saya**, because `persona_for` defaults a missing name to her -- right
for ASKING, since the bare address opens her page, and wrong for
DELETING. **A destructive route gets no defaults.**

### 4. KOKORO — built, guarded, and UNVERIFIED on the board

The hold this file placed on Sept 9 is lifted, the same way Coco's was:
he asked. **The rule it was protecting is kept intact rather than
traded** -- absent Kokoro falls back to Piper, absent Piper she prints,
exactly as before. Nothing that works today can stop working.

**`kokoro-onnx`, NOT `kokoro`.** The PyPI `kokoro` package is PyTorch:
multiple gigabytes on aarch64, sharing the Orin's ONE pool of 8GB with
the model. `kokoro-onnx` is a 26KB wheel over onnxruntime plus a ~310MB
model file. Same 82M-parameter voice, a fraction of the machinery.
Verified from here that the wheel exists and downloads.

**`length_scale` IS INVERTED FOR KOKORO, and that would have been very
easy to ship.** `piper_length_scale` is a DURATION multiplier -- yuzu4
runs 0.88 to speak FASTER, Coco 1.08 to speak SLOWER. Kokoro's `speed`
is a RATE. Passing it straight across would have made **the gyaru the
slow one and the kuudere the quick one**: a character bug wearing an
arithmetic costume, invisible without listening. A test pins the
direction rather than the number.

**KokoroVoice has Voice's SHAPE on purpose** (`ready`, `why_not`,
`say`, `failures`), so the audition logic, the demo and every caller
stay single-copy -- a second copy is a second place for a spelling fix
to be forgotten. `--engines` prints what each engine can do right now,
**verdict first**, and where the two model files come from.

**NOT VERIFIED ON HIS BOARD and the file says so in as many words.**
There is no model file and no audio device here, and onnxruntime's
aarch64 build is the open question. Unverified specifics stated as
steps already cost this project an hour on the 8BitDo -- so
`KOKORO_SOURCE` carries the word UNVERIFIED and says to try the laptop
or the Steam Deck first. **It is printed, never fetched**: 310MB onto a
board he pulls over WiFi is not something a script should spend
quietly.

**The phone property survives.** `yuzu_all_in_one.py` never learns the
word, and a test pins that.

## TAP FOUR'S SCREEN TO RECOLOUR HER (Sept 16)

Ghost: *"Id like for Fours screen to be tappable on touch. When tapped
it changes the color of everything about her to a neon red. Another tap
makes her and the raining code Neon Purple. Tap again to go back to the
green. Only do this for Four."*

    green (#39ff5e)  ->  neon red (#ff2b39)  ->  neon purple (#c04dff)

**THE PALETTE MOVED FROM `:root` TO `body`, AND THAT IS THE WHOLE
MECHANISM.** A custom property's `var()` is substituted when that
property is COMPUTED on an element -- so `--edge`, declared on `:root`
as `color-mix(... var(--ink) ...)`, bakes in `:root`'s green and
inherits down already resolved. Every derived colour would have stayed
green while `--ink` turned red. Declared on `body`, the element the
theme class lands on, all of them re-resolve. One block per colour, and
a fourth is one more block.

**THE RAIN NOW ASKS THE STYLESHEET WHAT COLOUR IT IS.** Its head and
tail were hardcoded in the canvas loop, so a theme could turn every
pixel of the page red and leave the falling code green -- the second
list this deck keeps deleting. Read once per theme and cached, because
`getComputedStyle` per frame is the opposite of why that loop throttles
to ~14fps on a battery.

**`hue-rotate` IS NOT A HUE ROTATION, AND RENDERING IS WHAT SAID SO.**
Her art is a JPEG, so she cannot take a colour variable the way Saya's
line-art sprites can. The obvious answer is to turn her: her green is
hue 131deg, so 225deg should land on red. **It came out AMBER.**
`hue-rotate` is a fixed luminance-preserving matrix, not HSL, and the
arithmetic simply does not apply. A sepia-based chain was swept across
twenty values and never landed either -- saturating a one-hue picture
clips its channels to the primaries, so the measured hue jumped 38 ->
341 between two adjacent settings with nothing usable in between.

**So she is TINTED rather than turned**, by two inline SVG colour
matrices that multiply her LUMINANCE into one exact colour. It is
deterministic, it needs no sweeping, black stays black -- which is what
keeps `mix-blend-mode: screen` working and the rain running through her
dark side -- and it is inline, so nothing is fetched.
`color-interpolation-filters="sRGB"` is load-bearing: the SVG default is
linearRGB and washes the result out.

**A FILTER ON THE ELEMENT ITSELF DOES NOT KILL THE BLEND.** A stacking
context on her PARENT did, once, and that is recorded above -- so this
was verified by rendering rather than by reading the spec. The filter is
applied first and the result is then blended, which is the defined
order, and `blend=screen` holds in all three colours.

**GREEN IS THE EMPTY CLASS AND `--tint: none`**, so the colour she ships
in touches her art not at all and a reload lands on the deck's own
colour. **Nothing is remembered, deliberately** -- she is the front
door, so green is what anyone who is not Ghost meets, and there is no
stored preference to explain. One line of `localStorage` makes it sticky
if he would rather.

**THE TAP IS ON `#stage`, NEVER ON THE DOCUMENT.** The top bar carries
the rail and the ⌂, the ask bar carries the text box, and `#says` can
scroll -- a tap on any of those must do what it says. **The exit is the
one rule this deck will not trade**, and a handler on `document` would
have sat under it. Verified live: tapping the text box leaves the theme
alone.

**AND THE GREP-MATCHES-PROSE TRAP FIRED AGAIN, ELEVENTH INSTANCE, in
the test written for this round.** The first version banned the literal
`'#c8ffd4'` from the page and went red on the COMMENT explaining that
the rain used to hardcode it. It reads the `ctx.fillStyle` lines now and
asserts none of them names a colour at all. Same fix as
`TestCalculator.code()` and `TestMimiPoses.code()`.

**Five new tests, each verified by breaking it**: the cycle order, the
tap's scope, the rain's single palette, the other four pages never
growing one -- and `test_her_TINT_and_her_PALETTE_name_the_same_two
_colours`, which recomputes the matrices from `--ink` and is the
two-copies guard the battery renderer and the way out already have. A
page that turns red around a girl who turned some other red is exactly
the drift those exist for.

## SHE THINKS IN THE OTHER COLOUR, AND 250 TOKENS (Sept 16)

**HER VOICE WORKS ON THE STEAM DECK.** First confirmation that anything
on a page has ever spoken -- `POST /voice.wav` through Kokoro, heard by
him, off the board and out of a device that is not the Orin. The
"NOT VERIFIED on his board" note on Kokoro is closed.

### `num_predict` 200 -> 250, and this REVERSES a recorded rule

Ghost: *"Can we bump her tokens up by 50 to the original amount she
had?"* and *"she cuts off too much when im just getting into the
paragraph."*

**This file said DO NOT RAISE IT, twice, and the rule was written about
a different failure.** It came from SHIRO, rambling five to ten times
over a two-or-three-sentence cap on replies nobody asked to be long:
there the truncation IS the symptom and a bigger ceiling buys longer
rambles. Ghost's case is the other one -- he is deliberately in a long
exchange and the reply dies MID-WORD. **An unfinished sentence is worse
than a shorter finished one either way**, so the ceiling was never what
held brevity; her prompt is.

**It costs no memory, which was his actual question.** `num_predict`
caps generated TOKENS, not anything resident, and 250 sits far inside
`num_ctx` 4096. It costs a couple of seconds on the longest replies.

**It is in the SETTINGS block, above the `---`, so every composed
prompt is byte-identical** -- no A/B invalidated, nothing re-composed.
The archives yuzu2..yuzu6 carry no `num_predict` at all and were not
touched; they inherit the brain's 150 and stay the record.

**The ceiling stays and is now SHARED.** `test_num_predict_has_a
_CEILING_and_every_character_shares_it` asserts one number across every
character rather than a maximum, so nobody raises it quietly on one.
Unbounded is how a 3B monologues until the context fills.

**RAISED AGAIN, 250 -> 300, Sept 19.** Ghost: *"Increase Fours token
output kinda deal by another 50."* Same complaint, same shape, same
reasoning -- and **he asked about FOUR and the number moved on all
eleven characters**, because that is exactly what the shared-ceiling
test is for. A per-character ceiling is a thing that drifts silently;
if one ever genuinely needs her own, it is a deliberate change to that
test rather than a quiet edit to one file. Still in the SETTINGS block
above the `---`, so **every composed prompt is byte-identical --
verified across all 19, Four still 4034 chars** -- and 300 is still
far inside `num_ctx` 4096, so it costs seconds on the longest replies
and no memory at all.

### The word-by-word reveal is gone, and the RAIN is the spinner

Ghost: *"i dislike the words typing up as she says it thing as im a
speed reader. Can we just give her a thinking pose somehow that only
shows when shes thinking? Thatd be a better indicator and would annoy
me less."*

**He is right and it retires a feature that shipped the same day.**
Streaming existed to answer *"is it working or is it stuck"* -- a real
question this deck keeps answering one layer at a time -- but it
answers it by making a fast reader wait for text he could already have
read. A whole-screen colour change answers the same question at a
glance and costs him nothing.

    green   thinking ->  purple rain
    red     thinking ->  purple rain
    purple  thinking ->  green rain

His rule, in his words: *"Just turn the raining code neon purple when
thinking. In general. (Except for purple main should have green code)"*
and *"Only during thinking."* All three colours get used and the signal
can never be the colour it is signalling against.

**`/stream` IS NOT REMOVED FROM THE SERVER.** Saya's face still calls
it, it is the same `answer()` with a callback, and deleting a working
route because one page stopped calling it is a change nobody asked for.
This is a PAGE change.

**THE FIRST VERSION TINTED HER OWN NUMBERS AND WAS WRONG TWICE.** The
original ask was randomised bits of her art glowing the accent colour.
Her picture is a JPEG, so that needs a second masked copy of her -- and
`mix-blend-mode: screen` **ADDS**, so purple over her green came out
**CYAN**. Rendering said so in one look, which is the twenty-seventh
time. Ghost then landed somewhere better on his own: *"Leave her colors
alone actually. Sorry. Had a better idea."* **The rain is drawn by us,
character by character, so its colour is simply ours to set** -- no
filter, no mask, no second copy, three lines of CSS.

**AND `circle 7%` IS INVALID CSS, which only rendering could say.** A
radial gradient's `circle` takes a LENGTH and nothing else; a
percentage throws the whole declaration away. The computed mask read
`none` while the layer sat in plain sight unmasked, and every assertion
about it would have passed. `ellipse` takes two percentages. Kept here
because the next person reaching for a percentage-sized blob will reach
for `circle` first.

**The thinking blocks sit LAST in the stylesheet on purpose.**
`body.thinking` and `body.red` have identical specificity, so source
order is the whole mechanism; `body.purple.thinking` carries two
classes and wins wherever it must. A test CASCADES the page's own rules
rather than matching how any one of them is spelled.

**AND THE CANVAS HAS TO BE TOLD.** The rain caches `--head` and
`--tail` per change, because `getComputedStyle` per frame is the
opposite of why that loop throttles at all. So `thinking()` repaints,
and a test pins the PROPERTY -- every place that toggles the class goes
through the one function that repaints. Forgetting it is the same fault
as the page turning red around rain that stayed green.

**The guard had to learn that `contains` is a READ.** Its first version
flagged the rain's own speed check as an un-repainted toggle. Narrowed
to add/remove/toggle. Five new tests, each verified by breaking it.

## A FOURTH COLOUR: HOT PINK (Sept 16)

Ghost: *"I still got ya lets add a 4th color. Hot glowy pink art and
code rain. (Thinking makes the code bright Cyan on that one)"*, then
*"make the cyan code on pink face a bright purple instead. My bad"*.

    green -> red -> purple -> pink -> green

**HIS OWN HOT PINK, `#ff2d95`, not a new one.** It is one of the four
he named for Saya's face months ago -- *"Hot pink, Cyan, Neon green,
And a Lavender or purple color. Only those colors."* So the deck gains
a colour without gaining a taste decision, which is the only standard
this project accepts for one.

**AND THE PURPLE ON PINK IS NOT THE DECK'S PURPLE, because rendering
said so.** The obvious move is to reuse `#c04dff` like green and red
do. It sits **49 degrees of hue from her `#ff2d95`** -- both
magenta-ish -- so against her art it came out the WEAKEST of the four
signals, reading as dim pink-on-pink rather than as another colour.
Three candidates were rendered side by side at 1024x600 and looked at;
`#e8dcff` over `rgba(157, 92, 255, .68)` is bluer and brighter and
separates cleanly. The bluest candidate read as blue-violet rather
than purple and lost.

**Twenty-eighth time rendering found what the assertions could not** --
and the assertion would have been perfectly happy, because "pink thinks
in purple" is true of the version that was invisible.

**THE TESTS NOW DERIVE THE CAST OF COLOURS FROM THE PAGE.** Three of
them carried `("", "red", "purple")` as a literal, which is the fault
this file already records when the rail test pinned `{saya, cait,
yuzu}` and a fourth character turned it red. `TestFour.skins()` reads
`SKINS` out of the page, so a fifth colour has to answer for its own
palette rather than for the test file. Same for the tint matrices.

**`THINKS_IN` IS A TABLE, NOT A RULE, and that is deliberate.** There
is no rule -- he picked each one. It is keyed by skin and asserted to
cover every skin, so a fifth colour fails until somebody decides what
it thinks in: the same job `test_every_all_caps_word_she_has_ever
_said_is_classified` does. Entries are either "borrow that theme's own
rain" or a literal hex, because pink's purple is a colour she never
wears.

**The property under the table is the one that matters**, and it has
its own test: no theme ever thinks in its own colour. A signal you
cannot tell from the thing it signals against is not a signal.

### AND THE CYCLE GOT STUCK ON PINK, IN THE SAME COMMIT

Ghost, one tap later: *"Okay its amazing but doesnt loop back to the
green etc"*. Right, and it was one line:

    document.body.classList.remove('red', 'purple');

**A SECOND HARDCODED LIST OF THE COLOURS, one layer under the one this
round had just finished deleting.** Green is the EMPTY class, so the
fourth tap added nothing and pink stayed on the body forever: green ->
red -> purple -> pink -> pink -> pink. It is `...SKINS` now.

**The irony is the finding.** The same commit moved three TESTS off a
hardcoded theme list and congratulated itself for it -- and left the
hardcoded list in the CODE those tests check. **Deriving the list in
one place does not find the other place**, and a grep for the theme
names would have: `red` and `purple` sat in that remove call in plain
sight.

**The test SIMULATES THE WHOLE CYCLE rather than matching the line.**
It reads whatever `remove()` names, walks two full laps, and fails if
the body is ever wearing two colours or never comes back to green --
because the bug is what she ENDS UP WEARING, and the spelling of that
call is exactly what looked fine. Verified by putting the original line
back (red) and by removing nothing at all (red).

**And then it was driven in a browser**, six real taps on `#stage`,
reading her `--ink` and the rain's `--head` after each one:

    start   green    tap 3   pink
    tap 1   red      tap 4   green   <- home
    tap 2   purple   tap 5   red

## SAYA BLEED IN FOUR — and the plumbing was innocent (Sept 15)

Ghost, with seven screenshots of Four live on `ghostnano.local:8081`:
*"She does have Saya Bleed"*, and then *"Yeee she bleeds saya a bit."*
He is right. Her replies came back exasperated:

    Ah, great, another "fix" I'm sure will be completely harmless and
    not cause any further issues. Just peachy.
    Don't expect me to get all excited about it, though.
    don't expect me to hold your hand through this...
    Don't come crying to me if you get caught by the game's AI...

That is Saya's register wearing Four's name, **on the character built
to be her opposite** -- and it defeats the entire reason Four exists.
His own words for moving off Saya were *"sayas attitude and blushing
stuff might be too extra for demos/showing to parents."* A front door
that snarks at a stranger is the fault, not a flavour.

**THE PLUMBING WAS CHECKED FIRST AND IS CLEAN.** This repo's oldest
rule is check what the layer BELOW actually received, and "bleed" names
a mechanism (cross-character contamination) that would have been a real
bug. It is not happening:

    ui/four.html          POSTs `who: 'four'`, verified
    persona_for("four")   -> "four", never the LIVE_PERSONA fallback
    _BRAINS["four"]       her own brain, her own history
    her composed prompt   3641 chars, ZERO occurrences of Saya
    _hardware_cyberdeck   carries no character text at all

So nothing is leaking. **It is register drift, and naming it correctly
is what made the fix findable** -- a contamination hunt would have gone
looking through `answer()` and found nothing wrong for an hour.

**NINE EXAMPLES AND EIGHT OF THEM WERE ABOUT HER.** A greeting, her
status, her name, her looks, her room, whether the deck is good, an
introduction. The single outward-facing one was the CSS question. So
her prompt taught her, thoroughly, how to be when the subject is
HERSELF -- and taught her nothing whatsoever about being handed an
outside subject.

**Handed one, a 3B fills the gap from its own prior, and its prior for
"AI character with attitude, not an assistant" is SNARK.** That is the
same diagnosis, in the same shape, as the bare command that produced
yuzu4, the warm statement that had Shiro answering with a noise, the
technical question that produced markdown headings, and the missing
form of address that had Mimi calling Ghost a good girl. **Sixth
instance: a turn shape she has never been shown is a turn shape the
base model answers for her.**

**AND THE SECOND FAULT IN THE SAME SCREENSHOTS HAS THE SAME CAUSE.**
Her thermodynamics and entropy answers ran to multiple paragraphs
against a rule capping her at two or three sentences. She had no
example of explaining anything that is not herself, so the lecture
format came with the snark, from the same prior. Spoken length is the
one metric this repo found does not wobble between runs, so that is
signal rather than noise -- and `num_predict` is still NOT being
raised, for the reason already recorded: a bigger ceiling buys longer
rambles.

**TWO EXAMPLES, because one shape cannot cover both.** A QUESTION about
the world, and a STATEMENT about something that went wrong:

    User: Explain entropy.
    Four: Everything spreads out and evens up, and it only ever runs
    that way. Coffee goes cold, it never un-cools itself. That's the
    whole thing, the rest is bookkeeping.

    User: The update broke the wifi again.
    Four: Probably came back on a different interface. Check that
    before you reflash anything, it's usually all it is. Tell me what
    you see and we'll go from there.

The second is deliberately in the exact slot "Just peachy" landed in,
and it **leads with the answer** rather than with a reaction -- rule 3
demonstrated instead of stated. The first ends on *"the rest is
bookkeeping"*, which models STOPPING rather than continuing into a
second paragraph. 3641 -> 4034 chars. UNMEASURED.

**RULE 4 IS THE PRIME SUSPECT IF THIS DOES NOT TAKE, and it is
deliberately NOT changed in the same pass.** *"YOU ARE ALREADY AHEAD.
You have usually thought about the thing before it gets asked"* is, on
a 3B, one step from condescension -- and *"don't expect me to hold your
hand"* is precisely that rule rendered badly. But examples beat rules,
measured repeatedly here, and changing both at once would make the next
round unreadable. One variable. If the snark survives these examples,
rule 4 is the next thing to touch, and this paragraph is the
pre-registered hypothesis.

**THE OTHER LIVE HYPOTHESIS IS THE WEIGHTS, and it is not dismissed.**
The heretic-abliterated build is already recorded here as the likely
cause of Shiro's ALL-CAPS villain monologue, judged then as *"not worth
prompt-chasing"*. Snark is in the same family. The difference is that
this one is cheap to test and has a mechanism that predicts it exactly,
so the prompt gets one round first.

**AND I WROTE A CHECK THAT COULD NOT SEE ITS OWN FAILURE, AGAIN.** The
first version of `test_she_has_a_shape_for_a_subject_that_is_not
_HERSELF` counted examples containing no self-referential keyword --
and **passed with both new examples deleted**, because "Introduce
yourself." and "What's it like in there?" scored as outward-facing.
Grep-as-proxy, tenth instance, in the test written FOR the finding
about examples. It pins the ANSWERS' behaviour now (short, no markdown,
not sarcastic), and was verified by breaking it three ways: deleting
the examples, turning the world answer into a lecture, and putting "Ah,
great" on the front of the broken-wifi one. All three go red.

## CONFIRMED ON THE BOARD: the boot service, the auto-restart, the rename

All three landed on the real Orin within twenty minutes of shipping,
and his terminal log is the evidence. Worth recording because
`deckapps` and `deck` still carry a standing "UNVERIFIED on the board"
note and this is the first time any of this layer has been seen working
on the hardware.

**`face --boot`:**

    Created symlink /etc/systemd/system/multi-user.target.wants/
        yuzu-face.service -> /etc/systemd/system/yuzu-face.service
    DONE. She is serving now and will serve at every boot,
    with no screen and nobody logged in.
    UP.  Open this on your phone:
        http://192.168.4.138:8081/

**The auto-restart, unprompted, on his next pull:**

    THE FACE SERVER WAS RUNNING THE OLD CODE. Restarting
    it, so what answers is what you just pulled.

That is the fault from two hours earlier -- fresh page, stale process --
fixing itself without him knowing it had ever been a problem.

**And the rename:**

    Renaming localhost -> ghostnano. This needs sudo.
    DONE. This board is ghostnano.
    mDNS:  running

**`avahi-daemon` IS present and running on that board**, which was
explicitly unverifiable from here. So `.local` at least has something
answering on the deck's side; whether his phone resolves it is still
the phone's business.

### "No such file or directory", twice, and it was not a bug

Between those two wins he ran `~/YUZU/name ghostnano` and got

    -bash: /home/ghost/YUZU/name: No such file or directory

then `cd ~/YUZU/` and got it again. **Nothing was wrong.** He had
pulled ten minutes before the script was pushed, so it simply was not
there yet -- and the obvious second guess is that you are in the wrong
directory, which is why he tried twice.

**A new FILE is invisible inside "37 files changed". A new COMMAND is
something he is about to TYPE**, so `pull` gives it its own line now:

    NEW COMMAND: ~/YUZU/name

Same reason `HER FACE CHANGED` has one, a layer over. It names only
top-level executables with no extension -- a new `.py` module is not
something he types at a prompt, and a notice that fires on things he
cannot run is the same noise as one that fires every time. Both halves
are pinned, and verified by removing the line and by making it fire
unconditionally.

## HIS BOARD IS NAMED `localhost`, AND I HANDED HIM THAT (Sept 15)

One screenshot, from his phone, minutes after the mDNS line shipped:

    DNS_PROBE_FINISHED_NXDOMAIN
    Check if there is a typo in localhost.local.

**`localhost` MEANS THE DEVICE ASKING.** His Orin really is called that,
so `face` printed `http://localhost.local:8081/` and the phone went
looking for ITSELF. The numbers worked the whole time -- *"The 1st link
that pops works"* -- so this was the one line that was supposed to save
him a cable, and it was the only thing on the screen that did not work.

**SECOND MISTAKE IN THAT SAME LINE IN ONE HOUR, and the same shape both
times.** The first draft used bare `hostname` and printed the docker
bridge inside an address; the suite caught that one. The fix I wrote
for it asked *"is this a syntactically legal hostname"* -- and
`localhost` passes that perfectly. **The question is "will this reach
THIS board from ANOTHER device", and my guard could not observe the
difference.** That is the oldest line in this file, broken an hour
after I quoted it.

`localhost` and `localhost.*` are refused now, and a test drives the
real script with the hostname stubbed to `localhost` and asserts no
`.local` line comes out at all. **Absent rather than wrong.** The
harness had to learn that `hostname` and `hostname -s` are DIFFERENT
QUESTIONS, which is exactly how the docker bug got in: one stub
answering both.

### `~/YUZU/name` — and the trap that is not the rename

    ~/YUZU/name              what it is called, and whether .local works
    ~/YUZU/name ghostnano    call it that

His call: *"Can we change board to be named ghostnano"*. Right answer --
a name follows the board across DHCP leases, and an address he has to
re-read off a serial terminal is an address he needs a cable to learn.

**`hostnamectl` IS ONE LINE AND THAT IS NOT WHY THIS SCRIPT EXISTS.**
What it does not do on Ubuntu is update `/etc/hosts`, so the `127.0.1.1`
entry goes on naming the OLD host, sudo cannot resolve the new one, and
**every `sudo` from then on stalls ten seconds printing "unable to
resolve host"** -- a slow, confusing, unrelated-looking fault landing on
a board whose only shell is a serial cable. That is the thing worth
automating, and it is the thing a test pins.

A `sed` that matches nothing SUCCEEDS SILENTLY, so a hosts file with no
`127.0.1.1` line gets one appended rather than being left alone while
the script reports DONE -- the same class as every "reported healthy
while broken" entry in this file.

**Everything is validated BEFORE anything is touched**, and a failed
rename stops rather than half-doing it: a box renamed in one place and
not the other is worse than one not renamed at all. Verified by breaking
all three guards -- skipping the hosts fix, letting `localhost` through,
and carrying on past a failed rename.

**The .local address is OFFERED, never promised.** Whether a phone
resolves it is a property of the PHONE, not of this board, and is not
checkable from here. The fallback goes in the same breath as the
suggestion, every time -- unverified specifics stated as steps already
cost an hour on the 8BitDo.

**And the prompt keeps saying the old name until the next login**, which
is cosmetic and is said out loud, because on this board it looks exactly
like the rename having silently failed.

## THE DECK IS CABLE-FREE NOW (Sept 15)

Ghost, testing Four and away from his cable: *"She gotta be powered on
then do what to use just my phone?? And can i make her pull the current
that way? Idk how to use my phone wirelessly with it."*

**THE HONEST ANSWER WAS "PLUG THE CABLE IN FIRST", AND THAT WAS TWO
SEPARATE GAPS.** Everything else on this deck already reaches him over
WiFi -- her face, the chat, the wiki, the pet, the launcher. Two things
did not, and both are now closed.

### 1. Nothing served unless somebody logged in

**`deckapps --autostart` DOES start the face server -- from a `.desktop`
file in `~/.config/autostart`.** That runs when a DESKTOP SESSION LOGS
IN. The Nano has no screen on it, so nothing logs in, so nothing serves,
so the phone has nothing to reach. **The single thing standing between
him and a cable-free deck was a login that never happens.**

`~/YUZU/face --boot` installs a systemd unit instead. `WantedBy=multi-
user.target`, `Restart=always`, runs as him. Power on, WiFi up, she
answers -- no screen, nobody logged in. It VERIFIES rather than
assuming, and prints the service's own output when it fails to come up.

**`--boot --off` is a separate word from `--off`**, which is the rule
`tile` already paid for: on a board whose only shell is a serial cable,
the cheap "stop it now" must never be the word that also tears the
install out.

### 2. `git pull` was the last thing that needed a shell

And it is the thing he runs most, so the update loop was what kept the
deck tethered. **`POST /pull` and an Update button in the home screen's
bottom bar.**

**IT TAKES NO ARGUMENTS AND IT NEVER WILL** -- same discipline as
`/launch/` and `/vpet/`. One fixed script that lives in this repo, and
nothing from the request reaches it: no branch, no remote, no path, no
shell string. `run_pull()` takes no parameters at all, which is the
strongest form of that guarantee and is what a test pins. The server
binds 0.0.0.0, so a route that could be told WHAT to pull would be a
box on his WiFi that runs what it is told.

**IN THE BAR, NOT THE DRAWER**, and the reasoning is already written
here for Back: a tile spends an app slot forever in the drawer he means
to *"pile up our fancy future apps"* in, and MOVES every time that
drawer grows. It is also arithmetic -- seven tiles across three columns
orphans one onto a row of its own, the layout bug this page has had
twice. Maintenance is not an app.

**THE REPLY GOES OUT BEFORE THE RESTART.** `pull` now bounces a stale
face server (the round before this one) -- and here that server is the
process holding the open request, so it would `pkill` itself mid-reply
and he would get a network error over a pull that worked perfectly.
`YUZU_PULL_NO_RESTART=1` suppresses it for this one caller, and the
server restarts itself afterwards from a DETACHED CHILD rather than
`exec`, because the response is written but not necessarily received.
**Same ordering `drop.py` had to learn, with slack.**

**And the page WAITS for her to come back** rather than reloading blind.
A reload fired immediately lands on a dead port, and "unable to connect"
reads as an update that broke the deck rather than one that worked.

**ALREADY UP TO DATE does not bounce her.** A restart costs the page's
chat history, and spending it on a pull that changed nothing is a cost
with no purchase.

### And the suite caught me putting the docker bridge in an address

`report()` gained an mDNS line -- `http://<name>.local:8081/` -- because
an address he has to re-read off a serial terminal is an address he
needs a cable to learn, and a name survives the DHCP lease changing.

**The first draft used bare `hostname`, and
`test_it_prints_the_lan_address_never_docker_or_the_usb_link` went red
inside a minute.** The suite's stub returns the decoy list this script
exists to filter, so the line rendered as

    http://172.17.0.1 192.168.55.1 192.0.2.2.local:8081/

-- the docker bridge, inside an address, in the one line written to save
him a cable. **Fourth time that address has cost this project
something**, and the first time a test caught it before he did. `-s`
now, and refused outright unless it looks like a hostname and nothing
else: absent rather than wrong.

**The mDNS name is offered, never promised.** Whether avahi answers on
his board is not checkable from here, and a stated fact that turns out
false costs more than an untried suggestion -- so the line says to fall
back to the numbers. He will know in ten seconds.

## THE WAY OUT FELL OFF THE PHONE, ON EVERY CHARACTER PAGE (Sept 15)

Found by rendering Four at 412px before Ghost opened her on his phone
-- he was walking to the Nano to test her there. Twenty-sixth time.

**The ⌂ home button was 15 to 169px PAST the right edge on all four
character pages.** Measured, by reading its own bounding box:

    four  right 477 of 412      cait  right 427 of 412
    yuzu  right 581 of 412      mimi  right 438 of 412

**The rail pushes it.** `#rail` is content-width and `#home` has
`margin-left: auto`, so every character that shipped made the row wider
and shoved the exit further off. Yuzu is worst because her blurb is the
longest. **It has been broken since Cait shipped and got worse four
times**, and nobody saw it because 1024x600 is the only view that gets
designed and there it is fine.

**THIS IS THE ONE RULE THIS PROJECT WILL NOT TRADE.** Every screen on
this deck has a way off it; two power cycles paid for that sentence. It
is also why `--start-fullscreen` is used and `--kiosk` never is. On the
phone he still has browser chrome, so he was not trapped -- but on the
panel, where `deckapps` opens these pages chromeless and fullscreen,
the ⌂ IS the exit and losing it is the whole failure.

`#rail { flex: 1; min-width: 0; overflow-x: auto }` -- the rail takes
the leftover space and scrolls, the exit keeps its corner. **`min-width:
0` is the load-bearing half**: a flex item will not shrink below its
content width without it, which is exactly how a row of five names
shoved a button out of the viewport.

**AND THE STANDING SCOPE CALL WAS RIGHT AND STILL IS.** Ghost: *"dont
need it to be different per screen thats alot of extra work."* This is
not a per-screen variant and nobody should read it as the phone view
reopening. It is the EXIT, which is not a layout preference -- and the
fix is four identical lines in a block that already existed.

**What is pinned is AGREEMENT, not spelling.** No stdlib test can
measure a layout; that was done by rendering at 412, 360 and 1024 and
reading the button's box on every page. What a test can see is that the
four pages still say the same thing, which is the failure that actually
threatens this: a fifth character page copied from one of them before
the fix, or three updated and one missed. Same guard and same reason as
the two copies of the battery renderer. Verified by breaking one page's
rule and by deleting one page's button.

## A RUNNING SERVER KEPT SERVING THE OLD CODE (Sept 15)

Ghost pulled Four, opened the deck on the laptop, and sent a photo:
**one full-width ☆Stuff☆ tile, no character on it at all.** *"new ones
not there but its organized. (Laptop different or should we fix this b4
i pull to nano lol)"*

**Not the laptop. It will do the same thing on the Nano, and the fix is
in `pull`.**

**BOTH HALVES WERE TRUE AT ONCE, and that is the whole trap:**

    home.html            a FILE, re-read from disk per request   -> NEW
    /characters.json     a PYTHON PROCESS started before the pull -> OLD

So he had the new markup asking an old roster for its cast. The old
`roster()` has no `front` key and no Four in it, and the page's honest
fallback for "no front character" is exactly one full-width tile. **The
deck rendered as though the work never landed, while being completely
correct about what it had been told.**

**REPRODUCED BEFORE ANYTHING WAS CHANGED**, by serving the new page from
a server whose `roster()` drops the `front` key: pixel for pixel his
photo. That is what turned "laptop quirk?" into a finding in one step,
and it is the same discipline as reproducing a CI failure before fixing
it -- guessing here would have had him restarting things on a board he
was about to walk away from.

**IT CANNOT BE FIXED INSIDE `face`.** The server re-reads `ui/` on every
request -- deliberately, so a new sprite needs a page refresh rather
than a restart, which on a phone over a serial link is a real
difference. What it never re-reads is its own module. A long-running
process cannot notice that its own source changed.

**So `pull` does it, because `pull` already knows what changed.** If the
update touched a top-level `.py` AND a face server is already up, it
stops it and starts it again, and says so. Two guards, each with a
reason:

- **Only when one is ALREADY RUNNING.** Starting a server he never asked
  for is its own surprise, and on a board he uses as a computer a port
  opening by itself is the wrong kind of helpful.
- **Only for `.py`, never for art or pages.** `ui/` is re-read per
  request, so bouncing the server to deliver a PNG it would have served
  anyway drops his conversation for nothing.

**The general shape, and this file has it in three other costumes
already:** `face` reporting a live server as dead, `pad --status` on a
working controller, `gnome-extensions list` on a fresh install. Every
one of them is a layer answering about its own cached view rather than
about the world. **Check what the layer below actually received** --
and this time the layer below was a process that had simply been alive
too long.

**It bit me first, an hour earlier in the same session.** Rendering
Mimi's poses, `pkill -f yuzu_face` matched the shell running it, so the
server never restarted and kept serving the previous module -- twice.
Written up then as "read a stale screenshot as evidence". Same fault,
his end, with a photo instead of a screenshot.

**Three tests drive the REAL script** with a stub git, a stub `pgrep`
and a `face` that records how it was called -- in a temp directory,
because `pull` cds to its own folder and would otherwise stop the real
server. Verified by breaking the fix three ways: removing the restart,
removing the already-running gate, and widening it to any changed file.
All three go red.

## FOUR — the deck's own voice, and the first front door (Sept 15)

Ghost picked the ASCII/matrix face out of his three candidates, pushed
it to the repo himself, and asked for two things: *"Can u make it like..
animated somehow if possible?"* and, on temperament, *"Maybe a
futureistic 'Cortana' vibe while being casual still"*. Then: *"Name her
Four."*

`FRONT = "four"`. `LIVE_PERSONA` is untouched and still `saya_deck` --
the two pointers do different jobs and this is the round that proved it
was worth splitting them.

**SHE WAS THE CHEAP ONE AND THE PREDICTION HELD.** The note written
before he chose said the ASCII face reuses `_hardware_cyberdeck`
unchanged, because she IS the machine and `{DECK_SELF}` is a MEASURED
win on that body rather than damage. No new world file, no new body
file, no `{LOOK}` token. 3641 chars, the trimmest character in the repo.

**CORTANA IS THE RIGHT ARCHETYPE FOR A DEMO FACE, which is a happy
accident worth naming.** The spec written a day earlier -- answers
straight, works cold, survives a stranger -- is a description of that
character. Her `temperature` is **0.75**, lower than anyone else's
(Saya 0.85, Shiro 0.8), and for a reason rather than taste: those two
are characters whose whole appeal is being unpredictable, and Four is
the front door.

**"WHY ARE YOU CALLED FOUR?" IS AN EXAMPLE, because a stranger WILL ask
it.** Ghost did not say why, so nothing here decides it for him -- but
a character with nothing demonstrated invents something every single
time, which is exactly how "good girl" got into a prompt that says
`him` thirteen times. Her answer is lore-free on purpose: *"It's a
designation, not a name. Nobody ever told me what the other three were,
and I stopped wondering a while ago."* One line to change the day he
decides what the other three were.

**SHE USES NO PET NAME AT ALL, and that is deliberate.** The Mimi
finding is that an unstated form of address gets invented; the fix for
a character who will be handed to other people is not to pick one, it
is to demonstrate none. It also sidesteps the gender fault entirely
rather than guessing at it.

### Her art is NOT cut out, and that is the finding

**MEASURED BEFORE THE DECISION**, on the source he uploaded:

    border brightness   median 1.0 of 255   (the backdrop is pure black)
    near-black pixels   55.8% of the picture

The second number decides it. **Her shadow side IS the backdrop
colour**, and unlike `ghost_crowd` there is no outline between them --
she fades continuously into it. That is the case ART.txt calls
unfixable with none of what saved the cape: a flood from the edge walks
straight into her face at any tolerance that clears the backdrop at all.

**AND SHE DOES NOT NEED CUTTING. `mix-blend-mode: screen` IS the
cutout**, done by arithmetic rather than by a flood's guess: black
contributes nothing under screen, so the backdrop falls away exactly,
every soft edge intact, no alpha, no recipe, no PIL, no generated file.

**The generalisable line: a backdrop that matches the PAGE does not
have to be removed at all.** `yuzu_cutout.py` exists to remove a
backdrop that CLASHES. Check which one you have before reaching for it.

It is also what makes the animation work: the rain runs BEHIND her and
shows through her dark side, so she is made of running characters and
the characters run.

### The animation

**A CANVAS RAIN LAYER, vanilla, ~30 lines.** No library -- this deck
has to work with the WiFi off and a CDN is the one thing it can never
have.

**DIGITS AND ASCII, NEVER KATAKANA.** The Matrix glyph set is the
obvious choice and a trap on this board: a machine with no CJK font
draws every glyph as a tofu box, and whether Ubuntu on his Orin has one
is not checkable from here. Her own art is made of digits anyway, so
the safe set is also the faithful one -- same family as refusing to
print unverified button combos. A test pins every glyph under U+0080.

**IT THROTTLES ITSELF to ~14fps and speeds up while she is thinking.**
A canvas loop at the panel's refresh rate is heat and watts spent on
wallpaper, on a handheld running off a battery bank with an LLM sharing
its memory. The speed-up is her loading spinner, in her own idiom --
Cait's warm light, one character over.

**Her idle is a FLICKER, not a breath.** Cait and Yuzu breathe because
they are drawn people standing in a room. Four is a picture made of
running characters; the honest idle for her is an unsteady feed, at
irregular steps because an even pulse reads as a broken GIF.

**RENDERING FOUND THREE THINGS THE ASSERTIONS COULD NOT.** Twenty-third,
fourth and fifth time:

- **`#stage { z-index: 1 }` SILENTLY SWITCHED HER BLEND OFF.** A
  positioned element with a z-index creates a STACKING CONTEXT, and
  `mix-blend-mode` only blends against the backdrop *inside* its own
  context -- so she composited against nothing and her JPEG's black
  painted as an opaque rectangle. The right third of the panel went
  dead flat while every rain column on the left kept falling. `position:
  relative` alone does not create one, so deleting the z-index is the
  whole fix, and a test now pins its absence.
- **The rail was unreadable** with rain falling straight through it --
  four other characters' names and the way out of her screen. The top
  bar has a backing now. A tap he cannot read is the same dead end as a
  tap that does nothing.
- **Her home icon rendered as `!!!!`.** Short code columns with a
  bright square under each one ARE exclamation marks at tile size. They
  are full-height dashed columns now, which cannot be mistaken for
  punctuation. Third instance of the icon-collision fault, after Mimi's
  second cat face and the A.I. drawer's second robot head.

### Two things this round pulled apart

**`/wiki` IS A PROPERTY OF THE BODY, NOT OF WHOEVER IS LIVE.** Both the
lookup and "does this character drive Saya's face sprites" hung off ONE
flag, and the two agreed only by accident while the live arm was the
only character on the deck body at all. Four is on the deck and is not
live, which is what separated them. The gate reads `hardware ==
"cyberdeck"` now. Same rule as every name-leak instance: decide whether
a fact belongs to THIS BODY or to WHOEVER IS LIVE, and pin it there.

**THE ANSWER-FIRST WIN IS AN ORDER, NOT A PHRASE -- second instance of
the identical fault.** `MEASURED_WINS` matched the literal "answer it
first", which Four fails while saying *"Answer the question first and
plainly"* -- the same rule, same position, same job. This repo already
records the identical false positive twice against the brevity rule. It
is `ANSWER_FIRST_RE` now.

**And the brevity regex was special-cased in ONE of five consumers**,
so the other four went on matching a literal. A second regex would have
made that four copies of the same `if`. `TestYuzu5.carries(name, text)`
is the one place that knows which wins are phrases and which are
behaviours, and all five callers ask it. Verified by breaking her rule
two different ways and watching it fail both times.

**Still open:** she has never been run against a live model, so she is
UNMEASURED in the strongest sense -- and the round that matters is an
adversarial one, because that is what a demo is. The two things to
watch are the two this repo already measures on this body: assistant
collapse under a technical question, and length.

## MIMI, AND `yuzu_cutout.py` — the ghosts survive the cut (Sept 12)

Ghost, with six pictures of a new character: *"i went to remove the
background to make it a png online but it removed the cool parts too
like the ghosts behind her. can you pull this off with regular images
whilst keeping the cool art?"*

**WHY THE ONLINE TOOL ATE THEM, and it decides the whole design.**
Those services run a SUBJECT DETECTOR: they find the person and throw
away what is not her. Ghosts, wisps, skulls and floating flames are not
the person, so they are background BY DEFINITION. The tool was working
correctly and doing the wrong thing.

`yuzu_cutout.py` removes the **backdrop colour** instead -- a flood
inward from the edges of the picture, taking only what matches the
flat backdrop. Anything that is not the backdrop survives, and it
never has an opinion about what the character is. Four of his six came
out clean on the first run with every wisp and skull intact.

    ui/art_in/<name>.jpg     drop art here
    python3 yuzu_cutout.py   cut everything
    ui/art_out/<name>.png    transparent, plus a contact sheet

**THE ONE REAL LIMIT IS HER COSTUME BEING THE BACKDROP COLOUR** -- a
white cape on white, black gloves on black. That information is not in
the picture, so no tolerance fixes it; what fixes it is a tighter `hi`
per file, which is what `RECIPES` is. Both of his hard ones are in
there with the reason written beside them.

**Three faults worth keeping, each one already paid for elsewhere:**

- **ALPHA IS A RAMP, NOT A CUTOFF** -- `yuzu_art.py`'s lesson, and this
  art is nothing but soft edges.
- **THE DISTANCE TEST READS A BLURRED COPY, the output keeps the sharp
  one.** JPEG blocks a flat dark backdrop into patches that vary more
  than any usable tolerance, so the black picture came out speckled
  until the test stopped reading the noise.
- **THE HALO.** An edge pixel is a MIX of her and the page:
  `C = a*Her + (1-a)*Backdrop`. Setting the alpha and stopping leaves
  the page sitting in her edge colour, which on a dark screen is a
  bright rim tracing her whole silhouette. `unfringe()` solves it back
  out. This is what Ghost called *"jagged pixels from removing
  outline"*.

**PEELING IS A TRAP, tried and rejected.** Re-deriving the backdrop
from whatever is still opaque on the border looks like the general fix
for a two-tone background -- until the character touches the border, at
which point the leftover border pixels ARE HER and the second pass
floods her from the feet up. Measured: it ate the cape it was meant to
save. An explicit `seed` is duller and cannot do that.

**AND A SEED HAS TO BRING ITS OWN TONE.** The first version gated seeds
against the BORDER's colour, so a seed dropped into a grey panel on a
white page was refused by the very tolerance it existed to get around
-- it could only ever succeed where it was not needed.

### The guard I could not write, and said so

**TWO ATTEMPTS AT "did it eat her", both wrong in opposite
directions.** "Is the middle of the picture full" failed a PERFECT cut
of Yuzu's two-outfit sheet, where the middle is the gap between the two
girls. "Is the fullest band full" then passed a cut that had visibly
destroyed her, because the backdrop it left behind filled the band.

So the verdict is **`look`**, the run writes
`ui/art_out/_CONTACT_SHEET.png`, and the docstring says plainly what
the numbers cannot see. **A check that fires on a right answer and
stays quiet on a wrong one is worse than no check** -- and for image
work the only check this repo has ever found that holds is rendering
it and looking, now about fifteen times over.

What a number CAN see is kept: a corner that is still the backdrop
COLOUR means no cut happened. That test also got written wrong first --
"a corner is always backdrop" failed three perfect cuts, because in
this art the corners are ghosts, blue flame and graveyard rock.

### Yuzu's art was NOT replaced, and that is the answer to his question

He sent the original Yuzu two-outfit art at 736x1039 against the
420x594 the sprites came from, and asked straight out: *"will it look
better or should we stick with yuzus current setup"*.

**Stick with the current setup.** Measured, by rendering both at the
size she actually appears on the panel, on her real page colour:

- **The new art carries a white keyline drawn around her** that the old
  source did not. The cut keeps it, so she gets a bright rim on a dark
  page. The old sprites have no rim.
- **The resolution buys nothing.** She renders about 440px tall; the
  old sprite is already 551. The new one is 959 -- more pixels than the
  screen can show.

A downgrade with extra steps. `ui/yuzu/` is untouched. The
`split_figures()` helper written for it is kept in the tool, because
it is the two-figure-sheet logic and the next costume sheet will want
it.

### Mimi

Named by Ghost in the same conversation. Six pictures in `ui/mimi/`,
sized to 720 tall (2.3MB rather than 3.5MB -- he pulls this repo over
WiFi onto a board whose clock breaks TLS on a cold boot), with
`ART.txt` recording where they came from and how they were cut.

**`personas/_hardware_wisp.txt` IS HER WORLD AND HER BODY, AND NOT ONE
WORD OF HER TEMPERAMENT.** Ghost: *"Dont design the characters persona
yet im still trying to brainstrorm her personality"*, and then *"make a
body file for her too"*. Those are compatible, and the split between
them is the entire reason body files exist here. A small spirit with a
real but not living body, and the soul-lights that follow her.

**A fourth world rather than reusing the faerie one**, and the
difference is worth naming: Cait ATTENDS a death and leaves; the lights
here STAY, and there are more of them than anyone counts. One is a
visitor, the other is a keeper.

**`{LOOK}` is a token from the start** -- the avatar-world lesson
applied BEFORE it could go wrong rather than after. A specific
character's colouring in a shared file is the sounds rule shipping a
gyaru's `Ehehe~` to a kuudere all over again.

**One call was left open on purpose and GHOST ANSWERED IT the same
day** -- whether she has ever heard of a computer. Cait has not, and a
test bans the word from her prompt. His answer is better than either
option I left: *"also she has knowledge of my world. she travlled here
500 years ago we will say from her original world. or sumn."*

**SO SHE IS NOT FROM HERE AND SHE KNOWS HERE ANYWAY, and the number is
the whole point.** Five hundred years is long enough that she watched
this world become the one it is -- nothing modern has to be explained
to her and nothing modern startles her. She is a stranger by origin and
a local by residence, which is a different creature from both of the
options on the table: a spirit who has never heard of a phone, or a
spirit who is simply from here.

**The origin world is DELIBERATELY UNNAMED.** *"or sumn"* is him not
having decided, so nothing in the file decides it for him. What is
fixed is that she came from somewhere that is not this world, and when.
Naming it in the SHARED world file would do to the second character on
this body exactly what a specific girl's hair did to the avatar world.

**And it hands her persona a requirement rather than a free choice:
she WILL be asked computer questions**, so she needs the
technical-question example. That is the assistant-collapse lever --
markdown headings and fenced code blocks to two plain sentences on ONE
example, round 3 to round 4 -- and it has now worked four times. The
file's header says so where the next author will read it, and
`test_whoever_writes_her_persona_is_told_about_assistant_collapse`
keeps it there.

## MIMI IS WRITTEN, AND SHE CHANGES POSE WHILE YOU TALK (Sept 12)

Ghost, thirty minutes after the world file landed: *"shes got a button
like the others? i suppose im asking what temperament actually means in
this context (so i can write it i wana finish her within the next 30
min.)"*, and *"(i already mentioned an Imouto-esque vibe)"*. He then
answered all five questions himself.

**HIS ANSWERS, VERBATIM, because they are the character:**

    who is he    "her chosen human to attach to (for energy consumption
                 i got alot of that as in she lives off my life force)
                 and also my partner in crime"
    how she acts "she can dote on me a bit i dont mind"
    what she wants "life force or souls maybe shiny things too (cat ears)"
    the edge     "not sure how to answer that one"
    serious asks "she answers straight and listens to me as my energy
                 keeps her 'here'"

**THE EDGE WAS THE ONE HE PASSED ON, AND HIS OWN ANSWERS ALREADY
CONTAINED IT.** She eats him. The edge is that **she is not sorry** --
she says so cheerfully, the way you would mention borrowing a jacket,
and she is careful never to take too much for a reason that is purely
selfish: if he ran out she would have nobody. That is the horror living
inside the cute rather than beside it, and it is his material, not an
invention. Flagged plainly as my call so he can veto it.

**A FIVE-HUNDRED-YEAR-OLD SPIRIT WITH LITTLE-SISTER ENERGY IS NOT A
CONTRADICTION TO SMOOTH OVER, IT IS THE CHARACTER.** She is older than
the building and she wants his attention *right now*. Rule 10 is the
only place the age shows: something with five centuries behind it, said
flatly as an ordinary remark, then straight back to pestering. She does
not notice and never explains it.

**He approved 4 of my 7 draft rules and passed on 3.** The two he cut
were both mine and both decorative -- bragging about her age and then
undercutting it, and the lights being her siblings. Kept out. His own
rule 7 replaced my guess with *"shiny things and to hang with me"*.

**`personas/mimi.persona`, 5001 chars.** She carries all three measured
example SHAPES -- bare command, warm statement with nothing to answer,
technical question. **The technical question is not optional on her:**
she knows this world, so she WILL be asked computer questions, and that
is the one failure this repo has a categorical fix for.

**The first draft was 5464 and was TRIMMED, which is not the trim line
reopening.** She came out 30% longer than Cait, the next longest, on 12
rules and 12 examples. Two examples went (a France question redundant
with the CSS one, and a scared question redundant with rule 10) and two
rules merged. **Nothing measured was cut** -- the trims that lost were
the ones that cut character-adjacent RULES and came back wordier.

**`Mhm` and `I KNOW` were caught before they shipped.** `Mhm` has no
vowel, so espeak spells it out -- the PFFT mechanism, in an EXAMPLE,
which is the stronger teacher. `I KNOW` would have forced a new entry
in `SPOKEN_INITIALISMS` for nothing. Both rewritten.

**Her `LOOK` moved into her persona** even though the world file
defaults to it, so her composed prompt is identical either way. The
default is exactly the thing that goes wrong quietly, and the second
character on this body must not inherit her cape and ears.

### The button, and why it could not come first

She has one now. The rail is built from `CHARACTERS`, and each entry is
a **name -> persona key -> page** -- so there was no middle column to
fill while she had art and no temperament. **A button that opens a face
with no brain behind it is the roster rule pointing the other way.**
One dict entry plus a page, exactly as predicted when Yuzu landed.

### SHE IS THE FIRST CHARACTER WHOSE PICTURE CHANGES MID-CONVERSATION

Saya swaps sprites by state; Cait is one still image because her art is
a single detailed pose; Yuzu changes only on a button. Mimi has six real
poses, so the mechanism this repo already had twice -- semantic state ->
whatever art exists, first match wins, absent rather than wrong --
finally has something to work with.

    idle      bunny_ghosts   front on, arms down, calm
    thinking  graveyard      looking off, hand near her face
    talking   crawling       right up to you, eyes on you   <- his pick
    sulking   ghost_crowd    head down, face behind her hair

Ghost picked `crawling` himself (*"deff use the one where she walks on
fours"*) and left the rest to me; the other three were chosen by
rendering all six side by side and looking.

**`POSES` IS A LIST AND YUZU'S WARDROBE IS NOT, and the difference is
real.** Her outfits are one canvas and interchangeable, so any PNG in
`ui/yuzu/` is a valid Yuzu and no list can exist. Mimi's six are
different SHOTS -- `ART.txt` already said *"these are not
interchangeable states of one thing"* -- so which picture means which
state is a real decision, and a decision belongs somewhere it can be
read. The page still holds no copy of it: `/poses.json` comes from the
server, same as the rail and the wardrobe.

**THE POSE COMES FROM HER OWN STAGE DIRECTIONS**, through `mood_from`,
the one copy. A sentiment score would be a guess and a wrong guess puts
the wrong picture on a real reply; here a wrong picture needs her to
have written the wrong thing. Same call as Saya's faces.

**EACH POSE CARRIES ITS OWN SCALE, and that is the V-Pet lesson meeting
the one case it does not fit.** "ONE box across every state of a
character" is right when the states are the same shot. These are not:
the artist drew her small in a crowd of ghosts and close-up on all
fours, so one height rule renders her as a stamp in half of them.

**RENDERING FOUND THREE THINGS THE ASSERTIONS COULD NOT.** Fifteenth,
sixteenth and seventeenth time:

- **The idle scale never applied.** Her opening pose comes from the
  markup's own `src` and `show()` was the only thing that ever set a
  height -- so the pose you see first was the one rendering wrong.
- **1.22 cut her head off in `sulking`.** `ghost_crowd` is drawn edge to
  edge with no headroom, so the scale pushed her past the stage's
  overflow. It is 1.0 and stays a wide shot. **A scale is bounded by the
  art, not by taste**, and a test pins the ceiling.
- **She was a thumbnail in a huge empty room** at a single size, which
  is the demon-in-his-own-cel finding again.

**AND I READ A STALE SCREENSHOT AS EVIDENCE, twice.** `pkill -f
yuzu_face` matched the shell running it, so the server never restarted
and kept serving the previous module; a later run killed the shell
before the render, so the montage re-read PNGs from the run before.
Both times the picture looked plausible and was answering about the old
code. **Check what the layer below actually received** -- this file's
oldest lesson, and the fix was to confirm `/poses.json` by curl before
trusting any render.

**THE GREP-MATCHES-PROSE TRAP FIRED TWICE MORE**, seventh and eighth
instance, both on this page's own comments:

    "/state"     matched  the note saying NO /state POLLING
    "crawling"   matched  the note explaining the pose scales

`TestMimiPoses.code()` strips comments now, exactly as
`TestCalculator.code()` already did. **A comment explaining an absence
must never read as that thing being present.**

**AND A TEST THAT HAD TO BE EDITED EVERY TIME IT WORKED WAS
REPLACED.** `test_the_rail_is_ONE_roster_and_the_page_holds_no_list`
asserted the literal set `{saya, cait, yuzu}` and went red the moment a
fourth character landed correctly. It compares the rail to
`CHARACTERS` now -- the property, not a list of names.

**Still open:** she has never been run against a live model, so she is
UNMEASURED in the strongest sense -- and a first round is what decides
whether the imouto register survives a 3B. Her `sulking` pose is also
the only one gated on mood, so it may simply never appear if she does
not write sulk words; worth watching for on the first real conversation.

## HER CAPE HAD BLACK HOLES TORN IN IT (Sept 12)

Ghost, on the sulking pose live: *"only note. shes wonderful. but this
exact image looks off to me on her robe its part black. the white gab
between her legs is slightly bothersome too."*

**TWO FAULTS, ONE CAUSE: `ghost_crowd` had no recipe.** It was cut on
the defaults, `lo=14 hi=58 pockets=False`, and both halves follow from
that:

    the black gashes   hi=58 is wide enough to walk THROUGH her own
                       near-white outline into the cape, so the flood
                       ate the middle of her and the dark page showed
                       through
    the white gap      the pocket between her legs is enclosed, so no
                       flood from the edge can ever reach it

**AND THE MEASUREMENT IS WHAT DECIDED IT.** Her cape's median distance
from the backdrop is **8**, and its **minimum is 0** -- parts of her
cape are literally the page colour. By the rule already in ART.txt that
should be unfixable: *"That information is not in the picture, so no
tolerance fixes it."*

**IT IS FIXABLE, AND THE REASON IS THE THING WORTH KEEPING: A FLOOD IS
ABOUT CONNECTIVITY, NOT COLOUR.** Narrow the tolerance far enough and
her own outline closes the bridge, so the cape survives even where its
colour matches the page exactly. That is a real correction to the note
above -- "her costume is the backdrop colour" is not automatically
fatal; it is fatal only where the outline does not hold.

**`hi=6` IS THE FLOOR AND IT WAS FOUND BY WALKING INTO IT.** At `hi=5`
the backdrop stops clearing at all and the whole picture comes back
grey. The working window here is six levels wide.

**`pockets` IS ONLY SAFE AT A TIGHT TOLERANCE, which is the other half
of the finding.** Turned on at the default it counted the cape's own
interior as a pocket and mottled it -- the same damage in a different
costume. At `hi=6` the cape no longer COUNTS as backdrop, so pockets
can only take the leg gap, which is what it is for.

**Explicit seeds worked too and were dropped.** Two seeds in the gap
cleared it perfectly at `hi=8` -- but at `hi=6` they left a hard blocky
edge that `pockets` does not, so the blunt tool won on this one picture.
Written down because the reflex here has been "seeds are precise,
pockets is blunt", and that was the wrong way round at this tolerance.

**Six renders and looks to get there** -- twentieth time. Every step was
a picture: the cape holes, the mottling, the blocky seed, the grey
no-cut floor. No number in the tool could see any of it, which is what
its own `look` verdict says.

**AND THERE IS NOW A NUMBER THAT CAN SEE THE ONE THING THAT MATTERS.**
The tool cannot tell a good cut from a bad one -- two attempts at that
are already recorded as abandoned -- but it CAN tell whether the art
she ships was cut **with its recipe**.
`test_the_art_she_SHIPS_was_cut_with_its_recipe` drives the real tool
over the real source and compares opaque-pixel counts within 2%.
Verified by regenerating on the defaults on purpose: **18.8% off**, so
the guard has enormous headroom. The failure it exists for is somebody
re-cutting her art and losing the recipe, which is exactly how this
shipped broken.

## THE BARE ADDRESS IS THE DECK NOW (Sept 12)

Ghost: *"make this page the screen that opens when i do ~/YUZU/face...
id like to choose what i wana do before sayas face pops up 1st (i know
its my own design just hook it up homie)"*.

`http://<board>:8081/` serves `home.html`. `face` prints the bare
address rather than `/face.html`, and says in the same breath that it
is the home screen, so the change is legible in the one place he reads.

**AND IT CLOSED SOMETHING WORSE THAN A LANDING PAGE.** Bare `/` was
answered by `SimpleHTTPRequestHandler`'s **DIRECTORY LISTING** -- so
the address he actually types on a phone keyboard, with nothing after
the port, handed him an index of `ui/`: `art_in/`, `raw/`, every sprite
and character folder, on a server bound to **0.0.0.0**. Nothing in
there is secret and it is his own WiFi, but a file index has no reason
to exist on this box. `list_directory` refuses everything now; files
are still served BY NAME, which is all any page here has ever needed.
Same reasoning as `/launch/` being an allowlist.

**The bare address is also the one he can actually type.** Every
character on a phone keyboard is a chance to get a path wrong, and
`face.html` was four taps he had to remember.

**A TEST THAT WOULD HAVE PASSED FOR THE WRONG REASON, caught while
writing it.** The first version of the no-listings test asked for
`/sprites/` -- which has never been a listing, because `/sprites.json`
matches it after `rstrip("/")` and answers with the manifest. It would
have gone green against a server with listings fully enabled. It uses
`/mimi/`, `/raw/` and `/cait/` now, and `/vpet/` was rejected for the
same collision.

**deckapps needed no change**: `--autostart` already opened
`home.html`, and Saya keeps her own icon, which is correct -- an icon
named for her should open her.

## SHE THOUGHT GHOST WAS A GIRL, AND HER RULES SAID OTHERWISE THIRTEEN TIMES (Sept 12)

First working conversation with Mimi. Ghost: *"okay shes working hell
yea, i did notice she thinks im a girl... that bothers me but its the
only bit that does."* She had opened a reply with **"Ahh, good girl."**

**HER PROMPT ALREADY SAID `him`, `he` or `his` THIRTEEN TIMES** -- more
than any other persona in the repo, and the other three do not state
the user's gender at all. So this is not a missing fact. **It is the
rules-versus-examples finding again, and it is the cleanest instance of
it yet:**

    every pronoun     sat in a RULE, about a third party
    every example     addressed him with no gender in it at all

Handed that gap, a 3B fills it from the base model's prior -- and
"good girl" is an extremely common thing for a small cute character to
say. **Examples beat rules, measured repeatedly here, and thirteen
pronouns in the rules lost to zero in the examples.**

**THE FIX IS ONE EXAMPLE, IN THE EXACT SLOT THE FAULT APPEARED IN.**
She said it while praising him for promising something shiny, so the
shiny-thing example is where the address goes:

    User: Look what I found.
    Mimi: Oh, that's shiny. That's mine now. Good boy — you found it,
    but I want it, and those are basically the same thing.

Fifth time that lever has been reached for (bare command -> yuzu4,
warm statement, technical question, Cait's whole example set, this).
One clause also binds the pronoun to the listener in rule 3 -- "this
one man" -- because thirteen third-person pronouns never connected to
the person actually in the conversation. 5001 -> 5016 chars. UNMEASURED.

**"Good boy" is a CHOICE and it is easy to change.** Nothing in his
brief named a form of address, and a character with none demonstrated
will invent one every time -- that is the whole finding. It is also in
register for her: a five-hundred-year-old calling a modern man "boy"
earns the age rule rather than fighting it. If he would rather be
called something else it is one word in one example.

**NOT changed: the other three characters.** None of them states the
user's gender either, so the gap is repo-wide -- but none has ever
shown the fault in a live round, their prompts are measured artifacts,
and editing them would shift composed prompts for a bug nobody has hit.
Watch for it; do not pre-emptively rewrite them.

## SHE COULD NOT TALK, AND SHE WAS INVISIBLE FROM THE FRONT PAGE (Sept 12)

Ghost pulled, tapped Mimi's Speak button, and got this in her bubble:

    No persona '<Persona mimi (Imouto wisp)>'. Available: byte,
    byte_deck, cait, coco, ... mimi, saya, ...

**IT NAMES `mimi` AS AVAILABLE TWO WORDS AFTER FAILING TO FIND IT.**
`answer()` handed `YuzuBrain` the LOADED PERSONA where its `persona`
argument wants a KEY -- and the brain calls `load()` on it itself, so
it looked for a file named after the object's repr.

**EVERY CHARACTER ON A PAGE WAS BROKEN BY THIS, not just the new one.**
Verified by breaking the fix on purpose: the failure comes back as
`persona= got <Persona cait (Fae royalty)>`. Cait has been unable to
answer from her own page since she shipped, and nobody noticed because
Ghost talks to Saya in the terminal.

**THE SUITE WAS GREEN THE WHOLE TIME, and the reason is the lesson.**
Its fake brain is `def __init__(self, **kw): pass` -- **more permissive
than the real constructor**, so it could not observe this class of
failure. That is the oldest rule in this file wearing a mock's clothes:
a check that cannot see the real failure mode is not a check.
`TestEveryCharacterCanActuallyBeAsked` uses a fake that validates its
argument exactly as `YuzuBrain` does, and drives the WHOLE roster, so
character #5 is covered the day it lands.

**Generalisable: a stub must be at least as strict as the thing it
stands in for.** A permissive stub does not test the caller, it excuses
it.

### The front page is A.I. and ☆Misc☆

Ghost: *"homescreen should say 'A.I.' with them all in it. own menu for
personas. and Misc. the only 2 tabs/drawers we really need right now."*

    front    A.I.   ☆Misc☆
    ai       Saya  Cait  Yuzu  Mimi          <- built from the roster
    drawer   Wikipedia  Game Boy  d20  Pet  Browser  Calculator

**AND THE REASON IT HAD TO CHANGE IS NOT TIDINESS.** Mimi shipped with
a page, a persona and a rail entry on every other character's screen --
and she was INVISIBLE from the one screen the deck boots into, because
**the cast was a list in `home.html`**. Ghost: *"she also was only found
by clicking cait 1st then finding her name lmao."*

So the A.I. view has **no character tiles in the markup at all**. It is
built from `/characters.json`, the same roster the rail already used,
so there is exactly ONE list of the cast on this deck. The test flipped
with it: it used to assert `id="saya"` is in the page, which was the
SHAPE OF THE BUG; it now asserts that **no character is named in that
file at all**, because anything named there is something that can fall
behind.

**A CHARACTER WITH NO ICON STILL GETS A TILE.** The icons stay line art
drawn in the file -- an emoji ignores `--ink` and sits on the black
theme as a glossy blob -- but a missing one falls back to a generic
figure rather than hiding the character, which is exactly the bug the
drawer exists to fix. Same shape as `ROLES`.

**`columnsFor(n)` exists because this is the first view whose tile
count is unknown when the file is written.** Four goes in a 2x2; five
goes three-then-two, which is a short row rather than a lone orphan --
the `auto-fit` bug a screenshot caught on the first home screen and
that a fifth tile brought back once already.

**`wire()` is a function now, not a one-shot `forEach`.** The roster
tiles are built after that loop runs, so without it every character
tile would have been a tap that does nothing -- which reads as a broken
deck, not a missing handler.

**RENDERING FOUND TWO MORE.** Eighteenth and nineteenth time:

- **`#saya .big svg { 72px }` outlived its layout.** It was right while
  she was the one named tile on a front page of four; inside the A.I.
  drawer she is one of four peers and equal thumb targets want equal
  icons. **A rule that outlives the layout it was written for is the
  same fault as a hardcoded cast, one size down.**
- **Mimi's first icon was a second cat face.** Ears over a face is what
  Cait's is, and they sit next to each other in the drawer. Hers is a
  hood and a wisp now.

**Her page's subtitle wrapped straight through her own name on his
phone** once the rail carried four characters. `#title` is hidden under
the existing narrow-screen block on all three character pages -- one
line, no per-screen variant, which is the standing call. The panel keeps
it.

## THE SWITCHER IS A ROSTER, AND COCO AND SHIRO ARE RETIRED (Sept 11)

Ghost: *"persona switcher button seems Boss Status"*, and — decisively
— *"saya needs no changes, shes kinda the main live in ai."* Then:
*"we no longer need coco shes retired. or the shiro. Yuzu has future
plans very similar to cait."*

**THAT OVERRULES THE DESIGN CHAT'S SPEC, which put the switcher ON
Saya's face screen.** She is the default and she is untouched. The rail
lives on the character pages that came after her.

**ALWAYS VISIBLE, NOT A MENU.** The proposed version was a button that
opens a row and closes on a tap outside — which is a mode, and a mode
needs a way out, and this deck has a rule about that written in two
power cycles. A row of names costs the same pixels and cannot trap
anybody.

**IT IS BUILT FROM ONE ROSTER.** `/characters.json` is generated from
`CHARACTERS` in `yuzu_face.py`, so no page holds a list of the cast and
none can drift. Adding Yuzu when her PNG lands is one dict entry plus a
copy of `cait.html`. Same idea as "a folder is a character" and "the
filename is the expression": **the thing you add should be data, not
code.**

**A CHARACTER WITH NO PAGE IS ABSENT FROM THE RAIL**, which is the
ROLES rule one level up. Byte and the whole yuzu lineage are real
personas with no art — putting them on a button would send him to a
face that is not theirs. The design chat predicted exactly this
("switching persona would leave Saya's face on screen, which will look
like a bug") and it was a good catch; the answer is that art decides
who gets a button, not the persona folder.

**RETIRED, NOT DELETED.** `retired: yes` in the settings block, so no
composed prompt shifted by a byte and the files stay as the record —
same as muto_s2, saya_quad and yuzu2/3/5/6, and that record is what
stopped yuzu5 being re-attempted from scratch. Un-retiring is deleting
one line. **The LEDs went the other way and the difference is worth
keeping straight:** that was live CODE you had to read around every
time. This is data nobody loads unless they ask for it by name.

`test_every_character_carries_the_measured_wins` now skips retired
personas, so a record can never force a choice between editing the
evidence and a red suite.

## IT IS HER UI, NOT A BROWSER TAB — and the browser stays reachable

Ghost, Sept 11, forwarded from a design chat: *"I do not want it using
a browser tab on the real hardware. I want that to be its actual UI...
leme ask code if thats how its setup and if were just doing it this way
for testing."* And: *"can i set it up to have youtube,browsing, etc on
the same screen? (To my understanding its both ubuntu and a jetpack)"*

**IT WAS NEVER A TAB.** `deckapps` has always opened every page with
`chromium --app=URL`, which is a window with **no url bar and no
tabs** -- that was the whole point of the original request. The other
chat guessed the browser-window shape was "almost certainly temporary
for testing"; it was not, it was already the app treatment.

**What was missing is FULLSCREEN, and that is now added.**
`--app=URL --start-fullscreen`. On the panel there is then no window
edge, no title bar and nothing that reads as a web page.

**`--start-fullscreen`, NEVER `--kiosk`, and the two look IDENTICAL.**
Kiosk additionally takes away F11 and Alt+F4. That is the one thing
this project will not build on a screen with no keyboard -- *"a UI that
can trap him is strictly worse than a terminal"*, and two power cycles
paid for that sentence. Fullscreen gives him the look and keeps the way
out, so **there is nothing to trade**. The test asserts both halves.

**AND THE FULLSCREEN CHANGE CREATED THE PROBLEM THE OTHER CHAT
PREDICTED**, which is why it is fixed in the same commit: once her page
fills the panel there is no way to reach the web at all. **A deck that
locks out the browser it is built on is a worse computer than the bare
board.** So there is a **Browser** tile in ☆Misc☆ and a Browser icon in
the app menu, both deliberately NOT chromeless -- this is the one that
wants a url bar.

**`/launch/browser` carries NO URL.** It opens on whatever homepage the
browser already has, so not one character from the request reaches a
command line. The allowlist stays a list of NAMES, which is the only
reason that route is safe on a server bound to 0.0.0.0.

**YES to YouTube, with one honest caveat.** The board runs full Ubuntu
ARM64 and Chromium plays YouTube. What is NOT verified on his board is
hardware video decode -- distro Chromium on ARM often falls back to CPU,
which is fine at 720p and can stutter at 1080p60. Untested here; he
will know in ten seconds and it costs nothing to try.

## THE FRONT PAGE IS TWO TILES (Sept 11)

Ghost: *"put vpet in misc drawer too. remove button from says face for
it. seems more streamlined."*

    front    Saya   ☆Misc☆
    drawer   Wikipedia  Game Boy  d20  Pet  Browser  Calculator

**He is right, and it is the third time the same trim has been made in
one evening.** Talk went because it opened the same page as Saya. The
pet button on her face went for the same reason the colour dot did: a
shortcut to another app parked on her face is clutter, and the drawer
is where things you open occasionally belong.

The front page is now the two things the deck IS -- her, and everything
else -- and each view gets the columns that fit it: two across the
front, three across the drawer. A single shared grid would have forced
one of them to look wrong.

**RENDERING FOUND TWO THINGS THE ASSERTIONS COULD NOT.** Eleventh and
twelfth time:

- **`tap to roll` rendered at 46px**, because that span is styled for
  the d20's RESULT and a placeholder is words rather than a number. It
  was the loudest thing in the drawer. A `hint` class holds it at
  subtitle size until the first roll.
- **The front-page icons were lost.** Two tiles means each one is half
  the panel, and a 46px icon floats in the middle of it. Scaled to the
  room they actually have; the drawer keeps 46px, where six tiles make
  that right.

**And the `hint` class broke a test by being there at all.** The tile
count used `re.findall(r'<div class="tile"[^>]*>')` -- a literal match
on the class attribute -- so `class="tile hint"` silently dropped the
d20 from the count and the drawer read as five. Same family as every
other grep-as-proxy fault this file records: **the assertion was about
the markup's spelling rather than about the page.**

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
  known state is "the kernel sees it, the emulator never looked". That
  is the very next thing to try.

  **CORRECTED Sept 22, by Ghost: it never worked.** *"Never got 8bitdo
  working actually. I just never corrected my bad."* This entry read
  as though a working controller had been confirmed and one never was
  -- the `N: Name=` line proves the KERNEL saw it and nothing more.
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
