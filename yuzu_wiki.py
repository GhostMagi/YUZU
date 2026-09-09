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
import os
import re
import subprocess
import sys
import time
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


# The book's short name. Modern kiwix-serve scopes /search and /suggest
# to a BOOK, and answers a bare query with nothing at all -- which is
# indistinguishable from "no such article" and is the likeliest reason
# `/wiki cats` came back empty on a Simple English Wikipedia.
_BOOK = None


def book_name(force=False):
    """The name kiwix-serve knows his archive by, or "" if it will not
    say. Asked once and remembered: it cannot change while the server
    is up, and every lookup would otherwise pay for it."""
    global _BOOK
    if _BOOK is not None and not force:
        return _BOOK
    _BOOK = ""
    for path in ("/catalog/v2/entries?count=-1", "/catalog/searchdescription.xml",
                 "/"):
        try:
            page = _get(path, timeout=6)
        except Exception:
            continue
        # The catalog gives it plainly; the root page only ever mentions
        # it inside a link. Both are worth trying before giving up.
        for pattern in (r"<name>([^<]+)</name>",
                        r"bookName=([^&\"'\s]+)",
                        r"/viewer#([^\"'?&/]+)",
                        r"/content/([^/\"'?#]+)"):
            found = re.search(pattern, page)
            if found:
                _BOOK = html.unescape(found.group(1)).strip()
                return _BOOK
    return _BOOK


def _article_links(page):
    """Article paths out of a search results page.

    **THE `/A/` REQUIREMENT WAS THE BUG.** The old regex demanded that
    namespace, and modern ZIMs do not have it -- articles live at
    `/content/<book>/<Article>` with nothing in between. So a search that
    worked returned links this could not see, and the answer came back
    `Nothing in the archive`, which reads as a missing article rather
    than as a parser that stopped matching.

    Now anything under /content/ or /A/ counts, and the obvious
    furniture is excluded by name rather than by shape."""
    out, seen = [], set()
    for href in re.findall(r'href="([^"]+)"', page):
        href = html.unescape(href)
        if not href.startswith("/"):
            continue
        if "/content/" not in href and "/A/" not in href:
            continue
        if any(skip in href for skip in ("/skin/", "/search?", "/suggest?",
                                         "/catalog/", "/random", "/viewer",
                                         ".css", ".js", ".png", ".svg")):
            continue
        if href not in seen:
            seen.add(href)
            out.append(href)
    return out


def _suggest(term):
    """Ask Kiwix for matching article paths.

    Several shapes, because kiwix-serve has changed across versions and
    this project cannot pin the one on his board. Each is cheap and the
    first that answers wins."""
    quoted = urllib.parse.quote(term)
    book = book_name()
    scoped = ("&books.name=" + urllib.parse.quote(book)) if book else ""

    for path in (f"/suggest?term={quoted}&count=10{scoped}",
                 f"/suggest?term={quoted}{scoped}",
                 f"/suggest?term={quoted}"):
        try:
            hits = json.loads(_get(path))
        except Exception:
            continue
        if isinstance(hits, dict):
            hits = hits.get("suggestions") or hits.get("items") or []
        paths = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            # `path` when it is offered; otherwise build one from the
            # title, which is what the newer JSON gives back.
            if hit.get("path"):
                where = hit["path"]
                paths.append(where if where.startswith("/") else "/" + where)
            elif hit.get("value") and book:
                paths.append("/content/%s/%s" % (
                    book, urllib.parse.quote(hit["value"].replace(" ", "_"))))
        if paths:
            return paths

    for path in (f"/search?books.name={urllib.parse.quote(book)}&pattern={quoted}"
                 if book else None,
                 f"/search?pattern={quoted}",
                 f"/search?books.filter.lang=eng&pattern={quoted}"):
        if not path:
            continue
        try:
            page = _get(path)
        except Exception:
            continue
        found = _article_links(page)
        if found:
            # LEARN THE BOOK FROM THE ANSWER. The catalog gave
            # `wikipedia_en_simple_all` on his board while the real
            # articles live under `wikipedia_en_simple_all_nopic_2026-05`
            # -- close enough to look right, wrong enough that every
            # scoped query would miss. An article path that actually
            # exists is ground truth; a catalogue entry is a claim.
            global _BOOK
            real = re.match(r"/content/([^/]+)/", found[0])
            if real:
                _BOOK = real.group(1)
            return found
    return []


