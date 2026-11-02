"""Freight truck ports (tranfrt.f) vs the transportation oracle, stretch by stretch.

Dump points inside TRANFRT and TRUCK_NEW are before-only (hooks_tran.py ONLY_IN), so
a stretch runs from one point's "_in" to the next one reached that year. Points
inside TRUCK_NEW's GHG retry loop are taken on the first try.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.transportation import frt_act, frt_agg, frt_choice, frt_cost, frt_fuel, frt_new, frt_stock, frt_tech, frt_vmt
from tran_harness import YEARS, _blank_from, needs, run

pytestmark = needs("frt_tech")
RUN = "run_tran"
POINTS = ["tranfrt_in", "frt_new_in", "frt_tech_in", "frt_inc_in", "frt_choice_in", "frt_act_in", "frt_agg_in",
          "frt_ghg_in", "frt_stock_in", "frt_vmt_in", "frt_clt_in", "frt_fuel_in", "tranfrt_out"]
PBK = ["start_curve", "midyr_choice", "slope_choice", "midyr_adj"]
YEARLY = ["techpenyr_p2", "cpm_r_ice", "ttonmi", "tvmt", "temp_stk_vmt_ratio"] + frt_act.CARRY


def carry(y):
    """All of the freight module's saved locals, as they stood when year y started."""
    out = oracle_state.load("tranfrt_out", y, run=RUN)
    # Privates of routines not called in the run (TRUCK_ACT: ACT_switch is 0) or not yet
    # called by year y are absent; those routines start from zero.
    c = {k: _blank_from(out[f"p_{k}"], y) for k in YEARLY if f"p_{k}" in out}
    if "p_start_curve" not in out:
        # Privates are dumped only once their routine has run on a first iteration
        # (2020 is before TRUCK_CHOICE starts): take the next dump year's, cut at y.
        later = [z for z in YEARS if z > y and oracle_state.available("tranfrt_out", z, run=RUN)]
        if later:
            nxt = oracle_state.load("tranfrt_out", later[0], run=RUN)
            for k in YEARLY:
                if k not in c and f"p_{k}" in nxt:
                    c[k] = _blank_from(nxt[f"p_{k}"], y)
            c["ghgbank"] = _blank_from(nxt["p0_ghgbank"], y)
        return c
    c["ghgbank"] = out["p0_ghgbank"].copy()
    # TRUCK_PBK's curve history after this year's first-try calls: undo the curves that
    # started this year (their midpoint is this year plus half the curve length).
    st = {k: out[f"p_{k}"].copy() for k in ("start_curve", "midyr_choice", "slope_choice", "midyr_adj")}
    yrs = 1989 + y
    cy = oracle_state.load("frt_choice_in", y, run=RUN)["f_cyafvxg"] if oracle_state.available("frt_choice_in", y, run=RUN) else None
    if cy is not None:
        sc19 = oracle_state.load("frt_choice_in", y, run=RUN)["f_sc19map"]
        a = st["start_curve"].a
        for c19 in range(1, 20):
            isc4 = int(sc19[c19])
            for f in range(1, 13):
                for fl in (1, 2):
                    started_now = np.float32(yrs) + np.float32(cy[isc4, f, fl]) / np.float32(2.0)
                    sel = (a[c19 - 1, f - 1, fl - 1, :] != 0) & (st["midyr_choice"].a[c19 - 1, f - 1, fl - 1, :] == started_now)
                    a[c19 - 1, f - 1, fl - 1, sel] = 0
    # MIDYR_adj moves on GHG retries; its value at the year's start is dumped on a first-try call.
    st["midyr_adj"] = out["p0_midyr_adj"].copy()
    c.update(st)
    return c


def _pre_new(s, carry=None):
    frt_new.truck_new_pre(s)
    from nems_open.transportation.frt_common import V
    v = V(s)
    v["itryghg"] = 1
    v["hdv_passghg"][v.i("iyr"), :] = 0


def _act(s, carry):
    from nems_open.transportation.frt_common import V
    v = V(s)
    if v.i("act_switch") == 1 and v.i("yrs") >= 2021:
        frt_act.truck_act(s, carry)


def _fuel_and_post(s, carry=None):
    frt_fuel.truck_fuel(s)
    frt_new.tranfrt_post(s)


STRETCHES = {
    "tranfrt_pre": (lambda s, carry=None: frt_new.tranfrt_pre(s), "tranfrt_in"),
    "truck_new_pre": (_pre_new, "frt_new_in"),
    "techadopt": (frt_tech.truck_techadopt, "frt_tech_in"),
    "inccost": (lambda s, carry=None: frt_cost.truck_inccost(s), "frt_inc_in"),
    "choice": (frt_choice.truck_choice, "frt_choice_in"),
    "act": (_act, "frt_act_in"),
    "aggvars": (lambda s, carry=None: frt_agg.truck_aggvars(s), "frt_agg_in"),
    # The later GHG tries lean on saved locals the first try sets, so the loop is tested
    # whole: all of TRUCK_NEW, from its entry to the next point after it.
    "truck_new": (frt_new.truck_new, "frt_new_in"),
    "stock": (lambda s, carry=None: frt_stock.truck_stock(s), "frt_stock_in"),
    "vmt": (frt_vmt.truck_vmt, "frt_vmt_in"),
    "commcl": (lambda s, carry=None: frt_vmt.tcommcl_trk(s), "frt_clt_in"),
    "fuel_and_post": (_fuel_and_post, "frt_fuel_in"),
    "whole": (frt_new.tranfrt, "tranfrt_in"),
}


def _end(start, y, name):
    if name == "whole":
        return "tranfrt_out"
    if name == "truck_new":
        start = "frt_ghg_in"
    for p in POINTS[POINTS.index(start) + 1:]:
        if oracle_state.available(p, y, run=RUN):
            return p
    return None


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("name", list(STRETCHES))
def test_stretch(name, y):
    port, start = STRETCHES[name]
    end = _end(start, y, name)
    if not oracle_state.available(start, y, run=RUN) or end is None:
        pytest.skip(f"{start} not reached in {1989 + y}")
    # The act stretch's state depends on TRUCK_PBK's float32 logit; held to the 0.1% rule.
    tol = 1e-3 if name in ("truck_new", "whole", "choice", "act") else 1e-4
    c = None if name == "fuel_and_post" else carry(y)
    # TRUCK_PBK's curve history is dumped after the first GHG try, not at TRANFRT's end.
    skip = [f"p_{k}" for k in PBK] if name == "whole" else ()
    assert run(port, "tranfrt", y, start=start, end=end, tol=tol, carry=c, may_be_empty=True, skip=skip) == {}
