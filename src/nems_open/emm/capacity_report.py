"""Compare the capacity expansion loop with the AEO2026 reference run.

Run:  python -m nems_open.emm.capacity_report [out.md]     (about 15 minutes)
"""

import pickle
import sys
from pathlib import Path

import numpy as np

from nems_open.emm import capacity, history
from nems_open.snapshot import Snapshot

TOLERANCE = 0.15
FLOOR_GW = 2.0               # a gap smaller than this is not a miss, whatever the percentage
CHECK_YEARS = (2027, 2030, 2035)
BASE_YEAR = 2024

# Category -> restart capacity prefixes (UECPOUT/UADD<prefix><u|n>, planned plus unplanned builds), and the model groups.
ADD_CATEGORIES = {
    "Gas combined cycle": (("cc", "ac", "a2"), ("gas_cc", "gas_cc_new")),
    "Gas combined cycle with CCS": (("as",), ("gas_ccs",)),
    "Gas turbines": (("ct", "at", "ic", "t2"), ("gas_ct", "gas_ct_new")),
    "Wind": (("wn", "wf", "wl"), ("wind",)),
    "Solar": (("pv", "pt", "st"), ("solar",)),
    "Batteries": (("ds",), ("battery",)),
    "Nuclear": (("nu", "sm"), ("nuclear",)),
}
# Retirements: EIA's coal and steam capacity only falls through retirement, so its change is the retirement.
RETIRE_CATEGORIES = {
    "Coal": (("cs",), ("coal",)),
    "Oil and gas steam": (("os",), ("steam",)),
}


def eia_additions(snapshot, year: int, prefixes) -> float:
    """Cumulative GW added since the end of 2024, planned plus unplanned, both owner classes."""
    y = year - history.FIRST_YEAR
    total = 0.0
    for p in prefixes:
        for o in ("u", "n"):
            try:
                a = snapshot[f"UECPOUT/uadd{p}{o}"]
            except KeyError:
                continue
            total += float(a[:, 27, y].sum())
    return total


def eia_retirements(snapshot, year: int, prefixes) -> float:
    """Cumulative GW retired since the end of 2024, from the fall in capacity."""
    y = year - history.FIRST_YEAR
    b = BASE_YEAR - history.FIRST_YEAR
    total = 0.0
    for p in prefixes:
        for o in ("u", "n"):
            a = snapshot[f"UDATOUT/ucap{p}{o}"]
            total += float(a[27, b] - a[27, y])
    return total


def model_additions(results, year: int, groups) -> float:
    total = 0.0
    for r in results:
        if r.year <= year:
            total += sum(float(r.planned_adds[g].sum()) + float(r.builds[g].sum()) for g in groups)
    return total


def model_retirements(results, year: int, groups) -> float:
    total = 0.0
    for r in results:
        if r.year <= year:
            total += sum(float(r.planned_retire[g].sum()) + float(r.economic_retire[g].sum()) for g in groups)
    return total


def is_miss(model: float, eia: float) -> bool:
    return abs(model - eia) > FLOOR_GW and abs(model / eia - 1.0 if eia else 1.0) > TOLERANCE


def compare(snapshot, results) -> dict:
    """{(kind, category, year): (model, eia)} in GW."""
    out = {}
    for name, (prefixes, groups) in ADD_CATEGORIES.items():
        for yr in CHECK_YEARS:
            out[("add", name, yr)] = (model_additions(results, yr, groups), eia_additions(snapshot, yr, prefixes))
    for name, (prefixes, groups) in RETIRE_CATEGORIES.items():
        for yr in CHECK_YEARS:
            out[("ret", name, yr)] = (model_retirements(results, yr, groups), eia_retirements(snapshot, yr, prefixes))
    return out


def table(cmp: dict) -> str:
    lines = ["| GW since end of 2024 | " + " | ".join(f"{y} model / EIA" for y in CHECK_YEARS) + " |", "|---|" + "---|" * len(CHECK_YEARS)]
    for kind, label in (("add", "Additions"), ("ret", "Retirements")):
        lines.append(f"| **{label}** |" + " |" * len(CHECK_YEARS))
        for (k, name, _), _ in cmp.items():
            pass
        names = [n for (k, n, y) in cmp if k == kind and y == CHECK_YEARS[0]]
        for name in names:
            cells = []
            for y in CHECK_YEARS:
                m, e = cmp[(kind, name, y)]
                err = (m / e - 1.0) if e else float("nan")
                cells.append(f"{m:,.1f} / {e:,.1f} ({err:+.0%}){' MISS' if is_miss(m, e) else ''}")
            lines.append(f"| {name} | " + " | ".join(cells) + " |")
    return "\n".join(lines)


def run_all(snapshot, cache=None):
    if cache and Path(cache).exists():
        return pickle.load(open(cache, "rb"))
    results = capacity.run(snapshot, 2025, 2035)
    if cache:
        pickle.dump(results, open(cache, "wb"))
    return results


def main(path=None, cache=None):
    snap = Snapshot()
    results = run_all(snap, cache)
    text = table(compare(snap, results))
    print(text)
    if path:
        Path(path).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None, sys.argv[2] if len(sys.argv) > 2 else None)
