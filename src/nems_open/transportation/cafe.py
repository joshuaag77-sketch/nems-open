"""CAFE and GHG compliance (tran.f): CAFECALC.

Footprint-based GHG (g/mi) and CAFE (mpg) targets by group, each group's
achieved values with EV multipliers, off-cycle and AC credits, pass/fail, credit
banking (five-year carry-forward), and the new-vehicle averages the rest of the
model reads: true and adjusted MPG, MPG by fuel and region, degradation factors,
technology penetration and cost, and sales-weighted MPG, price, range, weight
and horsepower.
"""

import numpy as np

from nems_open.transportation.common import expf, f32, fsum, MAXLDV, MAXVTYP, MNUMCR
from nems_open.transportation.mean_funcs import harmonic_mean as hmean
from nems_open.transportation.mean_funcs import weighted_mean as wmean

CURRENT = 2
GAS = 1
MAXCLASS = 8
MAXGROUP = 11
CARGRP = 5
LTKGRP = 6
XYR = 2022
MAXTECH = 71
R9 = slice(1, MNUMCR - 2)
ONE = f32(1.0)
CARS, TRKS = slice(1, CARGRP), slice(LTKGRP, MAXGROUP)
G, C, L = slice(1, MAXGROUP), slice(1, MAXCLASS), slice(1, MAXLDV)


def _ghg(s, n, yrs):
    cafe, fpr = s["cafesales"], s["fprint"]
    fpg, grp = s["fpghg"], s["fpghggrp"]
    fpg[C, G, n] = 0.0
    cars_on = fsum(cafe[CARS, C, yrs, L], axis=2).T > 0.0
    trks_on = fsum(cafe[TRKS, C, yrs, L], axis=2).T > 0.0
    k = lambda name: s[name][n]  # noqa: E731
    car = np.minimum(k("cfcoefepab2"), np.maximum(k("cfcoefepaa2"), k("cfcoefepac2") * fpr[C, CARS, n] + k("cfcoefepad2")))
    fpg[C, CARS, n] = np.where(cars_on, car, fpg[C, CARS, n])
    t1 = np.minimum(k("tfcoefepab2"), np.maximum(k("tfcoefepaa2"), k("tfcoefepac2") * fpr[C, TRKS, n] + k("tfcoefepad2")))
    t2 = np.minimum(k("tfcoefepaf2"), np.maximum(k("tfcoefepae2"), k("tfcoefepag2") * fpr[C, TRKS, n] + k("tfcoefepah2")))
    fpg[C, TRKS, n] = np.where(trks_on, np.minimum(t1, t2), fpg[C, TRKS, n])
    for jgp in range(1, MAXGROUP + 1):
        grp[jgp, n] = wmean(fpg[C, jgp, n], fsum(cafe[jgp, C, yrs, L], axis=1), "FPghgGrp(CAFECALC)")

    regs27 = int(s["enforce_my27regs"]) == 1 and yrs >= 2027
    mpg, evmt, mpg_s = s["femmpg"], s["phev_evmt"], s["phevmpg_s"]
    epag = s["epaghggrp"]
    g8887 = f32(8887.0)
    for jgp in range(1, MAXGROUP + 1):
        ac = s["ac_oc_credit"][jgp, n] * g8887
        num = f32(0.0)
        for ildv in range(1, MAXLDV + 1):
            for icl in range(1, MAXCLASS + 1):
                m = mpg[jgp, icl, yrs, ildv]
                if m == 0.0:
                    continue
                sal = cafe[jgp, icl, yrs, ildv]
                zero_tail = (4, 7, 15) if jgp <= CARGRP else (4, 7, 15, 14)
                if regs27 and ildv in (4, 7, 15):
                    continue
                if ildv in zero_tail:
                    num = num + sal * (-ac)
                elif ildv in (5, 6):
                    num = num + sal * (ONE - evmt[jgp, icl, yrs, ildv]) * (ONE / mpg_s[jgp, icl, yrs, ildv] * g8887 - ac)
                elif jgp > CARGRP and yrs == 2024 and icl == 2 and ildv == 16:
                    num = num + sal * (ONE / m * g8887 - ac - s["pu_cred_elig"][jgp] * f32(20.0))
                else:
                    num = num + sal * (ONE / m * g8887 - ac)
        alt = [4, 7, 15, 14]
        den = fsum(np.array([fsum(cafe[jgp, C, yrs, k]) for k in alt], dtype=f32)
                   * (np.array([s["epaaltmult"][k, n] for k in alt], dtype=f32) - ONE))
        epag[jgp, n] = num / (fsum(cafe[jgp, C, yrs, L]) + den) - s["ac_co2_offset"][jgp, n]
    s.update(ildv=MAXLDV + 1, icl=MAXCLASS + 1)
    life = s["ldv_vehlifemi"]
    mg = s["mgghggrp"]
    mg[CARS, n] = (grp[CARS, n] - epag[CARS, n]) * fsum(fsum(cafe[CARS, C, yrs, L], axis=2), axis=1) * life[1]
    mg[TRKS, n] = (grp[TRKS, n] - epag[TRKS, n]) * fsum(fsum(cafe[TRKS, C, yrs, L], axis=2), axis=1) * life[2]


