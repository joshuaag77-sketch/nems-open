"""Turn the showroom's saved runs into the small JSON files joshagarwal.com/energy reads.

    python scripts/showroom_web.py --out <site>/data/energy                    # every story, real where finished
    python scripts/showroom_web.py --out <dir> --reference-npz <path>          # use another saved reference run
    python scripts/showroom_web.py --check <dir>                               # validate files against the schema

One file per scenario, <key>.json, plus eia.json (EIA's own AEO2026 reference) and index.json. Schema
"energy-showroom/1" (SCHEMA below): years 2025-2050, national series ("us") and per-EMM-region series
("region", 25 rows in EMM order TRE..BASN).

Where numbers come from:
  - A finished scenario: data/showroom/<key>.npz written by scripts/showroom_scenarios.py (status "model").
  - The reference: data/showroom/reference.npz when it exists, else --reference-npz (a saved full_model.py run).
  - A story whose run has not finished: the reference plus illustrative deltas from placeholder() below,
    status "placeholder". These are rules of thumb, not model output, and the page says so on every frame.

Regional numbers: the saved runs keep prices and quantities by census division (11 rows), not by EMM region.
Each EMM region gets the residential-load-weighted average of its divisions, with EIA's own weights
(emm.regions.emm_share_of_census, sector 1). So two EMM regions inside one division move together. Saving the
LP's (25, 61) wholesale prices in full_model.save_run would let a later version split them.
"""

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

Y0, US = 1990, 10
YEARS = list(range(2025, 2051))
J = np.array([y - Y0 for y in YEARS])
NDIV = 9
MMBTU_PER_KWH = 0.003412
TBTU_PER_BCF = 1.037          # trillion Btu per Bcf of dry gas (EIA's heat content, about 1,037 Btu/cf)

STORIES = {   # site story -> showroom scenario key
    "ai": "dc100",
    "lng": "lng35",
    "both": "dc100_lng35",
    "carbon": "co2_50",
}

SCHEMA = {
    "schema": "energy-showroom/1",
    "fields": {
        "key": "scenario key in scripts/showroom_scenarios.py",
        "status": "model (a finished full run), placeholder (reference plus illustrative deltas), or eia",
        "years": "2025..2050",
        "regions": "25 EMM region names in NEMS order",
        "us": {
            "added_load_twh": "data center load above EIA's path, TWh a year (an input)",
            "lng_bcfd": "LNG exports, Bcf/d (an input where the story sets it, else EIA's path)",
            "carbon_usd_t": "carbon price, 2024 $ per metric ton CO2 (an input)",
            "gas_power_bcfd": "natural gas burned in power plants, Bcf/d",
            "henry_hub": "Henry Hub spot price, 2024 $/MMBtu",
            "res_price": "residential electricity price, 2024 cents/kWh",
            "power_bill": "home electricity bill, average US home, 2024 $/month",
            "gen_gas_twh": "power generation from gas, TWh",
            "co2": "US energy CO2, million metric tons",
        },
        "region": {
            "res_price": "[25][26] residential electricity price, 2024 cents/kWh",
            "power_bill": "[25][26] home electricity bill, 2024 $/month",
        },
    },
}


# ---- shared inputs --------------------------------------------------------------------------------

def _ctx():
    from nems_open.emm import regions as R
    from nems_open.supply_standin.data import load_case
    from nems_open.uncertainty import restart_path
    import build_ux2050 as ux
    base = load_case("cb2026")
    with np.load(restart_path("cb2026"), allow_pickle=False) as z:
        houses = z["RESDREP/rshouses"].astype(np.float64) / 1e6           # (61, 9) millions of homes
    w = R.emm_share_of_census()[:25, :NDIV, 0]                              # (25, 9) residential load shares
    w = w / w.sum(axis=1, keepdims=True)
    return {"base": base, "k": ux.to_2024(base), "houses": houses, "w": w, "names": R.names()[:25]}


