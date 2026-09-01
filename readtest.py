import json
from pathlib import Path

# Point to yuzu_robot_config.json relative to this script's own location,
# so this works wherever it's run from (Pydroid, Jetson, etc.) instead of
# a hardcoded path tied to one specific phone.
CONFIG_FILE = Path(__file__).parent / "yuzu_robot_config.json"

# Open the JSON file and read it like a book
with open(CONFIG_FILE, "r") as f:
    yuzu_data = json.load(f)

# Print out what it finds inside
print("--- TEST SUCCESSFUL ---")
print(
    "Robot Name:", yuzu_data["robot_name"]
)
print(
    "Underglow Color:",
    yuzu_data["led_zones"]["underglow"]["color"],
)
print("Effect Mode:", yuzu_data["led_zones"]["underglow"]["effect"])
