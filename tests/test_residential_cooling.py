"""RCLTEC, RCLADD and RCLCON ports vs the residential oracle's state.

The dumps hold neither PELRSOUT nor RCLADD's carried local EQCPN90, so the tests
rebuild them from what is dumped (see the helpers below). PELRSOUT is rebuilt from
the electricity row of PRICES; only the current year of that row is cooling's own.
"""

import numpy as np
import pytest

from resd_oracle import YEARS, assert_matches, before_after, rel_err, skip_unless_dumped
from nems_open.fortran_array import FArray
from nems_open.residential.common import BASEYR, RECSYEAR, f32
from nems_open.residential.cooling import rcladd, rclcon, rcltec

LATER = [y for y in YEARS if y > 31]  # the yearly routines start the year after RECS


def _with_pelrsout(state, after):
    """PELRSOUT(R, iyr, 2) from PRICES(4, R, year) / deflator ratio, nudged by a few
    ulps until the Fortran product reproduces the dumped price exactly."""
    gdp = state["mc_jpgdp"]
    ratio = gdp[int(state["rtekdollaryr"]) - BASEYR + 1] / gdp[-2]
    p = FArray.zeros([(1, 11), (1, 61), (1, 5)])
    prices = after["prices"] if "prices" in after else state["prices"]
    for r in range(1, 10):
        for iyr in range(1, 62):
            target = prices[4, r, iyr + BASEYR - 1]
            v = f32(target / ratio)
            for _ in range(4):
                if f32(v * ratio) == target:
                    break
                v = np.nextafter(v, f32(np.inf) if f32(v * ratio) < target else f32(-np.inf))
            p[r, iyr, 2] = v
    state["pelrsout"] = p


def _with_eqcpn90(state):
    """EQCPN90 (static local of RCLADD): central AC, single-family, is
    ND90 * (1 + CACPR) - ND90 for each year already run, else zero."""
    pn = FArray.zeros([(RECSYEAR, 2050), (1, 40), (1, 3), (1, 11)])
    lo, hi = int(state["rtcleupt"][2]) + 1, int(state["rtcleupt"][3])
    cur = int(state["curcalyr"])
    for reccl in range(lo, hi + 1):
        if state["rtclname"][reccl].decode().strip() == "CENT_AIR":
            for y in range(RECSYEAR + 1, cur + 1):
                for r in range(1, 10):
                    nd = state["eqcnd90"][y, reccl, 1, r]
                    pn[y, reccl, 1, r] = nd * (f32(1.0) + state["cacpr"][r]) - nd
    state["_eqcpn90"] = pn


def check(state, after):
    # text arrays (RTMATURE, RTCLNAME) are inputs; the shared helper only compares numbers
    text = tuple(k for k, v in after.items() if isinstance(v, FArray) and v.a.dtype.kind == "S")
    return assert_matches(state, after, tol=1e-6, skip=text)


@skip_unless_dumped("clt")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rcltec(y):
    state, after = before_after("clt", y)
    _with_pelrsout(state, after)
    rcltec(state)
    check(state, after)


@skip_unless_dumped("cla")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rcladd(y):
    state, after = before_after("cla", y)
    _with_eqcpn90(state)
    rcladd(state)
    check(state, after)


@skip_unless_dumped("clc")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rclcon(y):
    """Everything matches to 1e-6, but the electricity rows of COOLCN, COOLCNWT and
    EQCEQCN only to 1e-2: RSELAST needs PELRSOUT for the two prior years, which the
    dump lacks and PRICES(4) cannot stand in for (it holds whichever end use ran
    last). Natural gas rows do not use PELRSOUT and match to float rounding."""
    state, after = before_after("clc", y)
    _with_pelrsout(state, after)
    rclcon(state)
    elec = ("coolcn", "coolcnwt", "eqceqcn")
    text = tuple(k for k, v in after.items() if isinstance(v, FArray) and v.a.dtype.kind == "S")
    assert_matches(state, after, tol=1e-6, skip=text + elec)
    for k in ("coolcn", "coolcnwt"):
        a, b = state[k].a, after[k].a
        assert rel_err(a[:, 1], b[:, 1]) < 1e-6  # natural gas
        assert rel_err(a[:, 0], b[:, 0]) < 1e-2  # electricity, PELRSOUT lags rebuilt
    assert rel_err(state["eqceqcn"].a, after["eqceqcn"].a) < 1e-2
