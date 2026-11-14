"""The industrial module's year loop, 2025 to 2050, from the oracle's 2025 start state, against the oracle's QBLK.

QBLK industrial fuel totals (US, all fuels) must match the oracle within 1e-3 in every year. The process-flow
industries and oil and gas mining are replayed from the oracle's reference record (standin.py), scaled by output; with
EIA's macro inputs that reproduces them, so this checks the ported end-use industries, the yearly shell,
benchmarking and CALIBRATE carried from year to year."""

import os

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.industrial.standin import Reference, make_standin
from nems_open.industrial.year import run_year, start_state

FUELS = ["qelin", "qgfin", "qgiin", "qngin", "qclin", "qmcin", "qciin", "qrsin", "qdsin", "qlgin", "qmgin", "qsgin", "qpcin",
         "qasin", "qluin", "qpfin", "qksin", "qotin", "qhoin", "qbmin", "qmsin", "qtrin", "qprin", "qetin", "qh2in"]
TOL = 1e-3

pytestmark = [
    pytest.mark.skipif(not oracle_state.available("ys_in", 36, "ind"), reason="oracle state not dumped"),
    pytest.mark.skipif(not os.environ.get("NEMS_SLOW"), reason="set NEMS_SLOW=1 (about two minutes)"),
]


def test_chain_2025_2050():
    ref = Reference.from_dump(oracle_state.load("wx_out", 61, "ind", only=["refqm", "refqi", "refqr", "refelown", "refelsale", "outind"]))
    s, bufs = start_state(oracle_state.load("ys_in", 36, "ind"))
    standin = make_standin(ref)
    out = oracle_state.out_dir("ind")
    oracle = {k: np.fromfile(out / f"{k}.bin", dtype=np.float32).reshape((11, -1), order="F") for k in FUELS if (out / f"{k}.bin").exists()}
    worst = {}
    for y in range(36, 62):
        s["curiyr"] = np.int32(y)
        s["curcalyr"] = np.int32(y + 1989)
        s["iyr"] = np.int32(y + 1989)
        run_year(s, bufs, 2, standin)
        for k, o in oracle.items():
            a = np.asarray(s[k].a[10, y - s[k].lb[1]], dtype=np.float64)   # US total
            b = float(o[10, y - 1])
            e = abs(a - b) / max(abs(b), 1e-3)
            worst[(y + 1989, k)] = e
    bad = {k: round(e, 5) for k, e in worst.items() if e > TOL}
    assert not bad, dict(sorted(bad.items(), key=lambda kv: -kv[1])[:20])
