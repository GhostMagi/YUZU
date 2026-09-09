#!/usr/bin/env python3
"""Her pet. A creature on the deck you can poke -- NOT a chore.

Ghost's spec, Sept 11: a Digimon/Tamagotchi-style creature page, its own
world, full colour, separate from Saya's face. Sprites sourced from
itch.io rather than drawn.

Then, immediately and importantly: *"dont make him require food id like
it to be more of an interactive bare bones game almost. not a
babysitting program per se (on the surface sure)."*

**SO THERE ARE NO NEEDS.** No hunger, no energy budget, no fail state,
nothing that is WORSE for having been ignored. It looks like a v-pet on
the surface and underneath it is a toy: you open it, he does something,
you poke him, he reacts. That is the entire game in v1.

Two numbers only, and neither of them can nag:

    mood   drifts back to NEUTRAL over time, never to empty. A week
           away leaves him quiet and a bit aloof -- exactly what Ghost
           asked for -- rather than sad, starving or dead.
    bond   only ever goes UP, slowly, and never decays at all. It is
           the hook the evolution stages hang off later, and it means
           time spent is never taken away from him.

**GRUMPY IS THE ONE NEGATIVE, and it is a REACTION rather than a
punishment.** Poke him over and over and he gets fed up for a minute.
That is what the `sad` sprite is for -- it earns its place as a
character beat instead of as a guilt trip, and it wears off by itself.

    ui/vpet/<who>/<state>.png  demon/idle.png, orc/walk.png ...
    ui/vpet/bg.jpg             the room, shared by all of them

**A FOLDER IS A CHARACTER.** Ghost, Sept 11: "can you add the orc as an
option to select from." So the cast is whatever folders are in there,
one button cycles between them, and adding a fifth creature is copying
five PNGs into a new folder -- no list, no code, no menu to maintain.
Loose files directly in ui/vpet/ still work and read as a character
called `pet`, so the older "just drop a file in" instruction was not
quietly broken by this.

**THE FILENAME IS THE STATE**, exactly like her face. Drop `sleep.png`
in and he can sleep; leave it out and that state falls back to whatever
else exists. No manifest, nothing to keep in sync, and a pack
downloaded at 2am works on the next page refresh.

**A SPRITE STRIP IS READ AS A STRIP, WITH NO SLICING STEP.** The packs
Ghost is buying ship one PNG per animation -- `Demon_A_Idle.png` is
600x100, which is six 100x100 cels in a row. A file whose width is an
exact multiple of its height IS that many frames, and the page walks
across it with `background-position`. No PIL, no build step, no
generated files: the thing he downloaded is the thing that runs.

    idle.png   600x100  ->  6 frames
    sleep.png  100x100  ->  1 frame
    idle_1.png, idle_2.png  ->  still works, two separate frames

**AND THE PACK'S OWN NAMES ARE ACCEPTED.** `Demon_A_Idle.png` is read
as `idle` -- the state is the last word, and a trailing `_<number>` is
a frame index. Making him rename fourteen files before anything appears
on screen is the kind of friction that stops a thing being used, and
this repo already learned that lesson from `/wiki`.

**NO BACKGROUND PROCESS.** Mood drifts from a timestamp, computed when
the page opens. A daemon on this board would be one more thing to
start, one more thing to leave running, and one more thing to explain
when it is not.

**THE STATE FILE LIVES OUTSIDE THE REPO**, in ~/.yuzu/. That is not
tidiness: a file inside the repo is a local change, and `~/YUZU/pull`
stops on local changes rather than overwriting them. His pet would have
blocked every update Ghost ever ran.
"""

import json
import os
import struct
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PET_DIR = os.path.join(HERE, "ui", "vpet")
EXTS = (".png", ".gif", ".webp", ".jpg", ".jpeg")

NOT_A_STATE = ("bg",)          # the room is not something he can be

STATE_FILE = os.path.join(os.path.expanduser("~"), ".yuzu", "vpet.json")

# What the page asks for, mapped onto whatever art the pack actually
# has. First match wins and each role falls back down its own list, so
# a two-sprite pack still works -- the same ROLES trick her face uses,
# and the same rule: never point a state at art that means something
# else.
ROLES = {
    "idle":  ("idle", "neutral", "stand", "happy"),
    "walk":  ("walk", "move", "run", "idle"),
    # PLAY MAKES HIM SWING THE BLADE. An attack animation is the best
    # thing in one of these packs and no pet sim ever uses it; here it
    # is what "play" looks like, which is both funnier and free.
    "happy": ("happy", "cheer", "attack01", "attack", "eat", "idle"),
    "sad":   ("sad", "hurt", "angry", "sleepy", "idle"),
    "sleep": ("sleep", "sleepy", "idle"),
}

NEUTRAL = 50          # where mood drifts to, and it is NOT zero
DRIFT_PER_HOUR = 3.0  # a day away lands him back at neutral, no worse
GRUMPY_FOR = 90       # seconds of being fed up after too much poking
POKES_BEFORE_GRUMPY = 5

