"""TRUCK_FUEL (tranfrt.f): heavy truck and class 2b fuel use.

Fuel by size class, fuel, fleet and region from VMT over stock MPG (platooning
savings for class 7-8 fleet trucks), plug-in hybrid electric shares by vintage,
charging losses, conversion to Btu by NEMS fuel, commercial light truck fuel, the
public/depot charging split, and natural gas demand for NGTDM.

EIA quirks kept:
- The PHEV charging-loss correction uses the class 2b electric VMT share for every class.
- The charging split tests IFLT, which an earlier loop leaves at 3, so every
  non-sleeper truck counts as depot charging.
"""

import numpy as np

from nems_open.transportation.common import MNUMCR, f32, fsum
from nems_open.transportation.frt_common import AGE, CAFE19, FUEL12, ONE, SC4, V, ZERO

R9 = slice(1, MNUMCR - 2)
CUR = 2
NFT, FLT = 1, 2
E12 = f32(1e-12)


def truck_fuel(s: dict) -> None:
    v = V(s, angtdm=False)   # TRUCK_FUEL includes NGTDMOUT, not ANGTDM
    iyr, yrs, curiyr = v.i("iyr"), v.i("yrs"), v.i("curiyr")
    toon = v["toonshr"]
    toonyear = v.i("toonyear")
    toon[1:toonyear - 1] = 0.0
    cav = np.zeros((4, AGE + 1), dtype=f32)              # VMTFLTR_CAV_SHR(CUR, isc=3, age, :, flt=2, :)
    cav_adj = ZERO
    if toonyear <= curiyr <= v.i("lastyr"):
        for iage in range(1, curiyr - toonyear + 2):
            v["isc"], v["iflt"] = 3, 2
            cav[3, iage] = toon[curiyr]
        v["iage"] = curiyr - toonyear + 2
        cav_adj = f32(.07)
    cav = cav * f32(.656)

    stk, pct, avgp = v["trkstk_19r"], v["pctevmt_phev"], v["pctevmt_phev_avg"]
    share = v["phev_evmt_share"]
    sc19 = v["sc19map"]
    for iregn in range(1, MNUMCR + 1):
        pct[iyr, :, iregn, :] = 0.0
        avgp[iyr, iregn, :] = 0.0
        if iregn == 10 or iyr <= 33:
            continue
        for c19 in range(1, CAFE19 + 1):
            isc4 = int(sc19[c19])
            v["isc4"] = isc4
            for iflt in (1, 2):
                for f, k in ((7, 1), (8, 2)):
                    if fsum(stk[iyr, c19, :, f, iflt, iregn]) > 0.0:
                        for iage in range(1, AGE + 1):
                            x = stk[iyr, c19, iage, f, iflt, iregn]
                            if x > 0.0:
                                pct[iyr, isc4, iregn, k] = pct[iyr, isc4, iregn, k] + share[iyr - iage + 1, iflt, c19, iregn, k] * x
                        v["iage"] = AGE + 1
        for i, k in ((7, 1), (8, 2)):
            tot = fsum(stk[iyr, :, :, i, :, iregn])
            if tot > 0.0:
                avgp[iyr, iregn, k] = fsum(pct[iyr, :, iregn, k]) / tot
            for isc, cls in ((1, slice(3, 4)), (2, slice(5, 7)), (3, slice(8, 19)), (4, slice(1, 2))):
                t = fsum(stk[iyr, cls, :, i, :, iregn])
                if t > 0.0:
                    pct[iyr, isc, iregn, k] = pct[iyr, isc, iregn, k] / t
    v.s.update({v.key("iregn"): MNUMCR + 1, v.key("icafe19"): CAFE19 + 1, v.key("iflt"): 3})

    dmd, btu = v["fueldmdr"], v["fuelbtur"]
    dmd[1:SC4, 1:FUEL12, 1:2, 1:MNUMCR] = 0.0
    hdv, vfr, clt, cmap, cvmt = v["hdv_mpg"], v["vmtfltr"], v["cltmpg_yr"], v["cltmap"], v["cltvmt"]
    vflt19, chrg, hrate, af = v["vmtflt_19"], v["chrg_eff"][iyr], v["hrate"], v["pctaf"]
    for isc in range(1, SC4 + 1):
        for iflt in (1, 2):
            for iregn in range(1, MNUMCR - 1):
                for ifuel in range(1, FUEL12 + 1):
                    acc = dmd[isc, ifuel, iflt, iregn]
                    k = int(cmap[ifuel])
                    for iage in range(1, AGE + 1):
                        if isc != 4:
                            m = hdv[iyr, isc, iage, ifuel]
                            if m > 0.0:
                                c = cav[isc, iage] if (isc == 3 and iflt == 2) else ZERO
                                a = cav_adj if isc == 3 else ZERO
                                vm = vfr[CUR, isc, iage, ifuel, iflt, iregn]
                                acc = (acc + ((ONE - c) * vm / (m))) + (c) * vm / (m / (ONE - a))
                        elif yrs <= 2011:
                            tot = fsum(stk[2012 - 1989, 1:2, iage, ifuel, 1:2, 11])
                            if clt[iyr, k, iage] > 0.0 and tot > 0.0:
                                acc = acc + cvmt[iyr, k, iage] / clt[iyr, k, iage] * fsum(stk[2012 - 1989, 1:2, iage, ifuel, iflt, iregn]) / tot
                        else:
                            tot = fsum(stk[iyr, 1:2, iage, ifuel, 1:2, 11])
                            if clt[iyr, k, iage] > 0.0 and tot > 0.0:
                                acc = acc + fsum(vflt19[iyr, 1:2, iage, ifuel]) * fsum(stk[iyr, 1:2, iage, ifuel, iflt, iregn]) / tot / clt[iyr, k, iage]
                    if ifuel == 6:
                        acc = acc / chrg
                    elif ifuel in (7, 8):
                        p = pct[iyr, 4, iregn, ifuel - 6]
                        acc = acc * p / chrg + acc * (ONE - p)
                    dmd[isc, ifuel, iflt, iregn] = acc
                d = lambda f: dmd[isc, f, iflt, iregn] * hrate[isc, f] * E12  # noqa: E731
                p1, p2 = pct[iyr, isc, iregn, 1], pct[iyr, isc, iregn, 2]
                btu[isc, 1, iflt, iregn] = d(1) + d(7) * (ONE - p1)
                btu[isc, 2, iflt, iregn] = d(2) + d(5) * (ONE - af[2, iregn, iyr]) + d(8) * (ONE - p2) + d(11)
                btu[isc, 3, iflt, iregn] = d(3)
                btu[isc, 4, iflt, iregn] = d(4)
                btu[isc, 5, iflt, iregn] = d(5) * af[2, iregn, iyr]
                btu[isc, 6, iflt, iregn] = d(6) + d(7) * p1 + d(8) * p2
                btu[isc, 7, iflt, iregn] = d(9) + d(10) + d(12)
            for ifuel in range(1, 8):
                btu[isc, ifuel, iflt, 11] = fsum(btu[isc, ifuel, iflt, R9])
    v.s.update({v.key("isc"): SC4 + 1, v.key("iflt"): 3, v.key("iregn"): MNUMCR - 1, v.key("ifuel"): 8, v.key("iage"): AGE + 1})

    tfr, cltf, cmap2 = v["tfrbtu_f_t"], v["cltfbtu"], v["cltmap2"]
    for isc in range(1, SC4 + 1):
        for ifuel in range(1, 8):
            for iregn in range(1, MNUMCR - 1):
                t = fsum(btu[isc, ifuel, 1:2, iregn])
                if isc != 4:
                    tfr[iyr, isc, ifuel, iregn] = t
                else:
                    cltf[iyr, int(cmap2[ifuel]), iregn] = t
            if isc != 4:
                tfr[iyr, isc, ifuel, MNUMCR] = fsum(tfr[iyr, isc, ifuel, R9])
            else:
                cltf[iyr, int(cmap2[ifuel]), MNUMCR] = fsum(cltf[iyr, int(cmap2[ifuel]), R9])

    cbt = v["cltbtut"]
    gal = ZERO
    for ifuel in range(1, FUEL12 + 1):
        k = int(cmap[ifuel])
        cbt[k, R9, iyr] = fsum(dmd[4, ifuel, 1:2, R9], axis=0) * hrate[4, ifuel] * E12
        cbt[k, MNUMCR, iyr] = fsum(cbt[k, R9, iyr])
        gal = gal + cbt[k, MNUMCR, iyr] / hrate[4, 2] * f32(1E12)
    v["cltgal"] = gal
    v["cltmpgt"][iyr] = (fsum(v["cltvmtt"][:, iyr]) * f32(10.0) ** 9) / gal

    split = v["tfrbtu_chgsplit"]
    if yrs > 2020:
        split[:, iyr] = 0.0
        ann, mpg, df, p219 = v["annvmt_19"], v["new_mpg_19"], v["hdv_df"], v["p219map"]
        iflt = v.i("iflt")
        for c19 in range(3, CAFE19 + 1):
            c14 = int(p219[c19])
            v["icafe14"] = c14
            if mpg[iyr, 6, c19] == 0.0:
                continue
            k = 1 if (iflt == 1 or c19 >= 16) else 2
            for iregn in range(1, MNUMCR - 1):
                for iage in range(1, AGE + 1):
                    split[k, iyr] = split[k, iyr] + ann[iyr, c19, iage, 6] * fsum(stk[iyr, c19, iage, 6, 1:2, iregn]) / (mpg[iyr, 6, c19] * (ONE - df[6, c14]))
        v.s.update({v.key("icafe19"): CAFE19 + 1, v.key("iregn"): MNUMCR - 1, v.key("iage"): AGE + 1})
        t = fsum(split[:, iyr])
        if t > 0.0:
            split[:, iyr] = split[:, iyr] / t
    else:
        split[:, iyr] = 0.5
    for iregn in range(1, MNUMCR + 1):
        v["qgftrpv"][iregn, iyr] = fsum(btu[1:2, 4, NFT, iregn])
        v["qgftrfv"][iregn, iyr] = fsum(btu[1:2, 4, FLT, iregn])
        v["qgltrpv"][iregn, iyr] = btu[3, 4, NFT, iregn]
        v["qgltrfv"][iregn, iyr] = btu[3, 4, FLT, iregn]
    v["iregn"] = MNUMCR + 1
