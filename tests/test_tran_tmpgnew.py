"""TMPGNEW ports vs the transportation oracle, stretch by stretch.

Each test runs the Python between two dump points inside TMPGNEW (hooks_tran.py
TARGETS tmpg_*), comparing the whole TMPGNEW state at the end.
"""

import pytest

from nems_open.transportation import ldv_tech, tmpgnew
from tran_harness import YEARS, needs, run

pytestmark = needs("tmpg_lion")

STRETCHES = {
    "setup": (tmpgnew.setup, "tmpgnew_in", "tmpg_lion_in"),
    "lioncostcalc": (ldv_tech.lioncostcalc, "tmpg_lion_in", "tmpg_lion_out"),
    "nameplates": (tmpgnew.nameplates, "tmpg_lion_out", "tmpg_fem1_in"),
}


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("name", list(STRETCHES))
def test_stretch(name, y):
    port, start, end = STRETCHES[name]
    if name == "lioncostcalc":
        # Called only from FIRST_BAT_YR on; before that the stretch is empty.
        import nems_open.oracle_state as os_
        st = os_.load(start, y, run="run_tran")
        if int(st["yrs"]) < int(st["first_bat_yr"]) + 1989 - 1:
            pytest.skip("LIONCOSTCALC not called this year")
    # Before the EPA calibration years the setup stretch does nothing, as in the Fortran.
    assert run(port, "tmpgnew", y, start=start, end=end, may_be_empty=(name == "setup")) == {}
