"""TMAC port vs the transportation oracle."""

import pytest

from nems_open.transportation.tmac import tmac
from tran_harness import YEARS, needs, run

pytestmark = needs("tmac")


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
def test_tmac(y):
    assert run(tmac, "tmac", y) == {}
