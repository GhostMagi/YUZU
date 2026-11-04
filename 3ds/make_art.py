#!/usr/bin/env python3
"""The girls' pictures for the 3DS app, baked into it.

    python3 3ds/make_art.py        rewrite 3ds/data/<who>.bin,
                                   3ds/source/art.h, the HOME menu's
                                   icon and banner, and the banner's chime

THE 3DS'S TOP SCREEN IS 400x240 and its framebuffer is the screen turned
on its side: column by column, bottom to top, two bytes a pixel (RGB565,
little end first) once libctru's console owns the screen. So each girl
is composed at 400x240 here, once, and written in EXACTLY that order --
the app copies her onto the screen with one memcpy and decodes nothing.

EACH GIRL IS FRAMED THE WAY HER OTHER SCREENS FRAME HER, never anew:

  four   her page: all of her on black. Black IS her backdrop (her page
         blends her with `screen`), so the bars either side are her.
  zero   the cube's close-up: head to chest, cut from the top of her
         picture, because shown whole she is a strip down the middle.
  rei    the cube's close-up of her face, her twin's framing.
  yuzu   her page's portrait on her page's lavender room.
  saya   her resting face, his kaomoji, in her neon green on black with
         the page's CRT scanlines.

A girl with no picture here still gets a screen: the app draws her name
on a plain one. ABSENT RATHER THAN WRONG -- a new girl on the roster
never wears another girl's face. The roster decides who is on the 3DS;
this decides only what each one looks like.

GENERATED, AND COMMITTED ANYWAY, the cube's call: building the app must
not need PIL, and a test regenerates these and compares, so a picture
cannot drift from her art. Change a picture, run this, commit both.

WORKBENCH TOOL. PIL is needed here and nowhere else.
"""
import math
import pathlib
import struct
import sys
import wave

HERE = pathlib.Path(__file__).resolve().parent
UI = HERE.parent / "ui"
DATA = HERE / "data"
HEADER = HERE / "source" / "art.h"
W, H = 400, 240

# who -> (picture, how she is framed, her colour on the 3DS's console)
# The console has eight colours; each girl gets the one nearest her ink.
GIRLS = {
    "four": (UI / "four" / "four.jpg", "whole", 32),      # her green
    "yuzu": (UI / "yuzu" / "yuzu.png", "room", 35),       # hot pink
    "zero": (UI / "zero" / "zero.jpg", "close", 35),      # neon pink
    "saya": (UI / "sprites" / "idle.png", "crt", 32),     # neon green
    "rei":  (UI / "rei" / "rei.jpg", "face", 36),         # his cyan
}

# The cube's own numbers for the two close-ups (stackchan/make_art.py),
# so the 3DS and the cube frame them alike.
ZERO_TOP = 60
REI_CROP_W, REI_TOP = 600, 90

# Yuzu's room, her page's radial gradient (ui/yuzu.html), the same stops
# the cube draws.
ROOM = ((0.00, (0x5b, 0x4a, 0x82)), (0.46, (0x33, 0x29, 0x4a)),
        (1.00, (0x1c, 0x16, 0x29)))
SAYA_INK = (0x39, 0xff, 0x5e)


def _cover(img, box_w, box_h, top=None):
    """Cut `img` to the box's shape and scale it to fill the box.
    `top` pins where the cut starts from the top; centred otherwise."""
    from PIL import Image
    want = box_w / box_h
    if img.width / img.height > want:
        cw, ch = int(img.height * want), img.height
        x0, y0 = (img.width - cw) // 2, 0
    else:
        cw, ch = img.width, int(img.width / want)
        x0 = 0
        y0 = (img.height - ch) // 2 if top is None else min(top, img.height - ch)
    return img.crop((x0, y0, x0 + cw, y0 + ch)).resize((box_w, box_h),
                                                        Image.LANCZOS)


def _room():
    from PIL import Image
    img = Image.new("RGB", (W, H))
    px = img.load()
    cx, cy, rx, ry = W * 0.5, H * 0.06, W * 1.2, H * 0.9
    for y in range(H):
        for x in range(W):
            at = min(1.0, math.hypot((x - cx) / rx, (y - cy) / ry))
            s = 0 if at <= ROOM[1][0] else 1
            f = (at - ROOM[s][0]) / (ROOM[s + 1][0] - ROOM[s][0])
            px[x, y] = tuple(int(round(a + (b - a) * f))
                             for a, b in zip(ROOM[s][1], ROOM[s + 1][1]))
    return img


