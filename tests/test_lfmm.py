"""The LFMM stand-in against EIA's AEO2026 cases, and wired into the loop.

On its own baseline it returns EIA's product prices and refinery fuel exactly. Fed a case's
end-use demand, Brent and gas price, it lands within the tolerances below (largest US error
2027-2050, percent; docs/lfmm_fit.md has every case). It moves the right way on crude and demand.
"""

import numpy as np
import pytest

from nems_open.lfmm import LfmmStandin
from nems_open.lfmm.fit import errors
from nems_open.lfmm.standin import PRODUCTS
from nems_open.supply_standin.data import US, available, load_case

pytestmark = pytest.mark.skipif(not available(), reason="AEO2026 runs not available")

DEMAND_CASES = ["hm2026", "lm2026", "higheldmd", "highztc", "lowztc", "altelec"]
# Demand-side cases: prices within 5%, total refinery energy within 3%.
TOLERANCE = {"mg": 5, "ds": 5, "jf": 5, "rs": 5, "ts": 3, "tp": 5, "el": 7}
# The oil and gas supply cases (Brent -15% / +23%) and the transport case: looser, as stated in the fit report.
WIDE = {"highogs": {"mg": 7, "ds": 5, "jf": 10, "rs": 5, "ts": 8},
        "lowogs": {"mg": 16, "ds": 5, "jf": 10, "rs": 6, "ts": 3},
        "electrnp": {"mg": 4, "ds": 7, "jf": 9, "rs": 6, "ts": 4}}


@pytest.fixture(scope="module")
def model():
    return LfmmStandin("cb2026")


def test_baseline_exact(model):
    base = model.base
    r = model.solve()
    for k, v in r.prices.items():
        np.testing.assert_allclose(v, base[k], rtol=1e-12)
    for k, v in r.refinery.items():
        np.testing.assert_allclose(v, base[k], rtol=1e-6, atol=1e-6)
    for k, v in r.industry.items():
        np.testing.assert_allclose(v, base[k], rtol=1e-6, atol=1e-6)
    assert {"MPBLK/pmgtr", "MPBLK/pdstr", "MPBLK/pjftr", "MPBLK/prltr", "MPBLK/prhtr"} <= set(r.prices)


@pytest.mark.parametrize("case", DEMAND_CASES)
def test_demand_cases(model, case):
    err = errors(model, case)
    for k, tol in TOLERANCE.items():
        assert err[k] < tol, (case, k, err[k])


@pytest.mark.parametrize("case", list(WIDE))
def test_supply_and_transport_cases(model, case):
    err = errors(model, case)
    for k, tol in WIDE[case].items():
        assert err[k] < tol, (case, k, err[k])


def test_refinery_adds_up(model):
    z = load_case("electrnp")
    r = model.solve(z, z["INTOUT/brent_price"], z["MPBLK/pngin"][US])
    total = sum(r.refinery[f"QBLK/q{f}rf"] for f in ("el", "ng", "tp")) + model.base["QBLK/qclrf"] + model.base["QBLK/qbmrf"]
    np.testing.assert_allclose(total, r.refinery["QBLK/qtsrf"], rtol=1e-6, atol=1e-3)


def test_responds_to_crude_and_demand(model):
    base = model.base
    j = 2040 - 1990
    up = model.solve(brent=base["INTOUT/brent_price"] * 1.2)
    for p in PRODUCTS:
        name = PRODUCTS[p][2]
        assert up.prices[name][US, j] > base[name][US, j]
    # Dollar for dollar per barrel of gasoline.
    d = (up.prices["MPBLK/pmgtr"] - base["MPBLK/pmgtr"])[US, j]
    assert d == pytest.approx(0.2 * base["INTOUT/brent_price"][j] / PRODUCTS["mg"][1], rel=1e-9)
    low = {k: base[k] * 0.7 for k in base if k.startswith("QBLK/qmg")}
    r = model.solve(low)
    assert r.prices["MPBLK/pmgtr"][US, j] < base["MPBLK/pmgtr"][US, j]
    assert r.refinery["QBLK/qtsrf"][US, j] < base["QBLK/qtsrf"][US, j]
    assert r.industry["QBLK/qngin"][US, j] < base["QBLK/qngin"][US, j]


def test_run_lfmm_baseline_and_ev():
    from nems_open.demand_adapter import Policy
    from nems_open.run_model import run
    off = run(ported=(), start_year=2027, end_year=2030)
    on = run(ported=(), start_year=2027, end_year=2030, lfmm="standin")
    j = 2030 - 1990
    for k in ("MPBLK/pmgtr", "MPBLK/pdstr", "MPBLK/pjftr", "MPBLK/prltr"):
        assert on.prices[k][US, j] == pytest.approx(off.prices[k][US, j], rel=1e-5)
    assert on.quantities["QBLK/qtsrf"][US, j] == pytest.approx(off.quantities["QBLK/qtsrf"][US, j], rel=1e-5)
    assert "LFMM stand-in" in on.passes[-1].routines
    ev = run(Policy(ev_share=0.9, start_year=2027), ported=(), start_year=2027, end_year=2030, lfmm="standin")
    assert ev.quantities["QBLK/qtsrf"][US, j] < on.quantities["QBLK/qtsrf"][US, j]
    assert ev.prices["MPBLK/pmgtr"][US, j] < on.prices["MPBLK/pmgtr"][US, j]
    assert all(p.converged for p in ev.passes if p.fcrl == 1)
    with pytest.raises(ValueError):
        run(ported=(), start_year=2027, end_year=2027, lfmm="lp")
