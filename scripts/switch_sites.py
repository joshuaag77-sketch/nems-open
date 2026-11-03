"""Switch archaeology, step 1: the facts a script can establish about every scedes key.

For each key in EIA's scedes files: its cb2026 value, owner and description, the values in
the side cases, and every place the code reads it (RTOVALUE/RTOSTRING calls, the key quoted
in Fortran, Python or AIMMS). Read-only over nems-upstream. Writes one JSON of sites.

    python scripts/switch_sites.py OUT.json
"""

import csv
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = ROOT / "nems-upstream"
CODE = {".f", ".f90", ".for", ".inc", ".py", ".ams", ".bat", ".ps1", ".c", ".csh", ".sh", ".aimms", ".gms", ".pyf"}
SKIP = {"scedes", "output", ".git", "__pycache__", "docs"}
QUOTED = re.compile(r"""(['"])\s*([A-Za-z][A-Za-z0-9_$#-]*)\s*\1""")
RTO = re.compile(r"""(?:(\w+(?:\(\w+\))?)\s*=\s*)?\brto(value|string)\s*\(\s*['"]\s*([A-Za-z0-9_$#]+)\s*['"]\s*,?\s*([^)]*)\)""", re.I)
OWNERS = {"EXM": "Macroeconomic", "EXC": "Coal", "EXR": "Residential", "EXK": "Commercial", "EXI": "Industrial",
          "EXT": "Transportation", "EXE": "Electricity", "EXW": "International", "EXL": "Oil and gas supply",
          "EXG": "Natural gas", "EXO": "Refinery", "EXN": "Renewables", "EXH": "Hydrogen", "EXQ": "CCATS"}
SIDE = ["altelec", "alttrnp", "electrnp", "higheldmd", "highogs", "highztc", "hm2026", "lm2026", "lowogs", "lowztc"]
OTHER = ["cb2026_solo", "prepett", "prepplt"]


FILE_ASSIGN = re.compile(r"""\b\w*(?:nm|name|file|fi[a-z0-9]+)\s*=\s*['"]""")
NOT_A_READ = re.compile(r"""^\s*(?:#\s*)?include\b""", re.I)   # a source include that shares a file key's name
GENERATED = {"source/pyfiler1module.c", "source/pyfiler1-f2pywrappers.f", "source/pyfiler1-f2pywrappers2.f90"}


# Keys the code reads by prefix, not by name (models/main/prenems.py).
DYNAMIC = [(re.compile(r"^EX[A-Z]$"), "models/main/prenems.py", 'k.startswith("EX") and len(k)==3'),
           (re.compile(r"^ORD[A-Z]$"), "models/main/prenems.py", 'k.startswith("ORD")')]
ROUTINE = re.compile(r"^\s*(?:(?:recursive|pure|integer|real(?:\*\d)?|logical|character(?:\*\d+)?|double precision)\s+)*"
                     r"(subroutine|function|program|def|class|procedure)\s+([A-Za-z_]\w*)", re.I)


def enrich(rel, lines, site):
    """Add the enclosing routine, nearby lines, and how the assigned variable is used in the file."""
    n = site["line"] - 1
    site["routine"] = None
    for i in range(n, -1, -1):
        m = ROUTINE.match(lines[i])
        if m:
            site["routine"] = m.group(2)
            break
    site["context"] = [lines[i].strip()[:160] for i in range(max(0, n - 2), min(len(lines), n + 3))]
    var = site.get("assigns")
    if var is None:
        m = re.match(r"\s*(\w+)\s*=[^=]", lines[n])
        var = m.group(1) if m else None
    if var:
        word = re.compile(rf"{re.escape(var.split('(')[0])}", re.I)
        uses = [{"line": i + 1, "text": s.strip()[:160]} for i, s in enumerate(lines)
                if i != n and word.search(s) and not s.lstrip().startswith(("!", "#"))]
        branch = [u for u in uses if re.search(r"if|case|while", u["text"], re.I)]
        site["var"] = var.split("(")[0]
        site["uses"] = (branch + [u for u in uses if u not in branch])[:14]
        site["use_count"] = len(uses)


