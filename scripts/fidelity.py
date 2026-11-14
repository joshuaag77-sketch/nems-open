"""Build the fidelity scoreboard: how close each module and each headline number is to EIA.

    python scripts/fidelity.py

Three grades, worst last:
- "matches EIA": a port of EIA's code whose tests compare it with EIA's own Fortran, run as
  the oracle (oracle/). Evidence: the loosest tolerance its tests assert, the tests, and the
  rows of its progress table in SCOPE.md that are done.
- "within X%": our own model of the piece (not a port), measured against EIA's AEO2026
  reference run (cb2026). X is the worst gap over 2027-2050 in the demo's reference run.
- "stand-in": a curve or elasticity fitted to EIA's runs. Evidence: what it is fitted from
  and how well (supply_standin/coefficients.json, demand_elasticities.json).

Nothing here is a grade typed by hand. What is declared below is wiring: which files and
tables belong to a module, and which modules produce each number on the demo page. The
grades come from SCOPE.md, the tests (`pytest --collect-only` and the tolerances in their
source), the fit files, and the demo's own reference runs (web/data).

Writes web/data/fidelity.json and web/data/fidelity.js (window.NEMS_FIDELITY).
"""

import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src" / "nems_open"
TESTS = ROOT / "tests"
WEB = ROOT / "web" / "data"
sys.path.insert(0, str(ROOT / "scripts"))
from build_engine_catalog import markdown_table  # noqa: E402

FIRST, LAST = 2027, 2050          # the years the demo's levers act on
SAME = 0.005                      # a ported module's demo number counts as matching within 0.5%

# Ported modules: test files (by name prefix), the harnesses they run through, and the
# SCOPE.md table that lists their routines (heading, state column, match column).
PORTS = {
    "residential": {"name": "Residential demand", "tests": ["test_residential_", "test_oracle_residential"],
                    "harness": ["resd_oracle.py"], "table": ("### Routine map", "State", "State")},
    "commercial": {"name": "Commercial demand", "tests": ["test_commercial_", "test_oracle.py"],
                   "harness": ["oracle_harness.py"], "table": ("## Pilot progress", "State", "Match vs EIA")},
    "transportation": {"name": "Transportation demand", "tests": ["test_tran_"],
                       "harness": ["tran_harness.py"], "table": ("### Port progress", "State", "Match vs oracle")},
    "ldsm": {"name": "Electricity load and demand (LDSM)", "tests": ["test_ldsm_"], "harness": ["emm_oracle.py"],
             "table": ("## LDSM port", "Python", "Check")},
    "efp": {"name": "Electricity finance and pricing (EFP)", "tests": ["test_efp_"], "harness": ["emm_oracle.py"],
            "table": ("## EFP port", "Python", "Checked")},
}
# Rows that are not part of a module's yearly path (reports, switched-off features).
NOT_COUNTED = re.compile(r"^(skip|not ported)", re.I)
NOT_DONE = re.compile(r"^(to do|not yet)", re.I)

# Our own models of a piece of NEMS (not ports): measured against cb2026 in the demo.
OWN = {
    "dispatch": {"name": "Electricity dispatch LP", "tests": ["test_emm_dispatch", "test_emm_capacity", "test_run_model_lp"],
                 "measure": ("co2_sector", "el"), "doc": "docs/dispatch.md"},
}

# Stand-ins: which fitted prices or elasticities they use.
STANDINS = {
    "electricity": {"name": "Electricity prices", "prices": ["MPBLK/pelrs", "MPBLK/pelcm", "MPBLK/pelin"],
                    "doc": "docs/supply_standin.md"},
    "natural_gas": {"name": "Natural gas", "prices": ["MPBLK/pngrs", "MPBLK/pngcm", "MPBLK/pngin", "MPBLK/pngel"],
                    "doc": "docs/supply_standin.md"},
    "oil": {"name": "Oil and refining", "prices": ["MPBLK/pmgtr", "MPBLK/pdstr", "MPBLK/pjftr", "MPBLK/plgrs"],
            "doc": "docs/supply_standin.md"},
    "coal": {"name": "Coal", "prices": ["MPBLK/pclel", "MPBLK/pclin"], "doc": "docs/supply_standin.md"},
    "emissions": {"name": "Emissions", "prices": [], "doc": "docs/supply_standin.md"},
    "demand_stub": {"name": "Demand stub (any sector not run through its port)", "elasticities": True,
                    "doc": "docs/demand_elasticities.md"},
}

