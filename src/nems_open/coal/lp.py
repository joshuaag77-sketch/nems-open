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
          solver: str = "highs", steo: dict | None = None, tolerance: float = 0.02, power=None,
          tier1: np.ndarray | None = None) -> dict:
    """Solve one year. `step` has sc_quan, sc_1_price87 and cap (tons) as from supply.base_year/Chain.year.
    power: an electric.PowerDemand. Given, electricity demand is met per plant type and region and the
    sub-bituminous and lignite diversity caps apply (coal.ams SubbituminousDiversity, LigniteDiversity),
    each with a 999 slack (EIA's has none; the slack is reported and should stay zero); dem.elec is then
    ignored. Without it, one electricity demand per region as before.
    tier1: electric.tier1_bound, (curves, 16) TBtu. Given, electricity deliveries from a curve to a region
    above it pay the second-tier premium max(trate3 - trate2, 0) * RCAF per MMBtu (coal.ams
    TransportationBound*, BalanceScrubUnscrubTier*, MakeSureSecondTierGetsFirstTierPrice)."""
    data = data or inputs.load()
    rcaf = rcaf if rcaf is not None else float(transport.rcaf()["cum"][year - 1990])
    nc, nd = len(keys), len(dem.regions)
    cap_tbtu = (step.get("cap") if "cap" in step else np.array([k for k in btu * 0])) * btu
    price = np.asarray(step["sc_1_price87"])
    qstep = np.asarray(step["sc_quan"]) * btu[:, None]

    trate2, trate1, flag = data.param("trate2"), data.param("trate1"), data.param("coalgroupflag")
    trate3 = data.param("trate3")
    tier2 = {}         # (c, d) -> second-tier premium per MMBtu, where positive
    ship = {}          # (sector, c, d, plant type or -1) -> rate per MMBtu
    types = {di: ([t for t in range(power.demand.shape[1]) if power.demand[di, t] > 0] if power is not None else [-1])
             for di in range(len(dem.regions))}
    for ci, k in enumerate(keys):
        sreg, sulf, mtyp, rank = k[1:]
        for di, d in enumerate(dem.regions):
            r = trate2.get((sreg, sulf, mtyp, rank, d, "E"))
            if r is not None and r < 900 and rank != "4P":
                for t in types[di]:
                    ship[("E", ci, di, t)] = r * rcaf / btu[ci]
                r3 = trate3.get((sreg, sulf, mtyp, rank, d, "E"))
                if tier1 is not None and r3 is not None and r3 - r > 0:
                    tier2[(ci, di)] = (r3 - r) * rcaf / btu[ci]
            for sec in NON_ELEC:
                if flag.get((d, sec, sreg, sulf, mtyp, rank)) == -1:
                    r = trate1.get((sreg, sulf, mtyp, rank, d, sec), 0.0)
                    if r < 900:
                        ship[(sec, ci, di, -1)] = max(r, 0.0) * rcaf / btu[ci]

    m = linopy.Model()
    P = m.add_variables(lower=0, upper=qstep, name="P", coords=[pd.RangeIndex(nc, name="c"), pd.RangeIndex(qstep.shape[1], name="s")])
    idx = pd.RangeIndex(len(ship), name="k")
    X = m.add_variables(lower=0, coords=[idx], name="X")
    E = m.add_variables(lower=0, coords=[pd.RangeIndex(nc, name="c")], name="E")
    m.add_constraints(P.sum("s") <= cap_tbtu, name="cap")

    ship_keys = list(ship)
    sec_c, sec_d, sec_t = np.array([i[0] for i in ship]), np.array([i[2] for i in ship]), np.array([i[3] for i in ship])
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

    demand_cons, type_cons, slack_cost, slacks = {}, {}, 0, {}
    if power is not None:
        rank = np.array([keys[i[1]][4] for i in ship])
        for di in range(nd):
            for t in types[di]:
                sel = np.where((sec_c == "E") & (sec_d == di) & (sec_t == t))[0]
                if not len(sel):
                    continue
                type_cons[(di, t)] = m.add_constraints(X.isel(k=sel).sum() == power.demand[di, t], name=f"dem_E_{di}_{t}")
                for kind, ranks, cap, on in (("sub", ("2S",), power.sub_cap, power.sub_active[di, t]),
                                             ("lig", ("3L", "5G"), power.lig_cap, True)):
                    cs = sel[np.isin(rank[sel], ranks)]
                    if not on or not len(cs):
                        continue
                    sl = m.add_variables(lower=0, name=f"slack_{kind}_{di}_{t}")
                    m.add_constraints(X.isel(k=cs).sum() - sl <= cap[di, t], name=f"div_{kind}_{di}_{t}")
                    slack_cost = slack_cost + 999.0 * sl
                    slacks[(kind, di, t)] = sl
    tier_cost = 0
    if tier1 is not None and tier2:
        e_idx = np.where(sec_c == "E")[0]
        cd = [(ship_keys[k][1], ship_keys[k][2]) for k in e_idx]
        idx2 = np.array([k for k, g in zip(e_idx, cd) if g in tier2])
        X2 = m.add_variables(lower=0, coords=[pd.Index(idx2, name="k")], name="X2")
        m.add_constraints(X2 - X.sel(k=idx2) <= 0, name="tier2_le_tier1")
        prem = xr.DataArray(np.array([tier2[(ship_keys[k][1], ship_keys[k][2])] for k in idx2]), coords=[pd.Index(idx2, name="k")])
        tier_cost = (X2 * prem).sum()
        groups: dict = {}
        for k in idx2:
            groups.setdefault((ship_keys[k][1], ship_keys[k][2]), []).append(k)
        for (ci, di), ks in groups.items():
            m.add_constraints(X.sel(k=ks).sum() - X2.sel(k=ks).sum() <= tier1[ci, di], name=f"trubnd_{ci}_{di}")
    for sec in (() if power is not None else ("E",)) + NON_ELEC:
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
    obj = stock_cost + slack_cost + tier_cost + (P * price).sum() + (X * xr.DataArray(np.array(list(ship.values())), coords=[idx])).sum()
    m.add_objective(obj)
    status, cond = m.solve(solver_name=solver, io_api="lp")
    out = dict(status=status, cond=cond, objective=float(m.objective.value) if status == "ok" else np.nan)
    if status != "ok":
        return out
    p = P.solution.values
    x = pd.Series(X.solution.values, index=pd.MultiIndex.from_tuples(list(ship), names=['sec', 'c', 'd', 't']))
    dual = {k: float(c.dual.values) for k, c in demand_cons.items()}
    if power is not None:   # one electricity price per region: the plant-type duals weighted by demand
        for di in range(nd):
            short = {t for (_, d2, t), v in slacks.items() if d2 == di and float(v.solution.values) > 1e-6}
            # a cell that needed the 999 slack prices at the slack, not at coal: left out of the average
            w = [(power.demand[di, t], float(type_cons[(di, t)].dual.values)) for t in types[di]
                 if (di, t) in type_cons and t not in short]
            if w and sum(a for a, _ in w) > 0:
                dual[("E", di)] = sum(a * b for a, b in w) / sum(a for a, _ in w)
        out["dual_type"] = {k: float(c.dual.values) for k, c in type_cons.items()}
        out["slack"] = {k: float(v.solution.values) for k, v in slacks.items()}
    out.update(production_tbtu=p.sum(axis=1), steps=p, exports=E.solution.values, shipments=x, ship=ship, keys=keys,
               dual=dual, dem=dem,
               production_tons=p.sum(axis=1) / btu)
    return out
