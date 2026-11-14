"""scripts/full_model.py without the hour-long run: the stub loop for two years, then the table."""

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
fm = pytest.importorskip("full_model")
from nems_open import run_model  # noqa: E402


@pytest.fixture(scope="module")
def stub_table():
    try:
        r = run_model.run(None, 2027, 2028, "cb2026", ported=())
    except FileNotFoundError as e:
        pytest.skip(f"reference data missing: {e}")
    return fm.table(r, {"switches": {}, "not_landed": [], "ported": [], "cycles": 1}, None)


def test_switches_that_have_not_landed_are_skipped_not_passed(monkeypatch):
    monkeypatch.setitem(fm.SWITCHES, "not_a_real_switch", "x")
    p = fm.plan()
    assert "not_a_real_switch" in p["not_landed"] and "not_a_real_switch" not in p["switches"]
    assert p["switches"].get("elec") == "lp"


def test_fifteen_headline_numbers(stub_table):
    keys = [r["key"] for r in stub_table["rows"]]
    assert len(keys) == 15 and {"co2", "energy", "henry_hub", "brent", "bill", "gen_gas"} <= set(keys)


def test_numbers_the_model_does_not_compute_say_so(stub_table):
    by = {r["key"]: r for r in stub_table["rows"]}
    for k in ("henry_hub", "brent", "gen_gas"):          # no gas market, no oil market, no LP in the stub run
        assert by[k]["model"] is None and by[k]["note"] == "not modeled yet" and by[k]["eia"][2050] > 0


def test_a_no_policy_run_lands_near_eia_where_it_runs_eias_numbers(stub_table):
    by = {r["key"]: r for r in stub_table["rows"]}
    assert abs(by["energy"]["gap_pct"][2030]) < 1.0      # 2030 is past the run: EIA's own quantities
    assert by["co2"]["worst_gap_pct"] is not None
