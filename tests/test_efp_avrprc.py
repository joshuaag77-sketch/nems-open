"""AVRPRC chained (src/nems_open/emm/efp/avrprc.py) against the oracle's state
around each AVRPRC call: generation, transmission and distribution, on the
first iteration (where the capital accounts roll forward) and the final one.
The routine tests only cover generation; this is the check on T and D."""

import pytest

from emm_oracle import REGION_YEARS, REGIONS, assert_matches, available, before_after
from nems_open.emm.efp import avrprc
from test_efp_phasein import _fix_efpnd  # until the oracle is rebuilt (REAL *4 dump fix)

ids = lambda y: str(1989 + y)  # noqa: E731
CASES = [("ag", "G"), ("at", "T"), ("ad", "D"), ("ag1", "G"), ("at1", "T"), ("ad1", "D")]


@pytest.mark.parametrize("r", REGIONS)
@pytest.mark.parametrize("y", REGION_YEARS, ids=ids)
@pytest.mark.parametrize("tag,icall", CASES, ids=[t for t, _ in CASES])
def test_avrprc(tag, icall, y, r):
    if not (available(f"{tag}_in", y) and available(f"{tag}_out", y)):
        pytest.skip(f"no {tag} dump for {1989 + y}")
    s, after = before_after(tag, y, r)
    _fix_efpnd(s, f"{tag}_in", y, r)
    _fix_efpnd(after, f"{tag}_out", y, r)
    avrprc.avrprc(s, r, icall)
    # As in test_efp_rates: FPRICE(.,1,NRGN), a SAVEd local of RATES left by an
    # earlier D call, is not in the dump; take those five buffer entries from the oracle.
    s["colv"].a[:, 7, :5] = after["colv"].a[:, 7, :5]
    s["colvals"].a[7, :5] = after["colvals"].a[7, :5]
    assert_matches(s, after, tol=1e-6, skip=("outrp2", "outrc", "outrcy", "outrep", "ebildn"))  # byte views of whole blocks
