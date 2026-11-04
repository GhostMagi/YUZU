#!/bin/sh
# The HOME menu's copy of the app: yuzu3ds.elf, wrapped with its icon,
# its banner (the girls side by side, and a chime) and yuzu.rsf into
# yuzu3ds.cia.
#
# ONE COPY OF THIS RECIPE. `make cia` runs it, and so does the GitHub
# build (.github/workflows/3ds.yml) -- which compiles the program in
# devkitPro's image and packages it on a plain Ubuntu machine, because
# the two packaging tools want a newer system than that image has.
#
# Needs bannertool and makerom on the PATH, and `make` run first.
set -e
cd "$(dirname "$0")"

[ -f yuzu3ds.elf ] || { echo "No yuzu3ds.elf here. Run make first."; exit 1; }
for tool in bannertool makerom; do
    command -v "$tool" >/dev/null 2>&1 || { echo "$tool is not on the PATH."; exit 1; }
done

# The app's name, description and author are the Makefile's, so the
# .3dsx and the .cia can never disagree about what she is called.
setting() { sed -n "s/^$1[[:space:]]*:=[[:space:]]*//p" Makefile; }
title=$(setting APP_TITLE)
about=$(setting APP_DESCRIPTION)
author=$(setting APP_AUTHOR)
[ -n "$title" ] && [ -n "$about" ] && [ -n "$author" ] || {
    echo "The Makefile lost APP_TITLE, APP_DESCRIPTION or APP_AUTHOR."; exit 1; }

mkdir -p build
bannertool makebanner -i banner.png -a banner.wav -o build/banner.bnr
bannertool makesmdh -s "$title" -l "$about" -p "$author" -i icon.png \
    -o build/icon.icn
makerom -f cia -o yuzu3ds.cia -target t -exefslogo -elf yuzu3ds.elf \
    -rsf yuzu.rsf -icon build/icon.icn -banner build/banner.bnr
echo "built yuzu3ds.cia"
