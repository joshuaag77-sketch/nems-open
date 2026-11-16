"""EPA 111 as EMM applies it (emmcntl.txt %EPA 111 SW%): coal-gas cofiring ends after 2038 and those plants retire,
no coal-to-gas switches after 2030, new gas combined cycle without CCS held to 40% from 2029."""

import numpy as np
import pytest

from nems_open.emm import capacity
from nems_open.emm.regions import NUM_EMM

try:
    from nems_open.snapshot import Snapshot
    SNAP = Snapshot()
except Exception:                       # no reference run in this checkout
    SNAP = None


def test_reads_cb2026_rule():
    r = capacity.epa111()
    assert r["switch"] == 1
    assert (r["gas_switch_last"], r["cofire_last"], r["coal_rule"], r["new_cc_year"]) == (2030, 2038, 2031, 2029)
    assert r["cofire_coal_share"] == pytest.approx(0.6)
    assert r["new_cc_cf"] == pytest.approx(0.4)


def test_coal_rule_year_matches_the_lp():
    # coal without CCS retires at the end of UEPA_CLYR, so the LP's rule year is the year after
    assert capacity.RULE_YEAR == capacity.epa111()["coal_rule"] + 1


@pytest.mark.skipif(SNAP is None, reason="reference run missing")
def test_cofiring_plants_retire_after_2038_only():
    cap = {g: np.full(NUM_EMM, 2.0) for g in capacity.STATE_GROUPS}
    zero = {g: np.zeros(NUM_EMM) for g in capacity.STATE_GROUPS}
    assert capacity.epa111_retirements(SNAP, 2038, cap, zero) is zero
    rets = capacity.epa111_retirements(SNAP, 2039, cap, zero)
    assert np.allclose(rets["gas_conv"], 2.0)                    # every LP conversion cofires
    existing = capacity.cofiring_existing(SNAP, capacity.START_YEAR)
    assert 10.0 < existing.sum() < 15.0                          # 14.3 GW of ng in 2024, 1.7 GW full conversions kept
    assert np.allclose(rets["steam"], np.minimum(existing, 2.0))
    assert np.allclose(rets["coal"], 0.0)
