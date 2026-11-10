"""Data for "Your America in 2050" (web/2050.html): the plant map, the emulator and its training runs.

    python scripts/build_ux2050.py plants          # web/data/ux2050/plants.json from EIA's plant file
    python scripts/build_ux2050.py runs [--n 240]  # fast-loop runs over eight levers (about 4 s each, one core, resumable)
    python scripts/build_ux2050.py fit             # web/data/ux2050/emulator.json, with held-out error per output

The emulator answers instantly in the browser. It is a polynomial fitted to fast-loop runs
(run_model.run with every sector on the stub, supply on the stand-in) over a Latin hypercube of
eight levers. It is a fit to a fit: its grade is the training runs' grade (stand-in) and its own
error on runs it never saw is written next to every output. Building codes and appliance
standards need the ported buildings modules (the stub refuses them), so the emulator leaves them
out; the page sends them to the real run.

Every output is one of the page's numbers; `outputs()` says how each comes from a run.
"""

import argparse
import json
import sys
import time
from functools import lru_cache
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nems_open.supply_standin.data import FIRST_YEAR, US, load_case  # noqa: E402

OUT = ROOT / "web" / "data" / "ux2050"
CACHE = ROOT / "data" / "ux2050"          # training runs, not committed (data/ is git-ignored)
START = 2027
YEARS = list(range(2025, 2051))
J = [y - FIRST_YEAR for y in YEARS]
SEED = 20261110

# The eight levers the emulator spans: name -> (low, high, off). Units as on the page.
LEVERS = {
    "carbon_price": (0.0, 200.0, 0.0),        # 2024 $ per ton CO2 from 2027
    "ev_2035": (0.25, 1.0, None),             # plug-in share of new light-duty sales in 2035; off = EIA's path
    "load_growth": (0.0, 1000.0, 0.0),        # extra TWh of US electricity sales by 2050 (data centers)
    "coal_retirement": (0.0, 1.0, 0.0),       # share of EIA's coal fleet closed early by 2035
    "renewable_cost": (-1.0, 1.0, 0.0),       # EIA's low (-1) to high (+1) zero-carbon cost case
    "gas_supply": (-1.0, 1.0, 0.0),           # EIA's low (-1) to high (+1) oil and gas supply case
    "oil_price": (0.5, 2.0, 1.0),             # multiple of EIA's Brent price
    "nuclear": (0.5, 1.5, 1.0),               # multiple of EIA's nuclear output by 2040
}

MMBTU_PER_KWH = 0.003412
PRICES = {"electricity": ("MPBLK/pelas", MMBTU_PER_KWH * 100), "gas_home": ("MPBLK/pngrs", 1.0),
          "gasoline": ("MPBLK/pmgtr", 0.1205), "diesel": ("MPBLK/pdstr", 0.1374)}
RES_FUELS = ("el", "ng", "lg", "ds", "ks", "cl")   # priced home fuels, as uncertainty.py's bill
SECTORS = ("rs", "cm", "in", "tr")
SOURCES = {"petroleum": "tp", "gas": "ng", "coal": "cl", "renewables": "tr", "electricity": "el"}
POWER = {"coal": "qclel", "gas": "qngel", "oil": "qtpel", "nuclear": "qurel", "hydro": "qhoel",
         "wind": "qwiel", "solar": "qpvel"}   # "other" = qtrel less hydro, wind and solar


@lru_cache(maxsize=1)
def ev_reference_2035() -> float:
    from nems_open.demand_adapter import EVLever, Policy
    return float(EVLever(load_case("cb2026"), Policy(ev_share=0.5)).sales_share[2035 - FIRST_YEAR])


def ev_path(target_2035: float) -> np.ndarray:
    """EIA's plug-in sales path moved to `target_2035` by 2035, linearly from 2027, the same move after."""
    from nems_open.demand_adapter import EVLever, Policy
    ref = EVLever(load_case("cb2026"), Policy(ev_share=0.5)).sales_share
    ramp = np.clip((np.arange(61) + FIRST_YEAR - (START - 1)) / (2035 - (START - 1)), 0, 1)
    return np.clip(ref + (target_2035 - ref[2035 - FIRST_YEAR]) * ramp, 0, 1)


