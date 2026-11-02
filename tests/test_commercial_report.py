"""COMReport port vs the oracle's internal state.

COMReport runs once, in 2050 on the last iteration. The port is checked on the state it
leaves in COMMREP: the oracle's state just before and after that call. Skipped until the
oracle has run.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.commercial.report import report

pytestmark = pytest.mark.skipif(not oracle_state.available("rp_out", 61), reason="oracle state not dumped")

OUTPUTS = ["cmfinalenduse", "cmnonbldguse", "cmfinalunbenchuse", "cmussurvfloortot", "cmusnewfloortot",
           "cmuscogen", "cmfinalendusecon", "cmsurvfloortot", "cmnewflrspace", "cmusconsumption",
           "cmusavgeff", "cmuspurcheff", "cmusdistserv"]


@pytest.fixture(scope="module")
def run():
    before, after = oracle_state.load("rp_in", 61), oracle_state.load("rp_out", 61)
    inp = dict(before)
    inp["cmfinalunbenchuse"] = after["cmfinalunbenchuse"]  # local to COMReport, dumped after the call
    return report(inp), before, after


@pytest.mark.parametrize("name", OUTPUTS)
def test_report(run, name):
    mine, _, after = run
    eia = after["cmfinalunbenchuse" if name == "cmfinalunbenchuse" else name]
    err = np.abs(mine[name].a.astype(np.float64) - eia.a) / np.maximum(np.abs(eia.a), 1e-6)
    assert err.max() < 1e-6


def test_report_changes_state(run):
    """The national column is really rebuilt: clear it first and the port must restore it."""
    _, before, after = run
    inp = dict(before)
    inp["cmfinalunbenchuse"] = after["cmfinalunbenchuse"].copy()
    for name in ("cmfinalenduse", "cmnonbldguse"):
        inp[name] = before[name].copy()
    inp["cmfinalenduse"][:, 11, 30:61] = 0.0
    inp["cmnonbldguse"][:, 11, 30:37] = 0.0  # EIA rebuilds this one only to the last STEO year
    inp["cmfinalunbenchuse"][:, 11, 30:61] = 0.0
    out = report(inp)
    for name, last in (("cmfinalenduse", 61), ("cmnonbldguse", 37), ("cmfinalunbenchuse", 61)):
        mine, eia = out[name][1:3, 11, 30:last].astype(np.float64), after[name][1:3, 11, 30:last]
        assert (np.abs(mine - eia) / np.maximum(np.abs(eia), 1e-6)).max() < 1e-6, name
