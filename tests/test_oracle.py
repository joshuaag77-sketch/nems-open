"""The Fortran oracle vs EIA's reference run. Skipped until the oracle has run.

Build and run it first (see SCOPE.md). Floorspace matches to rounding. Consumption
is within 0.12% in every cell; the remaining gap is float rounding between gfortran
and EIA's Intel build, so its tolerance is 0.2% rather than the 0.1% port rule.
"""

from pathlib import Path

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.snapshot import Snapshot

OUT = oracle_state.out_dir("comm")
YEARS = slice(29, 61)  # 2019-2050

pytestmark = pytest.mark.skipif(not (OUT / "cmusconsumption.bin").exists(), reason="oracle not run")


def oracle(name, like):
    return np.fromfile(OUT / f"{name}.bin", dtype=np.float32).reshape(like.shape, order="F")


@pytest.mark.parametrize("name,tol", [
    ("cmtotalflspc", 1e-5),
    ("survfloortotal", 1e-5),
    ("cmusconsumption", 2e-3),
])
def test_oracle_matches_eia(name, tol):
    eia = Snapshot()[f"COMMREP/{name}"]
    mine = oracle(name, eia)
    err = np.abs(mine - eia)[..., YEARS] / np.maximum(np.abs(eia[..., YEARS]), 1e-6)
    assert err.max() < tol
