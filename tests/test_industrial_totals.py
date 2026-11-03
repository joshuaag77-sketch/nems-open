"""INDTOTAL port vs the industrial oracle's internal state.

Feeds the port the state just before EIA's routine ran (<tag>_in) and compares what
it writes with what the routine left (<tag>_out). The oracle dumps one industry and
region per tag: the last of the year (itot: 24, 4) plus agriculture, food, paper,
steel and electrical equipment. Skipped until the oracle has run.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.industrial.totals import indtotal

YEARS = [36, 37, 38, 41, 51, 61]  # 2025 on
TAGS = ["itot", "itot1", "itot7", "itot8", "itot12", "itot16"]
NEED = ["inddir", "indreg", "indnum", "curiyr", "mainfuels", "enpmqty", "enpiqty", "enprqty", "enbqty", "ensqty",
        "bypbsci", "bypbscr", "bypbscm", "cfelq", "elown", "elsale", "refcon", "elownx", "elsalex", "xelin",
        "xelinshr", "qtymain", "qtyintr", "qtyrenw"]
OUT = ["qtymain", "qtyintr", "qtyrenw", "elown", "elsale", "xelin", "xelinshr"]
TOL = 1e-4

pytestmark = pytest.mark.skipif(not oracle_state.available("itot_out", 61, "ind"), reason="oracle state not dumped")

_cache = {}


def run(tag, y):
    if (tag, y) not in _cache:
        before = oracle_state.load(f"{tag}_in", y, "ind", only=NEED)
        after = oracle_state.load(f"{tag}_out", y, "ind", only=NEED)
        s = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in before.items()}
        indtotal(s, int(s["inddir"]), int(s["indreg"]), int(s["indnum"]))
        _cache[(tag, y)] = s, after
    return _cache[(tag, y)]


def rel_err(mine, eia):
    mine, eia = np.asarray(mine, dtype=np.float64), np.asarray(eia, dtype=np.float64)
    return float((np.abs(mine - eia) / np.maximum(np.abs(eia), 1e-6)).max())


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("tag", TAGS)
@pytest.mark.parametrize("name", OUT)
def test_indtotal(tag, y, name):
    if not oracle_state.available(f"{tag}_out", y, "ind"):
        pytest.skip(f"{tag} not dumped")
    s, after = run(tag, y)
    mine, eia = s[name], after[name]
    assert rel_err(getattr(mine, "a", mine), getattr(eia, "a", eia)) < TOL
