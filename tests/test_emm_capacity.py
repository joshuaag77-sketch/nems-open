"""Capacity expansion loop.

Fast checks run always. The comparison with the reference run needs the full 2025 to 2035 loop,
about 15 minutes, so it runs only when NEMS_RUN_SLOW=1 and otherwise reuses a cached result if
NEMS_CAPACITY_CACHE points at one. Misses we know about are marked xfail with the reason.
"""

import os

import numpy as np
import pytest

from nems_open.emm import capacity, capacity_report as rep, dispatch
from nems_open.paths import INPUT, REFERENCE_RUN
from nems_open.snapshot import Snapshot

pytestmark = pytest.mark.skipif(
    not ((INPUT / "emm" / "emm_db" / "NEMS_INPUT.db").exists() and REFERENCE_RUN.exists()), reason="EMM inputs missing")


@pytest.fixture(scope="module")
def snapshot():
    return Snapshot()


def test_initial_capacity_matches_restart(snapshot):
    cap = capacity.initial_capacity(snapshot, 2024)
    assert set(cap) == set(capacity.STATE_GROUPS)
    assert abs(cap["nuclear"].sum() - 96.8) < 0.5
    assert 150 < cap["coal"].sum() < 170
    assert all((v >= 0).all() for v in cap.values())


def test_dated_changes_cover_the_planned_builds():
    adds, rets = capacity.dated_changes(2026)
    assert adds["solar"].sum() > 20                  # the plant file dates tens of GW of solar to 2026
    assert adds["battery"].sum() > 5
    assert rets["coal"].sum() > 1


def test_first_year_has_no_unplanned_builds_and_stays_feasible(snapshot):
    cap = capacity.initial_capacity(snapshot, 2024)
    res = capacity.solve_year(snapshot, 2025, cap)
    assert res.status == "ok:optimal"
    assert sum(v.sum() for v in res.builds.values()) < 1e-6      # EIA's first model-chosen builds are 2027
    assert res.unserved_twh < 0.01 * 4000
    # Capacity carries over: last year plus dated changes.
    total_in = sum(v.sum() for v in cap.values())
    total_out = sum(v.sum() for v in res.capacity.values())
    dated = sum(v.sum() for v in res.planned_adds.values()) - sum(v.sum() for v in res.planned_retire.values())
    economic = sum(v.sum() for v in res.economic_retire.values())          # retirements the LP chose (EIA's cap lets it from 2025)
    assert abs(total_out - (total_in + dated - economic)) < 1.0


# (kind, category, year) -> why the loop misses. Measured on the full loop (cache from capacity_report).
_TIMING = "timing: the LP builds at the annual limit in the first year builds are allowed (2027); EIA ramps up through 2030"
_RETIRE_TIMING = "timing: the LP retires as soon as replacements exist, up to EIA's own 3% a year cap; EIA retires more slowly, then 60 GW at once in 2032"
KNOWN_MISSES = {
    ("add", "Gas combined cycle", 2027): _TIMING,
    ("add", "Gas combined cycle", 2030): "34 GW against 43: with capacity credits from the load shape (hydro counts fully) the LP needs less new capacity in 2030",
    ("add", "Gas combined cycle with CCS", 2030): "EIA builds 2.4 GW by 2030; the LP waits until 2032 because the 45Q credit lasts only 12 of 30 years",
    ("add", "Gas combined cycle with CCS", 2035): "10 GW against 23: same cause, and the 10 GW a year build limit is an assumption",
    ("add", "Gas combined cycle", 2035): "147 GW against EIA's 73 (cache from before the subgroup fix: EIA's target was 146 when UADDCC and UADDAC were both counted); rerun the loop",
    ("add", "Gas turbines", 2027): "ECP's overnight costs make combined cycle cheaper than turbines per kW (AC 441 vs AT 497 1987$), so the LP builds combined cycle; EIA builds 15 GW of turbines by 2027",
    ("add", "Gas turbines", 2030): "same, 29 GW of turbines in EIA by 2030",
    ("add", "Gas turbines", 2035): "same, 67 GW in EIA (not 120: UADDAT is inside UADDCT); the restart does not carry the risk premium (UPRSK) that ECP takes off combined cycle's discount rate",
    ("add", "Wind", 2027): _TIMING,
    ("add", "Wind", 2030): "wind builds at the assumed 30 GW a year limit through the 2029 tax-credit deadline; EIA builds slower",
    ("add", "Wind", 2035): "wind stops when the credit ends (2030); EIA keeps building (194 GW) without it",
    ("add", "Solar", 2027): _TIMING,
    ("add", "Solar", 2030): "solar builds at the assumed 60 GW a year limit through the 2028 credit deadline",
    ("add", "Solar", 2035): "18% high: solar is cheap and the LP is not limited by interconnection or land",
    ("add", "Batteries", 2030): "no battery builds between 2027 and 2031 in the LP; EIA adds steadily",
    ("add", "Nuclear", 2027): "classification: the plant file dates 3 to 7 GW of nuclear uprates and restarts; EIA counts them as capacity changes, not additions",
    ("add", "Nuclear", 2030): "same",
    ("add", "Nuclear", 2035): "same",
    ("ret", "Coal", 2027): _RETIRE_TIMING,
    ("ret", "Coal", 2030): "retirements 24% low in 2030: the LP retires only as replacements arrive; EIA retires 75 GW by 2030",
    ("ret", "Oil and gas steam", 2027): _RETIRE_TIMING,
    ("ret", "Oil and gas steam", 2030): "steam retirements 123% high in 2030: ECP retires through cost groups with a 5% hurdle rate that the LP does not have",
    ("ret", "Oil and gas steam", 2035): "steam retirements 61% high in 2035, same cause",
}


