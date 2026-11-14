"""EIA's real NGMM (AIMMS), run headless on our data: the reference for the gas market, and a module run_model can call.

How NEMS runs NGMM (models/main/aimms_endpoint.py, models/ngas/nems_ngmm.ams): the AIMMS library stays open as a DEX
web service. Each call, the Fortran first writes every array in ngas/input/ngputvars.txt to the text file
ngas/toAIMMS/GlobalDataToAimms_<year>_<itr>.txt (AIMMS composite tables), then posts the year, iteration and
reporting flag; NGMM_MainExecution_API reads the file, solves, and writes the arrays in nggetvars.txt to
ngas/fromAIMMS/GlobalDataToNEMS_<year>_<itr>.txt. NGMM keeps its own state (storage, last year's prices) in memory
from call to call, and rolls to the next year on the reporting call (NCRL = 1).

Here the same, without the web service or the Fortran:
- prepare() copies EIA's ngas folder into a run folder and adds one interface procedure to the library,
  NGMM_File_Call: NGMM_MainExecution_API without the DEX request read (the caller sets curcalyr, curitr, ncrl).
  A small wrapper project (main/wrapper, as oracle/aimms_patch.py on the electricity lane) references the library
  and has serve_ngmm, a loop that waits for ngas/request.txt, calls NGMM_File_Call, and waits again, until asked to quit.
  It also writes ng_runval.txt (from the scedes file, as models/main/prenems_aimms.py does) and ngsteo.txt (STEO
  targets, with EIA's steo_load.py as NEMS writes them).
- write_inputs() writes the toAIMMS file from arrays keyed like the restart ("NGTDMREP/ogprcng").
- read_outputs() parses the fromAIMMS file back into arrays.
- Ngmm runs one AIMMS process and calls it year by year.

    python -m nems_open.ngmm.aimms 2024 2050       # EIA's NGMM on cb2026's inputs, every year
"""
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np

from nems_open.paths import UPSTREAM

AIMMS_EXE = Path(os.environ.get("AIMMS_EXE", Path(os.environ.get("LOCALAPPDATA", "")) / "AIMMS" / "IFA" / "Aimms"
                                / "25.5.7.1-x64-VS2022" / "Bin" / "aimms.exe"))
RUN_DIR = Path(os.environ.get("NEMS_NGMM_RUN", Path.home() / "dev" / "oracle-cache" / "ngmm-aimms"))
SRC = Path(UPSTREAM) / "models" / "ngas"

