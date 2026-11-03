"""EFP CWIP ports (src/nems_open/emm/efp/cwip.py) against the oracle."""

import pytest

from emm_oracle import REGION_YEARS, REGIONS, assert_matches, available, before_after
from nems_open.emm.efp import cwip

ids = lambda y: str(1989 + y)  # noqa: E731


def _need(tag, y):
    if not available(f"{tag}_out", y):
        pytest.skip(f"EMM oracle state for {tag} not dumped for {1989 + y}")


@pytest.mark.parametrize("r", REGIONS)
@pytest.mark.parametrize("y", REGION_YEARS, ids=ids)
def test_eladcr(y, r):
    _need("x_adcr", y)
    s, after = before_after("x_adcr", y, r)
    cwip.eladcr(s)
    assert_matches(s, after, tol=1e-6)


@pytest.mark.parametrize("r", REGIONS)
@pytest.mark.parametrize("y", REGION_YEARS, ids=ids)
def test_elcwip(y, r):
    _need("x_cwip", y)
    s, after = before_after("x_cwip", y, r)
    cwip.elcwip(s, r, "G")
    assert_matches(s, after, tol=1e-6)
