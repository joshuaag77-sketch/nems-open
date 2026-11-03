"""TRAN's state before its first call (1995), built from EIA's files, no oracle dump.

As the oracle does (oracle/driver_tran.f90): every variable in state_layout.json starts
at zero (static storage), COMMON variables take their values from EIA's restart file,
the module variables with DATA statements take those values, and STEO's variables
come from steovars.csv. Then TRAN's first call reads its input files
(readers.first_call). `run(last_year)` calls TRAN from 1995 on, three times a year,
like the oracle's driver.

    s, carry = run(2020)      # the state at the top of 2020's first iteration
"""

import json
from pathlib import Path

import numpy as np

from nems_open.fortran_array import FArray
from nems_open.snapshot import Snapshot
from nems_open.transportation import readers, tran

LAYOUT = json.loads(Path(__file__).with_name("state_layout.json").read_text())
FIRST_YEAR = 1995
ITERATIONS = 3          # NEMS calls TRAN three times a year (see oracle/driver_tran.f90)
MNUMYR, IJUMPYR = 61, 61

# DATA statements in MODULE T_, F_ and AIRMOD.
DATA = {
    "grpmap": [1, 1, 1, 1, 1, 2, 2, 2, 2, 2, 2],
    "f_p219map": [1, 2, 1, 2, 2, 2, 3, 3, 5, 6, 7, 4, 8, 9, 10, 11, 12, 13, 14],
    "f_sc19map": [4, 4, 1, 1, 2, 2, 2, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3, 3],
    "f_p24map": [1, 2, 3, 3, 3, 3, 3, 4, 4, 4, 4, 4, 4, 4],
    "f_techrptmap": [1, 1, 1, 1, 2, 2, 2, 3, 4, 4, 4, 3, 4, 4, 4, 5, 5, 5, 5],
    "f_gvwrp2map": [2, 2, 3, 3, 4, 5, 6, 7, 7, 7, 7, 8, 8, 8, 8, 8, 8, 8, 9],
    "f_vocornomap": [1, 2, 1, 2, 2, 2, 2, 2, 1, 1, 1, 2, 1, 1, 1, 1, 1, 1, 1],
    "f_survmap": [1, 2, 3, 4, 5, 6, 7, 9, 8, 8, 8, 11, 10, 10, 10, 10, 10, 10, 10],
    "f_cltmap": [2, 1, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12],
    "f_cltmap2": [2, 1, 3, 4, 5, 6, 7],
}
TEXT_DATA = {
    "a_reg_def": ["USA", "CAN", "MXC", "EUR", "JPN", "ANZ", "SKO", "RUS", "URA", "CHI", "IND", "OAS", "MID", "AFR",
                  "BRZ", "CSA"],
    "a_reg_atyp": ["NB", "WB", "RJ"],
}
# STEO variables TRANEASY copies (STEOBLOCK, not in the restart file).
STEO = ("mgtcbus", "jftcbus", "datcpus", "dfepdel", "rftcbus")


def zeros() -> dict:
    s = {}
    for name, d in LAYOUT.items():
        dt = np.dtype(d["dtype"])
        if "shape" in d:
            s[name] = FArray(np.zeros(d["shape"], dtype=dt), d["lb"])
        else:
            s[name] = dt.type(0)
    return s


def _load(dst, src: np.ndarray):
    """The oracle's load_restart: the restart array's values fill the variable in memory order."""
    if not isinstance(dst, FArray):
        return np.asarray(src).reshape(-1)[0].astype(np.asarray(dst).dtype)
    if src.shape == dst.a.shape:
        dst.a[...] = src.astype(dst.a.dtype)
    else:
        n = min(flat.size, dst.a.size)
        f = dst.a.reshape(-1, order="F").copy()
        f[:n] = np.asfortranarray(src).reshape(-1, order="F")[:n]
        dst.a[...] = f.reshape(dst.a.shape, order="F")
    return dst


def initial_state(snapshot: Snapshot | None = None, traneff: int = 0):
    """(state, carry) just before TRAN's first call."""
    snap = snapshot or Snapshot()
    names = set(snap.names())
    s = zeros()
    for name, d in LAYOUT.items():
        src = d.get("restart")
        if src is None:
            continue
        key = next((k for k in (src, src.upper(), src.split("/")[0] + "/" + src.split("/")[1].upper()) if k in names), None)
        if key is None:
            continue
        a = snap[key]
        if a.dtype.kind not in "iuf":
            continue
        s[name] = _load(s[name], a)
    for name, vals in DATA.items():
        if name in s:
            s[name].a[...] = np.array(vals, dtype=s[name].a.dtype)
    for name, vals in TEXT_DATA.items():
        if name in s:
            tran.text(s[name], vals)
    from nems_open import steo
    v = steo.load()
    for k in STEO:
        s[k] = FArray(np.asarray(v[k], dtype=np.float32))
    s["ijumpyr"] = type(s["ijumpyr"])(IJUMPYR) if "ijumpyr" in s else IJUMPYR
    readers.first_call(s, traneff=traneff)
    return s, empty_carry(s)


def empty_carry(s: dict) -> tran.Carry:
    """The routines' saved local arrays before the first call: all zero."""
    c = tran.Carry()
    c["treport"] = {k: np.zeros(17, dtype=np.float32) for k in ("cmpg_2", "tmpg_2", "lmpg_2")}
    shapes = json.loads(Path(__file__).with_name("carry_layout.json").read_text())
    for routine, arrays in shapes.items():
        c[routine] = {k: FArray(np.zeros(d["shape"], dtype=np.dtype(d["dtype"])), d["lb"]) for k, d in arrays.items()}
    c["tmpgnew"]["sta_rat_base"] = np.zeros(8, dtype=np.float32)     # TALT2's STA_RAT_BASE(MAXFUEL)
    return c


def run(last_year: int, snapshot: Snapshot | None = None, first_year: int = FIRST_YEAR, state=None):
    """TRAN from 1995 (or from `state` at first_year) to the top of last_year's first iteration."""
    s, carry = state if state is not None else initial_state(snapshot)
    for year in range(first_year, last_year):
        for itr in range(1, ITERATIONS + 1):
            call(s, carry, year, itr)
    return s, carry


def call(s: dict, carry, year: int, itr: int) -> None:
    """One call of TRAN, as NEMS makes it."""
    s["curcalyr"] = type(s["curcalyr"])(year)
    s["curiyr"] = type(s["curiyr"])(year - 1989)
    s["curitr"] = type(s["curitr"])(itr)
    fcrl = 1 if itr == ITERATIONS else 0
    for k in ("fcrl", "ncrl"):
        if k in s:
            s[k] = type(s[k])(fcrl)
    tran.tran(s, carry)
