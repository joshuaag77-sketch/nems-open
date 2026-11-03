"""Export NEMS's structure for the 3D engine: modules, who writes what the others read, the
routines inside, and the switches that go in.

    python scripts/engine_structure.py

Everything is read from EIA's release (nems-upstream) and this repo; nothing is drawn by hand:
- Shared variables: EIA's variable dictionary (input/dict.txt), the COMMON blocks NEMS passes
  between modules (4,405 variables).
- Fortran modules: every routine, its size, the routines it CALLs, the INCLUDEs it uses, and
  which dictionary variables it assigns (a write) or uses otherwise (a read). Assignment
  statements only: a variable passed to a CALL counts as a read.
- AIMMS modules (coal, natural gas, hydrogen): their transfer lists (models/*/input/*putvars.txt
  is what NEMS sends them, *getvars.txt what they send back); hydrogen has no get list, so its
  writes are the dictionary variables its AIMMS model assigns (`:=`).
- Python module (oil and gas supply, HSM): `restart.<block>_<var>` assigned (a write) or used.
- Switches: the scedes file (scedes/scedes.cb2026.csv), each row's ModuleOwner, and the routines
  that read it by name (RTOVALUE).
- Ported: the routines named in done rows of this repo's SCOPE.md tables (and the industrial
  slot's list), plus every routine they call in the same module.

Module edges: A -> B when A writes a dictionary variable that B reads, thickness = how many
COMMON blocks carry such variables. If more than MAX_PAIRS of the 78 module pairs connect, only
each module's TOP_PER_MODULE thickest edges are kept (the rest are still in the file, flagged).

Writes web/data/engine3d/structure.json (modules, edges, switches, outputs) and
web/data/engine3d/routines.json (every routine with its calls, reads and writes).
"""

import csv
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "oracle"))
sys.path.insert(0, str(ROOT / "scripts"))
from build_engine_catalog import markdown_table  # noqa: E402
from gen_oracle import walk_includes, common_members  # noqa: E402
from nems_open import dictionary  # noqa: E402
from nems_open.paths import UPSTREAM  # noqa: E402

SRC, INC, MODELS = UPSTREAM / "source", UPSTREAM / "includes", UPSTREAM / "models"
OUT = ROOT / "web" / "data" / "engine3d"
MAX_PAIRS, TOP_PER_MODULE = 60, 3

# The 13 modules: EIA's source for each, and its execution switch in the scedes file.
MODULES = {
    "residential": {"name": "Residential", "code": "EXR", "fortran": ["resd.f"]},
    "commercial": {"name": "Commercial", "code": "EXK", "fortran": ["comm.f"]},
    "transportation": {"name": "Transportation", "code": "EXT", "fortran": ["tran.f", "tranair.f", "tranfrt.f"]},
    "industrial": {"name": "Industrial", "code": "EXI", "fortran": ["ind.f"]},
    "electricity": {"name": "Electricity", "code": "EXE",
                    "fortran": ["util.f", "uecp.f", "uefd.f", "udat.f", "uefp.f", "uldsm.f", "ucape.f", "udaf.f",
                                "uaimms.f", "uread.f", "unugs.f", "prepplt.f", "prepett.f", "ephrts.f90", "uesql.f90"],
                    "other": ["models/ecp", "models/efd"]},
    "coal": {"name": "Coal", "code": "EXC", "aimms": "coal", "other": ["models/coal"]},
    "natural_gas": {"name": "Natural gas", "code": "EXG", "aimms": "ngas", "other": ["models/ngas", "models/ngpl"]},
    "oil_gas_supply": {"name": "Oil and gas supply", "code": "EXL", "python": "hsm", "other": ["models/hsm"]},
    "refining": {"name": "Refining", "code": "EXO", "fortran": ["refine.f", "refine_hogs.f", "refine_logs.f"],
                 "other": ["models/lfmm"]},
    "economy": {"name": "Economy", "code": "EXM", "fortran": ["mac.f"]},
    "renewables": {"name": "Renewables", "code": "EXN", "fortran": ["renew.f"], "other": ["models/rest"]},
    "hydrogen": {"name": "Hydrogen", "code": "EXH", "aimms": "hmm", "other": ["models/hmm"]},
    "international": {"name": "International", "code": "EXW", "fortran": ["world.f"]},
}
HUB = {"name": "Integrating module", "fortran": ["nemsfunct.f", "util_avepas_avepasa.f90", "util_copyadjusted.f90",
                                                  "util_sumqas.f90", "util_ngpl_stat_price.f90", "util_refine.f90"],
       "other": ["models/main", "models/converge", "source/nems_flow.py"]}

