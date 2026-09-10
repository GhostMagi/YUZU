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
# Yuzu is coming back as a portrait like Cait's ("Yuzu has future plans
# very similar to cait... will provide pngs"). When her PNG lands she
# is one entry here plus a copy of cait.html.
CHARACTERS = {
    # name      persona key            page          what she is
    "saya": (None,                     "face.html",  "the deck"),
    "cait": ("cait",                   "cait.html",  "king of the cats"),
}

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
                    "page": page, "blurb": blurb})
    return out


def answer(text, who="saya"):
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
    if drives_face:
        text, problem = yuzu_brain.ground(text)
    if problem:
        # The VERDICT, in the bubble, where he is already looking --
        # not silence, and not a sentence she never said.
        face("idle")
        return "(%s)" % problem, None
    try:
        if key not in _BRAINS:
            import yuzu_personas
            _BRAINS[key] = yuzu_brain.YuzuBrain(
                persona=yuzu_personas.load(key))
        face("thinking")
        reply = _BRAINS[key].ask(text)
        # The brain already wrote `talking` WITH the token rate it just
        # measured. Re-stating it here without one would blank the
        # badge on every reply that came through this page.
        face("talking", reply, get_state().get("rate"))
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

    def do_GET(self):
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

    def _json(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
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
            self._json({"ok": error is None, "said": reply or error})
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
    if "--serve" in sys.argv:
        port = 8081
        for i, a in enumerate(sys.argv):
            if a == "--port" and i + 1 < len(sys.argv):
                port = int(sys.argv[i + 1])
        serve(port)
    else:
        sys.exit(_report())
