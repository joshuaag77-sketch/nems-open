"""CMM input readers, checked against the restart where the two overlap."""

import numpy as np
import pytest

from nems_open.coal import aimms_data as ad, inputs, mappings, state, steo
from nems_open.paths import REFERENCE_RUN
from nems_open.snapshot import Snapshot

pytestmark = pytest.mark.skipif(not (REFERENCE_RUN.exists() and state.COAL_AMS.exists()), reason="EIA checkout missing")


@pytest.fixture(scope="module")
def snap():
    return Snapshot()


@pytest.fixture(scope="module")
def data():
    return inputs.load()


def test_every_header_resolves_to_a_declaration(data):
    assert len(data.params) >= 200
    assert data.unresolved == []
    assert data.duplicates == []


def test_declarations_find_the_lag_identifiers():
    assert len(ad.declarations().lag_identifiers) == 131


def test_numeric_ids_with_underscores_stay_text():
    assert ad._value("3_4") == "3_4" and ad._value("12") == 12 and ad._value("1.5e2") == 150.0


def _units(snap, n):
    u = snap["COALEMM/EMM_CL_UNITS"]
    flat = b"".join(u[:, j].tobytes() for j in range(10))
    chunks = [flat[i:i + 10].decode("latin-1") for i in range(0, 10 * n, 10)]
    return [f"{c[:6].strip()}_{c[6:].strip()}" for c in chunks]


def test_plant_unit_list_is_the_restart_list(data, snap):
    n = int(snap["COALEMM/NUM_CMM_UNITS"])
    assert n == 533 and len(data.assignments["plantid_unitid"]) == 533
    assert _units(snap, n) == [str(x) for x in data.assignments["plantid_unitid"]]


def test_plant_region_and_profiles_match_the_restart(data, snap):
    units = _units(snap, 533)
    for param, key in (("ndreg_plant", "COALEMM/EMM_CL_CLRG"), ("plant_s_prof", "COALEMM/CMM_SDV_INDX"),
                       ("plant_l_prof", "COALEMM/CMM_LDV_INDX")):
        p, r = data.param(param), snap[key]
        assert sum(int(p[(u,)]) == int(r[i]) for i, u in enumerate(units)) == 533, param


def test_world_coal_prices_match_the_restart(data, snap):
    h, (m4, m11, tc, yrs) = mappings.dense("hclworld")
    checked = 0
    for t_i, t in enumerate(tc):
        r = snap[{1: "COALREP/WSCF", 2: "COALREP/WMCF"}[t]]
        for a, ma in enumerate(m4):
            for b, mb in enumerate(m11):
                for c, y in enumerate(yrs):
                    v = h[a, b, t_i, c]
                    if np.isnan(v) or y in (2013, 2014, 2015, 2022, 2023):   # history years the restart carries from a later vintage
                        continue
                    checked += 1
                    assert abs(v - r[ma - 1, mb - 1, y - 1990]) <= 0.01 + 1e-4 * abs(v)
    assert checked > 100


def test_clsteo_history_matches_steovars_exactly():
    s, r = steo.shipped(), steo.regenerate()
    for col, series in r.items():
        for y in range(1990, 2024):
            assert abs(s[col][y] - series[y]) <= 0.006 * max(1.0, abs(s[col][y])), (col, y)


def test_dense_helper_shapes(data):
    a, axes = mappings.dense("hclworld")
    assert a.shape == tuple(len(x) for x in axes)


# --- step 3: supply curves and rate escalators ---------------------------------------------

def test_base_year_step_six_price_is_the_calibrated_minemouth_price():
    from nems_open.coal import supply
    c = supply.curves()
    b = supply.base_year(c)
    assert len(c.keys) == 14
    assert np.allclose(b["sc_price"][:, 5], c.v["mmp92"], atol=1e-8)       # CALK makes this an identity
    # Curves slope up from step 3. Steps 1 and 2 dip below step 1 on three Western curves: the utilization
    # term has a minimum at low output in the equation as written (coal.ams 19120), so this is not a port error.
    assert (np.diff(b["sc_price"][:, 2:], axis=1) >= -1e-9).all()
    assert (b["sc_quan"] >= 0).all()
    assert np.allclose(b["t_quan"][:, 5], c.v["prod_cap"] * c.v["cap_util"])


def test_base_year_prices_are_plausible_and_steps_follow_the_input():
    from nems_open.coal import supply
    b = supply.base_year()
    assert np.allclose(supply.step_sizes(), [-.54, -.27, -.09, -.03, -.01, 0, .01, .03, .09, .27, .54])
    per_mmbtu = b["sc_1_price87"][:, 5]
    assert 0.1 < per_mmbtu.min() and per_mmbtu.max() < 3.0                # 1987 $/MMBtu


def test_rcaf_shares_start_at_the_input_weights_and_roll_forward():
    from nems_open.coal import transport
    data = inputs.load()
    r = transport.rcaf()
    b = transport.RCAF_BASE_YR - 1990
    assert abs(r["total_a"][b] - sum(float(data.param(f"wt_{n}")[(transport.RCAF_BASE_YR,)]) for n in transport.COMPONENTS)) < 1e-12
    assert (r["cum"][: b + 1] == 1.0).all()
    # one year by hand: total_b = total_a ratio + productivity * pass-through
    i = 2030 - 1990
    assert abs(r["total_b"][i] - (r["total_a"][i] / r["total_a"][i - 1] + transport.RR_PRODUCTIVITY * r["productivity_pct"][i])) < 1e-12
    assert abs(r["cum"][i] - r["total_b"][i] * r["cum"][i - 1]) < 1e-12


def test_productivity_pass_through_limits():
    from nems_open.coal import transport
    falling = 100.0 * 0.9 ** np.arange(10)
    rising = 100.0 * 1.1 ** np.arange(10)
    assert transport.productivity_pass_through(falling)[-1] == 0.5
    assert transport.productivity_pass_through(rising)[-1] == 0.0
