"""The Python EFD stand-in (efp/efd_standin.py) against the block the oracle's
stand-in wrote for every region (fs_out), every dumped year."""

import numpy as np
import pytest

from emm_oracle import YEARS, available
from nems_open import oracle_state
from nems_open.emm.efp import efd_standin
from nems_open.snapshot import Snapshot

UIUF, MVS = 45, 36  # control's uranium fuel index; EFD vertical slices


@pytest.fixture(scope="module")
def snap():
    return Snapshot()


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
def test_standin_block(snap, y):
    if not available("fs_out", y):
        pytest.skip(f"no fs_out dump for {1989 + y}")
    d = oracle_state.load("fs_out", y, "emm")
    for irg in range(1, 26):
        mine = efd_standin.block(snap, y, irg, UIUF, MVS)
        for k, v in mine.items():
            ref = d[f"{k}_r{irg:02d}"]
            ref = ref.a if hasattr(ref, "a") else ref
            assert np.array_equal(np.asarray(v, dtype=np.asarray(ref).dtype), np.asarray(ref)), (y, irg, k)