def read_scedes(name):
    keys, section = {}, ""
    with open(UPSTREAM / "scedes" / f"scedes.{name}.csv", encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            k = (r["Key"] or "").strip()
            if k.startswith("###"):
                if k.strip("# ").endswith(("Settings", "Benchmarks", "Regulations", "Models", "Execution", "Case", "Keys")):
                    section = k.strip("# ")
                continue
            if k:
                keys[k] = {**r, "section": section}
    return keys


def code_files():
    roots = [UPSTREAM / d for d in ("source", "includes", "models", "scripts", "utils")]
    files = [p for p in UPSTREAM.iterdir() if p.is_file() and p.suffix.lower() in CODE]
    for root in roots:
        for p in root.rglob("*"):
            if not p.is_file() or SKIP & set(p.relative_to(UPSTREAM).parts):
                continue
            if p.suffix.lower() in CODE or root.name == "includes" and not p.suffix:
                if "input" not in p.relative_to(UPSTREAM).parts:
                    files.append(p)
    return files


def kind_of(path, line, rto):
    ext = path.suffix.lower()
    low = line.lower()
    if rto:
        return "rto" + rto
    if ext in (".py",):
        return "python_scedes" if "scedes" in low else "python_quoted"
    if ext in (".ams", ".aimms"):
        return "aimms_quoted"
    if ext in (".bat", ".ps1", ".sh", ".csh"):
        return "script_quoted"
    if "file_mgr" in low or FILE_ASSIGN.search(low):
        return "fortran_file_open"
    return "fortran_quoted"


def main(out):
    base = read_scedes("cb2026")
    cases = {c: read_scedes(c) for c in SIDE + OTHER}
    all_keys = dict(base)
    for c in cases.values():
        for k, r in c.items():
            all_keys.setdefault(k, r)
    wanted = {k.lower(): k for k in all_keys}
    # A file key's code name drops the trailing N: key RSEFF01N, FNAME='RSEFF01' in resd.f.
    for k, r in all_keys.items():
        if r["UsedInFilelist"] == "1" and k.endswith("N") and k[:-1].lower() not in wanted:
            wanted[k[:-1].lower()] = k
    word = re.compile(r"\b(" + "|".join(re.escape(k) for k in sorted(wanted, key=len, reverse=True)) + r")\b", re.I)
    sites, mentions = defaultdict(list), defaultdict(list)
    files = code_files()
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = str(p.relative_to(UPSTREAM)).replace("\\", "/")
        if rel in GENERATED:
            continue
        lines = text.splitlines()
        for n, line in enumerate(lines, 1):
            if len(line) > 2000 or NOT_A_READ.match(line):
                continue
            seen = set()
            for m in RTO.finditer(line):
                k = wanted.get(m.group(3).lower())
                if k:
                    seen.add(k)
                    sites[k].append({"file": rel, "line": n, "kind": "rto" + m.group(2).lower(), "assigns": m.group(1),
                                     "default": m.group(4).strip() or None, "text": line.strip()[:200]})
                    enrich(rel, lines, sites[k][-1])
            for m in QUOTED.finditer(line):
                k = wanted.get(m.group(2).lower())
                if k and k not in seen:
                    seen.add(k)
                    sites[k].append({"file": rel, "line": n, "kind": kind_of(p, line, None), "text": line.strip()[:200]})
                    enrich(rel, lines, sites[k][-1])
            for m in word.finditer(line):
                k = wanted[m.group(1).lower()]
                if k not in seen:
                    seen.add(k)
                    mentions[k].append({"file": rel, "line": n, "text": line.strip()[:200]})
    prenems = (UPSTREAM / "models/main/prenems.py").read_text(encoding="utf-8", errors="replace").splitlines()
    for k in all_keys:
        for pat, rel, needle in DYNAMIC:
            if pat.match(k):
                n = next(i for i, s in enumerate(prenems, 1) if needle in s)
                sites[k].append({"file": rel, "line": n, "kind": "python_scedes_prefix", "text": prenems[n - 1].strip()[:200]})
                enrich(rel, prenems, sites[k][-1])
    res = []
    for k, r in all_keys.items():
        values = {c: cases[c][k]["Value"] if k in cases[c] else None for c in cases}
        b = base[k]["Value"] if k in base else None
        res.append({"key": k, "in_cb2026": k in base, "value": b, "owner": (r["ModuleOwner"] or "").strip(),
                    "owner_name": OWNERS.get((r["ModuleOwner"] or "").strip()), "section": r["section"],
                    "description": (r["Description"] or "").strip(), "moreopt": r["UsedInMoreOpt"] == "1",
                    "filelist": r["UsedInFilelist"] == "1", "filelist_format": (r["Filelist_format"] or "").strip(),
                    "side_cases": {c: values[c] for c in SIDE if values[c] != b},
                    "other_scedes": {c: values[c] for c in OTHER if values[c] != b},
                    "sites": sites.get(k, []), "mentions": mentions.get(k, [])[:40], "mention_count": len(mentions.get(k, []))})
    Path(out).write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(len(files), "code files;", len(res), "keys,", sum(x["in_cb2026"] for x in res), "in cb2026")


if __name__ == "__main__":
    main(sys.argv[1])
