"""Electricity demand on the EMM regions."""

import numpy as np
import pytest

from nems_open.emm import demand
from nems_open.paths import INPUT, REFERENCE_RUN
from nems_open.snapshot import Snapshot

pytestmark = pytest.mark.skipif(
    not ((INPUT / "emm" / "emm_db" / "NEMS_INPUT.db").exists() and REFERENCE_RUN.exists()), reason="EMM inputs missing")

YEARS = (2025, 2030, 2040, 2050)


@pytest.fixture(scope="module")
def snapshot():
    return Snapshot()


@pytest.mark.parametrize("year", YEARS)
def test_census_sales_add_up_to_the_us(snapshot, year):
    """California (slot 10) is part of the Pacific division, so the nine divisions already add up to the US.
    Adding it again overstated the Pacific by 56% and left three western regions short of power."""
    mine = demand.census_sales_twh(snapshot, year).sum(axis=0)
    for s, key in enumerate(demand.SALES_KEYS):
        us = snapshot[key][10, year - 1990] / demand.TBTU_PER_TWH
        assert abs(mine[s] / us - 1) < 1e-4


@pytest.mark.parametrize("year", YEARS)
def test_net_load_matches_reference_generation(snapshot, year):
    """National net load within 1% of EIA's generation in 2025 and within 4% by 2050 (the rest is storage
    losses, which the LP models itself)."""
    nl = demand.net_load_twh(snapshot, year).sum()
    ref = float(snapshot["UEFDOUT/ugntlnr"][:, :25, year - 1990].sum())
    assert abs(nl / ref - 1) < 0.04


def test_regional_load_is_not_wildly_off(snapshot):
    nl = demand.net_load_twh(snapshot, 2030)
    ref = snapshot["UEFDOUT/ugntlnr"][:, :25, 2030 - 1990].sum(axis=0)
    assert np.median(np.abs(nl / ref - 1)) < 0.15
    assert (nl[20:23] / ref[20:23]).max() < 1.25            # the western regions that used to run short
