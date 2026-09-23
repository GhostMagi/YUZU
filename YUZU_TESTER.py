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

import contextlib
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
import urllib.error
import urllib.request
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
        # ANY label, not the two that were hardcoded. `(User|You)` was
        # true of every persona here until Four's examples started
        # labelling his turn with his own name -- and the check would
        # have gone blind on the ONE character it matters most on, the
        # front door, where a stranger watches her write both halves.
        for label in ("Ghost", "Four", "Cait"):
            self.assertFalse(
                prompt_eval.no_puppeteering("Sure.\n%s: thanks" % label),
                "no_puppeteering misses the label %r" % label)
        # and it still leaves ordinary text alone
        for fine in ("it is 3:30 babe", "Flexbox on the parent.",
                     "Warm, mostly. I can feel the fan pick up."):
            self.assertTrue(prompt_eval.no_puppeteering(fine),
                            "no_puppeteering flags %r" % fine)
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

    def test_show_LIVE_names_the_pointer_and_prints_the_real_prompt(self):
        """THE COMMAND GHOST ACTUALLY TYPES. He tests in PocketPal on a
        phone, so the composed prompt is the deliverable and this is
        what prints it.

        CLAUDE.md's own conventions block told whoever read it to run
        `--show shiro_deck` -- and that line went stale the day Saya was
        promoted, stayed stale through Four, and was still there on
        Sept 20. A hardcoded cast in a DOC, which is worse than one in a
        page: a page has a test.

        So the flag names the POINTER. It is driven through a real shell
        rather than read, and compared against the live persona's own
        composed prompt, because "it printed something" is exactly what
        `--show shiro_deck` did for eleven days."""
        import subprocess
        here = Path(__file__).parent
        done = subprocess.run(
            [sys.executable, str(here / "yuzu_personas.py"), "--show", "live"],
            capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0, done.stderr)
        live = yuzu_personas.load(yuzu_personas.LIVE_PERSONA)
        self.assertIn(live.prompt.strip(), done.stdout,
                      "--show live printed somebody else's prompt")
        self.assertIn(live.name, done.stdout)
        # A persona genuinely called `live` would shadow the word, so
        # the alias is guarded rather than unconditional -- and nobody
        # should create one.
        self.assertNotIn("live", yuzu_personas.available(),
                         "a persona named `live` shadows the pointer")
        # And the doc says the same thing, because the doc going stale
        # is the failure this exists for.
        self.assertIn("--show live", (here / "CLAUDE.md").read_text(),
                      "the conventions block names a key again")

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

        for name in TestYuzu5.MEASURED_WINS:
            self.assertTrue(TestYuzu5.carries(name, prompt),
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

    # AND THE ANSWER-FIRST WIN IS AN ORDER, NOT A PHRASE -- the second
    # instance of the identical fault, caught by Four. Every persona
    # before her happens to spell it "answer it first"; hers reads
    # "Answer the question first and plainly", which is the same rule
    # in the same position doing the same job. A literal needle would
    # have forced her wording to match a test instead of her register,
    # which is exactly backwards -- CLAUDE.md already records that
    # false positive against Coco's brevity rule and against Byte's.
    ANSWER_FIRST_WIN = "answer-first rule, fixed the dodge"
    ANSWER_FIRST_RE = re.compile(
        r"answer (?:it|the question)(?: \w+){0,2} first", re.I)

    @staticmethod
    def carries(name, text):
        """Does this prompt carry that measured win?

        ONE PLACE THAT KNOWS WHICH WINS ARE PHRASES AND WHICH ARE
        BEHAVIOURS. Five tests read MEASURED_WINS and the brevity regex
        was special-cased in exactly ONE of them -- so the other four
        went on matching a literal, and a second regex would have made
        that four copies of the same `if`. Callers ask this instead."""
        if name == TestYuzu5.BREVITY_WIN:
            return bool(TestYuzu5.BREVITY_RE.search(text))
        if name == TestYuzu5.ANSWER_FIRST_WIN:
            return bool(TestYuzu5.ANSWER_FIRST_RE.search(text))
        return TestYuzu5.MEASURED_WINS[name] in text

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
        for name in self.MEASURED_WINS:
            self.assertTrue(self.carries(name, prompt), f"v5 dropped: {name}")

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
        for name in TestYuzu5.MEASURED_WINS:
            self.assertTrue(TestYuzu5.carries(name, prompt),
                            f"v6 dropped: {name}")

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

    def test_the_stop_token_is_the_label_her_own_examples_use(self):
        """A decoder guard that names a word the prompt no longer
        contains is a guard that does nothing, SILENTLY -- she simply
        starts writing his side of the conversation again.

        `PARAMETER stop "User:"` was hardcoded, and it was right for
        every persona in the repo until Four's examples began labelling
        his turn `Ghost:`. It is read off the composed prompt now, so a
        character who learns a name keeps the guard, and a character
        who never does keeps "User:".

        Driven rather than read: the generator is run against both."""
        import build_yuzu_model, yuzu_personas
        for key in ("yuzu", "four"):
            label = build_yuzu_model.ask_label(yuzu_personas.load(key))
            rendered = build_yuzu_model.render(persona_key=key)
            self.assertIn('PARAMETER stop "%s"' % label, rendered)
            # and the label is one the prompt genuinely uses
            self.assertIn("\n" + label + " ", rendered,
                          "%s stops on a label its own examples never "
                          "write" % key)
        self.assertNotEqual(
            build_yuzu_model.ask_label(yuzu_personas.load("yuzu")),
            build_yuzu_model.ask_label(yuzu_personas.load("four")),
            "both labels are the same, so this test cannot tell a read "
            "one from a hardcoded one")

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
        # AND RETIRED CHARACTERS ARE EXEMPT TOO, for the same reason
        # the archives are. Ghost, Sept 11: "we no longer need coco
        # shes retired. or the shiro." They are kept as the record;
        # holding a record to today's wins would eventually force a
        # choice between editing the evidence and a red suite.
        characters = [k for k in yuzu_personas.available()
                      if k != yuzu_personas.LIVE_PERSONA
                      and not yuzu_personas.load(k).retired
                      and yuzu_personas.load(k).hardware
                      == live_persona.hardware]
        self.assertTrue(characters, "no peer characters on the live body")
        for key in characters:
            persona = yuzu_personas.load(key)
            for name in TestYuzu5.MEASURED_WINS:
                if not TestYuzu5.carries(name, live):
                    continue
                if (not persona.moves
                        and name in TestYuzu5.BODY_PROTOCOL_WINS):
                    continue
                self.assertTrue(TestYuzu5.carries(name, persona.prompt),
                                f"{key} lacks: {name}")

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
        for name in TestYuzu5.MEASURED_WINS:
            if not TestYuzu5.carries(name, live):
                continue                      # not a win the live arm has
            self.assertTrue(TestYuzu5.carries(name, coco),
                            f"coco lacks: {name}")

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


class TestCait(unittest.TestCase):
    """Cait -- the cait sith, on her own tab, in her own world.

    Ghost, Sept 11: "id like to have this. its own tab. and for it to
    act like a cait sith (whatever that means, may require u to study
    them a bit) seperate thing from saya", plus "Doesnt need access to
    wiki this is more of a personal RP one", "dont let it think its a
    cyberdeck per se its its own thing", and "id like her to not be
    green and black xD the image colors are fine."

    Every test here pins one of those sentences."""

    PAGE = Path(__file__).parent / "ui" / "cait.html"
    ART = Path(__file__).parent / "ui" / "cait" / "cait.png"

    def test_she_loads_and_is_her_own_character(self):
        cait = yuzu_personas.load("cait")
        self.assertEqual(cait.name, "Cait")
        self.assertEqual(cait.hardware, "faerie")
        self.assertNotEqual(cait.name, yuzu_personas.load(
            yuzu_personas.LIVE_PERSONA).name, "she is Saya with a hat on")

    def test_she_has_never_heard_of_a_computer(self):
        """THE POINT OF THE SEPARATE BODY FILE. The deck self-concept
        was a measured win ON THE DECK -- "my battery's always running
        low" arriving unprompted -- and it is an active fault here. A
        win is measured against a specific failure; a different
        character in a different world does not inherit it."""
        prompt = yuzu_personas.load("cait").prompt.lower()
        for word in ("cyberdeck", "handheld computer", "battery",
                     "screen", "ai assistant", "language model"):
            self.assertNotIn(word, prompt,
                             f"Cait's prompt tells her about '{word}'")
        self.assertIn("otherworld", prompt)
        # "never a generic AI assistant" is in every OTHER persona and
        # was in the first draft of this one. It came out, and this
        # pins that: it is the pink-elephant pattern -- naming the
        # thing she must not be -- which this repo has measured three
        # times, and it is self-defeating on a character who is
        # supposed to have never heard the word. What actually fixed
        # assistant collapse was the ONE EXAMPLE of a technical
        # question (round 3 -> round 4, categorical), and she has it.
        self.assertNotIn("assistant", prompt)

    def test_the_folklore_is_actually_in_her(self):
        """He asked me to study them, so this pins the four beats that
        make her a cait sith rather than a generic cat:

          the crown      the King of the Cats tale -- a procession, a
                         small coffin, a crown, and a cat who leaps up
                         crying that the king is dead
          the milk       leave it out and the house is blessed; withhold
                         it and the cows dry up. She trades, and she
                         keeps score.
          the wake       she sits with the newly dead the night before
                         burial. Stated as work, not as horror.
          the contest    her kind cannot refuse a riddle or a wager --
                         which is why the old wake-games existed."""
        prompt = yuzu_personas.load("cait").prompt.lower()
        for beat in ("crown", "coffin", "milk", "bless", "buried",
                     "riddle", "wager"):
            self.assertIn(beat, prompt, f"the folklore lost '{beat}'")

    def test_she_carries_the_levers_this_repo_actually_measured(self):
        """She starts where the lineage ended, not where it began.

        Each of these example SHAPES fixed a measured failure: the bare
        command (yuzu4, 4/4), the warm statement with no question
        (Shiro round 2), and the technical question (Shiro round 3 ->
        4, where assistant collapse went from a markdown manual with
        fenced code blocks to two sentences in her own register).

        A new character built without them restarts the lineage from
        the worst prompt in the repo, which is exactly what the rotten
        `--new` scaffold used to do."""
        prompt = yuzu_personas.load("cait").prompt
        self.assertIn("User: Stand up.", prompt, "no bare command")
        self.assertIn("actually gave me chills", prompt,
                      "no warm statement with nothing to answer")
        self.assertIn("center a div", prompt, "no technical question")
        # and the technical one has to be ANSWERED, not deflected
        tech = prompt.split("center a div in CSS?")[1].split("User:")[0]
        self.assertIn("flex", tech.lower(),
                      "she dodges the technical question, which teaches "
                      "her to dodge every question")

    def test_every_sound_she_is_taught_survives_the_voice(self):
        """`Mrrp` and `Mm` were the first draft and both were cut: no
        vowel means espeak spells them out letter by letter, the exact
        mechanism that made PFFT come out "Pee Eff Eff Tee"."""
        import yuzu_voice
        sounds = yuzu_personas.load("cait").settings["SOUND_EXAMPLES"]
        for sound in (x.strip() for x in sounds.split(",")):
            self.assertTrue(yuzu_voice.for_speech(sound).strip(),
                            f"the voice drops '{sound}'")
            self.assertTrue(set(sound.lower()) & set("aeiou"),
                            f"'{sound}' has no vowel -- espeak will "
                            f"spell it out one letter at a time")

    # ---- her page ----------------------------------------------------

    def test_her_page_exists_offline_with_her_picture(self):
        self.assertTrue(self.PAGE.exists())
        self.assertTrue(self.ART.exists(), "her art is not in the repo")
        page = self.PAGE.read_text()
        for reach in ("http://", "https://", "//cdn", "@import",
                      "fonts.googleapis"):
            self.assertNotIn(reach, page,
                             f"cait.html reaches outside itself: {reach}")
        self.assertIn('src="cait/cait.png"', page)

    def test_she_is_NOT_green_on_black(self):
        """Ghost: "id like her to not be green and black xD the image
        colors are fine." Her palette is sampled off her own picture --
        slate-blue fur, crimson cape, cream, gold."""
        page = self.PAGE.read_text()
        self.assertNotIn("#39ff5e", page, "she got the deck's neon green")
        for hers in ("--gold", "--wine", "--slate"):
            self.assertIn(hers, page, f"{hers} is missing from her palette")

    def test_she_is_a_STILL_IMAGE_and_needs_no_sprite_set(self):
        """Ghost: "Id have to design a new face (anime faces look p much
        the same throughout sounds annoying)". Correct, and this art is
        one detailed pose -- slicing it into expressions is work he does
        not want for a result that would look worse. What makes her feel
        alive happens AROUND the picture."""
        page = self.PAGE.read_text()
        self.assertNotIn("sprites.json", page, "she grew a sprite set")
        self.assertIn("breathe", page, "she is a dead sticker")
        self.assertIn("body.thinking", page,
                      "nothing shows that she is answering")

    def test_the_grid_row_is_BOUNDED_so_she_cannot_overflow(self):
        """THE BUG RENDERING FOUND. A grid row is `auto` by default, so
        it grew to fit her and `max-height` had nothing bounded to
        resolve against: measured, a 779px image inside a 460px stage,
        painting straight over the ask bar and her own Speak button."""
        page = self.PAGE.read_text()
        self.assertIn("grid-template-rows: minmax(0, 1fr)", page)
        self.assertIn("z-index: 2", page,
                      "the ask bar can fall behind her again")

    def test_a_broken_rail_never_takes_her_page_down(self):
        """`.catch(() => {})`. If the roster cannot be fetched the rail
        is simply absent and she still talks -- the same call the brain
        makes about the face server, and Piper, and the wiki import."""
        page = self.PAGE.read_text()
        # [-1], NOT [1]. "characters.json" appears twice -- once in the
        # comment explaining the rail and once in the fetch -- so [1]
        # is the text BETWEEN them, which stops just before the code
        # this test is about. It failed on correct code. Same family as
        # every other grep-as-proxy fault in here: the assertion was
        # about the file's spelling rather than about the page.
        rail = page.split("characters.json")[-1].split("</script>")[0]
        self.assertIn(".catch(", rail,
                      "a failed roster fetch is unhandled")


def drive_route(path, body):
    """Call the REAL `do_POST` for one route and return what it answered.

    READING THE SOURCE IS WHAT KEPT MISSING THIS. Two versions of the
    empty-name check split `do_POST`'s text on a literal route name:
    the first landed in a NEIGHBOUR'S COMMENT that happened to quote
    `/forget`, and the second stopped at a neighbour's `if path ==`
    before reaching the branch it was aiming at. Both read a paragraph
    and reported on a guard they never saw. Build a request, run the
    branch, read the verdict."""
    import io, json as _json, yuzu_face
    raw = _json.dumps(body).encode()
    handler = object.__new__(yuzu_face._Handler)
    handler.path = path
    handler.headers = {"Content-Length": str(len(raw))}
    handler.rfile = io.BytesIO(raw)
    answered = {}
    handler._json = lambda obj, code=200: answered.update(obj, _code=code)
    handler.do_POST()
    return answered


class TestTheCastIsTwo(unittest.TestCase):
    """Ghost, Sept 20: "Can we actually remove saya cait and mimi? I
    dont need them they were laye night tests really. Like from the
    interface of the cyberdeck entirely. For now i only wana keep Yuzu
    and Four. With Four as the main ai"

    RETIRED, NOT DELETED -- the call Coco and Shiro already set. Their
    personas, their pages and their art stay on disk as the record, and
    un-retiring is deleting one line. What changed is the ROSTER, which
    is the one place this deck keeps its cast: the rail, the A.I.
    drawer, the front tile and the desktop icons all emptied together
    out of one dict, because not one of them holds a list of names.
    That is the payoff for four rounds of deleting hardcoded casts.

    MOST OF THIS CLASS WAS `TestCait`'S. Those properties were never
    about her -- they are about routing and the roster, and she was
    only ever the fixture -- so they live here now, pointed at the cast
    that is actually live. The cut characters earn a better job in
    them: a name that used to resolve and now must not is a far
    stronger unknown-name case than a string nobody ever wired up.
    """

    CUT = ("saya", "cait", "mimi")

    def test_a_name_crosses_and_nothing_else_does(self):
        """Same discipline as /launch/ and /vpet/: the page POSTs a
        NAME, CHARACTERS turns it into a persona key, and an unknown
        name is refused rather than quietly answered by whoever is
        live. Putting the wrong character on screen is the confusing
        kind of wrong."""
        import yuzu_face
        self.assertEqual(yuzu_face.persona_for("four"), "four")
        self.assertEqual(yuzu_face.persona_for("  FOUR "), "four")
        self.assertEqual(yuzu_face.persona_for("yuzu"), "yuzu_avatar")
        # "" IS NOT IN HERE, and that is deliberate. An unnamed request
        # is a real case with a real answer -- the front door -- and it
        # has its own test one function up. The old version of this
        # list carried it behind an `if hostile else None`, which is a
        # check that could not observe its own failure.
        for hostile in ("../../etc/passwd", "four;rm -rf /", "nope",
                        "saya_deck", "yuzu_avatar", "four\x00") + self.CUT:
            self.assertIsNone(yuzu_face.persona_for(hostile),
                              f"{hostile!r} resolved to a persona")

    def test_an_UNNAMED_request_goes_to_the_front_door_and_follows_it(self):
        """`persona_for` defaulted a missing name to the literal
        "saya" -- right while the bare address opened her page, and
        stale from the day it opened the home screen instead.

        CUTTING HER OFF THE ROSTER MADE IT ACCIDENTALLY SAFE RATHER
        THAN RIGHT: "saya" is simply not in CHARACTERS any more, so an
        unnamed request began being refused, which LOOKS like a
        deliberate guard and is not one. A correct answer reached by
        accident comes back the moment somebody adds a character under
        that name -- the same shape as `drives_face` comparing against
        a key that had quietly become None.

        So it names `FRONT`, and this MOVES it, because a default
        bound when the function is defined cannot follow a pointer."""
        import yuzu_face
        was = yuzu_face.FRONT
        try:
            self.assertEqual(yuzu_face.persona_for(None),
                             yuzu_face.persona_for(was))
            self.assertEqual(yuzu_face.persona_for(""),
                             yuzu_face.persona_for(was))
            yuzu_face.FRONT = "yuzu"
            self.assertEqual(yuzu_face.persona_for(None), "yuzu_avatar",
                             "an unnamed request is frozen to one "
                             "character rather than following the door")
        finally:
            yuzu_face.FRONT = was
        # ...and EVERY destructive route still refuses an empty name,
        # which is the half a default must never reach. DRIVEN: the
        # branch runs and the verdict is read, because two attempts at
        # reading this out of the source both reported on prose.
        for route in ("/forget", "/unremember"):
            answered = drive_route(route, {"who": ""})
            self.assertFalse(
                answered.get("ok"),
                "%s accepted an empty name, so a blank field now wipes "
                "the front character" % route)
        # and the ADDITIVE ones still take the honest default, which is
        # the other half -- a guard that refuses everything is not a
        # guard, it is an outage.
        self.assertTrue(drive_route("/facts", {}).get("ok"),
                        "/facts refuses a request that names nobody")

    def test_the_FRONT_door_and_the_LIVE_arm_are_still_TWO_pointers(self):
        """The name-leak rule again: decide whether a fact belongs to
        THIS CHARACTER or to WHOEVER IS LIVE, and pin it accordingly.

        `FRONT` decides who greets you. `LIVE_PERSONA` decides which
        prompt boots -- `yuzu_brain --chat`, the eval, the terminal
        icon. `deckapps` asks each one with its own flag, and a
        character can be either without being the other.

        THEY NAME THE SAME CHARACTER TODAY, which is exactly the
        condition under which a collapse into one pointer would go
        unnoticed -- the identical trap that hid the dead `/wiki` gate
        for a week, where the wrong answer agreed with the right one
        for the only character anybody tested. So this MOVES each one
        and asserts the other stays put."""
        import yuzu_face
        was_front, was_live = yuzu_face.FRONT, yuzu_personas.LIVE_PERSONA
        try:
            yuzu_face.FRONT = "yuzu"
            self.assertTrue(yuzu_face.front_app().startswith("Yuzu\t"),
                            "the front door does not follow FRONT")
            self.assertEqual(yuzu_face.live_app(),
                             yuzu_personas.load(was_live).name,
                             "moving FRONT dragged the live arm with it")
            yuzu_face.FRONT = was_front
            yuzu_personas.LIVE_PERSONA = "yuzu_avatar"
            self.assertEqual(yuzu_face.live_app(), "Yuzu")
            self.assertTrue(
                yuzu_face.front_app().startswith(
                    yuzu_personas.load(
                        yuzu_face.CHARACTERS[was_front][0]).name + "\t"),
                "moving the live arm dragged the front door with it")
        finally:
            yuzu_face.FRONT = was_front
            yuzu_personas.LIVE_PERSONA = was_live

    def test_with_NOBODY_on_the_face_page_nobody_drives_it(self):
        """THE CROSS-TALK TRAP, in the shape the two-character deck
        leaves it in. `face.html` polls /state to pick a sprite, and
        that file belongs to whoever is on that page -- so a second
        character writing to it would light a face up in another window
        and read as a haunted deck rather than as a bug.

        Saya was the only character ever on `face.html` and she is off
        the interface now, so the honest invariant is the stronger one:
        NOBODY writes it. And the gate is derived from the roster's own
        page rather than from a name, so a character put back on
        `face.html` lights it up again with no code change -- which is
        what this drives, rather than asserting the file never moves."""
        import yuzu_face

        class Fake:
            def __init__(self, **kw): pass
            def ask(self, text): return "..."

        yuzu_face.set_state("idle")
        was = dict(yuzu_face._BRAINS)
        was_cast = dict(yuzu_face.CHARACTERS)
        try:
            with mock.patch.object(yuzu_face, "_BRAINS", {}):
                with mock.patch("yuzu_brain.YuzuBrain", Fake):
                    for who in yuzu_face.CHARACTERS:
                        yuzu_face.answer("hello", who)
                        self.assertEqual(
                            yuzu_face.get_state().get("state"), "idle",
                            f"{who} drove a face page nobody is on")
                    # ...and it is the ROSTER that decides, not a name.
                    yuzu_face.CHARACTERS["four"] = ("four", "face.html", "x")
                    yuzu_face._BRAINS.clear()
                    yuzu_face.answer("hello", "four")
                    self.assertEqual(
                        yuzu_face.get_state().get("state"), "talking",
                        "a character back on face.html cannot drive it")
        finally:
            yuzu_face.CHARACTERS.clear()
            yuzu_face.CHARACTERS.update(was_cast)
            yuzu_face._BRAINS.clear()
            yuzu_face._BRAINS.update(was)
            yuzu_face.set_state("idle")

    def test_the_rail_is_ONE_roster_and_the_pages_hold_no_list(self):
        """Ghost: "persona switcher button seems Boss Status."

        Built from /characters.json, which comes from CHARACTERS in
        yuzu_face.py. If a page carried its own copy of the cast it
        would drift the first time somebody was added -- or, as of
        this round, the first time somebody was taken away.

        THE BANNED NAMES ARE THE CUT ONES, which is the whole argument
        for the roster made concrete: the fastest way to put Saya back
        on the interface by accident is to type her into a page."""
        import yuzu_face
        for page in ("cait.html", "yuzu.html", "four.html", "mimi.html"):
            text = (Path(__file__).parent / "ui" / page).read_text()
            self.assertIn("characters.json", text, page)
            # HER OWN NAME IS EXEMPT ON HER OWN PAGE: `<div id="who">`
            # is the heading, not the rail, and banning it outright
            # would be the pink-elephant fix aimed at the wrong half --
            # the same call the chat icon's name already forced.
            mine = Path(page).stem.capitalize()
            for name in ("Saya", "Cait", "Mimi", "Byte", "Coco", "Shiro"):
                if name == mine:
                    continue
                self.assertNotIn(">%s<" % name, text,
                                 f"{name} is hardcoded into {page}'s rail")
        # THE PROPERTY, NOT A LIST OF NAMES. This asserted the literal
        # set {saya, cait, yuzu} and went red the moment Mimi landed --
        # a test that has to be edited every time the thing it guards
        # works correctly. The guarantee worth pinning is that the rail
        # and the roster are the SAME cast, which is the whole reason
        # /characters.json exists.
        cast = {c["who"] for c in yuzu_face.roster()}
        self.assertEqual(cast, set(yuzu_face.CHARACTERS),
                         "the rail and the roster disagree about the cast")

    def test_the_cut_characters_are_off_the_INTERFACE_and_still_on_disk(self):
        """The two halves of "remove them from the interface entirely"
        without deleting a thing.

        OFF: no roster entry, so no rail button, no drawer tile, no
        desktop icon and no route -- `persona_for` refuses the name, so
        her page cannot ask a question even if it is opened by hand.

        ON DISK: her persona, her page and her art are exactly where
        they were, marked `retired` in one line. Mimi in particular had
        a page AND a persona AND art, which is what used to earn a
        button automatically; she has all three and no button now, and
        that is the ask rather than a regression."""
        import yuzu_face
        here = Path(__file__).parent
        cast = {c["who"] for c in yuzu_face.roster()}
        for who, key, page in (("saya", "saya_deck", "face.html"),
                               ("cait", "cait", "cait.html"),
                               ("mimi", "mimi", "mimi.html")):
            self.assertNotIn(who, yuzu_face.CHARACTERS,
                             f"{who} is back on the rail")
            self.assertNotIn(who, cast)
            self.assertIsNone(yuzu_face.persona_for(who),
                              f"{who} can still be asked a question")
            self.assertTrue((here / "personas" / f"{key}.persona").exists(),
                            f"{key} was deleted rather than retired")
            self.assertTrue(yuzu_personas.load(key).retired,
                            f"{key} is not marked retired")
            self.assertTrue((here / "ui" / page).exists(),
                            f"{page} was deleted rather than unlinked")

    def test_retired_characters_are_off_the_roster_but_still_on_disk(self):
        """Ghost, Sept 11: "we no longer need coco shes retired. or the
        shiro." And Sept 20, the same call for three more.

        RETIRED, NOT DELETED. Every superseded thing in this repo is
        kept -- muto_s2, saya_quad, yuzu2/3/5/6 -- and that record is
        what stopped yuzu5 being re-attempted from scratch. A persona
        file costs nothing while nobody names it, and un-retiring is
        deleting one line.

        (The LEDs went the other way, deleted outright, and the
        difference is worth keeping straight: that was live code you
        had to read around. This is data nobody loads unless asked.)"""
        import yuzu_face
        for key in ("coco", "coco_deck", "shiro", "shiro_deck",
                    "cait", "mimi", "saya", "saya_deck"):
            self.assertTrue(
                (Path(__file__).parent / "personas" / f"{key}.persona").exists(),
                f"{key} was deleted rather than retired")
            self.assertTrue(yuzu_personas.load(key).retired,
                            f"{key} is not marked retired")
        names = {c["name"] for c in yuzu_face.roster()}
        for gone in ("Coco", "Shiro", "Saya", "Cait", "Mimi"):
            self.assertNotIn(gone, names)

    def test_a_character_with_no_page_is_ABSENT_from_the_rail(self):
        """The ROLES rule, one level up. Byte and the whole yuzu
        lineage are real personas with no art and no page -- putting
        them on a button would send him to a face that is not theirs,
        which is the "switching persona leaves Saya's face on screen"
        bug the design chat correctly predicted.

        A role with no art is absent rather than pointing at the wrong
        face. So is a character."""
        import yuzu_face
        self.assertIn("byte", yuzu_personas.available())
        self.assertNotIn("byte", yuzu_face.CHARACTERS,
                         "a character with no page got a button")
        for who, (key, page, blurb) in yuzu_face.CHARACTERS.items():
            self.assertTrue(
                (Path(__file__).parent / "ui" / page).exists(),
                f"the rail offers {who}, whose page {page} is missing")

    def test_the_wiki_stays_on_the_DECK_and_off_everyone_else(self):
        """A lookup arrives as "I looked up X and it says: <700 chars
        of encyclopedia>", which is the shortest path to assistant
        collapse on a character who is not the machine.

        It was CAIT who demonstrated this until she came off the
        interface, and the guard matters more now, not less: Yuzu is
        the only character left who is off the deck, so she is the only
        thing standing between that gate and nobody testing it."""
        import yuzu_face
        asked = []

        class Fake:
            def __init__(self, **kw): pass
            def ask(self, text): asked.append(text); return "..."

        was = dict(yuzu_face._BRAINS)
        try:
            with mock.patch.object(yuzu_face, "_BRAINS", {}):
                with mock.patch("yuzu_brain.YuzuBrain", Fake):
                    with mock.patch.object(
                            yuzu_brain.yuzu_wiki, "as_context",
                            lambda t: ("I looked up %s: FACTS." % t, None)):
                        yuzu_face.answer("/wiki cats", "yuzu")
                        self.assertEqual(asked[-1], "/wiki cats",
                                         "an encyclopedia reached the avatar")
                        yuzu_face.answer("/wiki cats", "four")
        finally:
            yuzu_face._BRAINS.clear()
            yuzu_face._BRAINS.update(was)
            yuzu_face.set_state("idle")
        self.assertIn("FACTS", asked[-1],
                      "the deck's own voice cannot reach the encyclopedia")



class TestYuzuAvatar(unittest.TestCase):
    """Yuzu, back with a body she can be dressed in.

    Ghost, Sept 11: "Yuzu. let her be able to 'switch outfits' and also
    if she doesnt already think she has a virtual body or body let that
    be a thing. (in case i wana paint her nails she wouldnt just be
    like 'ima computer') same treatment as Cait."

    The parenthesis is the spec and most of these tests pin it."""

    PAGE = Path(__file__).parent / "ui" / "yuzu.html"
    ART = Path(__file__).parent / "ui" / "yuzu"

    def voice_block(self, page):
        """The `hear()` function with comments stripped.

        THIRTEENTH INSTANCE OF THE GREP-MATCHES-PROSE TRAP WAITING TO
        HAPPEN: this block's own comment explains why `who` must be her
        own name, and names the failure. A test reading the prose would
        find whatever the comment discusses."""
        text = (Path(__file__).parent / "ui" / page).read_text()
        text = re.sub(r"^\s*//.*$", "", text, flags=re.M)
        start = text.index("function hear(words)")
        return text[start:text.index("\n}", start) + 2]

    def test_her_page_asks_for_HER_voice_and_not_somebody_elses(self):
        """Ghost, Sept 20: "Can we give Yuzus page the voice like Four
        has?"

        The server builds one voice PER CHARACTER and reaches her own
        `piper_length_scale` to do it, so a `who` copied along with the
        rest of the block does not merely mislabel the request -- it
        hands her ANOTHER CHARACTER'S SPEAKING RATE. Yuzu runs 0.88 and
        Four runs 0.9, so the mistake is real, and it is inaudible in
        the code and only barely audible out of the speaker: a character
        bug wearing a plumbing costume, which is the shape this repo
        already paid for when Kokoro's `speed` was nearly passed a
        duration multiplier.

        Both ends are pinned: the name the page sends, and the fact that
        the two characters really do differ, because if they ever
        converge this test stops meaning anything and should be re-read
        rather than trusted."""
        import yuzu_personas, yuzu_face
        self.assertIn("who: 'yuzu'", self.voice_block("yuzu.html"),
                      "her page asks for somebody else's voice")
        scales = {}
        for who in ("yuzu", "four"):
            key = yuzu_face.persona_for(who)
            found = re.search(r"piper_length_scale:\s*([\d.]+)",
                              (Path(__file__).parent / "personas"
                               / ("%s.persona" % key)).read_text())
            scales[who] = found and found.group(1)
        self.assertNotEqual(scales["yuzu"], scales["four"],
                            "the two rates converged, so a copied `who` "
                            "would no longer be audible: re-read this")

    def test_both_speaking_pages_hear_the_SAME_way(self):
        """TWO COPIES, PINNED TO AGREE -- the guard the battery renderer
        and the way out already carry, and for the same reason: there is
        no build step on this deck, so a page that speaks is a page with
        its own copy of the fetch.

        What actually threatens this is a third character page copied
        from whichever one somebody happened to open, drifting on the
        revoke, the `r.ok` check or the silent catch. Only the NAME may
        differ, so that is the one thing normalised away before the
        comparison."""
        mine = self.voice_block("yuzu.html").replace("who: 'yuzu'", "WHO")
        hers = self.voice_block("four.html").replace("who: 'four'", "WHO")
        self.assertEqual(mine, hers,
                         "the two speaking pages have drifted apart")
        self.assertIn("WHO", mine, "the name was not where it was expected")


    def test_she_loads_and_is_the_gyaru_on_a_new_body(self):
        yuzu = yuzu_personas.load("yuzu_avatar")
        self.assertEqual(yuzu.name, "Yuzu")
        self.assertEqual(yuzu.hardware, "avatar")
        self.assertFalse(yuzu.moves, "the avatar world has no servos")
        self.assertFalse(yuzu.retired)
        # SHE SHARES A NAME WITH THE WHOLE yuzu2..yuzu6 LINEAGE AND WITH
        # yuzu_deck, which is legitimate and deliberate -- same
        # character, different bodies, exactly like shiro/shiro_deck and
        # saya_quad/saya_deck. The name-leak rule says the fix belongs
        # in what gets DISPLAYED, not in forbidding it, and the boot
        # banner already prints the KEY whenever it differs from the
        # name. This pins that the keys stay distinct.
        same_name = [k for k in yuzu_personas.available()
                     if yuzu_personas.load(k).name == "Yuzu"]
        self.assertIn("yuzu_avatar", same_name)
        self.assertIn("yuzu_deck", same_name)
        self.assertEqual(len(same_name), len(set(same_name)))

    def test_she_has_a_body_and_never_answers_with_the_machine(self):
        """THE WHOLE ASK. "in case i wana paint her nails she wouldnt
        just be like 'ima computer'".

        {DECK_SELF} says, in as many words, "You have no legs, no arms,
        no camera and no face" -- so that block IS the failure he
        named, and this is the third time this repo has had to record
        that a measured win is measured against a SPECIFIC failure. On
        the deck it was a win. On a character with a wardrobe it is
        damage."""
        prompt = yuzu_personas.load("yuzu_avatar").prompt.lower()
        for machine in ("no legs", "no arms", "handheld computer",
                        "battery", "cyberdeck", "language model"):
            self.assertNotIn(machine, prompt,
                             f"the avatar prompt still says '{machine}'")
        for body in ("nails", "outfit", "tail", "hair"):
            self.assertIn(body, prompt, f"she has no '{body}'")

    def test_the_body_is_DRAWN_which_is_the_honest_bound(self):
        """"You have a body" with nothing bounding it is how deck Shiro
        ended up offering to "'walk' over to the kitchen" -- recorded
        above as a self-concept fault.

        A drawn body is the line that is both true and useful: a
        drawing has nails you can paint and a jacket you can change,
        and it does not walk anywhere."""
        prompt = yuzu_personas.load("yuzu_avatar").prompt.lower()
        self.assertIn("drawn", prompt)
        self.assertIn("not one that walks anywhere", prompt,
                      "nothing stops her offering to fetch the milk")

    def test_every_character_on_this_body_declares_her_OWN_look(self):
        """WHAT SHE LOOKS LIKE IS HERS, NOT THE WORLD'S.

        The faerie file gets this split right: its world says "fur, a
        tail, paws" -- true of any fae cat -- while Cait's own file
        carries "large, dark, with one patch of white at your breast".
        The first draft of the avatar world put Yuzu's blonde hair and
        her tail in the SHARED file, which is the character bleed this
        repo already paid for once: the sounds rule shipped "Ehehe~" to
        a kuudere and a netrunner from a file about legs.

        Ghost, Sept 11: "avatars may change down the road." That is
        exactly when a shared default dresses the next character as
        Yuzu, silently. {LOOK} is defaulted to hers so no composed
        prompt shifted by a byte, and this makes the decision forced
        rather than remembered."""
        import yuzu_face
        body = yuzu_personas.load("yuzu_avatar").hardware
        wearing_it = [k for k in yuzu_personas.available()
                      if yuzu_personas.load(k).hardware == body]
        self.assertIn("yuzu_avatar", wearing_it)
        for key in wearing_it:
            persona = yuzu_personas.load(key)
            self.assertIn("LOOK", persona.settings,
                          f"{key} inherits another character's body "
                          f"from the shared world file")
            self.assertTrue(persona.settings["LOOK"].strip(),
                            f"{key} declares an empty LOOK")
        # and the world file must not describe any ONE character
        world = (Path(__file__).parent / "personas"
                 / "_hardware_avatar.txt").read_text()
        body_text = world.split("[AVATAR_SELF]")[1].split("[")[0]
        for hers in ("blonde", "brown eyes"):
            self.assertNotIn(hers, body_text,
                             f"the shared world file still says '{hers}'")

    def test_no_outfit_is_named_in_her_prompt(self):
        """THE WARDROBE IS DATA. ui/yuzu/ is the list, /outfits.json is
        generated from it per request, and the filename is the button.
        Naming the outfits in the prompt would make it code again and
        the list would go stale the first time he draws another one --
        the same reason `sprites()` scans a folder instead of reading a
        manifest."""
        prompt = yuzu_personas.load("yuzu_avatar").prompt.lower()
        import yuzu_face
        for outfit in yuzu_face.outfits():
            self.assertNotIn(outfit, prompt,
                             f"'{outfit}' is hardcoded into her prompt")

    def test_she_carries_the_levers_this_repo_actually_measured(self):
        """The three example SHAPES that each fixed a measured failure:
        the bare command (yuzu4, 4/4), the warm statement with nothing
        to answer (Shiro round 2), and the technical question (Shiro
        round 3 -> 4, a categorical fix of assistant collapse).

        A new arm built without them restarts the lineage from the
        worst prompt in the repo."""
        prompt = yuzu_personas.load("yuzu_avatar").prompt
        self.assertIn("User: Spin around.", prompt, "no bare command")
        self.assertIn("made my whole day", prompt,
                      "no warm statement with nothing to answer")
        self.assertIn("center a div", prompt, "no technical question")
        tech = prompt.split("center a div in CSS?")[1].split("User:")[0]
        self.assertIn("flex", tech.lower(),
                      "she dodges the technical question, which teaches "
                      "her to dodge every question")

    def test_a_body_request_is_ANSWERED_in_her_examples(self):
        """Examples beat rules -- measured twice in this repo. The rule
        telling her she has a body is worth much less than her being
        SHOWN taking a body request and running with it, so the two
        shapes he actually named get an example each."""
        prompt = yuzu_personas.load("yuzu_avatar").prompt
        for ask in ("Can I paint your nails?", "Can I have a hug?"):
            self.assertIn("User: " + ask, prompt, f"no example for '{ask}'")
            reply = prompt.split(ask)[1].split("User:")[0]
            for dodge in ("no arms", "no hands", "I'm a computer",
                          "I don't have"):
                self.assertNotIn(dodge.lower(), reply.lower(),
                                 f"she deflects '{ask}' with '{dodge}'")

    def test_she_still_sounds_like_the_gyaru(self):
        """The body changed; the character did not. Her register is
        hers and this repo pins it to yuzu4 for exactly that reason."""
        prompt = yuzu_personas.load("yuzu_avatar").prompt.lower()
        for hers in ("cutie", "pink", "gyaru", "mall"):
            self.assertIn(hers, prompt, f"she lost '{hers}'")

    def test_every_sound_she_is_taught_survives_the_voice(self):
        """Same check Cait gets. A sound with no vowel is spelled out
        letter by letter by espeak -- the PFFT mechanism."""
        import yuzu_voice
        prompt = yuzu_personas.load("yuzu_avatar").prompt
        line = [l for l in prompt.splitlines() if "just write them:" in l]
        self.assertTrue(line, "the sounds rule is gone")
        sounds = line[0].split("just write them:")[1].strip(" .")
        for sound in (x.strip() for x in sounds.split(",")):
            self.assertTrue(yuzu_voice.for_speech(sound).strip(),
                            f"the voice drops '{sound}'")
            self.assertTrue(set(sound.lower()) & set("aeiou"),
                            f"'{sound}' has no vowel -- espeak will "
                            f"spell it out one letter at a time")

    def test_CSS_is_spelled_out_rather_than_phonemised(self):
        """Her technical-question example SAYS the word out loud, which
        no other persona's does. Lowercased by unshout() it becomes
        mush; kept capitalised espeak spells it, and "see ess ess" is
        how the word is actually pronounced. It went on the list the
        day a persona started saying it -- evidence, not speculation."""
        import yuzu_voice
        self.assertIn("CSS", yuzu_voice.SPOKEN_INITIALISMS)
        self.assertIn("CSS", yuzu_voice.for_speech("it's the only CSS I like"))

    # ---- her wardrobe -------------------------------------------------

    def test_a_folder_is_the_wardrobe_and_a_png_is_an_outfit(self):
        """Same rule as "a folder is a character" in the V-Pet and "the
        filename is the expression" in her sprites. Adding an outfit is
        dropping a file in, with nothing else to edit anywhere."""
        import yuzu_face
        found = yuzu_face.outfits()
        self.assertGreaterEqual(len(found), 2,
                                "there is nothing to switch between")
        for outfit in found:
            self.assertTrue((self.ART / (outfit + ".png")).exists())
        self.assertNotIn("ART", found, "the provenance note became an outfit")

    def test_a_missing_wardrobe_is_empty_and_never_an_exception(self):
        """Same guard as sprites(): the page treats an empty list as
        "no button", not as "no Yuzu" -- her <img> carries a real src
        in the markup, so a dead route costs the wardrobe and never
        costs her."""
        import yuzu_face
        self.assertEqual(yuzu_face.outfits("/nowhere/at/all"), [])
        page = self.PAGE.read_text()
        self.assertIn('src="yuzu/', page,
                      "she has no picture until JavaScript supplies one")

    def test_every_outfit_is_the_same_canvas_so_she_does_not_jump(self):
        """ONE box across every state of a character, never one per
        state -- the V-Pet lesson, where a per-state crop made him
        change size when his mood did.

        Here it is worse than cosmetic: two outfits of the same girl at
        two different scales read as a glitch rather than a change of
        clothes."""
        import yuzu_face
        sizes = set()
        for outfit in yuzu_face.outfits():
            size = yuzu_face._png_size(str(self.ART / (outfit + ".png")))
            self.assertIsNotNone(size, f"{outfit}.png is not a readable PNG")
            sizes.add(size)
        self.assertEqual(len(sizes), 1,
                         f"her outfits are different sizes: {sizes}")

    def test_the_button_names_the_outfit_it_will_PUT_HER_IN(self):
        """Same call as the V-Pet's swap button and the old colour dot:
        what she is wearing right now is standing in the middle of the
        screen, so a button labelling it tells you nothing."""
        page = self.PAGE.read_text()
        self.assertIn("outfits[(wearing + 1) % outfits.length]", page,
                      "the wardrobe button names what she already has on")

    def test_the_outfits_route_is_regenerated_per_request(self):
        """A new PNG needs a page refresh, never a server restart. On a
        phone over a serial link that is a much bigger difference than
        it sounds -- the same reason /sprites.json is rebuilt per GET.

        DRIVEN, NOT GREPPED. An assertion that "outfits()" appears in
        do_GET's source would pass just as happily against a list
        cached at import time, which is the exact failure it exists to
        catch. This one starts the real server, adds a real file, and
        asks the real route twice."""
        import json as _json
        import shutil
        import threading
        import urllib.request
        import yuzu_face

        room = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, room, True)
        shutil.copy(str(self.ART / "zebra.png"),
                    os.path.join(room, "zebra.png"))

        from http.server import ThreadingHTTPServer
        server = ThreadingHTTPServer(("127.0.0.1", 0), yuzu_face._Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        url = "http://127.0.0.1:%d/outfits.json" % server.server_address[1]

        def ask():
            with urllib.request.urlopen(url, timeout=5) as got:
                return _json.loads(got.read().decode())

        with mock.patch.object(yuzu_face, "OUTFIT_DIR", room):
            self.assertEqual(ask(), ["zebra"])
            shutil.copy(str(self.ART / "cream.png"),
                        os.path.join(room, "cream.png"))
            self.assertEqual(ask(), ["cream", "zebra"],
                             "a new outfit needs a server restart to "
                             "show up, which on a phone is a real cost")

    # ---- her page ------------------------------------------------------

    def test_her_page_exists_offline_with_her_art(self):
        self.assertTrue(self.PAGE.exists())
        self.assertTrue((self.ART / "ART.txt").exists(),
                        "nobody wrote down where her picture came from")
        page = self.PAGE.read_text()
        for reach in ("http://", "https://", "//cdn", "@import",
                      "fonts.googleapis"):
            self.assertNotIn(reach, page,
                             f"yuzu.html reaches outside itself: {reach}")

    def test_she_is_NOT_green_on_black_either(self):
        """The CRT look is locked to the deck screens on purpose --
        the same call cait.html and vpet.html already make. Her palette
        is sampled off her own PNGs, except the hot pink, which is
        character."""
        page = self.PAGE.read_text()
        self.assertNotIn("#39ff5e", page, "she got the deck's neon green")
        for hers in ("--pink", "--blonde", "--slate"):
            self.assertIn(hers, page, f"{hers} is missing from her palette")

    def test_she_is_shown_WHOLE_because_her_shoes_are_half_the_outfit(self):
        """The one place this page refuses to copy Cait's.

        Cait is deliberately cropped at the shins -- her picture is a
        pose and nothing below the knee carries information. Yuzu's
        picture is an OUTFIT, and the most legible difference between
        her two looks is at the bottom of it: grey fur boots and leg
        warmers against white knee socks. Measured by rendering it at
        the panel's real 1024x600: at Cait's 136% she is cut just above
        the leg warmers, which hides the exact thing the wardrobe
        button exists to show."""
        page = self.PAGE.read_text()
        height = re.search(r"#yuzu\s*\{[^}]*height:\s*(\d+)%", page)
        self.assertIsNotNone(height, "her height is not set in percent")
        self.assertLessEqual(int(height.group(1)), 100,
                             "she overruns the stage and loses her shoes")
        # and the breath needs headroom, or `overflow: hidden` shaves
        # her hair off the top on every cycle
        self.assertLess(int(height.group(1)), 100,
                        "the breath has nowhere to go")
        self.assertIn("align-items: end", page,
                      "she is hung from the ceiling rather than standing")

    def test_her_page_holds_no_list_of_the_cast_and_no_list_of_outfits(self):
        """Both come from the server: /characters.json from ONE roster
        in yuzu_face.py, /outfits.json from ONE folder. A page that
        keeps its own copy of either drifts the first time something is
        added."""
        page = self.PAGE.read_text()
        self.assertIn("characters.json", page)
        self.assertIn("outfits.json", page)
        for name in ("Saya", "Cait", "Byte", "Coco", "Shiro"):
            self.assertNotIn(">%s<" % name, page,
                             f"{name} is hardcoded into her rail")

    def test_she_has_a_way_out_and_it_is_never_a_mode(self):
        """Every screen on this deck has an exit, which is the rule two
        power cycles paid for. And the switcher is a visible row rather
        than a menu: a menu is a mode, and a mode needs a way out of
        its own."""
        page = self.PAGE.read_text()
        self.assertIn("home.html", page, "there is no way off her page")
        self.assertNotIn("kiosk", page)

    def test_she_asks_as_a_NAME_and_the_server_refuses_anything_else(self):
        """Same allowlist discipline as /launch/ and /vpet/. The server
        binds 0.0.0.0, so a name crossing the wire must never be able
        to reach a file."""
        import yuzu_face
        page = self.PAGE.read_text()
        self.assertIn("who: 'yuzu'", page)
        self.assertEqual(yuzu_face.persona_for("yuzu"), "yuzu_avatar")
        self.assertEqual(yuzu_face.persona_for("  YUZU "), "yuzu_avatar")
        for hostile in ("yuzu_avatar", "../../etc/passwd", "yuzu;rm -rf /",
                        "yuzu4", "yuzu_deck", "yuzu\x00"):
            self.assertIsNone(yuzu_face.persona_for(hostile),
                              f"'{hostile}' resolved to a persona")


class TestCutout(unittest.TestCase):
    """`yuzu_cutout.py` -- backdrop out, ghosts kept.

    Ghost, Sept 12: "i went to remove the background to make it a png
    online but it removed the cool parts too like the ghosts behind
    her. can you pull this off with regular images whilst keeping the
    cool art?"

    Everything here is DRIVEN against a synthetic picture rather than
    against his art, because what decides all of it is what the
    function does to pixels -- and because a test that needs a
    particular JPEG is a test that rots the day the art changes.
    """

    def setUp(self):
        self.cut = __import__("yuzu_cutout")
        if self.cut.Image is None:
            self.skipTest("Pillow is a workbench dependency and is absent")

    def test_every_recipe_names_a_picture_that_is_actually_there(self):
        """A recipe for a file nobody has is a note, not a setting, and
        it goes stale silently. `yuzu_outfits` is exempt: Ghost's Yuzu
        art was deliberately NOT adopted (the new source carries a white
        keyline and the resolution buys nothing), and the recipe stays
        as the record of that round."""
        art = Path(__file__).parent / "ui" / "art_in"
        for name in self.cut.RECIPES:
            self.assertTrue((art / (name + ".jpg")).exists(),
                            "RECIPES has %r and ui/art_in does not" % name)

    def test_the_art_she_SHIPS_was_cut_with_its_recipe(self):
        """Ghost, Sept 12, on the sulking pose: "this exact image looks
        off to me on her robe its part black" and "the white gab between
        her legs is slightly bothersome too."

        Both were one cause: `ghost_crowd` had no recipe, so the default
        hi=58 walked through her near-white outline and tore the cape
        open, while the enclosed gap between her legs was left behind.

        THE FAILURE THIS GUARDS IS RE-CUTTING WITHOUT THE RECIPE. The
        committed PNG is what the deck actually shows; the recipe only
        matters if it was the thing that made it. So this drives the
        real tool over the real source and compares the ALPHA to the
        file in ui/mimi/ -- and it is deliberately not a byte compare of
        the colours, because a Pillow version can shift a resample by a
        level without anything being wrong."""
        import io
        root = Path(__file__).parent
        src = root / "ui" / "art_in" / "ghost_crowd.jpg"
        shipped = root / "ui" / "mimi" / "ghost_crowd.png"
        if not (src.exists() and shipped.exists()):
            self.skipTest("her art is not in this checkout")
        Image = self.cut.Image
        opts = dict(self.cut.DEFAULTS)
        opts.update(self.cut.RECIPES["ghost_crowd"])
        fresh = self.cut.lift(Image.open(src).convert("RGB"), **opts)
        have = Image.open(shipped).convert("RGBA")
        fresh = fresh.resize(have.size, Image.LANCZOS)

        def solid(im):
            a = im.split()[3]
            return sum(1 for v in a.getdata() if v > 200)

        want, got = solid(fresh), solid(have)
        self.assertLess(abs(want - got) / float(want), 0.02,
                        "ui/mimi/ghost_crowd.png is not what the recipe "
                        "produces -- it was re-cut on the defaults, which "
                        "is what tore her cape open")

    def picture(self, backdrop=(250, 250, 250)):
        """A dark ring (her), a same-colour hole inside it (her cape),
        and a detached blob away from her (a ghost)."""
        im = self.cut.Image.new("RGB", (80, 80), backdrop)
        d = __import__("PIL.ImageDraw", fromlist=["ImageDraw"]).Draw(im)
        d.ellipse([20, 20, 60, 60], outline=(20, 20, 30), width=3,
                  fill=backdrop)            # her: outline, backdrop inside
        d.ellipse([4, 4, 12, 12], fill=(90, 140, 200))   # a floating ghost
        return im

    def test_a_detached_ghost_survives_the_cut(self):
        """THE WHOLE POINT. A subject detector drops anything that is
        not the person; this keeps everything that is not the backdrop,
        so a ghost floating in the corner with nothing joining it to
        her comes through untouched."""
        out = self.cut.lift(self.picture(), lo=10, hi=40)
        a = out.getchannel("A").load()
        self.assertGreater(a[8, 8], 200, "the floating ghost was eaten")
        self.assertEqual(a[0, 0], 0, "the backdrop survived")

    def test_it_floods_rather_than_matching_colour(self):
        """Her cape is the same white as the page. A colour match would
        erase it; a flood cannot get through her outline."""
        out = self.cut.lift(self.picture(), lo=10, hi=40)
        a = out.getchannel("A").load()
        self.assertGreater(a[40, 40], 200,
                           "the fill walked through her outline and "
                           "erased the inside of her")

    def test_alpha_is_a_ramp_not_a_cutoff(self):
        """Same lesson as yuzu_art.py: a hard threshold turns every
        anti-aliased edge into a staircase, and this art is nothing but
        soft edges. Some pixel on the boundary has to land between."""
        out = self.cut.lift(self.picture(), lo=6, hi=60)
        seen = set(out.getchannel("A").tobytes())
        self.assertTrue(any(0 < v < 255 for v in seen),
                        "every pixel is fully on or fully off")

    def test_the_backdrop_is_taken_back_out_of_the_soft_edge(self):
        """THE HALO. An edge pixel is a MIX of her and the page, so
        cutting the backdrop out without un-mixing the colour leaves a
        bright rim tracing her whole silhouette on any dark page.
        Ghost saw it as "jagged pixels from removing outline"."""
        white = (255, 255, 255)
        edge = (250, 250, 250)          # nearly all page, a little her
        rgba = self.cut.Image.new("RGBA", (1, 1), edge + (128,))
        fixed = self.cut.unfringe(rgba, white).getpixel((0, 0))
        self.assertLess(fixed[0], edge[0],
                        "the page is still sitting in the edge colour")
        self.assertEqual(fixed[3], 128, "it moved the alpha")

    def test_a_seed_brings_its_own_tone(self):
        """An inset panel is unreachable from the edge, and the first
        version gated seeds against the BORDER's colour -- so a seed
        dropped into a grey panel on a white page was refused by the
        very tolerance it existed to get around. It could only succeed
        where it was not needed."""
        im = self.picture()
        d = __import__("PIL.ImageDraw", fromlist=["ImageDraw"]).Draw(im)
        d.rectangle([62, 62, 78, 78], fill=(180, 180, 190))   # a panel
        plain = self.cut.lift(im, lo=6, hi=20)
        seeded = self.cut.lift(im, lo=6, hi=20, seeds=[(70, 70)])
        self.assertGreater(plain.getchannel("A").load()[70, 70], 200,
                           "the panel went without being asked")
        self.assertLess(seeded.getchannel("A").load()[70, 70], 40,
                        "the seed did not reach the panel")

    def test_pockets_are_opt_in_because_they_ate_a_cape(self):
        """Backdrop her own body encloses is only safe to take when she
        wears nothing like it. On the tan pictures it cleared the gap
        between her legs; on a white page it took her face."""
        out = self.cut.lift(self.picture(), lo=10, hi=40, pockets=True)
        self.assertLess(out.getchannel("A").load()[40, 40], 40,
                        "pockets did not reach the enclosed backdrop")
        self.assertFalse(self.cut.DEFAULTS["pockets"],
                         "pockets are on by default, which eats capes")

    def test_the_corner_check_asks_about_COLOUR_not_just_opacity(self):
        """It read "a corner is always backdrop" first and failed three
        cuts that were perfect, because in this art the corners are
        ghosts, blue flame and graveyard rock."""
        im = self.cut.Image.new("RGBA", (40, 40), (12, 200, 90, 255))
        pct, solid, note = self.cut.sanity(im, (250, 250, 250), 10)
        self.assertEqual(note, "look", "opaque art in a corner read as a miss")
        page = self.cut.Image.new("RGBA", (40, 40), (250, 250, 250, 255))
        self.assertIn("BACKDROP LEFT BEHIND",
                      self.cut.sanity(page, (250, 250, 250), 10)[2])

    def test_the_deck_never_needs_pillow(self):
        """Workbench only. "Installs nothing" is what lets the brain run
        in Pydroid on his phone, and what ships is a plain PNG."""
        import yuzu_face
        source = Path(__file__).parent / "yuzu_face.py"
        self.assertNotIn("PIL", source.read_text())
        self.assertNotIn("yuzu_cutout", source.read_text())

    def test_it_says_to_look_because_the_numbers_cannot_tell(self):
        """Two guards were tried and both were wrong in opposite
        directions -- one failed a perfect two-figure sheet, the other
        passed a cut that had destroyed her. For image work the only
        check this repo has ever found that holds is looking, so the
        run writes a contact sheet and says so."""
        source = (Path(__file__).parent / "yuzu_cutout.py").read_text()
        self.assertIn("_CONTACT_SHEET.png", source)
        self.assertIn("contact_sheet", source)


class TestMimiBody(unittest.TestCase):
    """`personas/_hardware_wisp.txt` -- her world and her body, and
    deliberately not one word of her temperament.

    Ghost, Sept 12: "Dont design the characters persona yet im still
    trying to brainstrorm her personality", and then "make a body file
    for her too". Those are compatible, and the split between them is
    the whole reason body files exist in this repo.
    """

    FILE = Path(__file__).parent / "personas" / "_hardware_wisp.txt"

    def test_the_world_exists_and_declares_a_body_that_cannot_move(self):
        text = self.FILE.read_text()
        self.assertIn("[MOVES]", text)
        self.assertRegex(text, r"\[MOVES\]\s*\n\s*no")
        for block in ("[WISP_SELF]", "[SOUND_EXAMPLES]", "[LOOK]"):
            self.assertIn(block, text, "%s is missing" % block)

    def test_she_is_not_a_cyberdeck(self):
        """{DECK_SELF} was a MEASURED win on the deck and is damage on
        anyone else. Third time this has had to be said in a body
        file."""
        text = self.FILE.read_text().lower()
        for machine in ("cyberdeck", "handheld computer", "battery",
                        "language model", "no legs, no arms"):
            self.assertNotIn(machine, text.split("referenced from")[-1],
                             "the wisp world says '%s'" % machine)

    def test_her_look_is_a_token_so_the_next_character_cannot_inherit_it(self):
        """The lesson from the avatar world, applied before it could go
        wrong rather than after: a specific character's colouring in a
        SHARED file is the sounds rule shipping a gyaru's "Ehehe~" to a
        kuudere all over again."""
        text = self.FILE.read_text()
        body = text.split("[WISP_SELF]")[1].split("[NO_STAGE")[0]
        self.assertIn("{LOOK}", body,
                      "her appearance is written into the shared world")

    def test_every_sound_it_teaches_survives_the_voice(self):
        """A sound with no vowel is spelled out letter by letter by
        espeak -- the mechanism that made PFFT come out "Pee Eff Eff
        Tee". Checked BEFORE they went in, not after."""
        import yuzu_voice
        text = self.FILE.read_text()
        sounds = text.split("[SOUND_EXAMPLES]")[1].split("[")[0].strip()
        for sound in (s.strip() for s in sounds.split(",")):
            self.assertTrue(yuzu_voice.for_speech(sound).strip(),
                            "the voice drops '%s'" % sound)
            self.assertTrue(set(sound.lower()) & set("aeiou"),
                            "'%s' has no vowel -- espeak will spell it "
                            "out one letter at a time" % sound)

    def test_the_world_file_still_carries_no_TEMPERAMENT(self):
        """Ghost wrote her personality himself, Sept 12, so the gap this
        file was holding open is closed -- but the SPLIT it exists for
        is not. Her temperament belongs in `mimi.persona`; anything of
        it that leaks in here is inherited by the next character on this
        body, which is the shared-file bleed that cost this repo the
        sounds rule and the avatar world's hair.

        The needles are the load-bearing words of her own rules. Each
        one is hers and none of them is true of a wisp in general."""
        text = self.FILE.read_text().split("Referenced from")[-1].lower()
        for hers in ("shiny", "sulk", "brat", "life force", "picked you",
                     "partner in crime", "little sister", "dote"):
            self.assertNotIn(hers, text,
                             "the WORLD file has grown a temperament: %r "
                             "would be inherited by the next character "
                             "on this body" % hers)
        self.assertNotIn("---", text, "a body file has no composed prompt")

    def test_she_travelled_here_and_therefore_knows_this_world(self):
        """Ghost, Sept 12, answering the one call this file left open:
        "she has knowledge of my world. she travlled here 500 years ago
        we will say from her original world."

        Both halves matter and they pull against each other, so both are
        pinned. NOT FROM HERE is what makes her a spirit from somewhere
        rather than a local ghost. KNOWS HERE is what stops her being
        Cait -- Cait has never heard of a computer and a test bans the
        word from her prompt, and running that same rule here would make
        every modern question a thing she has to work around, which
        costs latency on every turn forever."""
        prompt = self.FILE.read_text().split("Referenced from")[-1]
        self.assertRegex(prompt, r"five hundred years|500 years",
                         "nothing says when she arrived")
        self.assertRegex(prompt.lower(), r"not from this world",
                         "nothing says she came from somewhere else")
        self.assertRegex(
            prompt.lower(), r"nothing here (is strange|needs explaining)",
            "she arrived but the file never says she caught up")

    def test_whoever_writes_her_persona_is_told_about_assistant_collapse(self):
        """She knows this world, so she WILL be asked computer
        questions -- and that is the one failure this repo has a
        CATEGORICAL fix for. Markdown headings and fenced code blocks
        became two plain sentences on ONE example, round 3 to round 4.
        A character built without it restarts from the worst prompt in
        the repo, which is exactly what the rotten scaffold did to
        Saya."""
        header = self.FILE.read_text().split("Referenced from")[0].lower()
        self.assertIn("technical-question", header,
                      "the header never names the one measured lever the "
                      "next author is going to need")

    def test_her_art_is_in_the_repo_with_its_provenance(self):
        art = Path(__file__).parent / "ui" / "mimi"
        self.assertTrue(art.is_dir(), "her art never landed")
        pngs = sorted(p.name for p in art.glob("*.png"))
        self.assertGreaterEqual(len(pngs), 5)
        self.assertTrue((art / "ART.txt").exists(),
                        "nobody wrote down where her pictures came from")


class TestMimi(unittest.TestCase):
    """MIMI -- the imouto wisp, and the first character whose picture
    changes during a conversation.

    Ghost wrote her temperament himself, Sept 12, answering five
    questions: "her chosen human to attach to (for energy consumption i
    got alot of that as in she lives off my life force) and also my
    partner in crime", "she can dote on me a bit", "she wants life force
    or souls maybe shiny things too", and "she answers straight and
    listens to me as my energy keeps her 'here'".
    """

    KEY = "mimi"

    def persona(self):
        import yuzu_personas
        return yuzu_personas.load(self.KEY)

    def test_she_loads_and_lives_in_the_wisp_world(self):
        her = self.persona()
        self.assertEqual(her.hardware, "wisp")
        self.assertEqual(her.name, "Mimi")
        self.assertFalse(her.moves, "the wisp body declares [MOVES] no")

    def test_the_deck_self_is_nowhere_near_her(self):
        """{DECK_SELF} was a MEASURED win on the deck -- "my battery's
        always running low", unprompted -- and this repo has recorded
        four times now that a win is measured against a SPECIFIC
        failure. On a spirit with a real body it is not budget, it is
        damage."""
        prompt = self.persona().prompt.lower()
        for machine in ("cyberdeck", "handheld computer", "battery",
                        "language model", "no legs, no arms"):
            self.assertNotIn(machine, prompt,
                             "her prompt says %r" % machine)

    def test_she_knows_this_world_unlike_cait(self):
        """The half of Ghost's answer that is easy to lose. Cait has
        never heard of a computer and a test BANS the word from her
        prompt; running that rule here would make every modern question
        something Mimi has to work around, which costs latency on every
        turn forever. Five hundred years here is what buys her the
        technical-question example."""
        prompt = self.persona().prompt
        self.assertIn("five hundred years", prompt.lower())
        self.assertIn("CSS", prompt,
                      "she has no technical-question example -- the one "
                      "lever that fixed assistant collapse, four times")

    def test_she_knows_she_is_talking_to_a_MAN(self):
        """Ghost, Sept 12, on her first working conversation: "i did
        notice she thinks im a girl... that bothers me but its the only
        bit that does." She had opened with "Ahh, good girl."

        HER RULES ALREADY SAID `him` THIRTEEN TIMES. That is what makes
        this the rules-versus-examples finding again rather than a
        missing fact: every pronoun sat in a RULE describing a third
        party, every EXAMPLE addressed him with no gender in it at all,
        and a 3B handed a gap fills it from the base model's prior --
        where "good girl" is an extremely common thing for a small
        cute character to say.

        So the load-bearing half of the fix is the EXAMPLE, which is
        the lever this repo has measured working four times, and it is
        placed in the exact slot the fault appeared in: her praising
        him for finding something shiny."""
        persona = self.persona()
        self.assertIn("this one man", persona.prompt,
                      "nothing in her prompt says who she is talking to")
        spoken = [ln for ln in persona.prompt.splitlines()
                  if ln.startswith("Mimi:")]
        self.assertTrue(
            any("boy" in ln for ln in spoken),
            "no example shows her addressing him -- the rules alone did "
            "not hold, which is how 'good girl' got in")
        self.assertFalse(
            any("good girl" in ln.lower() for ln in spoken),
            "an example teaches the exact thing that went wrong")

    def test_she_carries_the_three_measured_example_SHAPES(self):
        """Bare command (yuzu4, 4/4), warm statement with nothing to
        answer (Shiro round 2), technical question (round 3 -> 4, a
        CATEGORICAL change). A character built without them restarts the
        lineage from the worst prompt in the repo."""
        asked = re.findall(r"^User: (.+)$", self.persona().prompt,
                           re.MULTILINE)
        self.assertTrue(any(a.rstrip(".!?").split() and
                            a[0].isupper() and a.endswith(".") and
                            "?" not in a and len(a.split()) <= 3
                            for a in asked),
                        "no bare command in %r" % (asked,))
        self.assertTrue(any("?" not in a and "thank" in a.lower()
                            for a in asked),
                        "no warm statement with nothing to answer")
        self.assertTrue(any("CSS" in a for a in asked),
                        "no technical question")

    def test_every_sound_she_is_taught_survives_the_voice(self):
        """A sound with no vowel is spelled out letter by letter -- the
        mechanism that made PFFT come out "Pee Eff Eff Tee". `Mmn` and
        `Nn` were the obvious clingy little noises and both were cut
        BEFORE they went in."""
        import yuzu_voice
        sounds = self.persona().blocks.get("SOUND_EXAMPLES", "")
        self.assertTrue(sounds, "she teaches no sounds at all")
        for sound in (s.strip() for s in sounds.split(",")):
            self.assertTrue(yuzu_voice.for_speech(sound).strip(),
                            "the voice drops %r" % sound)
            self.assertTrue(set(sound.lower()) & set("aeiou"),
                            "%r has no vowel -- espeak will spell it out "
                            "one letter at a time" % sound)

    def test_her_look_is_declared_in_HER_file(self):
        """The avatar world's lesson, and the default is exactly the
        thing that goes wrong quietly: the world file defaults {LOOK} to
        Mimi's own cape and ears, so a second character on this body
        would silently inherit them unless someone remembers. This is
        what forces the decision instead of trusting a memory."""
        self.assertIn("LOOK", self.persona().blocks,
                      "she leans on the world file's default look")

    def test_she_has_everything_a_button_needs_and_no_button(self):
        """THIS ASSERTED THE OPPOSITE UNTIL SEPT 20, and the flip is the
        point rather than a concession.

        It used to say: a character with art AND a persona AND a page
        earns a rail button, because the alternative -- art with no
        brain behind it -- opens a face that cannot answer. She has all
        three and no button now. Ghost: "Can we actually remove saya
        cait and mimi? ... Like from the interface of the cyberdeck
        entirely."

        So the roster's middle column is not the only gate any more:
        being ON the roster is a DECISION, and the three things below
        are what makes putting her back one dict entry rather than a
        round of work. Everything she needs is still here, which is the
        whole difference between retired and deleted."""
        import yuzu_face
        here = Path(__file__).parent
        self.assertTrue((here / "personas" / f"{self.KEY}.persona").exists())
        self.assertTrue((here / "ui" / "mimi.html").exists())
        self.assertTrue(any((here / "ui" / "mimi").glob("*.png")),
                        "her art went with her button")
        self.assertNotIn("mimi", yuzu_face.CHARACTERS,
                         "she is back on the interface")
        self.assertNotIn("mimi", [c["who"] for c in yuzu_face.roster()])


class TestMimiPoses(unittest.TestCase):
    """Her picture changes during a conversation, which no other
    character's does. Saya swaps sprites by state; Cait is one still
    image; Yuzu changes only on a button."""

    PAGE = Path(__file__).parent / "ui" / "mimi.html"

    def code(self):
        """The page with its comments removed.

        THE GREP-MATCHES-PROSE TRAP FIRED TWICE HERE, both times on
        this page's own notes: the comment saying "NO /state POLLING,
        deliberately" matched a test banning /state, and a comment
        reading "standing versus crawling versus sitting" matched a
        test counting how many of her pictures the page names. Both
        were a check tripping over the sentence explaining the absence
        it was checking for -- the seventh instance in this file, after
        the four in TestCalculator. Assert on code, or assert on the
        model; never on prose."""
        body = self.PAGE.read_text()
        body = re.sub(r"<!--.*?-->", " ", body, flags=re.S)
        body = re.sub(r"/\*.*?\*/", " ", body, flags=re.S)
        return "\n".join(ln.split("//")[0] for ln in body.splitlines())

    def test_every_pose_names_art_that_actually_exists(self):
        """A state pointing at a missing PNG puts a broken image on
        screen. Same rule as roles_for(): ABSENT beats wrong."""
        import yuzu_face
        served = yuzu_face.poses("mimi")
        self.assertTrue(served, "she has no poses at all")
        for state, url, scale in served:
            self.assertTrue(
                (Path(__file__).parent / "ui" / url).exists(),
                "%s points at %s, which is not there" % (state, url))

    def test_a_pose_whose_art_is_missing_is_DROPPED_not_served(self):
        import yuzu_face
        with mock.patch.dict(yuzu_face.POSES,
                             {"mimi": (("idle", "bunny_ghosts", 1.0),
                                       ("talking", "not_a_file", 1.0))},
                             clear=False):
            states = [s for s, _, _ in yuzu_face.poses("mimi")]
        self.assertEqual(states, ["idle"])

    def test_a_character_who_is_one_still_image_gets_no_poses(self):
        """Cait and Yuzu must come back EMPTY rather than raising, and
        their pages read that as "you are one picture", which they
        are."""
        import yuzu_face
        for who in ("cait", "yuzu", "saya"):
            self.assertEqual(yuzu_face.poses(who), [])

    def test_the_who_parameter_is_an_allowlist_like_every_other_route(self):
        """The server binds 0.0.0.0. `who` is a NAME looked up in a
        fixed dict, so nothing in a query string can ever name a file --
        same discipline as /launch/ and /vpet/."""
        import yuzu_face
        for hostile in ("../etc", "../../ui/yuzu", "mimi/../saya", "",
                        "MIMI; rm -rf /", None):
            self.assertEqual(yuzu_face.poses(hostile), [],
                             "%r got an answer" % (hostile,))

    def test_the_pose_comes_from_HER_OWN_stage_directions(self):
        """Not from a sentiment score. A sentiment score is a guess, and
        a wrong guess puts the wrong picture on a real reply; here a
        wrong picture needs her to have written the wrong thing. It
        reads mood_from, which is the ONE copy."""
        import yuzu_face
        self.assertEqual(yuzu_face.pose_for("[sulks] fine, whatever."),
                         "sulking")
        self.assertEqual(yuzu_face.pose_for("*pouts* I waited all day."),
                         "sulking")
        self.assertEqual(yuzu_face.pose_for("Ahh, there you are!"),
                         "talking")
        self.assertEqual(yuzu_face.pose_for(""), "talking")

    def test_every_pose_scale_is_one_the_art_can_actually_take(self):
        """RENDERING IS WHAT FOUND THIS. `ghost_crowd` is drawn edge to
        edge, so a 1.22 scale pushed her head past the stage's overflow
        and cut it off -- every assertion passed and the screenshot did
        not. A scale can only ever be a modest bump, and a pose with no
        headroom stays at 1.0."""
        import yuzu_face
        for state, url, scale in yuzu_face.poses("mimi"):
            self.assertGreaterEqual(scale, 1.0, state)
            self.assertLessEqual(scale, 1.25,
                                 "%s is scaled past what the stage can "
                                 "show without cropping her" % state)

    def test_the_page_holds_no_list_of_her_pictures(self):
        """The map lives in yuzu_face.POSES and arrives over
        /poses.json, so the page cannot disagree with the server about
        which picture means what. Only her opening pose is named in the
        markup, and that is on purpose: a real src means a dead server
        costs the pose changes and never costs HER."""
        page = self.PAGE.read_text()
        import yuzu_face
        named = [stem for _, stem, _ in yuzu_face.POSES["mimi"]
                 if stem in self.code()]
        self.assertEqual(len(named), 1,
                         "the page names %r -- it is keeping its own "
                         "copy of the pose map" % (named,))
        self.assertIn('src="mimi/', page,
                      "no real src in the markup: a dead server would "
                      "cost her entirely")

    def test_talking_to_her_never_drives_SAYAS_face(self):
        """THE CROSS-TALK TRAP. Saya's page polls /state to pick her
        expression and that file is hers -- without a guard, talking to
        Mimi in one window lights Saya's face up in another, which is
        the confusing kind of wrong."""
        page = self.code()
        self.assertNotIn("'state'", page)
        self.assertNotIn('"state"', page)
        self.assertNotIn("/state", page)


class TestSheStreamsAndRemembers(unittest.TestCase):
    """Streaming, the live board facts, and memory across a restart.

    Every one of these drives the REAL server through a real socket
    with a fake brain that is at least as STRICT as YuzuBrain --
    `TestEveryCharacterCanActuallyBeAsked` was green for two days over
    a stub that accepted anything, and a permissive stub does not test
    the caller, it excuses it."""

    class Brain:
        def __init__(self, persona=None, **kw):
            if not isinstance(persona, str):
                raise TypeError("persona= got %r" % (persona,))
            import yuzu_personas
            self.persona = yuzu_personas.load(persona)
            self.system_prompt = self.persona.prompt
            self.history, self.history_turns = [], 8

        def ask_stream(self, text):
            for piece in ("one ", "two ", "three"):
                yield piece
            self.history += [{"role": "user", "content": text},
                             {"role": "assistant", "content": "one two three"}]

        def ask(self, text):
            return "".join(self.ask_stream(text))

        def reset(self):
            self.history = []

    def setUp(self):
        import json, tempfile, threading, sys
        from http.server import ThreadingHTTPServer
        import yuzu_face
        self.face, self.json = yuzu_face, json

        outer = self
        class FakeBrainMod:
            YuzuBrain = outer.Brain
            @staticmethod
            def ground(text):
                return text, None
        self._real_brain = sys.modules.get("yuzu_brain")
        sys.modules["yuzu_brain"] = FakeBrainMod

        self._home = tempfile.mkdtemp()
        self._memory = yuzu_face.MEMORY_DIR
        yuzu_face.MEMORY_DIR = os.path.join(self._home, "history")
        self._stats = yuzu_face.stats
        yuzu_face.stats = lambda: {"watts": 5.6, "temp": 47, "power": "MAXN"}
        yuzu_face._BRAINS.clear()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), yuzu_face._Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        import shutil, sys
        self.server.shutdown()
        self.face.MEMORY_DIR = self._memory
        self.face.stats = self._stats
        self.face._BRAINS.clear()
        if self._real_brain is None:
            sys.modules.pop("yuzu_brain", None)
        else:
            sys.modules["yuzu_brain"] = self._real_brain
        shutil.rmtree(self._home, ignore_errors=True)

    def post(self, path, payload):
        import urllib.request
        req = urllib.request.Request(
            "http://127.0.0.1:%d%s" % (self.port, path),
            data=self.json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=20)

    def lines(self, response):
        return [self.json.loads(ln) for ln in response.read().decode().splitlines()
                if ln.strip()]

    def test_she_arrives_in_PIECES_and_not_in_one_lump(self):
        """The whole point. /say waited for the entire reply and the
        page was dead for ten to thirty seconds -- which is the "is it
        working or is it stuck" question this project keeps answering
        one layer at a time."""
        got = self.lines(self.post("/stream", {"text": "hi", "who": "four"}))
        pieces = [m["piece"] for m in got if "piece" in m]
        self.assertEqual(pieces, ["one ", "two ", "three"],
                         "it buffered instead of streaming")
        self.assertTrue(got[-1].get("done"), "no verdict line")
        self.assertEqual(got[-1]["said"], "one two three")

    def test_the_last_line_carries_the_verdict_so_a_cut_reply_shows(self):
        """A stream that dies halfway must be visibly unfinished rather
        than quietly truncated -- the same reason `pull` and `wiki
        --test` put the answer above the evidence."""
        got = self.lines(self.post("/stream", {"text": "", "who": "four"}))
        self.assertEqual(len(got), 1)
        self.assertFalse(got[0]["ok"])
        self.assertTrue(got[0]["done"])

    def test_BOTH_ways_of_asking_reach_the_same_brain(self):
        """One function, two transports. Duplicating the wiki
        grounding, the allowlist and the memory for the streaming route
        would only have made a second place to forget -- which is
        exactly what `ground()` exists to prevent one layer down."""
        import inspect
        source = inspect.getsource(self.face.answer)
        self.assertIn("on_chunk", source)
        self.assertEqual(source.count("load_memory"), 1)
        self.assertEqual(source.count("save_memory"), 1)
        plain = self.json.loads(self.post("/say", {"text": "hi", "who": "four"}).read())
        self.assertEqual(plain["said"], "one two three")

    def test_a_failed_save_keeps_the_memory_it_was_ALREADY_holding(self):
        """FOUND BY RUNNING THE SUITE AND LOOKING AT THE REAL `~/.yuzu`,
        Sept 20: five ZERO-BYTE memory files, created by the run.

        `open(path, "w")` truncates immediately, so the old memory was
        gone before the new one existed -- and when the dump then raised
        part way, the `except Exception: pass` swallowed it and left a
        half-written fragment behind. Measured on the real function: 58
        bytes of conversation became 29 bytes of
        `[{"role": "user", "content": ` and nothing anywhere said so.

        `load_memory` is guarded too, so the corrupt file parses as
        nothing and she boots having forgotten -- indistinguishable, on
        his screen, from her never having remembered. Two guards, each
        correct alone, together shredding the thing they protect.

        Writing beside it and renaming is what `pull` already does for
        a download, and `os.replace` is atomic: the file is entirely the
        old memory or entirely the new one, never a fragment."""
        import json as _json

        class WillNotSerialise:
            history_turns = 8
            history = [{"role": "user", "content": object()}]

        os.makedirs(self.face.MEMORY_DIR, exist_ok=True)
        path = self.face._memory_file("four")
        real = [{"role": "user", "content": "months of this"}]
        with open(path, "w", encoding="utf-8") as fh:
            _json.dump(real, fh)
        before = open(path, encoding="utf-8").read()

        self.face.save_memory(WillNotSerialise(), "four")   # must not raise

        self.assertEqual(before, open(path, encoding="utf-8").read(),
                         "a failed save destroyed the memory it held")
        self.assertEqual(real, _json.loads(open(path, encoding="utf-8").read()),
                         "what survived is no longer valid JSON")
        self.assertFalse(os.path.exists(path + ".part"),
                         "a scrap was left to be mistaken for a memory")

    def test_the_board_facts_reach_a_DECK_character_and_never_stack(self):
        """Four's rule 8 says she notices the fan, the heat and what is
        loaded, and until now she had no data at all -- so she invented
        a number every time. The stacking half is the real trap: a
        prompt appended to an already-appended prompt grows a line of
        stale readings per turn and stays invisible until the context
        fills."""
        self.post("/say", {"text": "how are you", "who": "four"}).read()
        prompt = self.face._BRAINS["four"].system_prompt
        self.assertIn("RIGHT NOW", prompt, "she was told nothing about the board")
        self.assertIn("5.6 watts", prompt)
        for _ in range(3):
            self.post("/say", {"text": "again", "who": "four"}).read()
        self.assertEqual(
            self.face._BRAINS["four"].system_prompt.count("RIGHT NOW"), 1,
            "the board line stacks, one stale copy per turn")

    def test_a_character_who_is_NOT_on_the_deck_is_told_no_such_thing(self):
        """It was CAIT who demonstrated this -- she has never heard of a
        computer and a test bans `battery` and `screen` from her prompt,
        so handing her the watts at runtime would walk straight around
        it. She came off the interface on Sept 20 and YUZU is now the
        only live character who is not the machine, which makes this
        guard matter more rather than less: she is the only thing left
        standing between the gate and nobody exercising it."""
        self.post("/say", {"text": "hello", "who": "yuzu"}).read()
        key = self.face.persona_for("yuzu")
        self.assertNotIn("RIGHT NOW", self.face._BRAINS[key].system_prompt)

    def test_her_specs_are_READ_from_this_machine_and_never_typed_in(self):
        """Asked for her specs, Four gave an Intel XScale palmtop with
        64MB of DDR and Windows CE -- invented whole, on the front door.

        The fix cannot be a spec string typed into the file: that is
        right until he swaps the NVMe, it is already wrong on the
        laptop and the phone, and the failure looks exactly like the
        deck working. So this drives the REAL function and checks the
        number against what this machine says about itself RIGHT NOW --
        which a hardcoded answer cannot pass on two different boxes."""
        self.face._SPECS = None
        try:
            said = self.face.board_specs()
        finally:
            self.face._SPECS = None
        with open("/proc/meminfo") as fh:
            for line in fh:
                if line.startswith("MemTotal:"):
                    gb = int(line.split()[1]) / (1024.0 * 1024.0)
                    break
        self.assertIn("%.1fGB of memory" % gb, said,
                      "her memory figure is not this machine's")
        self.assertIn("cores", said)

    def test_she_only_claims_SHARED_memory_where_the_memory_is_shared(self):
        """Shared CPU/GPU memory is the Orin's defining trait -- it is
        the whole keep_alive argument -- and it is flatly false of the
        laptop's discrete card. A confident wrong fact about her own
        body is worse than a missing one, so the clause rides on the
        Jetson check that already exists twice and is pinned to agree,
        rather than on a third copy."""
        import yuzu_doctor
        real = yuzu_doctor.on_a_jetson
        try:
            for jetson in (True, False):
                yuzu_doctor.on_a_jetson = lambda j=jetson: j
                self.face._SPECS = None
                said = self.face.board_specs()
                self.assertEqual(jetson, "shared between" in said,
                                 "shared-memory claim ignores the board")
        finally:
            yuzu_doctor.on_a_jetson = real
            self.face._SPECS = None

    def test_the_specs_reach_a_deck_character_and_never_stack(self):
        """Same trap as the live board line one function up: a prompt
        appended to an already-appended prompt grows a stale copy per
        turn and stays invisible until the context fills."""
        self.post("/say", {"text": "what are your specs", "who": "four"}).read()
        prompt = self.face._BRAINS["four"].system_prompt
        self.assertIn("WHAT YOU RUN ON", prompt,
                      "she was never told what she is made of")
        for _ in range(3):
            self.post("/say", {"text": "again", "who": "four"}).read()
        self.assertEqual(
            self.face._BRAINS["four"].system_prompt.count("WHAT YOU RUN ON"), 1,
            "the specs line stacks, one stale copy per turn")

    def test_a_character_off_the_deck_is_never_told_what_she_runs_on(self):
        """Same gate as the watts one function up, and the same reason
        it moved off Cait: she is retired, Yuzu is the only live
        character off the deck, and a drawn girl with a storage figure
        in her prompt is the deflection fault `_hardware_avatar.txt`
        exists to design against."""
        self.post("/say", {"text": "hello", "who": "yuzu"}).read()
        key = self.face.persona_for("yuzu")
        self.assertNotIn("WHAT YOU RUN ON",
                         self.face._BRAINS[key].system_prompt)

    # ---- and what is ON the board with her -------------------------

    def fake_board(self, roms=(), zims=()):
        """A board with a known library on it, so the inventory can be
        checked against something rather than against whatever this
        container happens to have. Returns the rendered line."""
        home = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, home, True)
        for system, names in roms:
            folder = os.path.join(home, "ROMs", system)
            os.makedirs(folder)
            for name in names:
                open(os.path.join(folder, name), "w").close()
        for zim in zims:
            with open(os.path.join(home, zim), "wb") as fh:
                fh.write(b"\0" * (2 << 20))   # over `wiki`'s 1MB floor
        real = os.path.expanduser

        def fake(path):
            return path.replace("~", home, 1) if path.startswith("~") else path
        patch = mock.patch.object(os.path, "expanduser", fake)
        patch.start()
        self.addCleanup(patch.stop)
        # The cache is a module global; leaving it set would hand the
        # next test this test's board.
        self.addCleanup(setattr, self.face, "_HAS", None)
        self.face._HAS, self.face._HAS_AT = None, 0
        return self.face.board_has()

    def test_what_is_ON_the_board_is_READ_and_never_typed_in(self):
        """The `ghostnano` rule and the `board_specs()` rule for the
        third time. A library typed into the file is right until he
        copies a ZIM across over WiFi or drops a ROM in from his phone
        -- and the failure looks exactly like the deck working.

        Checked against a board built for the purpose: a hardcoded
        answer cannot pass this AND pass on his Orin."""
        line = self.fake_board(
            roms=[("gba", ["a.gba", "b.gba", "c.gba"]),
                  ("snes", ["x.sfc"])],
            zims=["wikipedia_en_simple_all.zim"])
        self.assertIn("3 Game Boy Advance games", line)
        self.assertIn("1 SNES game", line,
                      "one game is pluralised as if it were several")
        self.assertIn("wikipedia en simple all", line)

    def test_a_SAVE_is_not_a_game(self):
        """Counting them tells him he has twice the library he has --
        and he WILL have them, because the whole point of the emulator
        is that he plays the things."""
        line = self.fake_board(roms=[("gba", [
            "pokemon.gba", "pokemon.sav", "pokemon.srm", "pokemon.state"])])
        self.assertIn("1 Game Boy Advance game", line)

    def test_a_system_nobody_thought_of_keeps_its_OWN_name(self):
        """`_SYSTEMS` is a politeness layer, not an allowlist. A folder
        it has never heard of still gets counted, because a library
        that silently omits things is worse than one that says
        `dreamcast` in lower case."""
        line = self.fake_board(roms=[("dreamcast", ["shenmue.gdi"])])
        self.assertIn("1 dreamcast game", line)

    def test_an_EMPTY_board_says_NOTHING_at_all(self):
        """ABSENT RATHER THAN WRONG, and here it matters more than on
        the specs line: "no games and no archives" would have her
        volunteering that the deck is empty to the first stranger who
        picks it up."""
        self.assertEqual(self.fake_board(), "")

    def test_the_inventory_is_BOUNDED(self):
        """It rides on the system prompt on EVERY turn, so an inventory
        that grows with the NVMe is one the context guard cannot see
        the worst case of -- forty ROM folders would quietly do what a
        full facts store is stopped from doing.

        The shelves are sorted biggest first, so a trim drops the ones
        he has a single game in, and the SENTENCE is never cut: half a
        clause is worse than a shorter list."""
        line = self.fake_board(
            roms=[("sys%02d" % i, ["g%d.rom" % n for n in range(i + 1)])
                  for i in range(40)],
            zims=["archive_number_%d.zim" % i for i in range(6)])
        # IT MUST NOT MEASURE AGAINST THE CONSTANT IT IS CHECKING.
        # The first version asserted `len(line) <= HAS_MAX` and passed
        # happily with HAS_MAX raised to 100000 -- the threshold moved
        # with the thing under test, so the check could not observe its
        # own failure. What it actually has to see is that shelves got
        # DROPPED, which is derived from the board it built.
        shown = sum(1 for i in range(40) if "sys%02d" % i in line)
        self.assertLess(shown, 40,
                        "every shelf survived, so nothing was trimmed "
                        "and the inventory is unbounded")
        self.assertLessEqual(len(line), self.face.HAS_MAX,
                             "it trimmed and still overran its own cap")
        self.assertTrue(line.rstrip().endswith("."),
                        "it cut the sentence in half rather than the list")

    def test_it_notices_a_ROM_he_just_sent_WITHOUT_a_restart(self):
        """The one real difference from the specs line. A processor
        does not change while the server is up; a ROM folder does,
        precisely because `drop.py` exists to put things in it from his
        phone. Needing a restart to see a file he just sent would be
        the stale-process fault wearing a helpful hat."""
        line = self.fake_board(roms=[("gba", ["a.gba"])])
        self.assertIn("1 Game Boy Advance game", line)
        roms = os.path.join(os.path.expanduser("~"), "ROMs", "gba")
        open(os.path.join(roms, "b.gba"), "w").close()
        # Still inside the cache window: she does not see it yet.
        self.assertIn("1 Game Boy Advance game", self.face.board_has())
        # EXPIRED ABSOLUTELY, NOT RELATIVE TO THE TTL. This read
        # `_HAS_AT -= _HAS_TTL + 1`, which expires the cache however
        # enormous the TTL is -- so it passed with the TTL set to a
        # billion seconds. Same fault as the bounded test one method
        # down: a check that derives its threshold from the constant
        # under test cannot see that constant change.
        self.face._HAS_AT = 0
        self.assertLessEqual(
            self.face._HAS_TTL, 600,
            "the inventory is cached for more than ten minutes, so a "
            "ROM he sends from his phone is not on the deck as far as "
            "she is concerned")
        self.assertIn("2 Game Boy Advance games", self.face.board_has(),
                      "the inventory never refreshes, so a ROM he sends "
                      "needs a server restart to exist")

    def test_the_inventory_reaches_a_deck_character_and_never_stacks(self):
        """Same trap as the board line and the specs line: a prompt
        appended to an already-appended prompt grows a stale copy per
        turn and stays invisible until the context fills."""
        with mock.patch.object(self.face, "board_has",
                               return_value="\n\nWHAT IS ON THE BOARD WITH YOU: x."):
            self.post("/say", {"text": "what have you got", "who": "four"}).read()
            prompt = self.face._BRAINS["four"].system_prompt
            self.assertIn("WHAT IS ON THE BOARD", prompt,
                          "she was never told what is on the board")
            for _ in range(3):
                self.post("/say", {"text": "again", "who": "four"}).read()
            self.assertEqual(
                self.face._BRAINS["four"].system_prompt.count(
                    "WHAT IS ON THE BOARD"), 1,
                "the inventory stacks, one stale copy per turn")

    def test_a_character_off_the_deck_never_hears_the_INVENTORY(self):
        """The same gate as the watts and the specs, and for the same
        reason: the archives and the ROMs are facts about the MACHINE,
        and Yuzu is a drawn girl who does not live on one."""
        with mock.patch.object(self.face, "board_has",
                               return_value="\n\nWHAT IS ON THE BOARD WITH YOU: x."):
            self.post("/say", {"text": "hello", "who": "yuzu"}).read()
        key = self.face.persona_for("yuzu")
        self.assertNotIn("WHAT IS ON THE BOARD",
                         self.face._BRAINS[key].system_prompt)

    def test_the_hardware_gate_is_READ_and_not_merely_written(self):
        """THE BUG THIS ROUND FOUND. `answer()` referenced
        `yuzu_personas` without importing it -- the module is imported
        INSIDE persona_for() and roster(), never at module level -- so
        every call raised NameError, the surrounding `except` swallowed
        it, and `has_wiki` fell back to `key == saya_deck`.

        So the gate CLAUDE.md records as "reads the hardware now" was
        answering a different question entirely, and /wiki has been
        DEAD on Four's page since she shipped. It hid because the wrong
        answer agreed with the right one for Saya, who is both the live
        arm and on the deck -- the only character anyone tested.

        This drives the real function rather than reading it, because
        reading it is what missed it."""
        self.assertFalse(hasattr(self.face, "yuzu_personas"),
                         "if this is now a module global, simplify the fix")
        self.post("/say", {"text": "hello", "who": "four"}).read()
        self.assertIn("RIGHT NOW", self.face._BRAINS["four"].system_prompt,
                      "the deck gate is not reading the hardware")

    def memory_ceiling(self):
        """How big her memory file can honestly get, off the two
        settings that bound it rather than off a number somebody typed.

        `history_turns` exchanges is 2x that many messages, each of her
        own capped at `num_predict` tokens; 4 bytes per token is a
        loose upper bound for English, and the JSON wrapper is small
        beside it. Doubling it is the headroom."""
        # Read from SOURCE, not from the module: this class stubs the
        # brain, and a helper that quietly picked up the stub's numbers
        # would be a guard measuring its own fixture.
        import re as _re, yuzu_personas
        brain = (Path(__file__).parent / "yuzu_brain.py").read_text()
        turns = int(_re.search(r"history_turns=(\d+)", brain).group(1))
        cap = int(yuzu_personas.load("four").settings["num_predict"])
        return 2 * (2 * turns * cap * 4)

    def test_she_remembers_across_a_restart_and_the_file_stays_small(self):
        """Every `~/YUZU/pull` bounces the face server, and that took
        the whole conversation with it."""
        self.post("/say", {"text": "my name is Ghost", "who": "four"}).read()
        saved = os.path.join(self.face.MEMORY_DIR, "four.json")
        self.assertTrue(os.path.exists(saved), "she wrote nothing down")
        # THE CAP IS DERIVED, not a number typed in. It was a literal
        # 8192 -- generous against a measured 247 bytes at num_predict
        # 250, and a guard that would have to be edited every time the
        # ceiling moved, which is the fault this repo keeps deleting.
        # What bounds the file is history_turns x num_predict, so that
        # is what it asks.
        self.assertLess(os.path.getsize(saved), self.memory_ceiling(),
                        "the memory file is fat")
        self.face._BRAINS.clear()                      # the server was bounced
        self.post("/say", {"text": "still there?", "who": "four"}).read()
        remembered = self.face._BRAINS["four"].history
        self.assertTrue(any("Ghost" in m["content"] for m in remembered),
                        "she forgot everything across the restart")

    def test_the_memory_is_CAPPED_and_cannot_creep(self):
        """`history_turns` is 8, so a file is at most 16 messages. A
        memory that grows without bound is a `pull` that gets slower
        every week for no visible reason."""
        for n in range(14):
            self.post("/say", {"text": "turn %d" % n, "who": "four"}).read()
        with open(os.path.join(self.face.MEMORY_DIR, "four.json")) as fh:
            self.assertLessEqual(len(json.load(fh)), 16)

    def test_the_memory_lives_OUTSIDE_the_repo(self):
        """The V-Pet already paid for this: a file inside the repo is a
        local change, and `~/YUZU/pull` stops on local changes rather
        than overwriting them. Her memory of a conversation would have
        blocked every update he ever ran."""
        here = os.path.dirname(os.path.abspath(self.face.__file__))
        import yuzu_face
        self.assertNotIn(here, yuzu_face.MEMORY_DIR.replace(self._home, ""),
                         "her memory would block every git pull")
        self.assertIn(".yuzu", self._memory)

    def test_forgetting_takes_a_NAME_and_nothing_else(self):
        """Same allowlist discipline as /launch/, /vpet/ and /say: a
        NAME crosses the wire, never a path, on a server bound to
        0.0.0.0."""
        self.post("/say", {"text": "hi", "who": "four"}).read()
        saved = os.path.join(self.face.MEMORY_DIR, "four.json")
        self.assertTrue(os.path.exists(saved))
        for junk in ("../../etc/passwd", "four/../../x", "", "nobody"):
            got = self.json.loads(self.post("/forget", {"who": junk}).read())
            self.assertFalse(got["ok"], "/forget accepted %r" % junk)
        self.assertTrue(os.path.exists(saved), "junk deleted a real memory")
        self.assertTrue(self.json.loads(
            self.post("/forget", {"who": "four"}).read())["ok"])
        self.assertFalse(os.path.exists(saved))