def _levers(key: str) -> dict:
    """The scenario's input paths by year (61,), from the same functions the runner uses."""
    import showroom_scenarios as ss
    from nems_open.ngmm import lng
    lv = ss.BY_KEY[key].levers if key in ss.BY_KEY else {}
    out = {"added_load_twh": np.zeros(61), "carbon_usd_t": np.zeros(61)}
    if "dc_gw" in lv:
        out["added_load_twh"] = ss.ramp_to(lv["dc_gw"] * 8.76)
    if "carbon_price" in lv:
        out["carbon_usd_t"] = ss.carbon_path(lv["carbon_price"])
    out["lng_bcfd"] = lng.path(lv["lng_bcfd"]) if "lng_bcfd" in lv else lng.eia_bcfd()
    return out


def _series(prices, q, gen, henry_hub, co2, ctx) -> dict:
    """National and regional series (by YEARS) from loop-shaped arrays. prices, q: {name: (11, 61)}."""
    k, houses, w = ctx["k"], ctx["houses"], ctx["w"]
    f = lambda a: np.asarray(a, dtype=np.float64)
    pel = f(prices["MPBLK/pelrs"])[:, J]                                  # (11, n) 1987 $/MMBtu
    qel = f(q["QBLK/qelrs"])[:, J]                                        # (11, n) trillion Btu
    h = houses[J].T                                                       # (9, n)
    div_price = pel[:NDIV] * k * MMBTU_PER_KWH * 100                     # cents/kWh
    div_bill = pel[:NDIV] * qel[:NDIV] * k / h / 12                       # $ million / million homes / 12
    us = {
        "gas_power_bcfd": f(q["QBLK/qngel"])[US, J] / TBTU_PER_BCF / 365,
        "henry_hub": None if henry_hub is None else f(henry_hub)[J] * k,
        "res_price": pel[US] * k * MMBTU_PER_KWH * 100,
        "power_bill": pel[US] * qel[US] * k / houses[J].sum(axis=1) / 12,
        "gen_gas_twh": None if gen is None else f(gen)[J],
        "co2": None if co2 is None else f(co2)[J],
    }
    region = {"res_price": w @ div_price, "power_bill": w @ div_bill}
    return {"us": us, "region": region}


def from_npz(path: Path, ctx) -> dict:
    import full_model as fm
    r = fm.load_run(path)
    gen = None
    if r.generation_twh:
        gen = sum(np.asarray(r.generation_twh[n], dtype=np.float64) for n in fm.GEN["gas"][0] if n in r.generation_twh)
    co2 = sum(np.asarray(v[US], dtype=np.float64) for v in r.co2.values()) if r.co2 else None
    hh = (r.gas or {}).get("henry_hub")
    return _series(r.prices, r.quantities, gen, hh, co2, ctx)


def from_eia(ctx) -> dict:
    import full_model as fm
    from nems_open.snapshot import Snapshot
    base = ctx["base"]
    gen = sum(np.asarray(base[f"UEFDOUT/{n}"], dtype=np.float64)[:, :fm.NUM_R, :].sum(axis=(0, 1)) for n in fm.GEN["gas"][1])
    return _series(base, base, gen, Snapshot()["NGTDMREP/oghhprng"], None, ctx)


# ---- placeholders ---------------------------------------------------------------------------------
# Illustrative only. Each rule is a round number chosen to give the right sign and a plausible size, so the page
# can be built and read before the runs finish. None of it is model output. Replace by finishing the runs.

PH = {
    "gas_share_new_load": 0.55,     # share of added data center energy met by gas plants
    "heat_rate": 7.0,               # MMBtu per MWh for those plants
    "hh_per_bcfd": 0.12,            # Henry Hub $/MMBtu per extra Bcf/d of US gas demand
    "fuel_passthrough": 0.35,       # share of the power price set by gas fuel cost
    "cap_cents_per_100twh": 0.15,   # national capacity and wires cost, cents/kWh per 100 TWh of added load
    "grid_t_per_mwh_2030": 0.33,    # power sector CO2 intensity in 2030, falling 2% a year
    "carbon_passthrough": 0.6,      # share of the carbon cost that reaches retail prices
    "carbon_gas_cut": 0.15,         # gas burn cut at $50/t
}
DC_SHARES = None


