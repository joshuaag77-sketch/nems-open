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
the cofired and CCS groups buy at the regional price, outside the LP). As in EFD a class pays only the LP's delivered
price (dispatch.COAL_PRICE_ANCHOR off). With the anchor on, the LP's prices are shifted onto the regional price
(UPCOALAVG) through `pay`, what EIA's own burn pays in each class at base-step delivered prices within its caps, or
`ref`, the same by region (dispatch.COAL_PRICE_BY_CLASS).

Also ported: contracts (K_ rows, CONTRACTS), the twelve import curves (IMPORTS) and the transport-tier choice with its
T_ rows (TIER_RATES). Not ported, and shown not to bind in cb2026 (tests/test_emm_dispatch.py
test_coal_lp_rows_left_out_cannot_bind): the national SO2 rows (free from UYR_NOCAIR = 2015), the CSAPR coal-region
SO2 rows (EIA's burn at the dirtiest routed coal stays under half of every limit), the mercury rows (national row free,
no MATS HGO_ rows since HG_OUTPUT, HG_INPUT and HG_MEF are zero). The activated carbon supply curve is ported as a
cost on ACI coal (ACI_SORBENT). The coal_ccs and cofire groups are not split.
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
# The reference price fills a class's EIA burn from its cheapest routes. The sub-bituminous (lignite) cap is one row
# per class over every curve of that rank (uefd.f 17199-17209: each rank-2 column gets 1.0 in ROW_DS). On: the routes
# share the cap. Off: each route could take the whole cap (Codex finding 14).
SHARED_DIVERSITY_CAP = True
# EFD puts EFD_SB_DVLIM and EFD_LG_DVLIM on the rows as they are (uefd.f 16738-16740, 16765-16767), the CMM's 0.05 TBtu
# allowance included (coal.ams 10540-10547), and writes no row where the value is negative. The coal group gets its
# part of the burn under the cap. On: that part of the cap less the allowance, plus the whole allowance; no row where
# EIA has none. Off: the part of the cap less the allowance, a negative value read as 0 (Codex finding 13).
KEEP_CAP_ALLOWANCE = True
# Contracts (uefd.f 16694-16720, 17185-17195). The CMM writes EFD_CONT(curve, coal region, scrubbed or not) from its
# contract quantities (coal.ams USO2GRP_EFD_CONT_A..E: Copy8c_CdyrsScrubbed, Copy9c_CdyrsUnScrubbed; -1 for none).
# EFD makes a row K_ >= EFD_CONT per entry that is not negative; every transport column from that curve to that coal
# region for a configuration with that scrubber status (ECP_SCRUB) enters it, and an escape KX costs 15 1987$/MMBtu.
# So up to the contract the coal is all but forced: each MMBtu short costs 15. On: those rows, the right-hand side
# scaled to the coal group's part of the region's and status's burn in EIA's run (the same basis as the caps; cofired
# units and CCS retrofits are outside this LP). Off: no contracts. 2030: 350 TBtu in 8 rows, 2025: 4,154 in 40.
CONTRACTS = True
CONTRACT_ESCAPE = 15.0     # KX column cost in ED$COL, 1987$/MMBtu
# Imports (uefd.f 16868-16914; uecp.f COMBINE_COAL_RATES 3049-3108). Twelve international curves (supply curves 15-26),
# each up to 10 steps of XCL_QIMP at XCL_PIMP (no 9.999 cap and no 12th step), after XCL_OTHER (held at most at the
# steps' total less 0.1). All are bituminous (rank 1). A route to a coal region takes the cheapest port: XCL_TR_IN x
# XCL_TESCI + XCL_TRATI2 over the four ports where XCL_TRATI2 > 0 and 0 < XCL_TR_IN < 900. On: the import curves and
# routes. Off: domestic curves only.
IMPORTS = True
NUM_IMPORT = 12            # MX_ISCV
IMPORT_STEPS = 10
# Transport tiers (uefd.f 17134-17142, 17179-17183, 17311-17332). A domestic route costs the first-tier rate where the
# CMM writes a tier-1 limit (EFD_TIER1_LIM > 0, existing configurations, PLT < WIPC) and the second-tier rate
# otherwise; with XCL_TR_T2 > XCL_TR_T1 a row T_ caps the first-tier coal at the limit and a column C_ takes the rest at
# the rate difference. On: that choice and those rows. Off: every route at the first-tier rate, no rows. In cb2026 the
# two rates are equal on every route (escalated and raw) in 2025-2050, so no T_ row exists and the choice moves nothing.
TIER_RATES = True
# The activated carbon supply curve (uefd.f 16651-16691, 17294-17302; USW_HG = 1 in cb2026). Each ACI column puts
# max(ACI_QAC x 1e-6, 1e-4) per TBtu into the row ACICSTXX <= 0, which one supply step fills at UCL_PAC = 0.33 (udat.f
# 2776; NUM_ACSS = 1, bound UCL_QAC 9,999.99, far above use). So ACI coal pays the sorbent too: 0.006-0.03
# 1987$/MMBtu on most configurations, 0.07 on C4 and 0.31 on C1 and CX bituminous. On: added to the route cost with the
# ACI O&M. Off: O&M only.
ACI_SORBENT = True
ACI_SORBENT_PRICE = 0.33   # UCL_PAC(1), from the oracle composite (aimms-showreel efd_2030_01)
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
    route_contract: np.ndarray = None   # (Rt,) contract row of the route, -1 for none (CONTRACTS)
    contract_rhs: np.ndarray = None     # (N,) TBtu, the coal group's part of EFD_CONT
    contract_key: list = None           # N (curve 1..26, coal region code, "S" or "U")
    route_tier: np.ndarray = None       # (Rt,) tier-1 row of the route, -1 for none (TIER_RATES)
    tier_rhs: np.ndarray = None         # (T,) TBtu, the coal group's part of EFD_TIER1_LIM
    tier_cost: np.ndarray = None        # (T,) 1987$/MMBtu, second-tier less first-tier rate (C_ column)


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


