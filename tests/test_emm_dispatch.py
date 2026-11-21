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


def test_max_load_shape_is_efd_drat_max():
    """uefd.f OPBSLD: a coal unit's maximum-load mode makes (1 - FOR) x (SR_MAX_LF + (1 - SR_MAX_LF) x height / the
    season's peak slice height) per committed GW, SR_MAX_LF 0.55 for existing coal; the plain derate up to 2027."""
    rng = np.random.default_rng(2)
    load = 50.0 + 20.0 * rng.random((2, 36, 8))
    from nems_open.emm import capacity
    sl, ht = capacity.ecp_slice_heights(load, np.full(36, 365.0 / 36), np.repeat(np.arange(12), 3), load)
    shape = dispatch.max_load_shape(sl, ht, 2030)["coal"]
    for r in range(2):
        for s in range(3):
            peak = ht[r, 3 * s]
            for j in range(3):
                assert np.allclose(shape[r][sl[r] == 3 * s + j], 0.55 + 0.45 * ht[r, 3 * s + j] / peak, atol=1e-6)
    assert (shape <= 1.0 + 1e-9).all() and shape.min() > 0.55
    assert (dispatch.max_load_shape(sl, ht, 2027)["coal"] == 1.0).all()


@pytest.mark.parametrize("year", (2030,))
def test_coal_units_stay_under_efd_ceiling(results, year):
    """With the maximum-load shape coal units run at 0.57-0.60 of capacity where they run flat out, EFD's 2030 ceiling
    (oracle 2030 EFD: 0.570-0.583 by region), not the flat (1 - FOR)(1 - PMR) = 0.65."""
    _, _, res = results[year]
    gen, cap = res.generation_twh["coal"], dispatch.generating_capacity(res.case)["coal"]
    big = cap > 1.0
    cf = gen[big] / cap[big] / 8.76
    assert cf.max() < 0.61, cf.round(3)
    assert 0.48 < gen.sum() / cap.sum() / 8.76 < 0.58


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
    from CTN, EIA 67 in 2030 and 90 in 2040). The reserve is met without load shedding or shortfall. Floors are 10 and 25
    TWh since the load took off nontraditional cogeneration and LDSM's loss factor (11 and 29 TWh, from 16 and 40)."""
    _, _, res = results[year]
    if not dispatch.EFD_SPIN_RESERVE:
        pytest.skip("EFD_SPIN_RESERVE off")
    assert res.generation_twh["gas_ct"].sum() > (10.0 if year == 2030 else 25.0)
    supply = sum(v for k, v in res.spin_gw.items() if k != "required")
    assert (supply >= res.spin_gw["required"] - 1e-3).all()
    assert res.unserved_twh.sum() < 0.001


def test_eia_steam_is_cofired_coal_units(snapshot):
    """EIA's steam from 2030 is mostly the coal-gas cofiring units (restart prefix ng), and they burn coal: coal by fuel
    (UGNCLNR) less the coal units (UGENPC + UGENIG) is 50-60% of their generation in 2031-2038. The plant file's ng units
    are EFD type CTN with a coal curve as second fuel at about 52% of Btu."""
    def gen(t, year):
        return float(snapshot[f"UDATOUT/ugen{t}"][:dispatch.NUM_R, year - 1990].sum())
    for y in (2031, 2033, 2035, 2038):
        ng, os_ = gen("ng", y), gen("os", y)
        coal_in_ng = rep.reference(snapshot, y)["gen_coal"] - gen("pc", y) - gen("ig", y)
        assert ng > 5 * os_ and 0.50 < coal_in_ng / ng < 0.60, (y, ng, os_, coal_in_ng)
    assert gen("ng", 2040) < 1.0                     # cofiring ends after UEPA_CLCFYR (2038)


