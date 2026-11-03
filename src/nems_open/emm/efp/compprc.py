"""EFP competitive pricing: COMPPRC and RATES2 (uefp.f).

GENERA calls COMPPRC after AVRPRC when USW_POL=4. COMPPRC prices each EFD slice at its
marginal energy cost (with the lag blend, loss adjustment and taxes) and RATES2 turns the
slice prices into a price per end-use service group (EPRIC2) and its components (COMPCOMP).

Not ported, because nothing reads them afterwards: the regulated tax block (BKITAX, ERGNTX;
the Fortran sets INCTAX = 0 right after reading BKITAX), FOM_ALL / FOM_NUC, EMBCST / TAXADJ,
the SORTEFDSUM debug sums, and the demand-weighted RELCOMP / MECCOMP / FIXCOMP / TAXCOMP /
PRCALL tail of RATES2 (all locals). WRITE statements are skipped.
"""

import numpy as np

from nems_open.emm.efp.common import f32, f64, i, put
from nems_open.emm.efp.rates import _quiet
from nems_open.fortran_array import FArray

MNUMNR = 28
MNUMYR = 61
EFD_D_MSP = 4
EFD_D_MVS = 36
MNEUGRP = 32


def _saved(s, name, bounds, dtype=np.float32):
    """A SAVEd local array: it lives in the state and starts at zero (-finit-local-zero)."""
    if name not in s:
        s[name] = FArray.zeros(bounds, dtype)
    return s[name]