FILE_CALL_NAME = "NGMM_File_Call"
WRAPPER_REFS = """<?xml version="1.0"?>
<References AIMMS_Version="25.5.7.1 (x64)">
	<MainProject Path="MainProject" />
	<RepositoryLibrary UUID="BDF54E1C-AF05-4D77-856C-F3C05F20FFB8" Name="AimmsDEX" Version="25.2.1.1" />
	<RepositoryLibrary UUID="E26C298C-5EF6-42C5-B7B7-59ED3DF48D6F" Name="AimmsXLLibrary" Version="24.0.1.1" />
	<Library Path="..\\..\\ngas" />
</References>
"""
WRAPPER_PROJECT = """<?xml version="1.0"?>
<Project AimmsVersion="25.5.7.1 unicode x64" ProjectUUID="7C3B2E91-4D6A-4F0B-9E27-1A5D8C0F6B34">
	<ModelFileName>wrapper.ams</ModelFileName>
</Project>
"""
WRAPPER_MODEL = """## ams_version=1.0

Model Main_wrapper {
    Parameter req_year;
    Parameter req_itr;
    Parameter req_ncrl;
    Parameter req_quit;
    Parameter served;
    Procedure MainInitialization;
    Procedure MainExecution;
    Procedure serve_ngmm {
        Body: {
            ! nems-open: wait for ../../ngas/request.txt, run NGMM once, repeat; req_quit := 1 ends it.
            served := 0;
            while served < 100000 do
                if FileExists("../../ngas/request.txt") then
                    req_quit := 0;
                    read from file "../../ngas/request.txt";
                    FileDelete("../../ngas/request.txt", 0);
                    if req_quit = 1 then
                        break;
                    endif;
                    nn::curcalyr := req_year;
                    nn::curitr := req_itr;
                    nn::ncrl := req_ncrl;
                    nn::NGMM_File_Call;
                    served += 1;
                else
                    Delay(0.1);
                endif;
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

ARRAY_LINE = re.compile(r"^\s*LABEL=\s*(\w+)\s*,\s*VAR=\s*(\w+)", re.I)


# --- the run folder ---------------------------------------------------------------------------------

def add_file_call(ams: Path) -> None:
    """Copy NGMM_MainExecution_API as NGMM_File_Call, minus the DEX request read, and export it."""
    text = ams.read_text(encoding="utf-8-sig")
    if f"Procedure {FILE_CALL_NAME}" in text:
        return
    start = text.index("\tProcedure NGMM_MainExecution_API {")
    end = text.index("\n\t}\n", text.index("dex::ServiceName", start)) + len("\n\t}\n")
    proc = text[start:end].replace("Procedure NGMM_MainExecution_API {", f"Procedure {FILE_CALL_NAME} {{", 1)
    a = proc.index("_sp_input := dex::api::RequestAttribute")
    b = proc.index("helper_sp_input := _sp_input;")
    b = proc.index("\n", b) + 1
    proc = proc[:a] + "! nems-open: no DEX request; the caller set curcalyr, curitr and ncrl.\n" + proc[b:]
    proc = re.sub(r"\n\t\tdex::ServiceName:[^\n]*", "", proc)
    text = text[:end] + proc + text[end:]
    text = text.replace("NGMM_MainExecution_API, ncrl", f"NGMM_MainExecution_API, {FILE_CALL_NAME}, ncrl", 1)
    ams.write_text(text, encoding="utf-8")


def runval_text(scenario: str = "cb2026") -> str:
    """ng_runval.txt as models/main/prenems_aimms.py write_runval_ng writes it."""
    keys = ["STEOBM", "STEONG", "STSCALNG", "KEEPOPEN", "NGASSUMPTIONSN", "NGMARKUPSN", "NGLNGEXPN", "NGMEXICON",
            "NGSPOTPRCN", "NGCAPACITYN", "NGCANADAN", "NGEIAN", "NGSETMAPN", "NGVARTARN", "NGSTEOFACTINN", "NGTEXASN",
            "NGTXCAPAN"]
    vals = {}
    for line in (Path(UPSTREAM) / "scedes" / f"scedes.{scenario}.csv").read_text(encoding="latin-1").splitlines():
        parts = line.split(",")
        if len(parts) > 1:
            vals.setdefault(parts[0].strip().upper(), parts[1].strip())
    out = ""
    for k in keys:
        v = vals[k]
        out += f"{k} := {v};\n" if v.isnumeric() else f'{k} := "{v}";\n'
    return out + "x_LNG_Gamma2 := 55.0;\nx_LNG_Gamma1 := -42.5;"


def ngsteo_text() -> str:
    """ngsteo.txt as EIA's steo_load.py writes it (exg = 1), on the STEO arrays nems_open.steo rebuilds."""
    from nems_open import steo
    upstream = Path(UPSTREAM)
    names, nvars = steo.block_order(upstream / "includes" / "steoblock")
    other = steo.SteoBlock(names, nvars)
    from types import SimpleNamespace
    pyfiler = SimpleNamespace(ncntrl=SimpleNamespace(exc=0, exg=1), other=other, utils=SimpleNamespace(baseyr=1990))
    sys.path.insert(0, str(upstream / "models" / "main"))
    try:
        import steo_load
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "input").mkdir()
            (Path(tmp) / "ngas").mkdir()
            for f in ("steovars.csv", "steolist.txt"):
                shutil.copy(upstream / "input" / f, Path(tmp) / "input" / f)
            cwd = Path.cwd()
            os.chdir(tmp)
            try:
                steo_load.read_all_steo_vars(None, pyfiler)
            finally:
                os.chdir(cwd)
            return (Path(tmp) / "ngas" / "ngsteo.txt").read_text()
    finally:
        sys.path.remove(str(upstream / "models" / "main"))


