"""Run EIA's HSM (oil and gas supply, models/hsm in the AEO2026 release) standalone on a restart file.

EIA's code is read from NEMS_UPSTREAM at run time, not copied into this repo. HSM wants a work
folder holding its input/ folder, restart.npz, dict.txt, varlist.txt and FILELIST, so one is built
under NEMS_OGSM_WORK (default ~/dev/oracle-cache/ogsm). pyfiler1 is our pure Python stand-in.
"""
import os
import re
import shutil
import sys
from pathlib import Path

import numpy as np

from nems_open.paths import REFERENCE_RUN, UPSTREAM


def upstream() -> Path:
    return Path(UPSTREAM)


def work_dir() -> Path:
    return Path(os.environ.get("NEMS_OGSM_WORK", Path.home() / "dev" / "oracle-cache" / "ogsm"))


def prepare(restart: Path = REFERENCE_RUN, scedes: str = "scedes.cb2026.csv") -> Path:
    """Build the work folder (cheap to redo) and return it.

    EIA ships models/hsm/input/setup.csv pointing standalone runs at scedes.lowogs.csv, the low oil and gas
    supply side case (OGTECH=30, technology 50% slower, benchmarked to one STEO year only). That is not the
    reference case, so we point the work copy at `scedes` (cb2026, the reference).
    """
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
    setup = work / "input" / "setup.csv"
    setup.write_text(re.sub(r"(?m)^(standalone_scedes_file,)[^,]*", lambda m: m.group(1) + scedes, setup.read_text()))
    shutil.copy(restart, work / "restart.npz")
    return work


def run(restart: Path = REFERENCE_RUN, scedes: str = "scedes.cb2026.csv", scale: dict | None = None):
    """Run HSM for every year; return the pyfiler1 stand-in, whose arrays now hold HSM's outputs.

    scale: {"BLOCK/var": ratio} multiplies those restart arrays along their last (year) axis before the
    run. nems_open.ogsm.couple uses it to hand HSM a run's prices (NGTDMREP/ogprcng, ogwprng, LFMMOUT/rfcrudewhp).
    """
    work = prepare(restart, scedes)
    os.environ.setdefault("MPLBACKEND", "Agg")
    os.environ["OMP_NUM_THREADS"] = "1"
    sys.path[:0] = [str(Path(__file__).parent), str(upstream() / "models" / "hsm"), str(upstream() / "models" / "main")]
    os.chdir(work)
    import pyfiler1
    pyfiler1.load(str(work / "restart.npz"))
    for name, ratio in (scale or {}).items():
        block, var = name.split("/")
        arr = getattr(getattr(pyfiler1, block.lower()), var)
        arr *= np.asarray(ratio, dtype=arr.dtype)
    # HSM adds this year's wells onto ognowell in the restart. In a NEMS run it zeroes it
    # each year after the STEO start (module_unf.py:976); the standalone loop never reaches that line, so the
    # reference run's own values stayed in and every well was counted twice. Zero it, as NEMS does. (Zeroing ogcruderef too breaks the 2027 price weights, so leave it.)
    first = 2026 - 1990
    pyfiler1.ogsmout.ognowell[first:] = 0
    import restart_load
    restart_load.read_restart_file = lambda *a, **k: None  # already loaded; EIA's loader trips on scalar keys
    import hsm
    hsm.run_hsm(2050, 1, pyfiler1, 0, None)
    return pyfiler1
