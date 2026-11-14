"""Recorded runs for "Watch the model think" (web/think.html): every pass the loop makes, as it made it.

    python scripts/think_runs.py [--only reference,ai] [--fast]

For each scenario this runs run_model.run with residential, commercial and transportation through EIA's
ported routines (industrial and supply on stand-ins) and a recorder (run_model.run's `record`) that copies,
after every demand step and every supply step of every iteration, the US values each module just handed
the others. Nothing is interpolated: the page animates these numbers and nothing else.

Writes web/data/think/<id>.json and web/data/think/manifest.json. One run at a time (about 6 to 8 minutes
each on ported code); finished scenarios are skipped, so it can be stopped and restarted. --fast puts every
sector on the stub (seconds a run) for trying the page; such files say so and the page grades them.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import build_ux2050 as ux  # noqa: E402  (the 2050 page's lever-to-Policy rules, so both pages mean the same thing)
from nems_open.supply_standin.data import FIRST_YEAR, US, load_case  # noqa: E402

OUT = ROOT / "web" / "data" / "think"
PORTED = ("residential", "commercial", "transportation")
START, END = 2027, 2050

MMBTU_PER_KWH, MMBTU_PER_GAL_MG, MMBTU_PER_GAL_DS = 0.003412, 0.1205, 0.1374
# key -> (module, label, kind, unit, MMBtu per display unit). Quantities are US trillion Btu shown as quads.
VARS = {}
for s, name in (("rs", "Homes"), ("cm", "Businesses"), ("in", "Industry"), ("tr", "Vehicles")):
    mod = {"rs": "residential", "cm": "commercial", "in": "industrial", "tr": "transportation"}[s]
    VARS[f"qel{s}"] = (mod, f"{name}: electricity use", "q", "quads", None)
    VARS[f"qng{s}"] = (mod, f"{name}: natural gas use", "q", "quads", None)
    VARS[f"qtp{s}"] = (mod, f"{name}: oil products use", "q", "quads", None)
    VARS[f"qts{s}"] = (mod, f"{name}: all energy", "q", "quads", None)
    VARS[f"pel{s}"] = ("electricity", f"Power price for {name.lower()}", "p", "¢/kWh", MMBTU_PER_KWH * 100)
VARS["qmgtr"] = ("transportation", "Gasoline use", "q", "quads", None)
for s, name in (("rs", "homes"), ("cm", "businesses"), ("in", "industry")):
    VARS[f"png{s}"] = ("natural_gas", f"Gas price for {name}", "p", "$/MMBtu", 1.0)
    VARS[f"ptp{s}"] = ("oil", f"Oil products price for {name}", "p", "$/MMBtu", 1.0)
VARS["pngel"] = ("natural_gas", "Gas price for power plants", "p", "$/MMBtu", 1.0)
VARS["pmgtr"] = ("oil", "Gasoline price", "p", "$/gal", MMBTU_PER_GAL_MG)
VARS["pdstr"] = ("oil", "Diesel price", "p", "$/gal", MMBTU_PER_GAL_DS)
VARS["pclel"] = ("coal", "Coal price at power plants", "p", "$/MMBtu", 1.0)
VARS["qngel"] = ("electricity", "Gas burned for power", "q", "quads", None)
VARS["qclel"] = ("electricity", "Coal burned for power", "q", "quads", None)
VARS["qtpel"] = ("electricity", "Oil burned for power", "q", "quads", None)
VARS["co2"] = ("emissions", "US energy CO2", "c", "Mt", None)
KEYS = list(VARS)

LEVER_DEFAULTS = {"carbon_price": 0.0, "ev_2035": None, "load_growth": 0.0, "building_code": 0.0, "appliance_standard": 0.0,
                  "coal_retirement": 0.0, "renewable_cost": 0.0, "gas_supply": 0.0, "oil_price": 1.0, "nuclear": 1.0}
# The module each lever acts on first (nems_open/levers.py, "moves"): where the shock enters the picture.
ENTERS = {"carbon_price": ["electricity", "natural_gas", "oil", "coal"], "ev_2035": ["transportation"],
          "load_growth": ["commercial"], "building_code": ["residential", "commercial"],
          "appliance_standard": ["residential", "commercial"], "coal_retirement": ["electricity"],
          "renewable_cost": ["electricity"], "gas_supply": ["natural_gas"], "oil_price": ["oil"], "nuclear": ["electricity"]}

STORIES = [   # the 2050 page's story cards, same levers
    ("reference", "EIA's reference", "No new policy: the loop run at EIA's own settings.", {}),
    ("fast", "Fast clean-up", "A $100 carbon price, 90% EV sales by 2035, coal closed early, cheaper wind and solar, tighter buildings.",
     {"carbon_price": 100, "ev_2035": 0.9, "coal_retirement": 0.8, "renewable_cost": -1, "building_code": 0.2, "appliance_standard": 0.2}),
    ("ai", "AI boom", "Data centers add 600 TWh a year of demand by 2050.", {"load_growth": 600}),
    ("gas", "Cheap gas, slow EVs", "Plentiful shale gas, oil 25% cheaper, EV sales stuck at 35% of new cars.",
     {"gas_supply": 1, "oil_price": 0.75, "ev_2035": 0.35}),
    ("nuke", "Nuclear comeback", "50% more nuclear output by 2040, a $50 carbon price, data centers adding 300 TWh.",
     {"nuclear": 1.5, "carbon_price": 50, "load_growth": 300}),
]
EXTREMES = [   # one lever pushed to an end of its range, the rest at EIA's settings
    ("carbon_price", 200, "Carbon price $200 a ton"), ("ev_2035", 1.0, "Every new car electric by 2035"),
    ("ev_2035", 0.25, "EV sales stall at 25%"), ("load_growth", 1000, "1,000 TWh of new load"),
    ("building_code", 0.4, "Building codes 40% tighter"), ("appliance_standard", 0.4, "Appliances 40% better"),
    ("coal_retirement", 1.0, "All coal closed by 2035"), ("renewable_cost", -1, "Cheap wind and solar"),
    ("renewable_cost", 1, "Expensive wind and solar"), ("gas_supply", 1, "Plentiful gas"), ("gas_supply", -1, "Scarce gas"),
    ("oil_price", 2.0, "Oil price doubles"), ("oil_price", 0.5, "Oil price halves"), ("nuclear", 1.5, "50% more nuclear"),
    ("nuclear", 0.5, "Half the nuclear"),
]


def scenarios() -> list[dict]:
    out = [{"id": i, "label": l, "desc": d, "kind": "story", "levers": x} for i, l, d, x in STORIES]
    for k, v, label in EXTREMES:
        out.append({"id": f"{k}_{str(v).replace('.', 'p').replace('-', 'm')}", "label": label, "desc": label + ". Everything else at EIA's settings.",
                    "kind": "lever", "levers": {k: v}})
    return out


class Recorder:
    """Copies the US value of every VARS key at each demand and supply step."""

    def __init__(self, k24: float):
        self.k24, self.steps = k24, []

    def value(self, key, prices, q, co2, j):
        mod, _, kind, _, per = VARS[key]
        if kind == "q":
            return float(q[f"QBLK/{key}"][US, j]) / 1000
        if kind == "p":
            return float(prices[f"MPBLK/{key}"][US, j]) * self.k24 * per
        return None if co2 is None else float(sum(v[US, j] for v in co2.values()))

    def __call__(self, stage, *, cycle, year, itr, fcrl, j, prices, q, co2=None, converged=None, dp=None, dq=None, worst=None):
        row = {"y": year, "c": cycle, "i": itr, "f": fcrl, "s": stage[0],
               "v": [None if (x := self.value(k, prices, q, co2, j)) is None else round(x, 5) for k in KEYS]}
        if stage == "supply":
            row.update(ok=bool(converged), dp=float(f"{dp:.3g}"), dq=float(f"{dq:.3g}"), w=worst)
        self.steps.append(row)


def eia_values(base, k24) -> dict:
    """The same keys straight from EIA's AEO2026 reference, by year START..END (the "vs EIA" line)."""
    from nems_open.supply_standin import SupplyStandin
    prices = {k: v for k, v in base.items() if k.startswith("MPBLK/")}
    q = {k: v for k, v in base.items() if k.startswith("QBLK/")}
    co2 = SupplyStandin("cb2026").solve(q, carbon_price=np.zeros(61)).co2
    rec = Recorder(k24)
    return {k: [round(rec.value(k, prices, q, co2, y - FIRST_YEAR), 5) for y in range(START, END + 1)] for k in KEYS}


