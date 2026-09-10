"""
Yuzu's test suite. Plain stdlib unittest -- no pip installs, so it runs
in Pydroid on the phone exactly like it runs on the Jetson:

    python YUZU_TESTER.py

Every test here is a real bug that was found by running the code, or a
behaviour worth locking down so a future edit can't quietly break it.
"""

import json
import inspect
import unittest
import unittest.mock
from unittest import mock
from pathlib import Path

import itertools
import os
import re
import shutil
import struct
import sys
import tempfile
import textwrap
import threading
import time
from collections import Counter
from http.server import BaseHTTPRequestHandler, HTTPServer

import muto_leg_control as legs
import yuzu_all_in_one as yuzu
import drop
import gguf_inspect
import yuzu_brain
import yuzu_personas
import yuzu_wiki
import yuzu_prompt_eval as prompt_eval
import yuzu_brain as yuzu_brain_module
from yuzu_brain import BrainError, YuzuBrain, load_system_prompt


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
        # By the LIVE persona's OWN name -- this asserted "You are Yuzu"
        # until Shiro took the slot, which would have made moving the
        # main character look like a broken build.
        self.assertIn(f"You are {yuzu_personas.load(live).name}",
                      yuzu_personas.load(live).prompt)
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
        self.assertIn(f"You are {brain.persona.name}", messages[0]["content"])

    def test_sampling_options_are_sent(self):
        """SIXTH instance of the name-leak class, caught by promoting
        Saya: this asserted `temperature == 0.8`, which was Shiro's
        number, not a property of the brain. Saya runs 0.85 and the
        test went red on a change that broke nothing.

        What the test is FOR is that the persona's sampling settings
        reach the request at all. So read the number off the persona
        instead of pinning it, and the next promotion is quiet."""
        brain = self.brain()
        brain.ask("hey")
        options = MockOllama.seen["last"]["options"]
        self.assertEqual(options["temperature"],
                         brain.persona.settings["temperature"])
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
        self.assertIn(f"You are {brain.persona.name}", brain.system_prompt)

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
        """REGRESSION: v1 carried an explicit anti-asterisk rule and its
        live output was all brackets. The first v2 draft dropped that
        rule while simplifying, and asterisks came straight back.

        SCOPED TO BODIES THAT MOVE, Sept 8. The regression this guards
        is "*spins* did not reach the whitelist, so the robot stood
        still" -- it needs a robot to be a regression at all. On the
        cyberdeck an asterisk costs a word Piper would have read aloud,
        and strip_stage_directions removes it in code every turn,
        whatever wrapper she reaches for. Ghost's call on the prompt
        rule: "im fine if she Rps a bit its all readble".
        """
        for key in yuzu_personas.available():
            persona = yuzu_personas.load(key)
            if not persona.moves:
                continue
            self.assertIn("asterisk", persona.prompt.lower(),
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
            persona = yuzu_personas.load(key)
            if not persona.built:
                continue        # no controller exists to check against
            prompt = persona.prompt
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

    # Of the nine, these three only mean anything on a body that moves:
    # they are phrased in brackets, in movement, and in a walk command.
    # A cyberdeck persona is not missing them, it has no use for them --
    # requiring them would put an action menu back into a character who
    # drives nothing, which is the exact failure _hardware_cyberdeck.txt
    # exists to prevent.
    # The brevity win is a CAP ON SENTENCES, not one literal phrase.
    # Coco says "One or two calm sentences", Byte "Keep it tight. One or
    # two sentences", Yuzu "two or three sentences". All three ARE the
    # brevity rule in their own register, and CLAUDE.md already records
    # one false positive from matching this one literally.
    BREVITY_WIN = "brevity rule, 62w -> 38w"
    BREVITY_RE = re.compile(r"(one or two|two or three)\s+\w*\s*sentences?",
                            re.I)

    BODY_PROTOCOL_WINS = {
        "always-speak rule, fixed the freeze",
        "always-move rule, 50% -> 100% moves_at_all",
        "bare-command example, 4/4 moved",
        # ADDED Sept 8. Both of these are about the BRACKET PROTOCOL,
        # and the regression each one guards against is "the action did
        # not run" -- impossible on a body with no actions. Ghost, on
        # the deck: "do brackets/asterisks stuff even matter now that
        # shes a cyberdeck ai? like im fine if she Rps a bit."
        #
        # On the hexapod an asterisk meant a servo stayed still, so the
        # rule earned its place. On the deck it means a word Piper would
        # have said out loud -- which strip_stage_directions removes in
        # code, every turn, whatever wrapper she reaches for. Five of
        # the nine measured wins turn out to be protocol, not character.
        "anti-asterisk rule, removing it regressed",
        "sounds rule names BOTH wrappers",
    }

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
        # ISOLATE `notes` TOO, not just the detector. It is a module
        # level list every check appends to, and summary() prints all of
        # it -- so whatever ran earlier in the suite leaks into this
        # render. Off a Jetson check_jetson() adds nothing and the leak
        # is invisible; ON one it appends "Run: sudo nvpmodel -m 0",
        # which made test_the_doctor_stays_quiet_on_a_phone fail the
        # first time this suite was ever run on Ghost's Orin. The test
        # was right and the harness was dirty.
        saved_notes = list(yuzu_doctor.notes)
        yuzu_doctor.notes.clear()
        yuzu_doctor.on_a_jetson = lambda: on_jetson
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                yuzu_doctor.summary({})
        finally:
            yuzu_doctor.on_a_jetson = real
            yuzu_doctor.notes[:] = saved_notes
        return buffer.getvalue()

    def test_the_doctor_prints_it_on_a_jetson(self):
        output = self.render_summary(True)
        self.assertIn("nvpmodel -m 0", output)
        self.assertIn("jetson_clocks", output)
        self.assertIn("THROTTLED", output)

    def test_the_doctor_stays_quiet_on_a_phone(self):
        self.assertNotIn("nvpmodel", self.render_summary(False))

    def test_the_two_copies_of_the_jetson_check_agree(self):
        """RENAMED AND FIXED -- it asserted both detectors return False,
        which is only true OFF a Jetson. The suite had never been run on
        the actual target hardware; the first time it was (Ghost's Orin,
        Sept 8) it came back "Ran 298 tests... FAILED (failures=2)", and
        this was one of them. The assertion was stronger than the name.

        What the duplication actually needs guarding is AGREEMENT.
        yuzu_doctor.on_a_jetson and yuzu_all_in_one._on_a_jetson are two
        copies of one check, kept separate on purpose because the doctor
        has to run as a lone download that imports nothing from this
        project. Two copies can drift -- and if they do, the doctor
        prints the throttle reminder while the robot's boot line stays
        silent, or the reverse. That is the bug worth catching, and
        unlike "always False" it is meaningful on every machine.
        """
        import yuzu_doctor
        doctor = yuzu_doctor.on_a_jetson()
        robot = yuzu.__dict__["_on_a_jetson"]()
        self.assertIsInstance(doctor, bool)
        self.assertIsInstance(robot, bool)
        self.assertEqual(doctor, robot,
                         "the two copies of the Jetson check disagree -- "
                         "the reminder would appear in one place only")

    def test_detection_answers_both_ways_and_never_raises(self):
        """The behaviour the old name claimed to test, actually tested:
        both copies say True when the marker is there, False when it is
        not, and neither raises when the paths are absent (the phone
        case the try/except exists for). Driven by faking the
        filesystem, so it gives the same answer on a laptop, a phone and
        an Orin."""
        import yuzu_doctor
        robot_check = yuzu.__dict__["_on_a_jetson"]
        for present in (True, False):
            with unittest.mock.patch.object(yuzu_doctor, "Path") as fake:
                fake.return_value.exists.return_value = present
                self.assertIs(yuzu_doctor.on_a_jetson(), present)
            with unittest.mock.patch("os.path.exists", return_value=present):
                self.assertIs(robot_check(), present)

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

    # Checks that ask "did it move?". Meaningless for a body with no
    # movements -- see Persona.moves. Named rather than detected so
    # adding a check makes someone decide which kind it is.
    MOVEMENT_CHECKS = ("moves_at_all", "actions_runnable", "one_per_bracket")

    def test_every_example_passes_every_compliance_check(self):
        for key in yuzu_personas.available():
            persona = yuzu_personas.load(key)
            for reply in self.example_replies(persona):
                for check in prompt_eval.CHECKS:
                    if (not (persona.moves and persona.built)
                            and check.name in self.MOVEMENT_CHECKS):
                        continue
                    self.assertTrue(
                        check.fn(reply),
                        f"{key} example fails {check.name} "
                        f"({check.rule}): {reply!r}")

    def test_no_example_demonstrates_an_action_the_robot_drops(self):
        for key in yuzu_personas.available():
            persona = yuzu_personas.load(key)
            if not persona.built:
                continue        # nothing wired up to drop it yet
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
        """THE WART IS FIXED. This test used to assert it.

        It read: "KNOWN WART... {HARDWARE_MENU} illustrates 'sounds are
        speech' with Yuzu's voice, and it lands in every persona that
        composes the menu in. Editing the shared file would change
        yuzu2's composed prompt mid-A/B, so instead Coco's EXAMPLES
        carry her own register."

        That objection was real and is now satisfied. The examples moved
        behind a {SOUND_EXAMPLES} token whose DEFAULT is Yuzu's exact
        list, so every yuzu prompt is byte-identical and no A/B moved.
        Coco supplies her own, so she is no longer handed "Ehehe~" by a
        file about legs.
        """
        self.assertNotIn("Ehehe~", self.prompt,
                         "Coco is still being handed the gyaru's sounds")
        self.assertIn("Ah, Oh, Huh", self.prompt)
        examples = self.prompt.split("EXAMPLES")[1]
        self.assertIn("Hm.", examples)                # a sound, typed inline
        self.assertEqual(yuzu.lookup_actions("Hm"), [],
                         "a sound must never resolve to a movement")

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

    def test_coco_has_it_now_that_her_hold_is_lifted(self):
        """Coco was deliberately held back while Yuzu iterated, so one
        character's round could not contaminate another's. Ghost lifted
        that hold on Sept 3 ("im ready for coco").

        The composing-by-name property this used to guard still holds
        and is still worth having -- a block reaches only the personas
        that reference its token. What changed is that Coco now
        references it on purpose.
        """
        blocks = yuzu_personas._parse_hardware("muto_s2")
        self.assertIn("MOVEMENT_RULE_V2", blocks)
        for key in ("yuzu2", "coco"):
            self.assertIn(blocks["MOVEMENT_RULE_V2"],
                          yuzu_personas.load(key).prompt,
                          f"{key} lost the 50%-to-100% movement rule")
        # The frozen v1 archive composes a different block set and must
        # NOT pick it up -- that is the property still being guarded.
        self.assertNotIn(blocks["MOVEMENT_RULE_V2"],
                         yuzu_personas.load("yuzu").prompt)

    def test_a_persona_can_override_a_shared_block(self):
        """The fix for character bleed, at the root.

        The shared file is for SERVO FACTS -- CLAUDE.md has said so
        since a character stance in there collared every persona at once
        ("your whole world is the room you're standing in"). But the
        sounds rule still shipped Yuzu's own examples to everybody, so a
        kuudere and a netrunner were handed a gyaru's vocabulary by a
        file about legs. Coco produced "Ehehe~" in her first live
        conversation.

        An ALL_CAPS setting above the '---' now overrides the block of
        that name. The RULE stays shared; the EXAMPLES come from the
        character.
        """
        blocks = yuzu_personas._parse_hardware("muto_s2")
        self.assertIn("SOUND_EXAMPLES", blocks,
                      "the shared file lost its default sounds block")
        for key in ("coco", "byte"):
            self.assertIn("SOUND_EXAMPLES",
                          yuzu_personas.load(key).settings,
                          f"{key} stopped supplying her own sounds")

    def test_the_default_sounds_are_still_yuzus_exact_list(self):
        """The whole point of a DEFAULT is that the lineage did not
        move. If this changes, every archived comparison shifts and the
        measured numbers stop describing the prompts on disk."""
        blocks = yuzu_personas._parse_hardware("muto_s2")
        self.assertEqual(blocks["SOUND_EXAMPLES"], "Ehehe~, Haha!, Ugh, Ooh")
        for key in ("yuzu2", "yuzu3", "yuzu4", "yuzu5", "yuzu6"):
            self.assertIn("Ehehe~, Haha!, Ugh, Ooh",
                          yuzu_personas.load(key).prompt,
                          f"{key}'s composed prompt drifted")

    def test_no_character_is_taught_another_characters_sounds(self):
        """What the SHARED BODY FILE hands her, not what she says.

        NARROWED, and the narrowing is the point. This used to scan the
        whole composed prompt, which conflated two different things:
        the sounds block a file about legs HANDS a character (bleed,
        the real bug -- Coco produced [Ehehe~] live because of it), and
        the words a character says in her OWN authored examples
        (character, the author's call).

        Shiro is why. She was written on the board before the override
        existed, so she really was handed 'Ehehe~, Haha!, Ugh, Ooh' --
        a gyaru's vocabulary given to a yami kawaii by the servo file.
        That is caught here. But her own line "...not that I'd ever
        need to. Ehehe." is a soft creepy giggle she was deliberately
        written with and tested on, and failing her for it is the same
        literal-needle false positive this project already recorded
        once against Coco's brevity rule.

        Authored register has its own guard -- see the '!'/'cutie'/
        'bestie' check on Coco's example.
        """
        gyaru = ("ehehe", "haha", "ooh")
        gyaru_name = yuzu_personas.load("yuzu4").name   # hers, not live's
        for key in yuzu_personas.available():
            persona = yuzu_personas.load(key)
            if persona.name == gyaru_name:
                continue
            handed = persona.blocks.get("SOUND_EXAMPLES", "").lower()
            for token in gyaru:
                self.assertNotIn(token, handed,
                                 f"{key} is still handed '{token}' by the "
                                 f"shared body file")

    def test_every_taught_sound_survives_tts(self):
        """A sound the voice drops is worse than no example: it teaches
        her to say something nobody hears. "pfft" was exactly that."""
        import yuzu_voice
        for key in yuzu_personas.available():
            prompt = yuzu_personas.load(key).prompt
            lines = [l for l in prompt.splitlines()
                     if "come out of your speaker" in l]
            if not lines:
                continue                      # v1 body block has no rule
            listed = lines[0].split("around them: ")[1]
            listed = listed.split(". Brackets")[0].rstrip(".")
            for sound in (x.strip() for x in listed.split(",")):
                self.assertTrue(
                    yuzu_voice.for_speech(sound).strip(),
                    f"{key} teaches '{sound}', which the voice drops")

    def test_every_character_carries_the_measured_wins(self):
        """Generalised from the Coco-only version.

        A CHARACTER (Coco, Byte, anyone added later) must carry every
        win the live arm has. The yuzu2/3/5/6 archives are exempt --
        they are the record of what was tried and yuzu2 lacks the
        bare-command example by definition.

        Coco drifted two wins behind while Yuzu had three more rounds,
        and nobody noticed until it was checked mechanically. This makes
        the next character impossible to forget: it derives the list
        from TestYuzu5.MEASURED_WINS and the set of characters from the
        persona files themselves.
        """
        live_persona = yuzu_personas.load(yuzu_personas.LIVE_PERSONA)
        live = live_persona.prompt
        # SCOPED TO THE LIVE BODY. It used to be "everyone whose name
        # differs from the live arm's", which silently assumed the live
        # arm was Yuzu and every other persona was a peer. Once the
        # cyberdeck became the build that broke twice over: the
        # yuzu2..yuzu6 lineage archives became "characters" and would
        # have been held to wins yuzu2 lacks by definition, and Saya's
        # quadruped -- a retired plan on a body with no controller --
        # was being asked to carry them too.
        #
        # A win is measured ON a body. Personas on a retired chassis are
        # records, exactly like the yuzu lineage; what has to keep up is
        # every character standing on the body that actually boots.
        characters = [k for k in yuzu_personas.available()
                      if k != yuzu_personas.LIVE_PERSONA
                      and yuzu_personas.load(k).hardware
                      == live_persona.hardware]
        self.assertTrue(characters, "no peer characters on the live body")
        for key in characters:
            persona = yuzu_personas.load(key)
            for name, needle in TestYuzu5.MEASURED_WINS.items():
                if needle not in live:
                    continue
                if (not persona.moves
                        and name in TestYuzu5.BODY_PROTOCOL_WINS):
                    continue
                if name == TestYuzu5.BREVITY_WIN:
                    self.assertTrue(
                        TestYuzu5.BREVITY_RE.search(persona.prompt),
                        f"{key} caps no sentence count: {name}")
                    continue
                self.assertIn(needle, persona.prompt, f"{key} lacks: {name}")

    def test_each_character_speaks_in_her_own_register(self):
        """The bare-command example is a measured SHAPE, but the voice
        has to be the character's. Teaching Yuzu's register to anyone
        else is the drift that makes persona switching clear history."""
        gyaru = ("cutie", "bestie", "omg", "hype", "sparkl", "uwu")
        # Pinned to Yuzu, NOT to whoever is live. These words are HERS,
        # and they stay hers after the main character changes -- keying
        # this on LIVE_PERSONA made the whole yuzu lineage read as
        # "other characters" the moment Shiro took the slot.
        gyaru_name = yuzu_personas.load("yuzu4").name
        for key in yuzu_personas.available():
            persona = yuzu_personas.load(key)
            if persona.name == gyaru_name:
                continue
            # Only her OWN text -- the shared body block is a separate,
            # known issue and is not this test's business.
            own = persona.path.read_text(encoding="utf-8").lower()
            for word in gyaru:
                self.assertNotIn(word, own,
                                 f"{key} uses '{word}', which is Yuzu's voice")

    def test_coco_carries_every_measured_win_the_live_persona_has(self):
        """Parity, checked mechanically instead of remembered.

        Coco was built on v2's structure and then Yuzu got three more
        rounds of measured fixes. She had drifted two behind: the
        always-MOVE rule (50% -> 100% on moves_at_all, the single
        biggest win in the project) and the bare-command example (4/4
        replies moved). Both were format rules, not character, so there
        was never a reason for her not to have them.

        Reuses TestYuzu5.MEASURED_WINS so a win added there is
        automatically required of her too.
        """
        coco = yuzu_personas.load("coco").prompt
        # yuzu4, not LIVE_PERSONA. Robot Coco is a record of the hexapod
        # era and yuzu4 is the arm she was built to keep up with; once
        # the deck took over, comparing her against a bodiless live arm
        # compared two different bodies. Deck parity is enforced by
        # test_every_character_carries_the_measured_wins.
        live = yuzu_personas.load("yuzu4").prompt
        for name, needle in TestYuzu5.MEASURED_WINS.items():
            if needle not in live:
                continue                      # not a win the live arm has
            if needle == "User: Walk forward.":
                self.assertIn(needle, coco, f"coco lacks: {name}")
                continue
            self.assertIn(needle, coco, f"coco lacks: {name}")

    def test_cocos_bare_command_example_is_in_her_own_register(self):
        """The SHAPE is what was measured -- a flat imperative. The
        voice has to be hers, or the example teaches Yuzu's register to
        a kuudere, which is the drift that made persona switching clear
        history in the first place."""
        coco = yuzu_personas.load("coco").prompt
        line = [l for l in coco.splitlines() if l.startswith("Coco: Walking")][0]
        self.assertEqual(yuzu.extract_actions(line), ["walks forward"])
        self.assertTrue(yuzu.lookup_actions("walks forward"))
        for gyaru in ("!", "cutie", "bestie", "omg", "hype"):
            self.assertNotIn(gyaru, line.lower(),
                             f"'{gyaru}' is Yuzu's voice, not Coco's")

    def test_every_example_in_every_persona_actually_moves(self):
        """If an example can sit still, the strongest signal in the
        prompt says sitting still is fine.

        Bodies that MOVE only. A bodiless persona (the cyberdeck) is
        held to the opposite rule below -- not a weaker one.
        """
        for key in yuzu_personas.available():
            persona = yuzu_personas.load(key)
            if not (persona.moves and persona.built):
                continue
            for reply in re.findall(rf'^{re.escape(persona.name)}:\s*(\S.*)$',
                                    persona.prompt, re.M):
                self.assertTrue(prompt_eval.moves_at_all(reply),
                                f"{key} example never moves: {reply!r}")

    def test_a_bodiless_persona_never_demonstrates_moving(self):
        """The inverse guarantee, and it is STRICTER than the one above.

        On the deck every bracket is dead weight: nothing runs it, the
        parser strips it, and it costs generated tokens on every turn.
        One example carrying a stray bracket teaches the whole habit --
        this repo has measured examples beating rules twice. So a body
        that declares [MOVES] no must show none, anywhere.
        """
        bodiless = [k for k in yuzu_personas.available()
                    if not yuzu_personas.load(k).moves]
        self.assertTrue(bodiless, "no bodiless persona to check")
        for key in bodiless:
            persona = yuzu_personas.load(key)
            for reply in re.findall(rf'^{re.escape(persona.name)}:\s*(\S.*)$',
                                    persona.prompt, re.M):
                self.assertEqual(
                    yuzu.extract_actions(yuzu.normalize_actions(reply)), [],
                    f"{key} has no body, but an example acts: {reply!r}")


class TestBootBanner(unittest.TestCase):
    """Two personas can share a NAME. The banner has to disambiguate."""

    def test_the_banner_names_the_key_when_it_differs_from_the_name(self):
        """MEASURED THE HARD WAY, Sept 9. `shiro` (retired hexapod) and
        `shiro_deck` (live) both printed "persona: Shiro". Ghost ran the
        first by hand, got [walks backward] and [shakes legs], and asked
        whether it was character bleed -- a completely fair reading,
        because nothing on screen said which of the two he had.

        Fifth instance of the name-vs-identity class this file keeps
        tripping over. The name is not the identity; the KEY is.
        """
        shiro = yuzu_personas.load("shiro")
        deck = yuzu_personas.load("shiro_deck")
        self.assertEqual(shiro.name, deck.name)     # the whole problem
        self.assertNotEqual(shiro.key, deck.key)

        import inspect
        body = inspect.getsource(yuzu_brain._cli)
        self.assertIn("brain.persona.key", body,
                      "the boot banner does not print the key, so two "
                      "personas sharing a name are indistinguishable")
        self.assertIn("no body", body,
                      "the banner should say when the body cannot move")
        self.assertIn("persona: {banner}", body,
                      "the boot banner no longer prints the disambiguated "
                      "label, so shiro and shiro_deck look identical again")

    def test_the_REPLY_prefix_is_only_her_name(self):
        """Ghost, Sept 9: "plz plz for my sanitys sake make her name
        just Saya lol."

        Right. Every reply was prefixed `Saya (saya_deck) [no body]:` --
        that is a database row talking, not a character. The banner
        needs the key because two personas share a name; a nametag in a
        conversation does not. One variable was doing both jobs."""
        import inspect
        body = inspect.getsource(yuzu_brain._cli)
        self.assertIn('who = brain.persona.name', body)
        # the reply prefix must use the plain name, never the banner
        for line in body.splitlines():
            if 'print(f"{' in line and '}: "' in line:
                self.assertIn("{who}", line, line.strip())
                self.assertNotIn("{banner}", line, line.strip())


class TestShiroDeck(unittest.TestCase):
    """The live arm. Findings here come from Ghost's first real deck
    conversation, Sept 8 -- four replies, on the Orin, through Ollama."""

    def prompt(self):
        return yuzu_personas.load("shiro_deck").prompt

    def test_she_is_not_taught_the_words_she_must_not_say(self):
        """MEASURED, and it is the pink elephant for the third time.

        Rule 5 read: never undercut it: no "jk," no disclaimer, no
        walking it back. Her very FIRST live reply was:

            Hii! *whispers* You didn't even notice my warning: "no
            jk"s and "disclaimers" are not allowed here...

        She recited the rule back at Ghost, quoting its own tokens. The
        repo has now measured this three times -- [winks] named as
        forbidden turning up in 3 of 4 replies, the asterisk ban that
        demonstrated an asterisk, and this. Naming the thing she must
        not say is how she learns to say it.

        The rule still forbids undercutting. It just describes the
        behaviour ("let it stand exactly as you said it") instead of
        listing the words, which is the same rewrite Byte's rule 5 got
        when it said "No hype" in Yuzu's own vocabulary.
        """
        prompt = self.prompt()
        for token in ('"jk', "disclaimer", "walking it back"):
            self.assertNotIn(token, prompt,
                             f"shiro_deck still quotes {token!r} -- she "
                             f"read that back to Ghost verbatim")
        # The rule itself must survive the rewrite; this is character,
        # not formatting, and dropping it would flatten her.
        self.assertIn("dark half", prompt)

    def test_her_examples_never_show_a_stage_direction(self):
        """3 of her first 4 live replies carried one (*whispers*,
        *silence*, *giggle*) despite being told not to and never being
        shown one. Examples beat rules in this repo, so the examples at
        least must stay clean -- and yuzu_voice.strip_stage_directions
        is the guarantee behind the reduction, because without it those
        reach Piper as the bare words "whispers", "silence", "giggle".
        """
        for line in self.prompt().splitlines():
            if line.startswith("Shiro:"):
                self.assertNotIn("*", line)
                self.assertNotIn("[", line)


class TestPadPairing(unittest.TestCase):
    """`pad` -- pairing the 8BitDo without fighting bluetoothctl.

    bluetoothctl is a REPL: type `scan on`, wait, read a wall of MAC
    addresses, type `pair <mac>`. That is a bad time on a phone keyboard
    over a serial link, and every step of it is scriptable."""

    SCRIPT = Path(__file__).parent / "pad"

    def _run(self, *args, devices="", info="", inputs=""):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            binv = Path(tmp) / "bin"
            binv.mkdir()
            bt = binv / "bluetoothctl"
            bt.write_text("#!/bin/bash\ncase \"$1\" in\n"
                          f"  devices) printf '%s\\n' {devices!r} ;;\n"
                          f"  info)    printf '%s\\n' {info!r} ;;\n"
                          "  *) exit 0 ;;\nesac\n")
            bt.chmod(0o755)
            # Drive the "is a gamepad present" check from a fixture
            # rather than from whatever this machine has plugged in --
            # a test that only passes on the machine it was written on
            # is not passing, it is untested.
            fake_inputs = Path(tmp) / "inputs"
            fake_inputs.write_text(inputs)
            env = dict(os.environ, PATH=f"{binv}:{os.environ['PATH']}",
                       PAD_INPUTS=str(fake_inputs))
            return subprocess.run(["bash", str(self.SCRIPT), *args],
                                  capture_output=True, text=True,
                                  env=env, input="\n", timeout=60)

    WIRED = 'N: Name="8BitDo 8BitDo Micro gamepad"\n'

    def test_status_leads_with_the_verdict_not_the_bluetooth_noise(self):
        """MEASURED Sept 9. A WORKING wired pad printed:

            Bluetooth:  NOT connected
            Bonded:     NO -- BlueZ will refuse the gamepad
            Gamepad:    visible to games

        Two alarming lines about a transport that is not in use, and
        the one line that decides everything last. Ghost read it as
        broken. It was working.

        Same fault as every bug this evening -- reporting the layers
        AROUND the answer -- except this time in my own output."""
        done = self._run("--status", inputs=self.WIRED,
                         devices=self.PAIRED,
                         info="\tConnected: no\n\tBonded: no")
        self.assertEqual(done.returncode, 0)
        first = [ln for ln in done.stdout.splitlines() if ln.strip()][0]
        self.assertIn("WORKING", first,
                      f"the first line is not the verdict: {first!r}")
        self.assertLess(done.stdout.index("WORKING"),
                        done.stdout.index("Bluetooth"),
                        "bluetooth noise still comes before the verdict")

    def test_it_says_to_RESTART_mgba_not_to_press_Refresh(self):
        """MEASURED Sept 9. The pad appeared at 17:38; mGBA had been
        running since 17:20. Its controller dropdown stayed empty and
        every mapping box refused input, so it read as a broken UI.

        SDL enumerates controllers at STARTUP. mGBA's Refresh button is
        unreliable for hotplug, and telling him to press it sent him
        clicking at a screen that could not work."""
        for kwargs in ({"inputs": self.WIRED},                    # --status
                       {"inputs": self.WIRED, "args": True}):     # pair flow
            args = ("--status",) if "args" not in kwargs else ()
            done = self._run(*args, inputs=self.WIRED)
            self.assertIn("gba --off", done.stdout,
                          "it does not tell him to restart mGBA, so a "
                          "pad plugged in later is invisible to the game")
            self.assertNotIn("press Refresh, then Set all", done.stdout)

    def test_a_missing_pad_says_what_to_DO_about_it(self):
        """A verdict with no next step just relocates the problem."""
        done = self._run("--status", inputs="", devices="", info="")
        self.assertEqual(done.returncode, 1)
        self.assertIn("NOT AVAILABLE", done.stdout)
        self.assertIn("USB-A", done.stdout)
        self.assertIn("wake", done.stdout.lower(),
                      "a sleeping pad only charges, and that is the "
                      "single most likely cause -- say so")

    PAIRED = "Device E4:17:D8:12:34:56 8BitDo Micro gamepad"

    def test_it_is_valid_shell(self):
        import subprocess
        done = subprocess.run(["bash", "-n", str(self.SCRIPT)],
                              capture_output=True)
        self.assertEqual(done.returncode, 0, done.stderr.decode())

    def test_status_is_honest_when_there_is_no_controller_at_all(self):
        done = self._run("--status")
        self.assertEqual(done.returncode, 1)
        self.assertIn("not available", done.stdout.lower(), done.stdout)

    def test_it_checks_for_a_GAMEPAD_not_just_a_bluetooth_link(self):
        """The failure this exists to catch: a pad linked at the
        Bluetooth layer that exposes no input device. bluetoothctl says
        `Connected: yes` and mGBA still sees nothing -- identical to
        working from every angle bluetoothctl can see.

        Same shape as the TigerVNC loopback bug an hour earlier: the
        obvious check was true the whole time it was broken."""
        body = self.SCRIPT.read_text()
        self.assertIn("/proc/bus/input/devices", body,
                      "nothing verifies a real gamepad appeared, so a "
                      "half-connected pad reports success")
        done = self._run("--status", inputs="", devices=self.PAIRED,
                         info="\tConnected: yes")
        self.assertIn("NOT AVAILABLE", done.stdout)

    def test_pairing_happens_in_ONE_session_so_the_bond_completes(self):
        """MEASURED, Sept 9, and it was the actual bug. The first
        version ran `bluetoothctl pair`, `trust` and `connect` as three
        separate commands. Each starts an agent and EXITS, so the agent
        dies before bonding finishes:

            Paired: yes
            Bonded: no
            hidp_add_connection() Rejected connection from !bonded device

        BlueZ then logged `input-hid Success (0)` on the very
        connection it had just rejected, so every layer above reported
        a working controller and no gamepad ever appeared.

        Piping the sequence keeps one session, and its agent, alive."""
        body = self.SCRIPT.read_text()
        self.assertNotIn("bluetoothctl pair ", body,
                         "pairing as a one-shot command lets the agent die "
                         "before the bond completes")
        self.assertIn("bluetoothctl >", body,
                      "pairing is not driven through a single session")
        self.assertIn("default-agent", body)

    def test_it_reports_BONDED_not_just_connected(self):
        """`Connected: yes` is true while the gamepad is being refused.
        Bonding is the only thing that tells the truth, so a pad that
        is NOT working has to say so or it repeats the lie that cost
        this evening."""
        done = self._run("--status", inputs="", devices=self.PAIRED,
                         info="\tConnected: yes\n\tBonded: no")
        self.assertIn("NOT BONDED", done.stdout)

    def test_a_wired_pad_short_circuits_the_whole_bluetooth_dance(self):
        """MEASURED Sept 9, after an hour of bonding failures: plugged
        into a USB-A port the pad appeared instantly as
        `8BitDo 8BitDo Micro gamepad` -- no pairing, no bonding, no
        agent, nothing to debug.

        So a connected pad must never be sent through pairing again.
        The cable is not a workaround; the deck has USB ports."""
        body = self.SCRIPT.read_text()
        self.assertIn("USB-A", body,
                      "it does not tell him the cable is the easy path")
        # the wired check must come BEFORE the pairing prompt, or he is
        # asked to hold buttons on a pad that already works
        self.assertLess(body.index("ALREADY connected (USB)"),
                        body.index("pairing mode"),
                        "it prompts for pairing before noticing the pad "
                        "is already plugged in and working")

    def test_it_no_longer_asserts_button_combos_it_cannot_verify(self):
        """Ghost, with the pad in his hand: "ur button combls dont
        matcj how it seems to work". They were the generic 8BitDo
        convention, stated as instructions, and they were wrong for
        this pad -- which sent him hunting for buttons that are not
        there while the real fault was bonding.

        He can see the pad. Describe the STATE to reach (light
        flashing), not the keys to press."""
        body = self.SCRIPT.read_text()
        self.assertNotIn("START + A", body)
        self.assertIn("FLASH", body.upper())

    def test_it_trusts_the_pad_so_it_reconnects_by_itself(self):
        """Without `trust`, it needs re-pairing after every power-off --
        which on a deck means every time he closes the lid."""
        self.assertIn("trust $MAC", self.SCRIPT.read_text())

    def test_a_failed_search_lists_what_it_COULD_see(self):
        """Dead ends are where he gets stuck. Printing the visible
        devices turns "it didn't work" into "the pad isn't in pairing
        mode", which he can act on alone."""
        done = self._run(devices="Device AA:BB:CC:DD:EE:FF Headphones")
        self.assertEqual(done.returncode, 1)
        self.assertIn("Headphones", done.stdout)
        self.assertIn("FLASHING", done.stdout)

    def test_there_is_a_way_to_start_over(self):
        """A half-pairing that will not connect is the common bad state
        and it cannot be fixed by trying harder."""
        self.assertIn("--forget", self.SCRIPT.read_text())
        done = self._run("--forget")
        self.assertEqual(done.returncode, 0)


class TestDeckApps(unittest.TestCase):
    """`deckapps` -- real app icons, because a touchscreen is not a
    terminal.

    Ghost, Sept 9: "as far as the https blah blah number number in a
    browser can we please go an 'app' route for when i have the monitor
    touch screen... like a ui that opens when i click an app."

    Typing 192.168.4.136:8080 is fine over a serial link and absurd on
    a 7" panel you are holding. A .desktop file IS what an app is on
    Linux."""

    SCRIPT = Path(__file__).parent / "deckapps"

    def _run(self, *args, have=()):
        """Install into a fake HOME with only `have` on PATH, so both
        'everything present' and 'nothing installed' are driven from
        fixtures rather than from whatever this machine has."""
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            home, binv = tmp / "home", tmp / "bin"
            (home / "YUZU").mkdir(parents=True)
            binv.mkdir()
            for tool in ("bash", "mkdir", "cat", "chmod", "cp", "rm",
                         "ls", "grep", "sleep"):
                found = shutil.which(tool)
                if found:
                    (binv / tool).symlink_to(found)
            for fake in have:
                stub = binv / fake
                stub.write_text("#!/bin/bash\nexit 0\n")
                stub.chmod(0o755)
            done = subprocess.run(
                [str(binv / "bash"), str(self.SCRIPT), *args],
                capture_output=True, text=True, timeout=60,
                env={"HOME": str(home), "PATH": str(binv)})
            # Read INSIDE the with-block: the tempdir is gone the
            # moment it exits, and an earlier version of this test
            # checked paths that no longer existed.
            apps = home / ".local/share/applications"
            names = sorted(p.name for p in apps.glob("*.desktop")) \
                if apps.exists() else []
            on_desktop = sorted(p.name for p in (home / "Desktop")
                                .glob("*.desktop")) \
                if (home / "Desktop").exists() else []
            # Beside the SCRIPT, not under $HOME/YUZU. deckapps used to
            # hardcode that path, which is exactly the bug that made it
            # install icons pointing at wrappers it never wrote.
            wrapper_path = self.SCRIPT.parent / ".wiki-app"
            wrapper = wrapper_path.read_text() if wrapper_path.exists() else None
            # deckapps writes its wrappers beside itself, which is the
            # repo when the suite runs it. Leaving them behind is test
            # pollution and it made one run go red on its own droppings.
            for junk in (".wiki-app", ".face-app"):
                (self.SCRIPT.parent / junk).unlink(missing_ok=True)
            return done, names, on_desktop, wrapper

    def test_it_is_valid_shell(self):
        import subprocess
        done = subprocess.run(["bash", "-n", str(self.SCRIPT)],
                              capture_output=True)
        self.assertEqual(done.returncode, 0, done.stderr.decode())

    def test_it_installs_every_app_when_the_desktop_has_what_it_needs(self):
        """Five now: her FACE and the HOME screen joined the original
        three when Ghost asked for "a desktop with my apps and a saya
        button visible"."""
        done, names, on_desktop, _ = self._run(have=("chromium", "xterm"))
        self.assertEqual(names, ["yuzu-face.desktop", "yuzu-gba.desktop",
                                 "yuzu-home.desktop", "yuzu-pet.desktop",
                                 "yuzu-saya.desktop",
                                 "yuzu-wiki.desktop"], done.stdout)
        # and on the Desktop too, which is where a touchscreen user taps
        self.assertIn("yuzu-wiki.desktop", on_desktop)
        self.assertIn("yuzu-home.desktop", on_desktop)

    def test_the_wiki_app_opens_CHROMELESS_not_a_browser_tab(self):
        """The whole request. --app= gives a window with no url bar and
        no tabs, so it reads as an application. A normal browser window
        is the "blah blah number number" problem in a nicer costume."""
        done, _, _, wrapper = self._run(have=("chromium", "xterm"))
        self.assertIsNotNone(wrapper, done.stdout)
        self.assertIn("--app=", wrapper)
        self.assertIn("127.0.0.1:8080", wrapper,
                      "it hardcodes a LAN address that changes with the "
                      "network -- on the deck itself, loopback is right")

    def test_the_wiki_app_STARTS_the_server_before_opening_it(self):
        """A tap that lands on a dead port is the same dead end he
        already has, just prettier. It launches ~/YUZU/wiki first and
        waits for the port."""
        done, _, _, wrapper = self._run(have=("chromium", "xterm"))
        self.assertIsNotNone(wrapper, done.stdout)
        self.assertIn("YUZU/wiki", wrapper)
        self.assertLess(wrapper.index("YUZU/wiki"), wrapper.index("exec "),
                        "it opens the browser before starting the server")

    def test_a_missing_browser_SKIPS_rather_than_installing_a_dead_icon(self):
        """An icon that opens nothing when tapped is worse than no
        icon: it reads as a broken deck rather than a missing package.
        It says which package instead."""
        done, names, _, wrapper = self._run(have=())
        self.assertEqual(names, ["yuzu-gba.desktop"], done.stdout)
        self.assertIn("SKIPPED Wikipedia", done.stdout)
        self.assertIn("chromium", done.stdout, "it does not name the fix")
        self.assertIsNone(wrapper,
                          "it wrote a launcher wrapper with no browser to run")
        self.assertEqual(done.returncode, 0,
                         "a partial install is not a failure -- Game Boy "
                         "still works and he should keep that")

    def test_it_can_be_undone(self):
        done, names, _, _ = self._run("--remove", have=("chromium", "xterm"))
        self.assertEqual(names, [])
        self.assertEqual(done.returncode, 0)


class TestWikiLookup(unittest.TestCase):
    """`/wiki` -- grounding her in a real encyclopedia, still offline.

    She is a character on a deck with no internet, and everything she
    "knows" is whatever a 3B memorised: thin, and confidently wrong at
    the edges. A ZIM archive on the NVMe is real checkable text sitting
    right next to her.

    Every test here drives a REAL HTTP server serving canned Kiwix
    responses, because the thing that decides whether this works is
    parsing what kiwix-serve actually returns."""

    PAGE = (b"<html><head><title>Black hole</title></head><body>"
            b"<script>var x = 1;</script>"
            b"<h1>Black hole</h1>"
            b"<p>A black hole is a region of spacetime where gravity is "
            b"so strong that nothing, not even light, can escape.[12] "
            b"It forms when a massive star collapses.</p>"
            b"<table><tr><td>infobox junk</td></tr></table>"
            b"</body></html>")

    def _serve(self, routes, test):
        """Run a stub kiwix-serve on the port yuzu_wiki talks to."""
        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                for prefix, (code, body) in routes.items():
                    if self.path.startswith(prefix):
                        self.send_response(code)
                        self.send_header("Content-Type", "text/html")
                        self.end_headers()
                        self.wfile.write(body)
                        return
                self.send_response(404)
                self.end_headers()
                self.wfile.write(b"no")

            def log_message(self, *a):
                pass

        server = HTTPServer(("127.0.0.1", 0), Handler)
        port = server.server_port
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        original = yuzu_wiki.BASE
        yuzu_wiki.BASE = f"http://127.0.0.1:{port}"
        try:
            return test()
        finally:
            yuzu_wiki.BASE = original
            server.shutdown()
            server.server_close()

    def test_it_reads_an_article_through_the_json_suggest_endpoint(self):
        routes = {"/suggest": (200, b'[{"path": "/c/A/Black_hole"}]'),
                  "/c/A/": (200, self.PAGE),
                  "/": (200, b"<html>kiwix</html>")}
        title, body = self._serve(routes, lambda: yuzu_wiki.look_up("black hole"))
        self.assertEqual(title, "Black hole")
        self.assertIn("nothing, not even light", body)

    def test_script_and_table_junk_never_reaches_her(self):
        """An infobox and a <script> body would be read out loud by
        Piper and would eat the context window for nothing."""
        routes = {"/suggest": (200, b'[{"path": "/c/A/Black_hole"}]'),
                  "/c/A/": (200, self.PAGE),
                  "/": (200, b"ok")}
        _, body = self._serve(routes, lambda: yuzu_wiki.look_up("black hole"))
        self.assertNotIn("var x", body)
        self.assertNotIn("infobox junk", body)
        self.assertNotIn("[12]", body, "citation markers survived")

    def test_it_falls_back_to_scraping_search_when_suggest_is_missing(self):
        """kiwix-serve has changed shape across versions and the one on
        his board is not pinned. Older builds have no /suggest at all."""
        routes = {"/suggest": (404, b"nope"),
                  "/search": (200, b'<a href="/c/A/Black_hole">Black hole</a>'),
                  "/c/A/": (200, self.PAGE),
                  "/": (200, b"ok")}
        title, _ = self._serve(routes, lambda: yuzu_wiki.look_up("black hole"))
        self.assertEqual(title, "Black hole")

    def test_a_missing_server_is_STARTED_not_reported(self):
        """MEASURED, Sept 9. `/wiki ice cream` correctly said "The wiki
        isn't running" -- accurate, and still a dead end, because he has
        ONE serial terminal. Fixing it meant quitting the chat, starting
        a server, and starting the chat again, mid-sentence.

        Same rule the app launcher already follows: a request that lands
        on a dead port should START the thing, not report on it."""
        import inspect
        body = inspect.getsource(yuzu_wiki.look_up)
        self.assertIn("start_server", body,
                      "a missing wiki is still only reported, so a lookup "
                      "mid-conversation is a dead end")
        starter = inspect.getsource(yuzu_wiki.start_server)
        self.assertIn("wiki", starter)
        # it must WAIT: kiwix-serve binds a second or two after forking,
        # and returning immediately would report failure on a server
        # that was seconds from being ready
        self.assertIn("time.sleep", starter)

    def test_a_wiki_that_will_not_start_returns_a_SENTENCE(self):
        """The failure that matters. A lookup mid-conversation must
        degrade to something he can read, not end the chat."""
        original = yuzu_wiki.BASE
        started = yuzu_wiki.start_server
        yuzu_wiki.BASE = "http://127.0.0.1:9"      # discard port
        yuzu_wiki.start_server = lambda *a, **k: False   # and it won't come up
        try:
            title, why = yuzu_wiki.look_up("anything")
            self.assertIsNone(title)
            self.assertIn("~/YUZU/wiki", why, "it does not say how to fix it")
        finally:
            yuzu_wiki.BASE = original
            yuzu_wiki.start_server = started

    def test_a_miss_says_so_plainly(self):
        routes = {"/suggest": (200, b"[]"), "/search": (200, b"<html></html>"),
                  "/": (200, b"ok")}
        title, why = self._serve(routes,
                                 lambda: yuzu_wiki.look_up("zzzznotathing"))
        self.assertIsNone(title)
        self.assertIn("zzzznotathing", why)

    def test_the_extract_is_capped_and_cut_on_a_SENTENCE(self):
        """4096 context on the Orin, shared with her whole prompt and
        eight turns of history. And half a clause is worse than none --
        she would answer from a sentence that stops mid-thought."""
        long_body = (b"<html><h1>T</h1><p>" + b"Fact number one here. " * 200
                     + b"</p></html>")
        routes = {"/suggest": (200, b'[{"path": "/c/A/T"}]'),
                  "/c/A/": (200, long_body), "/": (200, b"ok")}
        _, body = self._serve(routes, lambda: yuzu_wiki.look_up("t"))
        self.assertLessEqual(len(body), yuzu_wiki.MAX_CHARS + 3)
        self.assertTrue(body.rstrip().endswith((".", "...")), repr(body[-40:]))

    def test_it_arrives_as_a_USER_turn_not_a_system_instruction(self):
        """ASSISTANT COLLAPSE is this deck's signature failure and it
        is already measured once: asked a technical question she
        produced markdown headings and fenced code blocks.

        A wall of encyclopedia text delivered as a system message is
        the shortest path back to that. Phrased as something HE says,
        with an explicit ask for her own words, it stays conversation."""
        routes = {"/suggest": (200, b'[{"path": "/c/A/Black_hole"}]'),
                  "/c/A/": (200, self.PAGE), "/": (200, b"ok")}
        grounded, why = self._serve(
            routes, lambda: yuzu_wiki.as_context("black hole"))
        self.assertIsNone(why)
        self.assertTrue(grounded.startswith("I looked up"),
                        "it does not read as the user speaking")
        self.assertIn("in your own words", grounded)

    def test_the_brain_guards_the_import_like_the_voice_does(self):
        """yuzu_brain must still run with this file absent -- the
        encyclopedia is a nice-to-have and a missing sibling must never
        stop her talking. Same rule the Piper import already follows."""
        import inspect
        head = inspect.getsource(yuzu_brain)[:2000]
        self.assertIn("import yuzu_wiki", head)
        self.assertIn("except ImportError", head)

    def _grounded(self, typed):
        """What `ground()` hands the model, with a stub archive."""
        with mock.patch.object(
                yuzu_brain.yuzu_wiki, "as_context",
                lambda t: ("I looked up %s and it says: FACTS." % t, None)):
            return yuzu_brain.ground(typed)

    def test_wiki_is_recognised_ANYWHERE_in_the_line_and_in_ANY_case(self):
        """TWO MEASURED PHONE BEHAVIOURS, one test.

        Sept 9: he typed "hey saya we got u all pimped out wana try
        sumn? /wiki ice cream" and a startswith() check missed it
        SILENTLY -- the whole line went to her as ordinary chat and she
        answered about ice cream out of her own head.

        And the CASE. A soft keyboard capitalises the first word of a
        line, so `/Wiki cats` is what his phone produces whenever the
        command starts the message. The fix for the first bug checked
        `text.lower()` and then split the ORIGINAL, so `/Wiki` passed
        the check, found nothing to split on, and handed her the whole
        line anyway -- the same mechanism that made `Quit.` fail to
        quit, and just as invisible on screen.

        THIS TEST DRIVES THE REAL FUNCTION rather than grepping it. The
        version it replaces asserted the literal strings
        `"/wiki" in text.lower()` and `partition` were present in
        `_cli`'s source -- which was true the entire time the face page
        had no lookup at all."""
        for typed in ('/wiki cats', '/Wiki cats', '/WIKI cats',
                      'hey saya wana try sumn? /wiki cats',
                      'oh /wiki cats pls'):
            got, problem = self._grounded(typed)
            self.assertIsNone(problem, typed)
            self.assertIn("I looked up cats", got,
                          "no lookup happened for %r" % typed)

    def test_the_ARTICLE_ITSELF_beats_one_that_merely_mentions_it(self):
        """MEASURED, Sept 11, and the lookup was working perfectly.

        `/wiki video games` came back about **Electronic Games
        magazine** -- she named Arnie Katz, Bill Kunkel and Joyce
        Worley, its three real founders, which a 3B does not invent. So
        the server answered, the parser read it, and she was simply
        handed the wrong article. `/wiki fish` got fish FARMING.

        Kiwix ranks by full-text score, so a page that MENTIONS a term
        often can outrank the page that IS the term, and the first hit
        was taken on trust. Type fish, get Fish."""
        for term, hits, want in [
            ("video games",
             ["/c/b/Electronic_Games", "/c/b/Video_game",
              "/c/b/List_of_video_games"], "/c/b/Video_game"),
            ("fish",
             ["/c/b/Fish_farming", "/c/b/Fishing", "/c/b/Fish"],
             "/c/b/Fish"),
            ("cats", ["/c/b/Munchkin_cat", "/c/b/Cat"], "/c/b/Cat"),
        ]:
            self.assertEqual(yuzu_wiki.rank(term, hits)[0], want, term)

    def test_a_disambiguation_page_is_never_the_answer(self):
        """The qualifier is stripped before matching -- which is right,
        so "Fish (animal)" can match "fish" -- and that made "Black hole
        (disambiguation)" an EXACT match for "black holes". A list of
        links where she expected an article. Demoted, not dropped."""
        hits = ["/c/b/Black_hole_(disambiguation)", "/c/b/Black_hole"]
        self.assertEqual(yuzu_wiki.rank("black holes", hits)[0],
                         "/c/b/Black_hole")

    def test_ranking_leaves_kiwix_alone_when_no_title_matches(self):
        """It re-orders the obvious cases and stays out of the way
        otherwise -- kiwix's own relevance is better than nothing."""
        hits = ["/c/b/Fish_farming", "/c/b/Fishing"]
        self.assertEqual(yuzu_wiki.rank("zzzz", hits), hits)

    def test_the_turn_NAMES_the_subject_rather_than_saying_it(self):
        """She absorbed the subject into herself: handed an article
        about a magazine, "I used to be featured in this magazine back
        when I was still just a concept"; handed fish farming, "I don't
        think I'd make a very good fish farm".

        "Tell me about it" leaves "it" free to mean HER. Naming the
        title again costs a few characters and cannot be misread."""
        with mock.patch.object(yuzu_wiki, "look_up",
                               lambda t, **k: ("Video game", "Body text.")):
            said, _ = yuzu_wiki.as_context("video games")
        self.assertIn("Tell me about Video game", said)
        self.assertNotIn("Tell me about it", said)
        self.assertIn("sentence or two", said, "the brevity clause is gone")

    def test_whatever_he_said_around_the_lookup_is_KEPT(self):
        """Dropping his own words answers a question he never asked on
        its own."""
        got, _ = self._grounded('hey saya wana try sumn? /wiki cats')
        self.assertIn("hey saya wana try sumn?", got)
        self.assertIn("I looked up cats", got)

    def test_a_lookup_that_finds_nothing_SAYS_SO(self):
        """Silence is the failure mode this whole area keeps producing.
        A miss must come back as a sentence, never as her answering
        from her own head with nobody told a lookup was skipped."""
        with mock.patch.object(yuzu_brain.yuzu_wiki, "as_context",
                               lambda t: (None, "Nothing about '%s'" % t)):
            got, problem = yuzu_brain.ground('/wiki qqqq')
        self.assertEqual(problem, "Nothing about 'qqqq'")
        self.assertEqual(got, '/wiki qqqq', "it mangled what he typed")

    def test_ordinary_chat_is_left_completely_alone(self):
        for typed in ('hey saya', 'what is a wiki anyway',
                      'i read that on wikipedia lol'):
            self.assertEqual(yuzu_brain.ground(typed), (typed, None), typed)

    def test_it_still_uses_the_user_turn_phrasing(self):
        """A raw extract arriving as a system message is the shortest
        path back to assistant collapse -- measured once already."""
        import inspect
        self.assertIn("as_context", inspect.getsource(yuzu_brain.ground))

    def test_BOTH_ways_of_talking_to_her_do_the_lookup(self):
        """THE TEST THAT WAS MISSING, and its absence cost the feature.

        `/wiki` was written into the terminal loop; the face page was
        built afterwards and `POST /say` never got it. Ghost typed
        "/wiki cats" into the chat bar under her face, the literal
        string reached her as ordinary conversation, and she answered
        about "wiki cats" out of her own head -- he read it as her being
        a tsundere about being asked. **A missing feature that looks
        like a personality.**

        So this asserts the PROPERTY rather than either copy: every way
        in reaches the same `ground()`. A third way in has to as well."""
        self.assertIn("ground(", inspect.getsource(yuzu_brain._cli),
                      "the terminal chat no longer looks anything up")

        asked = []
        class FakeBrain:
            def ask(self, text):
                asked.append(text)
                return "..."
        import yuzu_face
        was, yuzu_face._BRAIN = yuzu_face._BRAIN, FakeBrain()
        try:
            with mock.patch.object(
                    yuzu_brain.yuzu_wiki, "as_context",
                    lambda t: ("I looked up %s and it says: FACTS." % t, None)):
                yuzu_face.answer("/wiki cats")
        finally:
            yuzu_face._BRAIN = was
            yuzu_face.set_state("idle")
        self.assertIn("I looked up cats", asked[-1],
                      "the chat bar under her face still hands her the "
                      "raw string -- the bug Ghost hit on Sept 11")


class TestWikiServer(unittest.TestCase):
    """`wiki` -- offline Wikipedia on the deck, one word.

    The previous attempt at this ran kiwix-serve in the FOREGROUND. It
    held the terminal, which on a phone serial link is indistinguishable
    from a frozen board: q, cd and `sudo poweroff` all went into a
    process that was not a shell, and Ghost power-cycled the board
    rather than lose the session. Nothing was damaged, but that is the
    failure this script exists to prevent."""

    SCRIPT = Path(__file__).parent / "wiki"

    def _run(self, *args, zims=(), up=False):
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            home = tmp / "home"
            home.mkdir()
            binv = tmp / "bin"
            binv.mkdir()
            calls = tmp / "calls"
            flag = tmp / "up"
            if up:
                flag.touch()
            for name, body in (
                    ("kiwix-serve",
                     f'echo "kiwix $*" >> {calls}\ntouch {flag}\nexit 0\n'),
                    ("ss",
                     'echo "State Recv-Q Send-Q Local:Port Peer"\n'
                     f'[ -f {flag} ] && echo "LISTEN 0 5 0.0.0.0:8080 *"\n'
                     "exit 0\n"),
                    ("pkill", "exit 0\n"),
                    ("pgrep", f'[ -f {flag} ]\n')):
                target = binv / name
                target.write_text("#!/bin/bash\n" + body)
                target.chmod(0o755)
            for zim in zims:
                (home / zim).write_bytes(b"z" * (2 * 1024 * 1024))
            env = dict(os.environ, HOME=str(home),
                       PATH=f"{binv}:{os.environ['PATH']}")
            done = subprocess.run(["bash", str(self.SCRIPT), *args],
                                  capture_output=True, text=True,
                                  env=env, timeout=90)
            return done, (calls.read_text() if calls.exists() else "")

    def test_it_is_valid_shell(self):
        import subprocess
        done = subprocess.run(["bash", "-n", str(self.SCRIPT)],
                              capture_output=True)
        self.assertEqual(done.returncode, 0, done.stderr.decode())

    def test_the_server_is_launched_DETACHED(self):
        """The whole reason this file exists. A foreground server on a
        serial link looks exactly like a frozen board, and that already
        cost one power-cycle."""
        body = self.SCRIPT.read_text()
        launch = [ln for ln in body.splitlines()
                  if "kiwix-serve --port" in ln and
                  not ln.strip().startswith("#")]
        self.assertTrue(launch, "nothing launches kiwix-serve")
        self.assertTrue(any("nohup" in ln and ln.rstrip().endswith("&")
                            for ln in launch),
                        "kiwix-serve runs in the FOREGROUND -- it will hold "
                        "the terminal and read as a hung board")

    def test_it_finds_the_archive_itself(self):
        """A 982MB download's path is not something to retype on a
        phone keyboard. Newest .zim wins, no argument needed."""
        done, calls = self._run(zims=("wikipedia_en_simple_all_nopic.zim",))
        self.assertIn("wikipedia_en_simple_all_nopic.zim", calls,
                      done.stdout + done.stderr)
        self.assertEqual(done.returncode, 0)

    def test_a_missing_archive_says_where_to_get_one(self):
        done, calls = self._run(zims=())
        self.assertEqual(done.returncode, 1)
        self.assertIn("kiwix.org", done.stdout)
        self.assertEqual(calls, "", "it launched a server with no archive")

    def test_it_checks_the_PHONE_can_reach_it(self):
        """Same fault as TigerVNC binding to loopback: a live process
        proves nothing about whether anything can connect."""
        body = self.SCRIPT.read_text()
        self.assertIn("ss -ltn", body)
        self.assertIn("127", body,
                      "nothing rejects a loopback-only bind")

    def test_a_running_server_is_left_alone(self):
        """Restarting it would drop whatever he is reading."""
        done, calls = self._run(zims=("w.zim",), up=True)
        self.assertEqual(calls, "", "it relaunched a healthy server")
        self.assertIn("Already up", done.stdout)

    def test_there_is_an_off_switch(self):
        """He asked how to macro a Ctrl-C once. He should never need
        one -- same reasoning as drop.py stopping itself."""
        self.assertIn("--off", self.SCRIPT.read_text())
        done, _ = self._run("--off", up=True)
        self.assertEqual(done.returncode, 0)


class TestGbaLauncher(unittest.TestCase):
    """`gba` -- one word to play, because the real command was three
    lines with a DISPLAY prefix, a vncserver invocation and a glob.
    None of that is something to retype on a phone keyboard.

    Shell rather than Python on purpose: it launches X apps and manages
    a VNC session, which is what a shell is actually good at."""

    SCRIPT = Path(__file__).parent / "gba"

    def test_it_exists_and_is_executable(self):
        self.assertTrue(self.SCRIPT.exists())
        self.assertTrue(os.access(self.SCRIPT, os.X_OK),
                        "gba is not executable, so `~/YUZU/gba` fails")

    def test_it_is_valid_shell(self):
        """A syntax error here surfaces on a phone at the board."""
        import subprocess
        done = subprocess.run(["bash", "-n", str(self.SCRIPT)],
                              capture_output=True)
        self.assertEqual(done.returncode, 0, done.stderr.decode())

    def test_the_emulator_is_launched_detached(self):
        """A foreground process on a serial link looks EXACTLY like a
        freeze. That already cost one power-cycle on this board, when a
        foreground kiwix-serve was read as the machine hanging."""
        body = self.SCRIPT.read_text()
        launch = [ln for ln in body.splitlines() if "mgba-qt" in ln
                  and not ln.strip().startswith("#")]
        self.assertTrue(launch, "nothing launches the emulator")
        self.assertTrue(any("nohup" in ln and ln.rstrip().endswith("&")
                            for ln in launch),
                        "mgba-qt is launched in the FOREGROUND -- it will "
                        "hold the terminal and read as a frozen board")

    NASTY = "Pokemon - Emerald Version (USA, Europe) (patched).gba"

    def _run(self, *args, roms=(NASTY,), bind="0.0.0.0"):
        """Drive the real script against stub vncserver/mgba-qt/xdpyinfo,
        so this tests BEHAVIOUR rather than matching source text. An
        earlier text-matching version of this flagged $ROMS inside a
        quoted echo string, which was never a bug."""
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            gba_dir = tmp / "home" / "ROMs" / "gba"
            gba_dir.mkdir(parents=True)
            binv = tmp / "bin"
            binv.mkdir()
            calls = tmp / "calls"
            # `ss` reports whatever `bind` says until vncserver is asked
            # to start a real session, at which point it reports a
            # reachable one -- so a test can drive the loopback repair.
            flag = tmp / "bound"
            for name, script in (
                    ("vncserver",
                     f'echo "vnc $*" >> {calls}\n'
                     f'[ "$1" = "-kill" ] || touch {flag}\nexit 0\n'),
                    ("mgba-qt", f'echo "rom=$1" >> {calls}\nexit 0\n'),
                    ("ss",
                     'echo "State Recv-Q Send-Q Local:Port Peer"\n'
                     f'if [ -f {flag} ]; then echo "LISTEN 0 5 0.0.0.0:5901 *"\n'
                     f'else echo "LISTEN 0 5 {bind}:5901 *"; fi\n')):
                target = binv / name
                target.write_text("#!/bin/bash\n" + script)
                target.chmod(0o755)
            if bind == "0.0.0.0":
                flag.touch()              # already reachable, nothing to fix
            for rom in roms:
                (gba_dir / rom).write_bytes(b"x")
            env = dict(os.environ, HOME=str(tmp / "home"),
                       PATH=f"{binv}:{os.environ['PATH']}")
            done = subprocess.run(["bash", str(self.SCRIPT), *args],
                                  capture_output=True, text=True, env=env)
            # The emulator is launched with `nohup ... &` ON PURPOSE, so
            # the script returns BEFORE the stub has written its line.
            # Reading the log immediately made this class fail about one
            # run in eight -- an intermittent red that reads as a broken
            # launcher and is really a test racing a correct detach.
            deadline = time.time() + 5
            log = ""
            while done.returncode == 0 and time.time() < deadline:
                log = calls.read_text() if calls.exists() else ""
                if "rom=" in log:
                    break
                time.sleep(0.02)
            else:
                log = calls.read_text() if calls.exists() else ""
            return done, log

    def test_a_rom_name_with_spaces_and_parens_reaches_the_emulator(self):
        """The one ROM he actually has is named `Pokemon - Emerald
        Version (USA, Europe) (patched).gba`. An unquoted expansion
        breaks on the only real input this will ever get -- and it
        would break as `mgba-qt: Pokemon: No such file`, which reads
        like a missing ROM rather than a quoting bug."""
        done, log = self._run()
        self.assertIn(f"rom=", log, done.stderr)
        self.assertIn(self.NASTY, log,
                      "the ROM path arrived at the emulator mangled")

    def test_it_picks_the_newest_rom_and_can_be_filtered_by_name(self):
        done, log = self._run("Emerald",
                              roms=("Metroid Fusion.gba", self.NASTY))
        self.assertIn(self.NASTY, log)
        self.assertNotIn("Metroid", log)

    def test_a_missing_rom_fails_fast_and_says_how_to_send_one(self):
        """Nothing should be started before the ROM is found -- a typo
        must fail in a second, not after a desktop has spun up."""
        done, log = self._run(roms=())
        self.assertEqual(done.returncode, 1)
        self.assertIn("drop.py", done.stdout)
        self.assertEqual(log, "", "it started a desktop with no ROM to play")

    def test_it_checks_the_phone_can_REACH_it_not_just_that_X_is_up(self):
        """MEASURED THE HARD WAY, Sept 9. The first version checked
        `xdpyinfo` -- is X running -- and reported success while
        TigerVNC was bound to 127.0.0.1. Every local signal said
        working: a session listed, a process alive, X answering. AVNC
        could not connect and nothing on screen said why.

        `vncserver -list`            1  5901  9170  Xtigervnc
        `ss -ltn`                    LISTEN  127.0.0.1:5901
        the log                      "on local interface(s), port 5901"

        Two things had to change: pass -localhost no, and check the
        BINDING rather than the process. A check that cannot see the
        actual failure mode is not a check."""
        done, log = self._run(bind="127.0.0.1")
        self.assertIn("-localhost no", log,
                      "it did not restart the desktop with -localhost no, "
                      "so the phone still cannot reach it")
        self.assertIn(self.NASTY, log, "the game never launched")

    def test_a_desktop_already_reachable_is_left_alone(self):
        """Restarting a working session would drop him mid-game."""
        done, log = self._run(bind="0.0.0.0")
        self.assertNotIn("vnc", log, "it restarted a healthy desktop")
        self.assertIn(self.NASTY, log)

    def test_the_desktop_check_does_not_trust_a_lock_file(self):
        """A leftover file in ~/.vnc claims a session exists when none
        does, which is how you end up debugging "could not connect to
        display :1" against a server that never ran. Ask the kernel
        what is actually listening instead."""
        body = self.SCRIPT.read_text()
        self.assertIn("ss -ltn", body)
        self.assertNotIn("~/.vnc", body,
                         "it is reading the lock directory again")

    def test_there_is_a_way_to_stop_it(self):
        """He asked how to macro a Ctrl-C. The answer is that he should
        never need one -- same reasoning as drop.py stopping itself."""
        body = self.SCRIPT.read_text()
        self.assertIn("--off", body)
        self.assertIn("pkill -f mgba-qt", body)


class TestDropBox(unittest.TestCase):
    """drop.py -- getting a file from the phone onto the board.

    Built Sept 9 because there was NO good path for it. Ghost patched a
    ROM on his phone and the board could not reach it: no scp from
    Serial USB Terminal, no URL to wget, and the microSD is the rescue
    image. The same gap cost real time earlier when a push failed on
    auth and two persona files had to be rescued by `cat` and paste.

    Stdlib only, same as everything else here, so it runs anywhere the
    rest of this project does."""

    def _post(self, filename, payload, boundary=b"XbndX"):
        body = (b"--" + boundary + b"\r\n"
                b'Content-Disposition: form-data; name="f"; filename="'
                + filename + b'"\r\n'
                b"Content-Type: application/octet-stream\r\n\r\n"
                + payload + b"\r\n--" + boundary + b"--\r\n")
        return drop.one_file(body, 'multipart/form-data; boundary=XbndX')

    def test_a_posted_file_survives_byte_for_byte(self):
        """A ROM that arrives one byte short is a ROM that will not
        boot, and nothing on screen would say why."""
        blob = bytes(range(256)) * 40
        name, data = self._post(b"SoulGold.gba", blob)
        self.assertEqual(name, "SoulGold.gba")
        self.assertEqual(data, blob)

    def test_a_filename_can_never_write_outside_the_folder(self):
        """The one genuinely dangerous line in the file. A crafted
        filename must not escape the directory it was started in."""
        for hostile in (b"../../../../etc/passwd", b"..\\..\\windows\\x",
                        b"/etc/shadow", b"....//evil"):
            with self.subTest(hostile=hostile):
                name, _ = self._post(hostile, b"x")
                safe = os.path.basename(name.replace("\\", "/"))
                self.assertNotIn("/", safe)
                self.assertNotIn("\\", safe)
                self.assertFalse(os.path.isabs(safe))

    def test_junk_is_refused_rather_than_written(self):
        """No boundary, or a part with no filename, must return nothing
        -- not an empty file, and not a traceback at the phone."""
        self.assertEqual(drop.one_file(b"whatever", "text/plain"),
                         (None, None))
        self.assertEqual(
            drop.one_file(b'--X\r\nContent-Disposition: form-data; '
                          b'name="f"\r\n\r\nnofile\r\n--X--\r\n',
                          'multipart/form-data; boundary=X'),
            (None, None))

    def test_it_stops_by_itself_after_one_file(self):
        """Ghost asked how to macro a Ctrl-C, which is the wrong thing
        to have to ask. His phone terminal has no easy one, and a
        server he cannot stop is worse than one that quits early -- so
        the default is one file and out, and --stay is the opt-in.

        The shutdown MUST happen after the reply is written. Stopping
        from inside the handler before that cuts the response off, and
        the phone shows a network error over a file that arrived
        perfectly intact."""
        import inspect
        body = inspect.getsource(drop.Drop.do_POST)
        self.assertIn("self._page(", body)
        self.assertLess(body.index("self._page("), body.index("done = True"),
                        "the server stops before answering the phone, so a "
                        "good upload will look like a failed one")
        self.assertIn("STAY", body)

    def test_it_reports_a_reachable_address(self):
        """It must print the LAN address, not 127.0.0.1 -- the phone
        cannot reach loopback, and this project has already lost time
        twice to picking the wrong interface off hostname -I."""
        ip = drop.lan_ip()
        self.assertNotEqual(ip, "127.0.0.1")
        self.assertRegex(ip, r"^\d+\.\d+\.\d+\.\d+$")


class TestGettingOutOfTheChat(unittest.TestCase):
    """THIS COST GHOST TWO POWER CYCLES IN ONE EVENING.

    He has ONE serial terminal. No SSH, no second session, no working
    Ctrl-C -- *"theres no option for a second session brudda. i had no
    choice."* When the chat loop would not let go, the only thing left
    was the plug.

    That is not a user error. It is a loop with no exit, and every
    piece of advice that assumed a second terminal was wrong.

    These drive the REAL functions against a real pipe, because select()
    is what decides all of it."""

    HARNESS = ("import sys, yuzu_brain\n"
               "text, out = yuzu_brain.read_turn(prompt='')\n"
               "print('OUT' if out else 'MSG=' + repr(text))\n")

    def _turn(self, typed):
        import subprocess
        done = subprocess.run([sys.executable, "-c", self.HARNESS],
                              input=typed, capture_output=True, text=True,
                              cwd=str(Path(__file__).parent), timeout=30)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout.strip()

    def test_quit_typed_while_she_is_talking_wins_IMMEDIATELY(self):
        """The exact trap. `quit` used to queue up BEHIND everything
        already buffered, so it looked ignored while she worked through
        a backlog. An exit anywhere in the buffer now ends it."""
        self.assertEqual(self._turn("hey saya whats up\nquit\n"), "OUT")

    def test_a_paste_with_quit_behind_it_still_gets_out(self):
        """He pasted a 12-line command by mistake; every line became a
        message costing a full generation, and the quit he typed next
        sat behind all twelve."""
        self.assertEqual(
            self._turn("import urllib.request as u\ndef g(p):\n"
                       "    return 1\nprint(g)\nquit\n"), "OUT")

    def test_hammering_exit_four_times_gets_out(self):
        self.assertEqual(self._turn("Exit\nExit!\nquit\nquit\n"), "OUT")

    def test_pkill_typed_in_desperation_gets_out(self):
        """He typed `pkill -f yuzu_brain` AT HER PROMPT while trapped,
        and she answered it. Someone reaching for pkill wants out."""
        self.assertEqual(self._turn("blah\npkill -f yuzu_brain\n"), "OUT")

    def test_a_paste_is_ONE_turn_not_one_message_per_line(self):
        out = self._turn("hey saya\nhows the deck\n")
        self.assertEqual(out, "MSG='hey saya\\nhows the deck'")

    def test_talking_ABOUT_quitting_is_not_quitting(self):
        """The dangerous half. These must reach her as conversation --
        an exit that fires on ordinary sentences is its own trap."""
        for typed in ("what does quit mean anyway\n",
                      "i quit my job today lol\n",
                      "stop it lol\n",
                      "does pkill work on ubuntu\n"):
            with self.subTest(typed=typed):
                self.assertTrue(self._turn(typed).startswith("MSG="), typed)

    def test_pending_lines_never_blocks_on_an_empty_stream(self):
        """A zero timeout is the whole contract: it must ask "is there
        input RIGHT NOW", never wait for something not yet typed."""
        import io
        self.assertEqual(yuzu_brain.pending_lines(io.StringIO("")), [])


class TestExitCommand(unittest.TestCase):
    """Getting OUT of the chat loop. Reported by Ghost, Sept 9: he typed
    quit twice into a live Shiro session and she REPLIED to it, in
    character, both times. The handoff called it a missing check and
    proposed exactly the check both loops already had -- so the check
    was never the gap. What a PHONE hands to input() is the gap: a soft
    keyboard capitalises the first word, double-space makes a full stop,
    and a serial terminal can add a trailing \\r. All three are
    invisible on screen, which is why it read as a missing feature."""

    PHONE_TYPED = ["quit", "Quit", "Quit.", "QUIT", "quit ", " quit",
                   "quit\r", "quit\r\n", "exit", "Exit!", "q", "Q.",
                   "bye", "Bye.", "/quit", "/exit", ":q"]

    CONVERSATION = ["stop", "Stop.", "stop walking", "quit it",
                    "what does quit mean", "i quit my job lol", "",
                    "   ", "byebye", "exit strategy", "queen"]

    def test_the_phone_shapes_of_the_word_all_get_out(self):
        for typed in self.PHONE_TYPED:
            with self.subTest(typed=typed):
                self.assertTrue(
                    yuzu_brain.is_exit_command(typed),
                    f"{typed!r} was typed to leave and did not leave")

    def test_things_you_say_to_HER_are_not_exit_commands(self):
        """The other half, and the more dangerous one. `stop` is
        deliberately excluded: on the robot loop it is a whitelisted
        MOVE (nine phrasings alias to stand(), a measured fix), and in
        a chat "stop it lol" is aimed at her, not at the program. An
        exit word has to be one nobody uses in conversation."""
        for typed in self.CONVERSATION:
            with self.subTest(typed=typed):
                self.assertFalse(
                    yuzu_brain.is_exit_command(typed),
                    f"{typed!r} would have ended the session mid-chat")

    def test_the_two_copies_of_the_exit_check_agree(self):
        """yuzu_all_in_one.py carries its own copy for the case its
        guarded `from yuzu_brain import ...` fails -- that file has to
        survive as a lone download, and a loop you cannot leave is the
        worst thing to lose to a missing import. Same deliberate
        duplication as the doctor's Jetson check, and the same risk:
        if they drift, quit works in one place and not the other.

        Read the FALLBACK out of the source rather than the imported
        name, because with yuzu_brain present the module attribute is
        just brain's function and the copy is never exercised."""
        import inspect
        src = inspect.getsource(yuzu)
        start = src.index("except ImportError:\n    YuzuBrain = None")
        end = src.index("\ntry:", start)
        namespace = {}
        exec(textwrap.dedent(src[src.index("def is_exit_command", start):end]),
             namespace)
        fallback = namespace["is_exit_command"]
        for typed in self.PHONE_TYPED + self.CONVERSATION:
            with self.subTest(typed=typed):
                self.assertEqual(
                    fallback(typed), yuzu_brain.is_exit_command(typed),
                    f"the two copies disagree about {typed!r}")

    def test_both_loops_actually_call_it(self):
        """A helper nothing calls fixes nothing.

        The chat loop reaches it through read_turn() now, which also
        makes an exit ANYWHERE in the buffer win -- see
        TestGettingOutOfTheChat. The robot loop still calls it
        directly."""
        import inspect
        self.assertIn("is_exit_command(",
                      inspect.getsource(yuzu_brain.read_turn),
                      "read_turn does not use the exit check, so a "
                      "phone's full stop gets sent to her")
        self.assertIn("read_turn(", inspect.getsource(yuzu_brain._cli),
                      "the chat loop bypasses read_turn, so a queued "
                      "quit waits behind the backlog again")
        self.assertIn("is_exit_command(",
                      inspect.getsource(yuzu.run_yuzu_forever),
                      "run_yuzu_forever still compares the word by hand")


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
            """Up to the sounds rule only.

            The sound EXAMPLES are deliberately per-character now, so
            comparing past them would fail by design. What must stay
            identical is everything about the BODY -- the self-concept,
            the bracket rule, and the action menu. If those ever differ,
            one character is being taught moves the other isn't, which
            is the failure this test exists for."""
            prompt = yuzu_personas.load(key).prompt
            start = prompt.index("You are a person, and right now")
            end = prompt.index("Sounds you make")
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

    def test_comparing_two_characters_is_not_a_promotion_race(self):
        """Every check is a hardware rule, so scoring a gyaru against a
        kuudere is fair and informative. But "move LIVE_PERSONA to the
        winner" is nonsense advice when the arms are two different
        characters -- nobody replaces Coco with Yuzu. Fix the losing
        one's prompt instead."""
        import contextlib, io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            self.ab.compare("yuzu4", self.arm(moves_at_all=12),
                            "coco", self.arm(moves_at_all=5),
                            {"yuzu4": 3785, "coco": 4058}, characters=True)
        out = buffer.getvalue()
        self.assertIn("different characters", out)
        self.assertNotIn("LIVE_PERSONA", out)

    def test_two_versions_of_one_character_still_talk_about_promotion(self):
        out = self.render(self.arm(moves_at_all=5), self.arm(moves_at_all=12))
        self.assertIn("LIVE_PERSONA", out)
        self.assertNotIn("different characters", out)

    def test_persona_names_distinguish_characters_from_versions(self):
        # yuzu2/yuzu4 are both NAMED Yuzu; coco is not.
        self.assertEqual(self.ab.persona_names("yuzu2", "yuzu4"),
                         ["Yuzu", "Yuzu"])
        self.assertEqual(self.ab.persona_names("yuzu4", "coco"),
                         ["Yuzu", "Coco"])

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
        """CONFIRMED Sept 3 by an A/B on a single word.

            "SIX legs"  -> spelled out, letter by letter
            "six legs"  -> said properly

        Same word, same sentence, only the case changed. Capitals
        really do trigger spelling-out -- independently of the
        vowel-less problem "pfft" turned out to have. Two separate
        mechanisms; this is the one lowercasing fixes, and the reason
        unshout() stays.
        """
        # unshout() is the caps layer specifically. for_speech also
        # respells the noise afterwards, which is a separate fix.
        self.assertEqual(self.voice.unshout("PFFT! My camera!"),
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

    def test_a_noise_this_voice_cannot_make_is_dropped_not_mangled(self):
        """MEASURED three times, Sept 3, en_US-amy-medium:

            "PFFT!"                       -> "Pee Eff Eff Tee"
            lowercased to "pfft"          -> still "pee eff eff tee"
            respelled puft/pift/puh/...   -> none of them worked either

        A synthesiser says WORDS. A bilabial raspberry is not one and no
        spelling of it becomes one. Third round is where guessing again
        stopped being worth it.

        So it is dropped -- the same call the action whitelist makes for
        a movement this body can't do: silence, never a substitute. The
        sentence around it survives.
        """
        self.assertEqual(self.voice.for_speech("PFFT! My camera!"),
                         "My camera!")
        for written in ("pfft", "PFFT", "Pfft"):
            self.assertEqual(self.voice.for_speech(written), "")

    def test_dropping_the_noise_leaves_no_orphaned_punctuation(self):
        # "PFFT! My camera" must not become "! My camera" -- a stray
        # "!" is exactly the kind of thing a synthesiser reads oddly.
        self.assertEqual(self.voice.for_speech("Ehehe~ Pfft, I crack up."),
                         "Ehehe I crack up.")

    def test_the_rest_of_the_reply_always_survives(self):
        """Fails safe. Losing one noise is fine; losing the sentence is
        the robot going quiet for no visible reason."""
        said = self.voice.for_speech("PFFT! No arms on this chassis, cutie!")
        self.assertIn("chassis", said)
        self.assertIn("cutie", said)

    def test_ordinary_words_are_not_dropped(self):
        for word in ("hey", "pink", "spin", "Paris", "camera", "puft"):
            self.assertEqual(self.voice.sayable(word), word)

    def test_nothing_is_dropped_that_was_never_heard_to_fail(self):
        """Only pfft has been measured. Dropping a noise espeak says
        perfectly well would delete character for no reason -- and this
        module has already changed one thing on a wrong hypothesis."""
        self.assertEqual(set(self.voice.UNSAYABLE), {"pfft", "pft"})
        for noise in ("tsk", "shh", "grr", "hmph", "psh", "ugh", "ooh",
                      "haha", "hehe", "woah"):
            self.assertEqual(self.voice.sayable(noise), noise,
                             f"{noise} is being dropped but was never heard")

    def test_the_live_prompt_never_teaches_a_sound_it_cannot_say(self):
        """Ghost's call, and the right one: fix it at the source.

        The prompt taught "Pfft" in TWO places -- the shared sounds
        rule, and yuzu4's own "Say something silly!" example. The
        example is the stronger teacher; this repo has twice measured
        that examples beat rules. Both are gone from the live persona.

        Generalised on purpose. Any future sound added to the prompt
        gets checked against what the voice can actually produce, so
        this can't come back by someone adding a nice-looking noise.
        """
        prompt = yuzu_personas.load(yuzu_personas.LIVE_PERSONA).prompt
        for noise in self.voice.UNSAYABLE:
            self.assertNotIn(
                noise.lower(), prompt.lower(),
                f"the live persona teaches '{noise}', which this voice "
                f"drops entirely -- pick a sound with a vowel in it")

    def test_the_sounds_it_still_teaches_are_all_sayable(self):
        # Ehehe~ and the tilde strip are already measured working.
        for sound in ("Ehehe~", "Haha!", "Ugh", "Ooh"):
            self.assertTrue(self.voice.for_speech(sound).strip(),
                            f"{sound} is taught by the prompt but would "
                            f"come out silent")

    def test_no_persona_anywhere_teaches_an_unsayable_sound(self):
        """Applied to the whole lineage, not just the live arm.

        The first attempt removed Pfft from ONE body block and ONE
        example, and immediately broke two archived A/Bs -- v2-vs-v3
        stopped differing by exactly one line, and v4 stopped being
        "v2 plus one example". The hardware file's own header says a
        body fix should "land on all of them at once", and that lockstep
        is precisely what keeps the closed comparisons one-variable.
        A vocabulary fix is a body fix. It goes everywhere.
        """
        for key in yuzu_personas.available():
            prompt = yuzu_personas.load(key).prompt.lower()
            for noise in self.voice.UNSAYABLE:
                self.assertNotIn(noise.lower(), prompt,
                                 f"{key} teaches '{noise}', which the voice "
                                 f"drops entirely")

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

    def fake_voices(self, *names):
        """A voices/ dir with real .onnx + .onnx.json pairs."""
        import tempfile
        holder = tempfile.TemporaryDirectory()
        self.addCleanup(holder.cleanup)
        root = Path(holder.name)
        for name in names:
            (root / f"{name}.onnx").write_bytes(b"\0" * 64)
            (root / f"{name}.onnx.json").write_text("{}")
        return root

    def test_a_voice_missing_its_json_is_not_offered(self):
        """Piper's error when the .onnx.json is absent does not mention
        the .onnx.json. Never list a voice that will fail that way."""
        root = self.fake_voices("good")
        (root / "orphan.onnx").write_bytes(b"\0" * 64)   # no .json beside it
        with unittest.mock.patch.object(self.voice, "VOICE_DIRS", (root,)):
            names = [v.name for v in self.voice.list_voices()]
        self.assertEqual(names, ["good.onnx"])

    def test_two_voices_and_no_choice_is_flagged_not_silent(self):
        """THE footgun. find_voice() takes the first alphabetically, so
        downloading en_GB-alba after en_US-amy silently changes who she
        sounds like -- and downloading a nicer voice and hearing the old
        one looks like nothing happened at all."""
        root = self.fake_voices("en_US-amy-medium", "en_GB-alba-medium")
        with unittest.mock.patch.object(self.voice, "VOICE_DIRS", (root,)):
            with unittest.mock.patch.object(
                    self.voice, "ACTIVE_FILE", root / "ACTIVE"):
                with unittest.mock.patch.dict(os.environ, {}, clear=False):
                    os.environ.pop(self.voice.VOICE_ENV, None)
                    self.assertEqual(self.voice.find_voice().name,
                                     "en_GB-alba-medium.onnx")
                    chosen = self.voice.use_voice("amy")
                    self.assertEqual(chosen.name, "en_US-amy-medium.onnx")
                    self.assertEqual(self.voice.find_voice().name,
                                     "en_US-amy-medium.onnx")

    def test_a_remembered_voice_that_was_deleted_falls_back(self):
        # Deleting the .onnx must not leave her mute with a dangling
        # pointer -- fall back to whatever is actually installed.
        root = self.fake_voices("en_US-amy-medium")
        active = root / "ACTIVE"
        active.write_text("en_US-gone-medium.onnx\n")
        with unittest.mock.patch.object(self.voice, "VOICE_DIRS", (root,)):
            with unittest.mock.patch.object(self.voice, "ACTIVE_FILE", active):
                self.assertIsNone(self.voice.remembered_voice())
                self.assertEqual(self.voice.find_voice().name,
                                 "en_US-amy-medium.onnx")

    def test_an_ambiguous_choice_refuses_rather_than_guessing(self):
        root = self.fake_voices("en_US-amy-medium", "en_US-lessac-medium")
        with unittest.mock.patch.object(self.voice, "VOICE_DIRS", (root,)):
            with unittest.mock.patch.object(
                    self.voice, "ACTIVE_FILE", root / "ACTIVE"):
                with self.assertRaises(self.voice.VoiceError) as ctx:
                    self.voice.use_voice("medium")
        self.assertIn("matches 2 voices", str(ctx.exception))

    def test_an_unknown_choice_lists_what_is_installed(self):
        root = self.fake_voices("en_US-amy-medium")
        with unittest.mock.patch.object(self.voice, "VOICE_DIRS", (root,)):
            with self.assertRaises(self.voice.VoiceError) as ctx:
                self.voice.use_voice("klingon")
        self.assertIn("en_US-amy-medium.onnx", str(ctx.exception))

    def test_the_env_override_still_wins_over_a_remembered_choice(self):
        # YUZU_VOICE is the one-off escape hatch; it must beat the file.
        root = self.fake_voices("en_US-amy-medium", "en_US-lessac-medium")
        active = root / "ACTIVE"
        active.write_text("en_US-amy-medium.onnx\n")
        override = root / "en_US-lessac-medium.onnx"
        with unittest.mock.patch.object(self.voice, "VOICE_DIRS", (root,)):
            with unittest.mock.patch.object(self.voice, "ACTIVE_FILE", active):
                with unittest.mock.patch.dict(
                        os.environ, {self.voice.VOICE_ENV: str(override)}):
                    self.assertEqual(self.voice.find_voice(), override)

    def test_a_bad_voice_override_says_both_files_are_needed(self):
        # Piper's own error when the .json is missing does not mention
        # the .json, which is a genuinely miserable half hour.
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

    def test_the_transcript_names_whoever_is_actually_talking(self):
        """A whole conversation with the kuudere scrolled past labelled
        "YUZU SAYS". Third instance of the same class -- the name
        leaking out of the character it belongs to -- after the eval
        prompt and the missing-model error. This one hid longest
        because it is a print, not logic, so auditing runtime
        references missed it."""
        import contextlib, io
        real = yuzu.current_persona
        try:
            live_says = yuzu_personas.load(
                yuzu_personas.LIVE_PERSONA).name.upper() + " SAYS"
            for key, expected in ((yuzu_personas.LIVE_PERSONA, live_says),
                                  ("coco", "COCO SAYS")):
                yuzu.current_persona = yuzu_personas.load(key)
                buffer = io.StringIO()
                with contextlib.redirect_stdout(buffer):
                    yuzu.speak("Waiting for you to say something.")
                self.assertIn(expected, buffer.getvalue())
                if key == "coco":
                    self.assertNotIn("YUZU", buffer.getvalue())
        finally:
            yuzu.current_persona = real

    def test_no_persona_loaded_still_labels_the_line(self):
        # The echo stub runs with current_persona None. Never crash, and
        # never claim to be a character that isn't loaded.
        real = yuzu.current_persona
        try:
            yuzu.current_persona = None
            self.assertEqual(yuzu.speaker_name(), "ROBOT")
        finally:
            yuzu.current_persona = real

    def test_the_transcript_says_when_audio_did_not_play(self):
        """The old label carried this distinction ("YUZU SAYS" heard vs
        "TTS SAYS" printed) and it is worth keeping -- on a robot you
        are SSH'd into, it is how you tell a silent speaker from a
        silent robot."""
        import contextlib, io
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            yuzu.speak("No arms on this chassis.")
        self.assertIn("(text only)", buffer.getvalue())

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


class TestDayOneRunbook(unittest.TestCase):
    """NANO_DAY_ONE.md is the one page Ghost reads at the board, off a
    phone, with the box open. A stale command there costs an evening,
    and he has said plainly he does not read much of the project -- so
    the runbook has to be right without being cross-checked."""

    def setUp(self):
        self.doc = (Path(__file__).parent / "NANO_DAY_ONE.md").read_text()

    def test_the_throttle_reminder_is_impossible_to_miss(self):
        """It ships throttled with no symptom but slowness. This is the
        fourth place that reminder lives, and the first one he will
        actually open on day one."""
        self.assertIn("nvpmodel -m 0", self.doc)
        self.assertIn("jetson_clocks", self.doc)
        # Before the halfway mark, not buried in troubleshooting.
        self.assertLess(self.doc.index("nvpmodel -m 0") / len(self.doc), 0.5,
                        "the throttle reminder drifted too far down")

    def test_every_project_file_it_names_exists(self):
        named = set(re.findall(r'\b([A-Za-z_]+\.(?:py|md))\b', self.doc))
        here = Path(__file__).parent
        for name in sorted(named):
            self.assertTrue((here / name).exists(),
                            f"NANO_DAY_ONE.md sends him to {name}, "
                            f"which does not exist")

    def test_the_test_count_it_promises_is_the_real_one(self):
        """He is told a test count is the sign the software arrived
        intact. If that number is stale, a correct install looks
        broken -- and this repo has shipped a stale count in four
        places at once before. Self-referential on purpose: adding a
        test fails this until the runbook is updated too."""
        claimed = re.search(r'\*\*(\d+) tests', self.doc)
        self.assertIsNotNone(claimed, "the runbook stopped naming a count")
        loader = unittest.TestLoader()
        actual = loader.loadTestsFromModule(sys.modules[__name__]).countTestCases()
        self.assertEqual(int(claimed.group(1)), actual,
                         "NANO_DAY_ONE.md promises a stale test count")

    def test_it_uses_the_model_name_he_will_actually_have(self):
        # The Ollama model is named after the HF path, not "yuzu". A
        # runbook that says `--model yuzu` fails on a fresh board.
        self.assertIn("grep -i heretic", self.doc)
        self.assertNotIn("YUZU_MODEL=yuzu ", self.doc)

    def test_it_is_honest_about_what_is_unverified(self):
        """Two things in it have never run on real hardware: piper on
        arm64, and the doctor's Jetson section. Saying so is what stops
        a failure there reading as "I broke it"."""
        lowered = self.doc.lower()
        self.assertIn("unverified", lowered)
        self.assertIn("never run on real hardware", lowered)


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
                'Environment="OLLAMA_KEEP_ALIVE=30m"\n'
                'Environment="OLLAMA_NUM_PARALLEL=1" "OLLAMA_FLASH_ATTENTION=1"\n')
        with self.fake_read({"/etc/systemd/system/ollama.service": unit}):
            env = self.doctor.ollama_service_env()
        self.assertEqual(env["OLLAMA_KEEP_ALIVE"], "30m")
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


class TestWikiNamespace(unittest.TestCase):
    """THE `/wiki` BUG, and it was the parser as predicted.

    Ghost, Sept 10: *"she cant access the wiki and i dont think i can
    either in that sense"* -- `/wiki cats` came back "Nothing in the
    archive about 'cats'" in three seconds, so the server ANSWERED and
    the lookup found nothing in what it said."""

    import yuzu_wiki as wiki

    MODERN = ('<a href="/skin/x.css">s</a>'
              '<a href="/content/wikipedia_en_simple/Cat">Cat</a>')
    OLD = '<a href="/wikipedia/A/Cat">Cat</a>'

    def test_the_A_namespace_is_no_longer_REQUIRED(self):
        """The old regex demanded `/A/`, and modern ZIMs do not have it
        -- articles live at `/content/<book>/<Article>` with nothing in
        between. A search that worked returned links the parser could
        not see, and the miss read as a missing article rather than as a
        parser that had stopped matching."""
        self.assertTrue(self.wiki._article_links(self.MODERN),
                        "a modern kiwix article link is still invisible")

    def test_the_OLD_shape_still_works(self):
        """His board's version is unknown and cannot be pinned, so the
        fix must not trade one era for the other."""
        self.assertTrue(self.wiki._article_links(self.OLD))

    def test_furniture_is_not_mistaken_for_an_article(self):
        for junk in ('<a href="/skin/style.css">x</a>',
                     '<a href="/search?pattern=cat">x</a>',
                     '<a href="/catalog/v2/entries">x</a>',
                     '<a href="https://example.com/content/x/Cat">x</a>'):
            self.assertEqual(self.wiki._article_links(junk), [], junk)

    def test_there_is_a_ONE_WORD_diagnostic(self):
        """The twelve-line diagnostic that would have settled this a day
        earlier was pasted into HER CHAT instead of the shell, and that
        is what started the night with no way out. `~/YUZU/wiki --test`
        is the same information without a paste."""
        self.assertTrue(hasattr(self.wiki, "diagnose"))
        script = (Path(__file__).parent / "wiki").read_text()
        self.assertIn("--test", script, "no one-word diagnostic")

    def test_the_diagnostic_leads_with_the_VERDICT(self):
        """MEASURED ON HIS BOARD, Sept 10, and it was mine end to end.

            server:   answering on http://127.0.0.1:8080
            book:     wikipedia_en_simple_all
            suggest:  FAILED (HTTP Error 404: Not Found)
            search:   24984 bytes, 25 article links
            result:   25 paths  first: /content/.../Munchkin_cat

        It WORKED -- 25 articles. `suggest` 404s because his kiwix build
        does not have that endpoint and the fallback covered it. He read
        the whole thing as broken, and said so: "says failed but
        sometimes it be lyin".

        Third time in this project I have reported the layers AROUND the
        answer and put the answer last: `pad --status` on a working
        controller, `face` on a serving server, now this."""
        import http.server, threading, importlib
        table = {"/": "<html>x</html>",
                 "/search": '<a href="/content/book_2026/Cat">Cat</a>'}

        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                key = self.path.split("?")[0]
                body = table.get(self.path) or table.get(key) or ""
                self.send_response(200 if body else 404)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body.encode())

            def log_message(self, *a):
                pass

        srv = http.server.HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        old_base, old_book = self.wiki.BASE, self.wiki._BOOK
        self.wiki.BASE = "http://127.0.0.1:%d" % srv.server_port
        self.wiki._BOOK = None
        try:
            lines = self.wiki.diagnose()
        finally:
            # BOTH of them. The first version put BASE back and left
            # _BOOK pointing at a stub server's book name.
            self.wiki.BASE, self.wiki._BOOK = old_base, old_book
            srv.shutdown()
        self.assertIn("WORKING", lines[0],
                      f"the verdict is not first: {lines[0]!r}")
        joined = " ".join(lines)
        self.assertLess(joined.index("WORKING"), joined.index("FAILED"),
                        "an alarming line about an unused endpoint comes "
                        "above the answer -- which is how he read a "
                        "working wiki as broken")

    def test_the_book_is_learned_from_a_real_article_path(self):
        """His catalog said `wikipedia_en_simple_all` while the articles
        actually live under `wikipedia_en_simple_all_nopic_2026-05` --
        close enough to look right, wrong enough that every scoped query
        would miss. A path that exists is ground truth; a catalogue
        entry is a claim."""
        with unittest.mock.patch.object(self.wiki, "_BOOK", "wrong_name"):
            links = self.wiki._article_links(
                '<a href="/content/the_real_book_2026/Cat">Cat</a>')
            self.assertTrue(links)
        body = (Path(__file__).parent / "yuzu_wiki.py").read_text()
        self.assertIn("LEARN THE BOOK FROM THE ANSWER", body,
                      "the book name is still only ever the catalog's")

    def test_the_diagnostic_never_raises_with_no_server(self):
        """It runs precisely when things are broken, so it has to be the
        one thing that cannot add a traceback to his screen."""
        old = self.wiki.BASE
        try:
            self.wiki.BASE = "http://127.0.0.1:1"
            lines = self.wiki.diagnose()
        finally:
            self.wiki.BASE = old
        self.assertTrue(lines)
        self.assertIn("~/YUZU/wiki", " ".join(lines),
                      "it does not say how to start the server")


