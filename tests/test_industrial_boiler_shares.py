"""CALBSC port vs the industrial oracle's internal state.

Feeds the port the state just before EIA's routine ran (<tag>_in) and compares
BSFUELSHR and BSSHR with what the routine left (<tag>_out). The oracle dumps one
industry and region per tag: the last one of the year (bsc: 24, 4), plus mining
(3, 1: nonmanufacturing, no coal boilers) and food (7, 3). Skipped until the
oracle has run.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.industrial.boiler_shares import calbsc

YEARS = [36, 37, 38, 41, 51, 61]  # 2025 on; the earlier dump years never reach CALBSC in a final pass
TAGS = ["bsc", "bsc3", "bsc7"]
NEED = ["inddir", "indreg", "curcalyr", "ibyr", "lastcalyr", "mainfuels", "bscibyr", "beff", "prcx", "prcxibyr",
        "bsfuelshr", "bsshr"]
TOL = 1e-4

pytestmark = pytest.mark.skipif(not oracle_state.available("bsc_out", 61, "ind"), reason="oracle state not dumped")

_cache = {}


def rel_err(mine, eia):
    mine, eia = np.asarray(mine, dtype=np.float64), np.asarray(eia, dtype=np.float64)
    return float((np.abs(mine - eia) / np.maximum(np.abs(eia), 1e-6)).max())


def run(tag, y):
    if (tag, y) not in _cache:
        before, after = oracle_state.load(f"{tag}_in", y, "ind", only=NEED), oracle_state.load(f"{tag}_out", y, "ind", only=NEED)
        s = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in before.items()}
        calbsc(s, int(s["inddir"]), int(s["indreg"]))
        _cache[(tag, y)] = s, after
    return _cache[(tag, y)]


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("tag", TAGS)
def test_bsfuelshr(tag, y):
    s, after = run(tag, y)
    d, r = int(s["inddir"]), int(s["indreg"])
    assert rel_err(s["bsfuelshr"][d, r, 1:24], after["bsfuelshr"][d, r, 1:24]) < TOL


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("tag", TAGS)
def test_bsshr(tag, y):
    s, after = run(tag, y)
    assert rel_err(s["bsshr"].a, after["bsshr"].a) < TOL
