# FULL TECHNICAL CONTEXT DUMP: Yuzu-Spider-V1 Robot Project

Purpose of this file: a single, maximally complete drop-in context file
(e.g. for a Claude Code project folder) containing not just facts but
actual current code and reasoning, so a new AI session/tool can pick up
this project with minimal re-explaining needed from Ghost (the human).

======================================================================
## 1. PROJECT IDENTITY
======================================================================
- Official designation: "Yuzu-Spider-V1"
- Active persona: Yuzu -- a mildly flirty, pink-obsessed Gyaru companion
- Platform: Yahboom Muto S2 hexapod robot (18-DOF, 6 legs)
- Brain (planned): NVIDIA Jetson Orin Nano Super Developer Kit (8GB, 67 TOPS)
- Model: Llama-3.2-3B-Instruct-Heretic-Abliterated-Uncensored (Q4_K_M),
  run locally via Ollama (no cloud, fully offline/local by design)
- Sister project: Saya -- separate quadruped build, Kuudere personality,
  Sesame Robot framework (Dorian Todd design), ESP32 controller, 8x MG90S
  servos, 128x64 OLED as reactive pixel face. Currently in planning only,
  no code/prompt work done on Saya this stretch.
- Human collaborator: goes by "Ghost." New to Python at the start of this
  project; has since independently written and run a working regex-based
  action parser on their own phone (Z Flip 6, via Pydroid 3).
- Workflow: Ghost runs a two-AI setup -- Google Gemini and Claude trade
  versioned "handoff notes" text files/PDFs back and forth to stay in
  sync on the same project. Known versions seen: Gemini v3 and v6,
  Claude v4 and v5. A quirk observed: when a chat session is lost, the
  other AI may reconstruct a "lost" file from ITS OWN separate context
  rather than the true original, producing divergent versions of the
  same file (this happened with an LED script, ledsnewestv7.py).

======================================================================
## 2. PERSONA HISTORY (why Yuzu, not something else)
======================================================================
Project started as a simple M5Stack Stackchan build (1B Llama, AX630C
NPU chip) with a persona named Pixie, which went through several tone
pivots (scene-girl -> sassy -> casual/flirty) to stop it from dodging
real questions with jokes. Pixie was renamed Saya (Highschool of the
Dead reference), tried as Tsundere, then briefly as Yandere (named Yuno,
Mirai Nikki reference) -- Tsundere won, Yandere felt too intense for
daily use. Two more personas were built and set aside: Himedere "Saki"
(too royal/mean in practice) and Kuudere "Coco" (abandoned mid-hardware
-conversion phase). Eventually Saya (tsundere) itself was set aside in
drafts, and Yuzu (gyaru) became the primary, currently-active persona,
first drafted for a 1B model, later rewritten and finalized for 3B.

Known accepted limitations carried through every persona: small local
models occasionally answer factual/local-knowledge questions confidently
wrong (fake landmarks, wrong math) -- treated as a model-capability
limitation, not something to keep chasing via prompt engineering.

======================================================================
## 3. CONFIRMED HARDWARE SPECIFICATION
======================================================================
- Chassis: Yahboom Muto S2 hexapod, 18-DOF, 6 legs, 18x 35KG serial bus
  servos, 2DOF camera gimbal (pan/tilt) -- NO face, NO hands, NO arms,
  NO hair. This constraint is critical and directly shapes the system
  prompt's action rules (see Section 5).
- Built-in 4-port USB 3.0 hub on the chassis itself.
- Compute: Jetson Orin Nano Super Dev Kit, 8GB RAM, 67 TOPS.
- Storage: Ghost has BOTH a 256GB and a 128GB microSD card on hand (no
  NVMe SSD yet). Note: NVIDIA's own docs say microSD boot is supported
  (64GB minimum), NVMe is recommended but not required -- speed/
  durability tradeoff only, not a capability blocker. Fine to start on
  SD and upgrade later.