class TestPull(unittest.TestCase):
    """`pull` -- get the latest, and SAY whether it worked.

    MEASURED, Sept 10, four seconds after he logged in:

        fatal: unable to access '.../YUZU.git/': server certificate
        verification failed. CAfile: none CRLfile: none

    He then ran `face`, got the OLD art, and asked why the new faces had
    not arrived. They had not arrived because the pull FAILED -- but the
    failure scrolled past above a wall of Ubuntu login banner and the
    next command printed a cheerful "UP. Open this on your phone."

    A failed update that looks like a successful one costs a whole
    session wondering why nothing changed."""

    SCRIPT = Path(__file__).parent / "pull"

    def _with_git(self, script_body, timeout=90):
        import subprocess
        tmp = tempfile.mkdtemp()
        try:
            binv = Path(tmp) / "bin"
            binv.mkdir()
            (binv / "git").write_text(script_body)
            (binv / "git").chmod(0o755)
            done = subprocess.run(
                ["bash", str(self.SCRIPT)], capture_output=True, text=True,
                timeout=timeout,
                env=dict(os.environ, YUZU_PULL_WAITS="0",
                         PATH=f"{binv}:{os.environ['PATH']}"))
            return done
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    TLS_FAIL = ('#!/bin/bash\ncase "$*" in\n'
                '"rev-parse HEAD") echo abc ;;\n'
                '"pull origin main") echo "fatal: unable to access: server '
                'certificate verification failed. CAfile: none" >&2; exit 128 ;;\n'
                '*) exit 0 ;;\nesac\n')

    def test_it_is_valid_shell_and_executable(self):
        import subprocess
        self.assertTrue(os.access(self.SCRIPT, os.X_OK))
        done = subprocess.run(["bash", "-n", str(self.SCRIPT)],
                              capture_output=True)
        self.assertEqual(done.returncode, 0, done.stderr.decode())

    def test_a_failed_pull_is_LOUD_and_exits_nonzero(self):
        """The whole point. His terminal showed the failure and then a
        happy message from the next command, so it read as success."""
        done = self._with_git(self.TLS_FAIL)
        self.assertEqual(done.returncode, 1, "a failed pull looked fine")
        self.assertIn("PULL FAILED", done.stdout)
        self.assertIn("Nothing was updated", done.stdout)

    def test_a_certificate_failure_names_the_CLOCK(self):
        """CONFIRMED on the board rather than theorised. The Orin devkit
        has no RTC battery, so every boot starts at the epoch and a
        certificate cannot be valid before it was issued. The window is
        the first minute of uptime -- exactly when someone who just
        booted is typing.

        Naming the cause is the difference between a thirty-second wait
        and an evening debugging TLS."""
        done = self._with_git(self.TLS_FAIL)
        self.assertIn("clock", done.stdout.lower(),
                      "it did not name the one cause it can be sure of")

    def test_the_verdict_comes_first(self):
        """Same rule `pad --status` had to learn: the answer goes above
        the evidence, not under it."""
        done = self._with_git(self.TLS_FAIL)
        text = done.stdout
        self.assertIn("PULL FAILED", text)
        # Progress lines are fine. What must not happen is the raw git
        # error appearing ABOVE the verdict -- that is the shape his
        # terminal already had, and he read it as success.
        self.assertLess(text.index("PULL FAILED"), text.index("fatal:"),
                        "the verdict is buried under the git output")

    def test_it_says_when_HER_FACE_changed(self):
        """The art is what he notices, and a cached page will show the
        old faces after a successful pull -- which is the same confusion
        all over again, one layer up."""
        self.assertIn("ui/sprites/", self.SCRIPT.read_text())
        self.assertIn("reload", self.SCRIPT.read_text().lower())


