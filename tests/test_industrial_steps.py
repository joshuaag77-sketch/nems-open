"""CALBYPROD, CALPROD, CALPATOT and CALCSC ports vs the industrial oracle.

Each tag is one call for one industry and region (CALCSC: one fuel and step too). The
port runs on the state dumped before the call and is compared with the state after it.
Skipped until the oracle has run.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.industrial.byproduct import calbyprod
from nems_open.industrial.process_totals import calpatot
from nems_open.industrial.production import calprod
from nems_open.industrial.tech_progress import calcsc

YEARS = [36, 37, 38, 41, 51, 61]
COMMON = ["inddir", "indreg", "iyr", "curiyr", "curcalyr", "ibyr", "ibyr2", "mpastp", "mainfuels", "idval", "techstrtyr",
          "frztech", "hitech", "prcxyr", "ifmax", "ifloc", "steolastyr"]
BYP = ["ifbyp", "iflocby", "bypcsc", "bypint", "bypintlag", "bypqty", "prodlag", "prodcur", "bypbscm", "bypbsci",
       "bypbscr", "bypadibyr", "bscibyr", "enpintlag"]
PRO = ["prodlag", "prodcur", "idlcap", "idlcaplag", "prodretr", "retrate", "iretire", "phdrat", "prodvx", "prodx", "prodflow",
       "ntmax", "ipastp", "foodship", "chemship", "enpintlag"]
PAT = ["prodcur", "enpint", "enpqty", "enpmqty", "enpiqty", "enprqty", "chemship", "fertilizer_h2", "bushel"]
CSC = ["bcsc", "ijumpcalyr", "itpc", "tpc1", "tpc2", "enpint", "enpintlag", "prodlag", "rei_adj", "rei_adj_lag"]
TOL = 2e-4

pytestmark = pytest.mark.skipif(not oracle_state.available("byp_out", 61, "ind"), reason="oracle state not dumped")


def rel_err(a, b):
    a, b = np.asarray(getattr(a, "a", a), dtype=np.float64), np.asarray(getattr(b, "a", b), dtype=np.float64)
    return float((np.abs(a - b) / np.maximum(np.abs(b), 1e-4)).max())


def states(tag, y, need):
    before = oracle_state.load(f"{tag}_in", y, "ind", only=COMMON + need)
    after = oracle_state.load(f"{tag}_out", y, "ind", only=COMMON + need)
    return {k: (v.copy() if hasattr(v, "copy") else v) for k, v in before.items()}, after


def check(s, after, names):
    for n in names:
        assert rel_err(s[n], after[n]) < TOL, n


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("tag", ["byp", "byp1", "byp7", "byp9", "byp24", "byp3", "byp19"])
def test_calbyprod(tag, y):
    if not oracle_state.available(f"{tag}_out", y, "ind"):
        pytest.skip("not dumped")
    s, after = states(tag, y, BYP)
    calbyprod(s)
    check(s, after, ["bypint", "bypqty", "bypbscm", "bypbsci", "bypbscr", "bypadibyr"])


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("tag", ["pr1", "pr3", "pr6", "pr7", "pr14", "pr24"])
def test_calprod(tag, y):
    if not oracle_state.available(f"{tag}_out", y, "ind"):
        pytest.skip("not dumped")
    s, after = states(tag, y, PRO)
    calprod(s)
    check(s, after, ["prodcur", "idlcap"])


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("tag", ["pt1", "pt7", "pt24", "pt18"])
def test_calpatot(tag, y):
    if not oracle_state.available(f"{tag}_out", y, "ind"):
        pytest.skip("not dumped")
    s, after = states(tag, y, PAT)
    if "bushel" not in s and tag == "pt1":
        pytest.skip("BUSHEL not in this dump")
    calpatot(s)
    check(s, after, ["enpqty", "enpmqty", "enpiqty", "enprqty"])


CSC_TAGS = [f"cs{i}_{f}{st}" for i in (7, 1, 9, 24, 18) for f, st in ((1, 1), (2, 1), (1, 2), (3, 2))]


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("tag", CSC_TAGS)
def test_calcsc(tag, y):
    if not oracle_state.available(f"{tag}_out", y, "ind"):
        pytest.skip("not dumped")
    s, after = states(tag, y, CSC)
    f, st = map(int, tag.split("_")[1])
    calcsc(s, f, st)
    check(s, after, ["enpint"])
