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
    # EIA's endpoint project settings: the user colours NGMM's report procedures name, and its compatibility
    # options (rounding_compatibility Aimms_3_7, Case_compatibility Aimms_4_80), so NGMM runs as in NEMS.
    shutil.copytree(Path(UPSTREAM) / "models" / "main" / "aimms_endpoint" / "MainProject" / "Settings",
                    w / "MainProject" / "Settings", dirs_exist_ok=True)
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
    rows = [[str(i + 1) for i in idx] + [f"{arr[idx]:.17g}"] for idx in np.ndindex(arr.shape)]
    head = list(dims) + [name]
    # AIMMS reads composite tables by column position: every entry must end where its header ends.
    width = [max([len(h)] + [len(r[c]) for r in rows]) for c, h in enumerate(head)]
    fmt = lambda cells: " " + " ".join(x.rjust(w) for x, w in zip(cells, width))
    return "COMPOSITE TABLE:\n" + "\n".join([fmt(head)] + [fmt(r) for r in rows]) + "\n;\n"


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
    """{"BLOCK_VAR": {(i, j, ...): value}} from NGMM's fromAIMMS file, 1-based indices.

    The file is AIMMS `display` output, read in NEMS by filer.f (funfmt 7): blocks of "COMPOSITE TABLE:", a header
    whose last word is the name (maybe with its domain in parentheses; the year column is "globalyr"), rows of
    index labels and a value, and ";". Labels may be quoted; rows AIMMS leaves out are zero."""
    return parse_composite(Path(run) / "ngas" / "fromAIMMS" / f"GlobalDataToNEMS_{year}_{itr:02d}.txt")


def parse_composite(path: Path) -> dict[str, dict]:
    text = Path(path).read_text(encoding="utf-8-sig", errors="replace")
    out = {}
    for block in re.split(r"(?i)composite table:", text)[1:]:
        lines = [ln for ln in block.split(";")[0].splitlines() if ln.strip()]
        if not lines:
            continue
        name = re.sub(r"\(.*", "", lines[0]).split()[-1].upper().split("::")[-1]
        vals = {}
        for ln in lines[1:]:
            cells = [c.strip("'\"") for c in ln.split()]
            try:
                vals[tuple(int(c) for c in cells[:-1])] = float(cells[-1].replace("D", "E").replace("d", "e"))
            except ValueError:
                continue
        out[name] = vals
    for m in re.finditer(r"(?m)^\s*([A-Za-z]\w*)\s*:=\s*([-+.\deEdD]+)\s*;", text):   # scalars, if any
        out.setdefault(m.group(1).upper(), {(): float(m.group(2))})
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


# --- inside run_model ---------------------------------------------------------------------------------

PRICE_OUT = ("MPBLK/pgfin", "MPBLK/pgiin", "MPBLK/pngcm", "MPBLK/pngel", "MPBLK/pngin", "MPBLK/pngrs", "MPBLK/pngtr")


