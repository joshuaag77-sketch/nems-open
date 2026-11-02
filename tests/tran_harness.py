"""Shared harness for the transportation port tests.

Each test feeds a port the oracle's state just before EIA's routine ran
(<tag>_in) and compares every dumped array with the state just after
(<tag>_out). Arrays the routine does not touch must come through unchanged too.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.fortran_array import FArray

RUN = "run_tran"
YEARS = [31, 36, 41, 51, 61]  # 2020, 2025, 2030, 2040, 2050
TOL = 1e-4


def needs(tag):
    return pytest.mark.skipif(not oracle_state.available(f"{tag}_out", YEARS[0], run=RUN),
                              reason="transportation oracle state not dumped")


def _raw(v):
    return v.a if isinstance(v, FArray) else np.asarray(v)


def rel_err(mine, eia):
    """Largest relative error; NaN in both places counts as a match (0/0 in the Fortran too)."""
    mine, eia = np.asarray(mine, dtype=np.float64), np.asarray(eia, dtype=np.float64)
    if mine.shape != eia.shape:
        return np.inf
    if mine.size == 0:
        return 0.0
    both_nan = np.isnan(mine) & np.isnan(eia)
    if (np.isnan(mine) ^ np.isnan(eia)).any():
        return np.inf
    m, e = np.where(both_nan, 0.0, mine), np.where(both_nan, 0.0, eia)
    scale = np.abs(e[np.isfinite(e)]).max(initial=0.0)
    with np.errstate(invalid="ignore"):
        d = np.where(m == e, 0.0, np.abs(m - e))
    return float((d / np.maximum(np.abs(e), max(1e-6, 1e-7 * scale))).max())


def run(port, tag, y, tol=TOL, **kwargs):
    """Run a port on <tag>_in for year y; return {name: error} for every array it got wrong."""
    before = oracle_state.load(f"{tag}_in", y, run=RUN)
    after = oracle_state.load(f"{tag}_out", y, run=RUN)
    state = {k: (v.copy() if isinstance(v, FArray) else v) for k, v in before.items()}
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        port(state, **kwargs)
    changed = [k for k in after if rel_err(_raw(before[k]), _raw(after[k])) > 0]
    assert changed, f"{tag}: nothing changed between _in and _out, so the test proves nothing"
    bad = {}
    for k, v in after.items():
        e = rel_err(_raw(state[k]), _raw(v)) if k in state else np.inf
        if e > tol:
            bad[k] = e
    return bad
