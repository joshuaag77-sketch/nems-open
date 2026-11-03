"""FEMCALC (tran.f): the Fuel Economy Model, one pass.

For every group, class and fuel type with vehicles, each technology's market
penetration moves toward a cost-effectiveness logit: fuel savings over the payback
period (with a fuel price trend), performance value, technology cost with
learning, and the regulatory cost signal from the CAFE passes. Engineering notes
(mandatory, supersedes, required, synergy) limit the shares. Fuel economy, weight,
price and horsepower follow the share changes, then horsepower responds to income,
price and fuel economy, capped by a performance ceiling and floor.

A direct port: scalar loops in the Fortran's order, because each float32 step and
each leftover module variable (ITECH, I, J, INOTE, the per-technology work arrays)
is compared with the oracle.
"""

import math

import numpy as np

from nems_open.transportation.common import expf, f32, fsum, MAXLDV, MNUMCR, powf
from nems_open.transportation.ldv_tech import evcalc, fccalc, femrange, hevcalc, phevcalc
from nems_open.transportation.misc_modes import powi

BASE, PREV, CURRENT = 0, 1, 2
GAS = 1
MAXCLASS = 8
MAXGROUP = 11
CARGRP = 5
LTKGRP = 6
XYR = 2022

# Related-technology groups whose penetrations must not sum past 1 (EIA's SUMCHECK).
SUMCHECK = [
    [1, 2, 3, 4, 5], [6, 7, 8, 9], [10, 11, 12], [13, 14, 15, 16, 17, 18, 19, 20, 21, 22],
    [13, 14, 17, 18, 19, 20, 21, 22], [15, 16], [23, 24], [25, 26, 27, 28, 29, 30, 31, 32, 33],
    [34, 35, 36, 37, 38, 39, 40, 41, 42], [34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48],
    [43, 44, 45, 46, 47, 48], [49, 50, 51, 52, 53, 54], [43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 54],
    [55, 56, 57, 58, 59, 60], [61, 62, 63], [55, 56, 57, 58, 59, 60, 61, 62, 63],
    [49, 50, 51, 52, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63], [49, 50, 51, 52, 53, 54, 61, 62, 63],
    [64, 65], [66, 67, 68],
]

RETD = [f32(x) for x in (0.000, 0.048, 0.096, 0.145, 0.193, 0.241, 0.289, 0.337, 0.385, 0.434,
                         0.482, 0.530, 0.578, 0.626, 0.674, 0.722, 0.771, 0.819, 0.869, 0.907,
                         0.936, 0.957, 0.973, 0.984, 0.992, 0.997, 1.000, 1.000, 1.000, 1.000, 1.000)]

ONE, ZERO = f32(1.0), f32(0.0)


def funcmax(s, oldmksh, oldpmax):
    """FUNCMAX: the most a technology's share may be this year, given last year's."""
    if oldpmax == 1.0:
        return ONE
    tpmax = min(oldpmax, ONE)
    for i in range(1, 31):
        if oldmksh <= RETD[i - 1] and tpmax < RETD[i]:
            s["i"] = i
            return RETD[i]
    s["i"] = 31
    return max(ZERO, tpmax)


def note_super(s, actual, mmax):
    """NOTE_SUPER: a technology and those it supersedes share one market ceiling."""
    itech = int(s["itech"])
    sup, cnt, rnd = s["supersedes"], s["tech_cnt"], s["roundoff_error"]
    for inote in range(1, int(s["num_sup"]) + 1):
        s["inote"] = inote
        if int(sup[1, inote]) == itech:
            tot = actual[itech]
            mx = mmax[itech]
            for i in range(2, int(cnt[inote]) + 1):
                mx = max(mx, mmax[int(sup[i, inote])])
            for i in range(2, int(cnt[inote]) + 1):
                s["i"] = i
                k = int(sup[i, inote])
                tot = tot + actual[k]
                if tot > mx:
                    actual[k] = actual[k] - (tot - mx)
                    tot = mx
                    if actual[k] < ZERO - rnd:
                        s["tot_mkt"], s["max_share"] = tot, mx
                        s["return_stat"] = (-100 * inote) - i
                        return
                    elif actual[k] < 0.0:
                        actual[k] = ZERO
            s["i"] = int(cnt[inote]) + 1
            s["tot_mkt"], s["max_share"] = tot, mx
    s["inote"] = int(s["num_sup"]) + 1
    s["return_stat"] = 0


