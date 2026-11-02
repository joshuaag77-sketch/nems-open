"""RDPR, NEWHSE and SQFTCALC ports vs the residential oracle's state."""

import pytest

from resd_oracle import YEARS, assert_matches, before_after, skip_unless_dumped
from nems_open.residential.housing import newhse, rdpr, sqftcalc

LATER = [y for y in YEARS if y > 31]  # NEWHSE and SQFTCALC start the year after RECS


@skip_unless_dumped("pr")
@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
def test_rdpr(y):
    state, after = before_after("pr", y)
    rdpr(state)
    assert_matches(state, after, tol=1e-6)


@skip_unless_dumped("nh")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_newhse(y):
    state, after = before_after("nh", y)
    newhse(state)
    assert_matches(state, after, tol=1e-6)


@skip_unless_dumped("sq")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_sqftcalc(y):
    state, after = before_after("sq", y)
    sqftcalc(state)
    assert_matches(state, after, tol=1e-6)
