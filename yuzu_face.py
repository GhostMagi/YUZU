#!/usr/bin/env python3
"""The sprite system behind her face.

Ghost's call, Sept 9: the hand-drawn SVG face read as MS Paint, and he
had already cropped real anime expressions into transparent PNGs. So
the art is DATA now, not code:

    ui/sprites/<name>.png      <- drop a file in, it is an expression
    python3 yuzu_face.py       <- see what it found
    ~/YUZU/face                <- serve it

**The filename IS the expression name.** No manifest to edit, no code
to touch, nothing to keep in sync -- adding `sleepy.png` adds a sleepy
face and removing it removes one. That is the whole point of him asking
for a sprite system rather than more drawing code.

Stdlib only, like everything else here except Piper.

HIS ART IS BLACK LINE WORK ON HOLES -- measured, not assumed: 92% of
`wink.png` is fully transparent and there is not ONE opaque white pixel
in it. The eye whites and the inside of her mouth are gaps, so whatever
colour is behind her shows straight through them. That is why the
background swatches work at all -- the background is doing the colouring
for free -- and it is why the page can recolour her LINE WORK by using
each sprite as a mask, which is what makes the black theme legible.
"""

import json
import os
import re
import tempfile
import time
import shutil
import subprocess
import zlib
import struct
import sys
import urllib.parse
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
UI_DIR = os.path.join(HERE, "ui")
SPRITE_DIR = os.path.join(UI_DIR, "sprites")

# PNG first because that is what he exports. SVG works identically --
# a mask does not care which one it is handed.
EXTS = (".png", ".svg", ".webp", ".gif", ".jpg", ".jpeg")

# Semantic states the BRAIN will ask for, mapped onto whatever art is
# actually present. Each role lists candidate sprite names in order of
# preference; the first one that exists wins, and a role with no art at
# all is simply absent rather than broken.
#
# This layer exists because the two vocabularies are different and
# should stay different: he names files after what the face is DOING
# ("woahshock"), and the code needs to ask for what she IS ("talking").
# Hard-coding one to the other is the name-leak bug this repo has now
# hit six times.
ROLES = {
    "idle":     ("idle", "neutral", "wink", "thinking"),
    "thinking": ("thinking",),
    "talking":  ("talking", "woahshock", "wink"),
    "happy":    ("happy", "wink"),
    "annoyed":  ("mad", "annoyed"),
    "sad":      ("cry", "sad"),
    "smug":     ("smug",),
    "shock":    ("woahshock", "shock"),
    "asleep":   ("asleep", "sleepy"),
}

# ---------------------------------------------------------------------
# HER MOOD, TAKEN FROM HER OWN WORDS.
#
# Ghost, Sept 11: *"saya never uses the cute blushing faces even when
# shes 'blushing'"*. He is right and it was not a taste problem -- it
# was a WIRING problem. The brain only ever reported idle / thinking /
# talking, and `talking` resolves to one sprite, so five of his eight
# faces could not appear no matter what she said. `mad` (the pouty
# blush) and `cry` and `smug` were dead files.
#
# The fix does NOT guess her feelings. She already writes them down:
# `[blushes]`, `[eye roll]`, `*giggles*`, `[pouts]` -- her own stage
# directions, in her own reply, which this project has spent two days
# deciding to keep rather than suppress. So the face reads what SHE
# said rather than a sentiment score somebody invented.
#
# That distinction is the whole reason this is safe to ship: a wrong
# guess would put the wrong face on a real reply, and there is no guess
# here. No stage direction, no mood, and `talking` as before.
# ---------------------------------------------------------------------

MOODS = (
    # (role, words she actually writes inside brackets or asterisks)
    ("annoyed", ("blush", "flustered", "embarrass", "pout", "huff",
                 "hmph", "annoy", "glare", "scowl", "grumbl", "mutter",
                 "eye roll", "rolls her eyes", "sulk", "tsk",
                 # exasperation, not sorrow -- see the note on `sad`
                 "sigh", "trails off", "ahem", "clears her throat")),
    ("smug",    ("smug", "smirk", "grin", "chuckl", "preen", "gloat")),
    # `sad` MEANS CRYING, and nothing softer. It used to catch "sigh",
    # "trails off" and "quiet" -- and a tsundere sighs in almost every
    # reply. Her very first live line was `*sigh* Fine, I'll talk about
    # these... annoyingly cute cats`, and `*trails off* Mochi ice
    # cream... I guess that sounds okay` is her GIVING GROUND, which is
    # the archetype at its best. Both put `cry.png` on screen -- tears
    # down her face over ice cream.
    #
    # Ghost, Sept 11: *"she 'cry faces' when she should blush"*. This
    # is that bug. A sigh is exasperation, so it belongs with annoyed,
    # and `mad.png` -- blush plus pout -- is what he confirmed he
    # wants: *"mad works for blushing looks like it. thats what i meant
    # by pouty."* Real tears need real crying words.
    ("sad",     ("cries", "crying", "sob", "sniff", "tear", "whimper",
                 "weep", "sad")),
    ("shock",   ("gasp", "startl", "shock", "jumps", "wide eye",
                 "wide-eyed", "surprise", "squeal", "yelp")),
    ("happy",   ("giggl", "laugh", "beam", "smile", "hums", "bounce",
                 "delight", "cheer", "wink")),
)


def mood_from(text):
    """The role her own stage directions ask for, or None.

    ORDER MATTERS and it is not alphabetical: a line can carry two
    directions, and the one that should win is the one that is most
    specific about how she FEELS. A tsundere who blushes AND giggles is
    blushing -- that is the whole character, and `happy` is last for
    exactly that reason."""
    if not text:
        return None
    found = [a or b for a, b in
             re.findall(r"\[([^\]]{1,80})\]|\*([^*]{1,80})\*", text.lower())]
    if not found:
        return None
    inside = " ".join(found)
    for role, words in MOODS:
        if any(word in inside for word in words):
            return role
    return None


