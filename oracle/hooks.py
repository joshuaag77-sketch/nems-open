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
RESD_TARGETS = [
    dict(tag="pr", call=r"IF \(CurCalYr\.GE\.RECSYear\) CALL RDPR\b"),
    dict(tag="nh", call=r"CALL NEWHSE\b"),
    dict(tag="sq", call=r"CALL SQFTCALC\b"),
    # RECS base year only (2020)
    dict(tag="ex", call=r"CALL EXCONS\b"),
    dict(tag="bb", call=r"CALL RSBENCH\b", nth=0),
    dict(tag="nb", call=r"CALL NEMSCN\b", nth=0),
    dict(tag="rb", call=r"CALL RESDRP\b", nth=0),
    # Every year after
    dict(tag="hv", call=r"CALL RSHVAC\b"),
    # end uses: ht heating, cl cooling, cw clothes washing, dw dishwashing, wh water
    # heating, ck cooking, dy drying, rf refrigeration, fz freezing;
    # t = technology choice, a = equipment added/replaced, c = consumption
    dict(tag="htt", call=r"CALL RHTRTEC\b", end=r"^END SUBROUTINE RHTRTEC", before=True, carried=["HEATSYS"]),
    dict(tag="hta", call=r"CALL RHTRADD\b"),
    dict(tag="dg", call=r"CALL RDISTGEN\b", nth=1, end=r"^RETURN  !SEND CONTROL BACK TO RESD", before=True,
         carried=["Income_L", "Households_L", "ElecRate_L", "PopDensity_L", "Lag1Installs", "Lag2Installs",
                  "ProjectedInstalls", "CumUnits", "CumUnits_L"]),
    dict(tag="clt", call=r"CALL RCLTEC\b"),
    dict(tag="cla", call=r"CALL RCLADD\b", end=r"^END SUBROUTINE RCLADD", before=True, carried=["EQCPN90"]),
    dict(tag="cwt", call=r"CALL RCWTEC\b"),
    dict(tag="cwa", call=r"CALL RCWADD\b"),
    dict(tag="dwt", call=r"CALL RDWTEC\b"),
    dict(tag="dwa", call=r"CALL RDWADD\b"),
    dict(tag="wht", call=r"CALL RWHTEC\b"),
    dict(tag="wha", call=r"CALL REUADD\b", nth=0),  # EU = 5
    dict(tag="ckt", call=r"CALL RSTVTEC\b"),
    dict(tag="cka", call=r"CALL REUADD\b", nth=1),  # EU = 6
    dict(tag="dyt", call=r"CALL RDRYTEC\b"),
    dict(tag="dya", call=r"CALL RDRYADD\b"),
    dict(tag="rft", call=r"CALL RREFTEC\b"),
    dict(tag="rfa", call=r"CALL RREFADD\b"),
    dict(tag="fzt", call=r"CALL RFRZTEC\b"),
    dict(tag="fza", call=r"CALL RFRZADD\b"),
    dict(tag="htc", call=r"CALL RHTRCON\b", end=r"^END SUBROUTINE RHTRCON", before=True,
         carried=["EFANUEC", "NFANUEC"]),
    dict(tag="clc", call=r"CALL RCLCON\b"),
    dict(tag="cwc", call=r"CALL RCWCON\b"),
    dict(tag="dwc", call=r"CALL RDWCON\b"),
    dict(tag="whc", call=r"CALL RWHCON\b"),
    dict(tag="ckc", call=r"CALL RSTOVCON\b"),
    dict(tag="dyc", call=r"CALL RDRYCON\b"),
    dict(tag="rfc", call=r"CALL RREFCON\b"),
    dict(tag="fzc", call=r"CALL RFRZCON\b"),
    dict(tag="lt", call=r"CALL LTCNS\b", end=r"^END SUBROUTINE LTCNS", before=True,
         carried=["LTREPFUTly", "LTrepstkly", "LTrepconsly"]),
    dict(tag="ap", call=r"CALL APCNS\b"),
    dict(tag="sh", call=r"CALL SHTCNS\b"),
    dict(tag="sa", call=r"CALL APPCNS\b"),
    dict(tag="fu", call=r"CALL FUELCN\b"),
    dict(tag="be", call=r"CALL RSBENCH\b", nth=1),
    dict(tag="ne", call=r"CALL NEMSCN\b", nth=1),
    dict(tag="re", call=r"CALL RESDRP\b", nth=1),
    # Start of each projection year (after RDPR): everything the yearly chain reads,
    # for the end-to-end test that runs every port in RESD's order.
    dict(tag="yb", call=r"CALL NEWHSE\b", routines=[
        "NEWHSE", "SQFTCALC", "RSHVAC", "RHTRTEC", "RHTRADD", "RDISTGEN", "RCLTEC", "RCLADD", "RCWTEC",
        "RCWADD", "RDWTEC", "RDWADD", "RWHTEC", "REUADD", "RSTVTEC", "RDRYTEC", "RDRYADD", "RREFTEC",
        "RREFADD", "RFRZTEC", "RFRZADD", "RHTRCON", "RCLCON", "RCWCON", "RDWCON", "RWHCON", "RSTOVCON",
        "RDRYCON", "RREFCON", "RFRZCON", "LTCNS", "APCNS", "SHTCNS", "APPCNS", "FUELCN", "RSBENCH",
        "NEMSCN", "RESDRP"]),
]
RESD_STATE_BLOCK_FILES = ["resdrep", "rtek", "rscon", "rseff"]
RESD_STATE_EXTRA = ["QELRS", "QNGRS", "QDSRS", "QLGRS", "QKSRS", "QBMRS", "QGERS", "QSTRS", "QPVRS",
                    "QTRRS", "PELRSOUT", "PELRS", "PNGRS", "PDSRS", "PLGRS", "PKSRS", "MC_JPGDP"]
