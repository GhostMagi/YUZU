"""
Muto S2 - Leg Control Wrapper + Gait Library
====================================================================
Wraps Yahboom's official bus servo API (g_bot.motor / Servo_torque_on
etc., from the "3. Control bus servo" course) so you can control a leg
by its 3 joint angles instead of tracking 18 raw servo IDs by hand,
and builds a first set of real gaits on top of that.

NOTHING HERE HAS TOUCHED REAL HARDWARE YET. The servo API calls match
Yahboom's documented signatures, but every angle constant below is an
educated guess and MUST be calibrated (see TUNING, further down).
Run it against DummyBot first - see the bottom of this file.

Requires an instantiated Yahboom Muto robot object. The exact import
depends on their library (check muto/Samples/Control/3.control_motor.ipynb
once you have the hardware) - something like:

    from muto_lib import Muto_Bot   # <- confirm real name later
    g_bot = Muto_Bot()

Servo ID map (from Yahboom docs, confirmed):
    leg1: servos 1, 2, 3      leg4: servos 10, 11, 12
    leg2: servos 4, 5, 6      leg5: servos 13, 14, 15
    leg3: servos 7, 8, 9      leg6: servos 16, 17, 18
(legs 1-3 = right wiring group, legs 4-6 = left wiring group)

Each leg's 3 servos, in ID order, are:
    coxa  -> hip joint (rotates leg left/right)
    femur -> upper leg joint (lifts leg up/down)
    tibia -> lower leg joint (extends/retracts foot)
"""

import time

LEG_SERVO_MAP = {
    1: (1, 2, 3),
    2: (4, 5, 6),
    3: (7, 8, 9),
    4: (10, 11, 12),
    5: (13, 14, 15),
    6: (16, 17, 18),
}

# Per-leg calibration offsets in degrees. Muto's raw servo range is
# -90 to 90, but "0" on each servo isn't necessarily the leg's neutral
# standing position - mechanical assembly varies slightly leg to leg.
# All zero for now. Fill these in with calibrate_leg() once the
# hardware arrives.
LEG_OFFSETS = {
    1: (0, 0, 0),
    2: (0, 0, 0),
    3: (0, 0, 0),
    4: (0, 0, 0),
    5: (0, 0, 0),
    6: (0, 0, 0),
}

# Left-side legs are physically mirrored, so a "+20 coxa" that swings
# leg 1 forward will swing leg 4 BACKWARD unless it's negated. Rather
# than write every gait twice, gaits are written for the right side and
# these signs mirror them onto the left.
#
# CALIBRATION STEP 2 (do this before trusting any gait): run
# check_mirroring() and watch the robot. All six legs should swing the
# same way at the same time. Any leg that goes the wrong way, flip that
# joint's sign here from 1 to -1.
LEG_SIGN = {
    1: (1, 1, 1),
    2: (1, 1, 1),
    3: (1, 1, 1),
    4: (-1, 1, 1),
    5: (-1, 1, 1),
    6: (-1, 1, 1),
}

# Tripod gait groups. A hexapod always keeps three feet down while the
# other three swing, and the two sets have to form stable tripods:
# front + back on one side, middle on the other.
#
# This assumes legs 2 and 5 are the MIDDLE legs (they are, on any
# 1-2-3-right / 4-5-6-left numbering, regardless of whether the left
# side is numbered front-to-back or back-to-front). Confirm visually
# with check_tripods() before walking on a table edge.
TRIPOD_A = (1, 3, 5)
TRIPOD_B = (2, 4, 6)

# ---------------------------------------------------------------------
# TUNING - every gait is built from these. Start small, work up.
# ---------------------------------------------------------------------
STANCE_FEMUR = 20      # femur angle when standing (body height)
STANCE_TIBIA = -30     # tibia angle when standing
LIFT_FEMUR = 45        # how high a leg lifts during its swing
STRIDE_COXA = 25       # how far a leg swings fore/aft per step
SQUAT_FEMUR = 55       # femur angle for a low squat
SQUAT_TIBIA = -60      # tibia angle for a low squat

STEP_MS = 180          # servo travel time per gait phase, milliseconds


