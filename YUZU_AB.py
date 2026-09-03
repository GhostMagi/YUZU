"""
YUZU A/B -- run two personas against the real model and compare them.

    python YUZU_AB.py                 # the two arms set below
    python YUZU_AB.py yuzu4 yuzu5     # any other pair
    python YUZU_AB.py yuzu2 yuzu4 --runs 3

No arguments needed. It runs the same 12 prompts through each arm, one
pass each, scores both with the SAME parser the robot uses, and prints
one table instead of two you have to hold side by side in your head.

WHY THIS EXISTS AS ITS OWN SCRIPT
Every A/B in this repo so far has been two separate yuzu_prompt_eval
runs, hand-transcribed into a table afterwards. That is where the
mistakes live: the header printed the persona NAME and not the KEY, so
two runs of "persona: Yuzu" were unattributable, and the comparison had
to be reconstructed from memory. Here both arms are labelled by key,
scored in one process, and printed together.

AND WHY IT SHOUTS ABOUT SAMPLE SIZE
The yuzu2-vs-yuzu3 round looked like a result and wasn't. Every
difference in it was ONE reply, and at 12 replies per arm one reply is
8.3 percentage points. This prints that number next to the table so a
coin flip is harder to mistake for a finding.
"""

import argparse
import sys

import yuzu_personas
from yuzu_brain import BrainError, YuzuBrain
from yuzu_prompt_eval import (CHECKS, TEST_PROMPTS, evaluate,
                              prompts_for)

# The pair to run when no arguments are given. Move these as the
# lineage advances -- the promotion rule in CLAUDE.md says the measured
# winner becomes the base, so the left arm should normally be
# yuzu_personas.LIVE_PERSONA and the right arm whatever is being tried
# against it.
ARMS = (yuzu_personas.LIVE_PERSONA, "yuzu5")

# moves_at_all is the honest robot-facing number and everything else is
# context. actions_runnable is an all() and no_asterisks measures a
# model prior that normalize_actions rescues anyway -- both look worse
# than the robot behaves. Printed, but never the headline.
HEADLINE = "moves_at_all"


def run_arm(key, model, runs, timeout, verbose):
    """Score one persona. Returns (results, prompt_chars) or None."""
    try:
        brain = YuzuBrain(model=model, persona=key, timeout=timeout)
    except BrainError as exc:
        print(f"\n{exc}\n")
        return None, 0
    print(f"\n{'=' * 66}")
    print(f"ARM: {key}  ({brain.persona.name}, {brain.persona.archetype})")
    print(f"{'=' * 66}")
    print(f"  prompt {len(brain.system_prompt)} chars   "
          f"temp {brain.options['temperature']}   "
          f"num_predict {brain.options['num_predict']}")
    print(f"  {len(TEST_PROMPTS)} prompts x {runs} = "
          f"{len(TEST_PROMPTS) * runs} replies...")
    # Each arm is addressed by its own persona's name, so an arm
    # never gets scored on a turn that calls it something else.
    results = evaluate(brain, prompts_for(brain.persona), runs, verbose)
    return results, len(brain.system_prompt)


def compare(left_key, left, right_key, right, chars):
    total = min(left["total"], right["total"])
    if not total:
        print("\nNothing was scored in one of the arms.")
        return

    # One reply is worth this many points. It is the whole reason the
    # asterisk hypothesis got closed instead of chased.
    point = 100.0 / total

    print(f"\n{'=' * 66}")
    print(f"{left_key} vs {right_key}   --   {total} replies each")
    print(f"{'=' * 66}")
    print(f"{'check':<18} {left_key:>9} {right_key:>9} {'diff':>8}   counts")
    print("-" * 66)

    ordered = sorted(CHECKS, key=lambda c: c.name != HEADLINE)
    for check in ordered:
        a = left["passes"][check.name]
        b = right["passes"][check.name]
        pa, pb = 100.0 * a / left["total"], 100.0 * b / right["total"]
        mark = "  <-- " if check.name == HEADLINE else ""
        print(f"{check.name:<18} {pa:8.1f}% {pb:8.1f}% {pb - pa:+7.1f}   "
              f"{a}/{left['total']} vs {b}/{right['total']}{mark}")

    for key, results in ((left_key, left), (right_key, right)):
        lengths = results["lengths"]
        if lengths:
            print(f"\n{key:<10} prompt {chars[key]} chars, "
                  f"spoken {sum(lengths) / len(lengths):.0f} words avg")

    print(f"\n{'-' * 66}")
    print(f"ONE REPLY IS {point:.1f} POINTS at this sample size.")
    biggest = max(
        abs(100.0 * right["passes"][c.name] / right["total"]
            - 100.0 * left["passes"][c.name] / left["total"])
        for c in CHECKS)
    if biggest <= point * 1.5:
        print("Every difference above is within one or two replies. That is a")
        print("coin flip, not a result. Re-run with --runs 3 before believing")
        print("any of it -- or accept that the two arms are the same.")
    else:
        headline = (100.0 * right["passes"][HEADLINE] / right["total"]
                    - 100.0 * left["passes"][HEADLINE] / left["total"])
        if abs(headline) <= point * 1.5:
            print(f"{HEADLINE} moved less than two replies. The arms are level")
            print("on the number that matters, whatever else shifted.")
        else:
            winner = right_key if headline > 0 else left_key
            print(f"{HEADLINE} favours {winner} by {abs(headline):.1f} points "
                  f"({abs(headline) / point:.1f} replies).")
            print("Confirm with --runs 3 before promoting it. Then move")
            print("LIVE_PERSONA in yuzu_personas.py and say so in CLAUDE.md.")

    dropped = right["dropped"]
    if dropped:
        print(f"\nactions {right_key} wrote that the whitelist dropped:")
        for action, count in dropped.most_common(6):
            print(f"  {count:>3}x  [{action}]")


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("arms", nargs="*", default=None,
                        help=f"two persona keys (default: {' '.join(ARMS)})")
    parser.add_argument("--model", default=None)
    parser.add_argument("--runs", type=int, default=1,
                        help="passes per prompt per arm (default 1 = 12 "
                             "replies each; --runs 3 to confirm a result)")
    parser.add_argument("--timeout", type=int, default=None)
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    arms = [a.lower() for a in args.arms] if args.arms else list(ARMS)
    if len(arms) != 2:
        print(f"Give exactly two persona keys, or none at all for "
              f"{ARMS[0]} vs {ARMS[1]}.")
        return 1
    for key in arms:
        if key not in yuzu_personas.available():
            print(f"\nNo persona '{key}'.\n  Available: "
                  f"{', '.join(yuzu_personas.available())}\n")
            return 1

    print(f"A/B: {arms[0]} vs {arms[1]}")
    print(f"Both arms judged cold -- history is reset before every prompt, "
          f"so\nthis measures each prompt standing on its own.")

    scored, chars = {}, {}
    for key in arms:
        results, size = run_arm(key, args.model, args.runs,
                                args.timeout, args.verbose)
        if results is None:
            return 1
        scored[key], chars[key] = results, size

    compare(arms[0], scored[arms[0]], arms[1], scored[arms[1]], chars)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
