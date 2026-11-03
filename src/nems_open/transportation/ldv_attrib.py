"""Sales shares and vehicle attributes for the choice model (tran.f).

CGSHARE  manufacturer-group and size-class shares of new sales (history, then a
         class-share logit on cost per mile, income and price), and sales by
         region, group and class
FLEXSHR  alternative-fuel use by flex-fuel and bi-fuel vehicles (price ratio and
         station availability logits), E85 availability totals
TATTRIB  fuel prices by powertrain, charging mix, and the attributes the consumer
         choice model reads: fuel cost per mile, acceleration, maintenance, luggage,
         range, and price net of IRA and state credits

TATTRIB and FLEXSHR include ANGTDM and AEUSPRC, so their natural gas and electricity
prices are the angtdm__ / aeusprc__ copies in the state.
"""

import numpy as np

from nems_open.transportation.common import f32, fsum, MAXAGE, MAXHAV, MAXLDV, MAXOWNER, MAXVTYP, MNUMCR, powf, STOCKYR

BASE, PREV, CURRENT = 0, 1, 2
GAS = 1
MAXCLASS = 8
MAXGROUP = 11
CARGRP = 5
LTKGRP = 6
R9 = slice(1, MNUMCR - 2)
ONE = f32(1.0)


def cgshare(s: dict) -> None:
    n, yrs, epa = int(s["n"]), int(s["yrs"]), int(s["epalyr"])
    sales, cafe = s["ldv_sales"], s["cafesales"]
    G, C, L = slice(1, MAXGROUP), slice(1, MAXCLASS), slice(1, MAXLDV)
    cars = fsum(fsum(fsum(sales[1:CARGRP, C, L, 1:MNUMCR, n], axis=2), axis=1), axis=0)
    trks = fsum(fsum(fsum(sales[LTKGRP:MAXGROUP, C, L, 1:MNUMCR, n], axis=2), axis=1), axis=0)
    gs = s["grpshare"]
    if yrs <= epa:
        gs[MNUMCR, 1:CARGRP, n] = fsum(fsum(cafe[1:CARGRP, C, yrs, L], axis=2), axis=1) / cars[MNUMCR - 1]
        gs[MNUMCR, LTKGRP:MAXGROUP, n] = fsum(fsum(cafe[LTKGRP:MAXGROUP, C, yrs, L], axis=2), axis=1) / trks[MNUMCR - 1]
        if yrs <= 2018:
            gs[R9, G, n] = np.broadcast_to(gs[MNUMCR, G, n], (MNUMCR - 2, MAXGROUP))
        else:
            for iregn in range(1, MNUMCR - 1):
                gs[iregn, 1:CARGRP, n] = fsum(fsum(sales[1:CARGRP, C, L, iregn, n], axis=2), axis=1) / cars[iregn - 1]
                gs[iregn, LTKGRP:MAXGROUP, n] = fsum(fsum(sales[LTKGRP:MAXGROUP, C, L, iregn, n], axis=2), axis=1) / trks[iregn - 1]
            s["iregn"] = MNUMCR - 1
    else:
        gs[1:MNUMCR, G, n] = gs[1:MNUMCR, G, n - 1]

    cs, gsum = s["class_share"], s["groupsum"]
    cs[1:MNUMCR, C, G, yrs] = 0.0
    for igp in range(1, MAXGROUP + 1):
        gsum[igp] = fsum(cafe[igp, C, yrs, L])
        for icl in range(1, MAXCLASS + 1):
            if gsum[igp] != 0.0:
                cs[MNUMCR, icl, igp, yrs] = fsum(cafe[igp, icl, yrs, L]) / gsum[igp]
    if yrs <= 2018:
        cs[R9, C, G, yrs] = np.broadcast_to(cs[MNUMCR, C, G, yrs], (MNUMCR - 2, MAXCLASS, MAXGROUP))
    elif 2019 <= yrs <= epa:
        for iregn in range(1, MNUMCR - 1):
            for igp in range(1, MAXGROUP + 1):
                gsum[igp] = fsum(sales[igp, C, L, iregn, n])
                for icl in range(1, MAXCLASS + 1):
                    if gsum[igp] != 0.0:
                        cs[iregn, icl, igp, yrs] = fsum(sales[igp, icl, L, iregn, n]) / gsum[igp]
        s["iregn"] = MNUMCR - 1

    if yrs > STOCKYR:
        s["ownsalesshr"][1:MAXOWNER, G, C, L, R9, n] = s["ownsalesshr"][1:MAXOWNER, G, C, L, R9, n - 1]
        s["ownsaletemp"][1:MAXOWNER, G, C, R9, n] = s["ownsaletemp"][1:MAXOWNER, G, C, R9, n - 1]
        log, exp = np.log, np.exp
        cost, inc, price = s["costmi"], s["inc90_d_np"], s["price"]
        cpm = log(cost[1:MNUMCR, n - 1] / cost[1:MNUMCR, n - 2])
        incd = log((inc[1:MNUMCR, yrs] - f32(13000.0)) / (inc[1:MNUMCR, yrs - 1] - f32(13000.0)))
        prid = log(price[G, C, CURRENT, GAS] / price[G, C, PREV, GAS])
        s["ratio_byr"] = log(f32(yrs - epa))
        ca, cb, cc, cp = s["coef_a"], s["coef_b"], s["coef_c"], s["coef_p"]
        for igp in range(1, MAXGROUP + 1):
            for icl in range(1, MAXCLASS + 1):
                for iregn in range(1, MNUMCR + 1):
                    if iregn == 10:
                        continue
                    if (cost[iregn, n - 1] >= 0.0 and inc[iregn, yrs - 1] > 13000.0
                            and price[igp, icl, PREV, GAS] > 0.0 and price[igp, icl, CURRENT, GAS] > 0.0):
                        d = (ca[icl, igp] * s["ratio_byr"] + cb[icl, igp] * cpm[iregn - 1] + cc[icl, igp] * incd[iregn - 1]
                             + cp[icl, igp] * prid[igp - 1, icl - 1])
                        base = max(cs[iregn, icl, igp, epa], f32(0.000001))
                        s["ratio_ln"] = d + log(base / (ONE - base))
                        s["ratio"] = exp(s["ratio_ln"])
                        cs[iregn, icl, igp, yrs] = s["ratio"] / (ONE + s["ratio"])
                    elif (price[igp, icl, CURRENT, :] > 0.0).any():
                        cs[iregn, icl, igp, yrs] = cs[iregn, icl, igp, yrs - 1]
                    else:
                        cs[iregn, icl, igp, yrs] = 0.0
            for iregn in range(1, MNUMCR + 1):
                if iregn == 10:
                    continue
                t = fsum(cs[iregn, C, igp, yrs])
                if t > 0.0:
                    cs[iregn, C, igp, yrs] = cs[iregn, C, igp, yrs] / t
        s["iregn"] = MNUMCR + 1

    mfr, newv = s["mfr_sales"], s["newldvs"]
    for icl in range(1, MAXCLASS + 1):
        for igp in range(1, MAXGROUP + 1):
            it = int(s["grpmap"][igp])
            mfr[R9, igp, icl, n] = newv[it, R9, n] * gs[R9, igp, n] * cs[R9, icl, igp, yrs]
    s.update(icl=MAXCLASS + 1, igp=MAXGROUP + 1)


