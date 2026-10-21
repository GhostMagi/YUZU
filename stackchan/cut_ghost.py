"""Cut the ghost out of his picture, once: ui/art_in/ghost.webp ->
stackchan/ghost.png. make_art.py makes the cube's header from the cut.

Ghost, Oct 17, of the screen after Zero on the cube: "a old neongreen/
black crt vibe behind this png of a ghost", with this picture ("I made
sure this was free").

Its transparency is a CHECKERBOARD PAINTED INTO THE PICTURE: 15px
squares, white (255) and grey (231), from the top-left corner. And his
face's highlight is exactly 255 too, so a flood on colour alone walks
straight into his face (it did, the first time). What saves it is the
grid: a grey square's pixel is the backdrop only if it is 231, and he
is never 231-and-neutral, so the grey squares are decided exactly. A
WHITE square the flood got into is kept only as far as its grey
neighbours say it is the backdrop -- each pixel asks the nearest grey
pixel in all four directions, nearer ones counting more.

Needs numpy and PIL. Five seconds. Not run by the tests; the cut it
writes is committed, and make_art.py's output is what the tests hold.
"""
import pathlib
import sys
from collections import deque

HERE = pathlib.Path(__file__).resolve().parent
SOURCE = HERE.parent / "ui" / "art_in" / "ghost.webp"
OUT = HERE / "ghost.png"
SQ = 15          # the painted checkerboard's square, in source pixels
KEEP_H = 400     # the cut is kept at about twice the cube's size


def cut(source=SOURCE):
    import numpy as np
    from PIL import Image, ImageFilter
    src = Image.open(source).convert("RGB")
    a = np.asarray(src).astype(int)
    h, w, _ = a.shape
    ys, xs = np.mgrid[0:h, 0:w]
    white_cell = (xs // SQ + ys // SQ) % 2 == 0
    spread, lo = a.max(2) - a.min(2), a.min(2)
    looks_bg = np.where(white_cell, (spread <= 3) & (lo >= 250),
                        (spread <= 3) & (abs(lo - 231) <= 4))
    bg = np.zeros((h, w), bool)
    q = deque((x, y) for x in range(w) for y in (0, h - 1))
    q.extend((x, y) for y in range(h) for x in (0, w - 1))
    while q:
        x, y = q.popleft()
        if not (0 <= x < w and 0 <= y < h) or bg[y, x] or not looks_bg[y, x]:
            continue
        bg[y, x] = True
        q.extend(((x - 1, y), (x + 1, y), (x, y - 1), (x, y + 1)))
    ghost = ~bg
    grey_ghost = ~bg & ~white_cell
    for cy in range(0, h, SQ):
        for cx in range(0, w, SQ):
            if (cx // SQ + cy // SQ) % 2 or not bg[cy:cy + SQ, cx:cx + SQ].any():
                continue
            y1, x1 = min(cy + SQ, h), min(cx + SQ, w)
            for y in range(cy, y1):
                for x in range(cx, x1):
                    if not bg[y, x]:
                        continue
                    votes = total = 0.0
                    for nx, ny in ((cx - 1, y), (x1, y), (x, cy - 1), (x, y1)):
                        if 0 <= nx < w and 0 <= ny < h:
                            k = 1.0 / (abs(nx - x) + abs(ny - y))
                            votes += k * grey_ghost[ny, nx]
                            total += k
                    if total and votes / total > 0.5:
                        ghost[y, x] = True
    mask = Image.fromarray((ghost * 255).astype(np.uint8))
    mask = mask.filter(ImageFilter.MedianFilter(5)).filter(
        ImageFilter.GaussianBlur(1))
    img = src.convert("RGBA")
    img.putalpha(mask)
    img = img.crop(mask.getbbox())
    keep_w = round(img.width * KEEP_H / img.height)
    return (img.convert("RGBa").resize((keep_w, KEEP_H), Image.LANCZOS)
            .convert("RGBA"))


if __name__ == "__main__":
    try:
        cut().save(OUT)
    except ImportError:
        sys.exit("This needs numpy and PIL. The committed ghost.png "
                 "already works; you only need this to change him.")
    print("wrote", OUT)
