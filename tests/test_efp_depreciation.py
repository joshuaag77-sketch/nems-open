"""EFP depreciation ports (src/nems_open/emm/efp/depreciation.py) against the oracle."""

import pytest

from emm_oracle import REGION_YEARS, REGIONS, assert_matches, available, before_after
from nems_open.emm.efp import depreciation


def _cases(tag):
    return [
        pytest.param(
            y, r, id=f"{1989 + y}-r{r}",
            marks=pytest.mark.skipif(not (available(f"{tag}_in", y) and available(f"{tag}_out", y)),
                                     reason=f"EMM oracle state for {tag} not dumped for year index {y}"))
        for y in REGION_YEARS for r in REGIONS
    ]


@pytest.mark.parametrize("y,r", _cases("x_itc"))
def test_elitc(y, r):
    s, after = before_after("x_itc", y, r)
    depreciation.elitc(s)
    assert_matches(s, after, tol=1e-6)


@pytest.mark.parametrize("y,r", _cases("x_bkdp"))
def test_elbkdp(y, r):
    s, after = before_after("x_bkdp", y, r)
    depreciation.elbkdp(s, r, "G")
    assert_matches(s, after, tol=1e-6)


@pytest.mark.parametrize("y,r", _cases("x_txdp"))
def test_eltxdp(y, r):
    s, after = before_after("x_txdp", y, r)
    depreciation.eltxdp(s, r, "G")
    assert_matches(s, after, tol=1e-6)


@pytest.mark.parametrize("y,r", _cases("x_tsaf"))
def test_eltsaf(y, r):
    s, after = before_after("x_tsaf", y, r)
    depreciation.eltsaf(s)
    assert_matches(s, after, tol=1e-6)
