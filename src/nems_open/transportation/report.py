"""TREPORT and the tail of TRAN (tran.f): report variables and NGTDM/refinery hand-offs.

TREPORT fills the published tables: highway and non-highway fuel use by mode, truck
fuel by size class, electricity by charging location, LDV fuel by technology, new
vehicle efficiency, horsepower and weight by class, fleet stocks, sales and stocks by
technology and region, new and stock fuel economy, and VMT per driver.
TRAN's tail passes natural gas by mode and fleet to NGTDM, splits residual oil into
high and low sulfur, and sets average new vehicle prices.

carry: TREPORT's saved cmpg_2, tmpg_2, lmpg_2 (MAXLDV each).
EIA quirks kept:
- TRLDQTEK for 100-mile electric vehicles adds the fleet use of 200-mile ones (index 7).
- cmpg_2, tmpg_2 and lmpg_2 are not reset: a technology with no use keeps its last
  value in the harmonic means behind TRLDMPGF.
"""

import numpy as np

from nems_open.transportation.cafe import CARGRP, LTKGRP, MAXCLASS, MAXGROUP
from nems_open.transportation.common import AGEGRP, MAXAGE, MAXHAV, MAXLDV, MAXOWNER, MAXVTYP, MF, MNUMCR, f32, fsum
from nems_open.transportation.mean_funcs import weighted_mean

ONE = f32(1.0)
R9 = slice(1, MNUMCR - 2)
A11 = slice(1, MNUMCR)
MAXFUEL = 8
MAXFLEET = 4
XYR = 2022       # PARAMETER in T_: FEM base year
MPGMAP = [None, 1, 2, 1, 5, 4, 4, 5, 3, 7, 7, 7, 7, 7, 6, 5, 3]
MPGMAP_CLT = [None, 1, 2, 7, 7, 1, 5, 4, 4, 6, 6, 3, 7]