def policy(x: dict, building_code: float = 0.0, appliance_standard: float = 0.0):
    from nems_open.demand_adapter import Policy
    ev = x.get("ev_2035")
    if ev is not None and abs(float(ev) - ev_reference_2035()) < 0.006:
        ev = None   # the slider at EIA's value: EIA's own path, untouched
    return Policy(carbon_price=float(x.get("carbon_price", 0.0)),
                  ev_share=None if ev is None else ev_path(float(ev)),
                  load_growth=float(x.get("load_growth", 0.0)),
                  coal_retirement=float(x.get("coal_retirement", 0.0)),
                  renewable_cost=float(x.get("renewable_cost", 0.0)),
                  gas_supply=float(x.get("gas_supply", 0.0)),
                  oil_price=float(x.get("oil_price", 1.0)),
                  nuclear=float(x.get("nuclear", 1.0)),
                  building_code=float(building_code), appliance_standard=float(appliance_standard),
                  start_year=START)


def households() -> np.ndarray:
    from nems_open.uncertainty import households as h
    return h("cb2026")


def to_2024(base) -> float:
    d = base["MACOUT/mc_jpgdp"]
    return float(d[2024 - 1987] / d[0])


def outputs(prices: dict, q: dict, co2: dict, base: dict, homes: np.ndarray) -> dict[str, np.ndarray]:
    """Every number the page shows, by year 2025-2050. Quantities in quads, CO2 in million tons,
    prices and the bill in 2024 dollars."""
    k = to_2024(base)
    g = lambda name: np.asarray(q[name][US, J], dtype=np.float64) if name in q else np.zeros(len(J))
    out = {"co2": sum(np.asarray(v[US, J], dtype=np.float64) for v in co2.values())}
    for s, v in co2.items():
        out[f"co2_{s}"] = np.asarray(v[US, J], dtype=np.float64)
    for name, (v, per) in PRICES.items():
        out[f"price_{name}"] = np.asarray(prices[v][US, J], dtype=np.float64) * k * per
    spend = sum(np.asarray(prices[f"MPBLK/p{f}rs"][US, J]) * g(f"QBLK/q{f}rs") for f in RES_FUELS)
    out["bill"] = spend * k / homes[J]   # trillion Btu x $/MMBtu = $ million, over millions of homes
    for s in SECTORS:
        for src, f in SOURCES.items():
            out[f"flow_{src}_{s}"] = g(f"QBLK/q{f}{s}") / 1000
    for src, f in (("petroleum", "tp"), ("gas", "ng"), ("coal", "cl"), ("nuclear", "ur"), ("renewables", "tr")):
        out[f"flow_{src}_el"] = g(f"QBLK/q{f}el") / 1000
    out["flow_losses"] = (g("QBLK/qtsel") - g("QBLK/qelas")) / 1000
    for grp, name in POWER.items():
        out[f"power_{grp}"] = g(f"QBLK/{name}") / 1000
    out["power_other"] = np.maximum(g("QBLK/qtrel") - g("QBLK/qhoel") - g("QBLK/qwiel") - g("QBLK/qpvel"), 0) / 1000
    return derived(out)


def derived(out: dict) -> dict:
    """Numbers built from other outputs: electricity sold to the four sectors, TWh."""
    out["elec_sales_twh"] = sum(out[f"flow_electricity_{s}"] for s in SECTORS) * 1000 / 3.412
    return out


# ---- plants ---------------------------------------------------------------------------------------

GROUPS = {   # EFD plant type -> map fuel group (emm/dispatch.py EXISTING_TYPES, oil split out)
    "coal": ("CSC", "CSU", "CAV", "COU", "CNC", "CN2", "CNG", "COQ", "CAS"),
    "gas": ("CCG", "CCX", "FCG", "CTG", "CTX", "STG", "STX", "CTN"),
    "oil": ("CTO", "STO", "CCO"),
    "nuclear": ("CNU", "ANC", "SMR"),
    "hydro": ("HYC", "HYR"),
    "wind": ("WND", "WFS"),
    "solar": ("SPV", "PVT", "STH"),
    "other": ("GTH", "BMS", "MSW"),
    "storage": ("DST",),
}


