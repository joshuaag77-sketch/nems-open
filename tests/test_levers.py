"""The ten plain levers: each moves results the right way, and each says how real its move is.

The supply-side levers run on stub demand (ported=()), a few seconds a run. Building codes and
appliance standards edit input tables of the ported modules, so they run those: residential from
its dump, commercial from the files, 2027 to 2029.
"""

import numpy as np
import pytest

from nems_open import levers
from nems_open.demand_adapter import Policy
from nems_open.paths import REFERENCE_RUN
from nems_open.run_model import run
from nems_open.supply_standin.data import FIRST_YEAR, US, available

pytestmark = pytest.mark.skipif(not (available() and REFERENCE_RUN.exists()), reason="AEO2026 runs not available")

START, END = 2027, 2040
J = 2035 - FIRST_YEAR


def stub(**kw):
    return run(Policy(start_year=START, **kw), START, END, ported=())


@pytest.fixture(scope="module")
def base():
    return stub()


def q(r, name, j=J):
    return float(r.quantities[f"QBLK/{name}"][US, j])


def p(r, name, j=J):
    return float(r.prices[f"MPBLK/{name}"][US, j])


def test_off_changes_nothing(base):
    """Every lever at its off value is the reference run, to the bit."""
    r = stub(**{v.name: v.off for v in levers.LEVERS.values()})
    for k in base.prices:
        assert np.array_equal(r.prices[k], base.prices[k]), k
    for k in base.quantities:
        assert np.array_equal(r.quantities[k], base.quantities[k]), k


def test_years_before_start_keep_the_baseline(base):
    r = stub(coal_retirement=0.5, nuclear=1.25, renewable_cost=-1.0, load_growth=500.0, gas_supply=-1.0, oil_price=1.5)
    j = START - 1 - FIRST_YEAR
    for k in base.prices:
        assert np.array_equal(r.prices[k][:, :j + 1], base.prices[k][:, :j + 1]), k


def test_carbon_price(base):
    r = stub(carbon_price=50.0)
    assert r.co2_total[J] < base.co2_total[J] and p(r, "pngrs") > p(base, "pngrs") and q(r, "qclel") < q(base, "qclel")


def test_ev_sales(base):
    r = stub(ev_share=0.8)
    assert q(r, "qmgtr") < q(base, "qmgtr") and q(r, "qeltr") > q(base, "qeltr") and r.co2_total[J] < base.co2_total[J]


def test_coal_retirement(base):
    j = 2030 - FIRST_YEAR   # EIA's own coal burn is nearly gone by the 2040s
    r = stub(coal_retirement=0.5)
    assert q(r, "qclel", j) < q(base, "qclel", j)
    assert q(r, "qngel", j) > q(base, "qngel", j)
    assert p(r, "pngel", j) > p(base, "pngel", j)     # more gas burned, dearer gas
    assert r.co2_total[j] < base.co2_total[j]         # gas in place of coal


def test_coal_retirement_size(base):
    """Half the fleet reached by 2035 means about half EIA's coal burn gone then (before gas moves it)."""
    r = stub(coal_retirement=0.5)
    assert 0.3 < q(r, "qclel") / q(base, "qclel") < 0.7


def test_nuclear(base):
    up, down = stub(nuclear=1.25), stub(nuclear=0.75)
    assert q(up, "qurel") > q(base, "qurel") > q(down, "qurel")
    assert q(up, "qngel") < q(base, "qngel") < q(down, "qngel")
    assert up.co2_total[J] < base.co2_total[J] < down.co2_total[J]


def test_renewable_cost(base):
    cheap, dear = stub(renewable_cost=-1.0), stub(renewable_cost=1.0)
    assert q(cheap, "qpvel") > q(base, "qpvel") > q(dear, "qpvel")
    assert q(cheap, "qngel") < q(base, "qngel") < q(dear, "qngel")
    assert cheap.co2_total[J] < base.co2_total[J] < dear.co2_total[J]
    assert p(cheap, "pelrs") < p(base, "pelrs")


def test_load_growth(base):
    r = stub(load_growth=500.0)
    j = 2040 - FIRST_YEAR
    added = 500.0 * 3.412 * (2040 - START + 1) / (2050 - START + 1)
    assert q(r, "qelcm", j) == pytest.approx(q(base, "qelcm", j) + added, rel=0.02)
    assert q(r, "qngel", j) > q(base, "qngel", j) and p(r, "pelrs", j) > p(base, "pelrs", j)
    assert r.co2_total[j] > base.co2_total[j]


def test_gas_supply(base):
    more, less = stub(gas_supply=1.0), stub(gas_supply=-1.0)
    assert p(more, "pngin") < p(base, "pngin") < p(less, "pngin")
    assert q(more, "qngel") > q(base, "qngel") > q(less, "qngel")
    assert q(more, "qclel") < q(base, "qclel")
    assert p(more, "pelrs") < p(base, "pelrs") < p(less, "pelrs")
    assert p(less, "pmgtr") == pytest.approx(p(base, "pmgtr"), rel=0.02)  # the oil price is the oil lever's


