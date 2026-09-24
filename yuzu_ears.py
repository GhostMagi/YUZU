"""Her ears: a recording from his device in, the words he said out.

Ghost, Sept 24: "Bout time we set up listening. I just prefer typing
tbh (im missing a lot of teeth) so lets make it so its only when i wana
use the talk to her functionality. Maybe a button for the touch screen
starts listening when i tap it, ends recording when i tap it again and
bam?"

PUSH-TO-TALK, NEVER A WAKE WORD. He specified this shape on Sept 22
("a 'certain button to start the recording' vibe like a walkie
talkie") and it is the right one on a battery: nothing listens until
he taps, nothing keeps listening after he taps again.

THE MICROPHONE IS ON HIS DEVICE, NOT THE BOARD -- the same split her
voice already uses the other way round. The Orin has no microphone
(the USB sound card is still on the parts list), and every device he
looks at her on has one. So the PAGE records, the recording travels to
the board, and Whisper turns it into text here. What comes back goes
into the text box and is sent exactly as if he had typed it.

faster-whisper, NOT openai-whisper. The PyPI `openai-whisper` is
PyTorch, gigabytes on aarch64 and sharing the Orin's one pool of 8GB
with her model. faster-whisper runs the same Whisper weights on
CTranslate2, on the CPU, with an int8 `base.en` of about 150MB. The
same call Kokoro made against the PyTorch `kokoro`.

IT NEVER DOWNLOADS ANYTHING. `local_files_only=True`, always. Her
prompt tells her nothing she does reaches the internet, and a
transcription is part of her turn; fetching the model is maintenance
that `pull` does once, the same line `wiki --get` sits on. Missing
model means a sentence saying so, never a download mid-conversation.

A MISSING EAR COSTS THE MICROPHONE, NEVER THE CHAT. Every failure is a
sentence for the page to show; typing works exactly as it always has.
The promise the voice, the wiki and Piper all make.

UNVERIFIED ON HIS BOARD: whether faster-whisper's aarch64 wheels
install there, and how well base.en hears him. If it mishears,
YUZU_WHISPER_MODEL=small.en is the stronger ear (about 480MB) -- and a
default that changes arrives with a pull, not with a command for him.
"""

import os
import tempfile
import threading

MODEL = os.environ.get("YUZU_WHISPER_MODEL", "base.en")

# Bigger than any sensible walkie-talkie message. The page stops a
# recording at 60 seconds by itself, so this only ever catches
# something that is not a recording from her page.
MAX_BYTES = 10 * 1024 * 1024

# What a browser's MediaRecorder hands over, and the suffix the decoder
# wants to see. Anything else is tried as webm, which is what Chrome
# records.
SUFFIX = {
    "audio/webm": ".webm", "video/webm": ".webm",
    "audio/ogg": ".ogg", "audio/mp4": ".mp4", "audio/mpeg": ".mp3",
    "audio/wav": ".wav", "audio/x-wav": ".wav", "audio/wave": ".wav",
}

_MODEL = None
_LOCK = threading.Lock()

NOT_INSTALLED = ("She can't hear yet -- run ~/YUZU/pull once and it "
                 "sets her ears up. Typing works as always.")


def _load():
    """The model, loaded once and kept -- a reload per recording would
    cost seconds every time he taps. Raises if it cannot be had."""
    global _MODEL
    with _LOCK:
        if _MODEL is None:
            from faster_whisper import WhisperModel
            try:
                _MODEL = WhisperModel(MODEL, device="cpu",
                                      compute_type="int8",
                                      local_files_only=True)
            except ValueError:
                # int8 is not on every CPU build; the default always is.
                _MODEL = WhisperModel(MODEL, device="cpu",
                                      local_files_only=True)
    return _MODEL


def why_not():
    """"" when she can hear right now, otherwise the sentence that says
    why not. One question, asked by `pull` and by the route alike, so
    the two can never disagree about whether she has ears."""
    try:
        import faster_whisper  # noqa: F401
    except ImportError:
        return NOT_INSTALLED
    try:
        _load()
    except Exception as exc:
        return ("Her ears are installed but the %s model is not on the "
                "board (%s). Run ~/YUZU/pull once." % (MODEL, type(exc).__name__))
    return ""


def transcribe(audio, content_type=""):
    """(what he said, problem). Exactly one of them is set. Never raises."""
    if not audio:
        return "", "Nothing was recorded -- tap the mic, talk, tap again."
    if len(audio) > MAX_BYTES:
        return "", "That recording is too long for her -- keep it under a minute."
    problem = why_not()
    if problem:
        return "", problem
    kind = (content_type or "").split(";")[0].strip().lower()
    fd, path = tempfile.mkstemp(prefix="yuzu-heard-", suffix=SUFFIX.get(kind, ".webm"))
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(audio)
        # vad_filter drops the silence either side of what he said, so
        # a slow second tap does not become a line of "you".
        segments, _info = _load().transcribe(path, language="en", beam_size=5,
                                             vad_filter=True)
        said = " ".join(seg.text.strip() for seg in segments).strip()
    except Exception as exc:
        return "", "Couldn't make that recording out (%s)." % type(exc).__name__
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
    if not said:
        return "", "I didn't catch anything -- try again, a little closer."
    return said, None


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1:
        with open(sys.argv[1], "rb") as f:
            heard, problem = transcribe(f.read())
        print(heard or problem)
    else:
        print(why_not() or "She can hear (%s)." % MODEL)
