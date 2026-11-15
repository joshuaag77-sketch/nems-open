"""The showroom's precomputed scenarios: 30 whole-model runs, defined here, run later (one heavy job at a time).

    python scripts/showroom_scenarios.py --list               # every scenario, its levers, and whether it can run
    python scripts/showroom_scenarios.py --estimate --tier 1  # runtime at one heavy job at a time
    python scripts/showroom_scenarios.py --tier 1 --run       # the launch set, one run at a time under HEAVY.lock

Each scenario maps to run_model.run arguments: one Policy plus the same switches for all of them (every finished
module on), except lfmm: EIA's LFMM (GAMS, about 2.4 hours a run) only where oil products matter (LFMM_GAMS), the
LFMM stand-in elsewhere. A scenario whose lever run_model cannot take yet says what is missing (NOT_YET) instead of
being approximated with a different lever.

The runner takes HEAVY.lock for one scenario at a time and gives it back between runs. Each finished run is saved to
data/showroom/<key>.npz with its headline table in web/data/showroom/<key>.json, and data/showroom/status.json records
every start, finish and error. Run it again after a crash: finished scenarios are skipped.

Data center load is added average load above EIA's own data center path (AEO2026 reference), flat across the year,
reaching the stated GW in 2035 linearly from 2027 and held after. 1 GW of average load is 8.76 TWh a year. The
regional split is explicit (DC_SHARES): by default EIA's own, the census-division pattern of extra commercial
electricity in its high electricity demand case (higheldmd minus cb2026, 2040).
"""

import argparse
import json
import os
import sys
import time
import traceback
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

FIRST_YEAR, LAST_YEAR, START = 1990, 2050, 2027
NYEARS = LAST_YEAR - FIRST_YEAR + 1

# Every finished module on. elec_cap='lp' so new load gets new plants; ogs='aimms' is EIA's NGMM with HSM between
# cycles; lfmm='gams' and coal='aimms' are EIA's own refinery and coal models.
SWITCHES = {"elec": "lp", "elec_price": "efp", "elec_cap": "lp", "macro": "frbus", "ogs": "aimms",
            "lfmm": "gams", "coal": "aimms", "ind": "ported"}
PORTED = ("residential", "commercial", "transportation", "industrial")
CYCLES = 2

DIVISIONS = ("New England", "Middle Atlantic", "East North Central", "West North Central", "South Atlantic",
             "East South Central", "West South Central", "Mountain", "Pacific")
# EIA's split (datacenter.regional_shares(): higheldmd minus cb2026 commercial electricity, 2040), rounded to 3 places.
DC_SHARES = dict(zip(DIVISIONS, (0.023, 0.167, 0.110, 0.057, 0.247, 0.023, 0.172, 0.121, 0.079)))
# A what-if, not a source: the build-out lands where it is landing today (Virginia and Georgia in South Atlantic,
# Texas in West South Central, Arizona in Mountain), 80% in three divisions.
DC_SHARES_CLUSTERED = dict(zip(DIVISIONS, (0.01, 0.04, 0.05, 0.03, 0.40, 0.03, 0.25, 0.15, 0.04)))

EV_EIA_2030 = 0.49   # EIA's reference plug-in share of new light-duty sales in 2030 (levers.py); 0.65 in 2035

# Levers run_model cannot take yet, and what each needs.
NOT_YET: dict[str, str] = {}
PARTIAL = {
    "gas_supply": ("Gas resource. The lever exists but shifts delivered gas and retail electricity prices by EIA's "
                   "lowogs/highogs price ratios; under ogs='aimms' HSM's resource base and NGMM do not see it. A real "
                   "resource case needs HSM's resource inputs from those side cases (tier 2)."),
    "lng_bcfd": ("LNG exports (Policy.lng_exports, ngmm/lng.py) run NGMM in its fixed-exports mode, while the "
                 "calibration factors come from NGMM's endogenous cb2026 run: check once that fixed exports at EIA's "
                 "own path reproduce the reference (one NGMM headless run, about 3 min)."),
}


