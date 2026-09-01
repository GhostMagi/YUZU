"""
Yuzu's test suite. Plain stdlib unittest -- no pip installs, so it runs
in Pydroid on the phone exactly like it runs on the Jetson:

    python test_yuzu.py

Every test here is a real bug that was found by running the code, or a
behaviour worth locking down so a future edit can't quietly break it.
"""

import json
import unittest
from pathlib import Path

import muto_leg_control as legs
import yuzu_all_in_one as yuzu
from yuzu_led_manager import LEDManager


class TestActionMatching(unittest.TestCase):
    """The whitelist has to catch what the 3B model actually writes."""

    def assert_matches(self, phrase, expected_name):
        match = yuzu.lookup_action(phrase)
        self.assertIsNotNone(match, f"'{phrase}' matched nothing")
        self.assertIs(match[0], yuzu.ACTION_WHITELIST[expected_name][0],
                      f"'{phrase}' matched the wrong action")

    def test_plain_forms(self):
        for phrase, name in [
            ("squat", "squat"), ("stand", "stand"), ("spin", "spin"),
            ("stretch", "stretch"), ("shake legs", "shake legs"),
            ("walk forward", "walk forward"), ("look up", "look up"),
            ("center camera", "center camera"),
        ]:
            self.assert_matches(phrase, name)

    def test_third_person_s(self):
        for phrase, name in [
            ("squats", "squat"), ("stands", "stand"), ("spins", "spin"),
            ("shakes legs", "shake legs"), ("walks forward", "walk forward"),
            ("looks up", "look up"),
        ]:
            self.assert_matches(phrase, name)

    def test_es_ending_was_dropping_a_real_action(self):
        # REGRESSION: the old stemmer turned "stretches" into "stretche"
        # and matched nothing, so a whitelisted move the system prompt
        # explicitly teaches Yuzu to use did nothing on the robot.
        self.assert_matches("stretches", "stretch")

    def test_aliases_the_model_actually_emits(self):
        # "[spins around]" appears in the prompt's own Wrong: example,
        # so the model produces it; it used to be silently dropped.
        self.assert_matches("spins around", "spin")
        self.assert_matches("turns left", "turn")
        self.assert_matches("wiggles legs", "shake legs")
        self.assert_matches("crouches", "squat")

    def test_punctuation_and_articles_are_ignored(self):
        self.assert_matches("squats!", "squat")
        self.assert_matches("shakes her legs", "shake legs")
        self.assert_matches("centers the camera", "center camera")

    def test_impossible_actions_still_match_nothing(self):
        # The whole point of a whitelist: no fallback, no guessing.
        for phrase in ["winks", "waves hand", "smiles", "stretches her arms",
                       "leans against the wall", "flips hair"]:
            self.assertIsNone(yuzu.lookup_action(phrase),
                              f"'{phrase}' should NOT have matched anything")


class TestNormalizeActions(unittest.TestCase):
    def test_single_asterisks_become_brackets(self):
        self.assertEqual(yuzu.normalize_actions("*squats* yo"), "[squats] yo")

    def test_bold_no_longer_produces_empty_brackets(self):
        # REGRESSION: "**waves**" used to become "[]waves[]" -- two empty
        # actions, and the word "waves" leaking into the spoken line.
        self.assertEqual(yuzu.normalize_actions("**waves** hey!"), "[waves] hey!")

    def test_stray_asterisks_dont_eat_speech(self):
        # REGRESSION: "2 * 3 * 4" used to become "2 [ 3 ] 4", deleting
        # the middle of a sentence Yuzu was trying to say.
        self.assertEqual(yuzu.normalize_actions("it's 2 * 3 * 4 babe"),
                         "it's 2 * 3 * 4 babe")

    def test_brackets_are_left_alone(self):
        self.assertEqual(yuzu.normalize_actions("[squats] hi"), "[squats] hi")


class TestStripActions(unittest.TestCase):
    def test_removes_bracketed_actions(self):
        self.assertEqual(
            yuzu.strip_actions("Not much, just vibing! [squats] What's good?"),
            "Not much, just vibing! What's good?")

    def test_truncated_bracket_never_reaches_tts(self):
        # REGRESSION: a cut-off generation used to be spoken literally,
        # brackets included -- "Heyyy cutie, open bracket, squa".
        self.assertEqual(yuzu.strip_actions("Heyyy cutie! [squa"), "Heyyy cutie!")

    def test_actions_only_reply_yields_empty_speech(self):
        self.assertEqual(yuzu.strip_actions("[squats] [shakes legs]"), "")


class TestSplitReply(unittest.TestCase):
    def test_speech_and_action_keep_written_order(self):
        # The silent-beat fix: she used to run every action to completion
        # before saying a single word.
        parts = yuzu.split_reply(
            "Not much, just vibing! [squats] [shakes legs] What's good with you?")
        self.assertEqual(parts, [
            ("speech", "Not much, just vibing!"),
            ("action", "squats"),
            ("action", "shakes legs"),
            ("speech", "What's good with you?"),
        ])

    def test_empty_reply_is_silent_and_safe(self):
        self.assertEqual(yuzu.split_reply(""), [])

    def test_leading_action(self):
        self.assertEqual(yuzu.split_reply("[squats] hey"),
                         [("action", "squats"), ("speech", "hey")])


