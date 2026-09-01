# Claude's Memory Export: The Robot Persona Project

This is everything Claude currently has saved in long-term memory about
this project — from the very first Stackchan idea through Pixie, Saya,
Yuno, Saki, Coco, and now Yuzu-Spider-V1. Exported as a plain note so
it survives independently of any one chat.

---

- wants to build an M5Stack Stackchan (robot with face display) using the M5Stack Module LLM Kit (AX630C NPU)
- goal is to run a 1B Llama model on this setup fully offline/locally
- wants the build to be slim and portable, not tethered to Ethernet
- has spare 128GB microSD cards on hand to use for the build
- finds Llama's tone more charming/personal for their scene-girl persona; feels Qwen reads more like a generic assistant
- revised the build to skip the Module 13.2 battery and LLM Mate, powering Stackchan Core + Module LLM off an existing external portable charger instead, plus a $7 tabletop chargepad for topping off at home
- final model decision: Llama-3.2-1B-Instruct, prioritizing personality/charm over raw capability, as long as it can handle single simple factual questions
- settled back on the name Pixie for the persona (had briefly tried Moxi)
- got Pixie's system prompt running on the actual build and is thrilled with how she turned out
- pivoted the persona from scene-kid/sassy energy to casual and mildly flirty, since the sass was causing her to dodge real questions with jokes instead of answering
- considers the Pixie prompt finalized after extensive testing — confidently-wrong local specifics are an accepted known limitation
- decided against the M5GO Battery Bottom3 — final hardware plan is StackChan Core (ESP32-S3), M5Stack Module LLM AX630C kit, and a 20000mAh portable battery pack/charger for power
- separately considering an AI Pyramid Computing Box Pro (8GB, AX8850) as a possible future addition
- renamed Pixie to Saya, a Highschool of the Dead reference
- considered an NVIDIA Jetson Orin Nano (Super) as a bigger "sister" robot running Llama 3.2-3B
- built a Yandere variant named Yuno (Mirai Nikki reference); concluded Saya (Tsundere) wins as the final persona, Yuno too intense for daily use
- built a third persona, Yuzu, a Gyaru character
- pivoted plans: Saya (tsundere) set aside in drafts; Yuzu (gyaru) became the primary persona
- wants Yuzu to be flirty, explicitly not sexual/explicit content
- finalized Yuzu's prompt with real gyaru slang plus a short-reply/answer-first rule
- long-term goal: a humanoid body for Yuzu eventually, ideally white with gold trim
- also built Himedere persona Saki (v1.2) and Kuudere persona Coco on the 1B setup, exploring which speech style survives the 1-2 sentence constraint best
- believes Llama 3.2 1B has roughly a 6-8 distinct-rule hardcap for reliably following a system prompt
- had college-level coursework in 4th grade, now in early 30s
- Yuzu is now live on an actual Yahboom Muto S2 hexapod robot body, with working TTS and physical movement actions
- final hardware/model decision: upgrading Yuzu's brain to a Jetson Orin Nano (Super Dev Kit, 8GB, 67 TOPS) running Llama-3.2-3B-Instruct-Heretic-Abliterated-Uncensored via Ollama
- has never used Python before this project; since then independently wrote and ran a working regex-based bracket-action parser on their phone (Z Flip 6, via Pydroid 3)
- also uses Google Gemini alongside Claude, trading versioned "handoff notes" text files between the two AIs
- confirmed hardware: 256GB NVMe SSD (or currently: both a 256GB and 128GB microSD card on hand), USB audio for mic+TTS, 18x 35KG serial bus servos, direct Python serial calls instead of ROS2
- finalized Yuzu's paint scheme: neon lime-green chassis with hot-pink lower leg struts ("cyberpunk watermelon"), pink LED underglow on its own dedicated micro LiPo battery
- has the real low-level servo API reference: g_bot.motor(servo_id, angle, runtime=100), torque/load-leg commands, 6-leg/18-servo ID mapping
- revisiting Saya as a separate physical quadruped build: Sesame Robot framework, ESP32, 8x MG90S servos, 128x64 OLED reactive pixel face, Kuudere personality
- Yuzu's spec now includes proposed accessories: 3D printed pink cyber-cat ears with RGB tips, phone charms/lanyards, a potential laser pointer clip on the camera gimbal
- planned audio pipeline: Whisper (STT) + Piper (TTS), both fully offline; considering a sub-$25 USB conference speaker/mic puck
- official project designation: "Yuzu-Spider-V1"; budget cap ~$450 total, Jetson targeted ~$400
- Steam Deck (Desktop Mode) will serve as the primary flashing/debugging/SSH workstation
- Yuzu's LED setup uses 3 zones (underglow, eye_matrix, leg_accents) — eye_matrix's cyan color is still an unconfirmed addition
- known open item: readtest.py hardcodes a Pydroid-specific file path that needs to be made portable before running on the Jetson

## Yuzu's Final Live System Prompt (verbatim)

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

## Pipeline Architecture (yuzu_reply_pipeline.py / yuzu_all_in_one.py)

Normalize stray asterisks to brackets → extract bracketed actions in
order → check each against a strict stemmed whitelist → run matched
actions sequentially with a pause between each → strip all bracket
text → send remaining dialogue to TTS.

Known accepted quirk: Yuzu still occasionally uses [winks] or arm/back
"stretch" language despite explicit rules against it. Silently dropped
by the whitelist with zero side effects — not worth more prompt-chasing.
