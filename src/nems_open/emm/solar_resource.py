"""Solar resource classes and their depletion (renew.f SolarMisc 3858-4995; SOLAR reads the land, 12603-12680).

Each region has six classes of land (solarin.txt, sq km x PWRDEN), shared by solar thermal (ST), PV and tilted PV with
storage (PT). Classes fill in order, best first (SolarRank_PV, RankVer = 1). ECP sees the first classes with at least the
region's committed PV capacity left: WCAPVEL (the build bound), the cost multiplier inside UPPVCCST, and the capacity
factor that scales WSSPVEL_CF (renew.f then caps each hour at 1). wind_resource.py is the same for wind.

Three things renew.f does that this keeps, because WCAPVEL shows them:
- RNum_ST / PV / PT are set only in the rank routines, which run after the first year's allocation, so what stood in
  2020 (UESTYR) never takes land;
- what is left for commitments restarts from the installed balance before each technology (4233, 4259, 4287), so only
  PT's commitments reduce it;
- a retirement gives back its MW times PWRDEN of land, not over it (4113, 4157, 4200), to every class the loop reaches
  first, and PT asks for its MW of land before taking its MW over PWRDEN (4175).
Capacity is MW, land sq km; arrays are (25 regions, 6 classes).
"""

from functools import lru_cache

import numpy as np

from nems_open.emm import db, plants, regions
from nems_open.paths import INPUT

NUM_R = regions.NUM_EMM
NUM_CLASS = 6
FIRST_YEAR = 1990
EXEC_YEAR = 2020          # UESTYR
TECHS = ("st", "pv", "pt")
FILE_TYPES = {"st": ("STH",), "pt": ("PVT",)}


@lru_cache(maxsize=1)
def inputs() -> dict:
    lines = (INPUT / "rfm" / "solarin.txt").read_text(errors="replace").splitlines()
    k = next(i for i, ln in enumerate(lines) if "Solar Power Resources" in ln)
    land = np.array([[float(x) for x in lines[k + 1 + r].split("!")[0].split()] for r in range(NUM_R)])

    def value(tag):
        i = next(i for i, ln in enumerate(lines) if ln.strip().startswith(tag))
        return [float(x) for x in next(ln for ln in lines[i:] if ln.strip().startswith("'")).split()[1:]]
    density = {p: value(f"%{p.upper()}_PD%")[0] for p in TECHS}
    t = db.table("V_EMM_RENDAT_LTEL")
    mult, ratio = np.ones((NUM_R, 5)), np.zeros((NUM_R, 5))
    for r, lev, tech, c, f in zip(t["EMM_REG"], t["MLPTMX"], t["ITECH"], t["UTCSFC"], t["UTRSFC"]):
        if tech.strip() == "PV" and r <= NUM_R:
            mult[r - 1, lev - 1], ratio[r - 1, lev - 1] = c, f
    wes = (INPUT / "rfm" / "wesarea.txt").read_text(errors="replace").splitlines()
    tol = float(next(wes[i + 1] for i, ln in enumerate(wes) if "Percent Tolerance" in ln))
    return {"land": land, "density": density, "cf": np.array(value("%PV_CF%")), "mult": mult, "ratio": ratio,
            "tolerance": tol}


