"""TRAN from EIA's files alone: no oracle dump in the start.

initial_state() builds the state before TRAN's first call (restart file, DATA values,
the first-call readers); TRAN then runs 1995 on, three calls a year, as NEMS calls it.
At the top of 2020 every array must match the oracle's state there (bit for bit, in
practice); with NEMS_SLOW=1 also at the top of 2025, after the GHG and CAFE years.
"""

import os

import numpy as np
import pytest

from nems_open.fortran_array import FArray
from nems_open.transportation import initial_state, tran
from tran_harness import needs

pytestmark = needs("tran_tail")
YEAR = 2020


def _err(a, b) -> float:
    a, b = np.asarray(a), np.asarray(b)
    if b.dtype.kind in "SUO":
        return 0.0 if np.array_equal(a, b) else np.inf
    a, b = a.astype(np.float64), b.astype(np.float64)
    same = (a == b) | (np.isnan(a) & np.isnan(b))       # equal infinities count as equal
    if same.all():
        return 0.0
    if (np.isnan(a) ^ np.isnan(b)).any() or (np.isinf(a) ^ np.isinf(b)).any():
        return np.inf
    fin = np.isfinite(b)
    scale = np.abs(b[fin]).max(initial=0.0)
    d = np.where(same, 0.0, np.abs(a - b) / np.maximum(np.abs(b), 1e-3 * scale))
    return float(d.max(initial=0.0))


@pytest.fixture(scope="module")
def runs():
    with np.errstate(all="ignore"):
        s, _ = initial_state.run(YEAR)
    ref, _ = tran.start_from_dump(YEAR - 1989)
    return s, ref


def test_every_array_matches_the_oracle(runs):
    _check(*runs)


@pytest.mark.skipif(os.environ.get("NEMS_SLOW") != "1", reason="set NEMS_SLOW=1 to run TRAN to 2025 (about 10 min)")
def test_every_array_matches_the_oracle_in_2025():
    with np.errstate(all="ignore"):
        s, _ = initial_state.run(2025)
    _check(s, tran.start_from_dump(2025 - 1989)[0])


def _check(s, ref):
    bad = {}
    n = 0
    for k, e in ref.items():
        if not isinstance(e, FArray) or k.startswith(("p_", "p0_")) or k not in s:
            continue
        n += 1
        err = _err(s[k].a, e.a)
        if err > 1e-4:
            bad[k] = err
    assert n > 1000
    assert bad == {}
