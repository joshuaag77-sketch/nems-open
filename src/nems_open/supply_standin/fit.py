"""Fit the stand-in's price responses across EIA's AEO2026 side cases.

    python -m nems_open.supply_standin.fit

Writes coefficients.json next to this file and docs/supply_standin_fit.md.

Each price is fitted on its own: ordinary least squares, no intercept, on
dlog P = sum(coef * regressor) over census divisions 1-9 and years 2027-2050 (after
STEO pins 2025-2026), after taking out the crude pass-through, pooling the side cases where that fuel's supply curve did not
move. A case that shifts supply (more or less gas in the ground, cheaper renewables,
different power plant rules) would read as a demand curve sloping the wrong way, so it
is held out and only reported. Every coefficient must be zero or positive (a supply
curve does not slope down; a product does not get cheaper when crude rises), so a term
that fits negative is dropped and the rest refitted.
"""

import json
from pathlib import Path

import numpy as np

from nems_open.paths import REPO_ROOT
from nems_open.supply_standin.data import CASES, US, load_case
from nems_open.supply_standin.model import (COEFFICIENTS, DEMAND_SECTORS, DRIVERS, REGRESSORS,
                                            SupplyStandin, crude_adjusted, dlog, parse_price,
                                            regressors)

BASE = "cb2026"
YEARS = slice(2027 - 1990, 2050 - 1990 + 1)
REGIONS = slice(0, 9)
# Cases whose supply side matches the reference for each fitting group.
FIT_CASES = {
    "el": ["hm2026", "lm2026", "higheldmd"],
    "ng": ["hm2026", "lm2026", "higheldmd", "highztc", "lowztc", "altelec", "electrnp"],
    # Crude is passed through by rule, not fitted, so the oil and gas supply cases (Brent
    # -15% and +23% by 2050) stay out of the fit and test that rule out of sample.
    "oil": ["hm2026", "lm2026", "higheldmd", "highztc", "lowztc", "altelec", "electrnp"],
    # Propane is mostly a gas-plant liquid: the oil and gas supply cases move its supply.
    "ngl": ["hm2026", "lm2026", "higheldmd", "highztc", "lowztc", "altelec", "electrnp"],
    "coal": ["hm2026", "lm2026", "higheldmd"],
}
REPORT = REPO_ROOT / "docs" / "supply_standin_fit.md"
# Prices worth a line in the docs summary.
HEADLINE = ["MPBLK/pelrs", "MPBLK/pelcm", "MPBLK/pelin", "MPBLK/pngrs", "MPBLK/pngcm",
            "MPBLK/pngin", "MPBLK/pngel", "MPBLK/pmgtr", "MPBLK/pdstr", "MPBLK/pjftr",
            "MPBLK/plgrs", "MPBLK/pdsrs", "MPBLK/pclel", "MPBLK/pclin"]


def design(name: str, case: str, keys: tuple[str, ...]):
    """Rows (regions x years) of regressors and dlog price for one case."""
    base, z = load_case(BASE), load_case(case)
    fuel, _ = parse_price(name)
    x = regressors(fuel, z, base, z["INTOUT/brent_price"], z["MPBLK/pngel"])
    y = dlog(z[name], crude_adjusted(name, z["INTOUT/brent_price"], base))
    ok = (base[name] > 0) & (z[name] > 0)
    ok = ok[REGIONS, YEARS].ravel()
    X = np.column_stack([np.asarray(x[k])[REGIONS, YEARS].ravel() for k in keys])
    return X[ok], y[REGIONS, YEARS].ravel()[ok]


def ols(X, y):
    coef, *_ = np.linalg.lstsq(X, y, rcond=None)
    return coef


def stack(name, cases, keys):
    parts = [design(name, c, keys) for c in cases]
    return np.vstack([p[0] for p in parts]), np.concatenate([p[1] for p in parts])


def fit_price(name: str) -> dict | None:
    fuel, _ = parse_price(name)
    if fuel not in DRIVERS or DRIVERS[fuel][1] not in load_case(BASE):
        return None
    group = DRIVERS[fuel][0]
    cases = FIT_CASES[group]
    keys = REGRESSORS[group]
    X, y = stack(name, cases, keys)
    if len(y) < 20 or not np.any(y):
        return None
    coef = ols(X, y)
    while np.any(coef < 0):  # supply curves do not slope down; prices do not fall as crude rises
        keys = tuple(k for k, c in zip(keys, coef) if c != coef.min())
        if not keys:
            return None
        X, y = stack(name, cases, keys)
        coef = ols(X, y)
    resid = y - X @ coef
    tss = float(np.sum((y - y.mean()) ** 2))
    out = {
        "group": group,
        "coef": {k: round(float(c), 5) for k, c in zip(keys, coef)},
        "n": int(len(y)),
        "r2": round(1 - float(np.sum(resid ** 2)) / tss, 4) if tss > 0 else None,
        "rmse_pct": round(100 * float(np.sqrt(np.mean(resid ** 2))), 3),
        "sd_pct": round(100 * float(np.std(y)), 3),
        "fit_cases": cases,
        "loco_rmse_pct": {},
        "held_out_rmse_pct": {},
    }
    for c in cases:  # leave one case out
        rest = [r for r in cases if r != c]
        Xr, yr = stack(name, rest, keys)
        Xc, yc = design(name, c, keys)
        if len(yc):
            e = yc - Xc @ ols(Xr, yr)
            out["loco_rmse_pct"][c] = round(100 * float(np.sqrt(np.mean(e ** 2))), 3)
    for c in CASES:
        if c == BASE or c in cases:
            continue
        Xc, yc = design(name, c, keys)
        if len(yc):
            e = yc - Xc @ coef
            out["held_out_rmse_pct"][c] = round(100 * float(np.sqrt(np.mean(e ** 2))), 3)
    return out


