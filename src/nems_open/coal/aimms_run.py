"""Run EIA's coal model (coal.ams, AIMMS) headless on the cb2026 restart, as the reference for the HiGHS port.

In NEMS the CMM is an AIMMS library started through a DEX web service. Each year and iteration NEMS's Python
(models/main/aimms_util.write_aimms_input) writes everything coalputvars.txt names into
coal/toAIMMS/GlobalDataToAIMMS_<year>_<itr>.txt as AIMMS composite tables, and the library's NEMS_Monitor reads
it (ReadGlobalDataFromNEMS) and runs MainExecution, which solves the LP and writes
coal/fromAIMMS/GlobalDataToNEMS_<year>_<itr>.txt. The model keeps its lagged state (prior-year production,
prices, targets) in memory from year to year, so a replay has to run every year in one AIMMS process.

This module:
  write_input(year, itr, folder)   the input file, written the way write_aimms_input writes it, from the restart
                                   (converged values; the base year sends every year, later years their own slice)
  prepare(run)                     a run folder: a copy of models/coal with a File_Call entry point added to
                                   coal.ams (Coal_API_Call without the DEX request read, plus an export of the
                                   supply curves, lag state and solution), and a wrapper project main/wrapper
                                   whose run_coal procedure loops years and iterations in one process
  command(run)                     the aimms.exe command line (EIA's own headless invocation)

Run (one AIMMS job at a time, under HEAVY.lock):
    python -m nems_open.coal.aimms_run <run folder> 2024 2050 2
"""

import shutil
import sys
from pathlib import Path

import numpy as np

from nems_open import dictionary
from nems_open.coal import state
from nems_open.snapshot import Snapshot

BASE_YEAR = 2024              # CPSBaseYr; the first year the CMM runs in NEMS
FIRST_NEMS_YEAR = 1990        # MNUMYR 1
AIMMS = Path.home() / "AppData" / "Local" / "AIMMS" / "IFA" / "Aimms" / "25.5.7.1-x64-VS2022" / "Bin" / "aimms.exe"

# What File_Call writes after each solve, for the HiGHS port to compare against (AIMMS text data format).
EXPORT = ("ProductionVolume", "ProdVolSolutionPriorYr", "LAG_PRI", "LAG_PROD", "QTarget", "qprods",
          "FY_PROD_CAP3", "SC_1_PRICE87", "SC_QUAN", "Qdutzr", "EMM_max_SubBitBtus_D", "EMM_max_LigBtus_D",
          "TrubndScrubbed", "TrubndUnscrubbed", "Copy8c_CdyrsScrubbed", "Copy9c_CdyrsUnscrubbed",
          # duals as MainExecution stores them after the solve (ShadowPrice * MC_JPGDP(CPSBaseYr))
          "ShadowDomesticElectricityDemand", "ShadowResidCommDemand", "ShadowIndustrialDemand", "ShadowCokingDemand",
          "SupplyCurveStepBalShadow3",
          # the solution's flows and the rates it paid
          "ElectricityTransportAC", "IndustrialTransport", "CokingTransport", "ResidentialTransport",
          "ExportsTransport2", "Trate2wSurchBtu",
          "IndustrialDemand", "CokingDemand", "ResidCommDemand", "ImportsElectricity", "ImportsIndustrial", "ImportsCoking")