# Ported routines: the done rows of SCOPE.md's tables, by module (heading, state column).
PORT_TABLES = {
    "residential": ("### Routine map", "State"), "commercial": ("## Pilot progress", "State"),
    "transportation": ("### Port progress", "State"), "electricity": ("## LDSM port", "Python"),
}
PORT_TABLES_EXTRA = {"electricity": [("## EFP port", "Python")]}
NOT_DONE = re.compile(r"^(to do|not yet|not ported|skip)", re.I)
CODE_EXT = {".f", ".f90", ".py", ".ams", ".gms", ".inc"}

ASSIGN = re.compile(r"^\s*(?:\d+\s+)?(?:if\s*\(.*\)\s*)?([a-z_]\w*)\s*(\([^=]*\))?\s*=(?!=)", re.I)
WORD = re.compile(r"[a-z_]\w*", re.I)
STRING = re.compile(r"'[^']*'|\"[^\"]*\"")


def strip_comment(line: str) -> str:
    """The line up to a '!' that is not inside a string."""
    q = None
    for i, ch in enumerate(line):
        if q:
            if ch == q:
                q = None
        elif ch in "'\"":
            q = ch
        elif ch == "!":
            return line[:i]
    return line


def norm(key: str) -> str:
    """BLOCK/name, the form used throughout this file."""
    b, n = key.split("/", 1)
    return f"{b.upper()}/{n.lower()}"


FREE_START = re.compile(r"^(subroutine|module|include|implicit|use|contains|integer|real|logical|character|end)\b", re.I | re.M)


def is_free_form(path: Path, text: str) -> bool:
    """.f90 is free form; a .f file is too when statements start in column 1 (EIA compiles
    several .f files as free form). In fixed form, column 1 holds only comments and labels."""
    return path.suffix == ".f90" or len(FREE_START.findall(text)) > 3


# EIA's files mix the two forms, so a column-1 C or * line is a statement when it reads like one.
C_STATEMENT = re.compile(r"^(call|contains|character|common|close|cycle|case|complex|continue)\b(?!\s*=)", re.I)


def is_comment(line: str) -> bool:
    if line.lstrip().startswith("!"):
        return True
    return line[0] in "cC*" and not C_STATEMENT.match(line)


def fortran_statements(text: str, free: bool):
    """(line number, statement) with comments dropped and continuations joined. Fixed form
    (comment in column 1, continuation in column 6 or a tab and a digit) and free form (&)."""
    out, buf, start = [], "", 0
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.rstrip()
        if not line.strip():
            continue
        if is_comment(line):
            continue
        cont = False
        if not free:
            if len(line) > 5 and line[:5].strip() == "" and line[5] not in " 0" and not line.startswith("\t"):
                cont, line = True, line[6:]
            elif line.startswith("\t") and len(line) > 1 and line[1] in "123456789":
                cont, line = True, line[2:]
        code = strip_comment(line)
        if cont and buf:
            buf += " " + code.strip()
            continue
        if buf.endswith("&"):
            buf = buf[:-1] + " " + code.strip().lstrip("&")
            continue
        if buf:
            out.append((start, buf))
        buf, start = code.strip(), i
    if buf:
        out.append((start, buf))
    return out


MODULE_INCLUDES = {}     # Fortran MODULE name -> the INCLUDEs in its specification part


