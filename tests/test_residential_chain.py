"""The whole residential port, every routine chained in RESD's order.

One year: start from the oracle's state at the top of a projection year ("yb_in"
plus the carried locals in "<tag>_pre"), run every routine, and the module's
outputs (NEMSCN's QBLK quantities, RESDRP's reports) must match the oracle.

All years: start once, in 2021, and let Python run alone to 2050 with NEMS's two
iterations a year. Results must match the oracle's final state (the port rule),
and EIA's restart file as closely as the oracle itself does (tests/test_oracle_residential.py).
About 2.5 minutes.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.fortran_array import FArray
from nems_open.residential import resd
from nems_open.snapshot import Snapshot
from resd_oracle import YEARS, rel_err

pytestmark = pytest.mark.skipif(not oracle_state.available("yb_in", 32, "resd"), reason="oracle not dumped")

LATER = [y for y in YEARS if y > 31]
FUELS = ["qelrs", "qngrs", "qdsrs", "qlgrs", "qbmrs", "qpvrs"]
REPORT_BLOCKS = ("RESDREP", "RSCON", "RSEFF")


def start_state(y):
    load = lambda tag: oracle_state.load(tag, y, "resd")
    s = {k: (v.copy() if isinstance(v, FArray) else v) for k, v in load("yb_in").items()}
    for k, v in load("pr_in").items():  # RDPR's price inputs, for later years
        s.setdefault(k, v.copy() if isinstance(v, FArray) else v)
    for d in oracle_state.state_dir("resd").glob("*_pre"):
        if oracle_state.available(d.name, y, "resd"):
            for k, v in load(d.name).items():
                s[k] = v.copy() if isinstance(v, FArray) else v
    resd.resume_from_dump(s)
    return s


def rel(mine, ref):
    mine, ref = np.asarray(mine, np.float64), np.asarray(ref, np.float64)
    return float((np.abs(mine - ref) / np.maximum(np.abs(ref), 1e-6 * max(np.abs(ref).max(), 1e-30))).max())


@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_one_year(y):
    s = start_state(y)
    resd.after_prices(s)
    for tag in ("ne_out", "re_out"):
        for k, v in oracle_state.load(tag, y, "resd").items():
            if isinstance(v, FArray) and v.a.dtype.kind == "f":
                assert rel_err(s[k].a, v.a) < 1e-6, (tag, k)


@pytest.fixture(scope="module")
def full_run():
    s = start_state(32)
    resd.after_prices(s)  # the rest of 2021's final iteration
    resd.run(s, 2022, 2050)
    return s, oracle_state.load("final", 61, "resd")


def test_full_run_fuel_use(full_run):
    s, fin = full_run
    snap = Snapshot()
    for q in FUELS:  # regions 1-9, 2021-2050
        mine, oracle, eia = s[q].a[:9, 31:], fin[q].a[:9, 31:], snap[f"QBLK/{q}"][:9, 31:]
        assert rel(mine, oracle) < 1e-6, q
        floor = np.maximum(np.abs(eia), 1e-3 * np.abs(eia).max())
        assert (np.abs(mine - eia) / floor).max() < 5e-3, q


def test_full_run_reports(full_run):
    s, fin = full_run
    names = {k.split("/")[1] for k in Snapshot().names() if k.split("/")[0] in REPORT_BLOCKS}
    worst = {}
    for k in names:
        ref = fin[k].a
        worst[k] = rel(s[k].a[31:], ref[31:]) if ref.shape[0] == 61 else rel(s[k].a, ref)
    # Float rounding compounds over 30 years in heating (RSCON/htrcon about 4e-5).
    assert max(worst.values()) < 1e-4, sorted(worst.items(), key=lambda kv: -kv[1])[:5]


def test_full_run_reports_vs_eia(full_run):
    """RESDREP's headline reports against EIA's restart file, 2021-2050: within
    the oracle's own float-rounding drift."""
    s, _ = full_run
    snap = Snapshot()
    for k in ("rshouses", "rseh", "rsnh", "sqftavg", "rshtrcon", "rscoolcn", "rsh2ocon", "rsltcon",
              "rsapcon", "rsrefcon", "rshtrs", "rscoolers", "rsnefht", "rseefht", "hshell1", "cshell1"):
        eia = snap[f"RESDREP/{k}"][31:]
        assert rel(s[k].a[31:], eia) < 1e-2, k
