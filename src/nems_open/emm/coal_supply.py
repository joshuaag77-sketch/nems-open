"""Coal by configuration: EFD's coal-supply LP (uefd.f ED$COL), for the dispatch.

EFD dispatches coal by plant group and buys every coal configuration's coal (ECP type B1..HC, PC, IG, ...) in every
coal demand region through its own coal LP, solved with the dispatch. Read from uefd.f ED$COL (16433-17460) and
ED$BTU (7700-7790):

    S_CL<curve>   supply, per domestic curve: deliveries + the curve's other demand (XCL_OTHER, fixed) <= production
                  in 11 steps of XCL_QECP x the XCL_STEPS widths (at most XCL_PCAP in all) at XCL_PECP (capped at
                  9.999 1987$/MMBtu), then a 12th step without limit at max(3 x the 11th price, 9.999)
    CL<crg><type> demand, per coal region and configuration: the dispatch columns' coal <= the deliveries CT from
                  each curve with a route (TOT_RATE1 < 800), at the first-tier rate (XCL_TR_T1 x XCL_1TESC) plus the
                  activated carbon MATS asks of that rank (ACI_CST / heat rate)
    DV<crg><type>S, L  sub-bituminous and lignite deliveries <= EFD_SB_DVLIM, EFD_LG_DVLIM (escape DX at 9.9)

The CMM writes the two caps from EFD's own coal burn by unit, EMM_CL_BTUS (uefd.f 2993, cofired NG units under their
old configuration), as sum of EMM_CL_BTUS x the plant's sub-bituminous (lignite) share + 0.05 (coal.ams 10536-10580).
So in a converged run a western configuration burns cheap Powder River or lignite coal up to what it burned and pays
for anything more at the next source: bituminous coal from far away (0.3-0.5 1987$/MMBtu more), or the 9.9 escape
where no bituminous route exists (coal regions C1 and MT). Western bituminous is short as well: in 2030 the Utah and
Colorado curves' base production (XCL_QECP 11.8 and 33 TBtu) all goes to other users (XCL_OTHER), so power plants
that burn only bituminous coal there (CU B3) get the steps above base, about 24 TBtu, and then 9.999. In EIA's 2030
restart every capped configuration burns its cap; in the oracle's 2030 EFD (aimms-showreel sample, a different fleet
on the same caps) MT C4 burns 4.45 TBtu on a 4.43 cap at a capacity factor of 0.05, MT CX 7.35 on 7.32, WS C4 248 on
247.

`coal_classes` gives the dispatch the coal units by EMM region and class (coal region, configuration) and the LP's
data. The caps count all of a class's burn, cofired units and CCS retrofits included; the coal group gets the part its
own units burned in EIA's run (EIA's coal-unit generation, UGENPC + UGENIG - UGENSQ, at the coal group's heat rate;
the cofired and CCS groups buy at the regional price, outside the LP). LP prices meet the regional price the dispatch
charges (UPCOALAVG) through `pay`, what EIA's own burn pays in each class at base-step delivered prices within its
caps, or `ref`, the same by region (dispatch.COAL_PRICE_BY_CLASS). Left out: imports, contracts (minimum takes, 350
TBtu nationally in 2030), the tier-1 limits (tier 2 rates equal tier 1 on every power route in cb2026), SO2 and
mercury rows (not binding in cb2026); the coal_ccs and cofire groups are not split.
"""

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from nems_open.emm import db, technology

NUM_R = 25
NDREG = 16
NUTSEC = 38
NCURVE = 14                # domestic supply curves (MX_NCOALS)
ESCAPE = 9.9               # DX column cost in ED$COL, 1987$/MMBtu
STEP_PRICE_MAX = 9.999     # ED$COL caps the 11 step prices here and prices the 12th step at max(3 x p11, this)
CAP_FLOOR = 0.05           # the CMM adds 0.05 TBtu to every cap
ROUTE_MAX = 800.0          # TOT_RATE1 at or above this is no route
BASE_STEP = 5              # XCL_STEPS index of 0.0: the curve's base quantity, for the reference price
MATS_MEF_LIMIT = 0.101     # as coal.electric.mats_adder: no-ACI burning allowed only at or under this factor
# EFD puts EFD_SB_DVLIM and EFD_LG_DVLIM on the rows as they are (uefd.f 16738-16740, 16765-16767), the CMM's 0.05 TBtu
# allowance included (coal.ams 10540-10547), and writes no row where the value is negative. The coal group gets its
# part of the burn under the cap. On: that part of the cap less the allowance, plus the whole allowance; no row where
# EIA has none. Off: the part of the cap less the allowance, a negative value read as 0 (Codex finding 13).
KEEP_CAP_ALLOWANCE = True
CL_CODES = "NE YP S1 S2 GF OH EN KT AM C1 C2 WS MT CU ZN PC".split()


