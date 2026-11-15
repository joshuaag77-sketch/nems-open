"""The gas market (nems_open.ngmm): NGMM's curve, baseline reproduction, response to demand."""
import numpy as np
import pytest

from nems_open.supply_standin.data import FIRST_YEAR, US, available

pytestmark = pytest.mark.skipif(not available("cb2026"), reason="needs the AEO2026 restart files or data/aeo2026 cache")


def test_curve_points_are_ngmm_option_2():
    from nems_open.ngmm import curve
    q, p = curve.points()
    assert np.allclose(q[2:4], [0.97, 1.03]) and np.allclose(p[2:4], [0.94, 1.06])   # centre, elasticity 0.5
    assert p[0] == 0 and np.isclose(q[5] / q[4], 4.0) and np.isclose(p[5] / p[4], 16.0)
    assert np.all(np.diff(q) > 0) and np.all(np.diff(p) > 0)
    x = np.linspace(0.5, 1.5, 11)
    assert np.allclose(curve.quantity(curve.price(x)), x)


def test_baseline_demand_gives_cb2026_prices():
    from nems_open.ngmm import GasMarket, data
    m = GasMarket()
    b = data.load("cb2026")
    out = m.simulate(m.qngas_b)
    j = slice(2027 - FIRST_YEAR, None)
    assert np.allclose(out["wellhead"][j], b["NGTDMREP/ngscrv_p"][j], rtol=1e-9)
    assert np.allclose(out["henry_hub"][j], b["NGTDMREP/oghhprng"][j], rtol=1e-9)
    for k, v in m.prices(m.qngas_b).items():
        assert np.allclose(v, b[k], rtol=1e-9), k


def test_more_demand_raises_price_and_production():
    from nems_open.ngmm import GasMarket
    m = GasMarket()
    base = m.simulate(m.qngas_b)
    high = m.simulate(m.qngas_b * 1.1)
    j = 2050 - FIRST_YEAR
    assert high["henry_hub"][j] > base["henry_hub"][j] * 1.02
    assert high["production"][j] > base["production"][j]
    assert high["exports"][j] < base["exports"][j]
    p = m.prices(m.qngas_b * 1.1)
    assert p["MPBLK/pngel"][US, j] > m.prices_b["MPBLK/pngel"][US, j]


def test_demand_cases_held_to_a_few_percent():
    """EIA's demand-side cases, each on its own gas use: 2050 Henry Hub within 7% (electrnp, whose LNG
    exports EIA raises by assumption, is the worst at about 6.6%)."""
    from nems_open.ngmm.fit import check
    res = check()
    for c in ("hm2026", "lm2026", "higheldmd", "highztc", "lowztc", "altelec", "electrnp"):
        assert abs(res[c]["hh_err_pct"]) < 7, (c, res[c])


def test_run_model_ngmm_keeps_baseline():
    from nems_open import run_model
    from nems_open.supply_standin.data import load_case
    b = load_case("cb2026")
    r = run_model.run(ported=(), ogs="ngmm", end_year=2030)
    j = 2030 - FIRST_YEAR
    for k in ("MPBLK/pngrs", "MPBLK/pngel", "MPBLK/pelrs"):
        assert np.isclose(r.prices[k][US, j], b[k][US, j], rtol=1e-6), k
    assert r.gas is not None and np.isclose(r.gas["henry_hub"][j], 1.0 * load_hh(j), rtol=1e-6)


def load_hh(j):
    from nems_open.ngmm import data
    return data.load("cb2026")["NGTDMREP/oghhprng"][j]
