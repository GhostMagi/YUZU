#!/usr/bin/env python3
"""Fetch another Kiwix archive onto the board, in the background.

    ~/YUZU/wiki --get wikipedia_en_all_mini

Ghost, Sept 23: "i wana get a few more wikipedia files for her but i
dont think ill need 100gb worth. Maybe just some useful files from the
same way we got em last time. (Which i cant recall how we did it)"

NOTHING IN THIS REPO RECORDED HOW. The Simple English archive arrived in
a chat this repo never saw. So this is the way, written down where the
next session will find it.

THIS IS MAINTENANCE, NOT HER. It lives in its own module, outside the
four her turn runs through, because her prompt tells her nothing she
does reaches the internet and a derived test holds those four to it.
Fetching an archive reaches library.kiwix.org, the way `pull` reaches
github: something he starts, never something she does mid-reply.

THE FILENAME COMES FROM KIWIX, NEVER FROM MEMORY. Archives are dated
(`..._2026-07.zim`) and replaced every few months, so a URL typed into a
doc or a chat is right until the next release and then a 404 -- an
unverified specific stated as a step, which cost an hour on the 8BitDo.
The live catalog is asked at the moment he runs it, the same rule `pull`
follows for Kokoro's release assets.

Stdlib only, like everything else here.
"""
import html
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request

import yuzu_wiki

# Overridable so the suite can hand it a local catalog. The real one is
# not reachable from where this was written, which CLAUDE.md says out
# loud rather than papering over.
LIBRARY = os.environ.get("YUZU_KIWIX_LIBRARY", "https://library.kiwix.org")
DISK_MARGIN = 1 << 30         # never fill the NVMe to the last byte
GET_LOG = "/tmp/wiki-get.log"

# The one worth having FOR HER, and the reason is arithmetic: a lookup
# hands her at most yuzu_wiki.MAX_CHARS of an article, which is its
# first paragraph. The "mini" flavour IS the first paragraph (and the
# infobox) of every article in English Wikipedia -- everything she can
# use, at a small fraction of the full archive's size.
FOR_HER = "wikipedia_en_all_mini"


def find_download(key):
    """((filename, url, bytes), None) for the newest release of a book,
    or (None, reason). Asks the live Kiwix catalog; never raises.

    The catalog files releases under the book's NAME, which is the stem
    minus its flavour -- `wikipedia_en_all_mini` lives under
    `wikipedia_en_all` beside `_maxi` and `_nopic`. So the stem is asked
    for first and then shortened a word at a time, and only an entry
    whose own filename has exactly the stem he asked for is taken."""
    key = yuzu_wiki._stem(key).lower()
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]*", key or ""):
        return None, ("Say which archive, like:  ~/YUZU/wiki --get %s"
                      % FOR_HER)
    names, parts = [], key.split("_")
    for cut in range(len(parts), max(len(parts) - 3, 1) - 1, -1):
        names.append("_".join(parts[:cut]))
    for name in names:
        url = "%s/catalog/v2/entries?name=%s&count=-1" % (
            LIBRARY, urllib.parse.quote(name))
        try:
            with urllib.request.urlopen(url, timeout=20) as got:
                page = got.read().decode("utf-8", "replace")
        except Exception as exc:
            return None, ("Could not reach the Kiwix library (%s). The "
                          "board needs the internet for this one." % exc)
        releases = []
        for entry in re.findall(r"<entry>(.*?)</entry>", page, re.S):
            for link in re.findall(r"<link\b[^>]*>", entry):
                if "acquisition" not in link:
                    continue
                href = re.search(r'href="([^"]+)"', link)
                size = re.search(r'length="(\d+)"', link)
                if not href:
                    continue
                where = urllib.parse.urljoin(LIBRARY + "/",
                                             html.unescape(href.group(1)))
                if where.endswith(".meta4"):
                    # The .meta4 is a mirror list; the same path without
                    # it is the file, redirected to the nearest mirror.
                    where = where[:-len(".meta4")]
                filename = os.path.basename(urllib.parse.urlparse(where).path)
                if (yuzu_wiki._stem(filename) == key
                        and filename.endswith(".zim")):
                    releases.append((filename, where,
                                     int(size.group(1)) if size else 0))
        if releases:
            # Dated names sort by date, so the biggest name is the newest.
            return max(releases), None
    return None, ("The Kiwix library has no archive called '%s'. The "
                  "names are on library.kiwix.org -- the part before the "
                  "date, like %s." % (key, FOR_HER))


