"""Household stock fuel economy (tran.f): TMPGSTK.

New household MPG by region (national FEM values, then regional sales-weighted
harmonic means), the vintage array of stock MPG, household VMT by vintage, and
VMT-weighted stock MPG by vehicle type, fuel and region.

Accumulations keep the Fortran's loop order, since float32 sums depend on it.
"""

import numpy as np

from nems_open.transportation.common import MAXAGE, MAXLDV, MAXVTYP, MNUMCR, f32, fsum

MAXCLASS = 8
MAXGROUP = 11
CARGRP = 5
LTKGRP = 6
GAS = 1
R9 = slice(1, MNUMCR - 2)
REGIONS = [r for r in range(1, MNUMCR + 1) if r != 10]  # California (10) is filled elsewhere


def tmpgstk(s: dict) -> None:
    n, yrs = int(s["n"]), int(s["curcalyr"])
    first = int(s["first_read_year"])
    mstk, mnew, ldvnew = s["hhmpgstk"], s["hhmpgnew"], s["ldvmpgnew"]
    deg, afv = s["degfac"], s["afvadjfe"]

    if yrs == first:
        gas95 = s["cmpgstkgas95"]
        for iregn in REGIONS:
            for ivtyp in range(1, MAXVTYP + 1):
                for ildv in range(1, MAXLDV + 1):
                    base = gas95[ivtyp, 2:MAXAGE] * deg[ivtyp, ildv, n]
                    if ildv in (1, 3, 9, 10, 11, 12):
                        mstk[iregn, ivtyp, ildv, 2:MAXAGE, n] = base
                    elif ildv == 2:
                        mstk[iregn, ivtyp, ildv, 2:MAXAGE, n] = base * afv[ildv, ivtyp]
                    elif ildv in (4, 7, 15):
                        mstk[iregn, ivtyp, ildv, 2:MAXAGE, n] = base * f32(4.0)
        s.update(iregn=MNUMCR + 1, ivtyp=MAXVTYP + 1, ildv=MAXLDV + 1)

    if yrs <= 2018:
        mnew[1:MNUMCR, 1:MAXVTYP, 1:MAXLDV, n] = np.broadcast_to(ldvnew[MNUMCR, 1:MAXVTYP, 1:MAXLDV, n],
                                                                (MNUMCR, MAXVTYP, MAXLDV))
        for iregn in REGIONS:
            for ivtyp in range(1, MAXVTYP + 1):
                for ildv in range(1, MAXLDV + 1):
                    if mnew[iregn, ivtyp, ildv, n] == 0.0:
                        # No new vehicle of this kind in the FEM data (conversions, small makers).
                        gas = ldvnew[MNUMCR, ivtyp, GAS, n]
                        if ildv == 2:
                            mnew[iregn, ivtyp, ildv, n] = gas * afv[ildv, ivtyp]
                        elif ildv in (3, 9, 10, 11, 12):
                            mnew[iregn, ivtyp, ildv, n] = gas
                        elif ildv in (4, 7, 15):
                            mnew[iregn, ivtyp, ildv, n] = f32(105.0) if ivtyp == 1 else f32(85.0)
        s.update(iregn=MNUMCR + 1, ivtyp=MAXVTYP + 1, ildv=MAXLDV + 1)

    if yrs >= 2019:
        mnew[1:MNUMCR, 1:MAXVTYP, 1:MAXLDV, n] = np.broadcast_to(ldvnew[MNUMCR, 1:MAXVTYP, 1:MAXLDV, n],
                                                                (MNUMCR, MAXVTYP, MAXLDV))
        reg = ldvnew[R9, 1:MAXVTYP, 1:MAXLDV, n]
        mnew[R9, 1:MAXVTYP, 1:MAXLDV, n] = np.where(reg != 0.0, reg, mnew[R9, 1:MAXVTYP, 1:MAXLDV, n])

        grp, femmpg = s["hhgrpsal"], s["femmpg"]
        for iregn in REGIONS:
            for ildv in range(1, MAXLDV + 1):
                den1 = den2 = f32(0.0)
                for icl in range(1, MAXCLASS + 1):
                    for igp in range(1, MAXGROUP + 1):
                        sal, mpg = grp[iregn, igp, icl, ildv, n], femmpg[igp, icl, yrs, ildv]
                        if sal != 0.0 and mpg != 0.0:
                            if igp <= CARGRP:
                                den1 = den1 + sal / mpg
                            else:
                                den2 = den2 + sal / mpg
                if den1 != 0.0:
                    mnew[iregn, 1, ildv, n] = fsum(grp[iregn, 1:CARGRP, 1:MAXCLASS, ildv, n]) / den1
                if den2 != 0.0:
                    mnew[iregn, 2, ildv, n] = fsum(grp[iregn, LTKGRP:MAXGROUP, 1:MAXCLASS, ildv, n]) / den2

        tech = s["hhtechsal"]
        for ivtyp in range(1, MAXVTYP + 1):
            for ildv in range(1, MAXLDV + 1):
                den1 = f32(0.0)
                for iregn in range(1, MNUMCR - 1):
                    sal = fsum(tech[iregn, ivtyp, 1:MAXCLASS, ildv, n])
                    if sal != 0.0 and mnew[iregn, ivtyp, ildv, n] != 0.0:
                        # EIA quirk: "=" not "+=", so the US value uses the last region with sales.
                        den1 = sal / mnew[iregn, ivtyp, ildv, n]
                if den1 != 0.0:
                    mnew[MNUMCR, ivtyp, ildv, n] = fsum(tech[R9, ivtyp, 1:MAXCLASS, ildv, n]) / den1
        s.update(iregn=MNUMCR - 1, ivtyp=MAXVTYP + 1, ildv=MAXLDV + 1, icl=MAXCLASS + 1, igp=MAXGROUP + 1)

    mstk[1:MNUMCR, 1:MAXVTYP, 1:MAXLDV, 1, n] = mnew[1:MNUMCR, 1:MAXVTYP, 1:MAXLDV, n] * deg[1:MAXVTYP, 1:MAXLDV, n][None]

    stock = s["ldv_stock"]
    if yrs > first:
        mstk[1:MNUMCR, 1:MAXVTYP, 1:MAXLDV, 2:MAXAGE, n] = mstk[1:MNUMCR, 1:MAXVTYP, 1:MAXLDV, 1:MAXAGE - 1, n - 1]
        for iregn in range(1, MNUMCR + 1):
            for ivtyp in range(1, MAXVTYP + 1):
                for ildv in range(1, MAXLDV + 1):
                    num1 = den1 = f32(0.0)
                    s1, m1 = stock[iregn, ivtyp, 1, ildv, MAXAGE - 1, 1, n - 1], mstk[iregn, ivtyp, ildv, MAXAGE - 1, n - 1]
                    s2, m2 = stock[iregn, ivtyp, 1, ildv, MAXAGE, 1, n - 1], mstk[iregn, ivtyp, ildv, MAXAGE, n - 1]
                    # EIA quirk: ELSEIF, so the oldest vintage only counts when the one before it is empty.
                    if s1 != 0.0 and m1 != 0.0:
                        num1, den1 = s1, s1 / m1
                    elif s2 != 0.0 and m2 != 0.0:
                        num1, den1 = num1 + s2, den1 + s2 / m2
                    if den1 != 0.0:
                        mstk[iregn, ivtyp, ildv, MAXAGE, n] = num1 / den1
        s.update(iregn=MNUMCR + 1, ivtyp=MAXVTYP + 1, ildv=MAXLDV + 1)

    if yrs <= int(s["epalyr"]) + 2:
        # The warning loop only writes to the debug file; it leaves its indexes here.
        s.update(iregn=MNUMCR + 1, ivtyp=MAXVTYP + 1, ildv=MAXLDV + 1, iage=MAXAGE + 1)

    vmt = s["vmt_stk_hh"]
    vmt.a[...] = 0.0
    pvmt, lvmt = s["pvmt"], s["lvmt"]
    for ildv in range(1, MAXLDV + 1):
        for iregn in range(1, MNUMCR - 1):
            vmt[1, ildv, 1:MAXAGE, 1, iregn] = stock[iregn, 1, 1, ildv, 1:MAXAGE, 1, n] * pvmt[1:MAXAGE, n, iregn, ildv]
            vmt[2, ildv, 1:MAXAGE, 1, iregn] = stock[iregn, 2, 1, ildv, 1:MAXAGE, 1, n] * lvmt[1:MAXAGE, n, iregn, ildv]
        for ivtyp in range(1, MAXVTYP + 1):
            vmt[ivtyp, ildv, 1:MAXAGE, 1, MNUMCR] = fsum(vmt[ivtyp, ildv, 1:MAXAGE, 1, R9], axis=1)

    typreg = s["hhmpgstk_typreg"]
    typreg[1:MNUMCR, 1:2, n] = 0.0
    for iregn in range(1, MNUMCR - 1):
        acc = [typreg[iregn, 1, n], typreg[iregn, 2, n]]
        for ildv in range(1, MAXLDV + 1):
            for iage in range(1, MAXAGE + 1):
                for k in (0, 1):
                    m = mstk[iregn, k + 1, ildv, iage, n]
                    if m != 0.0:
                        acc[k] = acc[k] + (vmt[k + 1, ildv, iage, 1, iregn] / m)
        typreg[iregn, 1, n], typreg[iregn, 2, n] = acc
    typreg[MNUMCR, 1, n] = fsum(typreg[R9, 1, n])
    typreg[MNUMCR, 2, n] = fsum(typreg[R9, 2, n])

    s["hhmpgstk_typ"][1, n] = fsum(vmt[1, 1:MAXLDV, 1:MAXAGE, 1, R9]) / typreg[MNUMCR, 1, n]
    s["hhmpgstk_typ"][2, n] = fsum(vmt[2, 1:MAXLDV, 1:MAXAGE, 1, R9]) / typreg[MNUMCR, 2, n]
    s["mpghh"][n] = fsum(vmt[1:MAXVTYP, 1:MAXLDV, 1:MAXAGE, 1, R9]) / (typreg[MNUMCR, 1, n] + typreg[MNUMCR, 2, n])

    typldv, ldvavg = s["hhmpgstk_typldv"], s["hhmpgstk_ldv"]
    for ildv in range(1, MAXLDV + 1):
        typldv[ildv, :, n] = 0.0
        ldvavg[ildv, n] = 0.0
        num1 = den1 = num2 = den2 = f32(0.0)
        for ivtyp in range(1, MAXVTYP + 1):
            for iage in range(1, MAXAGE + 1):
                for iregn in range(1, MNUMCR - 1):
                    m = mstk[iregn, ivtyp, ildv, iage, n]
                    if m != 0.0:
                        v = vmt[ivtyp, ildv, iage, 1, iregn]
                        if ivtyp == 1:
                            num1, den1 = num1 + v, den1 + (v / m)
                        else:
                            num2, den2 = num2 + v, den2 + (v / m)
            if ivtyp == 1:
                if den1 != 0.0:
                    typldv[ildv, 1, n] = num1 / den1
            elif den2 != 0.0:
                typldv[ildv, 2, n] = num2 / den2
        if (den1 + den2) != 0.0:
            ldvavg[ildv, n] = (num1 + num2) / (den1 + den2)
        # Missing CNG/LPG get 95% of gasoline; the rest 1.0, to avoid NaNs in TREPORT.
        if ldvavg[ildv, n] == 0.0:
            ldvavg[ildv, n] = ldvavg[1, n] * f32(0.95) if 9 <= ildv <= 12 else f32(1.0)
    s.update(iregn=MNUMCR - 1, ivtyp=MAXVTYP + 1, ildv=MAXLDV + 1, iage=MAXAGE + 1)
