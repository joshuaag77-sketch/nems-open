"""The residential Fortran oracle vs EIA's reference run. Skipped until it has run.

Build and run it first (see SCOPE.md). Like the commercial oracle it matches EIA to
rounding through 2026, the last STEO benchmark year, and drifts by up to about 0.3%
after that (2050 US totals within 0.05%). The drift is float rounding between
gfortran and EIA's Intel build, so cells after 2026 get a looser tolerance than
the port rule.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.snapshot import Snapshot

pytestmark = pytest.mark.skipif(not oracle_state.available("final", 61, "resd"), reason="oracle not run")

# Regions 1-9. 10 (California) and 11 (US) are filled outside the module.
FUELS = ["qelrs", "qngrs", "qdsrs", "qlgrs", "qbmrs", "qpvrs"]


@pytest.fixture(scope="module")
def final():
    return oracle_state.load("final", 61, "resd")


def rel(mine, eia):
    # Cells under 0.1% of the array's largest are compared on that floor: region 7
    # distillate is 0.01 trillion Btu, where float noise alone is 1%.
    mine, eia = np.asarray(mine, np.float64), np.asarray(eia, np.float64)
    return np.abs(mine - eia) / np.maximum(np.abs(eia), 1e-3 * np.abs(eia).max())


@pytest.mark.parametrize("name", FUELS)
def test_fuel_use_through_2026(final, name):
    eia = Snapshot()[f"QBLK/{name}"][:9, 30:37]  # 2020-2026
    assert rel(final[name].a[:9, 30:37], eia).max() < 1e-4


@pytest.mark.parametrize("name", FUELS)
def test_fuel_use_to_2050(final, name):
    eia = Snapshot()[f"QBLK/{name}"][:9, 30:]
    mine = final[name].a[:9, 30:]
    assert rel(mine, eia).max() < 2e-2
    assert rel(mine.sum(axis=0), eia.sum(axis=0)).max() < 3e-3


@pytest.mark.parametrize("name", ["RESDREP/rshouses", "RESDREP/rseh", "RESDREP/rsnh", "RESDREP/sqftavg",
                                  "RESDREP/rshtrcon", "RESDREP/rscoolcn", "RESDREP/rsltcon"])
def test_reports_2021_on(final, name):
    # 2020 is the RECS base year: some report cells are carried in EIA's restart
    # from earlier runs rather than computed, so start at 2021.
    eia = Snapshot()[name][31:]
    mine = final[name.split("/")[1]].a[31:]
    assert rel(mine, eia).max() < 5e-3
