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
    assert abs(total_out - (total_in + dated)) < 1.0


# (kind, category, year) -> why the loop misses. Measured on the full loop (cache from capacity_report).
_TIMING = "timing: the LP builds at the annual limit in the first year builds are allowed (2027); EIA ramps up through 2030"
_RETIRE_TIMING = "timing: the LP retires at the annual limit as soon as replacements exist; EIA retires more slowly, then 60 GW at once in 2032"
KNOWN_MISSES = {
    ("add", "Gas combined cycle", 2027): _TIMING,
    ("add", "Gas combined cycle with CCS", 2030): "EIA builds 2.4 GW by 2030; the LP waits until 2032 because the 45Q credit lasts only 12 of 30 years",
    ("add", "Gas combined cycle with CCS", 2035): "10 GW against 23: same cause, and the 10 GW a year build limit is an assumption",
    ("add", "Gas turbines", 2027): "the LP meets the reserve margin with combined cycle, EIA builds 22 GW of turbines by 2027",
    ("add", "Gas turbines", 2030): "same, 50 GW of turbines in EIA by 2030",
    ("add", "Gas turbines", 2035): "same, 120 GW in EIA: its capacity credits for wind and solar are lower than the assumed 15% and 25%",
    ("add", "Wind", 2027): _TIMING,
    ("add", "Wind", 2030): "wind builds at the assumed 30 GW a year limit through the 2029 tax-credit deadline; EIA builds slower",
    ("add", "Wind", 2035): "wind stops when the credit ends (2030); EIA keeps building (194 GW) without it",
    ("add", "Solar", 2027): _TIMING,
    ("add", "Solar", 2030): "solar builds at the assumed 60 GW a year limit through the 2028 credit deadline",
    ("add", "Solar", 2035): "29% high: solar is cheap and the LP is not limited by interconnection or land",
    ("add", "Batteries", 2030): "no battery builds between 2027 and 2031 in the LP; EIA adds steadily",
    ("add", "Nuclear", 2027): "classification: the plant file dates 3 to 7 GW of nuclear uprates and restarts; EIA counts them as capacity changes, not additions",
    ("add", "Nuclear", 2030): "same",
    ("add", "Nuclear", 2035): "same",
    ("ret", "Coal", 2027): _RETIRE_TIMING,
    ("ret", "Coal", 2030): "retirements 31% low in 2030: the LP retires only as replacements arrive; EIA retires 75 GW by 2030",
    ("ret", "Oil and gas steam", 2027): _RETIRE_TIMING,
    ("ret", "Oil and gas steam", 2030): "steam retirements 89% high in 2030, front-loaded",
    ("ret", "Oil and gas steam", 2035): "steam retirements 40% high in 2035: the LP retires more steam than EIA's age-based schedule",
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