def _size(n):
    return ("%.1f GB" % (n / 1e9)) if n >= 1e9 else ("%d MB" % (n // 10**6))


# THE DOWNLOAD RUNS BY ITSELF, and that is the whole of the design.
# A foreground `kiwix-serve` on his serial link read as a frozen board
# and cost a power-cycle; a foreground multi-gigabyte download would
# hold his only terminal for an hour. So it runs in a new session (no
# hangup when the cable drops), `-C -` so the same line CARRIES ON after
# WiFi or power goes, `.part` until it is whole so `wiki` never serves
# half an archive, and the wiki restarts itself at the end so the new
# book is simply there.
#
# The URL, the path and the script arrive as ARGUMENTS ($1 $2 $3), never
# pasted into the command text, so nothing the catalog says can become
# shell.
CHAIN = ('curl -sS -L --fail --retry 5 -C - -o "$1.part" "$2" '
         '&& mv "$1.part" "$1" && rm -f "$1.part.size" '
         '&& "$3" --off && "$3"')


def _running(part):
    """Is a download already writing this file? curl's own command line
    carries the `.part` path as one whole argument; nothing else's does.
    Read straight out of /proc and matched EXACTLY, rather than handed
    to pgrep as a pattern where every dot in the path is a wildcard."""
    want = part.encode()
    try:
        pids = [p for p in os.listdir("/proc") if p.isdigit()]
    except OSError:
        return False
    for pid in pids:
        try:
            with open("/proc/%s/cmdline" % pid, "rb") as fh:
                if want in fh.read().split(b"\0"):
                    return True
        except OSError:
            continue
    return False


def get(key, start=True):
    """Fetch one archive in the background. Returns (exit code, lines),
    verdict first."""
    found, why = find_download(key)
    if not found:
        return 1, ["NOT DOWNLOADING.", why]
    filename, url, size = found
    have = yuzu_wiki._zims()
    same = [p for p in have if yuzu_wiki._stem(p) == yuzu_wiki._stem(filename)]
    # Beside the archives he already has, so they stay in one place; a
    # new release of a book he has goes next to the old one.
    if same:
        folder = os.path.dirname(same[0])
    elif have:
        folder = os.path.dirname(have[0])
    else:
        folder = os.path.join(yuzu_wiki.ROOTS[0], "zims")
    dest = os.path.join(folder, filename)
    if os.path.exists(dest):
        return 0, ["ALREADY HERE. %s is on the board." % filename]
    os.makedirs(folder, exist_ok=True)
    part = dest + ".part"
    # PASTED TWICE IS THE LIKELY CASE, not the odd one: he has told us
    # he forgets, and the answer to "is it still going?" is to paste it
    # again. Two curls appending to one .part is a corrupt archive that
    # looks finished, so a second start is refused, not queued.
    if _running(part):
        return 0, ["ALREADY DOWNLOADING %s." % filename,
                   "  How far:   ~/YUZU/wiki --status"]
    started = os.path.getsize(part) if os.path.exists(part) else 0
    free = shutil.disk_usage(folder).free
    if size and free < size - started + DISK_MARGIN:
        return 1, ["NOT ENOUGH ROOM. %s is %s and there is %s free."
                   % (filename, _size(size), _size(free)),
                   "Nothing was downloaded."]
    lines = ["DOWNLOADING %s -- %s%s." % (
                 filename, _size(size) if size else "size unknown",
                 (", carrying on from %s" % _size(started)) if started else ""),
             "  into " + folder,
             "",
             "It runs by itself. You can close this, or unplug the cable.",
             "  How far:   ~/YUZU/wiki --status",
             "  If WiFi or power drops, paste the same line again and it",
             "  carries on from where it got to.",
             "When it finishes, the wiki restarts with it on."]
    if same:
        lines += ["", "The older copy stays until you delete it. The wiki "
                      "uses the newest:", "  " + same[0]]
    if start:
        if size:
            with open(part + ".size", "w") as f:
                f.write(str(size))
        script = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              "wiki")
        with open(GET_LOG, "a") as log:
            subprocess.Popen(["bash", "-c", CHAIN, "wiki-get", dest, url,
                              script], stdin=subprocess.DEVNULL, stdout=log,
                             stderr=log, start_new_session=True)
    return 0, lines


def _cli(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print()
        print("  Say which archive. The one worth having for her:")
        print("    ~/YUZU/wiki --get " + FOR_HER)
        print()
        return 1
    code, lines = get(" ".join(argv))
    print()
    for line in lines:
        print("  " + line if line else "")
    print()
    return code


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
