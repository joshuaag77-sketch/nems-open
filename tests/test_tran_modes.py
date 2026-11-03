"""TRAIL and TMISC ports vs the transportation oracle, with their saved local arrays."""

import pytest

from nems_open.transportation.misc_modes import tmisc, trail
from tran_harness import YEARS, needs, run

PORTS = {
    "trail": (trail, ["rail_fuel_shr", "lng_locom_inccost", "adoptlng"]),
    "tmisc": (tmisc, ["hyway", "ftvmt"]),
}


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("tag", list(PORTS))
def test_port(tag, y):
    if needs(tag).args[0]:
        pytest.skip("transportation oracle state not dumped")
    port, carry = PORTS[tag]
    assert run(port, tag, y, carry=carry) == {}