def placeholder(ref: dict, lev: dict, eia_lng: np.ndarray, ctx) -> dict:
    import showroom_scenarios as ss
    global DC_SHARES
    if DC_SHARES is None:
        DC_SHARES = np.array([ss.DC_SHARES[d] for d in ss.DIVISIONS])
    out = {"us": {k: (None if v is None else v.copy()) for k, v in ref["us"].items()},
           "region": {k: v.copy() for k, v in ref["region"].items()}}
    us, n = out["us"], len(YEARS)
    add = lev["added_load_twh"][J]
    lng_extra = np.maximum(lev["lng_bcfd"][J] - eia_lng[J], 0.0)
    carbon = lev["carbon_usd_t"][J]
    gas_burn_extra = add * PH["gas_share_new_load"] * PH["heat_rate"] / TBTU_PER_BCF / 365
    co2_cut = PH["carbon_gas_cut"] * carbon / 50.0
    gas_burn_extra = gas_burn_extra - co2_cut * ref["us"]["gas_power_bcfd"]
    d_hh = PH["hh_per_bcfd"] * (gas_burn_extra + lng_extra)
    us["gas_power_bcfd"] = ref["us"]["gas_power_bcfd"] + gas_burn_extra
    if us["henry_hub"] is not None:
        us["henry_hub"] = ref["us"]["henry_hub"] + d_hh
    if us["gen_gas_twh"] is not None:
        us["gen_gas_twh"] = ref["us"]["gen_gas_twh"] * (1 + gas_burn_extra / ref["us"]["gas_power_bcfd"])
    fuel = d_hh * PH["heat_rate"] * PH["fuel_passthrough"] / 10                       # cents/kWh
    years_on = np.array([max(0, y - 2030) for y in YEARS])
    intensity = PH["grid_t_per_mwh_2030"] * 0.98 ** years_on
    carb = carbon * intensity * PH["carbon_passthrough"] / 10                         # $/t x t/MWh = $/MWh -> cents
    cap_us = PH["cap_cents_per_100twh"] * add / 100
    # Capacity cost lands where the load lands: each region by its divisions' share of the build-out against
    # their share of homes.
    w = ctx["w"]
    home_share = ctx["houses"][2025 - Y0] / ctx["houses"][2025 - Y0].sum()
    tilt = np.clip(w @ (DC_SHARES / home_share), 0.3, 3.0)                              # (25,)
    d_region = fuel[None, :] + carb[None, :] + cap_us[None, :] * tilt[:, None]
    d_us = fuel + carb + cap_us
    kwh_region = ref["region"]["power_bill"] / (ref["region"]["res_price"] / 100)       # kWh a month
    kwh_us = ref["us"]["power_bill"] / (ref["us"]["res_price"] / 100)
    out["region"]["res_price"] = ref["region"]["res_price"] + d_region
    out["region"]["power_bill"] = ref["region"]["power_bill"] + d_region / 100 * kwh_region
    us["res_price"] = ref["us"]["res_price"] + d_us
    us["power_bill"] = ref["us"]["power_bill"] + d_us / 100 * kwh_us
    if us["co2"] is not None:
        us["co2"] = ref["us"]["co2"] + gas_burn_extra * 365 * TBTU_PER_BCF * 0.0531  # Mt per trillion Btu of gas
    assert out["region"]["res_price"].shape == (25, n)
    return out


# ---- writing --------------------------------------------------------------------------------------

def _r(a, nd=3):
    if a is None:
        return None
    a = np.asarray(a, dtype=np.float64)
    return np.where(np.isfinite(a), np.round(a, nd), np.nan).tolist() if a.ndim else round(float(a), nd)


def _clean(x):
    if isinstance(x, float) and not np.isfinite(x):
        return None
    if isinstance(x, list):
        return [_clean(v) for v in x]
    if isinstance(x, dict):
        return {k: _clean(v) for k, v in x.items()}
    return x


def document(key: str, title: str, story: str, status: str, s: dict, lev: dict, ctx, note: str, run: dict) -> dict:
    us = {k: _r(v) for k, v in s["us"].items()}
    us["added_load_twh"] = _r(lev["added_load_twh"][J], 1)
    us["lng_bcfd"] = _r(lev["lng_bcfd"][J], 2)
    us["carbon_usd_t"] = _r(lev["carbon_usd_t"][J], 1)
    return _clean({"schema": SCHEMA["schema"], "key": key, "title": title, "story": story, "status": status,
                   "note": note, "generated": str(date.today()), "run": run, "years": YEARS,
                   "regions": ctx["names"], "us": us, "region": {k: _r(v) for k, v in s["region"].items()}})


