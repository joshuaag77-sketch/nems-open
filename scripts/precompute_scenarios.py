"""Run the full model over the demo's policy grid and save one small JSON per scenario.

    python scripts/precompute_scenarios.py [--workers 6]

Grid: carbon price 0-200 $/t (2024 $) in steps of 25, plug-in share of new light-duty
sales in 2035 at 4 levels, building energy use in 2050 at 4 levels. 144 runs, stub
demand for every sector (seconds a run).

Writes web/data/scenarios/<id>.json and web/data/scenarios.js (all scenarios plus the
EIA reference in one file, so the page also works opened straight from disk).
"""

import argparse
import json
import sys
from concurrent.futures import ProcessPoolExecutor
from itertools import product
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from nems_open.demand_adapter import EVLever, Policy  # noqa: E402
from nems_open.run_model import run  # noqa: E402
from nems_open.supply_standin import SupplyStandin  # noqa: E402
from nems_open.supply_standin.data import FIRST_YEAR, US, load_case  # noqa: E402

OUT = ROOT / "web" / "data"
START, FIRST_SHOWN, LAST = 2027, 2025, 2050
YEARS = list(range(FIRST_SHOWN, LAST + 1))
J = slice(FIRST_SHOWN - FIRST_YEAR, LAST - FIRST_YEAR + 1)

CARBON = [0, 25, 50, 75, 100, 125, 150, 175, 200]
EV_2035 = [0.25, None, 0.80, 1.00]          # None = EIA's reference path (about 65% in 2035)
BUILDINGS_2050 = [1.00, 0.95, 0.90, 0.80]   # building fuel use vs EIA's, reached by 2050

# Display units. Prices come out of the model in 1987 $/MMBtu.
MMBTU_PER_KWH = 0.003412
MMBTU_PER_GAL_GASOLINE = 0.1205
MMBTU_PER_GAL_DIESEL = 0.1374
PRICES = {  # key: (MPBLK name, MMBtu per display unit, display unit)
    "electricity": ("MPBLK/pelas", MMBTU_PER_KWH * 100, "cents/kWh"),  # cents
    "gas_home": ("MPBLK/pngrs", 1.0, "$/MMBtu"),
    "gasoline": ("MPBLK/pmgtr", MMBTU_PER_GAL_GASOLINE, "$/gal"),
    "diesel": ("MPBLK/pdstr", MMBTU_PER_GAL_DIESEL, "$/gal"),
}
SECTORS = {"residential": "QBLK/qtsrs", "commercial": "QBLK/qtscm", "industrial": "QBLK/qtsin",
           "transportation": "QBLK/qtstr"}


def scenario_id(carbon, ev, bld) -> str:
    ev_s = "ref" if ev is None else f"{round(ev * 100)}"
    return f"c{carbon}_ev{ev_s}_b{round(bld * 100)}"


def policy(carbon, ev, bld) -> Policy:
    base = load_case("cb2026")
    ramp_ev = np.clip((np.arange(61) + FIRST_YEAR - (START - 1)) / (2035 - (START - 1)), 0, 1)
    ev_path = None
    if ev is not None:
        ref = EVLever(base, Policy(ev_share=0.5)).sales_share
        ev_path = np.clip(ref + (ev - ref[2035 - FIRST_YEAR]) * ramp_ev, 0, 1)
    ramp_b = np.clip((np.arange(61) + FIRST_YEAR - (START - 1)) / (LAST - (START - 1)), 0, 1)
    return Policy(carbon_price=float(carbon), ev_share=ev_path,
                  building_efficiency=1 + (bld - 1) * ramp_b, start_year=START)


def to_2024(base) -> float:
    d = base["MACOUT/mc_jpgdp"]
    return float(d[2024 - 1987] / d[0])


def series(prices, quantities, co2_total, base) -> dict:
    k = to_2024(base)
    r2 = lambda a, n=2: [round(float(x), n) for x in a]
    return {
        "co2": r2(co2_total[J], 0),
        "prices": {name: r2(prices[v][US, J] * k * per) for name, (v, per, _) in PRICES.items()},
        "energy": {s: r2(quantities[v][US, J] / 1000, 3) for s, v in SECTORS.items()},  # quads
        "gasoline_bgal": r2(quantities["QBLK/qmgtr"][US, J] / MMBTU_PER_GAL_GASOLINE / 1000, 1),
        "power_sales": r2(quantities["QBLK/qelas"][US, J] / 1000, 3),
    }


