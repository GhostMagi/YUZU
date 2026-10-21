#!/usr/bin/env python3
"""Saya's faces, cut from his kaomoji sheet: ui/art_in/saya_kaomoji.jpg
-> ui/sprites/<face>.png.

Ghost, Oct 19: *"bringing Saya the tsundere back but with these as her
faces in neon green with the crt effect like she has. (So its easier
and stays true) just a visual makeover."* The sheet is 24 kaomoji, white
on black, three rows of eight. Her page masks every sprite with its
neon green ink, so a sprite here is ALPHA ONLY: white line work becomes
opaque, the black ground becomes nothing, and the brown tears go green
with the rest, as he asked.

THREE THINGS DECIDE HOW SHE LOOKS, and each one was rendered and looked
at rather than assumed:

  ONE SIZE FOR EVERY FACE. The page scales a sprite to fit its box, so
  a face cropped to its own edges would change size with her mood. Each
  face is cut from a window of the same size, centred on that face.
  EYES ON ONE LINE. A face's top is its eyes on this sheet (two have
  brows; those are moved by their own measure), so the tops line up
  and her eyes do not jump when the expression changes.
  UPSCALED, THEN RE-SHARPENED. Each face is about 150px wide on the
  sheet and fills the panel, so it is enlarged four times and the alpha
  is squeezed back into a short ramp: strokes stay crisp, edges stay
  smooth, and the JPEG's grain on the black falls below the ramp.

The blink is not on the sheet: it is her resting face with each dot eye
swapped for a stroke cut from that same face's own mouth line, so the
line weight is his.

Three of the 24 are left out (two more tongue faces and a pi-eyed
weep, near repeats); add one by naming its cell in FACES and giving
yuzu_face a role for it. Needs numpy and PIL. Not run by the tests; the
sprites it writes are committed, and the tests hold those.
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
SOURCE = HERE / "ui" / "art_in" / "saya_kaomoji.jpg"
OUT = HERE / "ui" / "sprites"

# Rows (top to bottom) and columns (left to right) of the sheet, as
# measured: every row and column of ink, with the dark between them.
ROWS = [(86, 147), (185, 260), (313, 377), (425, 503),
        (540, 605), (650, 707), (763, 816), (858, 913)]
COLS = [(40, 245), (250, 490), (495, 736)]

# The file each cell becomes. The NAME is what the face is doing, the
# convention every sprite here has used; yuzu_face.ROLES maps her moods
# onto them.
FACES = {
    (1, 1): "sleepy",     (1, 2): "thinking",  (1, 3): "cry",
    (2, 1): "idle",                            (2, 3): "puff",
    (3, 1): "smug",       (3, 2): "pout",      (3, 3): "bleh",
    (4, 1): "cute",       (4, 2): "ooh",       (4, 3): "sob",
                          (5, 2): "angry",     (5, 3): "irritated",
    (6, 1): "flustered",  (6, 2): "dizzy",     (6, 3): "blush",
    (7, 1): "happy",                           (7, 3): "talking",
    (8, 1): "annoyed",    (8, 2): "shock",     (8, 3): "shout",
}

INK = 70           # brighter than this (any channel) is line work
WIN_W, WIN_H = 210, 112     # one window for every face, sheet pixels
TOP = 30           # where a face's eyes start inside the window
SCALE = 4          # 210x96 -> 840x384
RAMP = (80, 150)   # the re-sharpened edge, on the enlarged brightness
# The tears are a white outline round a BROWN fill. In one ink the fill
# goes in at half strength: a bright rim round a dimmer drop, the way
# he drew it, rather than a solid blob or an empty outline.
FILL = 0.5
# Faces whose top is not their eyes, measured: (5, 2)'s brows and
# (5, 3)'s anger mark sit above them.
EYES_BELOW_TOP = {(5, 2): 20, (5, 3): 26}
# Faces whose centre is not their bounding box's: the anger mark
# hangs off the right of (5, 3), so it is centred on the face itself.
CENTRE_X = {(5, 3): 600}


def bbox(ink, r, c):
    (r0, r1), (c0, c1) = ROWS[r - 1], COLS[c - 1]
    import numpy as np
    sub = ink[r0 - 20:r1 + 20, c0:c1]
    ys, xs = np.nonzero(sub)
    return (xs.min() + c0, ys.min() + r0 - 20, xs.max() + c0, ys.max() + r0 - 20)


def window(plane, ink, cell):
    """This face alone, in a WIN_W x WIN_H window at sheet scale."""
    import numpy as np
    x0, y0, x1, y1 = bbox(ink, *cell)
    own = np.zeros_like(plane)
    own[y0 - 2:y1 + 3, x0 - 2:x1 + 3] = plane[y0 - 2:y1 + 3, x0 - 2:x1 + 3]
    cx = CENTRE_X.get(cell, (x0 + x1) / 2)
    left = int(round(cx - WIN_W / 2))
    top = y0 + EYES_BELOW_TOP.get(cell, 0) - TOP
    return own[top:top + WIN_H, left:left + WIN_W].copy()


def parts(mask):
    """The separate strokes of a face, left to right, as (rows, cols)
    slices -- a flood fill, so the workbench needs nothing past numpy."""
    from collections import deque
    seen = mask.copy()
    found = []
    h, w = mask.shape
    for y0, x0 in zip(*mask.nonzero()):
        if not seen[y0, x0]:
            continue
        seen[y0, x0] = False
        todo, ys, xs = deque([(y0, x0)]), [], []
        while todo:
            y, x = todo.popleft()
            ys.append(y)
            xs.append(x)
            for ny, nx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= ny < h and 0 <= nx < w and seen[ny, nx]:
                    seen[ny, nx] = False
                    todo.append((ny, nx))
        found.append((slice(min(ys), max(ys) + 1), slice(min(xs), max(xs) + 1)))
    return sorted(found, key=lambda s: s[1].start)


def blink_from(face):
    """Her resting face with its eyes shut: each dot eye replaced by a
    stroke cut from the middle of that face's own mouth line."""
    import numpy as np
    left, mouth, right = parts(face > INK)
    out = face.copy()
    for eye in (left, right):
        out[eye] = 0
    my = mouth[0]
    mx = (mouth[1].start + mouth[1].stop) // 2
    for eye in (left, right):
        span = eye[1].stop - eye[1].start   # no longer than the eye was
        stroke = face[my, mx - span // 2:mx - span // 2 + span]
        ey = (eye[0].start + eye[0].stop) // 2 - (my.stop - my.start) // 2
        ex = (eye[1].start + eye[1].stop) // 2 - span // 2
        out[ey:ey + stroke.shape[0], ex:ex + span] = np.maximum(
            out[ey:ey + stroke.shape[0], ex:ex + span], stroke)
    return out


def sprite(face, brown=None):
    """Sheet-scale brightness -> an enlarged RGBA sprite, alpha only."""
    import numpy as np
    from PIL import Image

    def bigger(plane):
        return np.asarray(Image.fromarray(plane.astype("float32"), "F").resize(
            (plane.shape[1] * SCALE, plane.shape[0] * SCALE), Image.BICUBIC))
    a = (bigger(face) - RAMP[0]) / (RAMP[1] - RAMP[0])
    a = np.clip(a, 0, 1)
    a = a * a * (3 - 2 * a)                     # smoothstep
    if brown is not None and brown.any():
        a = np.maximum(a, FILL * np.clip(bigger(brown), 0, 1))
    rgba = np.zeros(a.shape + (4,), "uint8")    # black line art...
    rgba[..., 3] = np.round(a * 255)            # ...in the alpha
    return Image.fromarray(rgba, "RGBA")


def cut(source=SOURCE, out=OUT):
    import numpy as np
    from PIL import Image
    rgb = np.asarray(Image.open(source).convert("RGB")).astype(float)
    lum = rgb.max(2)
    ink = lum > INK
    # The tears' fill: warm (red well over blue) and not black.
    brown = (rgb[..., 0] - rgb[..., 2] > 35) & (lum > 45)
    # One pixel wider, so no dark ring is left between fill and rim.
    grown = brown.copy()
    grown[1:] |= brown[:-1]; grown[:-1] |= brown[1:]
    grown[:, 1:] |= brown[:, :-1]; grown[:, :-1] |= brown[:, 1:]
    brown = grown.astype(float)
    out.mkdir(parents=True, exist_ok=True)
    made = []
    for cell, name in FACES.items():
        face = window(lum, ink, cell)
        sprite(face, window(brown, ink, cell)).save(out / (name + ".png"),
                                                    optimize=True)
        made.append(name)
        if name == "idle":
            sprite(blink_from(face)).save(out / "blink.png", optimize=True)
            made.append("blink")
    return made


if __name__ == "__main__":
    try:
        made = cut()
    except ImportError as e:
        print("Needs numpy and PIL on the workbench: %s" % e)
        sys.exit(1)
    print("cut %d faces into %s" % (len(made), OUT))