FILE_CALL = """	Procedure File_Call {
		Body: {
			! nems-open coal/aimms_run.py: Coal_API_Call without the DEX request read, as NEMS_Monitor runs it.
			ncntrl_curcalyr(1) := api_curcalyr;
			ncntrl_curitr(1) := api_curitr;
			ErrorOut_file_name := "../../coal/log/aimmsRunOnly.err";
			block
			  if ncntrl_curcalyr(1) = cpsbaseyr and ncntrl_curitr(1) = 1 then
			    ReadData;
			    LoadGlobal("../../coal/cases/global_data");
			  endif;
			  ReadGlobalDataFromNEMS;
			  MainExecution;
			  ! what the solve was, for the showreel log (reads the math program's suffixes; changes nothing)
			  info_rows := PartialLeastCostDomesticCoal.NumberOfConstraints;
			  info_columns := PartialLeastCostDomesticCoal.NumberOfVariables;
			  info_nonzeros := PartialLeastCostDomesticCoal.NumberOfNonzeros;
			  info_objective := PartialLeastCostDomesticCoal.Objective;
			  info_iterations := PartialLeastCostDomesticCoal.Iterations;
			  info_solution_time := PartialLeastCostDomesticCoal.SolutionTime;
			  info_status := PartialLeastCostDomesticCoal.ProgramStatus;
			  info_solver := CurrentSolver('LP');
			  write info_rows, info_columns, info_nonzeros, info_objective, info_iterations, info_solution_time,
			        info_status, info_solver to file "../../coal/solve_info.txt" in replace mode;
			  if FileExists("../../coal/export.on") then   ! diagnostics only; run_model's calls skip them
			  sExportFile := "../../coal/export/coal_" + formatstring("%i", ncntrl_curcalyr(1)) + "_"
			                 + formatstring("%>02i", ncntrl_curitr(1)) + ".txt";
			  write EXPORT_LIST to file sExportFile in replace mode;
			  ! which constraints bind: their shadow prices after the solve
			  dual_sub(DReg,pt2,cyr) := SubbituminousDiversity.ShadowPrice(DReg,pt2,cyr);
			  dual_lig(DReg,pt2,cyr) := LigniteDiversity.ShadowPrice(DReg,pt2,cyr);
			  dual_cont_s(SReg,Sulf,Mtyp,Rank,DReg,cyr) := ContractsScrubbed.ShadowPrice(SReg,Sulf,Mtyp,Rank,DReg,cyr);
			  dual_cont_u(SReg,Sulf,Mtyp,Rank,DReg,cyr) := ContractsUnScrubbed.ShadowPrice(SReg,Sulf,Mtyp,Rank,DReg,cyr);
			  dual_so2(DReg,cyr) := Copy_SULFPNConstraint.ShadowPrice(DReg,cyr);
			  dual_cap(SReg,Sulf,Mtyp,Rank,cyr) := ProductionCapacityLimit.ShadowPrice(SReg,Sulf,Mtyp,Rank,cyr);
			  dual_hg(cyr) := Mercp02.ShadowPrice(cyr);
			  dual_aci(cyr) := Acixxxxy2.ShadowPrice(cyr);
			  dual_ind(IndSec,DReg,cyr) := IndustrialDemandRequirement.ShadowPrice(IndSec,DReg,cyr);
			  sExportFile := "../../coal/export/duals_" + formatstring("%i", ncntrl_curcalyr(1)) + "_"
			                 + formatstring("%>02i", ncntrl_curitr(1)) + ".txt";
			  write dual_sub, dual_lig, dual_cont_s, dual_cont_u, dual_so2, dual_cap, dual_hg, dual_aci, dual_ind
			        to file sExportFile in replace mode;
			  endif;
			Onerror err do
			  ErrorHandler(err);
			endblock;
			write done to file "../../coal/done.txt";
			COALResetOptions;
		}
		StringParameter sExportFile;
		Parameter info_rows;
		Parameter info_columns;
		Parameter info_nonzeros;
		Parameter info_objective;
		Parameter info_iterations;
		Parameter info_solution_time;
		ElementParameter info_status { Range: AllSolutionStates; }
		ElementParameter info_solver { Range: AllSolvers; }
		Parameter dual_sub { IndexDomain: (DReg,pt2,cyr); }
		Parameter dual_lig { IndexDomain: (DReg,pt2,cyr); }
		Parameter dual_cont_s { IndexDomain: (SReg,Sulf,Mtyp,Rank,DReg,cyr); }
		Parameter dual_cont_u { IndexDomain: (SReg,Sulf,Mtyp,Rank,DReg,cyr); }
		Parameter dual_so2 { IndexDomain: (DReg,cyr); }
		Parameter dual_cap { IndexDomain: (SReg,Sulf,Mtyp,Rank,cyr); }
		Parameter dual_hg { IndexDomain: cyr; }
		Parameter dual_aci { IndexDomain: cyr; }
		Parameter dual_ind { IndexDomain: (IndSec,DReg,cyr); }
	}
"""