def calibnhtsa(s):
    yrs, epa = int(s["yrs"]), int(s["epalyr"])
    G, C, L = slice(1, MAXGROUP), slice(1, MAXCLASS), slice(1, MAXLDV)
    if yrs <= epa:
        keys = [("calratio_fe", "epampg", "femmpg"), ("calratio_hp", "epahp", "femhp"),
                ("calratio_wgt", "epawgt", "femwgt"), ("calratio_pri", "epapri", "fempri")]
        for k, *_ in keys + [("calratio_tsz",)]:
            s[k].a[...] = 1.0
        mpg = s["femmpg"][G, C, yrs, L]
        ok = mpg != 0.0
        with np.errstate(divide="ignore", invalid="ignore"):
            for k, e, f in keys:
                s[k][G, C, L] = np.where(ok, s[e][G, C, yrs, L] / s[f][G, C, yrs, L], s[k][G, C, L])
            ok2 = ok & (s["femtsz"][G, C, yrs, L] != 0.0)
            s["calratio_tsz"][G, C, L] = np.where(ok2, s["epatsz"][G, C, yrs, L] / s["femtsz"][G, C, yrs, L], s["calratio_tsz"][G, C, L])
        for k, f in (("calratio_fe", "femmpg"), ("calratio_hp", "femhp"), ("calratio_wgt", "femwgt"),
                     ("calratio_pri", "fempri"), ("calratio_tsz", "femtsz")):
            s[f][G, C, yrs, L] = np.where(ok, s[f][G, C, yrs, L] * s[k][G, C, L], s[f][G, C, yrs, L])
    if yrs == epa:
        s.update(igp=MAXGROUP + 1, icl=MAXCLASS + 1, ildv=MAXLDV + 1)


