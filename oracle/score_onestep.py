"""One-step capacity scores: each year solved once from EIA's own fleet of the year before (CapacityPath with retirement
groups), with the one-year LP and with ECP's horizon (capacity.HORIZON); cells inside 5% of 175 against cb2026 and the
AIMMS oracle. Needs no full run, so it works while HEAVY.lock is taken (about 25 minutes).

Run:  python oracle/score_onestep.py <oracle dump>/state/final/61 out.pkl
"""
import sys, pickle
from pathlib import Path
sys.path.insert(0, "oracle")
from score_capacity import DumpSnapshot
from nems_open.snapshot import Snapshot
from nems_open.emm import capacity, capacity_regions as cr

YEARS = (2027, 2030, 2035, 2050)
s = Snapshot()
o = DumpSnapshot(Path(sys.argv[1]), s)
out = {}
for label, horizon in (("before", False), ("after", True)):
    capacity.HORIZON = horizon
    res = []
    for y in YEARS:
        r = capacity.CapacityPath(s, first=y, groups=True).step(y)
        print(label, y, r.status, "steam %.0f" % r.capacity["steam"].sum(), flush=True)
        res.append(r)
    out[label] = res
pickle.dump(out, open(sys.argv[2], "wb"))
for label, res in out.items():
    for name, snap in (("cb2026", s), ("oracle", o)):
        cmp = cr.compare(snap, res, YEARS)
        tot = {y: int(sum((~cr.misses(*cmp[(f, y)])).sum() for f in cr.FUELS)) for y in YEARS}
        print(label, "vs", name, tot, flush=True)
    for r in res:
        print("   ", label, r.year, {g: round(float(r.capacity[g].sum())) for g in ("gas_cc", "gas_ct", "steam", "coal", "wind", "solar", "battery")},
              "retired", round(sum(float(v.sum()) for v in r.economic_retire.values())), flush=True)
