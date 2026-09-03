"""
Yuzu's brain -- a real Ollama client. This is the swap-in for the
ask_yuzu_brain() STUB in yuzu_all_in_one.py.

Talks to Ollama over its HTTP API using nothing but the standard
library. No `pip install ollama`, no requests, no aiohttp -- which
means it runs on the Jetson, on the Steam Deck, and in Pydroid on the
phone with zero setup beyond Ollama itself.

Quick check that everything's alive:

    python yuzu_brain.py                 # one-shot smoke test
    python yuzu_brain.py --chat          # interactive, brain only
    python yuzu_brain.py --model llama3.2:3b

    python yuzu_brain.py --persona saya --chat

Personas live in personas/ -- one file per character, with the body
rules composed in from a shared hardware file. See yuzu_personas.py.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path

import yuzu_personas

HERE = Path(__file__).parent

# Override with:  export YUZU_MODEL=...   /  export OLLAMA_HOST=...
DEFAULT_MODEL = os.environ.get("YUZU_MODEL", "yuzu")
DEFAULT_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")

# Seconds to wait for one reply. Generous on purpose: a 3B on an older
# laptop GPU (or worse, spilled to CPU) can take minutes for a long
# reply, and an eval run that dies two thirds of the way through has
# wasted twenty minutes of someone's evening.
DEFAULT_TIMEOUT = int(os.environ.get("YUZU_TIMEOUT", "300"))

# How long Ollama keeps the model resident in memory after a reply.
#
# Ollama's own default is 5 minutes, which is the wrong shape for a
# companion robot. She sits quietly in a corner for six minutes, someone
# walks up and says hi, and the 3B has to be read back off disk before
# she can answer -- so the very first thing anyone says to her is the
# slowest reply she ever gives. On the Orin, off NVMe, that reload is
# seconds; off a microSD it is worse.
#
# 30m is the compromise for a laptop or phone that has other uses for
# its memory. On the Jetson, where nothing else wants the 8GB yet, pin
# her there for good:
#
#     export YUZU_KEEP_ALIVE=-1
#
# Set it to 0 to go back to unloading immediately after every reply,
# which is what you want if you're bringing up Whisper alongside her and
# need the memory back between turns.
DEFAULT_KEEP_ALIVE = os.environ.get("YUZU_KEEP_ALIVE", "30m")


def _keep_alive(raw):
    """Ollama takes either a Go duration string ("30m", "1h") or a plain
    number of seconds, where -1 means never unload.

    Numbers have to be sent as JSON numbers, not strings: "-1" and "0"
    are not valid Go durations, so a string would come back a 400 with a
    parse error that names neither this setting nor the fix.
    """
    text = str(raw).strip()
    try:
        return int(text)
    except ValueError:
        return text

# Sampling. Tuned for a companion persona on a small model, not for
# factual accuracy -- Section 2 of the context dump already accepts that
# a 3B gets local facts confidently wrong.
#
#   temperature 0.8  personality needs some spread; below ~0.6 she gets
#                    flat and starts sounding like a generic assistant
#   min_p 0.05       better than top_p alone at high temp -- cuts the
#                    genuinely bad tokens without flattening her voice
#   repeat_penalty   1.1, she loops catchphrases without it
#   num_predict 150  her prompt asks for short replies; this is a hard
#                    ceiling so one rambling turn can't stall the robot
#   num_ctx 4096     ~8 turns of history on a 3B without eating the
#                    8GB Jetson's memory pool
DEFAULT_OPTIONS = {
    "temperature": 0.8,
    "top_p": 0.9,
    "top_k": 40,
    "min_p": 0.05,
    "repeat_penalty": 1.1,
    "num_predict": 150,
    "num_ctx": 4096,
}


class ReplyHealth:
    """How well one reply followed the format rules.

    Cheap and local -- no second model call, which matters on a Jetson
    already running Whisper and Piper. It reuses the same parser the
    robot uses, so "healthy" means literally "this would have worked".
    """

    def __init__(self, raw):
        try:
            from yuzu_all_in_one import (extract_actions, lookup_actions,
                                         normalize_actions, strip_actions)
        except ImportError:
            self.usable = None          # no parser; can't judge
            self.asterisks = self.total = self.ran = 0
            self.has_dialogue = True
            return
        self.asterisks = raw.count("*") // 2
        cleaned = normalize_actions(raw)
        actions = extract_actions(cleaned)
        self.total = len(actions)
        self.ran = sum(1 for a in actions if lookup_actions(a))
        self.has_dialogue = bool(strip_actions(cleaned).strip())
        self.usable = True

    @property
    def ok(self):
        """A reply is wonky if she said nothing at all, or moved only in
        ways this body can't.

        Asterisks used to fail a reply on their own, as "format drift,
        the snowball starter". Measurement retired that:

          * pooled across both of its runs, yuzu2 scored 54.2% on
            no_asterisks (26/48) while moving on 80-83% of replies. So
            roughly a third of replies were asterisked AND moved fine.
          * _canonicalise() already rewrites them to brackets before
            they enter history, which is what actually stops the
            snowball -- the veto here was a second guard on a risk that
            was already handled.
          * normalize_actions() rescues *spins* to [spins] and it runs.
            Three of yuzu3's six "no_asterisks failures" moved perfectly.

        Vetoing on them meant two asterisked-but-fine replies in a row
        tripped the two-strike rule and wiped the conversation -- at a
        ~46% per-reply rate, about every fifth turn, for no reason the
        robot could see. She felt amnesiac because of a metric, not a
        fault. Asterisks are still counted and still show in the repr;
        they just no longer condemn a reply that worked.
        """
        if self.usable is None:
            return True
        if not self.has_dialogue:
            return False                # the freeze case
        if self.total and not self.ran:
            return False                # moved in ways the robot can't
        return True

    def __repr__(self):
        return (f"<{'ok' if self.ok else 'WONKY'} "
                f"actions {self.ran}/{self.total} "
                f"asterisks {self.asterisks} "
                f"dialogue {'y' if self.has_dialogue else 'n'}>")


class BrainError(RuntimeError):
    """Ollama is unreachable, or the model isn't there. Raised with a
    message that says what to actually do about it."""


def load_system_prompt(persona=yuzu_personas.LIVE_PERSONA):
    """The composed system prompt for one persona: her character text
    with the body's action rules substituted in."""
    try:
        return yuzu_personas.load(persona).prompt
    except yuzu_personas.PersonaError as exc:
        raise BrainError(str(exc)) from exc


