"""The light-duty CSV readers (tran.f): READSTOCK, READHIST, READVMT.

READSTOCK  census-division LDV stocks by owner, type, technology and vintage (1995 to
           STOCKYR); CNG/LPG vintages rolled forward from 2017 with survival; the US
           total; fleet stocks (owners 2-5) in vehicles
READHIST   the fuel economy model's history by year, class, group and technology
           (prices to 1990 dollars), the base and current attributes from XYR, sales
           history, and the electric system cost for plug-ins and fuel cells
READVMT    VMT per vehicle by age, year, region and technology (2016 to VMTYR), filled
           back to 1995 and forward with the schedule parameters from READLDV

EIA quirk kept (READSTOCK): the fleet owners' oldest vintage uses the survival rate at
MAXAGE-1 for both terms (the loop index is left at MAXAGE).
"""

import numpy as np

from nems_open.paths import INPUT
from nems_open.transportation.cafe import CARGRP, MAXCLASS, MAXGROUP
from nems_open.transportation.common import MAXAGE, MAXHAV, MAXLDV, MAXOWNER, MAXVTYP, MNUMCR, f32, fsum
from nems_open.transportation.readers.freight import _csv_rows

TDM = INPUT / "tdm"
STOCKYR, VMTYR, XYR = 2024, 2024, 2022
NUMSTKYRS = STOCKYR - 1994
MAXFLEET = 4
BASE, CURRENT, GAS = 0, 2, 1
R9 = slice(1, MNUMCR - 2)


def readstock(s: dict, tdm=TDM) -> None:
    n_rows = (MAXOWNER - 1) * MAXVTYP * MAXLDV * MAXAGE * (MNUMCR - 2) + MAXVTYP * MAXLDV * 3 * (MNUMCR - 2)
    rows = _csv_rows(tdm / "trnstockx_ldv.csv")[:n_rows]
    stk = s["ldv_stock"]
    stk.a[...] = 0.0
    yrs = slice(6, 5 + NUMSTKYRS)
    for row in rows:
        fl2, v2, r2, a2, f2 = (int(x) for x in row[:5])
        stk[r2, v2, fl2, f2, a2, 1, yrs] = np.array(row[5:5 + NUMSTKYRS], dtype=f32) / f32(1000000.0)
    ss, sf = s["ssurv25"], s["survflt"]
    for j2 in range(28, STOCKYR - 1989 + 1):
        for il in range(9, 13):
            for iv in range(1, MAXVTYP + 1):
                for io in range(1, MAXOWNER + 1):
                    if io == 1:
                        for ia in range(2, MAXAGE):
                            stk[R9, iv, io, il, ia, 1, j2] = stk[R9, iv, io, il, ia - 1, 1, j2 - 1] * ss[R9, ia - 1, iv]
                        stk[R9, iv, io, il, MAXAGE, 1, j2] = (stk[R9, iv, io, il, MAXAGE - 1, 1, j2 - 1] * ss[R9, MAXAGE - 1, iv]
                                                              + stk[R9, iv, io, il, MAXAGE, 1, j2 - 1] * ss[R9, MAXAGE, iv])
                    else:
                        for ia in range(2, MAXAGE):
                            stk[R9, iv, io, il, ia, 1, j2] = stk[R9, iv, io, il, ia - 1, 1, j2 - 1] * sf[io - 1, ia - 1, iv]
                        r = sf[io - 1, MAXAGE - 1, iv]           # EIA quirk: IAGE is MAXAGE here
                        stk[R9, iv, io, il, MAXAGE, 1, j2] = (stk[R9, iv, io, il, MAXAGE - 1, 1, j2 - 1] * r
                                                              + stk[R9, iv, io, il, MAXAGE, 1, j2 - 1] * r)
    V, O, L, A = slice(1, MAXVTYP), slice(1, MAXOWNER), slice(1, MAXLDV), slice(1, MAXAGE)
    stk[MNUMCR, V, O, L, A, 1, yrs] = fsum(stk[R9, V, O, L, A, 1, yrs], axis=0)
    s["flt_stock"][1:MNUMCR, V, slice(1, MAXFLEET), L, A, 1, yrs] = stk[1:MNUMCR, V, 2:MAXFLEET + 1, L, A, 1, yrs] * f32(1000000.0)
    s.update({"j2": STOCKYR - 1989 + 1, "ildv": 13, "ivtyp": MAXVTYP + 1, "iown": MAXOWNER + 1, "iage": MAXAGE})


