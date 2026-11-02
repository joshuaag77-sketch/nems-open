"""CALSTOT port vs the industrial oracle's internal state.

Feeds the port the state just before EIA's routine ran (<tag>_in) and compares what
it writes with what the routine left (<tag>_out). The oracle dumps one industry and
region per tag: the last one of the year (stot: 24, 4, which has no CHP) and the
food, bulk chemicals, wood products and mining cases, which have CHP and biomass.
Skipped until the oracle has run.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.industrial.boiler_totals import calstot

YEARS = [36, 37, 38, 41, 51, 61]  # 2025 on
TAGS = ["stot", "stot3", "stot7", "stot9", "stot19"]
NEED = ["inddir", "indreg", "iyr", "curcalyr", "ibyr", "baseyr", "numflchp", "mainfuels", "maxcogyr", "beff",
        "bscibyr", "bsshr", "cogthr", "cogelf", "coggrd", "cogcap", "coggen", "genfuel", "rptcap", "rptgen",
        "cogsteam", "biosteam", "biosteamlag", "prodvx", "prodvxlag", "stemcur", "noncogsteam", "noncogfossteam",
        "cogboilfuel", "fuelfossteam", "fosfuelsteamsize", "sizeshr", "calibibyr_fos", "calibibyr_bio", "boilibyr",
        "stemcuribyr", "cogsteamibyr", "biosteamibyr", "ensqty", "enprqty", "cogsteamhist"]
OUT = ["genfuel", "rptcap", "rptgen", "cogsteam", "biosteam", "biosteamlag", "noncogsteam", "noncogfossteam",
       "cogboilfuel", "fuelfossteam", "fosfuelsteamsize", "ensqty", "enprqty", "bscibyr", "cogsteamhist"]
TOL = 1e-4

pytestmark = pytest.mark.skipif(not oracle_state.available("stot_out", 61, "ind"), reason="oracle state not dumped")

_cache = {}


def run(tag, y):
    if (tag, y) not in _cache:
        before = oracle_state.load(f"{tag}_in", y, "ind", NEED)
        after = oracle_state.load(f"{tag}_out", y, "ind", NEED)
        s = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in before.items()}
        calstot(s, int(s["inddir"]), int(s["indreg"]))
        _cache[(tag, y)] = s, after
    return _cache[(tag, y)]


def rel_err(mine, eia):
    mine, eia = np.asarray(mine, dtype=np.float64), np.asarray(eia, dtype=np.float64)
    return float((np.abs(mine - eia) / np.maximum(np.abs(eia), 1e-6)).max())


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("tag", TAGS)
@pytest.mark.parametrize("name", OUT)
def test_calstot(tag, y, name):
    if not oracle_state.available(f"{tag}_out", y, "ind"):
        pytest.skip(f"{tag} not dumped")
    s, after = run(tag, y)
    mine, eia = s[name], after[name]
    assert rel_err(getattr(mine, "a", mine), getattr(eia, "a", eia)) < TOL