@dataclass
class CoalClasses:
    """Coal units by EMM region and class, as pairs P (one per region and class, plus each region's rest: coal capacity
    the CMM's units do not cover, at the coal group's heat rate, VOM and the regional price), and EFD's coal LP."""
    region: np.ndarray         # (P,) EMM region 1..25
    klass: np.ndarray          # (P,) index into classes, -1 for the rest
    share: np.ndarray          # (P,) share of the region's coal capacity
    heat_rate: np.ndarray      # (P,) Btu/kWh
    vom: np.ndarray            # (P,) 1987$/MWh
    classes: list              # K (coal region code, ECP type)
    sub_cap: np.ndarray        # (K,) TBtu, the coal group's part of EFD_SB_DVLIM (KEEP_CAP_ALLOWANCE; inf: no row)
    lig_cap: np.ndarray        # (K,) TBtu, of EFD_LG_DVLIM
    curves: np.ndarray         # (C,) curve numbers 1..14
    step_qty: np.ndarray       # (C, 12) TBtu, inf for the 12th step
    step_price: np.ndarray     # (C, 12) 1987$/MMBtu
    other: np.ndarray          # (C,) TBtu, the curve's fixed other demand
    route_curve: np.ndarray    # (Rt,) curve index 0..C-1
    route_class: np.ndarray    # (Rt,) class index
    route_rank: np.ndarray     # (Rt,) 1 bituminous, 2 sub-bituminous, 3 lignite
    route_cost: np.ndarray     # (Rt,) 1987$/MMBtu, transport + activated carbon
    ref: np.ndarray            # (25,) 1987$/MMBtu: what EIA's burn by class pays in the region at delivered prices
    pay: np.ndarray            # (K,) 1987$/MMBtu: what EIA's burn pays in each class


def _arr(s, k):
    return np.asarray(s[k], dtype=float)


@lru_cache(maxsize=1)
def _plant_units() -> dict:
    """pid_uid -> (EMM region, summer MW, MW x heat rate at EFD's part load, MW x VOM, cofired) over the plant file's
    coal and cofired (CTN) rows."""
    from nems_open.emm import dispatch
    t = db.table("V_EMM_PLTF860")
    coal, cof = set(dispatch.EXISTING_TYPES["coal"]), set(dispatch.EXISTING_TYPES["cofire"])
    part = dispatch.part_load_factor() if dispatch.COAL_PART_LOAD_HEAT_RATE else np.ones(len(t["T_PID"]))
    out = {}
    rows = zip(t["T_PID"], t["T_UID"], t["TNOPER"], t["EFDcd"], t["TC_SUM"], t["THRATE"], t["T_VOM"])
    for i, (p, u, r, e, m, h, v) in enumerate(rows):
        e = str(e).strip()
        if e not in coal and e not in cof:
            continue
        k = f"{int(p)}_{str(u).strip()}"
        r0, mw, mh, mv, c = out.get(k, (int(r), 0.0, 0.0, 0.0, e in cof))
        out[k] = (r0, mw + float(m), mh + float(m) * float(h) * part[i], mv + float(m) * float(v), c)
    return out


def supply_curves(snapshot, year: int) -> tuple:
    """ED$COL's supply steps for the active domestic curves: (curve numbers 1..14, rank, step quantity (C, 12) TBtu,
    step price (C, 12) 1987$/MMBtu, other demand (C,) TBtu)."""
    y = year - 1990
    typ = _arr(snapshot, "USO2GRP/xcl_type").astype(int)[:NCURVE]
    rank = _arr(snapshot, "USO2GRP/efd_rank").astype(int)[:NCURVE]
    pecp = _arr(snapshot, "USO2GRP/xcl_pecp")[:, :, 0, y]
    qecp = _arr(snapshot, "USO2GRP/xcl_qecp")[:, 0, y]
    pcap = _arr(snapshot, "USO2GRP/xcl_pcap")[:, y]
    steps = _arr(snapshot, "USO2GRP/xcl_steps")
    other = _arr(snapshot, "USO2GRP/xcl_other")[:NCURVE, y]
    width = np.concatenate([[1.0 + steps[0]], np.diff(steps)])
    act = np.flatnonzero(typ > 0)
    qty = np.zeros((len(act), 12))
    price = np.zeros((len(act), 12))
    for i, c in enumerate(act):
        left = pcap[c]
        for s in range(11):
            q = max(min(qecp[c] * width[s], left), 0.0)
            left -= q
            qty[i, s] = q
            price[i, s] = min(pecp[c, s], STEP_PRICE_MAX)
        qty[i, 11] = np.inf
        price[i, 11] = max(3.0 * price[i, 10], STEP_PRICE_MAX)
    return act + 1, rank[act], qty, price, other[act]