class TestSheRemembersWhatHeTellsHer(unittest.TestCase):
    """SHE KEEPS WHAT HE ASKS HER TO, AND IT IS NOT THE HISTORY.

    Ghost, Sept 22: *"14 sounds amazing as long as she never fills the
    memory."*

    `~/.yuzu/history/` is the last 8 turns and is bounded by
    CONSTRUCTION -- the brain trims eagerly. It is also gone the moment
    the conversation moves past it, so his cousin's name lasts nine
    turns and then is nowhere on the board.

    THE WORRY HE NAMED IS THE RIGHT ONE AND IT IS NOT DISK. Every fact
    rides on the system prompt on every single turn, inside the same
    `num_ctx` that `(history_turns + 1) x num_predict` already mostly
    fills -- and going over is SILENT: tokens are dropped and she comes
    back having forgotten the START of the conversation. So the cap is
    the feature, and `test_the_reply_ceiling_and_the_CONTEXT_agree`
    spends this budget as if full."""

    def store(self):
        """A temp facts directory. THE SUITE MUST NEVER WRITE TO HIS
        REAL ONE -- emptying `~/.yuzu/history/` and running the suite is
        exactly how the truncating-save bug was found, and the droppings
        were the symptom that led to it."""
        import yuzu_face
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        patch = mock.patch.object(yuzu_face, "FACTS_DIR", tmp)
        patch.start()
        self.addCleanup(patch.stop)
        return yuzu_face

    def test_the_store_can_NEVER_outgrow_its_budget(self):
        """HIS ACTUAL ASK, and the only one that matters.

        Driven rather than reasoned: a hundred facts go in, far past
        the cap, and the store is measured afterwards. Oldest out,
        newest in -- a FIFO rather than a refusal, because a store that
        stops accepting is a feature that quietly stopped working, and
        the count on her page is visible on every turn so he can see it
        coming."""
        face = self.store()
        for i in range(100):
            face.remember("four", "fact number %d about something" % i)
        facts = face.load_facts("four")
        used = sum(len(f) for f in facts)
        self.assertLessEqual(
            used, face.FACTS_BUDGET,
            "the store grew to %d characters against a budget of %d -- "
            "every one of them rides on her prompt every turn, and "
            "going over num_ctx is silent" % (used, face.FACTS_BUDGET))
        self.assertTrue(facts, "it evicted everything rather than the oldest")
        # NEWEST SURVIVES. A cap that drops what he just said would be
        # a button that reports success and does nothing.
        self.assertIn("fact number 99 about something", facts)

    def test_one_paste_can_never_BE_the_whole_store(self):
        """Without a per-fact cap a single paste IS the budget: he taps
        Remember on a wall of text and silently evicts everything she
        knew. It is trimmed, and the reply SAYS it trimmed."""
        face = self.store()
        face.remember("four", "his name is Ghost")
        facts, _dropped, note = face.remember("four", "x" * 5000)
        # NOT `max(len(f) for f in facts)`: the first version of this
        # line raised ValueError on an empty list when the cap was
        # broken, so it reported `errors=1` -- unittest saying the test
        # did not RUN -- where a skimmer reading for red would have
        # ticked it off as caught. Read the failure KIND, not the
        # colour. It says what went wrong now.
        self.assertTrue(facts, "one paste emptied the entire store")
        self.assertLessEqual(max(len(f) for f in facts), face.FACT_MAX,
                             "a single paste is bigger than the per-fact cap")
        self.assertIn("rimmed", note, "it trimmed his text and said nothing")
        self.assertIn("his name is Ghost", facts,
                      "one paste evicted everything she already knew")

    def test_one_fact_can_ALWAYS_fit_the_budget(self):
        """TWO CONSTANTS THAT HAVE TO AGREE, AND NOTHING CHECKED IT.

        Found by breaking the per-fact cap and watching the test ERROR
        rather than fail: with a fact larger than the whole budget,
        `_within_budget` pops until the list is EMPTY -- so the store is
        wiped, nothing is stored, and the page still says "Got it."
        Wiping months of facts and reporting success is the exact
        silent-failure shape this deck refuses everywhere else.

        It cannot happen at 200 against 1200. It happens the day
        somebody raises one number without looking at the other, which
        is the fault this repo keeps deleting."""
        import yuzu_face
        self.assertLess(
            yuzu_face.FACT_MAX, yuzu_face.FACTS_BUDGET,
            "one fact can be bigger than the whole store, so saving it "
            "empties the store and reports success")

    def test_being_told_the_same_thing_twice_costs_the_budget_once(self):
        """Tapping the button twice is the single most likely thing to
        happen to it on a touchscreen."""
        face = self.store()
        face.remember("four", "I work nights")
        facts, _d, note = face.remember("four", "i WORK nights")
        self.assertEqual(len(facts), 1, "a second tap spent the budget again")
        self.assertIn("already", note)

    def test_there_is_a_way_to_UNTELL_her(self):
        """A thing she can be told and never untold is a screen with no
        way off it, in data -- the one rule this deck will not trade."""
        face = self.store()
        face.remember("four", "one")
        face.remember("four", "two")
        self.assertEqual(face.unremember("four", 0), ["two"])
        # Out of range is SUCCESS. This exists so the store has an exit,
        # not so it can fail.
        self.assertEqual(face.unremember("four", 99), ["two"])
        self.assertEqual(face.unremember("four", "nonsense"), ["two"])

    def test_a_fact_reaches_a_brain_that_is_ALREADY_LOADED(self):
        """THE STALE-PROCESS FAULT, one layer in, and it would have
        looked exactly like the feature not working.

        `answer()` captures `_base_prompt` ONCE per brain so the board
        line cannot stack -- correct, and it also means a brain already
        in `_BRAINS` keeps answering from the prompt it was built with.
        Without dropping that cache the fact lands on disk and she does
        not know it until the next `~/YUZU/pull` restarts the server:
        he taps Remember, she says Got it, and then she has never heard
        of it. Same shape as the roster that rendered as though the
        work never landed."""
        face = self.store()

        class Loaded:
            system_prompt = "BASE"
        brain = Loaded()
        brain._base_prompt = "BASE"
        brain.system_prompt = "BASE and the old appendix"
        with mock.patch.dict(face._BRAINS, {"four": brain}, clear=False):
            face.remember("four", "his name is Ghost")
            self.assertFalse(
                hasattr(brain, "_base_prompt"),
                "the loaded brain kept its cached prompt, so she will "
                "not know this until the server restarts")
            self.assertEqual(brain.system_prompt, "BASE")

    def test_the_line_QUOTES_him_so_the_pronouns_still_point_at_him(self):
        """Stored verbatim, "my cousin's name is Dave" injected bare
        leaves `my` pointing at HER. Quoting them and naming the speaker
        costs four words and removes the ambiguity; rewriting them into
        the third person would need the model on every save."""
        face = self.store()
        face.remember("four", "my cousin's name is Dave")
        # TWO, NOT ONE. The first version stored a single fact and then
        # checked the joined text for list markup -- with one item
        # there IS no separator, so the check passed with the join
        # rewritten to "\n- " on purpose. A check that cannot observe
        # its own failure is not a check, and this one was written in
        # the round that quotes that rule.
        face.remember("four", "i work nights")
        line = face.facts_line("four")
        self.assertIn('"my cousin\'s name is Dave"', line,
                      "the fact is not quoted, so `my` is hers now")
        self.assertIn("his own words", line)
        # PROSE, NEVER A BULLETED LIST -- the same call board_now() and
        # board_specs() both made. A list in a system prompt is a
        # FORMAT, and markdown headings are this deck's one categorical
        # failure.
        for markup in ("\n-", "\n*", "\n1.", "##"):
            self.assertNotIn(markup, line.lstrip("\n"),
                             "her facts line teaches her to answer in lists")

    def test_an_empty_store_says_NOTHING_at_all(self):
        """Absent rather than wrong, and it is worth a test because the
        alternative is a sentence saying she knows nothing about him
        riding on every turn of a fresh board -- which is both a waste
        of context and a thing she would then volunteer."""
        face = self.store()
        self.assertEqual(face.facts_line("four"), "")

    def test_losing_the_facts_never_loses_the_REPLY(self):
        """The promise the face, the wiki, Piper and the memory all
        make. Driven with the file corrupt, not assumed."""
        face = self.store()
        os.makedirs(face.FACTS_DIR, exist_ok=True)
        with open(face._facts_file("four"), "w") as fh:
            fh.write("{ this is not json")
        self.assertEqual(face.load_facts("four"), [])
        self.assertEqual(face.facts_line("four"), "")

    def test_it_writes_BESIDE_the_file_and_renames(self):
        """`open(path, "w")` TRUNCATES the instant it is called, so a
        dump that raises part way leaves a fragment where months of
        facts used to be -- and the `except` that protects the reply is
        what makes that silent. Measured on the memory file when it had
        this bug: 58 bytes of memory became 29 bytes of nothing.

        Driven by making the dump fail and checking the old store is
        still whole."""
        face = self.store()
        face.remember("four", "his name is Ghost")
        with mock.patch.object(json, "dump", side_effect=OSError("disk full")):
            self.assertFalse(face.save_facts("four", ["something new"]))
        self.assertEqual(face.load_facts("four"), ["his name is Ghost"],
                         "a failed save ate the store it was rewriting")
        self.assertFalse(
            os.path.exists(face._facts_file("four") + ".part"),
            "it left a .part to be mistaken for a store later")

    def test_the_facts_are_NOT_gated_on_the_deck_body(self):
        """The board line IS gated: Cait has never heard of a computer
        and a test bans the words from her prompt, so handing her the
        watts at runtime would walk straight around it.

        What Ghost asked her to remember is about HIM, so it belongs to
        every character on every body. Read off the real source, with
        comments stripped -- the prose here explains the gate it is
        deliberately outside of."""
        import inspect, yuzu_face
        src = inspect.getsource(yuzu_face.answer)
        code = "\n".join(l.split("#")[0] for l in src.split("\n"))
        line = [l for l in code.split("\n") if "facts_line(" in l]
        self.assertTrue(line, "answer() never sends her the facts at all")
        self.assertNotIn("if has_wiki", line[0],
                         "the facts got gated on the deck body, so only "
                         "Four ever hears them")

    # ---- she offers, he picks --------------------------------------

    def test_her_PROMPT_teaches_the_marker_the_CODE_actually_catches(self):
        """THE TWO-COPIES GUARD, and the one that would break silently.

        Her prompt teaches `[remember: ...]` in a rule and shows it in
        an example; `_SUGGEST_RE` is what finds it again. Change either
        spelling and she goes on writing a marker nothing catches --
        which reads as her ignoring the feature, with the marker then
        appearing raw in her bubble.

        DRIVEN: her own example is pulled out of the composed prompt
        and run through the real extractor."""
        import yuzu_personas, yuzu_face
        prompt = yuzu_personas.load("four").prompt
        # THE MARKER, NOT THE WORD. This filtered on "remember" and
        # picked her CSS example, which says "only ever REMEMBERING
        # which one does which axis" -- grep-matches-prose, in the test
        # written to stop two spellings drifting apart.
        # HER WHOLE PROMPT THROUGH THE REAL EXTRACTOR. Anything else is
        # a second opinion about the spelling; this is the property.
        clean, offers = yuzu_face.suggestions(prompt)
        self.assertTrue(
            offers,
            "her prompt demonstrates a marker the code cannot find, so "
            "she will write it and nothing will catch it -- and it will "
            "then show up raw in her bubble")
        # and she is SHOWN it, not merely told: examples beat rules,
        # measured five times in this repo.
        self.assertIn(offers[0].lower(), prompt.lower())
        self.assertNotIn("\nremember:", clean.lower(),
                         "the marker survives into what she says out loud")

    def test_an_offer_costs_NOTHING_until_he_taps_it(self):
        """THE WHOLE REASON THIS DESIGN IS SAFE.

        Naming a token in her prompt is measured three times here as
        how she learns to spam it -- `[winks]` in 3 of 4 replies while
        named as forbidden, the asterisk ban that printed an asterisk,
        rule 5 recited back word for word. So assume she over-offers.

        An offer he ignores must cost nothing: not a byte of the
        budget, not a word on screen. That is what turns the pink
        elephant from a fault into noise."""
        face = self.store()
        before = face.load_facts("four")
        clean, offers = face.suggestions(
            "Sure.\nREMEMBER: he hates the cold\nREMEMBER: he has a truck",
            "four")
        self.assertEqual(len(offers), 2)
        self.assertEqual(face.load_facts("four"), before,
                         "merely offering spent the budget, so she can "
                         "fill her own memory by being chatty")

    def test_she_can_offer_at_most_TWO(self):
        """A wall of offers is its own kind of nagging, and the row
        under the ask bar has room for two."""
        face = self.store()
        _clean, offers = face.suggestions(
            "\n".join("REMEMBER: thing number %d" % i for i in range(9)))
        self.assertEqual(len(offers), face.SUGGEST_MAX)

    def test_she_never_offers_something_she_ALREADY_knows(self):
        """He would tap it and watch nothing happen, which reads as a
        button that stopped working."""
        face = self.store()
        face.remember("four", "he hates the cold")
        _clean, offers = face.suggestions(
            "Right.\nREMEMBER: HE HATES THE COLD\nREMEMBER: he has a truck",
            "four")
        self.assertEqual(offers, ["he has a truck"])

    def test_the_marker_never_lands_in_her_HISTORY(self):
        """Her own replies outweigh the system prompt within a few
        turns -- measured on a real 7-turn chat, and the entire reason
        `_canonicalise` exists. A marker left in the transcript is her
        teaching herself to emit more of them, every turn, for as long
        as the conversation lasts.

        Driven through the real `answer()` with a brain that emits
        one."""
        face = self.store()
        marked = "Noted.\nREMEMBER: he has a truck"

        class Emitting:
            system_prompt = "BASE"
            history_turns = 8

            def __init__(self, **kw):
                self.history = []

            def ask(self, text):
                self.history += [{"role": "user", "content": text},
                                 {"role": "assistant", "content": marked}]
                return marked

        import yuzu_brain
        with mock.patch.object(yuzu_brain, "YuzuBrain", Emitting), \
                mock.patch.dict(face._BRAINS, {}, clear=True):
            reply, error = face.answer("hi", "four")
            self.assertIsNone(error)
            self.assertNotIn("remember:", reply.lower(),
                             "the marker reaches the bubble and the speaker")
            # READ INSIDE THE PATCH. `patch.dict` restores the dict on
            # exit, so reading _BRAINS afterwards is reading the state
            # this test deliberately replaced -- a fixture asserting
            # about its own teardown.
            stored = face._BRAINS["four"].history[-1]["content"]
            self.assertNotIn("remember:", stored.lower(),
                             "the marker is in her transcript, so she is "
                             "teaching herself to write more of them")

    def test_BOTH_routes_ship_what_she_offered(self):
        """`/say` and `/stream` are one `answer()` with a callback, and
        that is exactly the shape that grew a second copy to forget
        last time. A third way in has to carry it too."""
        import inspect, yuzu_face
        src = inspect.getsource(yuzu_face._Handler.do_POST)
        code = "\n".join(l.split("#")[0] for l in src.split("\n"))
        self.assertEqual(
            code.count("on_suggest="), 2,
            "one of the two reply routes does not pass on_suggest, so "
            "she offers into the void on that one")
        self.assertEqual(code.count('"suggests"'), 2,
                         "one of the two reply routes drops the offers")

    def test_his_REAL_facts_directory_is_never_touched_by_the_suite(self):
        """The memory round found five zero-byte files in the REAL
        `~/.yuzu/history/` after a run, and the pollution was the
        symptom that led to the truncating-write bug. This store gets
        the guard from the start rather than after."""
        import yuzu_face
        self.assertIn(".yuzu", yuzu_face.FACTS_DIR)
        real = os.path.join(os.path.expanduser("~"), ".yuzu", "facts")
        self.assertEqual(yuzu_face.FACTS_DIR, real,
                         "the module's own default moved, so every test "
                         "here is patching the wrong name")


