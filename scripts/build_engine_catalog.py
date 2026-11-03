"""Build the demo's module catalog from the repo itself.

    python scripts/build_engine_catalog.py

For each box in the engine view: the EIA source it replaces (files and line counts,
read from nems-upstream), its main routines (from SCOPE.md's tables for ported modules,
from the Fortran's SUBROUTINE lines for the rest), our Python (files and line counts),
its status, and how many tests cover it (from `pytest --collect-only`). Nothing here is
typed by hand except which files belong to which module.

Writes web/data/engine.js (window.NEMS_ENGINE) and web/data/engine.json.
"""

import json
import re
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "nems-upstream"
SRC = ROOT / "src" / "nems_open"
OUT = ROOT / "web" / "data"
CODE_EXT = {".f", ".f90", ".py", ".ams", ".gms", ".inc"}

# Which files make up each module. Globs relative to nems-upstream (EIA) and src/nems_open
# (ours); tests by file name prefix.
MODULES = {
    "residential": {
        "name": "Residential", "side": "demand", "kind": "real",
        "eia": ["source/resd.f"], "ours": ["residential/*.py"],
        "tests": ["test_residential_", "test_oracle_residential", "test_run_demand"],
        "scope_table": "### Routine map",
    },
    "commercial": {
        "name": "Commercial", "side": "demand", "kind": "real",
        "eia": ["source/comm.f"], "ours": ["commercial/*.py"],
        "tests": ["test_commercial_", "test_oracle.py", "test_run_demand"],
        "scope_table": "## Pilot progress",
    },
    "industrial": {
        "name": "Industrial", "side": "demand", "kind": "partial",
        "eia": ["source/ind.f"], "ours": ["demand_adapter.py", "fit_elasticities.py"],
        "tests": ["test_run_model"], "scope_row": "Industrial demand",
    },
    "transportation": {
        "name": "Transportation", "side": "demand", "kind": "partial",
        "eia": ["source/tran.f", "source/tranair.f", "source/tranfrt.f"],
        "ours": ["demand_adapter.py", "fit_elasticities.py"],
        "tests": ["test_run_model"], "scope_row": "Transportation demand",
    },
    "electricity": {
        "name": "Electricity", "side": "supply", "kind": "stand",
        "eia": ["source/uecp.f", "source/uefd.f", "source/udat.f", "source/uefp.f", "source/uldsm.f",
                "models/ecp/**/*", "models/efd/**/*"],
        "ours": ["supply_standin/*.py"], "tests": ["test_supply_standin"], "scope_row": "Electricity",
        "prices": ["MPBLK/pelrs", "MPBLK/pelcm", "MPBLK/pelin"],
    },
    "natural_gas": {
        "name": "Natural gas", "side": "supply", "kind": "stand",
        "eia": ["models/ngas/**/*"], "ours": ["supply_standin/*.py"], "tests": ["test_supply_standin"],
        "scope_row": "Coal, natural gas, restore",
        "prices": ["MPBLK/pngrs", "MPBLK/pngcm", "MPBLK/pngin", "MPBLK/pngel"],
    },
    "oil": {
        "name": "Oil and refining", "side": "supply", "kind": "stand",
        "eia": ["source/refine.f", "source/refine_hogs.f", "source/refine_logs.f", "models/lfmm/**/*"],
        "ours": ["supply_standin/*.py"], "tests": ["test_supply_standin"],
        "scope_row": "Liquid fuels (refining)",
        "prices": ["MPBLK/pmgtr", "MPBLK/pjftr", "MPBLK/plgrs"],
    },
    "coal": {
        "name": "Coal", "side": "supply", "kind": "stand",
        "eia": ["models/coal/**/*"], "ours": ["supply_standin/*.py"], "tests": ["test_supply_standin"],
        "scope_row": "Coal, natural gas, restore", "prices": ["MPBLK/pclel", "MPBLK/pclin"],
    },
    "emissions": {
        "name": "Emissions", "side": "supply", "kind": "stand",
        "eia": ["models/epm/**/*"], "ours": ["supply_standin/model.py"], "tests": ["test_supply_standin"],
        "scope_row": "Emissions policy (EPM)",
    },
}


def code_files(base: Path, patterns: list[str]) -> list[Path]:
    out = set()
    for pat in patterns:
        for p in base.glob(pat):
            if p.is_file() and p.suffix.lower() in CODE_EXT and "backup" not in p.parts:
                out.add(p)
    return sorted(out)


def count_lines(p: Path) -> int:
    with open(p, "rb") as f:
        return sum(1 for _ in f)


