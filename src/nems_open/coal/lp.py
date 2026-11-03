"""A reduced version of the CMM distribution LP (PartialLeastCostDomesticCoal) in linopy + HiGHS.

What is in: the 14 supply curves with their 11 priced production steps and capacity limit; shipments from
curves to the 16 coal demand regions for electric power, residential/commercial (R1, R2), industrial (I1 to I3)
and coking (C1, C2); first-tier transport rates scaled by the RCAF escalator; US exports as fixed amounts out of
each supply region. What is left out, and logged in docs/coal_lp.md: second-tier electricity transport, contracts,
diversity limits, activated carbon and SO2/Hg equations, STEO calibration, coal-to-liquids, imports and the
international export network, and all escape variables (the model must be feasible without them).

Units follow the AIMMS model: quantities in TBtu, prices in 1987$/MMBtu, so the objective is million 1987$.
"""

from dataclasses import dataclass

import numpy as np
import pandas as pd

import linopy
import xarray as xr

from nems_open.coal import inputs, supply, transport
from nems_open.coal.macro import Macro

NON_ELEC = ("R1", "R2", "I1", "I2", "I3", "C1", "C2")
SEC_GROUP = {"R1": "R", "R2": "R", "I1": "I", "I2": "I", "I3": "I", "C1": "C", "C2": "C"}


@dataclass
class Demand:
    regions: list                 # 16 coal demand regions
    elec: np.ndarray              # (16,) TBtu
    other: dict                   # sector -> (16,) TBtu
    exports: np.ndarray           # (6,) TBtu by supply region 1APN..6WSR
    sregs: list


def demands(year: int, macro: Macro | None = None, data=None) -> Demand:
    macro, data = macro or Macro(), data or inputs.load()
    s, yi = macro.s, year - 1990
    names = [data.assignments["map_ndregn"][i] if False else v for (i,), v in sorted(data.param("map_ndregn").items())]
    q = np.asarray(s["COALEMM/qclclnr"])[:, yi, :].sum(axis=1)
    cd = {m: c for (m, c), v in data.param("map_mnumcr_censdiv").items() if v == 1 and m <= 9}
    share, fradi = data.param("censdivshare"), data.param("fradi")

    def cens(name):
        a = np.asarray(s[f"QBLK/{name}"], float)[:, yi]
        return {cd[m]: a[m - 1] for m in cd}

    qrs, qcm, qin, qrf, qmc = (cens(n) for n in ("QCLRS", "QCLCM", "QCLIN", "QCLRF", "QMCIN"))
    base = {"R": {c: qrs[c] + qcm[c] for c in qrs}, "I": {c: qin[c] - qrf[c] for c in qin}, "C": qmc}
    other = {}
    for sec in NON_ELEC:
        g = SEC_GROUP[sec]
        other[sec] = np.array([sum(base[g][c] * fradi.get((d, sec), 0.0) * share.get((g, c, d), 0.0) for c in base[g])
                               for d in names])
    prod2, prod = np.asarray(s["COALREP/COALPROD2"])[:, :, yi], np.asarray(s["COALREP/COALPROD"])[:, :, yi]
    exp_mt = (prod2 - prod)[:10, :6].sum(axis=0)   # rows 1 to 10 are demand divisions; row 11 is production by supply region
    return Demand(names, q, other, exp_mt, ["1APN", "2APR", "3INR", "4LGN", "5PRB", "6WSR"])


