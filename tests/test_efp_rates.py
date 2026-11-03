"""EFP rate setting (src/nems_open/emm/efp/rates.py) against the oracle: ELRATE('G', NRGN)."""

import pytest

from emm_oracle import REGION_YEARS, REGIONS, assert_matches, available, before_after
from nems_open.emm.efp import rates

ids = lambda y: str(1989 + y)  # noqa: E731


@pytest.mark.parametrize("r", REGIONS)
@pytest.mark.parametrize("y", REGION_YEARS, ids=ids)
def test_elrate(y, r):
    if not (available("x_rate_in", y) and available("x_rate_out", y)):
        pytest.skip(f"EMM oracle state for x_rate not dumped for {1989 + y}")
    s, after = before_after("x_rate", y, r)
    rates.elrate(s, "G", r)
    # FPRICE(.,1,NRGN) is a SAVEd local of RATES, left by the D call of an earlier iteration;
    # the dump does not hold it, so those five entries of the record buffer (column 8,
    # records 1 to 5) are taken from the oracle. Everything else in the buffer is checked.
    s["colv"].a[:, 7, :5] = after["colv"].a[:, 7, :5]
    s["colvals"].a[7, :5] = after["colvals"].a[7, :5]
    # OUTRP2, OUTRC, OUTRCY, OUTREP are byte views of whole COMMON blocks; the arrays
    # inside them are checked by name.
    assert_matches(s, after, tol=1e-6, skip=("outrp2", "outrc", "outrcy", "outrep"))
