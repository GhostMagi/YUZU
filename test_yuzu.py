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

import itertools
import shutil
import struct
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import muto_leg_control as legs
import yuzu_all_in_one as yuzu
import gguf_inspect
import yuzu_personas
import yuzu_prompt_eval as prompt_eval
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
        prompt = load_system_prompt()
        self.assertIn("You are Yuzu", prompt)
        for directive in ("PERSONALITY", "HARDWARE ACTION PARSING",
                          "BALANCED FLIRTATION", "NO PUPPETEERING",
                          "GYARU AESTHETIC"):
            self.assertIn(directive, prompt)

    def test_check_passes_when_model_is_present(self):
        self.assertTrue(self.brain().check())

    def test_missing_model_names_the_fix(self):
        with self.assertRaises(BrainError) as ctx:
            self.brain(model="not-a-real-model").check()
        self.assertIn("ollama create", str(ctx.exception))

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
        self.assertTrue(top_level <= {"json", "os", "struct", "sys",
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


class TestModelfile(unittest.TestCase):
    def test_generated_modelfile_carries_prompt_and_params(self):
        import build_yuzu_model
        rendered = build_yuzu_model.render()
        self.assertIn("FROM ", rendered)
        self.assertIn("You are Yuzu", rendered)
        self.assertIn("PARAMETER temperature 0.8", rendered)
        self.assertIn('PARAMETER stop "User:"', rendered)

    def test_committed_modelfile_matches_the_generator(self):
        # If this fails, someone edited Modelfile.yuzu by hand or changed
        # the prompt without re-running build_yuzu_model.py.
        import build_yuzu_model
        committed = (Path(__file__).parent / "Modelfile.yuzu").read_text()
        self.assertEqual(committed, build_yuzu_model.render(),
                         "Modelfile.yuzu is stale -- run: python build_yuzu_model.py")


if __name__ == "__main__":
    unittest.main(verbosity=2)