class TestDeckSetup(unittest.TestCase):
    """`deck` -- one word, get ready for the screen.

    Ghost, Sept 10: *"i really want soooome plug and play in case i make
    enough for an adapter before the next expected time."* He is about
    to be a week without anyone to ask, so every failure here has to
    name its own fix."""

    SCRIPT = Path(__file__).parent / "deck"
    APPS = Path(__file__).parent / "deckapps"

    def _stub_run(self, script, have=(), extra=None):
        import subprocess
        tmp = tempfile.mkdtemp()
        binv, home = Path(tmp) / "bin", Path(tmp) / "home"
        binv.mkdir(); home.mkdir()
        for name in have:
            (binv / name).write_text("#!/bin/bash\nexit 0\n")
            (binv / name).chmod(0o755)
        env = {"PATH": f"{binv}:/usr/bin:/bin", "HOME": str(home)}
        done = subprocess.run(["bash", str(script)] + list(extra or []),
                              capture_output=True, text=True, env=env,
                              timeout=60)
        return done, home, tmp

    def test_it_is_valid_shell_and_executable(self):
        import subprocess
        self.assertTrue(os.access(self.SCRIPT, os.X_OK))
        done = subprocess.run(["bash", "-n", str(self.SCRIPT)],
                              capture_output=True)
        self.assertEqual(done.returncode, 0, done.stderr.decode())

    def test_check_never_changes_anything(self):
        """He has to be able to look without committing to anything."""
        done, home, tmp = self._stub_run(self.SCRIPT, extra=["--check"])
        try:
            self.assertEqual(list(home.rglob("*.desktop")), [],
                             "--check installed something")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_every_missing_piece_names_its_own_fix(self):
        """A week with nobody to ask. 'MISSING' on its own is a dead end;
        the apt line beside it is the whole difference."""
        done, home, tmp = self._stub_run(self.SCRIPT, extra=["--check"])
        try:
            for line in done.stdout.splitlines():
                if "MISSING" in line:
                    self.assertTrue("apt install" in line or "git pull" in line,
                                    f"no fix given: {line.strip()}")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_it_refuses_to_install_icons_with_no_browser(self):
        """An icon that opens nothing reads as a broken deck rather than
        as a missing package -- so stop, and say which package."""
        done, home, tmp = self._stub_run(self.SCRIPT)
        try:
            self.assertEqual(done.returncode, 1)
            self.assertIn("chromium", done.stdout)
            self.assertEqual(list(home.rglob("*.desktop")), [],
                             "it installed icons that cannot open")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestDeckAppsPaths(unittest.TestCase):
    """The bug that made `deck` worth writing.

    `deckapps` had NEVER BEEN RUN on that board. Running it for the
    first time, it hardcoded `$HOME/YUZU`, failed to write its wrapper
    scripts, installed every icon pointing at a file that did not
    exist -- and still printed "Done." Tapping them would have done
    nothing, a week from any help."""

    SCRIPT = Path(__file__).parent / "deckapps"

    def test_it_finds_itself_rather_than_assuming_a_path(self):
        body = self.SCRIPT.read_text()
        self.assertNotIn('YUZU="$HOME/YUZU"', body,
                         "the one path that cannot be assumed is assumed")
        self.assertIn('dirname "$0"', body)

    def test_a_dead_icon_is_REMOVED_not_installed(self):
        """The failure was not that something was missing -- it is that
        the output said Done. An icon whose target is not there looks
        installed, does nothing when tapped, and gives him no clue."""
        import subprocess
        tmp = tempfile.mkdtemp()
        try:
            fake, binv, home = (Path(tmp) / "y", Path(tmp) / "bin",
                                Path(tmp) / "home")
            fake.mkdir(); binv.mkdir(); home.mkdir()
            shutil.copy(self.SCRIPT, fake / "deckapps")
            (fake / "ui").mkdir()
            # `gba` deliberately absent -- that icon must not survive.
            for name in ("chromium", "xterm"):
                (binv / name).write_text("#!/bin/bash\nexit 0\n")
                (binv / name).chmod(0o755)
            done = subprocess.run(["bash", str(fake / "deckapps")],
                                  capture_output=True, text=True, timeout=60,
                                  env={"PATH": f"{binv}:/usr/bin:/bin",
                                       "HOME": str(home)})
            installed = {p.name for p in home.rglob("*.desktop")}
            self.assertNotIn("yuzu-gba.desktop", installed,
                             "a dead icon was left for him to tap")
            self.assertIn("BROKEN", done.stdout, "it did not say which")
            self.assertNotIn("Done. The icons", done.stdout,
                             "it claimed success with an icon missing")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestArtConversion(unittest.TestCase):
    """`yuzu_art.py` -- white background out, line art in.

    Ghost, Sept 10: "Write a Python function using PIL/Pygame that
    converts white pixels to transparent alpha when loading the images
    into memory, so we don't have to edit the backgrounds manually."
    Then, on the grey shading: "color not needed." """

    import yuzu_art as art

    RAW = Path(__file__).parent / "ui" / "raw"
    SPRITES = Path(__file__).parent / "ui" / "sprites"

    def _paper(self, w=40, h=40, mark=(10, 10)):
        """A white page with one black mark on it."""
        px = bytearray([255, 255, 255, 255] * (w * h))
        i = (mark[1] * w + mark[0]) * 4
        px[i:i + 4] = bytes((0, 0, 0, 255))
        return w, h, px

    def test_white_becomes_transparent_and_ink_becomes_black(self):
        w, h, px = self._paper()
        _, _, out = self.art.to_transparent(w, h, px)
        self.assertEqual(out[3], 0, "the paper is still opaque")
        i = (10 * w + 10) * 4
        self.assertEqual(out[i + 3], 255, "the drawing was erased")
        self.assertEqual(tuple(out[i:i + 3]), (0, 0, 0), "ink is not black")

    def test_alpha_RAMPS_so_curves_do_not_go_jagged(self):
        """A hard cutoff turns every anti-aliased edge into a staircase,
        and her line work is nothing but curves. The grey between paper
        and ink has to survive as partial alpha."""
        w, h, px = self._paper()
        mid = self.art.WHITE_AT - (self.art.WHITE_AT - self.art.INK_AT) // 2
        px[0:4] = bytes((mid, mid, mid, 255))
        _, _, out = self.art.to_transparent(w, h, px)
        self.assertGreater(out[3], 40, "mid-grey vanished; edges will be hard")
        self.assertLess(out[3], 215, "mid-grey went solid; edges will be fat")

    def test_a_transparent_border_is_NOT_a_screenshot_bar(self):
        """THIS BUG ATE blink.png AND LEFT ONE PIXEL.

        `strip_bars` removes the black and grey letterboxing his phone
        gallery puts around a picture. The first version asked only about
        BRIGHTNESS -- and the RGB underneath a transparent pixel is
        usually black, so on art that was already a sprite every
        transparent border row read as a solid black bar and the crop ate
        the whole image. 485x460 in, 1x1 out.

        A transparent edge is nothing being there. It is not furniture."""
        w = h = 30
        px = bytearray(w * h * 4)               # fully transparent
        i = (15 * w + 15) * 4
        px[i:i + 4] = bytes((0, 0, 0, 255))     # one real mark
        nw, nh, out = self.art.strip_bars(w, h, px)
        self.assertEqual((nw, nh), (w, h),
                         "a transparent border was cropped as a bar")

    def test_a_real_bar_IS_removed(self):
        """The second version of this test's subject: uniformity was the
        wrong question, because JPEG noise beat it -- a grey chrome strip
        survived, defined the bounding box, and her face rendered small
        and off-centre with a stray line beside it. That is exactly how
        it looked on the page.

        Every row of real line art crosses white paper somewhere. A
        letterbox never does, however noisy it is."""
        w = h = 40
        px = bytearray([255, 255, 255, 255] * (w * h))
        for y in range(h):                      # noisy grey bar, 3 wide
            for x in range(3):
                g = 120 + ((x * 7 + y * 13) % 40)
                i = (y * w + x) * 4
                px[i:i + 4] = bytes((g, g, g, 255))
        px[(20 * w + 20) * 4:(20 * w + 20) * 4 + 4] = bytes((0, 0, 0, 255))
        nw, _, _ = self.art.strip_bars(w, h, px)
        self.assertEqual(nw, w - 3, "the noisy bar survived the crop")

    def test_every_sprite_is_SQUARE(self):
        """What makes it look smooth. The page scales each sprite into
        one square box with object-fit: contain, so a wide sprite renders
        SMALLER -- her face visibly jumps size when the expression
        changes, or every few seconds when she blinks. Cropped tight, his
        four came out between 1.09 and 1.51 wide."""
        for f in sorted(self.SPRITES.glob("*.png")):
            if ".paint" in f.name:
                continue
            got = self.art.load_rgba(str(f))
            self.assertTrue(got, f"{f.name} will not load")
            w, h, _ = got
            self.assertEqual(w, h, f"{f.name} is {w}x{h}, not square")

    def test_no_sprite_was_reduced_to_nothing(self):
        """The blink disaster, guarded from the other end: whatever the
        conversion does, real art has to come out the far side."""
        for f in sorted(self.SPRITES.glob("*.png")):
            if ".paint" in f.name:
                continue
            w, h, px = self.art.load_rgba(str(f))
            inked = sum(1 for i in range(3, len(px), 4) if px[i] > 12)
            self.assertGreater(w, 200, f"{f.name} was cropped to {w}x{h}")
            self.assertGreater(inked, 2000, f"{f.name} has almost no art")

    def test_no_sprite_still_has_a_white_background(self):
        """The whole point. A sprite that kept its paper shows as a white
        card on the neon background instead of as her face."""
        for f in sorted(self.SPRITES.glob("*.png")):
            if ".paint" in f.name:
                continue
            w, h, px = self.art.load_rgba(str(f))
            self.assertFalse(self.art.looks_like_paper(w, h, px),
                             f"{f.name} still has a white background")

    def test_PIL_is_optional_and_the_import_is_guarded(self):
        """He asked for PIL and PIL is right -- the stdlib cannot read
        the JPEGs his phone gallery makes. But "installs nothing" is what
        lets the brain run in Pydroid on that phone, so this is a
        workbench tool whose OUTPUT is a plain PNG. The deck never needs
        PIL to show her face."""
        body = (Path(__file__).parent / "yuzu_art.py").read_text()
        self.assertIn("try:", body.split("from PIL")[0][-120:],
                      "the PIL import is not guarded")
        face = (Path(__file__).parent / "yuzu_face.py").read_text()
        self.assertNotIn("PIL", face,
                         "the runtime now depends on PIL, which ends the "
                         "phone property")

    def test_the_raw_art_is_kept_so_it_can_be_redone(self):
        """His originals live in ui/raw/ and the conversion is one
        command with no arguments. A lossy step whose input was thrown
        away can never be improved on."""
        self.assertTrue(list(self.RAW.glob("*")),
                        "the raw drawings were not kept")