def import_curves(snapshot, year: int) -> tuple:
    """ED$COL's international supply curves (16868-16914): (curve numbers 15..26, step quantity (12, 12) TBtu with
    XCL_QIMP in the first 10 steps and nothing after, step price (12, 12) XCL_PIMP 1987$/MMBtu, other demand (12,)
    TBtu, XCL_OTHER held at most at the steps' total less 0.1 as COMBINE_COAL_RATES does)."""
    y = year - 1990
    q = _arr(snapshot, "USO2GRP/xcl_qimp")[:NUM_IMPORT, :IMPORT_STEPS, y]
    p = _arr(snapshot, "USO2GRP/xcl_pimp")[:NUM_IMPORT, :IMPORT_STEPS, y]
    other = _arr(snapshot, "USO2GRP/xcl_other")[NCURVE:NCURVE + NUM_IMPORT, y]
    total = q.sum(axis=1)
    other = np.where(other > total - 0.1, np.maximum(total - 0.1, 0.0), other)
    qty = np.zeros((NUM_IMPORT, 12))
    price = np.zeros((NUM_IMPORT, 12))
    qty[:, :IMPORT_STEPS] = np.where(q > 0, q, 0.0)
    price[:, :IMPORT_STEPS] = p
    return np.arange(NCURVE + 1, NCURVE + NUM_IMPORT + 1), qty, price, other


def import_rates(snapshot, year: int) -> np.ndarray:
    """(12, 16) 1987$/MMBtu, TOT_RATE1 of each import curve to each coal region (COMBINE_COAL_RATES): the cheapest
    port of the four, XCL_TR_IN x XCL_TESCI + XCL_TRATI2, where XCL_TRATI2 > 0 and 0 < XCL_TR_IN < 900; 999.9 where no
    port qualifies."""
    y = year - 1990
    tr_in = _arr(snapshot, "USO2GRP/xcl_tr_in")[:, :NUM_IMPORT, :, y]             # (4, 12, 16)
    tesci = _arr(snapshot, "USO2GRP/xcl_tesci")[:, y, :]                          # (4, 16)
    trati2 = _arr(snapshot, "USO2GRP/xcl_trati2")[:NUM_IMPORT, :4]                # (12, 4)
    rate = tr_in * tesci[:, None, :] + trati2.T[:, :, None]
    ok = (trati2.T[:, :, None] > 0.0) & (tr_in > 0.0) & (tr_in < 900.0)
    best = np.where(ok, rate, np.inf).min(axis=0)
    return np.where(np.isfinite(best), best, 999.9)


