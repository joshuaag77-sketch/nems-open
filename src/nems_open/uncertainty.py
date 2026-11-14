"""Uncertainty bands: many runs of the fast loop over the inputs EIA itself varies.

EIA publishes side cases around its reference (AEO2026): high and low economic growth, high electricity
demand, high and low oil and gas supply, high and low zero-carbon technology cost. Each case is a finished
NEMS run. Here each pair is one uncertain input, and a run takes a point between its two ends:

    weight w in [-1, 1]:   -1 = EIA's low case, 0 = the reference, +1 = EIA's high case

The run's baseline (every price, quantity, Brent, GDP deflator...) is the reference plus w times the case's
difference from the reference, added up over the inputs. The loop then runs on that baseline as usual, with
any policy (a carbon price) on top. So the ends of every range are EIA's own, in `uncertainty_ranges.json`
with the size of the swing each one makes. What is ours:

  * the shape between the ends (triangular, most likely at the reference) and that the effects add up;
  * the stand-ins (the loop uses fitted curves, not EIA's modules);
  * AEO2026 has no oil price case. Brent moves with the oil and gas supply cases (-15% and +23%), so oil
    price and gas supply are one input here, not two.

    python -m nems_open.uncertainty ranges                      # measure each swing, write the ranges file
    python -m nems_open.uncertainty run --n 1000 --carbon 0 50 100 --workers 2
    python -m nems_open.uncertainty summary                     # bands and sensitivity for the demo

Bands come from this sampling, not from EIA, and they run on stand-ins.
"""

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np

from nems_open.paths import REPO_ROOT
from nems_open.supply_standin.data import FIRST_YEAR, US, load_case, restart_path

RANGES_FILE = Path(__file__).with_name("uncertainty_ranges.json")
RAW_DIR = REPO_ROOT / "data" / "uncertainty"
WEB_DATA = REPO_ROOT / "web" / "data"
REFERENCE = "cb2026"
YEARS = list(range(2027, 2051))
DOLLAR_YEAR = 2024
RESIDENTIAL_FUELS = ("el", "ng", "lg", "ds", "ks", "cl")     # priced residential fuels (wood has no price)
METRICS = ("co2", "bill", "gas")
UNITS = {"co2": "million metric tons CO2, US energy", "bill": "2024 $ per household per year, residential energy",
         "gas": "2024 $ per MMBtu, natural gas delivered to homes"}


def load_ranges() -> dict:
    return json.loads(RANGES_FILE.read_text())


# ---- blending EIA's cases ---------------------------------------------------------------------------

_cases: dict = {}


def case_arrays(case: str) -> dict:
    if case not in _cases:
        _cases[case] = load_case(case)
    return _cases[case]


def households(case: str) -> np.ndarray:
    """Housing units, US, by year 1990-2050 (millions): RESDREP/rshouses summed over the nine divisions."""
    key = ("households", case)
    if key not in _cases:
        with np.load(restart_path(case), allow_pickle=False) as z:
            _cases[key] = z["RESDREP/rshouses"].astype(np.float64).sum(axis=1) / 1e6
    return _cases[key]


def blend(weights: dict[str, float], ranges: dict | None = None) -> tuple[dict, np.ndarray]:
    """The reference plus each input's weight times its case's difference. Returns (arrays, households)."""
    ranges = ranges or load_ranges()
    ref = case_arrays(REFERENCE)
    out = {k: v.copy() for k, v in ref.items()}
    homes = households(REFERENCE).copy()
    for name, w in weights.items():
        if w == 0.0:
            continue
        f = ranges["factors"][name]
        case = f["low_case"] if w < 0 else f["high_case"]
        z = case_arrays(case)
        for k in out:
            if k in z and z[k].shape == out[k].shape:
                out[k] += abs(w) * (z[k] - ref[k])
        homes += abs(w) * (households(case) - households(REFERENCE))
    return out, homes


# ---- sampling ---------------------------------------------------------------------------------------

def triangular(u: np.ndarray, two_sided: bool) -> np.ndarray:
    """Inverse CDF of a triangular distribution with its mode at the reference (0): on [-1, 1], or on [0, 1]."""
    if two_sided:
        return np.where(u < 0.5, -1 + np.sqrt(2 * u), 1 - np.sqrt(2 * (1 - u)))
    return 1 - np.sqrt(1 - u)


