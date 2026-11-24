"""ECP inputs rebuilt from the plant file and our own dispatch: retirement groups (EPGCAP, EPGFOM), the
intermittent capacity credit (EPIRCCR), the cost of capital and the combined-cycle risk premium. Fast."""

import numpy as np
import pytest

from nems_open.emm import capacity, capacity_credit, dispatch, plants, retire_groups as rg
from nems_open.paths import INPUT, REFERENCE_RUN
from nems_open.snapshot import Snapshot

pytestmark = pytest.mark.skipif(
    not ((INPUT / "emm" / "emm_db" / "NEMS_INPUT.db").exists() and REFERENCE_RUN.exists()), reason="EMM inputs missing")


@pytest.fixture(scope="module")
def snapshot():
    return Snapshot()


@pytest.fixture(scope="module")
def case(snapshot):
    return dispatch.build_case(snapshot, 2027, "none")


def test_retirement_shares_read_from_emmcntl():
    shares = rg.retirement_shares()
    assert shares["B1"] == (4, (0.05, 0.45, 0.40, 0.10))
    assert shares["CT"][0] == 4 and shares["PV"][0] == 0


def test_age_adder_follows_both_options():
    a = rg.age_adder_table()
    assert a["B1"](50) == pytest.approx(0.0666 * 50)          # coal: %XTRA Opt 2% linear in age
    assert a["CT"](60) == 0.0 and a["ST"](60) == 0.0
    assert a["CN"](55) == pytest.approx(12.5 / 1.336922)      # nuclear: step table, 1999$ deflated
    assert a["CN"](45) == 0.0


def _groups(case, group, price_level=20.0):
    price = np.full((25, 36 * capacity.BLOCKS), price_level)
    price[:, :12] = 60.0                                      # a few expensive slices so margins differ by cost
    hours = np.full(36 * capacity.BLOCKS, 8760.0 / (36 * capacity.BLOCKS))
    alive = np.ones(len(plants.load_units().summer_mw))
    return rg.build(2027, group, alive, capacity.unit_costs(case, group), price, hours, 0.9), alive


def test_groups_hold_the_retirable_units_and_rank_them(case):
    g, alive = _groups(case, "coal")
    u = plants.load_units()
    mask = rg.retirable_units(2027, "coal", alive)
    assert g.capacity.sum() == pytest.approx(u.summer_mw[mask].sum() / 1000.0)
    assert (g.unit_group[mask] >= 0).all() and (g.unit_group[~mask] == -1).all()
    # Every unit in a lower group has a lower value than every unit in a higher group.
    for k in range(3):
        lo, hi = g.value[g.unit_group == k], g.value[g.unit_group == k + 1]
        if len(lo) and len(hi):
            assert lo.max() <= hi.min() + 1e-9
    # National cost of keeping falls from the worst group to the best.
    cost = (g.cost * g.capacity).sum(axis=0) / np.maximum(g.capacity.sum(axis=0), 1e-9)
    filled = g.capacity.sum(axis=0) > 1.0
    assert np.all(np.diff(cost[filled]) < 0)


def test_group_cost_is_fixed_cost_plus_margin_shortfall(case):
    """Capacity-weighted over a region, EPGFOM averages to the fixed cost (the margin shortfalls cancel)."""
    g, alive = _groups(case, "gas_cc")
    u = plants.load_units()
    fixed = rg.fixed_cost(2027)
    mask = rg.retirable_units(2027, "gas_cc", alive)
    for r in range(25):
        m = mask & (u.region - 1 == r)
        if m.sum() < 2:
            continue
        expect = (fixed[m] * u.summer_mw[m]).sum() / u.summer_mw[m].sum()
        got = (g.cost[r] * g.capacity[r]).sum() / g.capacity[r].sum()
        assert got == pytest.approx(expect, rel=1e-6)


def test_retire_units_takes_the_share_off(case):
    g, alive = _groups(case, "steam")
    share = np.zeros((25, 4))
    r, k = np.argwhere(g.capacity > 0.5)[0]
    share[r, k] = 1.0
    after = rg.retire_units(alive, g, share)
    u = plants.load_units()
    gone = (g.unit_group == k) & (u.region - 1 == r)
    assert (after[gone] == 0).all() and (after[~gone] == 1).all()


def test_credit_saturates_with_capacity(snapshot, case):
    cap = capacity.initial_capacity(snapshot, 2026)
    load = case.net_load_twh[:, None, None] * 1000.0 * case.shapes
    small = dict(cap, wind=cap["wind"] * 0.01, solar=cap["solar"] * 0.01)
    big = dict(cap, solar=cap["solar"] * 4.0)
    c_small = capacity_credit.credits(load, small, case.credit_profile, case.weights)
    c_now = capacity_credit.credits(load, cap, case.credit_profile, case.weights)
    c_big = capacity_credit.credits(load, big, case.credit_profile, case.weights)
    w = cap["solar"]
    avg = lambda c: (c["solar"] * w).sum() / w.sum()
    assert avg(c_big) < avg(c_now) < avg(c_small)             # solar's credit falls as it is built
    assert np.all((c_now["wind"] >= 0) & (c_now["wind"] <= 1))
    assert np.all(c_now["net_peak"] <= c_now["peak"] + 1e-9)


def test_cost_of_capital_and_risk_premium(snapshot):
    d = capacity.discount_rate(snapshot, 2030)
    assert 0.06 < d < 0.08                                    # EIA's formula from AA and Treasury rates
    assert capacity.risk_premium(snapshot, 2030, "AC") == pytest.approx(0.03 * (0.6 * 0.76 + 0.4), rel=1e-5)
    assert capacity.risk_premium(snapshot, 2030, "AT") == 0.0
