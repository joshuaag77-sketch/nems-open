"""Instrument the oracle's copy of comm.f so it can dump EIA's internal state.

For a routine being ported, the oracle dumps every commercial COMMON array just
before and just after the call ("<tag>_in", "<tag>_out"), plus the routine's
private SAVE arrays at its end. Each dump goes to
run/out/state/<tag>/<year>/<name>.bin with a line in index.txt giving the type,
rank and Fortran bounds, so Python can rebuild arrays with Fortran indexing.
Dumps only happen on the final iteration of the years in DUMP_YEARS.

Output only: nothing here changes a computed value.

Usage: python -I hooks.py <upstream> <comm.f90 to instrument in place>
"""

import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BUILD = HERE / "build"
RUN = HERE / "run"

# 2019, 2020, 2021, 2025, 2026, 2027, 2030, 2040, 2050
DUMP_YEARS = [30, 31, 32, 36, 37, 38, 41, 51, 61]
FIRST_YEAR = 30  # CMFirstYr: first-call dumps are written under this year

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

# Added for the rest of the commercial module. A target may carry a sixth item:
# "before" puts the private-array dump ahead of the end marker (for a RETURN).
TARGETS += [
    ("dg", r"CALL CDistGen\s*\(curiyr,curitr,rcrpt,rcdbg\)", r"before:^\s*RETURN\s+! SEND CONTROL BACK TO COMM", [
        "UNITS", "TRILLS", "capacity", "TRILLSOWNUSE", "fuelusage", "HWBTU", "SHBTU", "INVEST", "Ifueltype",
        "QCMDGSG", "QRSDGSG", "PRSDGSG", "xCumPenSqft", "com111drensub", "CMCogenEL",
        "SolarPVTechPotentialMW", "SolarPVAvailRoofArea", "SolarPVInstalledMW", "SolarPVUsedRoofArea",
        "WindTechPotentialMW", "WindAvailFS", "WindInstalledMW", "WindBldgCount",
        "xPVGenAdded", "xWindGenAdded", "XINXDECAY", "xRPS", "iNumYrsatRPSBaseRate", "iNumRPSCreditYrs", "xpen",
    ], []),
    ("bm", r"CALL COMBenchmarking\s*\(RCDBG,RCQUAN\)", r"^510\s+FORMAT \(A20,1X,A20", [
        "WaterServicesElQ", "TelecomServicesElQ", "DiffQBM", "SolarPVContrib", "ApplyRamp",
        "LastDecayYr", "DecayBM", "NoHist", "STEOBM2pct", "EF1", "EF2", "EF3", "NRGBILL", "STIMULUS", "STEOBM",
        "EmissionFactor", "CMEmissions",
    ], ["DiffQBM"]),
    # COMReport runs only in the last year; the call is the tail of a one-line IF.
    ("rp", r"IF\s*\(CURIYR\.EQ\.LASTYR\s*\.AND\.\s*FCRL\.EQ\.1\)\s*&\s*\n\s*CALL COMReport\s*\(RCDBG,RCRPT,SDReportOpts,ReportOption\)",
     r"before:^\s*RETURN\s*\n\s*END\s*\n!\*+\s*\n! Floorspace Survival function", [
         "CMFinalUnbenchUse", "UnBenchedCon",
     ], []),
]

# Run once, in the first iteration of the first year: state around the first call
# of a routine (the file readers and one-time edits live there).
FIRST_CALL = ["tc"]

