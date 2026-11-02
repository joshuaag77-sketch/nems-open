"""Technology choice first call vs the oracle: the file reads and one-time edits in COMTechnologyChoice.

The oracle dumps its state just before and after the routine's first call (`ftc_in`, `ftc_out`,
2019, first iteration). Skipped until the oracle has run.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.commercial import technology_choice_inputs as tci

pytestmark = pytest.mark.skipif(not oracle_state.available("ftc_out", 30), reason="oracle state not dumped")


@pytest.fixture(scope="module")
def before():
    return oracle_state.load("ftc_in", 30)


@pytest.fixture(scope="module")
def after():
    return oracle_state.load("ftc_out", 30)


def same(mine, theirs):
    mine, theirs = np.asarray(mine), np.asarray(theirs)
    assert mine.shape == theirs.shape
    err = np.abs(mine.astype(np.float64) - theirs) / np.maximum(np.abs(theirs), 1e-6)
    assert err.max() < 1e-6


def test_kbehav(after):
    same(tci.read_kbehav().a, after["behaviorshare"].a)


def test_kdeleff(after):
    eff = tci.read_kdeleff()
    same(eff.a, after["effgrowthrate"].a)
    same(eff.a, after["ceffgrowth"].a)


def test_kcapfac(after):
    same(tci.read_kcapfac().a, after["capacityfactor"].a)


def test_kprem(after):
    prop, prem = tci.read_kprem(nrg2007=1, stimulus=1)
    same(prop.a, after["timeprefprop"].a)
    same(prem.a, after["timeprefprem"].a)


def test_cooling_index(before):
    assert tci.read_kparm_cooling_index() == int(before["coolingtechindexhp"])


def test_heat_pump_cost_edit(before, after):
    cost = before["techcost"].copy()
    tci.heat_pump_cost_edit(cost, before["techbyservice"], before["techbymodel"], before["cmnumeqv"],
                            int(before["coolingtechindexhp"]))
    same(cost.a, after["techcost"].a)
    assert (cost.a != before["techcost"].a).any()  # the edit changed something
