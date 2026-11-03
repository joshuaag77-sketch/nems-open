"""The policy agent offline: the tools, the rules, and the loop with a scripted stand-in for the model.

No test here calls the API. `ScriptedModel` plays the model: it answers each request from a script, and can read
the tool results the loop sent back, the way the real model would.
"""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from nems_open.agent import PolicyAgent, rules
from nems_open.agent import scenarios as S
from nems_open.agent.__main__ import main as cli
from nems_open.agent.tools import SCHEMAS, Toolbox

pytestmark = pytest.mark.skipif(not (S.WEB_DATA / "fidelity.json").exists(), reason="demo data missing")

SAMPLES = json.loads((Path(rules.__file__).with_name("sample_questions.json")).read_text(encoding="utf-8"))


# ---- a scripted model -------------------------------------------------------------------------------

def use(name, **args):
    return SimpleNamespace(type="tool_use", id=f"toolu_{name}_{len(args)}", name=name, input=args)


def reply(*blocks, stop="tool_use"):
    return SimpleNamespace(content=list(blocks), stop_reason=stop, usage=SimpleNamespace(input_tokens=100, output_tokens=20))


class ScriptedModel:
    """steps: functions (messages) -> response. Records every request."""

    def __init__(self, *steps):
        self.steps, self.requests = list(steps), []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.requests.append({**kw, "messages": list(kw["messages"])})      # the loop keeps appending to its list
        return self.steps[len(self.requests) - 1](kw["messages"])


def last_results(messages):
    """The tool results the loop sent, parsed: {tool_use_id: dict or text}."""
    out = {}
    for item in messages[-1]["content"]:
        try:
            out[item["tool_use_id"]] = json.loads(item["content"])
        except (ValueError, TypeError):
            out[item["tool_use_id"]] = item["content"]
    return out


def rid_of(messages, _tool=None):
    return next(v["result_id"] for v in last_results(messages).values() if isinstance(v, dict) and "result_id" in v)


def grid_value(sid, path, year):
    rec = json.loads((S.WEB_DATA / "scenarios" / f"{sid}.json").read_text())
    return S.value(rec, path, year)


# ---- the gate ---------------------------------------------------------------------------------------

@pytest.mark.parametrize("q", SAMPLES, ids=lambda q: str(q["id"]))
def test_gate_matches_the_expected_behaviour(q):
    declined = rules.gate(q["question"]) is not None
    assert declined == (q["behaviour"] == "decline")


def test_ten_sample_questions_six_answered_four_declined():
    assert len(SAMPLES) == 10 and sum(q["behaviour"] == "decline" for q in SAMPLES) == 4


def test_gate_leaves_history_comparisons_to_the_model():
    assert rules.gate("Does a $50 carbon price get us below 2005 emissions by 2050?") is None


# ---- the tools --------------------------------------------------------------------------------------

def test_every_tool_schema_is_strict_and_closed():
    for t in SCHEMAS + [rules.SUBMIT]:
        assert t["strict"] is True and t["input_schema"]["additionalProperties"] is False
        assert set(t["input_schema"]["required"]) == set(t["input_schema"]["properties"])


def test_run_and_read_a_grid_scenario_match_the_demo_data():
    box = Toolbox()
    run, err = box.call("run_scenario", {"carbon_price": 50, "ev_share_2035": None, "building_energy_2050": 1.0})
    assert not err and run["scenario_id"] == "c50_evref_b100" and run["source"] == "precomputed grid"
    res, err = box.call("read_result", {"scenario_id": run["scenario_id"], "measure": "co2", "year": 2040})
    assert not err
    assert res["fields"]["value"] == pytest.approx(grid_value("c50_evref_b100", ("co2",), 2040), abs=1e-3)
    assert res["fields"]["difference"] == pytest.approx(res["fields"]["value"] - res["fields"]["reference"], abs=1e-3)
    assert res["grade"] == "stand-in"
    assert box.live_runs == 0


def test_tool_errors_are_returned_not_raised():
    box = Toolbox()
    assert box.call("read_result", {"scenario_id": "nope", "measure": "co2", "year": 2040})[1]
    assert box.call("run_scenario", {"carbon_price": 500, "ev_share_2035": None, "building_energy_2050": 1.0})[1]
    run, _ = box.call("run_scenario", {"carbon_price": 0, "ev_share_2035": None, "building_energy_2050": 1.0})
    assert box.call("read_result", {"scenario_id": run["scenario_id"], "measure": "co2", "year": 1975})[1]
    assert box.call("unknown", {})[1]