def _png_size(path):
    """(w, h) from a PNG header, or None. Eight bytes of signature and
    an IHDR -- no decoder, no dependency."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(24)
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        return struct.unpack(">II", head[16:24])
    except Exception:
        return None


def sprites(directory=None):
    """Every expression on disk, sorted by name.

    Never raises and never returns None: a missing folder is an empty
    list, because a face with no art should say so on screen rather
    than take the page down."""
    directory = directory or SPRITE_DIR
    found = []
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return found
    for entry in names:
        stem, ext = os.path.splitext(entry)
        if ext.lower() not in EXTS or entry.startswith("."):
            continue
        if stem.endswith(".paint"):
            continue          # a generated companion, not an expression
        size = _png_size(os.path.join(directory, entry))
        found.append({
            "name": stem,
            "file": "sprites/" + entry,
            "w": size[0] if size else None,
            "h": size[1] if size else None,
        })
    return found


def outfits(directory=None):
    """Every outfit PNG in ui/yuzu/, sorted, as bare names.

    Never raises and never returns None -- same guard as sprites(). A
    missing folder is an empty list, and the page treats that as "no
    wardrobe button", not as "no Yuzu": her <img> carries a real src in
    the markup, so she is on screen before this is ever asked for.
    """
    directory = directory or OUTFIT_DIR
    found = []
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return found
    for entry in names:
        stem, ext = os.path.splitext(entry)
        if ext.lower() not in EXTS or entry.startswith("."):
            continue
        found.append(stem)
    return found


def poses(who):
    """Ordered (state, url) for a character whose picture changes, or
    [] for one whose does not.

    Never raises, and a state whose PNG is not on disk is DROPPED
    rather than served -- same rule as roles_for(): a state pointing at
    art that is not there puts the wrong picture on screen, and a
    missing picture is the more honest failure. Cait and Yuzu are
    absent from POSES entirely and get an empty list, which their pages
    read as "you are one still image", which they are.
    """
    out = []
    for state, stem, scale in POSES.get((who or "").strip().lower(), ()):
        if os.path.exists(os.path.join(UI_DIR, who, stem + ".png")):
            out.append([state, "%s/%s.png" % (who, stem), scale])
    return out


def pose_for(text):
    """Which pose a reply of hers asks for: `sulking` when she writes a
    sulk into it, `talking` otherwise.

    It reads her OWN stage directions through mood_from -- the one copy
    -- rather than guessing at her feelings. A sentiment score would be
    a guess, and a wrong guess puts the wrong picture on a real reply;
    here a wrong picture needs her to have written the wrong thing.
    """
    return "sulking" if mood_from(text) in ("annoyed", "sad") else "talking"


def roles_for(found):
    """Map semantic state -> sprite name, using only art that exists."""
    have = {s["name"] for s in found}
    resolved = {}
    for role, candidates in ROLES.items():
        for candidate in candidates:
            if candidate in have:
                resolved[role] = candidate
                break
    return resolved


def manifest(directory=None):
    found = sprites(directory)
    return {"expressions": found, "roles": roles_for(found)}


# ---------------------------------------------------------------------
# READING AND WRITING PNGs, in the stdlib.
#
# This is here so the workbench converter has something to fall back
# on when its image library is absent, and so the suite can look at what
# a sprite actually contains rather than trusting a filename. Nothing
# the deck SHOWS depends on it.
#
# THE MOUTH PAINT IS GONE. Ghost, Sept 11: "her mouth paint seems kinda
# weird still. Revert back to strictly lineart on a colored background.
# No need for tongue/teeth paint."
#
# It generated a `<name>.paint.png` companion -- white teeth, pink
# tongue, dark cavity -- found by detecting the lowest enclosed ink blob.
# Every one of those tones was a guess about art he draws himself, and
# it read as weird next to line work that is deliberately flat. The
# whole feature is deleted rather than disabled: a dead subsystem you
# still have to read around is worse than no subsystem, which is the
# same call this repo made on the LEDs. `git show` has it if the idea
# ever comes back.
#
# What replaced it costs nothing and is not a guess: the page paints
# the LINE ART itself, by using each sprite as a MASK. Ink is one CSS
# variable, so black on his four colours and neon green on black.
# ---------------------------------------------------------------------


def _unfilter(raw, w, h):
    stride, bpp = w * 4, 4
    out = bytearray()
    prev = bytearray(stride)
    pos = 0
    for _ in range(h):
        f = raw[pos]; pos += 1
        line = bytearray(raw[pos:pos + stride]); pos += stride
        for x in range(stride):
            a = line[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            if f == 1:   line[x] = (line[x] + a) & 255
            elif f == 2: line[x] = (line[x] + b) & 255
            elif f == 3: line[x] = (line[x] + ((a + b) >> 1)) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[x] = (line[x] + (a if (pa <= pb and pa <= pc)
                                      else (b if pb <= pc else c))) & 255
        out += line
        prev = line
    return bytes(out)


def read_rgba(path):
    """(w, h, bytes) for a straightforward 8-bit RGBA PNG, or None.

    Deliberately narrow: it handles what his exporter produces and
    returns None for anything else rather than guessing. A sprite this
    cannot read is still DISPLAYED -- this is a workbench convenience,
    never something the page depends on."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        i, idat, w, h = 8, b"", 0, 0
        while i < len(data):
            ln = struct.unpack(">I", data[i:i + 4])[0]
            typ = data[i + 4:i + 8]
            if typ == b"IHDR":
                w, h, depth, colour = struct.unpack(">IIBB", data[i + 8:i + 18])
                if depth != 8 or colour != 6:
                    return None
            elif typ == b"IDAT":
                idat += data[i + 8:i + 8 + ln]
            elif typ == b"IEND":
                break
            i += 12 + ln
        return w, h, _unfilter(zlib.decompress(idat), w, h)
    except Exception:
        return None


def write_rgba(path, w, h, px):
    """Minimal PNG writer. Filter 0 on every row -- zlib does the work
    and this runs once per sprite, not per frame."""
    raw = b"".join(b"\x00" + bytes(px[y * w * 4:(y + 1) * w * 4])
                   for y in range(h))

    def chunk(tag, body):
        return (struct.pack(">I", len(body)) + tag + body
                + struct.pack(">I", zlib.crc32(tag + body) & 0xffffffff))

    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n")
        fh.write(chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)))
        fh.write(chunk(b"IDAT", zlib.compress(raw, 9)))
        fh.write(chunk(b"IEND", b""))


# ---------------------------------------------------------------------
# LAUNCHING NATIVE APPS FROM THE HOME PAGE.
#
# Ghost, Sept 10: "id like home button to take me to a desktop with my
# apps and a saya button visible."
#
# A web page cannot start mGBA, so the page POSTs a NAME and this runs
# the matching script. The whole design is in one word: ALLOWLIST.
# `launch()` takes a key, looks it up in a fixed dict, and runs what is
# there. Nothing from the request reaches a shell -- no arguments, no
# path, no string interpolation. Anything looser is a local web server
# that executes what it is told, on a board sitting on his WiFi.
#
# Everything it can run is a script he could already tap in the app
# menu, so this adds a route to existing things rather than new power.
# ---------------------------------------------------------------------

TERMINALS = ("xfce4-terminal", "lxterminal", "mate-terminal",
             "gnome-terminal", "xterm")

# A PLAIN browser -- url bar, tabs, the lot. Deliberately the opposite
# of how every other page on this deck is opened.
#
# Ghost, Sept 11: "can i set it up to have youtube,browsing, etc on the
# same screen?" Yes, and it needs a door. Her home screen fills the
# panel now (`deckapps` opens it with --app= --start-fullscreen), so
# without this there is no way from her face to the web at all -- a
# deck that locks out the browser it is built on is a worse computer
# than the bare board.
BROWSERS = ("chromium", "chromium-browser", "google-chrome",
            "brave-browser", "firefox")


def _browser():
    for name in BROWSERS:
        found = shutil.which(name)
        if found:
            return found
    return None


def _terminal():
    for t in TERMINALS:
        found = shutil.which(t)
        if found:
            return found
    return None


def launchers():
    """key -> (argv, what to say, where to send the browser next).

    Built fresh each call so a terminal installed after boot is picked
    up without a restart -- and so a MISSING one is reported as missing
    rather than silently doing nothing."""
    here = HERE
    plans = {
        "gba": ([os.path.join(here, "gba")],
                "Game Boy is starting on the deck's screen.", None),
        "wiki": ([os.path.join(here, "wiki")],
                 "Wikipedia is starting.", "http://127.0.0.1:8080"),
    }
    web = _browser()
    if web:
        # NO URL ARGUMENT. It opens on whatever homepage the browser
        # already has, which means not one character from the request
        # reaches the command line -- the allowlist stays a list of
        # NAMES, which is the only reason this route is safe on a
        # server bound to 0.0.0.0.
        plans["browser"] = ([web], "Browser is opening on the deck's "
                                   "screen.", None)
    term = _terminal()
    if term:
        plans["chat"] = (
            [term, "-e", "bash", "-c",
             "cd %s && python3 yuzu_brain.py --chat; exec bash" % here],
            "She is opening in a terminal on the deck's screen.", None)
    return plans


def launch(name):
    """(ok, message, open_url). Never raises and never runs anything
    that is not in the dict."""
    plans = launchers()
    if name not in plans:
        if name == "chat":
            return (False, "No terminal emulator on this board -- "
                           "install one: sudo apt install -y xterm", None)
        if name == "browser":
            return (False, "No browser on this board -- install one: "
                           "sudo apt install -y chromium-browser", None)
        return (False, "Not a thing this deck knows how to open.", None)
    argv, said, opens = plans[name]
    if not os.path.exists(argv[0]) and not shutil.which(argv[0]):
        return (False, "%s is missing from ~/YUZU." % os.path.basename(argv[0]),
                None)
    try:
        # Detached, always. A launcher that holds this server hostage
        # would take her face down with it, and a foreground process on
        # this board has already cost two power cycles.
        subprocess.Popen(argv, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL,
                         stdin=subprocess.DEVNULL, start_new_session=True)
    except Exception as exc:
        return (False, "It would not start: %s" % exc, None)
    return (True, said, opens)


# ---------------------------------------------------------------------
# WHAT SHE IS DOING, shared between processes by a FILE.
#
# The brain and the face server are separate processes -- he starts the
# chat in his terminal and the page is served here -- so the state has to
# cross a boundary. A file is the right size for that: no socket to
# fail, no order to get right, and the brain works exactly as before
# when the face server is not running at all.
#
# `thinking` is the whole point. Every frustration in this project's log
# is "is it working or is it stuck", and a face that visibly thinks
# answers that with no status text. It is the honest version of the
# loading spinner this deck has never had.
# ---------------------------------------------------------------------

STATE_FILE = os.path.join(tempfile.gettempdir(), "yuzu-face-state")
STATES = ("idle", "thinking", "talking")


def set_state(state, said="", rate=None):
    """Say what she is doing. NEVER raises -- this is called from the
    reply path, and a face that cannot be updated must not be able to
    stop her talking.

    `rate` is tokens per second for the turn that just finished, when
    the caller happens to know it. It is carried here rather than
    measured here because only the brain sees Ollama's own numbers, and
    a rate this deck GUESSED would be worse than no rate at all."""
    if state not in STATES:
        return
    body = {"state": state, "said": said[:600], "at": time.time()}
    if rate:
        body["rate"] = round(float(rate), 1)
    # TWO QUESTIONS, TWO FIELDS. `state` is what she is DOING (the
    # honest loading spinner); `mood` is how she IS. Collapsing them
    # would mean a thinking face could never also be a blushing one,
    # and this repo has already paid for merging two questions into one
    # variable more than once.
    mood = mood_from(said)
    if mood:
        body["mood"] = mood
    try:
        with open(STATE_FILE, "w") as fh:
            json.dump(body, fh)
    except Exception:
        pass


