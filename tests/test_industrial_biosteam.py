"""Biomass steam in the industrial year loop does not depend on how many times the coupled loop calls IND.

ind.f (CALSTOT, lines 8419-8421) grows BIOSTEAMLAG by output growth on every ISEAM call, so biomass steam compounds
once per call. EIA's run calls ISEAM three times a year (CURITR 1, 2 and the FCRL pass); the industrial oracle runs
two. The coupled loop calls it up to 21 times, which grew industrial biomass (QBMIN) to 2.85 quads in 2050 against
EIA's 1.56. See docs/industrial_biomass_steam.md and docs/per_call_state_audit.md."""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.converge import EIA_CALLS
from nems_open.industrial.standin import Reference, make_standin
from nems_open.industrial.year import run_year, start_state

pytestmark = pytest.mark.skipif(not oracle_state.available("ys_in", 51, "ind"), reason="oracle state not dumped")
QOUT = ("qbmin", "qtrin", "qngin", "qelin", "qclin", "qdsin")


@pytest.fixture(scope="module")
def standin():
    return make_standin(Reference.load())


def _col(s, name, y):
    return s[name].a[:, y - s[name].lb[1]].astype(np.float64)


def _year(y, iterations, standin):
    s, bufs = start_state(oracle_state.load("ys_in", y, "ind"))
    run_year(s, bufs, iterations, standin)
    return s, bufs


@pytest.mark.parametrize("y", [51, 61], ids=["2040", "2050"])
def test_extra_iterations_do_not_compound_biomass_steam(y, standin):
    s2, b2 = _year(y, EIA_CALLS, standin)
    s6, b6 = _year(y, 6, standin)
    for key in b2:
        assert b6[key]["biosteam"] == pytest.approx(float(b2[key]["biosteam"]), rel=1e-6), key
    for n in QOUT:
        assert np.allclose(_col(s6, n, y), _col(s2, n, y), rtol=1e-5, atol=1e-3), n


def test_two_iterations_still_match_the_oracle(standin):
    """The cap is at or above the oracle's two calls, so the oracle's two-iteration year is unchanged."""
    y = 61
    s, _ = _year(y, 2, standin)
    after = oracle_state.load("wx_out", y, "ind", only=["qbmin", "qtrin"])
    for n in ("qbmin", "qtrin"):
        got, want = _col(s, n, y), after[n].a[:, y - after[n].lb[1]].astype(np.float64)
        assert np.allclose(got, want, rtol=1e-4, atol=1e-3), n


@pytest.mark.skipif(not oracle_state.available("ys_in", 38, "ind"), reason="oracle state not dumped")
def test_coupled_first_year_counts_iterations_from_one(standin):
    """The coupled loop's first year calls IND with iterations 2, 3, ... (PortedSectors.solve). IND counts from its
    own first call, so the lag roll runs and the year matches two plain iterations from the same dump."""
    from nems_open.run_demand import IndustrialSector, Inputs
    inputs = Inputs()
    sec = IndustrialSector("ported")
    st = sec.start(2027, inputs)
    for itr in (2, 3):
        sec.iteration(st, 2027, itr, inputs)
    s, _ = _year(38, 2, standin)
    for n in ("qbmin", "qtrin", "qngin"):
        assert np.allclose(_col(st.s, n, 38), _col(s, n, 38), rtol=1e-5, atol=1e-3), n
