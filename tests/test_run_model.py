"""The full loop: demand and supply alternating each year until prices settle.

Default demand is the stub (every sector), so this runs in seconds. The ported modules
run through the same adapter when the demand runner and oracle dumps are present; that
check is opt-in (NEMS_SLOW=1) because commercial takes minutes per iteration.
"""

import os

import numpy as np
import pytest

from nems_open.demand_adapter import Policy
from nems_open.run_model import TOL, run
from nems_open.supply_standin.data import US, available, load_case

pytestmark = pytest.mark.skipif(not available(), reason="AEO2026 runs not available")

Y = slice(2030 - 1990, 2050 - 1990 + 1)


@pytest.fixture(scope="module")
def base():
    return load_case("cb2026")


@pytest.fixture(scope="module")
def no_policy():
    return run()


@pytest.fixture(scope="module")
def carbon50():
    return run(Policy(carbon_price=50.0))


def test_no_policy_reproduces_reference(no_policy, base):
    """With no levers, every year settles on EIA's reference prices, demand and CO2."""
    for k, v in no_policy.prices.items():
        np.testing.assert_allclose(v, base[k], rtol=1e-6, atol=1e-6, err_msg=k)
    for k in ("QBLK/qelrs", "QBLK/qngcm", "QBLK/qmgtr", "QBLK/qelas", "QBLK/qngas", "QBLK/qngel"):
        np.testing.assert_allclose(no_policy.quantities[k], base[k], rtol=1e-6, atol=1e-3, err_msg=k)
    assert all(p.number == 1 for p in no_policy.passes)


def test_every_year_converges(no_policy, carbon50):
    for r in (no_policy, carbon50):
        last = {}
        for p in r.passes:
            last[p.year] = p
        assert sorted(last) == list(range(2027, 2051))
        assert all(p.converged and p.max_price_change < TOL for p in last.values())
        assert max(p.number for p in r.passes) <= 12


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
    r = run(Policy(ev_share=1.0))
    assert np.all(r.quantities["QBLK/qmgtr"][US, Y] < base["QBLK/qmgtr"][US, Y])
    assert np.all(r.quantities["QBLK/qeltr"][US, Y] > base["QBLK/qeltr"][US, Y])
    j = 2050 - 1990
    gas_cut = base["QBLK/qmgtr"][US, j] - r.quantities["QBLK/qmgtr"][US, j]
    elec_add = r.quantities["QBLK/qeltr"][US, j] - base["QBLK/qeltr"][US, j]
    assert 0.2 < elec_add / gas_cut < 0.5  # EVs use about a third of the energy per mile


def test_building_efficiency(base):
    r = run(Policy(building_efficiency=0.8))
    j = 2040 - 1990
    for k in ("QBLK/qelrs", "QBLK/qngcm"):
        ratio = r.quantities[k][US, j] / base[k][US, j]
        assert 0.79 < ratio < 0.85, (k, ratio)  # 20% cut, a little rebound from lower prices
    assert np.all(r.quantities["QBLK/qngin"][US, Y] > base["QBLK/qngin"][US, Y])  # cheaper gas


@pytest.mark.skipif(os.environ.get("NEMS_SLOW") != "1", reason="set NEMS_SLOW=1 to run the ported modules")
def test_ported_residential_one_year(base):
    pytest.importorskip("nems_open.run_demand", reason="demand runner not merged into this branch")
    from nems_open import oracle_state
    if not oracle_state.available("yb_in", 41, "resd"):
        pytest.skip("residential oracle dumps not present")
    r = run(start_year=2030, end_year=2030, ported=("residential",))
    j = 2030 - 1990
    for k in ("MPBLK/pelrs", "MPBLK/pngrs"):
        assert abs(r.prices[k][US, j] / base[k][US, j] - 1) < 0.02, k
    for k in ("QBLK/qelrs", "QBLK/qngrs"):
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