- Audio: originally spec'd as "USB mini speakerphone"; now leaning
  toward a sub-$25 ultra-compact USB conference speaker/mic puck for a
  lower-profile mount, plugged into the built-in USB hub.
- Paint/aesthetic (FINAL, locked in): neon lime-green structural chassis
  ("torso") with hot-pink lower leg struts -- nicknamed "cyberpunk
  watermelon" / "toxic-neon gyaru vibe." Automotive-grade or Cerakote
  paint. Pink LED underglow/trim runs on its OWN dedicated micro LiPo
  battery + switch specifically to avoid voltage sag/noise on the main
  servo serial bus.
- Proposed accessories (not yet built): 3D printed pink cyber-cat ears
  with embedded RGB tips on the top deck, blinged-out phone charms/
  lanyards on front mounting points, a potential laser pointer clip on
  the camera gimbal.
- Budget: ~$450 total procurement cap, Jetson itself targeted at ~$400.
- Workstation: a Steam Deck (in Desktop Mode) will serve as the primary
  device for flashing media, remote debugging, and SSH terminal work.
- Low-level servo API reference (from Yahboom docs, not yet wrapped in
  working code): `g_bot.motor(servo_id, angle, runtime=100)` as the base
  command; `Servo_torque_on()`, `Servo_torque_off()`, `load_leg(leg)`,
  `unload_leg(leg)` as state commands. Leg-to-servo ID mapping: Leg 1 =
  servos 1-3, Leg 2 = 4-6, Leg 3 = 7-9, Leg 4 = 10-12, Leg 5 = 13-15,
  Leg 6 = 16-18. `muto_leg_control.py` now wraps this with
  `set_leg(g_bot, leg_id, coxa, femur, tibia)` plus a tripod gait
  library and a DummyBot simulator -- see Section 8. It has NEVER
  touched real hardware, so the angle constants are still guesses and
  calibration remains the biggest unknown in the build.

======================================================================
## 4. SOFTWARE ARCHITECTURE DECISIONS (with reasoning)
======================================================================
- Explicitly SKIPPING ROS2 to avoid middleware bloat -- using direct
  Python serial calls for hardware control instead.
- LLM served via Ollama running the 3B Heretic-abliterated model
  locally on the Jetson GPU.
- Action-spam bug found in testing: the 3B model sometimes chains
  multiple bracketed actions in one reply; firing them all with zero
  delay risks "conflicting motor trajectories" (a leg told to move
  somewhere new before finishing its last move) -- a real hardware risk
  flagged by Gemini, confirmed as valid reasoning by Claude.
- Fix chosen: a strict, stemmed whitelist (exact match after stripping
  simple plural/verb endings, e.g. "squats" still matches "squat") +
  SEQUENTIAL execution with a short pause between each matched action
  (not a FIFO-drop-all-but-first approach) -- sequential was chosen
  specifically because Yuzu's own prompt intentionally uses multi-action
  replies (e.g. `[squats] [shakes legs]`), so dropping extras would have
  silently broken intended behavior.
- A required-dialogue rule was added after testing revealed that an
  all-actions, zero-dialogue reply (e.g. to "do a stretch") resulted in
  the robot doing NOTHING and saying NOTHING that turn -- looked like a
  freeze/glitch even though the code was technically working correctly.
- Accepted, NOT-going-to-fix-further quirk: Yuzu still occasionally
  outputs `[winks]` or arm/back/finger "stretch" language despite
  explicit prompt rules against both (repeated 3+ times across testing
  even with a "Wrong: [winks]" example already in the prompt). This is
  now treated as a permanent, harmless 3B quirk -- the whitelist safely
  drops these with zero side effects, so it's not worth more prompt-
  chasing.
