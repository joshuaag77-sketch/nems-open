"""input_tables() against the tables the runner copies from the oracle, one test per table."""

import numpy as np
import pytest
from nems_open import oracle_state
from nems_open.commercial import comm
from nems_open.commercial.first_call import input_tables
from nems_open.snapshot import Snapshot

pytestmark = pytest.mark.skipif(not oracle_state.available("cn_out", 30), reason="oracle state not dumped")

# Which dump holds each table (comm.start_from_dump takes them from these).
SOURCES = [("sd_out", comm.SD_TABLES), ("tc_out", comm.TC_TABLES), ("cn_out", comm.CN_TABLES),
           ("bm_out", comm.BM_TABLES)]
# COMConsumption recomputes these two from zero in every call, so they are results, not inputs.
COMPUTED = {"prsvstdsavings", "foodsvchlthldgfloortot"}
NAMES = [(tag, name) for tag, names in SOURCES for name in names if name not in COMPUTED]


@pytest.fixture(scope="module")
def mine():
    return input_tables(Snapshot()["MACOUT/mc_revser"])


@pytest.fixture(scope="module")
def eia():
    return {tag: oracle_state.load(tag, 30) for tag, _ in SOURCES}


def values(x, name):
    a = np.asarray(x.a if hasattr(x, "a") else x, dtype=np.float64)
    if name == "servicesindex":
        return a[-32:]                         # 2019 to 2050
    if name == "steodat":
        return a[2:, :]                        # fuels 3 to 8; electricity and gas rows come from other modules
    if name == "minfuelbeta":
        return np.where(a > 0, 0, a)           # COMConsumption zeroes positive betas (comm.f 8714)
    return a


@pytest.mark.parametrize("tag,name", NAMES)
def test_table(mine, eia, tag, name):
    a, b = values(mine[name], name), values(eia[tag][name], name)
    assert a.shape == b.shape, (a.shape, b.shape)
    assert (np.abs(a - b) / np.maximum(np.abs(b), 1e-6)).max() < 1e-6