class TestSheReacts(unittest.TestCase):
    """Her face knows what she is doing.

    It was a picture until now -- it did not know she existed. The brain
    writes what it is doing to a file, the server serves it, the page
    asks. `thinking` is the whole point: every frustration in this
    project's log is "is it working or is it stuck", and a face that
    visibly thinks answers that with no status text."""

    import yuzu_face as face

    PAGE = Path(__file__).parent / "ui" / "face.html"

    def setUp(self):
        self.face.set_state("idle")

    def tearDown(self):
        # Leave her idle. A test that ends with the state file saying
        # `thinking` makes the NEXT thing that reads it wrong, and this
        # class is the one that would have caused it.
        self.face.set_state("idle")

    def test_state_crosses_between_processes(self):
        """The brain and the server are separate processes -- he starts
        the chat in his terminal and the page is served here -- so a
        file is the right size for the boundary. No socket to fail, no
        order to get right."""
        self.face.set_state("thinking")
        self.assertEqual(self.face.get_state()["state"], "thinking")
        self.face.set_state("talking", "Hmph.")
        got = self.face.get_state()
        self.assertEqual(got["state"], "talking")
        self.assertEqual(got["said"], "Hmph.")

    def test_a_stale_state_reads_as_idle(self):
        """A chat that died mid-reply must not leave her frozen mid-
        thought forever."""
        import json, time
        with open(self.face.STATE_FILE, "w") as fh:
            json.dump({"state": "thinking", "said": "",
                       "at": time.time() - 9999}, fh)
        self.assertEqual(self.face.get_state()["state"], "idle")

    def test_setting_state_NEVER_raises(self):
        """It is called from the reply path. A face that cannot be
        updated must never be able to stop her talking -- the same rule
        Piper and the wiki import already follow."""
        old = self.face.STATE_FILE
        try:
            self.face.STATE_FILE = "/nope/not/a/place/state"
            self.face.set_state("thinking")      # must not raise
        finally:
            self.face.STATE_FILE = old
        self.face.set_state("not-a-real-state")  # must not raise

    def test_the_brain_telling_the_face_is_GUARDED(self):
        """Same shape as Piper's import. The face is a nicety; the reply
        is the product."""
        import yuzu_brain
        brain = yuzu_brain.YuzuBrain.__new__(yuzu_brain.YuzuBrain)
        with unittest.mock.patch.dict("sys.modules", {"yuzu_face": None}):
            brain._face("thinking")              # must not raise
        body = (Path(__file__).parent / "yuzu_brain.py").read_text()
        self.assertIn("except Exception:", body.split("def _face")[1][:400],
                      "the face call is not swallowed")

    def test_both_reply_paths_report_thinking_then_talking(self):
        body = (Path(__file__).parent / "yuzu_brain.py").read_text()
        for path in ("def ask(", "def ask_stream("):
            chunk = body.split(path)[1].split("\n    def ")[0]
            self.assertIn('_face("thinking")', chunk,
                          f"{path} never says she is thinking")
            self.assertIn('_face("talking"', chunk,
                          f"{path} never says she is talking")

    def test_the_server_is_THREADED(self):
        """Not optional. One reply takes tens of seconds on that board,
        and a single-threaded server would stop answering /state for the
        whole time -- so her face would freeze exactly when it most
        needs to say `thinking`. Verified live as well: /state answered
        `thinking` mid-generation."""
        body = (Path(__file__).parent / "yuzu_face.py").read_text()
        self.assertIn("ThreadingHTTPServer", body)

    def test_an_empty_message_never_reaches_the_model(self):
        reply, error = self.face.answer("")
        self.assertIsNone(reply)

    # ---- the UI he asked to be quieter -------------------------------

    def test_there_are_no_expression_buttons(self):
        """Ghost: "remove the visual clues i can change her expression i
        want that automatic." The brain drives her face now, so a row of
        buttons offering to do it by hand advertised the wrong thing --
        and it also overlapped the speech bubble and cut her chin off,
        which a screenshot caught."""
        page = self.PAGE.read_text()
        self.assertNotIn('id="states"', page, "the expression chips are back")

    def test_she_can_be_talked_to_from_the_page(self):
        page = self.PAGE.read_text()
        self.assertIn("'say'", page, "there is no way to talk to her")
        self.assertIn('id="says"', page, "there is nowhere for her reply")


