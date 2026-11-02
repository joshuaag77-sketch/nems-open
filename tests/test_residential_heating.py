"""RHTRADD and RHTRCON ports vs the residential oracle's state.

RHTRCON's SAVEd locals EFANUEC and NFANUEC come from the "htc_pre" dump.
"""

import pytest

from resd_oracle import YEARS, assert_matches, before_after, skip_unless_dumped
from nems_open import oracle_state
from nems_open.residential.heating import _carried, rhtradd, rhtrcon

# text arrays (equipment maturity, class names) are inputs; the shared check cannot compare them
TEXT = ("rtmature", "rtclname")

LATER = [y for y in YEARS if y > 31]  # yearly routines start the year after RECS


@skip_unless_dumped("hta")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rhtradd(y):
    state, after = before_after("hta", y)
    rhtradd(state)
    assert_matches(state, after, tol=1e-6, skip=TEXT)


@skip_unless_dumped("htc")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rhtrcon(y):
    state, after = before_after("htc", y)
    pre = oracle_state.load("htc_pre", y, "resd")
    c = _carried(state)
    for yy in range(2020, 2051):
        c["faneff"][yy] = 1.0   # FANEFF is 1.0 in every year
        c["nfaneff"][yy] = 0.75  # 2019 furnace fan standard
    c["efanuec"] = pre["efanuec"].copy()
    c["nfanuec"] = pre["nfanuec"].copy()
    rhtrcon(state)
    state["efanuec"], state["nfanuec"] = c["efanuec"], c["nfanuec"]  # carried values compared too
    assert_matches(state, after, tol=1e-6, skip=TEXT)
