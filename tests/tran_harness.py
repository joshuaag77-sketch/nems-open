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
    have = any(oracle_state.available(f"{tag}_{side}", YEARS[0], run=RUN) for side in ("out", "in"))
    return pytest.mark.skipif(not have,
                              reason="transportation oracle state not dumped")


def _raw(v):
    return v.a if isinstance(v, FArray) else np.asarray(v)


def rel_err(mine, eia):
    """Largest relative error; NaN in both places counts as a match (0/0 in the Fortran too)."""
    if np.asarray(eia).dtype.kind in "SU":
        return 0.0 if np.array_equal(np.asarray(mine), np.asarray(eia)) else np.inf
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
    # Near-zero entries are judged against the array's scale: absolute error up to 1e-7 of
    # the largest value is float32 rounding (exp and pow differ by an ulp between libraries).
    return float((d / np.maximum(np.abs(e), max(1e-6, 1e-3 * scale))).max())


def _blank_from(a: FArray, y: int) -> FArray:
    """Copy with year y and later zeroed, on the array's year axis (bounds 1..61)."""
    a = a.copy()
    axis = max(i for i, (lo, n) in enumerate(zip(a.lb, a.a.shape)) if lo == 1 and n == 61)
    idx = [slice(None)] * a.a.ndim
    idx[axis] = slice(y - 1, None)
    a.a[tuple(idx)] = 0
    return a


def run(port, tag, y, tol=TOL, carry=None, start=None, end=None, may_be_empty=False, skip=(), **kwargs):
    """Run a port on <tag>_in for year y; return {name: error} for every array it got wrong.

    carry: the routine's saved local arrays (dumped as p_<name> in <tag>_out). The port
    gets them with this year and later blanked, as `carry`, and must fill them in.
    skip: dumped names not to compare (dumped somewhere other than the end point's moment).
    start, end: other dump folders to run between, e.g. "tmpg_lion_out" to "tmpg_fem1_in"
    for a stretch of TMPGNEW."""
    before = oracle_state.load(start or f"{tag}_in", y, run=RUN)
    after = oracle_state.load(end or f"{tag}_out", y, run=RUN)
    state = {k: (v.copy() if isinstance(v, FArray) else v) for k, v in before.items()}
    if carry is not None:
        # A dict is the carry itself (saved arrays dumped somewhere other than the end point).
        kwargs["carry"] = carry if isinstance(carry, dict) else {k: _blank_from(after[f"p_{k}"], y) for k in carry}
        before = dict(before, **{f"p_{k}": v for k, v in kwargs["carry"].items()})
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        port(state, **kwargs)
    if carry is not None:
        state.update({f"p_{k}": v for k, v in kwargs["carry"].items()})
    # Saved locals dumped at the end point that this stretch was not given are not its output.
    after = {k: v for k, v in after.items() if k in before or not k.startswith(("p_", "p0_"))}
    changed = [k for k in after if k in before and rel_err(_raw(before[k]), _raw(after[k])) > 0]
    assert changed or may_be_empty, f"{tag}: nothing changed between _in and _out, so the test proves nothing"
    bad = {}
    for k, v in after.items():
        if k in skip:
            continue
        e = rel_err(_raw(state[k]), _raw(v)) if k in state else np.inf
        if e > tol:
            bad[k] = e
    return bad