@pytest.fixture(scope="module")
def results(snapshot):
    cache = os.environ.get("NEMS_CAPACITY_CACHE")
    if os.environ.get("NEMS_RUN_SLOW") != "1" and not (cache and os.path.exists(cache)):
        pytest.skip("slow: set NEMS_RUN_SLOW=1 (15 minutes) or NEMS_CAPACITY_CACHE")
    return rep.run_all(snapshot, cache)


@pytest.fixture(scope="module")
def comparison(snapshot, results):
    return rep.compare(snapshot, results)


CASES = [(k, name, y) for k, cats in (("add", rep.ADD_CATEGORIES), ("ret", rep.RETIRE_CATEGORIES))
         for name in cats for y in rep.CHECK_YEARS]


@pytest.mark.parametrize("kind,name,year", CASES)
def test_against_reference(comparison, request, kind, name, year):
    if (kind, name, year) in KNOWN_MISSES:
        request.applymarker(pytest.mark.xfail(reason=KNOWN_MISSES[(kind, name, year)], strict=True))
    model, eia = comparison[(kind, name, year)]
    assert not rep.is_miss(model, eia), f"{kind} {name} {year}: model {model:.1f} GW, EIA {eia:.1f} GW"


def test_ptc_is_valued_as_ecp_does_ten_years_in_1987_dollars():
    import numpy as np
    from nems_open.emm import capacity as cap
    jp = np.ones(64)
    jp[5] = 1.25                         # 1992 dollars are 1.25 1987 dollars; no inflation after
    snap = {"MACOUT/mc_jpgdp": jp}
    r = 0.07
    pv10 = sum(1 / (1 + r) ** k for k in range(1, 11))
    want = 16.5 / 1.25 / (1 - cap.TAX_RATE) * pv10 * cap._crf(r, 30)
    assert cap.ptc_annual(16.5, 1992, 10, r, 30, 2028, snap) == pytest.approx(want)
    assert want < 16.5 * 0.75            # a 10-year credit spread over 30 years is well under the table value
    assert cap.ptc_annual(0.0, 1992, 10, r, 30, 2028, snap) == 0.0


def test_build_steps_follow_ecp_short_term_elasticities():
    from nems_open.emm import capacity as cap
    steps = cap.build_steps("WN", [7.4, 10.7, 5.6, 2.5, 15.4])      # the latest year counts in full
    assert [round(b, 2) for b, _ in steps] == [19.25, 11.55, 15.4]  # 1.25, 0.75 and 1.0 x 15.4 GW
    assert [round(mu, 3) for _, mu in steps] == [1.0, 1.375, 2.25]
    floor = cap.build_steps("WN", [0.0] * 5)                         # no history: ESTMNADD (1,500 MW) is step 1
    assert round(floor[0][0], 3) == 1.5