def cafecalc(s: dict, cafetestcall: int) -> None:
    n, yrs, epa = int(s["n"]), int(s["yrs"]), int(s["epalyr"])
    cafe, mpg = s["cafesales"], s["femmpg"]
    for k in ("fpghggrp", "mgghggrp", "epaghggrp"):
        s[k][G, n] = 0.0
    if int(s["enforce_epa"]) == 1 and yrs >= 2012:
        _ghg(s, n, yrs)

    if yrs >= 2010:
        fpm, fpr = s["fpmpg"], s["fprint"]
        fpm[C, G, n] = 0.0
        k = lambda name: s[name][n]  # noqa: E731
        if yrs < 2012:
            for grp, p in ((CARS, "cf"), (TRKS, "tf")):
                x = fpr[C, grp, n]
                e = expf((x - k(p + "coefc")) / k(p + "coefd"))
                v = ONE / ((ONE / k(p + "coefa")) + (ONE / k(p + "coefb") - ONE / k(p + "coefa")) * (e / (ONE + e)))
                fpm[C, grp, n] = np.where(x != 0.0, v, fpm[C, grp, n])
        else:
            x = fpr[C, CARS, n]
            v = ONE / (np.minimum(np.maximum(((k("cfcoefc2") * x) + k("cfcoefd2")), ONE / k("cfcoefa2")), ONE / k("cfcoefb2")))
            fpm[C, CARS, n] = np.where(x != 0.0, v, fpm[C, CARS, n])
            x = fpr[C, TRKS, n]
            v1 = ONE / (np.minimum(np.maximum(((k("tfcoefc2") * x) + k("tfcoefd2")), ONE / k("tfcoefa2")), ONE / k("tfcoefb2")))
            v2 = ONE / (np.minimum(np.maximum(((k("tfcoefg2") * x) + k("tfcoefh2")), ONE / k("tfcoefe2")), ONE / k("tfcoeff2")))
            fpm[C, TRKS, n] = np.where(x != 0.0, np.maximum(v1, v2), fpm[C, TRKS, n])
        for jgp in range(1, MAXGROUP + 1):
            s["fpmpggrp"][jgp, n] = hmean(fpm[C, jgp, n], fsum(cafe[jgp, C, yrs, L], axis=1))

    used = s["cafe_used"]
    if yrs <= 2010:
        used[G, yrs] = s["cafe_stand"][G, yrs]
    if yrs >= 2011:
        used[G, yrs] = s["fpmpggrp"][G, n]
    gs, std = s["grpshare"], s["cafestd"]
    std[1, n] = hmean(used[CARS, yrs], gs[MNUMCR, CARS, n])
    std[2, n] = hmean(used[TRKS, yrs], gs[MNUMCR, TRKS, n])
    std[3, n] = hmean(std[1:2, n], s["cartrksplit"][MNUMCR, 1:2, n])

    cmg = s["cafempggrp"]
    if yrs <= epa:
        for jgp in range(1, MAXGROUP + 1):
            cmg[jgp, n] = hmean(s["mpgcomp"][jgp, C, yrs, L], cafe[jgp, C, yrs, L], s["ac_oc_credit_expanded"][jgp, C, L, n])
    else:
        cred = s["ac_oc_credit_expanded_adj" if int(s["enforce_my27regs"]) == 1 and yrs >= 2027 else "ac_oc_credit_expanded"]
        for jgp in range(1, MAXGROUP + 1):
            cmg[jgp, n] = hmean(mpg[jgp, C, yrs, L] * s["cafepefmult_expanded"][jgp, C, L, n], cafe[jgp, C, yrs, L], cred[jgp, C, L, n])

    cpass = s["cafepass"]
    if cafetestcall == 0:
        for jgp in range(1, MAXGROUP + 1):
            ok = not (cmg[jgp, n] < used[jgp, yrs])
            if int(s["enforce_epa"]) == 1 and s["mgghggrp"][jgp, n] < 0.0:
                ok = False
            cpass[jgp] = int(ok)
        s["ivtyp"] = int(s["grpmap"][MAXGROUP])

    if int(s["ibank"]) == 1 and yrs >= epa:
        _bank(s, n, yrs, epa)
    s["bankbal"][G, yrs] = fsum(s["cafebank"][1:5, G], axis=0)

    if cafetestcall == 1 or yrs <= epa + 1:
        _averages(s, n, yrs, epa)


