"""RHTRADD and RHTRCON ports vs the residential oracle's state.

RHTRCON needs two things the oracle dumps do not hold, so the test rebuilds them:
- PELRSOUT(region, year, end use 1), the electricity price by end use. Out of the
  RHTRCON dump of a year, PRICES(4,r,year) is PELRSOUT times the deflator, so the
  price of every dumped year is exact. Other years fall back on the PRICES value the
  last routine of that year left, which is another end use's price and differs
  from end use 1 after 2024. Exact (all arrays checked) for 2021, 2022, 2027; for the
  other years the arrays that read an unknown year's electricity price are left out.
- RHTRCON's SAVEd locals EFANUEC and NFANUEC of earlier years. NFANUEC is recomputed
  from EXSQFTADJ. EFANUEC was fixed on iteration 1 from that iteration's EXSQFTADJ,
  which the iteration-2 dumps only hold for the dumped years (the "hta_in" dump).
  Other years use the final EXSQFTADJ, which is off by up to 1e-3 relative; the fan
  arrays of those years are left out.
"""

import numpy as np
import pytest

from resd_oracle import YEARS, assert_matches, before_after, rel_err, skip_unless_dumped
from nems_open import oracle_state
from nems_open.fortran_array import FArray
from nems_open.residential.heating import _carried, rhtradd, rhtrcon

# text arrays (equipment maturity, class names) are inputs; the shared check cannot compare them
TEXT = ("rtmature", "rtclname")

LATER = [y for y in YEARS if y > 31]  # yearly routines start the year after RECS
DUMPED = [y for y in LATER if oracle_state.available("htc_out", y, "resd")]
ELECTRIC_KNOWN = (32, 33, 38)  # years whose PELRSOUT inputs are fully known
FAN_KNOWN = (32, 33)           # years whose earlier EFANUEC values are fully known


@skip_unless_dumped("hta")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rhtradd(y):
    state, after = before_after("hta", y)
    rhtradd(state)
    assert_matches(state, after, tol=1e-6, skip=TEXT)


def rebuild_inputs(state, after, y):
    """Seed RHTRCON's carried locals and PELRSOUT for dump year y (NEMS index)."""
    Y = 1989 + y
    c = _carried(state)
    for yy in range(2020, 2051):
        c["faneff"][yy] = 1.0   # FANEFF is 1.0 in every year
        c["nfaneff"][yy] = 0.75  # 2019 furnace fan standard
    iteration1 = {yy: oracle_state.load("hta_in", yy - 1989, "resd")["exsqftadj"]
                  for yy in range(2021, Y + 1) if oracle_state.available("hta_in", yy - 1989, "resd")}
    for yy in range(2021, Y + 1):
        ex1 = iteration1.get(yy, state["exsqftadj"])
        for r in range(1, 10):
            for b in range(1, 4):
                c["efanuec"][yy, r, b] = state["fanuec"][r, b] * c["faneff"][yy] * ex1[yy, b, r, 5]
                c["nfanuec"][yy, r, b] = state["fanuec"][r, b] * c["nfaneff"][yy] * state["exsqftadj"][yy, b, r, 5]
    gdp = state["mc_jpgdp"]
    infl = gdp[int(state["rtekdollaryr"]) - 1990 + 1] / gdp[-2]
    pel = FArray.zeros([(1, 11), (1, 61), (1, 10)])
    for r in range(1, 10):
        for yy in range(1, 62):
            pel[r, yy, 1] = state["prices"][4, r, 1989 + yy] / infl
    for yd in DUMPED:
        out = oracle_state.load("htc_out", yd, "resd")
        for r in range(1, 10):
            pel[r, yd, 1] = out["prices"][4, r, 1989 + yd] / infl
    state["pelrsout"] = pel


# Arrays that read the electricity price of a year we cannot rebuild, or EFANUEC of
# an earlier year we cannot rebuild. Removed from the comparison for the other years.
ELECTRIC = {"ehshell": (slice(None), 4), "ecshell": None, "htrcon": (slice(None), 2),
            "htrconwt": (slice(None), 2), "htrconin": (slice(None), 2)}
FAN = ("fancon", "fanconwt", "faneqcn", "fanconin")
ELECTRIC_CLASSES = (1, 2, 9)


def compare(state, after, electric_known, fan_known):
    worst = {}
    for k, v in after.items():
        if k in TEXT or not isinstance(v, FArray):
            continue
        mine, eia = state[k].a.astype(np.float64), v.a.astype(np.float64)
        if k in FAN and not fan_known:
            continue
        if not electric_known:
            if k == "ecshell":
                continue
            mine, eia = mine.copy(), eia.copy()
            if k == "ehshell":
                mine[:, 3], eia[:, 3] = 0, 0                    # fuel 4 (electricity)
            elif k in ("htrcon", "htrconwt", "htrconin"):
                mine[:, 1], eia[:, 1] = 0, 0                    # consumption fuel 2 (electricity)
            elif k == "eqceqcn":
                for cl in ELECTRIC_CLASSES:
                    mine[:, cl - 1], eia[:, cl - 1] = 0, 0
        worst[k] = rel_err(mine, eia)
    return worst


@skip_unless_dumped("htc")
@pytest.mark.parametrize("y", DUMPED, ids=lambda y: str(1989 + y))
def test_rhtrcon(y):
    state, after = before_after("htc", y)
    rebuild_inputs(state, after, y)
    rhtrcon(state)
    worst = compare(state, after, y in ELECTRIC_KNOWN, y in FAN_KNOWN)
    bad = {k: e for k, e in worst.items() if e >= 1e-6}
    assert not bad, f"over 1e-6: {bad}"