def _scrub(snapshot, year: int) -> np.ndarray:
    """(38,) ECP_SCRUB: 1 scrubbed, 2 unscrubbed, by ECP type."""
    return _arr(snapshot, "USO2GRP/ecp_scrub")[:NUTSEC, year - 1990].astype(int)


def tier_rates(snapshot, year: int) -> tuple:
    """(TOT_RATE1, TOT_RATE2) (14, 16) 1987$/MMBtu: XCL_TR_T1 x XCL_1TESC and XCL_TR_T2 x XCL_2TESC (COMBINE_COAL_RATES)."""
    y = year - 1990
    t1 = _arr(snapshot, "USO2GRP/xcl_tr_t1")[:, :, y] * _arr(snapshot, "USO2GRP/xcl_1tesc")[:, 0, y, :]
    t2 = _arr(snapshot, "USO2GRP/xcl_tr_t2")[:, :, y] * _arr(snapshot, "USO2GRP/xcl_2tesc")[:, 0, y, :]
    return t1, t2


def route_costs(snapshot, year: int) -> np.ndarray:
    """(26, 16, 38) 1987$/MMBtu to bring a curve's coal to a coal region and configuration; nan where there is no route
    (TOT_RATE1 >= 800). Domestic curves (1-14): the first-tier rate where the CMM writes a tier-1 limit for the
    configuration's scrubber status and the configuration is existing (PLT < WIPC), the second-tier rate otherwise
    (TIER_RATES; off: the first-tier rate). Import curves (15-26, IMPORTS): the port rate, rank 1. Each adds the
    activated carbon the configuration needs for that rank under MATS (ACI_CST(2) / heat rate where EMM_MEF(1) is above
    the limit)."""
    from nems_open.emm import technology
    y = year - 1990
    rank = _arr(snapshot, "USO2GRP/efd_rank").astype(int)[:NCURVE]
    t1, t2 = tier_rates(snapshot, year)
    hr = _arr(snapshot, "COALEMM/hrtclnr")[:, y, :] / 1000.0                     # (16, 38) MMBtu/MWh
    mef = _arr(snapshot, "COALEMM/emm_mef")
    aci = _arr(snapshot, "COALEMM/aci_cst")
    out = np.full((NCURVE + NUM_IMPORT, NDREG, NUTSEC), np.nan)
    if TIER_RATES:
        lim = _arr(snapshot, "USO2GRP/efd_tier1_lim")[:NCURVE, :, :, y]             # (14, 16, 2)
        f = _scrub(snapshot, year) - 1
        existing = np.arange(NUTSEC) < technology.ecp_codes().index("PC")           # PLT < WIPC
        first = (lim[:, :, f] > 0.0) & existing[None, None, :]                      # (14, 16, 38)
        rate = np.where(first, t1[:, :, None], t2[:, :, None])
    else:
        rate = np.repeat(t1[:, :, None], NUTSEC, axis=2)

    qac = _arr(snapshot, "COALEMM/aci_qac")

    def aci_add(rk):
        blocked = mef[0, rk, :NUTSEC] > MATS_MEF_LIMIT
        add = np.minimum(aci[1, rk, :NUTSEC], 99.0)[None, :] / np.maximum(hr, 1.0)
        if ACI_SORBENT:
            add = add + ACI_SORBENT_PRICE * np.maximum(qac[1, rk, :NUTSEC] * 1e-6, 1e-4)[None, :]
        return np.where(blocked[None, :], add, 0.0)

    for c in range(NCURVE):
        if not 1 <= rank[c] <= 3:
            continue
        out[c] = np.where(t1[c][:, None] < ROUTE_MAX, rate[c] + aci_add(rank[c] - 1), np.nan)
    if IMPORTS:
        imp = import_rates(snapshot, year)
        add = aci_add(0)
        for i in range(NUM_IMPORT):
            out[NCURVE + i] = np.where(imp[i][:, None] < ROUTE_MAX, imp[i][:, None] + add, np.nan)
    return out


