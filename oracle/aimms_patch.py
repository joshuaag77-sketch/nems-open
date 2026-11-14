"""Prepare EIA's AIMMS projects for the oracle: copy them into the run folder and add a file-driven entry point.

NEMS starts ECP and EFD through a DEX web service (models/main/aimms_endpoint): Python posts the year and iteration,
the library's ECP_API_Call / EFD_API_Call reads them from the request and runs MainExecution. The oracle has no web
service, so each library gets one more interface procedure, File_Call, which is ECP_API_Call without the request
read: the caller sets api_curcalyr and api_curitr (already in the interface) and File_Call runs the same
MainExecution with the same error handler and writes the same done.txt. The model itself is not changed.

A small main project, main/wrapper, references the libraries the way EIA's aimms_endpoint does (less the stopwatch
library, which only times out runs and sits at an absolute path) and has one procedure per module:
run_ecp / run_efd read <module>/request.txt ("req_year := 2027 ; req_itr := 1 ;") and call File_Call.

Run:  python oracle/aimms_patch.py <run folder>
"""

import re
import shutil
import sys
from pathlib import Path

UPSTREAM = Path(__file__).resolve().parent.parent / "nems-upstream" / "models"
LIBRARIES = {"ecp": ("ecp/MainProject/ecp.ams", "ec", "ECP"), "efd": ("efd/MainProject/efd.ams", "ed", "EFD")}
COPY = ["ecp", "efd", "rest", "coal", "ngas", "hmm"]

FILE_CALL = """	Procedure File_Call {{
		Body: {{
			! Oracle entry point (nems-open oracle/aimms_patch.py): {mod}_API_Call without the DEX request read.
			curcalyr('1') := api_curcalyr;
			curitr('1') := api_curitr;
			ErrorOut_file_name := "../../{low}/log/aimmsRunOnly.err";
			if fileexists(ErrorOut_file_name) then
			    FileDelete(ErrorOut_file_name, 0);
			endif;
			block
			MainExecution;
			 Onerror err do
			   ErrorHandler(err);
			endblock;
			write done to file "../../{low}/done.txt";
		}}
	}}
"""

WRAPPER_REFS = """<?xml version="1.0"?>
<References AIMMS_Version="25.5.7.1 (x64)">
	<MainProject Path="MainProject" />
	<RepositoryLibrary UUID="BDF54E1C-AF05-4D77-856C-F3C05F20FFB8" Name="AimmsDEX" Version="25.2.1.1" />
	<Library Path="..\\..\\ecp\\MainProject" />
	<Library Path="..\\..\\efd\\MainProject" />
	<Library Path="..\\..\\rest\\MainProject" />
	<RepositoryLibrary UUID="E26C298C-5EF6-42C5-B7B7-59ED3DF48D6F" Name="AimmsXLLibrary" Version="24.0.1.1" />
	<Library Path="..\\..\\coal\\MainProject" />
	<Library Path="..\\..\\ngas" />
	<Library Path="..\\..\\hmm" />
</References>
"""

WRAPPER_PROJECT = """<?xml version="1.0"?>
<Project AimmsVersion="25.5.7.1 unicode x64" ProjectUUID="5A0C1E77-2B4D-4F7A-8C51-0E9D3B6A7F21">
	<ModelFileName>wrapper.ams</ModelFileName>
</Project>
"""

WRAPPER_MODEL = """## ams_version=1.0

Model Main_wrapper {
    Parameter req_year;
    Parameter req_itr;
    Procedure MainInitialization;
    Procedure MainExecution;
    Procedure run_ecp {
        Body: {
            read from file "../../ecp/request.txt";
            ec::api_curcalyr := req_year;
            ec::api_curitr := req_itr;
            ec::File_Call;
        }
    }
    Procedure run_efd {
        Body: {
            read from file "../../efd/request.txt";
            ed::api_curcalyr := req_year;
            ed::api_curitr := req_itr;
            ed::File_Call;
        }
    }
    Procedure MainTermination {
        Body: {
            return 1;
        }
    }
}
"""


def add_file_call(ams: Path, prefix: str, mod: str) -> None:
    text = ams.read_text(encoding="utf-8-sig")
    if "Procedure File_Call" in text:
        return
    iface = re.search(r"(Interface: \{\s*data \{)([^}]*)(\})", text)
    if not iface:
        raise SystemExit(f"{ams}: no Interface block")
    text = text[:iface.end(2)] + ", File_Call" + text[iface.end(2):]
    anchor = text.index(f"\tProcedure {mod}_API_Call {{")
    text = text[:anchor] + FILE_CALL.format(mod=mod, low=mod.lower()) + text[anchor:]
    ams.write_text(text, encoding="utf-8")


def prepare(run: Path) -> None:
    for name in COPY:
        dst = run / name
        if dst.exists():
            shutil.rmtree(dst)
        shutil.copytree(UPSTREAM / name, dst, ignore=shutil.ignore_patterns("_GIS", "*.aimmspack"))
    for low, (rel, prefix, mod) in LIBRARIES.items():
        add_file_call(run / rel, prefix, mod)
        (run / low / "log").mkdir(exist_ok=True)
    w = run / "main" / "wrapper"
    (w / "MainProject").mkdir(parents=True, exist_ok=True)
    (w / "wrapper.aimms").write_text(WRAPPER_REFS)
    (w / "MainProject" / "Project.xml").write_text(WRAPPER_PROJECT)
    (w / "MainProject" / "wrapper.ams").write_text(WRAPPER_MODEL)


if __name__ == "__main__":
    prepare(Path(sys.argv[1]))
