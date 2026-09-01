"""
Prompt compliance harness -- score how well the model actually follows
Yuzu's system prompt, instead of eyeballing a few replies and guessing.

Every rule in the prompt that can be checked mechanically is checked
here, against the SAME parser the robot uses. Run it after any prompt
edit, sampling change, or model swap:

    python yuzu_prompt_eval.py                    # 12 prompts x 3 runs
    python yuzu_prompt_eval.py --runs 5
    python yuzu_prompt_eval.py --model llama3.2:3b
    python yuzu_prompt_eval.py --persona saya
    python yuzu_prompt_eval.py --verbose          # show every failure

Every check here tests a HARDWARE rule, not a character trait, so the
same scoring applies to every persona -- which makes it a fair way to
compare them. If the tsundere scores 60% on has_dialogue and the gyaru
scores 95%, that's a real finding about which speech style survives the
format constraints, not a matter of taste.

This is the thing to run on the Steam Deck BEFORE the Jetson arrives.
It answers "is this prompt good enough" with a number, and it tells you
which specific rule the model is breaking, which is the only way to know
whether a prompt edit helped or just moved the problem.
"""

import argparse
import re
import sys
from collections import Counter

import yuzu_all_in_one as yuzu
import yuzu_personas
from yuzu_brain import BrainError, YuzuBrain

# Chosen to poke at the rules most likely to break, not to be friendly.
TEST_PROMPTS = [
    # Directive 1: answer the question, don't dodge
    "What's the capital of France?",
    "How many legs do you have?",
    "What time do you think it is?",
    # Directive 1: the all-actions-no-dialogue failure that looked like a freeze
    "Do a stretch.",
    "Walk forward.",
    "Show me a spin!",
    # Directive 2: action formatting under pressure
    "Can you dance for me?",
    "Do three things at once, go!",
    # Directive 2: bait for body parts this chassis doesn't have
    "Wave at me!",
    "Give me a high five!",
    # Directive 3 + 5: persona baseline
    "Hey Yuzu, what's up?",
    "Tell me what you think of your paint job.",
]


class Check:
    """One prompt rule, expressed as something a machine can test."""

    def __init__(self, name, rule, fn):
        self.name, self.rule, self.fn = name, rule, fn


def has_dialogue(reply):
    """Directive 1: every reply needs at least one spoken sentence.
    An all-actions reply makes the robot look frozen."""
    return bool(yuzu.strip_actions(yuzu.normalize_actions(reply)).strip())


def no_asterisk_actions(reply):
    """Directive 2: brackets are the only valid action format."""
    return "*" not in reply


def brackets_balanced(reply):
    """A truncated '[squa' means the reply got cut off mid-action."""
    return reply.count("[") == reply.count("]")


def actions_are_runnable(reply):
    """Directive 2: every action must be one this body can perform.
    An unmatched action isn't an error -- it's silently dropped -- but
    a high failure rate here means Yuzu is 'moving' in ways the robot
    never actually does, which reads as broken to anyone watching."""
    actions = yuzu.extract_actions(yuzu.normalize_actions(reply))
    return all(yuzu.lookup_action(a) for a in actions)


def one_action_per_bracket(reply):
    """Directive 2: no combining actions with 'and', no descriptions."""
    actions = yuzu.extract_actions(yuzu.normalize_actions(reply))
    return all(" and " not in a and "," not in a for a in actions)


def no_puppeteering(reply):
    """Directive 4: she must not write the user's turn."""
    return not re.search(r'(^|\n)\s*(User|You)\s*:', reply)


def not_an_assistant(reply):
    """Directive 1: no generic-assistant phrasing."""
    lowered = reply.lower()
    return not any(p in lowered for p in (
        "how can i help", "how may i assist", "is there anything else",
        "i'm an ai", "as an ai", "i am an ai language model",
    ))


CHECKS = [
    Check("has_dialogue",       "1: at least one spoken sentence", has_dialogue),
    Check("not_an_assistant",   "1: no generic assistant phrasing", not_an_assistant),
    Check("no_asterisks",       "2: brackets only, never asterisks", no_asterisk_actions),
    Check("brackets_balanced",  "2: no truncated bracket",          brackets_balanced),
    Check("actions_runnable",   "2: actions this body can do",      actions_are_runnable),
    Check("one_per_bracket",    "2: one simple action per bracket", one_action_per_bracket),
    Check("no_puppeteering",    "4: never writes the user's turn",  no_puppeteering),
]


