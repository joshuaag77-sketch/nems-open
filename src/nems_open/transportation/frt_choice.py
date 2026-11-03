"""TRUCK_CHOICE and TRUCK_PBK (tranfrt.f): powertrain choice for new trucks.

TRUCK_CHOICE  fuel cost per mile of each powertrain (five-year average prices,
              diesel exhaust fluid, depot or public charging, natural gas mix),
              the diesel/gasoline baseline, then a share for each powertrain in
              each annual-VMT bin, limited to a maximum yearly rise and drop
TRUCK_PBK     buyers adopt when discounted savings (fuel, maintenance, insurance,
              refueling time) pass the price within their payback period; adoption
              then follows an S-curve that starts the first year it is cost-effective

TRUCK_PBK's curve history is a saved local with no year axis, kept in carry
(start_curve, midyr_choice, slope_choice, midyr_adj).
"""

import math

import numpy as np

from nems_open.transportation.common import expf, f32, fsum, logf, MNUMCR
from nems_open.transportation.frt_common import CAFE19, FUEL12, NVMT, ONE, V, ZERO
from nems_open.transportation.mean_funcs import weighted_mean
from nems_open.transportation.misc_modes import powi

R9 = slice(1, MNUMCR - 2)
VM = slice(1, NVMT)
PBK_YR = 7


def truck_pbk(v, carry, inc_cost, vmt, cpm, cpm_base, mr_ice, veh_shr, refuel):
    iyr, yrs = v.i("iyr"), v.i("yrs")
    c19, jfuel, iflt, ivmt, iregn = v.i("icafe19"), v.i("jfuel"), v.i("iflt"), v.i("ivmt"), v.i("iregn")
    isc4 = v.i("isc4")
    veh_cost = inc_cost
    if jfuel == 6 and iflt == 2 and c19 < 16:
        veh_cost = inc_cost - v["bev_infra_cost"][c19, iyr]
    sav = vmt * (cpm_base - cpm)
    npv, mr = v["npv_choice"], v["mr_cost"]
    ins, disc = v["insure_rate"], v["discrtxg_p2"]
    npv[c19, jfuel, ivmt, 1, iregn, iyr] = (sav - (ins * veh_cost) + (mr_ice[1] - mr[c19, jfuel, 1, iyr]) * vmt - refuel) / (ONE + disc)
    for y in range(2, PBK_YR + 1):
        npv[c19, jfuel, ivmt, y, iregn, iyr] = (npv[c19, jfuel, ivmt, y - 1, iregn, iyr]
                                                + (sav - ins * veh_cost + (mr_ice[y] - mr[c19, jfuel, y, iyr]) * vmt - refuel)
                                                / powi(ONE + disc, y))
    tot = fsum(npv[c19, jfuel, ivmt, :, iregn, iyr])
    if tot != tot:
        raise ValueError("TDM TRUCK_PBK: STOP 901, NaN NPV")
    life = v["hdv_usefullife"][1, int(v["p219map"][c19])] * f32(2)
    tax = v["sales_tax_rate"][iregn]
    buy = [ZERO] * (PBK_YR + 1)
    for y in range(1, PBK_YR + 1):
        if f32(y) * v["vmt_veh"][ivmt, iflt, c19] > life:
            continue
        if inc_cost * (ONE + tax) < npv[c19, jfuel, ivmt, y, iregn, iyr]:
            buy[y] = v["pback_shr"][y, c19] * veh_shr
    agg = ZERO
    for y in range(1, PBK_YR + 1):
        agg = agg + buy[y]
    bf, ef = v["bfshxg"][isc4, jfuel, iflt], v["efshxg"][isc4, jfuel, iflt]
    start, midyr, slope, adj = carry["start_curve"], carry["midyr_choice"], carry["slope_choice"], carry["midyr_adj"]
    if agg >= bf and yrs >= v["trgshxg"][c19, jfuel, iflt]:
        cy = f32(v["cyafvxg"][isc4, jfuel, iflt])
        if not start[c19, jfuel, iflt, ivmt]:
            midyr[c19, jfuel, iflt, ivmt] = f32(yrs) * ONE + (ONE * cy / f32(2.0))
            start[c19, jfuel, iflt, ivmt] = 1
            slope[c19, jfuel, iflt, ivmt] = logf(f32(0.01)) / ((ONE * cy) / f32(2.0))
        itry = v.i("itryghg")
        c4 = int(v["p24map"][int(v["p219map"][c19])])
        if itry > 1 and jfuel >= 6 and not v["hdv_passghg"][iyr, c4]:
            if itry <= math.ceil(v["ghgtry"] / 2.0):
                if jfuel in (11, 7, 8):
                    adj[c19, jfuel, iflt, ivmt] = f32(itry) * f32(0.5)
            elif jfuel not in (11, 7, 8):
                adj[c19, jfuel, iflt, ivmt] = f32(itry) * f32(0.5)
        mpath = bf + (ef - bf) / (ONE + (expf(slope[c19, jfuel, iflt, ivmt]
                                                 * (ONE * f32(yrs) - (midyr[c19, jfuel, iflt, ivmt] - adj[c19, jfuel, iflt, ivmt])))))
    else:
        mpath = ONE
    v["fuel_shr_ivmt"][iyr, ivmt, iflt, c19, jfuel, iregn] = agg * mpath
    v["fuel_shr_regn"][iyr, c19, jfuel, iflt, iregn] = v["fuel_shr_regn"][iyr, c19, jfuel, iflt, iregn] + agg * mpath


