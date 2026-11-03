"""Rail and the smaller modes (tran.f): TRAIL, TMISC.

TRAIL  freight rail ton-miles (FAF commodity shares, coal growth), fuel use, and
       LNG locomotive adoption by payback against diesel
TMISC  military fuel; transit, commuter and intercity rail; transit, intercity and
       school buses by fuel; recreational boats; lubricants

Both routines read last year's values from saved local arrays. A port keeps them
in `carry` (the oracle dumps them as p_<name> at the routine's end).
"""

import numpy as np

from nems_open.transportation.common import f32, fsum, MAXHAV, MAXLDV, MAXVTYP, MNUMCR, powf

MAXFLEET = 4
SIC = 16
US = 11
R9 = slice(1, MNUMCR - 2)


_POWI = {}


def powi(x, n):
    """REAL**INTEGER as gfortran computes it (libgcc __powisf2, square and multiply in float32).
    Nonzero scalars are memoized (a zero keeps its sign, so it is not)."""
    if type(x) is np.float32 and x:
        key = (float(x), n)
        r = _POWI.get(key)
        if r is None:
            r = _POWI[key] = _powi(x, n)
        return r
    return _powi(f32(x), n)


def _powi(x, n):
    x = f32(x)
    m = abs(int(n))
    r = x if m % 2 else f32(1.0)
    m >>= 1
    while m:
        x = x * x
        if m % 2:
            r = r * x
        m >>= 1
    return f32(1.0) / r if n < 0 else r


def trail(s: dict, carry: dict) -> None:
    """carry: rail_fuel_shr(4, MNUMYR), lng_locom_inccost(MNUMYR), adoptlng(MNUMYR), year n-1 filled."""
    n, yrs = int(s["n"]), int(s["curcalyr"])
    nct, ct = s["rproj_nctonmi"], s["rproj_ctonmi"]
    nct[n, :, :] = 0.0
    ct[n, :] = 0.0
    tsic, rtm, hist_nc, hist_c = s["tsic"], s["rtm_output"], s["rhist_nctonmi"], s["rhist_ctonmi"]
    faf, railhist = 28, int(s["railhistyr"])  # iFAFyear: last Freight Analysis Framework year index

    if n == faf:
        for iregn in range(1, MNUMCR - 1):
            for isic in range(1, SIC + 1):
                t = tsic[isic, iregn, faf]
                rtm[iregn, isic] = hist_nc[n, iregn] * s["rtm_shares"][iregn, isic] / t if t > 0.0 else f32(0.0)

    for iregn in range(1, MNUMCR - 1):
        for isic in range(1, SIC + 1):
            if faf <= n <= railhist:
                nct[n, iregn, isic] = tsic[isic, iregn, n] * rtm[iregn, isic]

    rtmtt, ttonmile = s["rtmtt"], s["ttonmile"]
    for iregn in range(1, MNUMCR - 1):
        if n <= railhist:
            rtmtt[n, iregn] = 0.0
            tot = fsum(nct[n, R9, 1:SIC])
            if n >= faf and tot > 0.0:
                rtmtt[n, iregn] = (fsum(hist_nc[n, R9]) * (fsum(nct[n, iregn, 1:SIC]) / tot)) + hist_c[n, iregn]
            else:
                rtmtt[n, iregn] = hist_nc[n, iregn] + hist_c[n, iregn]
        else:
            for isic in range(1, SIC + 1):
                nct[n, iregn, isic] = tsic[isic, iregn, n] * rtm[iregn, isic]
            growth = (ttonmile[n] - ttonmile[n - 1]) / ttonmile[n - 1]
            prev = hist_c[n - 1, iregn] if n == railhist + 1 else ct[n - 1, iregn]
            ct[n, iregn] = prev * (f32(1.0) + growth)
            rtmtt[n, iregn] = fsum(nct[n, iregn, 1:SIC]) + ct[n, iregn]
    rtmtt[n, 11] = fsum(rtmtt[n, R9])

    for iregn in range(1, MNUMCR + 1):
        s["tqfrailt"][n, iregn] = rtmtt[n, iregn] * s["freff"][n]

    if s["paybk"] > 30:
        s["paybk"] = 30
    paybk = int(s["paybk"])

    shr, inccost, adopt = carry["rail_fuel_shr"], carry["lng_locom_inccost"], carry["adoptlng"]
    rail_fuel = s["rail_fuel"]
    ngyear = int(s["ngyear"])
    if yrs < ngyear:
        for ifuelx in range(1, 5):
            shr[ifuelx, n] = rail_fuel[ifuelx]
    else:
        jp = s["mc_jpgdp"]
        price_ds = s["pdstr"][US, n] * jp[1] * s["cidiscount"]           # diesel, 1990$/MMBtu
        price_lng = s["pgltrrail"][1, US, n] * jp[1] * f32(2.0)          # LNG
        btu, life, freff = s["locombtu"], s["locom_life"], s["freff"][n]
        sav = [f32(0.0)] * (paybk + 1)
        for y in range(1, paybk + 1):
            use = (btu * life[y] * freff) / f32(1000.0)
            sav[y] = (use * price_ds) - (use * price_lng)
        disc = f32(1.0) + s["discrt"]
        npv = sav[1] / disc
        for y in range(2, paybk + 1):
            npv = npv + sav[y] / powi(disc, y)
        if yrs == ngyear:
            inccost[n] = s["rlng_inccost"] / jp[24] * jp[1]
            adopt[n - 1] = 1
        else:
            inccost[n] = inccost[n - 1] * s["rlng_learn"]
        if inccost[n] > npv:
            adopt[n] = adopt[n - 1]
            shr[4, n] = shr[4, n - 1]
        else:
            adopt[n] = adopt[n - 1] + 1
            shr[4, n] = shr[4, n - 1] + s["lng_maxpen"][int(adopt[n])] * shr[1, n - 1]
        shr[1, n] = f32(1.0) - shr[4, n]
        shr[2, n] = rail_fuel[2]
        shr[3, n] = rail_fuel[3]

    q = s["tqrailr"]
    for iregn in range(1, MNUMCR + 1):
        for ifuelx in range(1, 5):
            q[ifuelx, iregn, n] = s["tqfrailt"][n, iregn] * shr[ifuelx, n]
    s.update(iregn=MNUMCR + 1, ifuelx=5)