def test_planned_additions_fill_the_first_build_step():
    """ECP's step-1 row holds the year's planned additions (uecp.f EP$ELAST,2-3), so the LP's own builds get only
    the rest of it; steps 2 and 3 and their costs are unchanged."""
    from nems_open.emm import capacity as cap
    recent = [7.4, 10.7, 5.6, 2.5, 15.4]
    free = cap.build_steps("WN", recent)
    some = cap.build_steps("WN", recent, planned=5.6)
    assert round(some[0][0], 2) == round(19.25 - 5.6, 2)
    assert some[1:] == free[1:] and [mu for _, mu in some] == [mu for _, mu in free]
    full = cap.build_steps("WN", recent, planned=40.0)                # more planned than step 1: step 1 is closed
    assert full[0][0] == 0.0 and full[1:] == free[1:]
    assert cap.build_steps("WN", recent, planned=-1.0) == free


def test_planned_units_count_in_their_own_ecp_type_step():
    """2027 in the plant file: 25.8 GW of PV and PT fill solar's step; offshore wind (WF) and the conventional
    combined cycle and turbine units (EC, ET) do not fill onshore wind's or the advanced gas types' steps."""
    from nems_open.emm import capacity as cap
    assert cap.planned_in_step(2027, "solar") == pytest.approx(25.8, abs=0.3)
    assert cap.planned_in_step(2027, "wind") == pytest.approx(1.2, abs=0.2)       # 4.4 GW offshore left out
    assert cap.planned_in_step(2027, "gas_cc_new") == 0.0
    assert cap.planned_in_step(2027, "gas_ct_new") == 0.0
    assert cap.planned_in_step(2030, "solar") == 0.0


def test_new_wind_and_solar_run_on_the_new_build_profile():
    """ECP values a plant built now on WRENEW's new-build profile (EP$INT UPICFC), not the fleet blend, which is
    zero where no wind stands today and is held to the STEO benchmark in early years."""
    import numpy as np
    pytest.importorskip("nems_open.emm.couple")
    from nems_open.emm import dispatch
    from nems_open.emm.couple import Snapshot
    try:
        s = Snapshot()
    except Exception:
        pytest.skip("no cb2026 restart here")
    case = dispatch.reduce_hours(dispatch.build_case(s, 2030, "none"), 3)
    new, fleet = case.build_profile["wind"].mean(axis=(1, 2)), case.profile["wind"].mean(axis=(1, 2))
    assert new.shape == fleet.shape == (25,)
    assert (new > 0.3).all()                      # every region can build wind at its own resource
    assert new.mean() > fleet.mean()              # new turbines beat the fleet average


def test_battery_credit_is_ecp_top_eight_hour_ratio():
    """CAP_CREDIT_LDC: credit = top-8 mean of (net load - stored energy / 4) over the top-8 mean of net load. No
    battery: 1. A battery that holds its charge through the peak hours loses that share; never below 0 or above 1."""
    from nems_open.emm import capacity_credit as cc
    net = np.full((36, 24), 50.0)
    net[:, 18:22] = 100.0                                   # a four-hour evening peak every day
    zero = {"wind": np.zeros(25), "solar": np.zeros(25), "battery": np.zeros(25)}
    prof = {"wind": np.zeros((25, 36, 24)), "solar": np.zeros((25, 36, 24))}
    load = np.broadcast_to(net, (25, 36, 24)).copy()
    assert np.allclose(cc.storage_credits(load, zero, prof), 1.0)
    soc = cc.battery_soc(net, 10.0)
    assert soc.min() == 0.0 and soc.max() == pytest.approx(40.0)          # 4 hours at 10 GW
    assert (soc[:, 21] == 0.0).all()                                         # empty after the peak
    some = dict(zero, battery=np.full(25, 10.0))
    c = cc.storage_credits(load, some, prof)
    assert ((c > 0.85) & (c <= 1.0)).all()
    wide = np.full((36, 24), 50.0)
    wide[:, 18:22] = 90.0
    wide[0, 14:22] = 100.0                                   # one eight-hour peak: the battery is still charged in part of it
    load = np.broadcast_to(wide, (25, 36, 24)).copy()
    stored = cc.battery_soc(wide, 10.0) / cc.HOURS_TO_SELL
    want = np.sort((wide - stored).ravel())[-8:].mean() / np.sort(wide.ravel())[-8:].mean()
    got = cc.storage_credits(load, some, prof)
    assert want < 1.0 and np.allclose(got, want)