def _post(url, payload, timeout):
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    return urllib.request.urlopen(request, timeout=timeout)


class YuzuBrain:
    def __init__(self, model=DEFAULT_MODEL, host=DEFAULT_HOST,
                 system_prompt=None, options=None,
                 history_turns=8, persona=None, auto_recover=True,
                 timeout=None, keep_alive=None):
        """
        model         : Ollama model name (see Modelfile.yuzu)
        persona       : key from personas/ -- supplies both the system
                        prompt and any sampling overrides that character
                        wants (a kuudere can run colder than a gyaru)
        auto_recover  : watch replies for format drift and trim history
                        when she goes wonky (see below)
        history_turns : how many past exchanges to keep. A 3B loses the
                        thread long before the context window fills, and
                        every extra token is latency on the Jetson, so
                        this is deliberately short.
        """
        # model=None means "the default", not "no model". Callers pass
        # it through from an unset --model flag or from a brain that
        # never came up (switch_persona does exactly that when Ollama
        # was down at boot). Leaving it None sent {"model": null} to
        # Ollama and every turn after the switch failed, with nothing
        # naming the switch as the cause.
        self.model = model or DEFAULT_MODEL
        self.host = (host or DEFAULT_HOST).rstrip("/")
        self.persona = None
        persona_options = {}
        if system_prompt is None:
            # LIVE_PERSONA, not DEFAULT_PERSONA: the plain "yuzu" key is
            # the frozen v1 archive (20% action hit rate). Booting it
            # because it owns the short name is a silent regression.
            key = persona or yuzu_personas.LIVE_PERSONA
            try:
                self.persona = yuzu_personas.load(key)
            except yuzu_personas.PersonaError as exc:
                raise BrainError(str(exc)) from exc
            system_prompt = self.persona.prompt
            persona_options = self.persona.options()
        self.system_prompt = system_prompt
        # Precedence: explicit options > persona settings > defaults.
        # Layered rather than dict(a, **b, **c) -- that form raises
        # TypeError the moment two layers set the same key, which is
        # precisely when an override is being used.
        merged = dict(DEFAULT_OPTIONS)
        merged.update(persona_options)
        merged.update(options or {})
        self.options = merged
        self.timeout = timeout if timeout is not None else DEFAULT_TIMEOUT
        self.keep_alive = _keep_alive(
            keep_alive if keep_alive is not None else DEFAULT_KEEP_ALIVE)
        self.history_turns = history_turns
        self.history = []

        # Drift recovery. Measured on a real 7-turn chat: format held on
        # turn 1 and had fully collapsed by turn 3, because her own
        # replies outweigh the system prompt once they pile up.
        #
        # A blind periodic reset would throw away the conversation at
        # random. This watches the replies instead and only acts when
        # she's actually gone wonky, and even then keeps the most recent
        # exchange so the thread survives. Her personality is in the
        # system prompt, which is re-sent every turn -- that's what
        # continuity actually rests on, not the transcript.
        self.auto_recover = auto_recover
        self.wonky_streak = 0
        self.recoveries = 0
        self.last_health = None
        self.on_recover = None          # optional callback(kind, health)

    # -- preflight ------------------------------------------------------

    def available_models(self):
        """Every model Ollama currently has pulled."""
        try:
            with urllib.request.urlopen(f"{self.host}/api/tags", timeout=5) as r:
                data = json.load(r)
        except urllib.error.URLError as exc:
            raise BrainError(
                f"Can't reach Ollama at {self.host} ({exc.reason}).\n"
                f"  Is it running?   ollama serve\n"
                f"  Different host?  export OLLAMA_HOST=http://...:11434"
            ) from exc
        except (TimeoutError, OSError) as exc:
            raise BrainError(
                f"Ollama at {self.host} didn't answer in time ({exc})."
            ) from exc
        return [m.get("name", "") for m in data.get("models", [])]

    def check(self):
        """Verify Ollama is up AND the model is pulled. Call this at
        startup so a missing model fails at boot with a clear message,
        instead of mid-conversation with a stack trace."""
        models = self.available_models()
        if not any(m == self.model or m.startswith(self.model + ":")
                   for m in models):
            # Name the model that is actually missing, not "yuzu". A
            # pivot to another main character, or a second robot, makes
            # a hardcoded fix instruction point at the wrong thing at
            # exactly the moment someone is stuck.
            raise BrainError(
                f"Ollama is running, but no model named '{self.model}'.\n"
                f"  Pulled models: {', '.join(models) or '(none)'}\n"
                f"  Build it:  python build_yuzu_model.py --persona "
                f"{self.persona.key if self.persona else '<key>'} --create\n"
                f"  Or point at another:  export YUZU_MODEL=<name>"
            )
        return True

    # -- generation -----------------------------------------------------

    def _messages(self, user_text):
        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(self.history[-self.history_turns * 2:])
        messages.append({"role": "user", "content": user_text})
        return messages

    def ask(self, user_text, remember=True):
        """One turn in, Yuzu's raw reply out -- brackets and all. Feed
        the result straight to handle_yuzu_reply()."""
        payload = {
            "model": self.model,
            "messages": self._messages(user_text),
            "stream": False,
            "options": self.options,
            "keep_alive": self.keep_alive,
        }
        try:
            with _post(f"{self.host}/api/chat", payload, self.timeout) as r:
                data = json.load(r)
        except urllib.error.HTTPError as exc:
            raise BrainError(
                f"Ollama returned {exc.code} for model '{self.model}': "
                f"{exc.read().decode('utf-8', 'replace')[:300]}"
            ) from exc
        except urllib.error.URLError as exc:
            raise BrainError(
                f"Can't reach Ollama at {self.host} ({exc.reason}). "
                f"Start it with: ollama serve"
            ) from exc
        except (TimeoutError, OSError) as exc:
            # A slow generation raises a bare socket TimeoutError from
            # the READ, and TimeoutError is not a URLError -- so this
            # used to escape every handler and abort a whole eval run
            # mid-way. Caught explicitly, with the dial to turn.
            raise BrainError(
                f"No reply within {self.timeout}s ({exc}).\n"
                f"  A 3B on a weak GPU, or spilled to CPU, can exceed this.\n"
                f"  Check placement:  ollama ps      (want GPU, not CPU)\n"
                f"  Or allow longer:  export YUZU_TIMEOUT=600"
            ) from exc

        reply = (data.get("message") or {}).get("content", "").strip()
        if remember:
            self._remember(user_text, reply)
        self._check_drift(reply)
        return reply

    def ask_stream(self, user_text, remember=True):
        """Yield the reply in chunks as the model produces it.

        Worth using on the robot: a 3B on a Jetson takes a couple of
        seconds for a full reply, and Yuzu's first sentence is usually
        ready long before the last one. Streaming lets speech start on
        the first complete sentence instead of after the whole thing.
        """
        payload = {
            "model": self.model,
            "messages": self._messages(user_text),
            "stream": True,
            "options": self.options,
            "keep_alive": self.keep_alive,
        }
        collected = []
        try:
            with _post(f"{self.host}/api/chat", payload, self.timeout) as response:
                for line in response:
                    line = line.strip()
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if chunk.get("error"):
                        raise BrainError(f"Ollama error: {chunk['error']}")
                    piece = (chunk.get("message") or {}).get("content", "")
                    if piece:
                        collected.append(piece)
                        yield piece
                    if chunk.get("done"):
                        break
        except urllib.error.URLError as exc:
            raise BrainError(
                f"Can't reach Ollama at {self.host} ({exc.reason}). "
                f"Start it with: ollama serve"
            ) from exc
        except (TimeoutError, OSError) as exc:
            raise BrainError(
                f"Stream stalled after {self.timeout}s ({exc}). "
                f"Try: export YUZU_TIMEOUT=600"
            ) from exc
        full_reply = "".join(collected).strip()
        if remember:
            self._remember(user_text, full_reply)
        # ask() scored drift and ask_stream() didn't, so streaming
        # silently disabled the whole recovery mechanism. Both paths
        # score now.
        self._check_drift(full_reply)

    @staticmethod
    def _canonicalise(reply):
        """Rewrite *asterisk* actions as [bracket] actions before the
        reply goes into history.

        This fixes a drift measured over a real 7-turn chat: turn 1 was
        100% brackets, turn 2 leaked one asterisk, and turns 3-7 were
        100% asterisks. Nothing about the prompt changed between them.
        What changed is that the conversation itself became the
        strongest set of examples in context, and a 3B follows its own
        recent output over a system prompt sitting further back.

        So her history is stored in the format we want her to keep
        using. She still SEES what she said, but she sees the corrected
        form, and every turn reinforces brackets instead of eroding
        them. One stray asterisk can no longer snowball.
        """
        try:
            from yuzu_all_in_one import normalize_actions
        except ImportError:
            return reply          # parser not present; store as-is
        return normalize_actions(reply)

    def _remember(self, user_text, reply):
        if not reply:
            return
        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant",
                             "content": self._canonicalise(reply)})
        # Trim eagerly so history can't creep past the window over a
        # long session.
        self.history = self.history[-self.history_turns * 2:]

    def _check_drift(self, reply):
        """Score the reply and recover if she's drifting.

        Two strikes, not one -- a single odd reply is noise, and
        resetting on it would make her feel amnesiac. Two in a row is a
        pattern, and in the measured chat the pattern never
        self-corrected once it started.
        """
        if not reply:
            return
        health = ReplyHealth(reply)
        self.last_health = health
        if health.ok:
            self.wonky_streak = 0
            return

        self.wonky_streak += 1
        if not self.auto_recover or self.wonky_streak < 2:
            return

        # Soft first: keep the last exchange so the thread survives.
        # If that didn't take, clear the lot -- the personality is in
        # the system prompt and comes back regardless.
        kind = "soft" if len(self.history) > 2 else "full"
        self.history = self.history[-2:] if kind == "soft" else []
        self.wonky_streak = 0
        self.recoveries += 1
        if self.on_recover:
            self.on_recover(kind, health)

    def reset(self):
        """Forget the conversation, keep the personality."""
        self.history = []
        self.wonky_streak = 0


