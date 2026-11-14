"""CALGEN port vs the industrial oracle's internal state.

Feeds the port the state just before EIA's routine ran (<tag>_in) and compares the
CHP arrays, the on-site and grid generation and the steam quantities with what the
routine left (<tag>_out), for the last industry that reaches CALGEN (cgen: 21,
region 4), food, bulk chemicals, wood products and agriculture. Skipped until the
oracle has run.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.industrial.cogen import calgen

YEARS = [36, 37, 38, 41, 51, 61]  # 2025 on
TAGS = ["cgen", "cgen7", "cgen9", "cgen19", "cgen1"]
ADD = [f"cogadd_{c}" for c in ("year", "industry", "censusdiv", "fuelind", "gen", "cap", "thr", "elc")]
EVAL = ["nsys", "nload", "cfelq", "capcostyearly", "cheatrateyearly", "overalleffyearly", "cogsizekw", "capfac",
        "qelas", "capcostmultstart", "capcostmultend", "capcostmult", "mc_rmtcm10y", "mc_cpi", "acceptfrac",
        "acceptfrac2", "cogcapcostkw", "cheatrate", "overalleff", "elecgeneff", "elecsizemwh", "fueluse",
        "powersteam", "steamoutput", "eboileff", "cogsys", "fuelcost", "existfueluse", "existfuelcost",
        "elecvalue", "incrfuelcost", "operprofit", "investment", "cpayback", "econfrac"]
NEED = (["inddir", "indreg", "iyr", "curiyr", "curcalyr", "baseyr", "ibyr2", "maxcogyr", "numflchp", "nadds",
         "lookahead", "ijumpyr", "ieyr", "dollaryearchp", "standbyfrac", "carbshr_ab", "qgfin", "qelin", "agfin",
         "pgfin", "aelin", "prcx", "mc_jpgdp", "steamseg_food", "steamseg_paper", "steamseg_chem",
         "steamseg_steel", "steamseg_other", "stemcurlag", "ifsbyp", "ifslocby", "bypbscm", "bypbsci", "bypbscr",
         "enbqty", "enpiqty", "penetration", "cogsteamhist", "regchputil", "maxregchputil", "cogfuelprice",
         "cogelecprice", "stemcur", "bypstmm", "bypstmi", "bypstmr", "bypstm", "elown", "elsale", "coggen",
         "cogcap", "cogthr", "cogelf", "coggrd"] + ADD + EVAL)
OUT = ["coggen", "cogcap", "cogthr", "cogelf", "coggrd", "elsale", "elown", "stemcur", "bypstmm", "bypstmi",
       "bypstmr", "bypstm", "regchputil", "maxregchputil", "cogfuelprice", "cogelecprice", "econfrac", "powersteam"]
TOL = 1e-4

pytestmark = pytest.mark.skipif(not oracle_state.available("cgen_out", 61, "ind"), reason="oracle state not dumped")

_cache = {}


def run(tag, y):
    if (tag, y) not in _cache:
        before = oracle_state.load(f"{tag}_in", y, "ind", only=NEED)
        after = oracle_state.load(f"{tag}_out", y, "ind", only=NEED)
        s = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in before.items()}
        calgen(s, int(s["inddir"]), int(s["indreg"]))
        _cache[(tag, y)] = s, after
    return _cache[(tag, y)]


def rel_err(mine, eia):
    mine, eia = np.asarray(mine, dtype=np.float64), np.asarray(eia, dtype=np.float64)
    return float((np.abs(mine - eia) / np.maximum(np.abs(eia), 1e-6)).max())


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("tag", TAGS)
@pytest.mark.parametrize("name", OUT)
def test_calgen(tag, y, name):
    if not oracle_state.available(f"{tag}_out", y, "ind"):
        pytest.skip(f"{tag} not dumped")
    s, after = run(tag, y)
    mine, eia = s[name], after[name]
    assert rel_err(getattr(mine, "a", mine), getattr(eia, "a", eia)) < TOL
