"""EIA's short-term forecast variables (STEO_VAR_COM), loaded the way NEMS loads them.

The restart file does not hold STEO_VAR_COM; NEMS rebuilds it at startup from input/steovars.csv with
models/main/steo_load.py (EIA's code, imported from the upstream checkout, not copied here). That loader
runs against a stand-in for PyFiler whose named STEO arrays are views into one flat EQ_STEO_VARS buffer
in COMMON order, as the Fortran EQUIVALENCE lays them out.

    steo.load()["exccpus"]   # a 61-year float32 array (index 0 = 1990)
"""

import os
import re
import shutil
import sys
import tempfile
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from nems_open.paths import UPSTREAM

MNUMYR = 61


def block_order(steoblock: Path):
    text = steoblock.read_text(encoding="latin-1")
    stmts, buf = [], ""
    for line in text.splitlines():
        line = line.split("!", 1)[0].rstrip()
        if line.endswith("&"):
            buf += line[:-1] + " "
            continue
        stmts.append((buf + line).strip())
        buf = ""
    nvars = int(re.search(r"PARAMETER\s*\(\s*STEOVR\s*=\s*(\d+)", text, re.I).group(1))
    for st in stmts:
        m = re.match(r"common\s*/\s*STEO_VAR_COM\s*/(.*)", st, re.I)
        if m:
            names = [v.strip().lower() for v in m.group(1).split(",") if v.strip()]
            return names, nvars
    raise ValueError("STEO_VAR_COM not found")


class SteoBlock:
    """PyFiler's 'other' module, reduced to the STEO block."""

    def __init__(self, names, nvars):
        object.__setattr__(self, "eq_steo_vars", np.zeros(nvars * MNUMYR, dtype=np.float32))
        object.__setattr__(self, "steovr", nvars)
        views = {n: self.eq_steo_vars[i * MNUMYR:(i + 1) * MNUMYR] for i, n in enumerate(names)}
        object.__setattr__(self, "_views", views)

    def __getattr__(self, name):
        try:
            return self._views[name]
        except KeyError:
            raise AttributeError(f"STEO loader touched {name}, which is not in STEO_VAR_COM")


@lru_cache(maxsize=1)
def load(upstream: Path = UPSTREAM) -> dict:
    """{lower-case name: float32 array of MNUMYR years} for every STEO variable."""
    upstream = Path(upstream)
    names, nvars = block_order(upstream / "includes" / "steoblock")
    if len(names) != nvars:
        raise ValueError(f"STEO_VAR_COM has {len(names)} members, STEOVR={nvars}")
    other = SteoBlock(names, nvars)
    pyfiler = SimpleNamespace(ncntrl=SimpleNamespace(exc=0, exg=0), other=other, utils=SimpleNamespace(baseyr=1990))
    sys.path.insert(0, str(upstream / "models" / "main"))
    try:
        import steo_load
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "input").mkdir()
            for f in ("steovars.csv", "steolist.txt"):
                shutil.copy(upstream / "input" / f, Path(tmp) / "input" / f)
            cwd = Path.cwd()
            os.chdir(tmp)
            try:
                steo_load.read_all_steo_vars(None, pyfiler)
            finally:
                os.chdir(cwd)
    finally:
        sys.path.remove(str(upstream / "models" / "main"))
    return {n: other.eq_steo_vars[i * MNUMYR:(i + 1) * MNUMYR].copy() for i, n in enumerate(names)}
