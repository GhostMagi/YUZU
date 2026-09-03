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
# The pair to run when no arguments are given.
#
# Both slots point at LIVE_PERSONA on purpose: yuzu5 and yuzu6 are both
# CLOSED and nothing is queued against yuzu4, so a bare `YUZU_AB.py`
# would otherwise quietly re-run a settled round and burn 15 minutes.
# Running a prompt against itself is the one genuinely useful thing to
# do with no candidate -- it measures the noise floor, which is what
# this round turned out to need. Put a real key in the right slot when
# there is something to test.
ARMS = (yuzu_personas.LIVE_PERSONA, yuzu_personas.LIVE_PERSONA)

# moves_at_all is the honest robot-facing number and everything else is
# context. actions_runnable is an all() and no_asterisks measures a
# model prior that normalize_actions rescues anyway -- both look worse
# than the robot behaves. Printed, but never the headline.
HEADLINE = "moves_at_all"

# The noise floor, MEASURED rather than assumed.
#
# yuzu4 was run twice against different challengers on the same laptop,
# same model, same settings, same 12 prompts. It scored 9/12 the first
# time and 12/12 the second on moves_at_all. Nothing about the prompt
# changed between those runs. So a SINGLE unchanged prompt swings three
# replies at this sample size, and any gap at or below that is not
# evidence of anything.
#
# This file used to declare a winner at 1.5 replies, which is how two
# rounds got read as results before anyone thought to compare a prompt
# against itself. If you widen the sample, lower this -- it is in
# replies, not points, precisely so it scales with --runs.
NOISE_FLOOR_REPLIES = 3

# Words spoken per reply. Worth watching BECAUSE it barely moves:
# yuzu4 came back 24w on both of its runs while its headline swung
# three replies. A metric that stable can resolve differences the
# headline cannot, and generation length costs far more time on the
# robot than prompt length does -- a shorter prompt that produces
# longer replies is a latency LOSS wearing a latency win's clothes.
LENGTH_WARN_WORDS = 4


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

    spoken = {}
    for key, results in ((left_key, left), (right_key, right)):
        lengths = results["lengths"]
        if lengths:
            spoken[key] = sum(lengths) / len(lengths)
            print(f"\n{key:<10} prompt {chars[key]} chars, "
                  f"spoken {spoken[key]:.0f} words avg")

    # Spoken length gets its own verdict. It is the low-variance metric
    # here, and it is the one that decides whether a prompt trim is
    # actually a latency win: characters saved once per turn against
    # words generated every turn, and generation is the expensive half.
    if len(spoken) == 2:
        grew = spoken[right_key] - spoken[left_key]
        if abs(grew) >= LENGTH_WARN_WORDS:
            longer, shorter = ((right_key, left_key) if grew > 0
                               else (left_key, right_key))
            print(f"\n!! {longer} speaks {abs(grew):.0f} words more per reply "
                  f"than {shorter}.")
            if chars.get(longer, 0) < chars.get(shorter, 0):
                print(f"   {longer} has the SHORTER prompt and the LONGER "
                      f"replies. That is not a")
                print("   latency win: prompt characters are paid once per "
                      "turn and prefilled,")
                print("   generated words are paid one at a time. Weigh it "
                      "before promoting.")

    print(f"\n{'-' * 66}")
    print(f"ONE REPLY IS {point:.1f} POINTS at this sample size.")
    print(f"MEASURED NOISE FLOOR: {NOISE_FLOOR_REPLIES} replies "
          f"({NOISE_FLOOR_REPLIES * point:.1f} points). yuzu4 scored 9/12 "
          f"then 12/12\non two runs of the SAME prompt -- so a gap this "
          f"size proves nothing.")
    floor = point * NOISE_FLOOR_REPLIES
    biggest = max(
        abs(100.0 * right["passes"][c.name] / right["total"]
            - 100.0 * left["passes"][c.name] / left["total"])
        for c in CHECKS)
    if biggest <= floor:
        print("Every difference above is inside the noise floor. That is not")
        print("a result. --runs 3 triples the sample and cuts one reply to")
        print(f"{point / 3:.1f} points -- or accept that the two arms are the same.")
    else:
        headline = (100.0 * right["passes"][HEADLINE] / right["total"]
                    - 100.0 * left["passes"][HEADLINE] / left["total"])
        if abs(headline) <= floor:
            print(f"{HEADLINE} moved less than the noise floor. The arms are")
            print("level on the number that matters, whatever else shifted.")
        else:
            winner = right_key if headline > 0 else left_key
            print(f"{HEADLINE} favours {winner} by {abs(headline):.1f} points "
                  f"({abs(headline) / point:.1f} replies).")
            # Only a PROMOTION needs confirming. When the arm that
            # already boots wins, the outcome is "change nothing", and
            # telling someone to spend 72 more replies confirming the
            # status quo is how a harness stops being run at all.
            if winner == yuzu_personas.LIVE_PERSONA:
                print(f"{winner} is already LIVE_PERSONA, so the outcome is")
                print("CHANGE NOTHING -- no confirmation run needed. Record")
                print(f"why {right_key} lost in CLAUDE.md and move on.")
            else:
                print("Confirm with --runs 3 before promoting it. Then move")
                print("LIVE_PERSONA in yuzu_personas.py and say so in CLAUDE.md.")

    # BOTH arms. Printing only the right one made the yuzu4-vs-yuzu5
    # round half-blind: yuzu5's dropped list named the mechanism
    # ([giggles], [pauses], [shrugs]) but there was nothing to compare
    # it against, so "is that worse than normal?" needed another run.
    # A comparison tool that shows one side is a comparison tool with a
    # blind spot, which is the failure mode this whole file exists for.
    for key, results in ((left_key, left), (right_key, right)):
        dropped = results["dropped"]
        total_dropped = sum(dropped.values())
        print(f"\n{key}: {total_dropped} action(s) the whitelist dropped"
              f"{' -- none' if not dropped else ':'}")
        for action, count in dropped.most_common(6):
            print(f"  {count:>3}x  [{action}]")
    print("\nVocalizations ([giggles], [laughs]) and invented moves are the")
    print("two categories here. Both fail safe -- speech survives -- but a")
    print("rising count means the prompt stopped holding them back.")


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
