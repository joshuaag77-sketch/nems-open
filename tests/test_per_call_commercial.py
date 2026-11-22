"""Commercial gives the same year however many times the coupled loop calls it, and keeps EIA's PITC reset.

comm.f 5607: on a year's first call ifwd restarts from last year's shift; on later calls the shift ratchets with the
previous call's leftover, in EIA too, so it is held at EIA's third call. COMReport (EIA: the FCRL pass of the last
year) runs once after the year's last call. See docs/per_call_state_audit.md."""

import numpy as np
import pytest

from nems_open.commercial.technology_choice import Carry, pitc_shift
from nems_open.converge import EIA_CALLS
from nems_open.run_demand import CommercialSector, Inputs

f32 = np.float32
YEAR = 2030


def _carry():
    return Carry(iforward=[-1, -2, 0], ifwd=-4, ifmax=-5, ilaststeoyr=2025, elasbaseyr=29)


def test_first_call_restarts_from_last_years_shift():
    c = _carry()
    pd3 = [f32(1.15), f32(1.25), f32(0.9)]   # price indexes: shifts of -1, -2, +1 years before the floor
    pitc_shift(c, pd3, 1)
    assert c.iforward == [-1, -2, 0]
    c = _carry()
    pitc_shift(c, pd3, 2)                   # a later call starts from the leftover ifwd = -4
    assert c.iforward == [-4, -4, -4]


@pytest.mark.slow
def test_six_calls_give_eias_three():
    """From EIA's input files (about 4 s a year from 2019), so no oracle dump is needed."""
    inputs = Inputs()
    sec = CommercialSector(from_files=True)
    c = sec.start(YEAR, inputs)          # has not run YEAR yet: calls 1, 2, 3 are EIA's
    for itr in range(1, EIA_CALLS + 1):
        sec.iteration(c, YEAR, itr, inputs)
    three = {k: np.array(v.a, dtype=np.float64) for k, v in sec.quantities(c).items()}
    pitc = (list(c.carry.iforward), c.carry.ifwd, c.carry.keq_ifwd)
    for itr in range(EIA_CALLS + 1, 7):
        sec.iteration(c, YEAR, itr, inputs)
    for k, v in sec.quantities(c).items():
        assert np.allclose(np.array(v.a, dtype=np.float64), three[k], rtol=1e-6, atol=1e-6), k
    assert (list(c.carry.iforward), c.carry.ifwd, c.carry.keq_ifwd) == pitc


def test_report_runs_once_after_the_last_call(monkeypatch):
    from nems_open.commercial import comm
    calls = []
    c = comm.Commercial.__new__(comm.Commercial)
    monkeypatch.setattr(comm.Commercial, "report", lambda self: calls.append(1))
    c.end_year(comm.LAST_YEAR - 1)
    c.end_year(comm.LAST_YEAR)
    assert calls == [1]