def split_routines(path: Path):
    """[(name, kind, first line, last line, statements, scope)] for every routine in a Fortran
    file. MODULE specification parts are not routines; their INCLUDEs go to MODULE_INCLUDES.
    scope: the statements the routine sees by host association (its MODULE and, for an
    internal procedure after CONTAINS, every enclosing routine), as (module name, [statements])."""
    text = path.read_text(encoding="latin-1")
    sts = fortran_statements(text, is_free_form(path, text))
    head = re.compile(r"^(?:(?:recursive|pure|elemental|integer|real|logical|double\s+precision|character\S*)\s+)*"
                      r"(subroutine|function|program|module)\s+(\w+)", re.I)
    done, stack, module, in_spec = [], [], None, False
    for ln, st in sts:
        low = st.strip().lower()
        if re.match(r"^end\s*module\b", low):
            while stack:
                done.append(stack.pop())
            module, in_spec = None, False
            continue
        m = head.match(st)
        if m and not low.startswith("module procedure"):
            if m.group(1).lower() == "module":
                while stack:
                    done.append(stack.pop())
                module, in_spec = m.group(2).upper(), True
                MODULE_INCLUDES.setdefault(module, [])
                continue
            # a new routine: internal if the open one has passed CONTAINS, else a sibling
            while stack and not stack[-1]["contains"]:
                done.append(stack.pop())
            parents = [r["sts"] for r in stack]
            host = stack[-1]["name"] if stack else None
            stack.append({"name": m.group(2).upper(), "kind": m.group(1).lower(), "first": ln, "last": ln,
                          "sts": [], "contains": False, "module": module, "parents": parents, "host": host})
            continue
        if not stack:
            if module and in_spec:
                if low == "contains":
                    in_spec = False
                MODULE_INCLUDES[module] += [n.lower() for n in re.findall(r"^include\s*'(\w+)'", st, re.I)]
            continue
        top = stack[-1]
        if low == "contains":
            top["contains"] = True
            continue
        if re.match(r"^end(\s*(subroutine|function|program)(\s+\w+)?)?$", low, re.I):
            if not top["contains"]:     # a host's span stops at CONTAINS: its internal routines count for themselves
                top["last"] = ln
            done.append(stack.pop())
            continue
        if not top["contains"]:
            top["sts"].append(st)
            top["last"] = ln
    done += stack
    out = []
    for r in done:
        inherited = [s for p in r["parents"] for s in p]
        out.append((r["name"], r["kind"], r["first"], r["last"], r["sts"], (r["module"], inherited), r["host"]))
    return sorted(out, key=lambda r: r[2])


def routine_includes(sts, scope) -> tuple:
    """A routine's INCLUDEs: its own, those of the routines that contain it, its module's, and
    those of every module it or they USE."""
    module, inherited = scope
    allst = list(sts) + list(inherited)
    own = [n.lower() for st in allst for n in re.findall(r"^include\s*'(\w+)'", st, re.I)]
    used = [u.upper() for st in allst for u in re.findall(r"^use\s+(\w+)", st, re.I)]
    mods = ([module] if module else []) + used
    inherited_incs = [n for mname in mods for n in MODULE_INCLUDES.get(mname, [])]
    return tuple(dict.fromkeys(own + inherited_incs))


def global_names():
    """{lowercase name: [BLOCK/name, ...]} for every dictionary variable."""
    names = defaultdict(list)
    for v in dictionary.variables().values():
        names[v.name.lower()].append(v.key)
    return names


_members = {}


def members_of(includes: tuple) -> dict:
    """{var: BLOCK/var} for the dictionary variables these includes declare in COMMON."""
    if includes not in _members:
        seen = walk_includes(list(includes), INC)
        dict_keys = {norm(k) for k in dictionary.variables()}
        _members[includes] = {v: norm(f"{b}/{v}") for b, v in common_members(INC, seen) if norm(f"{b}/{v}") in dict_keys}
    return _members[includes]


