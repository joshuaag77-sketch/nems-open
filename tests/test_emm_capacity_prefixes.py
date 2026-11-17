"""Restart capacity is read once per unit.

EIA's UCAP tally (util.f) adds each unit to its main group's array and, for some types, to a subgroup array too
(UCAPCC holds ACC, ACS and AC2 units, which also go to UCAPAC, UCAPAS and UCAPA2; UCAPCT holds ACT and CTA, also in
UCAPAT and UCAPT2; UCAPCS holds CAV, COQ and CAS). Reading main and subgroup together counted about 345 GW of gas
capacity twice by 2049, which is where the capacity LP's 380 GW reserve surplus in 2050 came from.
"""

import numpy as np
import pytest

from nems_open.emm import capacity, capacity_report as rep, dispatch, history
from nems_open.paths import INPUT, REFERENCE_RUN

NUM_R = dispatch.NUM_R
_HAVE_INPUTS = (INPUT / "emm" / "emm_db" / "NEMS_INPUT.db").exists() and REFERENCE_RUN.exists()
needs_inputs = pytest.mark.skipif(not _HAVE_INPUTS, reason="EMM inputs missing")

# ECP's reserve requirement for 2050 in the AIMMS oracle (sum over regions of rRXXXXXge.Lower for planning year 2
# in OutToNEMS_2049.txt; the row binds in all 25 regions).
ECP_REQUIREMENT_2050_GW = 1270.1


class FakeSnapshot(dict):
    def __getitem__(self, key):
        return dict.__getitem__(self, key)


def _fake(values: dict, years: int = 3) -> FakeSnapshot:
    s = FakeSnapshot()
    for name, v in values.items():
        s[f"UDATOUT/ucap{name}"] = np.full((28, years), float(v))
    return s


def test_minus_prefix_is_subtracted():
    s = _fake({"ccn": 10.0, "asn": 3.0, "fcn": 0.5, "acn": 4.0})
    assert dispatch._ucap(s, ("cc", "-as", "fc"), 1) == pytest.approx(np.full(NUM_R, 7.5))
    assert dispatch._ucap(s, ("as",), 1) == pytest.approx(np.full(NUM_R, 3.0))


def test_subtraction_never_goes_negative():
    s = _fake({"ccu": 1.0, "asn": 3.0})
    assert (dispatch._ucap(s, ("cc", "-as"), 0) == 0.0).all()


def test_no_group_reads_a_main_array_and_its_subgroup():
    for group, prefixes in dispatch.CAPACITY_PREFIXES.items():
        plus = {p for p in prefixes if not p.startswith("-")}
        for main, subs in dispatch.CAPACITY_SUBGROUPS.items():
            if main in plus:
                assert not plus & set(subs), f"{group} reads {main} and its subgroup {plus & set(subs)}"
    for name, (prefixes, _) in rep.ADD_CATEGORIES.items():
        plus = {p for p in prefixes if not p.startswith("-")}
        for main, subs in dispatch.CAPACITY_SUBGROUPS.items():
            if main in plus:
                assert not plus & set(subs), f"{name} adds {main} and its subgroup {plus & set(subs)}"


def test_ccs_is_taken_out_of_combined_cycle_once():
    """gas_cc and gas_ccs together are the whole UCAPCC array (plus fuel cells), with nothing counted twice."""
    s = _fake({"ccn": 20.0, "acn": 6.0, "asn": 2.0, "fcn": 0.1})
    p = dispatch.CAPACITY_PREFIXES
    total = dispatch._ucap(s, p["gas_cc"], 0) + dispatch._ucap(s, p["gas_ccs"], 0)
    assert total == pytest.approx(np.full(NUM_R, 20.1))


@needs_inputs
def test_restart_subgroups_sit_inside_their_main_group():
    from nems_open.snapshot import Snapshot
    s = Snapshot()
    for year in range(2025, 2051):
        y = year - history.FIRST_YEAR
        for main, subs in dispatch.CAPACITY_SUBGROUPS.items():
            gap = dispatch._ucap(s, (main,), y) - dispatch._ucap(s, subs, y)
            assert (gap > -1e-3).all(), f"{year}: {subs} exceed {main}"


@needs_inputs
def test_2049_fleet_counts_each_gas_unit_once():
    from nems_open.snapshot import Snapshot
    s = Snapshot()
    y = 2049 - history.FIRST_YEAR
    cap = capacity.initial_capacity(s, 2049)
    one = lambda *p: float(dispatch._ucap(s, p, y).sum())
    assert cap["gas_cc"].sum() + cap["gas_ccs"].sum() == pytest.approx(one("cc", "fc"), abs=0.1)
    assert cap["gas_ct"].sum() == pytest.approx(one("ct", "ic", "i2"), abs=0.1)
    thermal = sum(float(cap[g].sum()) for g in dispatch.THERMAL)
    assert 860 < thermal < 895                         # 877.5 GW; it was 1,222.5 with the subgroups added on top
    # Before the fix the thermal fleet, nuclear, hydro and pumped storage alone exceeded ECP's whole 2050
    # requirement, so the LP saw a surplus however low the wind, solar and battery credits. Now they do not.
    firm_without_variable = thermal + float(cap["nuclear"].sum() + cap["hydro"].sum() + cap["pumped"].sum())
    assert firm_without_variable < ECP_REQUIREMENT_2050_GW


@needs_inputs
def test_eia_turbine_additions_are_not_double_counted():
    from nems_open.snapshot import Snapshot
    s = Snapshot()
    y = 2035 - history.FIRST_YEAR
    def uadd(p):
        total = 0.0
        for o in "un":
            try:
                total += float(s[f"UECPOUT/uadd{p}{o}"][:, 27, y].sum())
            except KeyError:
                pass
        return total

    turbines = rep.eia_additions(s, 2035, rep.ADD_CATEGORIES["Gas turbines"][0])
    assert turbines == pytest.approx(uadd("ct") + uadd("ic"), abs=0.1)
    assert 60 < turbines < 75                          # 67 GW by 2035, not 120
    cc = rep.eia_additions(s, 2035, rep.ADD_CATEGORIES["Gas combined cycle"][0])
    ccs = rep.eia_additions(s, 2035, rep.ADD_CATEGORIES["Gas combined cycle with CCS"][0])
    assert cc + ccs == pytest.approx(uadd("cc"), abs=0.1)