@dataclass
class Scenario:
    key: str
    title: str
    story: str
    levers: dict = field(default_factory=dict)   # Policy fields, plus dc_gw, dc_shares, dc_flex, ev_2035, lng_bcfd

    def not_yet(self) -> list[str]:
        return [k for k in self.levers if k in NOT_YET]

    def partial(self) -> list[str]:
        return [k for k in self.levers if k in PARTIAL]


def ramp_to(value: float, by: int = 2035, start: int = START, off: float = 0.0) -> np.ndarray:
    """(61,) by year: off before start, linear to value in `by`, held after."""
    out = np.full(NYEARS, off, dtype=np.float64)
    for y in range(start, LAST_YEAR + 1):
        out[y - FIRST_YEAR] = off + (value - off) * min(1.0, (y - start + 1) / (by - start + 1))
    return out


def data_center(gw: float, shares: dict = DC_SHARES, flex: float = 0.0):
    """datacenter.AddedLoad: gw of average load above EIA's path by 2035, split by census division."""
    from nems_open.datacenter import AddedLoad
    s = np.array([shares[d] for d in DIVISIONS], dtype=np.float64)
    return AddedLoad(f"showroom_{gw:g}gw", ramp_to(gw * 8.76), s / s.sum(), flex)


def ev_path(share_2035: float) -> np.ndarray:
    """Plug-in share of new light-duty sales by year: EIA's own through 2030 (nan), linear from its 0.49 in 2030 to
    share_2035, held after. 0.50 is below EIA's 0.65 in 2035 (an EV stall); 0.75 is above it."""
    out = np.full(NYEARS, np.nan)
    for y in range(2031, LAST_YEAR + 1):
        out[y - FIRST_YEAR] = EV_EIA_2030 + (share_2035 - EV_EIA_2030) * min(1.0, (y - 2030) / 5)
    return out


def carbon_path(usd: float, start: int = 2030) -> np.ndarray:
    """2024 $ per metric ton CO2, flat from `start` (zero before)."""
    out = np.zeros(NYEARS)
    out[start - FIRST_YEAR:] = usd
    return out


def policy(sc: Scenario):
    """The run_model Policy for a scenario. Raises NotImplementedError for a lever run_model cannot take yet."""
    from nems_open.demand_adapter import Policy
    if sc.not_yet():
        raise NotImplementedError(f"{sc.key}: " + "; ".join(NOT_YET[k] for k in sc.not_yet()))
    lv = dict(sc.levers)
    kw = {"start_year": START}
    if "dc_gw" in lv:
        kw["added_load"] = data_center(lv.pop("dc_gw"), lv.pop("dc_shares", DC_SHARES), lv.pop("dc_flex", 0.0))
    if "ev_2035" in lv:
        kw["ev_share"] = ev_path(lv.pop("ev_2035"))
    if "carbon_price" in lv:
        kw["carbon_price"] = carbon_path(lv.pop("carbon_price"))
    if "lng_bcfd" in lv:
        from nems_open.ngmm import lng
        kw["lng_exports"] = lng.path(lv.pop("lng_bcfd"))
    return Policy(**kw, **lv)


def lfmm_for(sc: Scenario) -> str:
    """EIA's LFMM where refined products move (reference, carbon, EVs), the stand-in elsewhere."""
    return "gams" if sc.key in LFMM_GAMS else "standin"


def run_args(sc: Scenario) -> dict:
    """Keyword arguments for run_model.run."""
    return {"policy": policy(sc), "start_year": START, "end_year": LAST_YEAR, "baseline": "cb2026",
            "ported": PORTED, "cycles": CYCLES, **SWITCHES, "lfmm": lfmm_for(sc)}


