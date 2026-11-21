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


def test_efd_outage_rates_follow_udat_rule():
    """udat.f 10168-10236: FOR and PMR scaled by one factor so that (1 - FOR)(1 - PMR) is the maximum capacity factor.
    The 2030 composite's coal groups carry FOR 0.18-0.19 and PMR 0.185-0.20 (pltdata's 0.066 and 0.071)."""
    from nems_open.emm import technology
    mcf = {t.code: t.max_capacity_factor for t in technology.efd_plant_types()}
    rates = dispatch.efd_outage_rates()
    for g in ("coal", "gas_cc"):
        f, p = rates[g]
        assert abs((1 - f) * (1 - p) - mcf[dispatch.AVAIL_TYPE[g]]) < 1e-9
    assert 0.18 < rates["coal"][0] < 0.20 and 0.18 < rates["coal"][1] < 0.21
    assert abs(rates["gas_cc"][0] - 0.074) < 0.002 and abs(rates["gas_cc"][1] - 0.060) < 0.002


def test_spin_requirement_is_efd_slice_formula():
    """SP_RES_RQMT_IN = SR_RQMT_HGHT x height + SR_RQMT_DIFF x (season peak slice - height): 0.1 x the height in the
    peak slice, and the base slice adds 0.3 of its gap to the peak."""
    rng = np.random.default_rng(1)
    load = 50.0 + 20.0 * rng.random((2, 36, 24))
    slice_of, req = dispatch.spin_requirement(load, np.full(36, 365.0 / 36), load)
    for r in range(2):
        for s in range(3):
            h = [load[r][slice_of[r] == 3 * s + j].mean() for j in range(3)]
            for j in range(3):
                got = req[r][slice_of[r] == 3 * s + j]
                assert np.allclose(got, 0.1 * h[j] + 0.3 * (h[0] - h[j]))
    # 1% of each season's hours in the peak slice
    assert abs((slice_of % 3 == 0).mean() - 0.01) < 0.005


def test_maintenance_skips_the_peak_season():
    """The rule behind ED$PM's schedule: no maintenance in the season with the highest load, and PMR x 8760 hours in
    the other two."""
    load = np.ones((1, 36, 24))
    load[0, 18:21] = 2.0                       # July: summer peaks
    w = np.full(36, 365.0 / 36)
    share = dispatch.maintenance_season_share(load, w)[0]
    from nems_open.emm import capacity
    season = capacity.ecp_season_of_month()[np.repeat(np.arange(12), 3)]
    assert (share[season == 1] == 0).all() and (share[season != 1] > 0).all()
    assert abs((share * w * 24).sum() - 8760.0) < 1e-6


@pytest.mark.parametrize("year", (2030, 2040))
def test_turbines_carry_spinning_reserve(results, year):
    """With EFD's spinning reserve rows, turbines run at minimum load for reserve (EFD 2030: 32 TWh from CTG plus 28
    from CTN, EIA 67 in 2030 and 90 in 2040). The reserve is met without load shedding or shortfall."""
    _, _, res = results[year]
    if not dispatch.EFD_SPIN_RESERVE:
        pytest.skip("EFD_SPIN_RESERVE off")
    assert res.generation_twh["gas_ct"].sum() > (12.0 if year == 2030 else 30.0)
    supply = sum(v for k, v in res.spin_gw.items() if k != "required")
    assert (supply >= res.spin_gw["required"] - 1e-3).all()
    assert res.unserved_twh.sum() < 0.001
