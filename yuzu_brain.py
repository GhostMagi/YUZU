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


class BrainError(RuntimeError):
    """Ollama is unreachable, or the model isn't there. Raised with a
    message that says what to actually do about it."""


def load_system_prompt(persona=yuzu_personas.DEFAULT_PERSONA):
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
                 system_prompt=None, options=None, timeout=120,
                 history_turns=8, persona=None):
        """
        model         : Ollama model name (see Modelfile.yuzu)
        persona       : key from personas/ -- supplies both the system
                        prompt and any sampling overrides that character
                        wants (a kuudere can run colder than a gyaru)
        history_turns : how many past exchanges to keep. A 3B loses the
                        thread long before the context window fills, and
                        every extra token is latency on the Jetson, so
                        this is deliberately short.
        """
        self.model = model
        self.host = host.rstrip("/")
        self.persona = None
        persona_options = {}
        if system_prompt is None:
            key = persona or yuzu_personas.DEFAULT_PERSONA
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
        self.timeout = timeout
        self.history_turns = history_turns
        self.history = []

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
        return [m.get("name", "") for m in data.get("models", [])]

    def check(self):
        """Verify Ollama is up AND the model is pulled. Call this at
        startup so a missing model fails at boot with a clear message,
        instead of mid-conversation with a stack trace."""
        models = self.available_models()
        if not any(m == self.model or m.startswith(self.model + ":")
                   for m in models):
            raise BrainError(
                f"Ollama is running, but no model named '{self.model}'.\n"
                f"  Pulled models: {', '.join(models) or '(none)'}\n"
                f"  Build Yuzu:    ollama create yuzu -f Modelfile.yuzu\n"
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

        reply = (data.get("message") or {}).get("content", "").strip()
        if remember:
            self._remember(user_text, reply)
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
        if remember:
            self._remember(user_text, "".join(collected).strip())

    def _remember(self, user_text, reply):
        if not reply:
            return
        self.history.append({"role": "user", "content": user_text})
        self.history.append({"role": "assistant", "content": reply})
        # Trim eagerly so history can't creep past the window over a
        # long session.
        self.history = self.history[-self.history_turns * 2:]

    def reset(self):
        """Forget the conversation, keep the personality."""
        self.history = []


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