def femcalc(s: dict) -> None:
    yrs, n = int(s["yrs"]), int(s["n"])
    curitr, fem_pass = int(s["curitr"]), int(s["fem_pass"])
    numtech = int(s["numtech"])
    flag = s["classflag"]
    fe, wgt, price, hp, tank, rng = s["fe"], s["weight"], s["price"], s["hp"], s["tanksize"], s["range"]
    pen, mkt_max, esc = s["mkt_pen"], s["mkt_max"], s["elecsysinccost"]
    G, C, L, T = slice(1, MAXGROUP), slice(1, MAXCLASS), slice(1, MAXLDV), slice(1, numtech)

    if fem_pass == 1:
        s["tec_ornl"].a[...] = 0.0
    if curitr == 1 and fem_pass == 1 and yrs > XYR:
        on = flag[G, C, L] != 0
        for a in (fe, wgt, price, hp, tank, rng):
            a[G, C, PREV, L] = np.where(on, a[G, C, CURRENT, L], a[G, C, PREV, L])
        pen[G, C, T, PREV, L] = pen[G, C, T, CURRENT, L]
        for ildv in range(1, MAXLDV + 1):
            if (4 <= ildv <= 8) or ildv >= 13:
                for igp in range(1, MAXGROUP + 1):
                    for icl in range(1, MAXCLASS + 1):
                        if flag[igp, icl, ildv]:
                            esc[icl, igp, PREV, ildv] = esc[icl, igp, CURRENT, ildv]
        s.update(ildv=MAXLDV + 1, igp=MAXGROUP + 1, icl=MAXCLASS + 1)

    pm90 = s["pmgtr90_d_"]
    if yrs > XYR:
        f1 = fsum(pm90[11, yrs - 7:yrs - 3]) / f32(5.0)
        f2 = fsum(pm90[11, yrs - 8:yrs - 4]) / f32(5.0)
        s["pslope"] = max(ZERO, f1 - f2)
    else:
        f1 = ZERO
    if int(s["enforce_my27regs"]) == 1:
        s["payback"], s["discount"] = 8, f32(0.05)
    else:
        s["payback"], s["discount"] = 3, f32(0.1)
    payback, discount, pslope = int(s["payback"]), s["discount"], s["pslope"]

    # Read-only inputs, fetched once.
    applic, frst = s["tech_applic"], s["frstyear"]
    del_fe, del_hp, del_costabs, del_costwgt = s["del_fe"], s["del_hp"], s["del_costabs"], s["del_costwgt"]
    del_wgtabs, del_wgtwgt = s["del_wgtabs"], s["del_wgtwgt"]
    lrn1, lrn2, coeff_learn = s["coeff_lrn1"], s["coeff_lrn2"], s["coeff_learn"]
    usedcap, perfcap, perffact, valueperf = s["usedcap"], s["perfcap"], s["perffact"], s["valueperf"]
    old_pmax, tec_ornl = s["old_pmax"], s["tec_ornl"]
    inc_gr, invgr, inc90 = s["inc_gr_regn"][11, yrs], s["pmgtr90_invgr"][11, yrs], s["inc90_d_np"]
    regcost, cafepass, grpmap = s["regcost"], s["cafepass"], s["grpmap"]
    vmt_idx = 2024 - 1989  # VMTYR
    pvmt, lvmt = s["pvmt"], s["lvmt"]
    mmax, mkt_perf, mkt_fuel = s["mmax"], s["mkt_perf"], s["mkt_fuel"]
    actual, fuelsave, techcost = s["actual_mkt"], s["fuelsave"], s["techcost"]
    val_perf, cef_fuel, cef_perf = s["val_perf"], s["costef_fuel"], s["costef_perf"]
    price_ex, lcm = s["price_ex"], s["learn_cost_multiplier"]
    rnd = s["roundoff_error"]
    num_man, num_req, num_syn = int(s["num_man"]), int(s["num_req"]), int(s["num_syn"])
    syn_loss = s.setdefault("_femcalc_synergy_loss", np.zeros(numtech + 1, dtype=f32))
    learnyear = {}

    for ildv in range(1, MAXLDV + 1):
        s["ildv"] = ildv
        for igp in range(1, MAXGROUP + 1):
            s["igp"] = igp
            if fem_pass >= 2 and cafepass[igp]:
                continue
            for icl in range(1, MAXCLASS + 1):
                s["icl"] = icl
                if not flag[igp, icl, ildv]:
                    continue
                ivtyp = int(grpmap[igp])
                s["ivtyp"] = ivtyp
                for a in (fe, wgt, price, hp, tank):
                    a[igp, icl, CURRENT, ildv] = a[igp, icl, PREV, ildv]
                if yrs > XYR:
                    if (4 <= ildv <= 8) or ildv >= 13:
                        if price[igp, icl, CURRENT, ildv] != 0.0:
                            price[igp, icl, CURRENT, ildv] = price[igp, icl, CURRENT, ildv] - esc[icl, igp, PREV, ildv]
                    if wgt[igp, icl, BASE, ildv] == 0.0:
                        raise ValueError("TDM FEMCALC: STOP 505")
                    hp_wgt_base = hp[igp, icl, BASE, ildv] / wgt[igp, icl, BASE, ildv]
                    if wgt[igp, icl, CURRENT, ildv] == 0.0:
                        raise ValueError("TDM FEMCALC: STOP 506")
                    hp_wgt = hp[igp, icl, CURRENT, ildv] / wgt[igp, icl, CURRENT, ildv]
                    uc = usedcap[icl, igp]
                    if not (0.0 <= uc < 1.0):
                        raise ValueError("TDM FEMCALC: STOP 508")
                    demand_used = (perfcap[icl, igp] - hp_wgt_base) * (uc / (ONE - uc))
                    if perfcap[icl, igp] - hp_wgt_base + demand_used != 0.0:
                        perf_coeff = ONE - ((hp_wgt - hp_wgt_base + demand_used) / (perfcap[icl, igp] - hp_wgt_base + demand_used))
                        perf_coeff = max(ZERO, min(ONE, perf_coeff))
                    else:
                        if int(s["curiyr"]) > 1:
                            if perfcap[icl, igp] == hp_wgt_base:
                                perf_coeff = f32(0.01)
                                perfcap[icl, igp] = perfcap[icl, igp] + f32(0.01)
                        else:
                            raise ValueError("TDM FEMCALC: STOP 507")
                    pen[igp, icl, T, CURRENT, ildv] = pen[igp, icl, T, PREV, ildv]
                    mmax[T] = mkt_max[icl, igp, T, ildv]
                    mkt_perf[T] = 0.0
                    mkt_fuel[T] = 0.0
                    actual[T] = 0.0
                    fuelsave[T] = 0.0
                    cfe = fe[igp, icl, PREV, ildv]
                    cfe_inv = ONE / cfe if cfe > 0.0 else ZERO

                    for itech in range(1, numtech + 1):
                        s["itech"] = itech
                        if not applic[itech, ivtyp, ildv]:
                            continue
                        if curitr == 1 and fem_pass == 1:
                            old_pmax[icl, igp, itech, ildv, 1] = old_pmax[icl, igp, itech, ildv, 2]
                        elif fem_pass == 1:
                            old_pmax[icl, igp, itech, ildv, 2] = old_pmax[icl, igp, itech, ildv, 1]
                        if yrs < frst[itech, igp]:
                            continue
                        dfe = del_fe[itech, ivtyp]
                        if cfe > 0.0:
                            savings = cfe_inv - (ONE / ((ONE + dfe) * cfe))
                            fs = fuelsave[itech]
                            for i in range(1, payback + 1):
                                cur_vmt = ZERO
                                if igp <= CARGRP:
                                    cur_vmt = pvmt[i, vmt_idx, MNUMCR, 1]
                                if igp >= LTKGRP:
                                    cur_vmt = lvmt[i, vmt_idx, MNUMCR, 1]
                                price_ex[i] = pslope * (f32(i) + f32(2.0)) + f1
                                fs = fs + cur_vmt * savings * price_ex[i] * powi(ONE + discount, -i)
                            fuelsave[itech] = fs
                            s["i"] = payback + 1
                        tc = del_costabs[itech, ivtyp]
                        tc = tc + (del_costwgt[itech, ivtyp] * del_wgtabs[itech, ivtyp] * f32(math.copysign(1.0, del_wgtabs[itech, ivtyp])))
                        tc = tc + (del_costwgt[itech, ivtyp] * del_wgtwgt[itech, ivtyp]
                                   * f32(math.copysign(1.0, del_wgtwgt[itech, ivtyp])) * wgt[igp, icl, CURRENT, ildv])
                        if tc >= 0.0:
                            lcm[1:4] = 1.0
                            ly = f32(2011) if frst[itech, igp] < 2011 else f32(frst[itech, igp])
                            learnyear[itech, igp] = ly
                            ym = int(f32(yrs) - ly + ONE)
                            s["years_mktd"] = ym
                            if ym >= 1:
                                lcm[2] = ONE + (lrn1[itech, ivtyp] * coeff_learn[ym, 1])
                                lcm[3] = ONE + (lrn2[itech, ivtyp] * coeff_learn[ym, 2])
                            if tc > 0.0:
                                tc = tc * lcm[1] * lcm[2] * lcm[3] * lcm[4]
                        techcost[itech] = tc
                        tec_ornl[icl, igp, itech, ildv] = tc
                        vp = ZERO
                        if cfe != 0.0:
                            vp = (valueperf[icl, igp] * perf_coeff * inc_gr * (ONE + dfe) * invgr * del_hp[itech, ivtyp])
                        val_perf[itech] = vp
                        if tc > 0.0:
                            cf = (fuelsave[itech] - tc + regcost[igp] * cfe * dfe) / tc
                            cp = f32(-80.0)
                            if vp != 0.0:
                                cp = (vp - tc) / tc
                            cf, cp = max(f32(-80.0), cf), max(f32(-80.0), cp)
                        else:
                            cf = f32(80.0) if fuelsave[itech] > 0.0 else f32(-80.0)
                            cp = f32(80.0) if vp > 0.0 else f32(-80.0)
                        cef_fuel[itech], cef_perf[itech] = cf, cp
                        mmax[itech] = mkt_max[icl, igp, itech, ildv]
                        if fem_pass == 1 or (fem_pass == 2 and int(s["pass2"]) == 1):
                            old_pmax[icl, igp, itech, ildv, 2] = funcmax(s, pen[igp, icl, itech, PREV, ildv], old_pmax[icl, igp, itech, ildv, 2])
                        k = f32(-4.0) if cf < 0.0 else f32(-2.0)
                        mkt_fuel[itech] = ONE / (ONE + expf(k * cf))
                        k = f32(-4.0) if cp < 0.0 else f32(-2.0)
                        mkt_perf[itech] = ONE / (ONE + expf(min(k * cp, f32(75.0))))
                        am = old_pmax[icl, igp, itech, ildv, 2] * max(mkt_fuel[itech], mkt_perf[itech])
                        am = max(pen[igp, icl, itech, PREV, ildv], am)
                        actual[itech] = min(am, mmax[itech], ONE)
                    s["itech"] = numtech + 1

                    for itech in range(1, numtech + 1):
                        s["itech"] = itech
                        if yrs < frst[itech, igp]:
                            continue
                        if num_man > 0:
                            my, mand, oride = s["mandyear"], s["mandmksh"], s["mand_oride"]
                            for inote in range(1, num_man + 1):
                                s["inote"] = inote
                                if int(my[1, inote]) == itech and yrs >= my[2, inote]:
                                    if oride[inote]:
                                        actual[itech] = ZERO
                                    if my[3, inote] <= 1:
                                        actual[itech] = min(max(mand[inote], actual[itech]), mkt_max[icl, igp, itech, ildv])
                                    else:
                                        phasein = min(ONE, f32(yrs - int(my[2, inote])) / f32(my[3, inote]))
                                        cls = pen[igp, icl, itech, BASE, ildv] + (mand[inote] * phasein * (mkt_max[icl, igp, itech, ildv] - pen[igp, icl, itech, BASE, ildv]))
                                        actual[itech] = min(max(actual[itech], cls), mkt_max[icl, igp, itech, ildv])
                            s["inote"] = num_man + 1
                        note_super(s, actual, mmax)
                        if int(s["return_stat"]) < 0:
                            raise ValueError("TDM FEMCALC: logic error in supersedes algorithm, market penetration below zero")
                    s["itech"] = numtech + 1

                    if num_req > 0:
                        req = s["requires"]
                        for itech in range(1, numtech + 1):
                            s["itech"] = itech
                            if yrs < frst[itech, igp]:
                                continue
                            required, req_mkt = False, ZERO
                            for inote in range(1, num_req + 1):
                                if int(req[1, inote]) == itech:
                                    required = True
                                    req_mkt = req_mkt + pen[igp, icl, int(req[2, inote]), CURRENT, ildv]
                            s.update(required=int(required), req_mkt=req_mkt, inote=num_req + 1)
                            if required:
                                actual[itech] = min(actual[itech], min(req_mkt, ONE))
                        s["itech"] = numtech + 1

                    pen[igp, icl, T, CURRENT, ildv] = actual[T]

                    if num_syn > 0:
                        syn, sdel = s["synergy"], s["synr_del"]
                        for itech in range(1, numtech + 1):
                            s["itech"] = itech
                            if yrs < frst[itech, igp]:
                                continue
                            syn_loss[itech] = ZERO
                            for inote in range(1, num_syn + 1):
                                if int(syn[1, inote]) == itech:
                                    t2 = int(syn[2, inote])
                                    dm = ((pen[igp, icl, itech, CURRENT, ildv] * pen[igp, icl, t2, CURRENT, ildv])
                                          - (pen[igp, icl, itech, PREV, ildv] * pen[igp, icl, t2, PREV, ildv]))
                                    s["delta_mkt"] = dm
                                    if del_fe[itech, ivtyp] < abs(sdel[inote]):
                                        raise ValueError("TDM FEMCALC: STOP 291, synergy loss above fuel economy gain")
                                    syn_loss[itech] = syn_loss[itech] + (dm * sdel[inote])
                            s["inote"] = num_syn + 1
                        s["itech"] = numtech + 1

                    tech_adjhp = ZERO
                    fe_prev = fe[igp, icl, PREV, ildv]
                    for itech in range(1, numtech + 1):
                        if not applic[itech, ivtyp, ildv] or yrs < frst[itech, igp]:
                            continue
                        dm = pen[igp, icl, itech, CURRENT, ildv] - pen[igp, icl, itech, PREV, ildv]
                        s["delta_mkt"] = dm
                        fe[igp, icl, CURRENT, ildv] = fe[igp, icl, CURRENT, ildv] + fe_prev * ((dm * del_fe[itech, ivtyp]) + syn_loss[itech])
                        if dm != 0.0:
                            w = wgt[igp, icl, CURRENT, ildv]
                            wgt[igp, icl, CURRENT, ildv] = w + (dm * (del_wgtabs[itech, ivtyp] + (w * del_wgtwgt[itech, ivtyp])))
                            price[igp, icl, CURRENT, ildv] = price[igp, icl, CURRENT, ildv] + (dm * techcost[itech])
                            tech_adjhp = tech_adjhp + (dm * del_hp[itech, ivtyp])
                    s["itech"] = numtech + 1
                    tech_max_adjhp = tech_adjhp

                # Label 1100: related-technology shares may not sum past 1.
                for i, row in enumerate(SUMCHECK, start=1):
                    checksum = ZERO
                    for tid in row:
                        checksum = checksum + pen[igp, icl, tid, CURRENT, ildv]
                    s["j"] = len(row)
                    if checksum > ONE + rnd:
                        raise ValueError(f"TDM FEMCALC: STOP 702, related tech shares sum to {checksum}")
                s["i"] = len(SUMCHECK) + 1
                if yrs <= XYR:
                    continue

                # Label 2000
                if price[igp, icl, CURRENT, ildv] != 0.0 and flag[igp, icl, ildv]:
                    if ildv in (4, 7, 15):
                        evcalc(s, yrs, igp)
                    elif ildv in (8, 16):
                        hevcalc(s, yrs, igp)
                    elif ildv in (5, 6):
                        phevcalc(s, yrs, igp)
                    elif ildv in (13, 14):
                        fccalc(s, yrs, igp)
                if wgt[igp, icl, PREV, ildv] != 0.0:
                    hp[igp, icl, CURRENT, ildv] = (hp[igp, icl, PREV, ildv] / wgt[igp, icl, PREV, ildv]) * wgt[igp, icl, CURRENT, ildv]
                else:
                    hp[igp, icl, CURRENT, ildv] = ZERO

                if ildv < 4 or 9 <= ildv <= 12 or ildv == 16:
                    _performance(s, igp, icl, ildv, hp_wgt_base, demand_used, tech_adjhp, tech_max_adjhp, inc90, inc_gr, invgr)
            if s["icl"] == MAXCLASS:
                s["icl"] = MAXCLASS + 1
        if s["igp"] == MAXGROUP:
            s["igp"] = MAXGROUP + 1
    s["ildv"] = MAXLDV + 1

    femrange(s)
    if yrs > XYR:
        for k, a in (("femmpg", fe), ("femwgt", wgt), ("fempri", price), ("femhp", hp), ("femtsz", tank), ("femrng", rng)):
            s[k][G, C, yrs, L] = a[G, C, CURRENT, L]
        s["fempen"][G, C, T, yrs, L] = pen[G, C, T, CURRENT, L]
        if yrs <= int(s["epalyr"]):
            calibnhtsa(s)
            for k, a in (("femmpg", fe), ("femwgt", wgt), ("femhp", hp), ("fempri", price), ("femtsz", tank)):
                a[G, C, CURRENT, L] = s[k][G, C, yrs, L]
            femrange(s)