def _clamp(angle):
    """Keep angle within the servo's valid -90 to 90 range."""
    return max(-90, min(90, angle))


def set_leg(g_bot, leg_id, coxa, femur, tibia, runtime=100):
    """
    Move one leg's three joints to the given angles.

    leg_id : 1-6
    coxa, femur, tibia : target angles in degrees (-90 to 90),
                          BEFORE the per-leg calibration offset and
                          left/right mirroring are applied
    runtime : servo move duration in ms (smaller = faster move)
    """
    if leg_id not in LEG_SERVO_MAP:
        raise ValueError(f"leg_id must be 1-6, got {leg_id}")

    coxa_id, femur_id, tibia_id = LEG_SERVO_MAP[leg_id]
    coxa_off, femur_off, tibia_off = LEG_OFFSETS[leg_id]
    coxa_sgn, femur_sgn, tibia_sgn = LEG_SIGN[leg_id]

    g_bot.motor(coxa_id, _clamp(coxa * coxa_sgn + coxa_off), runtime)
    g_bot.motor(femur_id, _clamp(femur * femur_sgn + femur_off), runtime)
    g_bot.motor(tibia_id, _clamp(tibia * tibia_sgn + tibia_off), runtime)


def set_legs(g_bot, leg_ids, coxa, femur, tibia, runtime=100):
    """Same as set_leg, but for several legs at once."""
    for leg_id in leg_ids:
        set_leg(g_bot, leg_id, coxa, femur, tibia, runtime)


def settle(runtime=100):
    """
    Block until a move that was given `runtime` ms has finished.

    This is the fix for the 'conflicting motor trajectories' risk:
    g_bot.motor() returns immediately and the servo keeps travelling in
    the background, so firing the next pose without waiting tells a leg
    to go somewhere new mid-move. Every gait phase below ends with this.
    """
    time.sleep(runtime / 1000.0)


def stand_neutral(g_bot, runtime=200):
    """Move all six legs to angle 0,0,0 (plus calibration offset)."""
    for leg_id in range(1, 7):
        set_leg(g_bot, leg_id, 0, 0, 0, runtime)
    settle(runtime)


def load_all(g_bot):
    """Turn on torque for all 18 servos."""
    g_bot.Servo_torque_on()


def unload_all(g_bot):
    """Turn off torque for all 18 servos (legs go limp, posable by hand)."""
    g_bot.Servo_torque_off()


def calibrate_leg(g_bot, leg_id):
    """
    Interactive helper: releases torque on one leg so you can pose it
    by hand to your desired neutral stance, then restores torque.
    Run once per leg after the hardware arrives, and hand-record the
    angle you posed it to into LEG_OFFSETS.

    Open question for when the hardware lands: Yahboom's bus servos can
    usually report their current angle back over the serial bus. If the
    library exposes a read (something like g_bot.read_angle(servo_id)),
    wire it in here so this prints the offsets instead of you reading
    them off by eye.
    """
    g_bot.unload_leg(leg_id)
    input(
        f"Leg {leg_id} torque is off - pose it to your desired neutral "
        f"stance by hand, then press Enter..."
    )
    g_bot.load_leg(leg_id)
    print(
        f"Leg {leg_id} torque restored. Note the pose angle and record "
        f"it in LEG_OFFSETS[{leg_id}]."
    )


# =====================================================================
# CALIBRATION CHECKS - run these before any gait, on the ground, with
# the body propped up so the feet are not carrying weight.
# =====================================================================

def check_mirroring(g_bot, runtime=400):
    """Swing every coxa forward, then back. All six legs should move the
    same direction together. Any that don't: flip that leg's coxa sign
    in LEG_SIGN."""
    print("All legs swinging FORWARD...")
    set_legs(g_bot, range(1, 7), STRIDE_COXA, STANCE_FEMUR, STANCE_TIBIA, runtime)
    settle(runtime)
    time.sleep(1.0)
    print("All legs swinging BACKWARD...")
    set_legs(g_bot, range(1, 7), -STRIDE_COXA, STANCE_FEMUR, STANCE_TIBIA, runtime)
    settle(runtime)
    time.sleep(1.0)
    stance(g_bot, runtime)