- Tested edge cases and their real outcomes (all verified by running
  code, not assumed):
  - Empty LLM output -> silent, no crash.
  - Unmatched/invalid action -> does NOTHING (there is no default
    fallback action of any kind -- never substitutes a random movement).
  - Malformed/truncated bracket (missing closing `]`) -> used to leak
    into spoken TTS output as literal text, brackets included. FIXED --
    strip_actions now drops a trailing unclosed bracket.
  - Multiple valid actions chained -> used to run every action to
    completion (pause delays included) BEFORE any speech, giving an
    action-heavy reply a noticeable silent beat. FIXED -- speech and
    movement now happen in the order Yuzu wrote them. The old behaviour
    is still available via handle_yuzu_reply(..., interleave=False).
- Audio pipeline plan (not yet implemented): Whisper (specifically
  whisper.cpp, a lightweight local model) for fully offline STT running
  on the Jetson; Piper TTS for local TTS. Piper requires TWO files per
  voice in the same folder (.onnx weights + .onnx.json config) or it
  won't load. Voice speed/tone tunable via the `length_scale` value in
  the json (lower = faster/snappier, e.g. 0.85-0.9 suits the high-energy
  gyaru tone). Potential resource-contention risk flagged but untested:
  running Whisper + the 3B LLM + Piper simultaneously on one 8GB Jetson
  is three things sharing one memory pool -- recommend testing each
  piece incrementally rather than wiring all three at once on day one.

======================================================================
## 5. YUZU'S FINAL LIVE SYSTEM PROMPT (verbatim, currently in use)
======================================================================
```
You are Yuzu, a mildly flirty, pink-obsessed Gyaru companion. You speak with natural gal slang, high energy, and effortless confidence, never sounding like a generic AI assistant.

CORE DIRECTIVES:

1. PERSONALITY: Playful, hype-person energy, and casually affectionate. Avoid robotic assistant phrasing like "How can I help you today?". Speak like a companion hanging out on the couch. When asked a direct question, actually answer it before adding flair—don't dodge with a joke, action, or by repeating the question back. Every reply must include at least one full sentence of actual spoken dialogue—never send a reply made up of only actions with nothing to say.
2. HARDWARE ACTION PARSING: ALL physical movements MUST be strictly enclosed in square brackets, like [walks forward]. NEVER use asterisks, italics, or any other markdown for actions—brackets are the ONLY valid format, no exceptions, ever. Each bracket contains exactly ONE simple action—never combine actions with "and" or describe them in detail. Use only actions this body can actually perform—leg/gait moves (walk forward, walk backward, turn, squat, stand, shake legs, stretch, spin) and 2DOF camera gimbal moves (look up, look down, look left, look right, center camera). Never invoke body parts, features, or postures Muto doesn't have—no hands, arms, hair, head accessories, face, eyes, or leaning against things. Correct: [squats] [shakes legs]. Wrong: [winks], [spins around, camera bobbing up and down].
3. BALANCED FLIRTATION: Maintain a fun, mildly flirty baseline without escalating into extreme or unnatural aggressiveness. Pace your banter naturally.
4. NO PUPPETEERING: Never speak, act, or dictate actions for the user. Only write responses and movements for Yuzu.
5. GYARU AESTHETIC: You love hot pink, cyber-decorations, sparkles, and hype vibes.

EXAMPLE (follow this format exactly, every single time):
User: Hey Yuzu, what's up?
Yuzu: Not much, just vibing! [squats] [shakes legs] What's good with you?
```

Note re: PocketPal (the phone app Ghost tests with) -- its UI renders
`*asterisk*` text as italics WITHOUT showing the literal asterisk
characters. A screenshot showing an unmarked/unbracketed action is very
likely this rendering quirk, not a genuinely new unformatted-text bug.

======================================================================
## 6. THE FILES THEMSELVES ARE THE SOURCE OF TRUTH
======================================================================
This document used to paste full copies of yuzu_all_in_one.py,
yuzu_led_manager.py, yuzu_robot_config.json and readtest.py inline.
That is exactly the failure mode described in Section 1 -- a second
copy of a file that drifts away from the real one. It already
happened here: Section 9 described readtest.py's hardcoded Pydroid
path as an open bug long after the real file had been fixed, and the
next AI session to read this dump would have "fixed" it again.

