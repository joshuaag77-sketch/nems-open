"""Two short checks before the showroom queue, each under HEAVY.lock (about 10 minutes together).

    python scripts/showroom_checks.py ngmm    # NGMM in fixed-exports mode at its own cb2026 LNG path vs its endogenous run
    python scripts/showroom_checks.py lfmm    # one LFMM solve (2030, first iteration) without and with a $50/t carbon price

ngmm: the LNG lever (ngmm/lng.py) switches NGMM to EIA's fixed-exports mode. The calibration factors in AimmsGas come
from NGMM's endogenous cb2026 run (reference.pkl). Fixing exports at the volumes that run itself chose should give the
same prices; if it does, the factors hold for the LNG cases. Runs in its own folder (~/dev/oracle-cache/ngmm-fixed),
so reference.pkl and the shared run folder are untouched. The path is NGMM's own (reference.pkl's LNG row), not EIA's
restart, so the check isolates the mode; the two differ by under 1% (26.6 vs 26.8 Bcf/d in 2035).

lfmm: EIA's LFMM on cb2026's inputs for 2030, once as is and once with the carbon arrays (EMETAX, EMABLK J) for $50
per metric ton CO2 (2024 $) from 2030. Both solves must be optimal; the carbon one should move refinery fuel use and
product prices. Its own folder (~/dev/oracle-cache/lfmm-check).
"""

import json
import pickle
import shutil
import sys
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
CACHE = Path.home() / "dev" / "oracle-cache"
OUT = ROOT / "data" / "showroom"


def ngmm(first: int = 2024, last: int = 2050) -> dict:
    from nems_open.ngmm import aimms
    from nems_open.supply_standin.data import restart_path
    run = CACHE / "ngmm-fixed"
    run.mkdir(parents=True, exist_ok=True)
    shutil.copy(aimms.RUN_DIR / "reference.pkl", run / "reference.pkl")
    with open(run / "reference.pkl", "rb") as f:
        ref = pickle.load(f)["outputs"]
    own = np.full(61, np.nan)
    for y, o in ref.items():
        own[y - 1990] = o["NGTDMREP_NGEXPVOL"].get((3, y - 1989), np.nan) / 365.0
    from nems_open.snapshot import Snapshot
    hist = np.asarray(Snapshot()["NGTDMREP/ngexpvol"])[2] / 365.0
    path = np.where(np.isnan(own), hist, own)
    arrays = aimms.restart_arrays(restart_path("cb2026"))
    m = aimms.Ngmm(run, fresh=True, lng=path, showreel=None)
    rows = {}
    try:
        for y in range(first, last + 1):
            o, sec = m.call(y, 1, arrays)
            m.call(y, 2, arrays, ncrl=1, fcrl=1)
            j = y - 1989
            r = ref[y]
            hh = lambda d: float(d["NGTDMREP_OGHHPRNG"].get((j,), np.nan))
            wh = lambda d: float(d["NGTDMREP_OGWPRNG"].get((14, j), np.nan))
            lngv = lambda d: float(d["NGTDMREP_NGEXPVOL"].get((3, j), np.nan)) / 365.0
            rows[y] = {"henry_hub_fixed": hh(o), "henry_hub_endog": hh(r), "wellhead_fixed": wh(o), "wellhead_endog": wh(r),
                       "lng_bcfd_fixed": lngv(o), "lng_bcfd_endog": lngv(r), "seconds": round(sec, 1)}
            g = 100 * (rows[y]["henry_hub_fixed"] / rows[y]["henry_hub_endog"] - 1)
            print(f"{y}: Henry Hub {g:+.2f}%, LNG {rows[y]['lng_bcfd_fixed']:.2f} vs {rows[y]['lng_bcfd_endog']:.2f} Bcf/d",
                  flush=True)
    finally:
        m.close()
    gap = lambda a, b: max(abs(100 * (v[a] / v[b] - 1)) for v in rows.values() if v[b] and np.isfinite(v[a]))
    return {"years": rows, "worst_henry_hub_gap_pct": round(gap("henry_hub_fixed", "henry_hub_endog"), 3),
            "worst_wellhead_gap_pct": round(gap("wellhead_fixed", "wellhead_endog"), 3),
            "worst_lng_gap_pct": round(gap("lng_bcfd_fixed", "lng_bcfd_endog"), 3)}


def lfmm(year: int = 2030, usd_2024: float = 50.0) -> dict:
    from nems_open.lfmm.gams_couple import LfmmGams
    from nems_open.supply_standin.model import SupplyStandin
    cp = np.zeros(61)
    cp[year - 1990:] = usd_2024
    cp87 = SupplyStandin("cb2026")._cp87(cp)
    out = {}
    for name, carbon in (("none", None), ("carbon", cp87)):
        t = time.time()
        lf = LfmmGams(year, base={}, run=CACHE / "lfmm-check", showreel=False, carbon=carbon)
        cols = lf.call(year, 1, 0, lf.arrays)
        out[name] = {k: float(v[10]) for k, v in cols.items()}
        out[name + "_seconds"] = round(time.time() - t, 1)
        print(f"{name}: solved in {out[name + '_seconds']} s", flush=True)
    a, b = out["none"], out["carbon"]
    moved = {k: round(100 * (b[k] / a[k] - 1), 3) for k in a if k in b and abs(a[k]) > 1e-6 and abs(b[k] / a[k] - 1) > 1e-4}
    return {"year": year, "carbon_usd2024_per_t": usd_2024, "seconds": {k: out[k + "_seconds"] for k in ("none", "carbon")},
            "moved_pct": dict(sorted(moved.items(), key=lambda kv: -abs(kv[1]))),
            "headline_87usd_mmbtu": {k: {"none": a.get(k), "carbon": b.get(k)} for k in
                                     ("MPBLK/pmgtr", "MPBLK/pdstr", "MPBLK/pjftr")}}


def main(argv=None) -> int:
    which = (argv or sys.argv[1:] or ["ngmm", "lfmm"])
    OUT.mkdir(parents=True, exist_ok=True)
    for w in which:
        res = {"ngmm": ngmm, "lfmm": lfmm}[w]()
        (OUT / f"check_{w}.json").write_text(json.dumps(res, indent=1))
        print(json.dumps({k: v for k, v in res.items() if k != "years"}, indent=1)[:3000], flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