def run_one(sc: dict, fast: bool) -> dict:
    from nems_open import run_model
    x = {**LEVER_DEFAULTS, **sc["levers"]}
    left_out = []
    if fast:   # the stub refuses levers that edit ported inputs; a trial file says what it left out
        left_out = [k for k in ("building_code", "appliance_standard") if x[k]]
        x.update({k: 0.0 for k in left_out})
    pol = ux.policy({k: v for k, v in x.items() if k not in ("building_code", "appliance_standard") and v is not None},
                    x["building_code"], x["appliance_standard"])
    base = load_case("cb2026")
    d = base["MACOUT/mc_jpgdp"]
    k24 = float(d[2024 - 1987] / d[0])
    rec = Recorder(k24)
    t0 = time.time()
    ported = () if fast else PORTED
    r = run_model.run(pol, START, END, ported=ported, record=rec)
    entered = sorted({m for k, v in sc["levers"].items() if v != LEVER_DEFAULTS[k] for m in ENTERS[k]})
    return {
        **sc, "entered": entered, "ported": list(ported), "elec": "standin", "fast": fast, "left_out": left_out,
        "seconds": round(time.time() - t0, 1), "years": [START, END],
        "steps": rec.steps,
        "stable": {str(y): bool(v) for y, v in r.stable.items()},
    }


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="comma-separated scenario ids")
    ap.add_argument("--fast", action="store_true", help="every sector on the stub (seconds a run), for trying the page")
    a = ap.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    base = load_case("cb2026")
    d = base["MACOUT/mc_jpgdp"]
    k24 = float(d[2024 - 1987] / d[0])
    meta = {"keys": KEYS, "vars": {k: dict(zip(("module", "label", "kind", "unit"), v[:4])) for k, v in VARS.items()},
            "eia": eia_values(base, k24), "years": [START, END], "dollars": "2024 $",
            "about": "Every value is the US total a module handed the others at that step of run_model.run's loop "
                     "(scripts/think_runs.py records it through run_model.run's `record`). Nothing is interpolated."}
    (OUT / "meta.json").write_text(json.dumps(meta, separators=(",", ":")))
    todo = scenarios()
    if a.only:
        todo = [s for s in todo if s["id"] in a.only.split(",")]
    for sc in todo:
        f = OUT / f"{sc['id']}.json"
        if f.exists() and json.loads(f.read_text()).get("fast") == a.fast:
            continue
        print(f"{sc['id']}: running ({'stub' if a.fast else 'ported'})", flush=True)
        doc = run_one(sc, a.fast)
        f.write_text(json.dumps(doc, separators=(",", ":")))
        print(f"{sc['id']}: {doc['seconds']} s, {sum(1 for s in doc['steps'] if s['s'] == 's')} passes", flush=True)
        write_manifest()
    write_manifest()


def write_manifest() -> None:
    have = []
    for sc in scenarios():
        f = OUT / f"{sc['id']}.json"
        if f.exists():
            d = json.loads(f.read_text())
            have.append({k: d[k] for k in ("id", "label", "desc", "kind", "levers", "entered", "ported", "fast", "seconds")})
    (OUT / "manifest.json").write_text(json.dumps({"scenarios": have}, separators=(",", ":")))


if __name__ == "__main__":
    main()