def check_tripods(g_bot, runtime=400):
    """Lift tripod A, put it down, lift tripod B. The body should stay
    level and stable on both. If it tips, the groups are wrong."""
    for name, group in (("A", TRIPOD_A), ("B", TRIPOD_B)):
        print(f"Lifting tripod {name}: legs {group}")
        set_legs(g_bot, group, 0, LIFT_FEMUR, STANCE_TIBIA, runtime)
        settle(runtime)
        time.sleep(1.0)
        set_legs(g_bot, group, 0, STANCE_FEMUR, STANCE_TIBIA, runtime)
        settle(runtime)
        time.sleep(0.5)


# =====================================================================
# GAITS - these map 1:1 onto the bracketed actions in Yuzu's prompt.
# =====================================================================

def stance(g_bot, runtime=STEP_MS):
    """Neutral standing pose, all six feet down, coxas centred."""
    set_legs(g_bot, range(1, 7), 0, STANCE_FEMUR, STANCE_TIBIA, runtime)
    settle(runtime)


def _tripod_cycle(g_bot, swing, stance_group, coxa_swing, runtime):
    """One half-cycle: `swing` legs lift, swing to +coxa_swing and set
    down, while `stance_group` legs stay down and sweep to -coxa_swing,
    pushing the body forward."""
    # 1. lift the swing group
    set_legs(g_bot, swing, -coxa_swing, LIFT_FEMUR, STANCE_TIBIA, runtime)
    settle(runtime)
    # 2. swing it forward through the air while the planted group pushes back
    set_legs(g_bot, swing, coxa_swing, LIFT_FEMUR, STANCE_TIBIA, runtime)
    set_legs(g_bot, stance_group, -coxa_swing, STANCE_FEMUR, STANCE_TIBIA, runtime)
    settle(runtime)
    # 3. plant the swing group
    set_legs(g_bot, swing, coxa_swing, STANCE_FEMUR, STANCE_TIBIA, runtime)
    settle(runtime)


def walk(g_bot, steps=2, direction=1, runtime=STEP_MS):
    """Tripod-gait walk. direction=1 forward, direction=-1 backward."""
    stride = STRIDE_COXA * direction
    stance(g_bot, runtime)
    for _ in range(steps):
        _tripod_cycle(g_bot, TRIPOD_A, TRIPOD_B, stride, runtime)
        _tripod_cycle(g_bot, TRIPOD_B, TRIPOD_A, stride, runtime)
    stance(g_bot, runtime)


def walk_forward(g_bot, steps=2, runtime=STEP_MS):
    walk(g_bot, steps, direction=1, runtime=runtime)


def walk_backward(g_bot, steps=2, runtime=STEP_MS):
    walk(g_bot, steps, direction=-1, runtime=runtime)


def turn(g_bot, steps=2, direction=1, runtime=STEP_MS):
    """
    Turn in place. direction=1 is one way, -1 is the other; which is
    which depends on your final mirroring, so name it after you watch it.

    Same tripod timing as walk(), except both sides swing their coxas
    the SAME rotational way instead of mirroring, which spins the body
    rather than translating it. That's why it bypasses set_legs' sign
    handling and pushes a raw sign per side.
    """
    stride = STRIDE_COXA * direction
    stance(g_bot, runtime)
    for _ in range(steps):
        for swing, planted in ((TRIPOD_A, TRIPOD_B), (TRIPOD_B, TRIPOD_A)):
            for leg in swing:
                side = 1 if leg <= 3 else -1
                set_leg(g_bot, leg, -stride * side, LIFT_FEMUR, STANCE_TIBIA, runtime)
            settle(runtime)
            for leg in swing:
                side = 1 if leg <= 3 else -1
                set_leg(g_bot, leg, stride * side, LIFT_FEMUR, STANCE_TIBIA, runtime)
            for leg in planted:
                side = 1 if leg <= 3 else -1
                set_leg(g_bot, leg, -stride * side, STANCE_FEMUR, STANCE_TIBIA, runtime)
            settle(runtime)
            for leg in swing:
                side = 1 if leg <= 3 else -1
                set_leg(g_bot, leg, stride * side, STANCE_FEMUR, STANCE_TIBIA, runtime)
            settle(runtime)
    stance(g_bot, runtime)