def treport(s: dict, carry: dict) -> None:
    n, yrs = int(s["n"]), int(s["yrs"])
    for k, idx in (("tthcons", (slice(None), n)), ("trqhwy", (slice(None), n)), ("trvmttrk", (slice(None), slice(None), n)),
                   ("pas_rpm", (slice(None), n)), ("trqldv", (slice(None), slice(None), n)), ("trqftrk", (slice(None), n)),
                   ("trqftrk_new", (slice(None), slice(None), n)), ("trqhwy_new", (slice(None), n))):
        s[k][idx] = 0.0
    s["trvmttrk"][1:2, 1:12, n] = fsum(s["bfvmtechsc"][1:2, 1:12, R9], axis=2) / (ONE * f32(1E9))
    rpm, vmte = s["pas_rpm"], s["trldvmte"]
    if yrs <= int(s["cychistyr"]):
        rpm[1, n] = s["cyc_rpm"][n]
    else:
        rpm[1, n] = (vmte[1, n] / vmte[1, n - 1]) * rpm[1, n - 1]
    rpm[2, n] = (fsum(s["tmod"][1:2, n]) + s["tbpmt"][11, n]) / f32(1000.0)
    rpm[3, n] = (fsum(s["trrpm"][1:9, n]) + fsum(s["crrpm"][1:9, n]) + s["irrpm"][n]) / f32(1000.0)
    trqldv = s["trqldv"]
    for f in range(1, MAXFUEL + 1):
        trqldv[f, A11, n] = s["btqldv"][f, A11] + s["bfltfuelbtu"][A11, f, n]
    trqldt = fsum(trqldv[1:MAXFUEL, 11, n])
    bf = s["btqfreirsc"]
    ftrk, ftrk_new = s["trqftrk"], s["trqftrk_new"]
    for k, f in ((1, 2), (2, 1), (3, 4), (5, 3), (6, 5), (7, 6), (8, 7)):
        ftrk[k, n] = fsum(bf[1:3, f, R9])
    ftrk[4, n] = 0.0
    for isc in (1, 2, 3):
        ftrk_new[isc, 1, n] = fsum(bf[isc, 2, R9]) + fsum(bf[isc, 5, R9])
        for k, f in ((2, 1), (3, 3), (4, 6), (5, 4), (6, 7)):
            ftrk_new[isc, k, n] = fsum(bf[isc, f, R9])
    s["trqhwy_new"][5, n] = fsum(bf[1, 1:7, R9])
    s["trqhwy_new"][6, n] = fsum(bf[2, 1:7, R9])
    cfmgq, cfdstr = s["cfmgq"][n], s["cfdstr"][n]
    s["hfueltax"][n] = (((trqldv[1, 11, n] + ftrk[1, n]) / cfmgq * f32(0.042))
                        + ((trqldv[8, 11, n] + ftrk[2, n]) / cfdstr * f32(0.042))) * (s["fueltax87"][n] / f32(8))
    s["trqairt"][1, n] = s["bqjetr"][11]
    s["trqairt"][2, n] = s["bqagr"][11]
    hwy = s["trqhwy"]
    hwy[5, n] = fsum(bf[1:2, 1:7, R9])
    hwy[6, n] = fsum(bf[3, 1:7, R9])
    fl = s["fltldvbtu"]
    s["fltfcldvbtu"][1:MAXVTYP, 1:MAXLDV, n] = fl[MNUMCR, 1:MAXVTYP, 1:MAXLDV, n]
    cq = ltq = f32(0.0)
    hhs, bstk = s["hhmpgstk_typldv"], s["bvmt_stk_hh"]
    for il in range(1, MAXLDV + 1):
        if hhs[il, 1, n] != 0.0:
            cq = cq + (fsum(bstk[1, il, 1:MAXAGE, 1, R9]) / hhs[il, 1, n]) * cfmgq / f32(42.0)
        if hhs[il, 2, n] != 0.0:
            ltq = ltq + (fsum(bstk[2, il, 1:MAXAGE, 1, R9]) / hhs[il, 2, n]) * cfmgq / f32(42.0)
    t1 = cq + fsum(fl[MNUMCR, 1, 1:MAXLDV, n])
    t2 = ltq + fsum(fl[MNUMCR, 2, 1:MAXLDV, n])
    hwy[3, n] = rpm[1, n] / s["cyc_mpg"][n] * cfmgq / f32(42) * f32(1000)
    sh1, sh2 = t1 / (t1 + t2), t2 / (t1 + t2)
    hwy[1, n] = (trqldt - hwy[3, n]) * sh1
    hwy[2, n] = (trqldt - hwy[3, n]) * sh2
    qj, benjf = s["qjetr_di"], s["benjf"][MNUMCR, n]
    nh = s["trqnhwy"]
    tot = fsum(qj[1, :, :, n])
    nh[1, n] = s["bqagr"][11] + (tot - tot / f32(1.05)) * benjf
    nh[2, n] = (qj[1, 1, 1, n] / f32(1.05)) * benjf
    nh[3, n] = (qj[1, 2, 1, n] / f32(1.05)) * benjf
    nh[4, n] = (fsum(qj[1, :, 2, n]) / f32(1.05)) * benjf
    for i in range(1, 5):
        s["trqdoms"][i, n] = s["btqdshipr"][i, MNUMCR]
        s["trqints"][i, n] = s["btqishipr"][i, MNUMCR]
        s["trqrrf"][i, n] = s["btqrailr"][i, MNUMCR]
    ben = lambda k: s["ben" + k][MNUMCR, n]  # noqa: E731
    s["trqboat"][1, n] = fsum(s["qrecr"][1, R9, n]) * ben("mg")
    s["trqboat"][2, n] = fsum(s["qrecr"][2, R9, n]) * ben("ds")
    rrp = s["trqrrp"]
    rrp[1, n] = s["irede"][n]
    rrp[2, n] = s["iredd"][n] * ben("ds")
    rrp[3, n] = 0.0
    rrp[4, n] = 0.0
    rrp[5, n] = s["tred"][MNUMCR, n]
    rrp[6, n] = s["crede"][MNUMCR, n]
    rrp[7, n] = s["credd"][MNUMCR, n] * ben("ds")
    rrp[8, n] = 0.0
    rrp[9, n] = 0.0
    s["trqlub"][n] = s["bqlubr"][MNUMCR]
    for i, k in ((1, 4), (2, 2), (3, 3), (4, 1)):
        s["trqmil"][i, n] = s["bqmiltr"][k, MNUMCR]
    for i, k in enumerate(("qmgtr", "qdstr", "qjftr", "qrstr", "qagtr", "qlgtr", "qlutr", "qmetr", "qettr", "qeltr",
                           "qngtr", "qh2tr"), start=1):
        s["trqenuse"][i, n] = s[k][MNUMCR, n]
    el = s["trq_elec"]
    el[:, :, n] = 0.0
    chg, benel_r = s["chg_dist"], s["benel"][R9, n]
    el[1, R9, n] = trqldv[6, R9, n] * chg[R9, 2, n]
    el[2, R9, n] = trqldv[6, R9, n] * chg[R9, 3, n]
    el[3, R9, n] = trqldv[6, R9, n] - fsum(el[1:2, R9, n], axis=0)
    bus = s["qmtbr"]
    el[4, R9, n] = bus[3, 7, R9, n] * benel_r
    el[5, R9, n] = bus[1, 7, R9, n] * benel_r
    el[6, R9, n] = bus[2, 7, R9, n] * benel_r
    el[7, R9, n] = s["cltfbtu"][n, 6, R9] * benel_r
    el[8, R9, n] = fsum(bf[1:3, 6, R9], axis=0) * s["tfrbtu_chgsplit"][2, n]
    el[9, R9, n] = fsum(bf[1:3, 6, R9], axis=0) * s["tfrbtu_chgsplit"][1, n]
    el[10, R9, n] = s["trqrailr"][1, R9, n]
    el[1:10, MNUMCR, n] = fsum(el[1:10, R9, n], axis=1)
    s["tthcons"][1, n] = hwy[3, n]
    s["tthcons"][2:6, n] = 0.0

    tek, hh, flt_t, af = s["trldqtek"], s["hhtechbtu"], s["fltldvbtut"], s["pctaf"]
    tek[1:MAXLDV, n] = 0.0
    h = lambda il: fsum(hh[R9, 1:MAXVTYP, il, n], axis=1)  # noqa: E731
    f = lambda il: flt_t[R9, il, n]  # noqa: E731
    p20, p50 = s["pctphev20"][n], s["pctphev50"][n]
    mix = lambda il, p, a, b: (ONE - p) * h(il) * ben(a) + p * h(il) * ben(b)  # noqa: E731
    tek[1, n] = fsum(h(1) * ben("mg") + f(1))
    tek[2, n] = fsum(h(2) * ben("ds") + f(2))
    tek[3, n] = fsum(mix(3, af[2, R9, n], "mg", "et") + f(3))
    tek[4, n] = fsum(h(4) * ben("el") + f(7))
    tek[5, n] = fsum(mix(5, p20, "mg", "el") + f(5))
    tek[6, n] = fsum(mix(6, p50, "mg", "el") + f(6))
    tek[7, n] = fsum(h(7) * ben("el") + f(7))
    tek[8, n] = fsum(h(8) * ben("ds") + f(8))
    tek[9, n] = fsum(mix(9, af[3, R9, n], "mg", "ng") + f(9))
    tek[10, n] = fsum(mix(10, af[4, R9, n], "mg", "lg") + f(10))
    for il, k in ((11, "ng"), (12, "lg"), (13, "me"), (14, "hy"), (15, "el"), (16, "mg")):
        tek[il, n] = fsum(h(il) * ben(k) + f(il))

    car, trk = s["treffcar"], s["trefftrk"]
    car[:, n] = 0.0
    trk[:, n] = 0.0
    mpg, sal, deg = s["ldvmpg"], s["totalsalsc"], s["degfac"]
    for icl in range(1, MAXCLASS + 1):
        for il in (1, 2):
            m1, m2 = mpg[1, il, icl, yrs], mpg[2, il, icl, yrs]
            if m1 > 0.0:
                car[icl, n] = car[icl, n] + sal[1, icl, il, n] / m1
            if m2 > 0.0:
                trk[icl, n] = trk[icl, n] + sal[2, icl, il, n] / m2
            if m1 > 0.0:
                car[MAXCLASS + 1, n] = car[MAXCLASS + 1, n] + sal[1, icl, il, n] / m1
                car[MAXCLASS + 2, n] = car[MAXCLASS + 2, n] + sal[1, icl, il, n] / (m1 * deg[1, il, n])
            if m2 > 0.0:
                trk[MAXCLASS + 1, n] = trk[MAXCLASS + 1, n] + sal[2, icl, il, n] / m2
                trk[MAXCLASS + 2, n] = trk[MAXCLASS + 2, n] + sal[2, icl, il, n] / (m2 * deg[2, il, n])
        if car[icl, n] > 0.0:
            car[icl, n] = fsum(sal[1, icl, 1:2, n]) / car[icl, n]
        if trk[icl, n] > 0.0:
            trk[icl, n] = fsum(sal[2, icl, 1:2, n]) / trk[icl, n]
    for k in (MAXCLASS + 1, MAXCLASS + 2):
        if car[k, n] > 0.0:
            car[k, n] = fsum(sal[1, :, 1:2, n]) / car[k, n]
        if trk[k, n] > 0.0:
            trk[k, n] = fsum(sal[2, :, 1:2, n]) / trk[k, n]
    tot_sal = fsum(sal[:, 1:MAXCLASS, 1:MAXLDV, n])
    for icl in range(1, MAXCLASS + 1):
        s["trslshrc"][icl, n] = fsum(sal[1, icl, 1:MAXLDV, n]) / tot_sal
        s["trslshrt"][icl, n] = fsum(sal[2, icl, 1:MAXLDV, n]) / tot_sal
    hpw, femhp, cs = s["ldvhpw"], s["femhp"], s["cafesales"]
    for icl in range(1, MAXCLASS + 1):
        for il in range(1, MAXLDV + 1):
            hpw[1, il, icl, yrs] = weighted_mean(femhp[1:CARGRP, icl, yrs, il], cs[1:CARGRP, icl, yrs, il])
            hpw[2, il, icl, yrs] = weighted_mean(femhp[LTKGRP:MAXGROUP, icl, yrs, il], cs[LTKGRP:MAXGROUP, icl, yrs, il])
        s["trhpcar"][icl, n] = weighted_mean(hpw[1, 1:MAXLDV, icl, yrs], sal[1, icl, 1:MAXLDV, n])
        s["trhptrk"][icl, n] = weighted_mean(hpw[2, 1:MAXLDV, icl, yrs], sal[2, icl, 1:MAXLDV, n])
    s["trhpcar"][MAXCLASS + 1, n] = s["ahpcar"][11, n]
    s["trhptrk"][MAXCLASS + 1, n] = s["ahptruck"][11, n]
    wc, wt, wgt = s["trwtcar"], s["trwttrk"], s["wgt"]
    wc[:, n] = 0.0
    wt[:, n] = 0.0
    for icl in range(1, MAXCLASS + 1):
        for il in range(1, MAXLDV + 1):
            wc[icl, n] = wc[icl, n] + sal[1, icl, il, n] * wgt[1, il, icl, yrs]
            wt[icl, n] = wt[icl, n] + sal[2, icl, il, n] * wgt[2, il, icl, yrs]
        if fsum(sal[1, icl, :, n]) > 0.0:
            wc[icl, n] = wc[icl, n] / fsum(sal[1, icl, :, n])
        if fsum(sal[2, icl, :, n]) > 0.0:
            wt[icl, n] = wt[icl, n] / fsum(sal[2, icl, :, n])
    wc[MAXCLASS + 1, n] = s["awtcar"][11, n]
    wt[MAXCLASS + 1, n] = s["awttruck"][11, n]

    fs, fst, bfv = s["flt_stock"], s["fltechstk"], s["bfltvmtech"]
    V, FL, L, H = slice(1, MAXVTYP), slice(1, MAXFLEET), slice(1, MAXLDV), slice(1, MAXHAV)
    s["fltechrpt"][V, L, n] = fsum(fsum(fs[MNUMCR, V, FL, L, 1, H, n], axis=3), axis=1) / f32(1000.0)
    s["fltechstkrpt"][V, L, n] = fsum(fsum(fst[MNUMCR, V, FL, L, H], axis=3), axis=1) / f32(1000.0)
    s["fltechvmtrpt"][V, L, n] = fsum(bfv[V, FL, L], axis=1)
    s["trtmrr"][1, n] = fsum(s["brtmtt"][n, R9])
    s["trtmrr"][2, n] = ONE / s["freff"][n]
    s["trtmship"][1, n] = fsum(s["bstmtt"][n, R9])
    s["trtmship"][2, n] = ONE / s["dseff"][n]
    s["trimship"][n] = s["mc_mr"][n]
    salc, salt, stk = s["trldsalc"], s["trldsalt"], s["ldv_stock"]
    O = slice(1, MAXOWNER)
    salc[L, R9, n] = fsum(fsum(stk[R9, 1, O, L, 1, H, n], axis=3), axis=1).T
    salt[L, R9, n] = fsum(fsum(stk[R9, 2, O, L, 1, H, n], axis=3), axis=1).T
    salc[L, 11, n] = fsum(salc[L, R9, n], axis=1)
    salt[L, 11, n] = fsum(salt[L, R9, n], axis=1)
    mic = s["trmicros"]
    if yrs == 1995:
        mic[...] = 0.0
    if yrs >= XYR:
        pen = s["micropen"]
        mic[1, L, A11, n] = salc[L, A11, n] * pen[1, L, n][:, None]
        mic[2, L, A11, n] = salt[L, A11, n] * pen[2, L, n][:, None]
        mic[1:2, 4:MAXLDV, A11, n] = 0.0
    anc = fsum(salc[3:MAXLDV, A11, n], axis=0)
    ant = fsum(salt[3:MAXLDV, A11, n], axis=0)
    s["tncsale"][A11, n] = fsum(salc[:, A11, n], axis=0)
    s["tntsale"][A11, n] = fsum(salt[:, A11, n], axis=0)
    tc, tt = s["tncsale"][A11, n], s["tntsale"][A11, n]
    leg = s["legaltsal"]
    leg[1, A11, n] = 0.0
    with np.errstate(divide="ignore", invalid="ignore"):
        leg[1, A11, n] = np.where(tc + tt != 0.0, (anc + ant) / (tc + tt), leg[1, A11, n])
    leg[3, A11, n] = s["totlev"][A11]
    s["trldstkc"][L, n] = s["vstk"][1, L]
    s["trldstkt"][L, n] = s["vstk"][2, L]
    mc_, mt_ = s["trldmpgc"], s["trldmpgt"]
    if yrs == 1995:
        mc_[...] = 0.0
        mt_[...] = 0.0
    mc_[:, n] = 0.0
    mt_[:, n] = 0.0
    new = s["ldvmpgnew"]
    for il in range(1, MAXLDV + 1):
        if new[MNUMCR, 1, il, n] == new[MNUMCR, 1, il, n]:
            mc_[il, n] = new[MNUMCR, 1, il, n]
        if new[MNUMCR, 2, il, n] == new[MNUMCR, 2, il, n]:
            mt_[il, n] = new[MNUMCR, 2, il, n]

    tm = s["techmpg"]
    tm[:, n] = 0.0
    num = np.zeros(8, dtype=f32)
    for il in range(1, MAXLDV + 1):
        k = MPGMAP[il]
        if mc_[il, n] > 0.0:
            tm[k, n] = tm[k, n] + fsum(cs[1:CARGRP, :, yrs, il]) / mc_[il, n]
        if mt_[il, n] > 0.0:
            tm[k, n] = tm[k, n] + fsum(cs[LTKGRP:MAXGROUP, :, yrs, il]) / mt_[il, n]
        num[k] = num[k] + fsum(cs[1:MAXGROUP, :, yrs, il])
    nclt, csal = s["ncltmpg"], s["cltsalt"]
    for il in range(1, 13):
        k = MPGMAP_CLT[il]
        if nclt[n, il] > 0.0:
            tm[k, n] = tm[k, n] + csal[il, n] / f32(1000000) / nclt[n, il]
        if nclt[n, il] > 0.0:
            num[k] = num[k] + csal[il, n] / f32(1000000)
    for k in range(1, 8):
        if tm[k, n] > 0.0:
            tm[k, n] = num[k] / tm[k, n]
    sm = s["stkmpg"]
    sm[:, n] = 0.0
    num[:] = 0.0
    hhl, fll = s["hhmpgstk_ldv"], s["fltmpgstk_ldv"]
    for il in range(1, MAXLDV + 1):
        k = MPGMAP[il]
        if hhl[il, n] > 0.0:
            v = fsum(bstk[1:2, il, 1:MAXAGE, 1, R9])
            sm[k, n] = sm[k, n] + v / hhl[il, n]
            num[k] = num[k] + v
        if fll[il, n] > 0.0:
            v = fsum(bfv[1:2, :, il])
            sm[k, n] = sm[k, n] + v / fll[il, n]
            num[k] = num[k] + v
    bcv, cmpg = s["bcltvmt"], s["cltmpg"]
    for il in range(1, 13):
        k = MPGMAP_CLT[il]
        if cmpg[n, il] > 0.0:
            sm[k, n] = sm[k, n] + bcv[il, n] / cmpg[n, il]
            num[k] = num[k] + bcv[il, n]
    for k in range(1, 8):
        if sm[k, n] > 0.0:
            sm[k, n] = num[k] / sm[k, n]

    c2, t2, l2 = carry["cmpg_2"], carry["tmpg_2"], carry["lmpg_2"]
    c1, t1_, l1 = (np.zeros(MAXLDV + 1, dtype=f32) for _ in range(3))
    tot_v = np.zeros((MAXVTYP + 1, MAXLDV + 1), dtype=f32)
    hmpg, vsh = s["hhmpgstk"], s["vmt_stk_hh"]
    fvmt, fgge = s["fltechvmt"], s["fltechgge"]
    for il in range(1, MAXLDV + 1):
        n1 = d1 = n2 = d2 = f32(0.0)
        for ia in range(1, MAXAGE + 1):
            for iv in (1, 2):
                for r in range(1, MNUMCR - 1):
                    m = hmpg[r, iv, il, ia, n]
                    if m != 0.0:
                        x = vsh[iv, il, ia, 1, r]
                        if iv == 1:
                            n1, d1 = n1 + x, d1 + (x / m)
                        else:
                            n2, d2 = n2 + x, d2 + (x / m)
        n1 = n1 + fsum(fvmt[MNUMCR, 1, FL, il, H]) / f32(1000000.0)
        n2 = n2 + fsum(fvmt[MNUMCR, 2, FL, il, H]) / f32(1000000.0)
        d1 = d1 + fsum(fgge[MNUMCR, 1, FL, il, n])
        d2 = d2 + fsum(fgge[MNUMCR, 2, FL, il, n])
        n3, d3 = n1 + n2, d1 + d2
        if d1 != 0.0:
            c1[il] = n1 / d1
        if d2 != 0.0:
            t1_[il] = n2 / d2
        if d3 != 0.0:
            l1[il] = n3 / d3
        for iv in (1, 2):
            tot_v[iv, il] = fsum(vsh[iv, il, 1:MAXAGE, 1, MNUMCR]) + (fsum(fvmt[MNUMCR, iv, FL, il, H]) / f32(1000000.0))
    s1, s2 = fsum(tot_v[1, 1:]), fsum(tot_v[2, 1:])
    for il in range(1, MAXLDV + 1):
        if c1[il] != 0.0:
            c2[il] = (tot_v[1, il] / s1) / c1[il]
        if t1_[il] != 0.0:
            t2[il] = (tot_v[2, il] / s2) / t1_[il]
        if l1[il] != 0.0:
            l2[il] = (fsum(tot_v[1:, il]) / (s1 + s2)) / l1[il]
    mf = s["trldmpgf"]
    mf[1, n] = ONE / fsum(c2[1:])
    mf[2, n] = ONE / fsum(t2[1:])
    mf[3, n] = ONE / fsum(l2[1:])
    bv = s["bvmtech"]
    for il in range(1, MAXLDV + 1):
        s["trldvmt"][il, n] = bv[il, MNUMCR] + fsum(bfv[V, FL, il])
    lic = s["licdriver"]
    vmte[1, n] = fsum(bv[1:MAXLDV, MNUMCR]) + fsum(bfv[V, FL, L])
    lic_us = fsum(lic[1:AGEGRP, 1:MF, 11, n])
    vmte[2, n] = vmte[1, n] / lic_us
    vmte[3, n] = lic_us
    vmte[4, n] = s["pmgtr"][11, n]
    vmte[5, n] = s["mpghh"][n]
    vmte[6, n] = s["costmi"][MNUMCR, n]
    vmte[7, n] = fsum(lic[1:AGEGRP, 1:MF, R9, n]) / fsum(s["tmc_np15a"][1:AGEGRP, 1:MF, R9, n])
    vmte[8, n] = s["mc_ypdr"][11, n] / s["mc_np16a"][11, n]
    vmte[9, n] = s["ie"][n]
    vmte[10, n] = fsum(lic[1:AGEGRP, 2, 11, n]) / fsum(lic[1:AGEGRP, 1:MF, 11, n])
    vmte[11, n] = vmte[1, n] / fsum(s["vstk"][1:MAXVTYP, 1:MAXLDV])
    vmte[12, n] = 1.0
    tcs, tts, csalt = s["tncsale"], s["tntsale"], s["cltsalt"]
    shr = (tcs[11, n] + tts[11, n]) / (tcs[11, n] + tts[11, n] + (fsum(csalt[1:12, n]) * f32(.000001)))
    ldv_mpg, nt = s["ldv_mpg"], s["ncltmpgt"][n]
    ldv_mpg[1, n] = ONE / (shr / s["cafestd"][3, n] + (ONE - shr) / nt)
    ldv_mpg[2, n] = ONE / (shr / s["truempg"][3, n] + (ONE - shr) / nt)
    shr = vmte[1, n] / (vmte[1, n] + fsum(bcv[1:12, n]))
    ldv_mpg[3, n] = ONE / (shr / mf[3, n] + (ONE - shr) / s["cltmpgt"][n])
    s.update({"ildv": MAXLDV + 1, "icl": MAXCLASS + 1, "iregn": MNUMCR - 1, "iage": MAXAGE + 1,
              "ivtyp": MAXVTYP + 1, "ifuel": MAXFUEL + 1})