def get_state():
    """What she is doing, and what she last said.

    A stale file means a chat that died mid-reply, so anything older
    than a couple of minutes reads as idle rather than leaving her
    frozen mid-thought forever."""
    try:
        with open(STATE_FILE) as fh:
            got = json.load(fh)
        if time.time() - got.get("at", 0) > 150:
            got["state"] = "idle"
        return got
    except Exception:
        return {"state": "idle", "said": "", "at": 0}


# ---------------------------------------------------------------------
# WHO IS TALKING.
#
# Ghost, Sept 11: "id like to have this. its own tab... seperate thing
# from saya", and separately "saya needs no changes, shes kinda the
# main live in ai."
#
# A NAME CROSSES, AND A NAME IS ALL THAT CROSSES. Same discipline as
# /launch/ and /vpet/: the page POSTs "cait", this dict turns it into a
# persona KEY, and nothing a caller sends can name a file. An unknown
# name is REFUSED rather than quietly answered by whoever is live --
# putting the wrong character on screen is the confusing kind of wrong,
# and this repo has paid for name-versus-key confusion six times.
#
# Saya's entry follows LIVE_PERSONA rather than naming her file, which
# is the same rule: decide whether a fact belongs to THIS CHARACTER or
# to WHOEVER IS LIVE, and pin it accordingly. Move LIVE_PERSONA and
# this follows; Cait does not, because Cait is Cait.
# ADDING A CHARACTER IS A DICT ENTRY AND A PAGE. No list in the HTML,
# no menu to keep in sync -- /characters.json is generated from this,
# so the rail on every character page is the same roster by
# construction. Same idea as "a folder is a character" in the V-Pet and
# "the filename is the expression" in her sprites: the thing you add
# should be data, not code.
#
# WHO IS IN HERE IS THE SWITCHER'S ROSTER, and it is deliberately NOT
# "every persona file". Ghost, Sept 11: "we no longer need coco shes
# retired. or the shiro." Coco, Shiro, Byte and the whole yuzu lineage
# are still on disk -- they are records -- and none of them belong on a
# button, because a character with no art has no page to send you to.
# That is the ROLES rule one level up: a role with no art is ABSENT
# rather than pointing at the wrong face.
#
# Yuzu came back the next day, exactly as predicted: one entry here
# plus a page shaped like Cait's. She is `yuzu_avatar`, NOT `yuzu_deck`
# -- the deck version is the record of her bodiless era, the same way
# saya_quad is of the robot one, and the whole point of the new arm is
# that she HAS a body now.
CHARACTERS = {
    # name      persona key            page          what she is
    "saya": (None,                     "face.html",  "the deck"),
    "cait": ("cait",                   "cait.html",  "king of the cats"),
    "yuzu": ("yuzu_avatar",            "yuzu.html",  "gyaru, fully dressed"),
    "mimi": ("mimi",                   "mimi.html",  "five hundred years here"),
    "four": ("four",                   "four.html",  "the deck's own voice"),
}

# MIMI IS THE FIRST CHARACTER WHOSE PICTURE CHANGES DURING A
# CONVERSATION, and this list is why it is a list.
#
# Yuzu's wardrobe is a FOLDER with no list anywhere, because her
# outfits are one canvas and interchangeable -- any PNG in ui/yuzu/ is
# a valid Yuzu. Mimi's six are different SHOTS of her, which ART.txt
# says in as many words: "these are not interchangeable states of one
# thing". A crawl cannot stand in for a bust. So the mapping from what
# she is DOING to which picture shows it is a real decision, and a
# decision belongs somewhere it can be read.
#
# It is the ROLES rule, one character over: semantic state -> whatever
# art exists, and a state whose PNG is missing is ABSENT rather than
# pointing at the wrong picture. Ghost picked `crawling` himself
# ("deff use the one where she walks on fours"); the other three were
# chosen by rendering all six side by side and looking, which is the
# only check this repo has ever found that holds for art.
# EACH POSE CARRIES ITS OWN SCALE, and that is not a fudge -- it is
# the V-Pet lesson arriving in the one situation it does not fit. "ONE
# box across every state of a character" is right when the states are
# the same shot; these are not. The artist drew her small in a crowd of
# ghosts and close-up on all fours, so one height rule renders her as a
# thumbnail in half of them. Measured at the panel's real 1024x600: at
# a single size she was a stamp in the corner for `idle` and filled the
# screen for `talking`.
#
# The numbers below were tuned by rendering and looking, which is the
# only check this repo has ever found that holds for art -- about the
# sixteenth time. They are BOUNDED BY THE ART's own headroom, not by
# taste: `ghost_crowd` is drawn edge to edge and 1.22 cut her head off
# against the stage's overflow, so it is 1.0 and stays a wide shot.
POSES = {
    "mimi": (
        # state      file            scale  why this one
        ("idle",     "bunny_ghosts",  1.12),  # front on, arms down, calm
        ("thinking", "graveyard",     1.00),  # looking off, hand at her face
        ("talking",  "crawling",      1.00),  # right up to you, eyes on you
        ("sulking",  "ghost_crowd",   1.00),  # head down, face behind hair
    ),
}

# WHO OWNS THE FRONT PAGE. Ghost, Sept 15: "maybe have 1 specific one
# take over (have yet to choose the new main, sayas attitude and blushing
# stuff might be too extra for demos/showing to parents)".
#
# ONE LINE TO MOVE, exactly like LIVE_PERSONA, and for the same reason:
# he has contenders and has not picked, so the cost of changing his mind
# has to be one word in one place.
#
# IT IS DELIBERATELY *NOT* `LIVE_PERSONA`, and that is the one variable
# doing two jobs rule again. LIVE_PERSONA is a MEASUREMENT pointer -- the
# promotion rule moves it to whichever prompt last scored best, and it
# decides what `yuzu_brain --chat` and the eval boot. This decides who
# GREETS YOU. A character can be the front door without being the arm
# under test, and the reverse.
#
# AND IT HIDES NOBODY. The front tile is who you meet first; every
# character is still two taps away under Stuff -> A.I. If the ask ever
# becomes "my mother must not find Saya", that is a different feature
# and this is not it.
FRONT = "four"

# HER WARDROBE IS A FOLDER, exactly like the V-Pet's cast and her own
# sprite set: whatever PNGs are in ui/yuzu/ ARE the outfits, and the
# filename is the name on the button. Adding one is dropping a file in,
# with no list to update here, in the page, or in her prompt.
OUTFIT_DIR = os.path.join(UI_DIR, "yuzu")

_BRAINS = {}


def persona_for(who):
    """The persona key behind a character NAME, or None if it is not a
    name this deck knows."""
    who = (who or "saya").strip().lower()
    if who not in CHARACTERS:
        return None
    import yuzu_personas
    return CHARACTERS[who][0] or yuzu_personas.LIVE_PERSONA


def roster():
    """Every character with a page, for the rail. Never raises: a
    character whose persona file has gone missing is DROPPED rather
    than taking the page down, same guard as sprites()."""
    import yuzu_personas
    out = []
    for who, (key, page, blurb) in CHARACTERS.items():
        try:
            persona = yuzu_personas.load(key or yuzu_personas.LIVE_PERSONA)
        except Exception:
            continue
        if persona.retired:
            continue
        out.append({"who": who, "name": persona.name,
                    "page": page, "blurb": blurb,
                    # The home screen reads this rather than holding a
                    # name of its own. One roster, one truth -- the same
                    # rule that stopped Mimi being invisible.
                    "front": who == FRONT})
    return out


def front_app():
    """"<Name>\t<page>\t<blurb>" for whoever `FRONT` is, or "" when it
    cannot be worked out.

    `deckapps` asks this rather than naming a character, and that is
    the whole point of it existing. Its app icon said "Saya's Face" and
    opened `face.html` long after `FRONT` moved to Four -- a hardcoded
    cast one layer out from the page, which is the Mimi bug in its
    third costume after `#saya { border-color }` and the front tile
    itself. The failure looks like the deck working.

    ABSENT RATHER THAN WRONG. An empty string means the installer skips
    that one icon; the Deck icon is built from the same roster and is
    the way in to everybody."""
    try:
        for who in roster():
            if who["front"]:
                return "%s\t%s\t%s" % (who["name"], who["page"],
                                        who["blurb"])
    except Exception:
        pass
    return ""