WRAPPER_REFS = """<?xml version="1.0"?>
<References AIMMS_Version="25.5.7.1 (x64)">
	<MainProject Path="MainProject" />
	<RepositoryLibrary UUID="BDF54E1C-AF05-4D77-856C-F3C05F20FFB8" Name="AimmsDEX" Version="25.2.1.1" />
	<RepositoryLibrary UUID="E26C298C-5EF6-42C5-B7B7-59ED3DF48D6F" Name="AimmsXLLibrary" Version="24.0.1.1" />
	<Library Path="..\\\\..\\\\coal\\\\MainProject" />
</References>
""".replace("\\\\", "\\")

WRAPPER_PROJECT = """<?xml version="1.0"?>
<Project AimmsVersion="25.5.7.1 unicode x64" ProjectUUID="7C2D4E61-3A5B-4C8D-9E0F-1A2B3C4D5E6F">
	<ModelFileName>wrapper.ams</ModelFileName>
</Project>
"""

WRAPPER_MODEL = """## ams_version=1.0

Model Main_wrapper {
    Parameter req_first;
    Parameter req_last;
    Parameter req_itrs;
    Parameter wr_year;
    Parameter wr_itr;
    Parameter req_year;
    Parameter req_itr;
    Parameter req_quit;
    Parameter served;
    Procedure MainInitialization;
    Procedure serve_coal {
        Body: {
            ! nems-open: wait for ../../coal/serve.txt, run the CMM once for that year and iteration, repeat;
            ! req_quit := 1 ends it. One process for a whole run, so the model keeps its lag state as in NEMS.
            served := 0;
            while served < 100000 do
                if FileExists("../../coal/serve.txt") then
                    req_quit := 0;
                    read from file "../../coal/serve.txt";
                    FileDelete("../../coal/serve.txt", 0);
                    if req_quit = 1 then
                        break;
                    endif;
                    cl::api_curcalyr := req_year;
                    cl::api_curitr := req_itr;
                    cl::File_Call;
                    served += 1;
                else
                    Delay(0.1);
                endif;
            endwhile;
        }
    }
    Procedure MainExecution;
    Procedure run_coal {
        Body: {
            read from file "../../coal/request.txt";
            wr_year := req_first;
            while wr_year <= req_last do
                wr_itr := 1;
                while wr_itr <= req_itrs do
                    cl::api_curcalyr := wr_year;
                    cl::api_curitr := wr_itr;
                    cl::File_Call;
                    wr_itr += 1;
                endwhile;
                wr_year += 1;
            endwhile;
        }
    }
    Procedure MainTermination {
        Body: {
            return 1;
        }
    }
}
"""


def _dims(var: dictionary.Variable) -> list[str]:
    """Dimension names as parse_putget_file gives them (a number n becomes Mn)."""
    return [f"M{d}" if str(d).isdigit() else str(d) for d in var.dims]


def _aligned(head: list[str], rows: list[list[str]], left_last: bool = False) -> str:
    """A composite table laid out as pandas to_string lays it out: every column right-justified to its
    widest entry, one space between columns. AIMMS reads composite tables by column position, so each
    value must sit under its header ("The entry 1 is between two columns" otherwise)."""
    width = [max(len(c) for c in col) for col in zip(head, *rows)]

    def line(cells):
        last = len(cells) - 1
        return " ".join(c.ljust(w) if left_last and k == last else c.rjust(w) for k, (c, w) in enumerate(zip(cells, width)))

    return "\nCOMPOSITE TABLE:\n" + "\n".join(line(r) for r in [head] + rows) + "\n;\n"


