"""The finish-line test: the whole model, every finished module switched on, against EIA's AEO2026 reference.

    python scripts/full_model.py                 # runs it (about an hour; hold HEAVY.lock), writes web/data/full_model.json
    python scripts/full_model.py --plan          # prints what would run, runs nothing
    python scripts/full_model.py --from out.npz  # rebuilds the table from a saved run, no model run
    python scripts/full_model.py --watch         # the same run, narrated live year by year (a demo)
    python scripts/full_model.py --watch --years 2027 2030   # a short demo

One run of run_model.run, 2027-2050, on cb2026 with no new policy, so every gap is the model's own distance from
EIA, not a policy effect. Switches come from SWITCHES below: each is used only if run_model.run takes that keyword,
so a module that lands later (ngmm, elec_cap, coal, ...) joins the run once its switch exists, with no edit here.
Sectors come from ported_sectors(): industrial joins (with ind="ported") once run_model.run takes the ind switch.

Headline numbers, each by year against EIA's published arrays in the cb2026 restart file: total energy use, CO2,
power generation by fuel, Henry Hub, Brent, gasoline and diesel prices, electricity price, home gas price, the
household energy bill, electricity sales. A number this model does not compute yet (Brent before a world oil module) is listed with EIA's value and "not modeled yet", never a stand-in guess.

The page (web/scoreboard.html, "How close is the whole model to EIA") reads web/data/full_model.json.
"""

import argparse
import inspect
import json
import sys
import time
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

OUT = ROOT / "web" / "data" / "full_model.json"
FIRST, LAST = 2027, 2050
SHOW = (2030, 2035, 2040, 2045, 2050)
US, Y0 = 10, 1990                     # arrays run 1990-2050 (supply_standin.data FIRST_YEAR)

# keyword -> value for the full model. Missing keywords are skipped and listed as "not landed".
SWITCHES = {
    "elec": "lp",               # the dispatch LP
    "elec_price": "efp",        # EIA's ported EFP retail prices
    "macro": "frbus",           # the economy module (needs cycles >= 2)
    "ogs": "hsm",               # EIA's oil and gas supply (HSM) with the NGMM gas price loop
    "lfmm": "standin",          # the refining stand-in
    "ind": "ported",            # the ported industrial year loop (with "industrial" in ported)
    "elec_cap": "lp",           # capacity planning, when it lands
    "coal": "port",             # coal market, when it lands
}
CYCLES = 2


def ported_sectors() -> tuple[str, ...]:
    from nems_open import run_model
    out = ["residential", "commercial", "transportation"]
    if "ind" in inspect.signature(run_model.run).parameters:
        out.append("industrial")
    return tuple(out)


def plan() -> dict:
    from nems_open import run_model
    params = inspect.signature(run_model.run).parameters
    use = {k: v for k, v in SWITCHES.items() if k in params}
    return {"switches": use, "not_landed": sorted(k for k in SWITCHES if k not in params),
            "ported": list(ported_sectors()), "cycles": CYCLES}


# ---- the numbers ----------------------------------------------------------------------------------

GEN = {   # dispatch LP groups -> EIA's UEFDOUT generation arrays (billion kWh = TWh), as emm/dispatch_report.py
    "coal": (("coal", "coal_ccs"), ("ugnclnr", "ugncfnr")),
    "gas": (("gas_cc", "gas_ccs", "gas_ct", "steam"), ("ugngfnr", "ugnginr", "ugngcnr")),
    "nuclear": (("nuclear",), ("ugnurnr",)),
    "renewables": (("hydro", "wind", "solar", "other"), ("ugnhonr",)),
}
NUM_R = 25


def rows(r: dict, eia: dict) -> list[dict]:
    """r and eia: {key: (61,) arrays or None}. One row per headline number."""
    spec = [
        ("energy", "Total energy use", "quads"), ("co2", "US energy CO2", "million t"),
        ("gen_total", "Power generation, total", "TWh"), ("gen_coal", "Generation from coal", "TWh"),
        ("gen_gas", "Generation from gas", "TWh"), ("gen_nuclear", "Generation from nuclear", "TWh"),
        ("gen_renewables", "Generation from renewables", "TWh"), ("henry_hub", "Henry Hub gas price", "2024 $/MMBtu"),
        ("brent", "Brent crude price", "2024 $/barrel"), ("gasoline", "Gasoline price", "2024 $/gallon"),
        ("diesel", "Diesel price", "2024 $/gallon"), ("electricity", "Electricity price, all sectors", "2024 cents/kWh"),
        ("gas_home", "Home natural gas price", "2024 $/MMBtu"), ("bill", "Household energy bill", "2024 $/month"),
        ("sales", "Electricity sales", "TWh"),
    ]
    out = []
    for key, label, unit in spec:
        e, m = eia.get(key), r.get(key)
        row = {"key": key, "label": label, "unit": unit,
               "eia": {y: round(float(e[y - Y0]), 3) for y in SHOW} if e is not None else None}
        if m is None or e is None:
            row.update(model=None, gap_pct=None, worst_gap_pct=None, note="not modeled yet" if m is None else "no EIA value")
        else:
            yrs = range(FIRST, LAST + 1)
            gaps = [100 * (m[y - Y0] / e[y - Y0] - 1) for y in yrs if e[y - Y0]]
            row.update(model={y: round(float(m[y - Y0]), 3) for y in SHOW},
                       gap_pct={y: round(100 * (float(m[y - Y0]) / float(e[y - Y0]) - 1), 2) for y in SHOW if e[y - Y0]},
                       worst_gap_pct=round(float(max(gaps, key=abs)), 2),
                       mean_abs_gap_pct=round(float(np.mean(np.abs(gaps))), 2))
        out.append(row)
    return out