S = Scenario
SCENARIOS = [
    S("reference", "EIA's reference", "AEO2026 reference settings, nothing changed: the yardstick for every other card."),
    # AI boom: data center load above EIA's own path
    S("dc50", "AI boom, 50 GW", "50 GW more data center load by 2035 than EIA expects.", {"dc_gw": 50}),
    S("dc100", "AI boom, 100 GW", "100 GW more data center load by 2035.", {"dc_gw": 100}),
    S("dc150", "AI boom, 150 GW", "150 GW more data center load by 2035.", {"dc_gw": 150}),
    S("dc100_clustered", "AI boom, 100 GW, clustered", "Same 100 GW, 80% of it in South Atlantic, Texas's division and Mountain.",
      {"dc_gw": 100, "dc_shares": DC_SHARES_CLUSTERED}),
    S("dc100_flex", "AI boom, 100 GW, flexible", "100 GW where a fifth of the energy can be curtailed at peaks.",
      {"dc_gw": 100, "dc_flex": 0.2}),
    # LNG wave
    S("lng30", "LNG wave, 30 Bcf/d", "LNG exports reach 30 Bcf/d by 2035 (EIA: 26.8).", {"lng_bcfd": 30}),
    S("lng35", "LNG wave, 35 Bcf/d", "LNG exports reach 35 Bcf/d by 2035.", {"lng_bcfd": 35}),
    S("lng40", "LNG wave, 40 Bcf/d", "LNG exports reach 40 Bcf/d by 2035.", {"lng_bcfd": 40}),
    # Both
    S("dc100_lng35", "AI boom and LNG wave", "100 GW of data centers and 35 Bcf/d of LNG compete for the same gas.",
      {"dc_gw": 100, "lng_bcfd": 35}),
    S("dc150_lng40", "Both, high", "150 GW and 40 Bcf/d.", {"dc_gw": 150, "lng_bcfd": 40}),
    # Carbon price
    S("co2_25", "Carbon price $25", "$25/t CO2 from 2030 (2024 $).", {"carbon_price": 25}),
    S("co2_50", "Carbon price $50", "$50/t CO2 from 2030.", {"carbon_price": 50}),
    S("co2_100", "Carbon price $100", "$100/t CO2 from 2030.", {"carbon_price": 100}),
    # Gas resource
    S("gas_low", "Less gas than hoped", "EIA's low oil and gas supply case.", {"gas_supply": -1.0}),
    S("gas_high", "More gas than expected", "EIA's high oil and gas supply case.", {"gas_supply": 1.0}),
    # EVs
    S("ev50", "EV stall", "Plug-ins stall at 50% of new car sales in 2035 (EIA: 65%).", {"ev_2035": 0.50}),
    S("ev75", "EV push", "Plug-ins reach 75% of new car sales in 2035.", {"ev_2035": 0.75}),
    # Combinations
    S("dc100_co2_50", "AI boom with a carbon price", "100 GW of data centers under $50/t.", {"dc_gw": 100, "carbon_price": 50}),
    S("dc100_gas_low", "AI boom on scarce gas", "100 GW of data centers with EIA's low gas supply.", {"dc_gw": 100, "gas_supply": -1.0}),
    S("dc100_gas_high", "AI boom on cheap gas", "100 GW of data centers with EIA's high gas supply.", {"dc_gw": 100, "gas_supply": 1.0}),
    S("dc100_nuclear", "AI boom with a nuclear push", "100 GW of data centers and 25% more nuclear output by 2040.",
      {"dc_gw": 100, "nuclear": 1.25}),
    S("dc100_cheap_renew", "AI boom with cheap renewables", "100 GW of data centers in EIA's low zero-carbon cost case.",
      {"dc_gw": 100, "renewable_cost": -1.0}),
    S("dc100_ev75", "AI boom and EV push", "Two new loads on the grid at once: 100 GW and 75% EV sales.",
      {"dc_gw": 100, "ev_2035": 0.75}),
    S("lng40_gas_low", "LNG wave on scarce gas", "40 Bcf/d of LNG with EIA's low gas supply.", {"lng_bcfd": 40, "gas_supply": -1.0}),
    S("lng35_gas_high", "LNG wave on cheap gas", "35 Bcf/d of LNG with EIA's high gas supply.", {"lng_bcfd": 35, "gas_supply": 1.0}),
    S("dc100_lng35_co2_50", "Boom, wave and a carbon price", "100 GW, 35 Bcf/d and $50/t together.",
      {"dc_gw": 100, "lng_bcfd": 35, "carbon_price": 50}),
    S("stress", "Stress test", "150 GW, 40 Bcf/d and EIA's low gas supply: the tightest gas market here.",
      {"dc_gw": 150, "lng_bcfd": 40, "gas_supply": -1.0}),
    S("ev75_co2_50", "Clean transport", "75% EV sales and $50/t.", {"ev_2035": 0.75, "carbon_price": 50}),
    S("co2_100_nuclear", "Deep cut", "$100/t and 25% more nuclear output.", {"carbon_price": 100, "nuclear": 1.25}),
]

