"""Clothes washer and dishwasher ports vs the residential oracle's state."""

import numpy as np
import pytest

from resd_oracle import YEARS, assert_matches, before_after, skip_unless_dumped
from nems_open.fortran_array import FArray
from nems_open.residential.common import BASEYR
from nems_open.residential.washers import (EUPR_CW, EUPR_DW, rcwadd, rcwcon, rcwtec,
                                           rdwadd, rdwcon, rdwtec)

LATER = [y for y in YEARS if y > 31]  # yearly routines have no 2020 dump


def with_pelrsout(state, after, eupr):
    """PELRSOUT is EQUIVALENCEd, so the oracle does not dump it. Recover this year's
    value from the routine's own output price (PRICES(4) = PELRSOUT * deflator).
    Only the price line is not independently checked; everything after it is."""
    y_cal, y1 = int(state["curcalyr"]), int(state["curiyr"])
    gdp = state["mc_jpgdp"]
    infl = np.float32(gdp[int(state["rtekdollaryr"]) - BASEYR + 1] / gdp[-2])
    pel = FArray.zeros([(1, 11), (1, 61), (1, 12)])
    for r in range(1, 10):
        pel[r, y1, eupr] = np.float32(np.float64(after["prices"][4, r, y_cal]) / np.float64(infl))
    state["pelrsout"] = pel


def check(state, after, tol=1e-6):
    """assert_matches, with text tables (RTMATURE) compared for equality: the shared
    helper only handles numbers."""
    text = {k for k, v in after.items() if isinstance(v, FArray) and v.a.dtype.kind == "S"}
    for k in text:
        assert (state[k].a == after[k].a).all(), k
    return assert_matches(state, after, tol=tol, skip=text)


def run(tag, y, routine, eupr=None):
    state, after = before_after(tag, y)
    if eupr is not None:
        with_pelrsout(state, after, eupr)
    routine(state)
    return state, after


@skip_unless_dumped("cwt")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rcwtec(y):
    state, after = run("cwt", y, rcwtec, EUPR_CW)
    check(state, after)


@skip_unless_dumped("cwa")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rcwadd(y):
    state, after = run("cwa", y, rcwadd)
    check(state, after)


@skip_unless_dumped("cwc")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rcwcon(y):
    state, after = run("cwc", y, rcwcon, EUPR_CW)
    check(state, after)


@skip_unless_dumped("dwt")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rdwtec(y):
    state, after = run("dwt", y, rdwtec, EUPR_DW)
    check(state, after)


@skip_unless_dumped("dwa")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rdwadd(y):
    state, after = run("dwa", y, rdwadd)
    check(state, after)


@skip_unless_dumped("dwc")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rdwcon(y):
    state, after = run("dwc", y, rdwcon, EUPR_DW)
    check(state, after)
