"""The demand runner with transportation (run_demand.TransportationSector).

Starting from the oracle's state for 2025, the runner runs TRAN's iterations on EIA's
prices from the restart file. Its QBLK rows must match the oracle's TRAN output for that
year (regions 1-9; the oracle dumps the first iteration, and on fixed prices later
iterations change nothing these rows depend on), and EIA's restart file within the
oracle's gfortran vs Intel drift (SCOPE.md: exact to float rounding through 2025).
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.run_demand import BASEYR, SECTOR_QUANTITIES, DemandRunner, Inputs, apply_transportation, eia_quantities
from nems_open.snapshot import Snapshot

YEAR = 2025
pytestmark = pytest.mark.skipif(not oracle_state.available("tran_tail_out", YEAR - BASEYR + 1, run="run_tran"),
                                reason="transportation oracle state not dumped")


@pytest.fixture(scope="module")
def runner():
    r = DemandRunner(YEAR, sectors=("transportation",))
    r.run_year()
    return r


def test_inputs_are_what_the_oracle_ran_on():
    from nems_open.fortran_array import FArray
    from nems_open.transportation import tran
    s, _ = tran.start_from_dump(YEAR - BASEYR + 1)
    before = {k: v.a.copy() for k, v in s.items() if isinstance(v, FArray)}
    inputs = Inputs()
    apply_transportation(inputs, s)
    touched = [k for k in before if k in inputs.by_var or k.removeprefix("aeusprc__") in inputs.by_var]
    assert len(touched) > 20
    same = lambda a, b: np.array_equal(a, b, equal_nan=a.dtype.kind == "f")  # noqa: E731
    changed = [k for k in touched if not same(before[k], s[k].a)]
    assert changed == []


def test_matches_oracle(runner):
    y = YEAR - BASEYR + 1
    ref = {}
    for tag in ("tinteg_out", "tbenchmark_out", "tran_tail_out"):  # later dumps win
        ref.update(oracle_state.load(tag, y, run="run_tran"))
    for k in SECTOR_QUANTITIES["tr"]:
        # Natural gas changes between iterations (CURITR == 1 logic), so the first-iteration
        # dump is not the end of the year for it; it is checked against EIA below.
        if k in ref and k not in ("qrstr", "qngtr", "qgftr"):
            mine, theirs = runner.q[k][:9, y - 1].astype(np.float64), ref[k][1:9, y].astype(np.float64)
            err = np.abs(mine - theirs) / np.maximum(np.abs(theirs), 1e-6 * max(1.0, np.abs(theirs).max()))
            assert err.max() < 1e-4, (k, err.max())


@pytest.mark.parametrize("k", ["qmgtr", "qdstr", "qjftr", "qeltr", "qtstr", "qngtr"])
def test_matches_eia(runner, k):
    eia = eia_quantities(Snapshot())
    j = YEAR - BASEYR
    mine, theirs = runner.q[k][:, j].astype(np.float64), eia[k][:, j].astype(np.float64)
    tol = 3e-3 if k == "qngtr" else 1e-4  # gas: within the oracle's 0.3% gfortran vs Intel drift
    assert (np.abs(mine - theirs) / np.maximum(np.abs(theirs), 1e-6)).max() < tol, k
