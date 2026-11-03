"""LDSM hourly load and outputs (system_load.py, outputs.py) against the oracle."""

import pytest

from emm_oracle import REGION_YEARS, REGIONS, assert_matches, before_after, skip_unless_dumped
from nems_open.emm.ldsm import outputs, system_load

ids = lambda y: str(1989 + y)  # noqa: E731


def test_dsmqsr_sorts_descending_with_index():
    vals = [0.0, 3.0, 9.0, 1.0, 9.0, 4.0, 4.0, 7.0, 2.0, 8.0, 6.0, 5.0, 0.5]
    idx = list(range(len(vals)))
    system_load.dsmqsr(vals, idx, 1, len(vals) - 1)
    assert vals[1:] == sorted(vals[1:], reverse=True)
    assert sorted(idx[1:]) == list(range(1, len(vals)))


@skip_unless_dumped("hl")
@pytest.mark.parametrize("r", REGIONS)
@pytest.mark.parametrize("y", REGION_YEARS, ids=ids)
def test_dsmhlm(y, r):
    s, after = before_after("hl", y, r)
    system_load.dsmhlm(s)
    assert_matches(s, after, tol=1e-6)


@skip_unless_dumped("ep")
@pytest.mark.parametrize("r", REGIONS)
@pytest.mark.parametrize("y", REGION_YEARS, ids=ids)
def test_dsmefp(y, r):
    s, after = before_after("ep", y, r)
    outputs.dsmefp(s)
    assert_matches(s, after, tol=1e-6)


@skip_unless_dumped("to")
@pytest.mark.parametrize("r", REGIONS)
@pytest.mark.parametrize("y", REGION_YEARS, ids=ids)
def test_dsmtor(y, r):
    s, after = before_after("to", y, r)
    outputs.dsmtor(s)
    assert_matches(s, after, tol=1e-6)