class TestSheSpeaksOutOfThePage(unittest.TestCase):
    """AUDIO HAS TO TRAVEL. `yuzu_voice.say()` plays on the machine
    running the module -- the ORIN -- and the Orin has no speaker on it
    (the USB sound card is in the parts list, not bought). Every device
    Ghost actually looks at has speakers already, so the server renders
    a wav and the BROWSER plays it.

    Ghost: "Finish the page audio so i can hear on steam deck."
    """

    def setUp(self):
        import json, struct, tempfile, threading, time
        from http.server import ThreadingHTTPServer
        import yuzu_face
        self.face, self.json = yuzu_face, json

        def a_real_wav(text, clean=True):
            handle, path = tempfile.mkstemp(suffix=".wav")
            os.close(handle)
            data = b"\x00\x00" * 400
            with open(path, "wb") as fh:
                fh.write(b"RIFF" + struct.pack("<I", 36 + len(data)) +
                         b"WAVEfmt " +
                         struct.pack("<IHHIIHH", 16, 1, 1, 16000, 32000, 2, 16) +
                         b"data" + struct.pack("<I", len(data)) + data)
            return path

        outer = self
        class Fake:
            ready, failures = True, []
            def render(self, text, clean=True):
                outer.rendered = text
                return a_real_wav(text)
            def why_not(self):
                return ""
        self.rendered = None
        self._saved = dict(yuzu_face._VOICES)
        yuzu_face._VOICES.clear()
        yuzu_face._VOICES["four"] = Fake()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), yuzu_face._Handler)
        self.port = self.server.server_address[1]
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    def tearDown(self):
        self.server.shutdown()
        self.face._VOICES.clear()
        self.face._VOICES.update(self._saved)

    def post(self, payload):
        import urllib.request
        req = urllib.request.Request(
            "http://127.0.0.1:%d/voice.wav" % self.port,
            data=self.json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"})
        return urllib.request.urlopen(req, timeout=20)

    def test_it_returns_REAL_WAV_BYTES_and_not_a_promise(self):
        got = self.post({"text": "hello there", "who": "four"})
        body = got.read()
        self.assertEqual(got.headers["Content-Type"], "audio/wav")
        self.assertEqual(body[:4], b"RIFF", "that is not a wav")
        self.assertEqual(int(got.headers["Content-Length"]), len(body),
                         "a short read would cut her off mid-word")

    def test_every_failure_is_a_SENTENCE_with_a_real_status(self):
        """A 200 carrying a sad sentence cannot be told apart from
        audio by an <audio> element -- it would just play nothing. The
        page has to know the difference between "no voice installed"
        and "the deck is not answering", so the code says so."""
        import urllib.error
        for payload in ({"text": "hi", "who": "nobody"},
                        {"text": "   ", "who": "four"},
                        {"text": "hi", "who": "cait"}):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                self.post(payload).read()
            self.assertEqual(caught.exception.code, 503)
            said = self.json.loads(caught.exception.read())["said"]
            self.assertTrue(said and said[0].isupper() or "'" in said,
                            "a failure with no sentence in it: %r" % said)

    def test_stage_directions_are_never_read_out_loud(self):
        """`*leans in*` spoken is the word "leans" in the middle of a
        sentence -- measured on the board, and the whole reason
        strip_stage_directions exists. The bubble, the terminal and now
        the page all make the same call."""
        self.post({"text": "Hey. [leans in close] All good.",
                   "who": "four"}).read()
        self.assertNotIn("leans", self.rendered)
        self.assertIn("All good", self.rendered)

    def test_the_voice_is_built_ONCE_per_character(self):
        """Kokoro loads a ~310MB model. Building one per request would
        make her slower than Piper rather than nicer than it, and on a
        board with ONE pool of 8GB it would thrash."""
        import inspect
        source = inspect.getsource(self.face.voice_for)
        self.assertIn("_VOICES", source, "nothing caches the voice")
        built = []
        real = self.face._VOICES["four"]
        self.face._VOICES.clear()
        import yuzu_voice
        original = yuzu_voice.pick_voice
        yuzu_voice.pick_voice = lambda **kw: (built.append(kw), real)[1]
        try:
            for _ in range(3):
                self.face.voice_for("four")
        finally:
            yuzu_voice.pick_voice = original
        self.assertEqual(len(built), 1, "a voice was built per call")

    def test_she_speaks_at_HER_OWN_speed(self):
        """`piper_length_scale` is in every persona file and is hers --
        Four runs 0.9. It has to reach the voice or every character
        speaks identically."""
        import yuzu_voice, yuzu_personas
        want = float(yuzu_personas.load("four").settings["piper_length_scale"])
        seen = {}
        self.face._VOICES.clear()
        original = yuzu_voice.pick_voice
        yuzu_voice.pick_voice = lambda **kw: (seen.update(kw), None)[1]
        try:
            self.face.voice_for("four")
        finally:
            yuzu_voice.pick_voice = original
        self.assertEqual(seen.get("length_scale"), want,
                         "her persona's speed never reached the voice")

    def test_a_missing_voice_costs_the_AUDIO_and_never_the_REPLY(self):
        """The oldest promise on this deck, and the one the face, the
        wiki and Piper all already make. Verified by driving the real
        function with the voice module absent."""
        import sys
        self.face._VOICES.clear()
        saved = sys.modules.pop("yuzu_voice", None)
        sys.modules["yuzu_voice"] = None      # an import that yields None
        try:
            wav, problem = self.face.voice_wav("hello", "four")
            self.assertIsNone(wav)
            self.assertTrue(problem, "it failed without saying why")
        finally:
            if saved is not None:
                sys.modules["yuzu_voice"] = saved
            else:
                sys.modules.pop("yuzu_voice", None)

    def test_the_page_plays_it_and_stays_silent_when_there_is_none(self):
        with open("ui/four.html", encoding="utf-8") as fh:
            page = fh.read()
        self.assertIn("voice.wav", page, "the page never asks for audio")
        self.assertIn("r.ok ? r.blob() : null", page,
                      "a 503 would be played as if it were audio")
        self.assertIn("revokeObjectURL", page,
                      "one object url leaks per reply, on a battery")


class TestKokoro(unittest.TestCase):
    """A SECOND ENGINE THAT CANNOT BREAK THE FIRST.

    CLAUDE.md held Kokoro back since Sept 9 because "installs nothing"
    is what lets the brain run in Pydroid on his phone. Ghost lifted
    the hold; the rule it protected is kept intact rather than traded,
    and that is what these pin.

    NOT VERIFIED: that Kokoro actually speaks. There is no model file
    and no audio device here, and onnxruntime's aarch64 build is the
    open question. Same standing limit as every "tested in a sim" claim
    in CLAUDE.md."""

    def setUp(self):
        import yuzu_voice
        self.voice = yuzu_voice

    def test_an_absent_kokoro_falls_back_to_piper_and_never_raises(self):
        made = self.voice.KokoroVoice()
        self.assertFalse(made.ready)
        self.assertIn("kokoro-onnx", made.why_not())
        self.assertIs(made.say("hello"), False, "it spoke without an engine")
        self.assertIsInstance(self.voice.pick_voice(), self.voice.Voice)

    def test_asking_for_kokoro_BY_NAME_returns_it_broken_rather_than_swapped(self):
        """Being told why is the point of asking for it by name. A
        silent swap is `face` reporting a live server as dead, pointing
        the other way."""
        self.assertIsInstance(self.voice.pick_voice(engine="kokoro"),
                              self.voice.KokoroVoice)
        self.assertIsInstance(self.voice.pick_voice(engine="piper"),
                              self.voice.Voice)

    def test_a_READY_kokoro_is_preferred_without_being_asked(self):
        """The auto-pick cannot be observed on a machine where Kokoro
        is genuinely absent -- which is every machine this suite runs
        on today -- so `ready` is faked rather than assumed. A guard
        that can only pass is not a guard, and this repo has shipped
        that mistake in both directions already."""
        real = self.voice.KokoroVoice.ready
        try:
            self.voice.KokoroVoice.ready = property(lambda self: True)
            self.assertIsInstance(self.voice.pick_voice(),
                                  self.voice.KokoroVoice,
                                  "a working Kokoro was ignored")
        finally:
            self.voice.KokoroVoice.ready = real
        # And restored, so the next test sees the real answer.
        self.assertIsInstance(self.voice.pick_voice(), self.voice.Voice)

    def test_length_scale_is_INVERTED_for_kokoro(self):
        """Piper's `piper_length_scale` is a DURATION multiplier --
        yuzu4 runs 0.88 to speak FASTER, Coco 1.08 to speak SLOWER.
        Kokoro's `speed` is a RATE. Passing it straight across would
        have made the gyaru the slow one and the kuudere the quick one:
        a character bug wearing an arithmetic costume, very easy to
        ship and impossible to notice without listening."""
        fast = self.voice.KokoroVoice(length_scale=0.88).speed
        slow = self.voice.KokoroVoice(length_scale=1.08).speed
        self.assertGreater(fast, 1.0, "the gyaru got slower")
        self.assertLess(slow, 1.0, "the kuudere got faster")
        self.assertGreater(fast, slow)
        self.assertEqual(self.voice.KokoroVoice().speed, 1.0)

    def test_the_import_stays_GUARDED_like_pipers(self):
        """One module, one try/except, prints if absent -- the exact
        guard CLAUDE.md specified for this dependency a week before it
        was written."""
        import inspect
        source = inspect.getsource(self.voice.KokoroVoice)
        self.assertIn("except Exception", source)
        top = inspect.getsource(self.voice).split("class KokoroVoice")[0]
        self.assertNotIn("\nimport kokoro_onnx", top,
                         "kokoro is imported at module level and would "
                         "take the whole voice down when it is absent")

    def test_the_phone_property_survives_a_second_engine(self):
        """`yuzu_all_in_one.py` has to run in Pydroid with nothing
        installed. It must not learn the word kokoro."""
        with open("yuzu_all_in_one.py", encoding="utf-8") as fh:
            text = fh.read()
        self.assertNotIn("kokoro", text.lower())

    def test_both_engines_share_ONE_speaking_path(self):
        """KokoroVoice was given Voice's shape rather than its own
        interface so the audition logic, the demo and every caller stay
        single-copy. A second copy is a second place for a spelling fix
        to be forgotten."""
        for name in ("ready", "why_not", "say", "failures"):
            self.assertTrue(hasattr(self.voice.KokoroVoice(), name),
                            "KokoroVoice is missing %s" % name)
        import inspect
        cli = inspect.getsource(self.voice._cli)
        self.assertEqual(cli.count("voice.say(candidate"), 1,
                         "the audition logic was duplicated per engine")

    def test_synthesis_is_SPLIT_from_playback_on_both_engines(self):
        """`say()` plays on the machine running this module -- the
        BOARD -- and the board has no speaker yet. What Ghost asked for
        is audio on the device he is LOOKING at: the Steam Deck, his
        phone, the laptop. Bytes have to travel, so something must hand
        back a FILE rather than a sound.

        `render()` is that, on both engines, with the same shape and
        the same promise as `say()`: it never raises, and it returns
        None rather than a path when it cannot work."""
        for made in (self.voice.Voice(model=None, piper=None),
                     self.voice.KokoroVoice()):
            name = type(made).__name__
            self.assertTrue(hasattr(made, "render"), "%s cannot render" % name)
            self.assertFalse(made.ready, "this test wants an ABSENT engine")
            self.assertIsNone(made.render("hello"),
                              "%s returned a path with no engine" % name)
            self.assertIs(made.say("hello"), False,
                          "%s claimed to speak with no engine" % name)

    def test_say_RENDERS_rather_than_carrying_a_second_copy(self):
        """Both `say()` methods used to hold their own synthesis --
        the invocation, the empty-wav check and the cleanup -- so
        `render()` landing beside them made two places for a spelling
        fix to be forgotten. Same fault as the two copies of the
        battery renderer and the four copies of the way out.

        Verified by breaking it: making render() return None must make
        say() return False, which it cannot do if say() synthesises on
        its own."""
        import inspect
        for cls in (self.voice.Voice, self.voice.KokoroVoice):
            body = inspect.getsource(cls.say)
            self.assertIn("self.render(", body,
                          "%s.say does not call render" % cls.__name__)
            self.assertNotIn("mkstemp", body,
                             "%s.say still synthesises its own wav"
                             % cls.__name__)

        # And drive it: a render that fails must not produce a claim.
        made = self.voice.KokoroVoice()
        made.render = lambda *a, **k: None
        self.assertIs(made.say("hello"), False)

    def test_bella_is_the_default_because_he_LISTENED_to_them(self):
        """Ghost: "i wana use the Bella voice from kokoro. (I dont
        really but its the best sounding one)". That is the only
        standard this project accepts for a voice -- somebody heard it.

        The first draft defaulted to af_heart on the reasoning that
        Kokoro's own samples lead with it, which is a guess about taste
        wearing a default's clothes."""
        self.assertEqual(self.voice.KokoroVoice().speaker, "af_bella")

    def test_the_only_pitch_control_is_WHICH_VOICE_and_it_says_so(self):
        """kokoro-onnx's create() takes a voice, a speed and a
        language. There is no pitch argument, so a note saying where to
        look saves the next person hunting for a knob that is not
        there."""
        import inspect
        source = inspect.getsource(self.voice)
        self.assertIn("NO PITCH KNOB", source)
        self.assertIn(self.voice.KOKORO_SPEAKER_ENV, source)


    def test_it_says_plainly_that_the_board_has_not_answered_yet(self):
        """Unverified specifics stated as steps already cost this
        project an hour on the 8BitDo."""
        self.assertIn("UNVERIFIED", self.voice.KOKORO_SOURCE)


class TestOneWordGetsHerTalking(unittest.TestCase):
    """Ghost: "Plz dont add new commands i cant actually remember any
    except /wiki. Just help me simply get this goin brobro."

    HE IS RIGHT AND THE FIRST DRAFT WAS WRONG. A `~/YUZU/voice` script
    was the tidy answer and it is a THIRD thing to remember on a board
    whose only shell is a serial cable -- this repo already records
    that a new command needs its own line in `pull` precisely BECAUSE a
    new command is a cost. The cheapest command is the one he already
    types.

    These drive the REAL script with stub binaries."""

    def setUp(self):
        import shutil, tempfile
        self.work = tempfile.mkdtemp()
        for name in ("pull",):
            shutil.copy(name, self.work)
        self.stub = os.path.join(self.work, "stub")
        os.makedirs(self.stub)
        self.log = os.path.join(self.work, "log")
        self.write("git", '#!/bin/sh\n'
                   'case "$1 $2" in\n'
                   '  "rev-parse HEAD") echo same ;;\n'
                   '  *) exit 0 ;;\n'
                   'esac\n')
        self.write("pip", '#!/bin/sh\necho "pip $*" >> "$LOG"\n')
        self.write("curl", '#!/bin/sh\necho "curl" >> "$LOG"\nexit 1\n')
        self.write("pgrep", '#!/bin/sh\nexit 1\n')

    def tearDown(self):
        import shutil
        shutil.rmtree(self.work, ignore_errors=True)

    def write(self, name, body):
        path = os.path.join(self.stub, name)
        with open(path, "w") as fh:
            fh.write(body)
        os.chmod(path, 0o755)

    def run_pull(self, ready):
        """Drive it with a yuzu_voice whose pick_voice reports `ready`."""
        import subprocess
        with open(os.path.join(self.work, "yuzu_voice.py"), "w") as fh:
            fh.write("class _V:\n    ready = %s\n"
                     "def pick_voice(**kw): return _V()\n" % bool(ready))
        open(self.log, "w").close()
        env = dict(os.environ, PATH=self.stub + os.pathsep + os.environ["PATH"],
                   LOG=self.log)
        got = subprocess.run(["./pull"], cwd=self.work, env=env,
                             capture_output=True, text=True, timeout=90)
        with open(self.log) as fh:
            called = fh.read()
        return got.stdout + got.stderr, called

    def test_a_voice_she_ALREADY_HAS_costs_nothing_and_says_nothing(self):
        """It runs on every pull, so the no-op case has to be silent
        and free -- otherwise the thing he runs most grows a paragraph
        he learns to scroll past."""
        out, called = self.run_pull(ready=True)
        self.assertNotIn("NO VOICE", out.upper())
        self.assertEqual(called.strip(), "", "it spent something for nothing")

    def test_it_sets_one_up_when_she_has_none(self):
        out, called = self.run_pull(ready=False)
        self.assertIn("SHE HAS NO VOICE YET", out)
        self.assertIn("pip", called, "it never tried to install anything")

    def test_it_says_the_SIZE_before_it_spends_it(self):
        """~340MB onto a board he pulls over WiFi is real. He asked for
        one word, so it is announced rather than withheld -- but a
        script that spends that silently is the surprise this project
        keeps refusing to ship."""
        out, _ = self.run_pull(ready=False)
        self.assertRegex(out, r"\d+\s*MB")

    def test_a_FAILED_setup_still_leaves_her_talking_and_the_pull_good(self):
        """curl fails in this fixture. Every failure path has to leave
        the pull successful and her voice exactly as it was -- the
        promise the face, the wiki and Piper all make."""
        out, _ = self.run_pull(ready=False)
        self.assertIn("Nothing is broken", out)
        self.assertNotIn("PULL FAILED", out)

    def test_it_runs_even_when_the_pull_brought_NOTHING_NEW(self):
        """The stub git reports the same commit before and after, so
        this is the up-to-date path. He asked to type pull and have her
        work; a pull with no changes must still fix a voice she does
        not have, or the one word does not do what he was told."""
        out, called = self.run_pull(ready=False)
        self.assertIn("ALREADY UP TO DATE", out)
        self.assertIn("SHE HAS NO VOICE YET", out)
        self.assertIn("pip", called)

    def welcome(self, hostname, routes=True):
        """Drive the real script with `hostname` stubbed. `routes=False`
        makes `ip route` fail, which is the no-address case."""
        import subprocess
        if hostname is None:
            self.write("hostname", "#!/bin/sh\nexit 1\n")
        else:
            self.write("hostname", "#!/bin/sh\necho %s\n" % hostname)
        self.write("ip", '#!/bin/sh\n'
                   'echo "1.1.1.1 via x dev wlan0 src 192.168.4.138"\n'
                   if routes else "#!/bin/sh\nexit 1\n")
        with open(os.path.join(self.work, "yuzu_voice.py"), "w") as fh:
            fh.write("class _V:\n    ready = True\n"
                     "def pick_voice(**kw): return _V()\n")
        env = dict(os.environ, PATH=self.stub + os.pathsep + os.environ["PATH"])
        got = subprocess.run(["./pull"], cwd=self.work, env=env,
                             capture_output=True, text=True, timeout=90)
        return got.stdout

    def test_it_ends_with_WELCOME_and_the_address(self):
        """Ghost: "Just Welcome Ghost, (url here)". Two lines, last, so
        the thing he opens is the thing still on screen when the pull
        stops scrolling."""
        out = self.welcome("ghostnano")
        self.assertIn("Welcome Ghost,", out)
        self.assertIn("http://ghostnano.local:8081/", out)
        tail = [line for line in out.strip().splitlines() if line.strip()][-2:]
        self.assertIn("Welcome Ghost,", tail[0])
        self.assertIn("8081", tail[1])

    def test_the_hostname_is_READ_never_hardcoded(self):
        """`ghostnano` is what his board is called TODAY -- he renamed
        it himself. A hardcoded name goes stale the next time, and the
        failure looks like the deck working. Same fault as the
        hardcoded cast in home.html."""
        with open("pull", encoding="utf-8") as fh:
            code = "\n".join(line for line in fh.read().splitlines()
                             if not line.lstrip().startswith("#"))
        self.assertNotIn("ghostnano", code, "pull hardcodes his board's name")
        self.assertIn("http://ghostnano.local:8081/",
                      self.welcome("ghostnano"))

    def test_localhost_falls_back_to_the_NUMBERS(self):
        """A name can be perfectly valid and still useless to him.
        `localhost` means THE MACHINE ASKING, so a board really named
        that told his phone to open ITSELF -- measured, on his screen,
        DNS_PROBE_FINISHED_NXDOMAIN. Absent rather than wrong."""
        for name in ("localhost", "localhost.local", "bad name!", None):
            out = self.welcome(name)
            self.assertNotIn(".local:8081", out,
                             "it offered %r as an address" % name)
            self.assertIn("http://192.168.4.138:8081/", out)

    def test_no_address_prints_NO_ADDRESS_rather_than_a_wrong_one(self):
        """The first version of this test claimed to check that the
        docker bridge and the USB-gadget link never appear -- and it
        PASSED VACUOUSLY, because with no `ip` there is no address line
        at all, so "no decoys" was trivially true. A check that cannot
        observe its own failure is not a check, which is the oldest
        line in CLAUDE.md.

        What is actually true, and worth pinning: the welcome survives
        having no address and prints no wrong one. The decoy filtering
        lives in `face`, where its own test drives it with the decoys
        ahead of the real address on purpose -- one copy, one guard."""
        out = self.welcome(None, routes=False)
        self.assertIn("Welcome Ghost,", out, "the welcome vanished too")
        self.assertNotIn("8081", out, "it printed an address it cannot know")
        self.assertNotIn("http://", out)

    def test_there_is_no_second_command_to_remember(self):
        """The `voice` script was removed rather than kept alongside.
        Two ways in is two things to remember, and he said plainly he
        remembers one."""
        self.assertFalse(os.path.exists("voice"),
                         "a second command came back")

    def test_it_asks_the_SAME_question_the_page_asks(self):
        """`pick_voice().ready` is the one source of truth for "can she
        speak right now". A second copy -- checking for a filename, or
        for an import -- is a thing that can drift from what actually
        decides it, which is the fault this repo records under every
        two-copies heading."""
        with open("pull", encoding="utf-8") as fh:
            text = fh.read()
        self.assertIn("pick_voice().ready", text)
        self.assertNotIn(".onnx\"", text.split("ASK")[0],
                         "pull hardcodes a model filename")



class TestFour(unittest.TestCase):
    """FOUR — the deck's own voice, and the character on the front door.

    Ghost, Sept 15, choosing her art out of three candidates:
    "Ascii/matrix face one. I uploaded it to the git for ya. Can u make
    it like.. animated somehow if possible?", then "Maybe a futureistic
    'Cortana' vibe while being casual still", then "Name her Four."

    SHE IS THE DEMO FACE, which is a character spec rather than a
    layout one. His reason for moving off Saya is in the same breath as
    the ask -- "sayas attitude and blushing stuff might be too extra
    for demos/showing to parents" -- so Four is the one a stranger
    meets with no context, and the failures that matter for her are the
    ones that show up cold."""

    PAGE = Path(__file__).parent / "ui" / "four.html"
    ART = Path(__file__).parent / "ui" / "four" / "four.jpg"

    def code(self):
        """The page with every comment stripped.

        NINTH INSTANCE OF THE GREP-MATCHES-PROSE TRAP, and this page is
        the most loaded one yet: its own comments contain `katakana`,
        `z-index: 1`, `cutout` and `PIL`, every one of them explaining
        why that thing is ABSENT. A test that reads the prose would
        report each of them as present."""
        text = self.PAGE.read_text()
        text = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
        text = re.sub(r"/\*.*?\*/", " ", text, flags=re.S)
        text = re.sub(r"^\s*//.*$", " ", text, flags=re.M)
        return text

    def persona(self):
        import yuzu_personas
        return yuzu_personas.load("four").prompt

    def turns(self):
        """Her example turns as (ask, answer), LABEL READ NOT ASSUMED.

        Two tests here matched the literal `User: ` to find his turns,
        which is a check about the file's spelling rather than about
        her examples -- so both went red on the one change they exist
        to allow, the day the label became his own name. Her name is
        the anchor instead: the line above every `Four:` line is his
        turn, whatever it calls him."""
        me = "Four:"
        lines = self.persona().splitlines()
        return [(ask.split(":", 1)[1].strip(), answer[len(me):].strip())
                for ask, answer in zip(lines, lines[1:])
                if answer.startswith(me) and ":" in ask
                and not ask.startswith(me)]

    def test_the_example_label_is_his_NAME_and_never_a_ROLE(self):
        """Ghost, Sept 22: *"Four keeps calling me 'User' can we get
        her to know of me and my name as Ghost?"*

        ELEVEN `User:` LABELS AND ZERO `Ghost`. The label in front of
        his turn was the ONLY word anywhere in her context naming the
        person she is talking to -- his real turns arrive as
        `role: user` with no label on them at all -- so it was the only
        thing she had to copy, and she copied it to his face.

        AND IT CONTRADICTS A RECORDED DECISION, which is why it is
        worth a test rather than a diff: *"SHE USES NO PET NAME AT ALL,
        and that is deliberate... the fix for a character who will be
        handed to other people is not to pick one, it is to demonstrate
        none."* Demonstrating none is exactly what those labels were
        doing, and it lost -- because THE EXAMPLE FORMAT'S LABEL IS
        ITSELF A DEMONSTRATION OF ADDRESS. The restraint was right
        about pet names and blind to the format carrying one.

        Pinned as a PROPERTY: one label across every example, and it is
        the name her own prompt tells her he has. Asserting the literal
        "Ghost" would be a test that has to be edited the day he
        changes it, which is the fault that put "User" there."""
        import yuzu_personas
        persona = yuzu_personas.load("four")
        name = persona.settings.get("USER_NAME", "")
        self.assertTrue(name, "she is given no name for him at all")

        lines = persona.prompt.splitlines()
        labels = {ask.split(":", 1)[0].strip()
                  for ask, answer in zip(lines, lines[1:])
                  if answer.startswith("Four:") and ":" in ask
                  and not ask.startswith("Four:")}
        self.assertEqual(
            labels, {name},
            "her examples label his turn %s. That label is the only "
            "word in her context that names him, so whatever it says "
            "is what she calls him out loud." % sorted(labels))

        # SHOWN *AND* TOLD. The labels alone leave her copying a
        # transcript; asked outright what his name is, she needs to
        # have been given it as a fact rather than as formatting.
        preamble = persona.prompt.split("EXAMPLES")[0]
        self.assertIn(name, preamble,
                      "she is shown his name eleven times and never "
                      "actually told it")

    # ---- her prompt --------------------------------------------------

    # ---- she knows she is offline ------------------------------------

    OFFLINE_CLAIM = "Nothing you do reaches the internet"

    def test_every_character_on_the_DECK_is_told_she_is_offline(self):
        """Ghost, Sept 22: *"I want her to know shes designed to be
        offline capable... And that shes offline entirely (if thats
        true im p sure it is and thats her whole point xD)"*

        HE ASKED BECAUSE SHE GOT IT BACKWARDS IN FRONT OF HIM. Running
        on his own board, on a hotspot with no service, she said *"As a
        cyberdeck, I'm always connected and ready to go."* Being
        offline is the single most defining thing about this machine
        and nothing had ever told her -- so the base model answered
        for her, and its prior for "AI assistant" is "on the internet".
        Same mechanism as the Windows CE palmtop, on a bigger fact.

        IT IS A BODY FACT, so it lives in the BODY FILE rather than in
        her persona: every character on this deck is offline, and a
        second one must not have to remember. That is what
        `_hardware_cyberdeck.txt` is for, and it is why editing it
        lands on all six at once.

        IT IS PHRASED POSITIVELY -- "everything you need is already on
        this board" rather than a list of things she cannot reach.
        The restraint clause on `board_specs()` was written the same
        way for the same reason, and the pink-elephant pattern is
        measured three times in CLAUDE.md."""
        on_deck = [k for k in yuzu_personas.available()
                   if yuzu_personas.load(k).hardware == "cyberdeck"]
        self.assertTrue(on_deck, "nobody is on the deck body any more")
        for key in on_deck:
            self.assertIn(self.OFFLINE_CLAIM, yuzu_personas.load(key).prompt,
                          f"{key} lives on this board and does not know "
                          f"she is offline")

    def test_the_CODE_still_makes_that_claim_TRUE(self):
        """A PROMPT RULE WRITING A CHEQUE THE CODE DOES NOT CASH is
        this repo's own phrase, from rule 8 telling her she notices the
        board while she had no data at all. This is the same fault
        pointing the other way: the moment anything in her turn reaches
        out, her prompt is lying to her -- confidently, about herself,
        which is the failure `board_specs()` exists to prevent.

        So it is DERIVED. Every URL her turn can reach must be
        loopback, and a real domain is one with a letter after a dot --
        a PROPERTY rather than an allowlist somebody has to extend.
        `127.0.0.1` has dots and no letters; the `http://...:11434`
        placeholder in the brain's own help text is not a host.

        COMMENTS ARE STRIPPED FIRST. The grep-matches-prose trap has
        fired twelve times in this suite, and the paragraph above is
        exactly the kind of note that would match itself.

        WHAT IT CANNOT SEE, said plainly: this reads source, not
        packets. `pull` genuinely does reach github and huggingface --
        that is maintenance he triggers, never something she does
        mid-reply, which is why it is not in this list."""
        import re as _re
        here = Path(__file__).parent
        for name in ("yuzu_brain.py", "yuzu_wiki.py",
                     "yuzu_voice.py", "yuzu_face.py"):
            src = (here / name).read_text(encoding="utf-8")
            code = "\n".join(l.split("#")[0] for l in src.split("\n"))
            for host in set(_re.findall(r'https?://([^/"\'\s:,)]+)', code)):
                self.assertIsNone(
                    _re.search(r"\.[a-zA-Z]", host),
                    "%s can reach %s during a reply -- she is told "
                    "nothing she does reaches the internet, and that "
                    "is now false" % (name, host))

    def test_she_carries_the_three_measured_example_SHAPES(self):
        """The bare command (yuzu4, 4/4), the warm statement with
        nothing to answer (Shiro round 2), and the technical question
        (round 3 -> round 4, a CATEGORICAL change from markdown
        headings and fenced code blocks to two plain sentences).

        THE TECHNICAL ONE IS NOT OPTIONAL ON HER. Assistant collapse is
        this deck's signature failure, the ONE EXAMPLE lever is the only
        categorical fix this repo has ever measured for it, and she is
        the character who gets handed to people who are not Ghost."""
        prompt = self.persona()
        asks = [ask for ask, _ in self.turns()]
        self.assertTrue(asks, "she has no examples at all")

        # A bare imperative: a flat command with no social content in
        # it, which is the exact shape that produced ZERO brackets in
        # both yuzu2 and yuzu3.
        self.assertTrue(
            any(a.endswith(".") and "?" not in a and len(a.split()) <= 3
                for a in asks),
            "no bare command -- the shape that produced yuzu4")
        # A warm statement with no question in it. Handed praise with
        # nothing to answer, a character with no example of it returns
        # a token acknowledgement.
        self.assertTrue(
            any("?" not in a and re.search(r"thank|helped|nice|cool|love", a, re.I)
                for a in asks),
            "no warm statement -- she will answer it with a noise")
        # And the technical question, by its answer rather than by its
        # question: the fix is that she has a demonstrated SHAPE for
        # one, not that the word CSS appears.
        tech = [line for line in prompt.splitlines()
                if line.startswith("Four:") and "flex" in line.lower()]
        self.assertTrue(tech, "no technical-question example")
        answer = tech[0]
        self.assertNotIn("```", answer, "her own example teaches a code fence")
        self.assertNotIn("**", answer, "her own example teaches markdown")
        self.assertLessEqual(len(re.findall(r"[.!?]", answer)), 3,
                             "her technical answer is already a lecture")

    def test_she_has_a_shape_for_answering_from_a_LOOKUP(self):
        """MEASURED, live, on `/wiki`: handed 700 characters of
        encyclopedia she came back with *"I'm not going to try to
        summarize this information again; I've already 'learned' it
        from you."*

        A lookup reaches her as a USER turn -- "I looked up X and it
        says: ... Tell me about X in your own words" -- which is a turn
        SHAPE she had never been shown. Sixth instance of this repo's
        most repeated finding, and the lever is the one that has now
        worked five times.

        PINNED BY THE ANSWER'S BEHAVIOUR, not the ask's spelling. The
        first version of the sibling test below counted keywords and
        passed with both examples deleted, which is grep-as-proxy in
        the test written about examples."""
        prompt = self.persona()
        lookups = [(q, a) for q, a in self.turns()
                   if "looked up" in q.lower() and "own words" in q.lower()]
        self.assertTrue(
            lookups,
            "she has no example of answering from a lookup, so she has "
            "no shape for one and invents a reaction to being handed facts")
        ask, answer = lookups[0]

        # SHORT. The measured fault beside the snark was length: handed
        # an encyclopedia she summarised at encyclopedia length, and a
        # reply that long does not fit a 1024x600 panel either.
        self.assertLessEqual(len(re.findall(r"[.!?]", answer)), 3,
                             "her own lookup example is already a lecture")
        for markup in ("```", "**", "#"):
            self.assertNotIn(markup, answer,
                             "her lookup answer teaches markdown")

        # AND SHE ANSWERS FROM THE MATERIAL. Derived rather than
        # hardcoded: the answer has to carry a real word out of the
        # article, or the example teaches her to be handed facts and
        # then talk about something else.
        stop = set("a an the and or of is are it its in on to from that "
                   "this with for no not so you your i me my what when "
                   "where up about words own sentence two tell looked "
                   "says like have has can".split())
        article = {w for w in re.findall(r"[a-z]{4,}", ask.lower())
                   if w not in stop}
        used = article & set(re.findall(r"[a-z]{4,}", answer.lower()))
        self.assertTrue(
            used,
            "her lookup answer shares nothing with the article she was "
            "handed, so the example teaches her to ignore it: %r" % answer)

        # AND SHE IS NOT SULKY ABOUT IT, which is the actual reported
        # fault rather than a proxy for it.
        for sulk in ("i'm not going to", "i am not going to", "again",
                     "already", "as i said"):
            self.assertNotIn(sulk, answer.lower(),
                             "her own example grumbles about being "
                             "handed facts, which is the fault")

    def test_she_has_a_shape_for_a_subject_that_is_not_HERSELF(self):
        """SAYA BLEED, reported live by Ghost on the board, Sept 15.

        Four came back sarcastic -- "Ah, great, another 'fix'... Just
        peachy", "don't expect me to hold your hand through this" --
        which is Saya's register on the character built to be her
        opposite. The plumbing was checked FIRST and is clean: her page
        posts `who: four`, `persona_for` returns `four`, her brain is
        her own, and her composed prompt contains no Saya text. So it
        is register drift, and the diagnosis is the one this repo has
        now made six times.

        NINE EXAMPLES AND EIGHT WERE ABOUT HER -- a greeting, her
        status, her name, her looks, her room, the deck. The only
        outward-facing one was CSS. The prompt taught her how to be
        when the subject is herself and taught her nothing about being
        handed an outside subject, so a 3B filled that gap from its own
        prior for "AI character with attitude", which is snark.

        TWO SHAPES, because one cannot cover both: a QUESTION about the
        world (which also came back as a multi-paragraph lecture, the
        length fault in the same screenshots) and a STATEMENT about
        something that went wrong, which is the exact slot "Just
        peachy" landed in.

        Pinned by the ANSWER's behaviour rather than by the ask's
        spelling. The first version of this test counted examples with
        no self-referential keyword in them and PASSED with both new
        examples deleted -- "Introduce yourself." and "What's it like
        in there?" scored as outward-facing -- which is a check that
        cannot observe its own failure, and grep-as-proxy again."""
        prompt = self.persona()
        turns = dict(self.turns())

        # A question about the WORLD, answered short. This is the turn
        # that came back as a lecture wearing a sneer.
        world = [a for q, a in turns.items()
                 if q.rstrip(".?").lower() in ("explain entropy",)
                 or re.match(r"explain \w+", q, re.I)]
        self.assertTrue(
            world,
            "nothing shows her explaining something that is not her, "
            "so a world question falls back on the base model's lecture")
        self.assertLessEqual(
            len(re.findall(r"[.!?]", world[0])), 3,
            "her own example of explaining the world is already a lecture")
        for markup in ("```", "**", "#"):
            self.assertNotIn(markup, world[0],
                             "her world answer teaches markdown")

        # AND A STATEMENT, not a question -- something he brings her
        # that has gone wrong. "Ah, great, another 'fix'. Just peachy."
        broken = [a for q, a in turns.items()
                  if "?" not in q
                  and re.search(r"broke|broken|crashed|died|not working",
                                q, re.I)]
        self.assertTrue(
            broken,
            "nothing shows her handed something that went wrong, which "
            "is the exact turn that came back as sarcasm")
        self.assertFalse(
            re.search(r"\bgreat\b|peachy|of course it|hold your hand|"
                      r"don't come crying|figures", broken[0], re.I),
            "her own example of a broken thing is sarcastic")

    def test_her_name_has_an_answer_so_she_does_not_invent_one(self):
        """A stranger at a demo WILL ask why she is called Four, and
        the Mimi finding is that a character with nothing demonstrated
        invents something every single time -- that is how "good girl"
        got into a prompt that says `him` thirteen times.

        The answer is deliberately lore-free. It is one line to change
        if Ghost ever decides what the other three were."""
        prompt = self.persona()
        self.assertIn("Why are you called Four?", prompt,
                      "nothing shows her answering for her own name")

    def test_she_is_on_the_deck_body_and_demonstrates_no_movement(self):
        """She IS the machine, so `_hardware_cyberdeck` fits her
        unchanged and {DECK_SELF} is a MEASURED win on this body rather
        than damage -- the one thing that made her the cheap candidate
        of the three. A bodiless persona is held to the stricter
        inverse of the movement rule: no brackets anywhere, because
        examples beat rules and one stray bracket teaches the habit."""
        import yuzu_personas
        four = yuzu_personas.load("four")
        self.assertEqual(four.hardware, "cyberdeck")
        self.assertFalse(four.moves)
        self.assertNotIn("[", self.persona())
        self.assertNotIn("*", self.persona())

    def test_her_sounds_are_her_own_and_every_one_carries_a_vowel(self):
        """`Hm` and `Mmh` are the obvious dry-AI noises and both are
        unsayable: no vowel means espeak spells them out letter by
        letter, which is the mechanism that made PFFT come out "Pee Eff
        Eff Tee". And they must not be Byte's -- a netrunner and a
        resident AI should not share a laugh."""
        import yuzu_personas, yuzu_voice
        four = yuzu_personas.load("four")
        sounds = [x.strip() for x in four.blocks["SOUND_EXAMPLES"].split(",")]
        self.assertTrue(sounds)
        for sound in sounds:
            self.assertTrue(re.search(r"[aeiouy]", sound, re.I),
                            f"{sound!r} has no vowel; espeak will spell it")
            self.assertEqual(yuzu_voice.for_speech(sound).strip(), sound,
                             f"{sound!r} does not survive for_speech")
        byte = yuzu_personas.load("byte_deck").blocks["SOUND_EXAMPLES"]
        self.assertNotEqual(set(sounds),
                            {x.strip() for x in byte.split(",")},
                            "she was handed the netrunner's laugh")

    def test_her_every_spoken_line_is_already_TTS_clean(self):
        """Teaching her a line the voice mangles is worse than teaching
        none -- the example is the stronger teacher, measured twice."""
        import yuzu_voice
        for line in self.persona().splitlines():
            if line.startswith("Four: "):
                said = line[6:]
                self.assertEqual(yuzu_voice.for_speech(said).strip(),
                                 said.strip(), f"Piper mangles: {said}")

    # ---- her art -----------------------------------------------------

    def test_her_art_is_BRIGHT_ON_BLACK_because_the_page_blends_it(self):
        """HER PICTURE IS NOT CUT OUT AND MUST NOT BE. Measured on the
        source: the border is pure black and 55.8% of the whole picture
        is near-black, because her shadow side IS the backdrop with no
        outline between them. A flood from the edge walks into her face
        at any tolerance that clears the backdrop at all -- the case
        ART.txt calls unfixable, with none of what saved `ghost_crowd`.

        It does not need one: `mix-blend-mode: screen` composites
        bright-on-black exactly, for free, with every soft edge intact.

        SO THIS IS THE GUARD THAT MATTERS. If somebody ever replaces
        her art with a picture on a WHITE or transparent ground, screen
        blending does not fail loudly -- it silently paints a pale
        rectangle across her whole page. The property the page depends
        on is the one worth pinning."""
        self.assertTrue(self.ART.exists(), "her picture is gone")
        try:
            from PIL import Image
        except Exception:
            self.skipTest("PIL is a workbench dependency, absent here")
        im = Image.open(self.ART).convert("RGB")
        wide, tall = im.size
        edge = []
        for x in range(0, wide, 9):
            edge.append(sum(im.getpixel((x, 1))) / 3)
            edge.append(sum(im.getpixel((x, tall - 2))) / 3)
        for y in range(0, tall, 9):
            edge.append(sum(im.getpixel((1, y))) / 3)
            edge.append(sum(im.getpixel((wide - 2, y))) / 3)
        edge.sort()
        self.assertLess(edge[len(edge) // 2], 24,
                        "her backdrop is no longer black -- `screen` will "
                        "paint it over the page instead of dropping it")
        # And she is actually THERE. A picture that is black all over
        # passes the line above and renders as nothing at all.
        bright = sum(1 for y in range(0, tall, 6) for x in range(0, wide, 6)
                     if sum(im.getpixel((x, y))) / 3 > 90)
        seen = len(range(0, tall, 6)) * len(range(0, wide, 6))
        self.assertGreater(bright / seen, 0.02, "there is nothing lit in her")

    def test_nobody_re_cut_her_art_into_the_pipeline(self):
        """The tool exists to remove a backdrop that CLASHES with the
        page. Hers matches it. Running it over her is the one way to
        turn a working picture into a broken one here, so her name must
        not appear in the cutter's recipes and her source must not be
        sitting in art_in/ waiting for a batch run."""
        import yuzu_cutout
        self.assertNotIn("four", yuzu_cutout.RECIPES,
                         "she has a cutout recipe; she must not be cut")
        art_in = Path(__file__).parent / "ui" / "art_in"
        self.assertFalse((art_in / "four.jpg").exists(),
                         "her source is in the batch folder and will be cut")

    # ---- her page ----------------------------------------------------

    def test_the_page_reaches_for_nothing_outside_itself(self):
        page = self.PAGE.read_text()
        for reach in ("http://", "https://", "//cdn", "@import",
                      "fonts.googleapis", "integrity="):
            for hit in [ln for ln in page.splitlines() if reach in ln]:
                self.assertIn("127.0.0.1", hit,
                              f"four.html reaches outside itself: {hit}")

    def skins(self):
        """The colours she cycles, read off the page's own SKINS.

        A LIST OF NAMES IN A TEST GOES STALE THE DAY A COLOUR LANDS
        CORRECTLY -- which is the fault this repo already recorded when
        the rail test pinned {saya, cait, yuzu} and a fourth character
        turned it red. Derive it, so a fifth colour has to answer for
        its palette rather than for this file."""
        found = re.search(r"const SKINS = \[([^\]]*)\]", self.PAGE.read_text())
        self.assertTrue(found, "nothing cycles her colour")
        return [x.strip().strip("'\"") for x in found.group(1).split(",")]

    def test_tapping_her_screen_cycles_green_red_purple_and_back(self):
        """Ghost, Sept 16: "Id like for Fours screen to be tappable on
        touch... neon red... Neon Purple. Tap again to go back to the
        green."

        GREEN IS FIRST AND IS THE EMPTY CLASS, which is what makes a
        reload land on the deck's own colour with nothing stored and
        nothing to explain -- and what anyone who is not Ghost meets,
        since she is the front door."""
        page = self.PAGE.read_text()
        names = self.skins()
        self.assertEqual(names[0], "",
                         "green is not first, so a reload lands elsewhere")
        self.assertEqual(len(set(names)), len(names), "a colour repeats")
        # Hot pink joined Sept 16, at his ask. Every colour after the
        # first must bring a palette; a name in SKINS with no block is a
        # tap that appears to do nothing.
        for skin in names[1:]:
            self.assertIn("body.%s {" % skin, page,
                          "%s has no palette to switch to" % skin)

    def rain_palette(self, *classes):
        """What --head and --tail resolve to for a given set of body
        classes, by CASCADING the page's own rules rather than by
        matching how any one of them is spelled.

        Specificity then source order, which is what the browser does
        and what the thinking blocks depend on -- they tie with the
        theme blocks and win on position alone."""
        want, found = set(classes), {}
        for sel, body in re.findall(r"(body[^{}\n]*)\{([^{}]*)\}", self.code()):
            sel = sel.strip()
            if not re.fullmatch(r"body(\.[\w-]+)*", sel):
                continue
            need = set(re.findall(r"\.([\w-]+)", sel))
            if not need <= want:
                continue
            for prop, value in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body):
                found[(len(need), prop)] = value.strip()
        out = {}
        for (rank, prop), value in sorted(found.items()):
            out[prop] = value
        return out

    def test_the_rain_changes_COLOUR_while_she_thinks(self):
        """Ghost, Sept 16: *"i dislike the words typing up as she says
        it thing as im a speed reader. Can we just give her a thinking
        pose somehow that only shows when shes thinking?"* -- then,
        settling it: *"Just turn the raining code neon purple when
        thinking. In general. (Except for purple main should have green
        code)"* and *"Only during thinking."*

        The word-by-word reveal answered "is it working or is it stuck"
        by making a fast reader wait for text he could already have
        read. This answers the same question at a glance.

        Verified by RENDERING every theme idle and thinking at
        1024x600, because no stdlib test can see a canvas."""
        for theme in self.skins():
            classes = [c for c in (theme,) if c]
            idle = self.rain_palette(*classes)
            busy = self.rain_palette(*classes, "thinking")
            self.assertNotEqual(
                idle.get("--head"), busy.get("--head"),
                "%s has no thinking signal in the rain" % (theme or "green"))
            self.assertNotEqual(idle.get("--tail"), busy.get("--tail"))

    # What each theme's rain turns while she thinks, in HIS words.
    # "Just turn the raining code neon purple when thinking. In general.
    # (Except for purple main should have green code)", and for the
    # fourth: "Hot glowy pink art and code rain", then "make the cyan
    # code on pink face a bright purple instead".
    #
    # A TABLE RATHER THAN A RULE, because there is no rule -- he picked
    # each one. Keyed by skin, so a fifth colour fails here until
    # somebody decides what it thinks in, which is the same job
    # `test_every_all_caps_word_she_has_ever_said_is_classified` does.
    #
    # ("theme", x)  borrows theme x's own rain, exactly
    # ("hex",   h)  a colour she never wears -- pink's purple is bluer
    #               and brighter than the deck's, because the deck's sits
    #               49 degrees of hue from her and vanished against her.
    THINKS_IN = {"":       ("theme", "purple"),
                 "red":    ("theme", "purple"),
                 "purple": ("theme", ""),
                 "pink":   ("hex",   "#e8dcff")}

    def test_each_theme_thinks_in_the_colour_he_chose(self):
        """Every colour gets used across the four, and the signal can
        never be the colour it is signalling against."""
        self.assertEqual(set(self.skins()), set(self.THINKS_IN),
                         "a colour cycles with no thinking colour decided")
        for skin, (kind, value) in self.THINKS_IN.items():
            classes = [c for c in (skin,) if c]
            busy = self.rain_palette(*classes, "thinking")
            if kind == "hex":
                self.assertEqual(busy["--head"].lower(), value,
                                 "%s does not think in %s" % (skin, value))
                continue
            want = self.rain_palette(*[c for c in (value,) if c])
            self.assertEqual(busy["--head"], want["--head"],
                             "%s thinks in something else" % (skin or "green"))

    def test_no_theme_thinks_in_its_OWN_colour(self):
        """The property under the table, and the one that actually
        matters: a signal you cannot tell from the thing it signals
        against is not a signal."""
        for skin in self.skins():
            classes = [c for c in (skin,) if c]
            idle = self.rain_palette(*classes)
            busy = self.rain_palette(*classes, "thinking")
            self.assertNotEqual(idle["--head"], busy["--head"],
                                "%s thinks in its own colour" % (skin or "green"))

    def test_thinking_leaves_HER_alone(self):
        """*"Leave her colors alone actually."* A first pass tinted
        patches of her own numbers and was wrong twice over: her art is
        a JPEG, so the accent had to be a second masked copy of her --
        and `screen` ADDS, so purple over her green came out CYAN.
        Rendering said so in one look.

        The rain is drawn by us, character by character, so its colour
        is ours to set. Nothing about her may move with it."""
        for theme in self.skins():
            classes = [c for c in (theme,) if c]
            idle = self.rain_palette(*classes)
            busy = self.rain_palette(*classes, "thinking")
            for prop in ("--ink", "--tint", "--dim", "--box", "--key"):
                self.assertEqual(idle.get(prop), busy.get(prop),
                                 "thinking moved %s on %s" % (prop, classes))

    def test_the_canvas_is_TOLD_when_the_thinking_colour_changes(self):
        """The rain keeps its own copy of the two colours -- read once
        per change, because getComputedStyle per frame is the opposite
        of why that loop throttles at all. So the toggle has to repaint
        it, and forgetting that is the same fault as the page turning
        red around rain that stayed green.

        Pinned as a PROPERTY: every place that toggles the thinking
        class goes through the one function that repaints."""
        code = self.code()
        body = re.search(r"function thinking\(on\)\s*\{(.*?)\n\}",
                         code, re.S)
        self.assertTrue(body, "the thinking toggle is not one function")
        self.assertIn("repaint()", body.group(1),
                      "the canvas is never told the colour changed")
        # add/remove/toggle only -- `contains` is the rain reading the
        # state to pick its speed, which is a READ and must not count.
        loose = [m for m in re.findall(
                     r"classList\.(?:add|remove|toggle)\([^)]*thinking[^)]*\)",
                     code)
                 if m not in body.group(1)]
        self.assertEqual(loose, [],
                         "something toggles thinking without repainting: %s"
                         % loose)

    def test_her_reply_arrives_WHOLE_and_not_a_word_at_a_time(self):
        """*"i dislike the words typing up as she says it thing as im a
        speed reader."* The page asks /say and paints once.

        /stream is NOT removed from the server -- Saya's face still
        uses it, and deleting a working route because one page stopped
        calling it is a change nobody asked for. This pins the PAGE."""
        code = self.code()
        self.assertNotIn("'stream'", code, "four.html still streams")
        self.assertNotIn("getReader", code, "the incremental reader is back")
        self.assertIn("'say'", code, "she has no way to answer at all")

    def test_the_cycle_COMES_BACK_and_leaves_no_colour_behind(self):
        """Ghost, one tap after pink shipped: *"Okay its amazing but
        doesnt loop back to the green etc"*.

        The handler read `classList.remove('red', 'purple')` -- a
        SECOND hardcoded list of the colours, one layer under the one
        this page already deletes. Green is the EMPTY class, so the
        fourth tap added nothing and pink stayed on the body forever:
        green -> red -> purple -> pink -> pink -> pink.

        The whole cycle is simulated here rather than the line being
        matched, because the bug is what the BODY ends up wearing, and
        the spelling of the remove call is exactly what looked fine."""
        code = self.code()
        names = self.skins()
        taken = re.search(r"classList\.remove\(([^)]*)\)", code)
        self.assertTrue(taken, "the tap takes no colour off")

        # Walk the cycle: whatever remove() names comes off, then the
        # next skin goes on. A colour left behind shows up as a body
        # wearing two.
        drops = set(re.findall(r"[\w-]+", taken.group(1)))
        universal = "SKINS" in drops
        worn, seen = set(), []
        for step in range(1, len(names) * 2 + 1):
            worn = set() if universal else worn - drops
            nxt = names[step % len(names)]
            if nxt:
                worn.add(nxt)
            seen.append(frozenset(worn))
            self.assertLessEqual(
                len(worn), 1,
                "tap %d leaves her wearing %s" % (step, sorted(worn)))
        self.assertEqual(seen[len(names) - 1], frozenset(),
                         "the cycle never comes back to green")

    def test_the_tap_is_on_the_STAGE_and_never_steals_the_way_out(self):
        """The top bar carries the rail and the ⌂, the ask bar carries
        the text box, and #says can scroll. A tap that lands on any of
        those must do what it says.

        The exit is the one rule this deck will not trade, and a
        recolour handler on `document` would have sat under it."""
        page = self.PAGE.read_text()
        self.assertIn("getElementById('stage').addEventListener('click'", page,
                      "the tap is not scoped to her stage")
        # WHICH SELECTORS IT LETS THROUGH, not how they are spelled.
        # This matched the literal `closest('#says')` and went red the
        # day a second control on the stage had to be excluded too --
        # a check about the file's spelling rather than about the page,
        # which is the grep-as-proxy fault this repo has now recorded
        # more than a dozen times.
        guards = set()
        for sel in re.findall(r"closest\(\s*'([^']*)'\s*\)", page):
            guards.update(part.strip() for part in sel.split(","))
        self.assertIn("#says", guards,
                      "scrolling her reply would also recolour the page")
        self.assertIn("#facts", guards,
                      "the x that drops a fact would recolour the page "
                      "instead of dropping it")

    def test_her_TINT_and_her_PALETTE_name_the_same_two_colours(self):
        """TWO COPIES THAT MUST AGREE. Her art is a JPEG, so it cannot
        take a CSS variable -- it is recoloured by an inline SVG colour
        matrix, which carries the target colour as numbers. So the hex
        lives in the stylesheet and the same colour lives, scaled by
        luminance, in the matrix.

        A page that turns red around a girl who turned some OTHER red
        is exactly the drift `test_both_pages_draw_the_SAME_battery`
        and the four copies of the way out already guard. Verified by
        changing one and watching this go red."""
        page = self.PAGE.read_text()
        lum = (0.2126, 0.7152, 0.0722)
        # Derived, so a new colour's matrix is checked the day it lands
        # rather than the day somebody remembers to add it here.
        pairs = [(s, "four-" + s) for s in self.skins() if s]
        self.assertTrue(pairs, "no tinted skins at all")
        for skin, fid in pairs:
            ink = re.search(r"body\.%s \{[^}]*?--ink:\s*(#[0-9a-fA-F]{6})"
                            % skin, page, re.S)
            self.assertTrue(ink, "body.%s declares no --ink" % skin)
            want = [int(ink.group(1)[i:i + 2], 16) / 255 for i in (1, 3, 5)]

            block = re.search(r'id="%s".*?values="([^"]+)"' % fid, page, re.S)
            self.assertTrue(block, "no SVG tint named %s" % fid)
            nums = [float(n) for n in block.group(1).split()]
            self.assertEqual(len(nums), 20, "%s is not a 4x5 matrix" % fid)
            # Each row is luminance scaled by one channel of the target.
            for row, channel in enumerate(want):
                got = nums[row * 5:row * 5 + 3]
                for weight, value in zip(lum, got):
                    self.assertAlmostEqual(
                        value, weight * channel, places=3,
                        msg="%s row %d does not match --ink %s"
                            % (fid, row, ink.group(1)))
            self.assertIn('id="%s" color-interpolation-filters="sRGB"' % fid,
                          page,
                          "%s would filter in linearRGB and wash out" % fid)

    def test_the_rain_takes_its_colour_from_the_palette_not_a_second_list(self):
        """The head and tail were hardcoded in the canvas loop, so a
        theme could turn every pixel of the page red and leave the
        falling code green. One palette, and the loop asks it.

        Cached rather than read per frame: this throttles to ~14fps on
        purpose because it is wallpaper on a battery."""
        page = self.PAGE.read_text()
        # THE ASSERTION IS ABOUT THE CODE, NOT THE FILE'S SPELLING. The
        # first version banned the literal '#c8ffd4' and went red on the
        # COMMENT explaining that it used to be hardcoded -- eleventh
        # instance of the grep-matches-prose trap this file records, in
        # the test written for the round that quotes it.
        paints = [ln.strip() for ln in page.splitlines()
                  if "ctx.fillStyle" in ln and not ln.strip().startswith("//")]
        glyphs = [ln for ln in paints if "rgba(0, 0, 0" not in ln]
        self.assertEqual(len(glyphs), 2, "the rain paints something new")
        for line in glyphs:
            self.assertFalse(re.search(r"#[0-9a-fA-F]{3,6}|rgba?\(", line),
                             "the rain still hardcodes a colour: %s" % line)
        self.assertIn("getPropertyValue('--head')", page)
        self.assertIn("getPropertyValue('--tail')", page)
        self.assertIn("repaint();", page,
                      "a theme change would leave the rain the old colour")

    def test_only_FOUR_changes_colour(self):
        """Ghost: "Only do this for Four." The other three have
        palettes sampled off their own art, and the deck's green on
        black is locked everywhere else -- the colour swap was REMOVED
        from Saya's face for being a settings panel parked on it."""
        for other in ("cait.html", "yuzu.html", "mimi.html", "face.html",
                      "home.html"):
            page = (self.PAGE.parent / other).read_text()
            self.assertNotIn("const SKINS", page,
                             "%s grew a colour cycle" % other)

    def test_the_blend_is_what_removes_her_backdrop(self):
        code = self.code()
        self.assertIn("mix-blend-mode: screen", code,
                      "her black backdrop is painted over the rain again")

    def test_the_stage_creates_no_stacking_context(self):
        """THE FAULT RENDERING FOUND. `#stage` had `z-index: 1`, and a
        positioned element with a z-index creates a STACKING CONTEXT --
        inside which `mix-blend-mode` has nothing behind it to blend
        with. So she composited against an empty context and her JPEG's
        black painted as an opaque rectangle: the right third of the
        panel went dead flat while every rain column on the left kept
        falling. Every assertion passed. Twenty-third time that looking
        is what found it."""
        code = self.code()
        stage = re.search(r"#stage\s*\{([^}]*)\}", code)
        self.assertTrue(stage, "the stage is gone")
        self.assertNotIn("z-index", stage.group(1),
                         "#stage creates a stacking context again, which "
                         "silently switches her blend off")

    def test_the_rain_is_ASCII_and_can_never_render_as_tofu(self):
        """Katakana is the obvious Matrix glyph set and it is a trap on
        this board: a machine with no CJK font draws every one of them
        as an empty box, and whether Ubuntu on his Orin has one is not
        something this project can check from here. Her own art is made
        of digits, so the safe set is also the faithful one.

        Same family as refusing to print unverified button combos."""
        code = self.code()
        glyphs = re.search(r"const GLYPHS = '([^']*)'", code)
        self.assertTrue(glyphs, "the rain has no glyph set")
        for ch in glyphs.group(1):
            self.assertLess(ord(ch), 128,
                            f"{ch!r} needs a font this deck may not have")

    def test_the_rain_throttles_itself(self):
        """A canvas loop at the panel's full refresh rate is heat and
        watts spent on wallpaper, on a handheld running off a battery
        bank with an LLM sharing its memory."""
        code = self.code()
        self.assertIn("requestAnimationFrame", code)
        self.assertIn("now - last <", code,
                      "the rain redraws as fast as the panel will let it")

    def test_a_missing_picture_costs_her_and_never_costs_the_page(self):
        """Cait hardcodes her PNG with no fallback and a rename leaves a
        permanently broken image -- recorded as a known weakness before
        Four existed, so it is applied here before it can bite. Hidden,
        the rain is still running and the page still reads as
        intentional."""
        self.assertIn("onerror", self.code(),
                      "a missing file draws a torn-page icon on her screen")

    def test_the_rail_is_the_roster_and_she_holds_no_list(self):
        import yuzu_face
        page = self.PAGE.read_text()
        self.assertIn("characters.json", page)
        for name in ("Saya", "Cait", "Yuzu", "Mimi"):
            self.assertNotIn(">%s<" % name, page,
                             f"{name} is hardcoded into her rail")
        self.assertIn("four", yuzu_face.CHARACTERS)

    def rail_builder(self):
        """The rail-building block, comments stripped.

        Its own comment names Mimi, Saya and the app icon while
        explaining why none of them is hardcoded -- the grep-matches-
        prose trap this page has already sprung once."""
        code = self.code()
        start = code.index("characters.json")
        return code[start:code.index(".catch(", start)]

    def test_the_front_door_shows_nobody_else_and_it_FOLLOWS_front(self):
        """Ghost, Sept 19: "when im on fours screen the other ones arent
        visible tabs on her interface."

        She is the character a stranger meets with no context, so four
        other AIs across the top of her screen is the demo answering a
        question nobody asked.

        THE GATE READS `front`, NEVER HER NAME. Testing `ME === 'four'`
        would be the hardcoded cast in its fourth costume -- after Mimi
        invisible from the front page, `#saya { border-color }` glowing
        on a tile that had moved into a drawer, and an app icon called
        "Saya's Face" pointing at a page Four had taken over. Every one
        of those looked exactly like the deck working.

        BOTH ENDS ARE PINNED, because the gate is only as alive as the
        key it reads: if `roster()` ever stops emitting `front`, the
        page silently starts showing the rail again and nothing says
        so."""
        self.assertIn("front", self.rail_builder(),
                      "her rail does not consult `front` -- so it is "
                      "either always on, or gated on a hardcoded name")
        import yuzu_face
        mine = [c for c in yuzu_face.roster() if c["who"] == "four"]
        self.assertEqual([c["front"] for c in mine], [True],
                         "the roster no longer tells her page she is "
                         "the front door")

    def test_an_empty_rail_can_never_cost_the_way_out(self):
        """EVERY SCREEN ON THIS DECK HAS A WAY OFF IT -- two power
        cycles paid for that sentence, and it is the one rule this
        project will not trade.

        Emptying the rail is only safe because the ⌂ is its SIBLING
        rather than something inside it. Nest the exit in the rail and
        hiding the cast takes the way out with it, chromeless and
        fullscreen on the panel where the ⌂ IS the exit."""
        bar = self.code()
        bar = bar[bar.index('id="top"'):bar.index('id="stage"')]
        rail, home = bar.index('id="rail"'), bar.index('id="home"')
        self.assertLess(rail, home, "the exit moved above the rail")
        # Between the rail's id and the home button there is exactly one
        # closing tag -- the rail's own. More than one, and the exit is
        # nested inside the thing that is now empty.
        self.assertEqual(bar[rail:home].count("</div>"), 1,
                         "the way out is nested inside the rail")

    def test_she_is_the_front_door_and_still_in_the_drawer(self):
        import yuzu_face
        self.assertEqual(yuzu_face.FRONT, "four")
        front = [c for c in yuzu_face.roster() if c["front"]]
        self.assertEqual([c["who"] for c in front], ["four"])
        # Being the front tile is a shortcut, not a filing cabinet.
        self.assertIn("four", {c["who"] for c in yuzu_face.roster()})

    def test_the_wiki_belongs_to_the_BODY_not_to_whoever_is_live(self):
        """Both `/wiki` and "does this character drive Saya's face
        sprites" used to hang off ONE flag, and the two agreed only by
        accident while the live arm was the only character on the deck
        body at all. Four is on the deck and is not live, which is what
        pulled them apart.

        The encyclopedia belongs to the body -- a deck has a ZIM on its
        disk and a cat of the Otherworld does not, and a 700-char
        extract is the shortest path to assistant collapse on a
        character who has never heard of one."""
        import yuzu_face, yuzu_personas
        source = inspect.getsource(yuzu_face.answer)
        self.assertIn('hardware == "cyberdeck"', source,
                      "the wiki gate is not asking about the body")
        deck = {"four", "saya"}
        for who in yuzu_face.CHARACTERS:
            key = yuzu_face.persona_for(who)
            on_deck = yuzu_personas.load(key).hardware == "cyberdeck"
            self.assertEqual(on_deck, who in deck,
                             f"{who} moved bodies; the wiki gate follows")


class TestNamingTheBoard(unittest.TestCase):
    """`name` -- give the board a name so the phone stops needing an IP.

    MEASURED, on his phone, in one screenshot:

        DNS_PROBE_FINISHED_NXDOMAIN
        Check if there is a typo in localhost.local.

    HIS BOARD IS CALLED `localhost`, which means THE DEVICE ASKING --
    so the address pointed his phone at itself. The only way in was a
    number he has to re-read off a serial terminal whenever the DHCP
    lease moves, which is a cable, for an address."""

    SCRIPT = Path(__file__).parent / "name"

    def _run(self, *args, current="localhost", hosts="127.0.1.1\toldname\n"):
        """Drive the REAL script against stub sudo/hostnamectl/systemctl
        and a scratch hosts file."""
        import subprocess
        tmp = tempfile.mkdtemp()
        try:
            binv = Path(tmp) / "bin"
            binv.mkdir()
            state = Path(tmp) / "current"
            state.write_text(current)
            hostsfile = Path(tmp) / "hosts"
            hostsfile.write_text(hosts)
            # `sudo` just runs the thing, so the stubs below are what
            # actually answer.
            (binv / "sudo").write_text('#!/bin/bash\nexec "$@"\n')
            (binv / "hostname").write_text(
                '#!/bin/bash\ncat %s\n' % state)
            (binv / "hostnamectl").write_text(
                '#!/bin/bash\n[ "${1:-}" = set-hostname ] && '
                'printf "%%s" "$2" > %s\nexit 0\n' % state)
            (binv / "systemctl").write_text("#!/bin/bash\nexit 0\n")
            (binv / "apt-get").write_text("#!/bin/bash\nexit 0\n")
            for f in binv.iterdir():
                f.chmod(0o755)
            done = subprocess.run(
                ["bash", str(self.SCRIPT), *args], capture_output=True,
                text=True, timeout=60,
                env=dict(os.environ, YUZU_HOSTS=str(hostsfile),
                         PATH=f"{binv}:{os.environ['PATH']}"))
            return done, hostsfile.read_text(), state.read_text()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_it_fixes_etc_hosts_which_is_the_whole_point(self):
        """`hostnamectl` is one line and this script is not one line
        because of THIS. Renaming without updating 127.0.1.1 leaves sudo
        unable to resolve the new host, so every sudo from then on stalls
        ten seconds printing "unable to resolve host" -- a slow,
        confusing, unrelated-looking fault landing on a board whose only
        shell is a serial cable."""
        done, hosts, now = self._run("ghostnano")
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        self.assertEqual(now, "ghostnano")
        self.assertIn("127.0.1.1", hosts)
        self.assertIn("ghostnano", hosts,
                      "sudo will now stall on every command he runs")
        self.assertNotIn("oldname", hosts, "the old name is still mapped")

    def test_a_hosts_file_with_no_127_0_1_1_line_gains_one(self):
        """Not every image ships that entry, and a `sed` that matches
        nothing succeeds silently -- which would leave exactly the
        ten-second sudo this script exists to prevent, while reporting
        DONE."""
        done, hosts, _ = self._run("ghostnano", hosts="127.0.0.1\tlocalhost\n")
        self.assertEqual(done.returncode, 0, done.stdout)
        self.assertIn("127.0.1.1\tghostnano", hosts)

    def test_it_refuses_a_name_that_means_THIS_DEVICE(self):
        """The bug that caused all of this, refused at the door -- and
        refused BEFORE anything is touched, because a board that argues
        with sudo is not a typo you fix casually over a serial cable."""
        done, hosts, now = self._run("localhost")
        self.assertNotEqual(done.returncode, 0)
        self.assertEqual(now, "localhost", "it renamed anyway")
        self.assertIn("oldname", hosts, "it edited hosts before checking")

    def test_it_refuses_a_name_that_would_break_the_box(self):
        for bad in ("-lead", "gh ost", "under_score", "a" * 64, ""):
            done, hosts, now = self._run(bad)
            if bad == "":
                # No argument at all is the REPORT, not a rename.
                self.assertEqual(done.returncode, 0)
                self.assertIn("called", done.stdout)
                continue
            self.assertNotEqual(done.returncode, 0, "accepted %r" % bad)
            self.assertIn("oldname", hosts, "it edited hosts for %r" % bad)

    def test_the_report_tells_him_localhost_is_the_problem(self):
        """He had no reason to suspect the board's own name -- the page
        worked perfectly on the numbers. Running this with no argument
        has to name the fault, not just print a string."""
        done, _, _ = self._run(current="localhost")
        self.assertEqual(done.returncode, 0)
        self.assertIn("CANNOT REACH", done.stdout)
        self.assertIn("~/YUZU/name", done.stdout, "it names no way forward")

    def test_mDNS_is_offered_and_never_promised(self):
        """Whether a given phone resolves .local is a property of the
        PHONE, not of this board, and is not checkable from here.
        Unverified specifics stated as steps already cost an hour on the
        8BitDo -- so the fallback goes in the same breath."""
        done, _, _ = self._run("ghostnano")
        self.assertIn("http://ghostnano.local:8081/", done.stdout)
        self.assertIn("If it does not load", done.stdout)
        self.assertIn("~/YUZU/face", done.stdout,
                      "the fallback does not say how to get the numbers")

    def test_a_failed_rename_stops_instead_of_half_doing_it(self):
        """A box renamed in one place and not the other is worse than one
        not renamed at all."""
        import subprocess
        tmp = tempfile.mkdtemp()
        try:
            binv = Path(tmp) / "bin"; binv.mkdir()
            hostsfile = Path(tmp) / "hosts"
            hostsfile.write_text("127.0.1.1\toldname\n")
            (binv / "sudo").write_text('#!/bin/bash\nexec "$@"\n')
            (binv / "hostname").write_text("#!/bin/bash\necho localhost\n")
            (binv / "hostnamectl").write_text("#!/bin/bash\nexit 1\n")
            for f in binv.iterdir():
                f.chmod(0o755)
            done = subprocess.run(
                ["bash", str(self.SCRIPT), "ghostnano"], capture_output=True,
                text=True, timeout=60,
                env=dict(os.environ, YUZU_HOSTS=str(hostsfile),
                         PATH=f"{binv}:{os.environ['PATH']}"))
            self.assertNotEqual(done.returncode, 0)
            self.assertIn("oldname", hostsfile.read_text(),
                          "it edited hosts after the rename failed")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


class TestUpdatingWithoutTheCable(unittest.TestCase):
    """`POST /pull`, and the Update button in the home screen's bar.

    Ghost, Sept 15, having walked away from the cable: "And can i make
    her pull the current that way? Idk how to use my phone wirelessly
    with it."

    EVERYTHING ELSE ON THIS DECK ALREADY REACHES HIM OVER WIFI -- her
    face, the chat, the wiki, the pet, the launcher. `git pull` needed
    the one shell he can only get by plugging his phone into the board,
    and it is the thing he runs most, so the update loop was the single
    part that kept the deck tethered."""

    import yuzu_face as face

    def _stub(self, body):
        """A `pull` that records how it was called instead of pulling."""
        tmp = tempfile.mkdtemp()
        script = Path(tmp) / "pull"
        script.write_text(body)
        script.chmod(0o755)
        return tmp, script

    def test_it_never_lets_pull_bounce_the_server_mid_REQUEST(self):
        """`pull` restarts a running face server -- which HERE is the
        process holding the open request. He would tap Update and get a
        network error over a pull that worked perfectly.

        Same ordering drop.py had to learn: the reply goes out first,
        and the restart is a detached child afterwards."""
        tmp, script = self._stub(
            '#!/bin/bash\necho "NO_RESTART=[${YUZU_PULL_NO_RESTART:-unset}]"\n')
        try:
            with unittest.mock.patch.object(self.face, "PULL_SCRIPT",
                                            str(script)):
                said, restart = self.face.run_pull()
            self.assertIn("NO_RESTART=[1]", said,
                          "pull was allowed to kill the server it is "
                          "answering through")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_pull_itself_obeys_that_and_still_restarts_normally(self):
        """The suppression must be the CALLER's choice, not a new default
        -- a pull from his terminal still has to bounce a stale server,
        which is the fault the flag sits next to."""
        body = self.face and None       # (keep the import used above)
        text = (Path(__file__).parent / "pull").read_text()
        self.assertIn("YUZU_PULL_NO_RESTART", text)
        # And driven, both ways, through TestPull's own harness.
        run = TestPull("test_it_is_valid_shell_and_executable")
        done, calls = run._restart_run(["yuzu_face.py"], server_up=True)
        self.assertIn("face --off", calls,
                      "a terminal pull stopped restarting a stale server")

    def test_a_restart_is_only_promised_when_something_actually_landed(self):
        """ALREADY UP TO DATE must not bounce her. Restarting costs the
        page's chat history, and spending it on a pull that changed
        nothing is a cost with no purchase."""
        tmp, script = self._stub('#!/bin/bash\necho "  ALREADY UP TO DATE."\n')
        try:
            with unittest.mock.patch.object(self.face, "PULL_SCRIPT",
                                            str(script)):
                said, restart = self.face.run_pull()
            self.assertFalse(restart, "a no-op pull restarted the server")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        tmp, script = self._stub('#!/bin/bash\necho "  UPDATED."\n')
        try:
            with unittest.mock.patch.object(self.face, "PULL_SCRIPT",
                                            str(script)):
                said, restart = self.face.run_pull()
            self.assertTrue(restart, "a real update left stale code serving")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_route_takes_NOTHING_from_the_request(self):
        """The whole reason this is safe on a server bound to 0.0.0.0.

        Same discipline as /launch/ and /vpet/: one fixed script that
        lives in this repo, no branch, no remote, no path, no shell
        string. A route that could be told WHAT to pull would be a box
        on his WiFi that runs what it is told."""
        source = inspect.getsource(self.face.run_pull)
        # Nothing about the request is in scope at all -- it takes no
        # arguments, which is the strongest form of the guarantee.
        sig = inspect.signature(self.face.run_pull)
        self.assertEqual(list(sig.parameters), [],
                         "run_pull grew a parameter; the request can reach it")
        self.assertNotIn("shell=True", source)
        handler = inspect.getsource(self.face._Handler.do_POST)
        self.assertIn('path == "/pull"', handler,
                      "the route matches by prefix; a subpath would differ")

    def test_the_button_lives_in_the_BAR_and_not_in_the_drawer(self):
        """A tile would spend an app slot forever in the drawer he means
        to "pile up our fancy future apps" in -- and seven tiles across
        three columns orphans one onto a row of its own, which is the
        layout bug this page has already had twice. In the bar it is in
        the same place whatever is on screen, which is what maintenance
        wants."""
        page = (Path(__file__).parent / "ui" / "home.html").read_text()
        self.assertIn('id="update"', page, "there is no way to update")
        bar = page[page.index('<div id="bar">'):page.index("</div>",
                   page.index('<div id="bar">') + 400)]
        self.assertIn('id="update"', bar, "Update left the bottom bar")
        tiles = re.findall(r'<div class="tile[ "][^>]*>', page)
        for tile in tiles:
            self.assertNotIn("update", tile, "Update became a tile")

    def test_she_can_serve_with_NOBODY_LOGGED_IN(self):
        """THE OTHER HALF, and it is the one that made "use just my
        phone" impossible rather than awkward.

        `deckapps --autostart` does start this server -- from a .desktop
        file in ~/.config/autostart, which runs when a DESKTOP SESSION
        LOGS IN. The Nano has no screen on it, so nothing logs in, so
        nothing serves, so the phone has nothing to reach. The thing
        standing between him and a cable-free deck was a login that
        never happens.

        A systemd unit does not care whether anyone is looking."""
        text = (Path(__file__).parent / "face").read_text()
        self.assertIn("--boot", text, "there is no way to serve at boot")
        self.assertIn("WantedBy=multi-user.target", text,
                      "the unit waits for a graphical login, which is the "
                      "bug it exists to fix")
        self.assertIn("Restart=always", text)

    def test_the_cheap_STOP_is_not_the_word_that_uninstalls(self):
        """`tile` already paid for this: on a board whose only shell is a
        serial cable, the quick "turn it off" must never be the same word
        that tears the install out. `--off` stops the process; `--boot
        --off` is what removes the service."""
        text = (Path(__file__).parent / "face").read_text()
        off = text[text.index('case "${1:-}" in'):]
        off = off[:off.index("esac")]
        self.assertNotIn("systemctl", off,
                         "plain --off now disables the boot service too")
        boot = text[text.index('if [ "${1:-}" = "--boot" ]'):]
        boot = boot[:boot.index("\ncase ")]
        self.assertIn('"${2:-}" = "--off"', boot,
                      "there is no way to undo --boot")

    def test_the_page_waits_for_her_server_instead_of_reloading_blind(self):
        """The server restarts itself behind the reply, so a reload fired
        immediately lands on a dead port -- and "unable to connect" reads
        as an update that broke the deck rather than one that worked."""
        page = (Path(__file__).parent / "ui" / "home.html").read_text()
        block = page[page.index("update.onclick"):]
        block = block[:block.index("// ---- getting out")]
        self.assertIn("location.reload", block)
        reload_at = block.index("location.reload")
        self.assertLess(block.index("setInterval"), reload_at,
                        "it reloads without waiting for her to come back")


class TestTheDeckPutsItselfOnTheDesktop(unittest.TestCase):
    """`POST /icons`, and the ⊞ Desktop button beside Update.

    Ghost, Sept 17, told that plugging a monitor into the board gives
    him an ordinary Ubuntu desktop with the deck sitting on top of it:
    "i want a button on that gnome desktop that opens a window with
    this part in it if possible? I just dislike using terminals
    honestly", and then "Like fully a window not a browser tab."

    THE WINDOW ALREADY EXISTED. `deckapps` has always written .desktop
    files that open these pages with `--app= --start-fullscreen` -- no
    tab strip, no url bar, no window edge -- and
    test_her_pages_open_FULLSCREEN_but_never_as_a_kiosk pins that. What
    needed a keyboard was INSTALLING them, and his one shell is a
    serial cable. So the last setup step that needed typing became a
    button he can tap from the phone."""

    import yuzu_face as face

    def _stub(self, body):
        """A `deckapps` that records how it was called, or fails."""
        tmp = tempfile.mkdtemp()
        script = Path(tmp) / "deckapps"
        script.write_text(body)
        script.chmod(0o755)
        return tmp, script

    def _run(self, body):
        tmp, script = self._stub(body)
        try:
            with unittest.mock.patch.object(self.face, "DECKAPPS_SCRIPT",
                                            str(script)):
                return self.face.run_deckapps()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_last_setup_step_that_needed_a_TERMINAL_is_a_button(self):
        """It is in the BAR, for the reason Update and Back are: a tile
        spends an app slot forever in the drawer he means to "pile up
        our fancy future apps" in, and MOVES every time that drawer
        grows -- and seven tiles across three columns orphans one onto
        a row of its own, which is the layout bug this page has had
        twice. Maintenance is not an app."""
        page = (Path(__file__).parent / "ui" / "home.html").read_text()
        self.assertIn('id="desktop"', page,
                      "the icons still need a terminal to install")
        start = page.index('<div id="bar">')
        bar = page[start:page.index("</div>", start + 400)]
        self.assertIn('id="desktop"', bar, "⊞ Desktop left the bottom bar")
        for tile in re.findall(r'<div class="tile[ "][^>]*>', page):
            self.assertNotIn("desktop", tile, "⊞ Desktop became a tile")
        block = page[page.index("desktop.onclick"):]
        block = block[:block.index("// ---- getting out")]
        self.assertIn("fetch('icons'", block, "the button asks for nothing")
        self.assertIn("method: 'POST'", block)

    def test_the_route_takes_NOTHING_from_the_request(self):
        """The whole reason this is safe on a server bound to 0.0.0.0,
        and here it matters more than it does for /pull: `deckapps`
        takes `--remove`, which is the destructive word. A route that
        could be told WHICH word to pass would be a box on his WiFi
        that can strip his desktop.

        It takes no arguments at all, which is the strongest form of
        the guarantee."""
        sig = inspect.signature(self.face.run_deckapps)
        self.assertEqual(list(sig.parameters), [],
                         "run_deckapps grew a parameter; the request "
                         "can reach it")
        source = inspect.getsource(self.face.run_deckapps)
        self.assertNotIn("shell=True", source)
        handler = inspect.getsource(self.face._Handler.do_POST)
        self.assertIn('path == "/icons"', handler,
                      "the route matches by prefix; a subpath would differ")
        # DRIVEN, NOT GREPPED, and the first version of this test was
        # the twelfth instance of the trap: it banned the string
        # "--remove" from the source and went red on the DOCSTRING
        # saying --remove is unreachable. A comment explaining an
        # absence must never read as that thing being present.
        #
        # A failing stub is what makes the argv observable -- its own
        # output IS the message on a non-zero exit.
        said, ok = self._run('#!/bin/bash\necho "ARGS=[$*]"\nexit 1\n')
        self.assertFalse(ok)
        self.assertIn("ARGS=[]", said,
                      "deckapps was handed an argument, and one of the "
                      "words it takes is --remove")

    def test_a_FAILED_install_is_never_reported_as_DONE(self):
        """`deckapps` refuses to leave a dead icon and exits non-zero
        when it removes one -- an icon that looks installed and does
        nothing when tapped reads as a broken deck. Throwing that away
        for a cheerful sentence is the silent failure this project
        refuses everywhere else.

        Its own words are the message: they name which icon failed and
        what to install."""
        said, ok = self._run('#!/bin/bash\n'
                             'echo "  BROKEN: Game Boy points at /nope"\n'
                             'exit 1\n')
        self.assertFalse(ok, "a failed install reported success")
        self.assertIn("BROKEN", said,
                      "deckapps said which icon failed and it was dropped")
        said, ok = self._run('#!/bin/bash\necho "  installed: Deck"\n'
                             'echo "Done."\n')
        self.assertTrue(ok)
        self.assertTrue(said.startswith("DONE."),
                        "the verdict goes first: %r" % said[:40])
        self.assertIn("Deck", said, "it never says what it put out")

    def test_a_MISSING_script_says_so_rather_than_claiming_the_icons(self):
        """Absent rather than wrong, same as every other route here."""
        tmp = tempfile.mkdtemp()
        try:
            with unittest.mock.patch.object(
                    self.face, "DECKAPPS_SCRIPT",
                    str(Path(tmp) / "not-there")):
                said, ok = self.face.run_deckapps()
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        self.assertFalse(ok)
        self.assertIn("deckapps", said)

    def test_the_bar_can_GROW_without_shoving_a_button_off_the_screen(self):
        """MEASURED by rendering, which is the only thing that can see
        this: at 412px with a long verdict in it, the second button's
        right edge landed at 414 -- two pixels past the viewport, with
        the message column squeezed to one word wide and half the
        screen tall.

        `min-width: 0` is the load-bearing half. A flex item will not
        shrink below its own longest word without it, so the message
        pushed the row wider than the screen and the LAST thing in the
        row paid for it. Exactly the fault that put the ⌂ 169px past
        the viewport on four character pages, one bar down.

        What a stdlib test can see is that the message is still the
        item that yields and the buttons are still the ones that do
        not."""
        page = (Path(__file__).parent / "ui" / "home.html").read_text()
        style = page[page.index("#note {"):]
        style = style[:style.index("}")]
        self.assertIn("min-width: 0", style,
                      "the message cannot shrink, so a button leaves "
                      "the screen")
        self.assertIn("flex: 1", style)
        buttons = page[page.index("#update, #desktop {"):]
        buttons = buttons[:buttons.index("}")]
        self.assertIn("flex: none", buttons,
                      "the buttons shrink instead of the message")


class TestTheAppIconFollowsTheFrontDoor(unittest.TestCase):
    """Ghost, Sept 17: "Change it to say Four instead of sayas face."

    HE IS FIXING A HARDCODED CAST, one layer out from the page. The
    icon `deckapps` installed said "Saya's Face" and opened
    `face.html` -- true when it was written and stale from the moment
    `FRONT` moved to Four, with the failure looking exactly like the
    deck working. Third costume of the same fault, after Mimi being
    invisible from the front page and `#saya { border-color }` glowing
    on a tile that had moved into a drawer.

    So it is not renamed to "Four". It is built from the ROSTER, which
    is the only place this deck keeps its cast, and moving `FRONT` one
    word renames the icon on the next install."""

    import yuzu_face as face

    def _install(self, front_line=None, front_fails=False):
        """Run the REAL `deckapps` into a throwaway HOME, with a stub
        browser so the icons are actually written, and return what
        landed in the front character's .desktop file."""
        home = tempfile.mkdtemp()
        binder = Path(home) / "bin"
        binder.mkdir()
        for fake in ("chromium",):
            (binder / fake).write_text("#!/bin/sh\nexit 0\n")
            (binder / fake).chmod(0o755)
        if front_line is not None or front_fails:
            # Stand in for `python3 yuzu_face.py --front`, which is the
            # ONE thing deckapps asks about the cast.
            body = ("#!/bin/sh\nexit 1\n" if front_fails
                    else "#!/bin/sh\nprintf '%s\\n'\n" % front_line)
            (binder / "python3").write_text(body)
            (binder / "python3").chmod(0o755)
        import subprocess
        env = dict(os.environ, HOME=home,
                   PATH="%s:%s" % (binder, os.environ.get("PATH", "")))
        done = subprocess.run(
            ["bash", str(Path(__file__).parent / "deckapps")],
            capture_output=True, text=True, env=env, timeout=120)
        icon = Path(home) / ".local/share/applications/yuzu-face.desktop"
        text = icon.read_text() if icon.exists() else None
        shutil.rmtree(home, ignore_errors=True)
        # `deckapps` writes its launcher wrappers BESIDE ITSELF, which
        # is the repo when the suite drives it. Leaving them behind is
        # test pollution, and it made TestDeckApps go red on this
        # test's droppings -- the failure looked like a missing-browser
        # bug in a script nobody had touched.
        for junk in (".wiki-app", ".face-app"):
            (Path(__file__).parent / junk).unlink(missing_ok=True)
        return done.stdout + done.stderr, text

    def _field(self, desktop, key):
        for line in (desktop or "").splitlines():
            if line.startswith(key + "="):
                return line.split("=", 1)[1]
        return None

    def test_the_character_icon_IS_whoever_the_roster_puts_out_front(self):
        """Driven, not read: the same script, two different front
        characters, and the icon has to follow. A test that asserted
        the literal "Four" would have to be edited the next time he
        changes his main -- which is the thing that went wrong here in
        the first place."""
        for name, page, blurb in (("Mimi", "mimi.html", "a wisp"),
                                  ("Cait", "cait.html", "king of cats")):
            said, desktop = self._install("%s\t%s\t%s" % (name, page, blurb))
            self.assertIsNotNone(desktop,
                                 "no front icon was installed: %s" % said)
            self.assertEqual(self._field(desktop, "Name"), name,
                             "the icon is not named after the front door")
            self.assertIn(page, self._field(desktop, "Exec"),
                          "the icon opens somebody else's page")
            self.assertEqual(self._field(desktop, "Comment"), blurb)
            self.assertIn("installed: %s" % name, said)

    def test_the_two_layers_AGREE_about_who_is_out_front(self):
        """`--front` is what the installer asks; `roster()` is what the
        home screen reads. A deck whose desktop icon and whose front
        tile disagree is the same bug wearing two faces."""
        line = self.face.front_app()
        self.assertTrue(line, "nothing answers --front")
        name, page, blurb = line.split("\t")
        out = [c for c in self.face.roster() if c["front"]]
        self.assertEqual(len(out), 1, "the roster has no single front door")
        self.assertEqual((name, page, blurb),
                         (out[0]["name"], out[0]["page"], out[0]["blurb"]))
        # And the flag really is what a shell gets, not just a function.
        import subprocess
        done = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "yuzu_face.py"),
             "--front"], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.stdout.strip(), line)
        self.assertEqual(done.returncode, 0)

    def test_a_roster_that_does_not_answer_installs_NO_front_icon(self):
        """Absent rather than wrong, same as every other route here. An
        icon guessing at a character is worse than no icon: Deck is
        built from the same roster and is the way in to everybody."""
        said, desktop = self._install(front_fails=True)
        self.assertIsNone(desktop, "it installed a guess")
        self.assertIn("SKIPPED the front character", said)
        self.assertIn("Deck opens the home screen", said,
                      "it never says what to tap instead")
        self.assertIn("installed: Deck", said,
                      "one missing shortcut took the whole install down")

    def test_the_chat_icon_is_READ_from_the_LIVE_arm_and_not_typed_in(self):
        """THIS TEST USED TO PIN THE LITERAL "Saya" IN THE INSTALLER,
        and the reasoning was that the chat icon is genuinely hers: it
        runs `yuzu_brain --chat`, which boots LIVE_PERSONA, and that
        was `saya_deck`. True, and it was still a hardcoded cast --
        correct for exactly as long as nobody moved the pointer, which
        is the same sentence that was written about "Saya's Face" one
        icon over, three days before it went stale. The page icon and
        the chat icon were the same bug at two different ages.

        So it is `--live` now, beside `--front`, and what is pinned is
        that BOTH are read and that they are read SEPARATELY. The two
        flags answer different questions -- who greets you, versus
        which prompt boots -- and they happen to name the same
        character today, which is precisely when a collapse into one
        would go unnoticed."""
        text = (Path(__file__).parent / "deckapps").read_text()
        for name in ("Saya", "Cait", "Mimi", "Four", "Yuzu"):
            self.assertNotIn('write_app "%s"' % name, text,
                             f"{name} is typed into the installer")
        self.assertIn("--live", text, "the chat icon names nobody at all")
        self.assertIn("--front", text)
        self.assertIn('write_app "$LIVE"', text)
        self.assertIn('write_app "$FRONT_NAME"', text)
        # and the flag really answers, through a shell
        import subprocess
        done = subprocess.run(
            [sys.executable, str(Path(__file__).parent / "yuzu_face.py"),
             "--live"], capture_output=True, text=True, timeout=60)
        self.assertEqual(done.returncode, 0)
        self.assertEqual(done.stdout.strip(),
                         yuzu_personas.load(yuzu_personas.LIVE_PERSONA).name)


