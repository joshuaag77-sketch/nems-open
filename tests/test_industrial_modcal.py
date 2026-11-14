"""MODCAL port (end-use industries) vs the industrial oracle: the whole call chain for one
industry and region, from the state before CALL MODCAL('original') to the state after it.
Skipped until the oracle has run.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.industrial.modcal import modcal

YEARS = [36, 37, 38, 41, 51, 61]
TAGS = ["m7", "m1", "m1b", "m24", "m18", "m3", "m6", "m14"]
CHECK = ["qtymain", "qtyintr", "qtyrenw", "tqmain", "manhp", "nonhp", "foodcon", "qtybyind", "enpmqty", "enbqty", "elown", "elsale",
         "prodcur", "enpint", "bypbscr"]
TOL = 5e-4

pytestmark = pytest.mark.skipif(not oracle_state.available("m7_out", 61, "ind"), reason="oracle state not dumped")


def rel_err(a, b):
    a, b = np.asarray(getattr(a, "a", a), dtype=np.float64), np.asarray(getattr(b, "a", b), dtype=np.float64)
    return float((np.abs(a - b) / np.maximum(np.abs(b), 1e-3)).max())


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("tag", TAGS)
def test_modcal(tag, y):
    if not oracle_state.available(f"{tag}_out", y, "ind"):
        pytest.skip("not dumped")
    before = oracle_state.load(f"{tag}_in", y, "ind")
    after = oracle_state.load(f"{tag}_out", y, "ind")
    s = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in before.items()}
    d, r = int(s["inddir"]), int(s["indreg"])
    base = {(d, r): (np.float32(after["prodvxibyr"][d, r]), np.float32(after["emplxibyr"][d, r]))}
    modcal(s, base)
    bad = {n: rel_err(s[n], after[n]) for n in CHECK if n in s and rel_err(s[n], after[n]) > TOL}
    assert not bad, bad
