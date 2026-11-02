"""RWHTEC, REUADD (water heating and cooking), RWHCON, RSTVTEC and RSTOVCON vs the oracle.

The yearly routines have no 2020 dump, so the years are 2021 to 2050 as dumped.
"""

import numpy as np
import pytest

from resd_oracle import YEARS, assert_matches, before_after, skip_unless_dumped
from nems_open.residential.water_cooking import reuadd, rstovcon, rstvtec, rwhcon, rwhtec

LATER = [y for y in YEARS if y > 31]
TEXT = ("rtmature", "rtclname")  # input name tables; the shared check compares numbers only
NM = 9


@skip_unless_dumped("wht")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rwhtec(y):
    state, after = before_after("wht", y)
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
    rstvtec(state)
    assert_matches(state, after, tol=1e-6, skip=TEXT)


@skip_unless_dumped("ckc")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rstovcon(y):
    state, after = before_after("ckc", y)
    rstovcon(state)
    assert_matches(state, after, tol=1e-6, skip=TEXT)


@skip_unless_dumped("whc")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rwhcon(y):
    state, after = before_after("whc", y)
    rwhcon(state)
    assert_matches(state, after, tol=1e-6, skip=TEXT)
