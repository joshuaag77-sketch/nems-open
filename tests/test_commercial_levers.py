"""Commercial policy levers: edits to the input tables, and what the ported routines do with them."""

import numpy as np
import pytest
from nems_open.commercial import initial_state as ini
from nems_open.commercial import levers as lv
from nems_open.commercial.comm import Commercial
from nems_open.run_demand import Inputs

XDIST_BY_YEAR = False
LAST = 35       # 2024: enough years for a code or a standard to show
SH, SC = 1, 2


@pytest.fixture(scope="module")
def inputs():
    return Inputs()


def run(inputs, levers=None):
    flsp = inputs.array("MACOUT/mc_commflsp")
    c = Commercial.start_from_files(inputs, levers)
    for y in range(30, LAST + 1):
        for itr in (1, 2):
            inputs.apply(c.s)
            c.iteration(y, itr, flsp)
    return c.s


def use(s, services, y=LAST):
    """End-use consumption (trillion Btu, all fuels, divisions 1 to 9) for some services in year y."""
    a = s["enduseconsump"]
    return float(a.a[:, [x - 1 for x in services], :, :9, y - a.lb[4]].sum())


@pytest.fixture(scope="module")
def baseline(inputs):
    return run(inputs)


def test_default_levers_change_nothing():
    t, _ = ini.tables()
    before = {n: t[n].a.copy() for n in ("techavailability", "effgrowthrate")}
    assert lv.CommercialLevers().is_default()
    assert all(np.array_equal(t[n].a, before[n]) for n in before)


def test_standard_drops_low_efficiency_equipment_but_keeps_the_best():
    t, _ = ini.tables()
    before = t["techavailability"].a.copy()
    n = lv.apply_standard(t, lv.Standard(service=2, min_eff=3.5, year=2021, fuel=1))
    assert n > 0
    after = t["techavailability"].a
    assert (after <= before).all() and (after != before).any()
    # in every region the best cooling equipment is still on sale after 2021
    for r in range(1, 10):                   # the nine census divisions
        offered = [float(t["techeff"][r, 2, tech, v]) for tech in range(1, 62) for v in range(1, 45)
                   if t["techbyservice"][2, tech] == 1 and t["techbymodel"][tech, v] == 1 and t["techavailability"][r, tech, v, 2] >= 2021]
        assert offered, r


def test_standard_year_must_follow_the_base_year():
    t, _ = ini.tables()
    with pytest.raises(ValueError):
        lv.apply_standard(t, lv.Standard(service=2, min_eff=3.5, year=2019))


def test_a_stricter_building_code_cuts_heating_and_cooling(inputs, baseline):
    s = run(inputs, lv.CommercialLevers(shell_improvement=0.25, shell_start_year=2020))
    base, now = use(baseline, (SH, SC)), use(s, (SH, SC))
    assert now < base
    # new buildings only, and only five years of them: a real but modest cut
    assert now > 0.9 * base
    # the other services barely move (same floorspace, same prices)
    assert use(s, (6, 7)) == pytest.approx(use(baseline, (6, 7)), rel=1e-3)


def test_an_efficiency_standard_cuts_cooling(inputs, baseline):
    s = run(inputs, lv.CommercialLevers(standards=(lv.Standard(service=2, min_eff=3.5, year=2021, fuel=1),)))
    assert use(s, (SC,)) < use(baseline, (SC,))
