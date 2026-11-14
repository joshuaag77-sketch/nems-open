"""One model year of the industrial module (two iterations of Setup_Mac_and_Price, ISEAM, CALIBRATE_COAL_ELEC and
WEXOG) from the oracle's start-of-year state, against the oracle's end-of-year QBLK industrial fuels.

The process-flow industries are replayed from the oracle's reference record (standin.py), so this checks everything
else: the end-use industries, the yearly shell, benchmarking and QBLK."""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.industrial.standin import Reference, make_standin
from nems_open.industrial.year import run_year, start_state

YEARS = [36, 37, 38, 41, 51, 61]
QOUT = ["qelin", "qgfin", "qgiin", "qngin", "qclin", "qmcin", "qciin", "qrsin", "qdsin", "qlgin", "qmgin", "qsgin", "qpcin",
        "qasin", "qluin", "qpfin", "qksin", "qotin", "qhoin", "qbmin", "qmsin", "qtrin", "qprin", "qetin", "qh2in"]
TOL = 1e-3

pytestmark = pytest.mark.skipif(not oracle_state.available("ys_in", 61, "ind"), reason="oracle state not dumped")


def rel(a, b):
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    return float((np.abs(a - b) / np.maximum(np.abs(b), 1e-3)).max())


@pytest.fixture(scope="module")
def reference():
    final = oracle_state.load("wx_out", 61, "ind", only=["refqm", "refqi", "refqr", "refelown", "refelsale", "outind"])
    return Reference.from_dump(final)


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
def test_year(y, reference):
    s, bufs = start_state(oracle_state.load("ys_in", y, "ind"))
    run_year(s, bufs, 2, make_standin(reference))
    after = oracle_state.load("wx_out", y, "ind")
    bad = {}
    for n in QOUT:
        e = rel(s[n].a[:, y - s[n].lb[1]], after[n].a[:, y - after[n].lb[1]])
        if e > TOL:
            bad[n] = e
    assert not bad, bad