def test_trace_gives_modules_and_grade():
    box = Toolbox()
    res, err = box.call("trace_number", {"measure": "electricity_price"})
    assert not err and res["grade_label"] == "stand-in" and res["variable"] == "MPBLK/pelas"
    assert any(m["module"] == "electricity:price" for m in res["modules"])


def test_uncertainty_bands_are_ordered_and_labelled():
    box = Toolbox()
    res, err = box.call("read_uncertainty", {"measure": "co2", "carbon_price": 0, "year": 2050})
    assert not err and res["fields"]["p10"] < res["fields"]["p50"] < res["fields"]["p90"]
    assert "not EIA's" in res["label"]
    assert box.call("read_uncertainty", {"measure": "co2", "carbon_price": 37, "year": 2050})[1]


def test_live_runs_are_limited(monkeypatch):
    calls = []

    def fake_load(carbon, ev, bld):
        calls.append(carbon)
        return f"fake{carbon}", {"co2": [0.0] * 26}, "live run"

    monkeypatch.setattr(S, "load", fake_load)
    box = Toolbox()
    for c in (61, 62, 63, 64):
        assert not box.call("run_scenario", {"carbon_price": c, "ev_share_2035": None, "building_energy_2050": 1.0})[1]
    assert box.call("run_scenario", {"carbon_price": 65, "ev_share_2035": None, "building_energy_2050": 1.0})[1]
    assert box.live_runs == 4


def test_an_off_grid_scenario_really_runs():
    box = Toolbox()
    run, err = box.call("run_scenario", {"carbon_price": 60, "ev_share_2035": None, "building_energy_2050": 1.0})
    assert not err and run["source"] == "live run"
    hi, _ = box.call("read_result", {"scenario_id": run["scenario_id"], "measure": "co2", "year": 2050})
    assert hi["fields"]["difference"] < 0           # a carbon price lowers CO2 against the reference


# ---- the rules --------------------------------------------------------------------------------------

def stocked():
    box = Toolbox()
    run, _ = box.call("run_scenario", {"carbon_price": 50, "ev_share_2035": None, "building_energy_2050": 1.0})
    res, _ = box.call("read_result", {"scenario_id": run["scenario_id"], "measure": "co2", "year": 2040})
    return box, res["result_id"]


def claim(cid, rid, field, decimals=0):
    return {"id": cid, "result_id": rid, "field": field, "decimals": decimals}


def submit(prose, claims, can=True, reason=""):
    return {"can_answer": can, "answer": prose, "claims": claims, "reason_cannot_answer": reason}


def test_a_good_answer_gets_its_numbers_sources_and_the_stand_in_notice():
    box, rid = stocked()
    r, problems = rules.check(submit("A $50 carbon price puts US CO2 in 2040 at {c1} million tons, {c2}% against EIA.",
                                     [claim("c1", rid, "value"), claim("c2", rid, "difference_pct", 1)]), box,
                              "What does a $50 carbon price do in 2040?")
    assert not problems
    v = box.results[rid]["numbers"]["value"]
    assert f"{v:,.0f} [1]" in r.text and "[2]" in r.text
    assert "Module:" in r.text and "Variable:" in r.text and "Grade: stand-in" in r.text
    assert r.stand_in and "rest on stand-ins" in r.text


def test_a_number_without_a_claim_is_rejected():
    box, rid = stocked()
    r, problems = rules.check(submit("It falls to about 3,400 million tons by 2040.", []), box, "q")
    assert r is None and any("3,400" in p for p in problems)


def test_the_users_own_numbers_years_and_run_levers_are_allowed():
    box, rid = stocked()
    r, problems = rules.check(submit("With a $50 carbon price from 2027, CO2 in 2040 is {c1} million tons (10th to 90th "
                                     "percentile bands exist too).", [claim("c1", rid, "value")]), box,
                              "What does a $50 carbon price do?")
    assert not problems and r is not None


@pytest.mark.parametrize("bad", [
    submit("CO2 is {c1}.", [claim("c1", "r99", "value")]),
    submit("CO2 is {c1}.", [claim("c1", "r2", "nonsense")]),
    submit("CO2 is {c2}.", [claim("c1", "r2", "value")]),
    submit("CO2 is lower.", [claim("c1", "r2", "value")]),
])
def test_bad_claims_are_rejected(bad):
    box, rid = stocked()
    assert rules.check(bad, box, "q")[0] is None