@pytest.mark.skipif(not dispatch.COFIRE_GROUP, reason="COFIRE_GROUP off")
def test_cofire_group_takes_ng_out_of_steam(snapshot):
    """ng is its own group, at the CTN units' heat rate and coal share, and the converted coal's; no coal after 2038."""
    c = dispatch.build_case(snapshot, 2035)
    ng = dispatch._in_service(snapshot, dispatch.COFIRE_PREFIXES, dispatch.EXISTING_TYPES["cofire"], 2035)
    assert c.capacity["cofire"].sum() == pytest.approx(ng.sum(), abs=0.1)
    assert 45 < c.capacity["cofire"].sum() < 52 and 45 < c.capacity["steam"].sum() < 55
    w = c.capacity["cofire"]
    assert 0.52 < np.average(c.coal_share["cofire"], weights=w) < 0.60
    assert 10500 < np.average(c.heat_rate["cofire"], weights=w) < 11600
    assert (dispatch.build_case(snapshot, 2040).coal_share["cofire"] == 0).all()


def test_restart_counts_ccs_retrofits_before_their_capacity_loss(snapshot):
    """udat.f reports a CCS retrofit at WC_SUM / (1 - CCSADJ), its capacity before the capture plant's loss
    (CCSADJ = 1 - WHRATE / CCSHR, udat.f 9265). On that capacity EIA's CCS coal runs at 0.44 in every year 2033-2040;
    on the capacity left after the loss (about 0.7 of it) that is EFD's 0.6 to 0.65."""
    c = dispatch.build_case(snapshot, 2040)
    net = np.average(c.capture_net, weights=c.capacity["coal_ccs"])
    assert 0.68 < net < 0.73
    for y in range(2033, 2041):
        cap = float(dispatch._ucap(snapshot, ("sq",), y - 1990).sum())
        cf = float(snapshot["UDATOUT/ugensq"][:dispatch.NUM_R, y - 1990].sum()) / cap / 8.76
        assert 0.42 < cf < 0.46 and 0.58 < cf / net < 0.66, (y, cf)
    if dispatch.CCS_CAPACITY_PENALTY:
        gen = dispatch.generating_capacity(c)
        assert gen["coal_ccs"] == pytest.approx(c.capacity["coal_ccs"] * c.capture_net)


def test_part_load_factor_reproduces_efd_group_heat_rates():
    """udat.f CRPGRP stores THRATE x Target_EFF(T_CF) / Max_EFF as the group heat rate (UG_HTRT) on emmcntl's curve
    for the unit's coal region and configuration. The oracle's 2030 EFD composite: Northampton (B3, coal region 2,
    T_CF 0.40) 10,052 Btu/kWh; the PJME C7 group (Conemaugh and Keystone, THRATE 10,116-10,427) 9,230."""
    from nems_open.emm import db, plants
    tb, u = db.table("V_EMM_PLTF860"), plants.load_units()
    curves = dispatch.heat_rate_curves()
    assert (2, "B3") in curves and (1, "C7") in curves and (2, "B5") in curves       # B5 takes B3's curve
    assert curves[(2, "B5")] is curves[(2, "B3")]
    full = dispatch.part_load_factor(1.0)
    names = np.array([str(x).strip() for x in tb["T_PNM"]])
    pjme = (u.region == 10) & (u.efd_type == "CSC") & np.isin(names, ["Conemaugh", "Keystone"])
    north = (u.region == 10) & (u.efd_type == "CSC") & (names == "Northampton Generati")
    assert float((u.heat_rate * full)[north][0]) == pytest.approx(10052.0, abs=5)
    assert np.average((u.heat_rate * full)[pjme], weights=u.summer_mw[pjme]) == pytest.approx(9230.0, abs=40)
    # Units without a curve (gas) keep THRATE.
    assert (full[u.efd_type == "CCG"] == 1.0).all()