def prepare(run: Path = RUN_DIR, scenario: str = "cb2026") -> Path:
    """A fresh run folder: run/ngas (EIA's, patched) and run/main/wrapper."""
    run = Path(run)
    ng = run / "ngas"
    if ng.exists():
        shutil.rmtree(ng)
    shutil.copytree(SRC, ng, ignore=shutil.ignore_patterns("_GIS", "*.aimmspack", "Pages", "Templates"))
    add_file_call(ng / "nems_ngmm.ams")
    for d in ("toAIMMS", "fromAIMMS", "log", "log/ProfilerResults"):
        (ng / d).mkdir(parents=True, exist_ok=True)
    (ng / "ng_runval.txt").write_text(runval_text(scenario))
    (ng / "ngsteo.txt").write_text(ngsteo_text())
    w = run / "main" / "wrapper"
    (w / "MainProject").mkdir(parents=True, exist_ok=True)
    (w / "wrapper.aimms").write_text(WRAPPER_REFS)
    (w / "MainProject" / "Project.xml").write_text(WRAPPER_PROJECT)
    (w / "MainProject" / "wrapper.ams").write_text(WRAPPER_MODEL)
    return run


# --- the transfer files -----------------------------------------------------------------------------

def array_list(name: str) -> list[tuple[str, str]]:
    """[(BLOCK, VAR)] from ngas/input/ngputvars.txt (NEMS to NGMM) or nggetvars.txt (NGMM to NEMS)."""
    out = []
    for line in (SRC / "input" / name).read_text().splitlines():
        m = ARRAY_LINE.match(line)
        if m and (m.group(1).upper(), m.group(2).upper()) not in out:
            out.append((m.group(1).upper(), m.group(2).upper()))
    return out


_domains: dict | None = None


def domains() -> dict[str, list[str]]:
    """AIMMS index domain of every BLOCK_VAR parameter in nems_ngmm.ams (upper case)."""
    global _domains
    if _domains is None:
        text = (SRC / "nems_ngmm.ams").read_text(encoding="utf-8-sig")
        _domains = {}
        for m in re.finditer(r"Parameter (\w+) \{\s*IndexDomain: \(?([\w, ]+?)\)?;", text):
            _domains.setdefault(m.group(1).upper(), [s.strip() for s in m.group(2).split(",")])
    return _domains


def composite(name: str, dims: list[str], arr: np.ndarray) -> str:
    """One AIMMS composite table, every element (zeros included: the file is read in merge mode)."""
    arr = np.asarray(arr, dtype=np.float64)
    lines = ["COMPOSITE TABLE:", "  " + "  ".join(dims) + "  " + name]
    for idx in np.ndindex(arr.shape):
        lines.append("  " + "  ".join(str(i + 1) for i in idx) + f"  {arr[idx]:.17g}")
    return "\n".join(lines) + "\n;\n"


def write_inputs(run: Path, arrays: dict, year: int, itr: int, ncrl: int = 0, fcrl: int = 0, cycle: int = 1) -> Path:
    """ngas/toAIMMS/GlobalDataToAimms_<year>_<itr>.txt from restart-style arrays ("BLOCK/var", lower case)."""
    dom = domains()
    parts = [composite("NCNTRL_CURIYR", ["M1"], [year - 1989]), composite("NCNTRL_FCRL", ["M1"], [fcrl]),
             composite("NCNTRL_NCRL", ["M1"], [ncrl]), composite("CYCLEINFO_CURIRUN", ["M1"], [cycle])]
    for block, var in array_list("ngputvars.txt"):
        name = f"{block}_{var}"
        if name in ("NCNTRL_CURIYR", "NCNTRL_FCRL", "NCNTRL_NCRL", "CYCLEINFO_CURIRUN"):
            continue
        key = f"{block}/{var}".lower()
        if key not in arrays:
            raise KeyError(f"NGMM needs {key}")
        a = np.asarray(arrays[key])
        dims = dom.get(name, [])
        if a.ndim == 0 or not dims:
            parts.append(f"{name} := {float(a.reshape(-1)[0]) if a.size else 0.0!r};\n")
            continue
        if a.ndim != len(dims):
            raise ValueError(f"{name}: array {a.shape} against AIMMS domain {dims}")
        parts.append(composite(name, dims, a))
    out = Path(run) / "ngas" / "toAIMMS" / f"GlobalDataToAimms_{year}_{itr:02d}.txt"
    out.write_text("".join(parts))
    return out


