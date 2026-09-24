"""Exact arithmetic for a character who is asked to do sums.

Ghost, Sept 24, off the list of what Zero could learn next: "1 and 5
are approooooved" -- 1 being this. She is the one he brings maths to,
and she runs on a 4B model. A model that size explains a sum well and
can still slip a digit in a long multiplication, and it does so with
exactly the same confidence as when it is right.

THE PROMPT REDUCES, CODE GUARANTEES -- the rule this whole repo runs
on, applied to numbers. The /wiki lookup already works this way: the
deck fetches the fact, and she only ever explains what she was handed.
This does the same for a sum. When his message has one in it, the deck
works it out here, exactly, and the answer rides into her turn beside
what he typed:

    What's 17 times 23? (The deck worked it out exactly: 17 × 23 = 391.)

She never has to produce the number, only explain it -- and copying a
number is the one thing a small model does not get wrong.

THERE IS NO eval(). Not paranoia about his own deck: eval turns a typo
into a Python error instead of an answer, and a sum the deck cannot
parse should simply get no note. So a message is parsed with `ast` and
walked by hand over a short list of node types. Anything else --
names, calls other than sqrt, attributes, strings -- means "not a sum",
and she answers the way she always has.

BIG POWERS ARE REFUSED, not computed. `9 ** 9 ** 9` is a perfectly
valid expression that would hold the server for minutes. A result
past MAX_DIGITS is not something she could say out loud anyway.

WHAT COUNTS AS A SUM IS DELIBERATELY NARROW. A hyphen, a slash or an
x between two numbers is often not maths at all -- `2026-09-24`,
`3-4 sentences`, `9/24`, `the panel is 1024x600` -- so those alone
only count when the message
also asks for a calculation ("what's", "calculate", "how much"...) or
IS the sum and nothing else. A wrong note is worse than no note: it
hands her a confident number for a question he never asked.

Stdlib only, like everything on the turn path, and it never raises:
anything unexpected means no note.
"""

import ast
import math
import re

MAX_DIGITS = 60        # longer than this and it is not an answer to say
MAX_EXPONENT = 1000
MAX_SUMS = 3           # per message; more is a table, not a question

# What turns a message into a request for a calculation. The ambiguous
# operators (- and /) only count alongside one of these.
_ASKS = re.compile(
    r"\b(what'?s|what is|how much|how many|calculate|calc|compute|"
    r"work out|solve|equals?|total)\b|=", re.I)

# Words and symbols people type for an operator, in the order they must
# be replaced ("divided by" before "by", "to the power of" before "of").
_WORDS = [
    (r"\bmultiplied\s+by\b", " * "),
    (r"\btimes\b", " * "),
    (r"\bdivided\s+by\b", " / "),
    (r"\bplus\b", " + "),
    (r"\bminus\b", " - "),
    (r"\bto\s+the\s+power\s+of\b", " ** "),
    (r"÷", " / "),
    (r"[✕]", " * "),
    (r"−", " - "),                     # a real minus sign
    (r"\^", " ** "),
]
_NUM = r"\d+(?:\.\d+)?"


def _normalise(text):
    """His words turned into something `ast` can read, and a record of
    whether anything in it was UNAMBIGUOUSLY an operator."""
    s = " " + text + " "
    # Thousands separators: 12,000 is a number, "1, 2, 3" is a list.
    s = re.sub(r"(?<=\d),(?=\d{3}\b)", "", s)
    # Dates are not subtraction or division. Cut them out first.
    s = re.sub(r"\b\d{4}-\d{1,2}-\d{1,2}\b", " ; ", s)
    s = re.sub(r"\b\d{1,2}/\d{1,2}/\d{2,4}\b", " ; ", s)
    strong = False
    # "15% of 80", "15 percent of 80"
    s, n = re.subn(r"(%s)\s*(?:%%|percent)\s+of\s+" % _NUM, r" ( \1 / 100 ) * ", s,
                   flags=re.I)
    strong |= bool(n)
    # "square root of 144", "sqrt 144", "sqrt(144)", "√144"
    s, n = re.subn(r"(?:\bsquare\s+root\s+of\b|\bsqrt\b|√)\s*\(?\s*(%s)\s*\)?" % _NUM,
                   r" √( \1 ) ", s, flags=re.I)
    strong |= bool(n)
    s, n = re.subn(r"(%s|\))\s*squared\b" % _NUM, r"\1 ** 2 ", s, flags=re.I)
    strong |= bool(n)
    s, n = re.subn(r"(%s|\))\s*cubed\b" % _NUM, r"\1 ** 3 ", s, flags=re.I)
    strong |= bool(n)
    # An x between two numbers is times; an x anywhere else is a letter.
    # WEAK, like - and /: "the panel is 1024x600" is a size, not a
    # question, and it is exactly how he describes this deck's screen.
    s = re.sub(r"(?<=[\d)])\s*[xX]\s*(?=[\d(√])", " × ", s)
    for pattern, op in _WORDS:
        s, n = re.subn(pattern, op, s, flags=re.I)
        strong |= bool(n)
    return s, strong