def tmisc(s: dict, carry: dict) -> None:
    """carry: hyway(MNUMYR), ftvmt(MNUMYR), year n-1 filled."""
    n, yrs = int(s["n"]), int(s["curcalyr"])
    log, exp = np.log, np.exp
    np16, gdpr, jp = s["mc_np16a"], s["mc_gdpr"], s["mc_jpgdp"]

    # Military: national fuel use grows with military spending, split by fixed regional shares.
    mfd, milt = s["mfd"], int(s["milthistyr"])
    milt_gr = s["mc_gfmlr"][n] / s["mc_gfmlr"][n - 1] if yrs > milt else None
    for ifuelx in range(1, 5):
        if n < 6:
            mfd[ifuelx, n] = 0.0
        if n >= 6 and yrs <= milt:
            mfd[ifuelx, n] = s["mfdh"][ifuelx, n]
        if yrs > milt:
            mfd[ifuelx, n] = mfd[ifuelx, n - 1] * milt_gr
    qmil = s["qmiltr"]
    for ifuelx in range(1, 5):
        for iregn in range(1, MNUMCR - 1):
            qmil[ifuelx, iregn, n] = mfd[ifuelx, n] * s["miltrshr90"][ifuelx, iregn]
    for ifuelx in range(1, 5):
        qmil[ifuelx, MNUMCR, n] = fsum(qmil[ifuelx, R9, n])

    emp = s["mc_empna"]
    nonfarm = {r: fsum(emp[r, 1:39, n]) - fsum(emp[r, 20:21, n]) for r in range(1, MNUMCR - 1)}
    p19 = s["pmgtr"][11, n] * s["cfmgq"][n] / f32(42.0) * jp[30]
    gdp_pc = log(gdpr[n] / np16[11, n])

    def pc_exp(coef, covid, r):
        return coef[r, 1] + (gdp_pc * coef[r, 2] + log(p19) * coef[r, 3] + covid[r, n] * coef[r, 4])

    # Automated vehicles in taxi fleets (fleet 4, automation 2-4) take riders from rail and buses.
    cav = fsum(s["fltechvmt"][MNUMCR, 1:MAXVTYP, 4, 1:MAXLDV, 2:MAXHAV])

    # Transit rail
    trrpm, treff, tred, trpc = s["trrpm"], s["treff"], s["tred"], s["trrpmpc"]
    for r in range(1, MNUMCR - 1):
        if yrs <= int(s["trhistyear"]):
            trrpm[r, n], treff[r, n], tred[r, n] = s["trrpmhist"][r, n], s["treffhist"][r, n], s["tredhist"][r, n]
        elif tred[r, n - 1] > 0.0:
            trpc[r, n] = exp(pc_exp(s["tr_coef"], s["trcovid"], r))
            trrpm[r, n] = trpc[r, n] * nonfarm[r]
            adj = s["treffhist"][r, 33] - s["treffhist"][r, 30]
            if trrpm[r, n] < trrpm[r, 30]:
                treff[r, n] = s["treffhist"][r, 33] - (adj * (trrpm[r, n] / trrpm[r, 30]))
            else:
                treff[r, n] = treff[r, 30]
        else:
            trpc[r, n] = 0.0
    shr = {r: trrpm[r, n] / fsum(trrpm[R9, n]) for r in range(1, MNUMCR - 1)}
    for r in range(1, MNUMCR - 1):
        if shr[r] > 0.0:
            trrpm[r, n] = trrpm[r, n] - (cav * s["tr_cav_adj"][n] * shr[r] / f32(1000000.0))
        tred[r, n] = trrpm[r, n] * treff[r, n] / f32(1000000.0) if trrpm[r, n] > 0.0 else f32(0.0)
    tred[11, n] = fsum(tred[R9, n])

    # Commuter rail
    crrpm, creff, cred, credd, crede = s["crrpm"], s["creff"], s["cred"], s["credd"], s["crede"]
    crhist = int(s["crhistyear"])
    for r in range(1, MNUMCR - 1):
        if yrs <= crhist:
            crrpm[r, n], creff[r, n] = s["crrpmhist"][r, n], s["creffhist"][r, n]
            credd[r, n], crede[r, n] = s["creddhist"][r, n], s["credehist"][r, n]
        else:
            crrpm[r, n] = exp(pc_exp(s["cr_coef"], s["crcovid"], r)) * nonfarm[r]
            adj = s["creffhist"][r, 33] - s["creffhist"][r, 30]
            if crrpm[r, n] < crrpm[r, 30]:
                creff[r, n] = s["creffhist"][r, 33] - (adj * (crrpm[r, n] / crrpm[r, 30]))
            else:
                creff[r, n] = creff[r, 30]
    shr = {r: crrpm[r, n] / fsum(crrpm[R9, n]) for r in range(1, MNUMCR - 1)}
    if yrs > crhist:
        for r in range(1, MNUMCR - 1):
            crrpm[r, n] = crrpm[r, n] + (cav * s["cr_cav_adj"][n] * shr[r] / f32(1000000.0))
            cred[r, n] = crrpm[r, n] * creff[r, n] / f32(1000000.0)
            credd[r, n] = cred[r, n] * s["creddshr"][r]
            crede[r, n] = cred[r, n] - credd[r, n]
    credd[MNUMCR, n] = fsum(credd[R9, n])
    crede[MNUMCR, n] = fsum(crede[R9, n])

    # Intercity rail
    irh = int(s["irhistyear"]) - 1989
    s["ireddshr"] = s["ireddhist"][irh] / (s["ireddhist"][irh] + s["iredehist"][irh])
    irrpm, irpmpc, iredd, irede, ireff, ired = s["irrpm"], s["irpmpc"], s["iredd"], s["irede"], s["ireff"], s["ired"]
    if yrs <= int(s["irhistyear"]):
        irrpm[n] = s["irrpmhist"][n]
        irpmpc[n] = irrpm[n] / np16[11, n]
        iredd[n], irede[n] = s["ireddhist"][n], s["iredehist"][n]
        ireff[n] = (iredd[n] + irede[n]) / irrpm[n] * f32(1000000.0)
    else:
        irpmpc[n] = irpmpc[n - 1] * f32(1.002)
        ireff[n] = ireff[irh]
        irrpm[n] = irpmpc[n] * np16[11, n]
        ired[n] = irrpm[n] * ireff[n] / f32(1000000.0)
        iredd[n] = ired[n] * s["ireddshr"]
        irede[n] = ired[n] - iredd[n]
    ireddr, irer = s["ireddr"], s["ireder"]
    ireddr[11, n], irer[11, n] = 0.0, 0.0
    for r in range(1, MNUMCR - 1):
        ireddr[r, n] = iredd[n] * s["irregshr"][r]
        irer[r, n] = irede[n] * s["irregshr"][r]
        ireddr[11, n] = ireddr[11, n] + ireddr[r, n]
        irer[11, n] = irer[11, n] + irer[r, n]

    qmtrr = s["qmtrr"]
    for r in range(1, MNUMCR + 1):
        qmtrr[1, r, n] = credd[r, n] + ireddr[r, n]
        qmtrr[2, r, n] = tred[r, n] + crede[r, n] + irer[r, n]
        qmtrr[3, r, n] = 0.0
        qmtrr[4, r, n] = 0.0

    # Transit buses
    tbpmt, tbpc, tbhist = s["tbpmt"], s["tbpmtpc"], int(s["tbhistyear"])
    for r in range(1, MNUMCR - 1):
        if yrs <= tbhist:
            tbpmt[r, n] = s["tbpmthist"][r, n]
        if yrs == tbhist:
            tbpc[r, n] = s["tbpmtpc08"][r]
        if yrs > tbhist:
            tbpc[r, n] = exp(pc_exp(s["tb_coef"], s["tbcovid"], r))
            tbpmt[r, n] = tbpc[r, n] * nonfarm[r]
    shr = {r: tbpmt[r, n] / fsum(tbpmt[R9, n]) for r in range(1, MNUMCR - 1)}
    for r in range(1, MNUMCR - 1):
        tbpmt[r, n] = tbpmt[r, n] - (cav * s["tb_cav_adj"][n] * shr[r] / f32(1000000.0))
    tbpmt[11, n] = fsum(tbpmt[R9, n])

    tbfshr = s["tbfshr"]
    for r in range(1, MNUMCR - 1):
        tbfshr[r, 1:8, n] = s["tbfshrhist"][1:8, n, r]

    tbbtupm, ftmpg_s = s["tbbtupm"], s["tfr_ftmpg_s"]
    iy, one = int(s["iy"]), f32(1.0)
    for r in range(1, MNUMCR - 1):
        if yrs <= tbhist:
            tbbtupm[r, n] = s["tbbtupmhist"][r, n]
        else:
            adj = tbbtupm[r, 33] - tbbtupm[r, 30]
            if tbpmt[r, n] < tbpmt[r, 30]:
                tbbtupm[r, n] = s["tbbtupmhist"][r, 33] - (adj * (tbpmt[r, n] / tbpmt[r, 30]))
            else:
                # EIA quirk: the "*1-(...)*1+(...)" reads as subtract and add, not multiply.
                tbbtupm[r, n] = (tbbtupm[r, 30] * s["tbsyseff"][r] * one
                                 - ((one - (ftmpg_s[iy - 1, 3, 2] / ftmpg_s[iy, 3, 2]) * tbfshr[r, 2, n])) * one
                                 + ((tbfshr[r, 5, n] - tbfshr[r, 5, n - 1]) * f32(0.25)))

    qmtbr = s["qmtbr"]
    for f in range(1, 9):
        for r in range(1, MNUMCR - 1):
            qmtbr[1, f, r, n] = ((tbpmt[r, n] * tbbtupm[r, n]) / f32(1000000.0)) * tbfshr[r, f, n]
        qmtbr[1, f, 11, n] = fsum(qmtbr[1, f, R9, n])

    # Intercity (1) and school (2) buses
    tmod, ibsb = s["tmod"], int(s["ibsbhistyear"])
    npop = s["mc_np"]
    for im in (1, 2):
        if yrs <= ibsb:
            tmod[im, n] = s["tmodinit"][im, n]
        elif im == 1:
            tmod[im, n] = ((s["ibcoeff"][2] + (s["ibcoeff"][1] * log((gdpr[n] / np16[11, n])))) * np16[11, n]
                           * (one - (s["tmcovid"][im, n])))
        else:
            tmod[im, n] = ((s["sbcoeff"][2] + (s["sbcoeff"][1] * (npop[11, n] - np16[11, n]) / npop[11, n]))
                           * (one - (s["tmcovid"][im, n])))
    qmod = s["qmodfshr"]
    for im in (1, 2):
        for f in range(1, 9):
            qmod[im, f, n] = s["qmodfshrh"][f, n, im] if yrs <= ibsb else qmod[im, f, n - 1]
    sb = s["schbus_pmt_shr"]
    for r in range(1, MNUMCR - 1):
        sb[1:8, r, n] = qmod[2, 1:8, n]
    if yrs > ibsb:
        # EIA quirk: updated after the school bus shares above were copied, so it shows next year.
        # TMISC includes ANGTDM, whose PGFTRFV is not the NGTDMOUT one.
        qmod[2, 5, n] = qmod[2, 5, n - 1] + ((s["hwypdstr"][11, n] / s["angtdm__pgftrfv"][11, n] - one) * f32(0.0005))
        qmod[2, 8, n] = qmod[2, 8, n - 1]
    if yrs >= 2014:
        for r in range(1, MNUMCR - 1):
            temp = sb[1, r, n] + sb[2, r, n] + sb[6, r, n]
            sb[7, r, n] = s["schbus_ev_shr"][r, n]
            for f in (1, 2, 6):
                if yrs <= ibsb:
                    sb[f, r, n] = sb[f, r, n] - sb[7, r, n] * sb[f, r, n] / temp
                else:
                    sb[f, r, n] = sb[f, r, n] - (sb[7, r, n] + sb[5, r, n]) * sb[f, r, n] / temp
            if sb[2, r, n] < 0.01:
                s["schbus_adj"][r, n] = sb[2, r, n] + sb[7, r, n] + sb[5, r, n]
                sb[2, r, n] = f32(0.01)
                sb[5, r, n] = s["schbus_adj"][r, n] - sb[7, r, n] - sb[2, r, n]

    tmod_r = s["tmod_r"]
    for f in range(1, 9):
        for r in range(1, MNUMCR - 1):
            rshr = npop[r, n] / npop[11, n]
            tmod_r[1, f, r, n] = tmod[1, n] * rshr * qmod[1, f, n]
            tmod_r[2, f, r, n] = tmod[2, n] * s["schbus_shr"][r] * sb[f, r, n]

    syseff = [None, f32(1.007), f32(1.001)]
    tmeff, tmeff_f = s["tmeff"], s["tmeff_f"]
    tmeff_f.a[...] = 0.0
    for im in (1, 2):
        tmeff[im, n] = s["tmeffinit"][im, n] if yrs <= ibsb else tmeff[im, n - 1] / syseff[im]
        for f in range(1, 9):
            if im == 1 and f == 2:
                tmeff_f[im, f, n] = tmeff[im, n] / f32(1000000.0)
            if im == 2:
                tmeff_f[im, f, n] = (tmeff[im, n] * s["eff_adj"][f]) / f32(1000000.0)
    for im in (1, 2):
        for r in range(1, MNUMCR - 1):
            qmtbr[im + 1, 1:8, r, n] = tmod_r[im, 1:8, r, n] * tmeff_f[im, 1:8, n]
    for im in (1, 2):
        for f in range(1, 9):
            qmtbr[im + 1, f, MNUMCR, n] = fsum(qmtbr[im + 1, f, R9, n])

    # Recreational boats
    rbedpc, recfd = s["rbedpc"], s["recfd"]
    for f in (1, 2):
        if yrs <= int(s["rbhistyr"]):
            rbedpc[f, n] = s["recfdh"][f, n]
        else:
            boats = (gdpr[n] / np16[11, n]) * (s["rbboat_coef"][1] * exp(s["rbboat_coef"][2] * f32(n)))
            rbedpc[f, n] = boats * (s["rbmg_coef"][1] * exp(s["rbmg_coef"][2] * f32(n))) if f == 1 else boats * s["rbds_coef"]
        recfd[f, n] = rbedpc[f, n]
    qrec = s["qrecr"]
    for f in (1, 2):
        qrec[f, MNUMCR, n] = 0.0
        for r in range(1, MNUMCR - 1):
            qrec[f, r, n] = recfd[f, n] * (npop[r, n] / npop[11, n])
            qrec[f, MNUMCR, n] = qrec[f, MNUMCR, n] + qrec[f, r, n]

    # Lubricants grow with highway travel.
    hyway, ftvmt = carry["hyway"], carry["ftvmt"]
    ftvmt[n] = s["vmt_tr"][n]
    hh = fsum(s["vmthh"][n, MNUMCR, 1:MAXLDV, 1:MAXVTYP])
    fl = fsum(s["fltechvmt"][MNUMCR, 1:MAXVTYP, 1:MAXFLEET, 1:MAXLDV, 1:MAXHAV])
    hyway[n] = hh + ftvmt[n] + fl
    lub = s["lubfd"]
    if yrs <= int(s["lubhistyr"]):
        lub[n] = s["lubfdh"][n]
    else:
        lub[n] = (lub[n - 1] * powf(hyway[n] / hyway[n - 1], f32(0.25)))
    qlu = s["qlutr"]
    qlu[11, n] = 0.0
    for r in range(1, MNUMCR - 1):
        lshr = (hh * s["sedshrmg"][r, n] + fl * s["sedshrmg"][r, n] + ftvmt[n] * s["sedshrds"][r, n]) / hyway[n]
        qlu[r, n] = lub[n] * lshr
        qlu[11, n] = qlu[11, n] + qlu[r, n]
    s.update(iregn=MNUMCR - 1, ifuelx=3)