def deplete(installed: dict, commits: dict, last: int) -> dict:
    """Run the land from EXEC_YEAR to `last`. installed: {st, pv, pt: (25, years) MW at year end, from 1990}; commits: the
    same by online year, one year longer (UADDSTD, UADDPVD, UADDPTD). Returns (25, years) "bound" (MW), "cost" and "cf"."""
    p = inputs()
    land, den = p["land"], p["density"]
    n = last - FIRST_YEAR + 1
    left, cum = land.copy(), np.zeros_like(land)
    out = {k: np.zeros((NUM_R, n)) for k in ("bound", "cost", "cf")}
    for y in range(EXEC_YEAR - FIRST_YEAR, n):
        inc, pv_inc, free = np.zeros_like(land), np.zeros(NUM_R), np.zeros_like(land)
        for r in range(NUM_R):
            for tech in TECHS:
                mw = 0.0 if y == EXEC_YEAR - FIRST_YEAR else installed[tech][r, y] - installed[tech][r, y - 1]
                retired = mw < 0.0               # of the year's change; PT's odd test below can also turn mw negative
                for c in range(NUM_CLASS):
                    if left[r, c] <= 0.0:
                        continue
                    if retired:
                        cum[r, c] += mw
                        left[r, c] -= mw * den[tech]
                        mw = 0.0
                        break
                    need = mw if tech == "pt" else mw / den[tech]
                    if left[r, c] >= need:
                        left[r, c] -= mw / den[tech]
                        cum[r, c] += mw
                        mw = 0.0
                    else:
                        took = left[r, c] * den[tech]
                        cum[r, c] += took
                        mw -= took
                        left[r, c] = 0.0
            for tech in TECHS:
                free[r] = left[r]
                mw = commits[tech][r, y + 1]
                for c in range(NUM_CLASS):
                    took = min(mw, max(free[r, c], 0.0) * den[tech])
                    free[r, c] -= took / den[tech]
                    inc[r, c] += took
                    mw -= took
                    if tech == "pv":
                        pv_inc[r] += took
        top = land * den["st"]
        used = np.divide(cum + inc, top, out=np.zeros_like(top), where=top > 1e-6)
        lt = np.ones_like(top)
        for k in range(5):
            lt = np.where(p["ratio"][:, k][:, None] < used, p["mult"][:, k][:, None], lt)
        for r in range(NUM_R):
            tol = max(5.0, pv_inc[r] * p["tolerance"])
            total = w_lt = w_cf = 0.0
            for c in range(NUM_CLASS):
                if free[r, c] > 0.0:
                    mw = free[r, c] * den["pv"]
                    total += mw
                    w_lt += mw * lt[r, c]
                    w_cf += mw * p["cf"][c]
                if total > tol * (1.0 + 1e-6):        # REAL*4: a class exactly used up by the commitments is a tie
                    break
            out["bound"][r, y] = total
            out["cost"][r, y] = w_lt / total if total > 0 else lt[r, 2]
            out["cf"][r, y] = w_cf / total if total > 0 else p["cf"][2]
    return out


def reference_path(snapshot) -> tuple:
    """(installed, commits) of the reference run, MW."""
    inst = {t: sum(snapshot[f"UDATOUT/ucap{t}{o}"][:NUM_R, :61].astype(float) for o in "un") * 1000.0 for t in TECHS}
    return inst, {t: snapshot[f"UECPOUT/uadd{t}d"][:NUM_R, :62].astype(float) for t in TECHS}


def own_path(snapshot, first: int, solar_gw: dict, builds_gw: dict) -> tuple:
    """The reference path through `first` - 1, then this run's solar: year-end GW by year and PV builds. Solar thermal and
    tilted PV are the reference's at `first` - 1 moved by the plant file; the rest of the solar group is PV."""
    inst, com = reference_path(snapshot)
    inst, com = {t: a.copy() for t, a in inst.items()}, {t: a.copy() for t, a in com.items()}
    f = first - FIRST_YEAR
    for t in TECHS:
        inst[t][:, f:] = 0.0
        com[t][:, f:] = 0.0
    for y, total in solar_gw.items():
        k = y - FIRST_YEAR
        others = np.zeros(NUM_R)
        for t, types in FILE_TYPES.items():
            moved = plants.capacity_gw(y, types) - plants.capacity_gw(first - 1, types)
            inst[t][:, k] = np.maximum(inst[t][:, f - 1] + 1000.0 * moved[:NUM_R], 0.0)
            others += inst[t][:, k]
        inst["pv"][:, k] = np.maximum(total * 1000.0 - others, 0.0)
    for y, v in builds_gw.items():
        com["pv"][:, y - FIRST_YEAR] = v * 1000.0
    return inst, com


def for_build_year(snapshot, year: int, first: int, solar_gw: dict, builds_gw: dict) -> dict:
    """What ECP sees for PV online in `year`: "bound" (GW), and "cost" and "cf", this path's over the reference run's, to
    scale UPPVCCST and WSSPVEL_CF. All are renew.f's of year - 2 (RYR, RENOVR)."""
    own = deplete(*own_path(snapshot, first, solar_gw, builds_gw), year - 2)
    ref = deplete(*reference_path(snapshot), year - 2)
    return {"bound": own["bound"][:, -1] / 1000.0, "cost": own["cost"][:, -1] / ref["cost"][:, -1],
            "cf": own["cf"][:, -1] / ref["cf"][:, -1]}
