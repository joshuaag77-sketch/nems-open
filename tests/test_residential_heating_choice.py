"""RSHVAC and RHTRTEC ports vs the residential oracle's state.

RHTRTEC's HEATSYS is a SAVEd lagged logit that carries from year to year; the oracle
dumps its value at the start of the final iteration (htt_pre) and the port keeps it
in s["heatsys"], so htt_out checks it too.
"""

import pytest

from resd_oracle import YEARS, assert_matches, before_after, skip_unless_dumped
from nems_open import oracle_state
from nems_open.residential.heating_choice import rhtrtec, rshvac

TEXT = ("rtmature",)  # text array: the shared rel_err helper cannot compare bytes; the port never writes it
LATER = [y for y in YEARS if y > 31]  # yearly routines have no 2020 dump


@skip_unless_dumped("hv")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rshvac(y):
    state, after = before_after("hv", y)
    rshvac(state)
    assert_matches(state, after, tol=1e-6, skip=TEXT)


@skip_unless_dumped("htt")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rhtrtec(y):
    state, after = before_after("htt", y)
    state["heatsys"] = oracle_state.load("htt_pre", y, "resd")["heatsys"].copy()
    rhtrtec(state)
    assert_matches(state, after, tol=1e-6, skip=TEXT)
