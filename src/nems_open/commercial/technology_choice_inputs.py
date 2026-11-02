"""First call of COMTechnologyChoice (comm.f): the file reads and one-time edits.

Reads behaviour rule shares, efficiency growth, capacity factors and consumer time
preference groups, normalises them, and takes the cooling cost off heat pump capital
costs. The technology table itself (KTEK) is read earlier, in the service demand first
call; see `ktek.py`.

Names follow the Fortran so each step can be checked against comm.f.
"""

from pathlib import Path

import numpy as np

from nems_open.commercial.inputs import (
    CDM, CM_FIRST_YR, NUM_BLDG, NUM_DECISION, NUM_DIV, NUM_MAJ_SERV, NUM_PREF, NUM_RULE, NUM_SERV,
    _header, _slashes,
)
from nems_open.fortran_array import FArray

f32 = np.float32

LAST_YEAR = 61  # LASTYR for AEO2026
EPSILON = f32(0.001)  # the Epsilon DATA statement in COMTechnologyChoice


def read_kparm_cooling_index(cdm_dir: Path = CDM) -> int:
    """CoolingTechIndexHP from kparm.txt: the cooling technology a heat pump's cooling cost is taken from.

    The third value in the file; COMM reads the others (debug switches, report option).
    """
    rd = _header(Path(cdm_dir) / "kparm.txt")
    rd.read(5)
    _slashes(rd, 1)
    rd.read(1)
    _slashes(rd, 1)
    return int(rd.read(1)[0])


def read_kbehav(cdm_dir: Path = CDM) -> FArray:
    """BehaviorShare (s, b, d, u): share of buyers following each decision rule.

    d is the decision (new, replacement, retrofit) and u the rule (least cost, same fuel,
    same technology). Shares outside 0 to 1 are zeroed; a row that sums to 0 becomes all
    "same technology"; a row that does not sum to 1 is divided by its sum.
    """
    bs = FArray.zeros([(1, NUM_SERV), (1, NUM_BLDG), (1, NUM_DECISION), (1, NUM_RULE)])
    rd = _header(Path(cdm_dir) / "kbehav.txt")
    try:
        for s in range(1, NUM_MAJ_SERV + 1):
            for b in range(1, NUM_BLDG + 1):
                vals = rd.read(NUM_RULE * NUM_DECISION)
                if vals is None:
                    continue
                k = 0
                for d in range(1, NUM_DECISION + 1):
                    for u in range(1, NUM_RULE + 1):
                        bs[s, b, d, u] = f32(vals[k])
                        k += 1
                for u in range(1, NUM_RULE + 1):
                    for d in range(1, NUM_DECISION + 1):
                        if bs[s, b, d, u] < 0.0 or bs[s, b, d, u] > 1.0:
                            bs[s, b, d, u] = 0.0
    except EOFError:
        pass
    for s in range(1, NUM_MAJ_SERV + 1):
        for b in range(1, NUM_BLDG + 1):
            for d in range(1, NUM_DECISION + 1):
                total = f32(0.0)
                for u in range(1, NUM_RULE + 1):
                    total = f32(total + bs[s, b, d, u])
                if total == 0.0:
                    bs[s, b, d, 3] = 1.0
                elif total > f32(1.0) + EPSILON or total < f32(1.0) - EPSILON:
                    for u in range(1, NUM_RULE + 1):
                        bs[s, b, d, u] = f32(bs[s, b, d, u] / total)
    return bs


def read_kdeleff(cdm_dir: Path = CDM) -> FArray:
    """EffGrowthRate (s): yearly efficiency growth for minor services (CEffGrowth is a copy)."""
    out = FArray.zeros([(1, NUM_SERV)])
    rd = _header(Path(cdm_dir) / "kdeleff.txt")
    try:
        vals = rd.read(NUM_SERV)
        if vals is not None:
            out[:] = np.array(vals, dtype=f32)
    except EOFError:
        pass
    return out


