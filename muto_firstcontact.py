"""
First contact with the real Muto S2. Run this BEFORE any gait.

    python muto_firstcontact.py              # rehearse in simulation
    YUZU_HARDWARE=1 python muto_firstcontact.py   # the real thing

No arguments. It asks a yes/no question after every movement and stops
the moment you say no.

WHY THIS EXISTS
Every angle in muto_leg_control.py is an educated guess that has never
touched hardware. Against DummyBot a wrong sign is a wrong number in a
list. Against eighteen 35KG servos it is a leg driving itself into the
frame, or into another leg, at full torque, and holding there.

So this walks up in stages: comms, then one joint, then one leg, then
one tripod, then a stance, then a single walk cycle. The angle limit
starts at 15 degrees and is only raised once you've confirmed each
stage looks right. You cannot get to a walk cycle without having
watched every leg move on its own first.

BEFORE YOU RUN IT
  * Prop the body up so the feet hang free and carry no weight. A book
    under the chassis is fine. This is the single most important step:
    a wrong sign with the feet loaded is what breaks a servo horn.
  * Have the power switch or plug within reach.
  * Nothing fragile within a leg's reach.
"""

import os
import sys

import muto_leg_control as legs

BRINGUP_LIMIT = 15      # degrees; deliberately timid
STANCE_LIMIT = 40       # once individual legs are confirmed

# ms per move. 400 is slow enough to actually watch a joint travel,
# which is the entire point on real hardware. The override exists so
# the test suite can rehearse all six stages without sitting through
# 18 servos x 3 moves of real settle time.
PAUSE = int(os.environ.get("MUTO_PAUSE_MS", "400"))


def ask(question):
    """Yes/no. Anything but an explicit yes stops the run."""
    try:
        answer = input(f"    {question} [y/N] ").strip().lower()
    except (EOFError, KeyboardInterrupt):
        return False
    return answer in ("y", "yes")


class Aborted(Exception):
    pass


def confirm(question):
    if not ask(question):
        raise Aborted(question)


def stage(number, title):
    print(f"\n{'=' * 60}\nSTAGE {number}: {title}\n{'=' * 60}")


def check_one_joint(bot, leg_id, joint_index, joint_name):
    """Move a single joint off zero and back. Everything else stays put."""
    angles = [0, 0, 0]
    print(f"\n  Leg {leg_id}, {joint_name}: +{BRINGUP_LIMIT}deg, "
          f"then -{BRINGUP_LIMIT}deg, then back to neutral.")
    for value in (BRINGUP_LIMIT, -BRINGUP_LIMIT, 0):
        angles[joint_index] = value
        legs.set_leg(bot, leg_id, *angles, runtime=PAUSE)
        legs.settle(PAUSE)
    confirm(f"Did leg {leg_id}'s {joint_name} move, and ONLY that joint?")


