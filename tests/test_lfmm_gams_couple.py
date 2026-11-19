"""run(lfmm="gams") plumbing that needs no GAMS: log parsing, output columns, calibration and when LFMM is called."""

import pytest
import numpy as np

from nems_open.lfmm import gams_couple
from nems_open.lfmm.gams_couple import LfmmGams, columns, solve_info

LOG = """--- Starting execution: elapsed 0:00:00.858
---   46,768 rows  119,840 columns  657,089 non-zeroes
Running HiGHS 1.14.0
Model status        : Optimal
Objective value     : -8.1576145749e+07
HiGHS run time      :        112.12
    (solvestat, modelstat): (1, 1)
"""


def test_solve_info(tmp_path):
    p = tmp_path / "LFMM.log"
    p.write_text(LOG)
    i = solve_info(p)
    assert (i["rows"], i["columns"], i["nonzeros"]) == (46768, 119840, 657089)
    assert i["status"] == "Optimal" and i["modelstat"] == 1 and i["solver"] == "HiGHS"
    assert i["objective"] == -8.1576145749e+07 and i["solver_time_s"] == 112.12


def test_columns_picks_the_year_and_regions():
    o = {"MPBLK_PMGTR": {("01_New_England", "2035_MNUMYR"): 8.0, ("11_United_States", "2035_MNUMYR"): 9.0,
                         ("11_United_States", "2034_MNUMYR"): 1.0},
         "LFMMOUT_RFSCREDPRC": {("1_M4", "2035_MNUMYR"): 5.0}}
    c = columns(o, 2035)
    assert list(c) == ["MPBLK/pmgtr"]
    assert c["MPBLK/pmgtr"][0] == 8.0 and c["MPBLK/pmgtr"][10] == 9.0 and c["MPBLK/pmgtr"][1] == 0.0


def _fake(calibrate=True):
    lf = object.__new__(LfmmGams)
    j = 45
    base = {"MPBLK/pmgtr": np.full((11, 61), 10.0), "QBLK/qngrf": np.full((11, 61), 100.0),
            "QBLK/qngin": np.full((11, 61), 1000.0)}
    lf.base, lf.calibrate, lf.cycle, lf.showreel = base, calibrate, 1, False
    lf._ref = {2035: {"MPBLK/pmgtr": np.full(11, 8.0), "QBLK/qngrf": np.full(11, 90.0)}}
    lf._last, lf.calls = {}, []

    def call(year, itr, fcrl, arrays):
        lf.calls.append((year, itr, fcrl))
        return {"MPBLK/pmgtr": np.full(11, 8.8), "QBLK/qngrf": np.full(11, 99.0)}
    lf.call = call
    lf._inputs = lambda j, q, col, prices: {}
    return lf, j, base


def test_calibrated_moves_are_lfmm_ratios():
    lf, j, base = _fake()
    q = {k: v.copy() for k, v in base.items() if k.startswith("QBLK/")}
    r = lf.solve_year(j, q, {}, {}, 1, 0)
    assert np.allclose(r.prices["MPBLK/pmgtr"], 10.0 * 8.8 / 8.0)
    assert np.allclose(r.refinery["QBLK/qngrf"], 100.0 * 99.0 / 90.0)
    assert np.allclose(r.industry["QBLK/qngin"], 1000.0 + 100.0 * 99.0 / 90.0 - 100.0)


def test_lfmm_runs_on_first_and_final_iterations_only():
    lf, j, base = _fake()
    q = {k: v.copy() for k, v in base.items() if k.startswith("QBLK/")}
    for itr, fcrl in ((1, 0), (2, 0), (3, 0), (4, 1)):
        lf.solve_year(j, q, {}, {}, itr, fcrl)
    assert lf.calls == [(2035, 1, 0), (2035, 4, 1)]


def test_uncalibrated_passes_lfmm_through():
    lf, j, base = _fake(calibrate=False)
    q = {k: v.copy() for k, v in base.items() if k.startswith("QBLK/")}
    r = lf.solve_year(j, q, {}, {}, 1, 0)
    assert np.allclose(r.prices["MPBLK/pmgtr"], 8.8)


def test_run_model_accepts_gams():
    import pytest
    from nems_open import run_model
    with pytest.raises(ValueError, match="baseline must be cb2026"):
        run_model.run(lfmm="gams", baseline="hm2026")
    assert gams_couple.SAMPLE_YEAR == 2030