def _table(name: str, dims: list[str], arr: np.ndarray, year: int) -> str | None:
    """One composite table, as write_aimms_input writes it: indices 1-based, later indices vary slowest,
    and after the base year only the current year's slice of an MNUMYR array."""
    arr = np.asarray(arr)
    if arr.dtype.kind in "SUO":            # NCHAR scalars go as one quoted string; other character arrays are skipped
        if not name.startswith("NCHAR_"):
            return None
        text = b"".join(np.atleast_1d(arr).astype("S").ravel(order="F")).decode("latin-1").strip()
        return _aligned(["cl::M1", f"cl::{name}"], [["1", f'"{text}"']], left_last=True)
    yi = year - FIRST_NEMS_YEAR + 1
    if arr.ndim == 0:
        v = float(arr) if "CONVFACT" in name else int(arr)
        return _aligned(["cl::M1", f"cl::{name}"], [["1", str(v)]])
    idx = np.indices(arr.shape).reshape(arr.ndim, -1).T + 1
    vals = arr.reshape(-1)
    order = np.lexsort(idx.T)              # last index slowest, as sort_values([last, ..., first])
    idx, vals = idx[order], vals[order]
    if year > BASE_YEAR and "MNUMYR" in dims:
        keep = idx[:, dims.index("MNUMYR")] == yi
        idx, vals = idx[keep], vals[keep]
    head = [f"cl::{d}" for d in dims] + [f"cl::{name}"]
    rows = [[str(int(j)) for j in r] + [f"{float(v):.15f}"] for r, v in zip(idx, vals)]
    return _aligned(head, rows)


def write_input(year: int, itr: int, folder: Path, snapshot: Snapshot | None = None, arrays: dict | None = None,
                fcrl: int = 0) -> Path:
    """coal/toAIMMS/GlobalDataToAIMMS_<year>_<itr>.txt from the restart (converged values), with `arrays`
    ({"QBLK/QCLEL": array, ...}, upper-case restart keys) in place of the restart's where given."""
    s = snapshot or Snapshot()
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    parts = []
    for t in state.input_manifest():
        if t.key == "COALEMM/EMM_CL_UNITS" or t.variable is None:
            continue
        if t.key == "NCNTRL/CURCALYR":
            arr = np.asarray(year)
        elif t.key == "NCNTRL/CURITR":
            arr = np.asarray(itr)
        elif t.key == "NCNTRL/CURIYR":
            arr = np.asarray(year - FIRST_NEMS_YEAR + 1)
        elif t.key == "NCNTRL/FCRL":
            arr = np.asarray(fcrl)
        elif arrays and t.key in arrays:
            arr = arrays[t.key]
        else:
            arr = s[t.key]
        tab = _table(f"{t.block}_{t.name}", _dims(t.variable), arr, year)
        if tab:
            parts.append(tab)
    out = folder / f"GlobalDataToAIMMS_{year}_{itr:02d}.txt"
    out.write_text("".join(parts), encoding="utf-8")
    return out


def add_file_call(ams: Path) -> None:
    text = ams.read_text(encoding="utf-8-sig")
    if "Procedure File_Call" in text:
        return
    text = text.replace("data {api_curitr, api_curcalyr, Coal_API_Call}",
                        "data {api_curitr, api_curcalyr, Coal_API_Call, File_Call}", 1)
    anchor = text.index("\tProcedure coal_API_Call {")
    text = text[:anchor] + FILE_CALL.replace("EXPORT_LIST", ", ".join(EXPORT)) + text[anchor:]
    ams.write_text(text, encoding="utf-8")


