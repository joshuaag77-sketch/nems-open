"""Clothes washer and dishwasher ports vs the residential oracle's state."""

import pytest

from resd_oracle import YEARS, assert_matches, before_after, skip_unless_dumped
from nems_open.residential.washers import (rcwadd, rcwcon, rcwtec,
                                           rdwadd, rdwcon, rdwtec)

LATER = [y for y in YEARS if y > 31]  # yearly routines have no 2020 dump


def run(tag, y, routine):
    state, after = before_after(tag, y)
    routine(state)
    return state, after


@skip_unless_dumped("cwt")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rcwtec(y):
    state, after = run("cwt", y, rcwtec)
    assert_matches(state, after, tol=1e-6)


@skip_unless_dumped("cwa")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rcwadd(y):
    state, after = run("cwa", y, rcwadd)
    assert_matches(state, after, tol=1e-6)


@skip_unless_dumped("cwc")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rcwcon(y):
    state, after = run("cwc", y, rcwcon)
    assert_matches(state, after, tol=1e-6)


@skip_unless_dumped("dwt")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rdwtec(y):
    state, after = run("dwt", y, rdwtec)
    assert_matches(state, after, tol=1e-6)


@skip_unless_dumped("dwa")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rdwadd(y):
    state, after = run("dwa", y, rdwadd)
    assert_matches(state, after, tol=1e-6)


@skip_unless_dumped("dwc")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rdwcon(y):
    state, after = run("dwc", y, rdwcon)
    assert_matches(state, after, tol=1e-6)
