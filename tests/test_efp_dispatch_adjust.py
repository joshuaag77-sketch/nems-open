"""EFP's generation costs follow the loop's dispatch (efd_standin.block's `adjust`), not only EIA's."""
import numpy as np
import pytest


@pytest.fixture(scope="module")
def snap():
    from nems_open.snapshot import Snapshot
    try:
        return Snapshot()
    except Exception:
        pytest.skip("no cb2026 restart here")


def test_no_adjust_is_eias_dispatch(snap):
    from nems_open.emm.efp import efd_standin as e
    a, b = e.block(snap, 46, 5, 45, 36), e.block(snap, 46, 5, 45, 36, {"fuel": {}, "price": {}, "gen": 1.0})
    for k in a:
        assert np.array_equal(np.asarray(a[k]), np.asarray(b[k])), k


def test_more_fuel_and_dearer_gas_raise_generation_cost(snap):
    from nems_open.emm.efp import efd_standin as e
    base = e.block(snap, 46, 5, 45, 36)
    more = e.block(snap, 46, 5, 45, 36, {"fuel": {f: 1.1 for f in ("cl", "ng", "ds", "rs", "ur")},
                                        "price": {"ng": 1.2}, "gen": 1.1})
    assert more["ertfl"].sum() > 1.1 * base["ertfl"].sum()           # 10% more fuel, gas 20% dearer
    assert more["etgen"] == pytest.approx(1.1 * base["etgen"], rel=1e-5)
    assert more["ertom"].sum() == pytest.approx(1.1 * base["ertom"].sum(), rel=1e-5)