def coal_classes(snapshot, year: int, heat_rate: np.ndarray, vom: np.ndarray) -> CoalClasses:
    """The coal group's units by region and class, and EFD's coal LP (CoalClasses). heat_rate and vom (25,) are the
    coal group's own, for the rest and to size EIA's coal-unit burn. Units are the CMM's (COALEMM EMM_CL_UNITS, active
    this year), placed by the plant file; a region's classes share its coal capacity by their units' summer capacity."""
    from nems_open.coal.electric import unit_names
    y = year - 1990
    curves, crank, qty, sprice, other = supply_curves(snapshot, year)
    if IMPORTS:
        ic, iq, ip, io = import_curves(snapshot, year)
        curves, crank = np.concatenate([curves, ic]), np.concatenate([crank, np.ones(len(ic), dtype=int)])
        qty, sprice, other = np.vstack([qty, iq]), np.vstack([sprice, ip]), np.concatenate([other, io])
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
        dom = rows[curves[route_curve[rows]] <= NCURVE]        # the reference price is the domestic curves' base step
        rows = dom if len(dom) else rows
        left, paid = group_burn[k], 0.0
        room = {2: sub_cap[k], 3: lig_cap[k]}       # one diversity row per class and rank, over all its routes
        for j in rows[np.argsort(deliv[rows])]:
            rk = int(route_rank[j])
            if rk == 1:
                take = left
            else:
                take = min(left, room[rk]) if SHARED_DIVERSITY_CAP else min(left, sub_cap[k] if rk == 2 else lig_cap[k])
                room[rk] -= take
            paid += take * deliv[j]
            left -= take
            if left <= 1e-9:
                break
        if left > 1e-9:
            paid += left * (deliv[rows].min() + ESCAPE)
        pay[k] = paid / group_burn[k] if group_burn[k] > 0 else deliv[rows].min()
    # Contracts and tier-1 limits are per curve, coal region and scrubber status, over every configuration with that
    # status; the coal group gets its part of the region's and status's burn in EIA's run (1 where EIA burned none).
    scrub = _scrub(snapshot, year)
    f_k = scrub[cls_t] - 1
    all_rf = np.zeros((NDREG, 2))
    np.add.at(all_rf, (np.repeat(np.arange(NDREG), NUTSEC), np.tile(scrub - 1, NDREG)), burn_all.ravel())
    grp_rf = np.zeros((NDREG, 2))
    np.add.at(grp_rf, (cls_c, f_k), group_burn)
    part_rf = np.where(all_rf > 0, np.minimum(grp_rf / np.maximum(all_rf, 1e-12), 1.0), 1.0)
    route_key = (curves[route_curve] - 1, cls_c[route_class], f_k[route_class])     # curve 0..25, region, status
    route_contract, contract_rhs, contract_key = -np.ones(len(route_curve), dtype=int), [], []
    if CONTRACTS:
        cont = _arr(snapshot, "USO2GRP/efd_cont")[:, :, :, y]                       # (26, 16, 2)
        rows = {}
        for j, key in enumerate(zip(*route_key)):
            if cont[key] >= 0.0:
                if key not in rows:
                    rows[key] = len(rows)
                    contract_rhs.append(cont[key] * part_rf[key[1], key[2]])
                    contract_key.append((int(key[0]) + 1, CL_CODES[key[1]], "SU"[key[2]]))
                route_contract[j] = rows[key]
    route_tier, tier_rhs, tier_cost = -np.ones(len(route_curve), dtype=int), [], []
    if TIER_RATES:
        lim = _arr(snapshot, "USO2GRP/efd_tier1_lim")[:, :, :, y]
        t1, t2 = tier_rates(snapshot, year)
        raw1, raw2 = _arr(snapshot, "USO2GRP/xcl_tr_t1")[:, :, y], _arr(snapshot, "USO2GRP/xcl_tr_t2")[:, :, y]
        rows = {}
        for j, (c, r, f) in enumerate(zip(*route_key)):
            # cls_t < WIPC always: the classes are existing configurations
            if c < NCURVE and lim[c, r, f] > 0.0 and raw2[c, r] > raw1[c, r] and t2[c, r] > t1[c, r]:
                if (c, r, f) not in rows:
                    rows[(c, r, f)] = len(rows)
                    tier_rhs.append(lim[c, r, f] * part_rf[r, f])
                    tier_cost.append(max(1e-4, t2[c, r] - t1[c, r]))
                route_tier[j] = rows[(c, r, f)]

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
        route_curve=route_curve, route_class=route_class, route_rank=route_rank, route_cost=route_cost, ref=ref, pay=pay,
        route_contract=route_contract, contract_rhs=np.asarray(contract_rhs, dtype=float), contract_key=contract_key,
        route_tier=route_tier, tier_rhs=np.asarray(tier_rhs, dtype=float), tier_cost=np.asarray(tier_cost, dtype=float))


