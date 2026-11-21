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
