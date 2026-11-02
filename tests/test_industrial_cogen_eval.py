"""EVALCOGEN port vs the industrial oracle's internal state.

Feeds the port the state just before EIA's routine ran (<tag>_in) and compares what
it writes with what the routine left (<tag>_out), for the last industry and region
of the year (ecog) and food, bulk chemicals and wood products. Skipped until the
oracle has run.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.industrial.cogen_eval import evalcogen

YEARS = [36, 37, 38, 41, 51, 61]  # 2025 on
TAGS = ["ecog", "ecog7", "ecog9", "ecog19"]
INPUTS = ["nsys", "nload", "indreg", "inddir", "curiyr", "curcalyr", "cfelq", "capcostyearly", "cheatrateyearly",
          "overalleffyearly", "cogsizekw", "capfac", "maxregchputil", "qelas", "cogfuelprice", "cogelecprice",
          "capcostmultstart", "capcostmultend", "capcostmult", "mc_rmtcm10y", "mc_cpi", "acceptfrac", "acceptfrac2"]
OUT = ["cogcapcostkw", "cheatrate", "overalleff", "elecgeneff", "elecsizemwh", "fueluse", "powersteam",
       "steamoutput", "eboileff", "cogsys", "fuelcost", "existfueluse", "existfuelcost", "elecvalue",
       "incrfuelcost", "operprofit", "investment", "cpayback", "econfrac"]
TOL = 1e-4

pytestmark = pytest.mark.skipif(not oracle_state.available("ecog_out", 61, "ind"), reason="oracle state not dumped")

_cache = {}


def run(tag, y):
    if (tag, y) not in _cache:
        before = oracle_state.load(f"{tag}_in", y, "ind", INPUTS + OUT)
        after = oracle_state.load(f"{tag}_out", y, "ind", OUT)
        s = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in before.items()}
        evalcogen(s, int(s["curcalyr"]))
        _cache[(tag, y)] = s, after
    return _cache[(tag, y)]


def rel_err(mine, eia):
    mine, eia = np.asarray(mine, dtype=np.float64), np.asarray(eia, dtype=np.float64)
    return float((np.abs(mine - eia) / np.maximum(np.abs(eia), 1e-6)).max())


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("tag", TAGS)
@pytest.mark.parametrize("name", OUT)
def test_evalcogen(tag, y, name):
    if not oracle_state.available(f"{tag}_out", y, "ind"):
        pytest.skip(f"{tag} not dumped")
    s, after = run(tag, y)
    mine, eia = s[name], after[name]
    assert rel_err(getattr(mine, "a", mine), getattr(eia, "a", eia)) < TOL
