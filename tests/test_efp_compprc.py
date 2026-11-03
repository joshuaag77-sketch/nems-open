"""EFP competitive pricing (src/nems_open/emm/efp/compprc.py) against the oracle:
COMPPRC(NRGN), which calls RATES2 (final iteration, USW_POL=4)."""

import pytest

from emm_oracle import REGION_YEARS, REGIONS, assert_matches, available, before_after
from nems_open.emm.efp import compprc

ids = lambda y: str(1989 + y)  # noqa: E731


@pytest.mark.parametrize("r", REGIONS)
@pytest.mark.parametrize("y", REGION_YEARS, ids=ids)
def test_compprc(y, r):
    if not (available("cp_in", y) and available("cp_out", y)):
        pytest.skip(f"EMM oracle state for cp not dumped for {1989 + y}")
    s, after = before_after("cp", y, r)
    compprc.compprc(s, r)
    assert_matches(s, after, tol=1e-6)
