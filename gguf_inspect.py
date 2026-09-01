"""
Read a GGUF file's header and print what actually matters for getting
it running as Yuzu. Stdlib only -- no gguf package, no torch, no
llama.cpp. Reads a few hundred KB off the front of the file, never the
weights, so it's instant even on a 20GB model.

    python gguf_inspect.py path/to/model.gguf
    python gguf_inspect.py model.gguf --template     # dump chat template
    python gguf_inspect.py model.gguf --all          # every metadata key

Why this exists: the most common way a converted or third-party GGUF
goes wrong is the chat template. Ollama reads the template out of GGUF
metadata; if it's missing or wrong, the model still loads and still
generates -- it just ignores the system prompt, or starts talking to
itself, or answers as the user. Which looks like a bad persona prompt
and isn't. This tells you in one command.
"""

import argparse
import json
import re
import struct
import sys
from pathlib import Path

GGUF_MAGIC = b"GGUF"

# GGUF metadata value types, from the format spec.
(UINT8, INT8, UINT16, INT16, UINT32, INT32, FLOAT32, BOOL, STRING,
 ARRAY, UINT64, INT64, FLOAT64) = range(13)

_FIXED = {
    UINT8: ("<B", 1), INT8: ("<b", 1),
    UINT16: ("<H", 2), INT16: ("<h", 2),
    UINT32: ("<I", 4), INT32: ("<i", 4),
    FLOAT32: ("<f", 4), BOOL: ("<?", 1),
    UINT64: ("<Q", 8), INT64: ("<q", 8), FLOAT64: ("<d", 8),
}

# llama.cpp's file-type enum. Only the ones you'd plausibly be running.
FILE_TYPES = {
    0: "F32", 1: "F16", 2: "Q4_0", 3: "Q4_1", 7: "Q8_0",
    8: "Q5_0", 9: "Q5_1", 10: "Q2_K", 11: "Q3_K_S", 12: "Q3_K_M",
    13: "Q3_K_L", 14: "Q4_K_S", 15: "Q4_K_M", 16: "Q5_K_S",
    17: "Q5_K_M", 18: "Q6_K", 19: "IQ2_XXS", 20: "IQ2_XS",
    30: "BF16",
}


class GGUFError(RuntimeError):
    pass


class _Reader:
    """Buffered forward-only reader. Grows its window as needed so a
    long chat template or a 128k-entry token list still parses without
    loading the whole model."""

    def __init__(self, fh, chunk=1 << 20):
        self.fh = fh
        self.chunk = chunk
        self.buf = fh.read(chunk)
        self.pos = 0

    def _need(self, n):
        while len(self.buf) - self.pos < n:
            more = self.fh.read(max(self.chunk, n))
            if not more:
                raise GGUFError("File ended mid-header -- truncated download?")
            self.buf += more

    def raw(self, n):
        self._need(n)
        out = self.buf[self.pos:self.pos + n]
        self.pos += n
        return out

    def scalar(self, vtype):
        fmt, size = _FIXED[vtype]
        return struct.unpack(fmt, self.raw(size))[0]

    def string(self):
        length = self.scalar(UINT64)
        if length > 64 * 1024 * 1024:
            raise GGUFError(f"Absurd string length {length} -- not a GGUF?")
        return self.raw(length).decode("utf-8", "replace")

    def value(self, vtype):
        if vtype == STRING:
            return self.string()
        if vtype == ARRAY:
            elem_type = self.scalar(UINT32)
            count = self.scalar(UINT64)
            # Token lists run to 100k+ entries; keep a sample, not the lot.
            keep = min(count, 8)
            items = [self.value(elem_type) for _ in range(keep)]
            for _ in range(count - keep):
                self.value(elem_type)
            return {"_array": True, "count": count, "sample": items}
        if vtype in _FIXED:
            return self.scalar(vtype)
        raise GGUFError(f"Unknown GGUF value type {vtype}")


def read_metadata(path):
    with open(path, "rb") as fh:
        reader = _Reader(fh)
        magic = reader.raw(4)
        if magic != GGUF_MAGIC:
            raise GGUFError(
                f"Not a GGUF file -- starts with {magic!r}, expected {GGUF_MAGIC!r}.\n"
                f"If you downloaded from Hugging Face, check you got the file "
                f"itself and not an LFS pointer or an HTML error page."
            )
        version = reader.scalar(UINT32)
        if version not in (2, 3):
            print(f"warning: GGUF version {version} is newer than this "
                  f"script knows about; parsing anyway", file=sys.stderr)
        tensor_count = reader.scalar(UINT64)
        kv_count = reader.scalar(UINT64)

        meta = {}
        for _ in range(kv_count):
            key = reader.string()
            meta[key] = reader.value(reader.scalar(UINT32))

    return {"version": version, "tensor_count": tensor_count, "meta": meta}


def _fmt(value):
    if isinstance(value, dict) and value.get("_array"):
        sample = ", ".join(repr(s)[:22] for s in value["sample"][:4])
        return f"[{value['count']} items] {sample}..."
    text = str(value)
    return text if len(text) <= 70 else text[:67] + "..."


