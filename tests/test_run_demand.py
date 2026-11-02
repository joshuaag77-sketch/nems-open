"""The demand runner (src/nems_open/run_demand.py) against EIA's AEO2026 run.

For 2025, 2030, 2040 and 2050 the runner starts each ported module from the
oracle's state for that year, feeds it EIA's prices and macro drivers from the
restart file, and runs it. Its QBLK fuel use must match:
- the oracle (EIA's Fortran compiled with gfortran) to float rounding, regions 1-9;
- EIA's restart file within the oracle's own gfortran vs Intel drift (SCOPE.md), in
  every region including California and the US total: electricity and natural gas
  cell by cell within 0.3%; every fuel row within 0.2% of the sector's total use in
  that region (small rows such as solar thermal, residual oil and commercial
  kerosene drift by several percent of themselves in the oracle too); and each
  sector's US total delivered energy (QTS) within 0.1%.

It also starts at 2025 and keeps going into 2026 (NEMS's two iterations, every
module's state carried), which must match the oracle's 2026 to float rounding.

The runs go in parallel processes; commercial takes about 5 minutes per iteration
of a year, so the whole file takes about 10 minutes.
"""

from concurrent.futures import ProcessPoolExecutor

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.run_demand import (BASEYR, EQUIVALENCED, SECTOR_QUANTITIES, DemandRunner, Inputs, eia_quantities,
                                  run_year)
from nems_open.snapshot import Snapshot

YEARS = [2025, 2030, 2040, 2050]
SECTORS = {"commercial": ("cm", "bm_out", "comm"), "residential": ("rs", "ne_out", "resd")}
MAJOR_TOL = 3e-3  # electricity and natural gas, each cell
ROW_TOL = 2e-3    # any row, as a share of the sector's total in that region
TOTAL_TOL = 1e-3

pytestmark = pytest.mark.skipif(
    not (oracle_state.available("sd_in", 36) and oracle_state.available("yb_in", 36, "resd")),
    reason="oracle state not dumped")


def two_years(year):
    runner = DemandRunner(year)
    runner.run_year()
    runner.run_year()
    return runner.q


@pytest.fixture(scope="module")
def all_runs():
    with ProcessPoolExecutor(max_workers=len(YEARS) + 1) as pool:
        chained = pool.submit(two_years, 2025)
        return dict(zip(YEARS, pool.map(run_year, YEARS))), chained.result()


@pytest.fixture(scope="module")
def runs(all_runs):
    return all_runs[0]


@pytest.fixture(scope="module")
def eia():
    return eia_quantities(Snapshot())


@pytest.mark.parametrize("year", YEARS)
@pytest.mark.parametrize("sector", SECTORS)
def test_matches_oracle(runs, year, sector):
    suffix, tag, module = SECTORS[sector]
    y = year - BASEYR + 1
    ref = oracle_state.load(tag, y, module)
    for k in SECTOR_QUANTITIES[suffix]:
        if k not in ref:
            continue
        mine, theirs = runs[year][k][:9, y - 1].astype(np.float64), ref[k][1:9, y].astype(np.float64)
        err = np.abs(mine - theirs) / np.maximum(np.abs(theirs), 1e-6)
        assert err.max() < 1e-5, (k, err.max())


@pytest.mark.parametrize("year", YEARS)
@pytest.mark.parametrize("sector", SECTORS)
def test_matches_eia(runs, eia, year, sector):
    suffix = SECTORS[sector][0]
    j = year - BASEYR
    total = eia[f"qts{suffix}"][:, j].astype(np.float64)
    for k in SECTOR_QUANTITIES[suffix]:
        mine, theirs = runs[year][k][:, j].astype(np.float64), eia[k][:, j].astype(np.float64)
        diff = np.abs(mine - theirs)
        assert (diff / np.maximum(total, 1e-6)).max() < ROW_TOL, k
        if k in (f"qel{suffix}", f"qng{suffix}"):
            assert (diff / np.maximum(np.abs(theirs), 1e-6)).max() < MAJOR_TOL, k


@pytest.mark.parametrize("year", YEARS)
@pytest.mark.parametrize("sector", SECTORS)
def test_sector_total(runs, eia, year, sector):
    """QTSxx: the sector's total delivered energy, US."""
    k = f"qts{SECTORS[sector][0]}"
    mine, theirs = runs[year][k][10, year - BASEYR], eia[k][10, year - BASEYR]
    assert abs(mine - theirs) / theirs < TOTAL_TOL


@pytest.mark.parametrize("sector", SECTORS)
def test_next_year_matches_oracle(all_runs, sector):
    """2026 reached from 2025: iteration 1 rolls last year's results forward."""
    suffix, tag, module = SECTORS[sector]
    q, y = all_runs[1], 2026 - BASEYR + 1
    ref = oracle_state.load(tag, y, module)
    for k in SECTOR_QUANTITIES[suffix]:
        if k in ref:
            mine, theirs = q[k][:9, y - 1].astype(np.float64), ref[k][1:9, y].astype(np.float64)
            assert (np.abs(mine - theirs) / np.maximum(np.abs(theirs), 1e-6)).max() < 1e-5, k


def test_report(runs, eia):
    """Prints the runner's error against EIA by sector and year (pytest -s)."""
    print("\nsector       year  US total vs EIA  worst electricity/gas cell")
    for sector, (suffix, _, _) in SECTORS.items():
        for year in YEARS:
            j = year - BASEYR
            k = f"qts{suffix}"
            total = abs(runs[year][k][10, j] - eia[k][10, j]) / eia[k][10, j]
            major = max((np.abs(runs[year][q][:, j] - eia[q][:, j]) / np.maximum(np.abs(eia[q][:, j]), 1e-6)).max()
                        for q in (f"qel{suffix}", f"qng{suffix}"))
            print(f"{sector:12} {year}  {total:15.2e}  {major:10.2e}")


def test_unported_sectors_keep_eia(runs, eia):
    for k in ("qelin", "qngin", "qeltr", "qmgtr"):
        assert np.array_equal(runs[2030][k], eia[k])


def test_inputs_are_what_the_oracle_ran_on():
    """Applying EIA's inputs to the oracle's state changes nothing: the runner really is fed
    by the restart file, and an override is the only way an input changes."""
    from nems_open.residential import resd
    s = resd.start_from_dump(41)
    before = {k: v.a.copy() for k, v in s.items() if hasattr(v, "a")}
    inputs = Inputs()
    inputs.apply(s)
    touched = [k for k in before if k in inputs.by_var or k in EQUIVALENCED]
    assert len(touched) > 20
    for k in touched:
        assert np.array_equal(before[k], s[k].a, equal_nan=True), k


def test_demand_responds_to_price():
    """A 50% higher residential natural gas price in 2030 cuts residential gas use."""
    snap = Snapshot()
    base = DemandRunner(2030, sectors=("residential",))
    base.run_year()
    high = DemandRunner(2030, Inputs(snap, {"AMPBLK/pngrs": 1.5 * snap["AMPBLK/pngrs"]}), sectors=("residential",))
    high.run_year()
    assert high.q["qngrs"][10, 40] < 0.98 * base.q["qngrs"][10, 40]
    assert base.totals(2030)["residential"] == pytest.approx(float(base.q["qtsrs"][10, 40]))
