"""Transportation gives the same year however many times the coupled loop calls it.

EIA calls TRAN three times a year. Three pieces of TRAN's state change on every call in EIA's code too: the heavy-duty
GHG credit bank (spent again on each call), TRUCK_PBK's curve history (a curve started on any call stays started),
FEM's OLD_PMAX and the air load-factor sums LFDOMAVG/LFINTAVG (added to on every call). run_demand.TransportationSector
holds TRAN's whole state at what EIA's third call starts from (converge.EiaCalls), so calls 4 to 21 repeat call 3 on
the loop's latest inputs.
See docs/per_call_state_audit.md."""

import numpy as np
import pytest

from nems_open.converge import EIA_CALLS
from nems_open.run_demand import SECTOR_QUANTITIES, Inputs, TransportationSector, tran_state

# The first dumped year from 2027; with no dump, TRAN starts from EIA's files (about 30 min to 2027).
YEAR = next((y for y in range(2027, 2051) if TransportationSector.dumped(y)), 2027)
pytestmark = pytest.mark.slow


def _snap(t):
    s = t["s"]
    out = {k: np.array(s[k].a if hasattr(s[k], "a") else s[k], dtype=np.float64)
           for k in SECTOR_QUANTITIES["tr"] if k in s}
    held = tran_state(s, t["carry"])
    for k in ("carry/tranfrt/ghgbank", "carry/tranfrt/start_curve", "s/old_pmax", "s/a_lfdomavg", "s/a_lfintavg"):
        out[k] = np.array(held[k], dtype=np.float64)
    return out


def test_six_calls_give_eias_three():
    inputs = Inputs()
    sec = TransportationSector()
    t = sec.start(YEAR, inputs)
    for itr in range(1, EIA_CALLS + 1):
        sec.iteration(t, YEAR, itr, inputs)
    three = _snap(t)
    for itr in range(EIA_CALLS + 1, 7):
        sec.iteration(t, YEAR, itr, inputs)
    six = _snap(t)
    for k, v in three.items():
        assert np.allclose(six[k], v, rtol=1e-6, atol=1e-6, equal_nan=True), k
