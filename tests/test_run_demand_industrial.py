"""The industrial slot in the demand runner, and the fallback to stubs.

Industrial's year loop is not ported yet, so its slot supplies the industrial oracle's
fuel use (oracle/run_ind/out/q*in.bin). These tests check that the slot reads those
files right, that the runner's SUMQAS sums for industry (US, California, QTPIN, QTRIN,
QTSIN) reproduce EIA's own rows, and that a ported sector with no state for the start
year falls back to its stub.
"""

import warnings

import numpy as np
import pytest

from nems_open.run_demand import (BASEYR, MNUMCR, SECTOR_QUANTITIES, DemandRunner, IndustrialSector,
                                  eia_quantities, sum_quantities)
from nems_open.snapshot import Snapshot

YEARS = [2025, 2030, 2040, 2050]
TOTALS = ("qtpin", "qtrin", "qtsin")

needs_oracle = pytest.mark.skipif(IndustrialSector.oracle_out() is None, reason="industrial oracle not run")


@pytest.fixture(scope="module")
def eia():
    return eia_quantities(Snapshot())


@pytest.mark.parametrize("year", YEARS)
def test_sums_reproduce_eia(eia, year):
    """SUMQAS's industrial rules on EIA's divisions 1-9 give EIA's US, California and totals."""
    snap = Snapshot()
    q = {k: v.copy() for k, v in eia.items()}
    j = year - BASEYR
    for k in SECTOR_QUANTITIES["in"] + TOTALS:
        q[k][9:, j] = -1.0  # rebuilt below, so a leftover would show
    sum_quantities(q, "in", year - BASEYR + 1, lambda name: snap[f"CALSHR/{name}"])
    for k in SECTOR_QUANTITIES["in"] + TOTALS:
        mine, theirs = q[k][:, j].astype(np.float64), eia[k][:, j].astype(np.float64)
        assert np.allclose(mine, theirs, rtol=2e-6, atol=1e-5), (k, mine[9:], theirs[9:])


@needs_oracle
def test_oracle_files_match_eia_history(eia):
    """The oracle reproduces EIA's industrial history (1990-2022), so the files are read the right way round."""
    rows = IndustrialSector().start(2030)
    for k in SECTOR_QUANTITIES["in"]:
        assert np.allclose(rows[k].a[:9, :33], eia[k][:9, :33], rtol=1e-5, atol=1e-5), k


@needs_oracle
@pytest.mark.parametrize("year", YEARS)
def test_runner_uses_the_slot(eia, year):
    runner = DemandRunner(year, sectors=("industrial",))
    runner.run_year()
    rows = IndustrialSector().start(year)
    j = year - BASEYR
    for k in SECTOR_QUANTITIES["in"]:
        assert np.array_equal(runner.q[k][:9, j], rows[k].a[:9, j]), k
        assert runner.q[k][MNUMCR - 1, j] == pytest.approx(float(rows[k].a[:9, j].sum()), rel=1e-6), k
    for k in ("qelrs", "qelcm", "qeltr"):  # sectors not run keep EIA's rows
        assert np.array_equal(runner.q[k], eia[k]), k
    assert runner.totals(year)["industrial"] == pytest.approx(float(runner.q["qtsin"][MNUMCR - 1, j]))


def test_ported_without_state_falls_back_to_stub():
    """2028 has no oracle dump: asking for ported residential and commercial gives stubs and a warning."""
    from nems_open.demand_adapter import usable_ported
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        got = usable_ported(("residential", "commercial"), 2028)
    assert got == ()
    assert any("no oracle state" in str(w.message) for w in caught)
    assert usable_ported((), 2028) == ()


def test_ported_with_state_is_kept():
    from nems_open.demand_adapter import usable_ported
    from nems_open.run_demand import CommercialSector, ResidentialSector
    if not (ResidentialSector.available(2030) and CommercialSector.available(2030)):
        pytest.skip("oracle state not dumped")
    assert usable_ported(("residential", "commercial"), 2030) == ("residential", "commercial")