# ---------------------------------------------------------------------
# CLI -- exercise the brain on its own, with no robot and no audio.
# ---------------------------------------------------------------------

def _cli(argv):
    model = DEFAULT_MODEL
    persona = None
    chat = False
    args = list(argv)
    while args:
        arg = args.pop(0)
        if arg == "--model" and args:
            model = args.pop(0)
        elif arg == "--persona" and args:
            persona = args.pop(0).lower()
        elif arg == "--chat":
            chat = True
        elif arg in ("-h", "--help"):
            print(__doc__)
            return 0

    try:
        brain = YuzuBrain(model=model, persona=persona)
    except BrainError as exc:
        print(f"\n{exc}\n")
        return 1
    who = brain.persona.name if brain.persona else "custom prompt"
    print(f"persona: {who}   model: {brain.model}   host: {brain.host}")
    try:
        brain.check()
    except BrainError as exc:
        print(f"\n{exc}")
        return 1
    print("Ollama is up and the model is there.\n")

    if not chat:
        greeting = f"Hey {who}, what's up?"
        print(f"You: {greeting}")
        print(f"{who}: {brain.ask(greeting)}")
        return 0

    print("Interactive. 'quit' to exit, 'reset' to clear history.\n")
    while True:
        try:
            text = input("You: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if text.lower() in ("quit", "exit"):
            return 0
        if text.lower() == "reset":
            brain.reset()
            print("(history cleared)\n")
            continue
        if not text:
            continue
        print(f"{who}: ", end="", flush=True)
        try:
            for piece in brain.ask_stream(text):
                print(piece, end="", flush=True)
            print("\n")
        except BrainError as exc:
            print(f"\n{exc}\n")
            return 1


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