def test_a_decline_needs_a_reason_and_carries_no_numbers():
    box, _ = stocked()
    assert rules.check(submit("", [], can=False), box, "q")[0] is None
    assert rules.check(submit("It is 12", [], can=False, reason="outside scope"), box, "q")[0] is None
    r, problems = rules.check(submit("", [], can=False, reason="it is about one site"), box, "q")
    assert not problems and r.declined and "one site" in r.text and rules.SCOPE in r.text


def test_numbers_that_are_not_model_outputs_say_so():
    box = Toolbox()
    res, _ = box.call("list_levers", {})
    r, problems = rules.check(submit("The carbon price can go up to {c1} dollars a ton.",
                                     [claim("c1", res["result_id"], "carbon_price.max")]), box, "q")
    assert not problems and "model setting" in r.text and not r.stand_in


def test_eia_reference_numbers_cite_eia():
    box, rid = stocked()
    r, _ = rules.check(submit("EIA's reference has {c1} million tons.", [claim("c1", rid, "reference")]), box, "q")
    assert "Grade: EIA's own number" in r.text and not r.stand_in


# ---- the loop ---------------------------------------------------------------------------------------

def test_a_full_conversation_through_the_loop():
    model = ScriptedModel(
        lambda m: reply(use("run_scenario", carbon_price=50, ev_share_2035=None, building_energy_2050=1.0)),
        lambda m: reply(use("read_result", scenario_id="c50_evref_b100", measure="co2", year=2040)),
        lambda m: reply(use("submit_answer", **submit("A $50 carbon price puts 2040 CO2 at {c1} million tons, {c2} against "
                                                      "EIA's reference.",
                                                      [claim("c1", rid_of(m, "read_result"), "value"),
                                                       claim("c2", rid_of(m, "read_result"), "difference")]))),
    )
    ans = PolicyAgent(client=model).ask("What does a $50 carbon price do to US energy CO2 in 2040?")
    value = grid_value("c50_evref_b100", ("co2",), 2040)
    assert not ans.error and not ans.declined and ans.stand_in
    assert f"{value:,.0f} [1]" in ans.text and "Grade: stand-in" in ans.text and "stand-ins" in ans.text
    assert [c["tool"] for c in ans.tool_calls] == ["run_scenario", "read_result"] and ans.turns == 3
    assert ans.input_tokens == 300
    # the request carries the tools, the adaptive thinking setting, effort and the fallback opt-in
    kw = model.requests[0]
    assert kw["model"] == "claude-opus-5-5" and kw["thinking"] == {"type": "adaptive"}
    assert kw["extra_body"] == {"output_config": {"effort": "medium"}, "fallbacks": "default"}
    assert "submit_answer" in [t["name"] for t in kw["tools"]]


def test_a_rejected_answer_is_sent_back_and_repaired():
    def first(m):
        return reply(use("run_scenario", carbon_price=0, ev_share_2035=None, building_energy_2050=1.0))

    def second(m):
        return reply(use("read_result", scenario_id="c0_evref_b100", measure="gas_home_price", year=2035))

    def bad(m):
        return reply(use("submit_answer", **submit("Home gas costs 9.99 dollars per MMBtu in 2035.", [])))

    def good(m):
        assert "Rejected" in m[-1]["content"][0]["content"] and "9.99" in m[-1]["content"][0]["content"]
        return reply(use("submit_answer", **submit("Home gas costs {c1} dollars per MMBtu in 2035.",
                                                   [claim("c1", "r1", "value", 2)])))

    ans = PolicyAgent(client=ScriptedModel(first, second, bad, good)).ask("What do homes pay for gas in 2035?")
    assert not ans.error and "9.99" not in ans.text and "Natural gas" in ans.text and "MPBLK/pngrs" in ans.text


def test_the_model_can_decline_through_submit_answer():
    model = ScriptedModel(lambda m: reply(use("submit_answer", **submit("", [], can=False,
                                                                       reason="it needs a lever the model does not have"))))
    ans = PolicyAgent(client=model).ask("What if we banned gas stoves?")
    assert ans.declined and "does not have" in ans.text and rules.SCOPE in ans.text


def test_a_gated_question_never_reaches_the_model():
    class Boom:
        messages = SimpleNamespace(create=lambda **kw: pytest.fail("the model was called"))

    ans = PolicyAgent(client=Boom()).ask("What will power cost on my street in Pittsburgh in 2032?")
    assert ans.declined and ans.gated and "below the national level" in ans.text