def test_infeasible_keeps_last_solve():
    from nems_open.lfmm.gams_couple import LfmmInfeasible
    lf, j, base = _fake()
    lf.infeasible = []
    ok = lf.call
    q = {k: v.copy() for k, v in base.items() if k.startswith("QBLK/")}
    first = lf.solve_year(j, q, {}, {}, 1, 0)

    def bad(year, itr, fcrl, arrays):
        raise LfmmInfeasible("infeasible")
    lf.call = bad
    again = lf.solve_year(j, q, {}, {}, 9, 1)
    assert np.allclose(again.prices["MPBLK/pmgtr"], first.prices["MPBLK/pmgtr"])
    assert lf.infeasible == [(2035, 9)]
    lf._last.clear()   # 2041 cycle 2 itr 1: first solve of the year infeasible, falls back to the reference solve
    lf.fallbacks = []
    fb = lf.solve_year(j, q, {}, {}, 1, 0)
    assert np.allclose(fb.prices["MPBLK/pmgtr"], 10.0)   # calibrated: reference over reference = EIA's own value
    assert lf.fallbacks == [(2035, 1)]
    lf.call = ok


def test_infeasible_restores_state(tmp_path, monkeypatch):
    from nems_open.lfmm import gams_couple as gc
    lf = object.__new__(gc.LfmmGams)
    lf.run, lf.cycle, lf.timeout, lf.showreel = tmp_path, 1, 1, False
    lf.solver_failures = []
    (tmp_path / "LFMM_Builds.gdx").write_bytes(b"before")
    monkeypatch.setattr(gc.gams_run, "prepare", lambda *a, **k: None)
    monkeypatch.setattr(gc.gams_run, "clean_dumps", lambda *a: None)

    def gams(run, timeout):
        (run / "LFMM_Builds.gdx").write_bytes(b"after")
        (run / "LFshell.lst").write_text("listing")
        (run / "LFMM.log").write_text("    (solvestat, modelstat): (1, 4)\n")
        return 0
    monkeypatch.setattr(gc.gams_run, "gams", gams)
    with pytest.raises(gc.LfmmInfeasible):
        lf.call(2041, 9, 1, {})
    assert (tmp_path / "LFMM_Builds.gdx").read_bytes() == b"before"
    assert (tmp_path / "INFEAS.2041.1.9.lst").read_text() == "listing"


def _bare(tmp_path):
    from nems_open.lfmm import gams_couple as gc
    lf = object.__new__(gc.LfmmGams)
    lf.run, lf.cycle, lf.timeout, lf.showreel = tmp_path, 2, 1, False
    lf.solver_failures, lf.license_retries = [], 0
    (tmp_path / "LFMM_Builds.gdx").write_bytes(b"before")
    return lf


def test_solver_failure_retries_with_ipm(tmp_path, monkeypatch):
    """2039 cycle 2: dual simplex lost stability (Not Set, solvestat 13). Retry restores state and uses highs.opt."""
    from nems_open.lfmm import gams_couple as gc
    lf = _bare(tmp_path)
    monkeypatch.setattr(gc.gams_run, "prepare", lambda *a, **k: None)
    monkeypatch.setattr(gc.gams_run, "clean_dumps", lambda *a: None)
    monkeypatch.setattr(gc.gams_io, "read_outputs", lambda p: {})
    seen = []

    def gams(run, timeout):
        opt = run / "highs.opt"
        seen.append((opt.read_text() if opt.exists() else None, (run / "LFMM_Builds.gdx").read_bytes()))
        (run / "LFMM_Builds.gdx").write_bytes(b"after")
        if len(seen) == 1:
            (run / "LFMM.log").write_text("Model status        : Not Set\n    (solvestat, modelstat): (13, 13)\n")
        else:
            (run / "LFMM.log").write_text("    (solvestat, modelstat): (1, 1)\n")
            (run / "LFMM_to_NEMS.gdx").write_bytes(b"x")
        return 0
    monkeypatch.setattr(gc.gams_run, "gams", gams)
    lf.call(2039, 12, 1, {})
    assert seen[0] == (f"time_limit = {gc.TIME_LIMIT}\n", b"before")
    assert "ipm" in seen[1][0] and seen[1][1] == b"before"
    assert lf.solver_failures == [(2039, 12, 0)]
    assert not (tmp_path / "highs.opt").exists()


