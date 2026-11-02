"""KSTEO and KMINFL vs the benchmarking tables in the oracle (2019, first iteration)."""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.commercial import benchmark_inputs as bi

pytestmark = pytest.mark.skipif(not oracle_state.available("cn_out", 30), reason="oracle state not dumped")


@pytest.fixture(scope="module")
def eia():
    return oracle_state.load("cn_out", 30)


def same(mine, theirs):
    mine, theirs = np.asarray(mine, dtype=np.float64), np.asarray(theirs, dtype=np.float64)
    assert mine.shape == theirs.shape
    assert (np.abs(mine - theirs) / np.maximum(np.abs(theirs), 1e-6)).max() < 1e-6


def test_ksteo(eia):
    k = bi.read_ksteo()
    same(k["flagregsteo"][3:9], eia["flagregsteo"][3:9])
    same(k["steodat"][3:9, 1:5], eia["steodat"][3:9, 1:5])
    # Years the file does not give stay zero.
    assert not k["steodat"][3:9, 5:39].any() and not eia["steodat"][3:9, 5:39].any()
    # Regional history (y <= 34) and fuels 1 and 2 come from the restart file, not KSTEO.
    same(k["cmseds"][3:9, 1:10, 35:39], eia["cmseds"][3:9, 1:10, 35:39])


def test_kminfl(eia):
    k = bi.read_kminfl()
    same(k["flooradj"].a, eia["flooradj"].a)
    same(k["minfuelalpha"].a, eia["minfuelalpha"].a)
    # COMConsumption sets every positive MinFuelBeta to 0 each call (comm.f 8714), so the dump has none.
    beta = k["minfuelbeta"].a
    same(np.where(beta > 0, 0, beta), eia["minfuelbeta"].a)