PCTFLOOR = [None, f32(0.00000001), f32(0.001), f32(0.20), f32(0.20)]
PCTCEILING = [None, f32(0.00000001), f32(0.70), f32(0.70), f32(0.30)]
FCLOGIT0 = [f32(x) for x in (-1.2501, -1.6998, -2.1780, -2.0684, -0.8035, -0.7942, -0.9550, -1.3789, -1.1009)]


def flexshr(s: dict) -> None:
    n, yrs = int(s["n"]), int(s["yrs"])
    s["fclogit0"][1:9] = FCLOGIT0
    s.update(fclogit1=f32(-2.2540), fclogit2=f32(3.4444), fclogit3=f32(-18.830), fclogit4=f32(-2.4921))
    gammap = f32(-7.0)
    # BETAP(1) is only assigned through 2002 and keeps that value after (a saved local).
    betap = [None, f32(0.10), f32(0.01), f32(0.50) if n <= 13 else f32(0.70), f32(0.30)]
    pmetr, pettr, pmg = s["pmetr"], s["pettr"], s["pmgtr"]
    if pmetr[MNUMCR, n] == 0:
        pmetr[MNUMCR, n] = fsum(pmetr[R9, n]) / f32(MNUMCR - 2)
    fuel = {1: pmetr[R9, n], 2: pettr[R9, n], 3: s["angtdm__pgftrpv"][R9, n], 4: s["plgtr"][R9, n]}
    af = s["pctaf"]
    for k in range(1, 5):
        ratio = powf(fuel[k], gammap) / (powf(fuel[k], gammap) + powf(pmg[R9, n], gammap))
        ratio = np.where(ratio > 0.50, PCTCEILING[k], ratio)
        v = PCTFLOOR[k] + (betap[k] * ratio)
        af[k, R9, n] = np.where(v > PCTCEILING[k], PCTCEILING[k], v)

    e85 = s["e85avail"]
    favl = {1: np.full(MNUMCR - 2, f32(0.0000001), dtype=f32)}
    if yrs <= 2012:
        init = s["initsta"]
        favl[2] = init[3, 6, R9] / init[1, 6, R9] if yrs <= 1995 else init[3, n, R9] / init[1, n, R9]
        e85[R9, n] = favl[2]
    else:
        favl[2] = e85[R9, n].copy()
    favl[3] = s["favl"][5, R9, yrs]
    favl[4] = s["favl"][6, R9, yrs]

    stock = s["ldv_stock"]
    e85[11, n] = 0.0
    nat = fsum(stock[MNUMCR, 1:MAXVTYP, 1:MAXOWNER, 3, 1:MAXAGE, 1:MAXHAV, n])
    nat_lag = fsum(stock[MNUMCR, 1:MAXVTYP, 1:MAXOWNER, 3, 1:MAXAGE, 1:MAXHAV, n - 1])

    def regional(y):
        return fsum(fsum(fsum(fsum(stock[R9, 1:MAXVTYP, 1:MAXOWNER, 3, 1:MAXAGE, 1:MAXHAV, y], axis=4), axis=3), axis=2), axis=1)
    reg, reg_lag = regional(n), regional(n - 1)
    if yrs <= STOCKYR:
        e85[11, n] = fsum(e85[R9, n] * reg) / nat
    else:
        e85[11, n] = fsum(e85[R9, n] * reg_lag) / nat_lag

    cf = s["cfmgq"][n]
    if yrs >= 2006:
        pctafl = np.zeros((5, MNUMCR - 2), dtype=f32)
        gas = np.exp(np.float64(pmg[R9, n] * cf / f32(42.0)) * np.float64(s["fclogit4"])).astype(f32)
        for k in range(1, 5):
            alt = np.exp(np.float64(np.array(FCLOGIT0, dtype=f32)) + (np.float64(fuel[k] * cf / f32(42.0)) * np.float64(s["fclogit1"]))
                         - np.float64(s["fclogit2"]) * (np.exp(np.float64(favl[k]) * np.float64(s["fclogit3"])))).astype(f32)
            pctafl[k] = alt / (alt + gas)
        af[1:4, R9, n] = np.maximum(af[1:4, R9, n], pctafl[1:5])
    af[1, R9, n] = f32(0.00000001)
    for k in range(1, 5):
        if yrs <= STOCKYR:
            af[k, 11, n] = fsum(af[k, R9, n] * reg) / nat
        else:
            af[k, 11, n] = fsum(af[k, R9, n] * reg_lag) / nat_lag
    s.update(ifuelx=5, iregn=MNUMCR - 1)


