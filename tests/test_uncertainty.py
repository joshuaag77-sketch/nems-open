"""Uncertainty bands: the sampling, the blend of EIA's cases, and one run."""

import numpy as np
import pytest
from nems_open import uncertainty as U
from nems_open.paths import REFERENCE_RUN
from nems_open.supply_standin.data import CASES

pytestmark = pytest.mark.skipif(not REFERENCE_RUN.exists(), reason="restart files missing")


def zero():
    return {k: 0.0 for k in U.load_ranges()["factors"]}


def test_every_range_end_is_an_eia_case():
    for name, f in U.load_ranges()["factors"].items():
        assert f["low_case"] in CASES and f["high_case"] in CASES, name


def test_sample_uses_each_stratum_once_and_stays_in_range():
    ranges = U.load_ranges()
    w = U.sample(1000, ranges=ranges)
    for name, f in ranges["factors"].items():
        x = w[name]
        assert x.min() >= (-1 if f["two_sided"] else 0) and x.max() <= 1
        # triangular, most likely at the reference: the two-sided mean is near 0, the one-sided near 1/3
        assert abs(x.mean() - (0 if f["two_sided"] else 1 / 3)) < 0.03, name


def test_sample_is_reproducible_and_inputs_are_independent():
    a, b = U.sample(500), U.sample(500)
    assert all(np.array_equal(a[k], b[k]) for k in a)
    names = list(a)
    assert abs(np.corrcoef(a[names[0]], a[names[1]])[0, 1]) < 0.15


def test_blend_at_zero_is_the_reference_and_at_an_end_is_that_case():
    ref = U.case_arrays(U.REFERENCE)
    base, homes = U.blend(zero())
    assert all(np.array_equal(base[k], ref[k]) for k in ref)
    w = zero()
    w["economic_growth"] = 1.0
    base, homes = U.blend(w)
    hm = U.case_arrays("hm2026")
    key = "QBLK/qelas"
    assert np.allclose(base[key], hm[key])
    assert homes[2050 - 1990] == pytest.approx(U.households("hm2026")[2050 - 1990])
    w["economic_growth"] = -0.5
    half, _ = U.blend(w)
    lm = U.case_arrays("lm2026")
    assert np.allclose(half[key], ref[key] + 0.5 * (lm[key] - ref[key]))


def test_first_order_finds_the_input_that_matters():
    rng = np.random.default_rng(1)
    x1, x2 = rng.random(1000), rng.random(1000)
    y = 3 * x1 + 0.2 * x2 + 0.05 * rng.standard_normal(1000)
    assert U.first_order(x1, y) > 0.9
    assert U.first_order(x2, y) < 0.05


def test_reference_run_gives_sensible_measures_and_ends_move_them_the_right_way():
    ref = U.run_one((zero(), 0.0))
    assert ref["co2"].shape == (len(U.YEARS),)
    assert 3000 < ref["co2"][-1] < 5000 and 1500 < ref["bill"][-1] < 4000 and 5 < ref["gas"][-1] < 30
    w = zero()
    w["oil_gas_supply"] = -1.0           # EIA's low supply case: gas and oil dearer
    tight = U.run_one((w, 0.0))
    assert tight["gas"][-1] > ref["gas"][-1] and tight["bill"][-1] > ref["bill"][-1]
    assert tight["co2"][-1] < ref["co2"][-1]
    assert U.run_one((zero(), 50.0))["co2"][-1] < ref["co2"][-1]