def test_ending_without_an_answer_is_nudged_once_then_given_up():
    text = SimpleNamespace(type="text", text="CO2 will fall by 20%.")
    model = ScriptedModel(lambda m: reply(text, stop="end_turn"), lambda m: reply(text, stop="end_turn"))
    ans = PolicyAgent(client=model).ask("What does a carbon price do?")
    assert ans.error == "no submit_answer" and "20%" not in ans.text      # nothing unchecked is shown
    assert "submit_answer" in model.requests[1]["messages"][-1]["content"]


def test_a_refusal_is_reported_not_answered():
    ans = PolicyAgent(client=ScriptedModel(lambda m: reply(stop="refusal"))).ask("What does a carbon price do?")
    assert ans.declined and "safety" in ans.text


def test_fallbacks_can_be_turned_off():
    model = ScriptedModel(lambda m: reply(use("submit_answer", **submit("", [], can=False, reason="x"))))
    PolicyAgent(client=model, fallbacks=False).ask("What does a carbon price do?")
    assert "fallbacks" not in model.requests[0]["extra_body"] and "extra_headers" not in model.requests[0]


# ---- the command line -------------------------------------------------------------------------------

def test_cli_without_a_key_sends_nothing(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert cli(["What does a $50 carbon price do?"]) == 3
    assert "nothing was sent" in capsys.readouterr().err


def test_cli_declines_a_gated_question_without_a_key(monkeypatch, capsys):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert cli(["What was US energy CO2 in 1975?"]) == 0
    assert "before the model's first reported year" in capsys.readouterr().out


def test_cli_lists_the_sample_questions(capsys):
    assert cli(["--questions"]) == 0 and capsys.readouterr().out.count("expected:") == 10
    assert cli(["--check-gate"]) == 0


# ---- through the real SDK, against a fake server ----------------------------------------------------

def test_requests_through_the_real_sdk_have_the_right_shape():
    """The real anthropic client and httpx, with a mock transport in place of the network: checks what would be
    sent (tools, thinking, effort, the fallback opt-in) and that SDK content blocks go back on the next turn."""
    anthropic = pytest.importorskip("anthropic")
    try:                                  # anthropic 1.x is built on httpx2, 0.x on httpx
        import httpx2 as httpx
    except ImportError:
        httpx = pytest.importorskip("httpx")
    sent = []

    def message(content, stop):
        return {"id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5", "content": content,
                "stop_reason": stop, "stop_sequence": None, "usage": {"input_tokens": 11, "output_tokens": 7}}

    script = [
        message([{"type": "tool_use", "id": "toolu_a", "name": "run_scenario",
                  "input": {"carbon_price": 0, "ev_share_2035": None, "building_energy_2050": 1.0}}], "tool_use"),
        message([{"type": "tool_use", "id": "toolu_b", "name": "read_result",
                  "input": {"scenario_id": "c0_evref_b100", "measure": "co2", "year": 2040}}], "tool_use"),
        message([{"type": "tool_use", "id": "toolu_c", "name": "submit_answer",
                  "input": submit("With no carbon price, 2040 CO2 is {c1} million tons.", [claim("c1", "r1", "value")])}],
                "tool_use"),
    ]

    def handler(request):
        sent.append((dict(request.headers), json.loads(request.content)))
        return httpx.Response(200, json=script[len(sent) - 1])

    client = anthropic.Anthropic(api_key="test-key-not-real", max_retries=0,
                                 http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    ans = PolicyAgent(client=client).ask("What is US energy CO2 in 2040 with no carbon price?")
    assert not ans.error, ans.text
    value = grid_value("c0_evref_b100", ("co2",), 2040)
    assert f"{value:,.0f} [1]" in ans.text

    headers, body = sent[0]
    assert body["model"] == "claude-opus-5-5" and body["thinking"] == {"type": "adaptive"}
    assert body["output_config"] == {"effort": "medium"} and body["fallbacks"] == "default"
    assert headers["anthropic-beta"] == "server-side-fallback-2026-07-01"
    assert "tool_choice" not in body                                  # forced tool use is a 400 on this model
    assert [t["name"] for t in body["tools"]][-1] == "submit_answer" and all(t["strict"] for t in body["tools"])
    # turn 2 carries the assistant's tool_use block back unchanged and the result we computed
    second = sent[1][1]["messages"]
    assert second[1]["role"] == "assistant" and second[1]["content"][0]["id"] == "toolu_a"
    assert second[2]["content"][0]["tool_use_id"] == "toolu_a"
    assert json.loads(second[2]["content"][0]["content"])["scenario_id"] == "c0_evref_b100"
