"""Instrument the oracle's copy of comm.f so it can dump EIA's internal state.

For a routine being ported, the oracle dumps every commercial COMMON array just
before and just after the call ("<tag>_in", "<tag>_out"), plus the routine's
private SAVE arrays at its end. Each dump goes to
run/out/state/<tag>/<year>/<name>.bin with a line in index.txt giving the type,
rank and Fortran bounds, so Python can rebuild arrays with Fortran indexing.
Dumps only happen on the final iteration of the years in DUMP_YEARS.

Output only: nothing here changes a computed value.

Usage: python -I hooks.py <upstream> <source.f90 to instrument in place> [module]
module is comm (default) or resd.
"""

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
RUN = HERE / "run"

# 2019, 2020, 2021, 2025, 2026, 2027, 2030, 2040, 2050
DUMP_YEARS = [30, 31, 32, 36, 37, 38, 41, 51, 61]

# Routine being ported: (tag, the CALL line in COMM, label line at the routine's
# end where private arrays are dumped, private arrays to dump there, and saved
# values carried between iterations). Carried values are also dumped at the end
# of the non-final iteration ("<tag>_pre"), which is their value when the final
# iteration starts.
TARGETS = [
    ("sd", r"CALL COMServiceDemand\s*\(RCDBG\)", r"^490\s+CONTINUE", [
        "ExistImprvHt", "ExistImprvCl", "dcf", "MarketPenetrationMels", "MelsElQ",
        "ServicesIndex", "xplicitmiscshr", "DataCtrServPenetration", "OfficePCPenetration",
        "MarketPenetrationSC", "pctSCSavings", "CT_flag", "DatCtrShare", "ApplyRamp",
        "SSDnoShell", "RSDnoShell", "NSDnoShell", "TotExplicitMiscElQ",
        "XfmrsDry", "KitchenVent", "Security", "LabRefFrz", "MedImaging", "LrgVidBoard",
        "CoffeeBrewers", "ElVehicles", "FumeHoods", "Laundry", "Elevators", "Escalators",
        "ITEquip", "OfficeUPS", "Shredder", "OfficePBE", "VoiceIP", "POSsystems",
        "WarehouseRobots", "Televisions",
    ], []),
    ("tc", r"CALL COMTechnologyChoice\s*\(RCDBG\)", r"^\s*9100\s+CONTINUE", [
        "SDbyFuel", "SSDnoShell", "RSDnoShell", "NSDnoShell", "WHSE_EFF", "WHSE_SD",
        "PurchTechShare", "EquipSD", "STRetBehav", "CostTrendSwitch",
    ], ["iforward", "ifwd", "IFMAX", "iLastSTEOyr", "elasbaseyr"]),
    ("cn", r"CALL COMConsumption\s*\(RCDBG\)", r"^\s*210 CONTINUE\s+! across Building Types", [
        "UnBenchedCon", "CMFinalUnbenchUse", "SolarPVContrib", "Trills", "TrillsOwnUse", "TrillsOwnUseAdj",
        "shbtu", "hwbtu", "fuelusage", "FloorAdj", "defaultprices", "ifueltype", "ntek",
        "STEOdat", "FlagRegSTEO", "EF1", "EF2", "EF3", "NRGBILL", "STIMULUS",
        "prsvStdSavings", "prsvShpSavings", "FoodSvcHlthLdgFloorTot", "FoodSvcHlthLdgFlrPrev",
    ], []),
]

# Shared state dumped around each target call.
STATE_INCLUDES = ["parametr", "ncntrl", "apq", "macout", "eusprc", "mxpblk", "comparm", "comvars", "commrep"]
STATE_BLOCK_FILES = ["comparm", "comvars", "commrep"]
# Arrays from other modules' blocks that the commercial routines read.
STATE_EXTRA = ["QELCM",                                   # service demand
               "PELCM", "PNGCM", "PDSCM", "XPELCM", "XPNGCM", "XPDSCM",
               "PELCMOUT", "MC_JPGDP", "MC_RMGBLUSREAL",  # technology choice
               "PRSCM", "PLGCM", "PCLCM", "PMGCM", "PKSCM"]  # consumption (minor fuels)
DECL_FILES = ["parametr", "comparm", "comvars", "commrep", "qblk", "apq", "ampblk",
              "mpblk", "mxpblk", "eusprc", "macout"]

# Residential: every routine is CONTAINed in SUBROUTINE RESD and shares MODULE R_,
# so the state dump USEs R_ instead of including blocks. Targets are dicts:
# call (regex for the CALL line in RESD), nth (which match, 0-based; RESD calls
# some routines twice, once for the base year and once after), end (regex for the
# routine's last line), before (dump before that line rather than after it),
# private, carried.
RESD_DUMP_YEARS = [31, 32, 33, 36, 37, 38, 41, 51, 61]  # 2020 2021 2022 2025 2026 2027 2030 2040 2050
RESD_TARGETS = []
RESD_STATE_BLOCK_FILES = ["resdrep", "rtek", "rscon", "rseff"]
RESD_STATE_EXTRA = ["QELRS", "QNGRS", "QDSRS", "QLGRS", "QKSRS", "QBMRS", "QGERS", "QSTRS", "QPVRS",
                    "QTRRS", "PELRS", "PNGRS", "PDSRS", "PLGRS", "PKSRS", "MC_JPGDP"]