def report(path, info, show_template=False, show_all=False):
    meta = info["meta"]
    arch = meta.get("general.architecture", "?")
    size_gb = Path(path).stat().st_size / 1e9

    print(f"\n{'=' * 62}\n{Path(path).name}\n{'=' * 62}")
    print(f"{'size':<22} {size_gb:.2f} GB")
    print(f"{'gguf version':<22} {info['version']}   ({info['tensor_count']} tensors)")
    print(f"{'architecture':<22} {arch}")

    for label, key in (
        ("name", "general.name"),
        ("basename", "general.basename"),
        ("size label", "general.size_label"),
        ("finetune", "general.finetune"),
    ):
        if key in meta:
            print(f"{label:<22} {_fmt(meta[key])}")

    ftype = meta.get("general.file_type")
    if ftype is not None:
        print(f"{'quantization':<22} {FILE_TYPES.get(ftype, f'type {ftype}')}")

    print()
    for label, key in (
        ("context length", f"{arch}.context_length"),
        ("embedding length", f"{arch}.embedding_length"),
        ("block count", f"{arch}.block_count"),
        ("rope freq base", f"{arch}.rope.freq_base"),
    ):
        if key in meta:
            print(f"{label:<22} {_fmt(meta[key])}")

    print()
    tok_model = meta.get("tokenizer.ggml.model", "?")
    print(f"{'tokenizer':<22} {tok_model}")
    for label, key in (
        ("bos token id", "tokenizer.ggml.bos_token_id"),
        ("eos token id", "tokenizer.ggml.eos_token_id"),
        ("padding token id", "tokenizer.ggml.padding_token_id"),
        ("vocab size", "tokenizer.ggml.tokens"),
    ):
        if key in meta:
            print(f"{label:<22} {_fmt(meta[key])}")

    # --- the part that actually matters ---
    template = meta.get("tokenizer.chat_template")
    print(f"\n{'-' * 62}")
    if not template:
        print("CHAT TEMPLATE: *** MISSING ***\n")
        print("This is the thing that breaks converted GGUFs. Without a")
        print("template Ollama falls back to a generic one, and a Llama 3.2")
        print("model fed the wrong format will ignore the system prompt or")
        print("start writing both sides of the conversation. It still loads")
        print("and still generates -- it just won't be Yuzu.")
        print("\nFix: add an explicit TEMPLATE block to Modelfile.yuzu, or")
        print("re-convert with the tokenizer_config.json from the source repo.")
    else:
        print(f"CHAT TEMPLATE: present ({len(template)} chars)")
        markers = {
            "llama 3.x": "<|start_header_id|>",
            "chatml": "<|im_start|>",
            "mistral": "[INST]",
            "gemma": "<start_of_turn>",
        }
        found = [name for name, marker in markers.items() if marker in template]
        print(f"looks like:   {', '.join(found) if found else 'unrecognised format'}")
        # Two ways a template can handle a system message: an explicit
        # branch that names it, or a generic loop that emits whatever
        # role each message carries. Llama 3.2's stock template is the
        # second kind -- the word "system" never appears in it -- so
        # checking for the literal string alone gives a false alarm.
        explicit = "system" in template.lower()
        generic = ("messages" in template
                   and re.search(r"\[['\"]role['\"]\]|\.role\b", template))
        if explicit:
            print("handles a system role: yes (explicit branch)")
        elif generic:
            print("handles a system role: yes (generic role loop)")
        else:
            print("handles a system role: NO")
            print("  ^^ this template neither names a system role nor emits")
            print("     each message's role, so Yuzu's personality gets")
            print("     DROPPED. It's the #1 cause of 'she sounds like a")
            print("     stock assistant'. Verify with:")
            print("       ollama show yuzu --template")
        if show_template:
            print(f"\n{'- template ' + '-' * 50}\n{template}\n{'-' * 62}")
        else:
            print("(--template to print it in full)")

    if show_all:
        print(f"\n{'-' * 62}\nALL METADATA ({len(meta)} keys)\n{'-' * 62}")
        for key in sorted(meta):
            if key == "tokenizer.chat_template":
                continue
            print(f"{key:<44} {_fmt(meta[key])}")

    print(f"\n{'-' * 62}\nUse it with:")
    print(f"  python build_yuzu_model.py --base {path} --create")
    print(f"  python yuzu_prompt_eval.py --runs 3")
    print()


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("gguf", help="path to a .gguf file")
    parser.add_argument("--template", action="store_true",
                        help="print the full chat template")
    parser.add_argument("--all", action="store_true",
                        help="print every metadata key")
    parser.add_argument("--json", action="store_true",
                        help="machine-readable dump (paste-friendly)")
    args = parser.parse_args(argv)

    path = Path(args.gguf)
    if not path.exists():
        print(f"No such file: {path}")
        return 1
    try:
        info = read_metadata(path)
    except GGUFError as exc:
        print(f"\n{exc}\n")
        return 1

    if args.json:
        meta = info["meta"]
        print(json.dumps({
            "file": path.name,
            "size_bytes": path.stat().st_size,
            "gguf_version": info["version"],
            "tensor_count": info["tensor_count"],
            "architecture": meta.get("general.architecture"),
            "name": meta.get("general.name"),
            "quantization": FILE_TYPES.get(meta.get("general.file_type"),
                                           meta.get("general.file_type")),
            "context_length": meta.get(
                f"{meta.get('general.architecture')}.context_length"),
            "bos_token_id": meta.get("tokenizer.ggml.bos_token_id"),
            "eos_token_id": meta.get("tokenizer.ggml.eos_token_id"),
            "tokenizer_model": meta.get("tokenizer.ggml.model"),
            "chat_template": meta.get("tokenizer.chat_template"),
        }, indent=2))
        return 0

    report(path, info, args.template, args.all)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
