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


def truck_pbk(v, carry, k, inc_cost, vmt, cpm, cpm_base, mr_ice, veh_shr, refuel):
    """TRUCK_PBK for every region and the VMT bins k (0-based, in order), all at once: (region,
    bin) arrays. Each one's payback NPV, purchase share and S-curve are its own; the curve
    state has no region index, and a bin's curve starts with the same values whichever region
    starts it. FUEL_SHR_REGN adds the bins up, in order."""
    iyr, yrs = v.i("iyr"), v.i("yrs")
    c19, jfuel, iflt = v.i("icafe19"), v.i("jfuel"), v.i("iflt")
    isc4 = v.i("isc4")
    c, j, f, y0 = c19 - 1, jfuel - 1, iflt - 1, iyr - 1
    r = np.arange(MNUMCR - 2)[:, None]          # regions 1-9, 0-based, as a column
    kb = k[None, :]
    veh_cost = inc_cost
    if jfuel == 6 and iflt == 2 and c19 < 16:
        veh_cost = inc_cost - v["bev_infra_cost"][c19, iyr]
    sav = vmt * (cpm_base - cpm)
    npv, mr = v["npv_choice"].a, v["mr_cost"]
    ins, disc = v["insure_rate"], v["discrtxg_p2"]
    net = sav - (ins * veh_cost)
    row = ((net + (mr_ice[1][:, None] - mr[c19, jfuel, 1, iyr]) * vmt) - refuel) / (ONE + disc)
    npv[c, j, kb, 0, r, y0] = row
    for y in range(2, PBK_YR + 1):
        row = row + ((net + (mr_ice[y][:, None] - mr[c19, jfuel, y, iyr]) * vmt) - refuel) / powi(ONE + disc, y)
        npv[c, j, kb, y - 1, r, y0] = row
    tot = fsum(npv[c, j, kb[..., None], np.arange(PBK_YR)[None, None, :], r[..., None], y0], axis=2)
    if (tot != tot).any():
        raise ValueError("TDM TRUCK_PBK: STOP 901, NaN NPV")
    life = v["hdv_usefullife"][1, int(v["p219map"][c19])] * f32(2)
    cost = inc_cost * (ONE + v["sales_tax_rate"].a[:, None])
    vv, pb = v["vmt_veh"].a[k, f, c], v["pback_shr"]
    agg = np.zeros((MNUMCR - 2, k.size), dtype=f32)
    for y in range(1, PBK_YR + 1):
        buy = (~(f32(y) * vv > life)) & (cost < npv[c, j, kb, y - 1, r, y0])
        agg = agg + np.where(buy, pb[y, c19] * veh_shr, ZERO)
    bf, ef = v["bfshxg"][isc4, jfuel, iflt], v["efshxg"][isc4, jfuel, iflt]
    mpath = np.full(agg.shape, ONE)
    on = (agg >= bf) & (yrs >= v["trgshxg"][c19, jfuel, iflt])
    if on.any():
        kk = k[on.any(axis=0)]
        start, midyr, slope, adj = (carry[x].a for x in ("start_curve", "midyr_choice", "slope_choice", "midyr_adj"))
        cy = f32(v["cyafvxg"][isc4, jfuel, iflt])
        new = kk[start[c, j, f, kk] == 0]
        midyr[c, j, f, new] = f32(yrs) * ONE + (ONE * cy / f32(2.0))
        start[c, j, f, new] = 1
        slope[c, j, f, new] = logf(f32(0.01)) / ((ONE * cy) / f32(2.0))
        itry = v.i("itryghg")
        c4 = int(v["p24map"][int(v["p219map"][c19])])
        if itry > 1 and jfuel >= 6 and not v["hdv_passghg"][iyr, c4]:
            if itry <= math.ceil(v["ghgtry"] / 2.0):
                if jfuel in (11, 7, 8):
                    adj[c, j, f, kk] = f32(itry) * f32(0.5)
            elif jfuel not in (11, 7, 8):
                adj[c, j, f, kk] = f32(itry) * f32(0.5)
        kon = np.broadcast_to(kb, on.shape)[on]
        mpath[on] = bf + (ef - bf) / (ONE + (expf(slope[c, j, f, kon]
                                                  * (ONE * f32(yrs) - (midyr[c, j, f, kon] - adj[c, j, f, kon])))))
    x = agg * mpath
    v["fuel_shr_ivmt"].a[y0, kb, f, c, j, r] = x
    regn = v["fuel_shr_regn"].a
    regn[y0, c, j, f, :MNUMCR - 2] = np.add.accumulate(
        np.concatenate((regn[y0, c, j, f, :MNUMCR - 2][:, None], x), axis=1).astype(f32), axis=1, dtype=f32)[:, -1]