def numbers(prices, q, co2, base, homes, gen: dict | None, extra: dict) -> dict:
    """Headline series (61 years) from loop arrays. gen: LP groups -> (61,) TWh, or EIA's own (already grouped)."""
    import build_ux2050 as ux
    k = ux.to_2024(base)
    full = lambda a: np.asarray(a, dtype=np.float64)
    out = {"energy": full(q["QBLK/qtsas"][US]) / 1000,
           "co2": sum(full(v[US]) for v in co2.values())}
    for name, (v, per) in ux.PRICES.items():
        out[name] = full(prices[v][US]) * k * per
    res = sum(full(prices[f"MPBLK/p{f}rs"][US]) * full(q[f"QBLK/q{f}rs"][US]) for f in ux.RES_FUELS if f"QBLK/q{f}rs" in q)
    out["bill"] = res * k / homes / 12
    out["sales"] = full(q["QBLK/qelas"][US]) * 1e12 / 3412 / 1e9          # trillion Btu to TWh
    if gen:
        for g, v in gen.items():
            out[f"gen_{g}"] = full(v)
        out["gen_total"] = sum(full(v) for v in gen.values())
    for name, v in extra.items():
        out[name] = None if v is None else full(v) * k
    return out


def eia_numbers() -> dict:
    from nems_open.snapshot import Snapshot
    from nems_open.supply_standin.data import load_case
    from nems_open.supply_standin.model import SupplyStandin
    base, snap = load_case("cb2026"), Snapshot()
    co2 = SupplyStandin("cb2026").solve().co2      # EIA's fuel use with the same emission factors the model uses
    gen = {g: sum(np.asarray(base[f"UEFDOUT/{n}"], dtype=np.float64)[:, :NUM_R, :].sum(axis=(0, 1)) for n in names)
           for g, (_, names) in GEN.items()}
    homes = homes_series()
    return numbers(base, base, co2, base, homes, gen,
                   {"henry_hub": snap["NGTDMREP/oghhprng"], "brent": base["INTOUT/brent_price"]})


def homes_series() -> np.ndarray:
    from nems_open.uncertainty import households
    h = np.asarray(households("cb2026"), dtype=np.float64)
    return np.where(h > 0, h, np.nan)              # no housing count before EIA's history starts


def model_numbers(r) -> dict:
    from nems_open.supply_standin.data import load_case
    base = load_case("cb2026")
    gen = None
    if r.generation_twh:
        gen = {g: sum(np.asarray(r.generation_twh[n], dtype=np.float64) for n in lp if n in r.generation_twh)
               for g, (lp, _) in GEN.items()}
    return numbers(r.prices, r.quantities, r.co2, base, homes_series(), gen,
                   {"henry_hub": (getattr(r, "gas", None) or {}).get("henry_hub"), "brent": getattr(r, "brent", None)})


# ---- watch it run ---------------------------------------------------------------------------------

SECTOR_WORDS = {"residential": "homes", "commercial": "businesses", "transportation": "vehicles", "industrial": "factories"}


class Narrator:
    """run_model.run's record hook, in plain words: one line per pass, one per settled year. Reads only."""

    def __init__(self, ported, cycles: int, out=print):
        self.who = ", ".join(SECTOR_WORDS[s] for s in ported) or "every sector (on fitted curves)"
        self.cycles, self.out, self.t0, self.year, self.passes = cycles, out, time.time(), None, 0
        from nems_open.supply_standin.data import load_case
        import build_ux2050 as ux
        self.k, self.ux = ux.to_2024(load_case("cb2026")), ux

    def __call__(self, kind, cycle, year, itr, j, prices, q, **kw):
        if (cycle, year) != self.year:
            self.year, self.passes, self.settled = (cycle, year), 0, False
            head = f"Round {cycle} of {self.cycles}, " if self.cycles > 1 else ""
            self.out(f"\n{head}{year}  ({(time.time() - self.t0) / 60:.1f} min in)")
        if kind == "demand":
            quads = float(q["QBLK/qtsas"][US, j]) / 1000
            self.out(f"  pass {itr}: {self.who} asked for {quads:.1f} quadrillion Btu at last pass's prices")
            return
        self.passes += 1
        k, P = self.k, lambda v: float(prices[v][US, j])
        el = P("MPBLK/pelas") * k * self.ux.MMBTU_PER_KWH * 100
        gas, mg = P("MPBLK/pngel") * k, P("MPBLK/pmgtr") * k * 0.1205
        co2 = kw.get("co2")
        co2 = sum(float(v[US, j]) for v in co2.values()) if isinstance(co2, dict) else None
        line = (f"  pass {itr}: power plants and fuel markets answered: electricity {el:.1f} cents/kWh, "
                f"gas to power plants ${gas:.2f}/MMBtu, gasoline ${mg:.2f}/gal"
                + (f", CO2 {co2:,.0f} million t" if co2 is not None else ""))
        self.out(line)
        if kw.get("converged"):
            if not self.settled:
                self.out(f"  {year} settled in {self.passes} passes: buyers and sellers agree")
            else:
                self.out("  still agreed on the check pass")
            self.settled = True
        elif not kw.get("dp"):
            self.out("  first answer; the next pass checks whether it holds")
        else:
            what = str(kw.get("worst", "a price")).replace("MPBLK/p", "price ").replace("QBLK/q", "use of ")
            self.out(f"  not settled yet: {what} still moved {100 * kw['dp']:.1f}%")


