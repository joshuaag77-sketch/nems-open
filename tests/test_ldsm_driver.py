"""ELLDSM, the whole LDSM year (driver.py), against the oracle's state around it.

The oracle dumps around ELLDSM on the final iteration of each dump year, so
DSMECP1 (first iteration only) is not exercised here; tests/test_ldsm_ecp.py
covers it.
"""

import pytest

from emm_oracle import YEARS, assert_matches, before_after, skip_unless_dumped
from nems_open.emm.ldsm import driver

ids = lambda y: str(1989 + y)  # noqa: E731


@skip_unless_dumped("ld")
@pytest.mark.parametrize("y", YEARS, ids=ids)
def test_elldsm(y):
    s, after = before_after("ld", y)
    driver.elldsm(s, 1)
    assert_matches(s, after, tol=1e-6)
