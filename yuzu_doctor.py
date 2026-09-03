"""
YUZU DOCTOR -- open this in Pydroid and press Run. That's it.

No commands to type. No file paths to enter. No arguments. It looks
around your phone by itself, checks what's working, finds your GGUF if
it can reach it, and prints a summary at the bottom you can screenshot
and send to Claude.

This file works ALONE. You don't need the rest of the project for it
to run -- download just this one file if that's easier. If the other
Yuzu files happen to be in the same folder, it checks those too.
"""

import json
import os
import struct
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
START = time.time()
SEARCH_BUDGET = 25          # seconds; Android storage can be slow
MAX_DEPTH = 6

notes = []                  # (status, message) for the final summary
GOOD, WARN, BAD, INFO = "OK", "!!", "XX", "--"


def say(status, message):
    notes.append((status, message))
    print(f" [{status}] {message}")


def header(title):
    print(f"\n{'=' * 54}\n {title}\n{'=' * 54}")


# =====================================================================
# 1. WHERE ARE WE
# =====================================================================

def check_environment():
    header("1. WHERE THIS IS RUNNING")
    print(f" python   {sys.version.split()[0]}")
    print(f" platform {sys.platform}")
    print(f" folder   {HERE}")

    on_android = (
        "ANDROID_STORAGE" in os.environ
        or Path("/system/build.prop").exists()
        or "com.termux" in str(HERE)
        or "pydroid" in str(HERE).lower()
        or "iiec" in str(HERE).lower()
    )
    if on_android:
        say(GOOD, "Running on Android (Pydroid or similar)")
    else:
        say(INFO, "Running on a desktop/laptop, not a phone")
    return on_android


# =====================================================================
# 2. WHICH YUZU FILES ARE HERE
# =====================================================================

EXPECTED = {
    "yuzu_all_in_one.py":     "the main loop -- talk to Yuzu",
    "yuzu_brain.py":          "the Ollama client",
    "yuzu_system_prompt.txt": "Yuzu's personality",
    "yuzu_robot_config.json": "LED config",
    "muto_leg_control.py":    "leg gaits + simulator",
    "yuzu_led_manager.py":    "LED manager",
    "YUZU_TESTER.py":           "the test suite",
    "yuzu_prompt_eval.py":    "prompt scoring",
}


def check_project_files():
    header("2. YUZU FILES IN THIS FOLDER")
    present = [n for n in EXPECTED if (HERE / n).exists()]
    missing = [n for n in EXPECTED if n not in present]

    for name in present:
        print(f"  found    {name:<24} {EXPECTED[name]}")
    for name in missing:
        print(f"  missing  {name:<24} {EXPECTED[name]}")

    if not present:
        say(INFO, "Running standalone -- no other Yuzu files here (that's fine)")
    elif missing:
        say(WARN, f"{len(present)}/{len(EXPECTED)} Yuzu files here, {len(missing)} missing")
    else:
        say(GOOD, "All Yuzu files present")
    return present


# =====================================================================
# 3. DOES THE ACTION PARSER STILL WORK
# =====================================================================

def check_parser(present):
    header("3. DOES YUZU'S PARSER WORK")
    if "yuzu_all_in_one.py" not in present:
        say(INFO, "Skipped -- yuzu_all_in_one.py isn't in this folder")
        return
    sys.path.insert(0, str(HERE))
    try:
        import yuzu_all_in_one as yz
    except Exception as exc:
        say(BAD, f"yuzu_all_in_one.py won't import: {exc}")
        return

    sample = "Not much, just vibing! [squats] [shakes legs] What's good?"
    try:
        parts = yz.split_reply(yz.normalize_actions(sample))
        speech = [v for k, v in parts if k == "speech"]
        actions = [v for k, v in parts if k == "action"]
        matched = [a for a in actions if yz.lookup_action(a)]
        print(f"  test reply : {sample}")
        print(f"  she says   : {speech}")
        print(f"  she does   : {actions}")
        if speech and len(matched) == len(actions) == 2:
            say(GOOD, "Parser is working -- speech and actions both correct")
        else:
            say(BAD, "Parser gave an unexpected result")
    except Exception as exc:
        say(BAD, f"Parser crashed: {exc}")


# =====================================================================
# 4. FIND A GGUF ON THIS DEVICE
# =====================================================================

SKIP_DIRS = {
    "proc", "sys", "dev", "node_modules", ".git", "__pycache__",
    "cache", "Android", ".thumbnails", "obb",
}


