"""CAFEGHG_MEET and RSORT_SMALL (tran.f): forced compliance after the FEM passes.

A group that still fails moves sales from gasoline to plug-in hybrids and battery
EVs, most cost-effective first, size class by size class in a fixed order, a step
at a time, until it or the whole market meets CAFE and GHG.

EIA passes a REAL array (the powertrain order) to RSORT_SMALL's INTEGER argument.
The sort only copies the values, so the result is the same as sorting them as
numbers; kept as noted in SCOPE.md.
"""

import numpy as np

from nems_open.transportation.cafe import C, CARGRP, G, GAS, L, LTKGRP, MAXCLASS, MAXGROUP, ONE, R9
from nems_open.transportation.common import MAXLDV, MNUMCR, f32, fsum

CAFEVEH = [6, 7, 15]          # PHEV50, EV200, EV300: the powertrains added to meet the rules
CARCLS = [7, 8, 4, 3, 2, 5, 6, 1]
TRKCLS = [7, 8, 2, 5, 6, 4, 3, 1]
PAYB = 5
MAXPASS = 15
ZERO32 = f32(0.0)


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


def ghg_parts(s, igp, n, yrs):
    """GROUP_GHG's factors that do not depend on sales (fuel economy, credits): (ILDV, ICL)
    arrays, so each term is sales times a factor, as in the Fortran's expression."""
    mpg, evmt, mpg_s = s["femmpg"], s["phev_evmt"], s["phevmpg_s"]
    regs27 = int(s["enforce_my27regs"]) == 1 and yrs >= 2027
    g8887 = f32(8887.0)
    ac = s["ac_oc_credit"][igp, n] * g8887
    zero_tail = [k - 1 for k in ((4, 7, 15) if igp <= CARGRP else (4, 7, 15, 14))]
    m = mpg[igp, C, yrs, L].T
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        k = ((ONE / m) * g8887) - ac
        k[zero_tail] = -ac
        if igp > CARGRP and yrs == 2024:
            k[15, 1] = (((ONE / m[15, 1]) * g8887) - ac) - s["pu_cred_elig"][igp] * f32(20.0)
        k56 = ((ONE / mpg_s[igp, C, yrs, 5:6].T) * g8887) - ac
    keep = m != 0.0
    if regs27:
        keep[[3, 6, 14]] = False
    return k, ONE - evmt[igp, C, yrs, 5:6].T, k56, keep


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


def _acc(a):
    """fsum along the last axis for each row: one float32 accumulator in order, then +0."""
    return np.add.accumulate(a, axis=-1, dtype=f32)[..., -1] + ZERO32


def _hmean_rows(mpgs, weights, inv=None):
    """harmonic_mean for each row of (steps, n) arrays (inv: 1/MPG minus credits, if given)."""
    total = _acc(weights)
    valid = (mpgs != 0.0) & (weights != 0.0)
    with np.errstate(divide="ignore", invalid="ignore"):
        if inv is None:
            inv = f32(1.0) / mpgs
        num = _acc(np.where(valid, weights * inv, f32(0.0)).astype(f32))
        out = np.where(num == 0.0, f32(0.0), total / num)
    return np.where(total == 0.0, f32(0.0), out).astype(f32)


