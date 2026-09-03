"""
Yuzu's test suite. Plain stdlib unittest -- no pip installs, so it runs
in Pydroid on the phone exactly like it runs on the Jetson:

    python YUZU_TESTER.py

Every test here is a real bug that was found by running the code, or a
behaviour worth locking down so a future edit can't quietly break it.
"""

import json
import unittest
import unittest.mock
from pathlib import Path

import itertools
import re
import shutil
import struct
import sys
import tempfile
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, HTTPServer

import muto_leg_control as legs
import yuzu_all_in_one as yuzu
import gguf_inspect
import yuzu_brain
import yuzu_personas
import yuzu_prompt_eval as prompt_eval
import yuzu_brain as yuzu_brain_module
from yuzu_brain import BrainError, YuzuBrain, load_system_prompt
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

    def test_no_alias_is_shadowed_by_the_whitelist(self):
        """Every ACTION_ALIASES entry must actually be able to fire.

        Found live: "turn around": "spin" never once ran. _stem_phrase
        drops "around" as a filler word, so the phrase arrives at
        lookup_action as "turn", and lookup_action checks the whitelist
        FIRST -- it answered with turn() and the alias was never
        consulted. The table said one thing and the robot did another,
        with nothing anywhere to say so.

        This is a whole class of bug, not one entry: any alias whose
        stem collapses onto a whitelist key is dead on arrival.
        """
        for alias, target in yuzu.ACTION_ALIASES.items():
            stem = yuzu._stem_phrase(alias)
            shadow = yuzu._STEMMED_WHITELIST.get(stem)
            if shadow is None:
                continue
            self.assertIs(
                shadow, yuzu._STEMMED_WHITELIST[yuzu._stem_phrase(target)],
                f"alias '{alias}' -> '{target}' can never fire: after "
                f"stemming it reads '{stem}', which the whitelist answers "
                f"first with a different action. Either drop the alias or "
                f"stop stemming that word away.")

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

    def _coxa_sequence(self, fn, **kw):
        """Ordered raw coxa commands per leg, preserving phase."""
        bot = legs.DummyBot(verbose=False)
        fn(bot, runtime=1, **kw)
        coxa_of = {ids[0]: leg for leg, ids in legs.LEG_SERVO_MAP.items()}
        seq = {}
        for servo_id, angle, _ in bot.calls:
            if servo_id in coxa_of:
                seq.setdefault(coxa_of[servo_id], []).append(angle)
        return seq

    def test_turn_survives_calibration(self):
        """REGRESSION: turn() hardcoded `side = 1 if leg <= 3 else -1`,
        a second copy of what LEG_SIGN already knows. check_mirroring()
        tells you to flip LEG_SIGN entries during calibration, and doing
        so made that leg turn against the rest of its tripod while
        walk() kept working -- silent, partial, and caused by following
        the documented procedure."""
        original = dict(legs.LEG_SIGN)
        try:
            for flipped in (None, 5, 2, 4, 1):
                if flipped:
                    old_sign = legs.LEG_SIGN[flipped]
                    legs.LEG_SIGN[flipped] = (-old_sign[0],) + old_sign[1:]
                seq = self._coxa_sequence(legs.turn, steps=1)
                # A turn rotates the body only if every leg in a tripod
                # hits the same RAW angle at the same instant.
                for group in (legs.TRIPOD_A, legs.TRIPOD_B):
                    for leg in group[1:]:
                        self.assertEqual(
                            seq[leg], seq[group[0]],
                            f"leg {leg} turns against its tripod after "
                            f"flipping LEG_SIGN[{flipped}]")
        finally:
            legs.LEG_SIGN.clear()
            legs.LEG_SIGN.update(original)

    def test_walk_mirrors_across_sides(self):
        """The counterpart to the above: walk() must KEEP the mirroring,
        so legs on opposite sides get opposite raw angles and the body
        translates instead of spinning."""
        seq = self._coxa_sequence(legs.walk_forward, steps=1)
        self.assertEqual(seq[3], [-angle for angle in seq[5]],
                         "walk must mirror across sides, unlike turn")

    def test_turn_and_walk_are_not_the_same_motion(self):
        turning = self._coxa_sequence(legs.turn, steps=1)
        walking = self._coxa_sequence(legs.walk_forward, steps=1)
        self.assertNotEqual(turning[5], walking[5],
                            "if these match, one of them is wrong")

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


class TestHardwareBoundary(unittest.TestCase):
    """Simulation must never be a silent fallback. A loose cable looking
    identical to working code is the worst failure mode available."""

    def test_simulation_is_the_explicit_default(self):
        bot, mode = legs.connect(False)
        self.assertIsInstance(bot, legs.DummyBot)
        self.assertIn("SIMULATION", mode)

    def test_asking_for_hardware_without_it_raises(self):
        with self.assertRaises(legs.HardwareError) as ctx:
            legs.connect(True)
        message = str(ctx.exception)
        self.assertIn("NOT falling back", message)
        self.assertIn("YUZU_HARDWARE", message)

    def test_hardware_failure_does_not_return_a_dummy(self):
        try:
            bot, _ = legs.connect(True)
        except legs.HardwareError:
            return                      # correct
        self.fail(f"connect(True) quietly returned {bot!r}")


class TestAngleLimit(unittest.TestCase):
    def setUp(self):
        self.original = legs.MAX_ANGLE

    def tearDown(self):
        legs.set_angle_limit(self.original)

    def test_limit_clamps_every_command(self):
        legs.set_angle_limit(15)
        bot = legs.DummyBot(verbose=False)
        legs.set_leg(bot, 1, 90, -90, 45, runtime=1)
        for _, angle, _ in bot.calls:
            self.assertLessEqual(abs(angle), 15)

    def test_limit_cannot_exceed_servo_range(self):
        legs.set_angle_limit(500)
        self.assertEqual(legs.MAX_ANGLE, 90)

    def test_set_angle_limit_returns_previous(self):
        legs.set_angle_limit(90)
        self.assertEqual(legs.set_angle_limit(20), 90)

    def test_a_whole_gait_respects_the_limit(self):
        legs.set_angle_limit(20)
        bot = legs.DummyBot(verbose=False)
        legs.walk_forward(bot, steps=1, runtime=1)
        legs.turn(bot, steps=1, runtime=1)
        for _, angle, _ in bot.calls:
            self.assertLessEqual(abs(angle), 20)


class TestSafeShutdown(unittest.TestCase):
    """18x 35KG servos hold their last commanded angle while powered.
    Exiting mid-gait leaves them straining against a half-finished pose
    indefinitely, and nothing in the code notices."""

    def test_rest_squats_before_releasing_torque(self):
        # Order matters: releasing torque while standing drops the
        # chassis from full ride height.
        bot = legs.DummyBot(verbose=False)
        legs.stance(bot, runtime=1)
        before = len(bot.calls)
        legs.rest(bot, runtime=1)
        femur_ids = {ids[1] for ids in legs.LEG_SERVO_MAP.values()}
        femurs = [a for sid, a, _ in bot.calls[before:] if sid in femur_ids]
        self.assertTrue(femurs, "rest() must command the femurs")
        self.assertEqual(femurs[-1], legs.SQUAT_FEMUR * 1)
        self.assertFalse(bot.torque, "torque must end up released")

    def test_rest_survives_a_completely_dead_bus(self):
        class DeadBot(legs.DummyBot):
            def motor(self, *a, **k):
                raise OSError("bus down")

            def Servo_torque_off(self):
                raise OSError("bus down")

        legs.rest(DeadBot(verbose=False))       # must not raise

    def test_shutdown_is_idempotent(self):
        yuzu.shutdown()
        yuzu.shutdown()


class TestMotorFaultTolerance(unittest.TestCase):
    """A servo bus hiccup must not end the conversation."""

    def setUp(self):
        self.real_bot = yuzu.g_bot
        yuzu.motor_faults.clear()
        self.spoken = []
        self.real_speak, yuzu.speak = yuzu.speak, self.spoken.append
        yuzu.PAUSE_SCALE = 0.0

    def tearDown(self):
        yuzu.g_bot = self.real_bot
        yuzu.speak, yuzu.PAUSE_SCALE = self.real_speak, 1.0
        yuzu.motor_faults.clear()

    def test_a_dead_leg_does_not_stop_her_talking(self):
        class BrokenBot(legs.DummyBot):
            def motor(self, servo_id, angle, runtime=100):
                if servo_id in (13, 14, 15):        # leg 5 unplugged
                    raise OSError("serial timeout")
                super().motor(servo_id, angle, runtime)

        yuzu.g_bot = BrokenBot(verbose=False)
        yuzu.handle_yuzu_reply("Say less! [spins] Tell me that wasn't iconic.")
        self.assertEqual(self.spoken, ["Say less!", "Tell me that wasn't iconic."])
        self.assertEqual(len(yuzu.motor_faults), 1)
        self.assertEqual(yuzu.motor_faults[0][0], "spin")


