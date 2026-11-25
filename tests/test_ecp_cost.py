"""ECP's build column costs (emm/ecp_cost.py) against EIA's own 2030 solve and inputs."""

import numpy as np
import pytest

from nems_open.emm import capacity, ecp_cost, technology
from nems_open.snapshot import Snapshot

# Nominal costs of EIA's 2030 ECP solve (AIMMS, cB_DSP and cIX NomCoeff, step 1), regions TRE, PJME, SPPS: planning years
# 1 and 2. Wind and solar where the solve's resource cost factor is 1.
ECP_2030 = {"AT": ((1364.8, 1274.3),), "AC": ((1738.5, 1622.5),), "CS": ((3323.8, 3100.5),), "DS": ((1922.4, 1637.3),)}


@pytest.fixture(scope="module")
def snap():
    try:
        return Snapshot()
    except FileNotFoundError:
        pytest.skip("no snapshot")


def column(snap, code, online, itc=0.0, ptc=(0.0, 0.0), cf=0.0):
    p, reg = technology.type_parameters(), technology.regional_costs()
    i = technology.ecp_codes().index(code)
    ovn = capacity.learned_overnight(snap, code, online) * (1.0 - itc)
    wires = reg["transmission_overnight_cost"][:25, i] * (reg["transmission_charge_rate"][:25, i] - capacity.TAX_FCF_ADJ)
    fom = 0.0 if code == "DS" else reg["transmission_fom"][:25, i]
    return ecp_cost.build_column(snap, code, online, ovn, p["fom"][i], wires, fom, ptc, cf)


def test_columns_match_ecp_2030(snap):
    rate = ecp_cost.financing(snap, 2030, "AT")[-1]
    unit = ecp_cost.deflator(snap, 2031) * (1.0 + rate) ** -2
    for code, vals in ECP_2030.items():
        c = column(snap, code, 2031, 0.3 if code == "DS" else 0.0)
        for got, want in zip((c["first"][0], c["second"][0]), vals[0]):
            assert got * unit == pytest.approx(want, rel=0.012), code


def test_financing_adders_follow_ecpdaty():
    assert ecp_cost.rate_adder("WN", 2029) == pytest.approx((0.03, 0.03))
    assert ecp_cost.rate_adder("WN", 2030) == (0.0, 0.0)
    assert ecp_cost.rate_adder("PV", 2028) == pytest.approx((0.03, 0.03))
    assert ecp_cost.rate_adder("PV", 2029) == (0.0, 0.0)
    assert ecp_cost.rate_adder("DS", 2036) == pytest.approx((0.03, 0.03))
    assert ecp_cost.rate_adder("AT", 2030) == (0.0, 0.0)
    assert 0.0 < ecp_cost.rate_adder("DS", 2032, 0.073, tail=True)[0] < 0.03


def test_one_year_cost_of_storage_is_the_adder_for_life(snap):
    c = column(snap, "DS", 2031, 0.3)
    assert np.median(ecp_cost.one_year_cost(c)) > 2.0 * np.median(c["first"] / c["annuity"])
    late = column(snap, "DS", 2040)
    assert np.median(ecp_cost.one_year_cost(late)) == pytest.approx(np.median(late["first"] / late["annuity"]), rel=0.1)


def test_last_credit_year_is_not_charged_below_the_annuity(snap):
    c = column(snap, "WN", 2029, ptc=(16.5, 0.0), cf=0.4)
    assert c["first"][0] < c["second"][0]
    assert ecp_cost.one_year_cost(c)[0] == pytest.approx(c["first"][0] / c["annuity"])


def test_step_premium_is_the_whole_column(snap):
    c = column(snap, "AC", 2031)
    unit = ecp_cost.deflator(snap, 2031) * (1.0 + ecp_cost.financing(snap, 2030, "AC")[-1]) ** -2
    premium = (ecp_cost.one_year_cost(c, 1.375) - ecp_cost.one_year_cost(c))[0] * unit
    assert premium == pytest.approx(2234.3 - 1738.5, rel=0.03)      # TRE steps 2 and 1 in EIA's 2030 solve
    wind = column(snap, "WN", 2029, ptc=(16.5, 0.0), cf=0.4)         # waiting loses the credit
    last = (ecp_cost.one_year_cost(wind, 1.375) - ecp_cost.one_year_cost(wind))[0]
    assert last < 0.1 * 0.375 * wind["capital"][0]


def test_intermittent_cap_is_ten_points_over_the_largest_share(snap):
    a, b = np.full(25, 0.02), np.full(25, 0.5)
    b[0] = 0.8
    lim = capacity.intermittent_limit([a, b])
    assert lim[0] == pytest.approx(0.85) and lim[1] == pytest.approx(0.6)
    assert capacity.intermittent_limit([a])[0] == pytest.approx(0.15)
    # wind and solar over generation in 2026: the Plains high, Florida and the Southeast low
    share = capacity.reference_intermittent_share(snap, 2026)
    assert share[17] > 0.4 and share[0] > 0.3 and share[13] < 0.25


def test_conventional_cc_is_dearer_than_ac_and_has_its_own_steps(snap):
    from nems_open.emm import dispatch
    case = dispatch.build_case(snap, 2032, "none")
    ac = capacity.capital_costs(snap, 2032, case)["gas_cc_new"]
    cc = capacity.capital_costs(snap, 2032, case, {}, None, {"gas_cc_new": "CC"})["gas_cc_new"]
    assert 1.0 < np.median(cc / ac) < 1.15
    assert [round(b, 2) for b, _ in capacity.build_steps("CC", [0.0] * 5)] == [5.0, 3.0, 4.0]


def test_monthly_days_keep_the_year(snap):
    from nems_open.emm import dispatch
    case = dispatch.build_case(snap, 2031, "none")
    lp = capacity.monthly_days(case)
    assert lp.weights.sum() == pytest.approx(365.0) and lp.shapes.shape == (25, 12, 24)
    for a, b in ((case.shapes, lp.shapes), (case.profile["wind"], lp.profile["wind"])):
        full = (a * case.weights[None, :, None]).sum(axis=(1, 2))
        assert (b * lp.weights[None, :, None]).sum(axis=(1, 2)) == pytest.approx(full)


def test_max_load_factor_is_ecp_cU():
    """EIA's 2030 solve, TRE existing combined cycle, summer 2031: 0.927362 / 0.879999 / 0.852473 per committed GW."""
    h = np.tile(np.array([90.056, 74.6163, 65.6433]), (25, 3))
    f = 0.927362 * capacity.max_load_factor(h, 0.7)
    assert f[0, 3:6] == pytest.approx([0.927362, 0.8799, 0.8518], abs=2e-3)


def test_capacity_payment_levels_a_one_year_spike():
    """RMAVG: a 1,200 $/kW reserve dual for one year reaches the price levelized over the horizon, not as it is."""
    z = capacity.capacity_payment(np.array([1200.0]), np.array([500.0]), 15.7, np.array([38.0]))
    assert z[0] == pytest.approx(0.5 * 0.85 * 38.0 + 0.5 * 1700.0 / 15.7)
    z = capacity.capacity_payment(np.array([0.0]), np.array([0.0]), 15.7, np.array([38.0]))
    assert z[0] == pytest.approx(0.5 * 0.85 * 38.0)
