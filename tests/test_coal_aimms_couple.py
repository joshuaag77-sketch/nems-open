"""run(coal="aimms"): EIA's coal model in AIMMS as the loop's coal market. The input side is checked without AIMMS;
one short run checks the process end to end where AIMMS is installed (skipped elsewhere)."""

import numpy as np
import pytest

from nems_open.coal import aimms_couple as ac
from nems_open.coal import aimms_run, state
from nems_open.paths import REFERENCE_RUN
from nems_open.snapshot import Snapshot

pytestmark = pytest.mark.skipif(not (REFERENCE_RUN.exists() and state.COAL_AMS.exists()), reason="EIA checkout missing")


def bare():
    """An AimmsCoal without its AIMMS process, for the input side."""
    c = ac.AimmsCoal.__new__(ac.AimmsCoal)
    s = Snapshot()
    c.base = {k: np.asarray(s[k], dtype=np.float64) for k in ac.Q_IN + ac.P_IN + ("COALEMM/QCLCLNR", "COALEMM/EMM_CL_BTUS")}
    return c


def test_inputs_carry_the_loop_coal_use_and_prices():
    c = bare()
    j = 2030 - 1990
    q = {"QBLK/qclel": c.base["QBLK/QCLEL"] * 0.8, "QBLK/qclin": c.base["QBLK/QCLIN"] * 1.1}
    prices = {"MPBLK/pelin": c.base["MPBLK/PELIN"] * 1.3}
    a = c.inputs(2030, q, prices)
    np.testing.assert_allclose(a["QBLK/QCLEL"][:, j], 0.8 * c.base["QBLK/QCLEL"][:, j])
    np.testing.assert_allclose(a["QBLK/QCLEL"][:, j + 1], c.base["QBLK/QCLEL"][:, j + 1])   # other years untouched
    np.testing.assert_allclose(a["QBLK/QCLIN"][:, j], 1.1 * c.base["QBLK/QCLIN"][:, j])
    np.testing.assert_allclose(a["MPBLK/PELIN"][:, j], 1.3 * c.base["MPBLK/PELIN"][:, j])
    # the power sector's coal by coal region and plant type moves with US qclel
    np.testing.assert_allclose(a["COALEMM/QCLCLNR"][:, j, :].sum(), 0.8 * c.base["COALEMM/QCLCLNR"][:, j, :].sum(), rtol=1e-6)


def test_baseline_inputs_reproduce_the_restart_file(tmp_path):
    c = bare()
    s = Snapshot()
    base_q = {ac._loop_key(k): c.base[k] for k in ac.Q_IN}
    base_p = {ac._loop_key(k): c.base[k] for k in ac.P_IN}
    a = c.inputs(2030, base_q, base_p)
    one = aimms_run.write_input(2030, 1, tmp_path / "a", s).read_text()
    two = aimms_run.write_input(2030, 1, tmp_path / "b", s, a).read_text()
    assert one == two


@pytest.mark.skipif(not aimms_run.AIMMS.exists(), reason="AIMMS not installed")
@pytest.mark.slow
def test_cmm_serves_two_years(tmp_path):
    p = ac.CoalProcess(tmp_path / "run")
    try:
        for y in (2024, 2025):
            for i in (1, 2):
                o, sec = p.call(y, i, fcrl=int(i == 2))
        pr = ac._prices(o, 2025)
        eia = np.asarray(Snapshot()["MPBLK/PCLEL"])[10, 2025 - 1990]
        assert abs(pr["MPBLK/pclel"][10] / eia - 1) < 0.25
    finally:
        p.close()