def spin(g_bot, steps=4, runtime=STEP_MS):
    """A longer turn - reads as a spin rather than a course correction."""
    turn(g_bot, steps=steps, direction=1, runtime=runtime)


def squat(g_bot, runtime=300):
    """Drop the body low, feet stay planted."""
    set_legs(g_bot, range(1, 7), 0, SQUAT_FEMUR, SQUAT_TIBIA, runtime)
    settle(runtime)


def stand(g_bot, runtime=300):
    """Back up to normal ride height from a squat."""
    stance(g_bot, runtime)


def shake_legs(g_bot, shakes=2, runtime=140):
    """Wiggle the two middle legs. Body stays up on the other four, so
    this is stable at any time - it's Yuzu's idle flourish."""
    for _ in range(shakes):
        set_legs(g_bot, (2, 5), STRIDE_COXA, LIFT_FEMUR, STANCE_TIBIA, runtime)
        settle(runtime)
        set_legs(g_bot, (2, 5), -STRIDE_COXA, LIFT_FEMUR, STANCE_TIBIA, runtime)
        settle(runtime)
    stance(g_bot, runtime)


def stretch(g_bot, runtime=500):
    """A slow full-body extend and settle. No arms, no back - this is
    the whole chassis pushing tall and easing down, which is the only
    'stretch' this body can honestly do."""
    hold = runtime / 1000.0             # pose holds scale with move speed
    set_legs(g_bot, range(1, 7), 0, -10, -5, runtime)   # push tall
    settle(runtime)
    time.sleep(hold)
    set_legs(g_bot, range(1, 7), 0, SQUAT_FEMUR, SQUAT_TIBIA, runtime)  # sink
    settle(runtime)
    time.sleep(hold)
    stance(g_bot, runtime)


# =====================================================================
# DummyBot - lets you write and watch gaits with no hardware attached.
# Same method names as the real Yahboom object, so the gaits above run
# unmodified against either one.
# =====================================================================

class DummyBot:
    """Stand-in for the real Muto bot. Prints (or silently records)
    every servo command so gait timing can be checked on a phone."""

    def __init__(self, verbose=True):
        self.verbose = verbose
        self.calls = []
        self.torque = False

    def motor(self, servo_id, angle, runtime=100):
        self.calls.append((servo_id, angle, runtime))
        if self.verbose:
            print(f"  servo {servo_id:>2} -> {angle:>4}deg over {runtime}ms")

    def Servo_torque_on(self):
        self.torque = True
        if self.verbose:
            print("  [torque ON, all servos]")

    def Servo_torque_off(self):
        self.torque = False
        if self.verbose:
            print("  [torque OFF, all servos]")

    def load_leg(self, leg):
        if self.verbose:
            print(f"  [torque ON, leg {leg}]")

    def unload_leg(self, leg):
        if self.verbose:
            print(f"  [torque OFF, leg {leg}]")


if __name__ == "__main__":
    # No hardware needed - this dry-runs the whole gait library.
    # Once the real Muto arrives:
    #     from muto_lib import Muto_Bot
    #     g_bot = Muto_Bot()
    #     load_all(g_bot); check_mirroring(g_bot); check_tripods(g_bot)
    bot = DummyBot(verbose=False)

    for name, fn in (
        ("stance",        lambda: stance(bot)),
        ("walk_forward",  lambda: walk_forward(bot, steps=1)),
        ("walk_backward", lambda: walk_backward(bot, steps=1)),
        ("turn",          lambda: turn(bot, steps=1)),
        ("squat",         lambda: squat(bot)),
        ("stand",         lambda: stand(bot)),
        ("shake_legs",    lambda: shake_legs(bot, shakes=1)),
        ("stretch",       lambda: stretch(bot)),
    ):
        before = len(bot.calls)
        started = time.time()
        fn()
        print(f"{name:<14} {len(bot.calls) - before:>3} servo commands, "
              f"{time.time() - started:.1f}s of motion")

    bad = [c for c in bot.calls if not -90 <= c[1] <= 90]
    print(f"\nout-of-range commands: {len(bad)}  (must be 0)")
