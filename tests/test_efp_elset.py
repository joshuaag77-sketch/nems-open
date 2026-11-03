"""EFP ELSET and REVGAP (src/nems_open/emm/efp/elset.py) against the oracle."""

import pytest

from emm_oracle import YEARS, assert_matches, available, before_after
from nems_open.emm.efp import elset

ids = lambda y: str(1989 + y)  # noqa: E731


@pytest.mark.parametrize("y", YEARS, ids=ids)
def test_elset(y):
    if not available("se_out", y):
        pytest.skip("EMM oracle state for se not dumped")
    s, after = before_after("se", y)
    elset.elset(s)
    assert_matches(s, after, tol=1e-6)


@pytest.mark.parametrize("y", YEARS, ids=ids)
def test_revgap(y):
    if not available("rv_out", y):
        pytest.skip("EMM oracle state for rv not dumped")
    s, after = before_after("rv", y)
    # the rv dump has no EFPFCRL; the se dump of the same year (same final iteration) has it
    flag = before_after("se", y)[0]["efpfcrl"] if available("se_in", y) else 1
    if flag == 1:
        elset.revgap(s)
    assert_matches(s, after, tol=1e-6)