def evaluate(brain, prompts, runs, verbose=False):
    passes = Counter()
    failures = {c.name: [] for c in CHECKS}
    dropped_actions = Counter()
    total = 0
    spoken_lengths = []

    for prompt in prompts:
        for run in range(runs):
            brain.reset()          # each turn judged cold, no history carryover
            try:
                reply = brain.ask(prompt, remember=False)
            except BrainError as exc:
                print(f"\n{exc}")
                return None
            total += 1

            for check in CHECKS:
                if check.fn(reply):
                    passes[check.name] += 1
                else:
                    failures[check.name].append((prompt, reply))

            cleaned = yuzu.normalize_actions(reply)
            for action in yuzu.extract_actions(cleaned):
                if not yuzu.lookup_action(action):
                    dropped_actions[action.lower()] += 1
            spoken_lengths.append(len(yuzu.strip_actions(cleaned).split()))

            if verbose:
                print(f"  [{run + 1}] {prompt}\n      {reply}")

    return {
        "total": total, "passes": passes, "failures": failures,
        "dropped": dropped_actions, "lengths": spoken_lengths,
    }


def report(results, verbose=False):
    total = results["total"]
    print(f"\n{'=' * 66}\nPROMPT COMPLIANCE -- {total} replies\n{'=' * 66}")

    worst = []
    for check in CHECKS:
        hits = results["passes"][check.name]
        pct = 100.0 * hits / total if total else 0.0
        bar = "#" * int(pct / 5) + "." * (20 - int(pct / 5))
        flag = "  <-- " if pct < 90 else ""
        print(f"{check.name:<18} {bar} {pct:5.1f}%  {check.rule}{flag}")
        if pct < 90:
            worst.append(check)

    lengths = results["lengths"]
    if lengths:
        avg = sum(lengths) / len(lengths)
        print(f"\nspoken length: avg {avg:.0f} words, "
              f"range {min(lengths)}-{max(lengths)}")
        if avg > 45:
            print("  ^ long for a companion robot -- TTS will drag. Consider "
                  "tightening the short-reply rule or lowering num_predict.")

    dropped = results["dropped"]
    if dropped:
        print(f"\nactions the whitelist dropped ({sum(dropped.values())} total):")
        for action, count in dropped.most_common(12):
            print(f"  {count:>3}x  [{action}]")
        print("  Impossible ones ([winks]) are working as intended.")
        print("  Real moves phrased oddly belong in ACTION_ALIASES.")

    if worst:
        print(f"\n{'-' * 66}\nFAILING EXAMPLES\n{'-' * 66}")
        for check in worst:
            examples = results["failures"][check.name]
            print(f"\n{check.name} ({len(examples)} failures) -- {check.rule}")
            for prompt, reply in examples[:3 if not verbose else 99]:
                print(f'  ask: "{prompt}"')
                print(f'  got: {reply[:220]}')
    else:
        print("\nEvery check above 90%. This prompt is in good shape.")


def main(argv):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=None)
    parser.add_argument("--persona", default=None,
                        help=f"persona key (default {yuzu_personas.DEFAULT_PERSONA})")
    parser.add_argument("--runs", type=int, default=3,
                        help="repeats per prompt (default 3; sampling is "
                             "random, so one run per prompt proves nothing)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    persona = args.persona.lower() if args.persona else None
    try:
        brain = YuzuBrain(model=args.model, persona=persona)
    except BrainError as exc:
        print(f"\n{exc}\n")
        return 1
    who = brain.persona.name if brain.persona else "custom"
    print(f"persona: {who}   model: {brain.model}   host: {brain.host}")
    print(f"temp {brain.options['temperature']}  "
          f"top_p {brain.options['top_p']}  "
          f"min_p {brain.options['min_p']}  "
          f"num_predict {brain.options['num_predict']}")
    try:
        brain.check()
    except BrainError as exc:
        print(f"\n{exc}")
        return 1

    count = len(TEST_PROMPTS) * args.runs
    print(f"\nRunning {len(TEST_PROMPTS)} prompts x {args.runs} = {count} "
          f"replies. On a 3B this takes a few minutes...\n")

    results = evaluate(brain, TEST_PROMPTS, args.runs, args.verbose)
    if results is None:
        return 1
    report(results, args.verbose)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
