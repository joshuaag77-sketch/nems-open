"""Policy shocks must pass the unchanged EIA test before the default loop stops."""

import numpy as np
import pytest

from nems_open.converge import MAXITR
from nems_open.demand_adapter import Policy
from nems_open.run_model import DEFAULT_MAXITR, run
from nems_open.supply_standin.data import available

pytestmark = pytest.mark.skipif(not available(), reason="AEO2026 runs not available")


@pytest.mark.parametrize("policy", [Policy(ev_share=1.0), Policy(oil_price=2.0)],
                         ids=["high-ev", "high-oil"])
def test_policy_converges_with_confirming_pass(policy):
    result = run(policy, ported=())
    assert set(result.stable) == set(range(2027, 2051))
    assert all(result.stable.values()), result.report()
    for year in result.stable:
        passes = [p for p in result.passes if p.year == year]
        assert passes[-1].number <= DEFAULT_MAXITR + 1
        assert passes[-1].fcrl == 1
        assert all(p.converged and not p.failing for p in passes[-2:]), result.report()


def test_reference_unchanged_by_larger_iteration_budget():
    before = run(ported=(), maxitr=MAXITR)
    after = run(ported=())
    assert after.passes == before.passes
    assert after.stable == before.stable
    for group in ("prices", "quantities", "co2"):
        old, new = getattr(before, group), getattr(after, group)
        assert old.keys() == new.keys()
        for key in old:
            np.testing.assert_allclose(new[key], old[key], rtol=0, atol=1e-9, err_msg=key)


def test_explicit_cb2026_iteration_limit_is_honored():
    result = run(Policy(oil_price=2.0), ported=(), end_year=2027, maxitr=MAXITR)
    assert not result.stable[2027]
    assert len(result.passes) == MAXITR + 1
    assert "MPBLK/ppfin" in result.passes[-1].failing