def sample(n: int, seed: int = 20261103, ranges: dict | None = None) -> dict[str, np.ndarray]:
    """Latin hypercube over the inputs: n weights for each, every stratum used once."""
    ranges = ranges or load_ranges()
    rng = np.random.default_rng(seed)
    out = {}
    for name, f in ranges["factors"].items():
        u = (rng.permutation(n) + rng.random(n)) / n
        out[name] = triangular(u, f["two_sided"])
    return out


# ---- one run ----------------------------------------------------------------------------------------

def metrics(r, base: dict, homes: np.ndarray) -> dict[str, np.ndarray]:
    """The three measures for 2027-2050 from one run."""
    j = [y - FIRST_YEAR for y in YEARS]
    deflator = base["MACOUT/mc_jpgdp"]
    to_2024 = deflator[DOLLAR_YEAR - 1987] / deflator[0]            # 1987 $ -> 2024 $
    spend = sum(r.prices[f"MPBLK/p{f}rs"][US, j] * r.quantities[f"QBLK/q{f}rs"][US, j] for f in RESIDENTIAL_FUELS)
    return {
        "co2": np.asarray(r.co2_total)[j],
        "bill": spend * 1e6 * to_2024 / (homes[j] * 1e6),          # trillion Btu x $/MMBtu = $ million; homes in millions
        "gas": r.prices["MPBLK/pngrs"][US, j] * to_2024,
    }


def run_one(args: tuple) -> dict[str, np.ndarray]:
    """args: (weights, carbon price in 2024 $ per ton). Runs the all-stub loop 2027-2050."""
    from nems_open import run_model
    from nems_open.demand_adapter import Policy
    weights, carbon = args
    base, homes = blend(weights)
    r = run_model.run(Policy(carbon_price=carbon, start_year=2027), 2027, 2050, ported=(), base=base)
    return metrics(r, base, homes)


# ---- many runs --------------------------------------------------------------------------------------

def raw_path(carbon: float) -> Path:
    return RAW_DIR / f"carbon{carbon:g}.npz"


def run_many(n: int, carbons: list[float], workers: int = 2, seed: int = 20261103, chunk: int = 50) -> None:
    """Run n samples at each carbon price, saving every chunk so a stopped run resumes where it left off."""
    ranges = load_ranges()
    w = sample(n, seed, ranges)
    names = list(w)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for carbon in carbons:
        path = raw_path(carbon)
        done, store = 0, {m: np.full((n, len(YEARS)), np.nan) for m in METRICS}
        if path.exists():
            z = np.load(path)
            if z["n"] == n and z["seed"] == seed:
                store, done = {m: z[m] for m in METRICS}, int(z["done"])
        with ProcessPoolExecutor(max_workers=workers) as pool:
            for start in range(done, n, chunk):
                idx = range(start, min(start + chunk, n))
                jobs = [({k: float(w[k][i]) for k in names}, carbon) for i in idx]
                for i, res in zip(idx, pool.map(run_one, jobs)):
                    for m in METRICS:
                        store[m][i] = res[m]
                np.savez(path, n=n, seed=seed, done=idx[-1] + 1, names=np.array(names),
                         weights=np.stack([w[k] for k in names], axis=1), **store)
                print(f"carbon {carbon:g}: {idx[-1] + 1}/{n}", flush=True)


# ---- bands and sensitivity --------------------------------------------------------------------------

def first_order(x: np.ndarray, y: np.ndarray, bins: int = 10) -> float:
    """Share of y's variance explained by x alone: the correlation ratio over equal-count bins, less the share an
    input with no effect would score by chance."""
    order = np.argsort(x, kind="stable")
    groups = np.array_split(y[order], bins)
    means = np.array([g.mean() for g in groups])
    sizes = np.array([len(g) for g in groups])
    total = ((y - y.mean()) ** 2).sum()
    if total <= 0:
        return 0.0
    eta2 = float((sizes * (means - y.mean()) ** 2).sum() / total)
    noise = (bins - 1) / (len(y) - 1)          # what an input with no effect scores by chance
    return max(0.0, (eta2 - noise) / (1 - noise))