def test_solver_failure_on_every_option_keeps_last_solve(tmp_path, monkeypatch):
    from nems_open.lfmm import gams_couple as gc
    lf = _bare(tmp_path)
    monkeypatch.setattr(gc.gams_run, "prepare", lambda *a, **k: None)
    monkeypatch.setattr(gc.gams_run, "clean_dumps", lambda *a: None)

    def gams(run, timeout):
        (run / "LFMM_Builds.gdx").write_bytes(b"after")
        (run / "LFMM.log").write_text("Model status        : Not Set\n    (solvestat, modelstat): (13, 13)\n")
        return 0
    monkeypatch.setattr(gc.gams_run, "gams", gams)
    with pytest.raises(gc.LfmmInfeasible):
        lf.call(2039, 12, 1, {})
    assert (tmp_path / "LFMM_Builds.gdx").read_bytes() == b"before"
    assert len(lf.solver_failures) == len(gc.RETRY_OPTIONS)


def test_solver_crash_mid_solve_retries(tmp_path, monkeypatch):
    """2030 cycle 2: dual simplex stalled, then HiGHS died with bad_alloc (GAMS rc 6, no solve summary)."""
    from nems_open.lfmm import gams_couple as gc
    lf = _bare(tmp_path)
    monkeypatch.setattr(gc.gams_run, "prepare", lambda *a, **k: None)
    monkeypatch.setattr(gc.gams_run, "clean_dumps", lambda *a: None)
    monkeypatch.setattr(gc.gams_io, "read_outputs", lambda p: {})
    calls = []

    def gams(run, timeout):
        calls.append((run / "highs.opt").read_text())
        if len(calls) == 1:
            (run / "LFMM.log").write_text("Running HiGHS 1.7\nUsing dual simplex solver\n")
            return 6
        (run / "LFMM.log").write_text("    (solvestat, modelstat): (1, 1)\n")
        (run / "LFMM_to_NEMS.gdx").write_bytes(b"x")
        return 0
    monkeypatch.setattr(gc.gams_run, "gams", gams)
    lf.call(2030, 20, 1, {})
    assert lf.solver_failures == [(2030, 20, 0)]
    assert all(c.startswith("time_limit") for c in calls) and "ipm" in calls[1]


def test_compile_error_is_not_a_solver_failure():
    from nems_open.lfmm import gams_couple as gc
    assert not gc.solver_failed(2, {}, "*** Error 140 in LFshell.gms")
    assert gc.solver_failed(0, {"solvestat": 3, "status": "Time limit reached"})


def test_time_limit_with_nonzero_rc_is_a_solver_failure():
    from nems_open.lfmm import gams_couple as gc
    assert gc.solver_failed(6, {"solvestat": 3, "modelstat": 6, "status": "Time limit reached"}, "HiGHS")


def test_license_error_waits_and_reruns(tmp_path, monkeypatch):
    from nems_open.lfmm import gams_couple as gc
    lf = _bare(tmp_path)
    monkeypatch.setattr(gc.time, "sleep", lambda s: None)
    rcs = iter([7, 7, 0])
    monkeypatch.setattr(gc.gams_run, "gams", lambda run, timeout: next(rcs))
    assert lf._gams_licensed() == 0 and lf.license_retries == 2


def test_network_license_error_with_rc_minus_one_retries(tmp_path, monkeypatch):
    """2026-11-19 06:09, after standby: GAMS exited 4294967295 and LFMM.log held only the license curl error."""
    from nems_open.lfmm import gams_couple as gc
    lf = _bare(tmp_path)
    monkeypatch.setattr(gc.time, "sleep", lambda s: None)
    rcs = iter([4294967295, 0])

    def gams(run, timeout):
        rc = next(rcs)
        (run / "LFMM.log").write_text("*** Error: Error when trying to start network session:\nCurl error: x\n" if rc else "ok\n")
        return rc
    monkeypatch.setattr(gc.gams_run, "gams", gams)
    assert lf._gams_licensed() == 0 and lf.license_retries == 1
    assert not gc.license_failed(6, tmp_path / "missing.log")