def readhist(s: dict, tdm=TDM) -> None:
    rows = _csv_rows(tdm / "trnfem.csv")[:3328]
    jp = s["mc_jpgdp"]
    names = ["fempri", "femmpg", "mpgadj", "mpgcomp", "femhp", "femtsz", "ev_rng", "femrng", "femwgt", None,
             "fprt", "phev_evmt", "cafesales"]
    from nems_open.fortran_array import FArray
    for k in names:                            # arrays no ported routine reads are not dumped
        if k is not None and k not in s:
            s[k] = FArray(np.zeros_like(s["fempri"].a), s["fempri"].lb)
    for row in rows:
        y2, c2, g2, v2 = (int(x) for x in row[:4])
        vals = [f32(x) for x in row[4:17]]
        s["fempri"][g2, c2, y2, v2] = vals[0] * jp[1] / jp[y2 - 1989]
        for k, val in zip(names[1:], vals[1:]):
            if k is not None:
                s[k][g2, c2, y2, v2] = val
        s["batpacksize"][y2, c2, g2, v2] = vals[9]
    G, C, L = slice(1, MAXGROUP), slice(1, MAXCLASS), slice(1, MAXLDV)
    pairs = (("fe", "femmpg"), ("weight", "femwgt"), ("price", "fempri"), ("hp", "femhp"), ("tanksize", "femtsz"),
             ("range", "femrng"))
    for k, _ in pairs:
        s[k][G, C, BASE:CURRENT, L] = 0.0
    pen = s["mkt_pen"]
    for i in range(BASE, CURRENT + 1):
        for k, src in pairs:
            s[k][G, C, i, L] = s[src][G, C, XYR, L]
        for il in range(1, MAXLDV + 1):
            pen[G, C, 1:int(s["numtech"]), i, il] = pen[G, C, 1:int(s["numtech"]), BASE, GAS]
    last = 2023 - 1989
    sal, cs = s["ldv_sales"], s["cafesales"]
    iy = 1995 - 1990 + 1
    for g in range(1, MAXGROUP + 1):
        for c in range(1, MAXCLASS + 1):
            for il in range(1, MAXLDV + 1):
                sal[g, c, il, MNUMCR, iy:last] = cs[g, c, iy + 1989:last + 1989, il]
    inc, bat, li, nb = s["elecsysinccost"], s["batpacksize"], s["li_ion_cost"], s["elecnonbattcst"]
    for il in range(1, MAXLDV + 1):
        if 4 <= il <= 7 or il >= 14:
            for c in range(1, MAXCLASS + 1):
                for g in range(1, MAXGROUP + 1):
                    for i in range(BASE, CURRENT + 1):
                        k = 1 if g <= CARGRP else 2
                        inc[c, g, i, il] = (bat[XYR, c, g, il] * li[il, XYR]) + nb[c, XYR, k, il]
    s.update({"igp": MAXGROUP + 1, "icl": MAXCLASS + 1, "ildv": MAXLDV + 1, "i": CURRENT + 1})


def readvmt(s: dict, tdm=TDM) -> None:
    """READVMT: needs READLDV's VMT_SCHED_PARAM."""
    ncol = VMTYR - 2016 + 1
    pv, lv = s["pvmt"], s["lvmt"]
    ys = slice(27, 26 + ncol)
    for row in _csv_rows(tdm / "trnldv_vmt.csv")[:3600]:
        v2, r2, f2, a2 = (int(x) for x in row[:4])
        (pv if v2 == 1 else lv)[a2, ys, r2, f2] = np.array(row[4:4 + ncol], dtype=f32)
    yv = slice(27, VMTYR - 1989)
    for il in (3, 8, 9, 10, 11, 12, 13, 14):
        pv[:, yv, :, il] = pv[:, yv, :, 1]
    for il in (3, 8, 9, 10, 11, 12, 13, 14):
        lv[:, yv, :, il] = lv[:, yv, :, 1]
    iy = 1995 - 1990 + 1
    for icl in range(iy, 2015 - 1989 + 1):
        pv[:, icl, :, :] = pv[:, 2016 - 1989, :, :]
        lv[:, icl, :, :] = lv[:, 2016 - 1989, :, :]
    prm, ij = s["vmt_sched_param"], int(s["ijumpyr"])
    b = VMTYR - 1989
    for icl in range(b, ij + 1):
        for il in range(1, MAXLDV + 1):
            if prm[il, 1] == 0.0:
                pv[:, icl, :, il] = pv[:, b, :, il]
                lv[:, icl, :, il] = lv[:, b, :, il]
            elif icl <= prm[il, 2] - 1989:
                frac = f32(icl + 1989 - VMTYR) / (prm[il, 2] - f32(VMTYR))
                for a in (pv, lv):
                    for r in range(1, MNUMCR - 1):
                        for ia in range(1, MAXAGE + 1):
                            tgt = a[ia, b, r, 1] * prm[il, 1]
                            if a[ia, icl, r, il] < a[ia, icl, r, 1] * prm[il, 1]:
                                a[ia, icl, r, il] = (tgt - a[ia, b, r, il]) * f32(icl + 1989 - VMTYR) / (prm[il, 2] - f32(VMTYR)) + a[ia, b, r, il]
                            else:
                                a[ia, icl, r, il] = tgt
                del frac
            else:
                pv[1:MAXAGE, icl, R9, il] = pv[1:MAXAGE, icl - 1, R9, il]
                lv[1:MAXAGE, icl, R9, il] = lv[1:MAXAGE, icl - 1, R9, il]
    for a in (pv, lv):
        a[1:MAXAGE, iy:ij, MNUMCR, 1:MAXLDV] = fsum(a[1:MAXAGE, iy:ij, R9, 1:MAXLDV], axis=2) / f32(9.0)
    s.update({"icl": ij + 1, "ildv": MAXLDV + 1, "iregn": MNUMCR - 1, "iage": MAXAGE + 1})