class AimmsGas:
    """EIA's NGMM as run_model's gas market (ogs="aimms"). One AIMMS process for the whole run.

    Each loop iteration run_model calls begin(year, itr, q, prices, fcrl) once, with the demand the loop just
    settled; NGMM solves on cb2026's inputs with the loop's gas use (QBLK q*ng/gf/gi, lease, plant and pipeline
    fuel, and the power sector's seasonal burn by EMM region scaled to the loop's qngel) and the loop's gas prices.
    prices() then hands the stand-in NGMM's delivered prices for that year (every other gas price stays on the
    stand-in's curves). end_year(year) makes NEMS's reporting call, which rolls NGMM's state to the next year.
    Years from 2024 (NGMM's first) to start_year - 1 run first on cb2026's own inputs.

    calibrate: NGMM run once per year on cb2026's final inputs lands 0 to 5% off EIA's restart (EIA's restart
    is the end of several iterations and five cycles). With calibrate, each price is multiplied by EIA's value
    over NGMM's own on cb2026's inputs (reference.pkl from `python -m nems_open.ngmm.aimms`), so the baseline is
    EIA's and a run's moves are NGMM's."""

    def __init__(self, start_year: int = 2027, case: str = "cb2026", calibrate: bool = True, run: Path = RUN_DIR):
        from nems_open.supply_standin.data import restart_path
        self.base = restart_arrays(restart_path(case))
        z = np.load(restart_path(case), allow_pickle=False)
        names = {k.lower(): k for k in z.files}
        self.eia = {k: z[names[k.lower()]].astype(np.float64) for k in PRICE_OUT}
        self.eia_hh = z[names["ngtdmrep/oghhprng"]].astype(np.float64)
        self.factor = {k: np.ones((11, 61)) for k in PRICE_OUT}
        self.hh_factor = np.ones(61)
        if calibrate:
            ref = run / "reference.pkl"
            if not ref.exists():
                raise FileNotFoundError(f"{ref}: run python -m nems_open.ngmm.aimms first (about 3 min)")
            import pickle
            with open(ref, "rb") as f:
                outs = pickle.load(f)["outputs"]
            for y, o in outs.items():
                j = y - 1990
                for k in PRICE_OUT:
                    name = k.replace("/", "_").upper()
                    if name in o:
                        mine = to_array(o[name], (11, 61))[:, j]
                        self.factor[k][:, j] = np.divide(self.eia[k][:, j], mine, out=np.ones(11), where=mine > 0)
                if "NGTDMREP_OGHHPRNG" in o:
                    mine = to_array(o["NGTDMREP_OGHHPRNG"], (61,))[j]
                    self.hh_factor[j] = self.eia_hh[j] / mine if mine > 0 else 1.0
        self.ngmm = Ngmm(run, fresh=True)
        self.out = {k: v.copy() for k, v in self.eia.items()}
        self.henry_hub = self.eia_hh.copy()
        self.year, self.itr, self.seconds = None, 0, 0.0
        try:
            for y in range(2024, start_year):
                self.last = self.base
                self._call(y, 1, self.base)
                self.end_year(y)
        except Exception:
            self.close()
            raise

    def _call(self, year, itr, arrays, ncrl=0, fcrl=0):
        o, sec = self.ngmm.call(year, itr, arrays, ncrl=ncrl, fcrl=fcrl)
        self.seconds += sec
        self.year, self.itr = year, itr
        if ncrl:
            return
        j = year - 1990
        for k in PRICE_OUT:
            name = k.replace("/", "_").upper()
            if name in o:
                self.out[k][:, j] = to_array(o[name], (11, 61))[:, j] * self.factor[k][:, j]
        if "NGTDMREP_OGHHPRNG" in o:
            self.henry_hub[j] = to_array(o["NGTDMREP_OGHHPRNG"], (61,))[j] * self.hh_factor[j]

    def begin(self, year: int, itr: int, q: dict, prices: dict, fcrl: int = 0):
        j = year - 1990
        arrays = dict(self.base)
        for k, v in q.items():
            key = k.lower()
            if key in arrays and np.shape(arrays[key]) == np.shape(v):
                arrays[key] = np.asarray(v, dtype=np.float64)
        for k, v in prices.items():
            key = k.lower()
            if key in arrays and np.shape(arrays[key]) == np.shape(v):
                arrays[key] = np.asarray(v, dtype=np.float64)
        b, now = self.base["qblk/qngel"][10, j], q["QBLK/qngel"][10, j]
        if b > 0:   # the power sector's seasonal gas burn by EMM region, scaled to the loop's
            s = self.base["uefdout/sqngelgr"].copy()
            s[:, j, :] *= now / b
            arrays["uefdout/sqngelgr"] = s
        self.last = arrays
        self._call(year, itr, arrays, fcrl=fcrl)

    def prices(self, qngas_us=None) -> dict[str, np.ndarray]:
        return {k: v.copy() for k, v in self.out.items()}

    def end_year(self, year: int):
        self._call(year, self.itr + 1, getattr(self, "last", None) or self.base, ncrl=1, fcrl=1)
        self.last = None

    def close(self):
        self.ngmm.close()


HEADLINE = ("NGTDMREP_OGHHPRNG", "MPBLK_PNGRS", "MPBLK_PNGCM", "MPBLK_PNGIN", "MPBLK_PNGEL", "MPBLK_PNGTR",
            "NGTDMREP_NGSCRV_P", "NGTDMREP_NGSCRV_Q")


def compare(res: dict, case: str = "cb2026", names=HEADLINE) -> dict:
    """{name: {year: NGMM's value over EIA's restart value - 1}} for each year's own column (US row where regional)."""
    from nems_open.supply_standin.data import restart_path
    z = np.load(restart_path(case), allow_pickle=False)
    keys = {k.lower(): k for k in z.files}
    out = {}
    for name in names:
        block, var = name.split("_", 1)
        eia = z[keys[f"{block}/{var}".lower()]]
        rows = {}
        for y, outputs in res["outputs"].items():
            vals = outputs.get(name)
            if not vals:
                continue
            ours = to_array(vals, eia.shape)
            j = y - 1990
            o, e = (ours[10, j], eia[10, j]) if eia.ndim == 2 else (ours[j], eia[j])
            rows[y] = float(o / e - 1) if e else float("nan")
        out[name] = rows
    return out


if __name__ == "__main__":
    a = sys.argv[1:]
    res = reference(int(a[0]) if a else 2024, int(a[1]) if len(a) > 1 else 2050)
    import pickle
    with open(RUN_DIR / "reference.pkl", "wb") as f:
        pickle.dump(res, f)