def _bank(s, n, yrs, epa):
    """Five-year CAFE credit bank: a failing group draws down its oldest credits first."""
    cmg, used, cpass = s["cafempggrp"], s["cafe_used"], s["cafepass"]
    work, bank, banka = s["cafework"], s["cafebank"], s["cafebanka"]
    fem_pass, curitr = int(s["fem_pass"]), int(s["curitr"])
    for jgp in range(1, MAXGROUP + 1):
        if yrs == epa:
            work[1:4, jgp] = 0.0
            banka[jgp] = 0.0
            if cmg[jgp, n] > used[jgp, yrs]:
                banka[jgp] = cmg[jgp, n] - used[jgp, yrs]
            for i in range(1, 5):
                if cmg[jgp, n - i] > used[jgp, yrs - i]:
                    work[i, jgp] = cmg[jgp, n - i] - used[jgp, yrs - i]
            s["i"] = 5
        if fem_pass == 1 and curitr == 1:
            for i in range(5, 1, -1):
                bank[i, jgp] = work[i - 1, jgp]
            bank[1, jgp] = banka[jgp]
            banka[jgp] = 0.0
        if fem_pass == 1:
            work[1:5, jgp] = bank[1:5, jgp]
            if cpass[jgp]:
                banka[jgp] = cmg[jgp, n] - used[jgp, yrs]
            else:
                need = used[jgp, yrs] - cmg[jgp, n]
                for i in range(5, 0, -1):
                    if need > 0.0:
                        if need <= work[i, jgp]:
                            work[i, jgp] = work[i, jgp] - need
                            need = f32(0.0)
                            cpass[jgp] = 1
                        else:
                            need = need - work[i, jgp]
                            work[i, jgp] = 0.0
                s["i"] = 0
                s["cafeneed"] = need
                if need == 0.0:
                    cpass[jgp] = 1
                    cmg[jgp, n] = used[jgp, yrs]


