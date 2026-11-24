"""State RPS rows (emm/rps.py) against EIA's 2030 ECP solve: requirements, regions, escape prices, existing credits."""

import numpy as np
import pytest

from nems_open.emm import ecp_cost, regions, rps
from nems_open.snapshot import Snapshot


@pytest.fixture(scope="module")
def snap():
    try:
        return Snapshot()
    except FileNotFoundError:
        pytest.skip("no snapshot")


def tranche(state, tid):
    return next(t for t in rps.tranches() if t.state == state and t.id == tid)


def test_tranches_are_read():
    assert len(rps.tranches()) == 49
    az = tranche("AZ", "1")
    assert az.types["HY"] == (0.0, 1.0) and az.imports and az.hold
    assert [u for u, _ in az.utilities] == ["IOU", "COOP"]


def test_requirements_match_the_2030_solve(snap):
    """The -G(region)STRPS terms of rows G(state)(id)RPS2 in EIA's 2030 solve (requirement of 2031), TWh."""
    sales = np.asarray(snap["UDATOUT/qelasn"], dtype=float)[:regions.NUM_EMM, 41] / 1000.0
    want = {("AZ", "1"): 8.5, ("CA", "1"): 165.3, ("CA", "2"): 192.8, ("IL", "1"): 55.1, ("MA", "1"): 31.5, ("MI", "1"): 56.2,
            ("NY", "2"): 105.7, ("VA", "1"): 53.0}
    for k, v in want.items():
        assert float((rps.requirement_share(tranche(*k), 2031) * sales).sum()) == pytest.approx(v, abs=0.06), k


def test_regions_and_escape_prices(snap):
    ny = np.flatnonzero(rps.mapped_regions(tranche("NY", "2"))) + 1
    assert list(ny) == [8, 9]
    cap = rps.price_cap(tranche("MD", "3"), 2031, lambda y: ecp_cost.deflator(snap, y))
    rate = ecp_cost.financing(snap, 2030, "AT")[-1]
    # cGCAP(MD,3,2) costs 19.459 nominal, discounted to E with PWF(2)
    assert cap * ecp_cost.deflator(snap, 2031) * (1.0 + rate) ** -2 == pytest.approx(19.459, rel=0.01)
    assert rps.price_cap(tranche("AZ", "1"), 2031, lambda y: 1.0) == 200.0


def test_existing_credits_are_units_older_than_the_standard():
    flat = {k: np.full(regions.NUM_EMM, 0.35) for k in ("WN", "WF", "PV", "PT")}
    flat["HY"] = np.full(regions.NUM_EMM, 0.4)
    x, pool = rps.existing(2031, flat)
    # cXX levels of the 2030 solve, TWh: nuclear at the plant file's own factors
    assert x[("IL", "CN")].sum() == pytest.approx(100.4, rel=0.05)
    assert x[("CT", "CN")].sum() == pytest.approx(16.5, rel=0.05)
    assert all(pool[k].sum() >= sum(a.sum() for (s, t), a in x.items() if t == k) - 1e-6 for k in pool)