# A run of number-ish characters: digits, points, brackets, operators,
# the root sign and spaces. `**` is two `*`s, so it needs no entry.
#
# A LEADING MINUS BELONGS TO THE SUM. The first draft started every run
# at a digit, so "-5 × 3" was worked out as "5 × 3 = 15" -- a confident
# wrong answer, the one thing this module exists to prevent. A minus
# counts as a sign when nothing that could end a number comes before
# it. The × is the weak "x" from _normalise, a times that has not yet
# been asked for.
_SPAN = re.compile(r"(?:(?<![\w)])-\s*)?[\d(√][\d\s.+\-*/()√×]*[\d)]")
_HAS_OP = re.compile(r"[\d)]\s*(?:\*\*|[+\-*/×])\s*-?\s*[\d(√]|√")
_STRONG_OP = re.compile(r"[\d)]\s*(?:\*\*|[+*])\s*-?\s*[\d(√]|√")


class _NotASum(Exception):
    pass


def _value(node):
    """Walk the tree by hand. Only numbers, + - * / **, unary minus and
    sqrt of a number; anything else is not a sum."""
    if isinstance(node, ast.Expression):
        return _value(node.body)
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
        v = _value(node.operand)
        return -v if isinstance(node.op, ast.USub) else v
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id == "sqrt" and len(node.args) == 1 \
            and not node.keywords:
        v = _value(node.args[0])
        if v < 0:
            raise _NotASum("root of a negative")
        root = math.isqrt(v) if isinstance(v, int) else None
        return root if root is not None and root * root == v else math.sqrt(v)
    if isinstance(node, ast.BinOp):
        a, b = _value(node.left), _value(node.right)
        if isinstance(node.op, ast.Add):
            return a + b
        if isinstance(node.op, ast.Sub):
            return a - b
        if isinstance(node.op, ast.Mult):
            return a * b
        if isinstance(node.op, ast.Div):
            if b == 0:
                raise ZeroDivisionError
            if isinstance(a, int) and isinstance(b, int) and a % b == 0:
                return a // b
            return a / b
        if isinstance(node.op, ast.Pow):
            if abs(b) > MAX_EXPONENT or (
                    abs(a) > 1 and abs(b) * math.log10(abs(a)) > MAX_DIGITS):
                raise _NotASum("too big to say")
            return a ** b
    raise _NotASum(type(node).__name__)


def _say(n):
    """A number the way she should read it: exact when it is whole,
    ten significant figures when it is not."""
    if isinstance(n, float):
        if n != n or n in (float("inf"), float("-inf")):
            raise _NotASum("not a number")
        if n.is_integer() and abs(n) < 1e15:
            n = int(n)
        else:
            return "%.10g" % n
    if len(str(abs(n))) > MAX_DIGITS:
        raise _NotASum("too long to say")
    return "{:,}".format(n)


def _shown(expr):
    """The sum as she should see it: × and ÷, not * and /."""
    s = expr.replace("**", "^").replace("*", "×").replace("/", "÷")
    s = s.replace("√(", "√(")
    s = re.sub(r"\s*([×÷+^])\s*", r" \1 ", s)
    s = re.sub(r"(?<=[\d)])\s*-\s*(?=[\d(√])", " - ", s)
    s = re.sub(r"^-\s+", "-", s)
    s = re.sub(r"\(\s*-\s+", "(-", s)
    s = re.sub(r"([×÷+^-] )-\s+", r"\1-", s)
    s = re.sub(r"\(\s+", "(", s)
    s = re.sub(r"\s+\)", ")", s)
    return re.sub(r"\s{2,}", " ", s).strip()


def sums(text):
    """[(shown, answer)] for every sum in his message, or [].

    `answer` is a string: the exact result, or a sentence when there is
    no answer (dividing by zero). Never raises."""
    try:
        s, strong_words = _normalise(text or "")
        asked = bool(_ASKS.search(text or ""))
        # The whole message IS a sum ("17*23", "12.5 / 4?").
        bare = re.fullmatch(r"\s*-?\s*[\d(√][\d\s.+\-*/()√×]*[\d)]\s*[?.!]?\s*",
                            s.strip() + " ") is not None
        found = []
        for m in _SPAN.finditer(s):
            expr = m.group(0).strip()
            if not _HAS_OP.search(expr):
                continue
            if expr.count("(") != expr.count(")"):
                continue
            # A lone - or / is a date, a range or a fraction until the
            # message says it wants working out.
            if not (_STRONG_OP.search(expr) or strong_words or asked or bare):
                continue
            try:
                tree = ast.parse(expr.replace("√", "sqrt").replace("×", "*"),
                                 mode="eval")
                answer = _say(_value(tree))
            except ZeroDivisionError:
                answer = "no answer, it divides by zero"
            except (_NotASum, SyntaxError, ValueError, OverflowError,
                    TypeError, RecursionError, MemoryError):
                continue
            found.append((_shown(expr), answer))
            if len(found) >= MAX_SUMS:
                break
        return found
    except Exception:
        return []


def note(text):
    """The line that rides into her turn, or "" when there is no sum.

    Worded so she knows the number is settled and hers to explain,
    not a claim to check -- and short, because it rides in her history
    too, inside a context window with little room left."""
    found = sums(text)
    if not found:
        return ""
    worked = "; ".join(
        "%s = %s" % (shown, answer) if not answer.startswith("no answer")
        else "%s has %s" % (shown, answer)
        for shown, answer in found)
    return "(The deck worked it out exactly: %s.)" % worked


if __name__ == "__main__":
    import sys
    line = " ".join(sys.argv[1:]) or "What's 17 times 23?"
    print(note(line) or "(no sum in that)")