def route_costs(snapshot, year: int) -> np.ndarray:
    """(14, 16, 38) 1987$/MMBtu to bring a curve's coal to a coal region and configuration: the first-tier rate
    (XCL_TR_T1 x XCL_1TESC, COMBINE_COAL_RATES) + the activated carbon the configuration needs for that rank under
    MATS (ACI_CST(2) / heat rate where EMM_MEF(1) is above the limit); nan where there is no route."""
    y = year - 1990
    rank = _arr(snapshot, "USO2GRP/efd_rank").astype(int)[:NCURVE]
    rate = _arr(snapshot, "USO2GRP/xcl_tr_t1")[:, :, y] * _arr(snapshot, "USO2GRP/xcl_1tesc")[:, 0, y, :]
    hr = _arr(snapshot, "COALEMM/hrtclnr")[:, y, :] / 1000.0                     # (16, 38) MMBtu/MWh
    mef = _arr(snapshot, "COALEMM/emm_mef")
    aci = _arr(snapshot, "COALEMM/aci_cst")
    out = np.full((NCURVE, NDREG, NUTSEC), np.nan)
    for c in range(NCURVE):
        if not 1 <= rank[c] <= 3:
            continue
        rk = rank[c] - 1
        blocked = mef[0, rk, :NUTSEC] > MATS_MEF_LIMIT
        add = np.where(blocked[None, :], np.minimum(aci[1, rk, :NUTSEC], 99.0)[None, :] / np.maximum(hr, 1.0), 0.0)
        out[c] = np.where(rate[c][:, None] < ROUTE_MAX, rate[c][:, None] + add, np.nan)
    return out