@_quiet
def compprc(s, nrgn):
    """Competitive slice prices for one region (generation component)."""
    cur = i(s, "curiyr")
    efdns = i(s, "efdns")
    elnvct = s["elnvct"]
    estshr = s["estshr"]
    mc_jpgdp = s["mc_jpgdp"]
    ermecc, ermeclag = s["ermecc"], s["ermeclag"]
    erfxgnac, erotaxc, eritaxc = s["erfxgnac"], s["erotaxc"], s["eritaxc"]
    scsprc, scsann, scsrec = s["scsprc"], s["scsann"], s["scsrec"]
    erslcprc, elgenp, ewsprcn = s["erslcprc"], s["elgenp"], s["ewsprcn"]
    # ORIGMECC and SLCLOAD are SAVEd locals (ORIGMECC keeps the earlier years)
    origmecc = _saved(s, "_compprc_origmecc", [(1, MNUMYR), (1, MNUMNR), (1, EFD_D_MSP), (1, EFD_D_MVS)])

    mtoteusgrp = int(s["neusgrp"][1]) + int(s["neusgrp"][2]) + int(s["neusgrp"][3]) + int(s["neusgrp"][4])

    # load per slice
    slcload = {}
    for ise in range(1, EFD_D_MSP + 1):
        for b in range(1, EFD_D_MVS + 1):
            slcload[ise, b] = f32(0.0)
    totload = f32(0.0)
    efdblkserv, efdsedef = s["efdblkserv"], s["efdsedef"]
    for k in range(1, mtoteusgrp + 1):
        for ise in range(1, efdns + 1):
            b1 = int(efdsedef[ise, 1])
            b2 = int(efdsedef[ise, 2])
            for iblk in range(b1, b2 + 1):
                b = iblk - b1 + 1
                v = efdblkserv[b, ise, nrgn, k]
                slcload[ise, b] = f32(slcload[ise, b] + v)
                totload = f32(totload + v)

    # marginal-run price adjustment (MRPRC, REAL*4): ULMRCST is REAL*8
    thousand = f32(1000.0)
    if totload > 0.0:
        mrprc = f32(f64(s["ulmrcst"][nrgn]) / f64(s["qelasn"][nrgn, cur]) * f64(thousand))
    else:
        mrprc = f32(0.0)
    # STEO benchmark adder: same for all regions, from the national cost
    bmprc = f32(f64(s["ulbmcst"]) / f64(s["qelasn"][MNUMNR, cur]) * f64(thousand))

    steoprc_adj = f32(0.0)
    if s["bmelprc"][cur] > 0:
        steoprc_adj = f32(f32(s["bchmrksteoprc_n"][nrgn, cur] / thousand) / s["qelasn"][nrgn, cur])

    for iown in (1, 2):
        erfxgnac[cur, nrgn, iown] = f32(0.0)

    # marginal energy cost by slice
    uhbsyr, uestyr = i(s, "uhbsyr"), i(s, "uestyr")
    one = f32(1.0)
    for isea in range(1, efdns + 1):
        for islc in range(1, int(elnvct[isea]) + 1):
            nm = s["nmarcst"][nrgn, isea, islc, cur]
            if nm == 80.0:
                tempmec = f32(s["marcst2"][isea, islc])
            else:
                # REAL*8 NMARCST makes the whole sum REAL*8
                tempmec = f32(f64(nm) + f64(mrprc) + f64(bmprc) - f64(steoprc_adj))

            # adjust energy for losses
            ermecc[cur, nrgn, isea, islc] = f32(
                f32(tempmec * mc_jpgdp[cur])
                * f32(one + f32(s["nerctdloss"][nrgn] * s["ulossadj"][cur])))
            origmecc[cur, nrgn, isea, islc] = ermecc[cur, nrgn, isea, islc]

            # account for lag if appropriate; first reassign the lag if not enough history
            lag = ermeclag[cur, nrgn]
            if lag > 0.0 and lag < f32(1.01):
                if cur + uhbsyr == uestyr:
                    ermeclag[cur, nrgn] = f32(0)
            elif lag < f32(2.01):
                if cur + uhbsyr < uestyr + 2:
                    ermeclag[cur, nrgn] = f32(0)
            elif lag < f32(3.01):
                if cur + uhbsyr < uestyr + 4:
                    ermeclag[cur, nrgn] = f32(0)

            lag = ermeclag[cur, nrgn]
            if s["bmelprc"][cur] == 0.0 and lag > 0.0:
                infl1 = f32(mc_jpgdp[cur] / mc_jpgdp[cur - 1])
                infl2 = f32(mc_jpgdp[cur] / mc_jpgdp[cur - 2])
                infl3 = f32(mc_jpgdp[cur] / mc_jpgdp[cur - 3])
                infl4 = f32(mc_jpgdp[cur] / mc_jpgdp[cur - 4])
                o0 = origmecc[cur, nrgn, isea, islc]
                if lag < f32(1.01):
                    o1 = origmecc[cur - 1, nrgn, isea, islc]
                    ermecc[cur, nrgn, isea, islc] = f32(
                        f32(f32(lag * o1) * infl1) + f32(f32(one - lag) * o0))
                elif lag < f32(2.01):    # 3 year rolling average
                    o1 = origmecc[cur - 1, nrgn, isea, islc]
                    o2 = origmecc[cur - 2, nrgn, isea, islc]
                    ermecc[cur, nrgn, isea, islc] = f32(
                        f32(f32(f32(o2 * infl2) + f32(o1 * infl1)) + o0) / f32(3.0))
                elif lag > f32(2.00):    # 5 year rolling average
                    o1 = origmecc[cur - 1, nrgn, isea, islc]
                    o2 = origmecc[cur - 2, nrgn, isea, islc]
                    o3 = origmecc[cur - 3, nrgn, isea, islc]
                    o4 = origmecc[cur - 4, nrgn, isea, islc]
                    t = f32(o4 * infl4)
                    t = f32(t + f32(o3 * infl3))
                    t = f32(t + f32(o2 * infl2))
                    t = f32(t + f32(o1 * infl1))
                    t = f32(t + o0)
                    ermecc[cur, nrgn, isea, islc] = f32(t / f32(5.0))

    # wholesale price and revenue by ownership
    ewsprcn[nrgn, cur] = f32(0.0)
    ectxrt, eqtlsl = s["ectxrt"], s["eqtlsl"]
    ulwdth = s["ulwdth"]
    milli = f32(0.001)
    for iown in (1, 2):
        oth = erfxgnac[cur, nrgn, iown]
        temprev = f32(0.0)
        for isea in range(1, efdns + 1):
            for islc in range(1, int(elnvct[isea]) + 1):
                mec = ermecc[cur, nrgn, isea, islc]
                sls = f32(f32(slcload[isea, islc] * milli) * estshr[iown])
                hrs = ulwdth[islc, isea, nrgn]
                if iown == 1:
                    ewsprcn[nrgn, cur] = f32(ewsprcn[nrgn, cur] + f32(mec * hrs))
                # REL is a SAVEd local that is never set: always 0
                tempprc = f32(f32(f32(0.0) + mec) + oth)
                temprev = f32(temprev + f32(tempprc * sls))

        # stranded costs in billion nominal dollars
        scsann[cur, nrgn, iown] = f32(f32(scsrec[cur, nrgn] * thousand) * estshr[iown])

        # regulated income tax is zeroed in the Fortran
        inctax = f32(0.0)
        finrev = f32(f32(f32(temprev + inctax) + scsann[cur, nrgn, iown]) / f32(one - ectxrt[iown]))
        othtax = f32(finrev * ectxrt[iown])

        if eqtlsl[iown] > 0.0:
            erotaxc[cur, nrgn, iown] = f32(othtax / eqtlsl[iown])
            eritaxc[cur, nrgn, iown] = f32(inctax / eqtlsl[iown])
            scsprc[cur, nrgn, iown] = f32(scsann[cur, nrgn, iown] / eqtlsl[iown])
        else:
            erotaxc[cur, nrgn, iown] = f32(0.0)
            eritaxc[cur, nrgn, iown] = f32(0.0)
            scsprc[cur, nrgn, iown] = f32(0.0)

    ewsprcn[nrgn, cur] = f32(f32(ewsprcn[nrgn, cur] / f32(8760.0)) / mc_jpgdp[cur])
    ewsprcn[nrgn, cur] = f32(ewsprcn[nrgn, cur] + f32(s["rmavg"][cur, nrgn] / f32(8.760)))
    ewsprcn[nrgn, cur] = f32(ewsprcn[nrgn, cur] - f32(s["eprpspr"][cur] * s["uprnwbnd"][cur]))

    # final slice prices, with taxes and stranded cost recovery
    for isea in range(1, efdns + 1):
        for islc in range(1, int(elnvct[isea]) + 1):
            for iown in (1, 2):
                erslcprc[cur, nrgn, isea, islc, iown] = f32(
                    f32(f32(f32(ermecc[cur, nrgn, isea, islc] + erfxgnac[cur, nrgn, iown])
                            + erotaxc[cur, nrgn, iown]) + eritaxc[cur, nrgn, iown])
                    + scsprc[cur, nrgn, iown])

            # average public & private
            erslcprc[cur, nrgn, isea, islc, 3] = f32(
                f32(erslcprc[cur, nrgn, isea, islc, 1] * estshr[1])
                + f32(erslcprc[cur, nrgn, isea, islc, 2] * estshr[2]))
            erotaxc[cur, nrgn, 3] = f32(f32(erotaxc[cur, nrgn, 1] * estshr[1]) + f32(erotaxc[cur, nrgn, 2] * estshr[2]))
            eritaxc[cur, nrgn, 3] = f32(f32(eritaxc[cur, nrgn, 1] * estshr[1]) + f32(eritaxc[cur, nrgn, 2] * estshr[2]))
            scsprc[cur, nrgn, 3] = f32(f32(scsprc[cur, nrgn, 1] * estshr[1]) + f32(scsprc[cur, nrgn, 2] * estshr[2]))

            # slice price used for endogenous retirements
            elgenp[islc, isea, nrgn] = f32(ermecc[cur, nrgn, isea, islc] / mc_jpgdp[cur])

    rates2(s, nrgn)