def tran_tail(s: dict) -> None:
    """TRAN after TREPORT."""
    n = int(s["n"])
    yrs = int(s["yrs"])
    s["qgftr"][A11, n] = s["qngtr"][A11, n]
    benng = s["benng"][A11, n]
    s["qgftrpv"][A11, n] = s["qgftrpv"][A11, n] + s["tqldv"][4, A11, n] * benng
    bus = s["qmtbr"]
    s["qgftrfv"][A11, n] = s["qgftrfv"][A11, n] + (s["fltfuelbtu"][A11, 4, n] + bus[1, 5, A11, n] + bus[2, 5, A11, n]
                                                   + bus[3, 5, A11, n]) * benng
    brs, ship, rail, qrs = s["benrs"][A11, n], s["tqishipr"][5, A11, n], s["tqrailr"][2, A11, n], s["qrstr"][A11, n]
    zero = f32(0.0)
    s["qrhtr"][A11, n] = qrs - np.maximum(zero, brs * ship) - np.maximum(zero, brs * rail)
    s["qrltr"][A11, n] = np.maximum(zero, brs * ship) + np.maximum(zero, brs * rail)
    car, trk, veh = s["avg_prc_car"], s["avg_prc_trk"], s["avg_prc_veh"]
    car[n] = trk[n] = veh[n] = 0.0
    cs = ts = f32(0.0)
    pri, sal = s["ldvpri"], s["totalsalsc"]
    for icl in range(1, MAXCLASS + 1):
        for il in range(1, MAXLDV + 1):
            if pri[1, il, icl, yrs] > 0.0:
                car[n] = car[n] + pri[1, il, icl, yrs] * sal[1, icl, il, n]
                cs = cs + sal[1, icl, il, n]
            if pri[2, il, icl, yrs] > 0.0:
                trk[n] = trk[n] + pri[2, il, icl, yrs] * sal[2, icl, il, n]
                ts = ts + sal[2, icl, il, n]
    s["carsales"], s["trksales"] = cs, ts
    veh[n] = ((car[n] + trk[n]) / (cs + ts)) / f32(1000.0)
    car[n] = (car[n] / cs) / f32(1000.0)
    trk[n] = (trk[n] / ts) / f32(1000.0)
    s["full_prc_veh"][n] = veh[n]
    s["full_prc_car"][n] = car[n]
    s["full_prc_trk"][n] = trk[n]
    for name, src, k in (("qgftrrail", "btqrailr", 3), ("qgltrrail", "btqrailr", 4)):
        s[name][1, A11, n] = s[src][k, A11]
        s[name][2:4, A11, n] = 0.0
    for name, k in (("qgftrship", 3), ("qgltrship", 4)):
        s[name][1, A11, n] = s["btqdshipr"][k, A11]
        s[name][2, A11, n] = s["btqishipr"][k, A11]
        s[name][3, A11, n] = 0.0
    s.update({"icl": MAXCLASS + 1, "ildv": MAXLDV + 1})
