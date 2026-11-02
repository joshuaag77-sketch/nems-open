"""Fleet fuel economy (tran.f): TFLTMPGS.

New fleet MPG by region, fleet type and fuel (national FEM values, then regional
sales-weighted harmonic means), the vintage array of fleet stock MPG, and
stock-weighted fleet MPG by fuel and by car / light truck. Automated vehicles
(automation levels 2-4) carry an MPG penalty once lidar is available.

The accumulations run in the Fortran's loop order, vectorized only across the
dimensions that have their own accumulator.
"""

import numpy as np

from nems_open.transportation.common import MAXAGE, MAXHAV, MAXLDV, MAXVTYP, MNUMCR, f32, fsum

MAXFLEET = 4
MAXCLASS = 8
MAXGROUP = 11
CARGRP = 5
LTKGRP = 6
GAS = 1
R9 = slice(1, MNUMCR - 2)
REGIONS = [r for r in range(1, MNUMCR + 1) if r != 10]


def _roll_maxage(fs, mstk, iregn, ivtyp, ifleet, ildv, n):
    """Oldest vintage MPG: last year's two oldest, with EIA's ELSEIF (see TMPGSTK)."""
    s1, m1 = fs[iregn, ivtyp, ifleet, ildv, MAXAGE - 1, 1, n - 1], mstk[iregn, ivtyp, ifleet, ildv, MAXAGE - 1, n - 1]
    s2, m2 = fs[iregn, ivtyp, ifleet, ildv, MAXAGE, 1, n - 1], mstk[iregn, ivtyp, ifleet, ildv, MAXAGE, n - 1]
    num1 = den1 = f32(0.0)
    if s1 != 0.0 and m1 != 0.0:
        num1, den1 = s1, s1 / m1
    elif s2 != 0.0 and m2 != 0.0:
        num1, den1 = num1 + s2, den1 + s2 / m2
    if den1 != 0.0:
        mstk[iregn, ivtyp, ifleet, ildv, MAXAGE, n] = num1 / den1


