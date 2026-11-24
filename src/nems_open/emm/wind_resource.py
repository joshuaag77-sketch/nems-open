"""Onshore wind resource classes and their depletion (renew.f WindIn3, WindMisc3 and WindRank3).

Each region has four resource classes (wesarea.txt windy land x PWRDEN). Capacity fills them in the order of their
annual cost, and each class's capital cost rises by a long-term multiplier (UTCSFC, NEMS_INPUT.db V_EMM_RENDAT_LTEL)
as it is used up. What ECP sees for a year is the cheapest classes with at least the region's committed capacity
left: their capacity (ConsCap: WCAWIEL, the build bound), their capacity-weighted cost multiplier (ConsLT, inside
UPWNCCST) and their capacity factor (ConsCF, the level of WSFWIEL_CF).

Along EIA's own build path this gives WCAWIEL in every region and year from 2027 (tests/test_wind_resource.py). On
another path the resource follows that path's builds. Only the buffer zone the input has (zone 1) is kept.
Capacity is MW; arrays are (25 regions, 4 classes).
"""

from functools import lru_cache

import numpy as np

from nems_open.emm import db, regions
from nems_open.paths import INPUT

NUM_R = regions.NUM_EMM
FIRST_YEAR = 1990
EXEC_YEAR = 2020          # UESTYR (emmcntl.txt %EXEC YEARS%): ranks are the class order before it, by cost from it
LEAD = 1                  # UPPLYR(WN): what is committed in a year's solve is online the next


@lru_cache(maxsize=1)
def inputs() -> dict:
    lines = (INPUT / "rfm" / "wesarea.txt").read_text(errors="replace").splitlines()
    land = np.array([[float(x) for x in lines[3 + r].split("!")[0].split()] for r in range(NUM_R)])

    def value(tag):       # the first (onshore) line of each tag
        return [float(x) for x in next(ln for ln in lines if ln.strip().startswith("'" + tag + "'")).split()[1:]]
    t = db.table("V_EMM_RENDAT_LTEL")
    mult, ratio = np.ones((NUM_R, 5)), np.zeros((NUM_R, 5))
    for r, lev, tech, c, f in zip(t["EMM_REG"], t["MLPTMX"], t["ITECH"], t["UTCSFC"], t["UTRSFC"]):
        if tech.strip() == "WIND" and r <= NUM_R:
            mult[r - 1, lev - 1], ratio[r - 1, lev - 1] = c, f
    tol = float(next(lines[k + 1] for k, ln in enumerate(lines) if "Percent Tolerance" in ln))
    return {"max_mw": land * value("PWRDEN")[0], "cf_ult": np.array(value("CFULT")), "cf_at": value("CFATX")[0],
            "fixed_gw": value("FIXEDX")[0], "mult": mult, "ratio": ratio, "tolerance": tol}


def class_cf(national_mw: float) -> np.ndarray:
    """CF(year, class): CFULT x exp(FIXEDX ln(CFATX / CFULT(1)) / national GW) (WindMisc3, OVERRIDECF = 1)."""
    p = inputs()
    slope = p["fixed_gw"] * np.log(p["cf_at"] / p["cf_ult"][0])
    return p["cf_ult"] * np.exp(slope / max(national_mw / 1000.0, p["fixed_gw"]))


def _fill(room, order, mw):
    """Take `mw` out of `room` (4,) in class order; returns what each class gave."""
    used = np.zeros(4)
    for c in order:
        if room[c] > 0.0:
            used[c] = min(mw, room[c])
            room[c] -= used[c]
            mw -= used[c]
    return used


