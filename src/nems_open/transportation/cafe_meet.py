"""CAFEGHG_MEET and RSORT_SMALL (tran.f): forced compliance after the FEM passes.

A group that still fails moves sales from gasoline to plug-in hybrids and battery
EVs, most cost-effective first, size class by size class in a fixed order, a step
at a time, until it or the whole market meets CAFE and GHG.

EIA passes a REAL array (the powertrain order) to RSORT_SMALL's INTEGER argument.
The sort only copies the values, so the result is the same as sorting them as
numbers; kept as noted in SCOPE.md.
"""

import numpy as np

from nems_open.transportation.cafe import C, CARGRP, CARS, G, GAS, L, LTKGRP, MAXCLASS, MAXGROUP, ONE, R9, TRKS
from nems_open.transportation.common import MAXLDV, MNUMCR, f32, fsum
from nems_open.transportation.mean_funcs import harmonic_mean as hmean

CAFEVEH = [6, 7, 15]          # PHEV50, EV200, EV300: the powertrains added to meet the rules
CARCLS = [7, 8, 4, 3, 2, 5, 6, 1]
TRKCLS = [7, 8, 2, 5, 6, 4, 3, 1]
PAYB = 5
MAXPASS = 15


def rsort_small(s, a, idx):
    """Insertion sort, ascending, carrying idx along. Uses the module's I and J."""
    q = len(a)
    for i in range(2, q + 1):
        t, ti = a[i - 1], idx[i - 1]
        j = i - 1
        while j >= 1 and not (a[j - 1] <= t):
            a[j], idx[j] = a[j - 1], idx[j - 1]
            j -= 1
        a[j], idx[j] = t, ti
        s["j"] = j
    s["i"] = q + 1


def group_ghg(s, igp, n, yrs):
    """One group's achieved GHG rate, as CAFECALC computes it."""
    cafe, mpg, evmt, mpg_s = s["cafesales"], s["femmpg"], s["phev_evmt"], s["phevmpg_s"]
    regs27 = int(s["enforce_my27regs"]) == 1 and yrs >= 2027
    g8887 = f32(8887.0)
    ac = s["ac_oc_credit"][igp, n] * g8887
    zero_tail = [4, 7, 15] if igp <= CARGRP else [4, 7, 15, 14]
    # Every (fuel, class) term at once, as (ILDV, ICL); the sum runs in the loop's order
    # (ILDV outer, ICL inner) over the terms the loop counts.
    m, sal = mpg[igp, C, yrs, L].T, cafe[igp, C, yrs, L].T
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        term = sal * (((ONE / m) * g8887) - ac)
        term[4:6] = (sal[4:6] * (ONE - evmt[igp, C, yrs, 5:6].T)) * (((ONE / mpg_s[igp, C, yrs, 5:6].T) * g8887) - ac)
        term[[k - 1 for k in zero_tail]] = sal[[k - 1 for k in zero_tail]] * (-ac)
        if igp > CARGRP and yrs == 2024:
            term[15, 1] = sal[15, 1] * ((((ONE / m[15, 1]) * g8887) - ac) - s["pu_cred_elig"][igp] * f32(20.0))
    keep = m != 0.0
    if regs27:
        keep[[3, 6, 14]] = False
    num = fsum(term[keep])
    alt = [4, 7, 15, 14]
    den = fsum(np.array([fsum(cafe[igp, C, yrs, k]) for k in alt], dtype=f32)
               * (np.array([s["epaaltmult"][k, n] for k in alt], dtype=f32) - ONE))
    s["epaghggrp"][igp, n] = num / (fsum(cafe[igp, C, yrs, L]) + den) - s["ac_co2_offset"][igp, n]
    s.update(ildv=MAXLDV + 1, icl=MAXCLASS + 1)