def trace(supply, quantities, pol: Policy, base) -> dict:
    """What moved each charted number, by year: for the page's "trace this number".
    supply is the stand-in's answer on the run's final demand."""
    k = to_2024(base)
    r = lambda a, n=2: [round(float(x), n) for x in a]
    ev_cut = np.zeros(61)
    if pol.ev_share is not None:
        lever = EVLever(base, pol)
        for j in range(61):
            ev_cut[j] = -lever.shifts(j).get("QBLK/qmgtr", np.zeros(11))[US]
    adder = lambda name, per: r(supply.carbon_adders.get(name, np.zeros((11, 61)))[US, J] * k * per, 3)
    return {
        "co2_sector": {sec: r(v[US, J], 0) for sec, v in supply.co2.items()},
        "power_burn": {"gas": r(supply.power_fuel["QBLK/qngel"][US, J] / 1000, 3),
                       "coal": r(supply.power_fuel["QBLK/qclel"][US, J] / 1000, 3)},
        "totals": {"gas": r(supply.totals["QBLK/qngas"][US, J] / 1000, 3),
                   "elec": r(supply.totals["QBLK/qelas"][US, J] / 1000, 3),
                   "gasoline": r(supply.totals["QBLK/qmgas"][US, J] / 1000, 3)},
        # before the carbon cost: what the power price curve responds to
        "gas_to_power": r((supply.prices["MPBLK/pngel"] - supply.carbon_adders.get("MPBLK/pngel", 0.0))[US, J] * k),
        "adders": {"electricity": adder("MPBLK/pelas", PRICES["electricity"][1]),
                   "gas_home": adder("MPBLK/pngrs", 1.0),
                   "gasoline": adder("MPBLK/pmgtr", MMBTU_PER_GAL_GASOLINE)},
        "ev_cut_bgal": r(ev_cut[J] / MMBTU_PER_GAL_GASOLINE / 1000, 1),
    }


def one(args) -> tuple[str, dict]:
    carbon, ev, bld = args
    pol = policy(carbon, ev, bld)
    r = run(pol)
    base = load_case("cb2026")
    supply = SupplyStandin("cb2026").solve(r.quantities, carbon_price=pol.carbon())
    by_year = {}
    for p in r.passes:
        by_year.setdefault(p.year, []).append(p)
    report = {str(y): {"passes": len(ps),
                       "dp": [float(f"{p.max_price_change:.3g}") for p in ps],
                       "dq": [float(f"{p.max_quantity_change:.3g}") for p in ps],
                       "worst": ps[0].worst_price}
              for y, ps in by_year.items()}
    sid = scenario_id(carbon, ev, bld)
    return sid, {"id": sid, "carbon": carbon, "ev2035": ev, "buildings2050": bld,
                 **series(r.prices, r.quantities, r.co2_total, base),
                 "trace": trace(supply, r.quantities, pol, base),
                 "convergence": report, "routines": r.passes[0].routines}


def reference() -> dict:
    base = load_case("cb2026")
    s = SupplyStandin("cb2026").solve()
    ev = EVLever(base, Policy(ev_share=0.5)).sales_share
    return {**series(base, base, s.co2_total, base), "ev_share": [round(float(x), 3) for x in ev[J]],
            "trace": trace(s, base, Policy(), base)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=6)
    a = ap.parse_args()
    grid = list(product(CARBON, EV_2035, BUILDINGS_2050))
    (OUT / "scenarios").mkdir(parents=True, exist_ok=True)
    scenarios = {}
    with ProcessPoolExecutor(a.workers) as pool:
        for n, (sid, data) in enumerate(pool.map(one, grid), 1):
            (OUT / "scenarios" / f"{sid}.json").write_text(json.dumps(data, separators=(",", ":")))
            scenarios[sid] = data
            print(f"{n}/{len(grid)} {sid}", flush=True)
    meta = {"years": YEARS, "carbon": CARBON, "ev2035": EV_2035, "buildings2050": BUILDINGS_2050,
            "units": {k: v[2] for k, v in PRICES.items()}, "start_year": START,
            "dollars": "2024 $", "reference": reference()}
    bundle = {"meta": meta, "scenarios": scenarios}
    (OUT / "meta.json").write_text(json.dumps(meta, separators=(",", ":")))
    (OUT / "scenarios.js").write_text("window.NEMS_DATA = " + json.dumps(bundle, separators=(",", ":")) + ";\n")
    print("wrote", OUT)


if __name__ == "__main__":
    main()
