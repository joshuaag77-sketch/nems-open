"""READNHTSA (tran.f): light-duty sales by owner, region, class and technology
(trnnhtsa.csv, 2019 to STOCKYR) and the EPA attributes of the last EPA year
(trnnhtsax.xlsx, sheet "trnnhtsa"); then the choice-model constants by year (X210),
plug-in efficiency adjustments, luggage and footprint averages, and owner shares.
"""

import numpy as np

from nems_open.fortran_array import FArray
from nems_open.transportation.cafe import CARGRP, MAXCLASS, MAXGROUP
from nems_open.transportation.common import MAXLDV, MAXOWNER, MAXVTYP, MNUMCR, f32, fsum
from nems_open.transportation.mean_funcs import weighted_mean
from nems_open.transportation.readers.freight import _csv_rows
from nems_open.transportation.readers.getrng import Ranges
from nems_open.transportation.readers.ldv_tables import GAS, R9, STOCKYR, TDM, XYR

NUM_E = 159
FIRST_N = 1995 - 1989     # TRAN's first call is in 1995, when the readers run (N = 6)
LAST = 61


def _fem_like(s, k):
    if k not in s:                            # not read by any ported routine, so not dumped
        s[k] = FArray(np.zeros_like(s["fempri"].a), s["fempri"].lb)


