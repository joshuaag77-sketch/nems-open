"""The supply stand-in against EIA's AEO2026 cases.

On its own baseline it must return EIA's prices and CO2 exactly. Fed a demand-side
case's end-use demand, it must land within the stated tolerances of EIA's prices.
Tolerances are the largest error over 2027-2050, percent; see docs/supply_standin.md.
"""

import numpy as np
import pytest

from nems_open.supply_standin import SupplyStandin
from nems_open.supply_standin.data import CASES, US, available, load_case
from nems_open.supply_standin.fit import eia_co2
from nems_open.supply_standin.model import DEMAND_SECTORS

pytestmark = pytest.mark.skipif(not available(), reason="AEO2026 runs not available")

YEARS = slice(2027 - 1990, 2050 - 1990 + 1)
DEMAND_CASES = ["hm2026", "lm2026", "higheldmd"]

# Largest US error 2027-2050 (percent) for a demand-side case fed through the reference.
US_TOLERANCE = {
    "MPBLK/pelrs": 3, "MPBLK/pelcm": 3, "MPBLK/pelin": 4, "MPBLK/pelas": 3,
    "MPBLK/pngrs": 2, "MPBLK/pngcm": 3, "MPBLK/pngin": 5, "MPBLK/pngel": 6,
    "MPBLK/pmgtr": 4, "MPBLK/pdstr": 4, "MPBLK/pjftr": 3, "MPBLK/pdsrs": 4, "MPBLK/plgrs": 3,
}
REGIONAL_TOLERANCE = {"MPBLK/pelrs": 10, "MPBLK/pelcm": 10, "MPBLK/pngrs": 4, "MPBLK/pmgtr": 5}
CO2_TOLERANCE = 1.5


def end_use_demand(case):
    z = load_case(case)
    return {k: v for k, v in z.items() if k.startswith("QBLK/q") and k[-2:] in DEMAND_SECTORS}


def pct_err(model, eia):
    ok = eia > 0
    return 100 * np.max(np.abs(model[ok] / eia[ok] - 1)) if ok.any() else 0.0


@pytest.fixture(scope="module")
def ref():
    return SupplyStandin("cb2026")


@pytest.mark.parametrize("case", list(CASES))
def test_baseline_reproduces_itself(case):
    """Any case as baseline, with its own demand, gives back EIA's prices and CO2."""
    model = SupplyStandin(case)
    z = load_case(case)
    r = model.solve(end_use_demand(case))
    for name in (k for k in z if k.startswith("MPBLK/")):
        np.testing.assert_array_equal(r.prices[name], z[name], err_msg=name)
    np.testing.assert_allclose(r.co2_total, eia_co2(z), rtol=1e-9, atol=1e-9)
    for name, q in r.power_fuel.items():
        np.testing.assert_array_equal(q, z[name], err_msg=name)


def test_no_inputs_is_reference(ref):
    r = ref.solve()
    base = load_case("cb2026")
    for name in (k for k in base if k.startswith("MPBLK/")):
        np.testing.assert_array_equal(r.prices[name], base[name], err_msg=name)


@pytest.mark.parametrize("case", DEMAND_CASES)
def test_demand_cases_us_prices(ref, case):
    z = load_case(case)
    r = ref.solve(end_use_demand(case), brent=z["INTOUT/brent_price"])
    errors = {n: pct_err(r.prices[n][US, YEARS], z[n][US, YEARS]) for n in US_TOLERANCE}
    bad = {n: round(e, 2) for n, e in errors.items() if e > US_TOLERANCE[n]}
    assert not bad, bad


@pytest.mark.parametrize("case", DEMAND_CASES)
def test_demand_cases_regional_prices(ref, case):
    z = load_case(case)
    r = ref.solve(end_use_demand(case), brent=z["INTOUT/brent_price"])
    bad = {}
    for n, tol in REGIONAL_TOLERANCE.items():
        e = pct_err(r.prices[n][:9, YEARS], z[n][:9, YEARS])
        if e > tol:
            bad[n] = round(e, 2)
    assert not bad, bad


