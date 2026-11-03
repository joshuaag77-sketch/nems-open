"""TRUCK_VMT and TCOMMCL_TRK (tranfrt.f).

TRUCK_VMT    freight ton-miles by region and industrial sector grow with industrial
             output; truck VMT follows, then VMT per truck by class, vintage and fuel
             (from where new trucks of each fuel sit in the VMT bins) is scaled to the
             total; commercial light truck VMT; VMT by old size class and region
TCOMMCL_TRK  new and stock fuel economy of commercial light trucks

carry: TRUCK_VMT's saved ttonmi, tvmt and temp_stk_vmt_ratio (years before iyr).
"""

import numpy as np

from nems_open.transportation.common import MNUMCR, f32, fsum
from nems_open.transportation.frt_common import AGE, CAFE19, FUEL12, NVMT, SC, V
from nems_open.transportation.mean_funcs import harmonic_mean

R9 = slice(1, MNUMCR - 2)
CUR = 2
NSEC = 16      # SEC - 2: the non-service sectors
FAF = 28       # iFAFyear


def truck_vmt(s: dict, carry: dict) -> None:
    v = V(s)
    iyr, n, yrs = v.i("iyr"), v.i("n"), v.i("yrs")
    bsyr_vmt, bsyr = v.i("bsyr_vmt"), v.i("bsyr_stk")
    ton, tvmt, ratio = carry["ttonmi"], carry["tvmt"], carry["temp_stk_vmt_ratio"]
    tsic, ttm = v["tsic"], v["ttm_output"]
    if FAF <= iyr <= bsyr_vmt:
        for iregn in range(1, MNUMCR - 1):
            for isec in range(1, NSEC + 1):
                if iyr == FAF:
                    ttm[iregn, isec] = (v["ttonmi_orig"][iregn, isec] / (tsic[isec, iregn, FAF] * f32(0.001))
                                        if tsic[isec, iregn, FAF] > 0.0 else f32(0.0))
                ton[iyr, iregn, isec] = ttm[iregn, isec] * (tsic[isec, iregn, iyr] * f32(.001))
        v["isec"] = NSEC + 1
    dmd, hist = v["vmtdmdr"], v["thist_vmt"]
    for iregn in range(1, MNUMCR - 1):
        if iyr <= bsyr_vmt:
            dmd[iyr, iregn] = hist[iyr, iregn] * f32(1.0e9)
            if iyr >= FAF:
                dmd[iyr, iregn] = (fsum(hist[iyr, R9]) * (fsum(ton[iyr, iregn, 1:NSEC]) / (fsum(ton[iyr, R9, 1:NSEC])))) * f32(1.0e9)
        else:
            for isec in range(1, NSEC + 1):
                if iyr == bsyr_vmt + 1:
                    tvmt[bsyr_vmt, iregn, isec] = (fsum(hist[bsyr_vmt, R9]) * (ton[bsyr_vmt, iregn, isec]
                                                   / fsum(ton[bsyr_vmt, R9, 1:NSEC]))) * f32(1.0e9)
                ton[iyr, iregn, isec] = ttm[iregn, isec] * (tsic[isec, iregn, iyr] / f32(1000.))
                gr = ton[iyr, iregn, isec] / ton[iyr - 1, iregn, isec]
                tvmt[iyr, iregn, isec] = tvmt[iyr - 1, iregn, isec] * gr
            v["isec"] = NSEC + 1
            dmd[iyr, iregn] = fsum(tvmt[iyr, iregn, 1:NSEC])
    dmd[iyr, 11] = fsum(dmd[iyr, R9])

    ann19, vveh, vshr = v["annvmt_19"], v["vmt_veh"], v["veh_shr"]
    stk, shr_v = v["trkstk_19r"], v["fuel_shr_ivmt"]
    b = bsyr - 1989
    if yrs > bsyr:
        for c19 in range(1, CAFE19 + 1):
            # VMT_10YR_AVG: a saved local from 2025; VMT_VEH and VEH_SHR are fixed inputs.
            avg10 = fsum(vveh[1:NVMT, 1:2, c19] * vshr[1:NVMT, 1:2, c19]) / f32(2)
            if yrs == bsyr + 1:
                ratio[6:b, c19, :, :] = 1.0
            for ifuel in range(1, FUEL12 + 1):
                sh = np.zeros(NVMT, dtype=f32)
                for ivmt in range(1, NVMT + 1):
                    for iflt in (1, 2):
                        for iregn in range(1, MNUMCR - 1):
                            tot = fsum(shr_v[iyr, :, iflt, c19, ifuel, iregn])
                            if tot == 0.0:
                                continue
                            sh[ivmt - 1] = sh[ivmt - 1] + shr_v[iyr, ivmt, iflt, c19, ifuel, iregn] / tot * stk[iyr, c19, 1, ifuel, iflt, iregn]
                t = fsum(sh)
                if t != 0.0:
                    sh = sh / t
                ratio[iyr, c19, 1, ifuel] = fsum(sh * vveh[1:NVMT, 1, c19])
                ratio[iyr, c19, 1, ifuel] = ratio[iyr, c19, 1, ifuel] / avg10
                ann19[iyr, c19, 1, ifuel] = ann19[b, c19, 1, 1] * ratio[iyr, c19, 1, ifuel]
                diesel_fix = ifuel == 2 and (c19 > 7 or c19 <= 2)
                if diesel_fix:
                    ann19[iyr, c19, 1, ifuel] = ann19[b, c19, 1, 2] / ann19[b, c19, 1, 1] * ann19[iyr, c19, 1, 1]
                for iage in range(2, AGE + 1):
                    ratio[iyr, c19, iage, ifuel] = ratio[iyr - 1, c19, iage - 1, ifuel] if iage < AGE else ratio[iyr - 1, c19, iage, ifuel]
                    ann19[iyr, c19, iage, ifuel] = ann19[b, c19, iage, 1] * ratio[iyr, c19, iage, ifuel]
                    if diesel_fix:
                        ann19[iyr, c19, iage, ifuel] = ann19[b, c19, iage, 2] / ann19[b, c19, iage, 1] * ann19[iyr, c19, iage, 1]
        v.s.update({v.key("icafe19"): CAFE19 + 1, v.key("ivmt"): NVMT + 1})

    ann = v["annvmt"]
    old = v["trkstk"]
    agg = f32(0.0)
    for iflt in (1, 2):
        if yrs <= 2011:
            agg = agg + fsum(fsum(ann[1:3, 1:AGE, 1:FUEL12, 1:2], axis=3) / f32(2) * old[iyr, 1:3, 1:AGE, 1:FUEL12, iflt])
        else:
            agg = agg + fsum(ann19[iyr, 3:CAFE19, 1:AGE, 1:FUEL12] * stk[iyr, 3:CAFE19, 1:AGE, 1:FUEL12, iflt, 11])
    adj = dmd[iyr, 11] / agg
    ann[1:3, 1:AGE, 1:FUEL12, 1:2] = ann[1:3, 1:AGE, 1:FUEL12, 1:2] * adj
    ann19[iyr, 3:19, 1:AGE, 1:FUEL12] = ann19[iyr, 3:19, 1:AGE, 1:FUEL12] * adj
    vflt = v["vmtflt"]
    vflt[CUR, 1:3, :, :, :] = 0.0

    clt, cvmt, cvmtt, cmap, sic = v["cltstk"], v["cltvmt"], v["cltvmtt"], v["cltmap"], v["cltsic"]
    agg = f32(0.0)
    for ifuel in range(1, FUEL12 + 1):
        for iage in range(1, AGE + 1):
            if yrs <= 2011:
                tot = fsum(clt[n, ifuel, :, :, 11])
                cvmt[n, ifuel, iage] = (cvmtt[ifuel, n] * f32(1000000000.0) * fsum(clt[n, ifuel, iage, :, 11]) / tot) if tot > 0.0 else f32(0.0)
            elif yrs == 2012:
                agg = agg + clt[n, ifuel, iage, 1, 11] * ann19[iyr, 1, iage, ifuel] + clt[n, ifuel, iage, 2, 11] * ann19[iyr, 2, iage, ifuel]
    if yrs > 2011:
        if yrs == 2012:
            adj = (fsum(cvmt[n - 1, :, :]) * sic[n] / sic[n - 1]) / agg
            ann19[iyr, 1:2, :, :] = ann19[iyr, 1:2, :, :] * adj
        else:
            ann19[iyr, 1:2, :, :] = ann19[iyr - 1, 1:2, :, :] * (sic[n] / sic[n - 1]) / (fsum(clt[n, :, :, :, 11]) / fsum(clt[n - 1, :, :, :, 11]))
        for ifuel in range(1, FUEL12 + 1):
            k = int(cmap[ifuel])
            for iage in range(1, AGE + 1):
                cvmt[n, k, iage] = clt[n, k, iage, 1, 11] * ann19[iyr, 1, iage, ifuel] + clt[n, k, iage, 2, 11] * ann19[iyr, 2, iage, ifuel]
            cvmtt[k, n] = fsum(cvmt[n, k, 1:AGE]) / f32(1000000000.0)

    big = list(range(8, 20))
    for iage in range(1, AGE + 1):
        for ifuel in range(1, FUEL12 + 1):
            for iflt in (1, 2):
                if yrs <= 2011:
                    for isc in range(1, 4):
                        vflt[CUR, isc, iage, ifuel, iflt] = fsum(ann[isc, iage, ifuel, 1:2]) / f32(2) * old[iyr, isc, iage, ifuel, iflt]
                    v["isc"] = 4
                else:
                    for isc, cls in ((1, [3, 4]), (2, [5, 6, 7]), (3, big)):
                        vflt[CUR, isc, iage, ifuel, iflt] = fsum(np.array([ann19[iyr, c, iage, ifuel] * stk[iyr, c, iage, ifuel, iflt, 11] for c in cls], dtype=f32))
    v["vmtflt_19"][iyr, 1:CAFE19, 1:AGE, 1:FUEL12] = ann19[iyr, 1:CAFE19, 1:AGE, 1:FUEL12] * fsum(stk[iyr, 1:CAFE19, 1:AGE, 1:FUEL12, 1:2, 11], axis=3)
    vfr = v["vmtfltr"]
    for iregn in range(1, MNUMCR + 1):
        sh = dmd[iyr, iregn] / dmd[iyr, 11]
        vfr[CUR, 1:SC, 1:AGE, 1:FUEL12, 1:2, iregn] = vflt[CUR, 1:SC, 1:AGE, 1:FUEL12, 1:2] * sh
    v.s.update({v.key("iregn"): MNUMCR + 1, v.key("iflt"): 3, v.key("iage"): AGE + 1, v.key("ifuel"): FUEL12 + 1})


def tcommcl_trk(s: dict) -> None:
    v = V(s)
    iyr = v.i("iyr")
    clt, mpg, vmt = v["cltstk"], v["cltmpg_yr"], v["cltvmt"]
    v["ncltmpg"][iyr, 1:FUEL12] = mpg[iyr, 1:FUEL12, 1]
    share = fsum(clt[iyr, 1:FUEL12, 1, 1:2, MNUMCR], axis=1) / fsum(clt[iyr, 1:FUEL12, 1, 1:2, MNUMCR])
    v["ncltmpgt"][iyr] = harmonic_mean(v["ncltmpg"][iyr, 1:FUEL12], share)
    for ifuel in range(1, FUEL12 + 1):
        num = den = f32(0.0)
        for iage in range(1, AGE + 1):
            m = mpg[iyr, ifuel, iage]
            if m > 0.0:
                num = num + vmt[iyr, ifuel, iage]
                den = den + vmt[iyr, ifuel, iage] / m
        v["cltmpg"][iyr, ifuel] = num / den if den > 0.0 else f32(0.0)
    v.s.update({v.key("ifuel"): FUEL12 + 1, v.key("iage"): AGE + 1})