def summarize(carbons: list[float]) -> dict:
    ranges = load_ranges()
    ref = run_one(({k: 0.0 for k in ranges["factors"]}, 0.0))     # EIA's reference through the same loop
    out = {"years": YEARS, "units": UNITS, "metrics": list(METRICS), "carbon": [], "n": 0,
           "reference": {m: ref[m].round(3).tolist() for m in METRICS},
           "factors": {k: {"label": f["label"], "low_case": f["low_case"], "high_case": f["high_case"],
                           "swing": f.get("measured", {})} for k, f in ranges["factors"].items()},
           "sampling": ranges["sampling"], "note": ranges["note"]}
    for carbon in carbons:
        z = np.load(raw_path(carbon))
        n = int(z["done"])
        out["n"] = max(out["n"], n)
        names = [str(s) for s in z["names"]]
        entry = {"price": carbon, "n": n, "bands": {}, "sensitivity": {}}
        for m in METRICS:
            y = z[m][:n]
            p = np.percentile(y, [10, 50, 90], axis=0)
            entry["bands"][m] = {"p10": p[0].round(3).tolist(), "p50": p[1].round(3).tolist(), "p90": p[2].round(3).tolist()}
            sens = {}
            for year in (2035, 2050):
                col = YEARS.index(year)
                s = {names[k]: first_order(z["weights"][:n, k], y[:, col]) for k in range(len(names))}
                sens[str(year)] = [{"factor": k, "share": round(v, 4)} for k, v in sorted(s.items(), key=lambda kv: -kv[1])]
            entry["sensitivity"][m] = sens
        out["carbon"].append(entry)
    return out


def write_web(carbons: list[float]) -> Path:
    data = summarize(carbons)
    WEB_DATA.mkdir(parents=True, exist_ok=True)
    text = json.dumps(data, separators=(",", ":"))
    (WEB_DATA / "uncertainty.json").write_text(text)
    (WEB_DATA / "uncertainty.js").write_text("window.UNCERTAINTY=" + text + ";\n")
    return WEB_DATA / "uncertainty.json"


# ---- measuring the ranges ---------------------------------------------------------------------------

def measure_ranges() -> dict:
    """Fill in how far each end of each range moves Brent, US CO2 and the residential gas price in 2050."""
    ranges = load_ranges()
    ref = case_arrays(REFERENCE)
    j = 2050 - FIRST_YEAR

    def pct(case, key, region=US):
        a, b = case_arrays(case)[key], ref[key]
        a, b = (a[region, j], b[region, j]) if a.ndim == 2 else (a[j], b[j])
        return round(float(a / b - 1) * 100, 1)

    for f in ranges["factors"].values():
        m = {}
        for end in ("low_case", "high_case"):
            c = f[end]
            if c == REFERENCE:
                continue
            m[c] = {"brent_2050_pct": pct(c, "INTOUT/brent_price"), "gas_to_homes_2050_pct": pct(c, "MPBLK/pngrs"),
                    "electricity_sales_2050_pct": pct(c, "QBLK/qelas"), "energy_use_2050_pct": pct(c, "QBLK/qtsas")}
        f["measured"] = m
    RANGES_FILE.write_text(json.dumps(ranges, indent=1) + "\n")
    return ranges


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("ranges")
    r = sub.add_parser("run")
    r.add_argument("--n", type=int, default=1000)
    r.add_argument("--carbon", type=float, nargs="+", default=[0.0, 50.0, 100.0])
    r.add_argument("--workers", type=int, default=2)
    s = sub.add_parser("summary")
    s.add_argument("--carbon", type=float, nargs="+", default=[0.0, 50.0, 100.0])
    a = ap.parse_args(argv)
    if a.cmd == "ranges":
        print(json.dumps(measure_ranges()["factors"], indent=1))
    elif a.cmd == "run":
        run_many(a.n, a.carbon, min(a.workers, 2))
    else:
        print(write_web(a.carbon))


if __name__ == "__main__":
    sys.exit(main())
