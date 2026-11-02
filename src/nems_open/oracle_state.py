"""Read the oracle's state dumps (oracle/hooks.py, oracle/hooks_tran.py) as Fortran-indexed arrays.

Each module's oracle has its own run folder: run (commercial), run_tran (transportation).
"""

from pathlib import Path

import numpy as np

from nems_open.fortran_array import FArray
from nems_open.paths import REPO_ROOT

ORACLE = REPO_ROOT / "oracle"
STATE = ORACLE / "run" / "out" / "state"


def _folder(tag: str, year: int, run: str | None) -> Path:
    base = STATE if run is None else ORACLE / run / "out" / "state"
    return base / tag / str(year)


def available(tag: str, year: int, run: str | None = None) -> bool:
    return (_folder(tag, year, run) / "index.txt").exists()


def load(tag: str, year: int, run: str | None = None) -> dict:
    """{name: FArray, or a scalar} for one dump, keyed by lowercase Fortran name."""
    folder = _folder(tag, year, run)
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
