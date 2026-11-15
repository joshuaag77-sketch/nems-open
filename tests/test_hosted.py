"""The hosted Ask box offline: limits, spend ceiling, failing closed, and the deploy folder. No API call, no network."""

import json
import subprocess
import sys
from types import SimpleNamespace

import pytest
from nems_open.agent import hosted

Q = "What does a $50 carbon price do to US energy CO2 in 2040?"


class FakeStore:
    """The Redis commands hosted.py uses, in memory (expiry ignored)."""

    def __init__(self, fail=False):
        self.d, self.fail, self.calls = {}, fail, 0

    def pipeline(self, cmds):
        if self.fail:
            raise OSError("unreachable")
        self.calls += 1
        out = []
        for c in cmds:
            op, key = c[0], c[1]
            if op == "SET":
                if "NX" in c and key in self.d:
                    out.append(None)
                    continue
                self.d[key] = int(c[2])
                out.append("OK")
            elif op == "INCR":
                self.d[key] = self.d.get(key, 0) + 1
                out.append(self.d[key])
            elif op == "INCRBY":
                self.d[key] = self.d.get(key, 0) + int(c[2])
                out.append(self.d[key])
            elif op == "GET":
                out.append(None if key not in self.d else str(self.d[key]))
        return out

    def spent(self):
        return sum(v for k, v in self.d.items() if k.startswith("ask:usd:")) / 1e6


def model(input_tokens=20000, output_tokens=2000):
    """A model that never submits: two text replies, then the loop gives up. Enough to exercise limits and cost."""
    text = SimpleNamespace(type="text", text="thinking aloud")
    calls = []

    def create(**kw):
        calls.append(kw)
        return SimpleNamespace(content=[text], stop_reason="end_turn",
                               usage=SimpleNamespace(input_tokens=input_tokens // 2, output_tokens=output_tokens // 2,
                                                     cache_read_input_tokens=0, cache_creation_input_tokens=0))
    return SimpleNamespace(messages=SimpleNamespace(create=create)), calls


