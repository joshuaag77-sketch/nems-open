"""COGINIT port vs the industrial oracle's internal state.

Feeds the port the state just before EIA's routine ran (<tag>_in) and compares the
CHP arrays with what the routine left (<tag>_out), for the last industry that
reaches CALGEN (cinit: 21, region 4) and for food, bulk chemicals and wood
products. Skipped until the oracle has run.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.industrial.cogen_init import coginit

YEARS = [36, 37, 38, 41, 51, 61]  # 2025 on
TAGS = ["cinit", "cinit7", "cinit9", "cinit19"]
ADD = [f"cogadd_{c}" for c in ("year", "industry", "censusdiv", "fuelind", "gen", "cap", "thr", "elc")]
NEED = ["inddir", "indreg", "iyr", "curiyr", "maxcogyr", "numflchp", "nadds", "coggen", "cogcap", "cogthr",
        "cogelf", "coggrd"] + ADD
OUT = ["coggen", "cogcap", "cogthr", "cogelf", "coggrd"]
TOL = 1e-4

pytestmark = pytest.mark.skipif(not oracle_state.available("cinit_out", 61, "ind"), reason="oracle state not dumped")

_cache = {}


def run(tag, y):
    if (tag, y) not in _cache:
        before = oracle_state.load(f"{tag}_in", y, "ind", NEED)
        after = oracle_state.load(f"{tag}_out", y, "ind", NEED)
        s = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in before.items()}
        coginit(s, int(s["inddir"]), int(s["indreg"]))
        _cache[(tag, y)] = s, after
    return _cache[(tag, y)]


def rel_err(mine, eia):
    mine, eia = np.asarray(mine, dtype=np.float64), np.asarray(eia, dtype=np.float64)
    return float((np.abs(mine - eia) / np.maximum(np.abs(eia), 1e-6)).max())


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("tag", TAGS)
@pytest.mark.parametrize("name", OUT)
def test_coginit(tag, y, name):
    if not oracle_state.available(f"{tag}_out", y, "ind"):
        pytest.skip(f"{tag} not dumped")
    s, after = run(tag, y)
    assert rel_err(s[name].a, after[name].a) < TOL
