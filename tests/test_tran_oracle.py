"""The transportation oracle vs EIA's reference run. Skipped until it has run.

Build and run it first (SCOPE.md, transportation section). Regions 1-9 only:
California (10) and the US total (11) of QBLK are filled outside TRAN.

Through 2025 the main fuels match to float rounding. After that the oracle drifts:
NEMS calls TRAN with each iteration's unconverged prices and several routines do
work only on the first iteration (CURITR == 1), which a standalone run cannot see.
Gasoline, diesel, jet fuel, electricity and residual stay within 1%; truck natural
gas, ethanol and hydrogen move more and are only checked through 2025.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.snapshot import Snapshot

pytestmark = pytest.mark.skipif(not oracle_state.available("final", 0, run="run_tran"),
                                reason="transportation oracle not run")

HISTORY = slice(5, 36)      # 1995-2025
PROJECTION = slice(36, 61)  # 2026-2050


def rel_err(name, years):
    eia = Snapshot()[f"QBLK/{name}"][:9, years].astype(np.float64)
    mine = oracle_state.load("final", 0, run="run_tran")[name].a[:9, years].astype(np.float64)
    scale = np.abs(eia).max() or 1.0
    return float((np.abs(mine - eia) / np.maximum(np.abs(eia), 1e-6 * scale)).max())


@pytest.mark.parametrize("name,tol", [
    ("qmgtr", 1e-5), ("qdstr", 1e-5), ("qjftr", 1e-5), ("qeltr", 1e-5), ("qottr", 1e-5),
    ("qrstr", 1e-4), ("qngtr", 1e-2), ("qlgtr", 1e-2), ("qettr", 1e-2), ("qh2tr", 1e-3),
])
def test_history(name, tol):
    assert rel_err(name, HISTORY) < tol


@pytest.mark.parametrize("name", ["qmgtr", "qdstr", "qjftr", "qeltr", "qottr", "qrstr"])
def test_projection(name):
    assert rel_err(name, PROJECTION) < 1e-2
