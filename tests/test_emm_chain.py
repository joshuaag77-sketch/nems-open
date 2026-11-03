"""EMM's load and pricing in Python (emm/chain.py), run alone from the oracle's
2021 state, against the oracle.

LDSM, the EFD stand-in and EFP run year after year with NEMS's two iterations,
as the oracle runs them. Inputs from EMM parts not ported come from the oracle
(chain.py docstring). To 2030 (about 4 minutes): LDSM matches the oracle's 2030
state; retail electricity prices by sector, census division and EMM region
within 0.5% (worst 0.33%; US within 0.01%). To 2050 (NEMS_RUN_SLOW=1, about 14 minutes):
within 0.75% (worst 0.49%; US within 0.02%). The gap: ECP's yearly build data (BILDIN) stays
at 2021 in the chain, and region 25's books snapshot misses one buffered write.
"""

import os

import numpy as np
import pytest

from emm_oracle import available, rel_err
from nems_open import oracle_state
from nems_open.emm.chain import BOOKS, Chain
from nems_open.snapshot import Snapshot
from test_efp_elefp import finish_snapshot

PRICES = ["pelas", "pelrs", "pelcm", "pelin", "pelasnr", "pelrsnr", "pelcmnr", "pelinnr"]

pytestmark = pytest.mark.skipif(not (available("fp_out", 41) and (BOOKS / "32" / "EMM_EFPR.daf").exists()),
                                reason="EMM oracle dumps or the 2021 books snapshot missing")


def _run(last):
    c = Chain(Snapshot(), 32)
    finish_snapshot(c.books)
    c.iteration(32, 2)            # the rest of 2021: its final iteration
    for y in range(33, last + 1):
        for itr in (1, 2):
            c.iteration(y, itr)
    return c


def _price_err(s, y):
    ref = oracle_state.load("fp_out", y, "emm")
    worst, us = 0.0, 0.0
    for k in PRICES:
        n = 25 if k.endswith("nr") else 9
        mine, o = s[k].a[:n, y - 1], ref[k].a[:n, y - 1]
        worst = max(worst, rel_err(mine, o))
        if n == 9:
            us = max(us, rel_err(s[k].a[10, y - 1], ref[k].a[10, y - 1]))
    return worst, us


@pytest.fixture(scope="module")
def to_2030():
    return _run(41)


def test_ldsm_2030(to_2030):
    ref = oracle_state.load("ld_out", 41, "emm")
    errs = {k: rel_err(to_2030.s[k].a, v.a) for k, v in ref.items()
            if hasattr(v, "a") and v.a.dtype.kind == "f" and k in to_2030.s}
    assert max(errs.values()) < 1e-4, sorted(errs.items(), key=lambda kv: -kv[1])[:5]


def test_prices_2030(to_2030):
    worst, us = _price_err(to_2030.s, 41)
    assert worst < 5e-3 and us < 3e-4, (worst, us)   # measured: worst 0.33%, US 0.018%


@pytest.mark.skipif(os.environ.get("NEMS_RUN_SLOW") != "1", reason="slow: set NEMS_RUN_SLOW=1 (14 minutes)")
def test_prices_2050():
    worst, us = _price_err(_run(61).s, 61)
    assert worst < 7.5e-3 and us < 3e-4, (worst, us)