# The engine view's modules (web/data/engine.js keys) and what stands behind each in each set.
# "port:<key>" uses PORTS, "own:<key>" OWN, "stand:<key>" STANDINS.
ENGINE = {
    "residential": {"fast": "stand:demand_stub", "real": "port:residential", "datacenter": "port:residential"},
    "commercial": {"fast": "stand:demand_stub", "real": "port:commercial", "datacenter": "port:commercial"},
    "industrial": {"fast": "stand:demand_stub", "real": "stand:demand_stub", "datacenter": "stand:demand_stub"},
    "transportation": {"fast": "stand:demand_stub", "real": "stand:demand_stub", "datacenter": "port:transportation"},
    "electricity": {"fast": "stand:electricity", "real": "own:dispatch", "datacenter": "own:dispatch"},
    "natural_gas": {"fast": "stand:natural_gas", "real": "stand:natural_gas", "datacenter": "stand:natural_gas"},
    "oil": {"fast": "stand:oil", "real": "stand:oil", "datacenter": "stand:oil"},
    "coal": {"fast": "stand:coal", "real": "stand:coal", "datacenter": "stand:coal"},
    "emissions": {"fast": "stand:emissions", "real": "stand:emissions", "datacenter": "stand:emissions"},
}

# Numbers on the demo page: how to read them from a run, and the modules that produce them.
DEMAND = ["residential", "commercial", "industrial", "transportation"]
SUPPLY = ["electricity", "natural_gas", "oil", "coal", "emissions"]
OUTPUTS = {
    "co2": ("US energy CO2", lambda d: d["co2"], DEMAND + SUPPLY),
    "pel": ("Power price", lambda d: d["prices"]["electricity"], ["electricity:price"] + DEMAND),
    "mg": ("Gasoline price", lambda d: d["prices"]["gasoline"], ["oil"]),
    "ng": ("Home gas price", lambda d: d["prices"]["gas_home"], ["natural_gas"]),
    "gal": ("Gasoline use", lambda d: d["gasoline_bgal"], ["transportation", "oil"]),
    "use": ("Energy use", lambda d: [sum(v[i] for v in d["energy"].values()) for i in range(len(d["co2"]))], DEMAND),
    "whl": ("Wholesale power", None, ["electricity"]),
    "bill": ("Household energy bill", None, ["residential", "electricity:price", "natural_gas"]),
    "unserved": ("Load the fleet cannot meet", None, ["electricity"]),
}
REAL_ONLY = {"whl", "unserved"}     # numbers only the dispatch LP has
NO_COUNTERPART = {
    "whl": "No EIA counterpart: EIA reports its own price model's output, not this LP's marginal cost.",
    "unserved": "No EIA counterpart: EIA's model builds what it needs; this LP runs EIA's reference fleet and builds nothing.",
    "bill": "Home fuel use times home prices, over households; not a number EIA reports. As good as the weakest of those.",
}
for sector in DEMAND:
    OUTPUTS[f"energy.{sector}"] = (f"{sector.title()} energy use", lambda d, k=sector: d["energy"][k], [sector])
SECTOR_CO2 = {"rs": "residential", "cm": "commercial", "in": "industrial", "tr": "transportation", "el": "electricity"}
for k, mod in SECTOR_CO2.items():
    OUTPUTS[f"co2.{k}"] = (f"{mod.title()} CO2", lambda d, k=k: d["trace"]["co2_sector"][k],
                           [mod] + (DEMAND + ["natural_gas", "coal"] if k == "el" else ["natural_gas", "oil", "coal"]))

# rel=1e-6, tol = 1e-4, < 2e-2, and parametrized ("name", 2e-3) pairs
TOL_RE = re.compile(r"(?:\b(?:rel|abs|atol|rtol|tol|TOL|tolerance)\w*\s*=\s*|[<>]=?\s*|\",\s*)(\d+(?:\.\d+)?e-\d+|0\.\d+)")


def collected_tests() -> list[str]:
    out = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q"], cwd=ROOT,
                         capture_output=True, text=True).stdout
    return [line.strip().replace("\\", "/").removeprefix("tests/") for line in out.splitlines() if "::" in line]


EIA_LINE = re.compile(r"\beia\b|snap", re.I)


def tolerances(files: list[Path]) -> tuple[list[float], list[float]]:
    """Relative tolerances asserted in these files (numbers under 0.1 after rel=, tol=, <, ...):
    (against the oracle, against EIA's published run). A line that compares with `eia` or the
    restart file (Snapshot) is a published-run check; an oracle test file is one throughout."""
    oracle, published = [], []
    for p in files:
        whole = "oracle" in p.name and "test_" in p.name and "Snapshot" in p.read_text(encoding="utf-8", errors="replace")
        for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
            for m in TOL_RE.finditer(line):
                x = float(m.group(1))
                if 0 < x < 0.1:
                    (published if whole or EIA_LINE.search(line) else oracle).append(x)
    return oracle, published


