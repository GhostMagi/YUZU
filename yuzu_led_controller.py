"""
Zone dump -- prints every LED zone from yuzu_robot_config.json.

This used to parse the config itself, which meant two files (this one
and yuzu_led_manager.py) each had their own copy of "how to find and
read the config". They'd already drifted: the manager was reading a
different filename entirely. Now this is a thin front-end over
LEDManager, so there is exactly one loader and one config path.

Still runs standalone the same way it always did:  python yuzu_led_controller.py
"""

from yuzu_led_manager import LEDManager


def load_yuzu_config():
    """Kept for anything that already imports it -- returns the merged
    config dict, or None if the file is missing."""
    led = LEDManager()
    return led.data if led.config_path.exists() else None


def apply_led_settings(led=None):
    led = led or LEDManager()
    print(f"Initializing LEDs for: {led.robot_name}\n")
    for zone_name in led.zone_names():
        settings = led.get_zone(zone_name)
        print(f"[LED CONTROLLER] Zone: {zone_name.upper()}")
        print(f"  -> Hex Color: {settings.get('color')}")
        print(f"  -> Effect Pattern: {settings.get('effect')}")
        print(f"  -> Brightness: {settings.get('brightness')}%\n")


if __name__ == "__main__":
    apply_led_settings()
