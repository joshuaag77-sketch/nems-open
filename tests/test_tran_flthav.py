"""FLTHAV (taxi automation) port vs the transportation oracle."""

import pytest

from nems_open.transportation.hav import flthav
from tran_harness import YEARS, needs, run

pytestmark = needs("flthav")


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
def test_flthav(y):
    # Before 2025 TRAN does not call FLTHAV (no lidar yet), so 2020 changes nothing.
    assert run(flthav, "flthav", y, may_be_empty=(y < 36)) == {}
