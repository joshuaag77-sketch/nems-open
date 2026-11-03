"""Household light-duty stock (tran.f): TSMOD.

Household sales by group, class and fuel (history from owner sales, projection
from total sales and the household share), the stock rollover with survival
curves, retired fleet vehicles moving in, and the stock totals by fuel.
"""

import numpy as np

from nems_open.transportation.common import (AGEGRP, MAXAGE, MAXHAV, MAXLDV, MAXOWNER, MAXVTYP, MF, MNUMCR,
                                             STOCKYR, f32, fsum)

MAXFLEET = 4
MAXCLASS = 8
MAXGROUP = 11
CARGRP = 5
LTKGRP = 6
R9 = slice(1, MNUMCR - 2)
TRANSFER_LDV = [*range(1, 9), *range(13, MAXLDV + 1)]  # natural gas and propane (9-12) stay in fleets


def tsmod(s: dict) -> None:
    n, yrs = int(s["n"]), int(s["curcalyr"])

    if int(s["mmac"]) == 4 and yrs > STOCKYR + 1 and int(s["curitr"]) == 1:
        # Low macro case: stretch survival as sales fall. (The CURCALYR == STOCKYR
        # branch EIA nests inside can never run.)
        if yrs <= STOCKYR + 2:
            s["ssurv25"][1:MNUMCR, 1:23, 1:MAXVTYP] = s["ssurv25"][1:MNUMCR, 1:23, 1:MAXVTYP] * f32(1.002)

    grp, tech = s["hhgrpsal"], s["hhtechsal"]
    if 2019 <= yrs <= STOCKYR:
        own = s["own_sales"]
        for iregn in range(1, MNUMCR - 1):
            grp[iregn, 1:MAXGROUP, 1:MAXCLASS, 1:MAXLDV, n] = own[1, 1:MAXGROUP, 1:MAXCLASS, 1:MAXLDV, iregn, yrs] / f32(1000000.0)
        s["iregn"] = MNUMCR - 1
        tech[R9, 1, 1:MAXCLASS, 1:MAXLDV, n] = fsum(grp[R9, 1:CARGRP, 1:MAXCLASS, 1:MAXLDV, n], axis=1)
        tech[R9, 2, 1:MAXCLASS, 1:MAXLDV, n] = fsum(grp[R9, LTKGRP:MAXGROUP, 1:MAXCLASS, 1:MAXLDV, n], axis=1)
        tech[MNUMCR, 1:MAXVTYP, 1:MAXCLASS, 1:MAXLDV, n] = fsum(tech[R9, 1:MAXVTYP, 1:MAXCLASS, 1:MAXLDV, n], axis=0)
        grp[MNUMCR, 1:MAXGROUP, 1:MAXCLASS, 1:MAXLDV, n] = fsum(grp[R9, 1:MAXGROUP, 1:MAXCLASS, 1:MAXLDV, n], axis=0)
    elif yrs > STOCKYR:
        sales, own = s["ldv_sales"], s["ownsaletemp"]
        for igp in range(1, MAXGROUP + 1):
            for icl in range(1, MAXCLASS + 1):
                grp[R9, igp, icl, 1:MAXLDV, n] = sales[igp, icl, 1:MAXLDV, R9, n].T * own[1, igp, icl, R9, n][:, None]
                grp[MNUMCR, igp, icl, 1:MAXLDV, n] = fsum(grp[R9, igp, icl, 1:MAXLDV, n], axis=0)
        s.update(igp=MAXGROUP + 1, icl=MAXCLASS + 1, ildv=MAXLDV + 1)
        tech[1:MNUMCR, 1, 1:MAXCLASS, 1:MAXLDV, n] = fsum(grp[1:MNUMCR, 1:CARGRP, 1:MAXCLASS, 1:MAXLDV, n], axis=1)
        tech[1:MNUMCR, 2, 1:MAXCLASS, 1:MAXLDV, n] = fsum(grp[1:MNUMCR, LTKGRP:MAXGROUP, 1:MAXCLASS, 1:MAXLDV, n], axis=1)

    oldt = s["oldfstkt"]
    oldt.a[...] = 0.0
    stock = s["ldv_stock"]
    if yrs > STOCKYR:
        old = s["oldfstk"]
        for ildv in TRANSFER_LDV:
            oldt[R9, 1:MAXVTYP, ildv, 1:MAXAGE] = fsum(old[R9, 1:MAXVTYP, 1:MAXFLEET, ildv, 1:MAXAGE], axis=2) / f32(1000000.0)
        surv = s["ssurv25"]
        for ivtyp in range(1, MAXVTYP + 1):
            for ildv in range(1, MAXLDV + 1):
                stock[R9, ivtyp, 1, ildv, 1, 1, n] = fsum(tech[R9, ivtyp, 1:MAXCLASS, ildv, n], axis=1)
                stock[R9, ivtyp, 1, ildv, 2:MAXAGE - 1, 1, n] = (stock[R9, ivtyp, 1, ildv, 1:MAXAGE - 2, 1, n - 1]
                                                                 * surv[R9, 1:MAXAGE - 2, ivtyp])
                stock[R9, ivtyp, 1, ildv, MAXAGE, 1, n] = (stock[R9, ivtyp, 1, ildv, MAXAGE - 1, 1, n - 1] * surv[R9, MAXAGE - 1, ivtyp]
                                                           + stock[R9, ivtyp, 1, ildv, MAXAGE, 1, n - 1] * surv[R9, MAXAGE, ivtyp])
                stock[R9, ivtyp, 1, ildv, 1:MAXAGE, 1, n] = stock[R9, ivtyp, 1, ildv, 1:MAXAGE, 1, n] + oldt[R9, ivtyp, ildv, 1:MAXAGE]
        s.update(ivtyp=MAXVTYP + 1, ildv=MAXLDV + 1)
        stock[MNUMCR, 1:MAXVTYP, 1:MAXOWNER, 1:MAXLDV, 1:MAXAGE, 1, n] = fsum(stock[R9, 1:MAXVTYP, 1:MAXOWNER, 1:MAXLDV, 1:MAXAGE, 1, n], axis=0)

    nat = stock[MNUMCR, 1:MAXVTYP, 1:MAXOWNER, 1:MAXLDV, 1:MAXAGE, 1:MAXHAV, n]   # (2, 5, 16, 25, 4)
    vstk = fsum(fsum(fsum(nat, axis=4), axis=3), axis=1)                           # (2, 16)
    s["vstk"][1:MAXVTYP, 1:MAXLDV] = vstk
    s["vpld"][n] = fsum(vstk) / fsum(s["licdriver"][1:AGEGRP, 1:MF, R9, n])
    s["ldvstk"][1:MAXLDV, n] = fsum(vstk, axis=0)
