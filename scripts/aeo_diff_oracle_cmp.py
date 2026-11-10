"""Compare a 2025 oracle's final-iteration state with the ref2025 restart, array by array.

    python -I scripts/aeo_diff_oracle_cmp.py <oracle-state-dir> <restart.npz> <tag> <year-dir>[,..] [out.json]

A restart array and the oracle's array of the same name are compared whole (same shape) as the largest
relative difference, plus a count of cells that differ by more than 1e-4. This is the test of whether the
2025 code on 2025 inputs reproduces EIA's 2025 reference restart.
"""
import json
import sys
from pathlib import Path

import numpy as np

state, rlx, tag, years = Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3], sys.argv[4].split(",")
z = np.load(rlx, allow_pickle=False)
byname = {}
for k in z.files:
    byname.setdefault(k.partition("/")[2].lower(), k)
res = {}
for y in years:
    d = state / tag / y
    for line in (d / "index.txt").read_text(encoding="latin-1").splitlines():
        p = line.split()
        if not p or p[0] not in byname:
            continue
        a = np.fromfile(d / f"{p[0]}.bin", dtype=np.dtype(p[1]))
        try:
            b = np.asarray(z[byname[p[0]]])
        except ValueError:
            continue
        if b.dtype.kind not in "iuf" or a.size != b.size:
            res.setdefault(y, {})[p[0]] = {"status": "shape", "oracle": a.size, "restart": b.size}
            continue
        a = a.astype(np.float64).reshape(-1)
        b = np.asfortranarray(b).astype(np.float64).reshape(-1, order="F")
        ok = np.isfinite(a) & np.isfinite(b)
        rel = np.abs(a - b) / np.maximum(np.abs(b), 1e-6)
        res.setdefault(y, {})[p[0]] = {"status": "ok", "n": int(a.size), "nan_o": int((~np.isfinite(a)).sum()),
                                       "max_rel": float(rel[ok].max()) if ok.any() else None,
                                       "n_bad": int((rel[ok] > 1e-4).sum())}
out = json.dumps(res, indent=1)
if len(sys.argv) > 5:
    Path(sys.argv[5]).write_text(out)
for y, r in res.items():
    ok = [k for k, v in r.items() if v["status"] == "ok"]
    bad = [k for k in ok if r[k]["n_bad"]]
    print(y, "compared", len(ok), "shape-mismatch", len(r) - len(ok), "differ", len(bad))
    for k in sorted(bad, key=lambda k: -(r[k]["max_rel"] or 0))[:12]:
        print("  ", k, r[k])
