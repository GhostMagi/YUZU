# Her face on the screen — design notes, NOT built

Ghost, Sept 9: *"i totally wouldnt mind booting into seeing 'Sayas
face' with a passcode screen right before it and a homescreen button on
bottom right corner of her face screen to back me to a homepage. and
her face screen could be interactive or talk toable."*

Nothing here is written yet. This is the shape of it, the decisions
that matter, and what has to come from him before art or code starts.

---

## The one big call: it should be a WEB PAGE

Not tkinter, not Qt, not a game engine. A local page served by a tiny
stdlib HTTP server, opened chromeless with `chromium --app=`.

Five reasons, and the last is the one that decides it:

- **The pattern already works here.** `deckapps` opens the wiki exactly
  this way, and `drop.py` already proves a stdlib HTTP server on this
  board.
- **Touch is free.** A 7" 1024x600 capacitive panel is a browser's
  native habitat. Every other toolkit needs touch handled by hand.
- **The art is just an image.** Swapping a face is dropping in a PNG,
  not recompiling. Animation is CSS.
- **No new dependency.** The stdlib-only property survives, which is
  the rule this whole project is built on.
- **He can SEE it before the screen arrives.** The page renders in the
  VNC session today, at the panel's real 1024x600, so the whole UI can
  be designed and reacted to weeks before the hardware lands. Nothing
  else on this list can be tried early.

Shape of it:

    deck_ui.py        stdlib server: serves the page, talks to the brain
    ui/face.html      lock -> face -> home, one page, no framework
    ui/art/*.png      her face states (his art)

## The passcode is a RITUAL, not security. Say so plainly.

A lock screen on a kiosk page stops nobody. Anyone holding the deck can
close the window, plug in a keyboard, or pull the NVMe. **Real security
is the Linux login and disk encryption**, and the lock screen must not
be allowed to feel like it replaces them.

That is not an argument against it. Waking her up on purpose is a good
ritual and it makes the deck feel like hers rather than like a laptop
running a program. Build it because it feels right, and never describe
it as protection.

**Open question for him:** is the passcode there for the FEEL of waking
her, or because someone else might pick the deck up? Those are
different designs -- the second one needs the real Linux lock behind
it, and the page is just the pretty half.

## The face should show what she is ACTUALLY doing

This is where it stops being a wallpaper. The brain already knows all
of this, so the states are real state, not decoration:

    asleep      locked. eyes closed, dim.
    idle        awake, nothing happening. blinks. breathes.
    listening   he is typing / the mic is open
    thinking    the model is generating -- THIS ONE MATTERS MOST
    talking     text is streaming out / Piper is speaking

**`thinking` is the most valuable state on the whole screen.** Every
frustration in this project's logs is "is it working or is it stuck".
A face that visibly thinks answers that question without a single word
of status text, and it is the honest version of the loading spinner
this deck has never had.

## Layout, roughly

    +------------------------------------------+
    |                                          |
    |              HER FACE                    |   1024 x 600
    |          (most of the screen)            |
    |                                          |
    |  [ what she just said, a line or two ]   |
    |                                    (o)   |  <- home, bottom right
    +------------------------------------------+

Home button bottom right, as he asked. It goes to a page of the same
apps `deckapps` installs -- Saya, Wikipedia, Game Boy -- as big touch
targets. The face IS the home screen's first citizen; everything else
is a room off it.

## What must NOT be lost

- **`quit` always works.** The chat loop cost two power cycles this
  evening. A UI that can trap him is strictly worse than a terminal,
  because there is not even a keyboard to type an exit into. Whatever
  is built, there is always a way back to a shell.
- **She stays offline.** No CDN, no web font, no remote anything. The
  page must render with the WiFi off.
- **Nothing blocks.** Same rule as `gba` and `wiki` -- if the brain is
  slow, the face keeps blinking. It never freezes and waits.

## ANSWERED, Sept 9 — and `ui/face.html` is the first draft

He came back with a spec that is better and easier than what was asked
for:

- **NOT her face.** *"anime eyes and mouth on a screen with a
  background color i can change... doesnt have to be her face i just
  like her eyeshape."*
- **Eye shape off his references** -- sharp almond, heavy dark upper
  lash line, outer corner lifted, amber iris, angled brows.
- **Static art, at least 5 expressions.**
- **Passcode is `ghost`, pure flair.** *"its more a visual message to
  not mess w my stuff... she will have the option to be locked
  physically with a key so its mostly for flair."* So the ritual
  reading was right, and there IS real security -- a physical lock on
  the case. Nothing about the lock screen needs to pretend otherwise.

**Eyes-and-mouth is a much better design than a drawn face**, and not
only because it is less work:

- **It is VECTOR, so it costs nothing and scales to any panel.** No
  image files, no asset pipeline, nothing to redraw at a new size.
- **Expressions become geometry, not artwork.** Five faces is five sets
  of path data, and a sixth is ten minutes rather than a drawing
  session.
- **It sidesteps the uncanny valley entirely.** A stylised eye pair
  reads as alive at a glance; a rendered face that is slightly wrong
  reads as dead. This is why every good robot face in the world is two
  eyes and a mouth.
- **Colour is one variable.** `--bg` and `--iris` are CSS custom
  properties, so "I want it teal today" is one line and a reload.

### `ui/face.html` — built, opens in any browser, no server

10KB, one file, **zero external references** -- no CDN, no web font, no
network. Verified by grep, because "offline" has to survive the WiFi
being off.

Five expressions, exactly as asked: **idle, happy, annoyed, talking,
asleep.** Annoyed is the tsundere default and it is the one with brows.

Three things in it that were NOT asked for and are worth keeping:

- **She blinks.** One CSS keyframe, and it is the single cheapest thing
  that makes a face look alive rather than like a wallpaper.
- **She breathes.** Six pixels of drift. Invisible until it stops --
  and then the screen looks dead, which is the point.
- **`thinking` is a MODIFIER, not an expression.** Three pulsing dots
  that layer over whatever face she is wearing, so she can think while
  annoyed. Per the note above, this is the most valuable thing on the
  screen: it answers "is it working or is it stuck" with no text.

**Tap her face to cycle expressions, tap a swatch to change the
background.** Both work with no keyboard, which is the whole point of a
touchscreen. The state buttons across the top are DEMO controls and
come out once the brain drives the face.

**To look at it:** open `ui/face.html` in the VNC session. It needs
nothing running -- no Ollama, no server, no wiki.

### Still open, and none of it blocks looking at the draft

1. **Does the eye shape read as hers?** That is the only question that
   matters right now, and it is a taste call only he can make. Every
   number is a `--variable` at the top of the file.
2. **Wiring it to the brain.** The face is static until a tiny stdlib
   server pushes state at it -- `idle` -> `thinking` -> `talking` as
   she actually generates. That is the next build.
3. **The lock screen and the home page.** Not drawn yet. The passcode
   is `ghost` and it is decoration.
4. **Boot straight into it.** Autostart, once the rest is real.
