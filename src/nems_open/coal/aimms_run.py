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
          "TrubndScrubbed", "TrubndUnscrubbed", "Copy8c_CdyrsScrubbed", "Copy9c_CdyrsUnscrubbed")

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
			  sExportFile := "../../coal/export/coal_" + formatstring("%i", ncntrl_curcalyr(1)) + "_"
			                 + formatstring("%>02i", ncntrl_curitr(1)) + ".txt";
			  write EXPORT_LIST to file sExportFile in replace mode;
			Onerror err do
			  ErrorHandler(err);
			endblock;
			write done to file "../../coal/done.txt";
			COALResetOptions;
		}
		StringParameter sExportFile;
	}
"""

WRAPPER_REFS = """<?xml version="1.0"?>
<References AIMMS_Version="25.5.7.1 (x64)">
	<MainProject Path="MainProject" />
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
    Parameter y;
    Parameter i;
    Procedure MainInitialization;
    Procedure MainExecution;
    Procedure run_coal {
        Body: {
            read from file "../../coal/request.txt";
            y := req_first;
            while y <= req_last do
                i := 1;
                while i <= req_itrs do
                    cl::api_curcalyr := y;
                    cl::api_curitr := i;
                    cl::File_Call;
                    i += 1;
                endwhile;
                y += 1;
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


def _table(name: str, dims: list[str], arr: np.ndarray, year: int) -> str | None:
    """One composite table, as write_aimms_input writes it: indices 1-based, later indices vary slowest,
    and after the base year only the current year's slice of an MNUMYR array."""
    arr = np.asarray(arr)
    if arr.dtype.kind in "SUO":            # NCHAR scalars go as one quoted string; other character arrays are skipped
        if not name.startswith("NCHAR_"):
            return None
        text = b"".join(np.atleast_1d(arr).astype("S").ravel(order="F")).decode("latin-1").strip()
        return f'\nCOMPOSITE TABLE:\ncl::M1 cl::{name}\n1 "{text}"\n;'
    yi =year - FIRST_NEMS_YEAR + 1
    if arr.ndim == 0:
        v = float(arr) if "CONVFACT" in name else int(arr)
        return f"\nCOMPOSITE TABLE:\ncl::M1 cl::{name}\n1 {v}\n;"
    idx = np.indices(arr.shape).reshape(arr.ndim, -1).T + 1
    vals = arr.reshape(-1)
    order = np.lexsort(idx.T)              # last index slowest, as sort_values([last, ..., first])
    idx, vals = idx[order], vals[order]
    if year > BASE_YEAR and "MNUMYR" in dims:
        keep = idx[:, dims.index("MNUMYR")] == yi
        idx, vals = idx[keep], vals[keep]
    head = " ".join(f"cl::{d}" for d in dims) + f" cl::{name}"
    rows = [" ".join(str(int(j)) for j in r) + f" {float(v):.15f}" for r, v in zip(idx, vals)]
    return "\nCOMPOSITE TABLE:\n" + head + "\n" + "\n".join(rows) + "\n;\n"


def write_input(year: int, itr: int, folder: Path, snapshot: Snapshot | None = None) -> Path:
    """coal/toAIMMS/GlobalDataToAIMMS_<year>_<itr>.txt from the restart (converged values)."""
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


def prepare(run: Path) -> None:
    run = Path(run)
    dst = run / "coal"
    if dst.exists():
        shutil.rmtree(dst)
    shutil.copytree(state.COAL_DIR, dst, ignore=shutil.ignore_patterns("*.aimmspack", "backup"))
    add_file_call(dst / "MainProject" / "coal.ams")
    write_runval(run)
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
        lines.append(f'{key} := "{str(path)}";')
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
    prepare(run)
    s = Snapshot()
    for y in range(first, last + 1):
        for i in range(1, itrs + 1):
            write_input(y, i, run / "coal" / "toAIMMS", s)
    request(run, first, last, itrs)
    subprocess.run(command(run), cwd=run / "main" / "wrapper", check=False)


if __name__ == "__main__":
    main(sys.argv)