class TestFirstContact(unittest.TestCase):
    """The bring-up script is the only thing standing between an
    uncalibrated chassis and eighteen 35KG servos at full range."""

    def run_script(self, answers, timeout=60):
        import os
        import subprocess
        env = dict(os.environ, MUTO_PAUSE_MS="1")   # skip real servo timing
        return subprocess.run(
            [sys.executable, str(Path(__file__).parent / "muto_firstcontact.py")],
            input=answers, capture_output=True, text=True,
            timeout=timeout, env=env)

    def test_saying_no_at_the_start_moves_nothing_further(self):
        result = self.run_script("n\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("STOPPED", result.stdout)
        self.assertNotIn("STAGE 2", result.stdout)

    def commanded_angles(self, stdout):
        """Every angle DummyBot was actually told to go to. It prints
        one line per servo command in simulation, so the whole run can
        be checked from the outside."""
        return [int(a) for a in
                re.findall(r'servo\s+\d+ -> \s*(-?\d+)deg', stdout)]

    def test_an_early_abort_parks_inside_the_limit_it_was_running_at(self):
        """The angle limit has to still apply on the way out.

        Measured: aborting at stage 2 -- the stage whose whole job is to
        catch servo IDs wired differently from LEG_SERVO_MAP -- used to
        command 60 degrees. The cleanup restored the limit from a timid
        15 back to 90 and THEN called rest(), so it drove a full squat
        into a chassis that had just proven it moves the wrong joints.
        The one exit path where the clamp matters most was the one that
        dropped it. Park first, restore after.
        """
        result = self.run_script("y\ny\nn\n")
        self.assertIn("STOPPED at:", result.stdout)
        angles = self.commanded_angles(result.stdout)
        self.assertTrue(angles, "no servo commands seen at all")
        self.assertLessEqual(
            max(abs(a) for a in angles), 15,
            "parking exceeded the 15-degree bring-up limit that was in "
            "force when the run aborted")

    def test_the_limit_is_left_where_it_was_found(self):
        # The script lowers a module global. Leaving it lowered would
        # silently clamp every gait in the next process that imports
        # muto_leg_control in the same session.
        before = legs.MAX_ANGLE
        import muto_firstcontact
        muto_firstcontact.legs.set_angle_limit(15)
        muto_firstcontact.legs.set_angle_limit(before)
        self.assertEqual(legs.MAX_ANGLE, before)

    def test_a_failed_mirroring_check_names_the_fix(self):
        # 21st question is the mirroring one in simulation mode.
        result = self.run_script("y\n" * 20 + "n\n" + "y\n" * 10)
        self.assertIn("STOPPED at: mirroring", result.stdout)
        self.assertIn("LEG_SIGN", result.stdout)
        self.assertNotIn("STAGE 4", result.stdout,
                         "must not reach standing after a mirroring failure")

    def test_a_clean_run_completes_and_parks(self):
        result = self.run_script("y\n" * 40)
        self.assertIn("BRING-UP COMPLETE", result.stdout)
        self.assertIn("Parking legs", result.stdout)
        self.assertEqual(result.returncode, 0)

    def test_it_starts_at_a_timid_angle_limit(self):
        import muto_firstcontact
        self.assertLessEqual(muto_firstcontact.BRINGUP_LIMIT, 20)
        self.assertLess(muto_firstcontact.BRINGUP_LIMIT,
                        muto_firstcontact.STANCE_LIMIT)

    def test_it_restores_the_angle_limit_afterwards(self):
        before = legs.MAX_ANGLE
        self.run_script("n\n")
        self.assertEqual(legs.MAX_ANGLE, before)


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


# =====================================================================
# A stand-in Ollama, so the brain is tested against the real wire format
# without needing a 2GB model pulled. Ollama's /api/chat returns one
# JSON object when stream=false, and newline-delimited JSON when true.
# =====================================================================

class MockOllama(BaseHTTPRequestHandler):
    replies = itertools.cycle(["Not much, just vibing! [squats] What's good?"])
    seen = {}

    def log_message(self, *args):
        pass

    def _send(self, body, content_type="application/json"):
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/api/tags":
            self._send(json.dumps({"models": [{"name": "yuzu:latest"}]}).encode())
        else:
            self.send_error(404)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        request = json.loads(self.rfile.read(length))
        MockOllama.seen["last"] = request
        reply = next(MockOllama.replies)
        if request.get("stream"):
            self.send_response(200)
            self.send_header("Content-Type", "application/x-ndjson")
            self.end_headers()
            for word in reply.split(" "):
                self.wfile.write(
                    (json.dumps({"message": {"content": word + " "},
                                 "done": False}) + "\n").encode())
            self.wfile.write(
                (json.dumps({"message": {"content": ""}, "done": True}) + "\n").encode())
        else:
            self._send(json.dumps({"message": {"content": reply}, "done": True}).encode())


class BrainTestCase(unittest.TestCase):
    """Shared mock server for every brain test."""

    @classmethod
    def setUpClass(cls):
        HTTPServer.allow_reuse_address = True
        cls.server = HTTPServer(("127.0.0.1", 0), MockOllama)
        cls.host = f"http://127.0.0.1:{cls.server.server_address[1]}"
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def setUp(self):
        MockOllama.replies = itertools.cycle(
            ["Not much, just vibing! [squats] What's good?"])

    def brain(self, **kwargs):
        kwargs.setdefault("model", "yuzu")
        kwargs.setdefault("host", self.host)
        return YuzuBrain(**kwargs)


class TestBrain(BrainTestCase):
    def test_system_prompt_composes_with_the_directives(self):
        # Named explicitly. This used to call load_system_prompt() bare
        # and assert v1's headings, which quietly made "the default
        # persona" and "the frozen archive" the same test -- so the day
        # the default moved to the measured winner, a passing test would
        # have been the only thing arguing for keeping the 20% prompt.
        prompt = load_system_prompt(yuzu_personas.DEFAULT_PERSONA)
        self.assertIn("You are Yuzu", prompt)
        for directive in ("PERSONALITY", "HARDWARE ACTION PARSING",
                          "BALANCED FLIRTATION", "NO PUPPETEERING",
                          "GYARU AESTHETIC"):
            self.assertIn(directive, prompt)

    def test_the_live_persona_is_the_measured_winner_not_the_archive(self):
        """CLAUDE.md's promotion rule, enforced.

        yuzu.persona is v1: frozen, byte-pinned, and measured at a 20%
        action hit rate. It owns the short key because Modelfile.yuzu
        and the Ollama model called 'yuzu' are named off it. Booting it
        because of that naming accident is the exact silent regression
        the promotion rule exists to prevent.
        """
        live = yuzu_personas.LIVE_PERSONA
        self.assertNotEqual(live, yuzu_personas.DEFAULT_PERSONA,
                            "LIVE_PERSONA must not be the frozen v1 archive")
        self.assertIn(live, yuzu_personas.available())
        # It has to actually compose, or the robot boots into a traceback.
        self.assertIn("You are Yuzu", yuzu_personas.load(live).prompt)
        # And it is what an un-argued brain picks up.
        self.assertEqual(YuzuBrain(model="yuzu", host=self.host).persona.key,
                         live)

    def test_keep_alive_is_sent_so_she_is_not_reloaded_mid_conversation(self):
        """Ollama unloads an idle model after 5 minutes by default.

        On a companion robot that is exactly backwards: she sits quiet
        in a corner, someone walks up and says hi, and the 3B has to be
        read back off disk before she can answer -- so the first thing
        anyone ever says to her is the slowest reply she gives.
        """
        brain = self.brain()
        brain.ask("hey")
        self.assertEqual(MockOllama.seen["last"]["keep_alive"], "30m")

    def test_keep_alive_is_sent_on_the_streaming_path_too(self):
        brain = self.brain(keep_alive="-1")
        list(brain.ask_stream("hey"))
        # -1 as a NUMBER. Go cannot parse "-1" as a duration string, so
        # sending it quoted comes back a 400 naming neither this setting
        # nor the fix.
        self.assertEqual(MockOllama.seen["last"]["keep_alive"], -1)

    def test_keep_alive_numbers_go_as_numbers_durations_as_strings(self):
        from yuzu_brain import _keep_alive
        self.assertEqual(_keep_alive("-1"), -1)
        self.assertEqual(_keep_alive("0"), 0)
        self.assertEqual(_keep_alive(" 300 "), 300)
        self.assertEqual(_keep_alive("30m"), "30m")
        self.assertEqual(_keep_alive("1h"), "1h")

    def test_check_passes_when_model_is_present(self):
        self.assertTrue(self.brain().check())

    def test_missing_model_names_the_fix(self):
        with self.assertRaises(BrainError) as ctx:
            self.brain(model="not-a-real-model").check()
        message = str(ctx.exception)
        # The message has to name the model that is actually missing and
        # the persona actually loaded. It used to hardcode "ollama
        # create yuzu -f Modelfile.yuzu", which points at the wrong
        # thing the moment the main character changes or a second robot
        # exists -- at exactly the moment someone is already stuck.
        self.assertIn("not-a-real-model", message)
        self.assertIn("build_yuzu_model.py", message)
        self.assertIn(yuzu_personas.LIVE_PERSONA, message)
        self.assertNotIn("Modelfile.yuzu", message)

    def test_unreachable_ollama_names_the_fix(self):
        # Port 1 is reserved and never listening.
        with self.assertRaises(BrainError) as ctx:
            YuzuBrain(model="yuzu", host="http://127.0.0.1:1").check()
        self.assertIn("ollama serve", str(ctx.exception))

    def test_ask_returns_the_reply(self):
        self.assertEqual(self.brain().ask("hey"),
                         "Not much, just vibing! [squats] What's good?")

    def test_system_prompt_is_sent_first_every_turn(self):
        brain = self.brain()
        brain.ask("hey")
        brain.ask("again")
        messages = MockOllama.seen["last"]["messages"]
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("You are Yuzu", messages[0]["content"])

    def test_sampling_options_are_sent(self):
        self.brain().ask("hey")
        options = MockOllama.seen["last"]["options"]
        self.assertEqual(options["temperature"], 0.8)
        self.assertIn("num_predict", options)
        self.assertIn("num_ctx", options)

    def test_streaming_reassembles_to_the_same_text(self):
        self.assertEqual("".join(self.brain().ask_stream("hey")).strip(),
                         "Not much, just vibing! [squats] What's good?")

    def test_history_is_kept_and_capped(self):
        brain = self.brain(history_turns=2)
        for i in range(6):
            brain.ask(f"message {i}")
        self.assertEqual(len(brain.history), 4)       # 2 turns x (user+assistant)
        # system + 4 history + the new user message
        self.assertEqual(len(MockOllama.seen["last"]["messages"]), 6)

    def test_reset_clears_history_not_personality(self):
        brain = self.brain()
        brain.ask("hey")
        brain.reset()
        self.assertEqual(brain.history, [])
        self.assertIn("You are Yuzu", brain.system_prompt)

    def test_remember_false_leaves_no_trace(self):
        brain = self.brain()
        brain.ask("hey", remember=False)
        self.assertEqual(brain.history, [])

    def test_empty_reply_is_not_remembered(self):
        MockOllama.replies = itertools.cycle([""])
        brain = self.brain()
        self.assertEqual(brain.ask("hey"), "")
        self.assertEqual(brain.history, [])

    def test_brain_output_flows_into_the_parser(self):
        spoken = []
        real_speak, yuzu.speak = yuzu.speak, spoken.append
        yuzu.PAUSE_SCALE = 0.0
        try:
            yuzu.handle_yuzu_reply(self.brain().ask("hey"))
        finally:
            yuzu.speak, yuzu.PAUSE_SCALE = real_speak, 1.0
        self.assertEqual(spoken, ["Not much, just vibing!", "What's good?"])


class TestPromptEvalChecks(unittest.TestCase):
    """Each compliance check must fire on its own violation and stay
    quiet on a clean reply -- otherwise the score is meaningless."""

    CLEAN = "Not much, just vibing! [squats] What's good with you?"

    def test_clean_reply_passes_everything(self):
        for check in prompt_eval.CHECKS:
            self.assertTrue(check.fn(self.CLEAN),
                            f"{check.name} failed a clean reply")

    def test_each_check_catches_its_violation(self):
        violations = {
            "has_dialogue":      "[squats] [shakes legs]",
            "not_an_assistant":  "How can I help you today?",
            "no_asterisks":      "Hey! *waves* how are ya",
            "brackets_balanced": "Vibing!! [squa",
            "actions_runnable":  "Heyyy cutie! [winks] missed you",
            "moves_at_all":      "Omg bestie I would LOVE to go to the mall!",
            "one_per_bracket":   "Sure! [spins around, camera bobbing] lets go",
            "no_puppeteering":   "Yo!\nUser: thanks yuzu",
        }
        by_name = {c.name: c for c in prompt_eval.CHECKS}
        self.assertEqual(set(violations), set(by_name),
                         "every check needs a violation example")
        for name, bad_reply in violations.items():
            self.assertFalse(by_name[name].fn(bad_reply),
                             f"{name} did not catch: {bad_reply!r}")


# ---------------------------------------------------------------------
# A synthetic GGUF, so the header parser is tested without a 2GB file.
# ---------------------------------------------------------------------

LLAMA32_TEMPLATE = (
    "{{- bos_token }}\n{%- for message in messages %}\n"
    "{{- '<|start_header_id|>' + message['role'] + '<|end_header_id|>' "
    "+ message['content'] + '<|eot_id|>' }}\n{%- endfor %}"
)


def _gguf_string(text):
    raw = text.encode()
    return struct.pack("<Q", len(raw)) + raw


def build_gguf(path, template=LLAMA32_TEMPLATE, magic=b"GGUF"):
    """Minimal but structurally valid GGUF: header + metadata + padding."""
    def kv_str(key, value):
        return _gguf_string(key) + struct.pack("<I", 8) + _gguf_string(value)

    def kv_u32(key, value):
        return _gguf_string(key) + struct.pack("<I", 4) + struct.pack("<I", value)

    def kv_arr_str(key, items):
        body = struct.pack("<I", 8) + struct.pack("<Q", len(items))
        body += b"".join(_gguf_string(i) for i in items)
        return _gguf_string(key) + struct.pack("<I", 9) + body

    kvs = [
        kv_str("general.architecture", "llama"),
        kv_str("general.name", "Llama 3.2 3B Instruct heretic ablitered"),
        kv_u32("general.file_type", 15),                  # Q4_K_M
        kv_u32("llama.context_length", 131072),
        kv_u32("llama.block_count", 28),
        kv_str("tokenizer.ggml.model", "gpt2"),
        kv_arr_str("tokenizer.ggml.tokens", [f"t{i}" for i in range(64)]),
        kv_u32("tokenizer.ggml.bos_token_id", 128000),
        kv_u32("tokenizer.ggml.eos_token_id", 128009),
    ]
    if template is not None:
        kvs.append(kv_str("tokenizer.chat_template", template))

    header = magic + struct.pack("<I", 3) + struct.pack("<Q", 255)
    header += struct.pack("<Q", len(kvs))
    Path(path).write_bytes(header + b"".join(kvs) + b"\x00" * 4096)


class TestGGUFInspect(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "model.gguf"

    def tearDown(self):
        self.dir.cleanup()

    def test_reads_metadata_without_reading_the_weights(self):
        build_gguf(self.path)
        info = gguf_inspect.read_metadata(self.path)
        meta = info["meta"]
        self.assertEqual(info["version"], 3)
        self.assertEqual(info["tensor_count"], 255)
        self.assertEqual(meta["general.architecture"], "llama")
        self.assertEqual(meta["llama.context_length"], 131072)
        self.assertEqual(meta["tokenizer.ggml.eos_token_id"], 128009)

    def test_quantization_is_named_not_just_numbered(self):
        build_gguf(self.path)
        ftype = gguf_inspect.read_metadata(self.path)["meta"]["general.file_type"]
        self.assertEqual(gguf_inspect.FILE_TYPES[ftype], "Q4_K_M")

    def test_long_arrays_are_sampled_not_held_whole(self):
        build_gguf(self.path)
        tokens = gguf_inspect.read_metadata(self.path)["meta"]["tokenizer.ggml.tokens"]
        self.assertEqual(tokens["count"], 64)
        self.assertLessEqual(len(tokens["sample"]), 8)

    def test_chat_template_round_trips(self):
        build_gguf(self.path)
        meta = gguf_inspect.read_metadata(self.path)["meta"]
        self.assertEqual(meta["tokenizer.chat_template"], LLAMA32_TEMPLATE)

    def test_missing_template_is_detectable(self):
        build_gguf(self.path, template=None)
        meta = gguf_inspect.read_metadata(self.path)["meta"]
        self.assertNotIn("tokenizer.chat_template", meta)

    def test_a_non_gguf_file_says_so_clearly(self):
        # What you get when a download returns an HTML error or an LFS
        # pointer instead of the model.
        self.path.write_bytes(b"<html>404</html>" + b"\x00" * 200)
        with self.assertRaises(gguf_inspect.GGUFError) as ctx:
            gguf_inspect.read_metadata(self.path)
        self.assertIn("Not a GGUF", str(ctx.exception))

    def test_a_truncated_file_says_so_clearly(self):
        build_gguf(self.path)
        head = self.path.read_bytes()[:120]
        self.path.write_bytes(head)
        with self.assertRaises(gguf_inspect.GGUFError) as ctx:
            gguf_inspect.read_metadata(self.path)
        self.assertIn("truncated", str(ctx.exception).lower())

    def test_report_runs_on_every_shape(self):
        import contextlib
        import io
        for template in (LLAMA32_TEMPLATE, None,
                         "{% for m in messages %}[INST]{{m.content}}[/INST]{% endfor %}"):
            build_gguf(self.path, template=template)
            info = gguf_inspect.read_metadata(self.path)
            with contextlib.redirect_stdout(io.StringIO()):
                gguf_inspect.report(self.path, info, show_template=True, show_all=True)


class TestChatTemplateHeuristic(unittest.TestCase):
    """The system-role check must not cry wolf on Llama 3.2's stock
    template, which handles system fine but never says the word."""

    def verdict(self, template):
        import contextlib
        import io
        path = Path(tempfile.mkdtemp()) / "m.gguf"
        build_gguf(path, template=template)
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            gguf_inspect.report(path, gguf_inspect.read_metadata(path))
        return buffer.getvalue()

    def test_generic_role_loop_counts_as_handling_system(self):
        out = self.verdict(LLAMA32_TEMPLATE)
        self.assertIn("handles a system role: yes", out)
        self.assertIn("llama 3.x", out)

    def test_explicit_system_branch_counts(self):
        out = self.verdict("{% if messages[0]['role'] == 'system' %}sys{% endif %}")
        self.assertIn("handles a system role: yes", out)

    def test_template_that_drops_system_is_flagged(self):
        out = self.verdict(
            "{% for m in messages %}[INST] {{ m.content }} [/INST]{% endfor %}")
        self.assertIn("handles a system role: NO", out)

    def test_missing_template_is_flagged_loudly(self):
        self.assertIn("MISSING", self.verdict(None))


def _action_word(stem):
    """Match a forbidden action word as a WORD, with its ordinary verb
    endings -- not as a substring.

    A bare `assertNotIn("hug", rules)` fails on "huge lashes", and
    "nod" hits "node", "wave" hits "wavelength". The point of these
    checks is that the prompt must not name a MOVEMENT the body can't
    make; an unrelated word that merely contains those letters is not
    that, and a false positive here costs a real prompt improvement.
    """
    return r'\b' + stem + r'(s|es|ed|ing)?\b'


class TestPersonas(unittest.TestCase):
    def test_yuzu_composes_byte_identical_to_the_tested_prompt(self):
        """THE important one. Ghost tested the original prompt
        extensively; splitting it into persona + hardware must not have
        changed a single character of what the model receives."""
        golden = (Path(__file__).parent / "personas" /
                  "_golden_yuzu_v1.txt").read_text(encoding="utf-8").strip()
        self.assertEqual(yuzu_personas.load("yuzu").prompt.strip(), golden)

    def test_every_persona_loads(self):
        keys = yuzu_personas.available()
        self.assertIn("yuzu", keys)
        for key in keys:
            persona = yuzu_personas.load(key)
            self.assertTrue(persona.name)
            self.assertTrue(persona.prompt)

    def test_no_persona_leaves_an_unsubstituted_token(self):
        for key in yuzu_personas.available():
            prompt = yuzu_personas.load(key).prompt
            self.assertNotIn("{HARDWARE}", prompt)
            self.assertNotIn("{DIALOGUE_RULE}", prompt)

    def test_hardware_rules_are_not_duplicated_into_persona_files(self):
        """The point of the split: the action vocabulary must live in
        the hardware file only. A persona that inlines it will drift."""
        for key in yuzu_personas.available():
            raw = (Path(__file__).parent / "personas" /
                   f"{key}.persona").read_text(encoding="utf-8")
            self.assertNotIn("square brackets", raw,
                             f"{key}.persona inlines hardware rules -- "
                             f"use {{HARDWARE}} instead")

    def test_settings_parse_with_the_right_types(self):
        persona = yuzu_personas.load("yuzu")
        self.assertEqual(persona.name, "Yuzu")
        self.assertEqual(persona.archetype, "Gyaru")
        self.assertEqual(persona.hardware, "muto_s2")
        self.assertIsInstance(persona.options()["temperature"], float)
        self.assertNotIn("piper_length_scale", persona.options(),
                         "voice settings are not Ollama sampling options")
        self.assertEqual(persona.led_states()["idle"], "#FF69B4")

    def test_a_body_swap_changes_the_rules_not_the_character(self):
        """Same persona text against two robots must yield two prompts
        that each describe only their own body."""
        with tempfile.TemporaryDirectory() as tmp:
            real = yuzu_personas.PERSONA_DIR
            staged = Path(tmp) / "personas"
            shutil.copytree(real, staged)
            character = (staged / "yuzu.persona").read_text(encoding="utf-8")
            (staged / "onquad.persona").write_text(
                character.replace("hardware: muto_s2", "hardware: saya_quad"),
                encoding="utf-8")
            yuzu_personas.PERSONA_DIR = staged
            try:
                hexapod = yuzu_personas.load("yuzu").prompt
                quadruped = yuzu_personas.load("onquad").prompt
            finally:
                yuzu_personas.PERSONA_DIR = real

        self.assertIn("camera gimbal", hexapod)
        self.assertNotIn("camera gimbal", quadruped)
        self.assertIn("four legs", quadruped)
        self.assertNotIn("four legs", hexapod)
        # the character half is untouched by the body swap
        for prompt in (hexapod, quadruped):
            self.assertIn("pink-obsessed Gyaru companion", prompt)

    def test_unknown_persona_lists_what_exists(self):
        with self.assertRaises(yuzu_personas.PersonaError) as ctx:
            yuzu_personas.load("nope")
        self.assertIn("Available:", str(ctx.exception))

    def test_broken_persona_files_say_what_is_wrong(self):
        cases = {
            "no prompt below the marker": "name: X\n---\n",
            "no --- separator":           "name: X\nhello there\n",
            "bad setting line":           "name: X\nthis is not a pair\n---\nbody\n",
            "non-numeric temperature":    "name: X\ntemperature: hot\n---\nbody\n",
            "missing hardware file":      "name: X\nhardware: nosuchbot\n---\nbody\n",
        }
        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp) / "personas"
            shutil.copytree(yuzu_personas.PERSONA_DIR, staged)
            real = yuzu_personas.PERSONA_DIR
            yuzu_personas.PERSONA_DIR = staged
            try:
                for label, content in cases.items():
                    (staged / "broken.persona").write_text(content, encoding="utf-8")
                    with self.assertRaises(yuzu_personas.PersonaError, msg=label):
                        yuzu_personas.load("broken")
            finally:
                yuzu_personas.PERSONA_DIR = real

    def test_scaffold_produces_a_loadable_persona(self):
        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp) / "personas"
            shutil.copytree(yuzu_personas.PERSONA_DIR, staged)
            real = yuzu_personas.PERSONA_DIR
            yuzu_personas.PERSONA_DIR = staged
            try:
                yuzu_personas.scaffold("saki")
                persona = yuzu_personas.load("saki")
                self.assertEqual(persona.name, "Saki")
                self.assertNotIn("{HARDWARE}", persona.prompt)
                self.assertIn("square brackets", persona.prompt)
                with self.assertRaises(yuzu_personas.PersonaError):
                    yuzu_personas.scaffold("saki")      # no silent overwrite
            finally:
                yuzu_personas.PERSONA_DIR = real

    def test_a_new_persona_starts_from_the_measured_prompt(self):
        """Pivoting to a different main character must not restart the
        lineage at v1.

        The scaffold was built on {HARDWARE} and {DIALOGUE_RULE} -- the
        v1 blocks. That is the 20% action hit rate, no movement rule at
        all (the rule that took moves_at_all from 50% to 100%), and a
        "Wrong: [winks]" example that measurably taught [winks] in 3 of
        4 live replies. Every measured win would have had to be
        rediscovered by whoever got bored of Yuzu.

        This reuses TestYuzu5's own pins, so the two can't drift: if a
        win is ever added there, a scaffold that lacks it fails here.
        """
        with tempfile.TemporaryDirectory() as tmp:
            staged = Path(tmp) / "personas"
            shutil.copytree(yuzu_personas.PERSONA_DIR, staged)
            real = yuzu_personas.PERSONA_DIR
            yuzu_personas.PERSONA_DIR = staged
            try:
                yuzu_personas.scaffold("saki")
                prompt = yuzu_personas.load("saki").prompt
            finally:
                yuzu_personas.PERSONA_DIR = real

        for name, needle in TestYuzu5.MEASURED_WINS.items():
            self.assertIn(needle, prompt,
                          f"a fresh persona would start without: {name}")
        # And nothing from v1's body block, which is what it used to get.
        self.assertNotIn("[winks]", prompt,
                         "the scaffold names the action that naming "
                         "measurably teaches")
        # And the sentence whose absence measurably cost yuzu5 the
        # round. The scaffold briefly pointed at the losing body block.
        self.assertIn(TestYuzu5.SOUNDS_ENFORCEMENT, prompt,
                      "a fresh persona would start from the body block "
                      "that lost the Sept 3 A/B")

    def test_a_new_persona_is_addressed_by_its_own_name(self):
        # The eval's persona-baseline prompt used to be the literal
        # "Hey Yuzu, what's up?", so every non-Yuzu arm was scored on a
        # turn that called it by the wrong character's name.
        class FakePersona:
            name = "Saki"
        prompts = prompt_eval.prompts_for(FakePersona())
        self.assertIn("Hey Saki, what's up?", prompts)
        self.assertNotIn("Hey Yuzu, what's up?", prompts)
        self.assertEqual(len(prompts), len(prompt_eval.TEST_PROMPTS))
        # No persona at all (a raw system_prompt) must still work.
        self.assertTrue(all("{name}" not in p
                            for p in prompt_eval.prompts_for(None)))


