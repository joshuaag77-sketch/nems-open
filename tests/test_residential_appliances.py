"""Clothes dryer, refrigerator and freezer ports vs the residential oracle's state.

The dumps do not hold PELRSOUT. Every TEC and CON routine starts by mapping it into
PRICES(4, r, CurCalYr) for its own end use (EUPR), and the dumped "in" prices carry
the previous end use's value, so the port cannot rebuild that line. Until PELRSOUT
is dumped these tests copy PRICES(4, 1:9, CurCalYr) from the "out" dump into the
starting state. That is the only thing taken from "out"; the rest of the routine is
computed from "in".
"""

import numpy as np
import pytest

from resd_oracle import YEARS, assert_matches, before_after
from nems_open import oracle_state
from nems_open.fortran_array import FArray
from nems_open.residential import appliances as ap

LATER = [y for y in YEARS if y > 31]  # yearly routines have no 2020 dump
TOL = 1e-6


def year_id(y):
    return str(1989 + y)


def check(state, after, skip=()):
    """assert_matches, minus the text tables (RTMATURE...), which no routine here writes."""
    text = tuple(k for k, v in after.items() if hasattr(v, "a") and v.a.dtype.kind in "SU")
    return assert_matches(state, after, tol=TOL, skip=tuple(skip) + text)


def seed_electricity_price(state, after):
    """Stand in for PRICES(4,R,CurCalYr) = PELRSOUT(R,CurIYr,EUPR) * deflator."""
    if "pelrsout" not in state:
        y = int(state["curcalyr"])
        state["prices"][4, 1:9, y] = after["prices"][4, 1:9, y]


ROUTINES = [
    ("dyt", ap.rdrytec, True), ("dya", ap.rdryadd, False),
    ("rft", ap.rreftec, True), ("rfa", ap.rrefadd, False), ("rfc", ap.rrefcon, True),
    ("fzt", ap.rfrztec, True), ("fza", ap.rfrzadd, False), ("fzc", ap.rfrzcon, True),
]


@pytest.mark.parametrize("y", LATER, ids=year_id)
@pytest.mark.parametrize("tag,fn,maps_price", ROUTINES, ids=[r[0] for r in ROUTINES])
def test_routine(tag, fn, maps_price, y):
    if not oracle_state.available(f"{tag}_out", y, "resd"):
        pytest.skip(f"residential oracle state for {tag} not dumped")
    state, after = before_after(tag, y)
    if maps_price:
        seed_electricity_price(state, after)
    fn(state)
    check(state, after)


@pytest.mark.parametrize("y", LATER, ids=year_id)
def test_rdrycon(y):
    """RDRYCON also needs PELRSOUT inside RSELAST for electric dryers, and that
    cannot be seeded from "out". With a stand-in price response of 1, everything
    that does not carry the electric price response must match; DRYCON, DRYCONWT
    and EQCEQCN (which do) are checked only once PELRSOUT is dumped."""
    if not oracle_state.available("dyc_out", y, "resd"):
        pytest.skip("residential oracle state for dyc not dumped")
    state, after = before_after("dyc", y)
    seed_electricity_price(state, after)
    full = "pelrsout" in state
    if not full:
        state["pelrsout"] = FArray(np.ones((9, 61, 7), dtype=np.float32), (1, 1, 1))
    ap.rdrycon(state)
    check(state, after, () if full else ("drycon", "dryconwt", "eqceqcn", "prices"))