def deplete(installed: np.ndarray, commits: np.ndarray, fom_ratio: np.ndarray, last: int) -> dict:
    """Run the resource from 1990 to `last`. installed: (25, years) onshore MW at each year end, from 1990. commits:
    (25, years + 1) MW of model builds by online year (UADDWND). fom_ratio: (25,) fixed O&M over the annual capital
    charge, which only orders the classes. Returns arrays (25, years) "bound" (MW), "cost" and "cf"."""
    p = inputs()
    top = p["max_mw"]
    n = last - FIRST_YEAR + 1
    strict = np.tile(np.arange(4), (NUM_R, 1))
    left, cum = top.copy(), np.zeros_like(top)
    ranks = {}
    out = {k: np.zeros((NUM_R, n)) for k in ("bound", "cost", "cf")}
    before = np.zeros(NUM_R)
    for y in range(n):
        added = installed[:, y] - before
        before = installed[:, y]
        free, inc = np.zeros_like(top), np.zeros_like(top)
        for r in range(NUM_R):
            order = ranks.get(y - LEAD - 1, strict)[r]
            if added[r] >= 0.0:
                cum[r] += _fill(left[r], order, added[r])
            else:                             # a retirement goes back to the first class with room
                c = next((c for c in order if left[r, c] > 0.0), None)
                if c is not None:
                    left[r, c] -= added[r]
                    cum[r, c] += added[r]
            free[r] = left[r]
            for i in range(LEAD, 0, -1):
                inc[r] += _fill(free[r], ranks.get(y - i, strict)[r], commits[r, y - (i - 1) + LEAD])
        used = np.divide(cum + inc, top, out=np.zeros_like(top), where=top > 1e-6)
        lt = np.ones_like(top)
        for k in range(5):
            lt = np.where(p["ratio"][:, k][:, None] < used, p["mult"][:, k][:, None], lt)
        cf = class_cf(installed[:, y].sum())
        cost = (lt + fom_ratio[:, None]) / cf
        ranks[y] = strict if y < EXEC_YEAR - FIRST_YEAR else np.argsort(cost, axis=1, kind="stable")
        for r in range(NUM_R):
            tol = max(5.0, inc[r].sum() * p["tolerance"])
            total = w_lt = w_cf = 0.0
            for c in ranks[y][r]:
                if free[r, c] > 0.0:
                    total += free[r, c]
                    w_lt += free[r, c] * lt[r, c]
                    w_cf += free[r, c] * cf[c]
                if total > tol:
                    break
            out["bound"][r, y] = total
            out["cost"][r, y] = w_lt / total if total > 0 else lt[r, 2]
            out["cf"][r, y] = w_cf / total if total > 0 else cf[2]
    return out


def reference_path(snapshot) -> tuple:
    """(installed, commits) of the reference run: UCAPWNR and UADDWND, MW."""
    return (snapshot["UDATOUT/ucapwnr"][:NUM_R, :61].astype(float), snapshot["UECPOUT/uaddwnd"][:NUM_R, :62].astype(float))


def own_path(snapshot, first: int, installed_gw: dict, builds_gw: dict) -> tuple:
    """The reference path through `first` - 1, then this run's onshore year-end GW and builds by year."""
    inst, com = (a.copy() for a in reference_path(snapshot))
    inst[:, first - FIRST_YEAR:] = 0.0
    com[:, first - FIRST_YEAR:] = 0.0
    for y, v in installed_gw.items():
        inst[:, y - FIRST_YEAR] = np.maximum(v, 0.0) * 1000.0
    for y, v in builds_gw.items():
        com[:, y - FIRST_YEAR] = v * 1000.0
    return inst, com


def fom_ratio(snapshot, year: int = 2030) -> np.ndarray:
    """Fixed O&M over the annual capital charge of a new wind plant, (25,). It only orders the classes.
    WindRank3's charge is levelized in constant dollars (EP$LGNP's PVGNP), so the annuity is at the real rate. Its
    construction interest and tax terms (EPINCST, EPCNBLD) are left out: the bound is the same for any ratio from
    1.15 to 1.6 times the nominal one in every region and year."""
    from nems_open.emm import capacity, technology
    k = technology.ecp_codes().index("WN")
    t = technology.type_parameters()
    cost = snapshot["UECPOUT/upwnccst"][:NUM_R, year - FIRST_YEAR].astype(float)
    ref = deplete(*reference_path(snapshot), np.full(NUM_R, 0.28), year - 2)["cost"][:, -1]
    gdp = snapshot["MACOUT/mc_jpgdp"].astype(float)
    i = year - FIRST_YEAR
    real = (1.0 + capacity.discount_rate(snapshot, year)) / (gdp[i] / gdp[i - 10]) ** 0.1 - 1.0
    return float(t["fom"][k]) / (cost / ref * capacity._crf(real, t["economic_life"][k]))


def for_build_year(snapshot, year: int, first: int, installed_gw: dict, builds_gw: dict) -> dict:
    """What ECP sees for wind online in `year`: "bound" (GW), and "cost" and "cf", this path's over the reference
    run's, to scale the reference run's UPWNCCST and WSFWIEL_CF. All are renew.f's of year - 2 (RYR, RENOVR)."""
    ratio = fom_ratio(snapshot)
    last = year - 2
    own = deplete(*own_path(snapshot, first, installed_gw, builds_gw), ratio, last)
    ref = deplete(*reference_path(snapshot), ratio, last)
    return {"bound": own["bound"][:, -1] / 1000.0, "cost": own["cost"][:, -1] / ref["cost"][:, -1],
            "cf": own["cf"][:, -1] / ref["cf"][:, -1]}