def prepare(run: Path, mps: bool = False, steo: str = "shipped") -> None:
    """mps: switch on EIA's own debug branch in MainExecution (AIMCLSolvDebug, hard-set to 0 in the shipped
    model), which writes CPLEX's generated LP as an MPS file at every solve, with the row and column mapping.
    steo: "shipped" keeps the repo's clsteo.txt (what the checks in docs/coal_aimms.md used); "regenerate" writes it
    from steovars.csv as NEMS does each run (EXC = 1), not yet checked against cb2026."""
    run = Path(run)
    dst = run / "coal"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(state.COAL_DIR, dst, ignore=shutil.ignore_patterns("*.aimmspack", "backup"))
    add_file_call(dst / "MainProject" / "coal.ams")
    if mps:
        ams = dst / "MainProject" / "coal.ams"
        text = ams.read_text(encoding="utf-8")
        marker = "AIMCLSolvDebug :=0;"   # the first one, in MainExecution, just before if(AIMCLSolvDebug=1)
        at = text.find(marker)
        if at < 0 or "if(AIMCLSolvDebug=1)" not in text[at:at + 200]:
            raise SystemExit("AIMCLSolvDebug switch not found where expected")
        ams.write_text(text[:at] + "AIMCLSolvDebug :=1;" + text[at + len(marker):], encoding="utf-8")
    write_runval(run)
    if steo == "regenerate":   # NEMS regenerates it each run (EXC = 1)
        (dst / "clsteo.txt").write_text(clsteo_text())
    for sub in ("log", "export", "toAIMMS", "fromAIMMS"):
        (dst / sub).mkdir(exist_ok=True)
    w = run / "main" / "wrapper"
    (w / "MainProject").mkdir(parents=True, exist_ok=True)
    (w / "wrapper.aimms").write_text(WRAPPER_REFS)
    (w / "MainProject" / "Project.xml").write_text(WRAPPER_PROJECT)
    (w / "MainProject" / "wrapper.ams").write_text(WRAPPER_MODEL)


# prenems_aimms.write_runval_cmm's keys, in its order
RUNVAL_KEYS = ("CLUSEXPORTICMMN", "ICMMCOMMODITYMAPN", "CLOCEANDISTN", "CLAGGEXPORTMAPN", "CLEXPORTLIMITSN",
               "CLIMPORTLIMITSN", "CLINTLDEMANDN", "CLINTLQUALITYN", "CLINTLSUPPLYN", "CLDISTANCEN", "CLFEASIBLEROUTN",
               "CLFREIGHTN", "CLRATESELECN", "CLRATESNONELECN", "CLTONRAILMILEN", "CLTONSPERCARN", "CLINTLUSEXPORTN",
               "CLFLAGSN", "CLBYPRDN", "CLUSIMPN", "CLHMISCN", "CLHDISPN", "CLHSCPRN", "CLHWRLDN", "CLHEWQN", "CLRCAFN",
               "CLCPSRN", "CLCDSRN", "CLIMSURN", "CLCPSYRN", "CLPRFILN", "CLGNPLTN")


def write_runval(run: Path, scenario: str = "cb2026") -> Path:
    """coal/cl_runval.txt, as prenems_aimms.write_runval_cmm writes it from the scedes file: one line per
    file key, here with absolute paths into the run folder's copy of models/coal."""
    from nems_open.coal import inputs
    run = Path(run)
    lines = []
    files = inputs.selected_files(scenario)
    for key in RUNVAL_KEYS:
        path = Path(files[key]).resolve()
        try:
            path = run / "coal" / path.relative_to(state.COAL_DIR.resolve())
        except ValueError:
            pass
        lines.append(f'{key} := "{path.as_posix()}";')
    out = run / "coal" / "cl_runval.txt"
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return out


def request(run: Path, first: int, last: int, itrs: int) -> None:
    (Path(run) / "coal" / "request.txt").write_text(f"req_first := {first} ;\nreq_last := {last} ;\nreq_itrs := {itrs} ;\n")


def command(run: Path) -> list[str]:
    w = Path(run) / "main" / "wrapper"
    return [str(AIMMS), "-Rrun_coal", str(w / "wrapper.aimms"), "--hidden"]


def main(argv) -> None:
    import subprocess
    run, first, last, itrs = Path(argv[1]), int(argv[2]), int(argv[3]), int(argv[4])
    prepare(run, mps="mps" in argv[5:])
    s = Snapshot()
    for y in range(first, last + 1):
        for i in range(1, itrs + 1):
            write_input(y, i, run / "coal" / "toAIMMS", s)
    request(run, first, last, itrs)
    (run / "coal" / "export.on").write_text("")
    subprocess.run(command(run), cwd=run / "main" / "wrapper", check=False)


