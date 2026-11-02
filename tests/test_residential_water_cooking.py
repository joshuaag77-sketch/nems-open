"""RWHTEC, REUADD (water heating and cooking), RWHCON, RSTVTEC and RSTOVCON vs the oracle.

The yearly routines have no 2020 dump, so the years are 2021 to 2050 as dumped.

PELRSOUT (equivalenced to PELSHRS in eusprc) is not in the dumps. Four of these
routines overwrite PRICES(4, R, CurCalYr) from it, and RWHCON's RSELAST reads it for
electric equipment. Until the lead adds it, the tests stand in for it:
- PRICES(4, :, CurCalYr) is taken from the "out" dump before the routine runs (that
  line's result; the port skips the overwrite when "pelrsout" is not in the state).
- RWHCON's electric price response is solved from the oracle's EQCEQCN for the
  electric rows (one factor per division) and fed back in. The structure around it is
  still checked: every electric row must give the same factor to 1e-6.
"""

import numpy as np
import pytest

from resd_oracle import YEARS, assert_matches, before_after, skip_unless_dumped
import nems_open.residential.helpers as helpers
import nems_open.residential.water_cooking as wc
from nems_open.residential.water_cooking import reuadd, rstovcon, rstvtec, rwhcon, rwhtec

LATER = [y for y in YEARS if y > 31]
TEXT = ("rtmature", "rtclname")  # input name tables; the shared check compares numbers only
NM = 9


def stand_in_elec_price(state, after):
    Y = int(state["curcalyr"])
    for r in range(1, NM + 1):
        state["prices"][4, r, Y] = after["prices"][4, r, Y]


@skip_unless_dumped("wht")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rwhtec(y):
    state, after = before_after("wht", y)
    stand_in_elec_price(state, after)
    rwhtec(state)
    assert_matches(state, after, tol=1e-6, skip=TEXT)


@skip_unless_dumped("wha")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_reuadd_water(y):
    state, after = before_after("wha", y)
    reuadd(state, 5)
    assert_matches(state, after, tol=1e-6, skip=TEXT)


@skip_unless_dumped("cka")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_reuadd_cooking(y):
    state, after = before_after("cka", y)
    reuadd(state, 6)
    assert_matches(state, after, tol=1e-6, skip=TEXT)


@skip_unless_dumped("ckt")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rstvtec(y):
    state, after = before_after("ckt", y)
    stand_in_elec_price(state, after)
    rstvtec(state)
    assert_matches(state, after, tol=1e-6, skip=TEXT)


@skip_unless_dumped("ckc")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rstovcon(y):
    state, after = before_after("ckc", y)
    stand_in_elec_price(state, after)
    rstovcon(state)
    assert_matches(state, after, tol=1e-6, skip=TEXT)


@skip_unless_dumped("whc")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rwhcon(y, monkeypatch):
    state, after = before_after("whc", y)
    stand_in_elec_price(state, after)
    Y1 = int(state["curiyr"])
    factor = {}
    monkeypatch.setattr(wc, "_rselast", lambda s, f, r, *a: factor.get(r, np.float32(1.0)) if f == 4
                        else helpers.rselast(s, f, r, *a))
    # First pass with factor 1 for electricity; the oracle's EQCEQCN then gives the true factor.
    first = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in state.items()}
    rwhcon(first)
    ratios = {}
    for r in range(1, NM + 1):
        for reccl in range(int(state["rtcleupt"][5]) + 1, int(state["rtcleupt"][6]) + 1):
            if int(state["rtfuel"][reccl]) != 4:
                continue
            for b in range(1, 4):
                mine, eia = first["eqceqcn"][Y1, reccl, b, r], after["eqceqcn"][Y1, reccl, b, r]
                if mine > 0:
                    ratios.setdefault(r, []).append(float(eia) / float(mine))
    for r, v in ratios.items():
        assert max(v) / min(v) - 1 < 2e-6, (r, v)
        factor[r] = np.float32(np.median(v))
    rwhcon(state)
    assert_matches(state, after, tol=1e-6, skip=TEXT)
