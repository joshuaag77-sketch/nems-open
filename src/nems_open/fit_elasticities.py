"""Fit the demand stub's price elasticities from EIA's AEO2026 side cases.

    python -m nems_open.fit_elasticities

Writes src/nems_open/demand_elasticities.json (read by demand_adapter.py) and
docs/demand_elasticities.md.

For each sector s and fuel f, over census divisions 1-9 and years 2027-2050:

    dlog Q[s,f] = e * L + g * dlog GDP,   L_t = (1 - k) L_{t-1} + k * dlog P[s,f]_t

that is, fuel use answers its own delivered price with a lag (each year closes a share
k of the gap to the long-run response e) and answers GDP. dlog is against the reference
run. e and g are OLS with no intercept; k is picked per sector from a grid, the value
that fits all of that sector's fuels best.

Cases: those where prices move for supply-side reasons, so the price change is not
caused by the demand change (high and low oil and gas supply, high and low zero-carbon
technology cost, alternative electricity), plus high and low economic growth, which
pin down g. AEO2026 has no high or low oil price case. Left out: high electricity
demand (demand shifted on purpose) and alternative electricity and transportation
(vehicle rules change transport demand directly).

Limits: the standard errors treat every division-year as independent, which they are
not (7 cases drive all the variation), so they overstate precision; own price only (no gas-electricity switching); the cases move gas and power
prices much more than oil prices, so oil-product elasticities rest on less variation.
"""

import json
from pathlib import Path

import numpy as np

from nems_open.paths import REPO_ROOT
from nems_open.supply_standin.data import FIRST_YEAR, US, load_case

OUT = Path(__file__).with_name("demand_elasticities.json")
REPORT = REPO_ROOT / "docs" / "demand_elasticities.md"
BASE = "cb2026"
CASES = ["highogs", "lowogs", "highztc", "lowztc", "altelec", "hm2026", "lm2026"]
LAG_FROM = 2025 - FIRST_YEAR
YEARS = slice(2027 - FIRST_YEAR, 2050 - FIRST_YEAR + 1)
REGIONS = slice(0, 9)
ADJUSTMENTS = [0.05, 0.1, 0.15, 0.2, 0.3, 0.4, 0.5, 0.7, 1.0]
FUELS = {
    "rs": ["el", "ng", "ds", "lg", "ks"],
    "cm": ["el", "ng", "ds", "lg", "rl"],
    "in": ["el", "ng", "ds", "lg", "cl", "rl", "mc"],
    "tr": ["mg", "ds", "jf", "rl", "lg", "ng", "el"],
}
MIN_US_TBTU = 50.0  # skip rows too small to say anything


def dlog(a, b):
    ok = (a > 0) & (b > 0)
    return np.where(ok, np.log(np.where(ok, a, 1.0) / np.where(ok, b, 1.0)), 0.0), ok


def lagged(x: np.ndarray, k: float) -> np.ndarray:
    """Koyck lag along the year axis, starting from zero in 2025."""
    out = np.zeros_like(x)
    for j in range(LAG_FROM, x.shape[-1]):
        out[..., j] = (1 - k) * out[..., j - 1] + k * x[..., j]
    return out


def rows(s: str, f: str, k: float):
    base = load_case(BASE)
    q, p = f"QBLK/q{f}{s}", f"MPBLK/p{f}{s}"
    if q not in base or p not in base or base[q][US, YEARS].mean() < MIN_US_TBTU:
        return None
    X, Y = [], []
    for c in CASES:
        z = load_case(c)
        y, okq = dlog(z[q], base[q])
        x, okp = dlog(z[p], base[p])
        gdp = np.log(z["MACOUT/mc_gdpr"] / base["MACOUT/mc_gdpr"])[:61]
        L = lagged(x, k)
        ok = (okq & okp)[REGIONS, YEARS]
        X.append(np.column_stack([L[REGIONS, YEARS][ok], np.broadcast_to(gdp[YEARS], ok.shape)[ok]]))
        Y.append(y[REGIONS, YEARS][ok])
    return np.vstack(X), np.concatenate(Y)


def ols(X, y):
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    r = y - X @ coef
    return coef, float(r @ r)


