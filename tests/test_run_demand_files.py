"""The demand runner starts commercial from the input files and reproduces the oracle's year."""

import numpy as np
import pytest
from nems_open import oracle_state
from nems_open.run_demand import BASEYR, SECTOR_QUANTITIES, DemandRunner

pytestmark = pytest.mark.skipif(not oracle_state.available("bm_out", 36), reason="oracle state not dumped")

YEAR = 2025


@pytest.fixture(scope="module")
def runner():
    r = DemandRunner(YEAR, sectors=("commercial",), commercial_from_files=True)
    r.run_year()
    return r


@pytest.mark.parametrize("name", SECTOR_QUANTITIES["cm"])
def test_commercial_from_files_matches_oracle(runner, name):
    y = YEAR - BASEYR + 1
    ref = oracle_state.load("bm_out", y)
    if name not in ref:
        pytest.skip(f"{name} not in the oracle dump")
    mine, theirs = runner.q[name][:9, y - 1].astype(np.float64), ref[name][1:9, y].astype(np.float64)
    assert np.abs(mine - theirs).max() <= 1e-4 * max(np.abs(theirs).max(), 1.0), name


def test_a_lever_reaches_the_runner():
    """Benchmarking holds fuel use to SEDS and STEO through 2026, so a lever shows from 2027."""
    from nems_open.commercial.levers import CommercialLevers
    year, j = 2028, 2028 - BASEYR
    base = DemandRunner(year, sectors=("commercial",), commercial_from_files=True)
    base.run_year()
    cut = DemandRunner(year, sectors=("commercial",),
                       commercial_levers=CommercialLevers(shell_improvement=0.5, shell_start_year=2020))
    cut.run_year()
    assert cut.q["qngcm"][:9, j].sum() < base.q["qngcm"][:9, j].sum()
