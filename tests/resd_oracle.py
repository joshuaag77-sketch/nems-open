"""Shared check for residential ports: oracle state before a routine in, state after out.

The residential oracle dumps, around each target routine, every shared array the
routine mentions (oracle/hooks.py). A port gets a copy of the "before" state, runs,
and every array must then match the "after" state.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.fortran_array import FArray

# 2020 2021 2022 2025 2026 2027 2030 2040 2050
YEARS = [31, 32, 33, 36, 37, 38, 41, 51, 61]
TOL = 1e-4


def skip_unless_dumped(tag):
    return pytest.mark.skipif(not oracle_state.available(f"{tag}_out", 32, "resd"),
                              reason=f"residential oracle state for {tag} not dumped")


def before_after(tag, y):
    before = oracle_state.load(f"{tag}_in", y, "resd")
    after = oracle_state.load(f"{tag}_out", y, "resd")
    state = {k: (v.copy() if isinstance(v, FArray) else v) for k, v in before.items()}
    return state, after


def rel_err(mine, eia):
    mine, eia = np.asarray(mine, dtype=np.float64), np.asarray(eia, dtype=np.float64)
    return float((np.abs(mine - eia) / np.maximum(np.abs(eia), 1e-6)).max(initial=0.0))


def assert_matches(state, after, tol=TOL, skip=()):
    """Every array the oracle dumped after the routine matches the port's state."""
    worst = {}
    for k, v in after.items():
        if k in skip or not isinstance(v, FArray):
            continue
        worst[k] = rel_err(state[k].a, v.a)
    bad = {k: e for k, e in worst.items() if e >= tol}
    assert not bad, f"over {tol}: {bad}"
    return worst
