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
from nems_open.agent import scenarios as S

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "tests"))

pytestmark = pytest.mark.skipif(not (S.WEB_DATA / "fidelity.json").exists(), reason="demo data missing")

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


def carbon_script(carbon=50, ev=None):
    return ScriptedModel(
        lambda m: reply(use("run_scenario", carbon_price=carbon, ev_share_2035=ev, building_energy_2050=1.0)),
        lambda m: reply(use("read_result", scenario_id="c50_evref_b100", measure="co2", year=2040)),
        lambda m: reply(use("submit_answer", **submit("A $50 carbon price puts 2040 CO2 at {c1} million tons.",
                                                      [claim("c1", rid_of(m), "value")]))))


def test_answer_comes_back_with_sources_grades_and_levers(server, monkeypatch):
    monkeypatch.setattr(srv, "make_agent", lambda: PolicyAgent(client=carbon_script()))
    code, body = post(server, {"question": "What does a $50 carbon price do to US energy CO2 in 2040?"})
    assert code == 200 and not body["declined"] and not body["error"]
    value = grid_value("c50_evref_b100", ("co2",), 2040)
    assert f"{value:,.0f} [1]" in body["body"] and "Sources" not in body["body"]
    assert len(body["sources"]) == 1 and body["sources"][0]["grade"] == "stand"
    assert body["basis"].startswith("Basis: ") and body["stand_in"]
    assert body["apply"] == {"carbon_price": 50.0} and body["unmapped"] == []


def test_a_source_is_one_short_line_and_names_each_module_once(server, monkeypatch):
    monkeypatch.setattr(srv, "make_agent", lambda: PolicyAgent(client=carbon_script()))
    _, body = post(server, {"question": "What does a $50 carbon price do to CO2 in 2040?"})
    line = body["sources"][0]["line"]
    assert "\n" not in line and len(line) < 520
    assert line.count("Demand stub (any sector not run through its port)") == 1
    assert "Module:" in line and "Variable: RunResult.co2_total." in line and "Grade: stand-in" in line


def test_ev_lever_maps_and_building_energy_is_reported_not_mapped():
    apply, unmapped = srv.page_levers([{"carbon_price": 0.0, "building_energy_2050": 0.9, "ev_share_2035": 0.8}])
    assert apply == {"carbon_price": 0.0, "ev_2035": 0.8} and "90%" in unmapped[0]
    assert srv.page_levers([]) == ({}, [])
    # a comparison that ends on the baseline shows the policy run, not the baseline
    runs = [{"carbon_price": 50.0, "building_energy_2050": 1.0}, {"carbon_price": 0.0, "building_energy_2050": 1.0}]
    assert srv.page_levers(runs)[0] == {"carbon_price": 50.0}


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


def test_agent_failure_is_a_502_that_never_echoes_the_key(server, monkeypatch):
    secret = "sk-ant-secret-value"

    def boom():
        raise ConnectionError(f"x-api-key: {secret}")
    monkeypatch.setattr(srv, "make_agent", boom)
    code, body = post(server, {"question": "What does a $50 carbon price do to CO2 in 2040?"})
    assert code == 502 and "ConnectionError" in body["message"] and secret not in json.dumps(body)


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


def test_split_text_keeps_prose_and_basis():
    nn = "\n\n"
    body, basis = srv.split_text(f"Prose [1].{nn}Sources{nn[1:]}[1] x.{nn}Basis: rests on stand-ins.")
    assert body == "Prose [1]." and basis == "Basis: rests on stand-ins."
    assert srv.split_text("plain") == ("plain", "")