@pytest.fixture(autouse=True)
def env(monkeypatch):
    for k in list(hosted.limits()):
        monkeypatch.delenv("ASK_" + k.upper(), raising=False)
    monkeypatch.setenv("ASK_ENABLED", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-not-a-key")
    for k in ("KV_REST_API_URL", "KV_REST_API_TOKEN", "UPSTASH_REDIS_REST_URL", "UPSTASH_REDIS_REST_TOKEN"):
        monkeypatch.delenv(k, raising=False)


def test_an_answer_goes_through_and_its_real_cost_is_settled():
    store, (client, calls) = FakeStore(), model()
    status, body = hosted.answer(Q, "1.2.3.4", store=store, client=client)
    assert status == 200 and body["model"] == "claude-haiku-5-5" and "body" in body
    kw = calls[0]
    assert kw["model"] == "claude-haiku-5-5" and kw["max_tokens"] == 4000
    assert kw["extra_body"]["cache_control"] == {"type": "ephemeral"}
    assert "fallbacks" not in kw["extra_body"]                 # Haiku has no server-side fallback
    assert store.spent() == pytest.approx(hosted.cost_usd("claude-haiku-5-5", 20000, 2000), abs=2e-6)


def test_a_visitor_is_stopped_after_the_hourly_limit(monkeypatch):
    monkeypatch.setenv("ASK_PER_IP_HOUR", "2")
    store = FakeStore()
    codes = [hosted.answer(Q, "9.9.9.9", store=store, client=model()[0])[0] for _ in range(3)]
    assert codes == [200, 200, 429]
    assert hosted.answer(Q, "8.8.8.8", store=store, client=model()[0])[0] == 200     # someone else still can


def test_everyone_together_is_held_to_the_per_minute_limit(monkeypatch):
    monkeypatch.setenv("ASK_PER_MINUTE", "1")
    store = FakeStore()
    assert hosted.answer(Q, "1.1.1.1", store=store, client=model()[0])[0] == 200
    status, body = hosted.answer(Q, "2.2.2.2", store=store, client=model()[0])
    assert status == 429 and body["error"] == "busy"


def test_the_daily_ceiling_stops_questions_before_they_cost_anything(monkeypatch):
    monkeypatch.setenv("ASK_DAILY_USD", "0.01")                # below one question's worst case
    store, (client, calls) = FakeStore(), model()
    status, body = hosted.answer(Q, "1.2.3.4", store=store, client=client)
    assert status == 429 and body["error"] == "budget" and not calls


def test_spend_never_passes_the_ceiling_by_more_than_one_reserve(monkeypatch):
    monkeypatch.setenv("ASK_DAILY_USD", "0.2")
    monkeypatch.setenv("ASK_PER_IP_HOUR", "1000")
    monkeypatch.setenv("ASK_PER_IP_DAY", "1000")
    monkeypatch.setenv("ASK_PER_MINUTE", "1000")
    store = FakeStore()
    for _ in range(200):
        if hosted.answer(Q, "1.2.3.4", store=store, client=model(60000, 6000)[0])[0] != 200:
            break
    assert store.spent() <= 0.2


@pytest.mark.parametrize("setup, code, err", [
    ({"ASK_ENABLED": "0"}, 503, "off"),
    ({}, 503, "store"),                                        # no store configured: fail closed
])
def test_off_or_without_a_store_nothing_is_answered(monkeypatch, setup, code, err):
    for k, v in setup.items():
        monkeypatch.setenv(k, v)
    client, calls = model()
    status, body = hosted.answer(Q, "1.2.3.4", client=client)
    assert (status, body["error"]) == (code, err) and not calls


def test_an_unreachable_store_fails_closed():
    client, calls = model()
    status, body = hosted.answer(Q, "1.2.3.4", store=FakeStore(fail=True), client=client)
    assert (status, body["error"]) == (503, "store") and not calls


def test_a_question_the_gate_declines_costs_nothing_and_counts_nothing():
    store, (client, calls) = FakeStore(), model()
    status, body = hosted.answer("What happens to electricity prices in Texas in 2040?", "1.2.3.4", store=store, client=client)
    assert status == 200 and body["declined"] and not calls and store.calls == 0


def test_bad_questions_are_refused_before_anything_else():
    assert hosted.answer("   ", "x")[0] == 400
    assert hosted.answer("x" * 601, "x")[0] == 400


def test_visitors_are_stored_as_hashes_not_addresses():
    store = FakeStore()
    hosted.answer(Q, "203.0.113.7", store=store, client=model()[0])
    assert not any("203.0.113.7" in k for k in store.d)


def test_health_reports_ready_only_with_key_store_and_switch(monkeypatch):
    assert hosted.health() == {"ok": True, "hosted": True, "run": False, "ask": False}
    monkeypatch.setenv("KV_REST_API_URL", "https://example.invalid")
    monkeypatch.setenv("KV_REST_API_TOKEN", "t")
    assert hosted.health()["ask"] is True


def test_worst_case_per_question_is_small_on_the_default_model():
    assert hosted.worst_case_usd(hosted.limits()) < 0.05


def test_the_deploy_folder_holds_the_site_and_a_lean_function(tmp_path):
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    out = tmp_path / "site"
    subprocess.run([sys.executable, str(root / "scripts" / "build_site.py"), "--out", str(out)], check=True,
                   capture_output=True)
    assert (out / "web" / "2050.html").exists() and (out / "api" / "ask.py").exists()
    assert (out / "requirements.txt").read_text().split() == ["anthropic>=0.84", "numpy>=1.26"]
    assert not (out / "pyproject.toml").exists()
    cfg = json.loads((out / "vercel.json").read_text())
    assert cfg["functions"]["api/ask.py"]["maxDuration"] <= 60
    # the bundled agent imports and answers a gated question with only the bundle on the path (no repo src)
    code = ("import sys; sys.path.insert(0, 'src'); from nems_open.agent import hosted; "
            "print(hosted.answer('electricity prices in Texas in 2040?', 'x')[1]['declined'])")
    r = subprocess.run([sys.executable, "-I", "-c", code], cwd=out, capture_output=True, text=True,
                       env={"ASK_ENABLED": "1", "ANTHROPIC_API_KEY": "test", "SYSTEMROOT": __import__("os").environ.get("SYSTEMROOT", "")})
    assert r.stdout.strip() == "True", r.stderr
    for f in out.rglob("*"):
        if f.is_file() and f.suffix in (".py", ".json", ".txt", ".html", ".js"):
            assert "sk-ant-" not in f.read_text(encoding="utf-8", errors="ignore"), f