# WHAT THE BOARD IS DOING RIGHT NOW, as one line she can read.
#
# Four's rule 8 says she NOTICES THE MACHINE SHE LIVES ON -- "the fan,
# the heat, what is loaded, how much is left" -- and until now she had
# no data at all, so she invented a number every single time. A prompt
# rule writing a cheque the code does not cash is the same fault as a
# missing feature hiding inside a character, which this repo already
# paid for once when `/wiki` silently did nothing and read as her being
# a tsundere about it.
#
# IT GOES IN THE SYSTEM PROMPT, NOT IN A USER TURN, and that is the
# opposite call from the wiki extract -- on purpose. An encyclopedia
# extract is 700 characters of reference text and arrives as something
# HE said, because a wall of it delivered as a system message is the
# shortest path to assistant collapse. This is one short sentence about
# HERSELF, which is exactly what a system prompt is for, and it is far
# too small to teach a format.
#
# ABSENT RATHER THAN WRONG. On a phone and on the laptop there is no
# nvpmodel status and no thermal zone, so there is no line at all and
# she talks about her body the way she always did -- rather than being
# handed a confident zero.
def board_now():
    """One sentence of live board facts, or '' when there are none."""
    try:
        now = stats()
    except Exception:
        return ""
    bits = []
    # Every field is FORMATTED here rather than pasted. `watts` is a
    # float and `temp` is a whole number of degrees, and handing a 3B a
    # bare `5.6` to narrate is how you get a sentence about 5.6 of
    # something she had to guess the name of.
    if now.get("percent") is not None:
        bits.append("battery %d%%%s" % (now["percent"],
                                        ", charging" if now.get("charging") else ""))
    elif now.get("watts"):
        bits.append("drawing %.1f watts" % now["watts"])
        if now.get("hours"):
            bits.append("about %.1f hours from a full bank" % now["hours"])
    if now.get("temp"):
        bits.append("%d degrees" % now["temp"])
    if now.get("throttled"):
        # The reminder, reaching her too. She is the front door, so she
        # is the one who will be asked why the deck feels slow.
        bits.append("THROTTLED -- he needs to run: sudo nvpmodel -m 0")
    elif now.get("power"):
        bits.append("power mode %s" % now["power"])
    if now.get("rate"):
        bits.append("last reply came out at %s" % now["rate"])
    if not bits:
        return ""
    return ("\n\nRIGHT NOW, on the board you live on: "
            + ", ".join(bits) + ". "
            "Mention it only if it is relevant or you are asked -- "
            "it is the weather, not the news.")


# AND SHE KNOWS WHAT SHE IS MADE OF.
#
# Asked for her specs on the board, Sept 18, Four answered with an
# Intel XScale processor at 700MHz, 64MB of DDR, a 4GB flash card and
# a 3.5-inch 320x240 screen running Windows CE. That is a palmtop from
# about 2004, invented whole, on the character who IS the front door
# and whose whole job is surviving a stranger.
#
# SECOND INSTANCE, AND THE FIRST ONE IS ALREADY WRITTEN DOWN. Shiro
# hallucinated a custom PCB "with a little more RAM" and a dollhouse
# case, and the note filed then names this exactly: the deck
# self-concept holds for what she IS but not for what she is MADE OF,
# and nothing in her prompt names a single part.
#
# `board_now()` closed the WEATHER and its own last line says so --
# watts, degrees, power mode, "it is the weather, not the news". The ID
# CARD was never handed to her at all, so "what are your specs" is a
# turn shape she has no data for, and SIXTH INSTANCE of this repo's
# most repeated finding: a turn shape she has never been given is one
# the base model answers for her. Its prior for "specs of a small
# handheld computer" is a Windows CE palmtop, and that is what came
# out.
#
# READ, NEVER HARDCODED -- the `ghostnano` rule, one layer over. A spec
# string typed in here is right until he swaps the NVMe, and it is
# already wrong on the laptop and the phone, with the failure looking
# exactly like the deck working.
#
# CACHED, because none of this can change while the server is up and it
# rides on every single turn.
_SPECS = None


def board_specs():
    """One sentence of what this machine IS, or '' when it will not say."""
    global _SPECS
    if _SPECS is not None:
        return _SPECS
    _SPECS = ""
    bits = []

    # The board's own name for itself. device-tree is the ARM answer and
    # DMI is the x86 one; neither is assumed to be there.
    for path in ("/proc/device-tree/model",
                 "/sys/devices/virtual/dmi/id/product_name"):
        try:
            with open(path, "rb") as fh:
                name = fh.read().decode("utf-8", "replace")
            name = name.replace("\x00", "").strip()
            if name:
                bits.append(name)
                break
        except OSError:
            continue

    try:
        cores = os.cpu_count()
        if cores:
            bits.append("%d cores" % cores)
    except Exception:
        pass

    try:
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    gb = int(line.split()[1]) / (1024.0 * 1024.0)
                    # SHARED is the Orin's defining trait -- it is the
                    # whole `OLLAMA_KEEP_ALIVE` argument and the reason
                    # PC mode competes with her. It is also flatly false
                    # of the laptop's discrete card, so it rides on the
                    # Jetson check that ALREADY EXISTS TWICE and is
                    # pinned to agree, rather than becoming a third copy
                    # for the pair to drift away from.
                    shared = ""
                    try:
                        import yuzu_doctor
                        if yuzu_doctor.on_a_jetson():
                            shared = " shared between the processor and the graphics"
                    except Exception:
                        pass
                    bits.append("%.1fGB of memory%s" % (gb, shared))
                    break
    except OSError:
        pass

    try:
        st = os.statvfs("/")
        total = st.f_blocks * st.f_frsize / (1000.0 ** 3)
        free = st.f_bavail * st.f_frsize / (1000.0 ** 3)
        if total:
            bits.append("%dGB of storage with %dGB free" % (total, free))
    except OSError:
        pass

    if not bits:
        return _SPECS
    # ONE SENTENCE OF PROSE, NEVER A SPEC SHEET, and that is the same
    # call `board_now()` made for the same reason: a bulleted datasheet
    # in a system prompt is a FORMAT, and the one failure this repo has
    # a categorical fix for is her answering in markdown headings.
    #
    # And the restraint clause is positive. "Never invent different
    # numbers" would name inventing, which is the pink-elephant shape
    # measured three times here -- so it says what to DO with them.
    _SPECS = ("\n\nWHAT YOU RUN ON, really: " + ", ".join(bits) + ". "
              "Those are the true numbers for the machine you live on; "
              "bring them up when your own hardware comes up.")
    return _SPECS


# SHE REMEMBERS BETWEEN RESTARTS NOW.
#
# Every `~/YUZU/pull` bounces the face server, and until now that took
# the whole conversation with it -- she would forget his name, the deck,
# and what they were in the middle of, and the cause looked like nothing
# at all from his side.
#
# OUTSIDE THE REPO, in ~/.yuzu/, for the reason the V-Pet's mood file
# already paid for: a file INSIDE the repo is a local change, and
# `~/YUZU/pull` stops on local changes rather than overwriting them.
# Her memory of a conversation would have blocked every update he ever
# ran.
#
# It is TINY and it is capped. `history_turns` is 8, so a file is at
# most 16 short messages -- single-digit kilobytes per character, and it
# cannot creep, because the brain trims eagerly and this only ever
# writes what the brain is already holding.
MEMORY_DIR = os.path.join(os.path.expanduser("~"), ".yuzu", "history")


def _memory_file(key):
    # The key comes from CHARACTERS, never from the request -- same
    # allowlist discipline as /launch/ and /vpet/. basename is the belt
    # to that braces: nothing here can ever name a path.
    return os.path.join(MEMORY_DIR, os.path.basename(key) + ".json")


def load_memory(brain, key):
    """Give a fresh brain whatever it said last time. NEVER raises: a
    corrupt or unreadable file costs the memory, never the reply."""
    try:
        with open(_memory_file(key), encoding="utf-8") as fh:
            past = json.load(fh)
        if isinstance(past, list):
            brain.history = [m for m in past
                             if isinstance(m, dict)
                             and m.get("role") in ("user", "assistant")
                             and isinstance(m.get("content"), str)
                             ][-brain.history_turns * 2:]
    except Exception:
        pass


def save_memory(brain, key):
    """Write it back. Same guard: losing the memory must never lose the
    reply that was already given."""
    try:
        os.makedirs(MEMORY_DIR, exist_ok=True)
        with open(_memory_file(key), "w", encoding="utf-8") as fh:
            json.dump(brain.history[-brain.history_turns * 2:], fh)
    except Exception:
        pass