def compose(who):
    """Her 400x240 picture, as an RGB image."""
    from PIL import Image
    source, how, _ = GIRLS[who]
    if how == "whole":
        img = Image.open(source).convert("RGB")
        img = img.resize((img.width * H // img.height, H), Image.LANCZOS)
        out = Image.new("RGB", (W, H))
        out.paste(img, ((W - img.width) // 2, 0))
        return out
    if how == "close":
        img = Image.open(source).convert("RGB")
        return _cover(img, W, H, top=ZERO_TOP)
    if how == "face":
        img = Image.open(source).convert("RGB")
        x0 = (img.width - REI_CROP_W) // 2
        tall = REI_CROP_W * H // W
        return img.crop((x0, REI_TOP, x0 + REI_CROP_W, REI_TOP + tall)).resize(
            (W, H), Image.LANCZOS)
    if how == "room":
        # Shrunk with her alpha PREMULTIPLIED, or the cut-out's white edge
        # haloes her -- the cube learned it first.
        img = Image.open(source).convert("RGBA").convert("RGBa")
        tall = H - 6
        img = img.resize((img.width * tall // img.height, tall),
                         Image.LANCZOS).convert("RGBA")
        out = _room()
        out.paste(img, ((W - img.width) // 2, H - img.height), img)
        return out
    if how == "crt":
        img = Image.open(source).convert("RGBA")
        img = img.resize((360, 360 * img.height // img.width), Image.LANCZOS)
        out = Image.new("RGB", (W, H))
        ink = Image.new("RGB", img.size, SAYA_INK)
        out.paste(ink, ((W - img.width) // 2, (H - img.height) // 2),
                  img.split()[3])
        px = out.load()
        for y in range(0, H, 3):              # her page's 18% scanline
            for x in range(W):
                r, g, b = px[x, y]
                px[x, y] = (r * 82 // 100, g * 82 // 100, b * 82 // 100)
        return out
    raise ValueError(how)


def rgb565(r, g, b):
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def framebuffer(img):
    """The top screen's own byte order: column x, then row from the
    BOTTOM up -- fb[x * 240 + (239 - y)] -- two bytes each, low first."""
    px = img.load()
    out = bytearray(W * H * 2)
    i = 0
    for x in range(W):
        for y in range(H - 1, -1, -1):
            struct.pack_into("<H", out, i, rgb565(*px[x, y]))
            i += 2
    return bytes(out)


def header():
    lines = ["/* GENERATED by 3ds/make_art.py. Do not edit -- change a",
             " * picture and run the script. */",
             "#ifndef YUZU_ART_H",
             "#define YUZU_ART_H",
             "#include <stddef.h>",
             "#include <stdint.h>"]
    for who in GIRLS:
        lines.append('#include "%s_bin.h"' % who)
    lines += ["",
              "/* Each picture is the top screen's framebuffer, ready to copy. */",
              "#define ART_BYTES (400 * 240 * 2)",
              "",
              "typedef struct {",
              "    const char *who;      /* her name on the board */",
              "    const uint8_t *px;",
              "    /* bin2s writes each size as a `static const size_t`, which C",
              "     * cannot copy into a table, so the table keeps its address. */",
              "    const size_t *size;",
              "    int colour;           /* her console colour, 30-37 */",
              "} Art;",
              "",
              "static const Art ARTS[] = {"]
    for who, (_, _, colour) in GIRLS.items():
        lines.append('    { "%s", %s_bin, &%s_bin_size, %d },'
                     % (who, who, who, colour))
    lines += ["};",
              "#define ART_COUNT ((int)(sizeof ARTS / sizeof ARTS[0]))",
              "",
              "#endif"]
    return "\n".join(lines) + "\n"


def icon():
    """48x48 for the HOME menu. The app is YUZU, so it is her face, cut
    from her own 3DS picture -- rendered at 48 and looked at: Four's
    green at that size was a blur."""
    from PIL import Image
    return compose("yuzu").crop((142, 8, 256, 122)).resize((48, 48),
                                                            Image.LANCZOS)


def banner():
    """256x128 for the top screen when the app is picked in the HOME menu:
    every girl, side by side, each in her own strip."""
    from PIL import Image
    out = Image.new("RGB", (256, 128))
    n = len(GIRLS)
    for i, who in enumerate(GIRLS):
        x0, x1 = 256 * i // n, 256 * (i + 1) // n
        pic = compose(who)
        if GIRLS[who][1] == "crt":
            # HER WHOLE FACE, shrunk into her strip: cut to the strip's
            # shape it was one bar of green on black.
            face = pic.crop((20, 64, 380, 176))
            face = face.resize((x1 - x0, (x1 - x0) * face.height // face.width),
                               Image.LANCZOS)
            out.paste(face, (x0, (128 - face.height) // 2))
            continue
        out.paste(_cover(pic, x1 - x0, 128), (x0, 0))
    return out


def chime(path):
    """The HOME menu plays a banner's sound when the app is picked. Two
    soft notes, under a second -- a banner with no sound is allowed, but
    the tool that builds one wants a file."""
    rate = 22050
    frames = bytearray()
    for freq, dur in ((880.0, 0.18), (1318.5, 0.42)):
        n = int(rate * dur)
        for i in range(n):
            env = min(1.0, i / 200) * math.exp(-3.5 * i / n)
            s = int(5500 * env * math.sin(2 * math.pi * freq * i / rate))
            frames += struct.pack("<h", s)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(bytes(frames))


def main():
    DATA.mkdir(exist_ok=True)
    for who in GIRLS:
        (DATA / (who + ".bin")).write_bytes(framebuffer(compose(who)))
    HEADER.write_text(header())
    icon().save(HERE / "icon.png")
    banner().save(HERE / "banner.png")
    chime(HERE / "banner.wav")
    print("Wrote %d pictures, art.h, icon.png, banner.png and banner.wav."
          % len(GIRLS))
    return 0


if __name__ == "__main__":
    sys.exit(main())