def _weighted_rows(values, weights, caller_id):
    """weighted_mean of each row of values (rows, n) with the same weights."""
    if np.isnan(values).any():
        raise ValueError(f"ERROR TDM: (WEIGHTED_MEAN {caller_id}): Input VALUES array contains NaN.")
    total = fsum(weights)
    if total == 0.0:
        return np.zeros(values.shape[0], dtype=f32)
    return (np.add.accumulate(values * weights, axis=1, dtype=f32)[:, -1] + ZERO) / total


def _avg5(a, iyr):
    """Five-year averages for regions 1-9."""
    return fsum(a[R9, iyr - 4:iyr], axis=1) / f32(5.0)


def truck_choice(s: dict, carry: dict) -> None:
    """carry: cpm_r_ice (year iyr-1 filled) and TRUCK_PBK's curve history.

    The Fortran loops over region, fleet, class and fuel; every region's choice is its own
    (TRUCK_PBK's curve state is shared, and set the same by any region), so the nine regions
    run together for each fleet, class and fuel."""
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
    NR = MNUMCR - 2
    regions = range(1, NR + 1)
    dose = v["def_dose_lonox"] if (v.i("nox_switch") == 1 and yrs >= 2027) else v["def_dose"]
    adjng = v["ng_priceadj"]
    avg_fn, avg_ib = _avg5(v["pelfncm"], iyr), _avg5(v["pelibcm"], iyr)
    for iflt in (1, 2):
        v["iflt"] = iflt
        pv, pl, pg = ((v["pgftrpv"], v["pgltrpv"], v["pgftrpv"]) if iflt == 1
                      else (v["pgftrfv"], v["pgltrfv"], v["pgftrfv"]))
        avg_pv, avg_pl, avg_pg = _avg5(pv, iyr), _avg5(pl, iyr), _avg5(pg, iyr)
        for c19 in range(1, CAFE19 + 1):
            v["icafe19"] = c19
            if c19 == 19:
                shr_v[iyr, VM, iflt, c19, 1, R9] = veh[VM, iflt, c19][:, None]
                shr_v[iyr, VM, iflt, c19, 2:FUEL12, R9] = 0.0
                continue
            isc4 = int(sc19[c19])
            v["isc4"] = isc4
            # Operating cost per mile by fuel (rows) and region (columns).
            c = np.zeros((FUEL12 + 1, NR), dtype=f32)
            for ifuel in range(1, FUEL12 + 1):
                if ifuel != 4:
                    c[ifuel] = favg[ifuel, R9] / mpg[iyr, ifuel, c19] * hrate[isc4, ifuel] * f32(1e-6)
                if ifuel == 1:
                    d = ONE / mpg[iyr, ifuel, c19] * dose * v["cost_def"][iyr]
                    v["cpm_def"][iyr, c19, R9] = d
                    c[ifuel] = c[ifuel] + d
                elif ifuel == 6:
                    a6 = avg_fn if (iflt == 1 or c19 > 16) else avg_ib
                    c[6] = a6 * jp1 / mpg[iyr, 6, c19] * hrate[isc4, 6] * f32(1e-6)
                    c[6] = (c[6] + v["evse_maint"] / mpg[iyr, 6, c19] * hrate[isc4, 6] / f32(3412)) / chrg
            v["ifuel"] = FUEL12 + 1
            if c19 <= 7:
                c[4] = (avg_pv * jp1) * adjng[1] / mpg[iyr, 4, c19] * hrate[isc4, 4] * f32(1e-6)
            else:
                cs = v["cng_shrof_ng"][n]
                c[4] = ((avg_pl * adjng[2] * (ONE - cs) + avg_pg * adjng[1] * cs) * jp1) \
                    / mpg[iyr, 4, c19] * hrate[isc4, 4] * f32(1e-6)
            for iregn in regions:
                cpm[iflt, c19, iregn] = c[:, iregn - 1].copy()
            prev = stk[iyr - 1, c19, 1, 1:FUEL12, iflt, R9]          # (fuel, region)
            mr_ice = np.zeros((PBK_YR + 1, NR), dtype=f32)
            m3 = np.stack([mrc[c19, kf, 1:PBK_YR, iyr] for kf in (1, 2, 11)], axis=1)   # [year, fuel 1/2/11]
            base = np.zeros(NR, dtype=f32)
            for iregn in regions:
                p_ = prev[:, iregn - 1]
                ice3 = np.array([p_[0], p_[1], p_[10]], dtype=f32)
                if fsum(ice3) == 0.0:
                    cpm_ice[iyr, iregn, iflt, c19] = cpm_ice[iyr - 1, iregn, iflt, c19]
                    mr_ice[1:, iregn - 1] = (m3[:, 0] + m3[:, 1] + m3[:, 2]) / f32(3)
                elif c19 <= 7:
                    cpm_ice[iyr, iregn, iflt, c19] = weighted_mean(np.array([c[1, iregn - 1], c[2, iregn - 1], c[11, iregn - 1]],
                                                                            dtype=f32), ice3, "CPM_R_ICE")
                    mr_ice[1:, iregn - 1] = _weighted_rows(m3, ice3, "MR_ICE")
                else:
                    cpm_ice[iyr, iregn, iflt, c19] = c[1, iregn - 1]
                    mr_ice[1:, iregn - 1] = m3[:, 0]
                base[iregn - 1] = cpm_ice[iyr, iregn, iflt, c19]
            shr_v[iyr, :, iflt, c19, :, R9] = 0.0
            vs = veh[VM, iflt, c19]

            def pbk_loop(cost, cpm_k, refuel, mr=mr_ice, base_cpm=base, need_cng=False):
                ok = vs > 0.0
                if need_cng:
                    ok &= v["pt_tanksize_cng"][VM, c19] != 9999.
                k = np.nonzero(ok)[0]
                if k.size:
                    b = [int(x) + 1 for x in k]
                    row = lambda g: np.array([g(i) for i in b], dtype=f32) if callable(g) else g  # noqa: E731
                    ck = np.stack([cpm_k(i) for i in b], axis=1) if callable(cpm_k) else cpm_k[:, None]
                    truck_pbk(v, carry, k, row(cost), vmt[VM, iflt, c19][k], ck, base_cpm[:, None], mr, vs[k], row(refuel))
                v["ivmt"] = NVMT + 1

            def clamp(floor_base):
                cur, last = shr_v[iyr, VM, iflt, c19, jfuel, R9], shr_v[iyr - 1, VM, iflt, c19, jfuel, R9]
                lo = last - drop * vs[:, None]
                x = np.maximum(cur, lo)
                if floor_base:
                    x = np.maximum(x, shr_v[bsyr, VM, iflt, c19, jfuel, R9])
                shr_v[iyr, VM, iflt, c19, jfuel, R9] = np.minimum(x, last + rise * vs[:, None])

            def phev_cpm(cs_fuel, cs_mult):
                def f(ivmt):
                    rng = ((v["pt_battkwh_phev"][ivmt, c19] * dod * f32(3412.0) / hrate[isc4, 6]) * mpg[iyr, 6, c19] * phadj) * days
                    uf = min(rng / vmt[ivmt, iflt, c19], ONE)
                    return ((uf / (mpg[iyr, 6, c19] * phadj * chrg)) * favg[6, R9] * hrate[isc4, 6] * f32(1e-6)
                            + ((ONE - uf) / (mpg[iyr, cs_fuel, c19] * cs_mult * phadj)) * favg[cs_fuel, R9] * hrate[isc4, cs_fuel] * f32(1e-6))
                return f

            for jfuel in range(FUEL12, 0, -1):
                v["jfuel"] = jfuel
                if jfuel >= 3 and yrs >= trg[c19, jfuel, iflt]:
                    if jfuel == 4:
                        pbk_loop(lambda kv: v["inc_cost_cng"][kv, c19, iyr], c[4], ZERO, need_cng=True)
                        clamp(True)
                    elif jfuel == 6:
                        if iflt == 1 or c19 >= 16:
                            pbk_loop(lambda kv: v["inc_cost_bev"][kv, c19, iyr] - v["bev_infra_cost"][c19, iyr],
                                     c[6] * v["bev_elec_markup"][c19], lambda kv: v["bev_refuelopcost"][kv, c19, iyr])
                        else:
                            pbk_loop(lambda kv: v["inc_cost_bev"][kv, c19, n], c[6], lambda kv: v["bev_refuelopcost"][kv, c19, iyr])
                        clamp(True)
                    elif jfuel == 7:
                        pbk_loop(lambda kv: v["inc_cost_phevd"][kv, c19, n], phev_cpm(1, v["phev_chgsus_mult"][c19, 1]), ZERO)
                        clamp(False)
                    elif jfuel == 8:
                        pbk_loop(lambda kv: v["inc_cost_phevg"][kv, c19, n], phev_cpm(11, ONE), ZERO)
                        clamp(False)
                    elif jfuel == 9:
                        pbk_loop(lambda kv: v["inc_cost_fcev"][kv, c19, n], c[9], lambda kv: v["h2_refuelopcost"][kv, c19, 1])
                        clamp(False)
                    elif jfuel == 10:
                        pbk_loop(lambda kv: v["inc_cost_fchev"][kv, c19, n], c[10], lambda kv: v["h2_refuelopcost"][kv, c19, 1])
                        clamp(False)
                    elif jfuel == 11:
                        hev_cpm = np.zeros(NR, dtype=f32)
                        mr_hev = np.zeros((PBK_YR + 1, NR), dtype=f32)
                        for iregn in regions:
                            p_ = prev[:, iregn - 1]
                            two = np.array([p_[0], p_[1]], dtype=f32)
                            if fsum(two) == 0.0:
                                hev_cpm[iregn - 1] = (c[1, iregn - 1] + c[2, iregn - 1]) / f32(2)
                                mr_hev[1:, iregn - 1] = (m3[:, 0] + m3[:, 1]) / f32(2)
                            else:
                                hev_cpm[iregn - 1] = weighted_mean(np.array([c[1, iregn - 1], c[2, iregn - 1]], dtype=f32), two,
                                                                   "CPM_ICE_HEV")
                                mr_hev[1:, iregn - 1] = (m3[:, 0] * p_[0] + m3[:, 1] * p_[1]) / fsum(two)
                        pbk_loop(lambda kv: v["inc_cost_hev"][kv, c19, n], c[11], ZERO, mr=mr_hev, base_cpm=hev_cpm)
                        clamp(False)
                    elif jfuel == 12:
                        pbk_loop(lambda kv: v["inc_cost_h2ice"][kv, c19, n], c[12], lambda kv: v["h2_refuelopcost"][kv, c19, 3])
                        clamp(False)
                    else:
                        cyx = f32(cy[isc4, jfuel, iflt])
                        midyr = f32(trg[c19, jfuel, iflt]) + (ONE * cyx / f32(2))
                        slope = logf(f32(0.01)) / ((ONE * cyx) / f32(2))
                        mp = ONE * (bf[isc4, jfuel, iflt] + (ef[isc4, jfuel, iflt] - bf[isc4, jfuel, iflt])
                                    / (ONE + (expf(slope * (ONE * f32(yrs) - midyr)))))
                        shr_v[iyr, VM, iflt, c19, jfuel, R9] = (mp * vs)[:, None]
                elif jfuel == 1:
                    mp = bf[isc4, 1, iflt] + (ef[isc4, 1, iflt] - bf[isc4, 1, iflt]) * (
                        ONE - expf(v["cstdxg"][isc4, iflt] + v["cstdvxg"][isc4, iflt] * (ONE * f32(yrs))))
                    rest = fsum(shr_v[iyr, VM, iflt, c19, 3:FUEL12, R9], axis=1)
                    shr_v[iyr, VM, iflt, c19, 1, R9] = np.maximum(ZERO, mp * (vs[:, None] - rest))
            v["jfuel"] = 0
            others = np.concatenate([shr_v[iyr, VM, iflt, c19, 1:1, R9],
                                     shr_v[iyr, VM, iflt, c19, 3:FUEL12, R9]], axis=1)
            shr_v[iyr, VM, iflt, c19, 2, R9] = np.maximum(ZERO, (vs[:, None] - fsum(others, axis=1)))
            if c19 > 7:
                shr_v[iyr, VM, iflt, c19, 2, R9] = np.minimum(shr_v[iyr, VM, iflt, c19, 2, R9], shr_v[bsyr, VM, iflt, c19, 2, R9])
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
