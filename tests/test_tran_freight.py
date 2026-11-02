"""Freight truck ports (tranfrt.f) vs the transportation oracle, stretch by stretch.

Dump points inside TRANFRT and TRUCK_NEW are before-only (hooks_tran.py ONLY_IN), so
a stretch runs from one point's "_in" to the next one's. Points inside TRUCK_NEW's
GHG retry loop are taken on the first try.
"""

import pytest

from nems_open import oracle_state
from nems_open.transportation import frt_cost, frt_tech
from tran_harness import YEARS, needs, run

pytestmark = needs("frt_tech")


def _carry_techpen(y):
    from tran_harness import _blank_from
    out = oracle_state.load("tranfrt_out", y, run="run_tran")
    return {"techpenyr_p2": _blank_from(out["p_techpenyr_p2"], y)}


STRETCHES = {
    "techadopt": (frt_tech.truck_techadopt, "frt_tech_in", "frt_inc_in", _carry_techpen),
    "inccost": (frt_cost.truck_inccost, "frt_inc_in", "frt_choice_in", None),
}


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("name", list(STRETCHES))
def test_stretch(name, y):
    port, start, end, carry = STRETCHES[name]
    if not (oracle_state.available(start, y, run="run_tran") and oracle_state.available(end, y, run="run_tran")):
        pytest.skip(f"{start} or {end} not reached this year (TRUCK_INCCOST and TRUCK_CHOICE run after 2024)")
    kwargs = {"carry": carry(y)} if carry else {}
    assert run(port, "tranfrt", y, start=start, end=end, **kwargs) == {}
