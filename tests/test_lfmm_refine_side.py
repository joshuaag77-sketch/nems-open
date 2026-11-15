"""refine.f's E85.gdx and STEO_Hist.gdx contents (ports in nems_open.lfmm.refine_side)."""

import numpy as np
import pytest

from nems_open.lfmm import refine_side as rs
from nems_open.paths import REFERENCE_RUN

pytestmark = pytest.mark.skipif(not REFERENCE_RUN.exists(), reason="EIA checkout missing")


def test_rfinvest_reads_design_two():
    r = rs.rfinvest()
    assert r["E85curveSwitch"] == 2 and r["LFMM_PERIOD"] == {1: 1, 2: 1, 3: 19}
    assert (r["Lower_ELAS"], r["Upper_ELAS"], r["E85MGexpPrRatio"]) == (0.6, 0.3, 1.2)
    assert r["E85availLYR"] == 2019 and len(r["Upper_Percents"]) == 10


def test_e85_curve_shape():
    d = rs.e85(rs.restart_inputs(), 2035)
    j = 2035 - 1990
    assert d["E85_StepsLOOP"] == 20
    qo = d["QoE85"][:9, j]
    assert (qo >= 0).all() and qo.sum() > 0
    # steps add up to Qo times the step percents, and the price rises along the curve
    np.testing.assert_allclose(d["Q_E85STP_t"][:20, 3, j].sum(), qo[3] * 2.0, rtol=1e-6)
    assert np.all(np.diff(d["P_E85STP_t"][:20, 3, j]) > 0)
    # horizon: 1 + 1 + 19 years from 2035
    assert d["MOGASPRICE"][0, 2035 - 1990 + 20] > 0 and d["MOGASPRICE"][0, 2035 - 1990 + 21] == 0


def test_steo_hist_switches():
    assert rs.rfhist_switches()["STEOLYR"] == 37
