"""gas_supply under EIA's HSM (ogs "hsm" or "aimms"): HSM runs EIA's own low or high supply case, the stand-in's price
scaling stays off so the case is not counted twice, and the showroom's tier 2 runs on it. HSM and NGMM are stubbed."""
import sys
from pathlib import Path

import numpy as np
import pytest

from nems_open import levers, run_model
from nems_open.demand_adapter import Policy
from nems_open.ogsm import couple

START = END = 2030
LOW, REF, HIGH = "scedes.lowogs.csv", "scedes.cb2026.csv", "scedes.highogs.csv"


def test_hsm_runs_eias_own_side_cases():
    assert levers.hsm_scedes(Policy(gas_supply=-1.0)) == LOW
    assert levers.hsm_scedes(Policy()) == REF
    assert levers.hsm_scedes(Policy(gas_supply=1.0)) == HIGH
    with pytest.raises(ValueError):   # HSM has no case between EIA's two
        levers.hsm_scedes(Policy(gas_supply=0.5))


def test_side_case_scedes_set_hsms_switch():
    from nems_open.paths import UPSTREAM
    for name, ogtech in ((LOW, "30"), (HIGH, "23"), (REF, "1")):
        f = Path(UPSTREAM) / "scedes" / name
        if not f.exists():
            pytest.skip("EIA's scedes files not available")
        rows = dict(line.split(",")[:2] for line in f.read_text().splitlines() if "," in line)
        assert rows["OGTECH"] == ogtech


def test_no_stand_in_price_scaling_under_hsm():
    class Supply:
        base = {"MPBLK/pngin": np.ones((11, 61))}
    p = Policy(gas_supply=1.0, start_year=START)
    assert levers.supply_shifts(p, Supply(), ogs="aimms") is None
    assert levers.supply_shifts(p, Supply(), ogs="hsm") is None


def test_grade_says_hsm_runs_the_case():
    assert levers.fidelity("gas_supply")[0] == levers.STAND_IN
    assert levers.fidelity("gas_supply", ogs="aimms")[0] == levers.PORTED
    assert "HSM" in levers.fidelity("gas_supply", ogs="hsm")[1]


def test_expected_ratio_is_the_case_over_hsms_reference(monkeypatch):
    calls = []

    def fake(gas, oil, scedes=REF, verbose=False):
        calls.append((gas is None, scedes))
        v = 2.0 if scedes == HIGH else 1.0
        return {"ogenagprd": np.full((7, 6, 61), v)}

    monkeypatch.setattr(couple, "production", fake)
    r = couple.expected_ratio(None, None, HIGH)
    assert np.allclose(r, 2.0)
    assert (True, HIGH) in calls and (True, REF) in calls


def test_aimms_cycle_one_starts_from_the_side_case(monkeypatch):
    from nems_open.ngmm import aimms
    seen = {}

    class Stop(Exception):
        pass

    def fake(gas, oil=None, case="cb2026", scedes=REF):
        seen["gas"], seen["scedes"] = gas, scedes
        raise Stop

    monkeypatch.setattr(aimms, "hsm_expected", fake)
    with pytest.raises(Stop):
        run_model.run(Policy(gas_supply=-1.0, start_year=START), START, END, ported=(), ogs="aimms")
    assert seen == {"gas": None, "scedes": LOW}


def test_aimms_rejects_a_weight_hsm_has_no_case_for():
    with pytest.raises(ValueError):
        run_model.run(Policy(gas_supply=0.5, start_year=START), START, END, ported=(), ogs="aimms")


def test_hsm_market_runs_the_side_case(monkeypatch):
    from nems_open.supply_standin.data import available
    if not available():
        pytest.skip("AEO2026 runs not available")
    calls = []

    def fake(gas, oil, scedes=REF, verbose=False):
        calls.append(scedes)
        v = 1.3 if scedes == HIGH else 1.0
        return {"ogenagprd": np.full((7, 6, 61), v), "ogngprd": np.zeros(61)}

    monkeypatch.setattr(couple, "production", fake)
    high = run_model.run(Policy(gas_supply=1.0, start_year=START), START, END, ported=(), ogs="hsm")
    assert calls[-1] == HIGH and REF in calls   # the run's own HSM call is the case; the yardstick is the reference
    calls.clear()
    ref = run_model.run(Policy(start_year=START), START, END, ported=(), ogs="hsm")
    assert set(calls) == {REF}
    j = START - 1990
    # 30% more expected production on the same prices clears the gas market lower
    assert high.gas["henry_hub"][j] < ref.gas["henry_hub"][j]


def test_showroom_tier_two_is_the_gas_resource_set():
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    sc = pytest.importorskip("showroom_scenarios")
    t = sc.TIERS[2]
    assert set(t) <= set(sc.BY_KEY) and len(t) == 7
    for k in t:
        args = sc.run_args(sc.BY_KEY[k])
        assert args["ogs"] == "aimms"
        assert levers.hsm_scedes(args["policy"]) in (LOW, HIGH)