# Dump points inside a routine with no call to wrap: (tag, line to follow, private arrays).
# The dump is the first-call state, so it only fires in the first iteration of the first year.
PROBES = [
    ("frd", r"^\s*! End of block to read input data", [
        "ExistImprvHt", "ExistImprvCl", "dcf", "MarketPenetrationMels", "MelsElQ",
        "ServicesIndex", "xplicitmiscshr", "DataCtrServPenetration", "OfficePCPenetration",
        "MarketPenetrationSC", "pctSCSavings", "CT_flag", "ApplyRamp", "BASELINEBKWHCM",
    ]),
    # CDistGen's tables, right after it reads KCOGEN and KGENTK.
    ("fdg", r"^\s*xpctWindSuitable=\.10", [
        "CMCogenEL", "NUMTECHS", "NUMYEARS", "NUMDIV", "NUMBLDG", "NVINT", "iGenCapCostYr", "XOPERHOURS",
        "GlobalLearn", "xpctPVSuitable", "XBeta", "Xc0", "XINX", "XINXFY", "XINXLY", "XTAXRATE", "XDOWNPAYPCT",
        "XINTRATE", "XTERM", "XINFLATION", "XALPHA", "XPENPARM", "xkwMin", "xkwmax", "xScaleFac", "ISKIP",
        "iRPSStartYear", "iRPSPhaseOutYear", "iRPSGrandFatherYear", "AEQUIPNAME", "IFUELTYPE", "IFIRSTYR",
        "ILASTYR", "XKW", "XELEFF", "XLOSSFAC", "XDEGRAD", "XEQLIFE", "xtxlife", "xdep", "XWHRECOVERY",
        "XINSTCOST", "XCAPCOST", "XMAINTCST", "xIntervalCst", "iIntervalYrs", "XAVAIL", "XTXCRPCT",
        "xTXCrMaxPerKW", "xTXCrMaxPerSys", "comtxcrpct_div", "xRPS", "iNumYrsatRPSBaseRate", "iNumRPSCreditYrs",
        "NumPVNiche", "xSolarInsolation", "xSqftShare", "xRateScalar", "xRoofAreatoSqftRatio", "xWindSpeed",
        "xNGRateScalar", "XBLDGSHARE", "cbecsFlspcCatShare", "cbecsAVGSQFT", "xelecavgkwh", "XEXOGPEN",
        "XA", "XB", "XC", "xpctWindSuitable",
    ]),
]

# Shared state dumped around each target call.
STATE_INCLUDES = ["parametr", "ncntrl", "apq", "macout", "eusprc", "mxpblk", "emmparm", "emission", "qsblk",
                  "cogen", "bldglrn", "uefpout", "uecpout", "tranrep", "comparm", "comvars", "commrep"]
STATE_BLOCK_FILES = ["comparm", "comvars", "commrep"]
# Arrays from other modules' blocks that the commercial routines read.
STATE_EXTRA = ["QELCM",                                   # service demand
               "PELCM", "PNGCM", "PDSCM", "XPELCM", "XPNGCM", "XPDSCM",
               "PELCMOUT", "MC_JPGDP", "MC_RMGBLUSREAL",  # technology choice
               "PRSCM", "PLGCM", "PCLCM", "PMGCM", "PKSCM",  # consumption (minor fuels)
               "MC_NP", "PCLIN", "TRQ_ELEC", "WHRFOSS", "QSBMCM", "EMCM", "EMCMC",  # benchmarking
               "QNGCM", "QGFCM", "QGICM", "QDSCM", "QRSCM", "QRLCM", "QLGCM", "QPRCM", "QCLCM",
               "QMGCM", "QKSCM", "QSTCM", "QPVCM", "QBMCM",
               # distributed generation
               "CGCOMMGEN", "CGCOMMCAP", "CGCOMMQ", "CGCPVCOM", "CGCWNCOM", "KCHPCESGEN",
               "CFuelCell_MW", "CPV_MW", "RPV_MW", "UPV_MW", "RFuelCell_MW", "CWind_MW", "RWind_MW",
               "CMicroTur_MW", "RMicroTur_MW", "PELME", "EPRPSPR", "EPRPSTGT", "UPIRA_APPYR"]
DECL_FILES = ["parametr", "comparm", "comvars", "commrep", "qblk", "apq", "ampblk",
              "mpblk", "mxpblk", "eusprc", "macout", "emmparm", "emission", "qsblk", "cogen", "tranrep",
              "bldglrn", "uefpout", "uecpout"]

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


def write_state_routine(inc_dir):
    decls = {}
    for n in DECL_FILES:
        decls.update(declarations((inc_dir / n).read_text(encoding="latin-1")))
    names = []
    for n in STATE_BLOCK_FILES:
        names += common_names((inc_dir / n).read_text(encoding="latin-1"))
    names += STATE_EXTRA
    calls = [c for c in (dump_call("'//tag//'", n, *decls.get(n.lower(), ("?", 0))) for n in dict.fromkeys(names)) if c]
    calls = [c.replace("''//tag//''", "tag") for c in calls]
    years = ", ".join(map(str, DUMP_YEARS))
    inc = "\n".join(f"      include '{n}'" for n in STATE_INCLUDES)
    body = "\n".join(calls)
    (BUILD / "oracle_state.f90").write_text(f"""! Generated by hooks.py. Do not edit.
      subroutine oracle_state(tag)
      implicit none
{inc}
      character(*) tag
      integer, parameter :: years({len(DUMP_YEARS)}) = (/ {years} /)
      if (tag(1:1) == 'f') then
        if (CURIYR .ne. {FIRST_YEAR} .or. CURITR .ne. 1) return
      else
        if (FCRL .ne. 1 .or. .not. any(years == CURIYR)) return
      endif
{body}
      end subroutine oracle_state
""")
    return len(calls)