def scan_fortran(module: str, files: list[str]) -> list[dict]:
    out = []
    split = [(f, split_routines(SRC / f)) for f in files]   # all files first: modules may be USEd across files
    for f, rs in split:
        for name, kind, first, last, sts, scope, host in rs:
            incs = routine_includes(sts, scope)
            mem = members_of(incs) if incs else {}
            reads, writes, calls, switches = set(), set(), [], set()
            for raw in sts:
                st = STRING.sub("''", raw)
                low = st.lower()
                for c in re.findall(r"\bcall\s+(\w+)", low):
                    calls.append(c.upper())
                for s in re.findall(r"rtovalue\s*\(\s*'(\w+)", raw, re.I):
                    switches.add(s.upper())
                if not mem:
                    continue
                m = ASSIGN.match(low)
                lhs = None
                if m and m.group(1) not in ("if", "do", "call", "select", "case", "where", "forall", "data"):
                    lhs = m.group(1)
                    if lhs in mem:
                        writes.add(mem[lhs])
                body = low[m.end(1) + len(m.group(2) or ""):] if lhs else low
                for w in set(WORD.findall(body)):
                    if w in mem:
                        reads.add(mem[w])
            out.append({"name": name, "kind": kind, "module": module, "file": f, "lines": last - first + 1, "host": host,
                        "calls": sorted(set(calls)), "reads": sorted(reads), "writes": sorted(writes),
                        "switches": sorted(switches)})
    return out


def transfer_list(path: Path) -> set[str]:
    keys = set()
    for m in re.finditer(r"LABEL\s*=\s*(\w+)\s*,\s*VAR\s*=\s*(\w+)", path.read_text(encoding="latin-1"), re.I):
        keys.add(f"{m.group(1).upper()}/{m.group(2).lower()}")
    return keys


def scan_aimms(model: str) -> tuple[set, set]:
    base = MODELS / model / "input"
    prefix = {"coal": "coal", "ngas": "ng", "hmm": "h2"}[model]
    reads = transfer_list(base / f"{prefix}putvars.txt")
    get = base / f"{prefix}getvars.txt"
    if get.exists():
        writes = transfer_list(get)
    else:  # hydrogen: the BLOCK_VAR identifiers its AIMMS model assigns
        keys = {norm(v.key).upper(): norm(v.key) for v in dictionary.variables().values()}
        writes = set()
        for ams in (MODELS / model).rglob("*.ams"):
            for m in re.finditer(r"\b([A-Z0-9]+)_([A-Z0-9_]+)\s*(?:\([^)]*\))?\s*:=", ams.read_text(encoding="latin-1"), re.I):
                k = f"{m.group(1)}/{m.group(2)}".upper()
                if k in keys:
                    writes.add(keys[k])
    return reads, writes


def scan_python(model: str) -> tuple[set, set]:
    keys = {}
    for v in dictionary.variables().values():
        keys[f"{v.block}_{v.name}".lower()] = norm(v.key)
    reads, writes = set(), set()
    pat = re.compile(r"restart\.([a-z0-9]+_[a-z0-9_]+)")
    for py in (MODELS / model).rglob("*.py"):
        for line in py.read_text(encoding="latin-1").splitlines():
            code = line.split("#", 1)[0]
            for m in pat.finditer(code):
                k = keys.get(m.group(1))
                if not k:
                    continue
                after = code[m.end():]
                # restart.x = ..., restart.x[...] = ..., restart.x.loc[...] = ...
                if re.match(r"\s*(\.(loc|iloc|at|iat))?\s*(\[[^\]]*\])*\s*(\[[^\]]*\]\s*)*=(?!=)", after):
                    writes.add(k)
                else:
                    reads.add(k)
    return reads, writes


def count_lines(paths) -> int:
    n = 0
    for p in paths:
        if p.is_dir():
            n += sum(count_lines([q]) for q in p.rglob("*") if q.is_file() and q.suffix.lower() in CODE_EXT)
        elif p.is_file() and p.suffix.lower() in CODE_EXT:
            n += sum(1 for line in p.read_text(encoding="latin-1", errors="replace").splitlines() if line.strip())
    return n