class TestTheWayOutSurvivesANarrowScreen(unittest.TestCase):
    """EVERY SCREEN ON THIS DECK HAS A WAY OFF IT. Two power cycles paid
    for that rule and it is the one thing this project will not trade.

    MEASURED at 412px, the width of the phone that is his only screen
    until the panel arrives: the home button sat 15 to 169px PAST the
    right edge on all four character pages -- Four, Cait, Yuzu and Mimi
    -- because the rail is content-width and grows with the cast, and
    it pushes the exit out of the viewport ahead of it. Worse every time
    a character shipped, and invisible the whole time, because 1024x600
    is the only view that gets designed and there it is fine.

    The fix is that the rail takes the leftover space and scrolls while
    the exit keeps its corner.

    WHAT IS PINNED HERE IS AGREEMENT, NOT SPELLING. No stdlib test can
    measure a layout -- that was done by rendering at 412, 360 and 1024
    and reading the button's own bounding box on every page. What a test
    CAN see is that the four pages still say the same thing, which is
    the failure that actually threatens this: a fifth character page
    copied from one of them before the fix, or three updated and one
    missed. Same guard, same reason, as the two copies of the battery
    renderer and the two copies of the Jetson check."""

    PAGES = ("four", "cait", "yuzu", "mimi")

    def block(self, name):
        text = (Path(__file__).parent / "ui" / ("%s.html" % name)).read_text()
        start = text.index("@media (max-width: 760px)")
        end = text.index("}" + chr(10) + "</style>", start)
        chunk = text[start:end]
        keep = [ln.strip() for ln in chunk.splitlines()
                if ("#rail" in ln or "#home" in ln or "#who" in ln)
                and not ln.strip().startswith(("*", "/*"))]
        return keep

    def test_every_character_page_keeps_the_exit_on_a_narrow_screen(self):
        first = self.block(self.PAGES[0])
        self.assertTrue(first, "the narrow-screen exit rules are gone")
        # The rail must be allowed to SHRINK. `min-width: 0` is the
        # load-bearing half -- a flex item will not go below its content
        # width without it, which is exactly how it shoved the button off.
        joined = " ".join(first)
        self.assertIn("min-width: 0", joined)
        self.assertIn("overflow-x: auto", joined)
        for other in self.PAGES[1:]:
            self.assertEqual(self.block(other), first,
                             "%s disagrees with %s about keeping the way "
                             "out on screen" % (other, self.PAGES[0]))

    def test_every_character_page_has_a_way_out_at_all(self):
        """One level up from the CSS: a page with no home button cannot
        be fixed by any amount of layout."""
        for name in self.PAGES:
            text = (Path(__file__).parent / "ui" / ("%s.html" % name)).read_text()
            self.assertIn('id="home"', text, "%s has no way out" % name)
            self.assertIn("home.html", text,
                          "%s has a home button that goes nowhere" % name)