# Runtime, minutes, one scenario (24 years, CYCLES cycles), from measured pieces:
MINUTES = {
    "loop": 145,          # the 2-cycle reference run of 2026-11-14 (elec lp, EFP, frbus, ogs hsm, coal aimms, ported x4)
    "lfmm_gams": 3 * 24 * CYCLES,          # lfmm-gams handover: about 3 min per year per cycle
    "elec_cap_lp": 1.5 * 24 * CYCLES,      # emm-capacity handover: 1 to 2 min a year
    "ngmm_aimms": 5.5 * CYCLES,            # docs/ngmm.md: about 5.5 min of NGMM per full run
}


BY_KEY = {s.key: s for s in SCENARIOS}
TIERS = {1: ("reference", "dc50", "dc100", "dc150", "lng30", "lng35", "lng40", "dc100_lng35", "co2_50", "co2_100",
             "ev75")}
LFMM_GAMS = {"reference", "co2_25", "co2_50", "co2_100", "ev50", "ev75", "ev75_co2_50", "co2_100_nuclear"}


def minutes(sc: Scenario) -> float:
    return sum(v for k, v in MINUTES.items() if k != "lfmm_gams" or lfmm_for(sc) == "gams")


def estimate(tier: int | None = None) -> dict:
    pick = [s for s in SCENARIOS if tier is None or s.key in TIERS[tier]]
    return {"scenarios": len(pick), "hours": round(sum(minutes(s) for s in pick) / 60, 1),
            "with_gams_lfmm": sum(lfmm_for(s) == "gams" for s in pick), "parts_min": MINUTES}


# ---- the runner -----------------------------------------------------------------------------------

LOCK = Path(os.environ.get("NEMS_HEAVY_LOCK", Path.home() / "dev" / "HEAVY.lock"))
HOLDER = "showroom"
OUT = ROOT / "data" / "showroom"
WEB = ROOT / "web" / "data" / "showroom"


def take_lock(wait_s: float = 120.0, log=print) -> None:
    """Wait until HEAVY.lock is free, then create it holding HOLDER (no clobber)."""
    said = False
    while True:
        try:
            fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, HOLDER.encode())
            os.close(fd)
            return
        except FileExistsError:
            if not said:
                try:
                    who = LOCK.read_text(errors="replace").strip()
                except FileNotFoundError:
                    who = "?"
                log(f"waiting for {LOCK} (held by {who})")
                said = True
            time.sleep(wait_s)


def give_lock() -> None:
    """Remove HEAVY.lock only if this runner holds it."""
    try:
        if LOCK.read_text(errors="replace").strip() == HOLDER:
            LOCK.unlink()
    except FileNotFoundError:
        pass


def status() -> dict:
    f = OUT / "status.json"
    return json.loads(f.read_text()) if f.exists() else {}


def _set_status(key: str, **kw) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    st = status()
    st[key] = {**st.get(key, {}), **kw}
    (OUT / "status.json").write_text(json.dumps(st, indent=1))


def done(key: str) -> bool:
    return (OUT / f"{key}.npz").exists() and (WEB / f"{key}.json").exists()