def port_grade(key: str, scope: str, tests: list[str]) -> dict:
    m = PORTS[key]
    heading, state_col, match_col = m["table"]
    rows = markdown_table(scope, heading)
    counted = [r for r in rows if not NOT_COUNTED.match(r.get(state_col, ""))]
    done = [r for r in counted if r.get(state_col) and not NOT_DONE.match(r[state_col])]
    files = sorted({t.split("::")[0] for t in tests if any(t.startswith(p) for p in m["tests"])})
    mine = [t for t in tests if t.split("::")[0] in files]
    # Two kinds of check: the port against EIA's Fortran (the oracle), and the oracle itself
    # against EIA's published run (an oracle test that reads the restart file).
    tols, pub = tolerances([TESTS / f for f in files] + [TESTS / h for h in m["harness"] if (TESTS / h).exists()])
    published = [f for f in files if tolerances([TESTS / f])[1]]
    loosest = max(tols) if tols else None
    common = max(set(tols), key=tols.count) if tols else None
    first = lambda r: next(iter(r.values()))  # noqa: E731
    return {
        "name": m["name"], "grade": "match", "label": "matches EIA",
        "summary": (f"Ported from EIA's code: {len(done)} of {len(counted)} routines in SCOPE.md done. Tests compare "
                    f"its arrays with EIA's Fortran, run as the oracle"
                    + (f", to {common:g} relative typically and {loosest:g} at worst" if tols else "")
                    + (f"; against EIA's published run, within {max(pub):g} per cell" if pub else "") + "."),
        "evidence": {
            "routines_done": len(done), "routines": len(counted),
            "not_done": [first(r) for r in counted if r not in done],
            "match_notes": sorted({r.get(match_col, "") for r in done if r.get(match_col)})[:12],
            "tolerance_loosest": loosest, "tolerance_most_common": common,
            "published_run_tolerance": max(pub) if pub else None, "published_run_tests": published,
            "tests": len(mine), "test_files": files, "scope_section": heading.lstrip("# "),
        },
    }


def own_grade(key: str, tests: list[str], gap: float) -> dict:
    m = OWN[key]
    files = sorted({t.split("::")[0] for t in tests if any(t.startswith(p) for p in m["tests"])})
    pct = round(100 * gap, 1)
    return {
        "name": m["name"], "grade": "within", "label": f"within {pct:g}%", "pct": pct,
        "summary": (f"Our own model of this piece, not a port. In the demo's reference run its "
                    f"{'power-sector CO2' if m['measure'][1] == 'el' else m['measure']} is within {pct:g}% of EIA's "
                    f"AEO2026 reference, {FIRST}-{LAST}."),
        "evidence": {"measured_against": "cb2026", "worst_gap_pct": pct,
                     "tests": sum(1 for t in tests if t.split("::")[0] in files), "test_files": files, "doc": m["doc"]},
    }


def stand_grade(key: str, coef: dict, elast: dict) -> dict:
    m = STANDINS[key]
    ev = {"doc": m["doc"]}
    if m.get("prices"):
        fits = {p: coef["prices"][p] for p in m["prices"] if p in coef["prices"]}
        ev["fitted_from"] = sorted({c for f in fits.values() for c in f["fit_cases"]})
        ev["fits"] = [{"price": p, "rmse_pct": f["rmse_pct"],
                       "held_out_rmse_pct_worst": max(f["held_out_rmse_pct"].values())} for p, f in fits.items()]
        worst = max(f["held_out_rmse_pct_worst"] for f in ev["fits"])
        summary = (f"Price curves fitted to EIA's AEO2026 side runs ({', '.join(ev['fitted_from'])}); "
                   f"on runs left out of the fit, error up to {worst:.1f}%.")
    elif m.get("elasticities"):
        n = [(s, f, v) for s, fit in elast.items() for f, v in fit["fuels"].items()]
        fitted = [x for x in n if x[2].get("why") == "fitted"]
        ev["fuels"] = len(n)
        ev["fitted"] = len(fitted)
        summary = (f"EIA's reference demand moved by a price elasticity fitted to EIA's side runs "
                   f"({len(fitted)} of {len(n)} sector-fuel pairs fitted, the rest a placeholder).")
    else:
        summary = "CO2 from fuel use with EIA's emission factors; no policy model ported yet."
    return {"name": m["name"], "grade": "stand", "label": "stand-in", "summary": summary, "evidence": ev}


def series(run: dict, get) -> list[float]:
    return [float(x) for x in get(run)]


def worst_gap(run: dict, ref: dict, get, years: list[int]) -> float:
    a, b = series(run, get), series(ref, get)
    return max(abs(a[i] / b[i] - 1) for i, y in enumerate(years) if FIRST <= y <= LAST and b[i])


