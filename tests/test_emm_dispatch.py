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
    ("gen_coal", 2040): "coal 47% high: EIA runs 16 GW of CCS-retrofitted coal at 44% capacity factor in 2040 (87% before), the LP runs it at its maximum; "
                        "the restart has no per-unit retrofit years or CO2 transport cost to explain the step (docs/dispatch.md)",
    ("fuel_coal", 2040): "coal fuel 62% high, follows coal generation",
    ("fuel_coal", 2025): "coal fuel 12% high: EIA holds 2025 coal to the Short-Term Energy Outlook and burns it at 10.3 thousand Btu/kWh; plant-file heat rates give 10.7",
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


@pytest.mark.parametrize("year", YEARS)
def test_no_scarcity_prices(results, year):
    """Before the Pacific division stopped being double counted, three western regions ran short in 2025
    to 2030 and set the $1,000/MWh price. Wholesale prices should now be ordinary."""
    _, _, res = results[year]
    p = res.average_price()
    assert np.isfinite(p).all() and 5 < p.mean() < 30      # 1987$/MWh
    assert p.max() < 60
    assert res.unserved_twh.sum() < 0.001


@pytest.mark.parametrize("year", YEARS)
def test_residual_oil_comes_from_must_run_steam(results, snapshot, year):
    """EFD's minimum-run rows keep oil steam units at their historical capacity factor: about 20 trillion Btu
    of residual oil a year, steady, as in the reference run."""
    _, _, res = results[year]
    y = year - 1990
    ref = float(snapshot["UEFDOUT/uflrlnr"][:, :25, y].sum())
    assert abs(res.fuel_tbtu["residual"].sum() / ref - 1) < 0.25


def test_trade_none_uses_sales_based_load(snapshot):
    case = dispatch.build_case(snapshot, 2030, "none")
    ref = dispatch.build_case(snapshot, 2030, "reference")
    assert abs(case.net_load_twh.sum() / ref.net_load_twh.sum() - 1) < 0.05
    assert case.net_load_twh.shape == (25,)
