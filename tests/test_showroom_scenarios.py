"""scripts/showroom_scenarios.py: every scenario maps to real run_model inputs, or says what is missing."""

import inspect
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
sc = pytest.importorskip("showroom_scenarios")
from nems_open import run_model  # noqa: E402


def test_thirty_scenarios_with_unique_keys():
    keys = [s.key for s in sc.SCENARIOS]
    assert len(keys) == 30 and len(set(keys)) == 30


def test_switches_are_run_model_arguments():
    params = inspect.signature(run_model.run).parameters
    assert set(sc.SWITCHES) <= set(params)


def test_every_ready_scenario_builds_a_policy_and_the_rest_say_why():
    for s in sc.SCENARIOS:
        if s.not_yet():
            with pytest.raises(NotImplementedError, match="LNG"):
                sc.policy(s)
        else:
            args = sc.run_args(s)
            assert set(args) <= set(inspect.signature(run_model.run).parameters)


def test_data_center_gw_becomes_twh_and_reaches_target_in_2035():
    load = sc.data_center(100)
    assert load.twh[2035 - 1990] == pytest.approx(876.0)
    assert load.twh[2026 - 1990] == 0 and load.twh[2050 - 1990] == pytest.approx(876.0)
    assert load.shares.sum() == pytest.approx(1.0)


def test_default_split_is_eias_own():
    try:
        from nems_open.datacenter import regional_shares
        eia = regional_shares()
    except FileNotFoundError as e:
        pytest.skip(f"reference data missing: {e}")
    assert np.allclose([sc.DC_SHARES[d] for d in sc.DIVISIONS], eia, atol=0.002)


def test_ev_path_keeps_eia_through_2030_then_moves_to_target():
    p = sc.ev_path(0.75)
    assert np.isnan(p[2030 - 1990]) and p[2035 - 1990] == pytest.approx(0.75) and p[2050 - 1990] == pytest.approx(0.75)
