"""Run the four data center cases with the real ported modules and the dispatch LP.

    python scripts/datacenter_runs.py [--bundle-only]

Residential, commercial and transportation are EIA's ported modules; electricity is the
dispatch LP (elec="lp"), on EIA's reference fleet; industrial stays on the stub; gas, oil, coal
and retail power prices stay on the fitted stand-in (elec_price="standin": the ported EFP does
not see dispatch costs yet, so it could not see what this load does to them).

One run at a time, about an hour or more each. A finished case is skipped on a rerun, so the
script can be stopped and resumed. The load assumptions and their sources are in
src/nems_open/datacenter_load.json.

Writes web/data/datacenter/<case>.json, in the demo's scenario format with the load and LP
numbers added, and web/data/datacenter.js (window.NEMS_DATACENTER) with the sources.
"""

import json
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

import precompute_scenarios as fast  # noqa: E402
from engine_runs import BILL_FUELS, households  # noqa: E402
from nems_open import datacenter as dc  # noqa: E402
from nems_open.demand_adapter import Policy  # noqa: E402
from nems_open.run_model import PORTED, run  # noqa: E402
from nems_open.supply_standin import SupplyStandin  # noqa: E402
from nems_open.supply_standin.data import US, load_case  # noqa: E402

OUT = ROOT / "web" / "data"
SECTORS = PORTED + ("transportation",)


def rounded(a, n=1):
    return [None if np.isnan(x) else round(float(x), n) for x in np.asarray(a, dtype=float)]


def bill(prices, quantities, base, homes):
    """Household energy bill: home spending on the priced fuels over households, 2024 $ a year."""
    spend = sum(quantities[f"QBLK/q{f}rs"][US] * prices[f"MPBLK/p{f}rs"][US] for f in BILL_FUELS)  # million 1987 $
    with np.errstate(divide="ignore", invalid="ignore"):
        return spend * 1e6 * fast.to_2024(base) / homes


def one(key: str) -> dict:
    t = time.time()
    add = dc.added_load(key)
    pol = Policy(added_load=add, start_year=fast.START)
    r = run(pol, fast.START, fast.LAST, ported=SECTORS, elec="lp", elec_price="standin")
    base = load_case("cb2026")
    power = {k: r.quantities[k] for k in ("QBLK/qngel", "QBLK/qclel", "QBLK/qrlel", "QBLK/qdsel") if k in r.quantities}
    supply = SupplyStandin("cb2026").solve(r.quantities, carbon_price=pol.carbon(), power_fuel=power, co2_el=r.co2["el"])
    by_year = {}
    for p in r.passes:
        by_year.setdefault(p.year, []).append(p)
    report = {str(y): {"passes": len(ps), "dp": [float(f"{p.max_price_change:.3g}") for p in ps],
                       "dq": [float(f"{p.max_quantity_change:.3g}") for p in ps], "worst": ps[0].worst_price}
              for y, ps in by_year.items()}
    k, j = fast.to_2024(base), fast.J
    total = dc.case_path_twh(key)
    return {
        "id": key, "label": dc.SOURCE["cases"][key]["label"],
        **fast.series(r.prices, r.quantities, r.co2_total, base),
        "trace": fast.trace(supply, r.quantities, pol, base),
        "convergence": report, "routines": r.passes[0].routines,
        "wholesale": rounded(r.wholesale_us[j] * k),
        "generation_twh": {g: rounded(v[j]) for g, v in r.generation_twh.items()},
        "bill": rounded(bill(r.prices, r.quantities, base, households("cb2026"))[j], 0),
        "datacenter_twh": rounded(total[j], 0),
        "datacenter_gw": rounded(total[j] / 8.76 / dc.LOAD_FACTOR, 0),
        "added_twh": rounded((add.twh if add else np.zeros(61))[j], 0),
        "unserved_twh": rounded(r.unserved_twh[j], 1),
        "curtailed_twh": rounded(r.curtailed_twh[j], 1),
        "flex_share": add.flex_share if add else 0.0,
        "minutes": round((time.time() - t) / 60, 1),
    }


def bundle() -> None:
    cases = {}
    for key in dc.SOURCE["cases"]:
        f = OUT / "datacenter" / f"{key}.json"
        if f.exists():
            cases[key] = {**json.loads(f.read_text()), "label": dc.SOURCE["cases"][key]["label"]}
    base = load_case("cb2026")
    eia = {"bill": rounded(bill(base, base, base, households("cb2026"))[fast.J], 0)}
    # EIA's own high-demand case builds plants: the check on what a fixed fleet does to CO2
    hi = load_case("higheldmd")
    hi_co2, ref_co2 = SupplyStandin("higheldmd").solve().co2_total, SupplyStandin("cb2026").solve().co2_total
    check = {"added_twh": rounded((hi["QBLK/qelas"][US] - base["QBLK/qelas"][US])[fast.J] / dc.TBTU_PER_TWH, 0),
             "co2_mt": rounded((hi_co2 - ref_co2)[fast.J], 0)}
    data = {"years": fast.YEARS, "start_year": fast.START, "dollars": "2024 $", "sectors": list(SECTORS), "elec": "lp",
            "sources": dc.SOURCE["sources"], "case_notes": {k: {n: v.get(n) for n in ("label", "short", "anchors", "sources", "flex_share")}
                                                            for k, v in dc.SOURCE["cases"].items()},
            "choices": dc.SOURCE["choices"], "eia": eia, "eia_builds": check, "cases": cases,
            "complete": len(cases) == len(dc.SOURCE["cases"])}
    (OUT / "datacenter.js").write_text("window.NEMS_DATACENTER = " + json.dumps(data, separators=(",", ":")) + ";\n")
    print(f"datacenter.js: {len(cases)} of {len(dc.SOURCE['cases'])} cases", flush=True)


def main() -> None:
    (OUT / "datacenter").mkdir(parents=True, exist_ok=True)
    if "--bundle-only" not in sys.argv:
        for key in dc.SOURCE["cases"]:
            f = OUT / "datacenter" / f"{key}.json"
            if f.exists():
                continue
            d = one(key)
            f.write_text(json.dumps(d, separators=(",", ":")))
            print(f"done {key} in {d['minutes']} min; 2050 CO2 {d['co2'][-1]}, unserved {d['unserved_twh'][-1]}", flush=True)
            bundle()
    bundle()


if __name__ == "__main__":
    main()