def build_plants() -> None:
    from nems_open.emm import db, plants, regions
    u = plants.load_units()
    t = db.table("V_EMM_PLTF860")
    lat, lon = t["T_LAT"].astype(float), -np.abs(t["T_LONG"].astype(float))
    group_of = {code: i for i, (g, codes) in enumerate(GROUPS.items()) for code in codes}
    names = list(GROUPS)
    grp = np.array([group_of.get(c, names.index("other")) for c in u.efd_type])
    has_xy = (lat > 15) & (np.abs(lon) > 60)
    rows = []
    for i in np.flatnonzero(has_xy & (u.summer_mw > 0)):
        rows.append([round(float(lon[i]), 3), round(float(lat[i]), 3), round(float(u.summer_mw[i]), 1),
                     int(grp[i]), int(u.region[i]), int(u.online_year[i]), int(min(u.retire_year[i], 9999)),
                     round(float(np.clip(u.capacity_factor[i], 0, 1)), 3)])
    # Each group's capacity x capacity factor online by year: the page scales every plant's own
    # capacity factor by the run's fuel use relative to 2025, over this.
    fleet = {}
    for gi, g in enumerate(names):
        m = grp == gi
        fleet[g] = [round(float((u.summer_mw * np.clip(u.capacity_factor, 0, 1))[m & plants.online(y)].sum()), 1)
                    for y in YEARS]
    reg = [r.name for r in regions.regions()[:25]]
    OUT.mkdir(parents=True, exist_ok=True)
    doc = {
        "source": "EIA AEO2026 NEMS input database, table V_EMM_PLTF860 (EMM plant file: EIA-860 units and planned builds)",
        "units_in_file": int(len(u)),
        "drawn": len(rows),
        "not_drawn": {"no_coordinates": int((~has_xy).sum()), "zero_capacity": int((has_xy & (u.summer_mw <= 0)).sum())},
        "columns": ["lon", "lat", "summer_mw", "group", "emm_region", "online_year", "retire_year", "capacity_factor"],
        "groups": names,
        "regions": reg,
        "years": YEARS,
        "fleet_mw_cf": fleet,
        "rows": rows,
    }
    (OUT / "plants.json").write_text(json.dumps(doc, separators=(",", ":")))
    print(f"plants.json: {len(rows)} of {len(u)} units drawn")


# ---- training runs --------------------------------------------------------------------------------

def design(n: int) -> list[dict]:
    """Reference, each lever at both ends alone, then a Latin hypercube."""
    rng = np.random.default_rng(SEED)
    pts = [{}]
    for name, (lo, hi, off) in LEVERS.items():
        pts += [{name: lo}, {name: hi}]
    names = list(LEVERS)
    u = np.stack([(rng.permutation(n) + rng.random(n)) / n for _ in names], axis=1)
    for row in u:
        pts.append({nm: LEVERS[nm][0] + r * (LEVERS[nm][1] - LEVERS[nm][0]) for nm, r in zip(names, row)})
    return pts


def run_one(x: dict) -> dict[str, np.ndarray]:
    from nems_open import run_model
    r = run_model.run(policy(x), START, 2050, ported=())
    return outputs(r.prices, r.quantities, r.co2, load_case("cb2026"), households())


def build_runs(n: int) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    pts = design(n)
    (CACHE / "design.json").write_text(json.dumps(pts))
    t0 = time.time()
    for i, x in enumerate(pts):
        f = CACHE / f"run{i:04d}.npz"
        if f.exists():
            continue
        try:
            np.savez(f, **run_one(x))
        except Exception as e:   # a lever corner the loop cannot take is recorded, not hidden
            (CACHE / f"run{i:04d}.failed").write_text(f"{x}\n{type(e).__name__}: {e}")
        if i % 20 == 0:
            print(f"{i + 1}/{len(pts)} {time.time() - t0:.0f}s", flush=True)
    print(f"done {len(pts)} runs in {time.time() - t0:.0f}s")


# ---- the fit --------------------------------------------------------------------------------------

def features(X: np.ndarray) -> tuple[np.ndarray, list]:
    """Quadratic in the eight levers scaled to [-1, 1], plus cubes (the coal switch bends hard)."""
    n, d = X.shape
    cols, names = [np.ones(n)], [[]]
    for i in range(d):
        cols.append(X[:, i]); names.append([i])
    for i in range(d):
        for j in range(i, d):
            cols.append(X[:, i] * X[:, j]); names.append([i, j])
    for i in range(d):
        cols.append(X[:, i] ** 3); names.append([i, i, i])
    return np.stack(cols, axis=1), names


def scale(x: dict) -> np.ndarray:
    ev_ref = scale.ev_ref
    v = []
    for nm, (lo, hi, off) in LEVERS.items():
        val = x.get(nm, ev_ref if nm == "ev_2035" else off)
        v.append(2 * (val - lo) / (hi - lo) - 1)
    return np.array(v)


