"""TMPGNEW ports vs the transportation oracle, stretch by stretch.

Each test runs the Python between two dump points inside TMPGNEW (hooks_tran.py
TARGETS tmpg_*), comparing the whole TMPGNEW state at the end.
"""

import pytest

from nems_open.transportation import cafe, femcalc, ldv_attrib, ldv_choice, ldv_tech, tmpgnew
from tran_harness import YEARS, needs, run

pytestmark = needs("tmpg_lion")

STRETCHES = {
    "setup": (tmpgnew.setup, "tmpgnew_in", "tmpg_lion_in"),
    "lioncostcalc": (ldv_tech.lioncostcalc, "tmpg_lion_in", "tmpg_lion_out"),
    "nameplates": (tmpgnew.nameplates, "tmpg_lion_out", "tmpg_fem1_in"),
    "femcalc": (femcalc.femcalc, "tmpg_fem1_in", "tmpg_fem1_out"),
    "cgshare": (ldv_attrib.cgshare, "tmpg_cgs1_in", "tmpg_cgs1_out"),
    "tattrib": (ldv_attrib.tattrib, "tmpg_att1_in", "tmpg_att1_out"),
    "talt2": (ldv_choice.talt2, "tmpg_alt1_in", "tmpg_alt1_out"),
    "talt2x": (ldv_choice.talt2x, "tmpg_altx1_in", "tmpg_altx1_out"),
    "cafecalc0": (lambda st: cafe.cafecalc(st, 0), "tmpg_cafe0_in", "tmpg_cafe0_out"),
    "cafecalc1": (lambda st: cafe.cafecalc(st, 1), "tmpg_cafe1_in", "tmpg_cafe1_out"),
}


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("name", list(STRETCHES))
def test_stretch(name, y):
    port, start, end = STRETCHES[name]
    if name == "femcalc" and y <= 33:
        pytest.skip("FEMCALC runs only after 2022")
    if name == "lioncostcalc":
        # Called only from FIRST_BAT_YR on; before that the stretch is empty.
        import nems_open.oracle_state as os_
        st = os_.load(start, y, run="run_tran")
        if int(st["yrs"]) < int(st["first_bat_yr"]) + 1989 - 1:
            pytest.skip("LIONCOSTCALC not called this year")
    # Before the EPA calibration years the setup stretch does nothing, as in the Fortran.
    # Technology shares go through 1/(1+exp(x)); numpy's and gfortran's expf differ by an ulp,
    # about 1e-7 on shares near 0.001. FEMCALC is held to the project's 0.1% rule, not 1e-4.
    tol = 1e-3 if name == "femcalc" else 1e-4
    kwargs = {}
    if name == "talt2":
        # TALT2's saved arrays, dumped at its end in tmpgnew_out; only year n-1 is read.
        from tran_harness import _blank_from
        import nems_open.oracle_state as os_
        out = os_.load("tmpgnew_out", y, run="run_tran")
        kwargs["carry"] = {k: _blank_from(out[f"p_{k}"], y) for k in ("altstat", "predstk")}
    if name == "talt2x" and y <= 35:
        pytest.skip("TALT2X runs only after 2024")
    assert run(port, "tmpgnew", y, start=start, end=end, tol=tol, may_be_empty=name in ("setup", "cafecalc1"), **kwargs) == {}
