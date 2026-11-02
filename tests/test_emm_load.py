"""Load shapes and LDSM inputs."""

import numpy as np
import pytest

from nems_open.emm import load, regions
from nems_open.paths import INPUT, REFERENCE_RUN
from nems_open.snapshot import Snapshot

pytestmark = pytest.mark.skipif(not (INPUT / "emm" / "emm_db" / "NEMS_INPUT.db").exists(), reason="EMM inputs missing")


def test_day_weights_cover_the_year():
    assert load.day_weights().shape == (12, 3)
    assert load.day_weights().sum() == 365


def test_regional_shapes_sum_to_one():
    shape = load.regional_shapes()
    assert shape.shape == (25, 12, 3, 24)
    total = (shape * load.day_weights()[None, :, :, None]).sum(axis=(1, 2, 3))
    assert np.abs(total - 1.0).max() < 1e-5


def test_hourly_profile_is_8760_hours_of_the_same_energy():
    p = load.hourly_profile(1)
    assert p.shape == (8760,)
    assert abs(p.sum() - 1.0) < 1e-5


@pytest.mark.skipif(not REFERENCE_RUN.exists(), reason="reference run missing")
def test_load_factor_close_to_nems_system_load_factor():
    """NEMS reweights end-use shapes by sector mix, so the match is to about 5%, not exact."""
    eia = Snapshot()["DSMTFEFP/systemlf"][:25]
    mine = load.load_factor()
    assert np.abs(mine / eia - 1).max() < 0.05


def test_end_use_shapes_and_table():
    shapes = load.end_use_shapes()
    assert len(shapes) == 114
    eu = load.end_use_table()
    assert len(eu["region"]) == 3300 and set(eu["sector"]) == {1, 2, 3, 4}
    # 132 end-use rows per region; base-year loads in the file are zero, NEMS fills them from demand.
    assert all((eu["region"] == r).sum() == 132 for r in range(1, 26))


def test_region_parameters():
    p = load.region_parameters()
    assert p["td_loss"].shape == (25,) and 0 < p["td_loss"].max() < 0.2