def _deltas(s, n, yrs):
    """Sales moved per step for each failing group and class (first call of a CAFE test pass)."""
    cafe, mpg, cpass = s["cafesales"], s["femmpg"], s["cafepass"]
    by = np.zeros((MAXGROUP + 1, MAXCLASS + 1), dtype=f32)
    delta = s.setdefault("_cafeghg_delta", np.zeros((MAXGROUP + 1, MAXCLASS + 1), dtype=f32))
    delta[...] = 0.0
    for jgp in range(1, MAXGROUP + 1):
        for icl in range(1, MAXCLASS + 1):
            if fsum(np.array([mpg[jgp, icl, yrs, k] for k in CAFEVEH], dtype=f32)) > 0.0 and not cpass[jgp]:
                by[jgp, icl] = by[jgp, icl] + cafe[jgp, icl, yrs, 1]
    tot = fsum(by[1:, 1:].T)
    step = ONE / f32(MAXPASS) * s["maxadj_cafetest"]
    for jgp in range(1, MAXGROUP + 1):
        if cpass[jgp]:
            continue
        for icl in range(1, MAXCLASS + 1):
            delta[jgp, icl] = step * by[jgp, icl] / tot
    if int(s["enforce_epa"]) == 1:
        delta[...] = 0.0
        deficit = np.zeros(MAXGROUP + 1, dtype=f32)
        for jgp in range(1, MAXGROUP + 1):
            if not cpass[jgp]:
                deficit[jgp] = deficit[jgp] + s["mgghggrp"][jgp, n]
        dtot = fsum(deficit[1:])
        by_grp = fsum(by[1:, 1:], axis=1)
        for jgp in range(1, MAXGROUP + 1):
            if cpass[jgp]:
                continue
            for icl in range(1, MAXCLASS + 1):
                delta[jgp, icl] = step * deficit[jgp] / dtot * by[jgp, icl] / by_grp[jgp - 1]
    s["icl"] = MAXCLASS + 1
    s["first_time_cafetest"] = 0


