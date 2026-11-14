"""Run EIA's LFMM (GAMS) standalone for one year on restart-style inputs: the run folder and the GAMS call.

prepare(run, year, arrays) builds a run folder the way NEMS's refine.f leaves it before `gams LFshell.gms`:
EIA's LF*.gms and input/ (plus input/iem/intcrdshr.xls), NEM_TO_LFMM1.gdx (gams_io), E85.gdx and STEO_Hist.gdx
(refine_side), CoalDRefMap.gdx and crudeshares.gdx (side_files). Two edits to the run folder's copies only: the GDXXRW
calls in LFprep.gms are commented out (GDXXRW is not in the GAMSPy install; the files they would write are already
there) and the LP solver is HiGHS instead of EIA's Xpress (Josh's free GAMS licence has open-source solvers only).

    python -m nems_open.lfmm.gams_run <run folder> <year> [compile]

The GDX writes run under the GAMS venv's Python (gams_io.GAMS_PYTHON), so this module needs only numpy and pywin32.
"""

import os
import pickle
import shutil
import subprocess
import sys
from pathlib import Path

from nems_open.lfmm import gams_io, refine_side, side_files
from nems_open.paths import REPO_ROOT, UPSTREAM

GAMS_EXE = gams_io.GAMS_SYSDIR / "gams.exe"
LICENCE = Path(os.environ.get("GAMS_LICENSE", Path.home() / "Documents" / "GAMSPy" / "gamspy_license.txt"))
SRC = Path(UPSTREAM) / "models" / "lfmm"


def _write(payload: dict, gdx: Path) -> None:
    pk = gdx.with_suffix(".pkl")
    with open(pk, "wb") as f:
        pickle.dump(payload, f)
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    subprocess.run([str(gams_io.GAMS_PYTHON), "-m", "nems_open.lfmm.gams_io", "write", str(pk), str(gdx)],
                   check=True, env=env)
    pk.unlink()


def patch(run: Path) -> None:
    prep = run / "LFprep.gms"
    t = prep.read_text(encoding="latin-1")
    t = t.replace("\n$call GDXXRW", "\n*nems-open: no GDXXRW; file written by side_files.py\n*$call GDXXRW")
    prep.write_text(t, encoding="latin-1")
    shell = run / "LFshell.gms"
    t = shell.read_text(encoding="latin-1")
    t = t.replace("\n$set   LPsolver  Xpress", "\n*nems-open: open-source LP solver\n$set   LPsolver  HiGHS", 1)
    shell.write_text(t, encoding="latin-1")


def prepare(run: Path, year: int, arrays: dict, itr: int = 1, fcrl: int = 0, ncrl: int = 0, cycle: int = 1,
            fresh: bool = True) -> Path:
    run = Path(run)
    if fresh:
        run.mkdir(parents=True, exist_ok=True)
        for f in (SRC / "source").glob("*.gms"):
            shutil.copy(f, run / f.name)
        if (run / "input").exists():
            shutil.rmtree(run / "input")
        shutil.copytree(SRC / "input", run / "input")
        shutil.copy(Path(UPSTREAM) / "input" / "iem" / "intcrdshr.xls", run / "input" / "intcrdshr.xls")
        patch(run)
        for gdx, payload in side_files.xls_payloads(run).items():
            _write(payload, run / gdx)
        _write(refine_side.steo_hist_payload(arrays), run / "STEO_Hist.gdx")
    _write(refine_side.e85_payload(arrays, year), run / "E85.gdx")
    pk = run / "NEM_TO_LFMM1.pkl"
    gams_io.to_npz(arrays, year, itr, fcrl, ncrl, cycle, pk)
    env = {**os.environ, "PYTHONPATH": str(REPO_ROOT / "src")}
    subprocess.run([str(gams_io.GAMS_PYTHON), "-m", "nems_open.lfmm.gams_io", "write", str(pk), str(run / "NEM_TO_LFMM1.gdx")],
                   check=True, env=env)
    pk.unlink()
    return run


def gams(run: Path, action: str = "", timeout: float = 7200) -> int:
    """`gams LFshell.gms` in the run folder (action "c" compiles only), EIA's own arguments plus the licence."""
    args = [str(GAMS_EXE), "LFshell.gms", "lo=2", "lf=LFMM.log", "o=LFshell.lst", "al=1", "errmsg=1",
            f"license={LICENCE}"]
    if action:
        args.append(f"a={action}")
    return subprocess.run(args, cwd=run, timeout=timeout).returncode


def restart_arrays(case: str = "cb2026") -> dict:
    """Every array NEM_TO_LFMM1.gdx and the side files need, from a restart file, keyed "BLOCK/NAME"."""
    import numpy as np
    from nems_open.supply_standin.data import restart_path
    z = np.load(restart_path(case), allow_pickle=False)
    names = {k.upper(): k for k in z.files}
    out = {v.key.upper(): z[names[v.key.upper()]] for v in gams_io.varlist() if v.key.upper() in names}
    out.update(refine_side.restart_inputs(case))
    return out


if __name__ == "__main__":
    run, year = Path(sys.argv[1]), int(sys.argv[2])
    prepare(run, year, restart_arrays())
    print("gams rc", gams(run, "c" if "compile" in sys.argv[3:] else ""))