def nocair_year() -> int:
    """UYR_NOCAIR from emmcntl.txt: from this year on ED$COL makes the national SO2 rows free (type N, uefd.f 16545)."""
    from nems_open.paths import INPUT
    for line in (INPUT / "emm" / "emmcntl.txt").read_text(errors="replace").splitlines():
        if line.startswith("'NOCAIR YR'"):
            return int(line.split()[2])
    raise ValueError("NOCAIR YR not in emmcntl.txt")


def csapr_ratio(snapshot, year: int, classes=None, flows=None) -> np.ndarray:
    """(16,) for the CSAPR coal-region SO2 rows (EPA$TRANRG_EFD, uefd.f 19749-19777; NaN where TSO2_LIM_BY_CLRG is 0):
    SO2 over the row's limit (TSO2_LIM_BY_CLRG from TRANRULE2 on, TSO2_LM1_BY_CLRG before), thousand tons, each TBtu
    at XCL_SO2_YR x (1 - RCLCLNR) x 0.5 x TSO2_SHR_BY_CLRG. Without flows: EIA's coal burn by unit (EMM_CL_BTUS) in each
    region at the dirtiest curve with a route to its configuration, a bound whatever coal is bought. With the coal
    LP's route flows (TBtu, for CoalClasses `classes`): their SO2, scaled to EIA's whole burn in the region (cofired
    units and CCS retrofits at the coal group's mix). Under 1: the row is slack."""
    y = year - 1990
    lim = _arr(snapshot, "CSAPR/tso2_lim_by_clrg") if year >= int(np.asarray(snapshot["CSAPR/tranrule2"]))         else _arr(snapshot, "CSAPR/tso2_lm1_by_clrg")
    shr = _arr(snapshot, "CSAPR/tso2_shr_by_clrg")[:, 0]
    so2 = _arr(snapshot, "USO2GRP/xcl_so2_yr")[:NCURVE + NUM_IMPORT, y]
    removal = _arr(snapshot, "COALEMM/rclclnr")[:, y, :NUTSEC]                     # (16, 38) SO2 removal rate
    n = int(np.asarray(snapshot["COALEMM/num_cmm_units"]))
    btus = _arr(snapshot, "COALEMM/emm_cl_btus")[:n, y]
    ecpt = np.asarray(snapshot["COALEMM/emm_cl_ecpt"])[:n, y].astype(int)
    clrg = np.asarray(snapshot["COALEMM/emm_cl_clrg"])[:n].astype(int)
    burn = np.zeros((NDREG, NUTSEC))
    ok = (ecpt >= 1) & (ecpt <= NUTSEC) & (clrg >= 1) & (clrg <= NDREG)
    np.add.at(burn, (clrg[ok] - 1, ecpt[ok] - 1), np.maximum(btus[ok], 0.0))
    if flows is None:
        rc = route_costs(snapshot, year)
        dirtiest = np.where(np.isnan(rc), -np.inf, so2[:, None, None]).max(axis=0)       # (16, 38)
        dirtiest = np.where(np.isfinite(dirtiest), dirtiest, so2[:NCURVE].max())
        em = (burn * dirtiest * (1.0 - removal) * 0.5).sum(axis=1)
    else:
        from nems_open.emm import technology
        codes = technology.ecp_codes()
        crg = np.array([CL_CODES.index(classes.classes[k][0]) for k in classes.route_class])
        typ = np.array([codes.index(classes.classes[k][1]) for k in classes.route_class])
        e = flows * so2[classes.curves[classes.route_curve] - 1] * (1.0 - removal[crg, typ]) * 0.5
        em = np.bincount(crg, weights=e, minlength=NDREG)
        got = np.bincount(crg, weights=flows, minlength=NDREG)
        em = em * np.divide(burn.sum(axis=1), got, out=np.ones(NDREG), where=got > 1e-9)
    em = em * shr
    return np.where(lim > 0, em / np.where(lim > 0, lim, 1.0), np.nan)