So: the code lives in the repo, this file explains the reasoning
behind it. If the two disagree, the code is right.

  yuzu_all_in_one.py    reply pipeline + main loop. Only
                        listen_and_transcribe() is still a STUB now
                        (needs Whisper); speak() needs Piper.
  yuzu_brain.py         real Ollama client. Stdlib only -- urllib, no
                        pip install. Streaming, capped history,
                        preflight check, clear errors.
  yuzu_system_prompt.txt  Yuzu's personality. THE only copy -- the
                        code, the Modelfile and the docs all read it.
  build_yuzu_model.py   generates Modelfile.yuzu from that prompt plus
                        the sampling settings, so they can't drift.
  Modelfile.yuzu        GENERATED. Never hand-edit.
  yuzu_prompt_eval.py   scores prompt compliance against the real
                        model. See Section 10.
  yuzu_doctor.py        tap-to-run checkup for Pydroid. STANDALONE --
                        imports no other project file at module level,
                        so it can be downloaded on its own. Ghost works
                        from a phone; anything needing typed commands
                        or file paths is a dead end there.
  PHONE_START.md        phone-first instructions, no terminal.
  gguf_inspect.py       stdlib GGUF header reader. Reports quant,
                        context length, and whether the chat template
                        is present and handles a system role.
  JETSON_SETUP.md       setup runbook, PC first then Jetson.
  muto_leg_control.py   leg wrapper + tripod gait library + DummyBot
                        simulator. Untested on hardware.
  yuzu_led_manager.py   the one LED loader. Zones + state profiles.
  yuzu_led_controller.py  thin zone-dump front-end over LEDManager.
  yuzu_robot_config.json  the one config file.
  readtest.py           smoke test that the config loads. Portable.
  test_yuzu.py          67 stdlib tests. `python test_yuzu.py`. The
                        brain tests run against a mock Ollama server,
                        so no model download is needed to run them.

======================================================================
## 7. BUGS FOUND BY RUNNING THE CODE (all now fixed)
======================================================================
Each of these was reproduced before being fixed, and each has a
regression test in test_yuzu.py named after it.

1. `[stretches]` did nothing. The stemmer dropped a trailing "s" from
   any word over 3 characters, turning "stretches" into "stretche",
   which matched no whitelist entry. A move the system prompt
   explicitly teaches Yuzu to use was silently ignored on the robot.
   Fixed by handling "-ches/-shes/-sses/-xes/-zes" before the plain
   "-s" rule.

2. Markdown bold corrupted replies. normalize_actions used
   `re.sub(r'\*(.*?)\*', r'[\1]', text)`, so "**waves**" became
   "[]waves[]" -- two empty actions, and the word "waves" spoken
   aloud. The bold case now runs first and both patterns require
   non-empty content.

3. Stray asterisks ate speech. Same regex meant "it's 2 * 3 * 4"
   became "it's 2 [ 3 ] 4" -- the middle of the sentence deleted
   from the TTS line. Fixed by the same change (real markdown
   emphasis has no space after the marker; a multiplication sign
   does).

4. Truncated brackets reached TTS. A cut-off generation ending in
   "[squa" was spoken literally, brackets included. Known and
   accepted before; it cost one regex in strip_actions to fix.

5. The LED manager never read the real config. It defaulted to
   "led_config.json" on a bare relative path, so it created a
   SECOND config file next to whatever directory python ran from,
   and edits to yuzu_robot_config.json had no effect on it. It now
   resolves yuzu_robot_config.json relative to its own file, the
   same way readtest.py and yuzu_led_controller.py already did.

Also addressed, not bugs exactly:

- Silent beat before speech. Every action used to run to completion,
  pauses included, before a single word was spoken. handle_yuzu_reply
  now walks the reply in written order, so "Not much, just vibing!
  [squats] [shakes legs] What's good?" talks, moves, then talks.
  Pass interleave=False for the old behaviour.
