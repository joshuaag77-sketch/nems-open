"""LTCNS, APCNS, SHTCNS and APPCNS ports vs the residential oracle's state.

LTCNS keeps its purchase history in private SAVEd locals. The oracle dumps the
first-iteration copies (ltrepfutly, ltrepstkly, ltrepconsly) as lt_pre; the final
iteration restores the live arrays from them, so they are the port's input.
"""

import numpy as np
import pytest

from nems_open import oracle_state

from resd_oracle import YEARS, assert_matches, before_after, rel_err, skip_unless_dumped
from nems_open.fortran_array import FArray
from nems_open.paths import REPO_ROOT
from nems_open.residential.lighting_misc import appcns, apcns, ltcns, ltcns_recs_init, shtcns

LATER = [y for y in YEARS if y > 31]


def with_prices(tag, y):
    # the dumps carry the real pelrsout
    return before_after(tag, y)


@skip_unless_dumped("sa")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_appcns(y):
    state, after = before_after("sa", y)
    appcns(state)
    assert_matches(state, after, tol=1e-6)


@skip_unless_dumped("sh")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_shtcns(y):
    state, after = with_prices("sh", y)
    shtcns(state)
    assert_matches(state, after, tol=1e-6)


@skip_unless_dumped("ap")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_apcns(y):
    state, after = with_prices("ap", y)
    apcns(state)
    assert_matches(state, after, tol=1e-6)


def check(state, after, tol=1e-6):
    """assert_matches, plus equality for the text arrays (bulb names, ids) it cannot compare."""
    text = {k for k, v in after.items() if isinstance(v, FArray) and v.a.dtype.kind == "S"}
    for k in text:
        assert (state[k].a == after[k].a).all(), k
    return assert_matches(state, after, tol=tol, skip=text)


def recs_locals(state):
    """LTSTOCKEX and its consumption are fixed by the RECS-year stock, so they can be
    rebuilt for any year by running EIA's first-post-RECS-year block as 2021 would."""
    scratch = {k: (v.copy() if isinstance(v, FArray) else v) for k, v in state.items()}
    scratch["curcalyr"] = np.int32(2021)
    ltcns_recs_init(scratch)
    for k in ("ltstockex", "ltstockexcons"):
        state[k] = scratch[k]


@skip_unless_dumped("lt")
def test_ltcns_2021():
    # 2021 final iteration: purchase history before 2021 is zero, so the SAVEd locals
    # (LTREPFUT, LTREPSTK, LTREPCONS and their first-iteration copies) start at zero.
    state, after = with_prices("lt", 32)
    recs_locals(state)
    ltcns(state)
    worst = check(state, after)
    print({k: round(v, 9) for k, v in worst.items() if v > 0})


@skip_unless_dumped("lt")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_ltcns_full(y):
    state, after = before_after("lt", y)
    recs_locals(state)
    for k, v in oracle_state.load("lt_pre", y, "resd").items():
        state[k] = v.copy()
    ltcns(state)
    worst = check(state, after)
    assert max(worst.values()) < 1e-6, worst
