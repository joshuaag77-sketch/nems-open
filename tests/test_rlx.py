"""The AEO2025 restart reader (nems_open.rlx), on EIA's ref2025 restart if it has been fetched."""

from pathlib import Path

import numpy as np
import pytest

from nems_open import rlx
from nems_open.paths import REPO_ROOT

RLX = REPO_ROOT / "data" / "aeo2025" / "ref2025" / "d031725c" / "restart.rlx"
DICT = REPO_ROOT / "data" / "aeo2025" / "tag" / "input" / "dict.txt"
pytestmark = pytest.mark.skipif(not (RLX.exists() and DICT.exists()), reason="AEO2025 data not fetched (docs/aeo_diff.md)")


@pytest.fixture(scope="module")
def restart():
    return rlx.read(RLX, DICT)


def test_every_variable_is_read_and_most_have_their_dictionary_shape(restart):
    assert len(restart) == 3925
    assert restart["MPBLK/PELRS"].shape == (11, 61)
    assert restart["QBLK/QTSRS"].shape == (11, 61)
    assert restart["MACOUT/MC_GDPR"].shape == (61,)


def test_values_are_plausible_big_endian_reals(restart):
    gdp = restart["MACOUT/MC_GDPR"]
    assert np.isfinite(gdp).all() and 10000 < gdp[2024 - 1990] < 40000
    assert 5000 < restart["QBLK/QTSRS"][10, 2030 - 1990] < 20000


def test_national_row_is_the_sum_of_the_census_divisions(restart):
    q = restart["QBLK/QTSRS"]
    y = 2030 - 1990
    assert abs(q[:9, y].sum() - q[10, y]) < 0.5 * 1e-2 * q[10, y]
