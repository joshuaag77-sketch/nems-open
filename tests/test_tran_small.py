"""TREG, TFLTVMTS, TCURB and TMPGAG ports vs the transportation oracle."""

import pytest

from nems_open.transportation.small import tcurb, tfltvmts, tmpgag, treg
from tran_harness import YEARS, needs, run

PORTS = {"treg": treg, "tfltvmts": tfltvmts, "tcurb": tcurb, "tmpgag": tmpgag}


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("tag", list(PORTS))
def test_small(tag, y):
    if needs(tag).args[0]:
        pytest.skip("transportation oracle state not dumped")
    assert run(PORTS[tag], tag, y) == {}


from nems_open.transportation.fleet import tfltstks  # noqa: E402
PORTS["tfltstks"] = tfltstks
