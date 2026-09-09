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
background swatches work at all, and it is why the only paint this adds
goes INSIDE the mouth: everywhere else, the background is already doing
the colouring for free.
"""

import json
import os
import shutil
import subprocess
import zlib
import struct
import sys
from collections import deque
from http.server import SimpleHTTPRequestHandler, HTTPServer

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
    "asleep":   ("asleep", "sleepy"),
}


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
# PAINT: black line art stays black; the colour goes where a colourist
# would put it. Ghost, Sept 9: "make the art black lines for like where
# itd normally be so. lineart typa deal. but you can feel free to color
# the mouth appropriatly and maybe add a ring of pink color to her eyes"
#
# Nothing is hand-positioned. The features are FOUND in the art, so a
# new PNG dropped in the folder gets painted too, which is the whole
# reason this is a sprite system and not five hard-coded faces:
#
#   the mouth   the ink blob whose centroid sits lowest
#   its inside  the enclosed transparent holes within that blob's box
#
# A PINK IRIS RING WAS BUILT AND CUT THE SAME MINUTE. It found each eye
# blob and laid a ring of colour over its outer band. Rendered, it read
# as a smear: the ring flooded the pupil on the open eye and painted the
# CLOSED one, which has no iris to ring. Ghost, seeing it: "remove the
# pink iris idea my bad entirely. just use the art i gave u."
#
# Worth keeping as a note rather than a scar: the detection was right
# (it found both eyes) and the RENDERING was wrong, and the only reason
# that was knowable in one pass was compositing a preview and LOOKING at
# it. A geometry check would have passed. Same rule as the rest of this
# repo -- a check that cannot observe the actual failure is not a check.
#
# Output is one companion file, `<name>.paint.png`, stacked OVER the
# line art by the page. Over works because the mouth interior is a hole,
# so painting on top of it is the same as painting behind.
# ---------------------------------------------------------------------

# A mouth is three things, so it gets three colours. Ghost, Sept 9:
# "plz paint mouth like. pink tongue white teeth and black uhhh hole?"
TONGUE = (226, 106, 132, 255)
TEETH  = (250, 247, 244, 255)
CAVITY = (34, 18, 24, 255)        # the dark behind everything
INK_MAX = 110                     # r,g,b under this, with alpha, is a line
CLEAR_MAX = 60                    # alpha under this is a hole
MOUTH_FLOOR = 0.58                # nothing above this fraction is a mouth


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
    cannot read is still DISPLAYED -- it just goes unpainted."""
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


def _components(w, h, mask):
    """Connected runs of True in `mask`, as lists of pixel indices."""
    seen = bytearray(w * h)
    groups = []
    for start in range(w * h):
        if not mask[start] or seen[start]:
            continue
        queue = deque([start]); seen[start] = 1; cells = []
        while queue:
            i = queue.popleft(); cells.append(i)
            x, y = i % w, i // w
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < w and 0 <= ny < h:
                    j = ny * w + nx
                    if mask[j] and not seen[j]:
                        seen[j] = 1; queue.append(j)
        groups.append(cells)
    return groups


def _enclosed(w, h, clear):
    """Transparent pixels the outside cannot reach -- eye highlights and
    the inside of a mouth. Flooding from the border is what separates a
    hole from the empty space around her face."""
    seen = bytearray(w * h)
    queue = deque()
    edge = ([y * w for y in range(h)] + [y * w + w - 1 for y in range(h)]
            + list(range(w)) + [(h - 1) * w + x for x in range(w)])
    for i in edge:
        if clear[i] and not seen[i]:
            seen[i] = 1; queue.append(i)
    while queue:
        i = queue.popleft(); x, y = i % w, i // w
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < w and 0 <= ny < h:
                j = ny * w + nx
                if clear[j] and not seen[j]:
                    seen[j] = 1; queue.append(j)
    return bytearray(clear[i] and not seen[i] for i in range(w * h))


