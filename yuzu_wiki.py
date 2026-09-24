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


FOOTER = ("Category:", "Categories:", "Hidden categories:",
          "This page is issued from", "This article is issued from")


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
        # THE PAGE FOOTER IS NOT THE ARTICLE. The mini archive ends every
        # page with its categories and a licence line -- measured on his
        # board, Sept 23: "Category: Domain Name System Security
        # Extensions Hidden categories: ... This page is issued from
        # Wikipedia ... Creative Commons". Handed to her, that is what
        # she reads aloud. Everything from the first footer marker on
        # goes.
        cut = [joined.find(m) for m in FOOTER if joined.find(m) > 0]
        if cut:
            joined = joined[:min(cut)]
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
_BOOK_AT = 0.0
# HOW LONG A CHOICE OF BOOK IS TRUSTED. It used to be forever, on the
# reasoning that it "cannot change while the server is up" -- true
# while `wiki` served one archive. It serves every archive now, and a
# download finishing restarts it with one more, so the book she should
# be reading can change under a face server that has been up all day.
# Two minutes, the same as her inventory: a new book is noticed without
# a restart, and a lookup never pays for the catalog twice in a row.
_BOOK_TTL = 120


def _catalog():
    """Every book the server holds: [{name, id, articles}], or [].

    `id` is what the server puts in its article URLs --
    `wikipedia_en_simple_all_nopic_2026-05` -- and it is the only name
    that scopes a search on a modern kiwix-serve. `name` is the book's
    own claim about itself, `wikipedia_en_simple_all`, which is not.
    Verified against a real kiwix-serve 3.5 with three real ZIMs: a
    search scoped by `name` came back EMPTY and /suggest answered 404
    "No such book" -- the exact 404 his board printed on Sept 10."""
    try:
        page = _get("/catalog/v2/entries?count=-1", timeout=6)
    except Exception:
        return []
    books = []
    for entry in re.findall(r"<entry>(.*?)</entry>", page, re.S):
        name = re.search(r"<name>([^<]+)</name>", entry)
        where = re.search(r'href="/content/([^/"?#]+)"', entry)
        count = re.search(r"<articleCount>(\d+)</articleCount>", entry)
        if name or where:
            books.append({
                "name": html.unescape(name.group(1)).strip() if name else "",
                "id": html.unescape(where.group(1)) if where else "",
                "articles": int(count.group(1)) if count else 0})
    return books


def choose_book(books):
    """The one book /wiki reads from: THE BIGGEST WIKIPEDIA ON THE BOARD.

    **IT USED TO BE WHICHEVER FILE WAS DOWNLOADED LAST.** `wiki` served
    only the newest .zim, so fetching iFixit after Simple English
    Wikipedia silently turned `/wiki cats` into a search of repair
    guides -- reproduced with real archives, it came back "Nothing in
    the archive about 'cats'". A lookup is an encyclopedia question, so
    the encyclopedia is chosen on purpose: the Wikipedia with the most
    articles, whatever order they arrived in. Only when there is no
    Wikipedia at all does the biggest book of any kind stand in.

    Chosen by COUNT, never by name: `wikipedia_en_all_mini` beating
    `wikipedia_en_simple_all` is the whole English Wikipedia against
    the Simple English one, read off the catalog rather than written
    down here as a preference."""
    if not books:
        return None
    pool = [b for b in books if b["name"].lower().startswith("wikipedia")
            or b["id"].lower().startswith("wikipedia")] or books
    return max(pool, key=lambda b: b["articles"])


def book_name(force=False):
    """The name kiwix-serve knows her encyclopedia by, or "" if it will
    not say. Remembered for _BOOK_TTL seconds."""
    global _BOOK, _BOOK_AT
    if _BOOK is not None and not force and time.time() - _BOOK_AT < _BOOK_TTL:
        return _BOOK
    _BOOK, _BOOK_AT = "", time.time()
    best = choose_book(_catalog())
    if best:
        _BOOK = best["id"] or best["name"]
        return _BOOK
    # An older kiwix-serve with no usable catalog: fall back to the
    # first name any page will admit to, which is what this always did.
    for path in ("/catalog/searchdescription.xml", "/"):
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


