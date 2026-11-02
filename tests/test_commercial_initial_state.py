"""COMM's starting state built from files, against the oracle.

1. Each array built from an input file equals what EIA's first call leaves (fsd_out / ftc_out and
   the routine dumps), except three explained below.
2. A year run from that state alone gives the fuel use of a run started from the oracle's dumps.
"""

import numpy as np
import pytest
from nems_open import oracle_state
from nems_open.commercial import initial_state as ini
from nems_open.commercial.comm import Commercial
from nems_open.run_demand import Inputs

pytestmark = pytest.mark.skipif(not oracle_state.available("fsd_out", 30), reason="first-call oracle state not dumped")

DUMPS = ("fsd_out", "ftc_out", "ftc_in", "sd_in", "sd_out", "tc_out", "cn_out", "bm_out", "frd_out", "tc_pre", "bm_pre")

# Arrays the first call's own routine changes right after reading them: the service demand total
# column of ComEUI, the minor-fuel betas COMConsumption zeroes, and three backcast cells of new floorspace
# that differ in the last float32 bit (3 of 27467, 6e-4 square feet).
EXPLAINED = {"comeui", "minfuelbeta", "cmnewfloorspace"}


@pytest.fixture(scope="module")
def inputs():
    return Inputs()


@pytest.fixture(scope="module")
def state(inputs):
    return ini.initial_state(inputs)


@pytest.fixture(scope="module")
def eia():
    return {t: oracle_state.load(t, 30) for t in DUMPS}


def same(x, y):
    x = x.a if hasattr(x, "a") else np.asarray(x)
    y = y.a if hasattr(y, "a") else np.asarray(y)
    if x.dtype.kind in "SU" or y.dtype.kind in "SU":
        return bool((np.char.rstrip(x.astype(str)) == np.char.rstrip(y.astype(str))).all())
    return x.shape == y.shape and bool(np.allclose(x.astype(float), y.astype(float), rtol=1e-5, atol=1e-9, equal_nan=True))


FILES = sorted(set(ini.coverage()["files"]) - EXPLAINED) if oracle_state.available("fsd_out", 30) else []


@pytest.mark.parametrize("name", FILES)
def test_array_from_files(state, eia, name):
    matches = [t for t in DUMPS if name in eia[t] and same(state[name], eia[t][name])]
    assert matches, f"{name} matches no first-call dump"


def test_coverage_accounts_for_every_array():
    cov = ini.coverage()
    assert sum(len(v) for v in cov.values()) == len(ini.LAYOUT)


YEARS = [30, 31, 32, 36, 37, 38, 41, 51, 61]


@pytest.fixture(scope="module")
def run_from_files(inputs):
    """2019 to 2050 from files alone, keeping the state at the end of each test year."""
    flsp = inputs.array("MACOUT/mc_commflsp")
    c = Commercial.start_from_files(inputs)
    kept = {}
    for y in range(30, 62):
        for itr in (1, 2):
            inputs.apply(c.s)
            c.iteration(y, itr, flsp)
        if y in YEARS:
            kept[y] = {k: c.s[k].copy() for k in ("enduseconsump", "finalendusecon", "cmfinalenduse", "qelcm", "qngcm",
                                                  "qdscm", "qkscm", "qlgcm", "qmgcm", "qclcm", "qrscm")}
    return kept


def _slice_year(a, y):
    ax = [i for i in range(a.a.ndim) if a.a.shape[i] in (61, 62, 33)][-1]
    idx = [slice(None)] * a.a.ndim
    idx[ax] = y - a.lb[ax]
    return a.a[tuple(idx)].astype(np.float64)


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("name", ["enduseconsump", "finalendusecon", "cmfinalenduse"])
def test_year_from_files_matches_oracle(run_from_files, name, y):
    """The end-use arrays, which benchmarking does not touch, equal the oracle's after the last iteration."""
    after = {**oracle_state.load("sd_out", y), **oracle_state.load("cn_out", y), **oracle_state.load("bm_out", y)}
    mine, eia = _slice_year(run_from_files[y][name], y), _slice_year(after[name], y)
    if name == "cmfinalenduse":                 # the three major fuels, divisions 1 to 9
        mine, eia = mine[:3, :9], eia[:3, :9]
    assert (np.abs(mine - eia) / np.maximum(np.abs(eia), 1e-3)).max() < 1e-4


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("name", ["qelcm", "qngcm", "qdscm", "qkscm", "qlgcm", "qmgcm", "qclcm", "qrscm"])
def test_fuel_use_from_files_matches_oracle(run_from_files, name, y):
    eia = oracle_state.load("bm_out", y)[name].a[:9, y - 1].astype(np.float64)
    mine = run_from_files[y][name].a[:9, y - 1].astype(np.float64)
    assert np.abs(mine - eia).max() <= 1e-4 * max(np.abs(eia).max(), 1.0)


def test_2019_fuel_use_from_files_equals_dump_start(inputs):
    flsp = inputs.array("MACOUT/mc_commflsp")
    runs = []
    for make in (lambda: Commercial.start_from_dump(30), lambda: Commercial.start_from_files(inputs)):
        c = make()
        for itr in (1, 2):
            inputs.apply(c.s)
            c.iteration(30, itr, flsp)
        runs.append(c.qblk())
    for name in runs[0]:
        a, b = (np.asarray(r[name].a if hasattr(r[name], "a") else r[name], dtype=np.float64)[:9, 29] for r in runs)
        assert np.abs(a - b).max() <= 1e-5 * max(np.abs(a).max(), 1.0), name