FRESH = {"mood": 60, "bond": 0, "sleeping": False, "who": "",
         "pokes": 0, "grumpy_until": 0, "born": 0, "at": 0}


def _clamp(n, top=100):
    return max(0, min(top, round(n)))


def _png_size(path):
    """(w, h) from a PNG header, or None. No decoder, no dependency."""
    try:
        with open(path, "rb") as fh:
            head = fh.read(24)
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        return struct.unpack(">II", head[16:24])
    except Exception:
        return None


def _cels(path, web):
    """[[file, index, total], ...] for one file.

    A width that is an exact multiple of the height is a horizontal
    strip of square cels -- how every pack in this project ships. Any
    other shape is one picture, which is also how a hand-drawn frame
    and a JPEG background both behave."""
    size = _png_size(path)
    if size and size[1] and size[0] % size[1] == 0 and size[0] // size[1] > 1:
        total = size[0] // size[1]
        return [[web, i, total] for i in range(total)]
    return [[web, 0, 1]]


def _state_of(stem):
    """('idle', 0) from any of the shapes a pack actually uses.

    A trailing `_<number>` is a frame index; whatever word ends the rest
    is the state. So `idle`, `idle_2`, `Demon_A_Idle` and
    `Blood Monster_A_Walk_3` all land where they should."""
    stem = stem.lower()
    head, _, tail = stem.rpartition("_")
    order = 0
    if head and tail.isdigit():
        order, stem = int(tail), head
    return stem.rpartition("_")[2] or stem, order


def frames(directory=None, prefix="vpet/"):
    """{state: [cel, ...]} for whatever art is in the folder.

    `prefix` is what the PAGE has to ask for, which is not the same as
    where the file sits on disk -- a character in a subfolder needs its
    folder in the URL. Building the web path here rather than bolting it
    on afterwards is what stops it being applied twice."""
    directory = directory or PET_DIR
    found = {}
    try:
        names = os.listdir(directory)
    except OSError:
        return {}
    for entry in sorted(names):
        stem, ext = os.path.splitext(entry)
        if ext.lower() not in EXTS or entry.startswith("."):
            continue
        if stem.lower() in NOT_A_STATE or stem.lower().startswith("icon_"):
            continue
        state, order = _state_of(stem)
        cels = _cels(os.path.join(directory, entry), prefix + entry)
        found.setdefault(state, []).append((order, cels))
    return {state: [cel for _, cels in sorted(shots) for cel in cels]
            for state, shots in sorted(found.items())}


def cast(directory=None):
    """{character: {state: [cel, ...]}} for the whole folder.

    A SUBFOLDER IS A CHARACTER. Loose files at the top level are read as
    one called `pet`, so the simplest possible thing -- drop five PNGs
    in ui/vpet/ -- still works and still shows up in the cycle."""
    directory = directory or PET_DIR
    out = {}
    try:
        entries = sorted(os.listdir(directory))
    except OSError:
        return {}
    loose = frames(directory)
    if loose:
        out["pet"] = loose
    for entry in entries:
        path = os.path.join(directory, entry)
        if not os.path.isdir(path) or entry.startswith("."):
            continue
        got = frames(path, "vpet/" + entry + "/")
        if got:
            out[entry.lower()] = got
    return out


def roles_for(found):
    out = {}
    for role, candidates in ROLES.items():
        for candidate in candidates:
            if found.get(candidate):
                out[role] = found[candidate]
                break
    return out


def background(directory=None):
    """The room, or None. A sprite floating on nothing looks unfinished
    -- Ghost's words, and he is right."""
    directory = directory or PET_DIR
    try:
        names = sorted(os.listdir(directory))
    except OSError:
        return None
    for entry in names:
        stem, ext = os.path.splitext(entry)
        if ext.lower() in EXTS and stem.lower() == "bg":
            return "vpet/" + entry
    return None


def _read():
    try:
        with open(STATE_FILE) as fh:
            got = json.load(fh)
        if not isinstance(got, dict):
            raise ValueError
    except Exception:
        got = {}
    pet = dict(FRESH)
    pet.update({k: v for k, v in got.items() if k in FRESH})
    if not pet["born"]:
        pet["born"] = time.time()
    return pet


def _write(pet):
    """NEVER raises. A pet that cannot be saved is a disappointment; a
    pet that takes the page down with it is a bug."""
    try:
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        with open(STATE_FILE, "w") as fh:
            json.dump(pet, fh)
    except Exception:
        pass


def _age(pet, now=None):
    """Apply the time since he was last looked at.

    THE WHOLE DESIGN IS IN ONE LINE: mood moves TOWARD NEUTRAL, from
    either side. Away for a week and he is neutral -- quieter, not sad,
    and certainly not starving. Bond is untouched, because time spent
    should never be taken back off him."""
    now = now or time.time()
    hours = max(0.0, (now - (pet.get("at") or now)) / 3600.0)
    if hours:
        drift = DRIFT_PER_HOUR * hours
        if pet["mood"] > NEUTRAL:
            pet["mood"] = _clamp(max(NEUTRAL, pet["mood"] - drift))
        else:
            pet["mood"] = _clamp(min(NEUTRAL, pet["mood"] + drift))
        # Poking resets after any real gap, so yesterday's prodding is
        # not held against him today.
        if hours > 0.05:
            pet["pokes"] = 0
        # He gets up on his own. Nothing here should need remembering
        # to undo.
        if pet.get("sleeping") and hours > 4:
            pet["sleeping"] = False
    pet["at"] = now
    return pet