def test_intermittent_credit_is_net_peak_capacity_factor():
    """ECP's EPIRCCR carry no single-plant variance (SINGLE_SITE_VARIANCE off): with a large conventional fleet or
    none, a region's wind credit is its capacity factor over the net-peak hours. The capped variance (on) gives less.
    net_cap moves the hours, not the denominator."""
    from nems_open.emm import capacity_credit as cc
    load = np.full((25, 36, 24), 50.0)
    load[:, :, 19] = 60.0                                     # the peak hour every day
    load[:, :, 12] = 52.0                                     # a windless midday shoulder
    wind = np.full((25, 36, 24), 0.4)
    wind[:, :, 19] = 0.25
    wind[:, :, 12] = 0.0
    prof = {"wind": wind, "solar": np.zeros((25, 36, 24))}
    cap = {"wind": np.full(25, 20.0), "solar": np.zeros(25), "gas_cc": np.full(25, 40.0)}
    w = np.full(36, 365.0 / 36)
    assert not cc.SINGLE_SITE_VARIANCE
    c = cc.credits(load, cap, prof, w)
    assert np.allclose(c["wind"], 0.25)
    cc.SINGLE_SITE_VARIANCE = True
    try:
        capped = cc.credits(load, cap, prof, w)
    finally:
        cc.SINGLE_SITE_VARIANCE = False
    assert (capped["wind"] < 0.22).all()                    # the variance takes part of the 0.25
    # with twice the wind in the net load, the windless hour becomes the net peak
    moved = cc.credits(load, cap, prof, w, net_cap={"wind": np.full(25, 40.0), "solar": np.zeros(25)})
    assert np.allclose(moved["wind"], 0.0, atol=0.002)


def test_wesarea_inputs():
    """renew.f's IntStDdv and IntRegCrl (input/rfm/wesarea.txt): wind sigma 0.38, solar 0.10; TRE wind rho 0.89."""
    from nems_open.emm import capacity_credit as cc
    if not (INPUT / "rfm" / "wesarea.txt").exists():
        pytest.skip("wesarea.txt missing")
    w = cc.wesarea()
    assert np.allclose(w["wind"][0], 0.38) and np.allclose(w["solar"][0], 0.10)
    assert w["wind"][1][0] == pytest.approx(0.89) and w["solar"][1][0] == pytest.approx(0.70)


# ECP's own EPIRCCR for 2030 (AIMMS oracle composite_2030.txt, ec::EPIRCCR, WN and PV), regions 1 to 25.
ECP_WIND_2030 = [0.24, 0.30, 0.26, 0.19, 0.19, 0.19, 0.30, 0.19, 0.21, 0.31, 0.21, 0.18, 0.23, 0.28, 0.30, 0.19, 0.31,
                 0.33, 0.33, 0.27, 0.67, 0.34, 0.34, 0.29, 0.33]
ECP_SOLAR_2030 = [0.06, 0.03, 0.08, 0.11, 0.07, 0.08, 0.06, 0.09, 0.03, 0.03, 0.09, 0.29, 0.08, 0.11, 0.04, 0.11, 0.26,
                  0.27, 0.09, 0.07, 0.01, 0.01, 0.05, 0.04, 0.03]


