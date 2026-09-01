import json
from pathlib import Path

# This locks the search path to the exact folder this script lives in
CONFIG_FILE = Path(__file__).parent / "yuzu_robot_config.json"


def load_yuzu_config():
  path = Path(CONFIG_FILE)
  if not path.exists():
    print(f"Error: Could not find {path.name}! Make sure it's in the folder.")
    return None

  with open(path, "r") as f:
    return json.load(f)


def apply_led_settings(config):
  if not config:
    return

  print(f"Initializing LEDs for: {config['robot_name']}\n")
  zones = config.get("led_zones", {})

  for zone_name, settings in zones.items():
    color = settings.get("color")
    effect = settings.get("effect")
    brightness = settings.get("brightness")

    print(f"[LED CONTROLLER] Zone: {zone_name.upper()}")
    print(f"  -> Hex Color: {color}")
    print(f"  -> Effect Pattern: {effect}")
    print(f"  -> Brightness: {brightness}%\n")


if __name__ == "__main__":
  yuzu_config = load_yuzu_config()
  if yuzu_config:
    apply_led_settings(yuzu_config)