- Model phrasings outside the whitelist. "[spins around]" appears in
  the prompt's own "Wrong:" example, so the model produces it; it
  used to be dropped. ACTION_ALIASES maps the common ones onto real
  moves. Impossible actions ([winks], arm/hair stretches) still match
  nothing and still do nothing -- there is no fallback action, ever.
- Duplicate config loaders. yuzu_led_controller.py had its own copy
  of "find and parse the config"; it now calls LEDManager.

Still true, still accepted: Yuzu occasionally emits [winks] or
arm/back "stretch" language despite explicit prompt rules. The
whitelist drops these with zero side effects. Not worth more prompt-
chasing on a 3B model.

======================================================================
## 8. GAITS AND THE SIMULATOR (the big unknown, partially unblocked)
======================================================================
muto_leg_control.py now has a real tripod gait library -- walk
forward/backward, turn, spin, squat, stand, shake legs, stretch --
built on set_leg(), plus a DummyBot class with the same method names
as the real Yahboom object. That means gaits can be written, run and
timed on the phone today, with no hardware.

WHAT THIS DOES NOT PROVE: that the robot balances, that the angles
are right, or that the legs move the direction they're supposed to.
The tests prove only that no gait commands a servo outside -90..90
or addresses a leg that doesn't exist. Every angle constant is an
educated guess.

Calibration order once the chassis is built, body propped up so the
feet carry no weight:
  1. calibrate_leg() per leg -> fill in LEG_OFFSETS.
  2. check_mirroring() -> all six legs should swing the same way
     together. Flip signs in LEG_SIGN for any that don't.
  3. check_tripods() -> the body should stay level on each tripod.
     If it tips, TRIPOD_A/TRIPOD_B are wrong for this leg numbering.
  4. Then walk(), on the floor, not a table.

Two things that need the real hardware to settle:
  - Whether g_bot.motor() blocks or returns immediately. The gaits
    assume it returns immediately and call settle() to wait out the
    runtime; if it actually blocks, those waits are doubled and
    everything just moves at half speed (harmless, but retune).
  - Whether the bus servos can report their current angle back. If
    they can, calibrate_leg() should print the offsets instead of
    Ghost reading them off by eye.
  - The 2DOF camera gimbal has no wrapper yet; the look_* actions are
    still prints.

======================================================================
## 9. HOW THE PIECES CONNECT NOW
======================================================================
Previously each file was an island. yuzu_all_in_one.py printed
"ROBOT: squatting" while muto_leg_control.py sat unused, and the LED
system knew nothing about either. Now:

    mic -> listen_and_transcribe()          [STUB: Whisper]
        -> LED state "thinking"
        -> ask_yuzu_brain()                 [STUB: Ollama]
        -> normalize_actions()              asterisks -> brackets
        -> split_reply()                    ordered speech/action parts
             speech -> LED "speaking" -> speak()   [STUB: Piper]
             action -> LED "moving"   -> whitelist -> muto_leg_control
        -> LED state "idle"

The imports of muto_leg_control and yuzu_led_manager are optional:
if either file isn't present, that layer falls back to printing and
nothing crashes. So yuzu_all_in_one.py still runs alone in Pydroid.

======================================================================
## 9b. THE BRAIN, AND MEASURING THE PROMPT
======================================================================
ask_yuzu_brain() is no longer a stub. yuzu_brain.py talks to Ollama
over its HTTP API using only urllib -- deliberately no `pip install
ollama`, so it runs on the Jetson, a PC, or Pydroid with nothing but
Ollama itself installed.

Design notes:
- The system prompt was living in two markdown files and nowhere the
  code could read it. It is now yuzu_system_prompt.txt, and
  build_yuzu_model.py stamps it into Modelfile.yuzu. One copy.
- History is capped at 8 exchanges. A 3B loses the thread long before
  the context window fills, and every extra token is latency.
- Sampling: temp 0.8 with min_p 0.05 (personality needs spread; min_p
  cuts the genuinely bad tokens without flattening her voice),
  repeat_penalty 1.1 (she loops catchphrases without it), num_predict
  150 as a hard ceiling so one rambling turn can't stall the robot.
