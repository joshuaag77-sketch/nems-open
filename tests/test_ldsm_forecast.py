"""LDSM load forecast ports (src/nems_open/emm/ldsm/forecast.py) against the oracle."""

import pytest

from emm_oracle import REGION_YEARS, REGIONS, YEARS, assert_matches, before_after, skip_unless_dumped
from nems_open.emm.ldsm import forecast

ids = lambda y: str(1989 + y)  # noqa: E731


@skip_unless_dumped("ca")
@pytest.mark.parametrize("y", YEARS, ids=ids)
def test_dsmcadj(y):
    s, after = before_after("ca", y)
    forecast.dsmcadj(s)
    assert_matches(s, after, tol=1e-6)


@skip_unless_dumped("fo")
@pytest.mark.parametrize("r", REGIONS)
@pytest.mark.parametrize("y", REGION_YEARS, ids=ids)
def test_dsmfor(y, r):
    s, after = before_after("fo", y, r)
    forecast.dsmfor(s)
    assert_matches(s, after, tol=1e-6)


@skip_unless_dumped("dl")
@pytest.mark.parametrize("r", REGIONS)
@pytest.mark.parametrize("y", REGION_YEARS, ids=ids)
def test_dsmdlt(y, r):
    s, after = before_after("dl", y, r)
    forecast.dsmdlt(s)
    assert_matches(s, after, tol=1e-6)