def ported_routines(scope: str, routines: list[dict]) -> dict[str, set]:
    """{module: routine names} named in done rows of SCOPE.md, closed over their calls."""
    by_module = defaultdict(dict)
    for r in routines:
        by_module[r["module"]][r["name"]] = r
    out = {}
    for mod, (heading, col) in PORT_TABLES.items():
        names = set()
        for h, c in [(heading, col)] + PORT_TABLES_EXTRA.get(mod, []):
            for row in markdown_table(scope, h):
                state = row.get(c, "")
                if not state or NOT_DONE.match(state):
                    continue
                first = next(iter(row.values()))
                names |= {w.upper() for w in re.findall(r"[A-Za-z_]\w+", first)}
        mine = by_module[mod]
        todo = [n for n in names if n in mine]
        done = set()
        while todo:
            n = todo.pop()
            if n in done:
                continue
            done.add(n)
            todo += [c for c in mine[n]["calls"] if c in mine and c not in done]
        # a host routine (RESD, TRAN) is ported when most of what it contains is
        kids = defaultdict(list)
        for r in mine.values():
            if r["host"]:
                kids[r["host"]].append(r["name"])
        done |= {h for h, ks in kids.items() if sum(k in done for k in ks) >= 0.8 * len(ks)}
        out[mod] = done
    from nems_open.run_demand import IndustrialSector
    out["industrial"] = {n for n in IndustrialSector.ported if n in by_module["industrial"]}
    return out


