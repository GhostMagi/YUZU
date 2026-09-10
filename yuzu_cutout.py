"""Backdrop out, artwork in -- a transparent PNG that keeps the ghosts.

    ui/art_in/<name>.jpg     drop his art here, any name
    python3 yuzu_cutout.py   cut everything in that folder
    ui/art_out/<name>.png    transparent, ready to be a character

Ghost, Sept 12, on the online background remover he tried first:
"i went to remove the background to make it a png online but it removed
the cool parts too like the ghosts behind her."

WHY THE ONLINE TOOL ATE THEM, because it decides everything else here.
Those services run a SUBJECT DETECTOR: they find the person and throw
away what is not her. Ghosts, wisps, skulls and floating flames are not
the person, so they are background by definition and they go. The tool
was working correctly and doing the wrong thing.

This removes the BACKDROP COLOUR instead. It floods inward from the
edges of the picture and only takes pixels that match the flat backdrop,
so anything that is not the backdrop survives -- every wisp, every
skull, every spark. It never has an opinion about what the character is.

Three things it does, and each one is a fault this repo already paid
for somewhere else:

  ALPHA IS A RAMP, NOT A CUTOFF.  Same lesson as yuzu_art.py. A hard
  threshold turns every anti-aliased edge into a staircase, and this
  art is nothing but soft edges.

  THE DISTANCE TEST READS A BLURRED COPY, the output keeps the sharp
  one.  JPEG blocks a flat dark backdrop into patches that vary more
  than any tolerance worth using, so a black background came out
  speckled until the test stopped reading the noise.

  IT IS A FLOOD, NOT A COLOUR MATCH.  A white cape on a white backdrop
  survives because the fill cannot get through her outline. Testing
  colour alone would erase her.

WHERE IT STILL NEEDS HELP, measured on his six:

  Her costume being the backdrop colour is the one real limit -- a
  white cape on white, black gloves on black. Tightening `hi` keeps her
  whole; that is what the per-file settings below are for.

  An INSET PANEL behind her (a lighter card that does not reach the
  edge of the picture) can never be reached by a flood from the edge.
  That wants a `seed` -- a point that says "this is backdrop too".

  AND PEELING IS A TRAP, tried and rejected. Re-deriving the backdrop
  from whatever is still opaque on the border looks like the general
  fix for a two-tone background -- until the character touches the
  border, at which point the leftover border pixels ARE HER and the
  second pass floods her from the feet up. Measured: it ate the cape it
  was meant to save. An explicit seed is duller and cannot do that.
"""

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ART_IN = os.path.join(HERE, "ui", "art_in")
ART_OUT = os.path.join(HERE, "ui", "art_out")
EXTS = (".jpg", ".jpeg", ".png", ".webp")

# PIL is a WORKBENCH dependency and is guarded exactly like Piper's. The
# deck never needs it: what ships is a plain PNG committed to the repo,
# and yuzu_face.py must keep running on a phone with nothing installed.
try:
    from PIL import Image, ImageFilter
except ImportError:
    Image = None


# Per-file settings for art that needs it. The KEY IS THE FILENAME STEM,
# so a recipe travels with the picture and nothing has to be remembered
# at the command line -- the standing rule here is that Ghost gets a
# no-argument script he can tap Run on.
RECIPES = {
    # white cape and a near-white face on a white backdrop: a wide
    # tolerance walks straight through her, so keep it tight.
    # The panel is split into left and right strips by her hood and
    # hair, so one seed only ever cleared one strip. Seeds sit in the
    # margins at x=90 and x=660, where the panel is and she never is.
    "hooded_portrait": dict(lo=4, hi=12, trim=200, seeds=[
        (90, 120), (90, 400), (90, 800), (300, 85),
        (660, 120), (660, 400), (660, 800)]),
    # black gloves and black legs on a black backdrop, plus JPEG
    # blocking in the darks.
    "crawling":        dict(lo=10, hi=40, denoise=3),
    # flat tan backdrops: she wears no tan, so the pockets her own legs
    # enclose are safe to take.
    "standing_tan":    dict(pockets=True),
    "bunny_ghosts":    dict(pockets=True),
    # Yuzu's cream poncho sits a few levels off the white page, so the
    # tolerance has to stay under that gap or the fill walks into her.
    "yuzu_outfits":    dict(lo=3, hi=9),
}
DEFAULTS = dict(lo=14, hi=58, denoise=1, pockets=False, seeds=(),
                trim=0, halo=True)


def _dist(a, b):
    return max(abs(a[0] - b[0]), abs(a[1] - b[1]), abs(a[2] - b[2]))