def forget(key):
    """Drop one character's memory. Absent is success -- this exists so
    starting clean is possible, not so it can fail."""
    brain = _BRAINS.get(key)
    if brain is not None:
        brain.reset()
    try:
        os.remove(_memory_file(key))
    except Exception:
        pass


# HER VOICE, SENT TO WHATEVER IS LOOKING AT HER.
#
# Ghost: "Finish the page audio so i can hear on steam deck."
#
# THE BOARD IS NOT WHERE THE SPEAKER IS. `yuzu_voice.say()` plays on the
# machine running the module -- the Orin -- and the Orin has no speaker
# on it yet (the USB sound card is in the parts list, not bought). Every
# device he actually looks at ALREADY has speakers: the Steam Deck, his
# phone, the laptop. So the audio has to TRAVEL, which is why
# `yuzu_voice.render()` exists beside `say()`.
#
# THE VOICE IS CACHED PER SPEED, and that is not a micro-optimisation.
# Kokoro loads a ~310MB model; building one per request would make her
# slower than Piper rather than nicer than it, and on a board with ONE
# pool of 8GB it would thrash. Piper is cheap to build but re-runs
# `piper --help` for flag detection, which is also not free per reply.
_VOICES = {}


def voice_for(key):
    """The voice a character speaks in, built once. None if the module
    is absent -- the same guard Piper, the wiki and the face all carry:
    a missing voice costs the AUDIO, never the reply."""
    try:
        import yuzu_voice
    except Exception:
        return None
    # HER OWN SPEED, from her own persona file. `piper_length_scale`
    # has been in every persona since the format was written, and
    # KokoroVoice INVERTS it because Piper's is a duration and Kokoro's
    # is a rate -- handled there, not here.
    scale = None
    try:
        import yuzu_personas
        scale = yuzu_personas.load(key).settings.get("piper_length_scale")
        scale = float(scale) if scale else None
    except Exception:
        pass
    if key not in _VOICES:
        try:
            _VOICES[key] = yuzu_voice.pick_voice(length_scale=scale)
        except Exception:
            _VOICES[key] = None
    return _VOICES[key]


def voice_wav(text, who="saya"):
    """(wav_bytes, error). The caller gets audio or a sentence, never
    an exception -- a speaker that fails must not take the page with
    it, which is the promise every nicety on this deck makes."""
    key = persona_for(who)
    if key is None:
        return None, "This deck has no character by that name."
    voice = voice_for(key)
    if voice is None:
        return None, "The voice module is not here."
    if not voice.ready:
        return None, voice.why_not()
    try:
        import yuzu_voice
        # STAGE DIRECTIONS ARE STRIPPED, the same call the bubble and
        # the terminal both make. `*leans in*` read out loud is the
        # word "leans" in the middle of a sentence -- measured, and the
        # whole reason strip_stage_directions exists.
        wav = voice.render(yuzu_voice.strip_stage_directions(text))
        if not wav:
            return None, "She could not say that. (%s)" % (
                voice.failures[-1][1][0] if voice.failures else "no audio")
        try:
            with open(wav, "rb") as fh:
                return fh.read(), None
        finally:
            yuzu_voice._drop(wav)
    except Exception as exc:
        return None, str(exc)


def answer(text, who="saya", on_chunk=None):
    """One turn with a character, for the page. (reply, error).

    The chat lives in a terminal today, which on a 10" touchscreen with
    no keyboard is the weakest part of the whole deck. This is the same
    brain, reached from the same box.

    NOTE: each character keeps its OWN conversation, and all of them
    are separate from a terminal chat running at the same time. Several
    mouths, one model -- and the model is loaded once, so a second
    character costs history, not RAM."""
    try:
        import yuzu_brain
    except Exception as exc:
        return None, "The brain is not importable here (%s)." % exc

    key = persona_for(who)
    if key is None:
        return None, "This deck has no character by that name."
    # `/wiki cats` HAS TO WORK HERE TOO. It was written into the
    # terminal loop and this page was built afterwards, so for two days
    # the chat bar under her face took the literal string and handed it
    # to her as ordinary conversation -- she answered about "wiki cats"
    # out of her own head and Ghost, fairly, read it as her being a
    # tsundere about it. A missing feature that looks like a
    # personality is the worst shape this bug has taken yet.
    #
    # yuzu_brain.ground() is the ONE copy. Calling it rather than
    # repeating it is what stops there being a third place to forget.
    # ONLY THE FACE CHARACTER DRIVES THE FACE. Saya's page polls /state
    # to pick her expression, and that file is hers -- if Cait wrote to
    # it, talking to Cait would make Saya's face light up in another
    # window. Cait's page needs no state at all: its own fetch is in
    # flight while she thinks, so it already knows.
    drives_face = (key == persona_for("saya"))

    # AND `/wiki` IS A SEPARATE QUESTION FROM THAT, which it was not
    # until Four landed. Both used to hang off `drives_face`, and the
    # two only agreed by accident while the live deck arm was the only
    # character on the deck body at all.
    #
    # THE ENCYCLOPEDIA BELONGS TO THE BODY. A deck has a ZIM on its
    # disk; a cat of the Otherworld does not, and a lookup arriving as
    # "I looked up X and it says: <700 chars of encyclopedia>" is the
    # shortest path to assistant collapse on a character who has never
    # heard of one. So the gate reads the HARDWARE -- which is exactly
    # the split this repo keeps paying for: decide whether a fact
    # belongs to WHOEVER IS LIVE or to THIS BODY, and pin it there.
    # IMPORTED HERE, AND THAT IS A BUG FIX RATHER THAN TIDYING.
    # `yuzu_personas` is imported INSIDE persona_for() and roster(), so
    # it was never a global of this module -- and this line referenced
    # it anyway. Every call raised NameError, the `except` below caught
    # it, and `has_wiki` silently fell back to `drives_face`. So the
    # gate CLAUDE.md records as "reads the hardware now" has been
    # answering `key == saya_deck` since the day it was written, and
    # /wiki has been DEAD on Four's page since she shipped -- the one
    # character whose body is the deck and who most needed it.
    #
    # It was invisible because the fallback is plausible: Saya is the
    # live arm AND on the deck, so the wrong answer agreed with the
    # right one for the only character anybody tested. Found by adding
    # board_now() and watching its line not arrive.
    #
    # A bare `except Exception` around a lookup will swallow a
    # programming error as happily as a missing file. That is the same
    # shape as every "reported healthy while broken" entry in
    # CLAUDE.md, and the reason the test below drives the real
    # function rather than reading it.
    import yuzu_personas
    try:
        has_wiki = yuzu_personas.load(key).hardware == "cyberdeck"
    except Exception:
        has_wiki = drives_face

    def face(*args, **kw):
        if drives_face:
            set_state(*args, **kw)

    # /wiki IS A DECK FEATURE AND STAYS ON THE DECK. Ghost, of Cait:
    # "Doesnt need access to wiki this is more of a personal RP one."
    # It is also the right call for her register -- the lookup arrives
    # as a user turn saying "I looked up X and it says: <700 chars of
    # encyclopedia>", which is the shortest path to assistant collapse
    # on a character who has never heard of an encyclopedia.
    problem = None
    if has_wiki:
        text, problem = yuzu_brain.ground(text)
    if problem:
        # The VERDICT, in the bubble, where he is already looking --
        # not silence, and not a sentence she never said.
        face("idle")
        return "(%s)" % problem, None
    try:
        if key not in _BRAINS:
            # A KEY, NOT A PERSONA OBJECT. YuzuBrain's `persona`
            # argument is "key from personas/" and it calls load() on
            # it itself -- so handing it the loaded object made the
            # brain look for a file named after the object's repr and
            # fail with `No persona '<Persona mimi (Imouto wisp)>'`,
            # which lists `mimi` as available two words later. Ghost
            # hit it the moment he tapped Speak.
            #
            # EVERY CHARACTER ON A PAGE WAS BROKEN BY THIS, not just
            # the new one, and the suite was green the whole time
            # because its fake brain accepts anything at all. A stub
            # that is more permissive than the real thing cannot
            # observe this class of failure -- the oldest lesson in
            # this repo, wearing a mock's clothes.
            _BRAINS[key] = yuzu_brain.YuzuBrain(persona=key)
            # Whatever she said last time, before she says anything new.
            load_memory(_BRAINS[key], key)
        brain = _BRAINS[key]

        # THE LIVE BOARD FACTS RIDE ON THE SYSTEM PROMPT, FOR THIS TURN
        # ONLY. `base` is captured once per brain so this can never
        # stack -- appending to an already-appended prompt would grow a
        # line of stale readings on every single turn, which is the
        # shape of bug that stays invisible until the context fills up.
        # GUARDED, because the board facts are a NICETY and the reply is
        # the product -- the same promise `_face()`, Piper and the wiki
        # import all make. Four pre-existing tests went red when this
        # was not guarded: their stub brains carry no `system_prompt`,
        # and a telemetry line that can take a whole turn down is a
        # worse fault than one that quietly does not appear.
        if has_wiki:
            try:
                if not hasattr(brain, "_base_prompt"):
                    brain._base_prompt = brain.system_prompt
                brain.system_prompt = brain._base_prompt + board_specs() + board_now()
            except Exception:
                pass

        face("thinking")
        if on_chunk is None:
            reply = brain.ask(text)
        else:
            # ONE FUNCTION, TWO TRANSPORTS. The wiki grounding, the
            # allowlist, the face state and the memory all live here and
            # nowhere else -- duplicating this for the streaming route
            # would only have created a second place to forget, which is
            # exactly what `ground()` exists to prevent one layer down.
            pieces = []
            for piece in brain.ask_stream(text):
                pieces.append(piece)
                on_chunk(piece)
            reply = "".join(pieces).strip()
        # The brain already wrote `talking` WITH the token rate it just
        # measured. Re-stating it here without one would blank the
        # badge on every reply that came through this page.
        face("talking", reply, get_state().get("rate"))
        save_memory(brain, key)
        return reply, None
    except Exception as exc:
        face("idle")
        return None, str(exc)