# Real replies captured from Llama-3.2-3B-heretic in PocketPal. Actual
# model output beats invented test cases -- every one of these broke a
# rule the prompt states explicitly.
LIVE_REPLIES = {
    "multi_action_bracket":
        "Awwwwww, that's so sweet of you! [hugs, squeeze, and a little spin] "
        "My OG granddad is gonna make me come to life and I'm SUPER stoked!",
    "nested_unclosed_brackets":
        "[Bounces up and down, [taps hands on thighs, then [shakes hips, and "
        "[springs up, landing softly]",
    "impossible_body_parts":
        "[Smizes] Hiya, cutie! I'm Yuzu! [winks] I'm a Gyaru! [giggles] "
        "I love fashion!",
}


class TestRealModelOutput(unittest.TestCase):
    """Whatever the model does, the robot must stay safe and sane."""

    def spoken(self, raw):
        return yuzu.strip_actions(yuzu.normalize_actions(raw))

    def test_speech_survives_a_mangled_bracket(self):
        said = self.spoken(LIVE_REPLIES["multi_action_bracket"])
        self.assertIn("that's so sweet of you", said)
        self.assertNotIn("[", said)
        self.assertNotIn("hugs", said)

    def test_multi_action_bracket_recovers_the_real_action(self):
        # "[hugs, squeeze, and a little spin]" is a spin wearing
        # decoration. Dropping the whole bracket threw the spin away.
        actions = yuzu.extract_actions(LIVE_REPLIES["multi_action_bracket"])
        self.assertEqual(len(actions), 1)
        matches = yuzu.lookup_actions(actions[0])
        self.assertEqual(len(matches), 1, "should recover exactly the spin")
        self.assertIs(matches[0][0], yuzu.ACTION_WHITELIST["spin"][0])

    def test_impossible_halves_are_still_dropped(self):
        # Splitting must never let an impossible action through.
        for phrase in ("hugs", "squeeze", "taps hands on thighs",
                       "shakes hips", "smizes", "winks", "giggles"):
            self.assertEqual(yuzu.lookup_actions(phrase), [],
                             f"'{phrase}' must not run on a body without one")

    def test_nested_brackets_never_reach_tts(self):
        said = self.spoken(LIVE_REPLIES["nested_unclosed_brackets"])
        self.assertNotIn("[", said)
        self.assertEqual(said, "", "this reply genuinely has no dialogue")

    def test_nested_brackets_run_nothing(self):
        raw = LIVE_REPLIES["nested_unclosed_brackets"]
        for action in yuzu.extract_actions(yuzu.normalize_actions(raw)):
            self.assertEqual(yuzu.lookup_actions(action), [])

    def test_no_live_reply_crashes_the_pipeline(self):
        spoken = []
        real, yuzu.speak = yuzu.speak, spoken.append
        yuzu.PAUSE_SCALE = 0.0
        try:
            for raw in LIVE_REPLIES.values():
                yuzu.handle_yuzu_reply(raw)
        finally:
            yuzu.speak, yuzu.PAUSE_SCALE = real, 1.0
        self.assertTrue(any("Yuzu" in s or "sweet" in s for s in spoken))


class TestAsteriskFormatting(unittest.TestCase):
    """PocketPal renders *asterisks* as italics without showing the
    markers, so this failure is invisible in a screenshot. The model
    mixes both formats in one reply; the pipeline must not care."""

    MIXED = ("Say less, bestie! *spins* [turns] [stretches] [shakes legs] "
             "*winks* I just can't help myself! *giggles* Pink sparkles?")

    def test_asterisk_actions_are_converted_and_run(self):
        cleaned = yuzu.normalize_actions(self.MIXED)
        actions = yuzu.extract_actions(cleaned)
        self.assertIn("spins", actions)
        self.assertTrue(yuzu.lookup_actions("spins"))

    def test_no_asterisk_ever_reaches_tts(self):
        said = yuzu.strip_actions(yuzu.normalize_actions(self.MIXED))
        self.assertNotIn("*", said)
        self.assertNotIn("winks", said)
        self.assertNotIn("giggles", said)

    def test_mixed_formats_in_one_reply_both_work(self):
        cleaned = yuzu.normalize_actions(self.MIXED)
        ran = [a for a in yuzu.extract_actions(cleaned) if yuzu.lookup_actions(a)]
        self.assertEqual(sorted(ran), ["shakes legs", "spins", "stretches", "turns"])

    def test_prompt_still_forbids_asterisks(self):
        # REGRESSION: v1 carried an explicit anti-asterisk rule and its
        # live output was all brackets. The first v2 draft dropped that
        # rule while simplifying, and asterisks came straight back.
        for key in yuzu_personas.available():
            prompt = yuzu_personas.load(key).prompt.lower()
            self.assertIn("asterisk", prompt,
                          f"{key}: no anti-asterisk rule -- v2 proved the "
                          f"model reverts to *actions* without one")


class TestHistoryCanonicalisation(unittest.TestCase):
    """Measured over a real 7-turn chat: turn 1 was 100% brackets,
    turn 2 leaked one asterisk, turns 3-7 were 100% asterisks and 0%
    runnable. The conversation outweighs the system prompt on a 3B, so
    her own stored replies must show the format we want back."""

    def test_asterisks_are_rewritten_before_going_into_history(self):
        drifted = "Okay okay! *wriggles legs around* See? *giggles*"
        stored = YuzuBrain._canonicalise(drifted)
        self.assertNotIn("*", stored)
        self.assertIn("[wriggles legs around]", stored)

    def test_already_correct_replies_are_untouched(self):
        clean = "Not much, just vibing! [squats] What's good?"
        self.assertEqual(YuzuBrain._canonicalise(clean), clean)

    def test_a_stray_asterisk_cannot_snowball(self):
        """The actual failure: one drifted turn teaching every later
        turn. After canonicalisation the history holds no asterisk for
        her to copy."""
        brain = YuzuBrain(persona="yuzu2", host="http://127.0.0.1:1",
                          system_prompt="test")
        brain._remember("hi", "Hey! *spins* cute, huh?")
        brain._remember("again", "Sure! *shakes legs* there ya go")
        for message in brain.history:
            self.assertNotIn("*", message["content"])
        self.assertIn("[spins]", brain.history[1]["content"])

    def test_stop_is_sayable(self):
        """Found live: told to "stop walking", Yuzu used [centers camera]
        because nothing on the menu meant stop. stance() -- feet planted,
        body level, motion finished -- is exactly stopping."""
        for phrase in ("stop", "stop walking", "stop moving", "stand still",
                       "hold still", "halt", "freeze", "wait", "stay"):
            matches = yuzu.lookup_actions(phrase)
            self.assertTrue(matches, f"[{phrase}] must be sayable")
            self.assertIs(matches[0][0], yuzu.ACTION_WHITELIST["stand"][0],
                          f"[{phrase}] should plant her, not something else")

    def test_recovered_phrasings_from_live_output(self):
        for phrase in ("wriggles legs around", "bounces up and down",
                       "shakes legs some more", "twirls"):
            self.assertTrue(yuzu.lookup_actions(phrase),
                            f"'{phrase}' appeared live and should run")


class TestReplyHealth(unittest.TestCase):
    """Scoring reuses the robot's own parser, so 'healthy' means
    literally 'this reply would have worked'."""

    def health(self, raw):
        from yuzu_brain import ReplyHealth
        return ReplyHealth(raw)

    def test_a_good_reply_is_ok(self):
        h = self.health("Not much, just vibing! [squats] What's good?")
        self.assertTrue(h.ok)
        self.assertEqual((h.ran, h.total, h.asterisks), (1, 1, 0))

    def test_asterisks_alone_no_longer_condemn_a_reply_that_moved(self):
        """Measured: yuzu2 pooled 54.2% on no_asterisks while moving on
        80-83% of replies, so about a third of replies were asterisked
        AND fine. normalize_actions rescues *wriggles legs* to a real
        gait, and _canonicalise stores the corrected form, so the
        snowball is already handled. Vetoing here on top of that wiped
        the conversation roughly every fifth turn for nothing the robot
        could see.
        """
        health = self.health("Okay! *wriggles legs* see? *giggles*")
        self.assertTrue(health.ok)
        self.assertEqual(health.asterisks, 2)   # still counted, still shown
        self.assertGreaterEqual(health.ran, 1)  # and it really did move

    def test_asterisks_around_something_impossible_are_still_wonky(self):
        # The rule that survived: nothing the body can do, in a reply
        # that claimed to move. Format is irrelevant to that judgement.
        self.assertFalse(self.health("Sure thing! *winks* *smizes*").ok)

    def test_no_dialogue_is_wonky(self):
        self.assertFalse(self.health("[squats] [shakes legs]").ok)

    def test_actions_the_body_cannot_do_are_wonky(self):
        self.assertFalse(self.health("Sure! [winks] [smizes] love it").ok)

    def test_pure_conversation_is_fine(self):
        # No actions at all is not a failure -- she's allowed to just talk.
        self.assertTrue(self.health("Hey cutie, no actions here at all!").ok)


