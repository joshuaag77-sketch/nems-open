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


_SUP_NOTES = {}


def _sup_notes(s):
    """{itech: [(inote, [superseded techs])]}: the supersede notes by technology (inputs, read once)."""
    sup, cnt, num = s["supersedes"], s["tech_cnt"], int(s["num_sup"])
    key = (id(sup), num)
    hit = _SUP_NOTES.get(key)
    if hit is None or hit[0] is not sup:
        notes = {}
        for inote in range(1, num + 1):
            notes.setdefault(int(sup[1, inote]), []).append(
                (inote, [int(sup[i, inote]) for i in range(2, int(cnt[inote]) + 1)]))
        hit = _SUP_NOTES[key] = (sup, notes)
    return hit[1]


def note_super(s, actual, mmax):
    """NOTE_SUPER: a technology and those it supersedes share one market ceiling.
    Only the notes about ITECH do anything, so only those are visited."""
    itech = int(s["itech"])
    rnd = s["roundoff_error"]
    act, mm = actual._p, mmax._p
    for inote, others in _sup_notes(s).get(itech, ()):
        tot = act[itech]
        mx = mm[itech]
        for k in others:
            mx = max(mx, mm[k])
        for i, k in enumerate(others, start=2):
            tot = tot + act[k]
            if tot > mx:
                act[k] = act[k] - (tot - mx)
                tot = mx
                if act[k] < ZERO - rnd:
                    s["inote"], s["i"] = inote, i
                    s["tot_mkt"], s["max_share"] = tot, mx
                    s["return_stat"] = (-100 * inote) - i
                    return
                elif act[k] < 0.0:
                    act[k] = ZERO
        s["i"] = len(others) + 2
        s["tot_mkt"], s["max_share"] = tot, mx
    s["inote"] = int(s["num_sup"]) + 1
    s["return_stat"] = 0



def _funcmax_v(oldmksh, oldpmax):
    """FUNCMAX for a vector of technologies: (ceiling, the I each call leaves, 0 where it sets none)."""
    one = oldpmax == 1.0
    tpmax = np.where(ONE < oldpmax, ONE, oldpmax)
    res = np.where(tpmax > ZERO, tpmax, ZERO)
    ival = np.full(oldpmax.shape, 31)
    for i in range(30, 0, -1):          # descending, so the first I that fits wins
        hit = (oldmksh <= RETD[i - 1]) & (tpmax < RETD[i])
        res = np.where(hit, RETD[i], res)
        ival = np.where(hit, i, ival)
    return np.where(one, ONE, res).astype(f32), np.where(one, 0, ival)


