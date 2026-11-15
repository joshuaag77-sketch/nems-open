"""Setup_Mac_and_Price port vs the industrial oracle: state before and after the call, for each dump year."""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.industrial.setup_price import setup_mac_and_price

YEARS = [36, 37, 38, 41, 51, 61]
CHECK = ["outind", "empind", "chemship", "foodship", "dprcx", "dprcxlag", "dconx", "prcx", "prcxlag", "prcxyr",
         "pelinp", "pelins", "pelinm", "pelinh2e", "limeoutput", "bushel"]
TOL = 1e-5

pytestmark = pytest.mark.skipif(not oracle_state.available("smp_out", 61, "ind"), reason="oracle state not dumped")


def rel(a, b):
    a, b = np.asarray(getattr(a, "a", a), dtype=np.float64), np.asarray(getattr(b, "a", b), dtype=np.float64)
    return float((np.abs(a - b) / np.maximum(np.abs(b), 1e-3)).max())


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
def test_setup_mac_and_price(y):
    before = oracle_state.load("smp_in", y, "ind")
    after = oracle_state.load("smp_out", y, "ind")
    s = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in before.items()}
    setup_mac_and_price(s)
    bad = {n: rel(s[n], after[n]) for n in CHECK if rel(s[n], after[n]) > TOL}
    assert not bad, bad
