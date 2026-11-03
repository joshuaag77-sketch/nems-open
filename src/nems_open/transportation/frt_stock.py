"""TRUCK_STOCK (tranfrt.f): heavy truck stock rollover.

Vintages survive by region, class and fuel; old fleet trucks move to non-fleet
owners; national totals by old size class; stock MPG by vintage; commercial light
truck stocks and sales by powertrain.

EIA quirk kept: the oldest vintage's survivors from age 33 use SURV_RATE at age 34,
because the loop index is left at AGE (34) when that line runs.
"""

import numpy as np

from nems_open.transportation.common import MNUMCR, f32, fsum
from nems_open.transportation.frt_common import AGE, CAFE19, FUEL12, SC, V
from nems_open.transportation.mean_funcs import harmonic_mean

R9 = slice(1, MNUMCR - 2)
CUR, LAG = 2, 1


def truck_stock(s: dict) -> None:
    v = V(s)
    iyr, n, yrs = v.i("iyr"), v.i("n"), v.i("yrs")
    bsyr = v.i("bsyr_stk")
    stk, surv, smap, sc19, tff = v["trkstk_19r"], v["surv_rate"], v["survmap"], v["sc19map"], v["tffxgrt"]
    if yrs > bsyr:
        # Every region, class, fuel and age at once (each element is its own product).
        S, y0, p0 = stk.a, iyr - 1, iyr - 2
        NR = MNUMCR - 2
        w = np.transpose(surv.a[:, :NR, smap.a.astype(int) - 1, :], (2, 0, 3, 1))[:, :, :, None, :]   # [c19, age, fuel, 1, regn]
        S[y0, :, 1:AGE - 1, :, :, :NR] = S[p0, :, 0:AGE - 2, :, :, :NR] * w[:, 1:AGE - 1]
        S[y0, :, AGE - 1, :, :, :NR] = S[p0, :, AGE - 1, :, :, :NR] * f32(0.7) + S[p0, :, AGE - 2, :, :, :NR] * w[:, AGE - 1]
        tt = tff.a[1:AGE, sc19.a.astype(int) - 1].T[:, :, None, None]                                  # [c19, age, 1, 1]
        a2 = S[y0, :, 1:AGE, 0:2, 1, :NR].copy()
        S[y0, :, 1:AGE, 0:2, 0, :NR] = S[y0, :, 1:AGE, 0:2, 0, :NR] + (tt * a2)
        S[y0, :, 1:AGE, 0:2, 1, :NR] = a2 - (tt * a2)
        v.s.update({v.key("iregn"): MNUMCR - 1, v.key("icafe19"): CAFE19 + 1, v.key("ifuel"): 3, v.key("iage"): AGE + 1})
    stk[iyr, 1:CAFE19, 1:AGE, 1:FUEL12, 1:2, 11] = fsum(stk[iyr, 1:CAFE19, 1:AGE, 1:FUEL12, 1:2, R9], axis=4)

    if yrs > bsyr:
        old = v["trkstk"]
        old[iyr, 1, 1:AGE, 1:FUEL12, 1:2] = fsum(stk[iyr, 3:4, 1:AGE, 1:FUEL12, 1:2, MNUMCR], axis=0)
        old[iyr, 2, 1:AGE, 1:FUEL12, 1:2] = fsum(stk[iyr, 5:7, 1:AGE, 1:FUEL12, 1:2, MNUMCR], axis=0)
        old[iyr, 3, 1:AGE, 1:FUEL12, 1:2] = fsum(stk[iyr, 8:19, 1:AGE, 1:FUEL12, 1:2, MNUMCR], axis=0)
        v["trkstk_19"][iyr, 1:CAFE19, 1:AGE, 1:FUEL12] = fsum(stk[iyr, 1:CAFE19, 1:AGE, 1:FUEL12, 1:2, MNUMCR], axis=3)
        hdv, vmtflt = v["hdv_mpg"], v["vmtflt"]
        for isc in range(1, SC + 1):
            for iage in range(2, AGE):
                hdv[iyr, isc, iage, 1:FUEL12] = hdv[iyr - 1, isc, iage - 1, 1:FUEL12]
            for ifuel in range(1, FUEL12 + 1):
                t1 = fsum(vmtflt[LAG, isc, AGE - 1, ifuel, 1:2])
                t2 = fsum(vmtflt[LAG, isc, AGE, ifuel, 1:2])
                if t1 + t2 <= 0.0:
                    hdv[iyr, isc, AGE, ifuel] = hdv[iyr - 1, isc, AGE - 1, ifuel]
                else:
                    hdv[iyr, isc, AGE, ifuel] = harmonic_mean(hdv[iyr - 1, isc, AGE - 1:AGE, ifuel], np.array([t1, t2], dtype=f32))
        v.s.update({v.key("isc"): SC + 1, v.key("iage"): AGE, v.key("ifuel"): FUEL12 + 1})

    if yrs >= 2012:
        clt, cmap = v["cltstk"], v["cltmap"]
        for iage in range(1, AGE + 1):
            for ivoc in (1, 2):
                for ifuel in range(1, FUEL12 + 1):
                    clt[iyr, int(cmap[ifuel]), iage, ivoc, R9] = fsum(stk[iyr, ivoc, iage, ifuel, 1:2, R9], axis=0)
            clt[n, 1:FUEL12, iage, 1:2, MNUMCR] = fsum(clt[n, 1:FUEL12, iage, 1:2, R9], axis=2)
        for ifuel in range(1, FUEL12 + 1):
            v["cltsalt"][ifuel, n] = fsum(clt[n, ifuel, 1, :, MNUMCR])
            v["cltstkt"][ifuel, n] = fsum(clt[n, ifuel, 1:34, :, MNUMCR]) / f32(1000.0)
        v.s.update({v.key("iage"): AGE + 1, v.key("ivoc"): 3, v.key("ifuel"): FUEL12 + 1})
