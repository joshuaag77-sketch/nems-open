"""CALBTOT port vs the industrial oracle's internal state.

The routine keeps base-year production and employment between calls (locals that stay
set); the oracle dumps them with the call, and the port is seeded from that.
One industry and region per tag: 24/4, 1/1, 7/3, 8/2 (process flow), 12/1. Skipped
until the oracle has run.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.industrial.buildings import calbtot

YEARS = [36, 37, 38, 41, 51, 61]
TAGS = ["", "1", "7", "8", "12"]
NEED = ["inddir", "indreg", "curiyr", "ibyr2", "baseyr", "emplx", "prodvx", "enbint", "enbqty", "prcxyr", "prodvxibyr", "emplxibyr"]
TOL = 1e-4

pytestmark = pytest.mark.skipif(not oracle_state.available("btot_out", 61, "ind"), reason="oracle state not dumped")

_cache = {}


def load(tag, y):
    k = (tag, y)
    if k not in _cache:
        _cache[k] = (oracle_state.load(f"{tag}_in", y, "ind", only=NEED), oracle_state.load(f"{tag}_out", y, "ind", only=NEED))
    return _cache[k]


def run(t, y):
    before, after = load(f"btot{t}", y)
    s = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in before.items()}
    d, r = int(s["inddir"]), int(s["indreg"])
    base = {(d, r): (np.float32(after["prodvxibyr"][d, r]), np.float32(after["emplxibyr"][d, r]))}
    calbtot(s, base)
    return s, after


def rel_err(mine, eia):
    mine, eia = np.asarray(mine, dtype=np.float64), np.asarray(eia, dtype=np.float64)
    return float((np.abs(mine - eia) / np.maximum(np.abs(eia), 1e-6)).max())


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("t", TAGS)
def test_calbtot(t, y):
    if not oracle_state.available(f"btot{t}_out", y, "ind"):
        pytest.skip("not dumped")
    s, after = run(t, y)
    mine, eia = s["enbqty"], after["enbqty"]
    assert rel_err(getattr(mine, "a", mine), getattr(eia, "a", eia)) < TOL