def fit_power_mix() -> dict[str, float]:
    """Each power-sector fuel's change per unit change in US electricity sales (Btu/Btu)."""
    base = load_case(BASE)
    names = sorted(k for k in base if k.startswith("QBLK/q") and k.endswith("el") and k != "QBLK/qelas")
    dx = np.concatenate([(load_case(c)["QBLK/qelas"][US] - base["QBLK/qelas"][US])[YEARS]
                         for c in FIT_CASES["el"]])
    mix = {}
    for n in names:
        if not np.any(base[n][US]):
            continue
        dy = np.concatenate([(load_case(c)[n][US] - base[n][US])[YEARS] for c in FIT_CASES["el"]])
        mix[n] = round(float(dx @ dy / (dx @ dx)), 5)
    return mix


def end_to_end(case: str, model: SupplyStandin) -> dict[str, float]:
    """Feed a case's end-use demand and Brent through the model built on the reference.
    Returns the largest error in the US price, percent, 2027-2050, for each headline price."""
    z = load_case(case)
    demand = {k: v for k, v in z.items() if k.startswith("QBLK/q") and k[-2:] in DEMAND_SECTORS}
    r = model.solve(demand, brent=z["INTOUT/brent_price"])
    out = {}
    for name in HEADLINE:
        p, e = r.prices[name][US, YEARS], z[name][US, YEARS]
        ok = e > 0
        out[name] = round(100 * float(np.max(np.abs(p[ok] / e[ok] - 1))), 2) if ok.any() else None
    co2, eia = r.co2_total[YEARS], eia_co2(z)[YEARS]
    out["co2_total"] = round(100 * float(np.max(np.abs(co2 / eia - 1))), 2)
    return out


def eia_co2(z) -> np.ndarray:
    """EIA's US energy CO2 by year, million metric tons, from its five sector arrays."""
    from nems_open.supply_standin.model import CO2_PER_C, EMISSION_SECTORS
    return sum(z[v][US, 0, :] for v in EMISSION_SECTORS.values()) * CO2_PER_C


def write_report(prices: dict, mix: dict, e2e: dict) -> None:
    lines = [
        "# Supply stand-in: fit report",
        "",
        "Generated by `python -m nems_open.supply_standin.fit`. Do not edit by hand.",
        "",
        "Units: errors are in percent of the price (RMSE of log deviations x 100). "
        "`sd` is the spread of the price across the fit cases before any model, so a fit "
        "is only useful where RMSE is well below sd. LOCO is leave-one-case-out: the fit "
        "redone without that case, then scored on it. Held out cases shift supply, so the "
        "model is not expected to match them; use them as a baseline instead.",
        "",
        "## End to end, model built on the reference",
        "",
        "Each case's own end-use demand and Brent price fed through the stand-in "
        "(power-sector fuel use computed by the stand-in, not taken from EIA). "
        "Largest US error 2027-2050, percent.",
        "",
        "| price | " + " | ".join(e2e) + " |",
        "|---|" + "---|" * len(e2e),
    ]
    for name in HEADLINE + ["co2_total"]:
        lines.append(f"| {name} | " + " | ".join(str(e2e[c][name]) for c in e2e) + " |")
    lines += ["", "## Power-sector fuel per unit of electricity sold (Btu per Btu)", "",
              "| fuel | change per Btu sold |", "|---|---|"]
    lines += [f"| {k} | {v} |" for k, v in mix.items()]
    lines += ["", "## Every fitted price", "",
              "| price | coef | n | R2 | RMSE % | sd % | LOCO RMSE % (worst) | held-out RMSE % (worst) |",
              "|---|---|---|---|---|---|---|---|"]
    for name, f in prices.items():
        loco = max(f["loco_rmse_pct"].items(), key=lambda kv: kv[1], default=("", ""))
        held = max(f["held_out_rmse_pct"].items(), key=lambda kv: kv[1], default=("", ""))
        coef = ", ".join(f"{k} {v}" for k, v in f["coef"].items())
        lines.append(f"| {name} | {coef} | {f['n']} | {f['r2']} | {f['rmse_pct']} | {f['sd_pct']} "
                     f"| {loco[1]} ({loco[0]}) | {held[1]} ({held[0]}) |")
    REPORT.parent.mkdir(exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n")


def main() -> None:
    base = load_case(BASE)
    prices = {}
    for name in sorted(k for k in base if k.startswith("MPBLK/p")):
        f = fit_price(name)
        if f:
            prices[name] = f
    mix = fit_power_mix()
    COEFFICIENTS.write_text(json.dumps({"baseline_fitted_on": BASE, "prices": prices,
                                        "power_mix": mix}, indent=1) + "\n")
    model = SupplyStandin(BASE)
    e2e = {c: end_to_end(c, model) for c in CASES if c != BASE}
    write_report(prices, mix, e2e)
    for name in HEADLINE:
        f = prices.get(name)
        if f:
            print(f"{name:14} {f['coef']} R2={f['r2']} rmse={f['rmse_pct']}% sd={f['sd_pct']}%")
    print("power mix", mix)
    for c, e in e2e.items():
        print(c, e)


if __name__ == "__main__":
    main()