def solve(year: int, step: dict, btu: np.ndarray, keys: list, dem: Demand, data=None, rcaf: float | None = None,
          solver: str = "highs", steo: dict | None = None, tolerance: float = 0.02) -> dict:
    """Solve one year. `step` has sc_quan, sc_1_price87 and cap (tons) as from supply.base_year/Chain.year."""
    data = data or inputs.load()
    rcaf = rcaf if rcaf is not None else float(transport.rcaf()["cum"][year - 1990])
    nc, nd = len(keys), len(dem.regions)
    cap_tbtu = (step.get("cap") if "cap" in step else np.array([k for k in btu * 0])) * btu
    price = np.asarray(step["sc_1_price87"])
    qstep = np.asarray(step["sc_quan"]) * btu[:, None]

    trate2, trate1, flag = data.param("trate2"), data.param("trate1"), data.param("coalgroupflag")
    ship = {}          # (sector, c, d) -> rate per MMBtu
    for ci, k in enumerate(keys):
        sreg, sulf, mtyp, rank = k[1:]
        for di, d in enumerate(dem.regions):
            r = trate2.get((sreg, sulf, mtyp, rank, d, "E"))
            if r is not None and r < 900 and rank != "4P":
                ship[("E", ci, di)] = r * rcaf / btu[ci]
            for sec in NON_ELEC:
                if flag.get((d, sec, sreg, sulf, mtyp, rank)) == -1:
                    r = trate1.get((sreg, sulf, mtyp, rank, d, sec), 0.0)
                    if r < 900:
                        ship[(sec, ci, di)] = max(r, 0.0) * rcaf / btu[ci]

    m = linopy.Model()
    P = m.add_variables(lower=0, upper=qstep, name="P", coords=[pd.RangeIndex(nc, name="c"), pd.RangeIndex(qstep.shape[1], name="s")])
    idx = pd.RangeIndex(len(ship), name="k")
    X = m.add_variables(lower=0, coords=[idx], name="X")
    E = m.add_variables(lower=0, coords=[pd.RangeIndex(nc, name="c")], name="E")
    m.add_constraints(P.sum("s") <= cap_tbtu, name="cap")

    sec_c, sec_d = np.array([i[0] for i in ship]), np.array([i[2] for i in ship])
    cur = np.array([i[1] for i in ship])
    # curve balance: shipments + exports = production
    cons_bal = {}
    for ci in range(nc):
        sel = np.where(cur == ci)[0]
        lhs = E.isel(c=ci) - P.isel(c=ci).sum()
        if len(sel):
            lhs = lhs + X.isel(k=sel).sum()
        cons_bal[ci] = m.add_constraints(lhs == 0, name=f"bal{ci}")
    sreg_idx = {s: [i for i, k in enumerate(keys) if k[1] == s] for s in dem.sregs}
    for si, s in enumerate(dem.sregs):
        avg_btu = btu[sreg_idx[s]].mean()
        m.add_constraints(E.isel(c=sreg_idx[s]).sum() == dem.exports[si] * avg_btu, name=f"exp{si}")

    demand_cons = {}
    for sec in ("E",) + NON_ELEC:
        target = dem.elec if sec == "E" else dem.other[sec]
        for di in range(nd):
            sel = np.where((sec_c == sec) & (sec_d == di))[0]
            if target[di] <= 1e-9 and not len(sel):
                continue
            if not len(sel):
                continue
            lhs = X.isel(k=sel).sum()
            op = (lhs >= target[di]) if sec in ("I1", "I2", "I3", "C1", "C2") else (lhs == target[di])
            demand_cons[(sec, di)] = m.add_constraints(op, name=f"dem_{sec}_{di}")

    stock_cost = 0
    if steo:                                  # STEO production bands by region group, with priced stock slack
        groups = {"Appalachia": (("1APN", "2APR"), 14.0), "Interior": (("3INR", "4LGN"), 12.0), "West": (("5PRB", "6WSR"), 8.0)}
        for g, (regs, cost) in groups.items():
            sel = [i for i, k in enumerate(keys) if k[1] in regs and k[4] != "5G"]
            w = xr.DataArray(1.0 / btu, coords=[pd.RangeIndex(nc, name="c")])
            prod_mt = (P * w).isel(c=sel).sum()
            hi = m.add_variables(lower=0, name=f"stk_hi_{g}")
            lo = m.add_variables(lower=0, name=f"stk_lo_{g}")
            m.add_constraints(prod_mt + hi - lo >= steo[g] * (1 - tolerance), name=f"steo_lo_{g}")
            m.add_constraints(prod_mt + hi - lo <= steo[g] * (1 + tolerance), name=f"steo_hi_{g}")
            stock_cost = stock_cost + cost * (hi + lo)
    obj = stock_cost + (P * price).sum() + (X * xr.DataArray(np.array(list(ship.values())), coords=[idx])).sum()
    m.add_objective(obj)
    status, cond = m.solve(solver_name=solver, io_api="lp")
    out = dict(status=status, cond=cond, objective=float(m.objective.value) if status == "ok" else np.nan)
    if status != "ok":
        return out
    p = P.solution.values
    x = pd.Series(X.solution.values, index=pd.MultiIndex.from_tuples(list(ship), names=['sec', 'c', 'd']))
    out.update(production_tbtu=p.sum(axis=1), steps=p, exports=E.solution.values, shipments=x, ship=ship, keys=keys,
               dual={k: float(c.dual.values) for k, c in demand_cons.items()}, dem=dem,
               production_tons=p.sum(axis=1) / btu)
    return out
