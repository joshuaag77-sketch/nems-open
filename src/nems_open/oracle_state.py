"""Read the oracle's state dumps (oracle/hooks.py) as Fortran-indexed arrays."""

from pathlib import Path

import numpy as np

from nems_open.fortran_array import FArray
from nems_open.paths import REPO_ROOT

# Each module's oracle runs in its own folder (see oracle/gen_oracle.py MODULES).
RUN_DIRS = {"comm": "run", "resd": "run_resd", "ind": "run_ind"}
STATE = REPO_ROOT / "oracle" / "run" / "out" / "state"


def state_dir(module: str = "comm") -> Path:
    return STATE if module == "comm" else REPO_ROOT / "oracle" / RUN_DIRS[module] / "out" / "state"


def available(tag: str, year: int, module: str = "comm") -> bool:
    return (state_dir(module) / tag / str(year) / "index.txt").exists()


def load(tag: str, year: int, module: str = "comm", only=None) -> dict:
    """{name: FArray, or a scalar} for one dump, keyed by lowercase Fortran name.

    only: read just these names (the industrial dumps are large and slow to load whole)."""
    folder = state_dir(module) / tag / str(year)
    out = {}
    for line in (folder / "index.txt").read_text(encoding="latin-1").splitlines():
        parts = line.split()
        if not parts:
            continue
        name, code, rank = parts[0], parts[1], int(parts[2])
        if only is not None and name not in only:
            continue
        bounds = [(int(parts[3 + 2 * k]), int(parts[4 + 2 * k])) for k in range(rank)]
        raw = np.fromfile(folder / f"{name}.bin", dtype=np.dtype(code))
        if rank == 0:
            out[name] = raw[0]
        else:
            shape = tuple(hi - lo + 1 for lo, hi in bounds)
            out[name] = FArray(raw.reshape(shape, order="F"), [lo for lo, _ in bounds])
    return out
