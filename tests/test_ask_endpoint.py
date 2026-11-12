"""POST /api/ask on scripts/serve_2050.py, with the model stubbed. No test here calls the API or needs a key."""

import json
import sys
import threading
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

import pytest
from nems_open.agent import PolicyAgent, rules
from nems_open.agent import knowledge as K

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

pytestmark = pytest.mark.skipif(not (K.WEB_DATA / "fidelity.json").exists(), reason="demo data missing")

import serve_2050 as srv  # noqa: E402
from test_agent import ScriptedModel, claim, grid_value, reply, rid_of, submit, use  # noqa: E402


@pytest.fixture()
def server(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), srv.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{httpd.server_address[1]}"
    httpd.shutdown()


def post(base, body, path="/api/ask"):
    data = body if isinstance(body, bytes) else json.dumps(body).encode()
    req = urllib.request.Request(base + path, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.load(e)


def carbon_script(levers=None, outside=None):
    levers = levers or {"carbon_price": 50}
    return ScriptedModel(
        lambda m: reply(use("run_scenario", **levers)),
        lambda m: reply(use("read_result", scenario_id=next(iter(m[-1]["content"])) and json.loads(m[-1]["content"][0]["content"])["scenario_id"],
                            measure="co2", year=2040)),
        lambda m: reply(use("submit_answer", **{**submit("Under that policy 2040 CO2 is {c1}, {c2} below EIA.",
                                                         [claim("c1", rid_of(m), "value"), claim("c2", rid_of(m), "difference_pct", 1)]),
                                                "not_from_model": outside or []})))


def test_answer_comes_back_with_sources_grades_and_levers(server, monkeypatch):
    monkeypatch.setattr(srv, "make_agent", lambda: PolicyAgent(client=carbon_script()))
    code, body = post(server, {"question": "What does a $50 carbon price do to US energy CO2 in 2040?"})
    assert code == 200 and not body["declined"] and not body["error"]
    value = grid_value("carbon_price=50", ("co2",), 2040)
    assert f"{value:,.0f} million t [1]" in body["body"] and "Sources" not in body["body"] and "% [2]" in body["body"]
    assert len(body["sources"]) == 1 and body["sources"][0]["markers"] == [1, 2] and body["sources"][0]["grade"] == "stand"
    assert body["basis"].startswith("Basis: ") and body["stand_in"]
    assert body["apply"] == {"carbon_price": 50.0} and body["outside"] == []


def test_outside_sentences_come_back_separately(server, monkeypatch):
    monkeypatch.setattr(srv, "make_agent", lambda: PolicyAgent(client=carbon_script(outside=["A dividend returns the revenue."])))
    _, body = post(server, {"question": "What does a $50 carbon price do to CO2 in 2040?"})
    assert body["outside"] == ["A dividend returns the revenue."] and "dividend" not in body["body"]


def test_every_page_lever_the_agent_runs_is_handed_to_the_page(server, monkeypatch):
    levers = {"carbon_price": 25, "ev_2035": 0.9, "load_growth": 600, "nuclear": 1.5, "gas_supply": 1.0}
    monkeypatch.setattr(srv, "make_agent", lambda: PolicyAgent(client=carbon_script(levers)))
    _, body = post(server, {"question": "What does a mix of policies do to CO2 in 2040?"})
    assert body["apply"] == {k: float(v) for k, v in levers.items()}


def test_page_levers_pick_the_policy_run_over_a_baseline():
    assert srv.page_levers([]) == ({}, [])
    runs = [{"carbon_price": 50.0}, {}]
    assert srv.page_levers(runs)[0] == {"carbon_price": 50.0}
    assert set(srv.LEVER_NAMES) >= set(srv.page_levers([{"load_growth": 600.0, "nuclear": 1.5}])[0])


def test_a_source_line_is_short_and_names_each_module_once(server, monkeypatch):
    monkeypatch.setattr(srv, "make_agent", lambda: PolicyAgent(client=carbon_script()))
    _, body = post(server, {"question": "What does a $50 carbon price do to CO2 in 2040?"})
    line = body["sources"][0]["line"]
    assert chr(10) not in line and len(line) < 520
    assert line.count("Demand stub (any sector not run through its port)") == 1
    assert "Variable: RunResult.co2_total." in line and "Grade: stand-in" in line


def test_no_key_says_so_without_calling_anything(server):
    code, body = post(server, {"question": "What does a $50 carbon price do to CO2 in 2040?"})
    assert code == 503 and body["error"] == "no_key" and "ANTHROPIC_API_KEY" in body["message"]


def test_gate_declines_with_no_key_and_no_model_call(server):
    code, body = post(server, {"question": "What happens to power prices in Texas?"})
    assert code == 200 and body["declined"] and "state or city" in body["body"] and body["sources"] == []


def test_bad_requests(server):
    assert post(server, b"not json")[0] == 400
    assert post(server, {"question": 5})[0] == 400
    assert post(server, {"question": "   "})[0] == 400
    assert post(server, {"question": "x" * 601})[0] == 400


@pytest.mark.parametrize("exc,words", [(ConnectionError, "could not be reached"), (TimeoutError, "could not be reached"),
                                       (KeyError, "Something went wrong")])
def test_agent_failure_is_a_502_in_plain_english_that_never_echoes_the_key(server, monkeypatch, exc, words):
    secret = "sk-ant-secret-value"

    def boom():
        raise exc(f"x-api-key: {secret}")
    monkeypatch.setattr(srv, "make_agent", boom)
    code, body = post(server, {"question": "What does a $50 carbon price do to CO2 in 2040?"})
    assert code == 502 and words in body["message"]
    assert secret not in json.dumps(body) and exc.__name__ not in body["message"]


def test_an_oversized_request_is_refused(server):
    code, body = post(server, {"question": "x" * 5000})
    assert code == 413 and body["error"] == "too_large"


def test_one_question_at_a_time(server, monkeypatch):
    srv.ASKING.acquire()
    try:
        code, body = post(server, {"question": "What does a $50 carbon price do to CO2 in 2040?"})
    finally:
        srv.ASKING.release()
    assert code == 409 and body["error"] == "busy"


def test_health_reports_whether_asking_is_possible(server, monkeypatch):
    def health():
        with urllib.request.urlopen(server + "/api/health") as r:
            return json.load(r)
    assert health()["ask"] is False
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-only")
    assert health()["ask"] is True
