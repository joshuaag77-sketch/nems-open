"""KSTEO and KMINFL: the benchmarking tables COMConsumption reads on its first call (comm.f 7835 to 8010).

KSTEO holds EIA's short-term forecast for the fuels the macro model does not supply (distillate,
residual, LPG, coal, motor gasoline, kerosene): national totals, and regional values when the
indicator is 1. The electricity and gas rows, and the history, come from the restart file, not here.
KMINFL holds the floor adjustment and the minor fuels' logit parameters.
"""

from pathlib import Path

import numpy as np

from nems_open.commercial.inputs import CDM, NUM_DIV, _header, _slashes
from nems_open.fortran_array import FArray

f32 = np.float32
NUM_MAJ_FUEL = 3        # CMnumMajFl
NUM_MIN_FUEL = 5        # CMnumMinFl
NUM_FUEL = NUM_MAJ_FUEL + NUM_MIN_FUEL
MSEDYR = 34             # historical SEDS years
LAST_YR_2PCT = 38       # comvars LastYr2pct: STEO years read


def read_ksteo(cdm_dir: Path = CDM) -> dict:
    """FlagRegSTEO (f), STEOdat (f, y - MSEDYR) and the regional CMSEDS (f, r, y), fuels 3 to 8.

    A row with fewer numbers than years leaves the rest zero: the label that follows ends the read.
    """
    nyears = LAST_YR_2PCT - MSEDYR
    flag = FArray.zeros([(1, NUM_FUEL)])
    steodat = FArray.zeros([(1, NUM_FUEL), (1, LAST_YR_2PCT)])
    cmseds = FArray.zeros([(1, NUM_FUEL), (1, NUM_DIV), (1, LAST_YR_2PCT)])
    rd = _header(Path(cdm_dir) / "ksteo.txt")
    for f, v in zip(range(3, NUM_FUEL + 1), rd.read(NUM_FUEL - 2, int)):
        flag[f] = v
    _slashes(rd, 2)
    for f in range(3, NUM_FUEL + 1):
        for y, v in enumerate(rd.read(nyears, partial=True), start=1):
            steodat[f, y] = f32(v)
    _slashes(rd, 1)
    for f in range(3, NUM_FUEL + 1):
        for r in range(1, NUM_DIV + 1):
            try:
                row = rd.read(nyears, partial=True)
            except EOFError:                     # END=284: the file may stop before the last fuels
                continue
            for y, v in enumerate(row, start=MSEDYR + 1):
                cmseds[f, r, y] = f32(v)
    return {"flagregsteo": flag, "steodat": steodat, "cmseds": cmseds}


def read_kminfl(cdm_dir: Path = CDM) -> dict:
    """FloorAdj (r) and the minor fuels' MinFuelAlpha, MinFuelBeta (r, f)."""
    floor_adj = FArray.zeros([(1, NUM_DIV)])
    alpha = FArray(np.ones((NUM_DIV, NUM_MIN_FUEL), dtype=f32), [1, 1])   # EXP(0.)
    beta = FArray.zeros([(1, NUM_DIV), (1, NUM_MIN_FUEL)])
    rd = _header(Path(cdm_dir) / "kminfl.txt")
    for r, v in enumerate(rd.read(NUM_DIV), start=1):
        floor_adj[r] = f32(v)
    _slashes(rd, 2)
    for r in range(1, NUM_DIV + 1):
        for f in range(1, NUM_MIN_FUEL + 1):
            a, b = rd.read(2)
            alpha[r, f], beta[r, f] = f32(a), f32(b)
    return {"flooradj": floor_adj, "minfuelalpha": alpha, "minfuelbeta": beta}
