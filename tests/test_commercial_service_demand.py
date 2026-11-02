"""COMServiceDemand port vs the oracle's internal state.

Feeds the port the oracle's state just before EIA's routine ran (sd_in) plus the
routine's own input tables (dumped at sd_out), and compares what the port computes
with the oracle's state just after (sd_out). Skipped until the oracle has run.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.commercial.service_demand import NUM_DIV, service_demand
from nems_open.fortran_array import FArray

YEARS = [30, 31, 32, 36, 37, 38, 41, 51, 61]  # 2019 ... 2050
TOL = 1e-4

# The routine's private input tables, constant after the first call.
PRIVATE_INPUTS = ["existimprvht", "existimprvcl", "dcf", "marketpenetrationmels", "melselq",
                  "servicesindex", "xplicitmiscshr", "datactrservpenetration", "officepcpenetration",
                  "marketpenetrationsc", "pctscsavings", "ct_flag", "applyramp"]

pytestmark = pytest.mark.skipif(not oracle_state.available("sd_out", 30), reason="oracle state not dumped")


def run(y):
    before = oracle_state.load("sd_in", y)
    after = oracle_state.load("sd_out", y)
    inp = dict(before)
    for k in PRIVATE_INPUTS:
        inp[k] = after[k]
    for k in ("ssdnoshell", "nsdnoshell", "rsdnoshell"):
        inp[k] = FArray(np.zeros_like(after[k].a), after[k].lb)
    inp["totexplicitmiscelq"] = FArray(np.zeros_like(after["totexplicitmiscelq"].a), after["totexplicitmiscelq"].lb)
    return service_demand(inp, y), after


def rel_err(mine, eia):
    mine, eia = np.asarray(mine, dtype=np.float64), np.asarray(eia, dtype=np.float64)
    return float((np.abs(mine - eia) / np.maximum(np.abs(eia), 1e-6)).max())


@pytest.fixture(scope="module", params=YEARS, ids=lambda y: str(1989 + y))
def case(request):
    y = request.param
    res, after = run(y)
    return y, res, after


@pytest.mark.parametrize("name", ["ServDmdExBldg", "NewServDmd", "ServDmdSurv", "RetireServDmd"])
def test_service_demand(case, name):
    y, res, after = case
    mine, eia = getattr(res, name), after[name.lower()]
    regions = slice(1, 11) if name != "ServDmdExBldg" else slice(1, NUM_DIV)
    assert rel_err(mine[:, :, regions, y], eia[:, :, regions, y]) < TOL


def test_shell_factors(case):
    y, res, after = case
    assert rel_err(res.ShellHeatFactor[:, :, 1, y], after["shellheatfactor"][:, :, 1, y]) < TOL
    assert rel_err(res.ShellCoolFactor[:, :, 1, y], after["shellcoolfactor"][:, :, 1, y]) < TOL


def test_misc_loads(case):
    y, res, after = case
    assert abs(res.DatCtrShare - float(after["datctrshare"])) < 1e-7
    for name, value in res.mel_totals.items():
        assert value == pytest.approx(float(after[name.lower()]), rel=TOL), name
    assert rel_err(res.TotExplicitMiscElQ[:, :, y], after["totexplicitmiscelq"][:, :, y]) < TOL