def _box(cells, w):
    xs = [i % w for i in cells]; ys = [i // w for i in cells]
    return (min(xs), min(ys), max(xs), max(ys),
            sum(xs) / len(cells), sum(ys) / len(cells))


def paint(path, out_path=None):
    """Write `<name>.paint.png` next to a sprite: her line art untouched,
    with the inside of her mouth coloured in -- white teeth, pink
    tongue, dark cavity. Returns the path, or None
    if the art could not be read -- never raises, because one odd file
    must not take her whole face down."""
    got = read_rgba(path)
    if not got:
        return None
    w, h, px = got
    ink = bytearray(w * h); clear = bytearray(w * h)
    for i in range(w * h):
        r, g, b, a = px[i * 4:i * 4 + 4]
        if a > 140 and r < INK_MAX and g < INK_MAX and b < INK_MAX:
            ink[i] = 1
        if a < CLEAR_MAX:
            clear[i] = 1

    blobs = sorted(_components(w, h, ink), key=len, reverse=True)[:8]
    if not blobs:
        return None
    boxed = [(_box(c, w), c) for c in blobs]

    # The mouth is the lowest substantial blob -- but it must actually
    # be DOWN THERE. Without that floor, `idle.png` (mouth drawn as two
    # open lines with no interior) had its lowest *enclosed* shape be an
    # EYE, and the paint pass filled one iris pink and left the other
    # black. Which is the cut iris ring back again, by accident, on one
    # side only.
    big = [b for b in boxed if len(b[1]) > 0.15 * len(blobs[0])]
    low = [b for b in big if b[0][5] > MOUTH_FLOOR * h]
    if not low:
        # A closed mouth with no interior. Nothing to colour, and an
        # empty layer is the RIGHT answer -- reaching further up the
        # face for something to paint is how you end up painting eyes.
        write_rgba(out_path or os.path.splitext(path)[0] + ".paint.png",
                   w, h, bytearray(w * h * 4))
        return out_path or os.path.splitext(path)[0] + ".paint.png"
    mouth_box, _ = max(low, key=lambda b: b[0][5])

    out = bytearray(w * h * 4)

    # Mouth interior. Each enclosed hole inside the mouth blob is one of
    # three things, decided by WHERE IT SITS in the mouth rather than by
    # any per-sprite knowledge -- measured across all eight of his faces,
    # every open mouth splits into an upper band and a lower one:
    #
    #     top third      teeth    white
    #     bottom third   tongue   pink
    #     the middle     cavity   near-black
    #
    # A hole spanning most of the mouth's height is the whole cavity --
    # a shocked O with nothing in it -- and is dark, not a giant tooth.
    holes = _enclosed(w, h, clear)
    x0, y0, x1, y1 = mouth_box[0], mouth_box[1], mouth_box[2], mouth_box[3]
    tall = max(1.0, y1 - y0)
    for cells in _components(w, h, holes):
        hx0, hy0, hx1, hy1, cx, cy = _box(cells, w)
        if not (x0 <= cx <= x1 and y0 <= cy <= y1 and cy > MOUTH_FLOOR * h):
            continue
        where = (cy - y0) / tall
        if (hy1 - hy0) / tall > 0.6:
            colour = CAVITY               # the whole open mouth
        elif where < 0.45:
            colour = TEETH
        elif where > 0.60:
            colour = TONGUE
        else:
            colour = CAVITY
        for i in cells:
            out[i * 4:i * 4 + 4] = bytes(colour)

    out_path = out_path or os.path.splitext(path)[0] + ".paint.png"
    write_rgba(out_path, w, h, out)
    return out_path


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


class _Handler(SimpleHTTPRequestHandler):
    """Static files out of ui/, plus one generated endpoint.

    `/sprites.json` is rebuilt PER REQUEST, so dropping a new PNG in
    the folder needs a page refresh and not a server restart. On a
    phone over a serial link, "restart the server" is a much bigger ask
    than it sounds."""

    def __init__(self, *a, **kw):
        super().__init__(*a, directory=UI_DIR, **kw)

    def do_GET(self):
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

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/")
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
    HTTPServer((bind, port), _Handler).serve_forever()


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


def paint_all(directory=None):
    """Paint every sprite that has no companion yet. Returns the names
    painted. Cheap to call: it skips art whose paint file is newer."""
    directory = directory or SPRITE_DIR
    done = []
    for s in sprites(directory):
        src = os.path.join(directory, os.path.basename(s["file"]))
        if src.endswith(".paint.png"):
            continue
        out = os.path.splitext(src)[0] + ".paint.png"
        try:
            if (os.path.exists(out)
                    and os.path.getmtime(out) >= os.path.getmtime(src)):
                continue
        except OSError:
            pass
        if paint(src):
            done.append(s["name"])
    return done


if __name__ == "__main__":
    if "--paint" in sys.argv:
        painted = paint_all()
        print(f"painted {len(painted)}: {', '.join(painted)}" if painted
              else "nothing to paint")
    elif "--serve" in sys.argv:
        port = 8081
        for i, a in enumerate(sys.argv):
            if a == "--port" and i + 1 < len(sys.argv):
                port = int(sys.argv[i + 1])
        serve(port)
    else:
        sys.exit(_report())