class TestEveryCharacterCanActuallyBeAsked(unittest.TestCase):
    """The bug Ghost hit the first time he tapped Speak on Mimi:

        No persona '<Persona mimi (Imouto wisp)>'. Available: byte,
        byte_deck, cait, coco, ... mimi, saya, ...

    It names `mimi` as available two words after failing to find it,
    because `answer()` handed YuzuBrain the LOADED PERSONA where its
    `persona` argument wants a KEY -- and the brain calls load() on it
    itself, so it looked for a file named after the object's repr.

    EVERY CHARACTER ON A PAGE WAS BROKEN BY THIS, not just the new one.
    The suite was green throughout because its fake brain is
    `def __init__(self, **kw): pass` -- more permissive than the real
    constructor, so it could not observe the failure. That is this
    file's oldest lesson wearing a mock's clothes: a check that cannot
    see the real failure mode is not a check.

    So this fake validates its argument the way YuzuBrain does, and it
    runs over the WHOLE roster rather than one name, which is what
    makes it a guard for character #5 as well.
    """

    def test_the_brain_is_handed_a_key_it_can_actually_load(self):
        import yuzu_face
        import yuzu_personas

        seen = []

        class Strict:
            def __init__(self, persona=None, **kw):
                # Exactly what YuzuBrain does with this argument.
                if not isinstance(persona, str):
                    raise AssertionError(
                        "persona= got %r, which is not a key" % (persona,))
                yuzu_personas.load(persona)      # raises if it is wrong
                seen.append(persona)

            def ask(self, text):
                return "..."

        was = dict(yuzu_face._BRAINS)
        try:
            for who in sorted(yuzu_face.CHARACTERS):
                with mock.patch.object(yuzu_face, "_BRAINS", {}):
                    with mock.patch("yuzu_brain.YuzuBrain", Strict):
                        reply, error = yuzu_face.answer("hello", who)
                self.assertIsNone(error,
                                  "asking %s failed: %s" % (who, error))
        finally:
            yuzu_face._BRAINS.clear()
            yuzu_face._BRAINS.update(was)
            yuzu_face.set_state("idle")
        self.assertEqual(len(seen), len(yuzu_face.CHARACTERS))

    def test_an_unknown_name_is_refused_rather_than_answered(self):
        """Putting the wrong character on screen is the confusing kind
        of wrong, so a name that is not in the roster gets a sentence
        and never somebody else's brain."""
        import yuzu_face
        for hostile in ("nobody", "../saya", "", "MIMI; rm -rf /"):
            reply, error = yuzu_face.answer("hello", hostile)
            if hostile == "":
                continue        # empty falls back to the live character
            self.assertIsNone(reply, "%r got an answer" % hostile)
            self.assertIn("no character", (error or "").lower())


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

    def _run(self, *args, have=(), plant=()):
        """Install into a fake HOME with only `have` on PATH, so both
        'everything present' and 'nothing installed' are driven from
        fixtures rather than from whatever this machine has. `plant`
        puts old icons in place first, the way his board has them."""
        import subprocess
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            home, binv = tmp / "home", tmp / "bin"
            (home / "YUZU").mkdir(parents=True)
            binv.mkdir()
            for icon in plant:
                for where in (home / ".local/share/applications",
                              home / "Desktop"):
                    where.mkdir(parents=True, exist_ok=True)
                    (where / icon).write_text("[Desktop Entry]\n")
            # `python3` is here because `deckapps` now ASKS who the
            # front character is rather than naming one. That is a new
            # dependency at install time for a script that used to need
            # only coreutils -- trivially satisfied on a board whose
            # whole deck is python, and worth having the fixture say so
            # out loud rather than discovering it on the hardware.
            for tool in ("bash", "mkdir", "cat", "chmod", "cp", "rm",
                         "ls", "grep", "sleep", "cut", "printf",
                         "python3"):
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
        """Six now. Her FACE and the HOME screen joined the original
        three when Ghost asked for "a desktop with my apps and a saya
        button visible", BROWSER joined when the home screen started
        opening fullscreen -- see the test below -- and PET left with
        the V-Pet on Sept 23."""
        done, names, on_desktop, _ = self._run(have=("chromium", "xterm"))
        self.assertEqual(names, ["yuzu-browser.desktop", "yuzu-chat.desktop",
                                 "yuzu-face.desktop", "yuzu-gba.desktop",
                                 "yuzu-home.desktop",
                                 "yuzu-wiki.desktop"], done.stdout)
        # and on the Desktop too, which is where a touchscreen user taps
        self.assertIn("yuzu-wiki.desktop", on_desktop)
        self.assertIn("yuzu-home.desktop", on_desktop)

    def test_an_icon_for_an_app_that_LEFT_is_taken_off_his_desktop(self):
        """Not writing the Pet icon any more does not remove the one
        already on his board. It would sit there pointing at a page
        that is gone -- the dead icon write_app exists to never leave --
        so a retired app is removed by name, on every run, and it says
        so."""
        done, names, on_desktop, _ = self._run(
            have=("chromium", "xterm"), plant=("yuzu-pet.desktop",))
        self.assertNotIn("yuzu-pet.desktop", names, done.stdout)
        self.assertNotIn("yuzu-pet.desktop", on_desktop, done.stdout)
        self.assertIn("removed: yuzu-pet", done.stdout)
        # and a board that never had it is not told about it
        done, _, _, _ = self._run(have=("chromium", "xterm"))
        self.assertNotIn("yuzu-pet", done.stdout)

    def test_her_pages_open_FULLSCREEN_but_never_as_a_kiosk(self):
        """Ghost, Sept 11: "I do not want it using a browser tab on the
        real hardware. I want that to be its actual UI."

        --app= already removed the url bar and the tabs; fullscreen is
        the rest of it, and on the panel there is then no window edge
        and nothing that says "web page".

        --kiosk WOULD LOOK IDENTICAL and take away F11 and Alt+F4. That
        is the one thing this project will not build on a screen with no
        keyboard: "a UI that can trap him is strictly worse than a
        terminal", and two power cycles paid for that sentence.
        Fullscreen gives the look and keeps the way out, so there is
        nothing to trade -- which is why this asserts BOTH halves."""
        body = self.SCRIPT.read_text()
        chrome = body.split("browser_cmd()")[1].split("}")[0]
        self.assertIn("--app=URL --start-fullscreen", chrome)
        self.assertNotIn("chromium --kiosk", body,
                         "her page can now trap him with no way out")

    def test_there_is_a_PLAIN_browser_and_it_is_not_chromeless(self):
        """The door back to the web. Ghost: "can i set it up to have
        youtube,browsing, etc on the same screen?" -- yes, and once her
        page fills the panel this is the only way to reach it. A deck
        that locks out the browser it is built on is a worse computer
        than the bare board.

        Deliberately NOT --app=: this one wants the url bar."""
        done, names, _, _ = self._run(have=("chromium", "xterm"))
        self.assertIn("yuzu-browser.desktop", names, done.stdout)
        body = self.SCRIPT.read_text()
        plain = body.split("plain_browser()")[1].split("\n}")[0]
        self.assertNotIn("--app=", plain, "the browser lost its url bar")
        self.assertNotIn("--kiosk", plain)

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
        # THE PATH IS DERIVED, NOT SPELLED. This asserted the wrapper
        # contained the literal "YUZU/wiki" -- which `deckapps` only
        # ever produces because it finds ITSELF with `dirname "$0"`, so
        # the string is really the CHECKOUT'S FOLDER NAME. It passed
        # here for one reason: this clone happens to be called YUZU.
        # Cloned to ~/deck, or to any temp directory, the suite went
        # red on a script that was working perfectly.
        #
        # Found under --shuffle, and the banner said "a test is leaving
        # something behind" -- which it was not. That message prints on
        # ANY shuffle failure, and it is a hint rather than a diagnosis.
        # Same rule as the Jetson round: a test that can only pass on
        # the machine you wrote it on is not passing, it is untested.
        wiki = str(Path(__file__).parent / "wiki")
        self.assertIn(wiki, wrapper,
                      "the wrapper does not start this repo's own wiki")
        self.assertLess(wrapper.index(wiki), wrapper.index("exec "),
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
        was = dict(yuzu_face._BRAINS)
        yuzu_face._BRAINS[yuzu_face.persona_for("four")] = FakeBrain()
        try:
            with mock.patch.object(
                    yuzu_brain.yuzu_wiki, "as_context",
                    lambda t: ("I looked up %s and it says: FACTS." % t, None)):
                yuzu_face.answer("/wiki cats", "four")
        finally:
            yuzu_face._BRAINS.clear()
            yuzu_face._BRAINS.update(was)
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


class TestNextSession(unittest.TestCase):
    """NEXT_SESSION.md is a SNAPSHOT for a fresh CODE session, and a snapshot is a
    thing that goes stale on purpose.

    So this class deliberately pins almost nothing about it. Asserting
    that it still says `four`, or still says 201 tokens, would be a test
    that has to be edited every single time it works -- which is the
    fault this repo keeps deleting, most recently on the icon that had
    to be renamed whenever the front door moved.

    What it pins is the two properties that CANNOT go stale by being
    right, and whose loss is exactly how a snapshot becomes a lie: it
    must keep saying it expires and name CLAUDE.md as the real record,
    and it must never teach a command that hardcodes a pointer's VALUE.
    `--show shiro_deck` sat wrong in CLAUDE.md for eleven days, and a
    stale cast in a DOC is worse than one in a page, because a page has
    a test."""

    def setUp(self):
        self.doc = (Path(__file__).parent / "NEXT_SESSION.md").read_text()

    def test_it_says_it_expires_and_names_the_real_record(self):
        """A snapshot that does not announce itself as one gets read as
        current, which is the only way this file can hurt anybody."""
        self.assertIn("expires", self.doc.lower(),
                      "NEXT_SESSION.md must say out loud that it expires -- "
                      "otherwise a two-month-old pointer reads as today's")
        self.assertIn("CLAUDE.md", self.doc,
                      "NEXT_SESSION.md must name CLAUDE.md as the real record")

    def test_it_never_teaches_a_command_that_hardcodes_a_pointer(self):
        """`--show live` names the POINTER. `--show four` names today's
        answer, and is wrong the day he promotes somebody -- with the
        failure looking exactly like the deck working.

        AND IT READS THE COMMANDS, NOT THE PROSE. The first version of
        this test banned the string outright and went red on the
        paragraph at the top of the doc explaining that `--show
        shiro_deck` is the fault being avoided -- the grep-matches-prose
        trap, fifteenth instance, in the test written to guard against
        exactly that class of staleness. A note explaining an absence
        must never read as that thing being present, so only indented
        command lines count."""
        commands = [ln for ln in self.doc.splitlines()
                    if ln.startswith("    ") and ln.strip()]
        found = False
        for line in commands:
            for stale in re.findall(r"--show\s+(\S+)", line):
                found = True
                self.assertEqual(
                    stale, "live",
                    "NEXT_SESSION.md tells a fresh session to run `--show %s`. "
                    "That is a persona KEY, so it goes stale the moment "
                    "LIVE_PERSONA moves -- name the pointer "
                    "(`--show live`) instead." % stale)
        self.assertTrue(
            found,
            "NEXT_SESSION.md no longer shows how to print the live composed "
            "prompt -- that is the deliverable every prompt change here "
            "is measured on, and he pastes it into PocketPal by hand")

    def test_the_files_and_commands_it_names_actually_exist(self):
        """It hands a fresh session a working loop. A path in it that is
        not there reads as the repo being broken rather than as the note
        being old."""
        here = Path(__file__).parent
        for name in ("CLAUDE.md", "YUZU_TESTER.py", "yuzu_personas.py",
                     "yuzu_face.py", "yuzu_brain.py", "deck"):
            self.assertIn(name, self.doc,
                          "NEXT_SESSION.md no longer mentions %s" % name)
            self.assertTrue((here / name).exists(),
                            "NEXT_SESSION.md names %s and it does not exist"
                            % name)


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

    # ---- a running server keeps serving the OLD code ------------------

    def _restart_run(self, changed, server_up, added=(), face_ok=True):
        """Drive the REAL pull script in a temp dir, with stubs beside it.

        A copy rather than the repo itself, because `pull` cds to its own
        directory and would otherwise call the real `face` and stop the
        real server."""
        import subprocess
        tmp = tempfile.mkdtemp()
        try:
            here = Path(tmp)
            shutil.copy(self.SCRIPT, here / "pull")
            (here / "pull").chmod(0o755)

            # `face` records how it was called instead of doing anything
            # -- and prints its real startup banner, because what that
            # banner does to his pull is the thing under test.
            log = here / "face.log"
            (here / "face").write_text(
                '#!/bin/bash\necho "face $*" >> %s\n'
                '[ "$1" = "--off" ] || {\n'
                '  echo "UP.  Open this on your phone:"\n'
                '  echo "That is the HOME SCREEN, not her face."\n'
                '  exit %d\n}\n' % (log, 0 if face_ok else 1))
            (here / "face").chmod(0o755)

            binv = here / "bin"
            binv.mkdir()
            # rev-parse is called TWICE and must differ, or the script
            # correctly reports ALREADY UP TO DATE and restarts nothing.
            names = " ".join("'%s'" % c for c in changed)
            fresh = " ".join("'%s'" % c for c in added) or "''"
            # Added files answer a DIFFERENT git question, and the stub
            # has to keep them apart -- one stub answering two questions
            # is how the docker bridge got into an address an hour ago.
            for f in added:
                (here / f).write_text("#!/bin/bash\n")
                (here / f).chmod(0o755)
            (binv / "git").write_text(
                '#!/bin/bash\n'
                'case "$*" in\n'
                '  "rev-parse HEAD")\n'
                '     n=$(cat {t}/n 2>/dev/null || echo 0)\n'
                '     echo $((n+1)) > {t}/n\n'
                '     echo "rev$n" ;;\n'
                '  "pull origin main") echo ok ;;\n'
                '  log*) echo "  abc123 a change" ;;\n'
                '  "diff --name-only --diff-filter=A"*) printf "%s\\n" {fresh} ;;\n'
                '  diff*) printf "%s\\n" {names} ;;\n'
                '  *) exit 0 ;;\n'
                'esac\n'.format(t=tmp, names=names, fresh=fresh))
            (binv / "git").chmod(0o755)
            (binv / "pgrep").write_text(
                "#!/bin/bash\nexit %d\n" % (0 if server_up else 1))
            (binv / "pgrep").chmod(0o755)

            done = subprocess.run(
                ["bash", str(here / "pull")], capture_output=True, text=True,
                timeout=60,
                env=dict(os.environ, YUZU_PULL_WAITS="0",
                         PATH=f"{binv}:{os.environ['PATH']}"))
            calls = log.read_text() if log.exists() else ""
            return done, calls
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_a_pull_NAMES_a_command_that_did_not_exist_before(self):
        """MEASURED, Sept 15. He was told to run `~/YUZU/name ghostnano`,
        had pulled ten minutes earlier, and got

            -bash: /home/ghost/YUZU/name: No such file or directory

        twice -- because the obvious second guess is that you are in the
        wrong directory, so he cd'd there and tried again. Nothing was
        wrong. The script simply landed after his pull.

        A new FILE is invisible inside "37 files changed". A new COMMAND
        is a thing he is about to TYPE, so it gets its own line -- the
        same reason HER FACE CHANGED has one, a layer over."""
        done, _ = self._restart_run(
            ["name", "ui/home.html"], server_up=False, added=["name"])
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("NEW COMMAND: ~/YUZU/name", done.stdout, done.stdout)

    def test_an_ordinary_pull_announces_no_new_commands(self):
        """A line that appears every time is a line he stops reading."""
        done, _ = self._restart_run(["ui/home.html"], server_up=False)
        self.assertNotIn("NEW COMMAND", done.stdout,
                         "it announces commands that are not new")

    def test_a_new_MODULE_is_not_a_new_command(self):
        """`yuzu_cutout.py` is not something he types at a prompt, and a
        notice that fires on things he cannot run is the same noise as
        one that fires every time."""
        done, _ = self._restart_run(
            ["yuzu_thing.py"], server_up=False, added=["yuzu_thing.py"])
        self.assertNotIn("NEW COMMAND", done.stdout,
                         "it offered him a python module to type")

    def test_a_pull_that_changes_server_code_restarts_a_LIVE_server(self):
        """MEASURED, Sept 15, and it looked exactly like a feature that
        had not arrived.

        Ghost pulled the round that added Four, opened the deck, and got
        ONE full-width Stuff tile with no character on it. Both halves
        were true at once, which is the trap: home.html is a FILE,
        re-read per request, so the markup was new -- and
        /characters.json comes out of a PYTHON PROCESS that had been
        running since before the pull, so the roster was old. No Four,
        no `front` flag, and the page's honest fallback for an empty
        roster is what he saw.

        Reproduced by serving the new page from a server with the old
        roster: pixel for pixel his screenshot. `face` cannot fix this
        from inside -- it re-reads ui/ but never its own module -- so
        the fix belongs where the changed files are already known."""
        done, calls = self._restart_run(["yuzu_face.py"], server_up=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("face --off", calls, "the stale server was left running")
        self.assertIn("face \n", calls.replace("face\n", "face \n"),
                      "it was stopped and never started again")
        self.assertIn("OLD CODE", done.stdout,
                      "it restarted silently; he cannot tell it happened")

    def test_a_pull_that_changes_WHO_SHE_IS_also_restarts_her(self):
        """FOUND BY SHIPPING ONE, Sept 22. The offline sentence went
        into the deck BODY FILE -- a change to what she IS -- and this
        gate matched only top-level `.py`, so his pull would have
        landed it and left the running server answering from the old
        prompt cached in `_BRAINS`. She would have gone on saying "I'm
        always connected" over a repo that already said otherwise.

        SAME FAULT AS THE STALE ROSTER, in the one costume the guard
        did not cover: pulled, landed, not in effect, and looking
        exactly like the work never arrived. A persona is as invisible
        as a module and fails the same way.

        `ui/` stays OUT on purpose -- it genuinely is re-read per
        request, so bouncing the server to deliver a PNG it would have
        served anyway drops his conversation for nothing."""
        for changed in ("personas/four.persona",
                        "personas/_hardware_cyberdeck.txt"):
            done, calls = self._restart_run([changed], server_up=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            self.assertIn("face --off", calls,
                          "%s landed and she kept the old prompt" % changed)
            self.assertIn("OLD CODE", done.stdout,
                          "it restarted silently; he cannot tell")

    def test_ART_AND_PAGES_still_do_not_cost_him_the_conversation(self):
        """The other half, and it is why the gate is not just "anything
        changed". `ui/` is re-read per request, so a restart there buys
        nothing and costs the chat history on screen."""
        done, calls = self._restart_run(
            ["ui/home.html", "ui/mimi/crawling.png"], server_up=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertNotIn("face --off", calls,
                         "a page change bounced her and dropped the chat")

    def test_the_restart_does_not_DUMP_the_server_banner_into_his_pull(self):
        """MEASURED, Sept 16, off his screen. The Welcome line WAS there
        -- and above it sat twenty lines of `face`'s own startup banner:
        the address twice, the HOME SCREEN paragraph, the sprite note.
        Ghost: "All that is unnecessary... just a buncha changes i
        already know happened."

        He asked for an update, not for a server. The address is printed
        by the welcome two inches below anyway, so the restart says it
        restarted and nothing else."""
        done, calls = self._restart_run(["yuzu_face.py"], server_up=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("face --off", calls, "it never restarted anything")
        self.assertIn("OLD CODE", done.stdout, "he cannot tell it happened")
        self.assertNotIn("HOME SCREEN", done.stdout, done.stdout)
        self.assertNotIn("Open this on your phone", done.stdout, done.stdout)

    def test_a_restart_that_FAILS_is_still_loud(self):
        """Swallowing it would be the silent-failure shape this repo
        refuses everywhere else. A server that did not come back is the
        one thing in that banner worth his attention."""
        done, _ = self._restart_run(
            ["yuzu_face.py"], server_up=True, face_ok=False)
        self.assertIn("did not come back", done.stdout, done.stdout)
        self.assertIn("Open this on your phone", done.stdout,
                      "it hid the server's own output on a real failure")

    def test_it_does_NOT_start_a_server_he_never_asked_for(self):
        """Starting one because a .py moved is its own surprise -- and on
        a board he is using as a computer, a port opening by itself is
        the wrong kind of helpful. Restart only what was already up."""
        done, calls = self._restart_run(["yuzu_face.py"], server_up=False)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(calls, "", "pull started a server on its own")

    def test_art_alone_does_not_bounce_a_healthy_server(self):
        """ui/ is re-read per request, so a new PNG or a new page needs a
        page refresh and nothing more. Dropping his conversation to
        deliver a file the server would have served anyway is a cost with
        no purchase."""
        done, calls = self._restart_run(
            ["ui/sprites/idle.png", "ui/home.html"], server_up=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(calls, "", "a picture restarted the server")
        self.assertIn("HER FACE CHANGED", done.stdout)

    # ---- the pull that delivers a change to THIS SCRIPT ---------------

    def _selfchange_run(self, tail, changed=("pull",)):
        """Replace the running script mid-run, exactly as `git pull` does.

        This is not a simulation of the fault, it IS the fault: bash has
        the file open, git swaps a new one in underneath, and the run
        that brought the change is the one run that cannot contain it."""
        import subprocess
        tmp = tempfile.mkdtemp()
        try:
            here = Path(tmp)
            shutil.copy(self.SCRIPT, here / "pull")
            (here / "pull").chmod(0o755)
            # What `git pull` will swap in: the same script plus a line
            # that can only come from the NEW copy.
            (here / "new_pull").write_text(
                self.SCRIPT.read_text() + "\n" + tail + "\n")

            (here / "yuzu_voice.py").write_text(
                "class _V:\n    ready = True\n"
                "def pick_voice(**kw): return _V()\n")

            binv = here / "bin"
            binv.mkdir()
            names = " ".join("'%s'" % c for c in changed)
            (binv / "git").write_text(
                '#!/bin/bash\n'
                'case "$*" in\n'
                # DRIVEN BY WHETHER THE PULL HAPPENED, never by a
                # counter. A counter hands out a fresh commit on every
                # call, so a re-run that FORGOT what it started from
                # still looks like an update -- the fixture would then
                # be a check that cannot observe its own failure, which
                # is the oldest line in CLAUDE.md. Verified by handing
                # the re-run the wrong commit on purpose.
                '  "rev-parse HEAD")\n'
                '     if [ -f {t}/pulls ]; then echo new; else echo old; fi ;;\n'
                '  "pull origin main")\n'
                '     echo pulled >> {t}/pulls\n'
                '     cp {t}/new_pull {t}/pull ;;\n'
                '  log*) echo "  abc123 the commit that changes pull" ;;\n'
                '  "diff --name-only --diff-filter=A"*) echo "" ;;\n'
                '  diff*) printf "%s\\n" {names} ;;\n'
                '  *) exit 0 ;;\n'
                'esac\n'.format(t=tmp, names=names))
            (binv / "git").chmod(0o755)
            for name, body in (("pgrep", "exit 1"), ("hostname", "echo deck")):
                (binv / name).write_text("#!/bin/sh\n%s\n" % body)
                (binv / name).chmod(0o755)

            done = subprocess.run(
                ["bash", str(here / "pull")], capture_output=True, text=True,
                timeout=60,
                env=dict(os.environ, YUZU_PULL_WAITS="0",
                         PATH=f"{binv}:{os.environ['PATH']}"))
            pulls = (here / "pulls").read_text().count("pulled") \
                if (here / "pulls").exists() else 0
            return done, pulls
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    MARK = 'echo "  MARKER-FROM-THE-NEW-COPY"'

    def test_a_pull_that_changes_THIS_SCRIPT_runs_the_new_one(self):
        """MEASURED, Sept 16, on his screen. He pulled the round that
        added the voice setup and the Welcome line; the output said
        UPDATED and listed the exact commit that added them -- and then
        printed the OLD tail, with neither of the new things in it.

        Nothing was broken and he read it exactly right. Bash had the
        file open before git replaced it, so the run that brings a
        change to this script is the one run that cannot contain it.
        Same shape as `~/YUZU/name` saying "No such file or directory"
        a day earlier: the work landed, one run late, and that looks
        exactly like the work not landing.

        And it is worse than a delay -- verified by replacing a running
        script mid-run, bash re-reads the NEW file at the byte offset it
        had reached in the OLD one and executes a FRAGMENT of the new
        script spliced onto the old run. Undefined behaviour, not a late
        delivery."""
        done, _ = self._selfchange_run(self.MARK)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertIn("MARKER-FROM-THE-NEW-COPY", done.stdout,
                      "the new copy never ran; he got the old tail again")
        self.assertIn("UPDATED ITSELF", done.stdout,
                      "it re-ran silently -- a broken new copy would give "
                      "him an empty pull with nothing to read")

    def test_the_re_run_reports_the_REAL_update(self):
        """The second run must not pull again, and must not report
        ALREADY UP TO DATE about an update it just delivered. It is
        handed the commit the first run started from, so the verdict
        and the commit list stay true."""
        done, pulls = self._selfchange_run(self.MARK)
        self.assertIn("UPDATED.", done.stdout, done.stdout)
        self.assertNotIn("ALREADY UP TO DATE", done.stdout,
                         "the re-run forgot what it had just pulled")
        self.assertIn("the commit that changes pull", done.stdout,
                      "the commit list was lost across the re-run")
        self.assertEqual(pulls, 1, "it pulled twice")

    def test_it_re_runs_AT_MOST_ONCE(self):
        """The stub reports `pull` as changed on EVERY run, so without
        the guard this is an infinite loop -- verified by removing the
        guard and watching it run until it was killed. One env var,
        set on the way out and checked on the way in, bounds it."""
        done, _ = self._selfchange_run(self.MARK)
        self.assertEqual(done.stdout.count("UPDATED ITSELF"), 1,
                         "it re-ran itself more than once")
        self.assertEqual(done.stdout.count("MARKER-FROM-THE-NEW-COPY"), 1)

    def test_an_ordinary_pull_does_not_re_run_itself(self):
        """Every other pull pays nothing for this. A second run costs a
        second git round trip and a second screen of output, for a
        script that did not change."""
        done, _ = self._restart_run(["ui/home.html"], server_up=False)
        self.assertNotIn("UPDATED ITSELF", done.stdout,
                         "it re-ran itself over somebody else's file")

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

    # ---- the systems he asked for ----------------------------------

    def test_every_system_he_asked_for_is_INVENTORIED(self):
        """Ghost, Sept 22: *"Snes ps1 nes and gameboy color please add
        those to ES-DE"* -- and Sept 23: *"Ive decided i dont need ps1
        for now. Too lazy to fw bios."*

        He is not going to remember which package plays what, and a
        list typed into a doc is a list that goes stale against his
        actual Ubuntu. `--check` asks HIS board and names the fix.

        AND IT NEVER OFFERS WHAT HE TURNED DOWN. `--check` ends with one
        line that installs everything missing, so a PS1 row left in it
        is an install he said no to, riding along in the line he pastes
        -- and the setup must not make a folder for it either."""
        done, home, tmp = self._stub_run(self.SCRIPT, extra=["--check"])
        try:
            out = done.stdout.lower()
            for system in ("gbc", "nes", "snes"):
                self.assertIn(system, out,
                              "%s is not in the inventory, so he has no "
                              "way to find out what plays it" % system)
            for gone in ("ps1", "playstation", "psx"):
                self.assertNotIn(gone, out,
                                 "--check still offers PlayStation")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
        made = re.search(r"for system in ([^;]+); do",
                         self.SCRIPT.read_text()).group(1).split()
        self.assertNotIn("psx", made, "the setup still makes a PS1 folder")

    def test_GAME_BOY_COLOR_needs_no_new_package_at_all(self):
        """THE FIRST ANSWER IS THAT ONE OF THE FOUR IS ALREADY DONE.
        mGBA plays Game Boy and Game Boy COLOR as well as Advance, so
        `gbc` needs a folder and nothing else -- and telling him to
        install something he already has is the kind of wrong step this
        project has paid for."""
        done, home, tmp = self._stub_run(
            self.SCRIPT, have=("mgba-qt",), extra=["--check"])
        try:
            line = [l for l in done.stdout.splitlines() if "gbc" in l.lower()]
            self.assertTrue(line, "no row covers Game Boy Color")
            self.assertNotIn("MISSING", line[0],
                             "it asks him to install something for GBC "
                             "while mGBA is right there: %r" % line[0])
        finally:
            shutil.rmtree(tmp, ignore_errors=True)

    def test_the_PLAYSTATION_BIOS_is_named_BEFORE_it_fails(self):
        """Every other system here runs a ROM straight off. PS1 needs a
        console BIOS that no package ships, and without it a game dies
        with an error about the machine rather than about the file --
        which reads as a broken emulator.

        Same rule as writing the Forge fallback into the failure
        message rather than into a doc he will not open.

        PS1 IS OFF THE LIST NOW (Sept 23), so this fires on a GAME and
        never on a folder: an earlier `deck` left an empty ~/ROMs/psx
        on his board, and a caveat about a system he turned down,
        printed every run, is noise."""
        import subprocess
        tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, tmp, True)
        home = Path(tmp) / "home"
        (home / "ROMs" / "psx").mkdir(parents=True)

        def check():
            return subprocess.run(
                ["bash", str(self.SCRIPT), "--check"],
                capture_output=True, text=True, timeout=60,
                env={"PATH": "/usr/bin:/bin", "HOME": str(home)}).stdout

        self.assertNotIn("BIOS", check(),
                         "an EMPTY psx folder nags him about a system he "
                         "decided against")
        (home / "ROMs" / "psx" / ".directory").write_text("")
        self.assertNotIn("BIOS", check(), "a hidden file counted as a game")
        (home / "ROMs" / "psx" / "Crash Bandicoot (USA).cue").write_text("")
        done = check()
        self.assertIn("BIOS", done,
                      "he finds out PS1 needs a BIOS by a game failing "
                      "at the panel")
        # AND IT STAYS QUIET WHEN THERE IS NO PS1 FOLDER. A caveat that
        # fires whatever is on the board is the same noise as a notice
        # that fires every time -- the rule `pull`'s NEW COMMAND line
        # already pays.
        bare = Path(tmp) / "bare"
        bare.mkdir()
        quiet = subprocess.run(
            ["bash", str(self.SCRIPT), "--check"],
            capture_output=True, text=True, timeout=60,
            env={"PATH": "/usr/bin:/bin", "HOME": str(bare)})
        self.assertNotIn("BIOS", quiet.stdout,
                         "the PS1 caveat fires on a board with no PS1 "
                         "folder on it")

    def test_every_folder_it_makes_is_one_SHE_can_name(self):
        """TWO LAYERS, PINNED TO AGREE. `deck` creates the ROM folders
        and `board_has()` counts what lands in them -- and a folder she
        has no readable name for comes out as "1 psx game" in her
        prompt. Both ends are ours here, so there is no excuse for them
        disagreeing.

        `_SYSTEMS` stays a politeness layer rather than an allowlist --
        an unknown folder is still COUNTED -- so this is about the ones
        the deck itself creates, not about every folder that can
        exist."""
        import yuzu_face
        body = self.SCRIPT.read_text()
        made = re.search(r"for system in ([^;]+); do", body)
        self.assertIsNotNone(made, "deck no longer creates the rom folders")
        for system in made.group(1).split():
            self.assertIn(
                system, yuzu_face._SYSTEMS,
                "deck makes a ~/ROMs/%s folder that she has no name "
                "for, so she will call it '%s' in her own prompt"
                % (system, system))

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

    CEILING = 600

    def test_the_reply_ceiling_and_the_CONTEXT_agree(self):
        """THE GUARD THIS ROUND EXISTS FOR, and it is the one that
        would have said how close 300 already was.

        `num_predict` is described everywhere in this repo as free --
        "it caps generated TOKENS, not anything resident" -- and that
        is true of MEMORY and false of CONTEXT. Everything she
        generates lands in history, so the reply ceiling multiplies by
        `history_turns` and lands squarely inside `num_ctx`:

            system prompt + (history_turns + 1) x num_predict

        AT THE SETTINGS THAT SHIPPED ON SEPT 19 THIS GOES RED, which
        is how the round found it. Driven, with every character back on
        300 and `num_ctx` 4096: `cait needs ~4375 tokens and num_ctx is
        4096`. Three +50 raises had walked the window to its edge one
        at a time, nobody checked the product, and the fourth was the
        one asked for.

        IT IS ARITHMETIC, NOT A READING FROM HIS BOARD -- there is no
        model and no Ollama in this container, and chars-per-token is
        an estimate. Counted loosely (3.8 chars/token, his turns short)
        the same settings come to ~3970 of 4096, just under. So the
        honest claim is AT OR OVER depending on how you count, which is
        exactly the place a ceiling should never be sitting -- and it
        is why the constant below is deliberately the pessimistic one.

        AND OVER IS NOT AN ERROR, which is why this matters more than
        the arithmetic suggests. Nothing raises, nothing prints;
        tokens are dropped and she comes back having quietly forgotten
        the start of the conversation -- the exact thing `~/.yuzu/
        history/` was built to stop, undone by the setting meant to
        make her better. A mid-word cut is VISIBLE and he answers it
        with "continue". A hole in her memory is not.

        So the two are ONE SETTING and this pins that they agree.
        Chars-per-token is deliberately PESSIMISTIC (3.5, where English
        on a Llama tokenizer runs nearer 3.8-4.0) so the guard errs
        toward complaining early."""
        import re as _re
        brain = (Path(__file__).parent / "yuzu_brain.py").read_text()
        num_ctx = int(_re.search(r'"num_ctx":\s*(\d+)', brain).group(1))
        turns = int(_re.search(r"history_turns=(\d+)", brain).group(1))

        CHARS_PER_TOKEN = 3.5
        HIS_TURN = 60          # tokens; what he types is short beside her

        worst = None
        for key in sorted(yuzu_personas.available()):
            persona = yuzu_personas.load(key)
            cap = persona.settings.get("num_predict")
            if not cap:
                continue                      # the archives inherit 150
            system = len(persona.prompt) / CHARS_PER_TOKEN
            # The deck characters also carry the live board line and
            # the specs line on every single turn.
            if persona.hardware == "cyberdeck":
                import yuzu_face
                yuzu_face._SPECS = None
                system += len(yuzu_face.board_specs()
                              + yuzu_face.board_now()) / CHARS_PER_TOKEN
                # AND THE INVENTORY AT ITS CAP. It is empty in this
                # container and ~350 characters on his board, so
                # counting what it happens to say HERE is a guard that
                # only holds where nobody has any games.
                system += yuzu_face.HAS_MAX / CHARS_PER_TOKEN
                yuzu_face._SPECS = None
            # AND THE FACTS BUDGET IS SPENT AS IF FULL.
            #
            # What Ghost asked her to remember rides on the system
            # prompt on EVERY turn, exactly like the board line -- so a
            # guard that counts the store at its CURRENT size is a
            # guard that only holds on a board nobody has used yet. It
            # is counted at its cap, with the real frame text measured
            # rather than estimated, because the number that matters is
            # the worst case he can actually reach by tapping a button.
            import yuzu_face
            with mock.patch.object(yuzu_face, "load_facts",
                                   lambda k: ["x" * yuzu_face.FACTS_BUDGET]):
                system += len(yuzu_face.facts_line(key)) / CHARS_PER_TOKEN
            need = system + turns * (int(cap) + HIS_TURN) + int(cap)
            if worst is None or need > worst[1]:
                worst = (key, need)
            self.assertLessEqual(
                need, num_ctx,
                "%s needs ~%d tokens of context in a long conversation "
                "and num_ctx is %d -- she will silently forget the "
                "start of it. Raise num_ctx with num_predict, or lower "
                "one of them." % (key, need, num_ctx))
        self.assertIsNotNone(worst, "nobody sets num_predict any more")

    def test_num_predict_has_a_CEILING_and_every_character_shares_it(self):
        """RAISED to 250 on Sept 16 and to 300 on Sept 19, and this
        test used to forbid exactly that -- so the reason is worth
        having next to the number.

        The second raise is Ghost again, same complaint, same shape:
        *"Increase Fours token output kinda deal by another 50."* He
        asked about FOUR and the number moved on everybody, because
        that is what this test is for -- see the last paragraph. If a
        character ever genuinely needs her own ceiling, that is a
        deliberate change to this test, not a quiet edit to one file.

        The rule it replaces ("the truncation is a symptom of rambling
        and a bigger ceiling just buys longer rambles") was written
        about SHIRO, against a rule capping her at two or three
        sentences, on replies nobody asked to be long. That is still
        true of a character who rambles.

        Ghost's case is the other one, and he was explicit: *"she cuts
        off too much when im just getting into the paragraph."* He is
        deliberately in a long exchange and the reply dies MID-WORD. An
        unfinished sentence is worse than a shorter finished one either
        way, so the ceiling is not what was protecting brevity -- her
        prompt is.

        RAISED AGAIN TO 600 ON SEPT 21, and that round found the
        thing the first two missed. Ghost, a third time: *"she still
        trys to go past her token limit i dont really mind as long as
        its in responsr to what i asked (always is so far js)"*. Three
        +50s had not fixed it, which is its own signal -- so this one
        DOUBLES, and it moves `num_ctx` with it.

        `num_predict` costs no memory on its own. What it costs is
        CONTEXT, because everything she generates lands in history --
        and at 300 the worst case was already ~3970 of `num_ctx` 4096.
        Going over does not error; tokens are dropped with nothing on
        screen to say so, which trades a VISIBLE mid-word cut for an
        INVISIBLE hole in what she remembers. `test_the_reply_ceiling
        _and_the_CONTEXT_agree` is the guard, and it is the one that
        would have caught how close 300 already was.

        The ceiling STAYS, because unbounded is how a 3B monologues
        until the context fills. It is one number, shared, so nobody
        raises it quietly on one character."""
        import re as _re
        seen = set()
        for f in sorted((Path(__file__).parent / "personas").glob("*.persona")):
            for found in _re.findall(r"num_predict:\s*(\d+)", f.read_text()):
                self.assertLessEqual(int(found), self.CEILING,
                                     f"{f.name} raised num_predict to {found}")
                seen.add(int(found))
        self.assertEqual(seen, {self.CEILING},
                         "the characters disagree about the ceiling: %s" % seen)


class TestTheVPetIsGone(unittest.TestCase):
    """Ghost, Sept 23: "Can you put the vpet aside while i get it set
    up? As in "delete it" from the cyberdeck. Prolly requires screen
    layout changing etc."

    DELETED, NOT RETIRED -- the LEDs' call rather than the cast's.
    `retired: yes` is one line of data nobody loads; the pet was a
    module, a page, twelve sprites, two source zips and a POST route on
    a server bound to 0.0.0.0, and a dead subsystem you still have to
    read around is worse than none. It is all in git.

    What is pinned is what would go wrong QUIETLY: a tap that lands on
    a page that is not there, a route that still answers, and an icon
    left on his desktop pointing at nothing."""

    UI = Path(__file__).parent / "ui"

    def test_every_page_the_deck_links_to_is_really_there(self):
        """A PROPERTY, not a search for the word "vpet". The Pet tile
        was `data-go="vpet.html"`; leave one like it behind and the tap
        does nothing, which on this deck reads as broken rather than
        as missing. So every page any page on the deck opens has to
        exist -- which also covers the next thing that gets deleted.

        Comments are stripped first. face.html still tells the story of
        the pet leaving its screen, and a comment describing an absence
        must never read as the thing being present."""
        for page in sorted(self.UI.glob("*.html")):
            body = re.sub(r"<!--.*?-->", "", page.read_text(), flags=re.S)
            for target in re.findall(
                    r'(?:data-go|href)="([\w./-]+\.html)(?:[#?][^"]*)?"',
                    body):
                self.assertTrue((self.UI / target).exists(),
                                "%s opens %s, which is not on the deck"
                                % (page.name, target))

    def test_the_server_does_not_answer_for_it_any_more(self):
        """Driven, not read. Both halves of the old route -- the GET the
        page polled and the POST its buttons sent -- must come back
        404, the same as any other name this server does not know."""
        import threading, urllib.error, urllib.request, yuzu_face
        from http.server import ThreadingHTTPServer
        server = ThreadingHTTPServer(("127.0.0.1", 0), yuzu_face._Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = "http://127.0.0.1:%d" % server.server_address[1]
        for path, data in (("/vpet.json", None), ("/vpet.html", None),
                           ("/vpet/poke", b"{}")):
            with self.assertRaises(urllib.error.HTTPError, msg=path) as got:
                urllib.request.urlopen(base + path, data=data, timeout=5)
            self.assertEqual(got.exception.code, 404, path)


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

    def test_every_character_is_reachable_from_this_screen(self):
        """Ghost, Sept 12: "she also was only found by clicking cait 1st
        then finding her name lmao."

        MIMI SHIPPED INVISIBLE FROM HERE. She had a page, a persona and
        a rail entry on every other character's screen, and this page
        kept its OWN list of the cast -- so the one screen the deck
        boots into was the one place she did not exist.

        The fix is that there is now exactly one list, in
        yuzu_face.CHARACTERS, and this page builds its A.I. drawer from
        /characters.json like every rail already did. So the assertion
        is not "Saya's tile is in the markup" any more -- that was the
        shape of the bug. It is that NO character is named in this file
        at all, because anything named here is something that can fall
        behind."""
        page = self.PAGE.read_text()
        import yuzu_face
        self.assertIn("characters.json", page,
                      "the home screen does not ask for the roster")
        for who, (key, target, blurb) in yuzu_face.CHARACTERS.items():
            self.assertNotIn('data-go="%s"' % target, page,
                             "%s is hardcoded onto the home screen -- the "
                             "exact way Mimi went missing" % who)

    def test_the_front_page_is_ONE_CHARACTER_and_ONE_DRAWER(self):
        """Ghost, Sept 15, in his own words: "i wana put the Ais in the
        misc drawer and maybe have 1 specific one take over (have yet to
        choose the new main...)", then the layout: "Feel free to cluster
        the etc stuff into one new misc drawer. Rename the outer front
        page drawer to ☆Stuff☆ so layout Homescreen (central new
        undecided ai and ☆stuff☆ > inside stuff theres ai tab and misc
        tab with the rest of the stuff in that one."

        THE FRONT TILE IS NOT IN THE MARKUP AT ALL, and that is the
        point this test exists to keep. It is built from whichever
        roster entry carries `front`. A character typed onto this page
        is exactly how Mimi went missing, and a hardcoded FRONT DOOR is
        the same bug with a shorter list: it goes stale the day he picks
        his new main."""
        page = self.PAGE.read_text()
        views = {}
        # `class="tile ..."`, not `class="tile"`: the d20 carries a
        # second class before its first roll, and a literal match
        # silently dropped it from the count.
        for tile in re.findall(r'<div class="tile[ "][^>]*>', page):
            views.setdefault(
                re.search(r'data-view="(\w+)"', tile).group(1), []).append(tile)
        # The `ai` view is BUILT FROM THE ROSTER and has no tiles here,
        # and so is the front character -- which is why `main` holds one
        # tile in this file and two on screen.
        self.assertEqual(sorted(views), ["main", "misc", "stuff"])
        self.assertEqual(len(views["main"]), 1,
                         "something other than ☆Stuff☆ is typed onto the "
                         "front page")
        self.assertEqual(len(views["stuff"]), 2, "☆Stuff☆ is not two")
        self.assertEqual(len(views["misc"]), 5, "the drawer is not five")
        for css in ("#grid.main { grid-template-columns: repeat(2, 1fr); }",
                    "#grid.stuff { grid-template-columns: repeat(2, 1fr); }"):
            self.assertIn(css, page)
        # NO VIEW MAY END ON A ROW WITH A HOLE IN IT. Stated as the
        # PROPERTY rather than as numbers, so the next tile added has to
        # answer for the layout it lands in. `main` counts the generated
        # front character as well as the ☆Stuff☆ tile in the markup --
        # one typed plus one built is the two that reach the screen.
        for view, built, columns in (("main", 1, 2), ("stuff", 0, 2)):
            self.assertEqual((len(views[view]) + built) % columns, 0,
                             f"the {view} view orphans a tile on its own row")
        # THE DRAWER IS THE ONE VIEW WHOSE COUNT MOVES BOTH WAYS, so it
        # does not rely on the count at all: its short row is CENTRED.
        # Rendered at 1024x600 when the V-Pet left -- a grid of three
        # left a hole in the corner and five across made pillars.
        misc = re.search(r"#grid\.misc\s*\{([^}]*)\}", page).group(1)
        for want in (r"display:\s*flex", r"flex-wrap:\s*wrap",
                     r"justify-content:\s*center"):
            self.assertRegex(misc, want,
                             "the drawer's short row is not centred, so it "
                             "ends on a hole: " + want)
        self.assertRegex(page, r"#grid\.misc > \.tile \{ flex: 0 0 "
                               r"calc\(\(100% - 2 \* 12px\) / 3\); \}",
                         "the drawer's tiles are not a third each")
        # The rule is about the TILE grid: a wide tile forced an odd row
        # and orphaned two others. The calculator's display spanning its
        # own keypad is not that, so pin WHICH selector may span rather
        # than banning the string and catching the wrong one.
        spans = re.findall(r"([#.][\w-]+)[^{}]*\{[^}]*grid-column:\s*span", page)
        self.assertEqual(spans, ["#screen"],
                         "a spanning tile is back, and an odd row with it")
        # EVERY LEVEL HAS A WAY DOWN INTO THE NEXT ONE.
        self.assertIn('data-show="stuff"', "".join(views["main"]),
                      "the front page does not open ☆Stuff☆")
        self.assertEqual(
            sorted(re.findall(r'data-show="(\w+)"', "".join(views["stuff"]))),
            ["ai", "misc"], "☆Stuff☆ does not hold exactly A.I. and ☆Misc☆")
        self.assertIn('data-launch="browser"', "".join(views["misc"]),
                      "there is no way to the web from her screen")
        # TALK IS NOT A TERMINAL. It used to POST /launch/chat, which
        # starts an xterm ON THE DECK'S SCREEN -- from the phone that is
        # a window nobody can see, and on the panel it lands him in a
        # terminal with no keyboard. The chat bar under her face is the
        # one that works on both.
        self.assertNotIn('data-launch="chat"', page,
                         "Talk opens a terminal again")
        for stars in ("☆Stuff☆", "☆Misc☆"):
            self.assertIn(stars, page, f"{stars} lost its stars")
        # AND THE TWO DRAWERS MUST NOT READ AS THE SAME DRAWER. They sit
        # one level apart in the same position on screen, and the first
        # draft gave both of them the subtitle "everything else" -- which
        # rendering it is what showed.
        subs = re.findall(r'<b class="stars">[^<]+</b>\s*\n\s*<span>([^<]+)', page)
        self.assertEqual(len(subs), len(set(subs)),
                         "☆Stuff☆ and ☆Misc☆ describe themselves identically")

    def test_a_TWO_TILE_view_gets_the_bigger_icon_whichever_view_it_is(self):
        """A 46px icon in a tile holding half the panel floats in the
        middle of it looking lost. That was found by rendering the
        two-tile front page, fixed there, and the fix was written as a
        LIST OF VIEW NAMES -- `#grid.main, #grid.stuff` -- with a
        comment beside it warning about exactly what happened next:
        "a rule that names one layout and not its twin is how #saya's
        72px outlived the page it was written for".

        Cutting the cast to Yuzu and Four dropped the A.I. drawer to
        two tiles, and its icons were the 46px ones, because that view
        was not on the list. It could never be on the list: it is the
        one view whose tile count is not known when the file is
        written, which is why it already emits its own
        `grid-template-columns` from `columnsFor()`. So it emits its
        icon size from the SAME number, in the same breath.

        WHAT IS PINNED IS AGREEMENT, NOT PIXELS -- no stdlib test can
        measure a layout, and that was done by rendering the drawer at
        1024x600 and looking. What a test can see is that every view
        laid out two across gets the same treatment, which is the
        failure that actually threatens this: a third two-column view
        landing without one."""
        page = self.PAGE.read_text()
        style = page.split("<style>")[1].split("</style>")[0]
        BIG = ".tile .big svg { width: 76px; height: 76px; }"

        # The static half: every view the stylesheet lays out two
        # across, and only those, carries the bigger icon.
        two = set(re.findall(r"#grid\.(\w+) \{ grid-template-columns: "
                             r"repeat\(2, 1fr\); \}", style))
        big = set(re.findall(r"#grid\.(\w+) \.tile \.big svg", style))
        self.assertTrue(two, "no view is laid out two across any more")
        self.assertEqual(two, big,
                         "a two-column view is missing the bigger icon, "
                         "or a wider one grew one it has no room for")

        # The dynamic half: the A.I. drawer must NOT be in either set --
        # its tile count comes off the roster, so a static rule about it
        # is a rule that is right until the cast changes. Both of its
        # rules ride on `columnsFor()` instead, emitted together.
        self.assertNotIn("ai", two, "the A.I. drawer's columns are static")
        self.assertNotIn("ai", big, "the A.I. drawer's icon size is static")
        script = page.split("function columnsFor")[1]
        # Bounded by the `.catch()` that follows, NOT by the first
        # semicolon -- the emitted text is CSS and is full of them.
        emitted = script.split("aicols")[1].split(".catch(")[0]
        self.assertIn("columnsFor", script)
        self.assertIn("#grid.ai { grid-template-columns: repeat(", emitted)
        self.assertIn("#grid.ai " + BIG.lstrip(), emitted,
                      "the A.I. drawer sizes its icons somewhere other "
                      "than where it decides its columns")
        self.assertIn("cols === 2", emitted,
                      "the icon size does not follow the column count")

    def test_the_front_character_is_a_ROLE_and_not_a_name(self):
        """`FRONT` in yuzu_face.py, one line to move, exactly like
        LIVE_PERSONA and for the same reason: Ghost has contenders and
        has not picked, so changing his mind has to cost one word in one
        place.

        IT IS DELIBERATELY NOT LIVE_PERSONA. That one is a MEASUREMENT
        pointer -- the promotion rule moves it to whichever prompt last
        scored best. This one decides who GREETS you. One variable doing
        two jobs is a fault this file records more than once."""
        import yuzu_face
        self.assertIn(yuzu_face.FRONT, yuzu_face.CHARACTERS,
                      "FRONT names nobody on the roster")
        front = [c for c in yuzu_face.roster() if c["front"]]
        self.assertEqual(len(front), 1, "the deck has no single front door")
        self.assertEqual(front[0]["who"], yuzu_face.FRONT)
        # A FRONT DOOR WITH NO PAGE IS A TAP THAT DOES NOTHING -- the
        # same rule that keeps a persona with no art off the rail.
        self.assertTrue(
            (Path(__file__).parent / "ui" / front[0]["page"]).exists(),
            "the front character has no page to open")
        # SHE IS STILL IN THE A.I. DRAWER. Being the front tile is a
        # shortcut, not a filing cabinet -- a character who vanished
        # from the roster because she was promoted would be the Mimi bug
        # pointing the other way.
        self.assertEqual(len(yuzu_face.roster()), len(yuzu_face.CHARACTERS))
        # And the highlight follows the ROLE. It used to be `#saya`,
        # which is the hardcoded-cast bug in stylesheet form: the day
        # the front door is somebody else the glow stays on a tile that
        # has moved into a drawer.
        page = self.PAGE.read_text()
        self.assertNotIn("#saya {", page, "the bright tile is pinned by name")
        self.assertIn(".lead {", page, "nothing marks the front tile")

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
        # IT WALKS DOWN ONE LEVEL rather than keeping a history -- a
        # stack is a thing that can strand you. It was a ternary reading
        # "calc goes to misc, everything else goes home", which was true
        # while home was one hop from everywhere; with ☆Stuff☆ in
        # between, "go home" from the calculator would skip two levels
        # he walked down on purpose.
        #
        # SO PIN THE PROPERTY, NOT THE SPELLING: parse the map out and
        # walk it. Every view must reach `main` in finite steps, and no
        # view may be its own ancestor -- a loop is a screen with no way
        # out, which is the one thing this deck must never ship.
        block = re.search(r"const PARENT = \{(.*?)\};", page, re.S)
        self.assertTrue(block, "Back has no map of the deck")
        parent = dict(re.findall(r"(\w+):\s*'(\w+)'", block.group(1)))
        self.assertEqual(parent.get("calc"), "misc",
                         "Back out of the calculator does not reach the drawer")
        self.assertEqual(parent.get("main"), "main",
                         "the front page has a parent")
        for view in set(re.findall(r'data-show="(\w+)"', page)) | {"calc"}:
            seen, at = [], view
            while at != "main":
                self.assertNotIn(at, seen, f"Back loops forever from {view}")
                seen.append(at)
                self.assertIn(at, parent, f"{at} has no way back")
                at = parent[at]
            self.assertLessEqual(len(seen), 3, f"{view} is buried too deep")
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
        # EVERY TILE HAS ONE, stated as the property rather than as a
        # magic number. The count version had to be edited every time a
        # tile was added, which is a test that costs attention without
        # ever catching anything -- and it would pass a page with ten
        # icons and nine tiles just as happily.
        tiles = re.findall(r'<div class="tile[^"]*"[^>]*>(.*?)(?=<div class="tile|</div>\s*\n\s*<div id=)',
                           page, re.S)
        self.assertGreaterEqual(page.count("<svg"), page.count('class="tile'),
                                "a tile is short of a line icon")
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

    def _run(self, *args, lan="10.1.2.3", port=None, host_name=None):
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
            # `hostname` and `hostname -s` are DIFFERENT QUESTIONS and
            # the stub has to answer them separately -- collapsing them
            # is how the real script's mDNS line ended up printing the
            # docker bridge inside an address.
            (binv / "hostname").write_text(
                "#!/bin/bash\n"
                'if [ "${1:-}" = "-s" ]; then echo "%s"; exit 0; fi\n'
                % (host_name if host_name is not None else "deckbox")
                + host_out)
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

    @contextlib.contextmanager
    def _serving(self):
        """The REAL handler on a free port, in this process.

        Not the `face` script: what is being pinned here is what the
        SERVER answers, and driving the shell wrapper as well would
        only add a way for the test to fail for an unrelated reason."""
        import yuzu_face
        from http.server import ThreadingHTTPServer
        server = ThreadingHTTPServer(("127.0.0.1", 0), yuzu_face._Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            yield "http://127.0.0.1:%d" % server.server_address[1]
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_the_bare_address_is_the_HOME_SCREEN(self):
        """Ghost, Sept 12: "make this page the screen that opens when i
        do ~/YUZU/face... id like to choose what i wana do before sayas
        face pops up 1st".

        It also closes a worse thing. Bare `/` was answered by
        SimpleHTTPRequestHandler's DIRECTORY LISTING, so the address he
        types on his phone gave him an index of ui/ -- art_in/, raw/,
        every sprite folder -- on a server bound to 0.0.0.0."""
        with self._serving() as base:
            landed = urllib.request.urlopen(base + "/", timeout=5).read()
            home = (Path(__file__).parent / "ui" / "home.html").read_bytes()
            self.assertEqual(landed, home, "`/` is not the home screen")

    def test_no_folder_under_ui_can_be_BROWSED(self):
        """A listing is not much of a hole -- it is her art -- but it
        has no reason to exist on a box sitting on his WiFi, and the
        files it lists are still served by NAME, which is all any page
        here needs. Same reasoning as `/launch/` being an allowlist."""
        # NOT `/sprites/`: that one is already an API route --
        # `/sprites.json` matches after rstrip("/"), so it answers with
        # the manifest rather than a listing and always has. Picking it
        # would have been a test that passes for the wrong reason.
        with self._serving() as base:
            for folder in ("/mimi/", "/raw/", "/cait/"):
                with self.assertRaises(urllib.error.HTTPError,
                                       msg=folder) as caught:
                    urllib.request.urlopen(base + folder, timeout=5)
                self.assertEqual(caught.exception.code, 404, folder)
            # ...and the art itself still arrives, which is the half
            # that would break the pages if this were done clumsily.
            got = urllib.request.urlopen(base + "/mimi/crawling.png",
                                         timeout=5)
            self.assertEqual(got.status, 200)
            self.assertTrue(got.read(8).startswith(b"\x89PNG"))

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
        # THE BARE ADDRESS, which lands on the home screen. Ghost, Sept
        # 12: "id like to choose what i wana do before sayas face pops
        # up 1st". It is also the address he actually types on a phone
        # keyboard, so anything after the port is a path he has to get
        # right by hand.
        self.assertIn(f"http://{real}:{port}/", done.stdout,
                      done.stdout + done.stderr)
        self.assertNotIn("/face.html", done.stdout,
                         "it still sends him straight to her face")
        for wrong in ("172.17.0.1", "192.168.55.1", "127.0.0.1"):
            if wrong == real:
                continue
            self.assertNotIn(f"http://{wrong}", done.stdout,
                             f"it told him to open {wrong}, which is not "
                             "reachable from the phone")

    def test_a_name_that_means_THIS_DEVICE_is_never_offered(self):
        """MEASURED, on his phone, in one screenshot:

            DNS_PROBE_FINISHED_NXDOMAIN
            Check if there is a typo in localhost.local.

        His board really is named `localhost`. The mDNS line took the
        hostname, checked it was made of legal characters, and printed
        http://localhost.local:8081/ -- which tells the PHONE to open
        ITSELF. Perfectly valid, and absolutely useless to anyone who is
        not the board.

        SECOND MISTAKE IN THAT ONE LINE IN AN HOUR, and the same shape
        both times: the guard asked "is this a syntactically legal
        hostname" when the question is "will this reach THIS board from
        ANOTHER device". A check that cannot observe the actual failure
        is not a check -- the oldest line in CLAUDE.md, broken an hour
        after quoting it."""
        real = self._this_machines_lan_ip()
        if not real:
            self.skipTest("this machine has no routable address to serve on")
        done, port = self._run(lan=real, host_name="localhost")
        self.assertNotIn(".local", done.stdout,
                         "it offered a name that means 'the device asking'")
        # The numbers still work, which is the point of absent-not-wrong.
        self.assertIn(f"http://{real}:{port}/", done.stdout)

    def test_a_real_name_IS_offered_because_an_IP_he_must_reread_needs_a_cable(self):
        """The line earns its place: an address he has to read off a
        serial terminal is an address he needs a cable to learn, and it
        changes with the DHCP lease. A name does not."""
        real = self._this_machines_lan_ip()
        if not real:
            self.skipTest("this machine has no routable address to serve on")
        done, port = self._run(lan=real, host_name="ghostnano")
        self.assertIn(f"http://ghostnano.local:{port}/", done.stdout,
                      done.stdout)
        # And it is OFFERED, never promised -- whether avahi answers on
        # his board is not checkable from here, and a stated fact that
        # turns out false costs more than an untried suggestion.
        self.assertIn("If it does not load", done.stdout,
                      "it promises mDNS works, which nothing here can know")

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
