"""Run EIA's HSM (oil and gas supply, models/hsm in the AEO2026 release) standalone on a restart file.

EIA's code is read from NEMS_UPSTREAM at run time, not copied into this repo. HSM wants a work
folder holding its input/ folder, restart.npz, dict.txt, varlist.txt and FILELIST, so one is built
under NEMS_OGSM_WORK (default ~/dev/oracle-cache/ogsm). pyfiler1 is our pure Python stand-in.
"""
import os
import shutil
import sys
from pathlib import Path

from nems_open.paths import REFERENCE_RUN, UPSTREAM


def upstream() -> Path:
    return Path(UPSTREAM)


def work_dir() -> Path:
    return Path(os.environ.get("NEMS_OGSM_WORK", Path.home() / "dev" / "oracle-cache" / "ogsm"))


def prepare(restart: Path = REFERENCE_RUN) -> Path:
    """Build the work folder (cheap to redo) and return it."""
    work = work_dir()
    src = upstream() / "models" / "hsm"
    work.mkdir(parents=True, exist_ok=True)
    if not (work / "input").exists():
        shutil.copytree(src / "input", work / "input")
    for name in ("dict.txt", "varlist.txt"):
        f = upstream() / "input" / name
        if f.exists() and not (work / "input" / name).exists():
            shutil.copy(f, work / "input" / name)
    for name in ("FILELIST", "pyfiler1.cp312-win_amd64.pyd"):  # only checked for existence
        (work / name).touch()
    # HSM writes some debug CSVs unconditionally, into folders it does not create.
    for d in ("intermediate_tables", "debug", "debug/projects_debug/crude", "debug/projects_debug/natgas", "debug/projects_debug/selected",
              "debug/projects_debug/all", "debug/steo_debug"):
        (work / d).mkdir(parents=True, exist_ok=True)
    shutil.copy(restart, work / "restart.npz")
    return work


def run(restart: Path = REFERENCE_RUN):
    """Run HSM for every year; return the pyfiler1 stand-in, whose arrays now hold HSM's outputs."""
    work = prepare(restart)
    os.environ.setdefault("MPLBACKEND", "Agg")
    os.environ["OMP_NUM_THREADS"] = "1"
    sys.path[:0] = [str(Path(__file__).parent), str(upstream() / "models" / "hsm"), str(upstream() / "models" / "main")]
    os.chdir(work)
    import pyfiler1
    pyfiler1.load(str(work / "restart.npz"))
    import restart_load
    restart_load.read_restart_file = lambda *a, **k: None  # already loaded; EIA's loader trips on scalar keys
    import hsm
    hsm.run_hsm(2050, 1, pyfiler1, 0, None)
    return pyfiler1
