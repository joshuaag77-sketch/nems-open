"""EMM region tables vs the AEO2026 reference run."""

import numpy as np
import pytest

from nems_open.emm import regions
from nems_open.paths import INPUT, REFERENCE_RUN
from nems_open.snapshot import Snapshot

pytestmark = pytest.mark.skipif(not (INPUT / "emm" / "emm_db" / "NEMS_INPUT.db").exists(), reason="EMM inputs missing")


def test_region_list():
    rs = regions.regions()
    assert [r.number for r in rs] == list(range(1, 29))
    assert rs[0].name == "TRE" and rs[24].name == "BASN" and rs[27].name == "US00"
    assert len(set(r.code for r in rs)) == 28


@pytest.mark.skipif(not REFERENCE_RUN.exists(), reason="reference run missing")
def test_census_share_matches_restart():
    eia = Snapshot()["DSMTFEFP/mappntoc"]          # (28, 11, 4)
    mine = regions.emm_share_of_census()
    assert mine.shape == eia.shape
    assert np.abs(mine[:25] - eia[:25]).max() < 1e-6
    assert np.allclose(mine[:25].sum(axis=1), 1.0, atol=1e-5)