def test_oil_price(base):
    r = stub(oil_price=1.25)
    assert p(r, "pmgtr") > p(base, "pmgtr") and p(r, "pdstr") > p(base, "pdstr")
    assert q(r, "qmgtr") < q(base, "qmgtr")


def test_side_case_levers_stop_at_their_ends():
    with pytest.raises(ValueError):
        stub(gas_supply=2.0)


def test_coal_and_nuclear_in_the_dispatch_lp():
    """With elec="lp" the capacity itself moves and the LP redispatches."""
    pytest.importorskip("highspy")
    j = 2030 - FIRST_YEAR
    a = run(Policy(start_year=2030), 2030, 2030, ported=(), elec="lp", elec_price="standin", maxitr=1)
    b = run(Policy(start_year=2030, coal_retirement=0.5), 2030, 2030, ported=(), elec="lp", elec_price="standin", maxitr=1)
    c = run(Policy(start_year=2030, nuclear=1.25), 2030, 2030, ported=(), elec="lp", elec_price="standin", maxitr=1)
    assert q(b, "qclel", j) < q(a, "qclel", j) and q(b, "qngel", j) > q(a, "qngel", j)
    assert q(c, "qclel", j) < q(a, "qclel", j)  # new nuclear pushes out coal first in this LP
    assert c.co2["el"][US, j] < a.co2["el"][US, j] and b.co2["el"][US, j] < a.co2["el"][US, j]


# ---- the levers on ported modules ------------------------------------------------------------

YEAR = 2029


def ported(**kw):
    r = run(Policy(start_year=2027, **kw), 2027, YEAR, ported=("residential", "commercial"))
    j = YEAR - FIRST_YEAR
    return {k: q(r, k, j) for k in ("qelrs", "qngrs", "qelcm", "qngcm")}


@pytest.fixture(scope="module")
def ported_base():
    # Commercial from the files in the baseline too, so the comparison is not of two starts.
    from nems_open.commercial.levers import CommercialLevers
    return ported(commercial=CommercialLevers(shell_improvement=1e-12))


def test_building_code(ported_base):
    r = ported(building_code=0.3)
    assert r["qngrs"] < ported_base["qngrs"], "new homes use less gas"
    assert r["qngcm"] < ported_base["qngcm"], "new commercial buildings use less gas"


def test_appliance_standard(ported_base):
    r = ported(appliance_standard=0.2)
    assert r["qelrs"] < ported_base["qelrs"]
    assert r["qngrs"] < ported_base["qngrs"]
    assert r["qelcm"] + r["qngcm"] < ported_base["qelcm"] + ported_base["qngcm"]


def test_building_levers_need_a_ported_buildings_sector():
    for kw in ({"building_code": 0.2}, {"appliance_standard": 0.2}):
        with pytest.raises(ValueError):
            stub(**kw)


def test_standard_never_passes_the_best_on_offer():
    from nems_open import oracle_state
    from nems_open.residential import levers as rl, resd
    if not oracle_state.available("yb_in", 38, "resd"):
        pytest.skip("residential oracle dumps not present")
    s = resd.start_from_dump(38)
    before = s["rteqeff"].a.copy()
    assert rl.tighten(s, 5.0, 2027) > 0
    assert (s["rteqeff"].a >= before).all()
    assert s["rteqeff"].a.max() == before.max()


# ---- the grades ------------------------------------------------------------------------------

def test_ten_levers_all_on_policy():
    assert len(levers.LEVERS) == 10
    for name, v in levers.LEVERS.items():
        assert hasattr(Policy(), name), name
        assert v.unit and v.moves and v.title


def test_grades_say_what_each_lever_acts_on():
    default = ("residential", "commercial")
    grade = lambda name, ported=default, elec="standin": levers.fidelity(name, ported, elec)[0]
    assert grade("building_code") == grade("appliance_standard") == levers.PORTED
    assert grade("ev_share") == levers.STAND_IN and grade("ev_share", default + ("transportation",)) == levers.PORTED
    assert grade("coal_retirement") == grade("nuclear") == levers.STAND_IN
    assert grade("coal_retirement", elec="lp") == grade("nuclear", elec="lp") == levers.OWN_MODEL
    for name in ("gas_supply", "oil_price"):
        assert grade(name) == grade(name, elec="lp") == levers.STAND_IN


def test_a_lever_on_a_stand_in_says_so_in_its_label():
    default = ("residential", "commercial")
    for row in levers.table(default):
        if row["grade"] == levers.PORTED:
            assert row["label"] == row["title"]
        else:
            assert row["grade"] in row["label"], row