def test_intermittent_credit_matches_ecp_2030(snapshot):
    """On EIA's 2030 fleet and LDSM's load, with ECP's adjusted capacities in the net load, wind and solar credits are
    within 0.04 of ECP's own EPIRCCR on average (the capped variance missed wind by 0.11), and capacity-weighted wind
    credit is within 10% of ECP's."""
    from nems_open.emm import capacity_credit as cc, ecp_load
    sy = ecp_load.system_load(2030)
    if sy is None:
        pytest.skip("no LDSM state dumps (oracle/run_emm/out/state/ld_in)")
    case = dispatch.build_case(snapshot, 2030, "none")
    cap = capacity.initial_capacity(snapshot, 2030)
    off = cc.cap_adjustment(snapshot, 2030)
    net_cap = {g: np.maximum(cap[g] + off[g], 0.0) for g in cc.INTERMITTENT}
    c = cc.credits(sy, cap, case.profile, case.weights, net_cap)
    ew, es = np.array(ECP_WIND_2030), np.array(ECP_SOLAR_2030)
    mw, ms = cap["wind"] > 0.5, cap["solar"] > 0.5
    assert np.abs(c["wind"] - ew)[mw].mean() < 0.04
    assert np.abs(c["solar"] - es)[ms].mean() < 0.04
    assert (cap["wind"] * c["wind"]).sum() == pytest.approx((cap["wind"] * ew).sum(), rel=0.10)


def test_reserve_row_uses_ecp_coefficients_and_no_free_lending(snapshot):
    """ECP counts hydro at RNWFAC (0.70), pumped storage at UPCCR(PS) (0.70) and batteries at CAP_CREDIT_LDC, and
    credits interregional transfers only on lines it builds, carried as UTRELADJ on the requirement."""
    from nems_open.emm import capacity_credit as cc
    assert capacity.ECP_RESERVE
    case = dispatch.build_case(snapshot, 2033, "none")
    cap = capacity.initial_capacity(snapshot, 2033)
    load_hr = case.net_load_twh[:, None, None] * 1000.0 * case.shapes
    cr = capacity.capacity_credits(case, cap, load_hr, np.repeat(np.arange(12), 3))
    assert cr["hydro"] == cc.HYDRO_CREDIT == 0.70 and cr["pumped"] == cc.PUMPED_CREDIT == 0.70
    assert cr["battery"].shape == (25,) and ((cr["battery"] > 0.8) & (cr["battery"] <= 1.0)).all()
    adj = capacity.reliability_adjustment(snapshot, 2033)
    assert adj.shape == (25,) and abs(adj.sum()) < 1.0 and np.abs(adj).max() > 1.0   # moves capacity, nets to ~0


def test_firm_contracts_follow_prepett():
    """UEITAJ: exports less imports of V_EMM_ETCNCT's firm contracts, times AVEFOR 0.91; a phased-out contract keeps
    0.9 of itself the year after it ends. Domestic contracts net to zero across the 25 regions."""
    from nems_open.emm import ecp_load
    a = ecp_load.firm_contracts(2033)
    assert a.shape == (25,)
    assert a[21] < -3.0                         # CASO imports (from CANO, SRSG, NWPP and the rest of the West)
    assert a[19] > 2.0                          # SRSG exports


def test_requirement_on_ldsm_load_matches_ecp(snapshot):
    """2033 on LDSM's load: EPPEAK x EPMRM + EP_NET_PEAK + PKADJ is within 1.5% of ECP's own reserve rows nationally
    (991 GW, OutToNEMS_2032 rRXXXXXge planning year 2) and ISNE's peak is LDSM's 29.3 GW, not the 19.8 of the
    LP's net-energy shape."""
    from nems_open.emm import capacity_credit as cc, db, ecp_load
    sy = ecp_load.system_load(2033)
    if sy is None:
        pytest.skip("no LDSM state dumps (oracle/run_emm/out/state/ld_in)")
    assert sy.max(axis=(1, 2))[6] == pytest.approx(29.3, abs=0.1)
    case = dispatch.build_case(snapshot, 2033, "none")
    cap = capacity.initial_capacity(snapshot, 2032)
    icc = cc.credits(sy, cap, case.profile, case.weights)
    tab = db.table("V_EMM_ECPDAT_REG")
    o = np.argsort(tab["EMM_REG"])
    margin = np.nan_to_num(np.asarray(tab["EPMRM"], dtype=float)[o[tab["EMM_REG"][o] <= 25]])
    req = (margin * icc["peak"] + icc["net_peak"] + capacity.reliability_adjustment(snapshot, 2033)
           + ecp_load.firm_contracts(2033) + ecp_load.cogen_adjustment(snapshot, 2033))
    assert req.sum() == pytest.approx(991.0, rel=0.015)


