"""Fit the LFMM stand-in on EIA's AEO2026 cases and report how well it holds out.

Prices: dP - dBrent/heat = a * P0 * dlog Q_own, US, 2027-2050, every side case, OLS with no
intercept (each case's deviation from the reference), a kept at zero or above. Refinery fuel:
dlog Q_ts and dlog Q_el on dlog liquids demand; dlog of the gas share on dlog(P_gas_ind / Brent).

Held-out test: leave one case out, refit, predict that case from its own end-use demand, Brent
and gas price (the inputs the loop would hand LFMM), and report the largest US error 2027-2050.

    python -m nems_open.lfmm.fit        # rewrites coefficients.json and docs/lfmm_fit.md
"""

import json

import numpy as np

from nems_open.lfmm.standin import (COEFFICIENTS, PRODUCTS, RF_FITTED, LfmmStandin, dlog, gas_share,
                                    price_regressors, rf_regressors)
from nems_open.paths import REPO_ROOT
from nems_open.supply_standin.data import CASES, US, load_case

YEARS = slice(2027 - 1990, 2050 - 1990 + 1)
SIDE = [c for c in CASES if c != "cb2026"]
REPORT = REPO_ROOT / "docs" / "lfmm_fit.md"
LABEL = {"mg": "Gasoline", "ds": "Diesel", "jf": "Jet fuel", "rs": "Residual",
         "tp": "Refinery petroleum", "ng": "Refinery natural gas", "el": "Refinery electricity"}


def _slope(x, y):
    """One-regressor OLS with no intercept: (coefficient, R2)."""
    coef = float(x @ y / (x @ x)) if x @ x > 0 else 0.0
    r2 = 1 - float(np.sum((y - coef * x) ** 2) / np.sum(y ** 2)) if np.sum(y ** 2) > 0 else 0.0
    return coef, r2


def price_rows(product, cases, ref):
    """x = P0 * dlog Q_own; y = the price change net of the crude pass-through."""
    x, y = [], []
    name = PRODUCTS[product][2]
    for c in cases:
        z = load_case(c)
        r = price_regressors(product, z, z["INTOUT/brent_price"], ref)
        x.append(r["own"][YEARS])
        y.append(z[name][US, YEARS] - ref[name][US, YEARS] - r["crude"][YEARS])
    return np.concatenate(x), np.concatenate(y)


def rf_rows(target, cases, ref):
    x, y = [], []
    for c in cases:
        z = load_case(c)
        r = rf_regressors(z, z["INTOUT/brent_price"], z["MPBLK/pngin"][US], ref)
        if target == "ng":
            x.append(r["gas_crude"][YEARS])
            y.append(dlog(gas_share(z)[YEARS], gas_share(ref)[YEARS]))
        else:
            x.append(r["liq"][YEARS])
            y.append(dlog(z[f"QBLK/q{target}rf"][US, YEARS], ref[f"QBLK/q{target}rf"][US, YEARS]))
    return np.concatenate(x), np.concatenate(y)


def fit(cases=SIDE) -> dict:
    ref = load_case("cb2026")
    out = {"prices": {}, "refinery": {}}
    for p in PRODUCTS:
        a, r2 = _slope(*price_rows(p, cases, ref))
        out["prices"][p] = {"coef": {"crude": 1.0, "own": max(a, 0.0)}, "r2": r2, "own_unconstrained": a}
    for target, key in (("ts", "liq"), ("el", "liq"), ("ng", "gas_crude")):
        e, r2 = _slope(*rf_rows(target, cases, ref))
        out["refinery"][target] = {"coef": {key: e}, "r2": r2}
    return out


def predict(model: LfmmStandin, case: str):
    z = load_case(case)
    return model.solve(z, z["INTOUT/brent_price"], z["MPBLK/pngin"][US])


def errors(model: LfmmStandin, case: str) -> dict[str, float]:
    """Largest US error 2027-2050, percent, per product price and refinery fuel."""
    z, r = load_case(case), predict(model, case)
    out = {}
    for p in PRODUCTS:
        name = PRODUCTS[p][2]
        out[p] = float(np.max(np.abs(r.prices[name][US, YEARS] / z[name][US, YEARS] - 1)) * 100)
    for f in RF_FITTED + ("ts",):
        k = f"QBLK/q{f}rf"
        out[f] = float(np.max(np.abs(r.refinery[k][US, YEARS] / z[k][US, YEARS] - 1)) * 100)
    return out


def held_out() -> dict[str, dict[str, float]]:
    import tempfile
    from pathlib import Path
    res = {}
    with tempfile.TemporaryDirectory() as d:
        path = Path(d) / "c.json"
        for c in SIDE:
            path.write_text(json.dumps(fit([s for s in SIDE if s != c])))
            res[c] = errors(LfmmStandin("cb2026", coefficients=path), c)
    return res


def write_report(coef: dict, loco: dict, insample: dict) -> None:
    keys = list(PRODUCTS) + list(RF_FITTED) + ["ts"]
    lab = {**LABEL, "ts": "Refinery energy, total"}
    lines = ["# LFMM stand-in fit", "",
             "Written by `python -m nems_open.lfmm.fit`. See [lfmm_plan.md](lfmm_plan.md) for the model.", "",
             "## Coefficients", "",
             "Prices: dP = dBrent/heat + a * P0 * dlog Q_own (US, 1987 $/MMBtu). Crude passes through dollar for dollar "
             "per barrel (set); a is fitted on what is left, kept at zero or above. R2 is of that remainder.", "",
             "| Product | a (own demand) | a before the floor | R2 |", "|---|---|---|---|"]
    for p, v in coef["prices"].items():
        lines.append(f"| {LABEL[p]} | {v['coef']['own']:.2f} | {v['own_unconstrained']:.2f} | {v['r2']:.2f} |")
    lines += ["", "Refinery fuel.", "",
              "| Equation | Coefficient | R2 |", "|---|---|---|"]
    rf = coef["refinery"]
    lines.append(f"| dlog total refinery energy = e * dlog liquids demand | {rf['ts']['coef']['liq']:.2f} | {rf['ts']['r2']:.2f} |")
    lines.append(f"| dlog refinery electricity = e * dlog liquids demand | {rf['el']['coef']['liq']:.2f} | {rf['el']['r2']:.2f} |")
    lines.append(f"| dlog gas share of refinery fuel = e * dlog(gas price to industry / Brent) | {rf['ng']['coef']['gas_crude']:.2f} | {rf['ng']['r2']:.2f} |")
    for title, tab in (("Held out (leave one case out)", loco), ("In sample", insample)):
        lines += ["", f"## {title}", "",
                  "Largest US error 2027-2050, percent, each case predicted from its own end-use demand, Brent and gas price.", "",
                  "| | " + " | ".join(SIDE) + " |", "|---" * (len(SIDE) + 1) + "|"]
        for k in keys:
            lines.append(f"| {lab[k]} | " + " | ".join(f"{tab[c][k]:.1f}" for c in SIDE) + " |")
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> None:
    coef = fit()
    COEFFICIENTS.write_text(json.dumps(coef, indent=2) + "\n")
    model = LfmmStandin("cb2026")
    insample = {c: errors(model, c) for c in SIDE}
    loco = held_out()
    write_report(coef, loco, insample)
    print(REPORT.read_text())


if __name__ == "__main__":
    main()