if __name__ == "__main__":
    main(sys.argv)


def _key(text: str) -> tuple:
    return tuple(x.strip().strip("'\"") for x in text.strip().strip("()").split(","))


def _num(text: str) -> float:
    return 0.0 if text == "zero" else float(text)


def _parse_table(lines: list[str]) -> dict:
    """An AIMMS `data table` block: header lines of column labels (right-aligned), a `!  ----` rule, then rows
    `( a, b )  v  v ...`, blanks meaning no value. Wide tables repeat header and rows in several blocks."""
    import re
    out, cols = {}, []
    for ln in lines:
        if not ln.strip():
            continue
        st = ln.strip()
        if st.startswith("!"):
            continue
        if st.startswith("("):
            close = ln.index(")")
            key = _key(ln[:close + 1])
            for label, right, left in cols:
                cell = ln[max(left, close + 1):right].strip()
                if cell:
                    out[key + (label,)] = _num(cell)
        else:   # a header line: labels and where they end
            cols, prev = [], 0
            for m in re.finditer(r"\S+", ln):
                cols.append((m.group(0), m.end(), prev))
                prev = m.end()
    return out


def read_export(path: Path) -> dict[str, dict]:
    """Parse an AIMMS `write ... to file` text data file into {identifier: {index tuple: value}}: the sparse
    form `NAME(dims) := data { ( a, b ) : v , ... } ;`, the `data table` form, and scalars. Prefixes (cl::)
    are dropped from names."""
    import re
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    heads = list(re.finditer(r"^\s*([\w:]+)(?:\([^)]*\))?\s*:=\s*", text, re.M))
    out: dict[str, dict] = {}
    for n, m in enumerate(heads):
        name = m.group(1).split("::")[-1]
        body = text[m.end(): heads[n + 1].start() if n + 1 < len(heads) else len(text)]
        body = body[:body.rfind(";")] if ";" in body else body
        if body.lstrip().startswith("data table"):
            out[name] = _parse_table(body.lstrip()[len("data table"):].splitlines())
        elif body.lstrip().startswith("data"):
            inner = body[body.index("{") + 1: body.rindex("}")]
            out[name] = {_key(e.group(1)): _num(e.group(2)) for e in
                         re.finditer(r"(\([^)]*\)|'[^']*'|[\w.+-]+)\s*:\s*([-+0-9.eE]+|zero)", inner)}
        else:
            try:
                out[name] = {(): float(body.strip())}
            except ValueError:
                pass
    return out


def clsteo_text() -> str:
    """coal/clsteo.txt as NEMS writes it before every run when the coal module is on (EXC = 1 in cb2026's scedes):
    EIA's steo_load.py (steovars_write_to_clsteo) on steovars.csv. The clsteo.txt shipped in the repo is an older
    STEO vintage (docs/coal_inputs.md); with it the CMM's STEO-year constraints do not fit cb2026's inputs."""
    import os
    import shutil as _sh
    import tempfile
    from types import SimpleNamespace
    from nems_open import steo
    from nems_open.paths import UPSTREAM
    upstream = Path(UPSTREAM)
    names, nvars = steo.block_order(upstream / "includes" / "steoblock")
    other = steo.SteoBlock(names, nvars)
    pyfiler = SimpleNamespace(ncntrl=SimpleNamespace(exc=1, exg=0), other=other, utils=SimpleNamespace(baseyr=1990))
    sys.path.insert(0, str(upstream / "models" / "main"))
    try:
        import steo_load
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "input").mkdir()
            (Path(tmp) / "coal").mkdir()
            for f in ("steovars.csv", "steolist.txt"):
                _sh.copy(upstream / "input" / f, Path(tmp) / "input" / f)
            cwd = Path.cwd()
            os.chdir(tmp)
            try:
                steo_load.read_all_steo_vars(None, pyfiler)
            finally:
                os.chdir(cwd)
            return (Path(tmp) / "coal" / "clsteo.txt").read_text()
    finally:
        sys.path.remove(str(upstream / "models" / "main"))