def _averages(s, n, yrs, epa):
    cafe, mpg, sales = s["cafesales"], s["femmpg"], s["ldv_sales"]
    true, adjm, madj = s["truempg"], s["adjmpg"], s["mpgadj"]
    true[1, n] = hmean(mpg[CARS, C, yrs, L], cafe[CARS, C, yrs, L])
    true[2, n] = hmean(mpg[TRKS, C, yrs, L], cafe[TRKS, C, yrs, L])
    true[3, n] = hmean(mpg[G, C, yrs, L], cafe[G, C, yrs, L])
    deggrp = s["degfacgrp"]
    if yrs > epa:
        madj[G, C, yrs, L] = mpg[G, C, yrs, L] * deggrp[G, C, L, n]
    adjm[1, n] = hmean(madj[CARS, C, yrs, L], cafe[CARS, C, yrs, L])
    adjm[2, n] = hmean(madj[TRKS, C, yrs, L], cafe[TRKS, C, yrs, L])
    adjm[3, n] = hmean(madj[G, C, yrs, L], cafe[G, C, yrs, L])

    new = s["ldvmpgnew"]
    new[:, :, :, n] = 0.0
    for ildv in range(1, MAXLDV + 1):
        new[MNUMCR, 1, ildv, n] = hmean(mpg[CARS, C, yrs, ildv], cafe[CARS, C, yrs, ildv])
        new[MNUMCR, 2, ildv, n] = hmean(mpg[TRKS, C, yrs, ildv], cafe[TRKS, C, yrs, ildv])
    if yrs <= 2018:
        new[R9, 1:MAXVTYP, L, n] = np.broadcast_to(new[MNUMCR, 1:MAXVTYP, L, n], (MNUMCR - 2, MAXVTYP, MAXLDV))
    if yrs >= 2019:
        treg = s["truempg_regn"]
        for iregn in range(1, MNUMCR - 1):
            for ildv in range(1, MAXLDV + 1):
                new[iregn, 1, ildv, n] = hmean(mpg[CARS, C, yrs, ildv], sales[CARS, C, ildv, iregn, n])
                new[iregn, 2, ildv, n] = hmean(mpg[TRKS, C, yrs, ildv], sales[TRKS, C, ildv, iregn, n])
            treg[iregn, 1, n] = hmean(new[iregn, 1, L, n], fsum(fsum(sales[CARS, C, L, iregn, n], axis=0), axis=0))
            treg[iregn, 2, n] = hmean(new[iregn, 2, L, n], fsum(fsum(sales[TRKS, C, L, iregn, n], axis=0), axis=0))
        s["iregn"] = MNUMCR - 1

    deg, degrpt = s["degfac"], s["degrpt"]
    if yrs <= epa:
        adjldv = {}
        for ildv in range(1, MAXLDV + 1):
            adjldv[1, ildv] = hmean(madj[CARS, C, yrs, ildv], cafe[CARS, C, yrs, ildv])
            adjldv[2, ildv] = hmean(madj[TRKS, C, yrs, ildv], cafe[TRKS, C, yrs, ildv])
        for ivtyp in range(1, MAXVTYP + 1):
            degrpt[ivtyp, n] = adjm[ivtyp, n] / true[ivtyp, n]
            for ildv in range(1, MAXLDV + 1):
                deg[ivtyp, ildv, n] = 0.0
                if new[MNUMCR, ivtyp, ildv, n] != 0.0:
                    deg[ivtyp, ildv, n] = adjldv[ivtyp, ildv] / new[MNUMCR, ivtyp, ildv, n]
                if deg[ivtyp, ildv, n - 1] > 0.0 and deg[ivtyp, ildv, n] == 0.0:
                    deg[ivtyp, ildv, n] = deg[ivtyp, ildv, n - 1]
                if deg[ivtyp, ildv, n] == 0.0:
                    deg[ivtyp, ildv, n] = degrpt[ivtyp, n]
        s["ivtyp"] = MAXVTYP + 1
        on = mpg[G, C, yrs, L] != 0.0
        with np.errstate(divide="ignore", invalid="ignore"):
            deggrp[G, C, L, n] = np.where(on, madj[G, C, yrs, L] / mpg[G, C, yrs, L], deggrp[G, C, L, n])
        for ildv in range(1, MAXLDV + 1):
            deggrp[CARS, C, ildv, n] = np.where(deggrp[CARS, C, ildv, n] == 0.0, deg[1, ildv, n], deggrp[CARS, C, ildv, n])
            deggrp[TRKS, C, ildv, n] = np.where(deggrp[TRKS, C, ildv, n] == 0.0, deg[2, ildv, n], deggrp[TRKS, C, ildv, n])
    else:
        degrpt[1:MAXVTYP, n] = adjm[1:MAXVTYP, n] / true[1:MAXVTYP, n]
        deg[1:MAXVTYP, L, n] = deg[1:MAXVTYP, L, n - 1]
        deggrp[G, C, L, n] = deggrp[G, C, L, n - 1]

    cmg, newmpg = s["cafempggrp"], s["newmpg"]
    newmpg[1, n] = hmean(cmg[CARS, n], fsum(fsum(cafe[CARS, C, yrs, L], axis=1), axis=1))
    newmpg[2, n] = hmean(cmg[TRKS, n], fsum(fsum(cafe[TRKS, C, yrs, L], axis=1), axis=1))
    newmpg[3, n] = hmean(cmg[G, n], fsum(fsum(cafe[G, C, yrs, L], axis=1), axis=1))
    A = slice(3, MAXLDV)
    for icl in range(1, MAXCLASS + 1):
        s["treffaltc"][icl, n] = hmean(mpg[CARS, icl, yrs, A], cafe[CARS, icl, yrs, A])
        s["treffaltt"][icl, n] = hmean(mpg[TRKS, icl, yrs, A], cafe[TRKS, icl, yrs, A])
    s["treffaltc"][MAXCLASS + 1, n] = hmean(mpg[CARS, C, yrs, A], cafe[CARS, C, yrs, A])
    s["treffaltt"][MAXCLASS + 1, n] = hmean(mpg[TRKS, C, yrs, A], cafe[TRKS, C, yrs, A])

    if yrs >= XYR:
        _tech_report(s, n, yrs)

    lmpg, lpri, lrng, wgt = s["ldvmpg"], s["ldvpri"], s["ldvrng"], s["wgt"]
    pri, rng, fw, fh = s["fempri"], s["femrng"], s["femwgt"], s["femhp"]
    for icl in range(1, MAXCLASS + 1):
        for ildv in range(1, MAXLDV + 1):
            for t, grp in ((1, CARS), (2, TRKS)):
                w = cafe[grp, icl, yrs, ildv]
                lmpg[t, ildv, icl, yrs] = hmean(mpg[grp, icl, yrs, ildv], w)
                lpri[t, ildv, icl, yrs] = wmean(pri[grp, icl, yrs, ildv], w, "LDVPRI")
                lrng[t, ildv, icl, yrs] = wmean(rng[grp, icl, yrs, ildv], w, "LDVRNG")
                wgt[t, ildv, icl, yrs] = wmean(fw[grp, icl, yrs, ildv], w, "WGT")
    s.update(icl=MAXCLASS + 1, ildv=MAXLDV + 1)
    for key, arr, grp in (("awtcar", fw, CARS), ("awttruck", fw, TRKS), ("ahpcar", fh, CARS), ("ahptruck", fh, TRKS)):
        s[key][MNUMCR, n] = wmean(arr[grp, C, yrs, L], cafe[grp, C, yrs, L], key.upper())
    if yrs < 2019:
        for key in ("ahpcar", "ahptruck", "awtcar", "awttruck"):
            s[key][R9, n] = s[key][MNUMCR, n]
    else:
        for iregn in range(1, MNUMCR - 1):
            for key, arr, grp in (("awtcar", fw, CARS), ("awttruck", fw, TRKS), ("ahpcar", fh, CARS), ("ahptruck", fh, TRKS)):
                s[key][iregn, n] = wmean(arr[grp, C, yrs, L], sales[grp, C, L, iregn, n], key.upper())
        s["iregn"] = MNUMCR - 1
    tot = s["totalsalsc"]
    tot[1, C, L, n] = fsum(cafe[CARS, C, yrs, L], axis=0)
    tot[2, C, L, n] = fsum(cafe[TRKS, C, yrs, L], axis=0)
    for ivtyp in range(1, MAXVTYP + 1):
        s["expendveh"][ivtyp, n] = fsum(tot[ivtyp, C, L, n] * lpri[ivtyp, L, C, yrs].T)
    s["ivtyp"] = MAXVTYP + 1


