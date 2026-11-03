"""RESD's state before its first call (2020, first iteration), built from EIA's input files.

Every array RESD works on, declared as in state_layout.json (EIA's declarations, from the
residential oracle's dumps), starts at zero as the Fortran's static storage does. Then:

  restart    arrays other modules own (prices, macro drivers, SEDS history, EV charging,
             renewables built elsewhere) come from the restart file through `Inputs`; the STEO
             variables from input/steovars.csv, as NEMS builds them at startup
  files      the first-call readers (inputs.py) fill the input tables
  computed   everything RESD computes itself stays zero until the chain runs
"""

import json
from pathlib import Path

import numpy as np

from nems_open.commercial.initial_state import put
from nems_open.fortran_array import FArray

LAYOUT = json.loads((Path(__file__).with_name("state_layout.json")).read_text())


def zeros() -> dict:
    """Every array in the layout, zeroed. Scalars are numpy scalars."""
    s = {}
    for name, d in LAYOUT.items():
        dt = np.dtype(d["dtype"])
        if "shape" in d:
            s[name] = FArray(np.zeros(d["shape"], dtype=dt), d["lb"])
        else:
            s[name] = dt.type(0)
    return s


# RESD's own output blocks: the oracle does not load them from the restart file, so every
# value in them is computed (and QBLK's residential rows, Q*RS).
OWN_BLOCKS = ("RESDREP", "RSCON", "RSEFF")


def _own(block: str, var: str) -> bool:
    return block in OWN_BLOCKS or (block in ("QBLK", "QMORE") and var.endswith("rs"))


def restart_arrays(s: dict, inputs) -> list:
    """Copy into s every layout array the restart file holds outside RESD's own blocks (what the
    oracle loads before RESD's first call). Inputs the runner overrides go through inputs.apply.
    Returns the names held in more than one block, which are left for the caller."""
    from nems_open.run_demand import EQUIVALENCED
    snap = inputs.snapshot
    blocks = {}
    for full in snap.names():
        block, _, var = full.partition("/")
        var = var.lower()
        if var in s and not _own(block, var):
            blocks.setdefault(var, []).append(block)
    ambiguous = []
    for var, bl in blocks.items():
        if var in inputs.by_var or var in EQUIVALENCED:
            continue
        if len(bl) != 1:
            ambiguous.append((var, bl))
            continue
        src = snap[f"{bl[0]}/{var}"]
        dst = s[var]
        if isinstance(dst, FArray) and src.ndim != dst.a.ndim:
            ambiguous.append((var, bl))  # same name, a different array (RESD's own local)
            continue
        put(s, var, src)
    inputs.apply(s)
    steo_arrays(s)
    return ambiguous


def steo_arrays(s: dict) -> None:
    """The short-term forecast variables RESD reads (STEO_VAR_COM): not in the restart file;
    NEMS builds them at startup from input/steovars.csv (nems_open.steo)."""
    from nems_open import steo
    v = steo.load()
    for name in s:
        if name in v and isinstance(s[name], FArray):
            put(s, name, v[name])


def initial_state(inputs=None) -> dict:
    """The state RESD holds just after its first-call readers (2020, first iteration)."""
    from nems_open.residential import inputs as readers
    from nems_open.run_demand import Inputs
    inputs = inputs or Inputs()
    s = zeros()
    restart_arrays(s, inputs)
    readers.first_call(s, inputs)
    return s


def base_year(s: dict) -> None:
    """RESD in the RECS year (2020), both iterations: RDISTGEN's first call, then RDPR and the
    base-year chain EXCONS, RSBENCH, NEMSCN, RESDRP (resd.f lines 488-494)."""
    from nems_open.residential.distgen import rdistgen
    from nems_open.residential.housing import rdpr
    from nems_open.residential.totals import excons, nemscn, resdrp, rsbench
    for itr in (1, 2):
        s["curcalyr"], s["curiyr"], s["curitr"] = 2020, 31, itr
        if itr == 1:
            rdistgen(s)
        rdpr(s)
        excons(s)
        rsbench(s)
        nemscn(s)
        resdrp(s)


__all__ = ["LAYOUT", "zeros", "put", "initial_state", "base_year"]