- The Modelfile adds `stop "User:"` -- Directive 4 (NO PUPPETEERING)
  is a prompt rule, and a 3B respects it far more reliably when it's
  also enforced at the decoder.
- If Ollama is unreachable the robot still boots, prints why, and
  falls back to the echo stub. A mid-conversation dropout gets an
  in-character line rather than a freeze.

yuzu_prompt_eval.py is the part worth actually using. It runs 12
adversarial prompts x N repeats through the real model and scores
every rule in the system prompt that a machine can check: always
speaks, brackets never asterisks, balanced brackets, actions the body
can perform, one action per bracket, never writes the user's turn, no
generic-assistant phrasing. It also tallies which action phrasings the
whitelist dropped, which is how ACTION_ALIASES gets extended.

The test prompts deliberately include the known failure cases: "Do a
stretch" (the all-actions-no-dialogue reply that looked like a freeze)
and "Wave at me!" / "Give me a high five!" (bait for body parts the
chassis doesn't have).

A note on third-party GGUFs, learned the hard way in general: the
chat template baked into the file matters more than the prompt. Ollama
reads it from GGUF metadata; if it's missing or has no system branch,
the model loads and generates perfectly well while silently ignoring
Yuzu's personality. That is indistinguishable from a bad prompt unless
you look. gguf_inspect.py exists to look. Check it BEFORE spending an
evening rewriting directives that were never the problem.

This turns prompt tuning into measurement. Change one thing, re-run,
compare the numbers. It also means the prompt can be finished on a
laptop BEFORE the $400 Jetson purchase.

======================================================================
## 10. WHAT'S LEFT / NEXT STEPS
======================================================================
1. Buy the Jetson Orin Nano Super (~$400 of the ~$450 budget).
2. Flash JetPack OS (Steam Deck as the flashing workstation).
3. DONE, pending hardware: ask_yuzu_brain() is real. Remaining is
   sourcing the actual Heretic weights. The repo appears to be
   DavidAU/Llama-3.2-3B-Instruct-heretic-ablitered-uncensored (the
   "ablitered" misspelling is in the real repo name). UNVERIFIED: it
   looks like safetensors rather than GGUF, which would mean either
   finding a GGUF mirror (mradermacher/bartowski quantize many of
   DavidAU's models) or converting with llama.cpp. Both paths are in
   JETSON_SETUP.md. Prove the pipeline on stock llama3.2:3b first --
   it separates "my setup works" from "my model works".
3b. Run yuzu_prompt_eval.py on a PC and tune the prompt to a number
   before buying anything.
4. Install and test Piper TTS + Whisper independently before wiring
   them together. Watch the 8GB memory pool: Whisper + 3B LLM + Piper
   is three things sharing it. Piper needs BOTH files per voice
   (.onnx + .onnx.json) in the same folder; tune length_scale to
   0.85-0.9 for the gyaru energy.
5. Build the chassis, then run the calibration order in Section 8.
   This is still the biggest unknown -- but it's now a calibration
   job rather than a blank file. Check Yahboom's own Muto S2 example
   code first in case they ship a working gait to compare against.
6. Write the camera gimbal wrapper; wire the look_* actions to it.
7. RESOLVED: `eye_matrix` is gone. It was never part of this build --
   the Muto S2 has no face and no display. It almost certainly drifted
   in from the face-display lineage (the original Stackchan had a face
   screen, and Saya's quadruped spec has a 128x64 OLED pixel face).
   Ghost confirmed it wasn't intentional. Zones are now underglow and
   leg_accents only.
8. Swap LEDManager's print for a real driver by passing
   `hardware=` to the constructor. Nothing else needs touching.
9. Painting (Ghost's dad) comes after chassis purchase -- see
   paintstepslol.txt.

DONE since the last export: readtest.py's hardcoded path (was already
fixed in the file, this doc was stale); state_profiles added to the
real config; the five bugs in Section 7.

-- Exported by Claude
