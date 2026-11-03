"""Read the oracle's state dumps (oracle/hooks.py) as Fortran-indexed arrays.

Dumps live in one shared cache outside the clones, NEMS_ORACLE_DIR (default ~/dev/oracle-cache),
one folder per module: <cache>/<module>/out/state/<tag>/<year>/. Until a module has been moved
there, the clone's own oracle/run*/out is used. A year folder is either raw (`index.txt` and one
.bin per array, as the Fortran writes it) or packed (`<tag>/<year>.npz`, see scripts/pack_oracle.py).
"""

import os
from pathlib import Path

import numpy as np

from nems_open.fortran_array import FArray
from nems_open.paths import REPO_ROOT

# Each module's oracle runs in its own folder (see oracle/gen_oracle.py MODULES).
RUN_DIRS = {"comm": "run", "resd": "run_resd", "emm": "run_emm", "tran": "run_tran"}
ORACLE_DIR = Path(os.environ.get("NEMS_ORACLE_DIR", Path.home() / "dev" / "oracle-cache"))


def out_dir(module: str = "comm") -> Path:
    """The folder holding this module's oracle output: the shared cache if it has state, else the clone's own."""
    shared = ORACLE_DIR / module / "out"
    local = REPO_ROOT / "oracle" / RUN_DIRS.get(module, f"run_{module}") / "out"
    if (shared / "state").is_dir() or not (local / "state").is_dir():
        return shared
    return local


def _module(module: str, run: str | None) -> str:
    """run: a run folder name ("run_tran") instead of the module name."""
    if run is None:
        return module
    return next(m for m, r in RUN_DIRS.items() if r == run)


def state_dir(module: str = "comm", run: str | None = None) -> Path:
    return out_dir(_module(module, run)) / "state"


def available(tag: str, year: int, module: str = "comm", run: str | None = None) -> bool:
    d = state_dir(module, run) / tag
    return (d / str(year) / "index.txt").exists() or (d / f"{year}.npz").exists()


def _array(raw, rank, bounds):
    if rank == 0:
        return raw[0]
    shape = tuple(hi - lo + 1 for lo, hi in bounds)
    return FArray(raw.reshape(shape, order="F"), [lo for lo, _ in bounds])


def _entries(index_text):
    for line in index_text.splitlines():
        parts = line.split()
        if parts:
            rank = int(parts[2])
            yield parts[0], parts[1], rank, [(int(parts[3 + 2 * k]), int(parts[4 + 2 * k])) for k in range(rank)]


def load(tag: str, year: int, module: str = "comm", run: str | None = None, only=None) -> dict:
    """{name: FArray, or a scalar} for one dump, keyed by lowercase Fortran name.

    only: read just these names (the industrial dumps are large and slow to load whole)."""
    base = state_dir(module, run) / tag
    folder = base / str(year)
    if not (folder / "index.txt").exists() and (base / f"{year}.npz").exists():
        with np.load(base / f"{year}.npz") as z:
            return {name: _array(z[name], rank, bounds)
                    for name, code, rank, bounds in _entries(str(z["__index__"])) if only is None or name in only}
    text = (folder / "index.txt").read_text(encoding="latin-1")
    return {name: _array(np.fromfile(folder / f"{name}.bin", dtype=np.dtype(code)), rank, bounds)
            for name, code, rank, bounds in _entries(text) if only is None or name in only}
