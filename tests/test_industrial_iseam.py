"""INDBIFURC port vs the industrial oracle: blended covered/uncovered industry prices."""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.industrial.iseam import electricity_price_slot, indbifurc

YEARS = [36, 37, 38, 41, 51, 61]
TAGS = ["bif7", "bif1", "bif24", "bif3"]

pytestmark = pytest.mark.skipif(not oracle_state.available("bif7_out", 61, "ind"), reason="oracle state not dumped")


def rel(a, b):
    a, b = np.asarray(getattr(a, "a", a), dtype=np.float64), np.asarray(getattr(b, "a", b), dtype=np.float64)
    return float((np.abs(a - b) / np.maximum(np.abs(b), 1e-4)).max())


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("tag", TAGS)
def test_indbifurc(tag, y):
    if not oracle_state.available(f"{tag}_out", y, "ind"):
        pytest.skip("not dumped")
    need = ["inddir", "indreg", "curiyr", "prcx", "prcxyr", "prcxlag", "carbshr_ab", "carbshr"]
    before = oracle_state.load(f"{tag}_in", y, "ind", only=need)
    after = oracle_state.load(f"{tag}_out", y, "ind", only=need)
    s = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in before.items()}
    indbifurc(s)
    for n in ("prcx", "prcxyr", "prcxlag"):
        assert rel(s[n], after[n]) < 1e-5, n


def test_electricity_slots():
    assert [electricity_price_slot(i) for i in (7, 12, 14, 18, 1, 24)] == [24, 24, 25, 25, 26, 26]
