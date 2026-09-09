#!/usr/bin/env python3
"""Turn a raw drawing into a sprite: white background out, line art in.

Ghost, Sept 10: *"Write a Python function using PIL/Pygame that converts
white pixels to transparent alpha when loading the images into memory,
so we don't have to edit the backgrounds manually."* And then, on the
grey shading in the new art: *"color not needed."*

    python3 yuzu_art.py drawing.jpg mad     -> ui/sprites/mad.png
    python3 yuzu_art.py                     -> convert everything in ui/raw/

**PIL IS OPTIONAL AND THE IMPORT IS GUARDED**, exactly like Piper's.
He asked for PIL and PIL is the right tool -- it reads the JPEGs his
phone gallery produces, which the stdlib cannot. But `installs nothing`
is what lets this project run in Pydroid on that phone, so:

    with PIL      any format, including his .jpg screenshots
    without PIL   PNG only, through the stdlib reader in yuzu_face

Either way the OUTPUT is a plain PNG committed to the repo, so the deck
never needs PIL to show her face. This is a workbench tool, not a
runtime dependency.

WHY ALPHA COMES FROM DARKNESS RATHER THAN A THRESHOLD. A hard cutoff
("whiter than X is gone") turns every anti-aliased edge into a staircase,
and her line work is nothing but curves. Ramping alpha across the last
few shades keeps the edges smooth and costs one subtraction. The colour
is thrown away and every surviving pixel is BLACK -- his call, and it
also matches the eight sprites already in the folder.

SCREENSHOT FURNITURE IS CROPPED FIRST. His art arrives as phone
screenshots, so it comes wrapped in black or grey bars from the gallery
app. Those are not white, so they would survive the transparency pass
and then define the bounding box -- her face would end up a small thing
floating inside a frame of nothing. `strip_bars` takes them off before
anything else looks at the picture.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SPRITES = os.path.join(HERE, "ui", "sprites")
RAW = os.path.join(HERE, "ui", "raw")

# Anything this pale is background. 245 rather than 255 because a JPEG
# never gives back the white it was handed -- his screenshots come in
# around 248-254 on the paper, with ringing near the lines.
WHITE_AT = 243
# Anything this dark is solid line. Between the two, alpha ramps.
INK_AT = 70


def _pil():
    """PIL if it is here, else None. Never raises."""
    try:
        from PIL import Image
        return Image
    except Exception:
        return None


def load_rgba(path):
    """(w, h, bytearray) in RGBA, or None.

    PIL handles anything; without it this falls back to the stdlib PNG
    reader that yuzu_face already carries, which is enough for PNG art
    and honest about everything else."""
    image = _pil()
    if image is not None:
        try:
            with image.open(path) as img:
                img = img.convert("RGBA")
                return img.width, img.height, bytearray(img.tobytes())
        except Exception:
            return None
    try:
        import yuzu_face
        got = yuzu_face.read_rgba(path)
        return (got[0], got[1], bytearray(got[2])) if got else None
    except Exception:
        return None


def _lum(px, i):
    return (px[i] * 299 + px[i + 1] * 587 + px[i + 2] * 114) // 1000


def strip_bars(w, h, px, edge_tol=26):
    """Crop the solid bars a screenshot app leaves around a picture.

    A bar is an edge row or column that is nearly all ONE colour and is
    not the paper -- black letterboxing, a grey chrome strip. Walk in
    from each side while that holds. Returns (w, h, px)."""
    # ALPHA FIRST, and this cost the whole art folder once. The first
    # version asked only about brightness, and the RGB sitting under a
    # transparent pixel is usually black -- so on art that was ALREADY a
    # sprite, every transparent border row read as a solid black bar and
    # this cropped `blink.png` down to ONE PIXEL. A transparent edge is
    # nothing being there; it is not furniture.
    # A bar is an edge line with NO PAPER IN IT, and that is the whole
    # test. Asking whether it is a UNIFORM colour was the first version
    # and JPEG noise beat it: the grey chrome strip down the side of one
    # screenshot varied by more than the tolerance, survived, and then
    # defined the bounding box -- so her face rendered small and
    # off-centre with a stray line beside it, which is exactly how it
    # looked on the page.
    #
    # Every row of real line art crosses white paper somewhere. A
    # letterbox never does. That holds for black bars, grey bars and
    # gradients alike, with nothing to tune.
    def _no_paper(indices):
        for i in indices:
            if px[i + 3] < 250:
                return False                # transparent: not furniture
            if _lum(px, i) > WHITE_AT:
                return False                # found paper: real art
        return True

    def row_is_bar(y):
        return _no_paper([(y * w + x) * 4
                          for x in range(0, w, max(1, w // 96))])

    def col_is_bar(x):
        return _no_paper([(y * w + x) * 4
                          for y in range(0, h, max(1, h // 96))])

    top, bottom, left, right = 0, h - 1, 0, w - 1
    while top < bottom and row_is_bar(top):
        top += 1
    while bottom > top and row_is_bar(bottom):
        bottom -= 1
    while left < right and col_is_bar(left):
        left += 1
    while right > left and col_is_bar(right):
        right -= 1
    if (top, left, bottom, right) == (0, 0, h - 1, w - 1):
        return w, h, px

    nw, nh = right - left + 1, bottom - top + 1
    out = bytearray(nw * nh * 4)
    for y in range(nh):
        src = ((y + top) * w + left) * 4
        out[y * nw * 4:(y + 1) * nw * 4] = px[src:src + nw * 4]
    return nw, nh, out


def to_transparent(w, h, px, white_at=WHITE_AT, ink_at=INK_AT):
    """White out, black line art in. THE function he asked for.

    Alpha is a RAMP over the last shades before white rather than a
    cutoff, so anti-aliased curves stay curves. Colour is discarded --
    "color not needed" -- so grey shading becomes faint black and the
    background shows through it."""
    span = max(1, white_at - ink_at)
    for i in range(0, len(px), 4):
        light = _lum(px, i)
        if light >= white_at:
            alpha = 0
        elif light <= ink_at:
            alpha = 255
        else:
            alpha = ((white_at - light) * 255) // span
        # An already-transparent pixel stays transparent: running this
        # over art that is already a sprite must not resurrect its
        # background out of whatever RGB sits under alpha 0.
        px[i] = px[i + 1] = px[i + 2] = 0
        px[i + 3] = min(alpha, px[i + 3]) if px[i + 3] < 255 else alpha
    return w, h, px


def trim(w, h, px, pad=8):
    """Crop to the drawing, leaving a little air.

    Two of his four arrived with the face off-centre in a tall frame.
    Cropping to content is what makes them all sit the same on screen,
    which matters because the page scales each sprite to one box."""
    left, right, top, bottom = w, -1, h, -1
    for y in range(h):
        row = y * w
        for x in range(w):
            if px[(row + x) * 4 + 3] > 12:
                if x < left:   left = x
                if x > right:  right = x
                if y < top:    top = y
                if y > bottom: bottom = y
    if right < 0:
        return w, h, px                     # nothing survived; leave it
    left = max(0, left - pad); top = max(0, top - pad)
    right = min(w - 1, right + pad); bottom = min(h - 1, bottom + pad)
    nw, nh = right - left + 1, bottom - top + 1
    out = bytearray(nw * nh * 4)
    for y in range(nh):
        src = ((y + top) * w + left) * 4
        out[y * nw * 4:(y + 1) * nw * 4] = px[src:src + nw * 4]
    return nw, nh, out


def square(w, h, px, margin=0.06):
    """Centre the drawing on a SQUARE canvas.

    THE THING THAT MAKES IT LOOK SMOOTH. The page scales every sprite
    into one square box with `object-fit: contain`, so a wide sprite
    renders SMALLER than a tall one -- and her face visibly jumps size
    when the expression changes, or every few seconds when she blinks.
    Cropped tight, his four came out between 1.09 and 1.51 wide.

    Squaring costs nothing (the padding is transparent) and makes every
    expression land at the same scale in the same place."""
    side = int(max(w, h) * (1 + margin * 2))
    out = bytearray(side * side * 4)
    ox, oy = (side - w) // 2, (side - h) // 2
    for y in range(h):
        src = y * w * 4
        dst = ((y + oy) * side + ox) * 4
        out[dst:dst + w * 4] = px[src:src + w * 4]
    return side, side, out


def looks_like_paper(w, h, px):
    """True if this image has a white background to remove.

    Guards the automatic path: running the conversion over a sprite that
    is ALREADY transparent would be a no-op at best, so it is skipped by
    asking about the border rather than by remembering a list."""
    edge, white = 0, 0
    for x in range(0, w, max(1, w // 40)):
        for y in (0, h - 1):
            i = (y * w + x) * 4
            edge += 1
            if px[i + 3] > 200 and _lum(px, i) >= WHITE_AT:
                white += 1
    return edge and white / edge > 0.8


def convert(src, dst=None, name=None):
    """Raw drawing -> sprite PNG. Returns the path written, or None."""
    got = load_rgba(src)
    if not got:
        return None
    w, h, px = got
    w, h, px = strip_bars(w, h, px)
    if looks_like_paper(w, h, px):
        w, h, px = to_transparent(w, h, px)
    w, h, px = trim(w, h, px)
    w, h, px = square(w, h, px)
    if dst is None:
        stem = name or os.path.splitext(os.path.basename(src))[0]
        dst = os.path.join(SPRITES, stem + ".png")
    image = _pil()
    if image is not None:
        image.frombytes("RGBA", (w, h), bytes(px)).save(dst)
    else:
        import yuzu_face
        yuzu_face.write_rgba(dst, w, h, px)
    return dst


def _cli(argv):
    if len(argv) >= 2:
        out = convert(argv[0], name=argv[1])
    elif len(argv) == 1:
        out = convert(argv[0])
    else:
        if not os.path.isdir(RAW):
            print("Give it a drawing:  python3 yuzu_art.py face.jpg mad")
            print("or put files in ui/raw/ and run it with no arguments.")
            return 1
        done = [convert(os.path.join(RAW, f)) for f in sorted(os.listdir(RAW))]
        done = [d for d in done if d]
        print("converted %d" % len(done))
        for d in done:
            print("   ", os.path.basename(d))
        return 0
    if not out:
        print("Could not read that. Without PIL only PNG works:")
        print("    pip install Pillow")
        return 1
    print("wrote", out)
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
