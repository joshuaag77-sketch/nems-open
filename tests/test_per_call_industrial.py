"""The industrial module gives the same year however many times the coupled loop calls it.

EIA's cb2026 run calls IND three times a year with NCRL = 0 (CURITR 1, 2 and the FCRL pass), then once with NCRL = 1,
which runs CALIBRATE (ind.f 1099). Our loop calls it up to 21 times. Two faults made the answer depend on that count:
CALIBRATE ran after iteration 2 and later iterations rebuilt the buffers uncalibrated, and CALIBRATE_COAL_ELEC scaled
the stand-in industries' saved steam and process fuel by its factor on every call, so it compounded and overflowed
float32 in 2041 at 6 calls a year. See docs/per_call_state_audit.md."""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.converge import EIA_CALLS
from nems_open.industrial.standin import REPLAYED, Reference, make_standin
from nems_open.industrial.year import run_year, start_state

pytestmark = pytest.mark.skipif(not oracle_state.available("ys_in", 51, "ind"), reason="oracle state not dumped")
BUFFERS = ("qtymain", "qtyrenw", "enpmqty", "ensqty", "bypbscm", "enbqty", "enpqty", "elown", "biosteam")
REPORTS = ("xelinshr", "xelin")
QOUT = ("qbmin", "qtrin", "qngin", "qelin", "qclin", "qdsin", "qlgin")


@pytest.fixture(scope="module")
def standin():
    return make_standin(Reference.load())


def _year(y, calls, standin):
    s, bufs = start_state(oracle_state.load("ys_in", y, "ind"))
    run_year(s, bufs, calls, standin)
    return s, bufs


def _val(v):
    return np.asarray(v.a if hasattr(v, "a") else v, dtype=np.float64)


@pytest.fixture(scope="module", params=[51], ids=["2040"])
def runs(request, standin):
    y = request.param
    return y, _year(y, EIA_CALLS, standin), _year(y, 6, standin)


def test_six_calls_leave_the_buffers_of_eias_three(runs):
    """The buffers next year starts from (after CALIBRATE) are the same after 6 calls as after EIA's 3."""
    _, (_, b3), (_, b6) = runs
    for key in b3:
        for n in BUFFERS:
            got, want = _val(b6[key][n]), _val(b3[key][n])
            assert np.all(np.isfinite(got)), (key, n)
            assert np.allclose(got, want, rtol=1e-5, atol=1e-3), (key, n)


def test_six_calls_give_eias_quantities_and_reports(runs):
    y, (s3, _), (s6, _) = runs
    for n in QOUT:
        j = y - s3[n].lb[1]
        assert np.allclose(s6[n].a[:, j], s3[n].a[:, j], rtol=1e-5, atol=1e-3), n
    for n in REPORTS:
        assert np.allclose(_val(s6[n]), _val(s3[n]), rtol=1e-5, atol=1e-6), n


def test_stand_in_steam_and_process_fuel_do_not_compound(runs):
    """CALIBRATE_COAL_ELEC no longer multiplies the stand-in industries' saved copies on every call."""
    _, _, (_, b6) = runs
    for (ind, ir), b in b6.items():
        if ind in REPLAYED:
            for n in ("enpmqty", "ensqty", "bypbscm"):
                assert not np.any(_val(b[n])), (ind, ir, n)


@pytest.mark.skipif(not oracle_state.available("ys_in", 38, "ind"), reason="oracle state not dumped")
def test_coupled_loop_calibrates_once_after_the_last_call():
    """Through IndustrialSector as the coupled loop drives it (first year from iteration 2, then end_year): 7 calls
    give the buffers and reports of EIA's 3 calls plus the NCRL call."""
    from nems_open.run_demand import IndustrialSector, Inputs
    inputs = Inputs()
    want = {}
    for calls in (EIA_CALLS, 7):
        sec = IndustrialSector("ported")
        st = sec.start(2027, inputs)
        for itr in range(2, calls + 2):
            sec.iteration(st, 2027, itr, inputs)
        sec.end_year(st, 2027)
        got = {(k, n): _val(b[n]) for k, b in st.bufs.items() for n in BUFFERS}
        got.update({n: _val(st.s[n]) for n in REPORTS})
        if not want:
            want = got
            continue
        for k, v in want.items():
            assert np.allclose(got[k], v, rtol=1e-5, atol=1e-3), k