RESD_DECL_FILES = ["parametr", "resdrep", "rtek", "rscon", "rseff", "qblk", "apq", "ampblk", "mpblk",
                   "eusprc", "macout", "ncntrl"]

MODULES = {
    "comm": dict(build="build", run="run", years=DUMP_YEARS, targets=TARGETS, includes=STATE_INCLUDES,
                 use=None, block_files=STATE_BLOCK_FILES, extra=STATE_EXTRA, decl_files=DECL_FILES,
                 module_text=False),
    "resd": dict(build="build_resd", run="run_resd", years=RESD_DUMP_YEARS, targets=RESD_TARGETS,
                 includes=[], use="R_", block_files=RESD_STATE_BLOCK_FILES, extra=RESD_STATE_EXTRA,
                 decl_files=RESD_DECL_FILES, module_text=True),
}
CFG = MODULES["comm"]

TYPE_RE = re.compile(r"^(real\*8|double precision|real\*4|real|integer\*1|integer\*2|integer\*4|integer\*8|integer"
                     r"|logical(?:\*\d+)?|character(?:\s*\*\s*(?:\(\s*[\w*]+\s*\)|\d+))?)(?![\w*])(.*)", re.I)


def statements(text):
    buf = ""
    for line in text.splitlines():
        line = line.split("!", 1)[0].rstrip()
        if not line.strip():
            continue
        if line.endswith("&"):
            buf += line[:-1] + " "
            continue
        yield (buf + line).strip()
        buf = ""


def split_top(s):
    parts, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            parts.append(cur)
            cur = ""
        else:
            cur += ch
    parts.append(cur)
    return [p.strip() for p in parts if p.strip()]


def declarations(text):
    """{name: (type, rank)} from type statements and COMMON dimension lists."""
    out = {}
    for st in statements(text):
        m = TYPE_RE.match(st)
        if m and not re.match(r"\s*function", m.group(2), re.I):
            t = m.group(1).lower().replace(" ", "")
            body = m.group(2).split("::", 1)[-1]
            for ent in split_top(body):
                em = re.match(r"(\w+)\s*(?:\*\s*\d+)?\s*(\((.*)\))?", ent)
                if em:
                    rank = len(split_top(em.group(3))) if em.group(2) else 0
                    prev = out.get(em.group(1).lower(), (t, 0))
                    out[em.group(1).lower()] = (t, max(rank, prev[1]))
        cm = re.match(r"common\s*/\s*\w+\s*/(.*)", st, re.I)
        if cm:
            for ent in split_top(cm.group(1)):
                em = re.match(r"(\w+)\s*(\((.*)\))?", ent)
                if em and em.group(2):
                    t = out.get(em.group(1).lower(), ("?", 0))[0]
                    out[em.group(1).lower()] = (t, len(split_top(em.group(3))))
    return out


def type_code(t, name):
    if t == "?":  # implicit typing
        t = "integer" if name[0].lower() in "ijklmn" else "real"
    if t.startswith("character"):
        m = re.match(r"character\*(\d+)$", t)
        return f"S{m.group(1)}" if m else None  # fixed-length text, e.g. CostTrend
    return {"real*8": "f8", "doubleprecision": "f8", "real*4": "f4", "real": "f4",
            "integer*1": "i1", "integer*2": "i2", "integer*4": "i4", "integer*8": "i8", "integer": "i4"}.get(
        t, "i4" if t.startswith("logical") else None)


def common_names(text):
    names = []
    for st in statements(text):
        cm = re.match(r"common\s*/\s*\w+\s*/(.*)", st, re.I)
        if cm:
            names += [re.match(r"\w+", e).group(0) for e in split_top(cm.group(1))]
    return names


def dump_call(tag, name, t, rank):
    code = type_code(t, name)
    if code is None:
        return None
    if code.startswith("S"):
        # Text arrays carry a hidden length argument, so they need a routine
        # that declares them as text (odump_c in stubs.f90).
        lb = f"lbound({name})" if rank else "0"
        ub = f"ubound({name})" if rank else "0"
        return (f"      call odump_c('{tag}', '{name.lower()}', CURIYR, {name}, sizeof({name}), '{code}', "
                f"{rank}, {lb}, {ub})")
    if rank == 0:
        return f"      call odump('{tag}', '{name.lower()}', CURIYR, {name}, sizeof({name}), '{code}', 0, 0, 0)"
    return (f"      call odump('{tag}', '{name.lower()}', CURIYR, {name}, sizeof({name}), '{code}', "
            f"{rank}, lbound({name}), ubound({name}))")


