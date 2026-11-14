"""Power-sector coal demand by plant type and EIA's diversity caps, against the cb2026 restart.

The caps are rebuilt from EMM's unit-level coal burn and the plant shares in cmmProfiles.txt. The
CMM writes its own copy of them back to NEMS (USO2GRP EFD_SB_DVLIM, EFD_LG_DVLIM), which is the check:
exact from 2040, within 4% nationally in 2030 and 2035 (the restart's unit burn is EMM's last
iteration, after the CMM's last call).
"""

import numpy as np
import pytest

from nems_open.coal import electric, state
from nems_open.coal.macro import Macro
from nems_open.paths import REFERENCE_RUN

pytestmark = pytest.mark.skipif(not (REFERENCE_RUN.exists() and state.COAL_AMS.exists()), reason="EIA checkout missing")


@pytest.fixture(scope="module")
def macro():
    return Macro()


def test_unit_names_are_plant_unit_ids(macro):
    names = electric.unit_names(macro.s)
    assert names[:3] == ["3_4", "3_5", "26_5"]
    assert sum(bool(n) for n in names) == int(np.asarray(macro.s["COALEMM/num_cmm_units"]))


@pytest.mark.parametrize("year", [2025, 2030, 2040, 2050])
def test_demand_is_qclclnr(macro, year):
    p = electric.power_demand(year, macro)
    np.testing.assert_allclose(p.demand.sum(), np.asarray(macro.s["COALEMM/qclclnr"])[:, year - 1990, :].sum(), rtol=1e-6)


@pytest.mark.parametrize("year", [2025, 2027, 2030, 2035, 2040, 2050])
def test_caps_match_what_cmm_wrote_back(macro, year):
    p = electric.power_demand(year, macro)
    yi = year - 1990
    for mine, theirs in ((p.sub_cap, "USO2GRP/efd_sb_dvlim"), (p.lig_cap, "USO2GRP/efd_lg_dvlim")):
        ref = np.asarray(macro.s[theirs], float)[:, :, yi]
        assert abs(mine.sum() / ref.sum() - 1) < (0.001 if year >= 2040 else 0.04), (theirs, mine.sum(), ref.sum())
        # cell by cell: no cell off by more than 3% of the national total (or 1.5 TBtu)
        assert np.abs(mine - ref).max() < max(0.03 * ref.sum(), 1.5), (theirs, np.abs(mine - ref).max())


def test_subbituminous_caps_are_active_somewhere(macro):
    p = electric.power_demand(2030, macro)
    assert p.sub_active.sum() > 20
    assert (p.sdvconct[p.sub_active] < electric.SUB_ACTIVE_MAX).all()
