"""Run the demo's smaller grid with the real ported pieces and save one JSON per scenario.

    python scripts/precompute_real.py [--workers 3] [--oracle-root PATH]

Grid: carbon 0/50/100/200 $/t (2024 $), 2035 EV share at EIA's path or 80%, building
energy at EIA's or 10% below by 2050. 16 runs. Residential and commercial are EIA's ported
modules, electricity is the dispatch LP (elec="lp"); industrial and transportation stay on
the stub and gas, oil and coal on the stand-in. 10 to 45 minutes a run.

Memory: each worker needs about 2 GB. Three workers ran out on a machine with 6 GB free; use
--workers 1 there.

The ported modules start each year from the oracle's dumps. --oracle-root is a clone whose
oracle/run and oracle/run_resd hold them (default: the main NEMS Open folder); it is only
read. A finished scenario is skipped on a rerun, so the script can be stopped and resumed.

Writes web/data/real/<id>.json and web/data/real.js (window.NEMS_REAL).
"""

import argparse
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from itertools import product
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import precompute_scenarios as fast  # noqa: E402

OUT = ROOT / "web" / "data"
CARBON = [0, 50, 100, 200]
EV_2035 = [None, 0.80]
BUILDINGS_2050 = [1.00, 0.90]
PORTED = ("residential", "commercial")
DEFAULT_ORACLE = Path.home() / "OneDrive" / "Desktop" / "3. AI Projects" / "NEMS Open"


def one(args) -> tuple[str, dict]:
    carbon, ev, bld, oracle_root = args
    # The dumps sit in a clone's oracle/run*/out; read them there, not from the shared cache.
    os.environ["NEMS_ORACLE_DIR"] = str(ROOT / ".no-shared-oracle")
    import nems_open.oracle_state as oracle_state
    oracle_state.REPO_ROOT = Path(oracle_root)
    from nems_open.run_model import run
    from nems_open.supply_standin import SupplyStandin
    from nems_open.supply_standin.data import load_case

    t = time.time()
    pol = fast.policy(carbon, ev, bld)
    r = run(pol, ported=PORTED, elec="lp")
    base = load_case("cb2026")
    power = {k: r.quantities[k] for k in ("QBLK/qngel", "QBLK/qclel", "QBLK/qrlel", "QBLK/qdsel")
             if k in r.quantities}
    supply = SupplyStandin("cb2026").solve(r.quantities, carbon_price=pol.carbon(),
                                           power_fuel=power, co2_el=r.co2["el"])
    by_year = {}
    for p in r.passes:
        by_year.setdefault(p.year, []).append(p)
    report = {str(y): {"passes": len(ps),
                       "dp": [float(f"{p.max_price_change:.3g}") for p in ps],
                       "dq": [float(f"{p.max_quantity_change:.3g}") for p in ps],
                       "worst": ps[0].worst_price}
              for y, ps in by_year.items()}
    k = fast.to_2024(base)
    j = fast.J
    sid = fast.scenario_id(carbon, ev, bld)
    return sid, {
        "id": sid, "carbon": carbon, "ev2035": ev, "buildings2050": bld,
        **fast.series(r.prices, r.quantities, r.co2_total, base),
        "trace": fast.trace(supply, r.quantities, pol, base),
        "convergence": report, "routines": r.passes[0].routines,
        # dispatch LP extras: wholesale marginal cost (2024 $/MWh, US, load-weighted) and generation
        "wholesale": [None if np.isnan(x) else round(float(x * k), 1) for x in r.wholesale_us[j]],
        "generation_twh": {g: [None if np.isnan(x) else round(float(x), 1) for x in v[j]]
                           for g, v in r.generation_twh.items()},
        "minutes": round((time.time() - t) / 60, 1),
    }


def bundle() -> None:
    scen = {}
    for f in sorted((OUT / "real").glob("*.json")):
        d = json.loads(f.read_text())
        scen[d["id"]] = d
    meta = {"carbon": CARBON, "ev2035": EV_2035, "buildings2050": BUILDINGS_2050, "ported": list(PORTED),
            "elec": "lp", "complete": len(scen) == len(CARBON) * len(EV_2035) * len(BUILDINGS_2050)}
    (OUT / "real.js").write_text("window.NEMS_REAL = " + json.dumps({"meta": meta, "scenarios": scen},
                                                                     separators=(",", ":")) + ";\n")
    print(f"real.js: {len(scen)} scenarios")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=3)
    ap.add_argument("--oracle-root", default=str(DEFAULT_ORACLE))
    ap.add_argument("--bundle-only", action="store_true")
    a = ap.parse_args()
    (OUT / "real").mkdir(parents=True, exist_ok=True)
    if not a.bundle_only:
        todo = [(c, e, b, a.oracle_root) for c, e, b in product(CARBON, EV_2035, BUILDINGS_2050)
                if not (OUT / "real" / f"{fast.scenario_id(c, e, b)}.json").exists()]
        print(f"{len(todo)} to run", flush=True)
        with ProcessPoolExecutor(a.workers) as pool:
            for fut in as_completed([pool.submit(one, t) for t in todo]):
                sid, data = fut.result()
                (OUT / "real" / f"{sid}.json").write_text(json.dumps(data, separators=(",", ":")))
                print(f"done {sid} in {data['minutes']} min", flush=True)
                bundle()
    bundle()


if __name__ == "__main__":
    main()