def run(bot, mode):
    print(__doc__)
    print(f"MODE: {mode}\n")
    if "REAL" in mode:
        confirm("Is the body propped up with the feet hanging free?")
        confirm("Is the power within reach?")
    confirm("Ready to start?")

    # ---- Stage 1: can we talk to the bus at all -------------------
    stage(1, "Communication")
    legs.set_angle_limit(BRINGUP_LIMIT)
    legs.load_all(bot)
    print("  Torque on. Legs should feel stiff if you nudge one.")
    legs.set_leg(bot, 1, BRINGUP_LIMIT, 0, 0, runtime=PAUSE)
    legs.settle(PAUSE)
    legs.set_leg(bot, 1, 0, 0, 0, runtime=PAUSE)
    legs.settle(PAUSE)
    confirm("Did leg 1's hip twitch and return?")

    # ---- Stage 2: every joint, one at a time ----------------------
    stage(2, "Each joint alone  (18 servos, one at a time)")
    print("  Watching for: the RIGHT joint moving, and nothing else.")
    print("  A wrong joint here means the servo IDs are wired")
    print("  differently from LEG_SERVO_MAP.")
    for leg_id in range(1, 7):
        for index, name in enumerate(("coxa/hip", "femur/lift", "tibia/foot")):
            check_one_joint(bot, leg_id, index, name)

    # ---- Stage 3: mirroring --------------------------------------
    stage(3, "Mirroring  (this is what LEG_SIGN is for)")
    print("  All six hips swing the same way together, then back.")
    print("  Any leg that goes the OPPOSITE way to the others needs its")
    print("  coxa sign flipped in LEG_SIGN.\n")
    for value in (BRINGUP_LIMIT, -BRINGUP_LIMIT, 0):
        legs.set_legs(bot, range(1, 7), value, 0, 0, runtime=PAUSE)
        legs.settle(PAUSE)
    if not ask("Did ALL SIX hips swing the same direction together?"):
        print("\n  Note which legs went the wrong way, then edit LEG_SIGN in")
        print("  muto_leg_control.py -- flip the FIRST number of that leg's")
        print("  tuple between 1 and -1. Then run this script again.")
        raise Aborted("mirroring")

    # ---- Stage 4: standing ---------------------------------------
    stage(4, "Standing  (raising the angle limit)")
    legs.set_angle_limit(STANCE_LIMIT)
    print(f"  Angle limit {BRINGUP_LIMIT} -> {STANCE_LIMIT} degrees.")
    print("  Body should rise to an even, level stance.")
    legs.stance(bot, runtime=PAUSE * 2)
    confirm("Is the body level, with all six feet at the same height?")

    # ---- Stage 5: tripods ----------------------------------------
    stage(5, "Tripods  (put the feet on the ground first)")
    print("  Take the prop out. The robot should now carry its own weight.")
    confirm("Feet on the ground and body supporting itself?")
    for name, group in (("A", legs.TRIPOD_A), ("B", legs.TRIPOD_B)):
        print(f"\n  Lifting tripod {name}: legs {group}")
        legs.set_legs(bot, group, 0, legs.LIFT_FEMUR, legs.STANCE_TIBIA,
                      runtime=PAUSE)
        legs.settle(PAUSE)
        stable = ask("Did the body stay level on the other three legs?")
        legs.set_legs(bot, group, 0, legs.STANCE_FEMUR, legs.STANCE_TIBIA,
                      runtime=PAUSE)
        legs.settle(PAUSE)
        if not stable:
            print("\n  A tripod that tips means TRIPOD_A/TRIPOD_B are wrong")
            print("  for this leg numbering. Each group needs exactly one")
            print("  middle leg. Check which legs are physically middle.")
            raise Aborted(f"tripod {name}")

    # ---- Stage 6: one walk cycle ---------------------------------
    stage(6, "One walk cycle  (full range)")
    legs.set_angle_limit(90)
    print("  Full range now. ONE cycle, slowly. Be ready to cut power.")
    confirm("Floor clear, nothing to walk into?")
    legs.walk_forward(bot, steps=1, runtime=PAUSE)
    confirm("Did it move forward without a leg fighting the others?")

    print(f"\n{'=' * 60}\nBRING-UP COMPLETE\n{'=' * 60}")
    print("""
Everything checked out. What to do now:

  1. Record the neutral offsets you noticed into LEG_OFFSETS, and any
     sign flips into LEG_SIGN, in muto_leg_control.py.
  2. Tune STANCE_FEMUR / STANCE_TIBIA for the ride height you want,
     and STRIDE_COXA for step length.
  3. Then run the real thing:
         YUZU_HARDWARE=1 python yuzu_all_in_one.py
""")


def main():
    use_hardware = os.environ.get("YUZU_HARDWARE", "").lower() in (
        "1", "true", "yes", "real", "on")
    original_limit = legs.MAX_ANGLE
    bot = None
    try:
        bot, mode = legs.connect(use_hardware, verbose=not use_hardware)
        run(bot, mode)
        return 0
    except legs.HardwareError as exc:
        print(f"\n{exc}\n")
        return 1
    except Aborted as reason:
        print(f"\n\nSTOPPED at: {reason}")
        print("Nothing further will move. Fix that stage, then re-run.")
        return 1
    except KeyboardInterrupt:
        print("\n\nInterrupted.")
        return 1
    finally:
        # Park FIRST, at whatever limit the run had reached, and only
        # then restore the original.
        #
        # This used to restore the limit before parking, which meant an
        # abort at stage 2 -- the stage that exists to catch servo IDs
        # wired differently from LEG_SERVO_MAP -- lifted the clamp from
        # a timid 15 degrees back to a full 90 and then drove a 55-degree
        # squat into a chassis that had just proven it moves the wrong
        # joints. The one path where the limit matters most is the one
        # where it was being dropped.
        #
        # Parking at the current limit is safe at both ends: after an
        # early abort the legs are near neutral and the clamped squat is
        # a small move before torque comes off, and after stage 6 the
        # limit is already 90 so rest() does its full squat as intended.
        if bot is not None:
            print("Parking legs...")
            legs.rest(bot)
        legs.set_angle_limit(original_limit)


if __name__ == "__main__":
    sys.exit(main())