def check(d: dict) -> list[str]:
    bad = []
    if d.get("schema") != SCHEMA["schema"]:
        bad.append("schema")
    if d.get("years") != YEARS:
        bad.append("years")
    if len(d.get("regions", [])) != 25:
        bad.append("regions")
    for k in SCHEMA["fields"]["us"]:
        v = d.get("us", {}).get(k)
        if v is not None and len(v) != len(YEARS):
            bad.append(f"us.{k}")
    for k in SCHEMA["fields"]["region"]:
        v = d.get("region", {}).get(k)
        if not v or len(v) != 25 or any(len(row) != len(YEARS) for row in v):
            bad.append(f"region.{k}")
    return bad


def main(argv=None) -> int:
    import showroom_scenarios as ss
    from nems_open.ngmm import lng
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", type=Path)
    ap.add_argument("--runs", type=Path, default=ss.OUT, help="folder of saved scenario runs (<key>.npz)")
    ap.add_argument("--reference-npz", type=Path, help="saved reference run, if <runs>/reference.npz is missing")
    ap.add_argument("--check", type=Path, help="validate every <key>.json in this folder and exit")
    a = ap.parse_args(argv)
    if a.check:
        bad = {p.name: check(json.loads(p.read_text())) for p in a.check.glob("*.json") if p.name != "index.json"}
        bad = {k: v for k, v in bad.items() if v}
        print(json.dumps(bad or "ok", indent=1))
        return 1 if bad else 0
    if not a.out:
        ap.error("--out is required")
    ctx = _ctx()
    a.out.mkdir(parents=True, exist_ok=True)
    eia_lng = lng.eia_bcfd()
    sf = a.runs / "status.json"
    st = json.loads(sf.read_text()) if sf.exists() else {}

    ref_npz = a.runs / "reference.npz"
    ref_note = "Finished showroom reference run."
    if not ref_npz.exists():
        if not a.reference_npz or not a.reference_npz.exists():
            print(f"No reference run: {ref_npz} missing and no --reference-npz")
            return 2
        ref_npz = a.reference_npz
        ref_note = (f"Stand-in reference: {ref_npz.name}, the whole-model reference run of the scoreboard (ogs hsm, "
                    "LFMM stand-in, no capacity LP), until the showroom's own reference run finishes.")
    ref = from_npz(ref_npz, ctx)
    eia = from_eia(ctx)
    index = {"schema": SCHEMA["schema"], "generated": str(date.today()), "stories": {}, "files": {}}

    def write(name: str, d: dict):
        bad = check(d)
        if bad:
            raise ValueError(f"{name}: {bad}")
        (a.out / f"{name}.json").write_text(json.dumps(d, separators=(",", ":")))
        index["files"][name] = d["status"]

    zero = _levers("reference")
    write("eia", document("eia", "EIA's AEO2026 reference", "EIA's own published numbers.", "eia", eia, zero, ctx,
                          "EIA's AEO2026 reference case arrays (cb2026 restart file).", {}))
    write("reference", document("reference", ss.BY_KEY["reference"].title, ss.BY_KEY["reference"].story, "model",
                                ref, zero, ctx, ref_note, {"npz": ref_npz.name, **st.get("reference", {})}))
    for story, key in STORIES.items():
        sc, lev = ss.BY_KEY[key], _levers(key)
        npz = a.runs / f"{key}.npz"
        if npz.exists() and st.get(key, {}).get("finished"):
            s, status, note = from_npz(npz, ctx), "model", "Finished full-model run."
        else:
            s, status = placeholder(ref, lev, eia_lng, ctx), "placeholder"
            note = ("Placeholder: the reference run plus rules of thumb (showroom_web.PH), not a model result. "
                    "The full-model run for this story is queued.")
        write(key, document(key, sc.title, sc.story, status, s, lev, ctx, note, {"npz": npz.name, **st.get(key, {})}))
        index["stories"][story] = key
    index["placeholder_rules"] = PH
    (a.out / "index.json").write_text(json.dumps(index, indent=1))
    print(json.dumps(index["files"], indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
