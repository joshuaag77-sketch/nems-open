"""EFP financial statements (src/nems_open/emm/efp/statements.py) against the oracle."""

import pytest

from emm_oracle import REGION_YEARS, REGIONS, assert_matches, available, before_after
from nems_open.emm.efp import statements

ids = lambda y: str(1989 + y)  # noqa: E731

# OUTREP/OUTRP2 are character buffers equivalenced onto the report arrays (EFPREP, EFPRP2);
# they are checked below by packing the arrays instead of by number.
REPORTS = ["revreq", "taxinc", "balsht", "funds", "xincst", "capreq", "sales", "cstcap", "canplt", "ppcost"]


@pytest.mark.parametrize("r", REGIONS)
@pytest.mark.parametrize("y", REGION_YEARS, ids=ids)
def test_stmts(y, r):
    if not available("x_stmt_out", y):
        pytest.skip("EMM oracle state for x_stmt not dumped")
    s, after = before_after("x_stmt", y, r)
    statements.stmts(s, r, "G")
    worst = assert_matches(s, after, tol=1e-6, skip=("outrep", "outrp2"))
    print(f"worst relative error {max(worst.values()):.3g}")
    # the buffers STRREP/STRRP2 would save: the report arrays packed in COMMON order
    packed = b"".join(s[k].a.tobytes(order="F") for k in REPORTS)
    assert packed.rstrip(b"\0") == bytes(after["outrep"])
    assert s["demrep"].a.tobytes(order="F") == bytes(after["outrp2"])[: s["demrep"].a.size * 4]
