# Yuzu-Spider-V1 — working notes for Claude

## Conventions

- **Work on `main`.** No feature branches unless Ghost asks.
- **Whenever Yuzu's prompt changes, paste the full composed prompt into
  the chat as a copy-paste block**, without being asked. Ghost tests in
  PocketPal on a phone, so a file path or a command is useless to him —
  he needs the text itself. Get it with:
      python yuzu_personas.py --show yuzu2
- **Ghost works from a phone** (Z Flip 6, Pydroid + PocketPal). Anything
  requiring typed commands, file paths, or arguments is a dead end.
  Prefer: text he can paste, or a no-argument script he can tap Run on.
- Run `python test_yuzu.py` before committing. 134 tests, ~9 seconds.

## Prompt work

`personas/yuzu.persona` is the ORIGINAL, extensively tested by Ghost.
Do not edit it — a test asserts it stays byte-identical to
`personas/_golden_yuzu_v1.txt`. Iterate on `personas/yuzu2.persona`.

Ghost's method is A/B testing in PocketPal and sending screenshots.
It works. Score them against the real parser rather than eyeballing —
`yuzu_all_in_one.lookup_actions()` is the ground truth for whether a
bracketed action would actually move the robot.

Measured so far: v1 20% action hit rate → v2 78–83%.

`personas/coco.persona` (kuudere) is built on v2's structure and carries
its fixes, but has **zero live rounds** — that's an argument, not a
number. Don't quote a hit rate for her until Ghost has A/B'd one.
Her predicted failure modes and what to watch for are in
PERSONA_SWITCHING.md.

Watch for: PocketPal renders `*asterisks*` as italics WITHOUT showing
the markers, so an italicised word in a screenshot is an asterisk
action, not plain text. Ask before scoring if it's ambiguous.
