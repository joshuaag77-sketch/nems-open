"""WEXOG port (benchmark to SEDS/STEO, cracking model, HGL split and QBLK writes) vs the industrial oracle, 2025 to 2050.

The state before and after CALL WEXOG; the port runs on the first and its QBLK industrial
fuels and benchmark factors for the year are compared with the second. The benchmark
factors BF_SEDS and BF_STEO are carried locals of the Fortran routine; the dump holds them.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.industrial.wexog import wexog

YEARS = [36, 37, 38, 41, 51, 61]
QOUT = ["qelin", "qgfin", "qgiin", "inqngpf", "qngin", "qclin", "qmcin", "qciin", "qrsin", "qdsin",
        "qmgin", "qsgin", "qpcin", "qasin", "qluin", "qpfin", "qksin", "qotin", "qhoin", "qbmin", "qmsin", "qtrin",
        "qlgin", "inqlgpf", "inqlghp", "qetinpf", "qprinpf", "qprolenerf", "qbuinpf", "qetin", "qprin", "qh2inpf", "qh2in",
        "byprdh2in", "qelinp", "qelins", "qelinm"]
TOL = 1e-4

pytestmark = pytest.mark.skipif(not oracle_state.available("wx_out", 38, "ind"), reason="oracle state not dumped")


def rel(a, b):
    a, b = np.asarray(a, dtype=np.float64), np.asarray(b, dtype=np.float64)
    return float((np.abs(a - b) / np.maximum(np.abs(b), 1e-3)).max())


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
def test_wexog(y):
    if not oracle_state.available("wx_out", y, "ind"):
        pytest.skip("not dumped")
    before = oracle_state.load("wx_in", y, "ind")
    after = oracle_state.load("wx_out", y, "ind")
    s = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in before.items()}
    wexog(s)
    iy = int(s["iyr"]) - 1989
    bad = {}
    for n in QOUT:
        e = rel(s[n].a[:, iy - s[n].lb[1]], after[n].a[:, iy - after[n].lb[1]])
        if e > TOL:
            bad[n] = e
    for n in ("bf", "rbf"):
        e = rel(s[n][iy], after[n][iy]) if False else rel(s[n].a[iy - s[n].lb[0]], after[n].a[iy - after[n].lb[0]])
        if e > TOL:
            bad[n] = e
    assert not bad, bad