def _tech_loop(s, igp, icl, ildv, ivtyp, numtech, cfe, cfe_inv, perf_coeff, payback, discount, pslope, f1,
               inc_gr, invgr):
    """FEMCALC's first technology loop (cost-effectiveness and logit shares), all technologies at
    once. Each technology's values depend only on its own inputs, so the float32 steps are the
    scalar loop's, element by element; the module variables it leaves (ITECH, I, YEARS_MKTD,
    LEARN_COST_MULTIPLIER) take the values the last technology leaves."""
    yrs, curitr, fem_pass = int(s["yrs"]), int(s["curitr"]), int(s["fem_pass"])
    T = slice(1, numtech)
    op, pen = s["old_pmax"], s["mkt_pen"]
    ap = s["tech_applic"][T, ivtyp, ildv] != 0
    if curitr == 1 and fem_pass == 1:
        op[icl, igp, T, ildv, 1] = np.where(ap, op[icl, igp, T, ildv, 2], op[icl, igp, T, ildv, 1])
    elif fem_pass == 1:
        op[icl, igp, T, ildv, 2] = np.where(ap, op[icl, igp, T, ildv, 1], op[icl, igp, T, ildv, 2])
    fr = s["frstyear"][T, igp]
    on = ap & (yrs >= fr)
    if not on.any():
        s["itech"] = numtech + 1
        return
    techs = np.nonzero(on)[0]           # 0-based: technology techs + 1
    dfe = s["del_fe"][T, ivtyp][on]
    fuelsave = s["fuelsave"]
    if cfe > 0.0:
        savings = cfe_inv - (ONE / ((ONE + dfe) * cfe))
        fs = fuelsave.a[techs]
        price_ex, vmt = s["price_ex"], (s["pvmt"] if igp <= CARGRP else s["lvmt"])
        for i in range(1, payback + 1):
            cur_vmt = vmt[i, 2024 - 1989, MNUMCR, 1]
            price_ex[i] = pslope * (f32(i) + f32(2.0)) + f1
            fs = fs + ((cur_vmt * savings) * price_ex[i]) * powi(ONE + discount, -i)
        fuelsave.a[techs] = fs
        s["i"] = payback + 1
    fs = fuelsave.a[techs]
    dwa, dww, dcw = s["del_wgtabs"][T, ivtyp][on], s["del_wgtwgt"][T, ivtyp][on], s["del_costwgt"][T, ivtyp][on]
    tc = s["del_costabs"][T, ivtyp][on]
    tc = tc + ((dcw * dwa) * np.copysign(ONE, dwa))
    tc = tc + (((dcw * dww) * np.copysign(ONE, dww)) * s["weight"][igp, icl, CURRENT, ildv])
    ly = np.where(fr[on] < 2011, f32(2011), fr[on].astype(f32))
    ym = ((f32(yrs) - ly) + ONE).astype(np.int64)
    learn = s["coeff_learn"]
    g = np.clip(ym, 1, learn.a.shape[0])
    l2 = np.where(ym >= 1, ONE + (s["coeff_lrn1"][T, ivtyp][on] * learn.a[g - 1, 0]), ONE)
    l3 = np.where(ym >= 1, ONE + (s["coeff_lrn2"][T, ivtyp][on] * learn.a[g - 1, 1]), ONE)
    tc = np.where(tc > 0.0, ((tc * l2) * l3), tc).astype(f32)
    ge = np.nonzero(tc >= 0.0)[0]
    if ge.size:
        last = ge[-1]
        lcm = s["learn_cost_multiplier"]
        lcm.a[...] = 1.0
        s["years_mktd"] = int(ym[last])
        if ym[last] >= 1:
            lcm[2], lcm[3] = l2[last], l3[last]
    s["techcost"].a[techs] = tc
    s["tec_ornl"].a[icl - 1, igp - 1, techs, ildv - 1] = tc
    if cfe != 0.0:
        a = (s["valueperf"][icl, igp] * perf_coeff) * inc_gr
        vp = (((a * (ONE + dfe)) * invgr) * s["del_hp"][T, ivtyp][on]).astype(f32)
    else:
        vp = np.zeros(techs.size, dtype=f32)
    s["val_perf"].a[techs] = vp
    pos = tc > 0.0
    m80, p80 = f32(-80.0), f32(80.0)
    cf = ((fs - tc) + ((s["regcost"][igp] * cfe) * dfe)) / tc
    cp = np.where(vp != 0.0, (vp - tc) / tc, m80)
    cf = np.where(pos, np.where(cf > m80, cf, m80), np.where(fs > 0.0, p80, m80)).astype(f32)
    cp = np.where(pos, np.where(cp > m80, cp, m80), np.where(vp > 0.0, p80, m80)).astype(f32)
    s["costef_fuel"].a[techs], s["costef_perf"].a[techs] = cf, cp
    op2 = op.a[icl - 1, igp - 1, techs, ildv - 1, 1]
    prev = pen.a[igp - 1, icl - 1, techs, PREV, ildv - 1]
    if fem_pass == 1 or (fem_pass == 2 and int(s["pass2"]) == 1):
        op2, ival = _funcmax_v(prev, op2)
        op.a[icl - 1, igp - 1, techs, ildv - 1, 1] = op2
        if ival[-1]:
            s["i"] = int(ival[-1])
    kf = np.where(cf < 0.0, f32(-4.0), f32(-2.0))
    mf = (ONE / (ONE + expf(kf * cf))).astype(f32)
    kp = np.where(cp < 0.0, f32(-4.0), f32(-2.0)) * cp
    mp = (ONE / (ONE + expf(np.where(f32(75.0) < kp, f32(75.0), kp)))).astype(f32)
    s["mkt_fuel"].a[techs], s["mkt_perf"].a[techs] = mf, mp
    am = op2 * np.where(mp > mf, mp, mf)
    am = np.where(am > prev, am, prev)
    mm = s["mmax"].a[techs]
    r = np.where(mm < am, mm, am)
    s["actual_mkt"].a[techs] = np.where(ONE < r, ONE, r)
    s["itech"] = numtech + 1

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
    del_fe, del_hp = s["del_fe"], s["del_hp"]
    del_wgtabs, del_wgtwgt = s["del_wgtabs"], s["del_wgtwgt"]
    usedcap, perfcap = s["usedcap"], s["perfcap"]
    inc_gr, invgr, inc90 = s["inc_gr_regn"][11, yrs], s["pmgtr90_invgr"][11, yrs], s["inc90_d_np"]
    cafepass, grpmap = s["cafepass"], s["grpmap"]
    mmax, mkt_perf, mkt_fuel = s["mmax"], s["mkt_perf"], s["mkt_fuel"]
    actual, fuelsave, techcost = s["actual_mkt"], s["fuelsave"], s["techcost"]
    rnd = s["roundoff_error"]
    num_man, num_req, num_syn = int(s["num_man"]), int(s["num_req"]), int(s["num_syn"])
    syn_loss = s.setdefault("_femcalc_synergy_loss", np.zeros(numtech + 1, dtype=f32))

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

                    _tech_loop(s, igp, icl, ildv, ivtyp, numtech, cfe, cfe_inv, perf_coeff, payback, discount,
                               pslope, f1, inc_gr, invgr)

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
