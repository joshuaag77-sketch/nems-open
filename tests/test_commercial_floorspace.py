"""COMFloorspace port vs the AEO2026 reference run.

Done rule for every port: within 0.1% of EIA for every region and year.
Floorspace currently matches to about 1e-6 (float32 rounding in EIA's file).
"""

import numpy as np
import pytest

from nems_open.commercial.floorspace import (
    FIRST_YEAR,
    MNUMYR,
    NUM_BLDG,
    NUM_DIV,
    Floorspace,
    FloorspaceInputs,
)
from nems_open.snapshot import Snapshot

TOL = 1e-3


@pytest.fixture(scope="module")
def snap():
    return Snapshot()


@pytest.fixture(scope="module")
def fs(snap):
    return Floorspace(FloorspaceInputs.load()).run(snap["MACOUT/mc_commflsp"])


def rel_err(mine, theirs):
    return np.abs(mine - theirs) / np.maximum(np.abs(theirs), 1e-6)


def test_backcast_construction_matches(fs, snap):
    eia = snap["COMMREP/cmnewfloorspace"][:NUM_DIV, :, : fs.NEW_OFFSET + FIRST_YEAR]
    mine = fs.new[1 : NUM_DIV + 1, 1 : NUM_BLDG + 1, : fs.NEW_OFFSET + FIRST_YEAR]
    assert rel_err(mine, eia).max() < TOL


@pytest.mark.parametrize("name,attr,nb", [
    ("COMMREP/cmtotalflspc", "total", NUM_BLDG + 1),
    ("COMMREP/survfloortotal", "surviving", NUM_BLDG),
])
def test_projection_matches(fs, snap, name, attr, nb):
    years = slice(FIRST_YEAR, MNUMYR + 1)
    eia = snap[name][:NUM_DIV, :nb, FIRST_YEAR - 1 : MNUMYR]
    mine = getattr(fs, attr)[1 : NUM_DIV + 1, 1 : nb + 1, years]
    assert rel_err(mine, eia).max() < TOL


def test_us_totals_match(fs, snap):
    for y in range(FIRST_YEAR, MNUMYR + 1):
        assert fs.us_surviving(y) == pytest.approx(snap["COMMREP/cmussurvfloortot"][y - 1], rel=TOL)
        assert fs.us_new(y) == pytest.approx(snap["COMMREP/cmusnewfloortot"][y - 1], rel=TOL)
