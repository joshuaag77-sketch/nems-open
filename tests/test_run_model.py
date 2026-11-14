"""The full loop: demand and supply alternating each year until prices settle.

These tests put every sector on the stub (ported=()), so they run in seconds. The default
(residential and commercial through EIA's ported modules) is checked in one year below, and
over 2027-2050 when NEMS_SLOW=1.
"""

import os

import numpy as np
import pytest

from nems_open.demand_adapter import Policy
from nems_open.run_model import DEFAULT_MAXITR, run
from nems_open.supply_standin.data import US, available, load_case

pytestmark = pytest.mark.skipif(not available(), reason="AEO2026 runs not available")

Y = slice(2030 - 1990, 2050 - 1990 + 1)


@pytest.fixture(scope="module")
def base():
    return load_case("cb2026")


@pytest.fixture(scope="module")
def no_policy():
    return run(ported=())


@pytest.fixture(scope="module")
def carbon50():
    return run(Policy(carbon_price=50.0), ported=())


def test_no_policy_reproduces_reference(no_policy, base):
    """With no levers, every year settles on EIA's reference prices, demand and CO2."""
    for k, v in no_policy.prices.items():
        np.testing.assert_allclose(v, base[k], rtol=1e-6, atol=1e-6, err_msg=k)
    for k in ("QBLK/qelrs", "QBLK/qngcm", "QBLK/qmgtr", "QBLK/qelas", "QBLK/qngas", "QBLK/qngel"):
        np.testing.assert_allclose(no_policy.quantities[k], base[k], rtol=1e-6, atol=1e-3, err_msg=k)
    # EIA's control: iteration 1 is untested, 2 passes and sets FCRL, 3 (the final loop) passes again
    assert [(p.number, p.fcrl, p.converged) for p in no_policy.passes if p.year == 2030] ==         [(1, 0, False), (2, 0, True), (3, 1, True)]


def test_every_year_converges(no_policy, carbon50):
    for r in (no_policy, carbon50):
        last = {}
        for p in r.passes:
            last[p.year] = p
        assert sorted(last) == list(range(2027, 2051))
        assert all(p.converged and p.fcrl == 1 for p in last.values())
        assert all(r.stable[y] for y in last)
        assert max(p.number for p in r.passes) <= DEFAULT_MAXITR + 1


def test_carbon_price_raises_prices(carbon50, base):
    for k in ("MPBLK/pelrs", "MPBLK/pngrs", "MPBLK/pngin", "MPBLK/pmgtr", "MPBLK/pdstr", "MPBLK/pclel"):
        assert np.all(carbon50.prices[k][US, Y] > base[k][US, Y]), k


def test_carbon_price_cuts_demand_and_co2(carbon50, no_policy, base):
    for k in ("QBLK/qngrs", "QBLK/qngcm", "QBLK/qngin", "QBLK/qmgtr", "QBLK/qelas", "QBLK/qngas"):
        assert np.all(carbon50.quantities[k][US, Y] < base[k][US, Y]), k
    assert np.all(carbon50.co2_total[Y] < no_policy.co2_total[Y])


def test_feedback_pulls_prices_back(carbon50, base):
    """Lower demand lowers the supply curve's price: the converged gas price sits below
    the reference plus the carbon adder alone."""
    from nems_open.supply_standin import SupplyStandin
    adder_only = SupplyStandin().solve(carbon_price=Policy(50.0).carbon()).prices["MPBLK/pngin"]
    assert np.all(carbon50.prices["MPBLK/pngin"][US, Y] < adder_only[US, Y])


def test_ev_share_moves_gasoline_to_electricity(base):
    r = run(Policy(ev_share=1.0), ported=())
    assert np.all(r.quantities["QBLK/qmgtr"][US, Y] < base["QBLK/qmgtr"][US, Y])
    assert np.all(r.quantities["QBLK/qeltr"][US, Y] > base["QBLK/qeltr"][US, Y])
    j = 2050 - 1990
    gas_cut = base["QBLK/qmgtr"][US, j] - r.quantities["QBLK/qmgtr"][US, j]
    elec_add = r.quantities["QBLK/qeltr"][US, j] - base["QBLK/qeltr"][US, j]
    assert 0.2 < elec_add / gas_cut < 0.5  # EVs use about a third of the energy per mile


