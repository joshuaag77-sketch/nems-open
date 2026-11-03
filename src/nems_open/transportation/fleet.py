"""Fleet vehicles (tran.f): TFLTSTKS.

Fleet sales by size class, fuel and region (history from owner sales, projection
from total LDV sales and fleet shares), fleet stock rollover with survival, the
transfer of old fleet vehicles to households, and the fleet totals TMPGAG and
the reports read.
"""

import numpy as np

from nems_open.transportation.common import MAXAGE, MAXHAV, MAXLDV, MAXVTYP, MNUMCR, STOCKYR, f32, fsum

MAXFLEET = 4
MAXCLASS = 8
MAXGROUP = 11
CARGRP = 5
LTKGRP = 6
R9 = slice(1, MNUMCR - 2)


def tfltstks(s: dict) -> None:
    n, yrs = int(s["n"]), int(s["curcalyr"])
    grp, tech = s["fltgrpsal"], s["fltechsal"]

    if 2019 <= yrs <= STOCKYR:
        own = s["own_sales"]
        for ifleet in range(1, MAXFLEET + 1):
            for icl in range(1, MAXCLASS + 1):
                for ildv in range(1, MAXLDV + 1):
                    for igp in range(1, MAXGROUP + 1):
                        grp[R9, ifleet, igp, icl, ildv] = own[ifleet + 1, igp, icl, ildv, R9, yrs]
                    tech[R9, 1, ifleet, icl, ildv, 1] = fsum(grp[R9, ifleet, 1:CARGRP, icl, ildv], axis=1)
                    tech[R9, 2, ifleet, icl, ildv, 1] = fsum(grp[R9, ifleet, LTKGRP:MAXGROUP, icl, ildv], axis=1)
        s.update(ifleet=MAXFLEET + 1, icl=MAXCLASS + 1, ildv=MAXLDV + 1, igp=MAXGROUP + 1)

    if yrs > STOCKYR:
        sales, own = s["ldv_sales"], s["ownsaletemp"]
        for ifleet in range(1, MAXFLEET + 1):
            for igp in range(1, MAXGROUP + 1):
                for icl in range(1, MAXCLASS + 1):
                    grp[R9, ifleet, igp, icl, 1:MAXLDV] = (sales[igp, icl, 1:MAXLDV, R9, n].T
                                                          * own[ifleet + 1, igp, icl, R9, n][:, None] * f32(1000000.0))
        s.update(ifleet=MAXFLEET + 1, igp=MAXGROUP + 1, icl=MAXCLASS + 1, ildv=MAXLDV + 1)
        tech[R9, 1, 1:MAXFLEET, 1:MAXCLASS, 1:MAXLDV, 1] = fsum(grp[R9, 1:MAXFLEET, 1:CARGRP, 1:MAXCLASS, 1:MAXLDV], axis=2)
        tech[R9, 2, 1:MAXFLEET, 1:MAXCLASS, 1:MAXLDV, 1] = fsum(grp[R9, 1:MAXFLEET, LTKGRP:MAXGROUP, 1:MAXCLASS, 1:MAXLDV], axis=2)

    tech[MNUMCR, 1:MAXVTYP, 1:MAXFLEET, 1:MAXCLASS, 1:MAXLDV, 1] = fsum(tech[R9, 1:MAXVTYP, 1:MAXFLEET, 1:MAXCLASS, 1:MAXLDV, 1], axis=0)
    grp[MNUMCR, 1:MAXFLEET, 1:MAXGROUP, 1:MAXCLASS, 1:MAXLDV] = fsum(grp[R9, 1:MAXFLEET, 1:MAXGROUP, 1:MAXCLASS, 1:MAXLDV], axis=0)

    fs = s["flt_stock"]
    if yrs > STOCKYR:
        surv = s["survflt"]
        # Vectorized over regions; the Fortran loops region innermost, so order doesn't matter.
        for ivtyp in range(1, MAXVTYP + 1):
            for ifleet in range(1, MAXFLEET + 1):
                for ildv in range(1, MAXLDV + 1):
                    for ihav in range(1, MAXHAV + 1):
                        fs[R9, ivtyp, ifleet, ildv, 1, ihav, n] = fsum(tech[R9, ivtyp, ifleet, 1:MAXCLASS, ildv, ihav], axis=1)
                        for iage in range(2, MAXAGE):
                            fs[R9, ivtyp, ifleet, ildv, iage, ihav, n] = (fs[R9, ivtyp, ifleet, ildv, iage - 1, ihav, n - 1]
                                                                          * surv[ifleet, iage - 1, ivtyp])
                        fs[R9, ivtyp, ifleet, ildv, MAXAGE, ihav, n] = (
                            fs[R9, ivtyp, ifleet, ildv, MAXAGE - 1, ihav, n - 1] * surv[ifleet, MAXAGE - 1, ivtyp]
                            + fs[R9, ivtyp, ifleet, ildv, MAXAGE, ihav, n - 1] * surv[ifleet, MAXAGE, ivtyp])
                        # EIA quirk: IAGE is left at MAXAGE by the loop above, so only the
                        # oldest vintage gets a national total here (overwritten below anyway).
                        fs[MNUMCR, ivtyp, ifleet, ildv, MAXAGE, ihav, n] = fsum(fs[R9, ivtyp, ifleet, ildv, MAXAGE, ihav, n])

        # Old fleet vehicles move to households; natural gas and propane (9-12) stay in fleets.
        old = s["oldfstk"]
        old.a[...] = 0.0
        trans = s["flttrans"]
        for ifleet in range(1, MAXFLEET + 1):
            for ildv in range(1, MAXLDV + 1):
                if ildv < 9 or ildv > 12:
                    for ivtyp in range(1, MAXVTYP + 1):
                        old[R9, ivtyp, ifleet, ildv, 1:MAXAGE] = fs[R9, ivtyp, ifleet, ildv, 1:MAXAGE, 1, n] * trans[ifleet, 1:MAXAGE, ivtyp]
                        fs[R9, ivtyp, ifleet, ildv, 1:MAXAGE, 1, n] = fs[R9, ivtyp, ifleet, ildv, 1:MAXAGE, 1, n] - old[R9, ivtyp, ifleet, ildv, 1:MAXAGE]

        ldv = s["ldv_stock"]
        ldv[R9, 1:MAXVTYP, 2:MAXFLEET + 1, 1:MAXLDV, 1:MAXAGE, 1:MAXHAV, n] = (
            fs[R9, 1:MAXVTYP, 1:MAXFLEET, 1:MAXLDV, 1:MAXAGE, 1:MAXHAV, n] / f32(1000000.0))
        fs[MNUMCR, 1:MAXVTYP, 1:MAXFLEET, 1:MAXLDV, 1:MAXAGE, 1:MAXHAV, n] = fsum(fs[R9, 1:MAXVTYP, 1:MAXFLEET, 1:MAXLDV, 1:MAXAGE, 1:MAXHAV, n], axis=0)
        ldv[MNUMCR, 1:MAXVTYP, 2:MAXFLEET + 1, 1:MAXLDV, 1:MAXAGE, 1:MAXHAV, n] = fsum(ldv[R9, 1:MAXVTYP, 2:MAXFLEET + 1, 1:MAXLDV, 1:MAXAGE, 1:MAXHAV, n], axis=0)
        s.update(ivtyp=MAXVTYP + 1, ifleet=MAXFLEET + 1, ildv=MAXLDV + 1, ihav=MAXHAV + 1, iregn=MNUMCR - 1, iage=MAXAGE)

    s["fltechstk"][1:MNUMCR, 1:MAXVTYP, 1:MAXFLEET, 1:MAXLDV, 1:MAXHAV] = fsum(fs[1:MNUMCR, 1:MAXVTYP, 1:MAXFLEET, 1:MAXLDV, 1:MAXAGE, 1:MAXHAV, n], axis=4)
    for ivtyp in range(1, MAXVTYP + 1):
        s["totfltcar"][ivtyp] = fsum(s["fltechstk"][MNUMCR, ivtyp, 1:MAXFLEET, 1:MAXLDV, 1:MAXHAV]) / f32(1000000.0)
    s["ivtyp"] = MAXVTYP + 1

    leg = s["legaltsal"]
    for iregn in range(1, MNUMCR - 1):
        leg[2, iregn, n] = fsum(tech[iregn, 1:2, 2:3, 1:6, 3:MAXLDV, 1:4]) / f32(1000000.0)
    leg[2, MNUMCR, n] = fsum(leg[2, R9, n])
    s["iregn"] = MNUMCR - 1