def diagnose():
    """What the server ACTUALLY says, short enough for a phone terminal.

    The 12-line diagnostic that would have settled this a day ago was
    pasted into her chat instead of the shell, and that is what started
    the night with no way out. One word, four lines of output, no
    paste."""
    lines = []
    try:
        _get("/", timeout=4)
        lines.append("server:   answering on " + BASE)
    except Exception as exc:
        lines.append("server:   NOT ANSWERING (%s)" % exc)
        lines.append("          start it with:  ~/YUZU/wiki")
        return lines
    book = book_name(force=True)
    lines.append("book:     " + (book or "COULD NOT FIND ONE -- see below"))
    for label, path in (("suggest", "/suggest?term=cat&count=5"),
                        ("search", "/search?pattern=cat")):
        try:
            body = _get(path, timeout=6)
            links = len(_article_links(body))
            lines.append("%-9s %d bytes, %d article links" %
                         (label + ":", len(body), links))
        except Exception as exc:
            lines.append("%-9s FAILED (%s)" % (label + ":", exc))
    hits = _suggest("cat")
    lines.append("result:   %d paths%s" %
                 (len(hits), ("  first: " + hits[0]) if hits else ""))

    # THE VERDICT GOES FIRST. Measured on his board, Sept 10: this
    # printed `suggest: FAILED (404)` in the middle -- one endpoint his
    # kiwix build does not have, fully covered by the fallback -- above a
    # last line saying 25 articles were found. He read it as broken.
    #
    # That is the third time in this project I have reported the layers
    # AROUND the answer and put the answer last: `pad --status` on a
    # working controller, `face` on a serving server, and now this. The
    # rule is not new and it was mine to follow.
    if hits:
        head = ["WORKING. %d articles found for 'cat'." % len(hits),
                "A FAILED line below is one endpoint this kiwix build",
                "does not have. Something else answered. Ignore it.", ""]
    else:
        head = ["NOT WORKING -- nothing came back for 'cat'.",
                "The lines below say which part went quiet.", ""]
    return head + lines


def start_server(wait=12):
    """Start ~/YUZU/wiki and wait for it, returning True if it came up.

    MEASURED, Sept 9. `/wiki ice cream` correctly reported "The wiki
    isn't running" -- accurate, and still a dead end, because he has
    ONE serial terminal. Fixing it meant quitting the chat, starting a
    server, and starting the chat again, mid-sentence.

    Same rule the app launcher already follows: a request that lands on
    a dead port should START the thing, not report on it. `wiki` is
    idempotent and backgrounds itself, so calling it costs nothing when
    it is already up.
    """
    script = os.path.join(os.path.dirname(os.path.abspath(__file__)), "wiki")
    if not os.path.exists(script):
        return False
    try:
        subprocess.run([script], capture_output=True, timeout=wait + 5)
    except Exception:
        return False
    for _ in range(wait):
        if available():
            return True
        time.sleep(1)
    return False


def look_up(term, max_chars=MAX_CHARS):
    """(title, extract) for a term, or (None, reason) if it can't.

    NEVER raises. A failed lookup mid-conversation must degrade to a
    sentence she can react to, not a traceback that ends the chat.
    """
    term = (term or "").strip()
    if not term:
        return None, "Say what to look up: /wiki black holes"
    if not available():
        if not start_server():
            return None, ("The wiki won't start. Try it by hand to see "
                          "why:  ~/YUZU/wiki")

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
    # THE LENGTH CLAUSE. Measured Sept 10: asked about Munchkin cats she
    # gave three paragraphs and truncated mid-sentence on num_predict.
    # This turn asked for "your own words" and said nothing about how
    # MANY, while her brevity rule is about ordinary conversation -- so
    # handed an encyclopedia she summarised at encyclopedia length.
    #
    # A reply that long also does not fit a 1024x600 face screen, which
    # is why the UI work and the brevity work are the same problem.
    #
    # One variable, no code, no persona edit. If it is not enough the
    # next step is ONE EXAMPLE of answering from a lookup -- the lever
    # that has worked three times here -- and that one does change the
    # composed prompt.
    return (f"I looked up {title} and it says: {body}\n\n"
            f"Tell me about it in your own words, in a sentence or "
            f"two."), None


def _cli(argv):
    if not argv or argv[0] in ("-h", "--help"):
        print(__doc__)
        return 0
    if argv[0] in ("--test", "--why"):
        # One word instead of a twelve-line paste. The paste is what
        # went into her chat by mistake and started the night that cost
        # two power cycles.
        print()
        for line in diagnose():
            print("   ", line)
        print()
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