class TestWikiBrevity(unittest.TestCase):
    """The Munchkin reply ran three paragraphs and truncated."""

    import yuzu_wiki as wiki

    def test_the_lookup_turn_asks_for_a_short_answer(self):
        """Measured Sept 10: asked about Munchkin cats she gave three
        paragraphs and was cut mid-sentence by num_predict. The turn
        asked for "your own words" and said nothing about how MANY,
        while her brevity rule is about ordinary conversation.

        A reply that long also does not fit a 1024x600 face screen,
        which is why the UI work and the brevity work are one problem.

        One variable, no code, no persona edit -- so no A/B was
        invalidated and nothing needs re-composing."""
        # PATCHED, not assigned. The first version replaced look_up on
        # the module and never put it back, which broke five unrelated
        # wiki tests further down the run -- test pollution, and it
        # looked like the wiki itself had regressed.
        with unittest.mock.patch.object(
                self.wiki, "look_up",
                lambda *a, **k: ("Cat", "A small animal.")):
            turn, error = self.wiki.as_context("cat")
        self.assertIsNone(error)
        self.assertIn("sentence or two", turn)
        # and it is still a USER turn, which is the load-bearing part
        self.assertIn("I looked up", turn)

    def test_num_predict_was_NOT_raised(self):
        """Already recorded: the truncation is a symptom of rambling and
        a bigger ceiling just buys longer rambles."""
        import re as _re
        for f in sorted((Path(__file__).parent / "personas").glob("*.persona")):
            for found in _re.findall(r"num_predict:\s*(\d+)", f.read_text()):
                self.assertLessEqual(int(found), 200,
                                     f"{f.name} raised num_predict to {found}")