def find_ggufs():
    """Walk the places Pydroid can actually read. PocketPal's own
    downloads live in app-private storage that other apps can't see,
    so this finds a GGUF only if it's somewhere shared -- Downloads,
    Documents, or a folder you made."""
    roots, seen = [], set()
    for candidate in [
        HERE,
        Path("/sdcard"), Path("/storage/emulated/0"),
        Path("/sdcard/Download"), Path("/sdcard/Documents"),
        Path.home(),
    ]:
        try:
            if candidate.exists():
                real = candidate.resolve()
                if real not in seen:
                    seen.add(real)
                    roots.append(candidate)
        except (OSError, PermissionError):
            pass

    found, blocked = [], 0
    for root in roots:
        base_depth = len(Path(root).parts)
        for dirpath, dirnames, filenames in os.walk(root, onerror=lambda e: None):
            if time.time() - START > SEARCH_BUDGET:
                print("  (search time limit reached, stopping here)")
                return found, blocked, True
            if len(Path(dirpath).parts) - base_depth >= MAX_DEPTH:
                dirnames[:] = []
                continue
            dirnames[:] = [d for d in dirnames
                           if d not in SKIP_DIRS and not d.startswith(".")]
            for name in filenames:
                if name.lower().endswith(".gguf"):
                    path = Path(dirpath) / name
                    try:
                        if path.stat().st_size > 1024:
                            found.append(path)
                    except (OSError, PermissionError):
                        blocked += 1
    return found, blocked, False


# --- minimal GGUF header reader, inlined so this file stands alone ---

_FIXED = {0: ("<B", 1), 1: ("<b", 1), 2: ("<H", 2), 3: ("<h", 2),
          4: ("<I", 4), 5: ("<i", 4), 6: ("<f", 4), 7: ("<?", 1),
          10: ("<Q", 8), 11: ("<q", 8), 12: ("<d", 8)}
QUANTS = {0: "F32", 1: "F16", 2: "Q4_0", 7: "Q8_0", 10: "Q2_K", 11: "Q3_K_S",
          12: "Q3_K_M", 13: "Q3_K_L", 14: "Q4_K_S", 15: "Q4_K_M",
          16: "Q5_K_S", 17: "Q5_K_M", 18: "Q6_K", 30: "BF16"}


def read_gguf_header(path):
    with open(path, "rb") as fh:
        buf, pos = fh.read(1 << 20), 0

        def need(n):
            nonlocal buf
            while len(buf) - pos < n:
                more = fh.read(max(1 << 20, n))
                if not more:
                    raise ValueError("file ends mid-header (truncated download)")
                buf += more

        def raw(n):
            nonlocal pos
            need(n)
            out = buf[pos:pos + n]
            pos += n
            return out

        def scalar(t):
            fmt, size = _FIXED[t]
            return struct.unpack(fmt, raw(size))[0]

        def string():
            n = scalar(10)
            if n > 64 * 1024 * 1024:
                raise ValueError("not a GGUF file")
            return raw(n).decode("utf-8", "replace")

        def value(t):
            if t == 8:
                return string()
            if t == 9:
                et, count = scalar(4), scalar(10)
                keep = min(count, 4)
                items = [value(et) for _ in range(keep)]
                for _ in range(count - keep):
                    value(et)
                return {"count": count, "sample": items}
            return scalar(t)

        if raw(4) != b"GGUF":
            raise ValueError("not a GGUF file (wrong magic bytes)")
        version, _tensors, kv_count = scalar(4), scalar(10), scalar(10)
        meta = {}
        for _ in range(kv_count):
            key = string()
            meta[key] = value(scalar(4))
        return version, meta


def describe_gguf(path):
    print(f"\n  {path}")
    size_gb = path.stat().st_size / 1e9
    print(f"    size          {size_gb:.2f} GB")
    try:
        version, meta = read_gguf_header(path)
    except (ValueError, OSError) as exc:
        say(BAD, f"{path.name}: {exc}")
        return None

    arch = meta.get("general.architecture", "?")
    name = meta.get("general.name", "(unnamed)")
    quant = QUANTS.get(meta.get("general.file_type"), meta.get("general.file_type"))
    ctx = meta.get(f"{arch}.context_length")
    print(f"    name          {name}")
    print(f"    architecture  {arch}")
    print(f"    quantization  {quant}")
    print(f"    context       {ctx}")
    print(f"    gguf version  {version}")

    template = meta.get("tokenizer.chat_template")
    if not template:
        say(BAD, f"{path.name}: NO CHAT TEMPLATE -- persona will be ignored")
        verdict = "missing"
    else:
        family = ("llama 3.x" if "<|start_header_id|>" in template else
                  "chatml" if "<|im_start|>" in template else
                  "mistral" if "[INST]" in template else "unrecognised")
        handles_system = (
            "system" in template.lower()
            or ("messages" in template
                and ("['role']" in template or '["role"]' in template
                     or ".role" in template))
        )
        print(f"    template      present, looks like {family}")
        if handles_system:
            say(GOOD, f"{path.name}: chat template present and handles a system role")
            verdict = "ok"
        else:
            say(BAD, f"{path.name}: template drops the system role -- persona ignored")
            verdict = "no-system"

    return {"file": path.name, "size_gb": round(size_gb, 2), "name": name,
            "arch": arch, "quant": quant, "context": ctx,
            "template": verdict}


