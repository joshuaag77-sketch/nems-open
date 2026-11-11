import numpy as np
import pytest

from nems_open.macro import frbus_core

pytestmark = pytest.mark.skipif(not frbus_core.available(), reason="pyfrbus not downloaded")


@pytest.fixture(scope="module")
def econ():
    return frbus_core.Economy()


def test_reference_follows_eia_gdp_growth(econ):
    a = econ.annual(econ.reference, "xgdp")
    eia = econ.eia_gdp.loc[2026:2050]
    rel = (a / a.loc[2026]) / (eia / eia.loc[2026])
    assert np.abs(rel - 1).max() < 0.003


def test_reference_unemployment_stays_at_baseline(econ):
    lur = econ.annual(econ.reference, "lur")
    assert 3.5 < lur.min() and lur.max() < 5.5


def test_reference_energy_path_is_a_fixed_point(econ):
    r = econ.run(1.0)
    assert np.abs(r.loc[econ.start : econ.end, "xgdp"] - econ.reference.loc[econ.start : econ.end, "xgdp"]).max() < 1e-3


def test_oil_shock_lowers_output_and_raises_prices(econ):
    base, hi = econ.reference, econ.run(1.5)
    assert np.isfinite(hi.loc[econ.start : econ.end].values).all()
    gdp = econ.annual(hi, "xgdp") - econ.annual(base, "xgdp")
    assert gdp.loc[2027:2035].max() < 0
    assert (econ.annual(hi, "pcpi") - econ.annual(base, "pcpi")).loc[2027] > 0