def fit_sector(s: str) -> dict:
    best = None
    for k in ADJUSTMENTS:
        sse, fits = 0.0, {}
        for f in FUELS[s]:
            d = rows(s, f, k)
            if d is None:
                continue
            coef, e = ols(*d)
            sse += e
            fits[f] = (coef, d)
        if best is None or sse < best[0]:
            best = (sse, k, fits)
    _, k, fits = best
    out = {"adjustment": k, "fuels": {}}
    for f, (coef, (X, y)) in fits.items():
        eps, g = float(coef[0]), float(coef[1])
        r = y - X @ coef
        tss = float(((y - y.mean()) ** 2).sum())
        se = float(np.sqrt((r @ r) / max(len(y) - 2, 1) * np.linalg.inv(X.T @ X)[0, 0]))
        price_sd = float(np.std(X[:, 0]))
        out["fuels"][f] = {
            "fitted": round(eps, 3), "se": round(se, 3), "gdp": round(g, 3),
            "n": int(len(y)), "r2": round(1 - float(r @ r) / tss, 3) if tss > 0 else None,
            "rmse_pct": round(100 * float(np.sqrt(np.mean(r ** 2))), 2),
            "price_spread_pct": round(100 * price_sd, 2),
        }
    return out


def usable(f: dict, default: float) -> tuple[float, str]:
    """The value the stub uses: the fit if it has the right sign and some precision,
    else the sector's placeholder."""
    e, se = f["fitted"], f["se"]
    if e > 0:
        return default, "fit has the wrong sign (demand rising with price); placeholder kept"
    if f["price_spread_pct"] < 1.0:
        return default, "price barely moves across the cases; placeholder kept"
    if se > abs(e):
        return default, "fit not distinguishable from zero; placeholder kept"
    return max(e, -1.5), "fitted"


PLACEHOLDER = {"rs": -0.30, "cm": -0.30, "in": -0.30, "tr": -0.20}
# Fits that read something other than a price response, set aside by hand.
CONFOUNDED = {
    ("tr", "ng"): "mostly pipeline compressor fuel, which follows gas throughput (high in the "
                  "high-supply case, when gas is cheap), not price; placeholder kept",
}


def main() -> None:
    result = {}
    for s in FUELS:
        fit = fit_sector(s)
        for f, v in fit["fuels"].items():
            v["used"], v["why"] = usable(v, PLACEHOLDER[s])
            if (s, f) in CONFOUNDED:
                v["used"], v["why"] = PLACEHOLDER[s], CONFOUNDED[(s, f)]
        result[s] = fit
    OUT.write_text(json.dumps(result, indent=1) + "\n")
    write_report(result)
    for s, fit in result.items():
        print(s, "adjustment", fit["adjustment"])
        for f, v in fit["fuels"].items():
            print(f"  {f}: fitted {v['fitted']:+.3f} (se {v['se']:.3f}) R2 {v['r2']} "
                  f"rmse {v['rmse_pct']}% price sd {v['price_spread_pct']}% -> used {v['used']:+.3f} ({v['why']})")


SECTOR_NAMES = {"rs": "Residential", "cm": "Commercial", "in": "Industrial", "tr": "Transportation"}
FUEL_NAMES = {"el": "electricity", "ng": "natural gas", "ds": "distillate", "lg": "propane",
              "ks": "kerosene", "rl": "residual oil", "cl": "coal", "mc": "metallurgical coal",
              "mg": "gasoline", "jf": "jet fuel"}


def write_report(result: dict) -> None:
    lines = [
        "# Demand stub elasticities: fit report",
        "",
        "Generated by `python -m nems_open.fit_elasticities`. Do not edit by hand. Method and",
        "limits are in the module docstring and in docs/run_model.md.",
        "",
        "Long-run own-price elasticity of fuel use, with a lag: each year closes `k` of the",
        "gap. `price sd` is how much that price moves across the fit cases; little movement",
        "means little to learn from. `used` is what the demand stub runs with.",
        "",
        "| Sector | k | Fuel | fitted | se | GDP | n | R2 | RMSE % | price sd % | used | note |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for s, fit in result.items():
        for f, v in fit["fuels"].items():
            lines.append(f"| {SECTOR_NAMES[s]} | {fit['adjustment']} | {FUEL_NAMES.get(f, f)} | {v['fitted']} | "
                         f"{v['se']} | {v['gdp']} | {v['n']} | {v['r2']} | {v['rmse_pct']} | "
                         f"{v['price_spread_pct']} | {v['used']} | {v['why']} |")
    REPORT.write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    main()