def read_kcapfac(cdm_dir: Path = CDM) -> FArray:
    """CapacityFactor (r, b, s); values outside 0 to 1 are zeroed."""
    out = FArray.zeros([(1, NUM_DIV), (1, NUM_BLDG), (1, NUM_SERV)])
    rd = _header(Path(cdm_dir) / "kcapfac.txt")
    try:
        for r in range(1, NUM_DIV + 1):
            for b in range(1, NUM_BLDG + 1):
                vals = rd.read(NUM_SERV)
                if vals is None:
                    continue
                out[r, b, :] = np.array(vals, dtype=f32)
                for s in range(1, NUM_SERV + 1):
                    if out[r, b, s] < 0.0 or out[r, b, s] > 1.0:
                        out[r, b, s] = 0.0
    except EOFError:
        pass
    return out


def read_kprem(cdm_dir: Path = CDM, nrg2007: int = 1, stimulus: int = 1):
    """(TimePrefProp, TimePrefPrem) (s, p, y): consumer time preference groups.

    TimePrefProp is the share of buyers in group p and TimePrefPrem the interest rate
    premium they add. The switches undo the 2007 energy bill lighting rule (nrg2007=0)
    and the 2009 stimulus spending (stimulus=0) for the years they affected.
    """
    shape = [(1, NUM_MAJ_SERV), (1, NUM_PREF), (1, LAST_YEAR)]
    prop, prem = FArray.zeros(shape), FArray.zeros(shape)
    rd = _header(Path(cdm_dir) / "kprem.txt")
    try:
        for y in range(1, LAST_YEAR + 1):
            for s in range(1, NUM_MAJ_SERV + 1):
                for p in range(1, NUM_PREF + 1):
                    vals = rd.read(2)
                    if vals is not None:
                        prop[s, p, y], prem[s, p, y] = f32(vals[0]), f32(vals[1])
    except EOFError:
        pass

    for y in range(CM_FIRST_YR, LAST_YEAR + 1):
        for s in range(1, NUM_MAJ_SERV + 1):
            total = f32(0.0)
            if stimulus == 0:
                if 20 < y < 25:
                    for p in range(1, NUM_PREF + 1):
                        prop[s, p, y] = prop[s, p, y - 1]
                if nrg2007 == 0 and s == 6 and y > 19:
                    prop[s, 5, y], prop[s, 6, y], prop[s, 7, y] = f32(0.100), f32(0.008), f32(0.002)
            elif s == 6 and y > 19 and nrg2007 == 0 and (y == 20 or y > 24):
                prop[s, 5, y], prop[s, 6, y], prop[s, 7, y] = f32(0.100), f32(0.008), f32(0.002)
            for p in range(1, NUM_PREF + 1):
                if prop[s, p, y] < 0.0 or prop[s, p, y] > 1.0:
                    prop[s, p, y] = 0.0
                total = f32(total + prop[s, p, y])
            if total == 0.0:
                prop[s, 1, y] = 1.0
                prem[s, 1, y] = 0.0
            elif total > f32(1.0) + EPSILON or total < f32(1.0) - EPSILON:
                for p in range(1, NUM_PREF + 1):
                    prop[s, p, y] = f32(prop[s, p, y] / total)
    return prop, prem


def heat_pump_cost_edit(tech_cost: FArray, techby_service: FArray, techby_model: FArray,
                        num_eq_v: FArray, cooling_tech_index_hp: int) -> None:
    """Heat pump capital cost covers only what heating adds to the cost of comparable cooling.

    Takes the cooling technology's capital cost off each defined heating heat pump
    (technologies 1 to 5). Changes `tech_cost` in place.
    """
    for t in range(1, 6):
        if techby_service[1, t] == 1:
            for v in range(1, int(num_eq_v[t]) + 1):
                for r in range(1, NUM_DIV + 1):
                    if techby_model[t, v] == 1:
                        tech_cost[r, t, v, 1] = f32(tech_cost[r, t, v, 1] - tech_cost[r, cooling_tech_index_hp, v, 1])