def test_coal_heat_rate_follows_eia_burn(snapshot):
    """EIA's 2030 coal burn (UFLCLNR / UGNCLNR) where coal units make nearly all the coal power: the plain THRATE
    average is 3-4% above it, at the part-load level within 3%. PJME's group heat rate drops from 10,960 to about
    10,140 (EIA burns 10,720 there)."""
    if not dispatch.COAL_PART_LOAD_HEAT_RATE:
        pytest.skip("COAL_PART_LOAD_HEAT_RATE off")
    y = 2030 - 1990
    c = dispatch.build_case(snapshot, 2030)
    gen_all = snapshot["UEFDOUT/ugnclnr"][:, :25, y].sum(0)
    burn = snapshot["UEFDOUT/uflclnr"][:, :25, y].sum(0) / np.maximum(gen_all, 1e-9) * 1000
    clean = np.array([5, 10, 11, 12, 13, 17, 20, 25]) - 1
    gen = snapshot["UDATOUT/ugenpc"][:25, y][clean]
    err = np.average(c.heat_rate["coal"][clean] / burn[clean] - 1, weights=gen)
    assert -0.03 < err < 0.0, err
    assert 10000 < c.heat_rate["coal"][9] < 10300
    # Conversions to cofiring start from the plain coal heat rate.
    on = c.capacity["cofire"] > 0
    assert (c.heat_rate["cofire"][on] > 10300).all()


@pytest.mark.parametrize("year", (2030,))
def test_pjm_coal_runs_at_eia_level(results, snapshot, year):
    """With the part-load heat rate PJM's coal is cheaper than its marginal cost again (2030 at THRATE: PJME 7.9,
    PJMW 71.0, PJMD 4.4 TWh against EIA's 21.7, 78.8, 7.8). With the coal classes (COAL_BY_CONFIGURATION) PJM's high
    heat rate waste-coal and northern Appalachian units sit near the dispatch's low eastern marginal cost and run less
    than EIA's: PJM as a whole stays within 15% of EIA's."""
    if not dispatch.COAL_PART_LOAD_HEAT_RATE:
        pytest.skip("COAL_PART_LOAD_HEAT_RATE off")
    _, _, res = results[year]
    y = year - 1990
    eia = snapshot["UDATOUT/ugenpc"][:25, y] + snapshot["UDATOUT/ugenig"][:25, y] - snapshot["UDATOUT/ugensq"][:25, y]
    pjm = [9, 10, 11, 12]
    ours = res.generation_twh["coal"][pjm].sum()
    assert abs(ours / eia[pjm].sum() - 1) < 0.15, (ours, eia[pjm].sum())


def test_diversity_caps_are_eia_burn(snapshot):
    """The CMM writes EFD's sub-bituminous and lignite caps from EFD's own unit burn (EMM_CL_BTUS x the plant's
    shares + 0.05): where a western configuration burns only those ranks the two caps add up to its burn in EIA's
    run (2030, restart COALEMM QCLCLNR by coal region and ECP type)."""
    from nems_open.emm import coal_supply, technology
    y = 2030 - 1990
    q = np.asarray(snapshot["COALEMM/qclclnr"], float)[:, y, :38]
    cap = np.asarray(snapshot["USO2GRP/efd_sb_dvlim"], float)[:, :38, y] + np.asarray(snapshot["USO2GRP/efd_lg_dvlim"], float)[:, :38, y] - 0.1
    codes = technology.ecp_codes()
    for crg, cfg in (("WS", "C4"), ("WS", "B7"), ("MT", "C4"), ("MT", "CX"), ("CU", "B7"), ("ZN", "B5")):
        c, t = coal_supply.CL_CODES.index(crg), codes.index(cfg)
        assert cap[c, t] == pytest.approx(q[c, t], rel=0.03), (crg, cfg, cap[c, t], q[c, t])


def test_coal_supply_steps_follow_ed_col(snapshot):
    """ED$COL's supply rows: 11 steps of XCL_QECP x the XCL_STEPS widths at most XCL_PCAP in all, then a 12th without
    limit at max(3 x the 11th price, 9.999). In 2030 the Utah bituminous curve's base production all goes to other
    users (XCL_OTHER = XCL_QECP = 11.8 TBtu), so power gets the steps above base and then 9.999."""
    from nems_open.emm import coal_supply
    curves, rank, qty, price, other = coal_supply.supply_curves(snapshot, 2030)
    assert np.isinf(qty[:, 11]).all() and (price[:, 11] >= 9.999).all()
    pcap = np.asarray(snapshot["USO2GRP/xcl_pcap"], float)[curves - 1, 2030 - 1990]
    assert (qty[:, :11].sum(axis=1) <= pcap + 1e-6).all()
    i = list(curves).index(12)
    assert rank[i] == 1 and other[i] == pytest.approx(qty[i, :6].sum(), rel=1e-6)
    assert 5.0 < qty[i, 6:11].sum() < 7.0