def cafeghg_meet(s: dict) -> None:
    n, yrs, epa = int(s["n"]), int(s["yrs"]), int(s["epalyr"])
    igp = int(s["igp"])
    cafe, mpg, pri, cpass = s["cafesales"], s["femmpg"], s["fempri"], s["cafepass"]
    if s["first_time_cafetest"]:
        _deltas(s, n, yrs)
    delta = s["_cafeghg_delta"]

    old = s["avsales_old"]
    old[G, C, L, n] = cafe[G, C, yrs, L]
    vmt = s["vmt"]
    vsrc = s["pvmt"] if igp <= CARGRP else s["lvmt"]
    vmt[1:PAYB, MNUMCR] = vsrc[1:PAYB, 2024 - 1989, MNUMCR, 1]
    disc = np.array([np.float64(f32(1.07)) ** -np.float64(i) for i in range(1, PAYB + 1)])
    fp = s["fprice"][1, MNUMCR, yrs]
    factor = {k: {icl: f32(-50000.0) for icl in range(1, MAXCLASS + 1)} for k in CAFEVEH}
    for xldv in CAFEVEH:
        for icl in range(1, MAXCLASS + 1):
            if mpg[igp, icl, yrs, xldv] != 0.0:
                d = (ONE / mpg[igp, icl, yrs, GAS] - ONE / mpg[igp, icl, yrs, xldv])
                terms = (vmt[1:PAYB, MNUMCR] * d * fp).astype(np.float64) * disc
                acc = np.float64(0.0)
                for t in terms:
                    acc += t
                factor[xldv][icl] = f32(acc) - (pri[igp, icl, yrs, xldv] - pri[igp, icl, yrs, GAS])
    s["icl"] = MAXCLASS + 1
    order = {}
    for icl in range(1, MAXCLASS + 1):
        a = [f32(-1.0) * factor[k][icl] for k in CAFEVEH]
        idx = list(CAFEVEH)
        rsort_small(s, a, idx)
        order[icl] = idx

    s["mgghggrp"][igp, n] = 0.0
    regs27 = int(s["enforce_my27regs"]) == 1 and yrs >= 2027
    cred = s["ac_oc_credit_expanded_adj" if regs27 else "ac_oc_credit_expanded"]
    cmg, used, std, newmpg = s["cafempggrp"], s["cafe_used"], s["cafestd"], s["newmpg"]
    mg, fpg, epag = s["mgghggrp"], s["fpghggrp"], s["epaghggrp"]
    avail = s["mmavail"]
    done = False
    for xcl in range(1, MAXCLASS + 1):
        if cpass[igp] or done:
            break
        ycl = CARCLS[xcl - 1] if igp <= CARGRP else TRKCLS[xcl - 1]
        if not old[igp, ycl, GAS, n] > 0.0:
            continue
        for xldv in order[ycl]:
            if not fsum(avail[igp, xldv, ycl, R9, yrs]) > 0.0:
                continue
            stop_gas = 0
            for _ in range(MAXPASS):
                if stop_gas == 0:
                    dl = delta[igp, ycl]
                    cafe[igp, ycl, yrs, 1] = cafe[igp, ycl, yrs, 1] - dl
                    cafe[igp, ycl, yrs, xldv] = cafe[igp, ycl, yrs, xldv] + dl
                    if cafe[igp, ycl, yrs, 1] <= 0.0:
                        cafe[igp, ycl, yrs, 1] = cafe[igp, ycl, yrs, 1] + dl
                        cafe[igp, ycl, yrs, xldv] = cafe[igp, ycl, yrs, xldv] - dl
                        stop_gas = 1
                cmg[igp, n] = hmean(mpg[igp, C, yrs, L] * s["cafepefmult_expanded"][igp, C, L, n], cafe[igp, C, yrs, L],
                                    cred[igp, C, L, n])
                group_ghg(s, igp, n, yrs)
                # EIA quirk: lifetime miles are hard-coded here, not LDV_VEHLIFEMI as in CAFECALC.
                mg[CARS, n] = (fpg[CARS, n] - epag[CARS, n]) * fsum(fsum(cafe[CARS, C, yrs, L], axis=2), axis=1) * f32(195264.0)
                mg[TRKS, n] = (fpg[TRKS, n] - epag[TRKS, n]) * fsum(fsum(cafe[TRKS, C, yrs, L], axis=2), axis=1) * f32(225865.0)
                if yrs > epa:
                    newmpg[1, n] = hmean(cmg[CARS, n], fsum(fsum(cafe[CARS, C, yrs, L], axis=1), axis=1))
                    newmpg[2, n] = hmean(cmg[TRKS, n], fsum(fsum(cafe[TRKS, C, yrs, L], axis=1), axis=1))
                    newmpg[3, n] = hmean(cmg[G, n], fsum(fsum(cafe[G, C, yrs, L], axis=1), axis=1))
                if (cmg[igp, n] >= used[igp, yrs]
                        or (newmpg[3, n] > std[3, n] and (newmpg[1, n] - std[1, n]) > -2.0 and (newmpg[2, n] - std[2, n]) > -2.0)
                        or int(s["enforce_cafe"]) == 0):
                    tot = fsum(mg[G, n])
                    if int(s["enforce_epa"]) == 0:
                        cpass[igp], done = 1, True
                    elif tot > 0.0 or tot + s["creds_avail"] > 0.0:
                        cpass[G], done = 1, True
                    elif mg[igp, n] > 0.0 or mg[igp, n] + s["creds_avail_grp"][igp] > 0.0:
                        cpass[igp], done = 1, True
                    if done:
                        break
                if stop_gas == 1:
                    break
            if done or stop_gas == 1:
                break

    sales, shr = s["ldv_sales"], s["apshrgrp"]
    reg = np.zeros((MAXCLASS, MNUMCR - 2, MAXLDV), dtype=f32)
    for icl in range(1, MAXCLASS + 1):
        for ildv in range(1, MAXLDV + 1):
            tot = fsum(sales[igp, icl, ildv, R9, n])
            if tot != 0.0:
                reg[icl - 1, :, ildv - 1] = sales[igp, icl, ildv, R9, n] / tot
    for iregn in range(1, MNUMCR - 1):
        sales[igp, C, L, iregn, n] = cafe[igp, C, yrs, L] * reg[:, iregn - 1, :]
    sales[igp, C, L, MNUMCR, n] = fsum(sales[igp, C, L, R9, n], axis=2)
    shr[igp, C, L, MNUMCR, n] = 0.0
    for iregn in range(1, MNUMCR + 1):
        if iregn == 10:
            continue
        for icl in range(1, MAXCLASS + 1):
            tot = fsum(sales[igp, icl, L, iregn, n])
            if tot != 0.0:
                shr[igp, icl, L, iregn, n] = sales[igp, icl, L, iregn, n] / tot
    s.update(icl=MAXCLASS + 1, ildv=MAXLDV + 1, iregn=MNUMCR + 1)
