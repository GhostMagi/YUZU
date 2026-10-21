"""His game, baked into the cube: stackchan/games/<game>.gbc -> game_rom.h.

Ghost, Oct 17: "Can we put my game on my stackchan cores slide-to-able
pages?" -- GHOSTRPG, his own Game Boy Color game. `~/YUZU/cube` runs
this into the build's OWN copy of the sketch at flash time, so the repo
carries the ROM once (512KB) and never a 2.6MB header of it, and
changing the game is dropping a different .gbc into stackchan/games/.

The header is checked before anything is written: a file that is not a
Game Boy cartridge (wrong size, a header checksum that does not add up)
is refused here, in words, rather than crashing the cube on the day.
No game written means the cube's game page says there is none; it never
stops her being flashed.
"""
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
GAMES = HERE / "games"
OUT_NAME = "game_rom.h"


def check(rom):
    """The cartridge's own header, or a sentence saying why not."""
    if len(rom) < 0x8000 or len(rom) % 0x4000:
        return "it is %d bytes, not a whole number of 16KB banks" % len(rom)
    total = 0
    for b in rom[0x134:0x14D]:
        total = (total - b - 1) & 0xFF
    if total != rom[0x14D]:
        return "its header checksum does not add up"
    return None


def title(rom):
    """The name in the cartridge header, as printable ASCII."""
    end = 0x143 if rom[0x143] & 0x80 else 0x144   # CGB carts lose a byte
    raw = bytes(rom[0x134:end]).split(b"\0")[0]
    return "".join(chr(c) for c in raw if 32 <= c < 127).strip() or "GAME"


def pick():
    games = sorted(p for p in GAMES.glob("*")
                   if p.suffix.lower() in (".gb", ".gbc"))
    return games[0] if games else None


def render(path):
    rom = path.read_bytes()
    problem = check(rom)
    if problem:
        raise ValueError("%s is not a game the cube can play: %s"
                         % (path.name, problem))
    lines = ["// GENERATED at flash time by stackchan/make_rom.py from",
             "// stackchan/games/%s. Not committed: the .gbc is." % path.name,
             "#pragma once",
             "#include <stdint.h>",
             "#define GAME_TITLE \"%s\"" % title(rom),
             "#define GAME_ROM_SIZE %d" % len(rom),
             # 4-byte aligned: the emulator reads 32 bits at a time where
             # it can, and the ESP32 faults on a misaligned word from flash.
             "alignas(4) static const uint8_t GAME_ROM[GAME_ROM_SIZE] = {"]
    for i in range(0, len(rom), 32):
        lines.append(",".join("%d" % b for b in rom[i:i + 32]) + ",")
    lines.append("};")
    return "\n".join(lines) + "\n"


def main(out_dir):
    game = pick()
    if not game:
        print("No game in stackchan/games/ -- the cube's game page will say so.")
        return 0
    try:
        text = render(game)
    except ValueError as e:
        print("NOT BAKED: %s" % e)
        return 1
    (pathlib.Path(out_dir) / OUT_NAME).write_text(text)
    print("Baked %s into the cube (%s)." % (title(game.read_bytes()), game.name))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else HERE / "cube"))
