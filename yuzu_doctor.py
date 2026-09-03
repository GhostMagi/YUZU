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
import re
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

# Kept in step with what the repo actually ships. This listed
# "yuzu_system_prompt.txt" long after personas/ replaced it, so every
# run on every machine reported one permanent missing file and could
# never say "all present" -- a warning that is always on teaches you to
# ignore warnings, which is the opposite of what this script is for.
EXPECTED = {
    "yuzu_all_in_one.py":     "the main loop -- talk to Yuzu",
    "yuzu_brain.py":          "the Ollama client",
    "yuzu_personas.py":       "persona loader (Yuzu's personality)",
    "personas":               "the persona + body files",
    "yuzu_robot_config.json": "LED config",
    "muto_leg_control.py":    "leg gaits + simulator",
    "muto_firstcontact.py":   "guided first bring-up on real servos",
    "yuzu_voice.py":          "Piper TTS (her voice)",
    "yuzu_led_manager.py":    "LED manager",
    "YUZU_TESTER.py":         "the test suite",
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
# 5. JETSON TUNING  (skipped everywhere else, including the phone)
# =====================================================================

# What the Orin Nano Super wants, and why. Every one of these is about
# the same 8GB shared between CPU and GPU -- there is no separate VRAM
# to spill into, so anything that reserves memory reserves it from the
# same pool Whisper and Piper will want later.
OLLAMA_TUNING = {
    "OLLAMA_NUM_PARALLEL": (
        "1",
        "Ollama sizes the KV cache as num_ctx x num_parallel. Left to "
        "pick for itself it can reserve several slots you will never "
        "use, and each one costs real memory out of the 8GB.",
    ),
    "OLLAMA_MAX_LOADED_MODELS": (
        "1",
        "Stops a second model being held resident alongside the 3B. On "
        "8GB shared, two models is how you land in swap.",
    ),
    "OLLAMA_KEEP_ALIVE": (
        "-1",
        "Keeps her loaded instead of unloading after 5 idle minutes. "
        "Otherwise the first thing anyone says to her after a quiet "
        "spell is the slowest reply she ever gives.",
    ),
    "OLLAMA_FLASH_ATTENTION": (
        "1",
        "Cheaper attention, less memory per token of context.",
    ),
    "OLLAMA_KV_CACHE_TYPE": (
        "q8_0",
        "Quantises the KV cache, roughly halving what the context costs "
        "in memory. Needs flash attention on.",
    ),
}


def _read_text(path):
    """Read a system file, or None. Everything in this section is a
    plain file read -- no subprocess, no sudo, nothing that can hang or
    need a password on a box you are SSH'd into from a Steam Deck."""
    try:
        return Path(path).read_text(errors="replace")
    except (OSError, PermissionError):
        return None


def jetson_power_mode():
    """(mode_number, raw_line) from nvpmodel's own status file.

    /var/lib/nvpmodel/status is where nvpmodel records the mode it last
    applied, as e.g. 'pmode:0000 fmode:fanmode_quiet'. Mode 0 is
    MAXN / MAXN SUPER. Anything else means the board is still throttled.
    Returns None if the file isn't there or doesn't parse, and the
    caller falls back to just printing the reminder.
    """
    raw = _read_text("/var/lib/nvpmodel/status")
    if not raw:
        return None
    for token in raw.split():
        if token.startswith("pmode:"):
            try:
                return int(token.split(":", 1)[1]), raw.strip()
            except ValueError:
                return None
    return None


def memory_picture():
    """Total RAM and swap in GiB, plus what the swap actually sits on."""
    totals = {}
    for line in (_read_text("/proc/meminfo") or "").splitlines():
        key, _, rest = line.partition(":")
        parts = rest.split()
        if parts and parts[0].isdigit():
            totals[key] = int(parts[0]) / (1024.0 * 1024.0)

    devices = []
    for line in (_read_text("/proc/swaps") or "").splitlines()[1:]:
        parts = line.split()
        if parts:
            devices.append((parts[0], parts[1] if len(parts) > 1 else "?"))
    return totals, devices


def ollama_service_env():
    """Environment= lines from Ollama's systemd unit and its drop-ins.

    Reading the unit, not os.environ: these are set for the ollama
    SERVICE, and the shell running this script does not inherit them.
    Checking os.environ would confidently report 'not set' on a box
    where they are set correctly, which is worse than not checking.
    """
    paths = [Path("/etc/systemd/system/ollama.service")]
    drop_in = Path("/etc/systemd/system/ollama.service.d")
    if drop_in.is_dir():
        try:
            paths.extend(sorted(drop_in.glob("*.conf")))
        except OSError:
            pass

    found, seen_any = {}, False
    for path in paths:
        raw = _read_text(path)
        if raw is None:
            continue
        seen_any = True
        for line in raw.splitlines():
            line = line.strip()
            if not line.startswith("Environment="):
                continue
            for pair in re.findall(r'([A-Z_][A-Z0-9_]*)=("[^"]*"|\S+)',
                                   line[len("Environment="):]):
                found[pair[0]] = pair[1].strip('"')
    return (found if seen_any else None)


def check_jetson():
    """Everything in this section is Jetson-only. On the phone, on the
    laptop, on the Steam Deck it does not run at all."""
    if not on_a_jetson():
        return
    header("5. JETSON TUNING")

    board = (_read_text("/sys/firmware/devicetree/base/model") or "").strip("\x00\n ")
    release = (_read_text("/etc/nv_tegra_release") or "").splitlines()
    if board:
        print(f" board    {board}")
    if release:
        print(f" L4T      {release[0].strip()}")

    # --- power mode ---------------------------------------------------
    mode = jetson_power_mode()
    if mode is None:
        say(INFO, "Couldn't read the power mode -- check it with: nvpmodel -q")
    elif mode[0] == 0:
        say(GOOD, "Power mode 0 (MAXN) -- not throttled")
    else:
        say(BAD, f"Power mode {mode[0]}, NOT 0. The board is throttled. "
                 f"Run: sudo nvpmodel -m 0 && sudo jetson_clocks")

    # --- memory -------------------------------------------------------
    totals, swap_devices = memory_picture()
    if totals.get("MemTotal"):
        print(f" RAM      {totals['MemTotal']:.1f} GiB total, "
              f"{totals.get('MemAvailable', 0):.1f} GiB available")
    if not swap_devices:
        say(WARN, "No swap. On 8GB shared, swap is the difference between "
                  "a slow reply and an out-of-memory kill.")
    else:
        for device, kind in swap_devices:
            size = totals.get("SwapTotal", 0)
            if "nvme" in device:
                say(GOOD, f"Swap on NVMe ({device}, {size:.1f} GiB) -- "
                          f"the right place for it")
            elif "zram" in device:
                say(WARN, f"Swap is zram ({device}) -- it trades CPU for "
                          f"RAM, which is the wrong trade under an LLM. "
                          f"A swapfile on the NVMe is better.")
            elif "mmcblk" in device:
                say(WARN, f"Swap on the SD card ({device}) -- miserable "
                          f"under sustained writes, and it wears the card "
                          f"out. Move it to the NVMe.")
            else:
                say(INFO, f"Swap on {device} ({kind}, {size:.1f} GiB)")

    # --- Ollama service settings --------------------------------------
    env = ollama_service_env()
    if env is None:
        say(INFO, "No Ollama systemd unit found -- install it, or you're "
                  "running `ollama serve` by hand")
        return
    print("\n Ollama service settings (from its systemd unit):")
    unset = []
    for name, (want, why) in OLLAMA_TUNING.items():
        have = env.get(name)
        if have is None:
            unset.append((name, want, why))
            print(f"   {name:<26} not set   (want {want})")
        else:
            flag = "" if have == want else f"   <-- want {want}"
            print(f"   {name:<26} {have}{flag}")
    if unset:
        say(WARN, f"{len(unset)} Ollama memory setting(s) not set -- see "
                  f"JETSON_SETUP.md, 'Ollama on 8GB'")
        for name, want, why in unset:
            print(f"\n   {name}={want}")
            print(f"     {why}")
    else:
        say(GOOD, "Ollama's memory settings are all tuned for 8GB")


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
    check_jetson()
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
