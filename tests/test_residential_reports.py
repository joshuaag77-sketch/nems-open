"""NHTSHR and RESDRP2 ports vs the residential oracle's state (final year only)."""

import numpy as np
import pytest

from resd_oracle import YEARS, assert_matches, before_after
from nems_open import oracle_state
from nems_open.residential.reports import nhtshr, resdrp2

Y2050 = YEARS[-1]  # NEMS index 61

needs_nt = pytest.mark.skipif(not oracle_state.available("nt_out", Y2050, "resd"),
                              reason="residential oracle state for nt not dumped")
needs_r2 = pytest.mark.skipif(not oracle_state.available("r2_out", Y2050, "resd"),
                              reason="residential oracle state for r2 not dumped")


@needs_nt
def test_nhtshr():
    state, after = before_after("nt", Y2050)
    nhtshr(state)
    assert_matches(state, after, tol=1e-6)
    # EIA only prints the shares; check they are shares
    sh = state["nweqhtsh"][2021:2050, 1:10]
    assert np.all(sh >= 0.0) and np.allclose(sh.sum(axis=1), 1.0, atol=1e-3)


@needs_r2
def test_resdrp2():
    state, after = before_after("r2", Y2050)
    resdrp2(state)
    worst = assert_matches(state, after, tol=1e-6)
    print({k: f"{v:.1e}" for k, v in worst.items() if v > 0})
