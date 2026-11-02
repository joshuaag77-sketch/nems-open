"""COMConsumption port vs the oracle's internal state.

Feeds the port the state just before EIA's routine ran (cn_in), plus inputs only
the routine sees (on-site generation outputs, minor-fuel tables, switches: from
cn_out) and the arrays it shares with technology choice (tc_out), and compares
what it writes with cn_out. Skipped until the oracle has run.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.commercial.consumption import consumption

YEARS = [30, 31, 32, 36, 37, 38, 41, 51, 61]
TOL = 1e-4

FROM_CN_OUT = ["trills", "trillsownuse", "shbtu", "hwbtu", "fuelusage", "flooradj", "defaultprices",
               "ifueltype", "ntek", "steodat", "flagregsteo", "ef1", "ef2", "ef3", "nrgbill",
               "prsvstdsavings", "foodsvchlthldgfloortot", "unbenchedcon", "cmfinalunbenchuse",
               "solarpvcontrib", "minfuelalpha", "minfuelbeta"]
FROM_TC_OUT = ["sdbyfuel", "equipsd"]

pytestmark = pytest.mark.skipif(not oracle_state.available("cn_out", 30), reason="oracle state not dumped")

_cache = {}


def result(y):
    if y not in _cache:
        before, after, tc = oracle_state.load("cn_in", y), oracle_state.load("cn_out", y), oracle_state.load("tc_out", y)
        inp = dict(before)
        for k in FROM_CN_OUT:
            inp[k] = after[k]
        for k in FROM_TC_OUT:
            inp[k] = tc[k]
        _cache[y] = consumption(inp, y), after
    return _cache[y]


def rel_err(mine, eia):
    mine, eia = np.asarray(mine, dtype=np.float64), np.asarray(eia, dtype=np.float64)
    return float((np.abs(mine - eia) / np.maximum(np.abs(eia), 1e-6)).max())


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("name", [
    "enduseconsump", "euconwithdg", "cmeffind", "finalendusecon", "unbenchedcon", "cmfinalenduse",
    "cmfinalunbenchuse", "cmusconsumption", "cmusavgeff", "distservconsump", "distservsteam",
    "cmusdistserv", "cmfinalendusecon", "solarpvcontrib", "solarrenewablecontrib", "cmseds",
])
def test_consumption(y, name):
    out, after = result(y)
    assert rel_err(out[name].a, after[name].a) < TOL, name
