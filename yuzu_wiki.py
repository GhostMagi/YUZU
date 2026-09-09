#!/usr/bin/env python3
"""Offline encyclopedia lookup, for grounding her answers in real facts.

Talks to a local `kiwix-serve` over HTTP with nothing but the standard
library -- same rule as yuzu_brain.py, so this still runs in Pydroid on
a phone with nothing installed.

    python3 yuzu_wiki.py black holes      # look something up
    python3 yuzu_wiki.py --check          # is the wiki reachable

Start the server first with:  ~/YUZU/wiki

WHY THIS EXISTS: she is a character who lives on a deck with no
internet. Everything she "knows" is whatever a 3B model memorised,
which is thin and confidently wrong at the edges. A ZIM archive on the
NVMe is real, checkable text sitting right next to her -- so `/wiki`
hands her facts to answer FROM, in her own voice, still entirely
offline.
"""
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

BASE = "http://127.0.0.1:8080"
TIMEOUT = 6
MAX_CHARS = 700          # enough to answer from, small enough not to
                         # blow out the 4096-token context on the Orin


class _Extract(HTMLParser):
    """Pull readable prose out of a Kiwix article page.

    Deliberately hand-rolled: BeautifulSoup would be the sane choice
    anywhere else, but this project installs nothing and that property
    is what lets the whole brain run on the phone.
    """

    SKIP = {"script", "style", "sup", "table", "figure", "nav"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []
        self.depth = 0          # inside something we are ignoring
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth += 1
        elif tag in ("h1", "title") and not self.title:
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth:
            self.depth -= 1
        elif tag in ("h1", "title"):
            self._in_title = False

    def handle_data(self, data):
        if self._in_title and not self.title:
            self.title = data.strip()
        elif not self.depth:
            self.parts.append(data)

    def text(self):
        joined = " ".join(self.parts)
        # Kiwix pages carry a lot of whitespace and bracketed citation
        # residue. Neither survives being read out loud, and neither
        # helps a 3B answer a question.
        joined = re.sub(r"\[\s*\d+\s*\]", " ", joined)
        return re.sub(r"\s+", " ", joined).strip()


def _get(path, timeout=TIMEOUT):
    url = BASE + path
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return response.read().decode("utf-8", "replace")


def available():
    """True when a kiwix-serve is answering locally."""
    try:
        _get("/", timeout=2)
        return True
    except Exception:
        return False


def _suggest(term):
    """Ask Kiwix for matching article paths.

    Two endpoints because kiwix-serve has changed shape across
    versions and this project cannot pin the one on his board: newer
    builds answer /suggest with JSON, older ones only have /search
    returning HTML. Try the clean one, fall back to scraping links.
    """
    quoted = urllib.parse.quote(term)
    try:
        raw = _get(f"/suggest?term={quoted}")
        hits = json.loads(raw)
        paths = [h["path"] for h in hits
                 if isinstance(h, dict) and h.get("path")]
        if paths:
            return paths
    except Exception:
        pass

    try:
        page = _get(f"/search?pattern={quoted}")
    except Exception:
        return []
    # Article links look like /content/<book>/A/<Article> or /<book>/A/...
    found = re.findall(r'href="(/[^"]*?/A/[^"#?]+)"', page)
    seen, paths = set(), []
    for href in found:
        cleaned = html.unescape(href)
        if cleaned not in seen:
            seen.add(cleaned)
            paths.append(cleaned)
    return paths


def look_up(term, max_chars=MAX_CHARS):
    """(title, extract) for a term, or (None, reason) if it can't.

    NEVER raises. A failed lookup mid-conversation must degrade to a
    sentence she can react to, not a traceback that ends the chat.
    """
    term = (term or "").strip()
    if not term:
        return None, "Say what to look up: /wiki black holes"
    if not available():
        return None, ("The wiki isn't running. Start it in another "
                      "terminal with:  ~/YUZU/wiki")

    try:
        paths = _suggest(term)
    except Exception as exc:
        return None, f"The wiki is up but the search failed: {exc}"
    if not paths:
        return None, f"Nothing in the archive about '{term}'."

    for path in paths[:3]:
        if not path.startswith("/"):
            path = "/" + path
        try:
            page = _get(path)
        except Exception:
            continue
        parser = _Extract()
        parser.feed(page)
        text = parser.text()
        if len(text) < 80:          # a stub or a redirect, try the next
            continue
        title = parser.title or term
        if len(text) > max_chars:
            # Cut on a sentence so she is never handed half a clause.
            cut = text[:max_chars]
            stop = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
            text = cut[:stop + 1] if stop > max_chars // 2 else cut + "..."
        return title, text

    return None, f"Found '{term}' but couldn't read the article."


def as_context(term):
    """One user-turn string that hands her facts to answer FROM.

    Phrased as something the USER says, not as a system instruction:
    the whole prompt architecture here assumes the system block is her
    character and everything else is conversation. A wall of
    encyclopedia text arriving as a system message is exactly how a
    character turns into a search engine -- the assistant-collapse
    failure this repo already measured once.
    """
    title, body = look_up(term)
    if title is None:
        return None, body
    return (f"I looked up {title} and it says: {body}\n\n"
            f"Tell me about it in your own words."), None


def _cli(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] == "--check":
        print("wiki is UP" if available()
              else f"no kiwix-serve answering at {BASE}\nstart it: ~/YUZU/wiki")
        return 0 if available() else 1
    title, body = look_up(" ".join(argv))
    if title is None:
        print(body)
        return 1
    print(f"{title}\n\n{body}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
