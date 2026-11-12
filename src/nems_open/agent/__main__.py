"""python -m nems_open.agent "question" [--model M] [--no-fallbacks] [--questions] [--check-gate]"""

import argparse
import json
import os
import sys
from pathlib import Path

from nems_open.agent import rules
from nems_open.agent.loop import DEFAULT_MODEL, PolicyAgent

QUESTIONS = Path(__file__).with_name("sample_questions.json")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m nems_open.agent", description=__doc__)
    ap.add_argument("question", nargs="?", help="the question, in quotes")
    ap.add_argument("--model", default=None, help=f"model id (default {DEFAULT_MODEL}, or NEMS_AGENT_MODEL)")
    ap.add_argument("--no-fallbacks", action="store_true", help="do not ask the API to retry refusals on a fallback model")
    ap.add_argument("--json", action="store_true", help="print the answer, claims and tool calls as JSON")
    ap.add_argument("--questions", action="store_true", help="list the 10 sample questions and the behaviour expected")
    ap.add_argument("--check-gate", action="store_true", help="run the sample questions through the scope gate only (no API call)")
    a = ap.parse_args(argv)

    samples = json.loads(QUESTIONS.read_text(encoding="utf-8"))
    if a.questions:
        for q in samples:
            print(f"{q['id']:2}. [{q['behaviour']}] {q['question']}\n      expected: {q['expect']}")
        return 0
    if a.check_gate:
        bad = 0
        for q in samples:
            got = "decline" if rules.gate(q["question"]) else "model"
            want = "decline" if q["behaviour"] == "decline" else "model"
            bad += got != want
            print(f"{q['id']:2}. gate says {got:7} (expected {want:7}) {q['question']}")
        return 1 if bad else 0
    if not a.question:
        ap.print_usage(sys.stderr)
        return 2

    declined = rules.gate(a.question)
    if declined:                        # no key and no model call needed
        print(rules.decline_text(declined.reason, declined.suggestion))
        return 0
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("No ANTHROPIC_API_KEY in the environment, so nothing was sent. Set it and run again.", file=sys.stderr)
        return 3
    answer = PolicyAgent(model=a.model, fallbacks=not a.no_fallbacks).ask(a.question)
    if a.json:
        print(json.dumps({"text": answer.text, "declined": answer.declined, "stand_in": answer.stand_in,
                          "tool_calls": answer.tool_calls, "turns": answer.turns, "model": answer.model,
                          "input_tokens": answer.input_tokens, "output_tokens": answer.output_tokens,
                          "error": answer.error}, indent=1))
    else:
        print(answer.text)
        print(f"\n({answer.turns} turns, {len(answer.tool_calls)} tool calls, {answer.input_tokens} in / "
              f"{answer.output_tokens} out tokens, {answer.model})", file=sys.stderr)
    return 1 if answer.error else 0


if __name__ == "__main__":
    sys.exit(main())