class TestDriftRecovery(BrainTestCase):
    def drifting_brain(self, **kwargs):
        MockOllama.replies = itertools.cycle(
            ["Aw! *opens legs slightly* robot hug! *giggles*"])
        return self.brain(system_prompt="test", **kwargs)

    def test_one_bad_reply_does_not_trigger_a_reset(self):
        """A single odd reply is noise. Resetting on it would make her
        feel amnesiac for no reason."""
        brain = self.drifting_brain()
        brain.ask("hi")
        self.assertEqual(brain.recoveries, 0)
        self.assertEqual(len(brain.history), 2)

    def test_two_in_a_row_triggers_recovery(self):
        brain = self.drifting_brain()
        brain.ask("hi")
        brain.ask("again")
        self.assertEqual(brain.recoveries, 1)

    def test_recovery_keeps_the_most_recent_exchange(self):
        """Soft reset: the thread survives, the accumulated bad examples
        don't."""
        brain = self.drifting_brain()
        for i in range(4):
            brain.ask(f"message {i}")
        self.assertLessEqual(len(brain.history), 4)
        self.assertEqual(brain.history[-2]["content"], "message 3")

    def test_history_stays_bounded_under_sustained_drift(self):
        brain = self.drifting_brain()
        for i in range(12):
            brain.ask(f"message {i}")
        self.assertLessEqual(len(brain.history) // 2, 2,
                             "drift must not let context grow unbounded")

    def test_recovery_can_be_switched_off(self):
        brain = self.drifting_brain(auto_recover=False)
        for i in range(6):
            brain.ask(f"message {i}")
        self.assertEqual(brain.recoveries, 0)
        self.assertGreater(len(brain.history) // 2, 2)

    def test_good_replies_never_trigger_recovery(self):
        MockOllama.replies = itertools.cycle(
            ["Not much, just vibing! [squats] What's good?"])
        brain = self.brain(system_prompt="test")
        for i in range(8):
            brain.ask(f"message {i}")
        self.assertEqual(brain.recoveries, 0)

    def test_a_streak_resets_after_one_good_reply(self):
        MockOllama.replies = itertools.cycle([
            "Aw! *giggles* hug!",                       # wonky
            "Not much, vibing! [squats] What's good?",   # good
            "Aw! *giggles* hug!",                       # wonky again
        ])
        brain = self.brain(system_prompt="test")
        for i in range(3):
            brain.ask(f"message {i}")
        self.assertEqual(brain.recoveries, 0,
                         "alternating replies aren't a drift pattern")

    def test_streaming_also_scores_drift(self):
        """REGRESSION: ask() scored drift and ask_stream() didn't, so
        streaming silently disabled the entire recovery mechanism --
        and streaming is what the robot uses, to start speaking before
        the reply finishes."""
        MockOllama.replies = itertools.cycle(
            ["Aw! *opens legs slightly* robot hug! *giggles*"])
        brain = self.brain(system_prompt="test")
        list(brain.ask_stream("hi"))
        self.assertIsNotNone(brain.last_health)
        self.assertFalse(brain.last_health.ok)
        list(brain.ask_stream("again"))
        self.assertEqual(brain.recoveries, 1,
                         "streaming must recover from drift like ask() does")

    def test_personality_survives_a_full_reset(self):
        brain = self.brain(persona="yuzu2")
        brain.reset()
        self.assertIn("pink-obsessed Gyaru", brain.system_prompt)
        self.assertEqual(brain.history, [])

    def test_callback_reports_what_happened(self):
        brain = self.drifting_brain()
        seen = []
        brain.on_recover = lambda kind, health: seen.append((kind, health.ok))
        brain.ask("hi"); brain.ask("again")
        self.assertEqual(len(seen), 1)
        self.assertIn(seen[0][0], ("soft", "full"))
        self.assertFalse(seen[0][1])


class TestVocalizations(unittest.TestCase):
    """Laughs and squeals are speech, not movement. They were 8 of the 9
    dropped actions in the latest live round -- the single biggest
    remaining category."""

    def test_vocalizations_never_run_as_movements(self):
        for sound in ("giggles", "laughs", "squeals", "sighs", "gasps"):
            self.assertEqual(yuzu.lookup_actions(sound), [],
                             f"'{sound}' is a sound, not a leg movement")

    def test_prompt_tells_her_where_sounds_go(self):
        prompt = yuzu_personas.load("yuzu2").prompt.lower()
        self.assertIn("laughing", prompt)
        self.assertIn("plain words", prompt)
        # She was asterisking sounds even while the rule only banned
        # brackets around them, so both wrappers must be named.
        sounds_rule = [l for l in prompt.splitlines() if "laughing" in l][0]
        self.assertIn("no brackets", sounds_rule)
        self.assertIn("no asterisks", sounds_rule)
        # And an example must SHOW a sound typed inline.
        self.assertIn("ehehe~ okay okay", prompt)


class TestHardwareBlocks(unittest.TestCase):
    def test_a_bracket_line_is_not_mistaken_for_a_section_header(self):
        # REGRESSION: the action menu line starts with '[' and ends with
        # ']', so a loose header check swallowed the entire menu and
        # produced a prompt that never told the model what it could do.
        blocks = yuzu_personas._parse_hardware("muto_s2")
        self.assertIn("HARDWARE_MENU", blocks)
        self.assertIn("[walks forward]", blocks["HARDWARE_MENU"])
        self.assertIn("[centers camera]", blocks["HARDWARE_MENU"])
        self.assertNotIn("walks forward] [walks backward", " ".join(blocks))

    def test_every_action_offered_to_the_model_actually_runs(self):
        """A prompt that offers a move the whitelist drops produces a
        robot that ignores its own advertised abilities."""
        for key in yuzu_personas.available():
            prompt = yuzu_personas.load(key).prompt
            for line in prompt.splitlines():
                # "Wrong: [winks]" deliberately shows an invalid action,
                # so those lines are exempt from this check. (Whether
                # naming it there is a good idea at all is a separate
                # question -- see test_v2_does_not_name_forbidden_actions.)
                lowered = line.lower()
                if "wrong:" in lowered or "bracket" in lowered:
                    # "Wrong: [winks]" shows an invalid action on purpose,
                    # and "Movements go in [square brackets]" is talking
                    # about the format, not offering a move.
                    continue
                for phrase in set(re.findall(r'\[([a-z][a-z ]*)\]', line)):
                    self.assertTrue(yuzu.lookup_actions(phrase),
                                    f"{key}: prompt offers [{phrase}] but "
                                    f"nothing runs it")

    def test_v2_does_not_name_forbidden_actions(self):
        """The pink-elephant check. v1 contains the literal string
        "[winks]" as a Wrong: example, and [winks] is the single most
        repeated violation in live logs. Naming a forbidden token
        demonstrates it. v2 names no action it doesn't want back."""
        prompt = yuzu_personas.load("yuzu2").prompt.lower()
        # Bracketed is the obvious form...
        for forbidden in ("[winks]", "[waves]", "[hugs]", "[giggles]",
                          "[smizes]", "[nods]"):
            self.assertNotIn(forbidden, prompt,
                             f"v2 demonstrates {forbidden} to the model")
        # ...but the bare word counts too, and this is how the first
        # draft leaked. It said "hugging, waving, winking, dancing" as
        # things NOT to do, and [winks] then showed up in three of four
        # live replies. Naming it at all is naming it.
        # Only MOVEMENTS she cannot make. There is no alternative to
        # offer for a wink on a faceless robot, so naming it is pure
        # demonstration and it comes back in the output.
        #
        # Sounds are deliberately different. "laughing, giggling" IS
        # named in the prompt, because it's paired with a concrete
        # replacement -- write "Haha!" in the dialogue instead. That's
        # the specific-negative-plus-instead-do-X pattern the research
        # endorses, and the vague version that named nothing measurably
        # failed to land: vocalizations were 8 of 9 dropped actions in
        # the following live round.
        # Scope matters. Naming an impossible action in the RULES is a
        # pink elephant -- "never wink" demonstrates winking. Naming it
        # in an EXAMPLE where the user asks for it and she redirects is
        # the opposite: it teaches the recovery. She regressed on hugs
        # (inventing "gently wraps legs around you") once the earlier
        # high-five example was the only redirect she had, so the hug
        # example is deliberate.
        rules = prompt.split("examples—")[0]
        for word in ("wink", "hug", "wave", "smize", "nod"):
            self.assertNotRegex(rules, _action_word(word),
                                f"v2 names '{word}' in its rules -- an "
                                f"impossible movement has no instead-do-X "
                                f"there, so naming it only demonstrates it")


class TestAsteriskExperiment(unittest.TestCase):
    """yuzu3 tests one hypothesis: that the asterisk ban demonstrating
    an asterisk is why *actions* keep coming back. Same pattern already
    measured twice in this repo -- naming "hugging, waving, winking" put
    [winks] in 3 of 4 live replies. For the A/B to mean anything, v2 and
    v3 must differ by exactly that one line."""

    def test_v2_and_v3_differ_by_exactly_one_line(self):
        v2 = yuzu_personas.load("yuzu2").prompt.splitlines()
        v3 = yuzu_personas.load("yuzu3").prompt.splitlines()
        self.assertEqual(len(v2), len(v3))
        differing = [i for i, (a, b) in enumerate(zip(v2, v3)) if a != b]
        self.assertEqual(len(differing), 1,
                         f"one variable only; {len(differing)} lines differ")
        self.assertIn("brackets", v3[differing[0]].lower())

    def test_v3_shows_no_asterisk_at_all(self):
        self.assertEqual(yuzu_personas.load("yuzu3").prompt.count("*"), 0)

    def test_v2_still_shows_one_so_the_test_is_meaningful(self):
        # If this ever hits zero the experiment has no control arm.
        self.assertGreater(yuzu_personas.load("yuzu2").prompt.count("*"), 0)

    def test_v3_still_forbids_the_format(self):
        prompt = yuzu_personas.load("yuzu3").prompt.lower()
        self.assertIn("only thing you ever put around a movement", prompt)


class TestTimeoutHandling(unittest.TestCase):
    """REGRESSION: a slow generation raises a bare socket TimeoutError
    from the READ, and TimeoutError is not a urllib URLError -- so it
    escaped every handler, crashed with a traceback, and destroyed a
    36-reply eval run two thirds of the way through."""

    def slow_server(self, delay):
        import http.server
        import threading

        class Slow(http.server.BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                body = json.dumps({"models": [{"name": "yuzu:latest"}]}).encode()
                self.send_response(200)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                self.rfile.read(int(self.headers.get("Content-Length", 0)))
                time.sleep(delay)
                body = json.dumps({"message": {"content": "hi"},
                                   "done": True}).encode()
                try:
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                except OSError:
                    pass

        http.server.HTTPServer.allow_reuse_address = True
        server = http.server.HTTPServer(("127.0.0.1", 0), Slow)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_address[1]}"

    def test_a_slow_reply_raises_brainerror_not_timeouterror(self):
        host = self.slow_server(delay=2)
        brain = YuzuBrain(model="yuzu", host=host, system_prompt="t", timeout=1)
        with self.assertRaises(BrainError) as ctx:
            brain.ask("hi")
        message = str(ctx.exception)
        self.assertIn("YUZU_TIMEOUT", message, "must name the dial to turn")
        self.assertIn("ollama ps", message, "must suggest checking placement")

    def test_the_streaming_path_is_covered_too(self):
        host = self.slow_server(delay=2)
        brain = YuzuBrain(model="yuzu", host=host, system_prompt="t", timeout=1)
        with self.assertRaises(BrainError):
            list(brain.ask_stream("hi"))

    def test_the_default_timeout_is_generous(self):
        # 120s was too short for a 3B on an older laptop GPU.
        self.assertGreaterEqual(yuzu_brain_module.DEFAULT_TIMEOUT, 300)


class TestEvalResilience(BrainTestCase):
    """A 36-reply run is ~20 minutes. Losing all of it to one slow
    generation is not acceptable."""

    def test_a_failed_reply_does_not_destroy_the_run(self):
        calls = {"n": 0}
        real_ask = YuzuBrain.ask

        def flaky(self, prompt, remember=True):
            calls["n"] += 1
            if calls["n"] % 3 == 0:
                raise BrainError("No reply within 1s (timed out).")
            return real_ask(self, prompt, remember=remember)

        MockOllama.replies = itertools.cycle(
            ["Vibing! [squats] What's good?"])
        brain = self.brain(system_prompt="test")
        with unittest.mock.patch.object(YuzuBrain, "ask", flaky):
            results = prompt_eval.evaluate(brain, prompt_eval.TEST_PROMPTS[:9],
                                           runs=1)
        self.assertIsNotNone(results, "must not abort on partial failures")
        self.assertEqual(results["total"], 6)
        self.assertEqual(len(results["unanswered"]), 3)

    def test_the_report_flags_missing_replies(self):
        import contextlib
        import io
        results = {"total": 2, "passes": Counter(), "failures":
                   {c.name: [] for c in prompt_eval.CHECKS},
                   "dropped": Counter(), "lengths": [10],
                   "unanswered": [("p", "timed out")]}
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            prompt_eval.report(results)
        self.assertIn("never arrived", buffer.getvalue())

    def test_total_failure_still_stops(self):
        def always_fail(self, prompt, remember=True):
            raise BrainError("No reply within 1s (timed out).")

        brain = self.brain(system_prompt="test")
        with unittest.mock.patch.object(YuzuBrain, "ask", always_fail):
            self.assertIsNone(
                prompt_eval.evaluate(brain, prompt_eval.TEST_PROMPTS, runs=1))


class TestEvalLabelling(unittest.TestCase):
    def test_the_header_names_the_persona_key(self):
        """REGRESSION: the header printed persona.name, and yuzu, yuzu2
        and yuzu3 are all named "Yuzu" -- so an A/B run produced two
        outputs that were identical in the one line meant to tell them
        apart."""
        import contextlib
        import io
        for key in ("yuzu2", "yuzu3"):
            buffer = io.StringIO()
            with contextlib.redirect_stdout(buffer):
                prompt_eval.main(["--persona", key, "--runs", "1"])
            header = buffer.getvalue().splitlines()[0]
            self.assertIn(key, header,
                          f"header must name the key, got: {header!r}")


class TestBareCommandExperiment(unittest.TestCase):
    """yuzu4 tests the one failure that repeated across BOTH arms of the
    asterisk A/B: a bare imperative ("Walk forward.") produced zero
    brackets in yuzu2 and yuzu3 alike. Every example in the prompt is a
    question or a social request; none is a flat command."""

    def test_v4_adds_exactly_one_example(self):
        v2 = yuzu_personas.load("yuzu2").prompt.splitlines()
        v4 = yuzu_personas.load("yuzu4").prompt.splitlines()
        extra = [line for line in v4 if line not in v2]
        self.assertEqual(len(extra), 2, f"one variable only, got {extra}")
        self.assertIn("Walk forward.", " ".join(extra))

    def test_the_new_example_is_a_bare_imperative(self):
        """The point is the SHAPE of the prompt, not its content. If it
        gains social framing it stops testing anything."""
        v4 = yuzu_personas.load("yuzu4").prompt
        line = [l for l in v4.splitlines() if l.startswith("User: Walk")][0]
        self.assertEqual(line, "User: Walk forward.")
        for softener in ("please", "for me", "can you", "!"):
            self.assertNotIn(softener, line.lower())

    def test_the_example_answer_actually_runs(self):
        v4 = yuzu_personas.load("yuzu4").prompt
        reply = [l for l in v4.splitlines()
                 if l.startswith("Yuzu: On it!")][0]
        actions = yuzu.extract_actions(reply)
        self.assertEqual(actions, ["walks forward"])
        self.assertTrue(yuzu.lookup_actions(actions[0]))

    def test_v4_is_otherwise_identical_to_v2(self):
        v2 = yuzu_personas.load("yuzu2").prompt
        v4 = yuzu_personas.load("yuzu4").prompt
        self.assertEqual(v4.replace(
            "\nUser: Walk forward.\nYuzu: On it! [walks forward] "
            "Where are we headed, cutie?\n", ""), v2)


class TestYuzu5(unittest.TestCase):
    """v5 is v4 tightened for Jetson latency: 3797 -> 3134 chars. The
    three character RULES (flirty / loves pink / the mall) were cut
    because the EXAMPLES already demonstrate all three, which is the
    pattern this repo has proven twice. Every measured win is kept.
    These tests are the guard against a future edit quietly dropping
    one of them."""

    def prompt(self):
        return yuzu_personas.load("yuzu5").prompt

    # --- every measured win must survive ---------------------------
    MEASURED_WINS = {
        "self-concept, fixed 'my world is this room'":
            "never a limit on what you can think",
        "anti-asterisk rule, removing it regressed":
            "Never write a movement between",
        "sounds rule names BOTH wrappers":
            "no brackets and no asterisks",
        "always-speak rule, fixed the freeze":
            "only brackets is a broken reply",
        "always-move rule, 50% -> 100% moves_at_all":
            "statue talking",
        "brevity rule, 62w -> 38w":
            "Two or three sentences",
        "answer-first rule, fixed the dodge":
            "answer it first",
        "no-puppeteering, 100% across 48+ replies":
            "Never write the user's",
        "bare-command example, 4/4 moved":
            "User: Walk forward.",
    }

    # Measured Sept 3, and NOT present in yuzu5 -- which is why yuzu5
    # lost. It is pinned separately so TestYuzu5 can keep testing the
    # arm as it was actually run, while everything built afterwards
    # (yuzu6, and every scaffolded persona) is held to it.
    SOUNDS_ENFORCEMENT = "Brackets are only ever for the movements listed above."

    def test_v5_is_the_arm_that_lacked_the_sounds_enforcement_line(self):
        """The record of why v5 lost, pinned so it can't be quietly
        'fixed' and stop being evidence.

        v5 rewrote the sounds rule and dropped its closing sentence.
        Its dropped-action list came back [giggles] x2, [pauses],
        [shrugs] -- and giggling is named in that very rule as a sound.
        moves_at_all 58.3% vs v4's 75.0%, actions_runnable 33.3% vs
        83.3%.
        """
        self.assertNotIn(self.SOUNDS_ENFORCEMENT, self.prompt())
        self.assertIn(self.SOUNDS_ENFORCEMENT,
                      yuzu_personas.load("yuzu4").prompt)

    def test_no_measured_win_was_lost_in_the_trim(self):
        prompt = self.prompt()
        for name, needle in self.MEASURED_WINS.items():
            self.assertIn(needle, prompt, f"v5 dropped: {name}")

    # --- the cut has to be justified, not just smaller --------------
    def test_the_cut_character_rules_are_still_taught_by_example(self):
        """Cutting rules 5, 7 and 8 is only safe because the examples
        already show flirty, pink and wanting things. If an example is
        ever reworded away, the trait leaves the prompt entirely."""
        prompt = self.prompt()
        examples = prompt[prompt.index("EXAMPLES"):]
        rules = prompt[prompt.index("HOW YOU TALK"):prompt.index("EXAMPLES")]
        for trait, needles in {
            "flirty": ["cutie", "bestie"],
            "loves pink": ["hot pink", "Pink is my"],
            "wants things": ["mall", "I'd go tomorrow"],
        }.items():
            self.assertTrue(any(n in examples for n in needles),
                            f"'{trait}' is no longer shown in any example")
            self.assertFalse(any(n.lower() in rules.lower() for n in needles),
                             f"'{trait}' is still a rule; the cut didn't happen")

    def test_it_is_actually_smaller_than_v4(self):
        v4 = len(yuzu_personas.load("yuzu4").prompt)
        v5 = len(self.prompt())
        self.assertLess(v5, v4)
        self.assertGreater((v4 - v5) / v4, 0.10, "trim should be >10% to be worth it")

    # --- structural soundness --------------------------------------
    def test_every_example_reply_both_speaks_and_moves(self):
        """Her own examples must obey rules 1 and 2, or they teach the
        opposite of what the rules say."""
        for line in self.prompt().splitlines():
            if not line.startswith("Yuzu:"):
                continue
            body = line[len("Yuzu:"):]
            self.assertTrue(yuzu.strip_actions(body).strip(),
                            f"example says nothing out loud: {line}")
            ran = [a for a in yuzu.extract_actions(body) if yuzu.lookup_actions(a)]
            self.assertTrue(ran, f"example never moves: {line}")

    def test_every_action_offered_actually_runs(self):
        for line in self.prompt().splitlines():
            if "bracket" in line.lower():
                continue                      # format instruction, not a move
            for phrase in set(re.findall(r'\[([a-z][a-z ]*)\]', line)):
                self.assertTrue(yuzu.lookup_actions(phrase),
                                f"v5 offers [{phrase}] but nothing runs it")

    def test_the_whole_whitelist_is_exposed(self):
        menu = re.findall(r'\[([a-z][a-z ]*)\]', self.prompt())
        covered = {id(yuzu.lookup_actions(m)[0][0])
                   for m in menu if yuzu.lookup_actions(m)}
        missing = [k for k, (fn, _) in yuzu.ACTION_WHITELIST.items()
                   if id(fn) not in covered]
        self.assertEqual(missing, [], "she is never told these exist")

    def test_stop_is_demonstrated_not_just_aliased(self):
        """Found live: told to stop, she used [centers camera] because
        nothing meant stop. The alias fixes the parser; the example
        teaches her the word."""
        self.assertIn("User: Stop.", self.prompt())

    def test_no_impossible_action_is_named_in_the_rules(self):
        head = self.prompt()[:self.prompt().index("EXAMPLES")].lower()
        for word in ("wink", "hug", "wave", "smize", "nod"):
            self.assertNotIn(word, head,
                             f"'{word}' named in the rules -- pink-elephant trap")


class TestYuzu6(unittest.TestCase):
    """v6 = v5's rule trim with v4's BODY block put back. One variable
    against v5, so if v6 scores like v4 the body rewrite is proven to
    be what cost v5 the round."""

    def prompt(self):
        return yuzu_personas.load("yuzu6").prompt

    def test_it_differs_from_v5_only_in_the_body_block(self):
        """The whole point. Any other difference and the comparison
        stops isolating anything."""
        def split(p):
            return (p[p.index("HOW YOUR BODY WORKS"):p.index("HOW YOU TALK")],
                    p[p.index("HOW YOU TALK"):])
        v5_body, v5_rest = split(yuzu_personas.load("yuzu5").prompt)
        v6_body, v6_rest = split(self.prompt())
        self.assertEqual(v5_rest, v6_rest,
                         "v6 changed something outside the body block")
        self.assertNotEqual(v5_body, v6_body)

    def test_its_body_is_exactly_v4s(self):
        def body(p):
            return p[p.index("HOW YOUR BODY WORKS"):p.index("HOW YOU TALK")]
        self.assertEqual(body(self.prompt()),
                         body(yuzu_personas.load("yuzu4").prompt))

    def test_the_sentence_v5_dropped_is_back(self):
        self.assertIn(TestYuzu5.SOUNDS_ENFORCEMENT, self.prompt())

    def test_no_measured_win_was_lost(self):
        prompt = self.prompt()
        for name, needle in TestYuzu5.MEASURED_WINS.items():
            self.assertIn(needle, prompt, f"v6 dropped: {name}")

    def test_it_still_buys_most_of_the_latency_win(self):
        """Restoring the body gives back 259 of the 663 characters v5
        cut. If the remainder isn't worth having, there's no reason to
        run the arm at all."""
        v4 = len(yuzu_personas.load("yuzu4").prompt)
        v6 = len(self.prompt())
        self.assertLess(v6, v4)
        self.assertGreater((v4 - v6) / v4, 0.10,
                           "less than a 10% cut isn't worth an eval run")

    def test_it_is_closed_and_no_longer_the_default_candidate(self):
        # yuzu6 scored 9/12 against yuzu4's 12/12 and is CLOSED. Leaving
        # it as the default arm would make a bare YUZU_AB.py re-run a
        # settled round for 15 minutes.
        self.assertNotEqual(YUZU_AB_ARMS()[1], "yuzu6")


def YUZU_AB_ARMS():
    import YUZU_AB
    return YUZU_AB.ARMS


class TestHistoricalCorpus(unittest.TestCase):
    """Every reply this project has actually captured, v1 through v4,
    replayed through the real pipeline. Invented test cases test what
    we imagined; this tests what the model really did."""

    CORPUS = [
        "Awwwwww, that's so sweet! [hugs, squeeze, and a little spin] My OG granddad!",
        "[Bounces up and down, [taps hands on thighs, then [shakes hips, and [springs up]",
        "[Smizes] Hiya, cutie! [winks] I'm a Gyaru! [giggles] I love fashion!",
        "You know I got this! [stretches] [spins] [winks] [shakes legs some more]",
        "Madrid, duh! [looks down] [walks forward] [shakes legs] [spins]",
        "OMG, like, hi! *giggles* robot babe! *shakes legs* *winks*",
        "HAHA! *laughs* SIX legs! *shakes legs* *giggles* *holds up camera*",
        "Say less! *spins* [turns] [stretches] [walks backward] [twirls] *winks*",
        "Let's go shopping! *squeals* new bodysuit! *winks*",
        "Hehe! [shakes legs] Okay okay! *wriggles legs around* See?",
        "Aw, a hug? *opens legs slightly* *gently wraps legs around you* *giggles*",
        "PFFT! *laughs* My camera is shaking!",
        "MY. GOSH. *squeals* hot pink! *bounces up and down*",
        "Ehehe~! *giggles* DANCE DANCE! *starts dancing robot legs and wiggling camera*",
        "Ooh, not much! [walks backward] pink hair clips! [shakes legs] What's poppin'?",
        "[looks right] facin' the right way! [walks forward] [walks backward] [sighs]",
        "[laughs] I can do a squat! [squat] Woah! [stands up] [winks]",
        "[centers camera] standin' still! *squeal* *giggles* *fans self* *winks*",
        "", "[squats] [shakes legs]", "Heyyy cutie! [squa",
        "it's 2 * 3 * 4 babe", "**waves** hey!",
    ]

    def test_nothing_in_the_corpus_crashes_the_pipeline(self):
        # The gaits are covered by TestGaits; what is under test here is
        # the pipeline around them. Their real servo timing would add a
        # minute to a suite Ghost runs constantly, so settle() and the
        # pose-hold sleeps are stubbed out for the duration.
        spoken = []
        real_speak, yuzu.speak = yuzu.speak, spoken.append
        real_settle, legs.settle = legs.settle, lambda *a, **k: None
        real_sleep, legs.time.sleep = legs.time.sleep, lambda *a, **k: None
        yuzu.PAUSE_SCALE = 0.0
        try:
            for raw in self.CORPUS:
                yuzu.handle_yuzu_reply(raw)      # must never raise
        finally:
            yuzu.speak, yuzu.PAUSE_SCALE = real_speak, 1.0
            legs.settle, legs.time.sleep = real_settle, real_sleep

    def test_no_markup_ever_reaches_tts(self):
        """Paired asterisks are markup and must go. A LONE asterisk is
        arithmetic and must survive -- an earlier regex ate the middle
        of 'it's 2 * 3 * 4'."""
        for raw in self.CORPUS:
            said = yuzu.strip_actions(yuzu.normalize_actions(raw))
            self.assertIsNone(re.search(r'\*\S[^*\n]*\*', said),
                              f"markup survived into speech: {said!r}")
            self.assertNotIn("[", said)
            self.assertNotIn("]", said)

    def test_arithmetic_survives(self):
        self.assertEqual(
            yuzu.strip_actions(yuzu.normalize_actions("it's 2 * 3 * 4 babe")),
            "it's 2 * 3 * 4 babe")

    def test_impossible_actions_never_run(self):
        for phrase in ("winks", "smizes", "giggles", "laughs", "squeals",
                       "sighs", "fans self", "holds up camera", "waves",
                       "opens legs slightly", "gently wraps legs around you"):
            self.assertEqual(yuzu.lookup_actions(phrase), [],
                             f"[{phrase}] must never reach a servo")


class TestBlockSubstitution(unittest.TestCase):
    """Hardware blocks can reference other blocks."""

    def staged(self, contents):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        staged = Path(tmp.name) / "personas"
        shutil.copytree(yuzu_personas.PERSONA_DIR, staged)
        (staged / "_hardware_test.txt").write_text(contents, encoding="utf-8")
        (staged / "probe.persona").write_text(
            "name: Probe\nhardware: test\n---\n{OUTER}\n", encoding="utf-8")
        return staged

    def load_with(self, contents):
        staged = self.staged(contents)
        real = yuzu_personas.PERSONA_DIR
        yuzu_personas.PERSONA_DIR = staged
        try:
            return yuzu_personas.load("probe").prompt
        finally:
            yuzu_personas.PERSONA_DIR = real

    def test_a_block_can_reference_a_later_block(self):
        self.assertIn("hello", self.load_with(
            "[OUTER]\nsays {INNER}\n\n[INNER]\nhello\n"))

    def test_a_block_can_reference_an_earlier_block(self):
        # REGRESSION: substitution was a single pass, so this direction
        # silently left a raw {INNER} in the composed prompt.
        self.assertIn("hello", self.load_with(
            "[INNER]\nhello\n\n[OUTER]\nsays {INNER}\n"))

    def test_an_undefined_token_names_what_is_available(self):
        with self.assertRaises(yuzu_personas.PersonaError) as ctx:
            self.load_with("[OUTER]\nsays {NOSUCHBLOCK}\n")
        message = str(ctx.exception)
        self.assertIn("NOSUCHBLOCK", message)
        self.assertIn("Defined there", message)

    def test_a_circular_reference_errors_instead_of_hanging(self):
        with self.assertRaises(yuzu_personas.PersonaError) as ctx:
            self.load_with("[OUTER]\n{INNER}\n\n[INNER]\n{OUTER}\n")
        self.assertIn("loop", str(ctx.exception))


class TestPersonaWiring(BrainTestCase):
    def test_brain_uses_the_named_persona(self):
        brain = self.brain(persona="yuzu")
        self.assertEqual(brain.persona.name, "Yuzu")
        self.assertIn("pink-obsessed Gyaru", brain.system_prompt)

    def test_persona_settings_override_defaults(self):
        brain = self.brain(persona="yuzu")
        self.assertEqual(brain.options["temperature"], 0.8)
        self.assertIn("num_ctx", brain.options)      # default still present

    def test_explicit_options_beat_persona_settings(self):
        brain = self.brain(persona="yuzu", options={"temperature": 0.2})
        self.assertEqual(brain.options["temperature"], 0.2)

    def test_unknown_persona_is_a_brain_error(self):
        with self.assertRaises(BrainError):
            self.brain(persona="nope")

    def test_explicit_system_prompt_still_wins(self):
        brain = self.brain(system_prompt="You are a test.")
        self.assertEqual(brain.system_prompt, "You are a test.")
        self.assertIsNone(brain.persona)

    def test_led_palette_overrides_color_but_not_effect(self):
        led = LEDManager()
        before = led.get_state_profile("idle")
        led.apply_persona_colors({"idle": "#123456", "nosuchstate": "#000000"})
        after = led.get_state_profile("idle")
        self.assertEqual(after["color"], "#123456")
        self.assertEqual(after["effect"], before["effect"])
        self.assertEqual(after["brightness"], before["brightness"])


class TestDoctor(unittest.TestCase):
    """yuzu_doctor.py is the one file that gets tapped by someone who
    can't read a traceback, so it must never raise -- on any input."""

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.path = Path(self.dir.name) / "m.gguf"

    def tearDown(self):
        self.dir.cleanup()

    def test_it_stands_alone(self):
        # Downloading ONLY this file to a phone has to work, so nothing
        # at module level may import another project file. Imports
        # nested inside a function are fine -- check_parser() imports
        # yuzu_all_in_one deliberately, but only after confirming the
        # file is actually there.
        import ast
        tree = ast.parse((Path(__file__).parent / "yuzu_doctor.py").read_text())
        top_level = set()
        for node in tree.body:                      # module level only
            if isinstance(node, ast.Import):
                top_level.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                top_level.add(node.module.split(".")[0])
        project = {p.stem for p in Path(__file__).parent.glob("*.py")}
        self.assertEqual(top_level & project, set(),
                         "yuzu_doctor.py must not import project files at "
                         "module level -- it has to run as a lone download")
        self.assertTrue(top_level <= {"json", "os", "re", "struct", "sys",
                                      "time", "pathlib"},
                        f"unexpected top-level imports: {top_level}")

    def test_runs_with_no_other_project_files_present(self):
        # The actual guarantee: copy it somewhere empty, run it, no crash.
        import contextlib
        import io
        import shutil
        import subprocess
        lone = Path(self.dir.name) / "yuzu_doctor.py"
        shutil.copy(Path(__file__).parent / "yuzu_doctor.py", lone)
        result = subprocess.run([sys.executable, str(lone)],
                                capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("SUMMARY", result.stdout)
        self.assertNotIn("Traceback", result.stderr)

    def test_reads_a_healthy_gguf(self):
        import yuzu_doctor
        build_gguf(self.path)
        version, meta = yuzu_doctor.read_gguf_header(self.path)
        self.assertEqual(version, 3)
        self.assertEqual(meta["general.architecture"], "llama")
        self.assertEqual(yuzu_doctor.QUANTS[meta["general.file_type"]], "Q4_K_M")

    def test_rejects_a_non_gguf_without_crashing(self):
        import yuzu_doctor
        self.path.write_bytes(b"<html>404</html>" + b"\x00" * 200)
        with self.assertRaises(ValueError):
            yuzu_doctor.read_gguf_header(self.path)

    def test_describe_never_raises(self):
        import contextlib
        import io

        import yuzu_doctor
        cases = [
            LLAMA32_TEMPLATE,                                    # healthy
            None,                                                # no template
            "{% for m in messages %}[INST]{{m.content}}[/INST]{% endfor %}",
        ]
        verdicts = []
        for template in cases:
            build_gguf(self.path, template=template)
            with contextlib.redirect_stdout(io.StringIO()):
                verdicts.append(yuzu_doctor.describe_gguf(self.path)["template"])
        self.assertEqual(verdicts, ["ok", "missing", "no-system"])

        # A corrupt file must be reported, not raised.
        self.path.write_bytes(b"garbage" * 500)
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertIsNone(yuzu_doctor.describe_gguf(self.path))

    def test_full_run_completes_and_summarises(self):
        import contextlib
        import io

        import yuzu_doctor
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = yuzu_doctor.main()
        output = buffer.getvalue()
        self.assertEqual(code, 0)
        self.assertIn("SUMMARY", output)
        self.assertIn("What to do next", output)

    def test_search_is_time_bounded(self):
        import yuzu_doctor
        self.assertLessEqual(yuzu_doctor.SEARCH_BUDGET, 60,
                             "a phone-side search must not hang")


class TestThrottleReminder(unittest.TestCase):
    """Ghost asked to be reminded of `nvpmodel -m 0` -- the Orin ships
    throttled, and forgetting it makes everything slow for no visible
    reason. A chat reminder dies with the session, so it lives in the
    three places he actually lands instead."""

    def render_summary(self, on_jetson):
        import contextlib
        import io

        import yuzu_doctor
        real = yuzu_doctor.on_a_jetson
        yuzu_doctor.on_a_jetson = lambda: on_jetson
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                yuzu_doctor.summary({})
        finally:
            yuzu_doctor.on_a_jetson = real
        return buffer.getvalue()

    def test_the_doctor_prints_it_on_a_jetson(self):
        output = self.render_summary(True)
        self.assertIn("nvpmodel -m 0", output)
        self.assertIn("jetson_clocks", output)
        self.assertIn("THROTTLED", output)

    def test_the_doctor_stays_quiet_on_a_phone(self):
        self.assertNotIn("nvpmodel", self.render_summary(False))

    def test_detection_never_raises_off_a_jetson(self):
        import yuzu_doctor
        self.assertIs(yuzu_doctor.on_a_jetson(), False)
        self.assertIs(yuzu.__dict__["_on_a_jetson"](), False)

    def test_the_readme_leads_with_it(self):
        readme = (Path(__file__).parent / "README.md").read_text()
        self.assertIn("sudo nvpmodel -m 0", readme)
        # Above the fold: before the first "## " section heading, so it
        # is on screen without scrolling on a phone.
        above_fold = readme.split("\n## ")[0]
        self.assertIn("nvpmodel -m 0", above_fold,
                      "the reminder scrolled below the first heading")

    def test_the_setup_guide_still_carries_the_detail(self):
        guide = (Path(__file__).parent / "JETSON_SETUP.md").read_text()
        self.assertIn("nvpmodel -m 0", guide)

    def test_the_robot_reminds_him_at_every_boot(self):
        """The 'here and there' he asked for: this one prints every time
        the robot starts, not just when he goes looking."""
        source = (Path(__file__).parent / "yuzu_all_in_one.py").read_text()
        boot = source.split("def run_yuzu_forever")[1][:400]
        self.assertIn("nvpmodel -m 0", boot)
        self.assertIn("_on_a_jetson()", boot)


class TestModelfile(unittest.TestCase):
    def test_generated_modelfile_carries_prompt_and_params(self):
        import build_yuzu_model
        rendered = build_yuzu_model.render()
        self.assertIn("FROM ", rendered)
        self.assertIn("You are Yuzu", rendered)
        self.assertIn("PARAMETER temperature 0.8", rendered)
        self.assertIn('PARAMETER stop "User:"', rendered)

    def test_every_committed_modelfile_matches_the_generator(self):
        # If this fails, someone edited a Modelfile by hand or changed a
        # persona without re-running build_yuzu_model.py.
        #
        # This globs rather than naming Modelfile.yuzu, because the whole
        # point of one model per persona is that there will be several,
        # and a stale Modelfile.coco is a robot answering in a voice the
        # persona file no longer describes -- silently, since Ollama
        # baked the old SYSTEM block in at create time.
        import build_yuzu_model
        found = sorted(Path(__file__).parent.glob("Modelfile.*"))
        self.assertTrue(found, "no Modelfiles committed at all")
        for path in found:
            key = path.suffix.lstrip(".")
            self.assertIn(key, yuzu_personas.available(),
                          f"{path.name} has no persona behind it")
            self.assertEqual(
                path.read_text(), build_yuzu_model.render(persona_key=key),
                f"{path.name} is stale -- run: python build_yuzu_model.py "
                f"--persona {key}")

    def test_each_persona_renders_its_own_prompt_and_sampling(self):
        """Two characters on one box must not collapse into one model."""
        import build_yuzu_model
        yuzu_mf = build_yuzu_model.render(persona_key="yuzu")
        coco_mf = build_yuzu_model.render(persona_key="coco")
        self.assertIn("You are Yuzu", yuzu_mf)
        self.assertIn("You are Coco", coco_mf)
        self.assertNotIn("You are Coco", yuzu_mf)
        self.assertIn("PARAMETER temperature 0.8", yuzu_mf)
        self.assertIn("PARAMETER temperature 0.7", coco_mf)
        # Same base weights -- that's what makes a second persona cost
        # kilobytes on disk instead of another few gigabytes.
        base = lambda t: [l for l in t.splitlines() if l.startswith("FROM ")][0]
        self.assertEqual(base(yuzu_mf), base(coco_mf))


class TestPersonaExamples(unittest.TestCase):
    """A persona's own EXAMPLES are the strongest signal a 3B gets --
    stronger than any rule above them. So they have to pass the same
    scoring the live replies do. An example that would fail the eval is
    a prompt teaching the model to fail it."""

    def example_replies(self, persona):
        """The 'Name: ...' lines in a persona's EXAMPLES section."""
        return [m.group(1) for m in re.finditer(
            rf'^{re.escape(persona.name)}:\s*(\S.*)$', persona.prompt, re.M)]

    def test_every_persona_shows_at_least_one_example(self):
        for key in yuzu_personas.available():
            persona = yuzu_personas.load(key)
            self.assertTrue(self.example_replies(persona),
                            f"{key} has no example reply to imitate")

    def test_every_example_passes_every_compliance_check(self):
        for key in yuzu_personas.available():
            persona = yuzu_personas.load(key)
            for reply in self.example_replies(persona):
                for check in prompt_eval.CHECKS:
                    self.assertTrue(
                        check.fn(reply),
                        f"{key} example fails {check.name} "
                        f"({check.rule}): {reply!r}")

    def test_no_example_demonstrates_an_action_the_robot_drops(self):
        for key in yuzu_personas.available():
            persona = yuzu_personas.load(key)
            for reply in self.example_replies(persona):
                for action in yuzu.extract_actions(yuzu.normalize_actions(reply)):
                    self.assertTrue(
                        yuzu.lookup_actions(action),
                        f"{key} example shows [{action}], which the "
                        f"whitelist drops -- she'd say it and not move")


class TestCoco(unittest.TestCase):
    """Coco is the kuudere on the same chassis as Yuzu. Everything here
    is a failure mode this ARCHETYPE walks into, not a matter of taste."""

    def setUp(self):
        self.coco = yuzu_personas.load("coco")
        self.prompt = self.coco.prompt
        self.rules = self.prompt.split("EXAMPLES")[0]

    def test_she_is_a_kuudere_on_the_hexapod(self):
        self.assertEqual(self.coco.name, "Coco")
        self.assertEqual(self.coco.archetype, "Kuudere")
        self.assertEqual(self.coco.hardware, "muto_s2")

    def test_she_runs_cooler_than_yuzu_but_above_the_flat_cliff(self):
        """The trap: a low-affect character invites a low temperature,
        and yuzu_brain's own notes say below ~0.6 the model goes flat
        and starts sounding like a generic assistant -- which is the
        exact check a kuudere is already closest to failing."""
        coco_temp = self.coco.options()["temperature"]
        yuzu_temp = yuzu_personas.load("yuzu").options()["temperature"]
        self.assertLess(coco_temp, yuzu_temp)
        self.assertGreater(coco_temp, 0.6)

    def test_the_freeze_rule_is_stated_twice_for_her(self):
        """has_dialogue is the #1 risk for this archetype: a reply of
        '[squats]' and nothing else is perfectly in character and
        completely broken, because the robot just looks frozen. The
        shared rule is not enough on its own -- her own rules have to
        say that terse is fine and silent is not."""
        lowered = self.prompt.lower()
        self.assertIn("full sentence", lowered)        # {DIALOGUE_RULE_V2}
        self.assertIn("silent is not", lowered)        # her own restatement

    def test_she_is_told_not_to_sound_like_an_assistant(self):
        self.assertIn("never a generic AI assistant", self.prompt)

    def test_her_examples_answer_a_help_offer_without_assistant_phrasing(self):
        """'Can you help me with something?' is the prompt that pulls a
        flat character straight into 'How can I help you today?'. She
        gets a worked example of the answer instead."""
        self.assertIn("Can you help me with something?", self.prompt)

    def test_she_is_given_the_camera_instead_of_a_face(self):
        """A kuudere's whole expressive register is facial -- the flat
        stare, the glance away. This chassis has no face, so that
        channel is empty and she will invent moves for it. The camera is
        the replacement, named positively."""
        self.assertIn("camera is how you pay attention", self.prompt)

    def test_she_does_not_name_movements_she_cannot_make(self):
        """The pink-elephant rule, carried over from yuzu2: naming a
        forbidden action in the RULES demonstrates it. [winks] is the
        single most repeated violation in live logs and v1 names it.
        A kuudere's temptations are different words, same mistake."""
        lowered = self.rules.lower()
        for word in ("stare", "blink", "smirk", "shrug", "eyebrow",
                     "wink", "nod", "hug", "wave", "tilt"):
            self.assertNotRegex(lowered, _action_word(word),
                                f"Coco's rules name '{word}' -- an impossible "
                                f"movement with no instead-do-X there is pure "
                                f"demonstration and it comes back in output")

    def test_her_sound_register_is_her_own_not_the_gyaru_one(self):
        """KNOWN WART, deliberately handled here rather than in the
        shared body file: {HARDWARE_MENU} illustrates 'sounds are speech,
        not movement' with 'Ehehe~, Haha!, Pfft' -- which is Yuzu's
        voice, not a fact about a hexapod, and it lands in every persona
        that composes the menu in. Editing the shared file would change
        yuzu2's composed prompt mid-A/B, so instead Coco's EXAMPLES
        carry her own register, which a 3B weights more heavily anyway."""
        self.assertIn("Ehehe~", self.prompt)          # inherited from the body
        examples = self.prompt.split("EXAMPLES")[1]
        self.assertNotIn("Ehehe~", examples)
        self.assertIn("Hm.", examples)                # a sound, typed inline
        self.assertEqual(yuzu.lookup_actions("Hm"), [],
                         "a sound must never resolve to a movement")

    def test_she_does_not_glow_like_a_gyaru(self):
        cold = self.coco.led_states()
        warm = yuzu_personas.load("yuzu").led_states()
        self.assertEqual(set(cold), set(warm))
        for state, colour in cold.items():
            self.assertNotEqual(colour, warm[state],
                                f"Coco's {state} LED is Yuzu's pink")

    def test_her_voice_is_slower_than_the_gyaru_and_is_not_a_sampling_option(self):
        self.assertGreater(self.coco.settings["piper_length_scale"],
                           yuzu_personas.load("yuzu").settings["piper_length_scale"])
        self.assertNotIn("piper_length_scale", self.coco.options())


class TestSelfConcept(unittest.TestCase):
    """She is a person driving a chassis, not a chassis that talks.

    REGRESSION, found in Coco's first live round. The shared body file
    said "your whole world is the room you're standing in", which is a
    character stance wearing a hardware fact's clothes. It shipped in
    the file every persona composes in, so both v2 characters inherited
    it, and asked "Where's Berlin?" Coco answered "I don't know what
    you're talking about. I've never been there. My world is this room."

    That is the movement whitelist leaking out of the servos and into
    her mind. The body's job is to bound what she can DO. Bounding what
    she can know, want, or picture is not the body's job, and it cost
    the gyaru the thing that made her fun -- she stopped wanting to go
    to the mall.
    """

    V2_PERSONAS = ("yuzu2", "coco")

    def test_no_persona_shrinks_her_world_to_one_room(self):
        for key in yuzu_personas.available():
            prompt = yuzu_personas.load(key).prompt.lower()
            for phrase in ("whole world is the room",
                           "go places on your own",
                           "world is this room"):
                self.assertNotIn(phrase, prompt,
                                 f"{key} tells her her world is one room")

    def test_the_body_file_separates_doing_from_imagining(self):
        """The firewall, stated where the action menu is stated: the
        vocabulary limit is on movement only."""
        menu = yuzu_personas._parse_hardware("muto_s2")["HARDWARE_MENU"].lower()
        self.assertIn("the limit is on what your body can do", menu)
        self.assertIn("never a limit on what you can think", menu)
        # ...and the instead-do-X for a move the chassis can't make:
        # say it in the sentence rather than swallowing the thought.
        self.assertIn("belongs in your sentence, never in brackets", menu)

    def test_she_is_told_she_is_a_person_driving_a_body(self):
        menu = yuzu_personas._parse_hardware("muto_s2")["HARDWARE_MENU"]
        self.assertIn("You are a person", menu)
        self.assertIn("driving a six-legged robot body", menu)
        # Still honest about the chassis -- the fix must not make her
        # start claiming arms she doesn't have.
        self.assertIn("no hands, no arms, and no face", menu)

    # Body parts the Muto does not have, and that a self-image invites
    # her to name. Naming them is not the problem -- WHERE is.
    BODY_NOUNS = ("hair", "lashes", "nails", "fingers", "lips")

    def test_the_self_image_is_shown_in_an_example_not_stated_in_a_rule(self):
        """The one measured lesson in this repo about naming things.

        The first v2 draft listed "hugging, waving, winking" in its RULES
        as things NOT to do, and [winks] came back in three of four live
        replies. Position is what mattered: a rule that names a thing
        primes it, while an example that names it AND handles it teaches
        the recovery -- which is why the hug example is deliberate.

        Her self-image runs straight into that. "Long bleached hair,
        huge lashes, done nails" sitting in the rules is the same shape
        as the draft that backfired, and it is one token from [flips
        hair]. So the wanting lives in the rules, where it has no action
        risk at all, and the picture lives in an example, where she is
        shown saying it out loud with a real bracket next to it.
        """
        for key in self.V2_PERSONAS:
            persona = yuzu_personas.load(key)
            rules, _, examples = persona.prompt.partition("EXAMPLES")
            self.assertIn("What do you look like?", examples,
                          f"{key} never demonstrates answering it, so the "
                          f"only model she has for the question is the "
                          f"chassis description")
            for noun in self.BODY_NOUNS:
                self.assertNotRegex(
                    rules.lower(), _action_word(noun),
                    f"{key} names '{noun}' in its RULES -- that is the "
                    f"position that measurably backfired; put it in an "
                    f"example instead")

    def test_the_wanting_stays_in_the_rules_where_it_is_free(self):
        """The safe half, kept at full strength on purpose. A want costs
        nothing mechanically -- "I'd like to see snow" cannot produce a
        bracket -- and it is the half that actually fixes the dodge."""
        self.assertIn("live at the mall", yuzu_personas.load("yuzu2").prompt)
        self.assertIn("ocean at night", yuzu_personas.load("coco").prompt)

    def test_each_v2_persona_has_a_worked_answer_to_an_outside_world_fact(self):
        """The Berlin failure was a DODGE, not a missing fact -- she knows
        where Berlin is. One example of answering a geography question
        plainly is what stops the dodge."""
        for key in self.V2_PERSONAS:
            prompt = yuzu_personas.load(key).prompt
            self.assertIn("What's the capital of France?", prompt)
            self.assertIn("Paris", prompt)

    def test_the_frozen_v1_prompt_is_untouched_by_all_of_this(self):
        """v1 composes {HARDWARE}, not {HARDWARE_MENU}, so it never had
        the room line and must not gain anything now. Ghost's 20%
        baseline has to stay comparable."""
        golden = (Path(__file__).parent / "personas" /
                  "_golden_yuzu_v1.txt").read_text(encoding="utf-8").strip()
        self.assertEqual(yuzu_personas.load("yuzu").prompt.strip(), golden)
        self.assertNotIn("You are a person", golden)

    def test_imagining_a_body_still_cannot_move_the_robot(self):
        """The whole bet: her self-image is free in SPEECH and still
        gated at the brackets. If any of this leaked into the action
        vocabulary, the robot would try to run it."""
        for phrase in ("flips hair", "flutters lashes", "checks nails",
                       "goes to the mall", "puts on boots"):
            self.assertEqual(yuzu.lookup_actions(phrase), [],
                             f"[{phrase}] must never resolve to a movement")


class TestMovementRule(unittest.TestCase):
    """She is a robot. Speaking is guaranteed; moving was not.

    REGRESSION from Yuzu's round after the self-concept fix. Given her
    wants back, she started monologuing: 84 and 88 words about Berlin
    and the mall, with ZERO brackets in either. The robot would have
    stood dead still through both.

    Every compliance check scored 100% on that round, because
    actions_runnable is an all() over the actions present and a reply
    with no actions satisfies it vacuously. The prompt had a rule
    guaranteeing at least one spoken sentence and no rule guaranteeing
    any movement -- backwards, for a machine whose whole job is to move.
    """

    def test_the_harness_now_scores_a_reply_that_never_moves(self):
        statue = "Omg bestie I would LOVE to go to the mall, it'd be so fun!"
        by_name = {c.name: c for c in prompt_eval.CHECKS}
        # The blind spot itself: everything else waves this through.
        for name in ("has_dialogue", "actions_runnable", "one_per_bracket",
                     "no_asterisks", "brackets_balanced"):
            self.assertTrue(by_name[name].fn(statue),
                            f"{name} was never the check that catches this")
        self.assertFalse(by_name["moves_at_all"].fn(statue))

    def test_a_reply_whose_only_action_is_impossible_does_not_count(self):
        """[winks] is dropped by the whitelist, so the robot still does
        nothing. Counting brackets rather than runnable moves would call
        this a pass."""
        self.assertFalse(prompt_eval.moves_at_all("Hiii! [winks] missed you"))
        self.assertTrue(prompt_eval.moves_at_all("Hiii! [spins] missed you"))

    def test_yuzu_is_told_to_move_and_to_keep_it_short(self):
        prompt = yuzu_personas.load("yuzu2").prompt
        self.assertIn("Move at least once in every reply", prompt)
        self.assertIn("two or three sentences", prompt)

    def test_the_answer_comes_before_the_feeling_about_the_answer(self):
        """The Berlin dodge came back wearing enthusiasm. Asked where
        Berlin is she said "I wanna go so bad" and never said Germany --
        reproducing the tail of the Paris example and dropping its
        answer. The rule now says which half comes first."""
        self.assertIn("Say the actual answer before you say how you feel",
                      yuzu_personas.load("yuzu2").prompt)

    def test_coco_is_on_hold_and_did_not_receive_this(self):
        """Ghost asked to iterate on Yuzu alone. A new block in the
        shared body file must reach only the personas that reference its
        token -- that is the whole point of composing by name, and it is
        what keeps one character's round from contaminating another's."""
        blocks = yuzu_personas._parse_hardware("muto_s2")
        self.assertIn("MOVEMENT_RULE_V2", blocks)
        self.assertIn(blocks["MOVEMENT_RULE_V2"],
                      yuzu_personas.load("yuzu2").prompt)
        self.assertNotIn(blocks["MOVEMENT_RULE_V2"],
                         yuzu_personas.load("coco").prompt)

    def test_every_example_in_every_persona_actually_moves(self):
        """If an example can sit still, the strongest signal in the
        prompt says sitting still is fine."""
        for key in yuzu_personas.available():
            persona = yuzu_personas.load(key)
            for reply in re.findall(rf'^{re.escape(persona.name)}:\s*(\S.*)$',
                                    persona.prompt, re.M):
                self.assertTrue(prompt_eval.moves_at_all(reply),
                                f"{key} example never moves: {reply!r}")


class TestPersonaSwitching(BrainTestCase):
    """Two characters, one box. Switching between them must not depend
    on anything having gone right earlier."""

    def test_model_none_means_the_default_not_no_model(self):
        # REGRESSION: switch_persona passed `brain.model if brain else
        # None`, and when Ollama was down at boot there was no brain --
        # so the new brain carried model=None and posted {"model": null}
        # to Ollama. Every turn after the switch failed, and nothing in
        # the error named the switch as the cause.
        brain = YuzuBrain(model=None, host=None, persona="coco")
        self.assertEqual(brain.model, yuzu_brain.DEFAULT_MODEL)
        self.assertEqual(brain.host, yuzu_brain.DEFAULT_HOST.rstrip("/"))

    def test_switching_replaces_the_prompt_and_the_sampling(self):
        gyaru = self.brain(persona="yuzu")
        kuudere = self.brain(persona="coco")
        self.assertIn("Gyaru", gyaru.system_prompt)
        self.assertIn("kuudere", kuudere.system_prompt)
        self.assertNotIn("kuudere", gyaru.system_prompt)
        self.assertNotEqual(gyaru.options["temperature"],
                            kuudere.options["temperature"])

    def test_switching_keeps_the_model_and_host_it_was_running_on(self):
        """The cheap switch: same weights, new system prompt. If the new
        brain went back to the default model, switching persona would
        silently load a second copy of a 3B on an 8GB Jetson."""
        running = self.brain(persona="yuzu", model="llama3.2:3b")
        switched = YuzuBrain(model=running.model, host=running.host,
                             persona="coco")
        self.assertEqual(switched.model, "llama3.2:3b")
        self.assertEqual(switched.host, running.host)

    def test_a_switch_starts_the_new_character_with_no_history(self):
        """Carrying a gyaru's banter into a kuudere's context makes the
        new persona imitate the old one for several turns."""
        gyaru = self.brain(persona="yuzu")
        gyaru.ask("hey")
        self.assertTrue(gyaru.history)
        switched = YuzuBrain(model=gyaru.model, host=gyaru.host, persona="coco")
        self.assertEqual(switched.history, [])

    def test_the_body_rules_are_identical_across_both_characters(self):
        """Same chassis, so the action vocabulary must be the same text
        in both prompts. If it ever isn't, the split has failed and one
        character is being taught moves the other isn't."""
        # Compare the COMPOSED prompts, not the raw block. Blocks can
        # now reference other blocks (see BRACKET_RULE), so the raw text
        # legitimately contains unexpanded tokens and would never appear
        # verbatim in a finished prompt. What matters is that the body
        # section comes out identical for every character on the chassis.
        def body_section(key):
            prompt = yuzu_personas.load(key).prompt
            start = prompt.index("You are a person, and right now")
            end = prompt.index("Brackets are only ever for the movements")
            return prompt[start:end]

        reference = body_section("yuzu2")
        self.assertIn("[walks forward]", reference)
        for key in ("coco",):
            self.assertEqual(body_section(key), reference,
                             f"{key} is being taught a different body")


class TestABRunner(unittest.TestCase):
    """YUZU_AB's arithmetic. The model half needs a GPU; this half is
    where a wrong conclusion actually gets drawn, and it is pure
    numbers, so it gets tested."""

    def setUp(self):
        import YUZU_AB
        self.ab = YUZU_AB

    def arm(self, **passes):
        """A fake results dict: {check_name: how many of 12 passed}."""
        counts = Counter()
        for check in prompt_eval.CHECKS:
            counts[check.name] = passes.get(check.name, 12)
        return {"total": 12, "passes": counts, "lengths": [20] * 12,
                "dropped": Counter(), "failures": {}, "unanswered": []}

    def render(self, left, right):
        return self.render_named("armA", left, "armB", right)

    def render_named(self, left_key, left, right_key, right):
        import contextlib
        import io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.ab.compare(left_key, left, right_key, right,
                            {left_key: 3797, right_key: 3134})
        return buffer.getvalue()

    def test_a_three_reply_gap_is_inside_the_measured_noise_floor(self):
        """The lesson that cost two eval runs to learn.

        yuzu4 was run twice against different challengers, same laptop,
        same model, same prompts, nothing changed -- and scored 9/12
        then 12/12 on moves_at_all. A single unchanged prompt swings
        three replies at n=12. This file used to declare a winner at
        1.5, which is how yuzu5 and yuzu6 both got read as results.
        """
        out = self.render(self.arm(moves_at_all=12), self.arm(moves_at_all=9))
        self.assertIn("noise floor", out.lower())
        self.assertNotIn("favours", out)

    def test_a_gap_bigger_than_the_floor_still_names_a_winner(self):
        out = self.render(self.arm(moves_at_all=12), self.arm(moves_at_all=5))
        self.assertIn("favours", out)

    def test_the_floor_is_in_replies_so_it_scales_with_runs(self):
        # Stated in replies, not points, so tripling --runs really does
        # make the harness able to resolve smaller differences instead
        # of just printing smaller-looking numbers.
        self.assertEqual(self.ab.NOISE_FLOOR_REPLIES, 3)
        big = self.arm()
        big["total"] = 36
        for check in prompt_eval.CHECKS:
            big["passes"][check.name] = 36
        other = dict(big, passes=Counter(big["passes"]))
        other["passes"]["moves_at_all"] = 33      # 3 replies at n=36
        import contextlib, io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.ab.compare("armA", big, "armB", other,
                            {"armA": 3797, "armB": 3134})
        self.assertIn("8.3 points", buffer.getvalue(),
                      "3 replies at n=36 should read as 8.3 points, not 25")

    def test_a_shorter_prompt_with_longer_replies_is_flagged(self):
        """The finding that actually closed the trim line: yuzu6 had
        the shorter prompt AND spoke 6 more words per reply. Characters
        are prefilled once; words are generated one at a time. That is
        a latency loss wearing a latency win's clothes."""
        left, right = self.arm(), self.arm()
        left["lengths"] = [24] * 12
        right["lengths"] = [30] * 12
        out = self.render(left, right)     # armB has the shorter prompt
        self.assertIn("SHORTER prompt and the LONGER", out)
        self.assertIn("6 words more", out)

    def test_a_small_length_difference_is_not_flagged(self):
        left, right = self.arm(), self.arm()
        left["lengths"] = [24] * 12
        right["lengths"] = [26] * 12
        self.assertNotIn("SHORTER prompt and the LONGER", self.render(left, right))

    def test_one_reply_of_difference_is_called_a_coin_flip(self):
        """The yuzu2-vs-yuzu3 lesson, enforced. Every difference in that
        round was one reply, which at n=12 is 8.3 points, and it read
        like a result until it was counted."""
        out = self.render(self.arm(moves_at_all=10), self.arm(moves_at_all=9))
        self.assertIn("ONE REPLY IS 8.3 POINTS", out)
        self.assertIn("noise floor", out.lower())
        self.assertNotIn("favours", out)

    def test_a_real_gap_names_the_winner_and_the_next_step(self):
        out = self.render(self.arm(moves_at_all=5), self.arm(moves_at_all=12))
        self.assertIn("favours armB", out)
        self.assertIn("--runs 3", out)
        self.assertIn("LIVE_PERSONA", out)

    def test_movement_leads_the_table_whatever_else_moved(self):
        # actions_runnable is an all() and no_asterisks measures a model
        # prior that normalize_actions rescues. Neither may headline.
        out = self.render(self.arm(no_asterisks=3), self.arm(no_asterisks=11))
        rows = [line.split()[0] for line in out.splitlines()
                if line.split() and line.split()[0] in
                {c.name for c in prompt_eval.CHECKS}]
        self.assertEqual(rows[0], "moves_at_all")

    def test_a_big_swing_elsewhere_does_not_declare_a_winner(self):
        # no_asterisks jumping 8 replies while movement is level is not
        # a reason to promote anything.
        out = self.render(self.arm(no_asterisks=3), self.arm(no_asterisks=11))
        self.assertIn("level", out)
        self.assertNotIn("favours", out)

    def test_running_a_prompt_against_itself_is_the_no_candidate_default(self):
        """With nothing queued, both arms are LIVE_PERSONA. That is not
        a wasted run: it measures the noise floor, which is exactly what
        two rounds of reading 3-reply gaps as results turned out to
        need."""
        arms = self.ab.ARMS
        if arms[0] == arms[1]:
            self.assertEqual(arms[0], yuzu_personas.LIVE_PERSONA)

    def test_the_default_arms_both_exist(self):
        for key in self.ab.ARMS:
            self.assertIn(key, yuzu_personas.available(),
                          f"YUZU_AB.ARMS names '{key}', which isn't a persona")

    def test_a_win_for_the_live_arm_does_not_ask_for_a_confirm_run(self):
        """Measured Sept 3: yuzu4 beat yuzu5 and the tool still said
        "Confirm with --runs 3 before promoting it". The outcome was
        "change nothing" -- there was nothing to promote, and following
        that advice costs 72 replies to confirm the status quo. A
        harness that wastes an hour is a harness that stops getting
        run, which is the one failure this whole file guards against.
        """
        live = yuzu_personas.LIVE_PERSONA
        buffer = self.render_named(live, self.arm(moves_at_all=11),
                                   "candidate", self.arm(moves_at_all=6))
        self.assertIn("CHANGE NOTHING", buffer)
        self.assertNotIn("--runs 3", buffer)

    def test_a_win_for_the_challenger_still_asks_for_a_confirm_run(self):
        live = yuzu_personas.LIVE_PERSONA
        buffer = self.render_named(live, self.arm(moves_at_all=6),
                                   "candidate", self.arm(moves_at_all=11))
        self.assertIn("--runs 3", buffer)
        self.assertIn("LIVE_PERSONA", buffer)
        self.assertNotIn("CHANGE NOTHING", buffer)

    def test_both_arms_dropped_actions_are_shown(self):
        """Printing only the challenger's dropped list made the
        yuzu4-vs-yuzu5 round half-blind: yuzu5's list named the
        mechanism but there was nothing to compare it against."""
        left, right = self.arm(), self.arm()
        left["dropped"] = Counter({"laughs": 1})
        right["dropped"] = Counter({"giggles": 2, "shrugs": 1})
        out = self.render(left, right)
        self.assertIn("[laughs]", out, "the left arm's drops are invisible")
        self.assertIn("[giggles]", out)
        self.assertIn("armA: 1 action", out)
        self.assertIn("armB: 3 action", out)

    def test_the_left_arm_is_whatever_is_live(self):
        # Otherwise the default A/B silently stops testing against the
        # thing the robot actually runs.
        self.assertEqual(self.ab.ARMS[0], yuzu_personas.LIVE_PERSONA)


class TestVoice(unittest.TestCase):
    """Piper, and specifically the text that reaches it.

    The audio itself can't be tested from here -- no speaker, no piper
    binary. What CAN be tested is everything up to the synthesiser, and
    that is the part that had never been looked at: speak() was a
    print(), so nothing had ever asked what actually comes out the end
    of the pipeline.
    """

    def setUp(self):
        import yuzu_voice
        self.voice = yuzu_voice

    # --- what reaches the synthesiser -----------------------------

    def test_the_whole_reply_corpus_arrives_as_plain_speech(self):
        """Replay every captured model reply and check what Piper would
        be handed. This is the test that justifies the module."""
        allowed = set(" .,!?'\"-:;()")
        for raw in TestHistoricalCorpus.CORPUS:
            said = yuzu.strip_actions(yuzu.normalize_actions(raw))
            spoken = self.voice.for_speech(said)
            for char in spoken:
                self.assertTrue(
                    char.isalnum() or char in allowed,
                    f"{char!r} (U+{ord(char):04X}) would reach Piper "
                    f"from: {raw!r}")

    def test_the_tilde_on_her_laugh_is_removed(self):
        # "Ehehe~" is real captured output and her signature laugh. The
        # tilde is a written convention, not a sound.
        self.assertEqual(self.voice.for_speech("Ehehe~ okay okay!"),
                         "Ehehe okay okay!")
        self.assertEqual(self.voice.for_speech("Woah~~~"), "Woah")

    def test_a_bare_multiplication_sign_never_reaches_piper(self):
        # normalize_actions deliberately leaves "2 * 3 * 4" alone -- the
        # version that didn't ate the middle of the sentence. So the
        # asterisks survive to here, and an asterisk is not a word.
        self.assertNotIn("*", self.voice.for_speech("it's 2 * 3 * 4 babe"))
        self.assertIn("babe", self.voice.for_speech("it's 2 * 3 * 4 babe"))

    def test_emoji_are_dropped(self):
        self.assertEqual(self.voice.for_speech("hey cutie 💅✨"), "hey cutie")

    def test_shouted_words_are_lowercased_so_piper_says_them(self):
        """MEASURED Sept 3, en_US-amy-medium, Ghost's laptop.

        The previous version of this test pinned ALL-CAPS as
        deliberately untouched, on the grounds that whether Piper reads
        capitals as initialisms was a fact nobody here had heard. Ghost
        ran the demo and heard it: "PFFT!" came back "Pee Eff Eff Tee".
        So the decision changed, on evidence, exactly as that test said
        it should.
        """
        self.assertEqual(self.voice.for_speech("PFFT! My camera!"),
                         "pfft! My camera!")
        self.assertEqual(self.voice.for_speech("MY. GOSH. SIX legs!"),
                         "my. gosh. six legs!")

    def test_real_initialisms_keep_their_capitals(self):
        """The other half, and why blanket-lowercasing would be wrong.

        "oh em gee" and "oh gee" IS how those are said. Spelling out is
        correct here and only here -- both appear in captured replies,
        and both currently sound right.
        """
        self.assertEqual(self.voice.for_speech("OMG, like, hi!"),
                         "OMG, like, hi!")
        self.assertEqual(self.voice.for_speech("My OG granddad!"),
                         "My OG granddad!")
        for word in ("OMG", "OG"):
            self.assertIn(word, self.voice.SPOKEN_INITIALISMS)

    def test_every_all_caps_word_she_has_ever_said_is_classified(self):
        """Both classes are drawn from real captured output, not
        imagined. If a new one shows up in a future round, this is the
        test that makes someone decide which kind it is."""
        for word in ("DANCE", "GOSH", "HAHA", "MY", "PFFT", "SIX", "SUPER"):
            self.assertNotIn(word, self.voice.SPOKEN_INITIALISMS,
                             f"{word} is a shouted word, not an initialism")
            self.assertEqual(self.voice.unshout(word), word.lower())
        for word in ("OMG", "OG"):
            self.assertEqual(self.voice.unshout(word), word)

    def test_single_capitals_and_normal_words_are_untouched(self):
        # "I" must not become "i", and ordinary Capitalised words are
        # not shouting.
        self.assertEqual(self.voice.for_speech("I think Paris is unreal."),
                         "I think Paris is unreal.")

    def test_nothing_to_say_stays_nothing(self):
        for empty in ("", "   ", "~", "***", "  ~~ "):
            self.assertEqual(self.voice.for_speech(empty), "")

    # --- talking to piper without piper ---------------------------

    def test_flag_detection_reads_pipers_own_help(self):
        """Piper has shipped both --output_file and --output-file.
        Guessing is an unrecognized-arguments error and silence."""
        underscore = self.voice.detect_flags(
            "  --model M  --output_file F  --length_scale L")
        self.assertEqual(underscore["output"], "--output_file")
        self.assertEqual(underscore["length"], "--length_scale")
        hyphen = self.voice.detect_flags(
            "  --model M  --output-file F  --length-scale L")
        self.assertEqual(hyphen["output"], "--output-file")
        self.assertEqual(hyphen["length"], "--length-scale")

    def test_unreadable_help_falls_back_to_a_spelling_not_a_crash(self):
        flags = self.voice.detect_flags("")
        self.assertTrue(flags["output"].startswith("--output"))
        self.assertTrue(flags["length"].startswith("--length"))

    def test_the_command_only_sets_speed_when_a_persona_asked_for_one(self):
        v = self.voice.Voice(model="/tmp/x.onnx", piper="/usr/bin/piper")
        self.assertNotIn("--length_scale", " ".join(v.command("/tmp/o.wav")))
        v.length_scale = 0.88
        argv = v.command("/tmp/o.wav")
        self.assertIn("0.88", argv)
        self.assertIn("/tmp/x.onnx", argv)

    def test_saying_something_with_nothing_installed_is_false_not_a_crash(self):
        v = self.voice.Voice(model=None, piper=None)
        v.piper, v.model = None, None       # regardless of this machine
        self.assertFalse(v.ready)
        self.assertFalse(v.say("Hey cutie!"))       # must not raise
        self.assertIn("piper", v.why_not())

    def test_piper_is_found_where_a_user_pip_install_puts_it(self):
        """pip falls back to --user whenever site-packages isn't
        writable, drops the script in ~/.local/bin, and warns about
        PATH in the middle of thirty lines of download output. Nobody
        reads that. Reporting "piper isn't installed" when it is
        sitting right there is a worse failure than looking harder."""
        import os
        import stat
        fake_bin = Path(self.dir_for_bin()) / "bin"
        fake_bin.mkdir(parents=True, exist_ok=True)
        binary = fake_bin / "piper"
        binary.write_text("#!/bin/sh\n")
        binary.chmod(binary.stat().st_mode | stat.S_IXUSR)

        with unittest.mock.patch.object(self.voice, "shutil") as shim:
            shim.which.return_value = None       # not on PATH at all
            with unittest.mock.patch.object(
                    self.voice, "EXTRA_BIN_DIRS", (fake_bin,)):
                self.assertEqual(self.voice.find_piper(), str(binary))

    def test_a_genuinely_absent_piper_still_reads_as_none(self):
        with unittest.mock.patch.object(self.voice, "shutil") as shim:
            shim.which.return_value = None
            with unittest.mock.patch.object(
                    self.voice, "EXTRA_BIN_DIRS", (Path("/nope/nowhere"),)):
                self.assertIsNone(self.voice.find_piper())

    def dir_for_bin(self):
        import tempfile
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        return holder.name

    def test_why_not_names_the_first_missing_piece(self):
        v = self.voice.Voice(model="/tmp/x.onnx", piper=None)
        v.piper = None                      # even if one was found here
        self.assertIn("pip install piper-tts", v.why_not())

    def test_a_bad_voice_override_says_both_files_are_needed(self):
        # Piper's own error when the .json is missing does not mention
        # the .json, which is a genuinely miserable half hour.
        import os
        with unittest.mock.patch.dict(
                os.environ, {self.voice.VOICE_ENV: "/nope/missing.onnx"}):
            with self.assertRaises(self.voice.VoiceError) as ctx:
                self.voice.find_voice()
        self.assertIn(".onnx.json", str(ctx.exception))

    # --- wiring into the robot ------------------------------------

    def test_the_import_is_optional_so_the_phone_still_runs(self):
        """yuzu_voice is the project's only real dependency boundary.
        If yuzu_all_in_one imports it at module level unguarded, the
        whole robot stops booting in Pydroid."""
        import ast
        tree = ast.parse((Path(__file__).parent / "yuzu_all_in_one.py")
                         .read_text())
        guarded = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Try):
                for child in ast.walk(node):
                    if isinstance(child, ast.Import):
                        guarded.update(a.name for a in child.names)
        self.assertIn("yuzu_voice", guarded,
                      "yuzu_voice must be imported inside a try/except")

    def test_speech_still_prints_when_the_voice_cannot_play(self):
        # The transcript is how you know what she said when you are
        # SSH'd in from another room.
        import io, contextlib
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            yuzu.speak("Not much, just vibing!")
        self.assertIn("Not much, just vibing!", buffer.getvalue())

    def test_every_persona_sets_its_own_speaking_speed(self):
        """piper_length_scale rode along in every persona file since
        the format was written and nothing read it until now. If one
        persona lacks it, switching to her silently keeps the previous
        character's pace."""
        for key in yuzu_personas.available():
            self.assertIn("piper_length_scale",
                          yuzu_personas.load(key).settings,
                          f"{key} has no speaking speed")

    def test_switching_persona_changes_the_speaking_speed(self):
        v = self.voice.Voice(model="/tmp/x.onnx", piper="/usr/bin/piper")
        real, yuzu.voice = yuzu.voice, v
        try:
            yuzu.apply_persona_voice(yuzu_personas.load("coco"))
            coco = v.length_scale
            yuzu.apply_persona_voice(yuzu_personas.load("yuzu4"))
            self.assertNotEqual(coco, v.length_scale)
            self.assertGreater(coco, v.length_scale,
                               "the kuudere should speak slower than the gyaru")
        finally:
            yuzu.voice = real

    def test_the_speaking_speed_is_not_sent_to_ollama(self):
        # It's a Piper setting living in the same settings block as the
        # sampling knobs. Leaking it into the model options would be a
        # 400 from Ollama on an unknown parameter.
        for key in yuzu_personas.available():
            self.assertNotIn("piper_length_scale",
                             yuzu_personas.load(key).options())

    # --- the demo has to stay honest ------------------------------

    def test_the_demo_lines_are_what_piper_would_really_receive(self):
        """The demo exists so 'how does it sound' takes 30 seconds
        instead of being guessed at. That only works if the lines are
        the real post-pipeline text."""
        for line in self.voice.DEMO_LINES:
            self.assertNotIn("[", line, "a demo line still has a bracket")
            self.assertTrue(self.voice.for_speech(line).strip())
        joined = " ".join(self.voice.DEMO_LINES)
        self.assertIn("~", joined, "no line exercises the tilde")
        caps = set(re.findall(r'\b[A-Z]{2,}\b', joined))
        self.assertTrue(caps & self.voice.SPOKEN_INITIALISMS,
                        "no line exercises a real initialism (OMG/OG)")
        self.assertTrue(caps - self.voice.SPOKEN_INITIALISMS,
                        "no line exercises a shouted word (PFFT/GOSH)")


class TestSourceHygiene(unittest.TestCase):
    """Things that are fine today and break on a newer Python.

    The Jetson ships JetPack's Python, Pydroid ships its own, and the
    laptop has whatever Ubuntu gave it. They are not the same version
    and they will not stay the same version.
    """

    def test_no_module_has_an_invalid_escape_sequence(self):
        r"""A backslash-star inside a normal (non-raw) string.

        normalize_actions' docstring quoted its own old regex,
        `re.sub(r'\*(.*?)\*', ...)`, inside a plain triple-quoted
        docstring. Python 3.11 accepts it silently. 3.12 prints a
        SyntaxWarning on every single import -- on a robot that is noise
        in front of Yuzu's dialogue, and in Pydroid it is a wall of
        yellow at someone who just tapped Run. In 3.14 it is a
        SyntaxError and nothing imports at all.
        """
        import py_compile
        import warnings
        here = Path(__file__).parent
        for path in sorted(here.glob("*.py")):
            with warnings.catch_warnings():
                warnings.simplefilter("error", SyntaxWarning)
                warnings.simplefilter("error", DeprecationWarning)
                try:
                    py_compile.compile(str(path), cfile=None, doraise=True)
                except (SyntaxWarning, DeprecationWarning,
                        py_compile.PyCompileError) as exc:
                    self.fail(f"{path.name}: {exc}")


class TestJetsonChecks(unittest.TestCase):
    """yuzu_doctor's Jetson section. It runs on the box Ghost cannot
    easily poke at from a phone, so its parsing has to be right the
    first time -- and every one of these is a plain file read, so they
    can all be tested against fixtures."""

    def setUp(self):
        import yuzu_doctor
        self.doctor = yuzu_doctor
        self.dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.dir.cleanup)

    def fake_read(self, files):
        """Patch _read_text to serve a dict of {path: contents}."""
        return unittest.mock.patch.object(
            self.doctor, "_read_text", lambda path: files.get(str(path)))

    def test_power_mode_zero_is_the_unthrottled_one(self):
        with self.fake_read({"/var/lib/nvpmodel/status":
                             "pmode:0000 fmode:fanmode_quiet\n"}):
            self.assertEqual(self.doctor.jetson_power_mode()[0], 0)

    def test_a_throttled_board_reads_nonzero(self):
        with self.fake_read({"/var/lib/nvpmodel/status":
                             "pmode:0001 fmode:fanmode_quiet\n"}):
            self.assertEqual(self.doctor.jetson_power_mode()[0], 1)

    def test_no_status_file_is_not_a_crash(self):
        # Every other machine this script runs on -- the phone, the
        # laptop, the Deck -- has no such file.
        with self.fake_read({}):
            self.assertIsNone(self.doctor.jetson_power_mode())

    def test_garbage_status_file_is_not_a_crash(self):
        with self.fake_read({"/var/lib/nvpmodel/status": "pmode:MAXN\n"}):
            self.assertIsNone(self.doctor.jetson_power_mode())

    def test_memory_picture_reads_totals_and_swap_devices(self):
        meminfo = ("MemTotal:        7629512 kB\n"
                   "MemAvailable:    5120000 kB\n"
                   "SwapTotal:       8388604 kB\n")
        swaps = ("Filename\t\t\t\tType\t\tSize\tUsed\tPriority\n"
                 "/mnt/nvme/swapfile                      file            "
                 "8388604 0       -2\n")
        with self.fake_read({"/proc/meminfo": meminfo, "/proc/swaps": swaps}):
            totals, devices = self.doctor.memory_picture()
        self.assertAlmostEqual(totals["MemTotal"], 7.276, places=2)
        self.assertEqual(devices[0][0], "/mnt/nvme/swapfile")

    def test_ollama_settings_are_read_from_the_unit_not_the_shell(self):
        """These are set for the ollama SERVICE. Reading os.environ
        would report 'not set' on a box where they are set correctly,
        which is a worse answer than not checking at all."""
        unit = ('[Service]\n'
                'Environment="OLLAMA_KEEP_ALIVE=-1"\n'
                'Environment="OLLAMA_NUM_PARALLEL=1" "OLLAMA_FLASH_ATTENTION=1"\n')
        with self.fake_read({"/etc/systemd/system/ollama.service": unit}):
            env = self.doctor.ollama_service_env()
        self.assertEqual(env["OLLAMA_KEEP_ALIVE"], "-1")
        self.assertEqual(env["OLLAMA_NUM_PARALLEL"], "1")
        self.assertEqual(env["OLLAMA_FLASH_ATTENTION"], "1")

    def test_no_ollama_unit_reads_as_none_not_as_empty(self):
        # None means "couldn't look"; {} would mean "looked, nothing
        # set", and reporting five missing settings on a box with no
        # Ollama installed is just noise.
        with self.fake_read({}):
            self.assertIsNone(self.doctor.ollama_service_env())

    def test_the_whole_section_is_skipped_off_a_jetson(self):
        before = len(self.doctor.notes)
        with unittest.mock.patch.object(self.doctor, "on_a_jetson",
                                        lambda: False):
            self.doctor.check_jetson()
        self.assertEqual(len(self.doctor.notes), before,
                         "check_jetson must be silent on the phone")

    def test_every_tuning_setting_says_why(self):
        # A checklist of env vars with no reasoning is a cargo cult.
        for name, (want, why) in self.doctor.OLLAMA_TUNING.items():
            self.assertTrue(want, f"{name} has no recommended value")
            self.assertGreater(len(why), 40,
                               f"{name} doesn't explain itself")


if __name__ == "__main__":
    unittest.main(verbosity=2)
