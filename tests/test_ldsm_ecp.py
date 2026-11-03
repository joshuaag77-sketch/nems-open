"""LDSM load duration curves for ECP (ecp.py) against the oracle. DSMECP1 runs
from UPSTYR (2025), on the first iteration, so it is dumped in 2030 and 2050."""

import pytest

from emm_oracle import REGIONS, assert_matches, before_after, skip_unless_dumped
from nems_open.emm.ldsm import ecp

ECP_YEARS = [41, 61]
ids = lambda y: str(1989 + y)  # noqa: E731


@skip_unless_dumped("lc", 41)
@pytest.mark.parametrize("r", REGIONS)
@pytest.mark.parametrize("y", ECP_YEARS, ids=ids)
def test_dsmlcp(y, r):
    s, after = before_after("lc", y, r)
    ecp.dsmlcp(s, 1)
    assert_matches(s, after, tol=1e-6)


@skip_unless_dumped("e1", 41)
@pytest.mark.parametrize("r", REGIONS)
@pytest.mark.parametrize("y", ECP_YEARS, ids=ids)
def test_dsmecp1(y, r):
    s, after = before_after("e1", y, r)
    ecp.dsmecp1(s)
    assert_matches(s, after, tol=1e-6)
