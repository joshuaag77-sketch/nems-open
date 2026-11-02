"""EMM historical inputs vs the same quantities in the AEO2026 reference run."""

import numpy as np
import pytest

from nems_open.emm import history
from nems_open.paths import INPUT, REFERENCE_RUN
from nems_open.snapshot import Snapshot

pytestmark = pytest.mark.skipif(
    not ((INPUT / "emm" / "emm_db" / "NEMS_INPUT.db").exists() and REFERENCE_RUN.exists()), reason="EMM inputs missing")

YEARS = slice(2010 - 1990, 2021 - 1990)       # 2010 to 2020; NEMS keeps these emissions only through 2021


@pytest.mark.parametrize("pollutant,name", [("co2", "hemco2r"), ("so2", "hemso2r"), ("nox", "hemnoxr")])
def test_emissions_history_matches_restart(pollutant, name):
    """The US total is exact. Some regions are re-allocated by EIA after the file is read (up to
    up to about 25% in a few regions and years), so regions are held to a looser test."""
    eia = Snapshot()[f"EMISSION/{name}"]
    mine = history.emissions(pollutant)
    assert mine.shape == eia.shape
    rel = np.abs(mine[:, YEARS] - eia[:, YEARS]) / np.maximum(np.abs(eia[:, YEARS]), 1e-3)
    assert rel[27].max() < 1e-5
    assert rel[:25].max() < 0.3
    assert (rel[:25] < 1e-5).mean() > 0.4


@pytest.mark.parametrize("fuel,name", [("cl", "qclel"), ("ng", "qngel")])
def test_fuel_use_history_close_to_restart(fuel, name):
    eia = Snapshot()[f"QBLK/{name}"]
    mine = history.fuel_use_census(fuel)
    years = slice(2009 - 1990, 2025 - 1990)
    ok = ~np.isnan(mine[:9, years])
    err = np.abs(mine[:9, years] - eia[:9, years])[ok] / np.maximum(eia[:9, years][ok], 1.0)
    assert err.max() < 2e-3


@pytest.mark.parametrize("column,name,tol", [
    ("HGENNU", "ugennu", 1e-5), ("HGENIG", "ugenig", 1e-5), ("HGENFC", "ugenfc", 1e-5),
    ("HGENCC", "ugencc", 0.01), ("HGENPC", "ugenpc", 0.01), ("HGENRN", "ugenrn", 0.01),
])
def test_generation_history_national(column, name, tol):
    eia = Snapshot()[f"UDATOUT/{name}"]
    mine = history.generation(column)
    y = 2015 - 1990
    assert abs(np.nansum(mine[:25, y]) - eia[27, y]) <= tol * abs(eia[27, y]) + 0.01


def test_sales_and_price_shapes():
    assert history.sales("as").shape == (28, 61)
    assert history.prices("rs").shape == (28, 61)
    assert np.isfinite(history.sales("as")[:25, 2020 - 1990]).all()