def _meet_steps(s, igp, n, yrs, epa, ycl, xldv, cv, inv_c, parts, by_cl, tot_cl, by_ldv, tot_ldv):
    """CAFEGHG_MEET's MAXPASS steps for one class and powertrain, all at once. Each step moves
    DELTA sales from gasoline to XLDV (undone, and the last step, once gasoline would go to
    zero); the state after step p depends only on p, so every step's tests are computed as
    arrays with the loop's sums in its order, and the first step that passes is the one kept.
    Returns (done, stop_gas) as the loop leaves them."""
    g0, y0, x0 = igp - 1, ycl - 1, xldv - 1
    cafe, cmg, mg, newmpg = s["cafesales"], s["cafempggrp"], s["mgghggrp"], s["newmpg"]
    fpg, epag, cpass = s["fpghggrp"], s["epaghggrp"], s["cafepass"]
    dl = s["_cafeghg_delta"][igp, ycl]
    c1, cx = cv[g0, y0, 0], cv[g0, y0, x0]
    c1s, cxs, stops = [], [], []
    stop_gas = 0
    for _ in range(MAXPASS):
        c1, cx = c1 - dl, cx + dl
        if c1 <= 0.0:
            c1, cx, stop_gas = c1 + dl, cx - dl, 1
        c1s.append(c1), cxs.append(cx), stops.append(stop_gas)
        if stop_gas:
            break
    P = len(c1s)
    w = np.repeat(cv[g0][None], P, axis=0)                       # (step, class, powertrain)
    w[:, y0, 0], w[:, y0, x0] = c1s, cxs
    wf = np.transpose(w, (0, 2, 1)).reshape(P, -1)                 # Fortran order of each (class, powertrain)
    cmg_p = _hmean_rows(np.broadcast_to(np.transpose(inv_c[0]).reshape(-1), wf.shape), wf,
                        np.broadcast_to(np.transpose(inv_c[1]).reshape(-1), wf.shape))
    # GROUP_GHG for each step
    k, omev, k56, keep = parts
    wt = np.transpose(w, (0, 2, 1))                                # (step, powertrain, class)
    with np.errstate(invalid="ignore", over="ignore"):
        term = wt * k
        term[:, 4:6] = (wt[:, 4:6] * omev) * k56
    num = _acc(term[:, keep])
    alt = [4, 7, 15, 14]
    cols = np.stack([_acc(w[:, :, a - 1]) for a in alt], axis=1)
    den = _acc(cols * (np.array([s["epaaltmult"][a, n] for a in alt], dtype=f32) - ONE))
    total = _acc(wf)
    epag_p = num / (total + den) - s["ac_co2_offset"][igp, n]
    # Group sales totals with this group's row redone
    bycl = np.repeat(by_cl[g0][None], P, axis=0)
    bycl[:, y0] = _acc(w[:, y0, :])
    totcl = _acc(bycl)
    byldv = np.add.accumulate(w, axis=1, dtype=f32)[:, -1, :] + ZERO32
    totldv = _acc(byldv)
    life = np.where(np.arange(1, MAXGROUP + 1) <= CARGRP, f32(195264.0), f32(225865.0))
    fp_, ep = fpg[G, n].copy(), np.repeat(epag[G, n][None], P, axis=0)
    ep[:, g0] = epag_p
    tc = np.repeat(tot_cl[None], P, axis=0)
    tc[:, g0] = totcl
    mgm = (fp_ - ep) * tc * life                                   # (step, group)
    cm = np.repeat(cmg[G, n][None], P, axis=0)
    cm[:, g0] = cmg_p
    tl = np.repeat(tot_ldv[None], P, axis=0)
    tl[:, g0] = totldv
    if yrs > epa:
        nm1 = _hmean_rows(cm[:, :CARGRP], tl[:, :CARGRP])
        nm2 = _hmean_rows(cm[:, LTKGRP - 1:], tl[:, LTKGRP - 1:])
        nm3 = _hmean_rows(cm, tl)
    else:
        nm1, nm2, nm3 = (np.full(P, newmpg[i, n]) for i in (1, 2, 3))
    std, used = s["cafestd"], s["cafe_used"]
    cafe_ok = ((cmg_p >= used[igp, yrs])
               | ((nm3 > std[3, n]) & ((nm1 - std[1, n]) > -2.0) & ((nm2 - std[2, n]) > -2.0))
               | (int(s["enforce_cafe"]) == 0))
    tot = _acc(mgm)
    mine = mgm[:, g0]
    if int(s["enforce_epa"]) == 0:
        kind = np.where(cafe_ok, 1, 0)
    else:
        all_ok = (tot > 0.0) | (tot + s["creds_avail"] > 0.0)
        own_ok = (mine > 0.0) | (mine + s["creds_avail_grp"][igp] > 0.0)
        kind = np.where(cafe_ok & all_ok, 2, np.where(cafe_ok & own_ok, 1, 0))
    hit = np.nonzero(kind)[0]
    q = int(hit[0]) if hit.size else P - 1
    # The state the loop leaves: the cells, totals and tests of step q
    cafe[igp, ycl, yrs, 1], cafe[igp, ycl, yrs, xldv] = c1s[q], cxs[q]
    by_cl[g0, y0], tot_cl[g0], by_ldv[g0], tot_ldv[g0] = bycl[q, y0], totcl[q], byldv[q], totldv[q]
    cmg[igp, n], epag[igp, n] = cmg_p[q], epag_p[q]
    s.update(ildv=MAXLDV + 1, icl=MAXCLASS + 1)
    mg[G, n] = mgm[q]
    if yrs > epa:
        newmpg[1, n], newmpg[2, n], newmpg[3, n] = nm1[q], nm2[q], nm3[q]
    if hit.size:
        if kind[q] == 2:
            cpass[G] = 1
        else:
            cpass[igp] = 1
    return bool(hit.size), stops[q]


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
    cv = cafe[G, C, yrs, L]                       # a view: [group, class, powertrain], 0-based
    mpgmult = mpg[igp, C, yrs, L] * s["cafepefmult_expanded"][igp, C, L, n]
    credv = cred[igp, C, L, n]
    parts = ghg_parts(s, igp, n, yrs)
    with np.errstate(divide="ignore", invalid="ignore"):
        inv_c = (mpgmult, (f32(1.0) / mpgmult) - credv)          # HARMONIC_MEAN's 1/MPG less credits
    # Group sales totals in both orders the Fortran sums them (powertrain then class, and class
    # then powertrain). A step changes one group's sales, so only that group's are redone.
    by_cl = fsum(cv, axis=2)
    tot_cl = fsum(by_cl, axis=1)
    by_ldv = fsum(cv, axis=1)
    tot_ldv = fsum(by_ldv, axis=1)
    g0 = igp - 1
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
            done, stop_gas = _meet_steps(s, igp, n, yrs, epa, ycl, xldv, cv, inv_c, parts, by_cl, tot_cl, by_ldv, tot_ldv)
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