def test_ldsm_load_follows_the_run_and_flat_load_lifts_the_requirement(snapshot):
    """Reference demand leaves LDSM's load as it is; 10 GW of flat added load in one region (a data center case)
    lifts that region's requirement by 10 x (1 + EPMRM) (EPPEAK and EP_NET_PEAK each rise by 10) and no other."""
    from nems_open.emm import capacity_credit as cc, db, ecp_load
    sy = ecp_load.system_load(2033)
    if sy is None:
        pytest.skip("no LDSM state dumps (oracle/run_emm/out/state/ld_in)")
    case = dispatch.build_case(snapshot, 2033, "none")
    ref = case.net_load_twh
    assert np.allclose(ecp_load.follow_run(sy, ref, ref, None), sy)
    flat = np.zeros(25)
    flat[0] = 10.0 * 8.76                                   # 10 GW all year in TRE
    cap = capacity.initial_capacity(snapshot, 2032)
    tab = db.table("V_EMM_ECPDAT_REG")
    o = np.argsort(tab["EMM_REG"])
    margin = np.nan_to_num(np.asarray(tab["EPMRM"], dtype=float)[o[tab["EMM_REG"][o] <= 25]])

    def req(load):
        icc = cc.credits(load, cap, case.profile, case.weights)
        return margin * icc["peak"] + icc["net_peak"]

    lift = req(ecp_load.follow_run(sy, ref + flat, ref, flat)) - req(sy)
    assert lift[0] == pytest.approx(10.0 * (1.0 + margin[0]), rel=0.01)
    assert np.allclose(lift[1:], 0.0, atol=1e-6)


def test_construction_interest_follows_epincst(snapshot):
    """EPINCST (uread.f): spending by UPCPRO, work in progress at the plant's rate, half a year on each year's spend.
    With flat prices a one-year build carries 1 + rate / 2 and the three-year combined cycle carries the most."""
    jp = np.asarray(snapshot["MACOUT/mc_jpgdp"], dtype=float).ravel()
    infl_year = 2035
    rate = 0.07
    ds = capacity.construction_factor(snapshot, "DS", infl_year, rate)
    # one year of spending, one year before online, in that year's (lower) price level
    expect = (1.0 + 0.5 * rate) * jp[infl_year - 1 - 1987] / jp[infl_year - 1987]
    assert abs(ds - expect) < 1e-9
    ac = capacity.construction_factor(snapshot, "AC", infl_year, rate)
    at = capacity.construction_factor(snapshot, "AT", infl_year, rate)
    assert ac > at > ds > 0.99
    assert 1.06 < ac < 1.12 and 1.01 < at < 1.05


def test_combined_cycle_over_turbine_cost_matches_ecp(snapshot):
    """ECP's own build columns (oracle OutToNEMS_2035, cB_DSP step 1, planning year 1) cost AC 1.23 to 1.30 times AT
    by region, median 1.28. Overnight cost and fixed O&M alone give 1.20 to 1.24; with interest during construction the
    LP's annual costs land on ECP's ratio."""
    case = dispatch.build_case(snapshot, 2035, "none")
    cap = capacity.capital_costs(snapshot, 2035, case)
    ratio = cap["gas_cc_new"] / cap["gas_ct_new"]
    assert 1.25 < np.median(ratio) < 1.31
    old = capacity.CONSTRUCTION_INTEREST
    try:
        capacity.CONSTRUCTION_INTEREST = False
        bare = capacity.capital_costs(snapshot, 2035, case)
    finally:
        capacity.CONSTRUCTION_INTEREST = old
    assert np.median(bare["gas_cc_new"] / bare["gas_ct_new"]) < 1.24