def run_one(sc: Scenario, run=None, log=print) -> None:
    """One scenario: run it, then save the run (npz) and its headline table (json). run: run_model.run, or a stub."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import full_model as fm
    if run is None:
        from nems_open import run_model
        run = run_model.run
    args = run_args(sc)
    ckpt = OUT / f"{sc.key}.checkpoint.pkl"   # a crash in cycle 2 or later restarts at that cycle, not from the start
    tag = json.dumps({"scenario": sc.key, "switches": {k: args[k] for k in SWITCHES}, "cycles": args.get("cycles")},
                     sort_keys=True, default=str)
    t0 = time.time()
    r = run(**args, checkpoint=(ckpt, tag))
    mins = (time.time() - t0) / 60
    OUT.mkdir(parents=True, exist_ok=True)
    WEB.mkdir(parents=True, exist_ok=True)
    fm.save_run(r, OUT / f"{sc.key}.npz")
    p = {"switches": {k: args[k] for k in SWITCHES}, "not_landed": [], "ported": list(PORTED), "cycles": CYCLES}
    t = fm.table(r, p, mins)
    t.update({"scenario": sc.key, "title": sc.title, "story": sc.story,
              "levers": {k: ("custom" if isinstance(v, dict) else v) for k, v in sc.levers.items()}})
    (WEB / f"{sc.key}.json").write_text(json.dumps(t, indent=1))
    ckpt.unlink(missing_ok=True)
    log(f"{sc.key}: done in {mins:.0f} min")


ES_CONTINUOUS, ES_SYSTEM_REQUIRED = 0x80000000, 0x00000001


def stay_awake(on: bool = True) -> bool:
    """Ask Windows not to idle-sleep while this process runs (SetThreadExecutionState, ES_CONTINUOUS |
    ES_SYSTEM_REQUIRED). The request ends with the process or with stay_awake(False); no power setting changes."""
    if sys.platform != "win32":
        return False
    import ctypes
    flags = ES_CONTINUOUS | (ES_SYSTEM_REQUIRED if on else 0)
    return bool(ctypes.windll.kernel32.SetThreadExecutionState(ctypes.c_uint(flags)))


def run_tier(tier: int, run=None, lock: bool = True, log=print) -> int:
    """Every scenario in the tier not done yet, one at a time, each under its own hold of HEAVY.lock.
    A failure is recorded in status.json and the queue goes on; a rerun retries it. Returns the number failed."""
    sys.path.insert(0, str(ROOT / "scripts"))
    import full_model as fm
    if run is None:
        missing = fm.preflight({**SWITCHES, "lfmm": "gams"}, PORTED)
        from nems_open.ngmm import aimms
        if any("lng_bcfd" in BY_KEY[k].levers for k in TIERS[tier]) and not (aimms.RUN_DIR / "reference_fixed.pkl").exists():
            missing.append(f"{aimms.RUN_DIR / 'reference_fixed.pkl'} (python -m nems_open.ngmm.aimms fixed, about 3 min)")
        if missing:
            log("Cannot run, missing: " + "; ".join(missing))
            return 1
    failed = 0
    for key in TIERS[tier]:
        sc = BY_KEY[key]
        if done(key):
            log(f"{key}: already done, skipped")
            continue
        if lock:
            take_lock(log=log)
        try:
            _set_status(key, started=time.strftime("%Y-%m-%d %H:%M"), lfmm=lfmm_for(sc), error=None)
            log(f"{key}: {sc.title} (lfmm={lfmm_for(sc)}, about {minutes(sc) / 60:.1f} h)")
            run_one(sc, run, log)
            _set_status(key, finished=time.strftime("%Y-%m-%d %H:%M"))
        except Exception as e:
            failed += 1
            _set_status(key, error=f"{type(e).__name__}: {e}", trace=traceback.format_exc()[-2000:])
            log(f"{key}: FAILED {type(e).__name__}: {e}")
        finally:
            if lock:
                give_lock()
    return failed


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--estimate", action="store_true")
    ap.add_argument("--tier", type=int, choices=sorted(TIERS))
    ap.add_argument("--run", action="store_true", help="run --tier, one scenario at a time under HEAVY.lock")
    a = ap.parse_args(argv)
    if a.run:
        if not a.tier:
            ap.error("--run needs --tier")
        say = lambda s: print(s, flush=True)
        say(f"wake request held: {stay_awake(True)}")
        try:
            return 1 if run_tier(a.tier, log=say) else 0
        finally:
            stay_awake(False)
    if a.list or not a.estimate:
        print(f"Switches for every run: {SWITCHES}, ported {PORTED}, cycles {CYCLES}")
        for s in SCENARIOS:
            flag = "NOT YET: " + ", ".join(s.not_yet()) if s.not_yet() else (
                "partial: " + ", ".join(s.partial()) if s.partial() else "ready")
            print(f"{s.key:20} {s.title:32} {flag:24} {s.levers}")
        for k, v in {**NOT_YET, **PARTIAL}.items():
            print(f"\n{k}: {v}")
    if a.estimate:
        print(estimate(a.tier))
    return 0


if __name__ == "__main__":
    sys.exit(main())