class TestVPet(unittest.TestCase):
    """The creature on the deck.

    Ghost asked for a Tamagotchi-ish page and then immediately drew the
    important line: *"dont make him require food id like it to be more
    of an interactive bare bones game almost. not a babysitting program
    per se (on the surface sure)."* Most of what follows pins that."""

    import yuzu_vpet as vpet

    PAGE = Path(__file__).parent / "ui" / "vpet.html"

    def setUp(self):
        self._real = self.vpet.STATE_FILE
        self._tmp = tempfile.mkdtemp()
        self.vpet.STATE_FILE = os.path.join(self._tmp, "vpet.json")

    def tearDown(self):
        self.vpet.STATE_FILE = self._real
        shutil.rmtree(self._tmp, ignore_errors=True)

    # ---- the whole point --------------------------------------------

    def test_nothing_gets_WORSE_for_being_ignored(self):
        """NO NEEDS, NO FAIL STATE. Mood drifts toward NEUTRAL from
        either side, so a week away leaves him quiet rather than
        starving -- and bond, which is the thing that will drive
        evolution later, never moves at all. A toy you owe nothing to
        was the request; this is the assertion that keeps it one."""
        now = time.time()
        self.vpet.do("play", now)
        self.vpet.do("play", now)
        before = self.vpet.look(now)
        self.assertGreater(before["mood"], self.vpet.NEUTRAL)

        week = self.vpet.look(now + 7 * 86400)
        self.assertEqual(week["mood"], self.vpet.NEUTRAL,
                         "mood drifted past neutral -- that is a needs bar")
        self.assertGreaterEqual(week["bond"], before["bond"],
                                "time away took bond off him")
        self.assertNotIn(week["state"], ("dead", "dying"))
        # and from BELOW neutral it comes back up, unprompted
        low = self.vpet.look(now)
        self.vpet._write(dict(self.vpet._read(), mood=10, at=now))
        self.assertGreater(self.vpet.look(now + 20 * 3600)["mood"], 10,
                           "a low mood never recovers on its own")

    def test_there_is_no_hunger_anywhere_in_the_model(self):
        """"dont make him require food". Not softened, not renamed --
        absent. A stat that exists is a stat something will eventually
        be built on top of.

        THIS ASSERTS THE MODEL, NOT THE PROSE. The first version grepped
        the source for "hunger" and failed on the comment that EXPLAINS
        why there is no hunger -- the same false positive as "remaining"
        in the runtime note and "no hype" in Coco's rule. Grepping
        source text is a proxy; the state file is the fact."""
        self.assertEqual(
            sorted(k for k in self.vpet.FRESH if k not in
                   ("born", "at", "who", "pokes", "grumpy_until")),
            ["bond", "mood", "sleeping"],
            "a new stat appeared, and every stat is a future chore")
        self.assertNotIn("feed", [a.lower() for a in self.vpet.ACTIONS])
        buttons = re.findall(r'data-do="([a-z]+)"', self.PAGE.read_text())
        self.assertNotIn("feed", buttons, "there is a Feed button")
        self.assertTrue(set(buttons) <= set(self.vpet.ACTIONS),
                        f"the page offers {buttons}, the deck allows "
                        f"{self.vpet.ACTIONS}")

    def test_grumpy_is_a_REACTION_and_it_wears_off(self):
        """The one negative in the whole thing, and it is a character
        beat rather than a punishment: poke him enough and he is fed up
        for a minute. Nothing has to be won back."""
        now = time.time()
        for _ in range(self.vpet.POKES_BEFORE_GRUMPY):
            got = self.vpet.do("poke", now)
        self.assertEqual(got["state"], "sad")
        later = self.vpet.look(now + self.vpet.GRUMPY_FOR + 1)
        self.assertNotEqual(later["state"], "sad",
                            "being fed up is permanent, which is a sulk")

    def test_only_the_allowlisted_actions_can_ever_run(self):
        """Same discipline as /launch/: a NAME crosses and nothing else.
        The server binds 0.0.0.0, so this route must never be able to
        take a path, an argument or a folder name from a request."""
        for hostile in ("", "eat", "../../etc/passwd", "swap; rm -rf /",
                        "poke ", "PLAY", "who/demon"):
            self.assertIsNone(self.vpet.do(hostile),
                              f"{hostile!r} was allowed to run")
        self.assertEqual(sorted(self.vpet.ACTIONS),
                         ["play", "poke", "rest", "swap"])

    # ---- the art pipeline -------------------------------------------

    def test_a_sprite_STRIP_is_counted_without_being_sliced(self):
        """The packs ship one PNG per animation -- 600x100 is six cels.
        A width that is an exact multiple of the height IS that many
        frames, so the file out of the zip is the file that runs: no
        slicing step, no generated art, no PIL on the deck."""
        with tempfile.TemporaryDirectory() as tmp:
            import yuzu_face
            yuzu_face.write_rgba(os.path.join(tmp, "idle.png"),
                                 300, 50, bytearray(300 * 50 * 4))
            yuzu_face.write_rgba(os.path.join(tmp, "sleep.png"),
                                 50, 50, bytearray(50 * 50 * 4))
            got = self.vpet.frames(tmp)
        self.assertEqual(len(got["idle"]), 6, "a 300x50 strip is six cels")
        self.assertEqual(got["idle"][0], ["vpet/idle.png", 0, 6])
        self.assertEqual(got["idle"][5], ["vpet/idle.png", 5, 6])
        self.assertEqual(len(got["sleep"]), 1, "a square file is one cel")

    def test_the_packs_own_filenames_are_accepted(self):
        """`Demon_A_Idle.png` reads as `idle`. Making him rename
        fourteen files before anything appears on screen is the kind of
        friction that stops a thing being used -- the same call as
        recognising /wiki anywhere in a line rather than only at the
        start."""
        for stem, want in (("idle", ("idle", 0)),
                           ("Demon_A_Idle", ("idle", 0)),
                           ("Blood Monster_A_Walk", ("walk", 0)),
                           ("walk_2", ("walk", 2)),
                           ("Demon_A_Walk_3", ("walk", 3))):
            self.assertEqual(self.vpet._state_of(stem), want, stem)

    def test_a_folder_is_a_character_and_one_button_cycles_them(self):
        """Ghost: "can you add the orc as an option to select from."
        Adding a fifth creature is copying PNGs into a new folder --
        there is no list, no menu and no code to touch."""
        everyone = self.vpet.cast()
        self.assertIn("demon", everyone)
        self.assertIn("orc", everyone)
        for who, states in everyone.items():
            self.assertIn("idle", states, f"{who} cannot stand still")
            for cel in states["idle"]:
                self.assertTrue(cel[0].startswith("vpet/" + who + "/"),
                                f"{who} asks for {cel[0]}, which is not "
                                "inside its own folder")
        now = time.time()
        first = self.vpet.look(now)["who"]
        second = self.vpet.do("swap", now)["who"]
        self.assertNotEqual(first, second)
        # and it is a CYCLE, so it always comes back
        for _ in range(len(everyone) - 1):
            self.vpet.do("swap", now)
        self.assertEqual(self.vpet.look(now)["who"], first)

    def test_a_character_that_was_deleted_falls_back_rather_than_blanks(self):
        """A remembered folder that is no longer there must not leave an
        empty room. Same call yuzu_voice makes about a voice that was
        uninstalled: fall back, never go silent."""
        now = time.time()
        self.vpet._write(dict(self.vpet._read(), who="a-thing-that-left",
                              at=now))
        got = self.vpet.look(now)
        self.assertIn(got["who"], got["cast"])
        self.assertTrue(got["frames"], "the room came back empty")

    # ---- the rules this deck has already paid for --------------------

    def test_the_state_file_is_OUTSIDE_the_repo(self):
        """Not tidiness. A file inside the repo is a local change, and
        `~/YUZU/pull` stops on local changes rather than overwriting
        them -- so his pet's mood would have blocked every update he
        ever ran."""
        self.assertNotIn(str(Path(__file__).parent), self._real,
                         "the pet writes into the repo")
        self.assertIn(".yuzu", self._real)

    def test_the_pet_page_always_has_a_way_out(self):
        """The rule two power cycles paid for. A colourful page with no
        exit is still a page with no exit."""
        page = self.PAGE.read_text()
        self.assertIn('id="home"', page, "there is no way off this page")
        self.assertIn("home.html", page)

    def test_the_pet_page_is_the_ONE_allowed_to_be_in_colour(self):
        """Everything else on the deck is green on black, permanently.
        This page is the deliberate exception -- "its own little world"
        -- so it must NOT inherit the CRT palette, and no other page may
        start quietly borrowing its colours."""
        page = self.PAGE.read_text()
        self.assertNotIn("#39ff5e", page,
                         "the pet page went green like everything else")
        for other in ("face.html", "home.html"):
            body = (Path(__file__).parent / "ui" / other).read_text()
            self.assertIn("#39ff5e", body, f"{other} lost the CRT ink")

    def test_the_pet_is_a_nicety_and_cannot_take_her_face_down(self):
        """Same guard as Piper and the wiki. If yuzu_vpet.py is missing
        or broken the face server keeps serving her face -- the reply is
        the product, the pet is not."""
        import yuzu_face
        body = (Path(__file__).parent / "yuzu_face.py").read_text()
        block = body.split("def _pet_look(")[1].split("def _pet_do(")[0]
        self.assertIn("except Exception", block, "the import is not guarded")
        with unittest.mock.patch.dict("sys.modules", {"yuzu_vpet": None}):
            got = yuzu_face._pet_look()
        self.assertEqual(got["frames"], {})
        self.assertTrue(got["says"], "it fails without saying anything")


class TestTelemetry(unittest.TestCase):
    """The chip under her chin: power mode, temperature, tokens/sec.

    It earns its pixels for one reason above the others -- **the Orin
    ships THROTTLED and forgetting `sudo nvpmodel -m 0` makes everything
    slow with no visible cause.** That reminder already lives in the
    README, the doctor and the boot line; this is the first place it is
    visible without running anything."""

    import yuzu_face as face
    import yuzu_brain as brain

    PAGE = Path(__file__).parent / "ui" / "face.html"

    def test_nothing_readable_means_no_badge_at_all(self):
        """On his phone and on any laptop there is no nvpmodel status and
        no thermal zone. An empty chip saying nothing is the same fault
        as `pad --status` reporting on the layers around the answer, so
        a field that cannot be read is ABSENT."""
        with tempfile.TemporaryDirectory() as tmp:
            with unittest.mock.patch.object(self.face, "THERMAL", tmp):
                with unittest.mock.patch.object(self.face, "power_mode",
                                                lambda: None):
                    with unittest.mock.patch.object(
                            self.face, "get_state", lambda: {"state": "idle"}):
                        self.assertEqual(self.face.stats(), {})
        page = self.PAGE.read_text()
        shown = page.split("badge.classList.toggle('on',")[1].split(";")[0]
        self.assertIn("board.textContent", shown)
        self.assertIn("batt", shown,
                      "the chip ignores the battery when deciding to show")
        self.assertNotIn("true", shown,
                         "an empty badge would still be drawn")

    def test_a_throttled_board_says_the_command_not_the_number(self):
        """"mode 1" is a number he has to interpret, and a number he has
        to interpret is a number he will ignore. This is the fourth
        place the reminder lives and the only one that appears without
        being asked for."""
        with unittest.mock.patch.object(self.face, "power_mode",
                                        lambda: (1, "mode 1")):
            with unittest.mock.patch.object(self.face, "temperature",
                                            lambda: 44):
                got = self.face.stats()
        self.assertIn("nvpmodel -m 0", got.get("throttled", ""))
        with unittest.mock.patch.object(self.face, "power_mode",
                                        lambda: (0, "MAXN")):
            with unittest.mock.patch.object(self.face, "temperature",
                                            lambda: 44):
                got = self.face.stats()
        self.assertNotIn("throttled", got, "MAXN is not a warning")
        self.assertEqual(got["power"], "MAXN")

    def test_the_power_mode_is_read_from_the_file_not_from_a_command(self):
        """No sudo, nothing that can hang. This is served to a page that
        polls it every few seconds, so shelling out to `nvpmodel -q` is
        the wrong shape as well as the slower one."""
        body = (Path(__file__).parent / "yuzu_face.py").read_text()
        block = body.split("def power_mode(")[1].split("def temperature(")[0]
        self.assertIn("/var/lib/nvpmodel/status", block)
        self.assertNotIn("subprocess", block)

    def test_a_nonsense_thermal_zone_is_ignored(self):
        """Some zones report an unpopulated -256000. A confidently wrong
        minus number on screen is worse than no temperature."""
        with tempfile.TemporaryDirectory() as tmp:
            for i, milli in enumerate(("-256000", "48200", "51900", "999999")):
                zone = Path(tmp) / ("thermal_zone%d" % i)
                zone.mkdir()
                (zone / "temp").write_text(milli + "\n")
            with unittest.mock.patch.object(self.face, "THERMAL", tmp):
                self.assertEqual(self.face.temperature(), 51)

    def test_no_battery_hardware_means_no_battery_shown(self):
        """THE HONEST DEFAULT, and it is what his board does today. The
        power path is a PD bank -> a barrel jack, and a barrel jack
        carries volts and nothing else: no data line, no fuel gauge, no
        state of charge. A percentage here would be a number this deck
        INVENTED."""
        with tempfile.TemporaryDirectory() as tmp:
            with unittest.mock.patch.object(self.face, "POWER_SUPPLY", tmp):
                with unittest.mock.patch.object(self.face, "HWMON", tmp):
                    self.assertIsNone(self.face.battery())
                    self.assertIsNone(self.face.power_draw())
                    self.assertEqual(self.face.charge(), {})

    def test_a_real_battery_node_is_used_the_day_one_exists(self):
        """A UPS HAT, or any bank that speaks over a DATA link, appears
        in /sys/class/power_supply and then the percentage is the
        KERNEL'S rather than ours. The indicator lights up with no code
        change, which is the whole reason it is written this way."""
        with tempfile.TemporaryDirectory() as tmp:
            node = Path(tmp) / "BAT0"
            node.mkdir()
            (node / "type").write_text("Battery\n")
            (node / "capacity").write_text("78\n")
            (node / "status").write_text("Discharging\n")
            # A mains node alongside it must not be mistaken for one.
            mains = Path(tmp) / "ADP1"
            mains.mkdir()
            (mains / "type").write_text("Mains\n")
            (mains / "online").write_text("1\n")
            with unittest.mock.patch.object(self.face, "POWER_SUPPLY", tmp):
                self.assertEqual(self.face.battery(), (78, False))
                (node / "status").write_text("Charging\n")
                self.assertEqual(self.face.battery(), (78, True))
                # A real percentage WINS over the watts estimate: it is
                # measured charge, and the estimate is not.
                with unittest.mock.patch.object(self.face, "power_draw",
                                                lambda: 14.2):
                    got = self.face.charge()
        self.assertEqual(got, {"percent": 78, "charging": True})

    def test_the_jetsons_own_rail_gives_WATTS_which_are_measured(self):
        """What the board can actually answer today, and it does --
        CONFIRMED on the real Orin, Sept 11: `deck --check` reported
        `5.6W now` at idle with a desktop up.

        The Orin carries INA3221 monitors on hwmon; two kernel shapes
        exist (microwatts directly, or millivolts x milliamps) and both
        are handled. Only the INPUT rail counts."""
        with tempfile.TemporaryDirectory() as tmp:
            box = Path(tmp) / "hwmon0"
            box.mkdir()
            (box / "in1_label").write_text("VDD_IN\n")
            (box / "in1_input").write_text("12000\n")     # mV
            (box / "curr1_input").write_text("1180\n")    # mA
            # a rail that is not an input rail at all, and must be
            # ignored however low its channel number
            (box / "in2_label").write_text("VDD_CPU\n")
            (box / "power2_input").write_text("9000000\n")
            with unittest.mock.patch.object(self.face, "HWMON", tmp):
                self.assertEqual(self.face.input_rail(), ("VDD_IN", 14.2))
                self.assertEqual(self.face.power_draw(), 14.2)
                (box / "power1_input").write_text("15500000\n")   # uW
                self.assertEqual(self.face.power_draw(), 15.5)

    def test_a_SUB_rail_can_never_be_mistaken_for_the_whole_board(self):
        """THE BUG THIS EXISTS FOR, and it shipped for one commit.
        `VDD_GPU_SOC` was in the input-rail list -- but that is the GPU
        and SOC block, which sits INSIDE VDD_IN. Reading it reports part
        of the board as the whole and makes every runtime estimate too
        optimistic, and the number looks perfectly reasonable while
        being wrong.

        Two guards: the sub-rail is not a candidate at all, and the
        choice is by PRIORITY rather than by whichever channel happened
        to come first -- so a board that lists a sub-rail on a lower
        channel than VDD_IN still reports VDD_IN."""
        self.assertNotIn("VDD_GPU_SOC", self.face.INPUT_RAILS)
        with tempfile.TemporaryDirectory() as tmp:
            box = Path(tmp) / "hwmon0"
            box.mkdir()
            # the sub-rail FIRST, on the lower channel, deliberately
            (box / "in1_label").write_text("VDD_GPU_SOC\n")
            (box / "power1_input").write_text("3100000\n")
            (box / "in2_label").write_text("POM_5V_IN\n")
            (box / "power2_input").write_text("7000000\n")
            (box / "in3_label").write_text("VDD_IN\n")
            (box / "power3_input").write_text("9400000\n")
            with unittest.mock.patch.object(self.face, "HWMON", tmp):
                # VDD_IN wins on priority even though it is listed last
                self.assertEqual(self.face.input_rail(), ("VDD_IN", 9.4))
                # and with VDD_IN absent, the older name is next -- but
                # the sub-rail is still never the answer
                (box / "in3_label").write_text("VDD_SOC\n")
                self.assertEqual(self.face.input_rail(), ("POM_5V_IN", 7.0))

    def test_deck_check_names_the_rail_it_read(self):
        """A watt figure off the wrong rail looks perfectly reasonable,
        so the only way to know it is the whole board is to SEE which
        rail answered. Same reason `pad --status` prints Bonded."""
        body = (Path(__file__).parent / "deck").read_text()
        block = body.split("POWER=$(")[1].split('")')[0]
        self.assertIn("input_rail", block, "deck --check hides the rail")
        self.assertIn("rail[0]", block, "the rail name is not printed")

    def test_the_runtime_says_FROM_FULL_and_never_remaining(self):
        """The wording is the whole point. Hours REMAINING needs a state
        of charge nothing on this board can read; hours FROM FULL is
        arithmetic on a measured draw and a bank whose capacity is on
        its label. Calling the second one the first is the confident lie
        this project keeps refusing to print."""
        with unittest.mock.patch.object(self.face, "battery", lambda: None):
            with unittest.mock.patch.object(self.face, "power_draw",
                                            lambda: 14.2):
                got = self.face.charge()
        self.assertEqual(got["watts"], 14.2)
        # 74Wh label x 0.8 for the boost-and-buck chain
        self.assertAlmostEqual(got["hours"], 4.2, places=1)
        for page in (self.PAGE, Path(__file__).parent / "ui" / "home.html"):
            # The RENDERED string only. The comment above it uses the
            # word "remaining" to explain why it is never printed, and
            # a whole-file grep read that as the fault it warns about --
            # the same false positive this repo has hit before by
            # matching source text instead of behaviour.
            shown = page.read_text().split("function charge(box, s)")[1]
            self.assertIn("h/full", shown,
                          f"{page.name} does not say FROM FULL")
            self.assertNotIn("remaining", shown.lower(),
                             f"{page.name} claims to know what is left")

    def test_both_pages_draw_the_SAME_battery(self):
        """Two pages and no build step, so the renderer is duplicated on
        purpose -- same deliberate copy as the doctor's Jetson check and
        the exit check, and it gets the same guard: if they drift, the
        battery reads one way on her face and another on the home
        screen, which is exactly the sort of thing nobody notices until
        it matters."""
        copies = []
        for page in (self.PAGE, Path(__file__).parent / "ui" / "home.html"):
            body = page.read_text()
            self.assertIn("function charge(box, s)", body,
                          f"{page.name} has no battery renderer")
            copies.append(body.split("function charge(box, s)")[1]
                              .split("\n}")[0])
        self.assertEqual(copies[0], copies[1],
                         "the two battery renderers have drifted apart")

    def test_the_battery_is_DRAWN_not_an_emoji(self):
        """An emoji is a full-colour bitmap that ignores --ink, so on the
        black theme it would sit there as a glossy blob while everything
        around it went neon. Same finding as the home screen icons."""
        for page in (self.PAGE, Path(__file__).parent / "ui" / "home.html"):
            body = page.read_text()
            self.assertIn("class=\"cell\"", body, f"{page.name}: no cell")
            for emoji in ("\U0001F50B", "\U0001F50C", "\u26A1"):
                self.assertNotIn(emoji, body,
                                 f"{page.name} uses an emoji battery")

    def test_her_face_reads_HER_OWN_stage_directions(self):
        """Ghost, Sept 11: "saya never uses the cute blushing faces even
        when shes 'blushing'". He was right, and it was WIRING rather
        than taste -- the brain only reported idle/thinking/talking, and
        `talking` resolves to one sprite, so five of his eight faces
        could never appear.

        The fix does not guess her feelings. She already writes them
        down in her own stage directions, which this project spent two
        days deciding to keep rather than suppress. No direction, no
        mood -- and then `talking`, exactly as before."""
        for said, want in (
                ("[blushes] I-It's not like I missed you.", "annoyed"),
                ("*giggles* fine, you win.", "happy"),
                ("[eye roll] whatever.", "annoyed"),
                ("[smirks] obviously.", "smug"),
                ("[gasps] you did WHAT?", "shock"),
                ("[sniffs] ...it's nothing.", "sad"),
                ("Just a plain reply with no directions.", None),
                ("", None)):
            self.assertEqual(self.face.mood_from(said), want, said)

    def test_a_SIGH_is_not_crying_and_never_puts_TEARS_on_her_face(self):
        """Ghost, Sept 11: "she 'cry faces' when she should blush with
        the actual blush image (the one with no tears) or the pouty
        blush at least."

        `sad` used to catch "sigh", "trails off" and "quiet" -- and a
        tsundere sighs in almost every reply. Her very first live line
        was `*sigh* Fine, I'll talk about these... annoyingly cute
        cats`, and `*trails off* Mochi ice cream... I guess that sounds
        okay` is her GIVING GROUND, which is the archetype at its best.
        Both rendered `cry.png`: tears down her face, over ice cream.

        A sigh is exasperation, so it goes with annoyed -- and `mad.png`
        is blush plus pout, which he confirmed is what he wants: "mad
        works for blushing looks like it. thats what i meant by pouty."
        """
        for said in ("*sigh* Fine, I'll talk about these cats.",
                     "*trails off* Mochi ice cream... I guess that's okay.",
                     "O-oh, shut up... *ahem* I'm not built for that.",
                     "[clears her throat] Anyway."):
            self.assertEqual(self.face.mood_from(said), "annoyed", said)

    def test_real_crying_still_gets_the_crying_face(self):
        """Narrowing `sad` must not empty it -- `cry.png` is his art and
        it has a job. The words that keep it are the ones that only ever
        mean crying."""
        for said in ("[starts crying] I hate you.",
                     "[sniffles] ...whatever.",
                     "[sobs quietly]",
                     "[a tear runs down] don't look at me."):
            self.assertEqual(self.face.mood_from(said), "sad", said)

    def test_the_blush_words_resolve_to_art_that_has_no_tears(self):
        """The end-to-end version: a blushing line must not land on the
        sprite with tears drawn on it. This is the assertion that would
        have caught the bug, because it names the FILE rather than the
        role."""
        art = self.face.roles_for(self.face.sprites())
        for said in ("[blushes] I-It's not like I missed you.",
                     "*sigh* whatever.",
                     "[pouts] hmph."):
            role = self.face.mood_from(said)
            self.assertNotEqual(role, "sad", said)
            self.assertNotIn("cry", art.get(role, ""),
                             f"{said!r} puts tears on her face")

    def test_a_blush_beats_a_giggle_in_the_same_line(self):
        """ORDER IS THE DESIGN, not alphabetical. A tsundere who blushes
        AND giggles is blushing -- that is the whole character, and it
        is why `happy` is last in the list."""
        self.assertEqual(
            self.face.mood_from("[blushes and giggles] shut up"), "annoyed")

    def test_the_mood_never_replaces_what_she_is_DOING(self):
        """Two questions, two fields. `state` is the honest loading
        spinner; `mood` is how she is. Collapsing them means a thinking
        face can never also be a blushing one -- and this repo has paid
        for merging two questions into one variable more than once."""
        real = self.face.STATE_FILE
        with tempfile.TemporaryDirectory() as tmp:
            self.face.STATE_FILE = os.path.join(tmp, "state")
            try:
                self.face.set_state("talking", "[blushes] hmph.")
                got = self.face.get_state()
                self.assertEqual(got["state"], "talking")
                self.assertEqual(got["mood"], "annoyed")
                self.face.set_state("thinking")
                self.assertNotIn("mood", self.face.get_state(),
                                 "a stale mood outlived the reply")
            finally:
                self.face.STATE_FILE = real
        page = (Path(__file__).parent / "ui" / "face.html").read_text()
        self.assertIn("s.state === 'talking' && s.mood", page,
                      "the mood is used outside of talking, so a blush "
                      "could override the thinking face")

    def test_every_sprite_he_drew_can_actually_be_reached(self):
        """THE POINT OF THE WHOLE FIX. Eight faces were in the repo and
        three could be shown. A file that no state resolves to is art
        he made for nothing."""
        resolved = set(self.face.roles_for(self.face.sprites()).values())
        have = {s["name"] for s in self.face.sprites()}
        unreachable = have - resolved - {"blink"}   # blink is a frame
        self.assertFalse(unreachable,
                         f"nothing can ever show: {sorted(unreachable)}")

    def test_the_rate_is_MEASURED_by_the_brain_not_guessed_here(self):
        """Only the brain sees Ollama's own eval_count / eval_duration.
        A rate this deck estimated would be worse than no rate, so the
        number crosses with the state and is simply absent when an older
        Ollama does not report it."""
        self.assertAlmostEqual(
            self.brain._token_rate({"eval_count": 200,
                                    "eval_duration": 11_000_000_000}),
            18.18, places=1)
        for empty in ({}, {"eval_count": 0, "eval_duration": 5},
                      {"eval_count": 5, "eval_duration": 0},
                      {"eval_count": None, "eval_duration": None}):
            self.assertIsNone(self.brain._token_rate(empty))

    def test_the_state_file_carries_the_rate_without_breaking_readers(self):
        """`set_state` is called from the reply path, so a new field must
        never be able to stop her talking -- and a caller that does not
        pass one must not blank it either."""
        real = self.face.STATE_FILE
        with tempfile.TemporaryDirectory() as tmp:
            self.face.STATE_FILE = os.path.join(tmp, "state")
            try:
                self.face.set_state("talking", "hi", 18.24)
                self.assertEqual(self.face.get_state()["rate"], 18.2)
                self.face.set_state("idle")
                self.assertNotIn("rate", self.face.get_state())
            finally:
                self.face.STATE_FILE = real