# Other modules' blocks the residential routines can read. Around a target, any of
# their arrays the routine mentions is dumped too (not in 'final').
RESD_WIDE_FILES = ["ncntrl", "qblk", "mpblk", "ampblk", "macout", "eusprc", "qsblk", "cogen", "uefpout",
                   "uecpout", "e111d", "steoblock", "emission", "emablk", "bldglrn"]
RESD_DECL_FILES = ["parametr", "resdrep", "rtek", "rscon", "rseff", "apq"] + RESD_WIDE_FILES

MODULES = {
    "comm": dict(build="build", run="run", years=DUMP_YEARS, targets=TARGETS, includes=STATE_INCLUDES,
                 use=None, block_files=STATE_BLOCK_FILES, extra=STATE_EXTRA, decl_files=DECL_FILES,
                 module_text=False),
    "resd": dict(build="build_resd", run="run_resd", years=RESD_DUMP_YEARS, targets=RESD_TARGETS,
                 includes=[], use="R_", block_files=RESD_STATE_BLOCK_FILES, extra=RESD_STATE_EXTRA,
                 decl_files=RESD_DECL_FILES, module_text=True, wide_files=RESD_WIDE_FILES,
                 outside_files=["tranrep"]),
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


def routine_bodies(source_text):
    """{lowercase name: body text} for every routine and function in the file."""
    out = {}
    # Routines nest (all of resd.f sits inside RESD), so find each one's own end.
    for m in re.finditer(r"^[ \t]*(?:REAL(?:\*4)?[ \t]+)?(?:SUBROUTINE|FUNCTION)[ \t]+(\w+)", source_text, re.I | re.M):
        e = re.compile(rf"^[ \t]*END[ \t]+(?:SUBROUTINE|FUNCTION)[ \t]+{m.group(1)}\b", re.I | re.M).search(source_text, m.end())
        if e:
            body = source_text[m.end():e.start()]
            out[m.group(1).lower()] = "\n".join(l.split("!", 1)[0] for l in body.splitlines())
    return out


def routine_idents(source_text, routines):
    """Lowercase identifiers used in the named routines and everything they call."""
    bodies = routine_bodies(source_text)
    used, todo, seen = set(), [r.lower() for r in routines], set()
    while todo:
        r = todo.pop()
        if r in seen:
            continue
        seen.add(r)
        words = {w.lower() for w in re.findall(r"[A-Za-z_]\w*", bodies[r])}
        used |= words
        todo += [w for w in words if w in bodies and w not in seen and w != "resd"]
    return used


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

    def calls_for(subset):
        cs = [c for c in (dump_call("'//tag//'", n, *decls.get(n.lower(), ("?", 0))) for n in {s.lower(): s for s in subset}.values()) if c]
        return [c.replace("''//tag//''", "tag") for c in cs]

    calls = calls_for(names)
    extra_routine = ""
    if CFG["module_text"]:
        # A full residential dump is about 170 MB. Around a target, dump only the
        # shared arrays its routines mention; the full set is kept for 'final'.
        wide = list(names)
        for n in CFG["wide_files"]:
            wide += common_names((inc_dir / n).read_text(encoding="latin-1"))
        # Blocks only some routines include (tranrep) clash with R_, so their
        # arrays go through a second routine that includes them instead.
        outside = []
        for n in CFG["outside_files"]:
            decls.update(declarations((inc_dir / n).read_text(encoding="latin-1")))
            outside += common_names((inc_dir / n).read_text(encoding="latin-1"))
        blocks, xblocks = [], []
        for tg in map(as_dict, CFG["targets"]):
            used = routine_idents(source_text, tg["routines"])
            sub = calls_for([n for n in wide if n.lower() in used])
            xsub = calls_for([n for n in outside if n.lower() in used])
            cond = f"if (tag == '{tg['tag']}_in' .or. tag == '{tg['tag']}_out') then"
            if xsub:
                sub.append("        call oracle_state_x(tag)")
                xblocks.append(f"      {cond}\n" + "\n".join(xsub) + "\n      endif")
            blocks.append(f"      {cond}\n" + "\n".join(sub) + "\n        return\n      endif")
        calls = blocks + calls
        xinc = "\n".join(f"      include '{n}'" for n in ["parametr", "ncntrl"] + CFG["outside_files"])
        extra_routine = f"""
      subroutine oracle_state_x(tag)
      implicit none
{xinc}
      character(*) tag
{chr(10).join(xblocks)}
      end subroutine oracle_state_x
"""
    years = ", ".join(map(str, CFG["years"]))
    inc = "\n".join(f"      include '{n}'" for n in CFG["includes"])
    if CFG["use"]:
        inc = f"      use {CFG['use']}\n      implicit none\n" + inc  # USE must come first
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
{extra_routine}""")
    return len(calls)


def as_dict(target):
    if isinstance(target, dict):
        name = re.search(r"CALL\s+(\w+)", target["call"], re.I).group(1)
        return dict(dict(nth=0, end=None, private=[], carried=[], before=False, routines=[name]), **target)
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
        if not private and not carried:
            continue
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
    """Create the dump folders and drop old index files (odump appends to them)."""
    dirs = [RUN / "out" / "state" / "final" / str(CFG["years"][-1])]
    for tg in map(as_dict, CFG["targets"]):
        for side in ("in", "out", "pre"):
            dirs += [RUN / "out" / "state" / f"{tg['tag']}_{side}" / str(y) for y in CFG["years"]]
    for d in dirs:
        d.mkdir(parents=True, exist_ok=True)
        (d / "index.txt").unlink(missing_ok=True)


if __name__ == "__main__":
    upstream, src = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
    CFG = MODULES[sys.argv[3] if len(sys.argv) > 3 else "comm"]
    BUILD, RUN = HERE / CFG["build"], HERE / CFG["run"]
    n = write_state_routine(upstream / "includes", src.read_text(encoding="latin-1"))
    instrument(src, upstream)
    make_dirs()
    print(f"hooks: {n} shared arrays per state dump, {len(CFG['targets'])} routine(s) instrumented")
