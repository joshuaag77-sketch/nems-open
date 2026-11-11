import numpy as np
import pytest

from nems_open.macro import regional

pytestmark = pytest.mark.skipif(regional.restart_path("highogs") is None, reason="EIA scenario restarts not present")

CASES = ("cb2026", "lowogs", "highogs", "hm2026", "lm2026")


@pytest.fixture(scope="module")
def runs():
    return {c: regional.load_case(c) for c in CASES}


@pytest.fixture(scope="module")
def model(runs):
    return regional.Regional(runs["cb2026"]).fit(runs["lowogs"])


def _predict(model, runs, case):
    return model.predict(regional.gdp_gap(runs[case]["mc_gdpr"], runs["cb2026"]["mc_gdpr"]))


def test_reference_gap_zero_reproduces_reference(runs, model):
    p = model.predict(np.zeros(61))
    for k in ("mc_commflsp", "mc_revind", "mc_empna"):
        assert np.allclose(p[k], runs["cb2026"][k])


def test_divisions_still_add_to_us_total(runs, model):
    ref = runs["cb2026"]["mc_revind"]
    leaf = (ref[regional.US, :, 40] > 0) & (np.abs(ref[: regional.DIVISIONS].sum(0)[:, 40] - ref[regional.US, :, 40]) < 1e-2 * ref[regional.US, :, 40])
    p = _predict(model, runs, "highogs")["mc_revind"]
    assert leaf.sum() > 50
    ratio = lambda a: a[: regional.DIVISIONS].sum(0)[leaf] / a[regional.US][leaf]
    assert np.allclose(ratio(p), ratio(ref), rtol=1e-6, equal_nan=True)


def test_floorspace_elasticity_matches_macro_cases(model, runs):
    assert 0.2 < model.beta_floor < 0.5
    for case in ("hm2026", "lm2026"):
        b = regional.Regional(runs["cb2026"]).fit(runs[case]).beta_floor
        assert abs(b - model.beta_floor) < 0.15


def test_floorspace_holdout_highogs_beats_no_change(model, runs):
    truth = model.floor_gap(runs["highogs"])[regional.FIT]
    gap = regional.gdp_gap(runs["highogs"]["mc_gdpr"], runs["cb2026"]["mc_gdpr"])
    pred = (model.beta_floor * gap)[regional.FIT]
    assert np.abs(pred - truth).mean() < np.abs(truth).mean()


@pytest.mark.parametrize("key", ["mc_revind", "mc_empna"])
def test_holdout_highogs_beats_no_change(model, runs, key):
    flat = lambda a: a[: regional.DIVISIONS][:, :, regional.FIT].reshape(-1, 25)
    p, t, r = flat(_predict(model, runs, "highogs")[key]), flat(runs["highogs"][key]), flat(runs["cb2026"][key])
    keep = (p > 0).all(1) & (t > 0).all(1) & (r > 0).all(1)
    rms = lambda a, b: np.sqrt((np.log(a[keep] / b[keep]) ** 2).mean())
    assert keep.sum() > 300
    assert rms(p, t) < rms(r, t)
