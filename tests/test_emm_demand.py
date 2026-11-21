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


FLEET_GEN = ("ugnclnr", "ugngfnr", "ugnginr", "ugngcnr", "ugndsnr", "ugnrlnr", "ugnrhnr", "ugnurnr", "ugnhonr",
             "ugnpsnr", "ugnsdnr", "ugndgnr", "ugnddnr")


def fleet_generation(snapshot, year, axis=None):
    """EIA's generation by the fleet the dispatch runs (ownership classes 1 to 3, storage net), 25 regions, TWh."""
    y = year - 1990
    return sum(snapshot[f"UEFDOUT/{k}"][:, :25, y].sum(axis=0) for k in FLEET_GEN).sum(axis=axis)


@pytest.mark.parametrize("year", YEARS)
def test_net_load_matches_fleet_generation(snapshot, year):
    """Net load is within 0.5% of what EIA's fleet generates (its storage losses included, which the LP adds itself).
    The old load (sales / (1 - loss), less end-use own use, nontraditional cogeneration not taken off, Alaska and
    Hawaii in) was 2-3% above it, 110-125 TWh, and the LP ran gas and coal for it."""
    nl = demand.net_load_twh(snapshot, year).sum()
    assert abs(nl / fleet_generation(snapshot, year) - 1) < 0.005


def test_total_generation_holds_distributed_pv(snapshot):
    """UGNTLNR is not the fleet's total: in every region it exceeds the sum of its own components (util.f 3779) by
    about the end-use solar output (COGEN/cgtotgennr's solar column, 80-90% of it), which is behind the meter and
    not load the fleet serves."""
    for year in (2030, 2040):
        y = year - 1990
        parts = sum(snapshot[f"UEFDOUT/{k}"][:, :25, y].sum(axis=0) for k in FLEET_GEN if k != "ugnsdnr")
        gap = snapshot["UEFDOUT/ugntlnr"][:, :25, y].sum(axis=0) - parts
        pv = snapshot["COGEN/cgtotgennr"][:25, y, demand.PV_COLUMN].sum(axis=1) / 1000.0
        assert np.corrcoef(gap, pv)[0, 1] > 0.98
        assert 0.75 < gap.sum() / pv.sum() < 0.95


def test_sales_follow_ldsm_mapping(snapshot):
    """Census sales go to EMM regions on MappCtoN shares (DSMEMMV): within 0.5% of EIA's QELASN in every region in
    2025, Alaska and Hawaii left out."""
    mine = demand.regional_sales_twh(snapshot, 2025).sum(axis=1)
    ref = snapshot["UDATOUT/qelasn"][:25, 2025 - 1990] / 1000.0
    assert np.abs(mine / ref - 1).max() < 0.005


def test_load_takes_off_nontraditional_cogen_and_ldsm_losses(snapshot):
    """LDSM grosses sales up by 1 + ULOSSADJ x UQTDLS (0.8 from 2020), and the electric power sector's CHP units,
    which the dispatched fleet does not hold, supply part of the load."""
    assert demand.loss_adjustment(2030) == 0.8 and demand.loss_adjustment(2012) == 1.05
    nt = demand.nontraditional_cogen_twh(snapshot, 2030)
    assert 110 < nt.sum() < 135
    assert np.all(nt >= 0)


def test_regional_load_is_not_wildly_off(snapshot):
    nl = demand.net_load_twh(snapshot, 2030)
    ref = snapshot["UEFDOUT/ugntlnr"][:, :25, 2030 - 1990].sum(axis=0)
    assert np.median(np.abs(nl / ref - 1)) < 0.15
    assert (nl[20:23] / ref[20:23]).max() < 1.25            # the western regions that used to run short


def test_nontraditional_cogen_fuel_is_part_of_power_sector_fuel(snapshot):
    """The CHP units' fuel (CGNTQ) is in EIA's QNGEL and in UFL* (classes 1 to 4), but not behind UGN* (1 to 3).
    The loop adds it back to the fleet's fuel."""
    nt = demand.nontraditional_cogen_fuel_tbtu(snapshot, 2030)
    qngel = float(snapshot["QBLK/qngel"][10, 2030 - 1990])
    assert 0.08 < nt["gas"] / qngel < 0.11
    assert nt["oil"] < 30.0
