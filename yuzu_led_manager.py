"""
Yuzu's LED manager -- combines two previously-separate, incompatible
systems into one:

  1. yuzu_robot_config.json's PHYSICAL ZONES (underglow, eye_matrix,
     leg_accents) -- "where are the LEDs and what's their base color"
  2. ledsnewestv7.py's STATE PROFILES (idle, moving, alert) -- "what
     should the lights do based on what the robot is currently doing"

Both now use the SAME color format (hex strings, matching what the
JSON config already used) and the SAME brightness scale (0-100).
Previously ledsnewestv7.py used [R,G,B] lists and a 0-1 brightness
scale, which couldn't be compared to the JSON file's hex/0-100 format
at all -- that mismatch is the actual "kink" worth fixing here.
"""

import json
from pathlib import Path

DEFAULT_CONFIG = {
    "robot_name": "Yuzu-Spider-V1",
    "led_zones": {
        "underglow":   {"color": "#FF1493", "effect": "neon_pulse", "brightness": 90},
        "eye_matrix":  {"color": "#00FFFF", "effect": "static",     "brightness": 100},
        "leg_accents": {"color": "#FF007F", "effect": "chase",      "brightness": 75},
    },
    "state_profiles": {
        "idle":   {"color": "#00FF00", "brightness": 50,  "effect": "breathing"},
        "moving": {"color": "#FFA500", "brightness": 80,  "effect": "solid"},
        "alert":  {"color": "#FF0000", "brightness": 100, "effect": "strobe"},
    },
}


class LEDManager:
    def __init__(self, config_path="led_config.json"):
        self.config_path = Path(config_path)
        self.data = self._load()

    def _load(self):
        if not self.config_path.exists():
            self._save(DEFAULT_CONFIG)
            return DEFAULT_CONFIG
        with open(self.config_path, "r") as f:
            return json.load(f)

    def _save(self, data):
        with open(self.config_path, "w") as f:
            json.dump(data, f, indent=4)

    def get_zone(self, zone_name):
        """Static, location-based color -- underglow / eye_matrix / leg_accents."""
        return self.data.get("led_zones", {}).get(zone_name)

    def get_state_profile(self, state_name):
        """Behavior-based lighting -- idle / moving / alert."""
        return self.data.get("state_profiles", {}).get(
            state_name, {"color": "#FFFFFF", "brightness": 50, "effect": "solid"}
        )

    def apply_zone(self, zone_name):
        """Placeholder -- swap the print for a real LED hardware call later."""
        zone = self.get_zone(zone_name)
        if zone:
            print(f"LED: zone '{zone_name}' -> {zone}")
        else:
            print(f"LED: no config found for zone '{zone_name}'")

    def apply_state(self, state_name):
        """Placeholder -- swap the print for a real LED hardware call later."""
        profile = self.get_state_profile(state_name)
        print(f"LED: robot state '{state_name}' -> {profile}")


if __name__ == "__main__":
    led = LEDManager()
    print("--- Loaded zones (from the JSON config side) ---")
    led.apply_zone("underglow")
    led.apply_zone("eye_matrix")
    led.apply_zone("leg_accents")
    print()
    print("--- Loaded state profiles (from the old ledsnewestv7 side) ---")
    led.apply_state("idle")
    led.apply_state("moving")
    led.apply_state("alert")