class TestHomeScreen(unittest.TestCase):
    """`ui/home.html` -- the desktop behind her face.

    Ghost, Sept 10: "id like home button to take me to a desktop with
    my apps and a saya button visible." It is what the home button goes
    to and what the deck can boot into."""

    import yuzu_face as face

    PAGE = Path(__file__).parent / "ui" / "home.html"
    FACE = Path(__file__).parent / "ui" / "face.html"

    def test_it_exists_and_reaches_for_nothing_outside_itself(self):
        self.assertTrue(self.PAGE.exists())
        page = self.PAGE.read_text()
        for reach in ("http://", "https://", "//cdn", "@import",
                      "fonts.googleapis", "integrity="):
            # 127.0.0.1 is the deck talking to itself and is not a reach
            # outside; a CDN is.
            for hit in [ln for ln in page.splitlines() if reach in ln]:
                self.assertIn("127.0.0.1", hit,
                              f"home.html reaches outside itself: {hit}")

    def test_the_home_button_on_her_face_actually_goes_somewhere(self):
        """It was decoration until now, which is WORSE than absent: a
        button that does nothing on a touchscreen reads as a broken
        deck, and he has no keyboard to work around it with."""
        self.assertIn("home.html", self.FACE.read_text(),
                      "the home button still goes nowhere")

    def test_her_tile_is_there_and_goes_to_her_face(self):
        page = self.PAGE.read_text()
        self.assertIn('id="saya"', page, "there is no Saya button")
        self.assertIn('data-go="face.html"', page)

    def test_the_front_page_is_three_tiles_and_misc_is_the_drawer(self):
        """Ghost, Sept 11: "lets hide the gameboy tab for now its not as
        important. or put it and the wikipedia tabs under a tab called
        ☆Misc☆ we can pile up our fancy future apps in that tab."

        So the front page is the four things he actually opens, and
        every view is FOUR EQUAL TILES with nothing spanning -- which is
        what the grid was before a fifth tile forced a wide row and a
        screenshot caught it orphaning two others."""
        page = self.PAGE.read_text()
        views = {}
        for tile in re.findall(r'<div class="tile"[^>]*>', page):
            views.setdefault(
                re.search(r'data-view="(\w+)"', tile).group(1), []).append(tile)
        self.assertEqual(sorted(views), ["main", "misc"])
        # THREE ON THE FRONT, FOUR IN THE DRAWER, and each view gets the
        # row that fits it rather than a shared 2x2 with a hole in the
        # corner. Ghost, Sept 11: "i noticed Face button and Talk button
        # are the same thing now? is that accurate?" -- it was. Both
        # opened face.html, so one of them was a wasted tile. Saya owns
        # both jobs now; her chat bar has always been on that page.
        self.assertEqual(len(views["main"]), 3, "the front page is not three")
        self.assertEqual(len(views["misc"]), 4, "the drawer is not four")
        self.assertIn("#grid.main { grid-template-columns: repeat(3, 1fr); }",
                      page, "three tiles in a two-column grid orphans one")
        # The rule is about the TILE grid: a wide tile forced an odd row
        # and orphaned two others. The calculator's display spanning its
        # own keypad is not that, so pin WHICH selector may span rather
        # than banning the string and catching the wrong one.
        spans = re.findall(r"([#.][\w-]+)[^{}]*\{[^}]*grid-column:\s*span", page)
        self.assertEqual(spans, ["#screen"],
                         "a spanning tile is back, and an odd row with it")
        for wanted in ('data-go="face.html"', 'data-go="vpet.html"'):
            self.assertIn(wanted, "".join(views["main"]) + page,
                          f"{wanted} left the front page")
        # TALK IS NOT A TERMINAL. It used to POST /launch/chat, which
        # starts an xterm ON THE DECK'S SCREEN -- from the phone that is
        # a window nobody can see, and on the panel it lands him in a
        # terminal with no keyboard. Ghost, Sept 11: "the chat in the ui
        # ismt actually clickable. like u can but it doesnt take you to
        # a chat." The chat bar under her face is the one that works on
        # both, so Talk goes there. `deckapps` still installs the
        # terminal chat as its own app icon, for when the keyboard is
        # in the case.
        self.assertNotIn('data-launch="chat"', page,
                         "Talk opens a terminal again")
        self.assertIn("☆Misc☆", page, "the stars are gone")

    def test_the_drawer_has_a_way_back_and_needs_no_second_page(self):
        """It is the SAME PAGE with the tiles swapped. A second file
        would need its own exit, and every screen on this deck having
        one is the rule two power cycles paid for -- so the cheapest
        way to keep that true is to not add a screen.

        BACK IS IN THE BOTTOM BAR, NOT A TILE. Ghost means to "pile up
        our fancy future apps" in the drawer, so a Back tile would spend
        an app slot forever and MOVE every time the drawer grew. In the
        bar it is in the same place whatever is on screen, which is what
        an exit has to be on a deck with no keyboard."""
        page = self.PAGE.read_text()
        self.assertIn('id="back"', page, "there is no way back")
        self.assertIn('data-show="misc"', page, "nothing opens the drawer")
        self.assertNotIn("misc.html", page, "the drawer became a page")
        # it walks DOWN one level rather than keeping a history -- a
        # stack is a thing that can strand you
        self.assertIn("'calc' ? 'misc'", page,
                      "Back out of the calculator does not reach the drawer")
        self.assertNotIn('data-view="calc"', page,
                         "the calculator became a tile that needs a view")

    def test_the_d20_is_FAIR_and_rolls_in_place(self):
        """Ghost: "add a D20 dice button somewhere with that black and
        neon green crt effects that rolls it randomly."

        `random() % 20` is biased -- 256 does not divide by 20, so some
        faces come up more often. A loaded die is a bad joke to leave
        in a thing somebody rolls for fun, and rejection sampling costs
        nothing."""
        page = self.PAGE.read_text()
        self.assertIn('data-roll="20"', page, "there is no d20")
        self.assertIn("getRandomValues", page, "the roll is not fair")
        self.assertIn("256 % sides", page, "no rejection sampling")
        self.assertNotIn("d20.html", page, "the dice grew a page")
        # the flourish belongs to the two results that earn one
        self.assertIn("nat20", page)
        self.assertIn("nat1", page)

    def test_the_icons_are_line_art_and_not_emoji(self):
        """Ghost wanted "clean single-color line icons... rather than
        smartphone". Emoji are full-colour bitmaps that ignore the ink
        colour entirely, so on the black theme they stayed as glossy
        3D blobs while everything else went neon.

        They are DRAWN HERE rather than pulled from Lucide or Feather,
        because a library is a download and this deck has to work with
        the WiFi off."""
        page = self.PAGE.read_text()
        self.assertEqual(page.count("<svg"), 7, "not seven line icons")
        self.assertIn("stroke: var(--ink)", page,
                      "the icons do not take the ink colour")
        for emoji in ("💬", "📖", "🎮", "☺"):
            self.assertNotIn(emoji, page, f"{emoji} is still a tile icon")

    # ---- the launcher, which is the only risky thing here ------------

    def test_only_the_allowlist_can_ever_run(self):
        """THE WHOLE DESIGN. A page cannot start mGBA, so it POSTs a
        NAME -- and a name is all that crosses. Nothing from the request
        reaches a shell: no arguments, no path, no interpolation.

        Verified against the real server with raw sockets as well as
        here: `gba;rm -rf /`, `../../etc/passwd`, a NUL byte and
        `wiki'&&touch /tmp/pwned` all come back 'not a thing this deck
        knows how to open', and /tmp/pwned was never created.

        This matters because the server binds 0.0.0.0 -- anything looser
        is a box on his WiFi that runs what it is told."""
        for hostile in ("gba;rm -rf /", "../../etc/passwd", "gba\x00",
                        "wiki'&&touch /tmp/pwned", "", "chat; echo hi",
                        "/bin/sh", "gba "):
            ok, said, opens = self.face.launch(hostile)
            self.assertFalse(ok, f"{hostile!r} was allowed to run")
        # And every allowed key maps to a real file in the repo.
        for name, (argv, said, opens) in self.face.launchers().items():
            self.assertTrue(said, f"{name} runs silently")
            first = argv[0]
            self.assertTrue(os.path.exists(first) or shutil.which(first),
                            f"{name} points at {first}, which is not there")

    def test_a_missing_terminal_says_so_instead_of_doing_nothing(self):
        """The chat needs a terminal to live in. On a board without one
        the tile must explain itself -- `deckapps` already learned that
        an icon which opens nothing reads as a broken deck rather than
        as a missing package."""
        with unittest.mock.patch.object(self.face, "_terminal",
                                        lambda: None):
            ok, said, opens = self.face.launch("chat")
        self.assertFalse(ok)
        self.assertIn("apt install", said, "it does not say how to fix it")

    def test_launching_is_detached(self):
        """A launcher that holds the server hostage takes her face down
        with it, and a foreground process on this board has already cost
        two power cycles."""
        body = (Path(__file__).parent / "yuzu_face.py").read_text()
        popen = body.split("subprocess.Popen(")[1].split(")")[0]
        self.assertIn("start_new_session=True", popen)


class TestCalculator(unittest.TestCase):
    """The calculator in the drawer. Ghost, Sept 11: "wana toss a
    working calculator in the same style into the misc drawer? (i suck
    at math)".

    THAT PARENTHESIS IS THE SPEC. If he could check the answer he would
    not need the tool, so the tool has to be checkable a different way:
    the whole sum stays on screen above the result. A normal calculator
    shows one number and hides what you typed, which makes a slipped
    digit invisible until the answer is already wrong.

    WHAT IS VERIFIED WHERE. The arithmetic is JavaScript and this suite
    is stdlib Python, so the sums themselves were driven in a real
    browser -- precedence, division by zero, 0.1 + 0.2, backspace,
    negation, chaining off an answer, and a twelve-digit product -- and
    the screen was rendered at the panel's real 1024x600 and LOOKED at,
    which is what caught the one bug this round had. What is pinned HERE
    is every structural property whose loss would bring a fault back."""

    PAGE = Path(__file__).parent / "ui" / "home.html"

    def code(self):
        """The page with its comments removed. Every rule worth pinning
        here is about what the page DOES, and a comment explaining why
        something is absent must never read as that thing being
        present."""
        body = self.PAGE.read_text()
        body = re.sub(r"/\*.*?\*/", " ", body, flags=re.S)
        return "\n".join(ln.split("//")[0] for ln in body.splitlines())

    def test_it_lives_in_the_drawer_and_is_not_another_page(self):
        page = self.PAGE.read_text()
        self.assertIn('id="calc"', page, "there is no calculator")
        self.assertIn('data-show="calc"', page, "nothing opens it")
        self.assertNotIn("calc.html", page, "the calculator grew a page")

    def test_there_is_no_eval_anywhere_near_it(self):
        """Not paranoia about a page the deck serves to itself. eval
        turns a typo into a JavaScript error instead of an answer, and
        "SyntaxError" on screen is the same dead end as a tap that does
        nothing -- on a deck with no keyboard to debug it with."""
        # CODE, not prose. Two false positives on the way to this line:
        # a bare "eval(" matches evaluate() -- the function that exists
        # SO THAT there is no eval -- and it also matches the COMMENT
        # saying there is no eval. Grepping source text is a proxy, and
        # this repo has now been bitten by that exact shape four times.
        code = self.code()
        self.assertIsNone(re.search(r"\beval\s*\(", code),
                          "eval() is in the calculator page")
        # NOT innerHTML: the battery cell writes a fixed string through
        # it and has since before there was a calculator. Banning it
        # here would fail a line this page is REQUIRED to keep byte for
        # byte identical to face.html.
        for hole in ("new Function", "setTimeout('"):
            self.assertNotIn(hole, code, f"{hole} is in the calculator page")

    def test_it_does_real_precedence_rather_than_left_to_right(self):
        """"2 + 3 x 4" is 14, which is what it is on paper. A calculator
        that answers 20 is a calculator you cannot trust with the sum
        you could not do yourself -- and he told us he cannot.

        Two passes: x and \u00f7 collapse first, then + and \u2212 left to
        right. Verified in a browser; pinned here so a rewrite cannot
        quietly flatten it."""
        body = self.code().split("function evaluate(")[1].split("\nfunction ")[0]
        # the multiply/divide pass has to come BEFORE the add/subtract one
        self.assertLess(body.index("\\u00d7"), body.index("'+' ?"),
                        "the precedence passes are the wrong way round")

    def test_dividing_by_zero_is_a_sentence_and_never_Infinity(self):
        """Infinity is a number that LOOKS like an answer. This project
        keeps refusing to print things it made up, and a wrong answer
        wearing a right answer's clothes is the worst version of it."""
        code = self.code()
        self.assertIn("cannot divide by zero", code)
        self.assertIn("n === 0", code, "nothing checks the divisor")
        # ...and again on the comment that explains why it is absent.
        self.assertNotIn("Infinity", code)

    def test_the_answer_is_rounded_so_binary_float_never_shows(self):
        """0.1 + 0.2 is 0.30000000000000004 if you let it. Ten
        significant digits removes that entirely and touches nothing a
        person would ever type into a deck."""
        self.assertIn("toPrecision(10)", self.code(),
                      "the answers are not rounded")

    def test_the_sum_is_NOT_laid_out_right_to_left(self):
        """THE BUG THIS ROUND HAD, and only rendering the page found it.
        `direction: rtl` was there to keep the END of a long sum on
        screen -- and it drew "12 x 3.5 + 7 =" as "= 7 + 3.5 x 12",
        because rtl reverses the ORDER OF RUNS in mixed text, not just
        the overflow. It would have flipped the minus off the front of a
        negative answer too, which is a wrong number rather than a
        scrambled one.

        Scrolling the box in draw() is what actually keeps the tail
        visible, and it cannot reorder anything."""
        code = self.code()
        self.assertNotIn("direction: rtl", code,
                         "the sum reads backwards again")
        self.assertIn("scrollLeft = ", code,
                      "nothing keeps the end of a long sum on screen")

    def test_the_whole_sum_stays_on_screen_next_to_the_answer(self):
        """The one thing he asked for, stated as structure: two boxes,
        the sum above the result, and the sum still there AFTER '='."""
        code = self.code()
        self.assertIn('id="sum"', code)
        self.assertIn('id="out"', code)
        self.assertLess(code.index('id="sum"'), code.index('id="out"'),
                        "the answer is above the sum")
        self.assertIn("last = shown + ' ='", code,
                      "the sum is thrown away the moment it is answered")

    def test_every_key_a_calculator_needs_is_on_the_pad(self):
        page = self.PAGE.read_text()
        keys = set(re.findall(r'data-k="([^"]+)"', page))
        wanted = set("0123456789") | {".", "+", "=", "%", "C", "back",
                                      "neg", "\u00d7", "\u00f7", "\u2212"}
        self.assertEqual(wanted - keys, set(), "keys missing from the pad")
        self.assertEqual(len(keys), 20, "the pad is not twenty keys")

    def test_a_stray_keypress_can_never_reach_the_launcher(self):
        """The Bluetooth keyboard exists and may end up on the deck, so
        typing a sum is free to support. But the tiles POST to the
        allowlist, and a keypress that reaches one of those is a tap he
        never made."""
        guard = self.code().split("addEventListener('keydown'")[1][:400]
        self.assertIn("grid.className !== 'calc'", guard,
                      "keys are handled outside the calculator")
        self.assertIn("return", guard)


class TestDeckAutostart(unittest.TestCase):
    """`deckapps --autostart` -- the deck opens the home screen at login."""

    SCRIPT = Path(__file__).parent / "deckapps"

    def test_autostart_is_opt_in_and_reversible(self):
        body = self.SCRIPT.read_text()
        self.assertIn("--autostart", body)
        auto_dir = body.split("AUTO=")[1].splitlines()[0]
        self.assertIn("autostart", auto_dir,
                      "AUTO does not point at the autostart folder")
        remove_block = body.split('= "--remove" ]')[1].split("fi")[0]
        self.assertIn("$AUTO", remove_block,
                      "--remove does not undo the autostart, so a bad "
                      "page would open at every login with no way back "
                      "except the serial cable")

    def test_it_is_a_window_he_can_close_not_a_kiosk(self):
        """CLAUDE.md is blunt about this: a UI that can trap him is
        strictly WORSE than a terminal, because there is not even a
        keyboard to type an exit into. Booting into a page is fine;
        booting into something he cannot leave is not."""
        body = self.SCRIPT.read_text()
        self.assertNotIn("--kiosk", body.split("autostart")[0],
                         "the autostart page is a locked kiosk")

    def test_the_face_launcher_waits_for_the_port(self):
        """A tap landing on a dead port is the same dead end as typing
        the address wrong, just prettier."""
        body = self.SCRIPT.read_text()
        wrapper = body.split('cat > "$YUZU/.face-app"')[1].split("\nAPP")[0]
        self.assertIn("8081", wrapper)
        self.assertIn("sleep", wrapper, "it opens the page immediately")