def tfltmpgs(s: dict) -> None:
    n, yrs = int(s["n"]), int(s["curcalyr"])
    first = int(s["first_read_year"])
    mstk, mnew, ldvnew = s["fltmpgstk"], s["fltmpgnew"], s["ldvmpgnew"]
    deg, afv = s["degfac"], s["afvadjfe"]
    fs = s["flt_stock"]

    if yrs == first:
        gas95 = s["cmpgstkgas95"]
        for iregn in range(1, MNUMCR + 1):
            for ivtyp in range(1, MAXVTYP + 1):
                for ildv in range(1, MAXLDV + 1):
                    base = gas95[ivtyp, 2:MAXAGE] * deg[ivtyp, ildv, n]
                    if ildv in (1, 3, 9, 10, 11, 12):
                        v = base
                    elif ildv == 2:
                        v = base * afv[ildv, ivtyp]
                    elif ildv in (4, 7, 15):
                        v = base * f32(4.0)
                    else:
                        continue
                    mstk[iregn, ivtyp, 1:MAXFLEET, ildv, 2:MAXAGE, n] = v[None, :]

    if yrs <= 2018:
        for iregn in REGIONS:
            for ivtyp in range(1, MAXVTYP + 1):
                for ifleet in range(1, MAXFLEET + 1):
                    for ildv in range(1, MAXLDV + 1):
                        mnew[iregn, ivtyp, ifleet, ildv, n] = ldvnew[MNUMCR, ivtyp, ildv, n]
                        if mnew[iregn, ivtyp, ifleet, ildv, n] == 0.0:
                            gas = ldvnew[MNUMCR, ivtyp, GAS, n]
                            if ildv == 2:
                                mnew[iregn, ivtyp, ifleet, ildv, n] = gas * afv[ildv, ivtyp]
                            elif ildv in (3, 9, 10, 11, 12):
                                mnew[iregn, ivtyp, ifleet, ildv, n] = gas
                            elif ildv in (4, 7, 15):
                                mnew[iregn, ivtyp, ifleet, ildv, n] = f32(105.0) if ivtyp == 1 else f32(85.0)

    if yrs >= 2019:
        nat = ldvnew[MNUMCR, 1:MAXVTYP, 1:MAXLDV, n]                                   # (2, 16)
        mnew[1:MNUMCR, 1:MAXVTYP, 1:MAXFLEET, 1:MAXLDV, n] = np.broadcast_to(nat[None, :, None, :], (MNUMCR, MAXVTYP, MAXFLEET, MAXLDV))
        reg = np.broadcast_to(ldvnew[R9, 1:MAXVTYP, 1:MAXLDV, n][:, :, None, :], (MNUMCR - 2, MAXVTYP, MAXFLEET, MAXLDV))
        mnew[R9, 1:MAXVTYP, 1:MAXFLEET, 1:MAXLDV, n] = np.where(reg != 0.0, reg, mnew[R9, 1:MAXVTYP, 1:MAXFLEET, 1:MAXLDV, n])

        grp, femmpg = s["fltgrpsal"], s["femmpg"]
        den1 = np.zeros((MNUMCR - 2, MAXFLEET, MAXLDV), dtype=f32)
        den2 = np.zeros_like(den1)
        for icl in range(1, MAXCLASS + 1):
            for igp in range(1, MAXGROUP + 1):
                sal = grp[R9, 1:MAXFLEET, igp, icl, 1:MAXLDV]                          # (9, 4, 16)
                mpg = femmpg[igp, icl, yrs, 1:MAXLDV][None, None, :]
                ok = (sal != 0.0) & (mpg != 0.0)
                with np.errstate(divide="ignore", invalid="ignore"):
                    term = sal / mpg
                if igp <= CARGRP:
                    den1 = np.where(ok, den1 + term, den1)
                else:
                    den2 = np.where(ok, den2 + term, den2)
        car = fsum(fsum(grp[R9, 1:MAXFLEET, 1:CARGRP, 1:MAXCLASS, 1:MAXLDV], axis=3), axis=2)
        trk = fsum(fsum(grp[R9, 1:MAXFLEET, LTKGRP:MAXGROUP, 1:MAXCLASS, 1:MAXLDV], axis=3), axis=2)
        with np.errstate(divide="ignore", invalid="ignore"):
            mnew[R9, 1, 1:MAXFLEET, 1:MAXLDV, n] = np.where(den1 != 0.0, car / den1, mnew[R9, 1, 1:MAXFLEET, 1:MAXLDV, n])
            mnew[R9, 2, 1:MAXFLEET, 1:MAXLDV, n] = np.where(den2 != 0.0, trk / den2, mnew[R9, 2, 1:MAXFLEET, 1:MAXLDV, n])

        tech = s["fltechsal"]
        # sum(fltechsal(iregn,ivtyp,ifleet,1:maxclass,ildv,:)) in Fortran element order: class, then automation level
        sal = fsum(np.moveaxis(tech[R9, 1:MAXVTYP, 1:MAXFLEET, 1:MAXCLASS, 1:MAXLDV, 1:MAXHAV], 3, 4).reshape(
            MNUMCR - 2, MAXVTYP, MAXFLEET, MAXLDV, MAXCLASS * MAXHAV, order="F"), axis=4)  # (9, 2, 4, 16)
        den = np.zeros((MAXVTYP, MAXFLEET, MAXLDV), dtype=f32)
        for iregn in range(1, MNUMCR - 1):
            m = mnew[iregn, 1:MAXVTYP, 1:MAXFLEET, 1:MAXLDV, n]
            ok = (sal[iregn - 1] != 0.0) & (m != 0.0)
            with np.errstate(divide="ignore", invalid="ignore"):
                den = np.where(ok, den + sal[iregn - 1] / m, den)
        tot = fsum(sal, axis=0)
        with np.errstate(divide="ignore", invalid="ignore"):
            mnew[MNUMCR, 1:MAXVTYP, 1:MAXFLEET, 1:MAXLDV, n] = np.where(den != 0.0, tot / den, mnew[MNUMCR, 1:MAXVTYP, 1:MAXFLEET, 1:MAXLDV, n])

    treff = s["treffflt"]
    for ivtyp in range(1, MAXVTYP + 1):
        num = den = f32(0.0)
        for ifleet in range(1, MAXFLEET + 1):
            for ildv in range(1, MAXLDV + 1):
                m = mnew[MNUMCR, ivtyp, ifleet, ildv, n]
                if m != 0.0:
                    st = fsum(fs[MNUMCR, ivtyp, ifleet, ildv, 1, 1:MAXHAV, n])
                    num, den = num + st, den + st / m
        treff[ivtyp, n] = f32(0.0)
        if den != 0.0:
            treff[ivtyp, n] = num / den

    for iregn in REGIONS:
        for ivtyp in range(1, MAXVTYP + 1):
            for ifleet in range(1, MAXFLEET + 1):
                mstk[iregn, ivtyp, ifleet, 1:MAXLDV, 1, n] = mnew[iregn, ivtyp, ifleet, 1:MAXLDV, n] * deg[ivtyp, 1:MAXLDV, n]
                if yrs > first:
                    for ildv in range(1, MAXLDV + 1):
                        mstk[iregn, ivtyp, ifleet, ildv, 2:MAXAGE, n] = mstk[iregn, ivtyp, ifleet, ildv, 1:MAXAGE - 1, n - 1]
                        _roll_maxage(fs, mstk, iregn, ivtyp, ifleet, ildv, n)

    # Stock-weighted MPG; automated vehicles count only once lidar exists, with a penalty.
    mfs = s["mpgfltstk"]
    havdeg, lidar1 = s["hav_mpgdeg"], int(s["first_lidar_year"][1])
    num = np.zeros((MNUMCR, MAXVTYP, MAXFLEET, MAXLDV), dtype=f32)
    den = np.zeros_like(num)
    for iage in range(1, MAXAGE + 1):
        m = mstk[1:MNUMCR, 1:MAXVTYP, 1:MAXFLEET, 1:MAXLDV, iage, n]
        ok = m != 0.0
        for ihav in range(1, MAXHAV + 1):
            if ihav > 1 and yrs < lidar1:
                continue
            st = fs[1:MNUMCR, 1:MAXVTYP, 1:MAXFLEET, 1:MAXLDV, iage, ihav, n]
            mm = m if ihav == 1 else m * havdeg[ihav, yrs]
            with np.errstate(divide="ignore", invalid="ignore"):
                num = np.where(ok, num + st, num)
                den = np.where(ok, den + (st / mm), den)
    num[9], den[9] = 0.0, 0.0  # California (10) is skipped
    with np.errstate(divide="ignore", invalid="ignore"):
        mfs[1:MNUMCR, 1:MAXVTYP, 1:MAXFLEET, 1:MAXLDV, n] = np.where(den != 0.0, num / den, f32(0.0))

    ftech, ldvavg = s["fltechstk"], s["fltmpgstk_ldv"]
    for ildv in range(1, MAXLDV + 1):
        num = den = f32(0.0)
        for ivtyp in range(1, MAXVTYP + 1):
            for ifleet in range(1, MAXFLEET + 1):
                m = mfs[MNUMCR, ivtyp, ifleet, ildv, n]
                for ihav in range(1, MAXHAV + 1):
                    if m != 0.0:
                        st = ftech[MNUMCR, ivtyp, ifleet, ildv, ihav]
                        num, den = num + st, den + (st / m)
        ldvavg[ildv, n] = f32(0.0)
        if den != 0.0:
            ldvavg[ildv, n] = num / den
        if ldvavg[ildv, n] == 0.0:
            ldvavg[ildv, n] = ldvavg[1, n] * f32(0.95) if 9 <= ildv <= 12 else f32(1.0)

    for ivtyp in range(1, MAXVTYP + 1):
        num = den = f32(0.0)
        for ifleet in range(1, MAXFLEET + 1):
            for ildv in range(1, MAXLDV + 1):
                m = mfs[MNUMCR, ivtyp, ifleet, ildv, n]
                for ihav in range(1, MAXHAV + 1):
                    if m != 0.0:
                        st = ftech[MNUMCR, ivtyp, ifleet, ildv, ihav]
                        num, den = num + st, den + (st / m)
        treff[ivtyp + 2, n] = f32(0.0)
        if den != 0.0:
            treff[ivtyp + 2, n] = num / den

    s.update(ivtyp=MAXVTYP + 1, ifleet=MAXFLEET + 1, ildv=MAXLDV + 1, ihav=MAXHAV + 1, iregn=MNUMCR + 1, iage=MAXAGE + 1)
    if yrs >= 2019:
        s.update(icl=MAXCLASS + 1, igp=MAXGROUP + 1)