def fortran_routines(files: list[Path], top: int = 12) -> list[dict]:
    """Routine starts, longest first: SUBROUTINE and FUNCTION in Fortran, Procedure in
    AIMMS (.ams), def in Python. An AIMMS procedure runs to its closing brace; the
    others run to the next routine's start."""
    pat = re.compile(r"^\s{0,10}(?:RECURSIVE\s+)?(SUBROUTINE|(?:REAL|INTEGER|LOGICAL)(?:\*\d+)?\s*FUNCTION|FUNCTION)\s+([\w$]+)", re.I)
    aimms = re.compile(r"^\s*(Procedure)\s+(\w+)\s*\{")
    python = re.compile(r"^(?:    )?(def)\s+(\w+)")
    found = []
    for f in files:
        ext = f.suffix.lower()
        if ext not in (".f", ".f90", ".ams", ".py"):
            continue
        lines = f.read_text(errors="replace").splitlines()
        if ext in (".ams", ".py"):
            rx = aimms if ext == ".ams" else python
            starts = [(i + 1, m.group(2)) for i, l in enumerate(lines) if (m := rx.match(l))]
        else:
            starts = [(i + 1, m.group(2).upper()) for i, l in enumerate(lines)
                      if l[:1] not in ("c", "C", "!", "*") and (m := pat.match(l))]
        for n, (line, name) in enumerate(starts):
            if ext == ".ams":  # an AIMMS procedure ends at its matching closing brace
                depth, end = 0, line
                for i in range(line - 1, len(lines)):
                    depth += lines[i].count("{") - lines[i].count("}")
                    if depth <= 0 and i >= line - 1 and "{" in "".join(lines[line - 1:i + 1]):
                        end = i + 2
                        break
            else:
                end = starts[n + 1][0] if n + 1 < len(starts) else len(lines) + 1
            found.append({"name": name, "file": f.name, "line": line, "lines": end - line})
    # EIA ships near-copies (refine.f, refine_hogs.f, refine_logs.f; two gas projects):
    # list each routine name once.
    seen, out = set(), []
    for r in sorted(found, key=lambda r: -r["lines"]):
        if r["name"].lower() not in seen:
            seen.add(r["name"].lower())
            out.append(r)
    return out[:top]


def markdown_table(text: str, heading: str) -> list[dict]:
    """The first table after a heading in SCOPE.md, as dicts keyed by header."""
    i = text.find(heading)
    if i < 0:
        return []
    rows = []
    header = None
    for line in text[i:].splitlines()[1:]:
        if not line.startswith("|"):
            if header:
                break
            continue
        cells = [c.strip().replace("`", "") for c in line.strip().strip("|").split("|")]
        if header is None:
            header = cells
        elif not set(line) <= set("|-: "):
            rows.append(dict(zip(header, cells)))
    return rows


def collected_tests() -> Counter:
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"], cwd=ROOT,
                         capture_output=True, text=True).stdout
    files = Counter()
    for line in out.splitlines():
        if "::" in line:
            files[line.split("::")[0].replace("\\", "/").split("/")[-1]] += 1
    return files


def routines_from_scope(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        name = r.get("Routine") or r.get("Subroutine")
        state = r.get("State", "")
        if not name:
            continue
        done = state.lower().startswith("done") or state.lower().startswith("ported")
        out.append({"name": name, "state": state, "match": r.get("Match vs EIA", ""),
                    "lines": r.get("Lines", ""), "done": bool(done)})
    return out


def main() -> None:
    scope = (ROOT / "SCOPE.md").read_text(encoding="utf-8")
    module_map = {r["Module"]: r for r in markdown_table(scope, "## Module map")}
    tests = collected_tests()
    coef = json.loads((SRC / "supply_standin" / "coefficients.json").read_text())
    catalog = {}
    for key, m in MODULES.items():
        eia_files = code_files(UPSTREAM, m["eia"])
        ours = code_files(SRC, m["ours"])
        n_tests = {f: c for f, c in tests.items() if any(f.startswith(p) for p in m["tests"])}
        entry = {
            "name": m["name"], "side": m["side"], "kind": m["kind"],
            "eia_lines": sum(count_lines(p) for p in eia_files),
            "eia_files": [{"path": str(p.relative_to(UPSTREAM)).replace("\\", "/"), "lines": count_lines(p)}
                          for p in sorted(eia_files, key=count_lines, reverse=True)[:8]],
            "eia_file_count": len(eia_files),
            "ours_lines": sum(count_lines(p) for p in ours),
            "ours_files": [str(p.relative_to(SRC.parent.parent)).replace("\\", "/") for p in ours],
            "tests": sum(n_tests.values()), "test_files": n_tests,
        }
        if "scope_table" in m:
            entry["routines"] = routines_from_scope(markdown_table(scope, m["scope_table"]))
            entry["routines_source"] = "SCOPE.md"
        else:
            entry["routines"] = [{"name": r["name"], "state": "", "match": "", "lines": str(r["lines"]),
                                  "done": False, "file": r["file"]} for r in fortran_routines(eia_files)]
            entry["routines_source"] = ("routine headers in EIA's source (Fortran SUBROUTINE, AIMMS Procedure, Python def)"
                                        if entry["routines"] else "")
        row = module_map.get(m.get("scope_row", ""), {})
        entry["eia_state"] = row.get("State", "")
        entry["blocker"] = row.get("Blocker", "")
        if "prices" in m:
            entry["fits"] = [{"price": p, **{k: coef["prices"][p][k] for k in ("coef", "r2", "rmse_pct")}}
                             for p in m["prices"] if p in coef["prices"]]
        if key == "electricity":
            entry["switching"] = {k: coef["power_switching"][k] for k in ("gas_own", "coal_from_gas_cost", "coal_own")}
        catalog[key] = entry
    data = {"modules": catalog, "totals": {"tests": sum(tests.values()), "generated": str(date.today())}}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "engine.json").write_text(json.dumps(data, indent=1))
    (OUT / "engine.js").write_text("window.NEMS_ENGINE = " + json.dumps(data, separators=(",", ":")) + ";\n")
    for k, e in catalog.items():
        print(f"{k:15} EIA {e['eia_lines']:>8} lines in {e['eia_file_count']:>3} files, ours {e['ours_lines']:>6}, "
              f"tests {e['tests']:>4}, routines {len(e['routines'])}")
    print("tests collected:", data["totals"]["tests"])


if __name__ == "__main__":
    main()