class TestTiling(unittest.TestCase):
    """`tile` -- Pop Shell, because a 10" panel is the wrong shape for
    floating windows.

    UNVERIFIED ON THE BOARD, like `deckapps`: nobody has run it on the
    Orin yet. What is checked here is that it cannot strand him."""

    SCRIPT = Path(__file__).parent / "tile"

    def test_it_exists_and_is_valid_shell(self):
        import subprocess
        self.assertTrue(self.SCRIPT.exists())
        self.assertTrue(os.access(self.SCRIPT, os.X_OK))
        done = subprocess.run(["bash", "-n", str(self.SCRIPT)],
                              capture_output=True)
        self.assertEqual(done.returncode, 0, done.stderr.decode())

    def test_off_disables_without_uninstalling(self):
        """The escape hatch has to be cheap. A GNOME extension can leave
        a desktop that will not draw, and his only shell is a serial
        cable -- so ONE WORD must give him the ordinary desktop back,
        and it must not be the same word that throws the package away."""
        body = self.SCRIPT.read_text()
        off = body.split("--off)")[1].split(";;")[0]
        self.assertIn("disable", off)
        self.assertNotIn("apt remove", off,
                         "--off must not uninstall -- that is --remove")
        self.assertIn("--remove", body, "there is no way to uninstall")

    def test_it_checks_gnome_is_RUNNING_not_merely_installed(self):
        """THE REPO'S MOST-REPEATED BUG, caught before shipping this
        time. Ubuntu ships gnome-shell, but his only desktop today is a
        VNC session started from ~/.vnc/xstartup, which may be a bare X
        session with no GNOME in it. `command -v gnome-shell` would say
        yes the whole time nothing was tiling -- exactly like xdpyinfo
        answering happily through a loopback-only VNC bind.

        So the check is on the RUNNING process, and the two cases get
        different messages because they have different fixes."""
        body = self.SCRIPT.read_text()
        check = body.split("on_gnome()")[1].split("}")[0]
        self.assertIn("pgrep", check,
                      "it checks whether GNOME is installed, which is "
                      "true on a board where nothing is tiling")
        self.assertIn("xstartup", body,
                      "it must say where the VNC session's desktop is "
                      "chosen -- otherwise 'not running' has no next step")

    def test_it_refuses_politely_off_gnome(self):
        """Pop Shell is a GNOME extension and only a GNOME one. On a
        board running something else this must say so, not fail deep
        inside apt."""
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            binv = Path(tmp) / "bin"
            binv.mkdir()
            # No gnome-shell on PATH, and no desktop declared.
            env = {"PATH": f"{binv}:/usr/bin:/bin", "HOME": tmp}
            done = subprocess.run(["bash", str(self.SCRIPT)],
                                  capture_output=True, text=True, env=env)
        self.assertEqual(done.returncode, 1)
        self.assertIn("GNOME", done.stdout)
        self.assertNotIn("apt install", done.stdout,
                         "it tried to install on a box with no GNOME")

    def test_installed_means_ON_DISK_not_listed_by_the_running_shell(self):
        """MEASURED LIVE, and it is the third instance in one evening.

            Forge downloaded and installed.
            Nothing installed itself. Its output is above.

        Both lines, one after the other, about a Forge that had just
        installed perfectly. `gnome-extensions list` reports what the
        running shell has LOADED, and a shell loads new extensions at
        startup -- so it is guaranteed to say no in exactly the moment
        this script needs it to say yes.

        The extension is a DIRECTORY. Look at the directory."""
        check = self.SCRIPT.read_text().split("have()")[1].split("\n}")[0]
        self.assertIn("gnome-shell/extensions/", check,
                      "it asks the running shell whether an extension it "
                      "has not scanned yet exists")
        self.assertIn("-d ", check, "it does not look on disk at all")

    def test_it_can_be_switched_on_without_a_keyboard(self):
        """Ghost, Sept 9: "i cant hit alt-f2-r-enter until i get the
        keyboard and screen goin". The standard advice for a freshly
        installed GNOME extension assumes both.

        `gnome-extensions enable` only works on an extension the running
        shell has already LOADED, and shells load them at startup. But
        all `enable` ultimately does is put the uuid in
        org.gnome.shell enabled-extensions, and THAT key is read at
        every startup -- so writing it directly means tiling switches
        itself on the first time he logs in with the panel attached.

        Same rule as the whole project: never ship an escape hatch that
        depends on something he cannot reach."""
        body = self.SCRIPT.read_text()
        self.assertIn("enabled-extensions", body,
                      "the only way to switch it on needs a keyboard")
        # And Alt+F2 must be an ASIDE, not the instruction. He hit the
        # old message live: "Installed, but GNOME has not picked it up
        # yet. In the desktop press Alt+F2..." -- correct, useless, and
        # a dead end on a board with no keyboard attached.
        self.assertIn("turns itself on", body,
                      "it does not tell him that waiting is enough")
        self.assertLess(body.index("turns itself on"), body.index("Alt+F2, r"),
                        "the keyboard workaround is offered before the "
                        "thing that needs no keyboard")

    def test_it_falls_back_to_forge_without_a_browser(self):
        """MEASURED ON THE BOARD, Sept 9: `E: Unable to locate package
        gnome-shell-extension-pop-shell`. Pop Shell ships in Pop!_OS's
        repos, not Ubuntu's, and "Ubuntu ships it" was simply wrong.

        Forge is the fallback, and the interesting constraint is not
        which extension wins -- it is that his only shell is a serial
        cable. So it must install WITHOUT a store page: ask
        extensions.gnome.org which zip matches this GNOME version, then
        `gnome-extensions install`. Asking rather than guessing a URL is
        what survives the next GNOME update."""
        body = self.SCRIPT.read_text()
        self.assertIn("forge@jmmaranan.com", body, "there is no fallback")
        self.assertIn("extension-info", body,
                      "it guesses a download URL instead of asking which "
                      "build matches this shell version")
        self.assertIn("gnome-extensions install", body)
        for browsery in ("xdg-open", "firefox", "chromium"):
            self.assertNotIn(browsery, body,
                             "installing must not need a browser -- his "
                             "only session is a serial terminal")

    def test_it_states_no_unverified_keystrokes_for_forge(self):
        """The 8BitDo lesson, applied before it costs anything. Generic
        button combos printed as numbered steps sent him hunting for
        buttons his pad does not have while the real fault was
        elsewhere. Pop Shell's Super+Y is documented and is printed;
        Forge's shortcuts were never verified on this board, so its
        branch names where to LOOK instead of inventing keys."""
        body = self.SCRIPT.read_text()
        forge_branch = body.split("Its shortcuts")[0].split("else")[-1]
        self.assertNotIn("Super +", forge_branch,
                         "unverified Forge keystrokes stated as fact")
        self.assertIn("--off", body,
                      "there must always be a way out that needs no "
                      "keyboard shortcut at all")


class TestFaceSprites(unittest.TestCase):
    """`yuzu_face.py` -- the art is DATA now.

    Ghost's call, Sept 9: the hand-drawn SVG face read as MS Paint, so
    he cropped real anime expressions into transparent PNGs and asked
    for "a sprite system so i can just swap out the image files". The
    filename IS the expression name, and that is the property every
    test here defends."""

    import yuzu_face as face

    SPRITES = Path(__file__).parent / "ui" / "sprites"

    def test_his_art_is_actually_there(self):
        found = self.face.sprites()
        self.assertTrue(found, "no sprites -- her face has no art at all")
        names = {s["name"] for s in found}
        self.assertIn("thinking", names,
                      "thinking is the state that answers 'is it stuck?' "
                      "-- see DECK_UI.md")

    def test_a_new_file_is_a_new_expression_with_no_code_change(self):
        """The whole point of the sprite system. Adding art must not
        require editing a list, this suite, or anything else."""
        with tempfile.TemporaryDirectory() as tmp:
            before = self.face.sprites(tmp)
            (Path(tmp) / "sleepy.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"0" * 40)
            after = self.face.sprites(tmp)
        self.assertEqual(before, [])
        self.assertEqual([s["name"] for s in after], ["sleepy"])

    def test_generated_paint_layers_are_not_offered_as_expressions(self):
        """`wink.paint.png` is the mouth colour for `wink`, not a sixth
        face. Left unfiltered it would appear as its own chip and show
        a mouth floating on an empty background."""
        names = [s["name"] for s in self.face.sprites()]
        self.assertFalse([n for n in names if n.endswith(".paint")], names)

    def test_a_missing_folder_is_empty_not_an_exception(self):
        """A face with no art should say so on screen. Raising here
        takes the whole page down instead."""
        self.assertEqual(self.face.sprites("/nope/not/here"), [])
        self.assertEqual(self.face.manifest("/nope/not/here")["roles"], {})

    def test_roles_resolve_only_to_art_that_exists(self):
        """The brain will ask for `talking`; he named a file
        `woahshock`. Those two vocabularies stay separate on purpose --
        collapsing a semantic state onto one artist's filename is the
        name-leak bug this repo has hit six times."""
        resolved = self.face.roles_for(self.face.sprites())
        have = {s["name"] for s in self.face.sprites()}
        for role, sprite in resolved.items():
            self.assertIn(sprite, have,
                          f"role {role} points at art that is not there")
        self.assertNotIn("asleep", resolved,
                         "there is no asleep art, so the role must be "
                         "ABSENT rather than pointing at the wrong face")

    def test_the_mouth_paint_is_GONE_not_disabled(self):
        """Ghost, Sept 11: "her mouth paint seems kinda weird still.
        Revert back to strictly lineart on a colored background. No need
        for tongue/teeth paint."

        Deleted rather than switched off, which is the call this repo
        made on the LEDs for the same reason: a dead subsystem you still
        have to read around is worse than no subsystem. The companion
        files go too -- one left in ui/sprites/ would render a floating
        mouth over her face."""
        body = (Path(__file__).parent / "yuzu_face.py").read_text()
        for gone in ("def paint(", "def paint_all(", "TONGUE", "TEETH",
                     "CAVITY", "MOUTH_FLOOR"):
            self.assertNotIn(gone, body,
                             f"the mouth paint is still here: {gone}")
        self.assertEqual(list(self.SPRITES.glob("*.paint.png")), [],
                         "a generated paint layer is still in the repo")
        page = (Path(__file__).parent / "ui" / "face.html").read_text()
        self.assertNotIn('id="paint"', page,
                         "the page still stacks a paint layer")

    def test_odd_art_is_survived_rather_than_raised_on(self):
        """One odd export must never take her whole face down."""
        with tempfile.TemporaryDirectory() as tmp:
            junk = Path(tmp) / "junk.png"
            junk.write_bytes(b"not a png at all")
            self.assertIsNone(self.face.read_rgba(str(junk)))


class TestFaceServer(unittest.TestCase):
    """`face` -- her face on a screen, one word.

    The PHONE is the screen until the 7" panel lands: it is already a
    touchscreen, the page is built for touch, and this needs no VNC, no
    X session and no browser on the board."""

    SCRIPT = Path(__file__).parent / "face"
    PAGE = Path(__file__).parent / "ui" / "face.html"

    def test_it_exists_and_is_executable(self):
        self.assertTrue(self.SCRIPT.exists())
        self.assertTrue(os.access(self.SCRIPT, os.X_OK),
                        "face is not executable, so `~/YUZU/face` fails")
        self.assertTrue(self.PAGE.exists(), "there is no face to serve")

    def test_it_is_valid_shell(self):
        """A syntax error here surfaces on a phone at the board."""
        import subprocess
        done = subprocess.run(["bash", "-n", str(self.SCRIPT)],
                              capture_output=True)
        self.assertEqual(done.returncode, 0, done.stderr.decode())

    def test_the_face_reaches_for_nothing_outside_itself(self):
        """THE PROPERTY THAT MATTERS MOST ABOUT THIS PAGE. The deck is
        offline by design: no cloud model, no CDN, no web font. One
        `<script src>` or one `@import` and the face renders wrong on
        the machine it was built for -- and it would look FINE on any
        development box with a network, which is the worst way for a
        thing to break.

        The art is SVG, the animation is CSS, and there is no third
        thing."""
        page = self.PAGE.read_text()
        for reach in ("http://", "https://", "//cdn", "@import",
                      "fonts.googleapis", "integrity="):
            self.assertNotIn(reach, page,
                             f"face.html reaches outside itself: {reach!r}")

    def test_there_is_no_colour_control_left_anywhere(self):
        """Ghost, Sept 11: "id like it removed. only use the cool green
        on black crt for ui."

        It was never a feature -- it was a settings panel parked on her
        face, and its button now opens the V-Pet, which is a thing you
        can actually do. Gone means gone: no swatches, no dot, no
        stored preference to come back from."""
        for page in (self.PAGE, Path(__file__).parent / "ui" / "home.html"):
            body = page.read_text()
            for gone in ("const COLOURS", "setColour", "saya-bg",
                         'id="swatches"', 'id="tint"'):
                self.assertNotIn(gone, body,
                                 f"{page.name} still carries {gone}")

    def test_the_deck_is_green_on_black_and_says_so_once(self):
        """One palette, declared in one place per page, and the two
        pages have to agree -- two screens of the same object
        disagreeing about its colour reads as a bug, which is exactly
        why the old shared-storage-key test existed."""
        for page in (self.PAGE, Path(__file__).parent / "ui" / "home.html"):
            head = page.read_text().split("</style>")[0]
            root = head.split(":root {")[1].split("}")[0]
            self.assertIn("#000000", root, f"{page.name} is not black")
            self.assertIn("#39ff5e", root, f"{page.name} has no neon green")

    def test_the_CRT_look_is_no_longer_a_mode_you_can_leave(self):
        """Scanlines and corner brackets used to be tied to a theme you
        could tap out of. There is nothing to tap out of now, so a
        leftover `body.hud` gate would hide the whole look behind a
        class nothing ever sets."""
        page = self.PAGE.read_text()
        self.assertIn("repeating-linear-gradient", page, "no scanlines")
        self.assertNotIn("body.hud", page,
                         "the CRT look is still gated on a class")

    def test_her_line_art_is_recoloured_by_a_MASK_not_a_second_copy(self):
        """How the ink colour is possible at all. Each sprite is used as
        a CSS mask and the box behind it is filled with --ink, so one
        variable recolours every expression -- including a blink frame
        and any PNG he draws next week -- with no second copy of his art
        anywhere and nothing generated at runtime."""
        page = self.PAGE.read_text()
        self.assertIn("mask-image", page, "nothing masks the sprite")
        self.assertIn("var(--ink)", page, "the ink colour is not used")
        self.assertNotIn("<img", page,
                         "a plain <img> cannot be recoloured, so the "
                         "black theme would show her in black on black")

    def test_she_looks_toward_a_touch_and_settles_back(self):
        """Ghost wanted her pupils to track his touch. They cannot: her
        eyes are HOLES in flat line art and there is no pupil layer to
        move -- cutting one out at runtime is the iris-ring smear again.
        The whole face leans instead, a few pixels, and returns to
        centre when left alone.

        The clamp is the part worth pinning. Unclamped this is her face
        sliding off the screen; at five pixels it reads as attention."""
        page = self.PAGE.read_text()
        self.assertIn("GAZE_MAX", page, "she does not look at anything")
        clamp = int(re.search(r"GAZE_MAX\s*=\s*(\d+)", page).group(1))
        self.assertLessEqual(clamp, 8,
                             "that is a face sliding around, not a glance")
        hold = int(re.search(r"GAZE_HOLD\s*=\s*(\d+)", page).group(1))
        self.assertGreater(hold, 500, "she snaps back before you let go")

    def test_the_page_draws_no_art_of_its_own(self):
        """The vector face is GONE, not disabled. Ghost: "she looks like
        MS Paint tbh" and then "just use the art i gave u". A leftover
        <path> would render behind or beside his sprites and there is
        no version of that which looks intentional.

        SCOPED TO THE STAGE, deliberately. The invariant is that nothing
        is drawn WHERE HER ART GOES -- it was never "this file may not
        contain a vector", and reading it that way would ban the line
        icon on the button beside the ask bar, which is the same icon
        set the home screen uses and is not her face."""
        page = self.PAGE.read_text()
        stage = page.split('<form id="ask"')[0].split("</style>")[-1]
        for drawn in ("<path", "<circle", "viewBox"):
            self.assertNotIn(drawn, stage,
                             f"face.html still draws its own art: {drawn}")

    def test_the_server_is_launched_detached(self):
        """nohup + & always. A foreground server on a serial link is
        indistinguishable from a frozen board, and reading one as a
        freeze has already cost this project two power cycles."""
        body = "\n".join(ln for ln in self.SCRIPT.read_text().splitlines()
                         if not ln.strip().startswith("#"))
        self.assertIn("--serve", body, "nothing starts a server")
        # The launch is a continued line, so match the statement rather
        # than one line of it.
        started = re.search(r"nohup[^&]*--serve[^&]*&", body, re.S)
        self.assertTrue(started,
                        "the server is started in the FOREGROUND -- on a "
                        "serial link that is indistinguishable from a "
                        "frozen board, and it has cost two power cycles")

    def test_it_binds_every_interface_because_the_phone_is_the_client(self):
        body = self.SCRIPT.read_text()
        self.assertIn("--bind 0.0.0.0", body,
                      "a loopback-only bind is unreachable from the phone "
                      "-- the exact TigerVNC failure, one port along")

    @staticmethod
    def _free_port():
        import socket
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        return port

    def _run(self, *args, lan="10.1.2.3", port=None):
        """Drive the REAL script against a stub `ip`/`hostname`, so the
        no-network path can be exercised on a machine that has one.

        `lan=None` fakes a board that is not on the network at all --
        the case that produced the bug this class exists for."""
        import subprocess
        port = port or self._free_port()
        with tempfile.TemporaryDirectory() as tmp:
            binv = Path(tmp) / "bin"
            binv.mkdir()
            if lan:
                ip_out = f'echo "8.8.8.8 via 10.1.2.1 dev wlan0 src {lan}"\n'
                host_out = f'echo "172.17.0.1 192.168.55.1 {lan}"\n'
            else:
                ip_out = "exit 1\n"          # no route: board is offline
                host_out = 'echo "172.17.0.1 192.168.55.1"\n'
            (binv / "ip").write_text("#!/bin/bash\n" + ip_out)
            (binv / "hostname").write_text("#!/bin/bash\n" + host_out)
            for name in ("ip", "hostname"):
                (binv / name).chmod(0o755)
            env = dict(os.environ, YUZU_FACE_PORT=str(port),
                       PATH=f"{binv}:{os.environ['PATH']}")
            try:
                done = subprocess.run(["bash", str(self.SCRIPT), *args],
                                      capture_output=True, text=True,
                                      env=env, timeout=30)
            finally:
                if not args:
                    subprocess.run(["bash", str(self.SCRIPT), "--off"],
                                   capture_output=True, env=env)
            return done, port

    def test_it_serves_the_real_page(self):
        """Everything else here is about what it SAYS. This is the one
        that checks it actually works."""
        import subprocess, urllib.request
        port = self._free_port()
        env = dict(os.environ, YUZU_FACE_PORT=str(port))
        try:
            subprocess.run(["bash", str(self.SCRIPT)], capture_output=True,
                           text=True, env=env, timeout=30)
            got = urllib.request.urlopen(
                f"http://127.0.0.1:{port}/face.html", timeout=5).read()
        finally:
            subprocess.run(["bash", str(self.SCRIPT), "--off"],
                           capture_output=True, env=env)
        self.assertEqual(got, self.PAGE.read_bytes(),
                         "what it served is not the face in the repo")

    def test_a_board_with_no_network_is_told_it_is_RUNNING(self):
        """THE BUG THIS CLASS EXISTS FOR, and it is the evening's
        pattern one more time: the first version asked only "can the
        LAN address reach it", so on a board with no LAN address it
        printed `It did not come up` about a server that was serving
        perfectly. A check that cannot observe the actual failure mode
        is not a check -- and merging two questions with two different
        fixes into one is how you build one.

        Running-but-unreachable and not-running are DIFFERENT problems.
        The first needs WiFi; the second needs a restart."""
        done, port = self._run(lan=None)
        self.assertIn("RUNNING", done.stdout, done.stdout + done.stderr)
        self.assertNotIn("did not come up", done.stdout)
        self.assertIn("not on the network", done.stdout,
                      "it must say WHY the phone cannot reach it")

    def test_the_verdict_comes_first(self):
        """`pad --status` printed two alarming lines about a transport
        that was not in use and put the answer last, and Ghost read a
        working controller as broken. The answer goes on the first line
        with content on it."""
        done, port = self._run()
        first = [ln.strip() for ln in done.stdout.splitlines() if ln.strip()]
        self.assertTrue(first, "it printed nothing at all")
        self.assertTrue(first[0].startswith(("UP", "RUNNING", "NOT RUNNING")),
                        f"the verdict is buried: {first[0]!r}")

    @staticmethod
    def _this_machines_lan_ip():
        """This box's own routable address, or None. Same UDP-socket
        trick drop.py uses -- no packet is sent, the routing table just
        says which local address it WOULD leave from."""
        import socket
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            probe.connect(("8.8.8.8", 53))
            found = probe.getsockname()[0]
        except Exception:
            return None
        finally:
            probe.close()
        return None if found.startswith("127.") else found

    def test_it_prints_the_lan_address_never_docker_or_the_usb_link(self):
        """Third time this exact confusion has cost time: `hostname -I`
        lists 172.17.0.1 (docker) and 192.168.55.1 (the USB gadget link
        to the phone's serial console) alongside the real address, and
        only the last is reachable over WiFi.

        The decoys are put AHEAD of the real one, because taking the
        first line is exactly the mistake being guarded against."""
        real = self._this_machines_lan_ip()
        if not real:
            self.skipTest("this machine has no routable address to serve on")
        done, port = self._run(lan=real)
        self.assertIn(f"http://{real}:{port}/face.html", done.stdout,
                      done.stdout + done.stderr)
        for wrong in ("172.17.0.1", "192.168.55.1", "127.0.0.1"):
            if wrong == real:
                continue
            self.assertNotIn(f"http://{wrong}", done.stdout,
                             f"it told him to open {wrong}, which is not "
                             "reachable from the phone")

    def test_an_unreachable_address_is_not_reported_as_UP(self):
        """The other half of the split, and the reason it is a split:
        a server that is running but cannot be reached from the LAN is
        a REAL failure and must not be dressed up as success. 10.1.2.3
        is not this machine, so nothing can answer on it."""
        done, port = self._run(lan="10.1.2.3")
        self.assertIn("RUNNING", done.stdout)
        self.assertIn("cannot reach it", done.stdout)
        self.assertNotIn(f"http://10.1.2.3:{port}/face.html", done.stdout,
                         "it printed an address that does not work")
        self.assertEqual(done.returncode, 1)

    def test_status_says_not_running_when_it_is_not(self):
        done, port = self._run("--status")
        self.assertIn("NOT RUNNING", done.stdout)
        self.assertEqual(done.returncode, 1,
                         "--status must exit non-zero when it is down")

    def test_off_is_safe_to_run_twice(self):
        """He will run it twice. It must not read as an error."""
        done, port = self._run("--off")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)



def _shuffled(seed=None):
    """Run every test in a RANDOM order.

    TEST POLLUTION IS INVISIBLE IN A FIXED ORDER. One test assigned over
    `yuzu_wiki.look_up` and never put it back, and five unrelated wiki
    tests failed further down the run -- which read as the wiki having
    regressed, not as the test that caused it. It only shows when the
    order changes, so:

        python3 YUZU_TESTER.py --shuffle          random seed
        python3 YUZU_TESTER.py --shuffle 7        that exact order again

    A failure here and a pass in the normal run means one test is
    leaving something behind. The seed is printed so it can be
    reproduced rather than chased."""
    import random
    seed = random.randrange(10000) if seed is None else int(seed)
    flat = []

    def walk(suite):
        for item in suite:
            walk(item) if isinstance(item, unittest.TestSuite) \
                else flat.append(item)

    walk(unittest.TestLoader().loadTestsFromModule(sys.modules[__name__]))
    random.Random(seed).shuffle(flat)
    print(f"shuffled with seed {seed} -- rerun this exact order with:")
    print(f"    python3 YUZU_TESTER.py --shuffle {seed}\n")
    result = unittest.TextTestRunner(verbosity=1).run(unittest.TestSuite(flat))
    if not result.wasSuccessful():
        print("\nFAILED IN THIS ORDER BUT NOT THE NORMAL ONE?")
        print("Then a test is leaving something behind. Look at what ran")
        print("BEFORE the failure, not at the failure.")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    if "--shuffle" in sys.argv:
        at = sys.argv.index("--shuffle")
        seed = sys.argv[at + 1] if len(sys.argv) > at + 1 else None
        sys.exit(_shuffled(seed))
    unittest.main(verbosity=2)