# ---- run ------------------------------------------------------------------------------------------

def run(first: int = FIRST, last: int = LAST, watch: bool = False) -> tuple[object, dict, float]:
    from nems_open import run_model
    p = plan()
    t0 = time.time()
    rec = Narrator(p["ported"], CYCLES, lambda s: print(s, flush=True)) if watch else None
    if watch:
        print(f"The whole model, {first}-{last}, EIA's reference settings. On: {', '.join(f'{k}={v}' for k, v in p['switches'].items())}. "
              f"EIA's own code runs {Narrator(p['ported'], CYCLES).who}.", flush=True)
    r = run_model.run(None, first, last, "cb2026", tuple(p["ported"]), cycles=CYCLES, record=rec, **p["switches"])
    return r, p, (time.time() - t0) / 60


def save_run(r, path: Path) -> None:
    arrays = {f"p:{k}": v for k, v in r.prices.items()} | {f"q:{k}": v for k, v in r.quantities.items()}
    arrays |= {f"c:{k}": v for k, v in r.co2.items()}
    arrays |= {f"g:{k}": v for k, v in (r.generation_twh or {}).items()}
    arrays |= {f"n:{k}": np.asarray(v) for k, v in (getattr(r, "gas", None) or {}).items()}
    np.savez_compressed(path, **arrays, stable=np.array([[y, int(s)] for y, s in r.stable.items()] or [[0, 0]]))


def load_run(path: Path):
    from types import SimpleNamespace
    z = np.load(path, allow_pickle=False)
    pick = lambda pre: {k[2:]: z[k] for k in z.files if k.startswith(pre)}
    return SimpleNamespace(prices=pick("p:"), quantities=pick("q:"), co2=pick("c:"), generation_twh=pick("g:") or None, gas=pick("n:") or None,
                           stable={int(y): bool(s) for y, s in z["stable"] if y})


def table(r, p: dict, minutes: float | None) -> dict:
    stable = getattr(r, "stable", {}) or {}
    return {"generated": str(date.today()), "case": "cb2026, no new policy", "years": [FIRST, LAST], "shown": list(SHOW),
            "switches": p["switches"], "not_landed": p["not_landed"], "ported": p["ported"], "cycles": p["cycles"],
            "minutes": round(minutes, 1) if minutes else None,
            "converged_years": sum(1 for y, s in stable.items() if FIRST <= y <= LAST and s),
            "rows": rows(model_numbers(r), eia_numbers()),
            "method": ("One run of the whole model on EIA's reference settings. Gap = model / EIA - 1 for each year "
                       f"{FIRST}-{LAST}; 'worst' is the year furthest from EIA. CO2 for EIA uses EIA's fuel use with "
                       "the model's emission factors, so it measures fuel use, not accounting.")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--plan", action="store_true", help="print the switches and sectors, run nothing")
    ap.add_argument("--from", dest="src", type=Path, help="rebuild the table from a saved run (.npz)")
    ap.add_argument("--watch", action="store_true", help="narrate the run live, year by year and pass by pass")
    ap.add_argument("--years", type=int, nargs=2, metavar=("FIRST", "LAST"), help="a shorter run (a demo); no table")
    ap.add_argument("--save", type=Path, default=ROOT / "data" / "full_model_run.npz", help="where to keep the run")
    a = ap.parse_args(argv)
    p = plan()
    if a.plan:
        print(json.dumps(p, indent=1))
        return 0
    if a.src:
        r, minutes = load_run(a.src), None
    else:
        first, last = a.years or (FIRST, LAST)
        r, p, minutes = run(first, last, a.watch)
        if a.years:                                   # a demo span: the table needs the whole 2027-2050
            print(f"done in {minutes:.1f} min")
            return 0
        a.save.parent.mkdir(parents=True, exist_ok=True)
        save_run(r, a.save)
    t = table(r, p, minutes)
    OUT.write_text(json.dumps(t, indent=1))
    for row in t["rows"]:
        g = row["gap_pct"] or {}
        print(f"{row['label']:34} " + ("not modeled yet" if row["model"] is None else
              f"worst {row['worst_gap_pct']:+7.2f}%  2050 {g.get(2050, float('nan')):+7.2f}%"))
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
