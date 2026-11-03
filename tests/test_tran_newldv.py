"""NEWLDV port vs the transportation oracle."""

import pytest

from nems_open.transportation.newldv import newldv
from tran_harness import YEARS, needs, run

pytestmark = needs("newldv")


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
def test_newldv(y):
    assert run(newldv, "newldv", y) == {}