def state_of(pet, now=None):
    """Which sprite to draw."""
    now = now or time.time()
    if pet.get("sleeping"):
        return "sleep"
    if now < pet.get("grumpy_until", 0):
        return "sad"
    if pet["mood"] >= 75:
        return "happy"
    return "idle"


def says(pet, now=None):
    """One line under him. Aloof at worst -- never an alarm."""
    now = now or time.time()
    if pet.get("sleeping"):
        return "Asleep. Leave him be."
    if now < pet.get("grumpy_until", 0):
        return "Fed up with being poked."
    if pet["mood"] >= 85:
        return "Delighted with himself."
    if pet["mood"] >= 70:
        return "In a good mood."
    if pet["mood"] <= NEUTRAL:
        return "Quiet. Keeping to himself."
    return "Pottering about."


def look(now=None):
    """Everything the page needs. Never raises."""
    now = now or time.time()
    pet = _age(_read(), now)
    everyone = cast()
    names = sorted(everyone)
    # A remembered character whose folder was deleted falls back to the
    # first one rather than to a blank screen -- the same call
    # yuzu_voice makes about a voice that is no longer installed.
    who = pet.get("who") if pet.get("who") in everyone else (
        names[0] if names else "")
    pet["who"] = who
    _write(pet)
    found = everyone.get(who, {})
    return {
        "mood": pet["mood"], "bond": pet["bond"],
        "sleeping": bool(pet["sleeping"]),
        "state": state_of(pet, now), "says": says(pet, now),
        "days": int((now - pet["born"]) / 86400),
        "who": who, "cast": names,
        "frames": roles_for(found),
        "states": sorted(found),
        "bg": background(),
    }


# What a tap can do, and nothing else. The same allowlist discipline as
# `/launch/`: a NAME crosses, never a command.
ACTIONS = ("poke", "play", "rest", "swap")


def do(action, now=None):
    """Apply one action, or None if it is not one of ours.

    NOTHING HERE IS A CHORE. Poke is free and always does something,
    play is the good one, rest is a toggle. There is no button that
    exists because he would suffer without it."""
    if action not in ACTIONS:
        return None
    now = now or time.time()
    pet = _age(_read(), now)
    if action == "poke":
        pet["sleeping"] = False
        pet["pokes"] = pet.get("pokes", 0) + 1
        if pet["pokes"] >= POKES_BEFORE_GRUMPY:
            # A reaction, not a penalty: it wears off by itself and
            # costs him nothing he has to win back.
            pet["grumpy_until"] = now + GRUMPY_FOR
            pet["pokes"] = 0
        else:
            pet["mood"] = _clamp(pet["mood"] + 3)
            pet["bond"] = _clamp(pet["bond"] + 1, 999)
    elif action == "play":
        pet["sleeping"] = False
        pet["grumpy_until"] = 0
        pet["pokes"] = 0
        pet["mood"] = _clamp(pet["mood"] + 18)
        pet["bond"] = _clamp(pet["bond"] + 3, 999)
    elif action == "rest":
        pet["sleeping"] = not pet["sleeping"]
    elif action == "swap":
        # CYCLE, rather than take a name from the request. Same reason
        # /launch/ takes a key and not a path: nothing a caller sends
        # should ever be able to name a folder on this board.
        names = sorted(cast())
        if names:
            here = names.index(pet["who"]) if pet["who"] in names else -1
            pet["who"] = names[(here + 1) % len(names)]
    _write(pet)
    out = look(now)
    out["did"] = action
    return out


if __name__ == "__main__":
    everyone = cast()
    found = everyone.get(look()["who"], {})
    if not found:
        print("\n  No sprites in ui/vpet/ yet.")
        print("  Drop PNGs in there -- the filename is the state.")
        print("  ui/vpet/SPRITES.txt is the shopping list.\n")
        raise SystemExit(1)
    now = look()
    print(f"\n  cast: {', '.join(sorted(everyone)) or 'nobody'}"
          f"   live: {now['who']}\n")
    for state, shots in found.items():
        print(f"    {state:<10} {len(shots)} frame(s)")
    print("\n  wired to:\n")
    for role in ROLES:
        got = now["frames"].get(role)
        print(f"    {role:<10} "
              f"{str(len(got)) + ' frame(s)' if got else '-- no art yet --'}")
    print(f"\n  background: {now['bg'] or 'MISSING -- add ui/vpet/bg.png'}")
    print(f"  right now:  {now['state']} -- {now['says']}")
    print(f"  mood {now['mood']}   bond {now['bond']}   day {now['days']}\n")
