"""COMBenchmarking port vs the oracle's internal state.

Feeds the port the state just before EIA's routine ran (bm_in) plus the switches only the
routine sees (bm_out) and compares what it writes with bm_out. Skipped until the oracle
has run.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.commercial.benchmarking import benchmarking, read_kemfac

YEARS = [30, 31, 32, 36, 37, 38, 41, 51, 61]
TOL = 1e-4
FROM_BM_OUT = ["solarpvcontrib", "nohist", "decaybm", "lastdecayyr", "steobm2pct"]

pytestmark = pytest.mark.skipif(not oracle_state.available("bm_out", 30), reason="oracle state not dumped")

_cache = {}


def result(y):
    if y not in _cache:
        before, after = oracle_state.load("bm_in", y), oracle_state.load("bm_out", y)
        inp = dict(before)
        for k in FROM_BM_OUT:
            inp[k] = after[k]
        if oracle_state.available("bm_pre", y):
            inp["diffqbm"] = oracle_state.load("bm_pre", y)["diffqbm"]
        # The state before the final iteration still holds the first iteration's results, so clear
        # what the routine writes: the port has to produce it, not inherit it.
        inp["cmnonbldguse"] = inp["cmnonbldguse"].copy()
        inp["cmnonbldguse"][:, 1:9, y] = 0.0  # divisions 10 and 11 are not rewritten
        for k in ("qelcm", "qngcm", "qgfcm", "qgicm", "qdscm", "qrscm", "qrlcm", "qlgcm", "qprcm", "qclcm",
                  "qmgcm", "qkscm", "qstcm", "qpvcm", "qbmcm"):
            inp[k] = inp[k].copy()
            inp[k][1:9, y] = 0.0  # division 10 is not rewritten; 11 is the US total
        for k in ("emcm", "emcmc"):
            inp[k] = inp[k].copy()
            inp[k][:, :, y] = 0.0
        # The oracle dumps the last of two iterations of each year.
        _cache[y] = benchmarking(inp, y, 2, read_kemfac()), after
    return _cache[y]


def rel_err(mine, eia):
    mine, eia = np.asarray(mine, dtype=np.float64), np.asarray(eia, dtype=np.float64)
    return float((np.abs(mine - eia) / np.maximum(np.abs(eia), 1e-6)).max())


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("name", [
    "cmnonbldguse", "sedsmistie", "steomistie", "cmfinalenduse", "waterserviceselq", "telecomserviceselq",
    "emcm", "emcmc", "qelcm", "qngcm", "qgfcm", "qgicm", "qdscm", "qrscm", "qrlcm", "qlgcm", "qprcm", "qclcm",
    "qmgcm", "qkscm", "qstcm", "qpvcm", "qbmcm", "diffqbm"])
def test_benchmarking(y, name):
    res, after = result(y)
    if name in ("waterserviceselq", "telecomserviceselq"):
        assert rel_err(res[name][1:9, y], after[name][1:9, y]) < TOL
        return
    assert rel_err(res[name].a, after[name].a) < TOL


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
def test_emissions(y):
    res, after = result(y)
    if "cmemissions" not in after:
        pytest.skip("CMEmissions not in this oracle build's dump")
    assert rel_err(res["cmemissions"].a, after["cmemissions"].a) < TOL


def test_emission_factors():
    after = oracle_state.load("bm_out", 61)
    if "emissionfactor" not in after:
        pytest.skip("EmissionFactor not in this oracle build's dump")
    assert rel_err(read_kemfac().a, after["emissionfactor"].a) < 1e-6
