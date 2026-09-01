"""
Muto S2 - Leg Control Wrapper (reference / not yet hardware-tested)
====================================================================
Wraps Yahboom's official bus servo API (g_bot.motor / Servo_torque_on
etc., from the "3. Control bus servo" course) so you can control a leg
by its 3 joint angles instead of tracking 18 raw servo IDs by hand.

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


def set_leg(g_bot, leg_id, coxa, femur, tibia, runtime=100):
    """
    Move one leg's three joints to the given angles.

    leg_id : 1-6
    coxa, femur, tibia : target angles in degrees (-90 to 90),
                          BEFORE the per-leg calibration offset is applied
    runtime : servo move duration in ms (smaller = faster move)
    """
    if leg_id not in LEG_SERVO_MAP:
        raise ValueError(f"leg_id must be 1-6, got {leg_id}")

    coxa_id, femur_id, tibia_id = LEG_SERVO_MAP[leg_id]
    coxa_off, femur_off, tibia_off = LEG_OFFSETS[leg_id]

    g_bot.motor(coxa_id, _clamp(coxa + coxa_off), runtime)
    g_bot.motor(femur_id, _clamp(femur + femur_off), runtime)
    g_bot.motor(tibia_id, _clamp(tibia + tibia_off), runtime)


def stand_neutral(g_bot, runtime=200):
    """Move all six legs to angle 0,0,0 (plus calibration offset)."""
    for leg_id in range(1, 7):
        set_leg(g_bot, leg_id, 0, 0, 0, runtime)


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


def _clamp(angle):
    """Keep angle within the servo's valid -90 to 90 range."""
    return max(-90, min(90, angle))


if __name__ == "__main__":
    # Example usage once g_bot exists and offsets are calibrated:
    # from muto_lib import Muto_Bot
    # g_bot = Muto_Bot()
    # load_all(g_bot)
    # stand_neutral(g_bot)
    pass