def main() -> None:
    scope = (ROOT / "SCOPE.md").read_text(encoding="utf-8")
    variables = dictionary.variables()
    routines = []
    io = {}
    for key, m in MODULES.items():
        if "fortran" in m:
            rs = scan_fortran(key, m["fortran"])
            routines += rs
            io[key] = ({v for r in rs for v in r["reads"]}, {v for r in rs for v in r["writes"]})
        if "aimms" in m:
            io[key] = scan_aimms(m["aimms"])
        if "python" in m:
            io[key] = scan_python(m["python"])
    hub_routines = scan_fortran("hub", HUB["fortran"])
    routines += hub_routines
    io["hub"] = ({v for r in hub_routines for v in r["reads"]}, {v for r in hub_routines for v in r["writes"]})

    ported = ported_routines(scope, routines)
    # Edges: A writes a variable B reads; thickness counted in COMMON blocks.
    edges = []
    for a, (_, wa) in io.items():
        for b, (rb, _) in io.items():
            if a == b:
                continue
            shared = wa & rb
            if shared:
                blocks = sorted({k.split("/")[0] for k in shared})
                edges.append({"from": a, "to": b, "blocks": blocks, "weight": len(blocks), "variables": len(shared)})
    # The integrating module's edges are the spokes: always shown, not counted as module pairs.
    for e in edges:
        e["hub"] = "hub" in (e["from"], e["to"])
    pairs = {frozenset((e["from"], e["to"])) for e in edges if not e["hub"]}
    filtered = len(pairs) > MAX_PAIRS
    keep = set()
    if filtered:
        for k in MODULES:
            mine = sorted((e for e in edges if not e["hub"] and k in (e["from"], e["to"])),
                          key=lambda e: (-e["weight"], -e["variables"]))
            keep |= {(e["from"], e["to"]) for e in mine[:TOP_PER_MODULE]}
    for e in edges:
        e["shown"] = e["hub"] or (not filtered) or (e["from"], e["to"]) in keep

    # Switches
    rows = list(csv.reader(open(UPSTREAM / "scedes" / "scedes.cb2026.csv", encoding="latin-1")))
    owner = {m["code"]: k for k, m in MODULES.items()}
    readers = defaultdict(list)
    for r in routines:
        for s in r["switches"]:
            readers[s].append(f"{r['module']}:{r['name']}")
    switches = []
    for r in rows[1:]:
        if not r or not r[0] or r[0].startswith("#") or len(r) < 4:
            continue
        switches.append({"key": r[0], "value": r[1][:80], "module": owner.get(r[2].strip(), "hub" if not r[2].strip() else "other"),
                         "owner_code": r[2].strip(), "description": r[3][:120], "file": r[5].strip() == "1" if len(r) > 5 else False,
                         "routines": readers.get(r[0].upper(), [])})

    # Outputs: every dictionary variable, with the modules that write and read it.
    writers, users = defaultdict(list), defaultdict(list)
    for k, (rs, ws) in io.items():
        if k == "hub":
            continue
        for v in ws:
            writers[v].append(k)
        for v in rs:
            users[v].append(k)
    outputs = [{"key": norm(v.key), "block": v.block.upper(), "writers": sorted(writers.get(norm(v.key), [])),
                "readers": sorted(users.get(norm(v.key), [])), "units": v.units, "description": v.description[:80]}
               for v in variables.values()]

    modules = []
    by_mod = defaultdict(list)
    for r in routines:
        by_mod[r["module"]].append(r)
    for key, m in MODULES.items():
        rs = by_mod.get(key, [])
        fortran = [SRC / f for f in m.get("fortran", [])]
        other = [UPSTREAM / o for o in m.get("other", [])]
        done = ported.get(key, set())
        modules.append({
            "key": key, "name": m["name"], "code": m["code"],
            "language": "Fortran" if "fortran" in m else ("AIMMS" if "aimms" in m else "Python"),
            "fortran_files": m.get("fortran", []), "other_sources": m.get("other", []),
            "fortran_lines": sum(len(p.read_text(encoding="latin-1").splitlines()) for p in fortran),
            "other_lines": count_lines(other),
            "routines": len(rs), "ported_routines": len(done),
            "ported_lines": sum(r["lines"] for r in rs if r["name"] in done),
            "reads": len(io[key][0]), "writes": len(io[key][1]),
            "switches": sum(1 for s in switches if s["module"] == key),
        })
    for r in routines:
        r["ported"] = r["name"] in ported.get(r["module"], set())

    structure = {
        "generated": str(date.today()),
        "source": "EIA NEMS AEO2026 release (nems-upstream): input/dict.txt, source/*.f, models/*/input/*vars.txt, scedes/scedes.cb2026.csv",
        "method": __doc__.split("\n\n", 2)[2].strip(),
        "modules": modules,
        "hub": {"name": HUB["name"], "fortran_files": HUB["fortran"], "routines": len(hub_routines),
                "reads": len(io["hub"][0]), "writes": len(io["hub"][1]),
                "fortran_lines": count_lines([SRC / f for f in HUB["fortran"]])},
        "edges": edges, "pairs_connected": len(pairs), "pairs_total": len(MODULES) * (len(MODULES) - 1) // 2,
        "edge_rule": (f"{len(pairs)} of {len(MODULES) * (len(MODULES) - 1) // 2} module pairs connect; "
                      + (f"showing each module's {TOP_PER_MODULE} thickest edges" if filtered else "all shown")),
        "switches": switches, "outputs": outputs,
        "counts": {"switches": len(switches), "outputs": len(outputs), "routines": len(routines),
                   "variables_written": sum(1 for o in outputs if o["writers"])},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "structure.json").write_text(json.dumps(structure, separators=(",", ":")))
    (OUT / "routines.json").write_text(json.dumps({"routines": routines}, separators=(",", ":")))
    for mm in modules:
        print(f"{mm['key']:15} {mm['language']:7} fortran {mm['fortran_lines']:>6} other {mm['other_lines']:>7} "
              f"routines {mm['routines']:>4} ported {mm['ported_routines']:>4} ({mm['ported_lines']:>6} lines) "
              f"reads {mm['reads']:>4} writes {mm['writes']:>4} switches {mm['switches']:>3}")
    print(structure["edge_rule"])
    print("counts", structure["counts"])
    top = sorted(edges, key=lambda e: -e["weight"])[:12]
    for e in top:
        print(f"  {e['from']:>15} -> {e['to']:<15} {e['weight']:>3} blocks {e['variables']:>4} vars {'shown' if e['shown'] else ''}")


if __name__ == "__main__":
    main()
