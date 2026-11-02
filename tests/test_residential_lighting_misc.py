"""LTCNS, APCNS, SHTCNS and APPCNS ports vs the residential oracle's state.

PELRSOUT (electricity price by end use, EQUIVALENCEd over PELSHRS...PELVHRS in
eusprc) is not in the per-routine dumps. It is a constant input the driver loads from
the restart files, so the tests rebuild it from oracle/run_resd/dump/eusprc__pel*.bin.

LTCNS keeps its purchase history in private SAVEd locals the dumps do not hold. For
2021 that history is zero (nothing came before), so 2021 is tested in full. For the
other years the full test is skipped and a partial test checks the arrays that do not
depend on the history. See the report for exactly what is needed.
"""

import numpy as np
import pytest

from resd_oracle import YEARS, assert_matches, before_after, rel_err, skip_unless_dumped
from nems_open.fortran_array import FArray
from nems_open.paths import REPO_ROOT
from nems_open.residential.lighting_misc import appcns, apcns, ltcns, ltcns_recs_init, shtcns

LATER = [y for y in YEARS if y > 31]
DUMP = REPO_ROOT / "oracle" / "run_resd" / "dump"
# COMMON /EUSPRC/ order of the residential end-use prices (PELRSOUT's third index)
PELRS = ["pelshrs", "pelclrs", "pelwhrs", "pelckrs", "pelcdrs", "pelrfrs",
         "pelfzrs", "pelltrs", "pelotrs", "pelh2rs", "pelvhrs"]


def pelrsout():
    cols = [np.fromfile(DUMP / f"eusprc__{n}.bin", dtype=np.float32).reshape((11, 61), order="F") for n in PELRS]
    return FArray(np.stack(cols, axis=2), (1, 1, 1))


def with_prices(tag, y):
    state, after = before_after(tag, y)
    state["pelrsout"] = pelrsout()
    return state, after


def test_pelrsout_is_the_oracle_input():
    # prices(4,d,year) in the dumps is pelrsout(d,year,eu) times the dollar-year ratio
    state, after = with_prices("ap", 32)
    g = state["mc_jpgdp"]
    infl = np.float32(g[int(state["rtekdollaryr"]) - 1990 + 1] / g[-2])
    mine = state["pelrsout"][1:9, 32, 9] * infl
    assert np.allclose(mine, after["prices"].a[3, :9, 2021 - 1990], rtol=1e-6)


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


# Arrays that depend only on this year's inputs, not on the purchase history
NO_HISTORY = ["prices", "ltlcap", "ltlsub", "ltlcapinvest", "cribulb", "watts", "bulbbinlife", "ltneededbyapp",
              "appbulbname"]


@skip_unless_dumped("lt")
@pytest.mark.parametrize("y", LATER[1:], ids=lambda y: str(1989 + y))
def test_ltcns_history_free_arrays(y):
    state, after = with_prices("lt", y)
    recs_locals(state)
    ltcns(state)
    for k in NO_HISTORY:
        if after[k].a.dtype.kind == "S":
            assert (state[k].a == after[k].a).all(), k
        else:
            assert rel_err(state[k].a, after[k].a) < 1e-6, k
    # slot 1 of the investment arrays is new construction only
    for k in ("ltinvest", "ltsubsidy"):
        assert rel_err(state[k].a[..., 0], after[k].a[..., 0]) < 1e-6, k


@pytest.mark.skip(reason="blocked: LTREPFUT/LTREPSTK/LTREPCONS (private SAVEd locals of LTCNS) are not dumped")
@pytest.mark.parametrize("y", LATER[1:], ids=lambda y: str(1989 + y))
def test_ltcns_full(y):
    pass