def test_coal_classes_split_the_coal_group(snapshot):
    """Every region's coal capacity is split over its classes (or the rest), and the coal group's part of a class's
    caps is at most the class's caps."""
    from nems_open.emm import coal_supply
    case = dispatch.build_case(snapshot, 2030)
    cl = case.coal_classes
    if cl is None:
        pytest.skip("COAL_BY_CONFIGURATION off")
    assert np.bincount(cl.region - 1, weights=cl.share, minlength=25) == pytest.approx(np.ones(25))
    sb = np.asarray(snapshot["USO2GRP/efd_sb_dvlim"], float)[:, :38, 2030 - 1990]
    from nems_open.emm import technology
    codes = technology.ecp_codes()
    for k, (crg, cfg) in enumerate(cl.classes):
        assert cl.sub_cap[k] <= sb[coal_supply.CL_CODES.index(crg), codes.index(cfg)] + 1e-6
    assert (cl.route_cost >= 0).all() and len(cl.route_cost) > 100


@pytest.mark.parametrize("year", (2030,))
def test_western_coal_held_by_its_caps(results, snapshot, year):
    """EFD's coal LP holds the western configurations at their caps: TRE, BASN and SRSG coal units land within 10% of
    EIA's (one regional price gave 2030 TRE 52, BASN 30 against 44.7, 14.8), and Montana's C4 units, with no
    bituminous route, stay near their 4.4 TBtu cap (EFD: capacity factor 0.05)."""
    if not dispatch.COAL_BY_CONFIGURATION:
        pytest.skip("COAL_BY_CONFIGURATION off")
    _, _, res = results[year]
    y = year - 1990
    eia = snapshot["UDATOUT/ugenpc"][:25, y] + snapshot["UDATOUT/ugenig"][:25, y] - snapshot["UDATOUT/ugensq"][:25, y]
    for r in (1, 20, 25):
        assert abs(res.generation_twh["coal"][r - 1] / eia[r - 1] - 1) < 0.10, (r, res.generation_twh["coal"][r - 1], eia[r - 1])
    cl = res.case.coal_classes
    k = cl.classes.index(("MT", "C4"))
    burn = (res.coal_class_twh * cl.heat_rate / 1000.0)[cl.klass == k].sum()
    assert burn < 1.1 * (cl.sub_cap[k] + cl.lig_cap[k]) + 0.5


def test_cofire_takes_the_ng_max_load_shape():
    """OPBSLD gives ECP type NG (SR_MAX_LF 0.5) its maximum-load mode in every year: the STEO exemption stops at WIIS."""
    if not dispatch.COFIRE_MAX_LOAD_SHAPE:
        pytest.skip("COFIRE_MAX_LOAD_SHAPE off")
    rng = np.random.default_rng(3)
    load = 50.0 + 20.0 * rng.random((2, 36, 8))
    from nems_open.emm import capacity
    sl, ht = capacity.ecp_slice_heights(load, np.full(36, 365.0 / 36), np.repeat(np.arange(12), 3), load)
    for year in (2025, 2030):
        shape = dispatch.max_load_shape(sl, ht, year)["cofire"]
        assert shape.min() > 0.5 and shape.max() <= 1.0 + 1e-9 and shape.min() < 0.99
    s = dispatch.max_load_shape(sl, ht, 2030)
    assert ((s["cofire"] - 0.5) / 0.5 == pytest.approx((s["coal"] - 0.55) / 0.45))
    assert (dispatch.max_load_shape(sl, ht, 2025)["coal"] == 1.0).all()