def test_building_efficiency(base):
    r = run(Policy(building_efficiency=0.8), ported=())
    j = 2040 - 1990
    for k in ("QBLK/qelrs", "QBLK/qngcm"):
        ratio = r.quantities[k][US, j] / base[k][US, j]
        assert 0.79 < ratio < 0.85, (k, ratio)  # 20% cut, a little rebound from lower prices
    assert np.all(r.quantities["QBLK/qngin"][US, Y] > base["QBLK/qngin"][US, Y])  # cheaper gas


def test_ported_residential_one_year(base):
    """One year with residential through EIA's port (2030: from the oracle's dump if present, else from the files)."""
    r = run(start_year=2030, end_year=2030, ported=("residential",))
    j = 2030 - 1990
    for k in ("MPBLK/pelrs", "MPBLK/pngrs"):
        assert abs(r.prices[k][US, j] / base[k][US, j] - 1) < 0.02, k
    for k in ("QBLK/qelrs", "QBLK/qngrs"):
        assert abs(r.quantities[k][US, j] / base[k][US, j] - 1) < 0.01, k


@pytest.mark.skipif(os.environ.get("NEMS_SLOW") != "1", reason="set NEMS_SLOW=1 to run the default model 2027-2050")
def test_default_runs_ported_modules_in_two_minutes(base):
    import time
    from nems_open.run_model import PORTED
    from nems_open import oracle_state
    if not oracle_state.available("sd_in", 38):
        pytest.skip("commercial oracle dumps not present")
    t = time.perf_counter()
    r = run()
    took = time.perf_counter() - t
    assert set(PORTED) == {"residential", "commercial"}
    assert {"residential", "commercial"} <= set(r.passes[0].routines)  # not on the stub
    assert took < 120, took
    j = 2050 - 1990
    for k in ("QBLK/qelrs", "QBLK/qngrs", "QBLK/qelcm", "QBLK/qngcm"):
        assert abs(r.quantities[k][US, j] / base[k][US, j] - 1) < 0.01, k


@pytest.mark.parametrize("case", ["highogs", "lowogs", "lowztc"])
def test_stub_demand_on_eia_prices(base, case):
    """Fed a price-driven case's own prices, the stub's fitted elasticities land near
    EIA's own demand for that case (US, 2030-2050). GDP is held at the reference, which
    is small in these cases."""
    from nems_open.demand_adapter import StubSector
    z = load_case(case)
    prices = {k: v for k, v in z.items() if k.startswith("MPBLK/")}
    worst = {}
    for sfx, fuels in {"rs": ("el", "ng"), "cm": ("el", "ng"), "in": ("el", "ng")}.items():
        stub = StubSector(sfx, base)
        for j in range(2025 - 1990, 2051 - 1990):
            out = stub.solve(j, prices, {})
            stub.end_year()
            if j >= 2030 - 1990:
                for f in fuels:
                    k = f"QBLK/q{f}{sfx}"
                    e = abs(out[k][:9].sum() / z[k][US, j] - 1)
                    worst[k] = max(worst.get(k, 0), e)
    # Buildings within 4%. Industry within 8%: in the gas supply cases cheap gas also
    # grows industrial output, which an own-price elasticity cannot carry.
    tol = lambda k: 0.08 if k.endswith("in") else 0.04
    bad = {k: round(100 * v, 1) for k, v in worst.items() if v > tol(k)}
    assert not bad, bad


@pytest.mark.skipif(os.environ.get("NEMS_SLOW") != "1", reason="set NEMS_SLOW=1 to run transportation's port (about 25 s an iteration)")
def test_three_ported_sectors_one_year(base):
    """Residential, commercial and transportation through EIA's ports in one year of the loop."""
    from nems_open.run_demand import TransportationSector
    from nems_open.run_model import PORTED
    if not TransportationSector.dumped(2030):
        pytest.skip("transportation oracle dump for 2030 not present (a start from files takes about 40 min)")
    r = run(start_year=2030, end_year=2030, ported=PORTED + ("transportation",))
    assert {"residential", "commercial", "transportation"} <= set(r.passes[0].routines)
    j = 2030 - 1990
    for k in ("QBLK/qelrs", "QBLK/qngcm", "QBLK/qmgtr", "QBLK/qjftr"):
        assert abs(r.quantities[k][US, j] / base[k][US, j] - 1) < 0.005, k
