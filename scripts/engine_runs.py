"""Precompute the runs the 3D engine replays.

    python scripts/engine_runs.py            # the three scenarios (seconds each) and the trace
    python scripts/engine_runs.py --no-trace # scenarios only

Scenarios, all on the fast stand-ins (every demand sector on the fitted stub, supply on the
fitted curves) so they compare like for like:
- Reference: EIA's AEO2026 reference inputs (cb2026).
- Data center boom: EIA's High Electricity Demand side case (higheldmd), whose extra load is
  mostly data centers.
- High gas price: EIA's Low Oil and Gas Supply side case (lowogs).
Each scenario starts from EIA's own inputs for that case and runs our loop on them; there
is no lever here, so the numbers sit close to EIA's published case.

Headline outputs by year: US energy CO2 (million metric tons), the household energy bill
(residential spending on electricity, natural gas, distillate, propane and kerosene over the
number of households, 2024 $ a year), and the natural gas price to homes (2024 $/MMBtu).
EIA's numbers for the same case come along, for the animation from EIA's value.

Trace: one Reference run 2027-2050 with the ported residential and commercial modules (EIA's
code, in a worker process each) and the supply stand-in: every pass of NEMS's integrating
loop, with the largest price and quantity change and the price behind it. Minutes, not
seconds: one heavy job.

Writes web/data/engine3d/runs.json.
"""

import json
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nems_open.run_model import PORTED, run  # noqa: E402
from nems_open.snapshot import Snapshot  # noqa: E402
from nems_open.supply_standin.data import CASES, FIRST_YEAR, US, load_case, restart_path  # noqa: E402
from nems_open.supply_standin.model import SupplyStandin  # noqa: E402

OUT = ROOT / "web" / "data" / "engine3d" / "runs.json"
START, FIRST_SHOWN, LAST = 2027, 2025, 2050
YEARS = list(range(FIRST_SHOWN, LAST + 1))
J = slice(FIRST_SHOWN - FIRST_YEAR, LAST - FIRST_YEAR + 1)
SCENARIOS = {
    "reference": ("Reference", "cb2026"),
    "data_center_boom": ("Data center boom", "higheldmd"),
    "high_gas_price": ("High gas price", "lowogs"),
}
BILL_FUELS = ("el", "ng", "ds", "lg", "ks")


def to_2024(base) -> float:
    d = base["MACOUT/mc_jpgdp"]
    return float(d[2024 - 1987] / d[0])


def households(case: str) -> np.ndarray:
    return Snapshot(restart_path(case))["RESDREP/rshouses"].sum(axis=1)


def headline(prices, quantities, co2_total, base, homes) -> dict:
    k = to_2024(base)
    spend = sum(quantities[f"QBLK/q{f}rs"][US] * prices[f"MPBLK/p{f}rs"][US] for f in BILL_FUELS)  # million 1987 $
    with np.errstate(divide="ignore", invalid="ignore"):
        bill = spend * 1e6 * k / homes     # no households before the history starts
    r = lambda a, n: [round(float(x), n) for x in a[J]]  # noqa: E731
    return {"co2": r(co2_total, 0), "bill": r(bill, 0), "gas_price": r(prices["MPBLK/pngrs"][US] * k, 2)}


def convergence(passes) -> dict:
    by_year = {}
    for p in passes:
        by_year.setdefault(str(p.year), []).append({
            "itr": p.number, "cycle": p.cycle, "fcrl": p.fcrl, "converged": p.converged,
            "dp": float(f"{p.max_price_change:.4g}"), "dq": float(f"{p.max_quantity_change:.4g}"),
            "worst": p.worst_price, "failing": len(p.failing)})
    return by_year


def scenario(key: str) -> dict:
    label, case = SCENARIOS[key]
    base = load_case(case)
    homes = households(case)
    t = time.perf_counter()
    r = run(start_year=START, end_year=LAST, baseline=case, ported=())
    secs = time.perf_counter() - t
    eia = SupplyStandin(case).solve()        # EIA's own case through the same CO2 accounting
    return {
        "key": key, "label": label, "case": case, "case_name": CASES[case], "model": "fast stand-ins",
        "precomputed": True, "seconds": round(secs, 1),
        "run": headline(r.prices, r.quantities, r.co2_total, base, homes),
        "eia": headline(base, base, eia.co2_total, base, homes),
        "convergence": convergence(r.passes), "routines": r.passes[0].routines,
    }


def trace() -> dict:
    base = load_case("cb2026")
    t = time.perf_counter()
    r = run(start_year=START, end_year=LAST, ported=PORTED)
    secs = time.perf_counter() - t
    return {"label": "Reference", "case": "cb2026", "model": "ported residential and commercial, supply stand-in",
            "ported": list(PORTED), "seconds": round(secs, 1),
            "run": headline(r.prices, r.quantities, r.co2_total, base, households("cb2026")),
            "convergence": convergence(r.passes), "routines": r.passes[0].routines}


def main(argv) -> None:
    old = json.loads(OUT.read_text()) if OUT.exists() else {}
    scenarios = {}
    for key in SCENARIOS:
        scenarios[key] = scenario(key)
        print(key, scenarios[key]["seconds"], "s; 2050:", {k: v[-1] for k, v in scenarios[key]["run"].items()},
              "EIA:", {k: v[-1] for k, v in scenarios[key]["eia"].items()}, flush=True)
    data = {"generated": str(date.today()), "years": YEARS, "start_year": START, "dollars": "2024 $",
            "units": {"co2": "million metric tons CO2", "bill": "2024 $ per household per year",
                      "gas_price": "2024 $ per MMBtu, delivered to homes"},
            "scenarios": scenarios, "trace": old.get("trace")}
    if "--no-trace" not in argv:
        data["trace"] = trace()
        print("trace", data["trace"]["seconds"], "s,", sum(len(v) for v in data["trace"]["convergence"].values()), "passes")
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(data, separators=(",", ":")))
    print("wrote", OUT, OUT.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main(sys.argv[1:])
