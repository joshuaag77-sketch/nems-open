"""The dispatch LP as the model's electricity supply (run_model elec="lp")."""

import numpy as np
import pytest

from nems_open import run_model
from nems_open.demand_adapter import Policy
from nems_open.paths import INPUT, REFERENCE_RUN
from nems_open.supply_standin import SupplyStandin
from nems_open.supply_standin.data import FIRST_YEAR, US

pytestmark = pytest.mark.skipif(
    not ((INPUT / "emm" / "emm_db" / "NEMS_INPUT.db").exists() and REFERENCE_RUN.exists()), reason="EMM inputs missing")

TOLERANCE = 0.10
YEARS = (2030, 2040, 2050)
# Known from the dispatch study (docs/dispatch.md): EIA holds CCS coal to about 40% capacity factor in 2040.
KNOWN_MISSES = {
    ("coal", 2040): "coal fuel 62% high in 2040 (docs/dispatch.md)",
    ("co2", 2050): "power CO2 11% low in 2050 against EMISSION/EMELC (which includes Alaska and Hawaii): gas fuel is 5% low and the LP captures a flat 90% at CCS plants",
}
FLOOR = 0.005          # a gap under 0.5% of power-sector fuel is not a miss (coal is nearly gone by 2050)


def one_year(year, carbon=0.0):
    return run_model.run(Policy(carbon, None, 1.0, year), year, year, elec="lp")


@pytest.fixture(scope="module")
def baseline():
    return SupplyStandin("cb2026").base


@pytest.fixture(scope="module")
def no_policy():
    return {y: one_year(y) for y in YEARS}


@pytest.fixture(scope="module")
def with_carbon():
    return one_year(2030, 50.0)


@pytest.mark.parametrize("year", YEARS)
@pytest.mark.parametrize("what", ["coal", "gas", "co2"])
def test_no_policy_lands_on_the_reference(no_policy, baseline, what, year, request):
    if (what, year) in KNOWN_MISSES:
        request.applymarker(pytest.mark.xfail(reason=KNOWN_MISSES[(what, year)] or "see docs/dispatch.md", strict=False))
    r, j = no_policy[year], year - FIRST_YEAR
    if what == "co2":
        got, want = r.co2["el"][US, j], baseline["EMISSION/emelc"][US, 0, j] * 44.0 / 12.0
    else:
        key = {"coal": "QBLK/qclel", "gas": "QBLK/qngel"}[what]
        got, want = r.quantities[key][US, j], baseline[key][US, j]
    scale = baseline["QBLK/qclel"][US, j] + baseline["QBLK/qngel"][US, j] if what != "co2" else want
    assert abs(got / want - 1.0) < TOLERANCE or abs(got - want) < FLOOR * scale, f"{what} {year}: {got:.0f} vs {want:.0f}"


def test_wholesale_cost_and_generation_come_back(no_policy):
    r, j = no_policy[2030], 2030 - FIRST_YEAR
    assert r.wholesale.shape == (25, 61) and np.isfinite(r.wholesale[:, j]).all()
    assert 5 < r.wholesale_us[j] < 100                  # 1987$/MWh; a few regions run short, see docs
    assert r.generation_twh["coal"][j] > 100 and r.generation_twh["gas_cc"][j] > 1000
    assert np.isnan(r.wholesale_us[j - 1])              # years that were not solved


def test_carbon_price_moves_coal_to_gas_and_cuts_co2(no_policy, with_carbon):
    j = 2030 - FIRST_YEAR
    a, b = no_policy[2030], with_carbon
    assert b.quantities["QBLK/qclel"][US, j] < 0.5 * a.quantities["QBLK/qclel"][US, j]
    assert b.quantities["QBLK/qngel"][US, j] > 1.1 * a.quantities["QBLK/qngel"][US, j]
    assert b.co2["el"][US, j] < 0.85 * a.co2["el"][US, j]
    assert b.wholesale_us[j] > a.wholesale_us[j]
    assert b.prices["MPBLK/pelas"][US, j] > a.prices["MPBLK/pelas"][US, j]       # the stand-in adds the carbon cost to retail


def test_standin_can_take_power_fuel_from_outside():
    s = SupplyStandin("cb2026")
    j = 2030 - FIRST_YEAR
    fuel = s.base["QBLK/qclel"].copy()
    fuel[:, j] *= 0.5
    out = s.solve(power_fuel={"QBLK/qclel": fuel})
    assert np.allclose(out.power_fuel["QBLK/qclel"][:, j], fuel[:, j])
    assert out.prices["MPBLK/pclel"][US, j] != s.solve().prices["MPBLK/pclel"][US, j]    # coal price responds to coal burn


def test_elec_switch_is_validated():
    with pytest.raises(ValueError):
        run_model.run(Policy(), 2030, 2030, elec="nope")
    with pytest.raises(ValueError):
        run_model.run(Policy(), 2030, 2030, baseline="hm2026", elec="lp")
