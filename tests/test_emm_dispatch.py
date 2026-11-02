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

# (quantity, year) -> why the dispatch model misses. Measured with sales-based load and interregional links.
KNOWN_MISSES = {
    ("gen_coal", 2040): "coal 47% high: EIA runs 16 GW of CCS-retrofitted coal at about 40% capacity factor, the LP runs it at its maximum; "
                        "EIA's 45Q credit lasts 12 years per unit and the LP applies it to all of them",
    ("fuel_coal", 2040): "coal fuel 64% high, follows coal generation",
    ("gen_gas", 2030): "gas generation 15% high: EIA's gas fleet runs less than the LP's, and coal and CCS take part of the load",
    ("gen_gas", 2040): "gas generation 12% high, same cause",
    ("gen_renewable", 2025): "2025 wind and solar 9% and 18% high against EIA with the same capacity and profiles; 2030 onward matches",
}


@pytest.fixture(scope="module")
def snapshot():
    return Snapshot()


@pytest.fixture(scope="module")
def results(snapshot):
    out = {}
    for y in YEARS:
        res = dispatch.solve(dispatch.build_case(snapshot, y, "none"))
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
    assert abs(total - case.net_load_twh.sum()) < 0.03 * case.net_load_twh.sum()      # trade losses and storage
    assert (res.price >= -1e-6).all()
    assert res.trade_twh.sum() > 0                  # regions do trade


def test_regional_marginal_cost_is_sane(results):
    _, _, res = results[2030]
    p = res.average_price()
    assert np.isfinite(p).all() and 5 < p.mean() < 100      # 1987$/MWh; a few regions run short in 2025 and 2030


def test_trade_none_uses_sales_based_load(snapshot):
    case = dispatch.build_case(snapshot, 2030, "none")
    ref = dispatch.build_case(snapshot, 2030, "reference")
    assert abs(case.net_load_twh.sum() / ref.net_load_twh.sum() - 1) < 0.05
    assert case.net_load_twh.shape == (25,)