def test_advanced_gas_steps_keep_the_conventional_floor():
    """ucape.f ELSTCAP: ESTCPADD(AT) = max(ESTCPADD(AT), ESTCPADD(CT)) and AC likewise from CC, whose ESTMNADD floor is
    5,000 MW / 1.25. With no recent additions the turbine's first step is 5 GW, not the 1.875 GW of AT's own floor."""
    for code in ("AT", "AC"):
        steps = capacity.build_steps(code, [0.0] * 5)
        assert [round(b, 2) for b, _ in steps] == [5.0, 3.0, 4.0]
    assert round(capacity.build_steps("DS", [0.0] * 5)[0][0], 3) == 3.0        # other types keep their own floor


def test_retirement_cap_follows_ecp_lead_time():
    """uecp.f 1171-1178 and EP$RET: ECP year E caps retirements in E + UPRTLT (1) at 3% + 1 point x (E - 2026), and
    switches the cap off past 6%. So 3% for 2027 (not 5%), 6% for 2030 and none from 2031."""
    rate = [capacity.max_retirement_rate(y) for y in range(2027, 2032)]
    assert rate[:4] == pytest.approx([0.03, 0.04, 0.05, 0.06])
    assert rate[4] == float("inf")


def test_conversion_credit_is_the_avoided_firm_build_after_the_coal_rule():
    """A conversion keeps firm capacity through ECP's 30-year horizon; only years from RULE_YEAR count (before then
    the coal unit itself is firm), each worth a new turbine less the converted unit's fixed O&M."""
    from nems_open.emm import capacity as cap
    r = 0.07
    firm, keep = np.array([40.0e3, 10.0e3]), np.array([10.0e3, 15.0e3])
    got = cap.conversion_credit(2028, firm, keep, r)
    k0 = cap.RULE_YEAR - 2028
    pv = sum((1 + r) ** -(k + 1) for k in range(k0, cap.HORIZON_YEARS))
    assert got[0] == pytest.approx(30.0e3 * pv * cap._crf(r, cap.HORIZON_YEARS))
    assert got[1] == 0.0                                                 # keeping costs more than building: no credit
    assert cap.conversion_credit(cap.RULE_YEAR, firm, keep, r)[0] == pytest.approx(30.0e3)    # every year counts
    assert cap.conversion_credit(2028, firm, keep, r)[0] < 30.0e3


def test_conversion_costs_come_from_the_plant_file():
    """ECP's OV_CLtNG is each coal unit's T_NG_COST plus T_NG_TRAN; units without a cost cannot convert."""
    from nems_open.emm import db, plants
    t, u = db.table("V_EMM_PLTF860"), plants.load_units()
    coal = np.isin(u.efd_type, dispatch.EXISTING_TYPES["coal"]) & plants.online(2028)
    cost = np.asarray(t["T_NG_COST"], dtype=float)[coal]
    gw = u.summer_mw[coal][cost > 0].sum() / 1000.0
    assert 50.0 < gw < 140.0                                             # most, not all, coal can convert
    tot = cost + np.asarray(t["T_NG_TRAN"], dtype=float)[coal]
    assert 100.0 < np.average(tot[cost > 0], weights=u.summer_mw[coal][cost > 0]) < 400.0     # 1987$/kW


def test_ecp_commits_every_type_one_year_ahead():
    """ECP's planning lead (COSTPERF UPPLYR) is 1 year for every type: a build chosen in ECP year E comes online in
    E + 1 (EPO$BILD, FULLYR = year + UPPLYR), whatever its construction years (UPCLYR, which only set the cost profile
    and first year). So a battery has no lead-time advantage over a combined cycle in ECP, and this LP's one-year
    step (builds online the year they are decided, held to that year's reserve row) is ECP's year 2."""
    from nems_open.xlsx_ranges import named_ranges
    from nems_open.emm import technology
    lead = dict(zip(technology.ecp_codes(), named_ranges(technology.ECPDATY, "COSTPERF")["UPPLYR"]))
    for code in capacity.BUILDS.values():
        assert lead[code] == 1.0
    assert lead["CC"] == 1.0



def test_battery_increment_share_follows_ds_params():
    """emmcntl.txt %DS PARAMS%: the ReStore test battery is 1% of the region's top load in 2017, a point a year more,
    at most 5% (uecp.f 37838-37842)."""
    assert capacity.battery_increment_share(2017) == pytest.approx(0.01)
    assert capacity.battery_increment_share(2019) == pytest.approx(0.03)
    assert capacity.battery_increment_share(2026) == pytest.approx(0.05)
    assert capacity.battery_increment_share(2045) == pytest.approx(0.05)