def _avg5(a, r, iyr):
    return fsum(a[r, iyr - 4:iyr]) / f32(5.0)


def truck_choice(s: dict, carry: dict) -> None:
    """carry: cpm_r_ice (year iyr-1 filled) and TRUCK_PBK's curve history."""
    v = V(s)
    iyr, n, yrs = v.i("iyr"), v.i("n"), v.i("yrs")
    bsyr = v.i("bsyr_stk") - 1989
    shr_v, shr_r = v["fuel_shr_ivmt"], v["fuel_shr_regn"]
    stk = v["trkstk_19r"]
    shr_r[iyr, :, :, :, :] = 0.0
    stk[iyr, :, 1, :, :, :] = 0.0
    cpm_ice = carry["cpm_r_ice"]
    cpm = v.priv("cpm_r", lambda: {})
    mpg, hrate, favg = v["new_mpg_19"], v["hrate"], v["fuelprice_r_avg"]
    jp1 = v["mc_jpgdp"][1]
    veh, vmt, mrc = v["veh_shr"], v["vmt_veh"], v["mr_cost"]
    drop, rise = v["max_drop"], v["max_rise"]
    sc19 = v["sc19map"]
    trg, cy, bf, ef = v["trgshxg"], v["cyafvxg"], v["bfshxg"], v["efshxg"]
    chrg = v["chrg_eff"][iyr]
    dod, phadj, days = v["trk_phev_dod"], v["phev_mpg_adj"], v["ann_uptime_days"]
    for iregn in range(1, MNUMCR - 1):
        v["iregn"] = iregn
        for iflt in (1, 2):
            v["iflt"] = iflt
            for c19 in range(1, CAFE19 + 1):
                v["icafe19"] = c19
                if c19 == 19:
                    shr_v[iyr, VM, iflt, c19, 1, iregn] = veh[VM, iflt, c19]
                    shr_v[iyr, VM, iflt, c19, 2:FUEL12, iregn] = 0.0
                    continue
                isc4 = int(sc19[c19])
                v["isc4"] = isc4
                c = np.zeros(FUEL12 + 1, dtype=f32)
                for ifuel in range(1, FUEL12 + 1):
                    if ifuel != 4:
                        c[ifuel] = favg[ifuel, iregn] / mpg[iyr, ifuel, c19] * hrate[isc4, ifuel] * f32(1e-6)
                    if ifuel == 1:
                        dose = v["def_dose_lonox"] if (v.i("nox_switch") == 1 and yrs >= 2027) else v["def_dose"]
                        d = ONE / mpg[iyr, ifuel, c19] * dose * v["cost_def"][iyr]
                        v["cpm_def"][iyr, c19, iregn] = d
                        c[ifuel] = c[ifuel] + d
                    elif ifuel == 6:
                        pe = v["pelfncm"] if (iflt == 1 or c19 > 16) else v["pelibcm"]
                        c[6] = _avg5(pe, iregn, iyr) * jp1 / mpg[iyr, 6, c19] * hrate[isc4, 6] * f32(1e-6)
                        c[6] = (c[6] + v["evse_maint"] / mpg[iyr, 6, c19] * hrate[isc4, 6] / f32(3412)) / chrg
                v["ifuel"] = FUEL12 + 1
                adjng = v["ng_priceadj"]
                if c19 <= 7:
                    p = v["pgftrpv"] if iflt == 1 else v["pgftrfv"]
                    c[4] = (_avg5(p, iregn, iyr) * jp1) * adjng[1] / mpg[iyr, 4, c19] * hrate[isc4, 4] * f32(1e-6)
                else:
                    pl, pg = (v["pgltrpv"], v["pgftrpv"]) if iflt == 1 else (v["pgltrfv"], v["pgftrfv"])
                    cs = v["cng_shrof_ng"][n]
                    c[4] = ((_avg5(pl, iregn, iyr) * adjng[2] * (ONE - cs) + _avg5(pg, iregn, iyr) * adjng[1] * cs) * jp1) \
                        / mpg[iyr, 4, c19] * hrate[isc4, 4] * f32(1e-6)
                cpm[iflt, c19, iregn] = c
                prev = stk[iyr - 1, c19, 1, :, iflt, iregn]
                ice3 = np.array([prev[0], prev[1], prev[10]], dtype=f32)
                mr_ice = [None] * (PBK_YR + 1)
                if fsum(ice3) == 0.0:
                    cpm_ice[iyr, iregn, iflt, c19] = cpm_ice[iyr - 1, iregn, iflt, c19]
                    for y in range(1, PBK_YR + 1):
                        mr_ice[y] = (mrc[c19, 1, y, iyr] + mrc[c19, 2, y, iyr] + mrc[c19, 11, y, iyr]) / f32(3)
                elif c19 <= 7:
                    cpm_ice[iyr, iregn, iflt, c19] = weighted_mean(np.array([c[1], c[2], c[11]], dtype=f32), ice3, "CPM_R_ICE")
                    for y in range(1, PBK_YR + 1):
                        mr_ice[y] = weighted_mean(np.array([mrc[c19, k, y, iyr] for k in (1, 2, 11)], dtype=f32), ice3, "MR_ICE")
                else:
                    cpm_ice[iyr, iregn, iflt, c19] = c[1]
                    for y in range(1, PBK_YR + 1):
                        mr_ice[y] = mrc[c19, 1, y, iyr]
                base = cpm_ice[iyr, iregn, iflt, c19]
                shr_v[iyr, :, iflt, c19, :, iregn] = 0.0

                def pbk_loop(cost, cpm_k, refuel, mr=mr_ice, base_cpm=base, need_cng=False):
                    for ivmt in range(1, NVMT + 1):
                        v["ivmt"] = ivmt
                        if veh[ivmt, iflt, c19] > 0.0 and (not need_cng or v["pt_tanksize_cng"][ivmt, c19] != 9999.):
                            ck = cpm_k(ivmt) if callable(cpm_k) else cpm_k
                            rf = refuel(ivmt) if callable(refuel) else refuel
                            truck_pbk(v, carry, cost(ivmt), vmt[ivmt, iflt, c19], ck, base_cpm, mr, veh[ivmt, iflt, c19], rf)
                    v["ivmt"] = NVMT + 1

                def clamp(floor_base):
                    cur, last = shr_v[iyr, VM, iflt, c19, jfuel, iregn], shr_v[iyr - 1, VM, iflt, c19, jfuel, iregn]
                    lo = last - drop * veh[VM, iflt, c19]
                    x = np.maximum(cur, lo)
                    if floor_base:
                        x = np.maximum(x, shr_v[bsyr, VM, iflt, c19, jfuel, iregn])
                    shr_v[iyr, VM, iflt, c19, jfuel, iregn] = np.minimum(x, last + rise * veh[VM, iflt, c19])

                def phev_cpm(cs_fuel, cs_mult):
                    def f(ivmt):
                        rng = ((v["pt_battkwh_phev"][ivmt, c19] * dod * f32(3412.0) / hrate[isc4, 6]) * mpg[iyr, 6, c19] * phadj) * days
                        uf = min(rng / vmt[ivmt, iflt, c19], ONE)
                        return ((uf / (mpg[iyr, 6, c19] * phadj * chrg)) * favg[6, iregn] * hrate[isc4, 6] * f32(1e-6)
                                + ((ONE - uf) / (mpg[iyr, cs_fuel, c19] * cs_mult * phadj)) * favg[cs_fuel, iregn] * hrate[isc4, cs_fuel] * f32(1e-6))
                    return f

                for jfuel in range(FUEL12, 0, -1):
                    v["jfuel"] = jfuel
                    if jfuel >= 3 and yrs >= trg[c19, jfuel, iflt]:
                        if jfuel == 4:
                            pbk_loop(lambda k: v["inc_cost_cng"][k, c19, iyr], c[4], ZERO, need_cng=True)
                            clamp(True)
                        elif jfuel == 6:
                            if iflt == 1 or c19 >= 16:
                                pbk_loop(lambda k: v["inc_cost_bev"][k, c19, iyr] - v["bev_infra_cost"][c19, iyr],
                                         c[6] * v["bev_elec_markup"][c19], lambda k: v["bev_refuelopcost"][k, c19, iyr])
                            else:
                                pbk_loop(lambda k: v["inc_cost_bev"][k, c19, n], c[6], lambda k: v["bev_refuelopcost"][k, c19, iyr])
                            clamp(True)
                        elif jfuel == 7:
                            pbk_loop(lambda k: v["inc_cost_phevd"][k, c19, n], phev_cpm(1, v["phev_chgsus_mult"][c19, 1]), ZERO)
                            clamp(False)
                        elif jfuel == 8:
                            pbk_loop(lambda k: v["inc_cost_phevg"][k, c19, n], phev_cpm(11, ONE), ZERO)
                            clamp(False)
                        elif jfuel == 9:
                            pbk_loop(lambda k: v["inc_cost_fcev"][k, c19, n], c[9], lambda k: v["h2_refuelopcost"][k, c19, 1])
                            clamp(False)
                        elif jfuel == 10:
                            pbk_loop(lambda k: v["inc_cost_fchev"][k, c19, n], c[10], lambda k: v["h2_refuelopcost"][k, c19, 1])
                            clamp(False)
                        elif jfuel == 11:
                            two = np.array([prev[0], prev[1]], dtype=f32)
                            if fsum(two) == 0.0:
                                hev_cpm = (c[1] + c[2]) / f32(2)
                                mr_hev = [None] + [(mrc[c19, 1, y, iyr] + mrc[c19, 2, y, iyr]) / f32(2) for y in range(1, PBK_YR + 1)]
                            else:
                                hev_cpm = weighted_mean(np.array([c[1], c[2]], dtype=f32), two, "CPM_ICE_HEV")
                                mr_hev = [None] + [(mrc[c19, 1, y, iyr] * prev[0] + mrc[c19, 2, y, iyr] * prev[1]) / fsum(two)
                                                   for y in range(1, PBK_YR + 1)]
                            pbk_loop(lambda k: v["inc_cost_hev"][k, c19, n], c[11], ZERO, mr=mr_hev, base_cpm=hev_cpm)
                            clamp(False)
                        elif jfuel == 12:
                            pbk_loop(lambda k: v["inc_cost_h2ice"][k, c19, n], c[12], lambda k: v["h2_refuelopcost"][k, c19, 3])
                            clamp(False)
                        else:
                            cyx = f32(cy[isc4, jfuel, iflt])
                            midyr = f32(trg[c19, jfuel, iflt]) + (ONE * cyx / f32(2))
                            slope = logf(f32(0.01)) / ((ONE * cyx) / f32(2))
                            mp = ONE * (bf[isc4, jfuel, iflt] + (ef[isc4, jfuel, iflt] - bf[isc4, jfuel, iflt])
                                        / (ONE + (expf(slope * (ONE * f32(yrs) - midyr)))))
                            shr_v[iyr, VM, iflt, c19, jfuel, iregn] = mp * veh[VM, iflt, c19]
                    elif jfuel == 1:
                        mp = bf[isc4, 1, iflt] + (ef[isc4, 1, iflt] - bf[isc4, 1, iflt]) * (
                            ONE - expf(v["cstdxg"][isc4, iflt] + v["cstdvxg"][isc4, iflt] * (ONE * f32(yrs))))
                        rest = fsum(shr_v[iyr, VM, iflt, c19, 3:FUEL12, iregn], axis=1)
                        shr_v[iyr, VM, iflt, c19, 1, iregn] = np.maximum(ZERO, mp * (veh[VM, iflt, c19] - rest))
                v["jfuel"] = 0
                others = np.concatenate([shr_v[iyr, VM, iflt, c19, 1:1, iregn],
                                         shr_v[iyr, VM, iflt, c19, 3:FUEL12, iregn]], axis=1)
                shr_v[iyr, VM, iflt, c19, 2, iregn] = np.maximum(ZERO, (veh[VM, iflt, c19] - fsum(others, axis=1)))
                if c19 > 7:
                    shr_v[iyr, VM, iflt, c19, 2, iregn] = np.minimum(shr_v[iyr, VM, iflt, c19, 2, iregn], shr_v[bsyr, VM, iflt, c19, 2, iregn])
            v["icafe19"] = CAFE19 + 1
        v["iflt"] = 3
    v["iregn"] = MNUMCR - 1

    temp = fsum(fsum(shr_v[iyr, VM, 1:2, 1:CAFE19, 1:FUEL12, R9], axis=3), axis=0)   # (flt, cafe19, regn)
    new = v["newtrucks_regn"]
    for iregn in range(1, MNUMCR - 1):
        shr_v[iyr, VM, 1:2, 1:CAFE19, 1:FUEL12, iregn] = (shr_v[iyr, VM, 1:2, 1:CAFE19, 1:FUEL12, iregn]
                                                         / temp[None, :, :, iregn - 1, None])
        for iflt in (1, 2):
            shr_r[iyr, 1:CAFE19, 1:FUEL12, iflt, iregn] = fsum(shr_v[iyr, VM, iflt, 1:CAFE19, 1:FUEL12, iregn], axis=0)
        stk[iyr, 1:CAFE19, 1, 1:FUEL12, 1:2, iregn] = (new[iyr, 1:CAFE19, 1:2, iregn][:, None, :]
                                                       * shr_r[iyr, 1:CAFE19, 1:FUEL12, 1:2, iregn])
        if iregn == MNUMCR - 2:
            stk[iyr, 1:CAFE19, 1:34, 1:FUEL12, 1:2, 11] = fsum(stk[iyr, 1:CAFE19, 1:34, 1:FUEL12, 1:2, R9], axis=4)
    v["iregn"], v["iflt"] = MNUMCR - 1, 3