def check_gguf():
    header("4. LOOKING FOR YOUR MODEL FILE")
    print(" Searching your phone's shared storage (this can take a moment)...")
    found, blocked, timed_out = find_ggufs()

    if not found:
        say(WARN, "No .gguf file found in shared storage")
        print("""
 That's expected if PocketPal downloaded the model itself -- Android
 keeps each app's downloads private, so Pydroid genuinely cannot see
 into PocketPal's folder. Nothing is broken.

 EASIEST FIX -- no files to move:
   Open PocketPal -> Models -> tap your model -> screenshot that
   screen. The model name and quant is all Claude needs.

 IF YOU WANT THE FULL CHECK:
   Download the .gguf again through your phone's browser instead of
   in-app. It lands in Downloads, where this script can read it.
   Then press Run again.""")
        if blocked:
            print(f"\n ({blocked} file(s) were there but Android blocked reading them)")
        return []

    say(GOOD, f"Found {len(found)} GGUF file(s)")
    return [d for d in (describe_gguf(p) for p in found[:5]) if d]


# =====================================================================
# 5. SUMMARY -- screenshot this part
# =====================================================================

def on_a_jetson():
    """True on Jetson hardware. Two well-known markers, both plain files
    so nothing has to be executed. Wrapped because this runs on a phone
    too, where none of these paths exist."""
    try:
        if Path("/etc/nv_tegra_release").exists():
            return True
        model = Path("/sys/firmware/devicetree/base/model")
        if model.exists():
            name = model.read_bytes().decode("utf-8", "replace").lower()
            return "jetson" in name or "orin" in name
    except OSError:
        pass
    return False


def throttle_reminder():
    """The one command Ghost asked to be reminded of.

    The Orin Nano ships in a low power mode. nvpmodel -m 0 is the single
    biggest free speedup on the box and it is easy to forget after a
    flash -- at which point everything just feels slow for no visible
    reason, which is the worst kind of problem to debug.

    Printed here, at the robot's boot, and at the top of the README:
    three places he actually lands, rather than one he has to remember
    to go looking for.
    """
    print("\n  !! JETSON: the board ships THROTTLED. Run this once:")
    print("       sudo nvpmodel -m 0     # MAXN / MAXN SUPER, max power")
    print("       sudo jetson_clocks     # lock the clocks up there")
    print("     Details in JETSON_SETUP.md.")


def summary(models):
    header("SUMMARY  <-- screenshot from here down")
    if on_a_jetson():
        throttle_reminder()
        print()
    counts = {GOOD: 0, WARN: 0, BAD: 0, INFO: 0}
    for status, message in notes:
        counts[status] += 1
        print(f" [{status}] {message}")

    print(f"\n {counts[GOOD]} ok, {counts[WARN]} warnings, {counts[BAD]} problems")

    if models:
        print("\n --- paste this to Claude ---")
        print(json.dumps(models, indent=1))
        print(" --- end ---")

    print("\n What to do next:")
    if counts[BAD]:
        print("  Send the summary above to Claude. Something needs fixing.")
    elif not models:
        print("  Screenshot your model's page in PocketPal and send that.")
    else:
        print("  Your model looks healthy. Send this summary to Claude and")
        print("  he can check the persona prompt against it.")
    print()


def main():
    print("\n" + "*" * 54)
    print(" YUZU DOCTOR -- checking your setup, hang tight")
    print("*" * 54)
    check_environment()
    present = check_project_files()
    check_parser(present)
    models = check_gguf()
    summary(models)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\nStopped.")
    except Exception as exc:
        # Never dump a raw traceback at someone who just tapped Run.
        print(f"\n\nThe doctor itself hit a problem: {type(exc).__name__}: {exc}")
        print("Screenshot this and send it to Claude -- it's a bug in the")
        print("script, not in your setup.")
