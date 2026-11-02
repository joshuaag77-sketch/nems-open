"""RCLTEC, RCLADD and RCLCON ports vs the residential oracle's state.

The dumps do not hold RCLADD's carried local EQCPN90 in its input state, so it is
loaded from cla_pre.
"""

import pytest

from resd_oracle import YEARS, assert_matches, before_after, skip_unless_dumped
from nems_open import oracle_state
from nems_open.fortran_array import FArray
from nems_open.residential.cooling import rcladd, rclcon, rcltec

LATER = [y for y in YEARS if y > 31]  # the yearly routines start the year after RECS


def _with_eqcpn90(state, y):
    """EQCPN90 is RCLADD's carried local; the oracle dumps its value at the start of
    the final iteration (cla_pre)."""
    state["eqcpn90"] = oracle_state.load("cla_pre", y, "resd")["eqcpn90"].copy()


def check(state, after):
    # text arrays (RTMATURE, RTCLNAME) are inputs; the shared helper only compares numbers
    text = tuple(k for k, v in after.items() if isinstance(v, FArray) and v.a.dtype.kind == "S")
    return assert_matches(state, after, tol=1e-6, skip=text)


@skip_unless_dumped("clt")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rcltec(y):
    state, after = before_after("clt", y)
    rcltec(state)
    check(state, after)


@skip_unless_dumped("cla")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rcladd(y):
    state, after = before_after("cla", y)
    _with_eqcpn90(state, y)
    rcladd(state)
    check(state, after)


@skip_unless_dumped("clc")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rclcon(y):
    state, after = before_after("clc", y)
    rclcon(state)
    check(state, after)