@pytest.mark.parametrize("case", DEMAND_CASES)
def test_demand_cases_co2(ref, case):
    z = load_case(case)
    r = ref.solve(end_use_demand(case), brent=z["INTOUT/brent_price"])
    assert pct_err(r.co2_total[YEARS], eia_co2(z)[YEARS]) < CO2_TOLERANCE


def test_crude_pass_through_out_of_sample(ref):
    """The oil and gas supply cases are not in the fit. Brent alone (their own demand,
    crude passed through dollar for dollar) should bring refined products within 10%."""
    for case in ("highogs", "lowogs"):
        z = load_case(case)
        r = ref.solve(end_use_demand(case), brent=z["INTOUT/brent_price"])
        for n in ("MPBLK/pdstr", "MPBLK/pjftr", "MPBLK/pdsrs"):
            assert pct_err(r.prices[n][US, YEARS], z[n][US, YEARS]) < 10, (case, n)


def test_carbon_price(ref):
    """$50/t CO2 (2024 $) adds the carbon content of each fuel to its price."""
    base = load_case("cb2026")
    r0, r = ref.solve(), ref.solve(carbon_price=50.0)
    to87 = base["MACOUT/mc_jpgdp"][2024 - 1987] / base["MACOUT/mc_jpgdp"][0]
    expect = 50.0 / to87 * base["EMEBLK/engrs"] * 44 / 12 / 1000  # 1987 $/MMBtu
    np.testing.assert_allclose(r.carbon_adders["MPBLK/pngrs"],
                               np.broadcast_to(expect, (11, 61)) * (base["MPBLK/pngrs"] > 0))
    # The delivered price moves by about the adder. Later, power plants burn less gas
    # and the gas price before carbon falls a little; early, while coal still runs,
    # coal switches to gas and it rises a little.
    rise = (r.prices["MPBLK/pngrs"] - r0.prices["MPBLK/pngrs"])[US, YEARS]
    assert np.all(rise > 0.8 * expect[YEARS]) and np.all(rise < 1.05 * expect[YEARS])
    # Electricity carries the power sector's average CO2 per unit sold.
    assert np.all(r.prices["MPBLK/pelrs"][US, YEARS] > r0.prices["MPBLK/pelrs"][US, YEARS])
    # Coal goes up more per MMBtu than gas.
    assert np.all(r.carbon_adders["MPBLK/pclin"][US, YEARS] > r.carbon_adders["MPBLK/pngin"][US, YEARS])


def test_carbon_price_switches_power_plants(ref):
    """A carbon price cuts coal burn hard, moves some of it to gas, and cuts power CO2."""
    base = load_case("cb2026")
    r0, r = ref.solve(), ref.solve(carbon_price=100.0)
    y = slice(2027 - 1990, 2035 - 1990 + 1)  # years with real coal burn
    coal = r.power_fuel["QBLK/qclel"][US, y] / base["QBLK/qclel"][US, y]
    gas = r.power_fuel["QBLK/qngel"][US, y] / base["QBLK/qngel"][US, y]
    assert np.all(coal < 0.7) and np.all(coal < gas)
    assert np.all(r.co2["el"][US, YEARS] < 0.9 * r0.co2["el"][US, YEARS])
    # Fixed point: more carbon, less power-sector CO2.
    co2 = [ref.solve(carbon_price=c).co2["el"][US, 2050 - 1990] for c in (0, 50, 100, 200)]
    assert co2 == sorted(co2, reverse=True)


def test_more_electricity_demand_raises_gas_and_power_prices(ref):
    base = load_case("cb2026")
    demand = {"QBLK/qelrs": base["QBLK/qelrs"] * 1.10}
    r = ref.solve(demand)
    assert np.all(r.power_fuel["QBLK/qngel"][US, YEARS] > base["QBLK/qngel"][US, YEARS])
    assert np.all(r.prices["MPBLK/pngin"][US, YEARS] > base["MPBLK/pngin"][US, YEARS])
    assert np.all(r.prices["MPBLK/pelrs"][US, YEARS] > base["MPBLK/pelrs"][US, YEARS])
    assert np.all(r.co2["el"][US, YEARS] > ref.solve().co2["el"][US, YEARS])
