"""TRUCK_AGGVARS (tranfrt.f): new-truck sales and fuel economy by size class and
regulatory group, and the commercial light truck MPG by vintage.

EIA quirk kept: the oldest commercial light truck vintage weights every fuel with
fuel 2's VMT and divides age 33's VMT by age 34's MPG and the other way round.
"""

import numpy as np

from nems_open.transportation.common import f32, fsum
from nems_open.transportation.frt_common import CAFE14, CAFE19, FUEL12, ONE, SC4, V


def truck_aggvars(s: dict) -> None:
    v = V(s)
    iyr = v.i("iyr")
    stk19, stk = v["trkstk_19"], v["trkstk_19r"]
    stk19[iyr, 1:CAFE19, 1, 1:FUEL12] = fsum(stk[iyr, 1:CAFE19, 1, 1:FUEL12, 1:2, 11], axis=2)
    sal_sc, sal_p2, hdv, mpg_p2 = v["trksal_sc"], v["trksal_p2"], v["hdv_mpg"], v["new_mpg_p2"]
    sal_sc[iyr, :, :] = 0.0
    sal_p2[iyr, :, :] = 0.0
    hdv[iyr, :, 1, :] = 0.0
    mpg_p2[iyr, :, :] = 0.0
    mpg19, df = v["new_mpg_19"], v["hdv_df"]
    sc19, p219 = v["sc19map"], v["p219map"]
    for ifuel in range(1, FUEL12 + 1):
        for c19 in range(1, CAFE19 + 1):
            isc4, c14 = int(sc19[c19]), int(p219[c19])
            x = stk19[iyr, c19, 1, ifuel]
            sal_sc[iyr, isc4, ifuel] = sal_sc[iyr, isc4, ifuel] + x
            sal_p2[iyr, c14, ifuel] = sal_p2[iyr, c14, ifuel] + x
            m = mpg19[iyr, ifuel, c19]
            if m > 0.0 and x > 0.0:
                hdv[iyr, isc4, 1, ifuel] = hdv[iyr, isc4, 1, ifuel] + x / (m * (ONE - df[ifuel, c14]))
                mpg_p2[iyr, ifuel, c14] = mpg_p2[iyr, ifuel, c14] + x / m
        v["icafe19"] = CAFE19 + 1
        v["isc4"], v["icafe14"] = int(sc19[CAFE19]), int(p219[CAFE19])
        for isc in range(1, SC4 + 1):
            if hdv[iyr, isc, 1, ifuel] > 0.0:
                hdv[iyr, isc, 1, ifuel] = sal_sc[iyr, isc, ifuel] / hdv[iyr, isc, 1, ifuel]
            if hdv[iyr, isc, 1, ifuel] == 0.0 and hdv[iyr - 1, isc, 1, ifuel] > 0.0:
                hdv[iyr, isc, 1, ifuel] = hdv[iyr - 1, isc, 1, ifuel]
        v["isc"] = SC4 + 1
        for c14 in range(1, CAFE14 + 1):
            if mpg_p2[iyr, ifuel, c14] > 0.0:
                mpg_p2[iyr, ifuel, c14] = sal_p2[iyr, c14, ifuel] / mpg_p2[iyr, ifuel, c14]
        v["icafe14"] = CAFE14 + 1
    v["ifuel"] = FUEL12 + 1
    for a in (hdv[iyr, :, 1, :], mpg_p2[iyr, :, :], sal_sc[iyr, :, :], sal_p2[iyr, :, :]):
        if np.isnan(fsum(a)):
            raise ValueError("TDM TRUCK_AGGVARS: NaN in truck MPG or sales")

    clt, vmt19, cmap = v["cltmpg_yr"], v["vmtflt_19"], v["cltmap"]
    m1 = ONE
    for ifuel in range(1, FUEL12 + 1):
        k = int(cmap[ifuel])
        tot = fsum(vmt19[iyr - 1, 1:2, 1, ifuel])
        d = ONE - df[ifuel, 1]
        if tot > 0.0:
            x = ((vmt19[iyr - 1, 1, 1, ifuel] / tot) / (mpg19[iyr, ifuel, 1] * d)
                 + (vmt19[iyr - 1, 2, 1, ifuel] / tot) / (mpg19[iyr, ifuel, 2] * d))
        else:
            x = ((fsum(stk[iyr, 1, 1, ifuel, :, 11]) / (mpg19[iyr, ifuel, 1] * d)
                  + fsum(stk[iyr, 2, 1, ifuel, :, 11]) / (mpg19[iyr, ifuel, 2] * d))
                 / fsum(stk[iyr, 1:2, 1, ifuel, :, 11]))
        clt[iyr, k, 1] = np.power(x, f32(-1.0))
    clt[iyr, 1:FUEL12, 2:34] = clt[iyr - 1, 1:FUEL12, 1:33]
    v33, v34 = fsum(vmt19[iyr - 1, 1:2, 33, 2]), fsum(vmt19[iyr - 1, 1:2, 34, 2])
    both = fsum(vmt19[iyr - 1, 1:2, 33:34, 2])
    for ifuel in range(1, FUEL12 + 1):
        k = int(cmap[ifuel])
        if both > 0.0 and clt[iyr - 1, k, 34] > 0.0 and clt[iyr - 1, k, 33] > 0.0:
            clt[iyr, k, 34] = m1 / (((v33 / clt[iyr - 1, k, 34]) + (v34 / clt[iyr - 1, k, 33])) / both)
        else:
            clt[iyr, k, 34] = clt[iyr - 1, k, 33]
    v["ifuel"] = FUEL12 + 1