def backdrop(test, w, h):
    """The dominant colour around the border, refined to its own mean."""
    from collections import Counter
    px = test.load()
    edge = ([px[x, 0] for x in range(w)] + [px[x, h - 1] for x in range(w)]
            + [px[0, y] for y in range(h)] + [px[w - 1, y] for y in range(h)])
    key, _ = Counter(tuple(v // 8 * 8 for v in q) for q in edge).most_common(1)[0]
    near = [q for q in edge if all(abs(q[i] - key[i]) < 24 for i in range(3))]
    return tuple(sum(q[i] for q in near) // len(near) for i in range(3))


def unfringe(cut, bg, floor=24):
    """Take the backdrop back out of the soft edge.

    THIS IS THE HALO, and it is what Ghost saw as "jagged pixels from
    removing outline". Every pixel along an anti-aliased edge is a MIX
    of her and the page behind her: what the file stores is
    C = a*Her + (1-a)*Backdrop. Cutting the backdrop out sets the alpha
    and stops -- so the colour left behind is still part white, and on
    any dark page that reads as a bright rim tracing her whole
    silhouette.

    So solve it back: Her = (C - (1-a)*Backdrop) / a. Fully opaque
    pixels are untouched, and below `floor` there is too little of her
    in the mix to recover anything but noise, so those are left alone
    and are nearly invisible anyway.
    """
    w, h = cut.size
    px = cut.load()
    for y in range(h):
        for x in range(w):
            r, g, b, a = px[x, y]
            if a >= 255 or a < floor:
                continue
            k = a / 255.0
            out = []
            for chan, back in ((r, bg[0]), (g, bg[1]), (b, bg[2])):
                v = (chan - (1 - k) * back) / k
                out.append(0 if v < 0 else (255 if v > 255 else int(v)))
            px[x, y] = (out[0], out[1], out[2], a)
    return cut


def prepare(image, denoise=1):
    """(sharp, blurred-for-testing, backdrop colour)."""
    im = image.convert("RGB")
    test = im.filter(ImageFilter.BoxBlur(denoise)) if denoise else im
    return im, test, backdrop(test, *im.size)


def trim_to_art(cut, floor=200, margin=6):
    """Crop to what is solidly drawn, with a small margin.

    The portrait's panel had a BORDER STROKE a shade darker than the
    panel itself, so it survived at part alpha -- a faint rectangle
    hanging in the air around her. Chasing it with more seeds meant
    widening the tolerance until it reached her cape, which is the
    trade this whole file exists to refuse. Cropping to what is solidly
    drawn removes it without touching a pixel of her.
    """
    a = cut.getchannel("A")
    solid = a.point(lambda v: 255 if v >= floor else 0)
    box = solid.getbbox()
    if not box:
        return cut
    x0, y0, x1, y1 = box
    return cut.crop((max(0, x0 - margin), max(0, y0 - margin),
                     min(cut.width, x1 + margin), min(cut.height, y1 + margin)))


def lift(image, lo=14, hi=58, denoise=1, pockets=False, seeds=(),
         trim=0, halo=True):
    """One RGB image in, one RGBA image out, backdrop removed."""
    from collections import deque
    im, test, _bg = prepare(image, denoise)
    w, h = im.size
    tp = test.load()

    alpha = [[255] * w for _ in range(h)]

    # ONE FLOOD PER BACKDROP TONE, and a seed brings its OWN tone.
    # The first version gated seeds against the BORDER's colour, so a
    # seed dropped into a grey panel on a white page was rejected by the
    # very tolerance it existed to get around -- it could only ever
    # succeed where it was not needed. A seed means "this pixel is
    # backdrop"; the honest reading is to believe it and take the colour
    # from under it.
    tones = [(_bg, "border")]
    for sx, sy in seeds:
        if 0 <= sx < w and 0 <= sy < h:
            tones.append((tp[sx, sy], (sx, sy)))

    for bg, where in tones:
        seen = bytearray(w * h)
        queue = deque()

        def offer(x, y):
            if 0 <= x < w and 0 <= y < h and not seen[y * w + x]:
                if _dist(tp[x, y], bg) <= hi:
                    seen[y * w + x] = 1
                    queue.append((x, y))

        if where == "border":
            for x in range(w):
                offer(x, 0)
                offer(x, h - 1)
            for y in range(h):
                offer(0, y)
                offer(w - 1, y)
        else:
            offer(*where)

        def flood():
            while queue:
                x, y = queue.popleft()
                d = _dist(tp[x, y], bg)
                a = 0 if d <= lo else int(255 * (d - lo) / (hi - lo))
                if a < alpha[y][x]:
                    alpha[y][x] = a
                for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                    offer(nx, ny)

        flood()

        if pockets:
            # Backdrop the edge could not reach because she encloses it
            # -- between her legs, inside a sleeve. Only ever takes
            # pixels that ARE the backdrop colour, so it is safe when
            # she wears nothing like it, and it is exactly what ate a
            # white cape when she did.
            for y in range(h):
                for x in range(w):
                    if not seen[y * w + x] and _dist(tp[x, y], bg) <= lo:
                        seen[y * w + x] = 1
                        queue.append((x, y))
                        flood()

    mask = Image.new("L", (w, h))
    mp = mask.load()
    for y in range(h):
        row = alpha[y]
        for x in range(w):
            mp[x, y] = row[x]
    out = im.convert("RGBA")
    out.putalpha(mask)
    if halo:
        out = unfringe(out, _bg)
    if trim:
        out = trim_to_art(out, trim)
    return out


def sanity(cut, bg, lo=14):
    """How much survived, and the one failure a number can actually see.

    WHAT THIS DELIBERATELY DOES NOT CLAIM: that it can tell when the
    fill ate the character. Two versions tried -- "is the middle of the
    picture full" failed a perfect cut of a two-figure sheet, where the
    middle is the gap between them; "is the fullest band full" then
    passed a cut that had visibly destroyed her, because the backdrop it
    left behind filled the band instead. A check that fires on a right
    answer and stays quiet on a wrong one is worse than no check.

    So it reports the numbers, flags the one thing it can be sure of,
    and the run writes a contact sheet to be LOOKED at. For image work
    that is the only check this repo has ever found that holds, and it
    has now been re-derived about fifteen times.
    """
    w, h = cut.size
    a = cut.getchannel("A").load()
    step = max(1, min(w, h) // 120)
    cells = [(x, y) for y in range(0, h, step) for x in range(0, w, step)]
    kept = sum(1 for x, y in cells if a[x, y] > 8)
    solid = sum(1 for x, y in cells if a[x, y] > 200)
    pct = 100.0 * kept / len(cells)
    solid_pct = 100.0 * solid / len(cells)
    # A CORNER STILL THE BACKDROP COLOUR means no cut happened at all --
    # a wrong tolerance, or art whose backdrop is not flat. It asks
    # about the COLOUR, not just the opacity: the first version read "a
    # corner is always backdrop" and failed three perfect cuts, because
    # in this art the corners are ghosts, blue flame and graveyard rock.
    rgb = cut.convert("RGB").load()
    stuck = sum(1 for x, y in ((0, 0), (w - 1, 0), (0, h - 1), (w - 1, h - 1))
                if a[x, y] > 200 and _dist(rgb[x, y], bg) <= lo)
    note = "BACKDROP LEFT BEHIND -- %d corner(s)" % stuck if stuck else "look"
    return pct, solid_pct, note


def contact_sheet(dst, names, width=1100):
    """One picture of every cut, on a checkerboard, so looking is one tap.

    Ghost reads this on a phone. "Open seven PNGs and check the alpha"
    is not a thing that happens; opening one is.
    """
    from PIL import ImageDraw
    if not names:
        return None
    cols = min(4, len(names))
    rows = (len(names) + cols - 1) // cols
    cw = width // cols
    ch = int(cw * 1.3)
    sheet = Image.new("RGB", (cw * cols, ch * rows), (255, 255, 255))
    draw = ImageDraw.Draw(sheet)
    box = max(8, cw // 22)
    for y in range(0, ch * rows, box):
        for x in range(0, cw * cols, box):
            if (x // box + y // box) % 2:
                draw.rectangle([x, y, x + box - 1, y + box - 1],
                               fill=(198, 198, 206))
    for i, name in enumerate(names):
        im = Image.open(os.path.join(dst, name + ".png"))
        im.thumbnail((cw - 12, ch - 12), Image.LANCZOS)
        sheet.paste(im, ((i % cols) * cw + (cw - im.width) // 2,
                         (i // cols) * ch + (ch - im.height) // 2), im)
    out = os.path.join(dst, "_CONTACT_SHEET.png")
    sheet.save(out, optimize=True)
    return out


def split_figures(cut, threshold=48, pad=4):
    """A two-outfit sheet -> one image per figure, on ONE shared canvas.

    NOT A VERTICAL CUT. The figures overlap in x -- on Yuzu's sheet the
    right one's raised fist crosses into the left one's column -- so the
    thinnest column still left a scrap of her hand beside the wrong
    girl. They are separate connected components, though, and nothing
    else in the picture is.

    ONE CANVAS ACROSS ALL OF THEM, registered on the HEAD. Each figure
    is pasted at the same offset from its head centre and its top of
    head, into a canvas sized by the union. That is the V-Pet lesson --
    one box across every state of a character, or she changes size when
    her outfit does -- and here it is worse than cosmetic: the same girl
    at two scales reads as a glitch rather than a change of clothes.
    """
    from collections import deque
    w, h = cut.size
    a = cut.getchannel("A").load()
    seen = bytearray(w * h)
    blobs = []
    for sy in range(h):
        for sx in range(w):
            if a[sx, sy] < threshold or seen[sy * w + sx]:
                continue
            q = deque([(sx, sy)])
            seen[sy * w + sx] = 1
            cells = []
            while q:
                x, y = q.popleft()
                cells.append((x, y))
                for nx, ny in ((x+1, y), (x-1, y), (x, y+1), (x, y-1),
                               (x+1, y+1), (x-1, y-1), (x+1, y-1), (x-1, y+1)):
                    if 0 <= nx < w and 0 <= ny < h and not seen[ny*w+nx] \
                            and a[nx, ny] >= threshold:
                        seen[ny*w+nx] = 1
                        q.append((nx, ny))
            blobs.append(cells)
    if not blobs:
        return []
    biggest = max(len(b) for b in blobs)
    figures = [b for b in blobs if len(b) > biggest * 0.25]
    figures.sort(key=lambda b: min(p[0] for p in b))

    marks = []
    for cells in figures:
        xs = [p[0] for p in cells]
        ys = [p[1] for p in cells]
        top = min(ys)
        head = [p[0] for p in cells if p[1] < top + max(8, (max(ys)-top)//12)]
        marks.append((cells, sum(head)/len(head), top,
                      min(xs), max(xs)+1, max(ys)+1))
    left = min(x0 - hc for _, hc, _, x0, _, _ in marks)
    right = max(x1 - hc for _, hc, _, _, x1, _ in marks)
    bottom = max(y1 - top for _, _, top, _, _, y1 in marks)
    cw, ch = int(right - left) + 2*pad, int(bottom) + 2*pad
    origin = -left + pad

    out = []
    for cells, hc, top, _, _, _ in marks:
        # MASK BY THE COMPONENT, then dilate, so the anti-aliased fringe
        # comes back. A bare mask at the threshold shaves the soft edge
        # and leaves a hard one.
        m = Image.new("L", (w, h), 0)
        mp = m.load()
        for x, y in cells:
            mp[x, y] = 255
        m = m.filter(ImageFilter.MaxFilter(5))
        only = cut.copy()
        only.putalpha(Image.composite(cut.getchannel("A"),
                                      Image.new("L", (w, h), 0), m))
        canvas = Image.new("RGBA", (cw, ch), (0, 0, 0, 0))
        canvas.paste(only, (int(round(origin - hc)), pad - top), only)
        out.append(canvas)
    return out


def convert_all(src=None, dst=None):
    """Every picture in ui/art_in/ -> a transparent PNG in ui/art_out/."""
    src, dst = src or ART_IN, dst or ART_OUT
    if not os.path.isdir(src):
        return []
    os.makedirs(dst, exist_ok=True)
    done = []
    for entry in sorted(os.listdir(src)):
        stem, ext = os.path.splitext(entry)
        if ext.lower() not in EXTS or entry.startswith("."):
            continue
        how = dict(DEFAULTS)
        how.update(RECIPES.get(stem, {}))
        source = Image.open(os.path.join(src, entry))
        cut = lift(source, **how)
        _, _, bg = prepare(source, how["denoise"])
        out = os.path.join(dst, stem + ".png")
        cut.save(out, optimize=True)
        done.append((stem, cut.size) + sanity(cut, bg, how["lo"]))
    contact_sheet(dst, [d[0] for d in done])
    return done


def _report(rows):
    if not rows:
        print("Nothing to do. Put art in ui/art_in/ and run this again.")
        return 0
    bad = [r for r in rows if r[4] != "look"]
    # THE VERDICT GOES FIRST. Written down three times in CLAUDE.md and
    # got it wrong anyway twice, so it is the opening line here.
    print("%s  %d picture%s cut -> ui/art_out/"
          % ("PROBLEM." if bad else "DONE.", len(rows),
             "" if len(rows) == 1 else "s"))
    print()
    for stem, size, pct, solid, note in rows:
        print("  %-20s %4dx%-4d  kept %4.0f%%  solid %3.0f%%  %s"
              % (stem, size[0], size[1], pct, solid, note))
    print()
    print("  NOW LOOK AT IT:  ui/art_out/_CONTACT_SHEET.png")
    print("  The numbers cannot tell you whether the fill ate the")
    print("  character -- her costume being the backdrop colour is the")
    print("  one real limit. If a cut lost part of her, give that file a")
    print("  RECIPES entry with a smaller `hi`; if a panel is left")
    print("  behind, add a `seed` inside it.")
    return 1 if bad else 0


if __name__ == "__main__":
    if Image is None:
        print("This one needs Pillow:  pip install --user Pillow")
        print("It is a workbench tool -- the deck never imports it.")
        sys.exit(2)
    sys.exit(_report(convert_all()))
