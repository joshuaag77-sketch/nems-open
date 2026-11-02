"""CALBSC port vs the industrial oracle's internal state.

Feeds the port the state just before EIA's routine ran (bsc_in) for the last
industry and region of the year (24, 4), and compares BSFUELSHR and BSSHR with
what EIA's routine left (bsc_out). Skipped until the oracle has run.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.industrial.boiler_shares import calbsc

YEARS = [36, 37, 38, 41, 51, 61]  # 2025 on; the earlier dump years never reach CALBSC in a final pass
NEED = ["inddir", "indreg", "curcalyr", "ibyr", "lastcalyr", "mainfuels", "bscibyr", "beff", "prcx", "prcxibyr",
        "bsfuelshr", "bsshr"]
TOL = 1e-4

pytestmark = pytest.mark.skipif(not oracle_state.available("bsc_out", 61, "ind"), reason="oracle state not dumped")


def rel_err(mine, eia):
    mine, eia = np.asarray(mine, dtype=np.float64), np.asarray(eia, dtype=np.float64)
    return float((np.abs(mine - eia) / np.maximum(np.abs(eia), 1e-6)).max())


_cache = {}


def run(y):
    if y not in _cache:
        before, after = oracle_state.load("bsc_in", y, "ind", NEED), oracle_state.load("bsc_out", y, "ind", NEED)
        s = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in before.items()}
        calbsc(s, int(s["inddir"]), int(s["indreg"]))
        _cache[y] = s, after
    return _cache[y]


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
def test_bsfuelshr(y):
    s, after = run(y)
    d, r = int(s["inddir"]), int(s["indreg"])
    assert rel_err(s["bsfuelshr"][d, r, 1:24], after["bsfuelshr"][d, r, 1:24]) < TOL


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
def test_bsshr(y):
    s, after = run(y)
    assert rel_err(s["bsshr"].a, after["bsshr"].a) < TOL