@_quiet
def rates2(s, nrgn):
    """Average competitive price by end-use service: slice price weighted by the service's
    share of load in each slice (EFDBLKSERV / TOTEULOAD), plus the reserve-margin adder."""
    cur = i(s, "curiyr")
    efdns = i(s, "efdns")
    nclass = i(s, "nclass")
    elnvct = s["elnvct"]
    estshr = s["estshr"]
    mc_jpgdp = s["mc_jpgdp"]
    epric2, compcomp = s["epric2"], s["compcomp"]
    erslcprc, ermecc = s["erslcprc"], s["ermecc"]
    errelc = s["errelc"]
    efdblkserv, efdsedef = s["efdblkserv"], s["efdsedef"]
    toteuload, salcls = s["toteuload"], s["salcls"]
    # SORTEFDBLK is a SAVEd local, divided in place
    sortefdblk = _saved(s, "_rates2_sortefdblk", [(1, EFD_D_MSP), (1, EFD_D_MVS), (1, MNEUGRP)])
    thousand = f32(1000.0)

    avgrel = [f32(0.0)] * (MNEUGRP + 1)
    avgmec = [f32(0.0)] * (MNEUGRP + 1)
    avgfix = [f32(0.0)] * (MNEUGRP + 1)
    avgitx = [f32(0.0)] * (MNEUGRP + 1)
    avgotx = [f32(0.0)] * (MNEUGRP + 1)
    avgrelo = [f32(0.0)] * (MNEUGRP + 1)
    for k in range(1, MNEUGRP + 1):
        epric2[k, nrgn] = f32(0.0)

    totload = f32(0.0)
    mtoteusgrp = int(s["neusgrp"][1]) + int(s["neusgrp"][2]) + int(s["neusgrp"][3]) + int(s["neusgrp"][4])
    for k in range(1, mtoteusgrp + 1):
        for ise in range(1, efdns + 1):
            b1 = int(efdsedef[ise, 1])
            b2 = int(efdsedef[ise, 2])
            for iblk in range(b1, b2 + 1):
                b = iblk - b1 + 1
                sortefdblk[ise, b, k] = efdblkserv[b, ise, nrgn, k]
                totload = f32(totload + sortefdblk[ise, b, k])

    # CO2 capacity price adjustment: ULCO2CST is REAL*8
    if totload > 0.0:
        co2prc = f32(f64(s["ulco2cst"][nrgn, cur]) / f64(s["qelasn"][nrgn, cur]) * f64(thousand))
    else:
        co2prc = f32(0.0)

    tmppcp = [f32(0.0)] * 6
    tmprm = [f32(0.0)] * 6
    for icls in range(1, nclass + 1):
        tmppcp[5] = f32(tmppcp[5] + s["secannpeaavpcp"][nrgn, icls])
    for icls in range(1, nclass + 1):
        tmppcp[icls] = f32(s["secannpeaavpcp"][nrgn, icls] / tmppcp[5])
        if tmppcp[icls] < 0.0:
            tmppcp[icls] = f32(0.0)

    jp = mc_jpgdp[cur]
    k = 1
    for icls in range(1, nclass + 1):
        if salcls[nrgn, icls] > 0.0:
            # RMPOOL is REAL*4 and SRPOOL REAL*8: the pool sum, and so the quotient, are REAL*8
            pool = f64(s["rmpool"][cur, nrgn]) + f64(s["srpool"][cur, nrgn])
            num = pool * f64(jp) * f64(tmppcp[icls])
            tmprm[icls] = f32(num / f64(salcls[nrgn, icls]) + f64(f32(co2prc * jp)))
        else:
            tmprm[icls] = f32(0.0)

        for _j in range(1, int(s["neusgrp"][icls]) + 1):
            for ise in range(1, efdns + 1):
                for isl in range(1, int(elnvct[ise]) + 1):
                    if toteuload[k, nrgn] > 0.0:
                        sortefdblk[ise, isl, k] = f32(sortefdblk[ise, isl, k] / toteuload[k, nrgn])
                    else:
                        sortefdblk[ise, isl, k] = f32(0.0)

                    epric2[k, nrgn] = f32(epric2[k, nrgn] + f32(erslcprc[cur, nrgn, ise, isl, 3] * sortefdblk[ise, isl, k]))
                    avgrelo[k] = f32(avgrelo[k] + f32(errelc[cur, nrgn, ise, isl] * sortefdblk[ise, isl, k]))
                    avgmec[k] = f32(avgmec[k] + f32(ermecc[cur, nrgn, ise, isl] * sortefdblk[ise, isl, k]))

            avgrel[k] = tmprm[icls]
            epric2[k, nrgn] = f32(epric2[k, nrgn] + tmprm[icls])

            fx, itx, otx = s["erfxgnac"], s["eritaxc"], s["erotaxc"]
            avgfix[k] = f32(f32(avgfix[k] + f32(fx[cur, nrgn, 1] * estshr[1])) + f32(fx[cur, nrgn, 2] * estshr[2]))
            avgitx[k] = f32(f32(avgitx[k] + f32(itx[cur, nrgn, 1] * estshr[1])) + f32(itx[cur, nrgn, 2] * estshr[2]))
            avgotx[k] = f32(f32(avgotx[k] + f32(otx[cur, nrgn, 1] * estshr[1])) + f32(otx[cur, nrgn, 2] * estshr[2]))
            k += 1

    for k in range(1, mtoteusgrp + 1):
        compcomp[1, k, nrgn] = avgrel[k]
        compcomp[2, k, nrgn] = avgmec[k]
        compcomp[3, k, nrgn] = avgfix[k]
        compcomp[4, k, nrgn] = f32(avgitx[k] + avgotx[k])
