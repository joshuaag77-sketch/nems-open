"""Fit the gas market's few coefficients on EIA's AEO2026 cases and check it on them.

    python -m nems_open.ngmm.fit        # writes coefficients.json and prints the checks

What is fitted, all on years 2027-2050 against cb2026:
    k               dry production per Bcf of extra use or exports (demand cases)
    hh_per_wellhead Henry Hub change per dollar of wellhead change (all cases)
    exports_up/down LNG and pipeline export elasticity to the wellhead price (lowogs above, highogs below)
    eps_long_run    HSM's expected production against the run's last `lag` years of prices: the value on
                    EPS_GRID that best reproduces the demand cases' Henry Hub paths when simulated year by
                    year (a one-step regression gives 0.59, attenuated by noise, and misses lowztc by 10%).
                    Above about 1.4 the lagged response and the steep short-run curve cobweb.
    pass_through    each delivered gas price's share of the Henry Hub change, by census division (all cases)
"""
import json

import numpy as np

from nems_open.ngmm import data
from nems_open.ngmm.market import COEFFICIENTS, EXPORTS, GasMarket, gas_price_names
from nems_open.supply_standin.data import CASES, FIRST_YEAR, US

DEMAND_CASES = ("hm2026", "lm2026", "higheldmd", "highztc", "lowztc", "altelec", "electrnp")
SUPPLY_CASES = ("highogs", "lowogs")
YEARS = np.arange(2027 - FIRST_YEAR, 61)
LAG = 2
EPS_GRID = np.round(np.arange(0.4, 1.21, 0.05), 2)


def slope(x, y) -> float:
    x, y = np.ravel(x), np.ravel(y)
    return float(x @ y / (x @ x)) if x @ x > 0 else 0.0


def fit() -> dict:
    b = data.load("cb2026")
    cases = {c: data.load(c) for c in CASES if c != "cb2026"}
    g = lambda z, k: z["NGTDMREP/" + k]
    j = YEARS
    # k: production change per unit change of use plus exports
    x, y = [], []
    for c in DEMAND_CASES:
        z = cases[c]
        dD = (z["QBLK/qngas"][US, j] - b["QBLK/qngas"][US, j]) / b["CONVFACT/cfngc"][j]
        dX = z[EXPORTS][3, j] - b[EXPORTS][3, j]
        x.append(dD + dX)
        y.append(g(z, "ngscrv_q")[j] - g(b, "ngscrv_q")[j])
    k = slope(x, y)
    # Henry Hub per wellhead dollar
    x = [g(z, "ngscrv_p")[j] - g(b, "ngscrv_p")[j] for z in cases.values()]
    y = [g(z, "oghhprng")[j] - g(b, "oghhprng")[j] for z in cases.values()]
    hh = slope(x, y)
    # exports
    ex = {}
    for name, c, side in (("exports_up", "lowogs", 1), ("exports_down", "highogs", -1)):
        z = cases[c]
        lp = np.log(g(z, "ngscrv_p")[j] / g(b, "ngscrv_p")[j])
        lx = np.log(z[EXPORTS][3, j] / b[EXPORTS][3, j])
        m = side * lp > 0
        ex[name] = slope(lp[m], lx[m])
    eps = None   # set by calibrate() once the rest is written
    # delivered prices' share of the Henry Hub change
    dhh = np.array([g(z, "oghhprng")[j] - g(b, "oghhprng")[j] for z in cases.values()])   # (cases, years)
    pt = {}
    for name in gas_price_names(b):
        share = np.zeros(11)
        for r in range(11):
            if b[name][r, j].min() <= 0:
                continue
            dp = np.array([z[name][r, j] - b[name][r, j] for z in cases.values()])
            share[r] = round(slope(dhh, dp), 4)
        pt[name] = share.tolist()
    return {"k": round(k, 4), "hh_per_wellhead": round(hh, 4), "exports_up": round(ex["exports_up"], 4),
            "exports_down": round(ex["exports_down"], 4), "eps_long_run": eps, "lag": LAG,
            "pass_through": pt}


def calibrate(coef: dict) -> float:
    """eps_long_run: the grid value with the smallest mean absolute Henry Hub error over the demand cases."""
    tmp = COEFFICIENTS.with_name("coefficients.tmp.json")
    tmp.write_text(json.dumps({**coef, "eps_long_run": 1.0}))
    m = GasMarket(coefficients=tmp)
    tmp.unlink()
    zs = [data.load(c) for c in DEMAND_CASES]
    best = None
    for eps in EPS_GRID:
        m.eps = float(eps)
        err = np.mean([np.mean(np.abs(m.simulate(z["QBLK/qngas"][US])["henry_hub"][YEARS] / z["NGTDMREP/oghhprng"][YEARS] - 1))
                       for z in zs])
        if best is None or err < best[1]:
            best = (float(eps), err)
    return best[0]


def check(market: GasMarket | None = None) -> dict:
    """Each AEO2026 case's own gas use through the market, year by year. Demand cases use the fitted
    long-run response; the two supply cases get their own expected production (as HSM would hand it)."""
    m = market or GasMarket()
    b = data.load("cb2026")
    out = {}
    for c in CASES:
        if c == "cb2026":
            continue
        z = data.load(c)
        m.reset()
        if c in SUPPLY_CASES:   # as if HSM had run on the case's own prices
            ratio = np.divide(z["NGTDMREP/ngscrv_q0"], b["NGTDMREP/ngscrv_q0"], out=np.ones(61), where=b["NGTDMREP/ngscrv_q0"] > 0)
            m.set_hsm(ratio, z["NGTDMREP/ngscrv_p"])
            m.P[:YEARS[0]] = z["NGTDMREP/ngscrv_p"][:YEARS[0]]   # the case's own history before 2027
            for i in YEARS:
                res = m.clear(z["QBLK/qngas"][US])
                m.settle(i)
            p = m.prices(z["QBLK/qngas"][US])
        else:
            res = m.simulate(z["QBLK/qngas"][US])
            p = m.prices(z["QBLK/qngas"][US])
        j = 2050 - FIRST_YEAR
        hh_eia, hh = z["NGTDMREP/oghhprng"][j], res["henry_hub"][j]
        out[c] = {"hh_2050": round(float(hh), 3), "hh_2050_eia": round(float(hh_eia), 3),
                  "hh_err_pct": round(100 * float(hh / hh_eia - 1), 1),
                  "hh_mean_abs_err_pct": round(100 * float(np.mean(np.abs(res["henry_hub"][YEARS] / z["NGTDMREP/oghhprng"][YEARS] - 1))), 1),
                  "pngrs_err_pct": round(100 * float(p["MPBLK/pngrs"][US, j] / z["MPBLK/pngrs"][US, j] - 1), 1),
                  "pngel_err_pct": round(100 * float(p["MPBLK/pngel"][US, j] / z["MPBLK/pngel"][US, j] - 1), 1),
                  "hh_move_pct_eia": round(100 * float(hh_eia / b["NGTDMREP/oghhprng"][j] - 1), 1),
                  "hh_move_pct_ours": round(100 * float(hh / b["NGTDMREP/oghhprng"][j] - 1), 1)}
    return out


def main():
    c = fit()
    c["eps_long_run"] = calibrate(c)
    meta = {k: v for k, v in c.items() if k != "pass_through"}
    COEFFICIENTS.write_text(json.dumps(c, indent=1) + "\n")
    print(json.dumps(meta, indent=1))
    print({k: v[US] for k, v in c["pass_through"].items()})
    for case, r in check().items():
        print(case, r)


if __name__ == "__main__":
    main()