def coal_classes(snapshot, year: int, heat_rate: np.ndarray, vom: np.ndarray) -> CoalClasses:
    """The coal group's units by region and class, and EFD's coal LP (CoalClasses). heat_rate and vom (25,) are the
    coal group's own, for the rest and to size EIA's coal-unit burn. Units are the CMM's (COALEMM EMM_CL_UNITS, active
    this year), placed by the plant file; a region's classes share its coal capacity by their units' summer capacity."""
    from nems_open.coal.electric import unit_names
    y = year - 1990
    curves, crank, qty, sprice, other = supply_curves(snapshot, year)
    rc = route_costs(snapshot, year)
    sb_raw = _arr(snapshot, "USO2GRP/efd_sb_dvlim")[:, :NUTSEC, y]
    lg_raw = _arr(snapshot, "USO2GRP/efd_lg_dvlim")[:, :NUTSEC, y]
    sb = np.maximum(sb_raw - CAP_FLOOR, 0.0)
    lg = np.maximum(lg_raw - CAP_FLOOR, 0.0)
    codes = technology.ecp_codes()
    names = unit_names(snapshot)
    n = int(np.asarray(snapshot["COALEMM/num_cmm_units"]))
    btus = _arr(snapshot, "COALEMM/emm_cl_btus")[:, y]
    ecpt = np.asarray(snapshot["COALEMM/emm_cl_ecpt"])[:, y].astype(int)
    clrg = np.asarray(snapshot["COALEMM/emm_cl_clrg"]).astype(int)
    units = _plant_units()
    # EMM_CL_BTUS by unit: all of a class's burn (its caps' basis), and the coal-type units' by region.
    burn_all = np.zeros((NDREG, NUTSEC))
    burn, mw, mh, mv = (np.zeros((NUM_R, NDREG, NUTSEC)) for _ in range(4))
    for u in range(n):
        k, t, c = names[u], ecpt[u], clrg[u]
        if not k or not 1 <= t <= NUTSEC or not 1 <= c <= NDREG or k not in units:
            continue
        r, m, h, v, cofired = units[k]
        burn_all[c - 1, t - 1] += max(btus[u], 0.0)
        if cofired or not 1 <= r <= NUM_R:
            continue
        burn[r - 1, c - 1, t - 1] += max(btus[u], 0.0)
        mw[r - 1, c - 1, t - 1] += m
        mh[r - 1, c - 1, t - 1] += h
        mv[r - 1, c - 1, t - 1] += v
    # Coal-type units also burn coal as EIA's cofired conversions (ECP type NG after the plant file) and as CCS
    # retrofits, neither of them in the coal group. A region's coal-type burn is scaled to what EIA's coal units burned
    # there (UGENPC + UGENIG - UGENSQ at the coal group's heat rate), and the coal group's part of each cap with it.
    eia_units = sum(_arr(snapshot, f"UDATOUT/ugen{t}")[:NUM_R, y] * sign for t, sign in (("pc", 1), ("ig", 1), ("sq", -1)))
    basis = np.maximum(eia_units, 0.0) * np.asarray(heat_rate, dtype=float) * 1e-3      # TWh x Btu/kWh x 1e-3 = TBtu
    have = burn.sum(axis=(1, 2))
    burn = burn * np.divide(np.minimum(basis, have), have, out=np.zeros(NUM_R), where=have > 0)[:, None, None]

    # Classes: a coal region and configuration with coal-group units and at least one route from an active curve.
    act = curves - 1
    has_route = (~np.isnan(rc[act])).any(axis=0)                          # (16, 38)
    cls_c, cls_t = np.nonzero((mw.sum(axis=0) > 0) & has_route)
    kid = -np.ones((NDREG, NUTSEC), dtype=int)
    kid[cls_c, cls_t] = np.arange(len(cls_c))
    group_burn = burn.sum(axis=0)[cls_c, cls_t]
    part = np.where(burn_all[cls_c, cls_t] > 0, group_burn / np.maximum(burn_all[cls_c, cls_t], 1e-12), 1.0)
    sub_cap, lig_cap = sb[cls_c, cls_t] * part, lg[cls_c, cls_t] * part
    if KEEP_CAP_ALLOWANCE:
        sub_cap = np.where(sb_raw[cls_c, cls_t] < 0, np.inf, sub_cap + np.clip(sb_raw[cls_c, cls_t], 0.0, CAP_FLOOR))
        lig_cap = np.where(lg_raw[cls_c, cls_t] < 0, np.inf, lig_cap + np.clip(lg_raw[cls_c, cls_t], 0.0, CAP_FLOOR))

    rr, cc, tt = np.nonzero((mw > 0) & (kid >= 0)[None])
    total = np.bincount(rr, weights=mw[rr, cc, tt], minlength=NUM_R)
    share = mw[rr, cc, tt] / np.maximum(total[rr], 1e-9)
    rest = (total <= 0).astype(float)
    hr_k = mh[rr, cc, tt] / mw[rr, cc, tt]
    vom_k = mv[rr, cc, tt] / mw[rr, cc, tt]

    rt = [(i, k, int(crank[i]), float(rc[c, cls_c[k], cls_t[k]]))
          for i, c in enumerate(act) for k in range(len(cls_c)) if not np.isnan(rc[c, cls_c[k], cls_t[k]])]
    route_curve, route_class, route_rank, route_cost = (np.array([x[j] for x in rt]) for j in range(4))

    # Reference: each class's EIA burn at the cheapest base-step delivered prices its caps allow, by region.
    deliv = sprice[route_curve, BASE_STEP] + route_cost
    pay = np.zeros(len(cls_c))
    for k in range(len(cls_c)):
        rows = np.flatnonzero(route_class == k)
        left, paid = group_burn[k], 0.0
        for j in rows[np.argsort(deliv[rows])]:
            take = left if route_rank[j] == 1 else min(left, sub_cap[k] if route_rank[j] == 2 else lig_cap[k])
            paid += take * deliv[j]
            left -= take
            if left <= 1e-9:
                break
        if left > 1e-9:
            paid += left * (deliv[rows].min() + ESCAPE)
        pay[k] = paid / group_burn[k] if group_burn[k] > 0 else deliv[rows].min()
    b = burn[rr, cc, tt]
    tot = np.bincount(rr, weights=b, minlength=NUM_R)
    ref = np.divide(np.bincount(rr, weights=b * pay[kid[cc, tt]], minlength=NUM_R), tot, out=np.zeros(NUM_R), where=tot > 0)
    for r in np.flatnonzero(tot <= 0):       # no EIA burn: the classes' own price, by capacity
        m = rr == r
        ref[r] = np.average(pay[kid[cc[m], tt[m]]], weights=share[m]) if m.any() else 0.0

    return CoalClasses(
        region=np.concatenate([rr + 1, np.arange(1, NUM_R + 1)]).astype(int),
        klass=np.concatenate([kid[cc, tt], -np.ones(NUM_R, dtype=int)]),
        share=np.concatenate([share, rest]),
        heat_rate=np.concatenate([hr_k, np.asarray(heat_rate, dtype=float)]),
        vom=np.concatenate([vom_k, np.asarray(vom, dtype=float)]),
        classes=[(CL_CODES[c], codes[t]) for c, t in zip(cls_c, cls_t)],
        sub_cap=sub_cap, lig_cap=lig_cap, curves=curves, step_qty=qty, step_price=sprice, other=other,
        route_curve=route_curve, route_class=route_class, route_rank=route_rank, route_cost=route_cost, ref=ref, pay=pay)
