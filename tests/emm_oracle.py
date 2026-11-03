"""Shared check for EMM ports: oracle state before a routine in, state after out.

Like tests/resd_oracle.py, for the EMM oracle (oracle/hooks.py EMM_TARGETS). LDSM
routines run once per EMM region; their dumps hold each array as "<name>_rNN" for
the regions in EMM_DUMP_REGIONS, in EMM_REGION_YEARS. `before_after(tag, y, r)`
gives region r's state under the plain names.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.fortran_array import FArray

YEARS = [31, 32, 33, 36, 37, 38, 41, 51, 61]  # 2020 2021 2022 2025 2026 2027 2030 2040 2050
REGIONS = [1, 13]
REGION_YEARS = [32, 41, 61]                   # 2021 2030 2050
TOL = 1e-4


def available(tag, y):
    return oracle_state.available(tag, y, "emm")


def skip_unless_dumped(tag, y=32):
    return pytest.mark.skipif(not available(f"{tag}_out", y), reason=f"EMM oracle state for {tag} not dumped")


def _region(d, r):
    if r is None:
        return d
    suf = f"_r{r:02d}"
    return {k[: -len(suf)]: v for k, v in d.items() if k.endswith(suf)}


def before_after(tag, y, region=None):
    """Skips the test if that year, or that region within it, was not dumped (the
    oracle keeps some dumps to fewer years and regions to save disk)."""
    if not (available(f"{tag}_in", y) and available(f"{tag}_out", y)):
        pytest.skip(f"no {tag} dump for {1989 + y}")
    before = _region(oracle_state.load(f"{tag}_in", y, "emm"), region)
    if region is not None and not before:
        pytest.skip(f"no {tag} dump for region {region} in {1989 + y}")
    after = _region(oracle_state.load(f"{tag}_out", y, "emm"), region)
    state = {k: (v.copy() if isinstance(v, FArray) else v) for k, v in before.items()}
    return state, after


def rel_err(mine, ref):
    """Worst relative error. NaN where the oracle has NaN counts as a match; NaN
    on one side only is an infinite error (a plain max would skip it)."""
    mine, ref = np.asarray(mine, dtype=np.float64), np.asarray(ref, dtype=np.float64)
    both = (np.isnan(mine) & np.isnan(ref)) | (mine == ref)  # equal infinities match too
    with np.errstate(invalid="ignore"):
        err = np.abs(mine - ref) / np.maximum(np.abs(ref), 1e-6)
    err = np.where(both, 0.0, np.where(np.isnan(err), np.inf, err))
    return float(err.max(initial=0.0))


def assert_matches(state, after, tol=TOL, skip=()):
    """Every array and scalar the oracle dumped after the routine matches the port's state."""
    worst = {}
    for k, v in after.items():
        if k in skip:
            continue
        if isinstance(v, FArray):
            if v.a.dtype.kind == "S":
                worst[k] = 0.0 if np.array_equal(state[k].a, v.a) else 1.0
            else:
                worst[k] = rel_err(state[k].a, v.a)
        else:
            worst[k] = rel_err(state[k], v)
    bad = {k: e for k, e in worst.items() if e >= tol}
    assert not bad, f"over {tol}: {bad}"
    return worst
