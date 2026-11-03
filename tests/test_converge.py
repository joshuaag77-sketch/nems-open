"""NEMS's integrating module (converge/): EIA's tables, test, relaxation and iteration control."""

import numpy as np
import pytest

from nems_open.converge import MAXITR, NRUNS, Control, Settings


def sequence(results, maxitr=MAXITR):
    """Run the control on a list of per-iteration test results: [(itr, fcrl, ctest)], stable."""
    c, out, it = Control(maxitr), [], iter(results)
    while c.next():
        r = next(it)
        out.append((c.itr, c.fcrl, r))
        c.done(r)
    return out, c.stable


def test_cb2026_settings():
    assert (MAXITR, NRUNS) == (2, 5)   # scedes.cb2026.csv


@pytest.mark.parametrize("results,expect,stable", [
    ([0, 1, 1], [(1, 0, 0), (2, 0, 1), (3, 1, 1)], True),       # converged, then held on the final loop
    ([0, 0, 1], [(1, 0, 0), (2, 0, 0), (3, 1, 1)], True),       # out of iterations: final loop anyway
    ([0, 0, 0], [(1, 0, 0), (2, 0, 0), (3, 1, 0)], False),
    ([0, 1, 0], [(1, 0, 0), (2, 0, 1), (3, 1, 0)], False),      # lost on the final loop, none left
])
def test_control_maxitr_2(results, expect, stable):
    assert sequence(results) == (expect, stable)


def test_control_final_loop_lost_and_regained():
    out, stable = sequence([0, 1, 0, 1, 1], maxitr=6)
    assert out == [(1, 0, 0), (2, 0, 1), (3, 1, 0), (4, 0, 1), (5, 1, 1)] and stable


def test_tables():
    s = Settings.load("conv")
    assert s.relax["MPBLK/pelrs"] == 0.5 and s.relax["MPBLK/pngrs"] == 1.0
    assert s.relax["QBLK/qngel"] == 0.8 and s.relax["QBLK/qelrs"] == 1.0
    assert s.match["MPBLK/pelrs"] == "QBLK/qelrs"
    assert "MPBLK/prsel" not in s.tested and "QBLK/qtpel" not in s.relax   # Test = -1, Relax = 0
    assert s.frac["QBLK/qh2in"] == 0.05 and s.abs["QBLK/qh2in"] == 20


def test_relaxation():
    s = Settings.load("conv")
    out = s.relaxed({"MPBLK/pelrs": np.array([10.0]), "QBLK/qngel": np.array([100.0])},
                    {"MPBLK/pelrs": np.array([12.0]), "QBLK/qngel": np.array([200.0]), "QBLK/xx": np.array([1.0])})
    assert out["MPBLK/pelrs"][0] == 11.0 and out["QBLK/qngel"][0] == 180.0 and out["QBLK/xx"][0] == 1.0


def _div(**kw):
    a = np.full(11, 50.0)
    for i, v in kw.items():
        a[int(i[1:])] = v
    return a


def test_quantity_test():
    s = Settings.load("conv")
    k = "QBLK/qelrs"
    big = {k: np.full(11, 2000.0)}
    assert not s.failing(big, {k: np.r_[2019.0, [2000.0] * 10]}, {}, {})      # 19 but under 1%
    assert s.failing(big, {k: np.r_[2030.0, [2000.0] * 10]}, {}, {}) == {k: pytest.approx(30 / 2015)}
    small = {k: np.full(11, 1.0)}
    assert not s.failing(small, {k: np.full(11, 1.5)}, {}, {})                # 50%, but under 10 trillion Btu
    assert not s.failing({k: _div()}, {k: _div(r9=500.0, r10=500.0)}, {}, {})  # only divisions 1-9 count


def test_price_test_needs_its_quantity():
    s = Settings.load("conv")
    p, q = "MPBLK/pelrs", "QBLK/qelrs"
    big, tiny = {q: np.full(11, 50.0)}, {q: np.full(11, 5.0)}
    old, new = {p: np.full(11, 10.0)}, {p: _div(r3=11.0)}
    assert s.failing(old, new, big, big)
    assert not s.failing(old, new, tiny, tiny)
    assert not s.failing(old, new, {}, {})   # quantity not carried: not tested


def test_any_any_quirk():
    """EIA takes any() on the fractional and absolute tests separately, as written."""
    s = Settings.load("conv")
    k = "QBLK/qelrs"
    old = np.array([1.0, 1000.0] + [50.0] * 9)
    new = np.array([1.5, 1009.0] + [50.0] * 9)   # division 1: 40% but 0.5; division 2: 9 but 0.9%
    assert not s.failing({k: old}, {k: new}, {}, {})   # 9 < 10: no absolute change reaches 10
    new[1] = 1010.0                                     # division 2 moves 10 (still under 1%)
    assert k in s.failing({k: old}, {k: new}, {}, {})   # fails, though no one division fails both