def _performance(s, igp, icl, ildv, hp_wgt_base, demand_used, tech_adjhp, tech_max_adjhp, inc90, inc_gr, invgr):
    """Horsepower response to income, price and fuel economy, with ceiling, floor and give-back."""
    yrs = int(s["yrs"])
    fem_pass = int(s["fem_pass"])
    fe, wgt, price, hp = s["fe"], s["weight"], s["price"], s["hp"]
    perfcap, vhp = s["perfcap"], s["vhp_adj"]
    rnd = s["roundoff_error"]
    if (inc90[11, yrs - 1] != 0.0 and price[igp, icl, CURRENT, ildv] != 0.0 and fe[igp, icl, PREV, ildv] != 0.0
            and wgt[igp, icl, BASE, ildv] != 0.0 and wgt[igp, icl, CURRENT, ildv] != 0.0
            and perfcap[icl, igp] - hp_wgt_base + demand_used != 0.0):
        k = 1 if ildv == 16 else ildv
        perf_adjhp = (powf(inc_gr, f32(0.9)) * powf(price[igp, icl, PREV, k] / price[igp, icl, CURRENT, k], f32(0.9))
                      * powf(fe[igp, icl, CURRENT, k] / fe[igp, icl, PREV, k], f32(0.2)) * powf(invgr, f32(0.2))) - ONE
        if ildv == 16:
            hp[igp, icl, CURRENT, ildv] = hp[igp, icl, CURRENT, ildv] * vhp[icl, igp, CURRENT, 1]
        else:
            vcw = wgt[igp, icl, CURRENT, ildv] / wgt[igp, icl, PREV, ildv] - ONE if wgt[igp, icl, PREV, ildv] != 0.0 else ZERO
            if vcw < 0.0:
                vhp[icl, igp, CURRENT, ildv] = ONE + (vcw * f32(0.8))
                vhp[icl, igp, PREV, ildv] = vhp[icl, igp, CURRENT, ildv]
            else:
                vhp[icl, igp, CURRENT, ildv] = ONE if vhp[icl, igp, PREV, ildv] == 0.0 else vhp[icl, igp, PREV, ildv]
            hp[igp, icl, CURRENT, ildv] = hp[igp, icl, CURRENT, ildv] * vhp[icl, igp, CURRENT, ildv]
        hp_wgt = ZERO
        if wgt[igp, icl, CURRENT, ildv] != 0.0:
            hp_wgt = hp[igp, icl, CURRENT, ildv] / wgt[igp, icl, CURRENT, ildv]
        perf_coeff = ONE - ((hp_wgt - hp_wgt_base + demand_used) / (perfcap[icl, igp] - hp_wgt_base + demand_used))
        perf_coeff = max(ZERO, min(ONE, perf_coeff))
        perf_adjhp = perf_adjhp * s["perffact"][icl, igp] * perf_coeff
        if fem_pass == 3:
            perf_adjhp = min(perf_adjhp, ZERO)
    else:
        raise ValueError("TDM FEMCALC: STOP 509")

    ttl = tech_adjhp + perf_adjhp
    give = ZERO
    if ttl > 0.1:
        give = ttl - f32(0.1)
        if perf_adjhp > 0.0:
            perf_adjhp = perf_adjhp - give
            if perf_adjhp >= 0.0:
                give = ZERO
            else:
                give = ZERO - perf_adjhp
                perf_adjhp = ZERO
        tech_adjhp = tech_adjhp - give
        ttl = tech_adjhp + perf_adjhp
    w = wgt[igp, icl, CURRENT, ildv]
    if w == 0.0:
        raise ValueError("TDM FEMCALC: STOP, zero weight")
    temp_hp = hp[igp, icl, CURRENT, ildv] * (ONE + ttl)
    hp_wgt = temp_hp / w
    if hp_wgt > perfcap[icl, igp]:
        excess = ttl
        if hp_wgt != 0.0:
            ttl = ((ONE + ttl) * (perfcap[icl, igp] / hp_wgt)) - ONE
        excess = excess - ttl
        if perf_adjhp > 0.0:
            perf_adjhp = perf_adjhp - excess
            if perf_adjhp >= 0.0:
                excess = ZERO
            else:
                excess = ZERO - perf_adjhp
                perf_adjhp = ZERO
        if excess > tech_adjhp:
            excess = tech_adjhp
        tech_adjhp = tech_adjhp - excess
        ttl = tech_adjhp + perf_adjhp
        give = give + excess
        temp_hp = hp[igp, icl, CURRENT, ildv] * (ONE + ttl)
        hp_wgt = temp_hp / w
    h, wb = hp[igp, icl, CURRENT, ildv], wgt[igp, icl, BASE, ildv]
    if w != 0.0 and wb != 0.0 and h != 0.0:
        hp_wgt_min = f32(0.9) * (hp[igp, icl, BASE, ildv] / wb)
        cap = (ONE / f32(25.0)) if (icl == 6 and igp <= 4) else (ONE / f32(30.0))
        hp_wgt_min = min(hp_wgt_min, cap)
        temp_hp = h * (ONE + ttl)
        hp_wgt = temp_hp / w
        min_adjhp = ((hp_wgt_min * w) / h) - ONE
        min_adj = False
    else:
        raise ValueError("TDM FEMCALC: STOP, zero horsepower or weight")
    if hp_wgt < hp_wgt_min:
        min_adj = True
        perf_adjhp = perf_adjhp + (min_adjhp - ttl)
        ttl = tech_adjhp + perf_adjhp
    if ildv < 4 or 9 <= ildv <= 12:
        lux = igp in (4, 5, 11)
        if not lux and fem_pass == 3:
            excess = max(ttl - max(min_adjhp, ZERO), ZERO)
            excess = excess * s["gbinc"]
            if tech_adjhp > rnd and (min_adj and excess > tech_adjhp):
                raise ValueError("TDM FEMCALC: STOP, horsepower give-back above technology gain")
            excess = min(max(tech_adjhp, ZERO), max(excess, ZERO))
            tech_adjhp = tech_adjhp - excess
            ttl = tech_adjhp + perf_adjhp
            give = give + excess
        elif ttl == 0.0:
            give = ZERO
        if not lux:
            if ((tech_max_adjhp > 0.0 and give > (tech_max_adjhp + rnd))
                    or (tech_max_adjhp <= 0.0 and abs(give) > (abs(tech_max_adjhp) + rnd))):
                raise ValueError("TDM FEMCALC: STOP, horsepower give-back above technology gain")
    perf_adjhp = perf_adjhp - give
    sign = -1 if perf_adjhp < 0.0 else 1
    s["sign_tdm"] = sign
    adjfe = (f32(-0.220) * perf_adjhp) - (f32(0.560) * f32(sign) * perf_adjhp * perf_adjhp)
    s["adjfe"] = adjfe
    hp[igp, icl, CURRENT, ildv] = hp[igp, icl, CURRENT, ildv] * (ONE + ttl)
    fe[igp, icl, CURRENT, ildv] = fe[igp, icl, CURRENT, ildv] * (ONE + adjfe)
    price[igp, icl, CURRENT, ildv] = price[igp, icl, CURRENT, ildv] + perf_adjhp * s["valueperf"][icl, igp]
