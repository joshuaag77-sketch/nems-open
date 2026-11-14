"""Record each AIMMS solve of the AIMMS-coupled EMM oracle for the showreel (a visual story of what AIMMS did).

Called by run_aimms.sh after every ECP or EFD solve, from the oracle's run folder. Appends one JSON line to
<SHOWREEL>/emm.jsonl and keeps the raw logs; for one sample year also the composite input and the solution file.
It only reads and copies files written by the solve, so it cannot change results.

Usage: python3 aimms_showreel.py <module> <year> <iteration> <wall seconds> <ok|failed>
"""

import json
import os
import re
import shutil
import sys
import time
from pathlib import Path

SHOWREEL = Path(os.environ.get("SHOWREEL_DIR", "/mnt/c/Users/joshu/dev/aimms-showreel"))
SAMPLE_YEAR = 2030
HEADLINE_MAX = 5


def read_stats(path: Path) -> dict:
    """AIMMS 'write ... to file' output: lines like `sr_rows := 123 ;` or `sr_status := "Optimal" ;`."""
    out = {}
    if not path.exists():
        return out
    for m in re.finditer(r"(\w+)\s*:=\s*(\"[^\"]*\"|[-+0-9.eE]+)\s*;", path.read_text(errors="replace")):
        key, val = m.group(1), m.group(2)
        out[key] = val.strip('"') if val.startswith('"') else float(val)
    return out


def headline(mod: str, year: int) -> dict:
    """A few totals from the solution file NEMS reads back (OutToNEMS), when its layout is known; see docs."""
    sol = Path(mod) / (f"OutToNEMS_{year}.txt" if mod == "ecp" else "")
    return {"solution_file_bytes": sol.stat().st_size} if sol.is_file() else {}


def main(mod: str, year: str, itr: str, wall: str, result: str) -> None:
    SHOWREEL.mkdir(parents=True, exist_ok=True)
    y, i = int(year), int(itr)
    stats = read_stats(Path(mod) / "showreel_stats.txt")
    rec = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "module": mod.upper(), "year": y, "iteration": i,
        "rows": stats.get("sr_rows"), "columns": stats.get("sr_cols"), "nonzeros": stats.get("sr_nonzeros"),
        "solver": "CPLEX 22.1 (AIMMS 25.5.7.1)",
        "solve_seconds": stats.get("sr_seconds"), "wall_seconds": float(wall), "iterations": stats.get("sr_iterations"),
        "objective": stats.get("sr_objective"),
        "status": stats.get("sr_status") or result, "solver_status": stats.get("sr_solver_status"),
        "fallback_with_safety": stats.get("sr_safety_status"),
        "headline": headline(mod, y),
    }
    with open(SHOWREEL / "emm.jsonl", "a") as f:
        f.write(json.dumps(rec) + "\n")
    logs = SHOWREEL / "logs" / f"{mod}_{y}_{i:02d}"
    logs.mkdir(parents=True, exist_ok=True)
    for src in list((Path(mod) / "log").glob("*")) + list(Path("main/wrapper/log").glob("*")):
        if src.is_file():
            shutil.copy2(src, logs / src.name)
    if y == SAMPLE_YEAR:
        sample = SHOWREEL / "sample" / f"{mod}_{y}_{i:02d}"
        sample.mkdir(parents=True, exist_ok=True)
        for pat in (f"composite_{y}*.txt", f"OutToNEMS_{y}*.txt", f"PassBack*_{y}*.txt"):
            for src in Path(mod).glob(pat):
                shutil.copy2(src, sample / src.name)


if __name__ == "__main__":
    main(*sys.argv[1:6])