def private_dumps(tag, names, src_decls):
    return [c for c in (dump_call(tag, n, *src_decls.get(n.lower(), ("?", 0))) for n in names) if c]


def private_dumps(tag, names, src_decls):
    return [c for c in (dump_call(tag, n, *src_decls.get(n.lower(), ("?", 0))) for n in names) if c]


def instrument(comm_path: Path, upstream: Path):
    text = comm_path.read_text(encoding="latin-1")
    # Private arrays may be declared in an include file (EmissionFactor) rather than in comm.f itself.
    src_decls = {}
    for n in DECL_FILES:
        src_decls.update(declarations((upstream / "includes" / n).read_text(encoding="latin-1")))
    src_decls.update(declarations(text))
    years = ", ".join(map(str, DUMP_YEARS))
    for tag, call_re, end_re, private, carried in TARGETS:
        m = re.search(r"^(\s*)(" + call_re + r")", text, re.I | re.M)
        ind = m.group(1)
        first_in = f"{ind}CALL ORACLE_STATE('f{tag}_in')\n" if tag in FIRST_CALL else ""
        first_out = f"\n{ind}CALL ORACLE_STATE('f{tag}_out')" if tag in FIRST_CALL else ""
        text = (text[:m.start()] + f"{ind}CALL ORACLE_STATE('{tag}_in')\n{first_in}{ind}{m.group(2)}\n"
                f"{ind}CALL ORACLE_STATE('{tag}_out'){first_out}" + text[m.end():])
        if end_re is None:
            continue
        lines = [f"      IF (FCRL .EQ. 1 .AND. ANY((/ {years} /) == CURIYR)) THEN"]
        lines += private_dumps(f"{tag}_out", private + carried, src_decls)
        lines.append(f"      ELSE IF (ANY((/ {years} /) == CURIYR)) THEN")
        lines += private_dumps(f"{tag}_pre", carried, src_decls)
        lines.append("      ENDIF")
        before = end_re.startswith("before:")
        e = re.search(end_re.removeprefix("before:"), text, re.I | re.M)
        if before:
            at = text.rindex("\n", 0, e.start()) + 1
        else:
            at = text.index("\n", e.end()) + 1
        text = text[:at] + "\n".join(lines) + "\n" + text[at:]
    for tag, anchor_re, private in PROBES:
        lines = [f"      IF (CURIYR .EQ. {FIRST_YEAR} .AND. CURITR .EQ. 1) THEN",
                 f"      CALL ORACLE_STATE('{tag}_out')"]
        lines += private_dumps(f"{tag}_out", private, src_decls)
        lines.append("      ENDIF")
        e = re.search(anchor_re, text, re.I | re.M)
        at = text.index("\n", e.end()) + 1
        text = text[:at] + "\n".join(lines) + "\n" + text[at:]
    comm_path.write_text(text, encoding="latin-1")


def make_dirs():
    for tag, *_ in TARGETS:
        for side in ("in", "out", "pre"):
            for y in DUMP_YEARS:
                (RUN / "out" / "state" / f"{tag}_{side}" / str(y)).mkdir(parents=True, exist_ok=True)
        if tag in FIRST_CALL:
            for side in ("in", "out"):
                (RUN / "out" / "state" / f"f{tag}_{side}" / str(FIRST_YEAR)).mkdir(parents=True, exist_ok=True)
    for tag, *_ in PROBES:
        (RUN / "out" / "state" / f"{tag}_out" / str(FIRST_YEAR)).mkdir(parents=True, exist_ok=True)


if __name__ == "__main__":
    upstream, comm = Path(sys.argv[1]).resolve(), Path(sys.argv[2])
    n = write_state_routine(upstream / "includes")
    instrument(comm, upstream)
    make_dirs()
    print(f"hooks: {n} shared arrays per state dump, {len(TARGETS)} routine(s) and {len(PROBES)} probe(s) instrumented")
