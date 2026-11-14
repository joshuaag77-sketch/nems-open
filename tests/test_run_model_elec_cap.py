"""run_model's elec_cap switch: the capacity expansion LP under the dispatch LP.

The coupled run builds the capacity LP once per year (about 2 minutes a year), so it runs only with
NEMS_RUN_SLOW=1."""

import os

import numpy as np
import pytest

from nems_open import run_model
from nems_open.demand_adapter import Policy
from nems_open.emm import capacity
from nems_open.paths import INPUT, REFERENCE_RUN

pytestmark = pytest.mark.skipif(
    not ((INPUT / "emm" / "emm_db" / "NEMS_INPUT.db").exists() and REFERENCE_RUN.exists()), reason="EMM inputs missing")


def test_elec_cap_switch_is_validated():
    with pytest.raises(ValueError):
        run_model.run(Policy(), 2030, 2030, elec_cap="nope")
    with pytest.raises(ValueError):
        run_model.run(Policy(), 2030, 2030, elec="standin", elec_cap="lp")


def test_dispatch_capacity_folds_the_new_groups():
    cap = {g: np.ones(capacity.NUM_R) for g in capacity.STATE_GROUPS}
    out = capacity.dispatch_capacity(cap)
    assert out["gas_cc"].sum() == pytest.approx(2 * capacity.NUM_R)       # gas_cc + gas_cc_new
    assert out["steam"].sum() == pytest.approx(2 * capacity.NUM_R)        # steam + gas_conv
    total = sum(v.sum() for v in cap.values())
    assert sum(v.sum() for v in out.values()) == pytest.approx(total)


@pytest.mark.skipif(os.environ.get("NEMS_RUN_SLOW") != "1", reason="slow: set NEMS_RUN_SLOW=1 (about 10 minutes)")
def test_capacity_lp_runs_inside_the_loop():
    r = run_model.run(Policy(0.0, None, 1.0, 2027), 2027, 2028, elec="lp", elec_price="standin", elec_cap="lp")
    assert set(r.capacity) == {2027, 2028}
    for y, res in r.capacity.items():
        assert res.status == "ok:optimal"
        assert res.unserved_twh < 5.0
    assert np.isfinite(r.wholesale_us[2028 - 1990])
    # The fleet the dispatch saw is the capacity LP's, not EIA's.
    assert r.capacity[2028].capacity["coal"].sum() > 0
