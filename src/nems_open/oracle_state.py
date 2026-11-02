"""Read the oracle's state dumps (oracle/hooks.py, oracle/hooks_tran.py) as Fortran-indexed arrays.

Each module's oracle has its own run folder: run (commercial), run_resd, run_tran.
"""

from pathlib import Path

import numpy as np

from nems_open.fortran_array import FArray
from nems_open.paths import REPO_ROOT

# Each module's oracle runs in its own folder (see oracle/gen_oracle.py MODULES).
RUN_DIRS = {"comm": "run", "resd": "run_resd", "tran": "run_tran"}
ORACLE = REPO_ROOT / "oracle"
STATE = ORACLE / "run" / "out" / "state"


def state_dir(module: str = "comm", run: str | None = None) -> Path:
    """run: the run folder by name (e.g. "run_tran"), instead of the module."""
    return ORACLE / (run or RUN_DIRS[module]) / "out" / "state"


def available(tag: str, year: int, module: str = "comm", run: str | None = None) -> bool:
    return (state_dir(module, run) / tag / str(year) / "index.txt").exists()


def load(tag: str, year: int, module: str = "comm", run: str | None = None) -> dict:
    """{name: FArray, or a scalar} for one dump, keyed by lowercase Fortran name."""
    folder = state_dir(module, run) / tag / str(year)
    out = {}
    for line in (folder / "index.txt").read_text(encoding="latin-1").splitlines():
        parts = line.split()
        if not parts:
            continue
        name, code, rank = parts[0], parts[1], int(parts[2])
        bounds = [(int(parts[3 + 2 * k]), int(parts[4 + 2 * k])) for k in range(rank)]
        dtype = np.dtype(code)
        raw = np.fromfile(folder / f"{name}.bin", dtype=dtype)
        if rank == 0:
            out[name] = raw[0]
        else:
            shape = tuple(hi - lo + 1 for lo, hi in bounds)
            out[name] = FArray(raw.reshape(shape, order="F"), [lo for lo, _ in bounds])
    return out
