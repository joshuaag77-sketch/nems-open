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
    for k in ("henry_hub", "brent", "gen_gas"):          # stub run: no gas market (ogs standin), no oil market, no LP
        assert by[k]["model"] is None and by[k]["note"] == "not modeled yet" and by[k]["eia"][2050] > 0


def test_a_no_policy_run_lands_near_eia_where_it_runs_eias_numbers(stub_table):
    by = {r["key"]: r for r in stub_table["rows"]}
    assert abs(by["energy"]["gap_pct"][2030]) < 1.0      # 2030 is past the run: EIA's own quantities
    assert by["co2"]["worst_gap_pct"] is not None


def test_watch_mode_narrates_each_pass_and_each_settled_year():
    lines = []
    rec = fm.Narrator((), 1, lines.append)
    try:
        run_model.run(None, 2027, 2028, "cb2026", ported=(), record=rec)
    except FileNotFoundError as e:
        pytest.skip(f"reference data missing: {e}")
    text = "\n".join(lines)
    assert "2027" in text and "2028" in text and "asked for" in text and "cents/kWh" in text
    assert "settled in" in text or "not settled yet" in text


def test_one_modules_dumps_can_be_pinned_to_another_folder(monkeypatch, tmp_path):
    from nems_open import oracle_state
    monkeypatch.setenv("NEMS_ORACLE_OUT_EMM", str(tmp_path))
    assert oracle_state.out_dir("emm") == tmp_path and oracle_state.out_dir("comm") != tmp_path


def test_each_cycle_but_the_last_is_saved_and_tabled(monkeypatch, tmp_path):
    out = tmp_path / "full_model.json"
    monkeypatch.setattr(fm, "OUT", out)
    monkeypatch.setattr(fm, "CYCLES", 2)
    p = {"switches": {}, "not_landed": [], "ported": [], "cycles": 2}
    keeper = fm.Keeper(None, p, 0.0, tmp_path / "run.npz")
    try:
        r = run_model.run(None, 2027, 2028, "cb2026", ported=(), cycles=2, record=keeper)
    except FileNotFoundError as e:
        pytest.skip(f"reference data missing: {e}")
    import json
    t = json.loads(out.read_text())
    assert t["cycles_done"] == 1 and (tmp_path / "run_cycle1.npz").exists()
    assert len(t["rows"]) == 15 and r.prices


def test_generation_by_fuel_gaps_are_points_of_total_generation():
    import numpy as np
    import full_model as fm
    n = 61
    e = {"gen_total": np.full(n, 4000.0), "gen_coal": np.full(n, 0.3), "energy": np.full(n, 90.0)}
    m = {"gen_total": np.full(n, 4100.0), "gen_coal": np.full(n, 100.0), "energy": np.full(n, 99.0)}
    by = {r["key"]: r for r in fm.rows(m, e)}
    assert by["gen_coal"]["gap_unit"] == "pts"
    assert by["gen_coal"]["worst_gap_pct"] == pytest.approx(100 * 99.7 / 4000, abs=0.01)   # 2.49 pts, not +33,233%
    assert by["energy"]["gap_unit"] == "%" and by["energy"]["worst_gap_pct"] == pytest.approx(10.0)
    assert by["gen_total"]["gap_unit"] == "%" and by["gen_total"]["worst_gap_pct"] == pytest.approx(2.5)


def test_capacity_path_is_saved_and_summarised(tmp_path):
    import numpy as np
    from types import SimpleNamespace
    import full_model as fm
    yr = lambda y, w: SimpleNamespace(capacity={"wind": np.full(25, w)}, builds={"wind": np.full(25, 0.4)},
                                      economic_retire={}, planned_adds={}, planned_retire={})
    cap = {2040: yr(2040, 40.0), 2041: yr(2041, 40.4)}
    a = fm.capacity_arrays(cap)
    assert a["capacity:wind"].shape == (61, 25) and a["capacity:wind"][2041 - 1990, 0] == 40.4
    s = fm.capacity_summary(cap)
    assert s["fleet"]["wind"][2040] == 1000.0 and s["built_to_date"]["wind"][2045] == 20.0
    r = SimpleNamespace(prices={}, quantities={}, co2={}, generation_twh={}, gas={}, stable={2040: True}, capacity=cap)
    fm.save_run(r, tmp_path / "x.npz")
    back = fm.load_run(tmp_path / "x.npz")
    assert np.allclose(back.capacity_arrays["builds:wind"][2041 - 1990], 0.4)
    assert fm.capacity_summary(None) is None