def readnhtsa(s: dict, tdm=TDM) -> None:
    own = s["own_sales"]
    for row in _csv_rows(tdm / "trnnhtsa.csv")[:29796]:
        cy, cd, cl, gp, ld, ow = (int(x) for x in row[:6])
        own[ow, gp, cl, ld, cd, cy] = f32(row[6])
    rng = Ranges(tdm / "trnnhtsax.xlsx", "trnnhtsa")
    s["epalyr"] = type(s["epalyr"])(rng.scalar("EPALYR", "i"))
    ey = int(s["epalyr"])
    e = {}
    for k in ("ICL_E", "IGP_E", "ILDV_E"):
        e[k] = rng.fill(k, np.zeros(NUM_E, dtype=np.int32), 1, NUM_E, 1, "i")
    for k in ("PRICE_E", "HRSPWR_E", "TANKSZ_E", "TRNKSZ_E", "CURBWGT_E", "BATTKWH_E", "FTPRNT_E", "SALES_E", "RANGE_E",
              "MPGTST_E", "MPGADJ_E", "MPGCOMP_E", "PHEV_EVMT_E", "PHEVMPG_S_E", "PHEVMPG_D_E", "NAMEPLATE_E",
              "EV_RANGE_E"):
        e[k] = rng.fill(k, np.zeros(NUM_E, dtype=f32), 1, NUM_E, 1)
    adj = FArray.zeros([(1, MAXCLASS), (1, 2), (1, MAXVTYP)])
    rng.read(adj, (slice(None), slice(None), slice(None)), "EVMPGADJ", MAXCLASS, 2, MAXVTYP)
    for k in ("ev_rng", "fprt", "phevmpg_s", "phevmpg_d", "nameplate"):
        _fem_like(s, k)
    jp = s["mc_jpgdp"]
    if ey > XYR:
        cols = (("epampg", "MPGTST_E"), ("epatsz", "TANKSZ_E"), ("epalug", "TRNKSZ_E"), ("epahp", "HRSPWR_E"),
                ("epawgt", "CURBWGT_E"), ("eparng", "RANGE_E"), ("ev_rng", "EV_RANGE_E"), ("fprt", "FTPRNT_E"),
                ("cafesales", "SALES_E"), ("mpgcomp", "MPGCOMP_E"), ("mpgadj", "MPGADJ_E"),
                ("phev_evmt", "PHEV_EVMT_E"), ("phevmpg_s", "PHEVMPG_S_E"), ("phevmpg_d", "PHEVMPG_D_E"),
                ("nameplate", "NAMEPLATE_E"))
        for nm in range(NUM_E):
            gp, cl, ld = int(e["IGP_E"][nm]), int(e["ICL_E"][nm]), int(e["ILDV_E"][nm])
            for k, src in cols:
                s[k][gp, cl, ey, ld] = e[src][nm]
            s["epapri"][gp, cl, ey, ld] = e["PRICE_E"][nm] * jp[1] / jp[ey - 1989]
            s["batpacksize"][ey, cl, gp, ld] = e["BATTKWH_E"][nm]

    x = s["x210"]
    coefs = [s[f"atvcocar{k}"] for k in range(1, 6)] + [s[f"atvcotrk{k}"] for k in range(1, 7)]
    calib, gmap = s["atvcoef_calib"], s["grpmap"]
    enforce = int(s["enforce_my27regs"])
    one = f32(1.0)
    for i in range(ey - 1989, LAST + 1):
        for icl in range(1, MAXCLASS + 1):
            for il in range(1, MAXLDV + 1):
                for g in range(1, MAXGROUP + 1):
                    x[g, icl, il, R9, i] = coefs[g - 1][il, R9, icl]
                if i > ey - 1989:
                    for g in range(1, MAXGROUP + 1):
                        c = calib[il, int(gmap[g])]
                        col = x[g, icl, il, R9, i]
                        x[g, icl, il, R9, i] = np.where(col > 0.0, col * c, col * ((one - c) + one))
                if il == 16:
                    for g in range(1, MAXGROUP + 1):
                        if enforce == 1 and i >= ey + 2 - 1989:
                            if i <= 2032 - 1989:
                                x[g, icl, il, R9, i] = x[g, icl, il, R9, i] + f32(0.1)
                            else:
                                x[g, icl, il, R9, i] = (x[g, icl, il, R9, 2032 - 1989]
                                                        + f32(0.75) * (f32(i + 1989.0) - f32(2032.0))
                                                        / (f32(LAST + 1989.0) - f32(2032.0)))
                        elif i == ey + 2 - 1989:
                            x[g, icl, il, R9, i] = x[g, icl, il, R9, i] + f32(0.2)
                        elif i > ey + 2 - 1989:
                            x[g, icl, il, R9, i] = (x[g, icl, il, R9, ey + 2 - 1989]
                                                    + f32(0.55) * (f32(i + 1989.0) - f32(ey + 2.0))
                                                    / (f32(LAST + 1989.0) - f32(ey + 2.0)))

    ev_adj = s["evmpg_adj"]
    for g in range(1, MAXGROUP + 1):
        iv = int(gmap[g])
        for icl in range(1, MAXCLASS + 1):
            for il in range(1, MAXLDV + 1):
                if il in (5, 6):
                    ev_adj[g, icl, il] = adj[icl, 1, iv]
                elif il in (4, 7, 15):
                    ev_adj[g, icl, il] = adj[icl, 2, iv]
    bat, evr, cfm = s["batpacksize"], s["ev_rng"], s["cfmgq"][FIRST_N]
    for g in range(1, MAXGROUP + 1):
        for icl in range(1, MAXCLASS + 1):
            for il in range(1, MAXLDV + 1):
                t = f32(0.0)
                if bat[ey, icl, g, il] != 0.0 and il in (4, 5, 6, 7, 15):
                    t = (evr[g, icl, ey, il] / bat[ey, icl, g, il] * cfm * f32(1000000.0) / f32(42.0)
                         * (one / f32(3412.0)))
                if t != 0.0:
                    if il in (5, 6):
                        ev_adj[g, icl, il] = s["phevmpg_d"][g, icl, ey, il] / t
                    if il in (4, 7, 15):
                        ev_adj[g, icl, il] = s["epampg"][g, icl, ey, il] / t

    mpg, lug, cs, avg = s["epampg"], s["epalug"], s["cafesales"], s["luggavg"]
    for icl in range(1, MAXCLASS + 1):
        for g in range(1, MAXGROUP + 1):
            n1 = d1 = f32(0.0)
            avg[g, icl] = 0.0
            for il in range(1, MAXLDV + 1):
                if mpg[g, icl, ey, il] > 0.0 and lug[g, icl, ey, GAS] > 0.0:
                    n1 = n1 + cs[g, icl, ey, il] * (lug[g, icl, ey, il] / lug[g, icl, ey, GAS])
                    d1 = d1 + cs[g, icl, ey, il]
            if d1 != 0.0:
                avg[g, icl] = n1 / d1
    luggage = np.zeros((MAXVTYP + 1, MAXCLASS + 1), dtype=f32)
    for icl in range(1, MAXCLASS + 1):
        n1 = d1 = n2 = d2 = f32(0.0)
        for g in range(1, MAXGROUP + 1):
            for il in range(1, MAXLDV + 1):
                if mpg[g, icl, ey, il] > 0.0 and lug[g, icl, ey, GAS] > 0.0:
                    t = cs[g, icl, ey, il] * lug[g, icl, ey, il] / lug[g, icl, ey, GAS]
                    if g <= CARGRP:
                        n1, d1 = n1 + t, d1 + cs[g, icl, ey, il]
                    else:
                        n2, d2 = n2 + t, d2 + cs[g, icl, ey, il]
        if d1 != 0.0:
            luggage[1, icl] = n1 / d1
        if d2 != 0.0:
            luggage[2, icl] = n2 / d2
        for g in range(1, MAXGROUP + 1):
            if avg[g, icl] == 0.0:
                avg[g, icl] = luggage[1 if g <= CARGRP else 2, icl]
    fp, fprt = s["fprint"], s["fprt"]
    for i in range(2010, LAST + 1989 + 1):
        if i <= ey:
            for g in range(1, MAXGROUP + 1):
                for icl in range(1, MAXCLASS + 1):
                    fp[icl, g, i - 1989] = weighted_mean(fprt[g, icl, i, 1:MAXLDV], cs[g, icl, i, 1:MAXLDV], "fprint")
        else:
            fp[1:MAXCLASS, 1:MAXGROUP, i - 1989] = fp[1:MAXCLASS, 1:MAXGROUP, ey - 1989]

    G, C, L, O = slice(1, MAXGROUP), slice(1, MAXCLASS), slice(1, MAXLDV), slice(1, MAXOWNER)
    sal = s["ldv_sales"]
    yrs = slice(2019 - 1989, STOCKYR - 1989)
    sal[G, C, L, R9, yrs] = fsum(own[O, G, C, L, R9, 2019:STOCKYR], axis=0)
    sal[G, C, L, 11, yrs] = fsum(sal[G, C, L, R9, yrs], axis=3)
    ttl = fsum(own[O, G, C, L, R9, STOCKYR], axis=0)
    shr = s["ownsalesshr"]
    shr[O, G, C, L, R9, STOCKYR - 1989] = 0.0
    with np.errstate(divide="ignore", invalid="ignore"):
        for io in range(1, MAXOWNER + 1):
            cur = shr[io, G, C, L, R9, STOCKYR - 1989]
            shr[io, G, C, L, R9, STOCKYR - 1989] = np.where(ttl > 0.0, own[io, G, C, L, R9, STOCKYR] / ttl, cur)
        tot3 = fsum(ttl, axis=2)
        tmp = s["ownsaletemp"]
        for io in range(1, MAXOWNER + 1):
            cur = tmp[io, G, C, R9, STOCKYR - 1989]
            tmp[io, G, C, R9, STOCKYR - 1989] = np.where(tot3 > 0.0, fsum(own[io, G, C, L, R9, STOCKYR], axis=2) / tot3, cur)
    if "ev_range" in s:
        for il in (4, 5, 6, 7, 15):
            s["ev_range"][G, C, il, 1990:ey] = evr[G, C, 1990:ey, il]
    s.update({"igp": MAXGROUP + 1, "icl": MAXCLASS + 1, "ildv": MAXLDV + 1, "iown": MAXOWNER + 1})
