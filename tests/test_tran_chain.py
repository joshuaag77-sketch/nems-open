"""Whole TRAN for a year, in Python, from the state at the top of the year.

The routines run back to back on one state (no reset from the oracle between them),
and after each one every array in its oracle dump must match.
"""

import pytest

from nems_open.transportation import tran
from tran_harness import YEARS, needs

pytestmark = needs("tran_tail")

# The same rule as each routine's own test: 0.1% where last-bit exp/pow differences grow.
LOOSE = {"tmpgnew", "tranfrt", "tranair"}


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
def test_tran_year(y):
    s, carry = tran.start_from_dump(y)
    worst = tran.tran(s, carry, check=y)
    assert "tran_tail" in worst
    bad = {tag: w for tag, w in worst.items() if w[0] > (1e-3 if tag in LOOSE else 1e-4)}
    assert bad == {}