def _tech_report(s, n, yrs):
    numtech = int(s["numtech"])
    T = slice(1, numtech)
    mdp, avg = s["mkt_d_p"], s["avgcost"]
    if yrs == XYR:
        mdp[1:3, 1:MAXTECH, :] = 0.0
        avg[1:3, 1:MAXTECH, :] = 0.0
    else:
        mdp[1:3, 1:MAXTECH, yrs] = 0.0
        avg[1:3, 1:MAXTECH, yrs] = 0.0
    pen, cs, tec = s["mkt_pen"], s["class_share"], s["tec_ornl"]
    penf, avc = s["mkt_penf"], s["avcost"]
    share = cs[MNUMCR, C, G, yrs]                                            # (class, group)
    for itech in range(1, numtech + 1):
        for ildv in range(1, MAXLDV + 1):
            penf[G, itech, ildv] = fsum(pen[G, C, itech, CURRENT, ildv] * share.T * f32(100.0), axis=1)
            avc[G, itech, ildv] = fsum(tec[C, G, itech, ildv] * share, axis=0)
    s.update(itech=numtech + 1, ildv=MAXLDV + 1)
    gs, split = s["grpshare"], s["cartrksplit"]
    for jgp in range(1, MAXGROUP + 1):
        it = int(s["grpmap"][jgp])
        mdp[it, T, yrs] = mdp[it, T, yrs] + (penf[jgp, T, GAS] * gs[MNUMCR, jgp, n])
        avg[it, T, yrs] = avg[it, T, yrs] + (avc[jgp, T, GAS] * gs[MNUMCR, jgp, n])
    mdp[3, T, yrs] = mdp[1, T, yrs] * split[MNUMCR, 1, n] + mdp[2, T, yrs] * split[MNUMCR, 2, n]
    avg[3, T, yrs] = avg[1, T, yrs] * split[MNUMCR, 1, n] + avg[2, T, yrs] * split[MNUMCR, 2, n]
    micro = s["micropen"]
    for ildv in range(1, MAXLDV + 1):
        micro[1, ildv, n] = fsum(fsum(np.stack([penf[CARS, 64, ildv], penf[CARS, 65, ildv]], axis=1), axis=1) / f32(100) * gs[MNUMCR, CARS, n])
        micro[2, ildv, n] = fsum(fsum(np.stack([penf[TRKS, 64, ildv], penf[TRKS, 65, ildv]], axis=1), axis=1) / f32(100) * gs[MNUMCR, TRKS, n])
