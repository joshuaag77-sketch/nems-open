"""scripts/showroom_scenarios.py: every scenario maps to real run_model inputs, or says what is missing."""

import inspect
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sc = pytest.importorskip("showroom_scenarios")
from nems_open import run_model  # noqa: E402


def test_thirty_scenarios_with_unique_keys():
    keys = [s.key for s in sc.SCENARIOS]
    assert len(keys) == 30 and len(set(keys)) == 30


def test_switches_are_run_model_arguments():
    params = inspect.signature(run_model.run).parameters
    assert set(sc.SWITCHES) <= set(params)


def test_every_scenario_builds_run_model_arguments():
    params = set(inspect.signature(run_model.run).parameters)
    for s in sc.SCENARIOS:
        assert not s.not_yet()
        args = sc.run_args(s)
        assert set(args) <= params
        assert args["lfmm"] == ("gams" if s.key in sc.LFMM_GAMS else "standin")
    lng = sc.run_args(sc.BY_KEY["lng35"])["policy"].lng_exports
    assert lng[2035 - 1990] == pytest.approx(35.0)


def test_tier_one_is_the_launch_set():
    t = sc.TIERS[1]
    assert len(t) == 11 and set(t) <= set(sc.BY_KEY)
    assert [k for k in t if sc.lfmm_for(sc.BY_KEY[k]) == "gams"] == ["reference", "co2_50", "co2_100", "ev75"]


@pytest.fixture
def stub(tmp_path, monkeypatch):
    try:
        r = run_model.run(None, 2027, 2028, "cb2026", ported=())
    except FileNotFoundError as e:
        pytest.skip(f"reference data missing: {e}")
    monkeypatch.setattr(sc, "OUT", tmp_path / "out")
    monkeypatch.setattr(sc, "WEB", tmp_path / "web")
    monkeypatch.setattr(sc, "LOCK", tmp_path / "HEAVY.lock")
    calls = []

    def run(**kw):
        calls.append(kw)
        if kw["policy"].carbon_price is not None and np.max(kw["policy"].carbon_price) >= 100:
            raise RuntimeError("boom")
        assert (tmp_path / "HEAVY.lock").read_text() == "showroom"
        return r
    return run, calls, tmp_path


def test_runner_saves_each_run_records_failures_and_resumes(stub):
    run, calls, tmp = stub
    assert sc.run_tier(1, run=run, log=lambda s: None) == 1          # co2_100 fails, the rest go on
    assert len(calls) == 11 and not (tmp / "HEAVY.lock").exists()
    st = sc.status()
    assert st["co2_100"]["error"].startswith("RuntimeError") and st["ev75"]["finished"]
    assert sc.done("dc100") and not sc.done("co2_100")
    calls.clear()
    sc.run_tier(1, run=run, log=lambda s: None)                      # a rerun retries only what is not done
    assert [c["policy"].carbon_price.max() for c in calls] == [100.0]


def test_runner_waits_for_another_holder(stub, monkeypatch):
    run, calls, tmp = stub
    (tmp / "HEAVY.lock").write_text("emm-capacity3")
    waits = []

    def sleep(s):
        waits.append(s)
        (tmp / "HEAVY.lock").unlink()
    monkeypatch.setattr(sc.time, "sleep", sleep)
    monkeypatch.setitem(sc.TIERS, 9, ("reference",))
    sc.run_tier(9, run=run, log=lambda s: None)
    assert waits and len(calls) == 1 and not (tmp / "HEAVY.lock").exists()


def test_data_center_gw_becomes_twh_and_reaches_target_in_2035():
    load = sc.data_center(100)
    assert load.twh[2035 - 1990] == pytest.approx(876.0)
    assert load.twh[2026 - 1990] == 0 and load.twh[2050 - 1990] == pytest.approx(876.0)
    assert load.shares.sum() == pytest.approx(1.0)


def test_default_split_is_eias_own():
    try:
        from nems_open.datacenter import regional_shares
        eia = regional_shares()
    except FileNotFoundError as e:
        pytest.skip(f"reference data missing: {e}")
    assert np.allclose([sc.DC_SHARES[d] for d in sc.DIVISIONS], eia, atol=0.002)


def test_ev_path_keeps_eia_through_2030_then_moves_to_target():
    p = sc.ev_path(0.75)
    assert np.isnan(p[2030 - 1990]) and p[2035 - 1990] == pytest.approx(0.75) and p[2050 - 1990] == pytest.approx(0.75)
