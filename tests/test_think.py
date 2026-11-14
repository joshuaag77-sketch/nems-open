"""run_model.run's `record` hook and the recorded runs behind web/think.html (scripts/think_runs.py)."""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
THINK = ROOT / "web" / "data" / "think"
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(scope="module")
def stub_runs():
    """The same stub run twice, with and without a recorder."""
    from nems_open import run_model
    from nems_open.demand_adapter import Policy
    calls = []
    pol = Policy(carbon_price=75.0, start_year=2027)
    plain = run_model.run(pol, 2027, 2030, ported=())
    rec = run_model.run(pol, 2027, 2030, ported=(), record=lambda stage, **kw: calls.append((stage, kw["year"], kw["itr"], kw)))
    return plain, rec, calls


def test_recording_changes_nothing(stub_runs):
    plain, rec, _ = stub_runs
    for k in plain.prices:
        np.testing.assert_array_equal(plain.prices[k], rec.prices[k])
    for k in plain.quantities:
        np.testing.assert_array_equal(plain.quantities[k], rec.quantities[k])


def test_two_records_per_pass_demand_first(stub_runs):
    plain, _, calls = stub_runs
    assert len(calls) == 2 * len(plain.passes)
    assert [c[0] for c in calls[:4]] == ["demand", "supply", "demand", "supply"]
    for (s1, y1, i1, _), (s2, y2, i2, kw) in zip(calls[::2], calls[1::2]):
        assert (s1, s2) == ("demand", "supply") and (y1, i1) == (y2, i2)
        assert {"co2", "converged", "dp", "dq", "worst"} <= set(kw)


def test_recorded_values_are_the_loops():
    """What the recorder writes for the last supply step of a year is the run's own settled value."""
    import think_runs
    from nems_open import run_model
    from nems_open.demand_adapter import Policy
    from nems_open.supply_standin.data import FIRST_YEAR, US, load_case
    d = load_case("cb2026")["MACOUT/mc_jpgdp"]
    rec = think_runs.Recorder(float(d[2024 - 1987] / d[0]))
    r = run_model.run(Policy(carbon_price=50.0, start_year=2027), 2027, 2028, ported=(), record=rec)
    last = [s for s in rec.steps if s["y"] == 2028 and s["s"] == "s"][-1]
    j = 2028 - FIRST_YEAR
    assert last["v"][think_runs.KEYS.index("qngel")] == pytest.approx(r.quantities["QBLK/qngel"][US, j] / 1000, rel=1e-4)
    assert last["v"][think_runs.KEYS.index("co2")] == pytest.approx(float(r.co2_total[j]), rel=1e-4)


@pytest.mark.skipif(not (THINK / "manifest.json").exists(), reason="no recorded runs")
def test_recorded_files_are_complete():
    meta = json.loads((THINK / "meta.json").read_text())
    man = json.loads((THINK / "manifest.json").read_text())
    assert man["scenarios"]
    for sc in man["scenarios"]:
        d = json.loads((THINK / f"{sc['id']}.json").read_text())
        years = {s["y"] for s in d["steps"]}
        assert years == set(range(meta["years"][0], meta["years"][1] + 1))
        assert all(len(s["v"]) == len(meta["keys"]) for s in d["steps"])
        assert all(s["s"] in ("d", "s") for s in d["steps"])