# ---------------------------------------------------------------------
# TELEMETRY -- what the board is actually doing, under her chin.
#
# Ghost picked this off a hardware pass: power mode, temperature, and
# how fast she is generating. It earns its pixels for one reason above
# the rest: **the Orin ships throttled and forgetting `nvpmodel -m 0`
# makes everything slow with no visible cause.** That reminder already
# lives in the README, the doctor and the boot line; this is the first
# place it can be seen WITHOUT running anything, on the screen he is
# already looking at.
#
# Every field is optional and ABSENT rather than wrong. On his phone or
# a laptop there is no nvpmodel status and no thermal zone, so the chip
# does not appear at all -- an empty badge saying nothing is the same
# fault as `pad --status` reporting on layers around the answer.
# ---------------------------------------------------------------------

THERMAL = "/sys/class/thermal"


def power_mode():
    """(number, name) from nvpmodel's own status file, or None.

    Reads the FILE rather than shelling out to `nvpmodel -q`: no sudo,
    nothing that can hang, and this is served to a page that polls."""
    try:
        with open("/var/lib/nvpmodel/status") as fh:
            raw = fh.read()
    except Exception:
        return None
    for token in raw.split():
        if token.startswith("pmode:"):
            try:
                mode = int(token.split(":", 1)[1])
            except ValueError:
                return None
            return (mode, "MAXN" if mode == 0 else "mode %d" % mode)
    return None


