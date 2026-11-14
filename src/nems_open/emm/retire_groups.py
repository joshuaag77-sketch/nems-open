"""ECP's retirement groups (EPGCAP, EPGFOM), rebuilt from the plant file and our own dispatch prices.

How EIA builds them (udat.f, ECP setup, called every year before the capacity LP):

1. Lines 7395-7480. Every existing plant group that could retire (in service, no dated retirement,
   owner 1 to 3, not must-run, its ECP type has retirement groups) gets a value per kW from last
   year's EFD dispatch:  RET_VAL = revenue (less the reserve-margin payment) - variable cost - fixed
   cost - emission charges. The type's national minimum and maximum RET_VAL are kept, and the
   region's capacity-weighted average of revenue - variable cost (RET_AVG).
2. Lines 10820-10880. Units are sorted by RET_VAL. The range [min, max] is cut at the cumulative
   RET_PCT shares (emmcntl.txt %RET GRPS%: 5, 45, 40, 10 percent of the RANGE, not of capacity), and
   each slice in a region is one retirement group: EPGCAP is its capacity, EPGFOM its capacity-weighted
   (RET_AVG - RET_VAL), which is the fixed cost plus how far the group's operating margin falls short of
   the type's regional average. ECP's LP dispatches a type at its average cost, so EPGFOM is what makes
   a group of poor units cheaper to lose than the average.
3. uecp.f EP$BDSP / EP$BRNW: keeping group k costs EPGFOM (year 1 sunk), times (1 - hurdle), never below 0.

The EFD outputs behind step 1 (ULREVS, ULVCST, ULFCST and so on) are not in the restart. Here the
revenue comes from our own capacity LP: the energy prices (duals of the regional balance) of the year
before, which leave out the reserve-margin payment just as udat.f takes it out. A unit earns
(price - its own cost) in every slice where that is positive, times its availability. Its cost is its own
heat rate (plant file THRATE) at the region's fuel price, plus its own variable O&M (T_VOM). Fixed cost is
udat.f's RET_FOM: T_FOM + T_CAPAD + the age adder (%XTRA OandM% / %XTRA Opt 2%). Emission charges are zero
in the reference case (no carbon price); a case carbon price is added to the unit's cost.

Money: 1987 dollars per kW-year. Capacity: GW.
"""

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from nems_open.emm import db, dispatch, plants, regions
from nems_open.paths import INPUT

NUM_R = regions.NUM_EMM
NUM_GROUPS = 4
CO2_TONS_PER_MMBTU = {"coal": 0.0954, "gas": 0.0532, "oil": 0.0749}


def _table(name: str) -> list[list[str]]:
    """Rows of an emmcntl.txt table (%NAME%), comments dropped, split on whitespace."""
    lines = (INPUT / "emm" / "emmcntl.txt").read_text(encoding="latin-1").splitlines()
    start = next(i for i, l in enumerate(lines) if l.strip().startswith(f"%{name}"))
    rows = []
    for l in lines[start + 1:]:
        s = l.strip()
        if s.startswith("%"):
            break
        if not s or s.startswith("#"):
            continue
        rows.append(s.split())
    return rows


@lru_cache(maxsize=1)
def retirement_shares() -> dict:
    """ECP type code -> (number of groups, shares of the margin range), from %RET GRPS %."""
    out = {}
    for r in _table("RET GRPS"):
        code = r[0].strip("'")
        out[code] = (int(r[1]), tuple(float(x) for x in r[2:2 + NUM_GROUPS]))
    return out


@lru_cache(maxsize=1)
def age_adder_table() -> dict:
    """ECP type code -> function(age) giving UPXTRA, 1987$/kW-year (udat.f 3386-3430)."""
    deflator = float(_table("XTRA Ages")[0][-1])
    rows = _table("XTRA OandM")
    steps = [float(x) for x in rows[0][1:]]                    # ages where each step starts (30, 40, 50)
    step_vals = {r[0].strip("'"): [float(x) / deflator for x in r[1:1 + len(steps)]] for r in rows[1:]}
    linear = {r[0].strip("'"): (int(r[1]), float(r[2])) for r in _table("XTRA Opt 2")}
    out = {}
    for code in set(step_vals) | set(linear):
        opt, coef = linear.get(code, (0, 0.0))
        if opt == 1:
            out[code] = (lambda c: (lambda age: c * age))(coef)
        else:
            vals = step_vals.get(code, [0.0] * len(steps))
            out[code] = (lambda v: (lambda age: v[int(np.searchsorted(steps, age, side="right")) - 1] if age >= steps[0] else 0.0))(vals)
    return out


@dataclass
class Groups:
    """Retirement groups for one dispatch group (coal, gas_cc, gas_ct, steam)."""
    capacity: np.ndarray        # (25, 4) GW, EPGCAP
    cost: np.ndarray            # (25, 4) 1987$/kW-year, EPGFOM
    unit_group: np.ndarray      # (units,) group 0..3 for each unit in this dispatch group, -1 otherwise
    value: np.ndarray           # (units,) RET_VAL, 1987$/kW-year (NaN where not retirable)


