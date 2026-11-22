"""Residential gives the same year however many times the coupled loop calls it.

The audit found no residential state that changes on every call (docs/per_call_state_audit.md): each call rebuilds
the year from earlier years' values and this call's prices. NHTSHR and RESDRP2 (EIA: the last year's FCRL pass) now
run once after the year's last call instead of on iteration 2."""

import numpy as np
import pytest

from nems_open.converge import EIA_CALLS
from nems_open.run_demand import Inputs, ResidentialSector

YEAR = 2030


@pytest.mark.skipif(not ResidentialSector.dumped(YEAR), reason="residential oracle dump missing")
def test_six_calls_give_eias_three():
    inputs = Inputs()
    sec = ResidentialSector()
    s = sec.start(YEAR, inputs)
    for itr in range(2, EIA_CALLS + 1):     # a dump is the top of the year's final oracle call (2)
        sec.iteration(s, YEAR, itr, inputs)
    three = {k: np.array(v.a, dtype=np.float64) for k, v in sec.quantities(s).items()}
    for itr in range(EIA_CALLS + 1, 7):
        sec.iteration(s, YEAR, itr, inputs)
    for k, v in sec.quantities(s).items():
        assert np.allclose(np.array(v.a, dtype=np.float64), three[k], rtol=1e-6, atol=1e-6), k


def test_reports_run_once_after_the_last_call(monkeypatch):
    from nems_open.residential import reports, resd
    calls = []
    monkeypatch.setattr(reports, "nhtshr", lambda s: calls.append("nhtshr"))
    monkeypatch.setattr(reports, "resdrp2", lambda s: calls.append("resdrp2"))
    sec = ResidentialSector()
    sec.end_year({}, resd.LASTYEAR - 1)
    sec.end_year({}, resd.LASTYEAR)
    assert calls == ["nhtshr", "resdrp2"]