def test_battery_build_limit_matches_ecp_2026(snapshot):
    """ECP's 2026 solve bounds each region's year-1 battery column (cIX DS step 1, CALC_STORAGE_VAL,11) at the
    ReStore test battery it used, at most 5% of MAX_LOAD. Where ReStore used all of it (19 of 25 regions) this
    model's limit for 2027 is ECP's bound (OutToNEMS_2026 coeff_cIX_UBOUND) to 0.01 GW; elsewhere it is above it."""
    from nems_open.emm import ecp_load
    if ecp_load.system_load(2026) is None:
        pytest.skip("no LDSM state dumps (oracle/run_emm/out/state/ld_in)")
    ecp = {"TRE": 4.754, "FRCC": 2.752, "MISW": 2.122, "MISC": 1.883, "MISE": 1.002, "MISS": 1.877, "ISNE": 1.370,
           "NYCW": 0.832, "NYUP": 0.673, "PJME": 2.154, "PJMW": 2.914, "PJMC": 1.053, "PJMD": 1.173, "SRCA": 2.281,
           "SRSE": 2.327, "SRCE": 1.855, "SPPS": 1.536, "SPPC": 0.835, "SPPN": 0.555, "SRSG": 0.0, "CANO": 0.0,
           "CASO": 0.0, "NWPP": 0.0, "RMRG": 0.860, "BASN": 0.0}
    from nems_open.emm import regions
    lim = capacity.battery_build_limit(snapshot, 2027, dispatch.build_case(snapshot, 2027, "none"))
    names = regions.names()[:25]
    full = [n for n in names if n not in ("NYUP", "PJME", "PJMD", "SRSG", "CANO", "CASO", "NWPP", "BASN")]
    for n in full:
        assert lim[names.index(n)] == pytest.approx(ecp[n], abs=0.01), n
    for n in names:
        assert lim[names.index(n)] >= ecp[n] - 0.01, n


def test_batteries_build_in_the_first_step_only(snapshot):
    """CALC_STORAGE_VAL,12: ECP's battery column sits in the step-1 elasticity row only, so a 2027 solve from EIA's
    2026 fleet builds no more batteries than the first step and no more in any region than its limit."""
    path = capacity.CapacityPath(snapshot, first=2027)
    recent = path.recent_adds(2027)["battery"]
    step1 = capacity.build_steps("DS", recent, capacity.planned_in_step(2027, "battery"))[0][0]
    res = path.step(2027)
    lim = capacity.battery_build_limit(snapshot, 2027, dispatch.build_case(snapshot, 2027, "none"))
    assert res.builds["battery"].sum() <= step1 + 1e-6
    assert np.all(res.builds["battery"] <= lim + 1e-6)


def test_new_gas_heat_rates_are_ecp_uphtrt():
    """ECP builds dispatchable plants at UPHTRT (uecp.f 37458-37478), which is UPPHRT0 when UPDHRSW <= 1 (ucape.f
    625-641), true of every type in ecpdaty.xlsx. The oracle's 2030 composite input carries UPHTRT CT 9447, AT 9142,
    CC 6226, AC 6226, CS 7239; the LP had the advanced turbine at its UPPHRTN, 9905. The build LP and the
    dispatch case's new capacity both use it."""
    from nems_open.emm import technology
    from nems_open.xlsx_ranges import named_ranges
    codes = technology.ecp_codes()
    hr = technology.new_heat_rate(2031)
    ecp = {"CT": 9447.0, "AT": 9142.0, "CC": 6226.0, "AC": 6226.0, "CS": 7239.0}
    for c, v in ecp.items():
        assert hr[codes.index(c)] == pytest.approx(v), c
    o = named_ranges(technology.ECPDATY, "OPTLRN")
    sw = np.asarray(o["UPDHRSW"], dtype=float)
    assert np.all(sw <= 1)
    assert np.allclose(hr, np.asarray(o["UPPHRT0"], dtype=float))
