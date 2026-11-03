"""The agent against the real API. Skipped unless ANTHROPIC_API_KEY is set AND NEMS_AGENT_LIVE=1: it spends money.

    NEMS_AGENT_LIVE=1 python -m pytest tests/test_agent_live.py -q

Checks behaviour, not wording: a graded answer cites module, variable and grade and says it rests on stand-ins; a
question the model cannot resolve is declined.
"""

import json
import os
from pathlib import Path

import pytest
from nems_open.agent import PolicyAgent, rules

pytestmark = pytest.mark.skipif(not (os.environ.get("ANTHROPIC_API_KEY") and os.environ.get("NEMS_AGENT_LIVE") == "1"),
                                reason="needs ANTHROPIC_API_KEY and NEMS_AGENT_LIVE=1 (spends money)")

SAMPLES = {q["id"]: q for q in json.loads(Path(rules.__file__).with_name("sample_questions.json").read_text(encoding="utf-8"))}


@pytest.mark.parametrize("qid", [1, 4, 5, 6])
def test_answered_questions_cite_and_disclose(qid):
    ans = PolicyAgent().ask(SAMPLES[qid]["question"])
    assert not ans.error, ans.text
    assert not ans.declined and "Module:" in ans.text and "Variable:" in ans.text and "Grade:" in ans.text
    if qid != 6:
        assert ans.stand_in and "stand-in" in ans.text


def test_a_question_outside_scope_is_declined_by_the_model():
    ans = PolicyAgent().ask("What would banning gas stoves do to US energy CO2 in 2040?")   # no such lever
    assert ans.declined
