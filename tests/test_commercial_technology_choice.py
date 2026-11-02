"""COMTechnologyChoice port vs the oracle's internal state.

Feeds the port the state just before EIA's routine ran (tc_in), the values it
carries between iterations (tc_pre) and the arrays it shares with service demand,
then compares everything the routine writes with tc_out. 2019 is skipped: it is
the first call, which also reads files and edits cost tables (not ported here).
Slow (pure-Python loops), so only a few years run by default.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.commercial.technology_choice import Carry, technology_choice
from nems_open.fortran_array import FArray

YEARS = [31, 37, 51]  # 2020, 2026, 2040
TOL = 1e-4

# Private to the routine or shared only with service demand: taken from tc_out.
FROM_OUT_INPUTS = ["nsdnoshell", "rsdnoshell", "ssdnoshell", "stretbehav", "costtrendswitch"]
# Private outputs: start from zeros so the port has to write them.
ZEROED_OUTPUTS = ["sdbyfuel", "purchtechshare", "equipsd", "whse_eff", "whse_sd"]

pytestmark = pytest.mark.skipif(not oracle_state.available("tc_out", 31), reason="oracle state not dumped")


def run(y):
    before = oracle_state.load("tc_in", y)
    after = oracle_state.load("tc_out", y)
    pre = oracle_state.load("tc_pre", y)
    inp = dict(before)
    for k in FROM_OUT_INPUTS:
        inp[k] = after[k]
    for k in ZEROED_OUTPUTS:
        inp[k] = FArray(np.zeros_like(after[k].a), after[k].lb)
    carry = Carry(list(pre["iforward"].a), int(pre["ifwd"]), int(pre["ifmax"]),
                  int(pre["ilaststeoyr"]), int(pre["elasbaseyr"]))
    return technology_choice(inp, carry, y), after


_cache = {}


def result(y):
    if y not in _cache:
        _cache[y] = run(y)
    return _cache[y]


def rel_err(mine, eia):
    mine, eia = np.asarray(mine, dtype=np.float64), np.asarray(eia, dtype=np.float64)
    return float((np.abs(mine - eia) / np.maximum(np.abs(eia), 1e-6)).max())


def year_slice(arr: FArray, y):
    """The given year's slice of an array whose last dimension is year."""
    return arr.a[..., y - arr.lb[-1]]


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("name", [
    "techshareofservice", "fuelshareofservice", "averageefficiency", "ms", "purchtechshare",
])
def test_shares(y, name):
    out, after = result(y)
    assert rel_err(out[name].a, after[name].a) < TOL, name


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("name", [
    "investcost", "subsidyinvestcost", "subsidy111dinvestcost", "decfuelshare", "decavgeff",
    "sdbyfuel", "equipsd", "whse_eff", "whse_sd", "cmusavgeff", "whse_heatindex", "whse_ventindex",
    "whse_lightindex", "whse_shellindex",
])
def test_yearly(y, name):
    out, after = result(y)
    assert rel_err(year_slice(out[name], y), year_slice(after[name], y)) < TOL, name
