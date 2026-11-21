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
    ("gen_coal", 2040): "coal 47% high: EIA runs 16 GW of CCS-retrofitted coal at 44% capacity factor (every year from 2033), the LP runs it at "
                        "its 65% maximum; EIA's coal units run at 42-48% in every year 2028-2040 for a reason not found in saved outputs "
                        "(docs/dispatch.md, coal capacity factor)",
    ("fuel_coal", 2040): "coal fuel 62% high, follows coal generation",
    ("fuel_coal", 2025):"coal fuel 12% high: EIA holds 2025 coal to the Short-Term Energy Outlook and burns it at 10.3 thousand Btu/kWh; plant-file heat rates give 10.7",
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


def test_eia_coal_units_run_below_their_maximum(snapshot):
    """What EFD reports for coal. UGENSQ (CCS retrofits) is a subset of UGENPC, like UCAPSQ of UCAPCS: in 2040 both are
    63 TWh and so is coal generation by fuel (UGNCLNR). Coal by fuel also holds the coal share of the cofired units
    (UGENNG). EIA's coal units (pc + ig) run at 42-48% of mid-year capacity from 2028 (2032 aside), below EFD's 0.65 maximum, while
    the dispatch LP runs them at the maximum (docs/dispatch.md)."""
    def gen(t, year):
        return float(snapshot[f"UDATOUT/ugen{t}"][:dispatch.NUM_R, year - 1990].sum())
    by_fuel = {y: rep.reference(snapshot, y)["gen_coal"] for y in (2031, 2040)}
    assert abs(gen("pc", 2040) - by_fuel[2040]) < 1.0 and abs(gen("sq", 2040) - by_fuel[2040]) < 1.0
    units = gen("pc", 2031) + gen("ig", 2031)
    assert 340 < units < 365 and 410 < by_fuel[2031] < 430          # 353 from coal units, 66 from cofiring
    for y in (2031, 2035, 2040):
        cap = float(dispatch._in_service(snapshot, dispatch.CAPACITY_PREFIXES["coal"], dispatch.EXISTING_TYPES["coal"], y).sum())
        cf = (gen("pc", y) + gen("ig", y)) / cap / 8.76
        assert 0.40 < cf < 0.53, (y, cf)


def test_undated_retirements_leave_for_the_whole_year(snapshot):
    """ECP dates an economic retirement in year Y to December of Y - 1 (uecp.f 27095-27098), so coal EMM retires
    itself is gone for all of Y: 2031 coal is near year-end capacity (78 GW), not the 2030-2031 midpoint (83)."""
    y = 2031 - 1990
    p, types = dispatch.CAPACITY_PREFIXES["coal"], dispatch.EXISTING_TYPES["coal"]
    end, mid = dispatch._ucap(snapshot, p, y).sum(), dispatch._ucap_mid(snapshot, p, y).sum()
    now = dispatch._in_service(snapshot, p, types, 2031).sum()
    assert end - 0.5 < now < end + 3.0 < mid
