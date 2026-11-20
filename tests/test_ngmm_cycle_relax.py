"""HSM's expected production is relaxed between cycles under ogs="aimms", and a year whose wellhead price still moved
between the last two cycles is not counted as settled. AIMMS and HSM are stubbed."""
import numpy as np
import pytest

from nems_open import run_model
from nems_open.demand_adapter import Policy
from nems_open.ngmm import aimms

START = END = 2030
J = START - 1990


def test_relax_takes_the_weight_of_the_move():
    prev = {"ogsmout/ogenagprd": np.full((3, 61), 10.0)}
    new = {"ogsmout/ogenagprd": np.full((3, 61), 5.0)}
    out = aimms.relax_expected(prev, new, weight=0.4)
    assert np.allclose(out["ogsmout/ogenagprd"], 8.0)
    assert np.allclose(prev["ogsmout/ogenagprd"], 10.0)   # inputs untouched


def test_relax_from_nothing_starts_at_cb2026():
    from nems_open.supply_standin.data import available, restart_path
    if not available():
        pytest.skip("AEO2026 runs not available")
    with np.load(restart_path("cb2026"), allow_pickle=False) as z:
        base = z["OGSMOUT/ogenagprd"].astype(np.float64)
    out = aimms.relax_expected(None, {"ogsmout/ogenagprd": base * 0.5}, weight=0.4)
    assert np.allclose(out["ogsmout/ogenagprd"], base * 0.8)


def test_cycle_change_is_the_log_move():
    before, after = np.ones(61), np.ones(61)
    after[J] = 1.79
    before[J + 1] = 0.0   # no price: no change counted
    c = aimms.cycle_change(before, after)
    assert c[J] == pytest.approx(np.log(1.79))
    assert c[J + 1] == 0.0 and c[:J].max() == 0.0


def test_the_weight_damps_a_cobweb_with_gain_two():
    """The 2026-11-19 reference: a 27% price cut came back as a 79% rise, a loop gain of about 2. Taking all of
    HSM's answer each cycle diverges; the weight converges."""
    gain = 2.0
    hsm = lambda x: 1.0 - gain * (x - 1.0)   # expected production answering the price the last cycle produced
    def gap(weight, cycles):
        x = 0.8
        for _ in range(cycles):
            x = x + weight * (hsm(x) - x)
        return abs(x - 1.0)
    assert gap(1.0, 4) == pytest.approx(0.2 * 2 ** 4)   # undamped: the gap doubles each cycle
    assert gap(aimms.HSM_RELAX, 4) == pytest.approx(0.2 * 0.2 ** 4)   # damped: a fifth each cycle


class FakeGas:
    """Stands in for AimmsGas: wellhead ratio by cycle, prices left to the stand-in."""
    made = []
    ratios = {1: 0.75, 2: 1.20}

    def __init__(self, start_year, expected=None, cycle=1, lng=None):
        FakeGas.made.append((cycle, expected))
        self.cycle, self.seconds = cycle, 0.0
        self.henry_hub = np.full(61, 3.0)

    def begin(self, *a, **k):
        pass

    def prices(self, qngas_us=None):
        return {}

    def end_year(self, year):
        pass

    def close(self):
        pass

    def wellhead_ratio(self):
        return np.full(61, FakeGas.ratios[self.cycle])


def test_run_relaxes_hsm_and_flags_a_moving_price(monkeypatch):
    from nems_open.supply_standin.data import available
    if not available():
        pytest.skip("AEO2026 runs not available")
    FakeGas.made.clear()
    monkeypatch.setattr(aimms, "AimmsGas", FakeGas)
    monkeypatch.setattr(aimms, "hsm_expected", lambda gas, oil=None, case="cb2026", scedes=None:
                        {"ogsmout/ogenagprd": np.full((3, 61), 5.0)})
    monkeypatch.setattr(aimms, "relax_expected", lambda prev, new, weight=aimms.HSM_RELAX, case="cb2026":
                        {k: 10.0 + weight * (v - 10.0) for k, v in new.items()})
    r = run_model.run(Policy(start_year=START), START, END, ported=(), ogs="aimms", cycles=2)
    assert [c for c, _ in FakeGas.made] == [1, 2]
    assert FakeGas.made[0][1] is None
    assert np.allclose(FakeGas.made[1][1]["ogsmout/ogenagprd"], 10.0 + aimms.HSM_RELAX * (5.0 - 10.0))
    assert r.gas["cycle_change"][J] == pytest.approx(np.log(1.20 / 0.75))
    assert r.stable[START] is False