def ira_credit(s: dict) -> np.ndarray:
    """TATTRIB's IRA_Credit(MAXLDV, MNUMYR): a saved local filled in the last EPA year
    (with that year's credit in 1990 dollars) and read every year after."""
    epa = int(s["epalyr"])
    out = np.zeros((MAXLDV + 1, 62), dtype=f32)
    if s["ira_stim"] != 1.0:
        return out
    jp = s["mc_jpgdp"]
    cred = f32(3750.0) / jp[epa - 1989] * jp[1]  # TMAC's ira_veh_cred and ira_bat_cred in that year
    vs, bs = s["ira_veh_shr"], s["ira_bat_shr"]
    col = 1 if int(s["switchldv_hr1"]) == 1 else 2
    for ildv in range(1, MAXLDV + 1):
        # EIA quirk: "ildv.le.7" sends plug-in hybrids (5, 6) down the battery-EV branch.
        if ildv == 4 or ildv <= 7 or ildv == 15 or ildv == 14:
            row = 1
        elif ildv in (5, 6):
            row = 2
        else:
            continue
        out[ildv, epa - 1989:62] = (cred * vs[row, epa:2050, col]) + (cred * bs[row, epa:2050, col])
    return out


def tattrib(s: dict) -> None:
    n, yrs, epa = int(s["n"]), int(s["yrs"]), int(s["epalyr"])
    pmg, pettr = s["pmgtr"], s["pettr"]
    pettr[R9, n] = np.where(pettr[R9, n] == 0.0, pmg[R9, n] * f32(1.18), pettr[R9, n])
    flexshr(s)

    fp, cd, mult = s["fprice"], s["chg_dist"], s["chgcstmult"]
    A = slice(1, MNUMCR)
    vhrs, p2, pf = s["aeusprc__pelvhrs"], s["aeusprc__pelp2cm"], s["aeusprc__pelpfcm"]
    hwy, af, gftrpv = s["hwypdstr"], s["pctaf"], s["angtdm__pgftrpv"]
    p20, p50 = s["pctphev20"][n], s["pctphev50"][n]
    c23 = 2023 - 1989
    elec = cd[A, 3, c23] * (p2[A, n] * mult[3]) + cd[A, 1, c23] * (pf[A, n] * mult[1]) + cd[A, 2, c23] * vhrs[A, n]
    fp[1, A, yrs] = pmg[A, n]
    fp[2, A, yrs] = hwy[A, n]
    fp[3, A, yrs] = np.minimum(pettr[A, n], pmg[A, n])
    fp[4, A, yrs] = elec
    fp[5, A, yrs] = (p20 * vhrs[A, n]) + ((ONE - p20) * pmg[A, n])
    fp[6, A, yrs] = (p50 * vhrs[A, n]) + ((ONE - p50) * pmg[A, n])
    fp[7, A, yrs] = elec
    fp[8, A, yrs] = hwy[A, n]
    fp[9, A, yrs] = (af[3, A, n] * gftrpv[A, n]) + ((ONE - af[3, A, n]) * pmg[A, n])
    fp[10, A, yrs] = (af[4, A, n] * s["plgtr"][A, n]) + ((ONE - af[4, A, n]) * pmg[A, n])
    fp[11, A, yrs] = gftrpv[A, n]
    fp[12, A, yrs] = s["plgtr"][A, n]
    fp[13, A, yrs] = s["pmetr"][A, n]
    fp[14, A, yrs] = s["ph2tr"][A, n]
    fp[15, A, yrs] = elec
    fp[16, A, yrs] = pmg[A, n]
    if yrs > 2023:
        cd[R9, 2, n] = cd[R9, 2, c23] - s["favl"][7, R9, yrs - 1] / f32(1.4)
        cd[R9, 1, n] = cd[R9, 1, c23] / (cd[R9, 1, c23] + cd[R9, 3, c23]) * (ONE - cd[R9, 2, n])
        cd[R9, 3, n] = ONE - (cd[R9, 1, n] + cd[R9, 2, n])
        # EIA quirk: here DC fast gets the L2 price and multiplier, and L2 the DC fast ones.
        e2 = cd[R9, 1, n] * (p2[R9, n] * mult[1]) + cd[R9, 3, n] * (pf[R9, n] * mult[3]) + cd[R9, 2, n] * vhrs[R9, n]
        for k in (4, 7, 15):
            fp[k, R9, yrs] = e2
    fp[:, :, yrs] = fp[:, :, yrs] * s["mc_jpgdp"][1] * f32(100.0) * s["cfmgq"][n] / f32(42.0)

    G, L, C = slice(1, MAXGROUP), slice(1, MAXLDV), slice(1, MAXCLASS)
    for k in ("flcost", "hfuel", "accl", "maint", "vrng"):
        s[k][G, L, C, R9, yrs] = 0.0
    s["lugg"][G, L, C, R9] = 0.0
    if yrs >= epa:
        flag = s["classflag"]
        mpg, wgt, hp, rng = s["femmpg"], s["femwgt"], s["femhp"], s["femrng"]
        lug, avg = s["epalug"], s["luggavg"]
        for igp in range(1, MAXGROUP + 1):
            ivtyp = int(s["grpmap"][igp])
            for icl in range(1, MAXCLASS + 1):
                for ildv in range(1, MAXLDV + 1):
                    if not flag[igp, icl, ildv]:
                        continue
                    if mpg[igp, icl, yrs, ildv] != 0.0:
                        s["flcost"][igp, ildv, icl, R9, yrs] = fp[ildv, R9, yrs] / mpg[igp, icl, yrs, ildv]
                    if ildv in (4, 7, 15):
                        s["hfuel"][igp, ildv, icl, R9, yrs] = ONE
                    if wgt[igp, icl, yrs, ildv] != 0.0:
                        s["accl"][igp, ildv, icl, R9, yrs] = hp[igp, icl, yrs, ildv] / wgt[igp, icl, yrs, ildv]
                    s["maint"][igp, ildv, icl, R9, yrs] = s["maintgrp"][ildv, icl, ivtyp]
                    if igp >= LTKGRP and icl <= 2:
                        s["lugg"][igp, ildv, icl, R9] = 0.0
                    elif lug[igp, icl, epa, ildv] > 0.0 and lug[igp, icl, epa, GAS] > 0.0:
                        s["lugg"][igp, ildv, icl, R9] = lug[igp, icl, epa, ildv] / lug[igp, icl, epa, GAS]
                    else:
                        s["lugg"][igp, ildv, icl, R9] = avg[igp, icl]
                    s["vrng"][igp, ildv, icl, R9, yrs] = rng[igp, icl, yrs, ildv]
        s.update(igp=MAXGROUP + 1, icl=MAXCLASS + 1, ildv=MAXLDV + 1, ivtyp=ivtyp)

        cred = ira_credit(s)
        pspr, avail, pri, st = s["pspr"], s["mmavail"], s["fempri"], s["state_cred"]
        for ildv in range(1, MAXLDV + 1):
            for igp in range(1, MAXGROUP + 1):
                for icl in range(1, MAXCLASS + 1):
                    p = pri[igp, icl, yrs, ildv]
                    for iregn in range(1, MNUMCR - 1):
                        pspr[igp, ildv, icl, iregn, yrs] = 0.0
                        if avail[igp, ildv, icl, iregn, yrs] > 0.0:
                            v = p
                            if ildv in (4, 7, 15, 14):
                                v = p - cred[ildv, n] - st[iregn, yrs, 1]
                            if ildv in (5, 6, 14):
                                v = p - cred[ildv, n] - st[iregn, yrs, 2]
                            if ildv == 16:
                                v = p - st[iregn, yrs, 3]
                            pspr[igp, ildv, icl, iregn, yrs] = v
        s.update(ildv=MAXLDV + 1, igp=MAXGROUP + 1, icl=MAXCLASS + 1, iregn=MNUMCR - 1)