class TestLEDManager(unittest.TestCase):
    def test_reads_the_real_config_not_a_second_one(self):
        # REGRESSION: it used to default to "led_config.json" on a bare
        # relative path, creating a duplicate config next to whatever
        # directory you ran python from, and never reading the real one.
        led = LEDManager()
        self.assertEqual(led.config_path.name, "yuzu_robot_config.json")
        self.assertTrue(led.config_path.is_absolute())
        self.assertEqual(led.robot_name, "Yuzu-Spider-V1")

    def test_state_profiles_are_configured_not_fallback_white(self):
        led = LEDManager()
        for state in ("idle", "moving", "alert"):
            self.assertNotEqual(led.get_state_profile(state)["color"], "#FFFFFF",
                                f"state '{state}' fell through to the white fallback")

    def test_missing_section_is_filled_from_defaults(self):
        from yuzu_led_manager import _merge_defaults, DEFAULT_CONFIG
        partial = {"robot_name": "Yuzu-Spider-V1", "led_zones": {}}
        merged = _merge_defaults(partial, DEFAULT_CONFIG)
        self.assertIn("state_profiles", merged)
        self.assertEqual(merged["robot_name"], "Yuzu-Spider-V1")

    def test_unknown_state_falls_back_without_crashing(self):
        self.assertEqual(LEDManager().get_state_profile("nonsense")["color"], "#FFFFFF")

    def test_config_file_is_valid_json_with_both_sections(self):
        path = Path(__file__).parent / "yuzu_robot_config.json"
        data = json.loads(path.read_text())
        self.assertIn("led_zones", data)
        self.assertIn("state_profiles", data)


class TestGaits(unittest.TestCase):
    """Runs the whole gait library against DummyBot. Can't prove the
    robot balances -- only hardware can -- but it does prove no gait
    commands a servo outside its physical range or a leg that
    doesn't exist."""

    def run_all_gaits(self):
        # runtime=1 so the suite doesn't sit through real servo travel time
        bot = legs.DummyBot(verbose=False)
        legs.stance(bot, runtime=1)
        legs.walk_forward(bot, steps=1, runtime=1)
        legs.walk_backward(bot, steps=1, runtime=1)
        legs.turn(bot, steps=1, runtime=1)
        legs.spin(bot, steps=1, runtime=1)
        legs.squat(bot, runtime=1)
        legs.stand(bot, runtime=1)
        legs.shake_legs(bot, shakes=1, runtime=1)
        legs.stretch(bot, runtime=1)
        return bot

    def test_no_servo_command_leaves_the_valid_range(self):
        for servo_id, angle, runtime in self.run_all_gaits().calls:
            self.assertGreaterEqual(angle, -90, f"servo {servo_id} driven to {angle}")
            self.assertLessEqual(angle, 90, f"servo {servo_id} driven to {angle}")

    def test_only_real_servo_ids_are_addressed(self):
        for servo_id, _, _ in self.run_all_gaits().calls:
            self.assertIn(servo_id, range(1, 19))

    def test_tripods_are_valid_and_cover_every_leg(self):
        self.assertEqual(sorted(legs.TRIPOD_A + legs.TRIPOD_B), list(range(1, 7)))
        self.assertEqual(len(legs.TRIPOD_A), 3)
        # Each tripod needs exactly one middle leg (2 and 5) for stability.
        self.assertEqual(len(set(legs.TRIPOD_A) & {2, 5}), 1)
        self.assertEqual(len(set(legs.TRIPOD_B) & {2, 5}), 1)

    def test_bad_leg_id_raises(self):
        with self.assertRaises(ValueError):
            legs.set_leg(legs.DummyBot(verbose=False), 7, 0, 0, 0)

    def test_clamp_protects_the_servos(self):
        self.assertEqual(legs._clamp(150), 90)
        self.assertEqual(legs._clamp(-150), -90)

    def test_maps_cover_all_six_legs(self):
        for leg_id in range(1, 7):
            self.assertIn(leg_id, legs.LEG_SERVO_MAP)
            self.assertIn(leg_id, legs.LEG_OFFSETS)
            self.assertIn(leg_id, legs.LEG_SIGN)
        flat = [s for ids in legs.LEG_SERVO_MAP.values() for s in ids]
        self.assertEqual(sorted(flat), list(range(1, 19)), "servo IDs 1-18 must be unique")


class TestEndToEnd(unittest.TestCase):
    def setUp(self):
        self.spoken = []
        self._real_speak = yuzu.speak
        yuzu.speak = self.spoken.append
        yuzu.PAUSE_SCALE = 0.0          # no real waiting in tests

    def tearDown(self):
        yuzu.speak = self._real_speak
        yuzu.PAUSE_SCALE = 1.0

    def test_a_normal_reply(self):
        yuzu.handle_yuzu_reply(
            "Not much, just vibing! [squats] [shakes legs] What's good with you?")
        self.assertEqual(self.spoken,
                         ["Not much, just vibing!", "What's good with you?"])

    def test_impossible_action_is_dropped_but_speech_survives(self):
        yuzu.handle_yuzu_reply("Heyyy cutie! [winks] Missed you!")
        self.assertEqual(self.spoken, ["Heyyy cutie!", "Missed you!"])

    def test_empty_output_is_silent_and_doesnt_crash(self):
        yuzu.handle_yuzu_reply("")
        self.assertEqual(self.spoken, [])

    def test_actions_only_reply_says_nothing(self):
        # This is the case that looked like a freeze in testing and drove
        # the "always include one sentence of dialogue" prompt rule.
        yuzu.handle_yuzu_reply("[squats] [shakes legs]")
        self.assertEqual(self.spoken, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