RANK = {"match": 0, "within": 1, "stand": 2}


def main() -> None:
    scope = (ROOT / "SCOPE.md").read_text(encoding="utf-8")
    tests = collected_tests()
    coef = json.loads((SRC / "supply_standin" / "coefficients.json").read_text())
    elast = json.loads((SRC / "demand_elasticities.json").read_text())
    meta = json.loads((WEB / "meta.json").read_text())
    real_meta = json.loads((WEB / "real_meta.json").read_text())
    years, ref = meta["years"], meta["reference"]
    runs = {"fast": json.loads((WEB / "scenarios" / "c0_evref_b100.json").read_text())}
    if real_meta.get("complete"):
        runs["real"] = json.loads((WEB / "real" / "c0_evref_b100.json").read_text())
    dc_reference = WEB / "datacenter" / "reference.json"
    if dc_reference.exists():
        runs["datacenter"] = json.loads(dc_reference.read_text())

    parts = {f"port:{k}": port_grade(k, scope, tests) for k in PORTS}
    parts.update({f"stand:{k}": stand_grade(k, coef, elast) for k in STANDINS})
    if "real" in runs:
        # the worst of every run the LP is in
        gap = max(worst_gap(runs[s], ref, lambda d: d["trace"]["co2_sector"]["el"], years) for s in runs if s != "fast")
        parts["own:dispatch"] = own_grade("dispatch", tests, gap)

    sets = {}
    for name, run in runs.items():
        mods = {}
        for key, by_set in ENGINE.items():
            part = by_set[name]
            if part not in parts:          # the dispatch LP only runs in the real sets
                part = by_set["fast"]
            mods[key] = {"part": part, **{k: parts[part][k] for k in ("grade", "label")}}
        # retail power prices come from the stand-in in both sets
        mods["electricity:price"] = {"part": "stand:electricity", "grade": "stand", "label": "stand-in"}
        outs = {}
        for key, (label, get, producers) in OUTPUTS.items():
            if key in REAL_ONLY and name == "fast":
                continue
            behind = [mods[p] for p in producers if p in mods]
            worst = max(behind, key=lambda m: RANK[m["grade"]])
            out = {"label": label, "modules": {p: mods[p]["part"] for p in producers if p in mods}}
            if get is None:
                out.update(grade=worst["grade"], label_grade=worst["label"],
                           summary=NO_COUNTERPART[key] + f" Weakest piece behind it: {parts[worst['part']]['name']} ({worst['label']}).")
            else:
                pct = round(100 * worst_gap(run, ref, get, years), 2)
                out["gap_pct"] = pct
                if worst["grade"] == "match" and pct <= 100 * SAME:
                    out.update(grade="match", label_grade="matches EIA")
                elif worst["grade"] == "stand":
                    out.update(grade="stand", label_grade="stand-in")
                else:
                    out.update(grade="within", label_grade=f"within {max(pct, 0.1):.1f}%")
                weakest = parts[worst["part"]]["name"]
                out["summary"] = (f"No-policy run vs EIA's AEO2026 reference: worst gap {pct:.2f}%, {FIRST}-{LAST}. "
                                  + ("Every module behind it is a port that matches EIA."
                                     if out["grade"] == "match" else f"Weakest piece behind it: {weakest} ({worst['label']})."))
            outs[key] = out
        outs["cum"] = {**outs["co2"], "label": "CO2 avoided, 2027-2050"}
        sets[name] = {"modules": mods, "outputs": outs}

    data = {
        "generated": str(date.today()),
        "reference": "EIA AEO2026 Counterfactual Baseline (cb2026)",
        "grades": {
            "match": "Ported from EIA's code and checked against EIA's own Fortran, run as an oracle.",
            "within": "Our own model of the piece (not a port), measured against EIA's AEO2026 reference.",
            "stand": "A curve or elasticity fitted to EIA's AEO2026 runs.",
        },
        "parts": parts, "sets": sets, "tests_collected": len(tests),
    }
    WEB.mkdir(parents=True, exist_ok=True)
    (WEB / "fidelity.json").write_text(json.dumps(data, indent=1))
    (WEB / "fidelity.js").write_text("window.NEMS_FIDELITY = " + json.dumps(data, separators=(",", ":")) + ";\n")
    for k, p in parts.items():
        print(f"{k:22} {p['label']:16} {p['summary'][:110]}")
    for name, st in sets.items():
        print(name, {k: f"{o['label_grade']} ({o.get('gap_pct', '-')})" for k, o in st["outputs"].items() if "." not in k})


if __name__ == "__main__":
    main()
