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

## WHAT I NEED FROM HIM (the design-note list)

He offered to deep-think the face art on his break. These are the
answers that actually change what gets built:

1. **How much of the screen is her?** Full-bleed face, a portrait with
   room around it, or head-and-shoulders? This decides the whole layout
   and it is the first thing to know.
2. **How many drawn states?** The five above is the ideal. **Two is
   enough to start** (open eyes / closed eyes = blinking, and that
   alone reads as alive). Say what he wants to draw, not what he thinks
   is required.
3. **Static art with effects, or drawn frames?** A single image plus
   CSS can blink, breathe, glitch and glow. Real frame animation looks
   better and is a lot more drawing. Either works; they are different
   amounts of his time.
4. **Style.** Anime portrait, pixel art, vector, CRT/scanline, glitchy?
   Reference images beat adjectives here -- if he has seen a face he
   likes, that is worth more than three paragraphs.
5. **Her palette.** NOT the chassis -- that rule stands, colours stay
   out of the repo for the case. Her FACE is character, same as Yuzu's
   hot pink living in her persona file, so a palette here is fine and
   useful.
6. **Does she look AT him?** A face that meets your eyes is a very
   different object from one gazing off. For a tsundere specifically,
   "looks away when embarrassed" is a state worth having.
7. **Passcode: ritual or real?** See above.

**None of these block each other.** Answer one and that part can be
built. The layout and the state machine can go in with placeholder
art -- coloured rectangles -- so the whole thing is testable before he
draws a line.
