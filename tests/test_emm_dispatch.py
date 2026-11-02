"""Dispatch LP against the AEO2026 reference run, 2025, 2030, 2040 and 2050.

Each year and quantity is its own test, so every year is reported even where it misses.
A miss is more than 10% off EIA (and more than 0.5% of the national total, see
dispatch_report.is_miss). Misses we know about are marked xfail with the reason; if one gets
fixed the test XPASSes and strict mode makes that visible.
"""

import numpy as np
import pytest

from nems_open.emm import dispatch, dispatch_report as rep
from nems_open.paths import INPUT, REFERENCE_RUN
from nems_open.snapshot import Snapshot

pytestmark = pytest.mark.skipif(
    not ((INPUT / "emm" / "emm_db" / "NEMS_INPUT.db").exists() and REFERENCE_RUN.exists()), reason="EMM inputs missing")

YEARS = (2025, 2030, 2040, 2050)

# (quantity, year) -> why the dispatch model misses. Measured with trade="reference".
KNOWN_MISSES = {
    ("gen_coal", 2030): "coal 11% low: EIA keeps more coal running than a pure merit order, from contracts and unit commitment",
    ("gen_coal", 2040): "coal 80% high: EIA runs 63 TWh from 16 GW of coal, about 44% capacity factor; the LP runs it flat out",
    ("gen_gas", 2030): "gas generation 15% high: the LP gives gas the load coal and CCS plants do not take",
    ("gen_gas", 2040): "gas generation 13% high, same cause",
    ("gen_gas", 2050): "gas generation 14% high: EIA dispatches 100+ TWh of CCS and advanced gas that carry another label",
    ("gen_renewable", 2025): "2025 renewables 11% high: year-end capacity and other-renewable output overstate a year still building",
    ("fuel_coal", 2030): "coal fuel 10% low, follows coal generation",
    ("fuel_coal", 2040): "coal fuel 40% high, follows coal generation",
    ("fuel_gas", 2025): "gas fuel 12% low: EIA burns more gas per kWh (part-load heat rates, oil/gas dual units) than plant-file heat rates",
    ("co2", 2040): "CO2 21% high, follows coal generation",
}


@pytest.fixture(scope="module")
def snapshot():
    return Snapshot()


@pytest.fixture(scope="module")
def results(snapshot):
    out = {}
    for y in YEARS:
        res = dispatch.solve(dispatch.build_case(snapshot, y, "reference"))
        out[y] = (rep.model(res), rep.reference(snapshot, y), res)
    return out


@pytest.mark.parametrize("year", YEARS)
@pytest.mark.parametrize("key", sorted(rep.SCORED))
def test_against_reference(results, request, key, year):
    if (key, year) in KNOWN_MISSES:
        request.applymarker(pytest.mark.xfail(reason=KNOWN_MISSES[(key, year)], strict=True))
    m, r, _ = results[year]
    assert not rep.is_miss(key, m, r), f"{key} {year}: model {m[key]:.0f}, EIA {r[key]:.0f}"


@pytest.mark.parametrize("year", YEARS)
def test_solution_is_sound(results, year):
    _, _, res = results[year]
    case = res.case
    assert res.status == "ok:optimal"
    assert res.unserved_twh.sum() < 0.002 * case.net_load_twh.sum()
    assert res.spilled_twh.sum() < 0.02 * case.net_load_twh.sum()
    # No group runs above its capacity.
    for g in dispatch.THERMAL:
        assert (res.generation_twh[g] <= case.capacity[g] * 8.76 + 1e-6).all()
    # Generation meets load: thermal + hydro + renewables + nuclear + storage = net load (+ spill removed).
    total = res.total_generation_twh()
    assert abs(total - case.net_load_twh.sum()) < 0.01 * case.net_load_twh.sum()
    assert (res.price >= -1e-6).all()


def test_regional_marginal_cost_is_sane(results):
    _, _, res = results[2030]
    p = res.average_price()
    assert np.isfinite(p).all() and 5 < p.mean() < 60       # 1987$/MWh


def test_trade_none_uses_sales_based_load(snapshot):
    case = dispatch.build_case(snapshot, 2030, "none")
    ref = dispatch.build_case(snapshot, 2030, "reference")
    assert abs(case.net_load_twh.sum() / ref.net_load_twh.sum() - 1) < 0.05
    assert case.net_load_twh.shape == (25,)
