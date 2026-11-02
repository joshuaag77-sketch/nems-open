"""RDISTGEN port vs the residential oracle's state (tag "dg", the yearly call).

Inputs are the "dg_in" dump plus "dg_pre", the ZIP model's carried locals as the
final iteration starts. The oracle's "in" state is the second NEMS iteration, which
already holds this year's answers; to prove the port recomputes them, the test poisons
the outputs that EIA assigns (not accumulates) before running.
"""

import numpy as np
import pytest

from resd_oracle import YEARS, assert_matches, before_after, skip_unless_dumped
from nems_open import oracle_state
from nems_open.residential.distgen import rdistgen

LATER = [y for y in YEARS if y > 31]  # the yearly call starts the year after RECS


def _poison(state, y):
    """NaN into this year's outputs that RDISTGEN assigns rather than adds to."""
    for nm in ("units", "cap", "trills", "gasusage", "hwbtu", "invest", "x111drensub"):
        state[nm][y, 1:9, 1:3] = np.nan
    state["trillsownuse"][y, 1:9, 1:3] = np.nan
    for nm in ("cgresgen", "cgresq", "cgrescap"):
        a = state[nm].a
        a[0:9, y - 1, ...] = np.nan  # divisions 1-9 of this year (zero-based year axis)
    for nm in ("rfuelcell_mw", "rpv_mw", "rwind_mw", "rmicrotur_mw"):
        state[nm][y] = np.nan


@skip_unless_dumped("dg")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rdistgen(y):
    state, after = before_after("dg", y)
    state.update(oracle_state.load("dg_pre", y, "resd"))
    _poison(state, y)
    rdistgen(state)
    worst = assert_matches(state, after, tol=1e-6)
    # the poison must all be gone
    for k in ("units", "cap", "trills", "invest"):
        assert not np.isnan(state[k].a).any(), k
    assert worst  # at least one array compared
