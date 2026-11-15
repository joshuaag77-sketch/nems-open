"""ogs='hsm': scale factors, cache key, and the hook in run_model (HSM itself is stubbed; a real run takes 9 minutes)."""
import numpy as np
import pytest

from nems_open import run_model
from nems_open.ogsm import couple
from nems_open.demand_adapter import Policy

START = END = 2030


def test_no_price_change_means_no_scaling():
    assert couple.scale_for(None, None) == {}
    assert couple.scale_for(np.ones(61), np.ones(61)) == {}


def test_gas_and_oil_ratios_reach_the_right_restart_arrays():
    s = couple.scale_for(np.full(61, 1.2), np.full(61, 0.8))
    assert set(s) == {"NGTDMREP/ogprcng", "NGTDMREP/ogwprng", "LFMMOUT/rfcrudewhp"}
    assert np.allclose(s["NGTDMREP/ogprcng"], 1.2) and np.allclose(s["LFMMOUT/rfcrudewhp"], 0.8)


def test_nan_ratio_is_no_change():
    r = np.ones(61)
    r[5] = np.nan
    assert couple.scale_for(r, None) == {}


def test_cache_key_follows_inputs():
    a = couple.scale_for(np.full(61, 1.2), None)
    b = couple.scale_for(np.full(61, 1.3), None)
    assert couple._key("x", a) == couple._key("x", dict(a))
    assert couple._key("x", a) != couple._key("x", b)
    assert couple._key("x", a) != couple._key("y", a)


def test_run_model_passes_run_prices_to_hsm(monkeypatch):
    seen = {}

    def fake(gas, oil, **kw):
        seen["gas"], seen["oil"] = gas, oil
        return {"ogngprd": np.zeros(61)}

    monkeypatch.setattr(couple, "production", fake)
    plain = run_model.run(Policy(start_year=START), START, END, ported=())
    assert plain.ogsm is None
    r = run_model.run(Policy(carbon_price=100, start_year=START), START, END, ported=(), ogs="hsm")
    assert r.ogsm is not None
    assert seen["gas"].shape == (61,)
    # HSM gets the gas market's wellhead price: a carbon price moves gas use, so it moves the wellhead price
    assert abs(seen["gas"][START - 1990] - 1.0) > 1e-4
    assert r.gas is not None
    assert np.allclose(seen["gas"][: START - 1990], 1.0)   # years before the run keep the baseline


def test_hsm_needs_cb2026():
    with pytest.raises(ValueError):
        run_model.run(Policy(start_year=START), START, END, baseline="lowogs", ported=(), ogs="hsm")
    with pytest.raises(ValueError):
        run_model.run(Policy(start_year=START), START, END, ported=(), ogs="bogus")