def module_r_(source_text):
    """The MODULE R_ block of resd.f: its declarations and its shared arrays."""
    m = re.search(r"^MODULE R_\s*$(.*?)^END MODULE R_", source_text, re.I | re.M | re.S)
    text = m.group(1)
    names = common_names(text)
    for st in statements(text):
        a = re.match(r"real\*\d\s*,\s*allocatable\s*::(.*)", st, re.I)
        if a:
            names += [re.match(r"\w+", e).group(0) for e in split_top(a.group(1))]
    return text, names


def write_state_routine(inc_dir, source_text=None):
    decls = {}
    for n in CFG["decl_files"]:
        decls.update(declarations((inc_dir / n).read_text(encoding="latin-1")))
    names = []
    for n in CFG["block_files"]:
        names += common_names((inc_dir / n).read_text(encoding="latin-1"))
    if CFG["module_text"]:
        mtext, mnames = module_r_(source_text)
        decls.update(declarations(mtext))
        names += mnames
    names += CFG["extra"]
    calls = [c for c in (dump_call("'//tag//'", n, *decls.get(n.lower(), ("?", 0))) for n in dict.fromkeys(names)) if c]
    calls = [c.replace("''//tag//''", "tag") for c in calls]
    years = ", ".join(map(str, CFG["years"]))
    inc = "\n".join(f"      include '{n}'" for n in CFG["includes"])
    if CFG["use"]:
        inc = f"      use {CFG['use']}\n      implicit none"  # USE must come first
    else:
        inc = "      implicit none\n" + inc
    body = "\n".join(calls)
    (BUILD / "oracle_state.f90").write_text(f"""! Generated by hooks.py. Do not edit.
      subroutine oracle_state(tag)
{inc}
      character(*) tag
      integer, parameter :: years({len(CFG["years"])}) = (/ {years} /)
      if (FCRL .ne. 1 .or. .not. any(years == CURIYR)) return
{body}
      end subroutine oracle_state
""")
    return len(calls)


def as_dict(target):
    if isinstance(target, dict):
        return dict(dict(nth=0, private=[], carried=[], before=False), **target)
    tag, call_re, end_re, private, carried = target
    return dict(tag=tag, call=call_re, end=end_re, private=private, carried=carried, nth=0, before=False)


def instrument(comm_path: Path, upstream: Path):
    text = comm_path.read_text(encoding="latin-1")
    src_decls = declarations(text)
    for tg in map(as_dict, CFG["targets"]):
        tag, call_re, end_re, private, carried = tg["tag"], tg["call"], tg["end"], tg["private"], tg["carried"]
        m = list(re.finditer(r"^(\s*)(" + call_re + r")", text, re.I | re.M))[tg["nth"]]
        ind = m.group(1)
        text = (text[:m.start()] + f"{ind}CALL ORACLE_STATE('{tag}_in')\n{ind}{m.group(2)}\n"
                f"{ind}CALL ORACLE_STATE('{tag}_out')" + text[m.end():])
        years = ", ".join(map(str, CFG["years"]))
        lines = [f"      IF (FCRL .EQ. 1 .AND. ANY((/ {years} /) == CURIYR)) THEN"]
        for name in private + carried:
            c = dump_call(f"{tag}_out", name, *src_decls.get(name.lower(), ("?", 0)))
            if c:
                lines.append(c)
        lines.append(f"      ELSE IF (ANY((/ {years} /) == CURIYR)) THEN")
        for name in carried:
            c = dump_call(f"{tag}_pre", name, *src_decls.get(name.lower(), ("?", 0)))
            if c:
                lines.append(c)
        lines.append("      ENDIF")
        e = re.search(end_re, text, re.I | re.M)
        if tg["before"]:
            line_start = text.rindex("\n", 0, e.start()) + 1
            text = text[:line_start] + "\n".join(lines) + "\n" + text[line_start:]
        else:
            line_end = text.index("\n", e.end())
            text = text[:line_end + 1] + "\n".join(lines) + "\n" + text[line_end + 1:]
    comm_path.write_text(text, encoding="latin-1")


def make_dirs():
    for tg in map(as_dict, CFG["targets"]):
        for side in ("in", "out", "pre"):
            for y in CFG["years"]:
                (RUN / "out" / "state" / f"{tg['tag']}_{side}" / str(y)).mkdir(parents=True, exist_ok=True)
    (RUN / "out" / "state" / "final" / str(CFG["years"][-1])).mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    upstream, src = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
    CFG = MODULES[sys.argv[3] if len(sys.argv) > 3 else "comm"]
    BUILD, RUN = HERE / CFG["build"], HERE / CFG["run"]
    n = write_state_routine(upstream / "includes", src.read_text(encoding="latin-1"))
    instrument(src, upstream)
    make_dirs()
    print(f"hooks: {n} shared arrays per state dump, {len(CFG['targets'])} routine(s) instrumented")
