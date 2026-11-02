"""Clothes dryer, refrigerator and freezer ports vs the residential oracle's state.
"""

import pytest

from resd_oracle import YEARS, assert_matches, before_after
from nems_open import oracle_state
from nems_open.residential import appliances as ap

LATER = [y for y in YEARS if y > 31]  # yearly routines have no 2020 dump
TOL = 1e-6


def year_id(y):
    return str(1989 + y)


def check(state, after, skip=()):
    """assert_matches, minus the text tables (RTMATURE...), which no routine here writes."""
    text = tuple(k for k, v in after.items() if hasattr(v, "a") and v.a.dtype.kind in "SU")
    return assert_matches(state, after, tol=TOL, skip=tuple(skip) + text)


ROUTINES = [
    ("dyt", ap.rdrytec), ("dya", ap.rdryadd),
    ("rft", ap.rreftec), ("rfa", ap.rrefadd), ("rfc", ap.rrefcon), ("dyc", ap.rdrycon),
    ("fzt", ap.rfrztec), ("fza", ap.rfrzadd), ("fzc", ap.rfrzcon),
]


@pytest.mark.parametrize("y", LATER, ids=year_id)
@pytest.mark.parametrize("tag,fn", ROUTINES, ids=[r[0] for r in ROUTINES])
def test_routine(tag, fn, y):
    if not oracle_state.available(f"{tag}_out", y, "resd"):
        pytest.skip(f"residential oracle state for {tag} not dumped")
    state, after = before_after(tag, y)
    fn(state)
    check(state, after)