def retirable_units(year: int, group: str, alive: np.ndarray) -> np.ndarray:
    """Units of `group` that udat.f puts in retirement groups this year."""
    u = plants.load_units()
    tb = db.table("V_EMM_PLTF860")
    mrun = tb["T_MRUN"]
    must_run = (mrun > 0) & (year <= mrun)
    return (plants.online(year) & np.isin(u.efd_type, dispatch.EXISTING_TYPES[group]) & (u.retire_year >= 9999)
            & (u.owner <= 3) & ~must_run & (alive > 0))


def fixed_cost(year: int) -> np.ndarray:
    """RET_FOM for every unit: fixed O&M + capital additions + age adder, 1987$/kW-year."""
    u = plants.load_units()
    tb = db.table("V_EMM_PLTF860")
    adder = age_adder_table()
    refurb = np.where(tb["TRFURB"] > 0, tb["TRFURB"], u.online_year)
    age = np.maximum(year - refurb + 1, 1)
    add = np.array([adder[c](a) if c in adder else 0.0 for c, a in zip(u.ecp_type, age)])
    return tb["T_FOM"] + tb["T_CAPAD"] + add


def unit_margin(cost_mwh: np.ndarray, region0: np.ndarray, price: np.ndarray, hours: np.ndarray, avail: float) -> np.ndarray:
    """Operating margin per kW-year of each unit as a price taker.

    cost_mwh: (n,) 1987$/MWh. region0: (n,) 0-based region. price: (25, S) 1987$/MWh in S slices.
    hours: (S,) hours a year each slice stands for. avail: share of capacity available.
    Returns (n,) 1987$/kW-year.
    """
    p = price[region0]                                         # (n, S)
    return (np.maximum(p - cost_mwh[:, None], 0.0) * hours[None, :]).sum(axis=1) * avail / 1000.0


def build(year: int, group: str, alive: np.ndarray, cost_mwh: np.ndarray, price: np.ndarray, hours: np.ndarray,
          avail: float) -> Groups:
    """EPGCAP and EPGFOM for one dispatch group.

    alive: (units,) share of each unit still in service (the LP's own earlier retirements).
    cost_mwh: (units,) each unit's variable cost this year, 1987$/MWh.
    """
    u = plants.load_units()
    n = len(u.summer_mw)
    mask = retirable_units(year, group, alive)
    out = Groups(np.zeros((NUM_R, NUM_GROUPS)), np.zeros((NUM_R, NUM_GROUPS)), np.full(n, -1), np.full(n, np.nan))
    if not mask.any():
        return out
    idx = np.flatnonzero(mask)
    r0 = u.region[idx] - 1
    cap = u.summer_mw[idx] * alive[idx] / 1000.0
    margin = unit_margin(cost_mwh[idx], r0, price, hours, avail)
    fom = fixed_cost(year)[idx]
    val = margin - fom
    out.value[idx] = val
    # RET_AVG: capacity-weighted operating margin by region
    avg = np.zeros(NUM_R)
    tot = np.zeros(NUM_R)
    np.add.at(avg, r0, margin * cap)
    np.add.at(tot, r0, cap)
    avg = np.divide(avg, tot, out=np.zeros(NUM_R), where=tot > 0)
    # Cut points on the national range, by the shares of the group's dominant ECP type (all equal in cb2026)
    codes, w = np.unique(u.ecp_type[idx], return_counts=True)
    ngrp, shares = retirement_shares().get(str(codes[np.argmax(w)]), (NUM_GROUPS, (0.05, 0.45, 0.40, 0.10)))
    lo, hi = float(val.min()), float(val.max())
    cuts = lo + (hi - lo) * np.cumsum(shares[:ngrp])
    cuts[-1] = hi + 0.001
    k = np.minimum(np.searchsorted(cuts, val, side="left"), ngrp - 1)
    out.unit_group[idx] = k
    gfom = avg[r0] - margin + fom                             # 1000 * (RET_AVG - RET_VAL) per unit
    np.add.at(out.capacity, (r0, k), cap)
    num = np.zeros((NUM_R, NUM_GROUPS))
    np.add.at(num, (r0, k), gfom * cap)
    out.cost = np.divide(num, out.capacity, out=np.zeros_like(num), where=out.capacity > 0)
    return out


def retire_units(alive: np.ndarray, groups: Groups, share: np.ndarray) -> np.ndarray:
    """Take the LP's retirements off the units of each group: `share` (25, 4) is the part of each group retired.
    Returns the new `alive`."""
    u = plants.load_units()
    alive = alive.copy()
    for r, k in zip(*np.nonzero(share > 1e-9)):
        m = (groups.unit_group == k) & (u.region - 1 == r)
        alive[m] *= 1.0 - share[r, k]
    return alive


def take_pro_rata(alive: np.ndarray, mask: np.ndarray, gw_by_region: np.ndarray, base_gw: np.ndarray) -> np.ndarray:
    """Remove gw_by_region (25,) from the units in `mask` in proportion to their capacity (conversions, retrofits)."""
    u = plants.load_units()
    alive = alive.copy()
    for r in np.flatnonzero(gw_by_region > 1e-6):
        if base_gw[r] <= 0:
            continue
        m = mask & (u.region - 1 == r)
        alive[m] *= max(0.0, 1.0 - gw_by_region[r] / base_gw[r])
    return alive