def temperature():
    """Hottest named thermal zone in whole degrees C, or None.

    The hottest is the honest one: the Orin exposes CPU, GPU and SOC
    zones and the number worth showing on a handheld is whichever is
    closest to throttling."""
    best = None
    try:
        zones = sorted(os.listdir(THERMAL))
    except Exception:
        return None
    for zone in zones:
        if not zone.startswith("thermal_zone"):
            continue
        try:
            with open(os.path.join(THERMAL, zone, "temp")) as fh:
                milli = int(fh.read().strip())
        except Exception:
            continue
        # Some zones report an unpopulated -256000. Ignore nonsense
        # rather than showing a confidently wrong minus number.
        if milli <= 0 or milli > 150000:
            continue
        best = max(best or 0, milli // 1000)
    return best


# ---------------------------------------------------------------------
# THE BATTERY, and the honest version of it.
#
# Ghost's little brother's idea, and it is a good one -- a handheld with
# no charge indicator is a handheld you cannot plan around. The problem
# is that **the deck has nothing to ask.** The power path is
#
#     USB-C PD bank  ->  PD-to-barrel cable  ->  5.5x2.5mm jack
#
# and a barrel jack carries volts and nothing else. No data line, no
# fuel gauge, no state of charge. The devkit has no battery management
# chip either. So a percentage would be a NUMBER THIS DECK INVENTED,
# which is the one thing this project refuses to put on a screen.
#
# What is real, in order of preference:
#
#   1. A battery node in /sys/class/power_supply. There is none today,
#      but a UPS HAT or any bank that speaks over a DATA link appears
#      here, and then the percentage is the kernel's, not ours. This
#      lights up the day he adds one, with no code change.
#   2. The Jetson's own INA3221 rail monitor, via hwmon. That is
#      WATTS BEING DRAWN RIGHT NOW -- measured, on the board, today --
#      and on a handheld it is arguably the more useful number: it is
#      the difference between "idle" and "she is generating at MAXN".
#   3. Nothing. Then nothing is shown.
#
# The runtime figure is `~Nh/full` and the wording is deliberate: it is
# hours FROM A FULL BANK at the draw measured this second, not hours
# remaining -- because remaining needs a state of charge nothing here
# can see. Labelling it "remaining" would be the confident lie.
# ---------------------------------------------------------------------

POWER_SUPPLY = "/sys/class/power_supply"
HWMON = "/sys/class/hwmon"

# His locked spec: JSAUX 20,000mAh 65W PD bank. Cells are nominally
# 3.7V, so 20Ah x 3.7V = 74Wh on the label. What reaches the board is
# less -- the bank boosts to 20V, the cable bucks to 12V, and neither
# is free. 0.8 is the usual real-world figure for that chain.
BANK_WH = float(os.environ.get("YUZU_BANK_WH", "74"))
BANK_EFFICIENCY = 0.8

# What the Jetson calls its INPUT rail, in order of preference. VDD_IN
# is the whole board on Orin; the others are what older Jetsons and some
# kernels call the same thing.
#
# VDD_GPU_SOC IS DELIBERATELY NOT HERE, and it was, for one commit. It
# is a SUB-rail -- the GPU and SOC block, which sits INSIDE VDD_IN -- so
# reading it would report part of the board as the whole board and make
# every runtime estimate too optimistic. The first version's own
# docstring said "the GPU rail is inside VDD_IN" while the list it
# guarded contained the GPU rail.
INPUT_RAILS = ("VDD_IN", "VDD_SYS_IN", "POM_5V_IN")


def battery():
    """(percent, charging) from a REAL battery node, or None.

    Nothing on the board reports one today. This exists so that the day
    he adds a UPS HAT or a bank with a data link, the indicator simply
    appears -- and so that until then it is ABSENT rather than made up."""
    try:
        names = sorted(os.listdir(POWER_SUPPLY))
    except Exception:
        return None
    for name in names:
        node = os.path.join(POWER_SUPPLY, name)

        def field(what):
            try:
                with open(os.path.join(node, what)) as fh:
                    return fh.read().strip()
            except Exception:
                return None

        if (field("type") or "").lower() != "battery":
            continue
        raw = field("capacity")
        if raw is None:
            continue
        try:
            percent = int(raw)
        except ValueError:
            continue
        status = (field("status") or "").lower()
        return (max(0, min(100, percent)), status in ("charging", "full"))
    return None


def input_rail():
    """(label, watts) for the board's whole-input rail, or None.

    The Jetson carries INA3221 monitors and exposes them through hwmon.
    Two shapes exist: some kernels give `power1_input` in microwatts,
    others give millivolts and milliamps to multiply. Both are handled.

    EVERY candidate is collected before one is chosen, and the choice is
    by the PRIORITY in INPUT_RAILS rather than by whichever channel came
    first. A board that lists a sub-rail on a lower channel number than
    VDD_IN would otherwise report part of itself as the whole, and the
    number would look perfectly reasonable while being wrong -- which is
    this repo's most common shape of bug.

    CONFIRMED on the real Orin, Sept 11: `deck --check` reported
    `5.6W now` at idle with a desktop up. The reading works; the rail it
    picks is what this function has to get right."""
    found = {}
    try:
        boxes = sorted(os.listdir(HWMON))
    except Exception:
        return None
    for box in boxes:
        node = os.path.join(HWMON, box)

        def field(what):
            try:
                with open(os.path.join(node, what)) as fh:
                    return fh.read().strip()
            except Exception:
                return None

        for channel in range(0, 8):
            label = field("in%d_label" % channel) or field("curr%d_label" % channel)
            if not label:
                continue
            label = label.strip().upper()
            if label not in INPUT_RAILS or label in found:
                continue
            watts = None
            micro = field("power%d_input" % channel)
            if micro:
                try:
                    watts = int(micro) / 1e6
                except ValueError:
                    watts = None
            if watts is None:
                milli_v = field("in%d_input" % channel)
                milli_a = field("curr%d_input" % channel)
                if milli_v and milli_a:
                    try:
                        watts = int(milli_v) * int(milli_a) / 1e6
                    except ValueError:
                        watts = None
            if watts:
                found[label] = round(watts, 1)
    for name in INPUT_RAILS:
        if name in found:
            return (name, found[name])
    return None


def power_draw():
    """Watts on the input rail, or None."""
    rail = input_rail()
    return rail[1] if rail else None


def charge():
    """What the battery indicator can honestly say, or {}."""
    real = battery()
    if real:
        return {"percent": real[0], "charging": real[1]}
    watts = power_draw()
    if not watts:
        return {}
    out = {"watts": watts}
    # Hours FROM FULL, never "remaining" -- see the note above.
    if BANK_WH > 0:
        out["hours"] = round(BANK_WH * BANK_EFFICIENCY / watts, 1)
    return out


def stats():
    """Everything the badge can say, with absent fields simply missing."""
    out = {}
    mode = power_mode()
    if mode:
        out["power"] = mode[1]
        # The whole reason this badge exists. A number he has to
        # interpret is a number he will ignore.
        if mode[0] != 0:
            out["throttled"] = "THROTTLED -- sudo nvpmodel -m 0"
    temp = temperature()
    if temp:
        out["temp"] = temp
    rate = get_state().get("rate")
    if rate:
        out["rate"] = rate
    out.update(charge())
    return out


# The pet is a NICETY, exactly like the face: a missing or broken
# yuzu_vpet.py must never be able to stop her talking, so the import is
# guarded the same way Piper's and the wiki's are.
def _pet_look():
    try:
        import yuzu_vpet
        return yuzu_vpet.look()
    except Exception as exc:
        return {"frames": {}, "says": "The pet module is not here (%s)." % exc}


def _pet_do(action):
    try:
        import yuzu_vpet
        got = yuzu_vpet.do(action)
        return got or {"ok": False, "says": "He does not know how to do that."}
    except Exception as exc:
        return {"frames": {}, "says": "The pet module is not here (%s)." % exc}




class _Handler(SimpleHTTPRequestHandler):
    """Static files out of ui/, plus one generated endpoint.

    `/sprites.json` is rebuilt PER REQUEST, so dropping a new PNG in
    the folder needs a page refresh and not a server restart. On a
    phone over a serial link, "restart the server" is a much bigger ask
    than it sounds."""

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=UI_DIR, **kw)

    # THE FRONT DOOR IS THE HOME SCREEN. Ghost, Sept 12: "id like to
    # choose what i wana do before sayas face pops up 1st".
    #
    # It also closes something worse than a landing page. Bare `/` was
    # answered by SimpleHTTPRequestHandler's DIRECTORY LISTING, so the
    # address he actually types on his phone -- 192.168.4.138:8081 with
    # no path -- gave him an index of ui/ with art_in/, raw/ and every
    # sprite folder in it, on a server bound to 0.0.0.0. Nothing there
    # is secret, and a file index is still not a thing to serve to his
    # whole WiFi.
    LANDING = "home.html"

    def do_GET(self):
        if self.path.split("?")[0] in ("/", "/index.html"):
            self.path = "/" + self.LANDING
        if self.path.split("?")[0].rstrip("/") == "/state":
            self._json(get_state())
            return
        if self.path.split("?")[0].rstrip("/") == "/stats":
            self._json(stats())
            return
        if self.path.split("?")[0].rstrip("/") in ("/characters.json",
                                                   "/characters"):
            self._json(roster())
            return
        # Regenerated PER REQUEST, same as /sprites.json: a new outfit
        # is a PNG dropped in ui/yuzu/ and a page refresh, never a
        # server restart. On a phone over a serial link that is a much
        # bigger difference than it sounds.
        if self.path.split("?")[0].rstrip("/") in ("/outfits.json", "/outfits"):
            self._json(outfits())
            return
        # Regenerated per request like the rest. `who` is a NAME and it
        # is looked up in POSES, so nothing in the query string can ever
        # reach a path -- same allowlist discipline as /launch/.
        if self.path.split("?")[0].rstrip("/") in ("/poses.json", "/poses"):
            query = urllib.parse.parse_qs(
                urllib.parse.urlparse(self.path).query)
            self._json(poses((query.get("who") or [""])[0]))
            return
        if self.path.split("?")[0].rstrip("/") in ("/vpet.json", "/vpet"):
            self._json(_pet_look())
            return
        if self.path.split("?")[0].rstrip("/") in ("/sprites.json", "/sprites"):
            body = json.dumps(manifest(), indent=1).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)
            return
        return super().do_GET()

    def list_directory(self, path):
        """No directory listings, anywhere.

        `/` is the home screen above; every other folder under ui/ is
        art this deck reads by name and nobody browses. A listing is
        not a security hole here so much as a thing that has no reason
        to exist on a box sitting on his WiFi -- the same reasoning as
        `/launch/` being an allowlist of NAMES."""
        self.send_error(404, "File not found")
        return None

    def _json(self, obj, code=200):
        # `code` so a route can say 503 and mean it. /voice.wav needs
        # the page to tell "she has no voice installed" apart from "the
        # deck is not answering", and a 200 carrying a sad sentence
        # cannot -- absent rather than wrong, one layer down.
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/")
        if path.startswith("/vpet/"):
            # Same allowlist discipline as /launch/: a NAME crosses and
            # nothing else. yuzu_vpet.do() refuses anything not in its
            # own tuple, so this route cannot grow a hole by accident.
            self._json(_pet_do(path[len("/vpet/"):]))
            return
        if path == "/say":
            try:
                size = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(size) or b"{}")
                said = body.get("text", "")
                who = body.get("who", "saya")
            except Exception:
                said = who = ""
            said = said.strip()[:2000]
            if not said:
                self._json({"ok": False, "said": "Say something first."})
                return
            # `who` is a NAME and gets looked up in CHARACTERS. Nothing
            # from the request reaches a path or a command.
            reply, error = answer(said, who)
            self._json({"ok": error is None, "said": reply or error,
                        "pose": pose_for(reply) if error is None else "idle"})
            return
        if path == "/stream":
            # SHE ARRIVES A WORD AT A TIME. A 3B on this board takes ten
            # to thirty seconds for a reply, and until now the page sat
            # dead silent for all of it and then dumped the whole thing
            # -- which is the "is it working or is it stuck" question
            # this whole project keeps answering, one layer at a time.
            #
            # NEWLINE-DELIMITED JSON, not SSE. Each line is one object,
            # the browser splits on \n, and there is no framing to get
            # wrong and no event names to keep in sync. The last line
            # carries the verdict, so a reply that dies halfway is
            # visibly unfinished rather than quietly truncated.
            #
            # It works because the server is THREADED -- already true,
            # and for this exact reason: a single-threaded server stops
            # answering /state for the whole generation, so her face
            # would freeze precisely when it is saying `thinking`.
            try:
                size = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(size) or b"{}")
                said = (body.get("text") or "").strip()[:2000]
                who = body.get("who", "saya")
            except Exception:
                said = who = ""
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.send_header("Cache-Control", "no-store")
            # No Content-Length: the whole point is that the length is
            # not known until she has finished saying it.
            self.end_headers()

            def push(obj):
                try:
                    self.wfile.write((json.dumps(obj) + "\n").encode())
                    self.wfile.flush()
                    return True
                except Exception:
                    # HE CLOSED THE PAGE. Not an error, and it must not
                    # take the generation down noisily -- the brain
                    # finishes the turn and the memory still gets it.
                    return False

            if not said:
                push({"done": True, "ok": False, "said": "Say something first."})
                return
            gone = []
            def chunk(piece):
                if not gone and not push({"piece": piece}):
                    gone.append(True)
            reply, error = answer(said, who, on_chunk=chunk)
            push({"done": True, "ok": error is None,
                  "said": reply or error,
                  "pose": pose_for(reply) if error is None else "idle"})
            return
        if path == "/voice.wav":
            # AUDIO, not JSON. The page feeds these bytes straight to an
            # <audio> element, so whatever device is LOOKING at her is
            # what speaks -- the Steam Deck, the phone, the panel.
            try:
                size = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(size) or b"{}")
                said = (body.get("text") or "").strip()[:2000]
                who = body.get("who", "saya")
            except Exception:
                said = who = ""
            wav, problem = (None, "Say something first.") if not said \
                else voice_wav(said, who)
            if wav is None:
                # A SENTENCE, with a real status code, so the page can
                # tell "she has no voice installed" from "the deck is
                # not answering". Absent rather than a silent 200.
                self._json({"ok": False, "said": problem}, code=503)
                return
            self.send_response(200)
            self.send_header("Content-Type", "audio/wav")
            self.send_header("Content-Length", str(len(wav)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            try:
                self.wfile.write(wav)
            except Exception:
                pass          # he closed the page mid-download
            return
        if path == "/forget":
            # STARTING CLEAN HAS TO BE POSSIBLE, now that she remembers.
            # It takes a NAME, looked up in CHARACTERS exactly like
            # /say, so nothing from the request can ever name a file.
            try:
                size = int(self.headers.get("Content-Length") or 0)
                who = json.loads(self.rfile.read(size) or b"{}").get("who", "")
            except Exception:
                who = ""
            # AN EMPTY NAME IS A REFUSAL HERE, and that is a real
            # difference from /say. `persona_for` defaults a missing
            # name to "saya", which is right for ASKING -- the bare
            # address opens her page -- and wrong for DELETING: an
            # empty field would have quietly wiped Saya's memory
            # instead of doing nothing. Caught by the test, not by
            # reading it. A destructive route gets no defaults.
            key = persona_for(who) if (who or "").strip() else None
            if key is None:
                self._json({"ok": False, "said": "No character by that name."})
                return
            forget(key)
            self._json({"ok": True, "said": "Forgotten."})
            return
        if path == "/icons":
            said, ok = run_deckapps()
            self._json({"ok": ok, "said": said})
            return
        if path == "/pull":
            said, restart = run_pull()
            self._json({"ok": True, "said": said})
            if restart:
                restart_later()
            return
        if not path.startswith("/launch/"):
            self.send_error(404)
            return
        ok, said, opens = launch(path[len("/launch/"):])
        body = json.dumps({"ok": ok, "said": said, "open": opens}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass                      # the shell script prints what matters


PULL_SCRIPT = None      # the suite points this at a stub


def run_pull():
    """Update the deck from the browser. (text, needs_restart)

    Ghost, Sept 15, with the cable on the other side of the room:
    "And can i make her pull the current that way? Idk how to use my
    phone wirelessly with it."

    UPDATING WAS THE LAST THING THAT NEEDED A CABLE. Everything else on
    this deck reaches him over WiFi -- her face, the chat, the wiki, the
    pet -- and `git pull` needed the one shell he can only get by
    plugging his phone into the board. So the update loop was the part
    that kept the deck tethered, and it is the part he runs most.

    IT TAKES NO ARGUMENTS AND IT NEVER WILL. Same discipline as
    /launch/ and /vpet/: this route runs ONE fixed script that lives in
    this repo, and nothing from the request reaches it -- no branch, no
    remote, no path, no shell string. The server binds 0.0.0.0, so a
    route that could be told WHAT to pull would be a box on his WiFi
    that runs what it is told. This one can only ever do the thing the
    button says.

    `pull` is already safe to tap twice: it stops on local changes
    rather than overwriting them, and says so."""
    import subprocess
    script = PULL_SCRIPT or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "pull")
    if not os.path.exists(script):
        return "No pull script on this board.", False
    try:
        done = subprocess.run(
            ["bash", script], capture_output=True, text=True, timeout=300,
            # THE RESTART IS OURS TO DO, NOT ITS. `pull` normally bounces
            # a running face server, which here is the process holding
            # this very request -- he would tap Pull and get a network
            # error over an update that worked. The reply goes out first.
            env=dict(os.environ, YUZU_PULL_NO_RESTART="1"))
        text = (done.stdout or "") + (done.stderr or "")
    except subprocess.TimeoutExpired:
        return "The pull is taking longer than five minutes. Check WiFi.", False
    except Exception as exc:
        return "Could not run the pull script (%s)." % exc, False
    # ALWAYS restart on a real update rather than working out whether
    # this particular one needs it. A restart costs the page's chat
    # history and nothing else, and getting the condition subtly wrong
    # is how a fresh page ends up asking a stale process -- which is the
    # exact fault this whole route was written the day after.
    return text.strip(), "UPDATED." in text


DECKAPPS_SCRIPT = None   # the suite points this at a stub


def run_deckapps():
    """Put the deck's app icons on the board's own desktop. (text, ok)

    Ghost, Sept 17, having just been told that plugging a monitor in
    gives him an ordinary Ubuntu desktop with his deck sitting on top
    of it: "i want a button on that gnome desktop that opens a window
    with this part in it if possible? I just dislike using terminals
    honestly", then "Like fully a window not a browser tab."

    THE WINDOW ALREADY EXISTED AND THE ONLY WAY TO GET IT WAS A
    TERMINAL. `deckapps` writes .desktop files that open every page
    with `--app= --start-fullscreen` -- no tab strip, no url bar, no
    window edge, which is exactly the thing he is asking for. What he
    could not do was install them without typing, and the one shell he
    has is a serial cable. So the last setup step that needed a
    keyboard becomes a button.

    AND HE CAN TAP IT FROM HIS PHONE. The icons land on the board's
    desktop whether or not anything is plugged into it, so the deck is
    already dressed the first time he looks at the monitor.

    IT TAKES NO ARGUMENTS AND IT NEVER WILL -- same discipline as
    /pull, /launch/ and /vpet/: one fixed script in this repo, and
    nothing from the request reaches it. `--autostart` and `--remove`
    are deliberately NOT reachable from here; a route that could be
    told WHICH word to pass is a box on his WiFi that runs what it is
    told, and --remove is the destructive one.

    IT IS ALSO DELIBERATELY NOT PART OF /launch/, which is
    fire-and-forget by design. This one CHANGES HIS DESKTOP, and
    `deckapps` already refuses to leave a dead icon and exits non-zero
    when it does -- throwing that away would be the silent failure this
    deck refuses everywhere else."""
    import subprocess
    script = DECKAPPS_SCRIPT or os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "deckapps")
    if not os.path.exists(script):
        return "No deckapps script on this board.", False
    try:
        done = subprocess.run(["bash", script], capture_output=True,
                              text=True, timeout=120)
    except Exception as exc:
        return "Could not put the icons out (%s)." % exc, False
    text = ((done.stdout or "") + (done.stderr or "")).strip()
    if done.returncode != 0:
        # deckapps names which icon failed and what is missing. That IS
        # the message -- it is more use than anything phrased here.
        return text or "The icons did not install.", False
    # VERDICT FIRST, and the verdict is not its last line. `deckapps`
    # ends on "Done." with the useful part scrolled above it, and the
    # bar he reads this in shows four lines.
    named = [line.split(":", 1)[1].strip() for line in text.splitlines()
             if line.strip().startswith("installed:")]
    said = ("DONE. Look at the screen plugged into the deck: there is a "
            "Deck icon on the desktop and in the app menu, and it opens "
            "as a window rather than a browser tab.")
    if named:
        said += "\n" + ", ".join(named)
    return said, True


def restart_later(delay=2):
    """Bounce the server AFTER the reply has gone out.

    A detached child rather than exec: the response is written but not
    necessarily received, and killing this process while the socket is
    still draining turns a successful update into a network error. Same
    ordering drop.py had to learn, with slack."""
    import subprocess
    here = os.path.dirname(os.path.abspath(__file__))
    face = os.path.join(here, "face")
    if not os.path.exists(face):
        return
    subprocess.Popen(
        ["bash", "-c", "sleep %d; '%s' --off >/dev/null 2>&1; "
                       "'%s' >/dev/null 2>&1" % (delay, face, face)],
        start_new_session=True,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def serve(port=8081, bind="0.0.0.0"):
    """Blocks. `face` backgrounds this with nohup -- never foreground on
    his serial link, which reads as a frozen board."""
    # THREADING, and it is not optional: one reply takes tens of seconds
    # on that board, and a single-threaded server would stop answering
    # /state for the whole time -- so her face would freeze exactly when
    # it most needs to say `thinking`.
    ThreadingHTTPServer((bind, port), _Handler).serve_forever()


def _report():
    found = sprites()
    if not found:
        print("No sprites in ui/sprites/.")
        print("Drop transparent PNGs in there -- the filename is the name.")
        return 1
    print(f"\n  {len(found)} expressions in ui/sprites/\n")
    for s in found:
        size = f"{s['w']}x{s['h']}" if s["w"] else "?"
        print(f"    {s['name']:<12} {size:>10}   {s['file']}")
    resolved = roles_for(found)
    print("\n  wired to:\n")
    for role in ROLES:
        print(f"    {role:<12} {resolved.get(role, '-- no art yet --')}")
    print()
    return 0


if __name__ == "__main__":
    if "--front" in sys.argv:
        # `deckapps` asks this so its app icon is never a cast list.
        said = front_app()
        print(said)
        sys.exit(0 if said else 1)
    if "--serve" in sys.argv:
        port = 8081
        for i, a in enumerate(sys.argv):
            if a == "--port" and i + 1 < len(sys.argv):
                port = int(sys.argv[i + 1])
        serve(port)
    else:
        sys.exit(_report())
