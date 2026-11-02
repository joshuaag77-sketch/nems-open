"""Light-duty routine ports vs the transportation oracle, one test per routine and year."""

import pytest

from nems_open.transportation.fleet import tfltstks
from nems_open.transportation.small import tcurb, tfltvmts, tmpgag, treg
from nems_open.transportation.stock import tsmod
from nems_open.transportation.stock_mpg import tmpgstk
from tran_harness import YEARS, needs, run

PORTS = {"treg": treg, "tfltstks": tfltstks, "tfltvmts": tfltvmts, "tsmod": tsmod, "tmpgstk": tmpgstk,
         "tcurb": tcurb, "tmpgag": tmpgag}


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("tag", list(PORTS))
def test_port(tag, y):
    if needs(tag).args[0]:
        pytest.skip("transportation oracle state not dumped")
    assert run(PORTS[tag], tag, y) == {}
