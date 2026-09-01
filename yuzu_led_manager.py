"""
Yuzu's LED manager -- the single source of truth for lighting.

It merges two previously-separate, incompatible systems:

  1. yuzu_robot_config.json's PHYSICAL ZONES (underglow, leg_accents)
     -- "where are the LEDs and what's their base color"
  2. ledsnewestv7.py's STATE PROFILES (idle, moving, alert, ...) --
     "what should the lights do based on what the robot is doing"

Both now use the SAME color format (hex strings, matching what the
JSON config already used) and the SAME brightness scale (0-100).
Previously ledsnewestv7.py used [R,G,B] lists and a 0-1 brightness
scale, which couldn't be compared to the JSON file's hex/0-100 format
at all -- that mismatch is the actual "kink" this file fixed.

Two later kinks, also fixed here:
  * It used to default to a config file called "led_config.json" via a
    bare relative path. That meant it wrote a SECOND config next to
    wherever you happened to run python from, and never once read
    yuzu_robot_config.json -- so edits to the real config did nothing
    and the two files silently drifted apart. Now it reads the real
    config, found relative to this script's own folder.
  * A config missing a section (the real one had no "state_profiles")
    used to make every lookup fall through to plain white. Now missing
    sections and missing keys are filled in from DEFAULT_CONFIG, so a
    partial config degrades gracefully instead of going colorless.
"""

import json
from pathlib import Path

CONFIG_FILE = Path(__file__).parent / "yuzu_robot_config.json"

DEFAULT_CONFIG = {
    "robot_name": "Yuzu-Spider-V1",
    "led_zones": {
        "underglow":   {"color": "#FF1493", "effect": "neon_pulse", "brightness": 90},
        "leg_accents": {"color": "#FF007F", "effect": "chase",      "brightness": 75},
    },
    "state_profiles": {
        "idle":     {"color": "#FF69B4", "effect": "breathing",  "brightness": 50},
        "moving":   {"color": "#39FF14", "effect": "solid",      "brightness": 80},
        "alert":    {"color": "#FF0000", "effect": "strobe",     "brightness": 100},
        "thinking": {"color": "#B026FF", "effect": "chase",      "brightness": 65},
        "speaking": {"color": "#FF1493", "effect": "neon_pulse", "brightness": 85},
    },
}

FALLBACK_PROFILE = {"color": "#FFFFFF", "effect": "solid", "brightness": 50}


def _merge_defaults(loaded, defaults):
    """Fill in anything the loaded config is missing, without clobbering
    what it does have. Two levels deep is all this config format needs."""
    merged = dict(defaults)
    for key, value in loaded.items():
        if isinstance(value, dict) and isinstance(defaults.get(key), dict):
            merged[key] = _merge_defaults(value, defaults[key])
        else:
            merged[key] = value
    return merged


class LEDManager:
    def __init__(self, config_path=CONFIG_FILE, hardware=None):
        """
        config_path : defaults to yuzu_robot_config.json beside this file
        hardware    : optional object with .set(zone, color, effect,
                      brightness). Left as None, everything just prints,
                      exactly like before -- so this stays runnable on a
                      phone with no LEDs attached.
        """
        self.config_path = Path(config_path)
        self.hardware = hardware
        self.data = self._load()
        self.current_state = None

    def _load(self):
        if not self.config_path.exists():
            self._save(DEFAULT_CONFIG)
            return dict(DEFAULT_CONFIG)
        with open(self.config_path, "r") as f:
            return _merge_defaults(json.load(f), DEFAULT_CONFIG)

    def _save(self, data):
        with open(self.config_path, "w") as f:
            json.dump(data, f, indent=4)

    @property
    def robot_name(self):
        return self.data.get("robot_name", "unnamed robot")

    def zone_names(self):
        return list(self.data.get("led_zones", {}))

    def state_names(self):
        return list(self.data.get("state_profiles", {}))

    def get_zone(self, zone_name):
        """Static, location-based color -- underglow / leg_accents."""
        return self.data.get("led_zones", {}).get(zone_name)

    def get_state_profile(self, state_name):
        """Behavior-based lighting -- idle / moving / alert / ..."""
        return self.data.get("state_profiles", {}).get(state_name, dict(FALLBACK_PROFILE))

    def _push(self, zone_name, profile):
        """One place where light actually reaches hardware. Swap in a
        real driver by passing `hardware=` to the constructor; with none,
        this prints, which is what every earlier version did."""
        if self.hardware is not None:
            self.hardware.set(
                zone_name,
                profile.get("color"),
                profile.get("effect"),
                profile.get("brightness"),
            )
        else:
            print(
                f"[LED] {zone_name:<12} {profile.get('color')}  "
                f"{profile.get('effect')}  {profile.get('brightness')}%"
            )

    def apply_zone(self, zone_name):
        """Light one zone with its own configured base color."""
        zone = self.get_zone(zone_name)
        if zone is None:
            print(f"[LED] no config found for zone '{zone_name}'")
            return
        self._push(zone_name, zone)

    def apply_all_zones(self):
        """Light every zone with its base color -- the boot/reset look."""
        for zone_name in self.zone_names():
            self.apply_zone(zone_name)

    def apply_state(self, state_name):
        """Push a behavior state across every zone. This is what the
        reply pipeline calls: idle while waiting, thinking while the LLM
        generates, moving while a gait runs, speaking during TTS."""
        if state_name == self.current_state:
            return                      # don't re-push a state we're already in
        profile = self.get_state_profile(state_name)
        self.current_state = state_name
        if self.hardware is None:
            # One line per state change, not one per zone -- otherwise the
            # console noise buries Yuzu's actual dialogue during testing.
            print(
                f"[LED] state={state_name:<9} {profile.get('color')}  "
                f"{profile.get('effect')}  {profile.get('brightness')}%"
            )
            return
        for zone_name in self.zone_names():
            self._push(zone_name, profile)


if __name__ == "__main__":
    led = LEDManager()
    print(f"Config: {led.config_path.name}   Robot: {led.robot_name}\n")

    print("--- Base zone colors (the JSON config side) ---")
    led.apply_all_zones()

    print("\n--- Behavior states (the old ledsnewestv7 side) ---")
    for state in led.state_names():
        print(f"state '{state}':")
        led.current_state = None        # force a re-push so the demo shows each
        led.apply_state(state)
