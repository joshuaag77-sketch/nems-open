"""LDSM load duration curves for EFD (efd.py) against the oracle."""

import pytest

from emm_oracle import REGION_YEARS, REGIONS, assert_matches, before_after, skip_unless_dumped
from nems_open.emm.ldsm import efd

ids = lambda y: str(1989 + y)  # noqa: E731


@skip_unless_dumped("ef")
@pytest.mark.parametrize("r", REGIONS)
@pytest.mark.parametrize("y", REGION_YEARS, ids=ids)
def test_dsmefd(y, r):
    s, after = before_after("ef", y, r)
    efd.dsmefd(s)
    assert_matches(s, after, tol=1e-6)