def fit() -> None:
    scale.ev_ref = ev_reference_2035()
    pts = json.loads((CACHE / "design.json").read_text())
    keep = [i for i in range(len(pts)) if (CACHE / f"run{i:04d}.npz").exists()]
    failed = [pts[i] for i in range(len(pts)) if (CACHE / f"run{i:04d}.failed").exists()]
    runs = [derived(dict(np.load(CACHE / f"run{i:04d}.npz"))) for i in keep]
    X = np.stack([scale(pts[i]) for i in keep])
    F, terms = features(X)
    keys = sorted(runs[0])
    Y = {k: np.stack([r[k] for r in runs]) for k in keys}       # (runs, years)
    # Hold out every fifth hypercube run (never the reference or the one-lever ends) to measure error.
    first_lhs = 1 + 2 * len(LEVERS)
    test = np.array([keep[i] >= first_lhs and (keep[i] - first_lhs) % 5 == 0 for i in range(len(keep))])
    ridge = 1e-6
    ref_row = keep.index(0)
    out, errors = {}, {}
    for k in keys:
        y = Y[k]
        A = F[~test]
        coef = np.linalg.solve(A.T @ A + ridge * np.eye(A.shape[1]), A.T @ y[~test])
        # The page anchors the fit on the reference run (exact at EIA's settings): measure it that way.
        pred = F[test] @ coef - F[ref_row] @ coef + y[ref_row]
        scale_k = max(float(np.abs(y[~test]).mean()), 1e-9)
        err = np.abs(pred - y[test]) / scale_k     # relative to the output's typical size over all years and runs
        errors[k] = {"mean_pct": round(float(err.mean() * 100), 2), "p95_pct": round(float(np.percentile(err, 95) * 100), 2),
                     "max_pct": round(float(err.max() * 100), 2)}
        # Refit on every run for the shipped coefficients.
        coef = np.linalg.solve(F.T @ F + ridge * np.eye(F.shape[1]), F.T @ y)
        out[k] = [[round(float(c), 6) for c in row] for row in coef]   # (terms, years)
    ref = runs[keep.index(0)] if 0 in keep else None
    eia = reference_outputs()
    doc = {
        "generated": time.strftime("%Y-%m-%d"),
        "method": "Polynomial (quadratic plus cubes) in eight levers scaled to [-1, 1], least squares on fast-loop runs "
                  "(run_model.run, every sector on the stub, supply on the stand-in), shifted so it returns the "
                  "reference run exactly at EIA's settings. Error: refit without every fifth hypercube run, then "
                  "predicted those; percent of the output's typical size over all years.",
        "runs": len(keep), "held_out": int(test.sum()), "failed": failed,
        "years": YEARS, "start_year": START,
        "levers": {nm: {"low": lo, "high": hi, "off": (round(scale.ev_ref, 4) if nm == "ev_2035" else off)}
                   for nm, (lo, hi, off) in LEVERS.items()},
        "terms": terms, "coef": out, "error": errors,
        "lever_grades": {"instant": lever_table(()), "real": lever_table(("residential", "commercial", "transportation"))},
        "fast_reference": {k: [round(float(v), 4) for v in ref[k]] for k in keys} if ref else None,
        "eia": eia,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "emulator.json").write_text(json.dumps(doc, separators=(",", ":")))
    worst = sorted(errors.items(), key=lambda kv: -kv[1]["p95_pct"])[:8]
    print(f"emulator.json: {len(keep)} runs, {int(test.sum())} held out, {len(failed)} failed")
    for k, e in worst:
        print(f"  {k}: mean {e['mean_pct']}%, p95 {e['p95_pct']}%, max {e['max_pct']}%")


def lever_table(ported: tuple) -> list[dict]:
    from nems_open import levers
    return levers.table(ported, "standin")


def reference_outputs() -> dict:
    """The same numbers straight from EIA's AEO2026 reference (cb2026), for "against EIA"."""
    base = load_case("cb2026")
    prices = {k: v for k, v in base.items() if k.startswith("MPBLK/")}
    q = {k: v for k, v in base.items() if k.startswith("QBLK/")}
    from nems_open.supply_standin import SupplyStandin
    co2 = SupplyStandin("cb2026").solve(q, carbon_price=np.zeros(61)).co2
    o = outputs(prices, q, co2, base, households())
    return {k: [round(float(v), 4) for v in a] for k, a in o.items()}


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("step", choices=("plants", "runs", "fit"))
    ap.add_argument("--n", type=int, default=240, help="hypercube runs (on top of 17 reference and one-lever runs)")
    a = ap.parse_args(argv)
    if a.step == "plants":
        build_plants()
    elif a.step == "runs":
        build_runs(a.n)
    else:
        fit()


if __name__ == "__main__":
    main()