def _book_of(path):
    got = re.match(r"/content/([^/]+)/", path)
    return got.group(1) if got else ""


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
    """Ask Kiwix for matching article paths IN HER BOOK.

    Several shapes, because kiwix-serve has changed across versions and
    this project cannot pin the one on his board. Each is cheap and the
    first that answers wins."""
    quoted = urllib.parse.quote(term)
    book = book_name()
    q_book = urllib.parse.quote(book)

    shapes = []
    if book:
        # `content=` is what /suggest wants on kiwix-serve 3.5 -- the
        # `books.name=` form answers 404 there, measured.
        shapes += [f"/suggest?term={quoted}&count=10&content={q_book}",
                   f"/suggest?term={quoted}&count=10&books.name={q_book}",
                   f"/suggest?term={quoted}&books.name={q_book}"]
    shapes.append(f"/suggest?term={quoted}")
    for path in shapes:
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
            # "containing 'cat'..." is an offer to SEARCH, not an
            # article, and building a path out of it asks for a page
            # called `cat_` that does not exist.
            if hit.get("kind") == "pattern":
                continue
            # `path` when it is offered; otherwise build one from the
            # title, which is what the newer JSON gives back. A RELATIVE
            # path is relative to the BOOK -- kiwix-serve 3.5 answers
            # `"path": "Cat"`, and "/Cat" is not a page.
            if hit.get("path"):
                where = hit["path"]
                if where.startswith("/"):
                    paths.append(where)
                elif book:
                    paths.append("/content/%s/%s" % (book, where))
            elif hit.get("value") and book:
                paths.append("/content/%s/%s" % (
                    book, urllib.parse.quote(hit["value"].replace(" ", "_"))))
        if paths:
            # TEN SUGGESTIONS OUT OF SIX MILLION TITLES may not include
            # the article itself -- "cat" came back led by `Cat_the_Cat`
            # and `.cat`. Only a suggestion list that holds the real title
            # is trusted alone; otherwise search too and rank both.
            if any(_raw_exact(term, p) for p in paths):
                return paths
            suggested = paths
            break
    else:
        suggested = []

    for path in (f"/search?books.name={q_book}&pattern={quoted}"
                 if book else None,
                 f"/search?content={q_book}&pattern={quoted}"
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
        # AN UNSCOPED SEARCH NOW SEARCHES EVERY BOOK. With one archive
        # served that was the same thing as searching hers; with all of
        # them served, `/search?pattern=cats` on a real kiwix-serve came
        # back with Simple English, the full Wikipedia AND an iFixit
        # guide mixed together. So a book-less answer is narrowed to her
        # book before anything is taken from it. Searching the OTHER
        # archives is a real feature (multi-ZIM /wiki, still queued) and
        # it is not going to arrive by accident through a fallback.
        #
        # "Hers" is a PREFIX match, and that is load-bearing for the old
        # case below: a catalog that only gives `wikipedia_en_simple_all`
        # must still recognise `wikipedia_en_simple_all_nopic_2026-05`.
        if book:
            found = [p for p in found
                     if _book_of(p).startswith(book) or not _book_of(p)]
        if found:
            # LEARN THE BOOK FROM THE ANSWER. The catalog gave
            # `wikipedia_en_simple_all` on his board while the real
            # articles live under `wikipedia_en_simple_all_nopic_2026-05`
            # -- close enough to look right, wrong enough that every
            # scoped query would miss. An article path that actually
            # exists is ground truth; a catalogue entry is a claim.
            global _BOOK
            real = _book_of(found[0])
            if real:
                _BOOK = real
            return suggested + [p for p in found if p not in suggested]
    return suggested


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
    books = _catalog()
    if len(books) > 1:
        lines.append("books:    %d on the server -- /wiki reads the one below"
                     % len(books))
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


# ---- what is on the board -------------------------------------------
# Shared with yuzu_zimget.py, which FETCHES archives. That lives in its
# own module on purpose: her prompt tells her nothing she does reaches
# the internet, a derived test holds every module in her turn to it,
# and a downloader is maintenance he starts -- the same line `pull`
# sits on. Nothing here has an address in it.
ROOTS = (os.path.expanduser("~"), "/media", "/mnt")


def _stem(filename):
    """`wikipedia_en_all_mini_2026-07.zim.meta4` -> `wikipedia_en_all_mini`.

    The dated part changes every release and the rest does not, so the
    rest is the book's identity -- the same rule `wiki` uses to serve
    only the newest copy of each book."""
    name = os.path.basename(filename or "").strip()
    for tail in (".meta4", ".part", ".zim"):
        if name.endswith(tail):
            name = name[:-len(tail)]
    return re.sub(r"_\d{4}-\d{2}$", "", name)


def _zims():
    """Every archive on the board, newest first. Same roots and the
    same 1MB floor as `wiki`, so the two cannot disagree."""
    import glob
    found = set()
    for root in ROOTS:
        for depth in range(1, 5):
            pattern = os.path.join(root, *(["*"] * (depth - 1)), "*.zim")
            try:
                found.update(glob.glob(pattern))
            except Exception:
                pass
    keep = []
    for path in found:
        try:
            if os.path.getsize(path) >= 1 << 20:
                keep.append((os.path.getmtime(path), path))
        except OSError:
            pass
    return [p for _, p in sorted(keep, reverse=True)]


def _title_of(path):
    """The article title a path implies, normalised for comparing."""
    slug = urllib.parse.unquote(path.rstrip("/").rsplit("/", 1)[-1])
    slug = re.sub(r"\(.*?\)", " ", slug)          # "Fish (disambiguation)"
    slug = re.sub(r"[^a-z0-9]+", " ", slug.lower()).strip()
    return slug


def _singular(words):
    """Crude, and crude is right: "video games" has to match "Video
    game". Nothing here needs real morphology."""
    return " ".join(w[:-1] if len(w) > 3 and w.endswith("s") else w
                    for w in words.split())


def _raw_exact(term, path):
    """The title IS the term, punctuation and all -- `Cat` for "cat",
    never `.cat`. rank()'s normalising makes those two an exact TIE, so
    this is what breaks it."""
    # THE QUALIFIER STAYS. Stripping it made `Cat_(disambiguation)`
    # "exactly" cat -- measured on his board the same night -- so a
    # shortlist holding only that was trusted and search never asked.
    raw = urllib.parse.unquote(path.rstrip("/").rsplit("/", 1)[-1])
    raw = raw.replace("_", " ").strip().lower()
    want = " ".join((term or "").lower().split())
    return raw in (want, _singular(want)) or _singular(raw) == _singular(want)


def _score(term, path):
    """How well a path's TITLE matches what he typed: 3 exact, 2 one
    starts the other, 1 every word present, 0 only the body matched."""
    want = _singular(re.sub(r"[^a-z0-9]+", " ", (term or "").lower()).strip())
    got = _singular(_title_of(path))
    if not want:
        return 0
    if got == want:
        return 3                      # "fish" -> Fish
    if got.startswith(want) or want.startswith(got):
        return 2                      # "fish" -> Fish farming
    if all(w in got.split() for w in want.split()):
        return 1                      # every word is in the title
    return 0                          # only the BODY matched


def rank(term, paths):
    """Search hits, best TITLE MATCH first.

    MEASURED, Sept 11. `/wiki video games` came back about **Electronic
    Games magazine** -- she named Arnie Katz, Bill Kunkel and Joyce
    Worley, its three real founders, so the lookup and the parser were
    both working perfectly and simply handed her the wrong article.
    `/wiki fish` got fish FARMING the same way.

    Kiwix ranks by its own full-text score, and an article that merely
    mentions a term a lot can outrank the article that IS the term. The
    first hit was being taken on trust. Asking "does the TITLE match
    what he typed" costs nothing and is the thing a person means: type
    fish, get Fish.

    Stable, so a tie keeps kiwix's own ordering -- this re-orders the
    obvious cases and stays out of the way otherwise."""
    want = _singular(re.sub(r"[^a-z0-9]+", " ", (term or "").lower()).strip())
    if not want:
        return list(paths)

    def score(path):
        return _score(term, path)

    def key(pair):
        i, path = pair
        # A DISAMBIGUATION PAGE IS NEVER THE ANSWER. The qualifier is
        # stripped before matching, so "Black hole (disambiguation)"
        # scores an exact match on "black holes" and would have won --
        # a list of links where she expected an article. Demoted, not
        # dropped: if it is genuinely all there is, it still gets tried.
        # MEASURED Sept 23 on the full English archive: `/wiki cat` got
        # `.cat`, the Catalan web domain, because it normalises to "cat"
        # and tied `Cat` exactly -- and a tie keeps kiwix's order. A title
        # that only matches once its punctuation is thrown away loses.
        return (-score(path), "disambig" in path.lower(),
                not _raw_exact(term, path), i)

    return [p for _, p in sorted(enumerate(paths), key=key)]


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

    # ASK FOR THE ARTICLE BY NAME FIRST. "cat" is `Cat` in any
    # Wikipedia, and a direct fetch cannot be outranked by `.cat`,
    # `Cat_the_Cat` or a disambiguation page the way a shortlist can.
    # A miss is a 404 and costs one local request.
    book = book_name()
    guesses = []
    if book:
        words = [term, _singular(term)]
        # AN ABBREVIATION IS TITLED IN CAPITALS. Sept 24: `/wiki emp` got
        # (R)-MDMA. "Emp" is not a page and `EMP` is; with the real title
        # missed, the best title match left was `EMP-01` -- one of that
        # drug's trial names, which redirects to it -- and she explained
        # the article she was handed. So a short single word is asked
        # for in capitals too, after the ordinary spelling.
        if term.isalpha() and 2 <= len(term) <= 5:
            words.append(term.upper())
        for word in words:
            title = word[:1].upper() + word[1:]
            guess = "/content/%s/%s" % (
                book, urllib.parse.quote(title.replace(" ", "_")))
            if guess not in guesses:
                guesses.append(guess)
    fallback = None
    stray = None
    exact_list = False
    for path in guesses + [p for p in rank(term, paths)[:3]
                           if p not in guesses]:
        if not path.startswith("/"):
            path = "/" + path
        # ONCE WHAT HE TYPED TURNED OUT TO BE A LIST OF MEANINGS, only a
        # page NAMED what he typed can beat it -- "Mercury (planet)" does;
        # a near-miss title like `EMP-01` does not. The list is the honest
        # answer: she can say what it might mean and ask which.
        if exact_list and path not in guesses and _score(term, path) < 3:
            continue
        try:
            page = _get(path)
        except Exception:
            continue
        parser = _Extract()
        parser.feed(page)
        text = parser.text()
        if len(text) < 80:          # a stub or a redirect, try the next
            # ...but a SHORT list of meanings for exactly what he typed
            # still rules out the near misses. The mini archive keeps a
            # page's opening lines, so its `EMP` can be "EMP may refer
            # to:" with the list itself cut away.
            if re.search(r"\brefers? to\b", text) and \
                    (path in guesses or _raw_exact(term, path)):
                exact_list = True
            continue
        title = parser.title or term
        # A NEAR-MISS TITLE THAT LANDS SOMEWHERE ELSE ENTIRELY is not a
        # match. `EMP-01` scored "starts with emp" and redirected to
        # (R)-MDMA. Held only to prefix matches from the shortlist: an
        # exact alias ("Big Apple" -> New York City) and a body-only
        # search hit never claimed a near-miss name.
        if path not in guesses and _score(term, path) == 2 and \
                _score(term, "/" + title.replace(" ", "_")) == 0:
            stray = stray or (title, text)
            continue
        if len(text) > max_chars:
            # Cut on a sentence so she is never handed half a clause.
            cut = text[:max_chars]
            stop = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
            text = cut[:stop + 1] if stop > max_chars // 2 else cut + "..."
        # A DISAMBIGUATION PAGE IS A LIST OF LINKS, whatever its title
        # says -- "Mercury" is one. Kept only as a last resort.
        if re.search(r"\bmay (also )?refer to\b", text[:400]):
            fallback = fallback or (title, text)
            if path in guesses or _raw_exact(term, path):
                exact_list = True
            continue
        return title, text

    if fallback:
        return fallback
    if exact_list:
        return None, (f"'{term}' means more than one thing in the archive "
                      "-- try the full name.")
    if stray:
        return None, (f"Nothing in the archive is called '{term}' -- "
                      "try the full name.")
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
    # NAME THE SUBJECT AGAIN, rather than "it". Measured the same day:
    # handed an article about a magazine she answered "I used to be
    # featured in this magazine back when I was still just a concept",
    # and handed one about fish farming, "I don't think I'd make a very
    # good fish farm". **She absorbed the subject into herself.** "Tell
    # me about it" leaves "it" free to mean her; naming the title again
    # costs a few characters and cannot be misread.
    return (f"I looked up {title} and it says: {body}\n\n"
            f"Tell me about {title} in your own words, in a sentence or "
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