def read_outputs(run: Path, year: int, itr: int) -> dict[str, dict]:
    """{"BLOCK_VAR": {(i, j, ...): value}} from NGMM's fromAIMMS file (AIMMS display output, 1-based labels)."""
    path = Path(run) / "ngas" / "fromAIMMS" / f"GlobalDataToNEMS_{year}_{itr:02d}.txt"
    text = path.read_text(encoding="utf-8-sig", errors="replace")
    out = {}
    for m in re.finditer(r"(\w+)\s*:=\s*data\s*\{(.*?)\}\s*;", text, re.S):
        vals = {}
        for k, v in re.findall(r"\(([^)]*)\)\s*:\s*([-+.\deE]+)", m.group(2)):
            vals[tuple(int(x.strip().strip("'")) for x in k.split(","))] = float(v)
        if not vals:
            for k, v in re.findall(r"'?(\d+)'?\s*:\s*([-+.\deE]+)", m.group(2)):
                vals[(int(k),)] = float(v)
        out[m.group(1).upper().split("::")[-1]] = vals
    return out


def to_array(values: dict, shape: tuple) -> np.ndarray:
    a = np.zeros(shape)
    for idx, v in values.items():
        a[tuple(i - 1 for i in idx)] = v
    return a


def restart_arrays(path) -> dict:
    """The arrays NGMM reads, from a restart file, keyed "block/var" (lower case)."""
    z = np.load(path, allow_pickle=False)
    names = {k.lower(): k for k in z.files}
    want = [f"{b}/{v}".lower() for b, v in array_list("ngputvars.txt")]
    return {k: z[names[k]] for k in want if k in names}


# --- the process ------------------------------------------------------------------------------------

class Ngmm:
    """One AIMMS process serving NGMM calls (single process: RAM is the limit on this machine)."""

    def __init__(self, run: Path = RUN_DIR, fresh: bool = True, timeout: float = 900):
        self.run = Path(run)
        if fresh or not (self.run / "ngas").exists():
            prepare(self.run)
        self.timeout = timeout
        self.ng = self.run / "ngas"
        for f in ("request.txt", "done.txt"):
            (self.ng / f).unlink(missing_ok=True)
        log = open(self.run / "aimms_stdout.txt", "w")
        self.proc = subprocess.Popen([str(AIMMS_EXE), "-Rserve_ngmm", str(self.run / "main" / "wrapper" / "wrapper.aimms"),
                                      "--hidden"], stdout=log, stderr=subprocess.STDOUT)

    def _request(self, text: str):
        tmp = self.ng / "request.tmp"
        tmp.write_text(text)
        os.replace(tmp, self.ng / "request.txt")

    def call(self, year: int, itr: int, arrays: dict, ncrl: int = 0, fcrl: int = 0, cycle: int = 1) -> tuple[dict, float]:
        """Write the inputs, run NGMM for (year, itr), return its outputs and the seconds it took."""
        write_inputs(self.run, arrays, year, itr, ncrl, fcrl, cycle)
        done = self.ng / "done.txt"
        done.unlink(missing_ok=True)
        t = time.time()
        self._request(f"req_year := {year} ;\nreq_itr := {itr} ;\nreq_ncrl := {ncrl} ;\nreq_quit := 0 ;\n")
        while not done.exists():
            if self.proc.poll() is not None:
                raise RuntimeError(f"AIMMS exited ({self.proc.returncode}) during NGMM {year} itr {itr}; see {self.run}")
            if time.time() - t > self.timeout:
                raise TimeoutError(f"NGMM {year} itr {itr} took over {self.timeout} s")
            time.sleep(0.2)
        return read_outputs(self.run, year, itr), time.time() - t

    def close(self):
        if self.proc.poll() is None:
            self._request("req_quit := 1 ;\n")
            try:
                self.proc.wait(60)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def reference(first: int = 2024, last: int = 2050, case: str = "cb2026") -> dict:
    """EIA's NGMM year by year on one case's final inputs: {year: outputs}, plus timings. Two calls a year as
    NEMS's last pass makes them: the solve (itr 1) and the reporting call (NCRL = 1) that rolls NGMM to the next year."""
    from nems_open.supply_standin.data import restart_path
    arrays = restart_arrays(restart_path(case))
    m = Ngmm()
    out, times = {}, {}
    try:
        for y in range(first, last + 1):
            out[y], times[y] = m.call(y, 1, arrays)
            m.call(y, 2, arrays, ncrl=1, fcrl=1)
            print(y, f"{times[y]:.1f} s", flush=True)
    finally:
        m.close()
    return {"outputs": out, "seconds": times}


if __name__ == "__main__":
    a = sys.argv[1:]
    res = reference(int(a[0]) if a else 2024, int(a[1]) if len(a) > 1 else 2050)
    import pickle
    with open(RUN_DIR / "reference.pkl", "wb") as f:
        pickle.dump(res, f)
