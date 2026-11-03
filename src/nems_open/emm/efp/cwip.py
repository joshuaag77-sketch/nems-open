"""EFP construction work in progress: ELADCR (AFUDC rate), ELCWIP (CWIP accounts for
new builds and capital additions to existing plant) and ELCEXP (construction
expenditure profile), uefp.f. All REAL*4 unless noted, so every operation is
rounded to float32 in Fortran's left-to-right order."""

import numpy as np

from nems_open.emm.efp.common import f32, i, powf

EIPROD = 12   # highest production plant type (efpgen)
NPTYP = 14    # number of plant types (efpgen)


def eladcr(s):
    """AFUDC rate and its debt fraction, for public and private ownership."""
    f = f32
    shr, prce, rtce = s["estshr"], s["esprce"], s["esrtce"]
    prps, empl, prlt = s["esprps"], s["esempl"], s["esprlt"]
    emdl, prst, rtst = s["esemdl"], s["esprst"], s["esrtst"]
    afdc, wacd = s["esafdc"], s["eswacd"]
    for n in (1, 2):
        if shr[n] != f(0.0):
            tempe = f(f(prce[n] * rtce[n]) + f(prps[n] * empl[n]))
            tempd = f(f(prlt[n] * emdl[n]) + f(prst[n] * rtst[n]))
            afdc[n] = f(tempd + tempe)
            if afdc[n] > f(0.001):
                wacd[n] = f(tempd / afdc[n])
            else:
                wacd[n] = f(1.0)
        else:
            afdc[n] = f(0.0)
            wacd[n] = f(0.0)


def elcexp(jyr, lcp):
    """Share of total construction spending that falls in year JYR of an LCP-year
    construction period (REAL*4 function; ELCWIP does not call it in this build)."""
    f = f32
    if jyr == 1:
        return f(0.0)
    iyr = lcp - jyr + 1
    clt = f(lcp - 1)
    half_pi, a, b, one = f(1.570796), f(4.08198), f(3.24948), f(1.0)
    with np.errstate(all="ignore"):
        ycur = f(iyr)
        c = f(np.cos(np.float64(f(f(half_pi * ycur) / clt))))
        cexpc = powf(f(one - powf(c, a)), b)
        ypre = f(iyr - 1)
        c = f(np.cos(np.float64(f(f(half_pi * ypre) / clt))))
        cexpl = powf(f(one - powf(c, a)), b)
    return f(cexpc - cexpl)


def _add_capital(s, ebnum, n, j, capad):
    f = f32
    s["ebbkvl"][ebnum, n] = f(capad + s["ebbkvl"][ebnum, n])
    s["ebasvl"][ebnum, n] = f(s["ebasvl"][ebnum, n] + capad)
    s["ebycwp"][ebnum, n] = f(s["ebycwp"][ebnum, n] + capad)
    s["epycwp"][j, n, 2] = f(s["epycwp"][j, n, 2] + capad)
    s["erycwp"][n] = f(s["erycwp"][n] + capad)


def elcwip(s, nrgn, icall):
    """CWIP, AFUDC, sales and property tax for each build, then the capital
    additions to existing plant and completed production builds (ICALL = 'G')."""
    f = f32
    one, half = f(1.0), f(0.5)
    curiyr = i(s, "curiyr")
    ebnum = i(s, "ebnum")
    shr = s["estshr"]
    gdp = f(s["mc_jpgdp"][curiyr])
    ebptyp, ebsyr, eslcp, escprf = s["ebptyp"], s["ebsyr"], s["eslcp"], s["escprf"]
    ebpcap, ebpcst, ebserp = s["ebpcap"], s["ebpcst"], s["ebserp"]
    ebycwp, ebasvl, ebbcwp = s["ebycwp"], s["ebasvl"], s["ebbcwp"]
    ebrcwp, ebbkvl = s["ebrcwp"], s["ebbkvl"]
    for n in (1, 2):
        if shr[n] == f(0.0):
            continue
        for name in ("erbcwp", "errcwp", "eroffs", "erfdce", "erfdcd", "ersltx", "erprtx", "erycwp",
                     "erdlrb", "erafdl", "erffdc", "erxfdc", "ercidc"):
            s[name][n] = f(0.0)
        for j in range(1, NPTYP + 1):
            for name in ("epgw", "epcgw", "epafdc", "eponln"):
                s[name][j, n] = f(0.0)
            s["epycwp"][j, n, 1] = f(0.0)
            s["epycwp"][j, n, 2] = f(0.0)
        wace = f(one - s["eswacd"][n])
        afdc_rate, rtlt, rbaf = s["esafdc"][n], s["esrtlt"][n], s["esrbaf"][n]

        for b in range(1, ebnum + 1):
            j = int(ebptyp[b])
            sy = int(ebsyr[b])
            # NSTRT is INTEGER = EBSYR - ESLCP(J) + 1 with ESLCP REAL: real arithmetic, truncated
            nstrt = int(f(f(f(sy) - eslcp[j]) + one))
            if curiyr >= nstrt:
                if curiyr <= sy:
                    cwpper = s["escwpp"][n]
                    iyrfc = sy - curiyr + 1
                    conper = escprf[j, iyrfc]
                    ycwp = f(f(f(conper * ebpcap[b, n]) * ebpcst[b]) * gdp)
                    ebycwp[b, n] = ycwp
                    s["erycwp"][n] = f(s["erycwp"][n] + ycwp)
                    elasvl = ebasvl[b, n]
                    ebasvl[b, n] = f(ebasvl[b, n] + ycwp)
                    cwipwa = f(ebbcwp[b, n] + ebycwp[b, n])
                    base = f(ebbcwp[b, n] + f(half * ebycwp[b, n]))
                    omc = f(one - cwpper)
                    if curiyr != sy:
                        afudc = f(f(base * omc) * afdc_rate)
                        avdint = f(f(elasvl + f(half * ebycwp[b, n])) * rtlt)
                        ebbcwp[b, n] = f(cwipwa + afudc)
                        rbcwpl = ebrcwp[b, n]
                        ebrcwp[b, n] = f(f(cwipwa * cwpper) + f(f(cwipwa * omc) * rbaf))
                        s["erdlrb"][n] = f(s["erdlrb"][n] + f(ebrcwp[b, n] - rbcwpl))
                        s["errcwp"][n] = f(ebrcwp[b, n] + s["errcwp"][n])
                        s["erbcwp"][n] = f(s["erbcwp"][n] + ebbcwp[b, n])
                        s["epgw"][j, n] = f(s["epgw"][j, n] + ebpcap[b, n])
                    else:
                        omsp = f(one - ebserp[b])
                        afudc = f(f(f(base * omc) * omsp) * afdc_rate)
                        ebbkvl[b, n] = f(cwipwa + afudc)
                        avdint = f(f(f(elasvl + f(half * ebycwp[b, n])) * rtlt) * omsp)
                        s["erdlrb"][n] = f(f(f(f(f(2.0) * ebserp[b]) - one) * f(ebbkvl[b, n] - ebrcwp[b, n]))
                                           + s["erdlrb"][n])
                        s["erafdl"][n] = f(s["erafdl"][n] + f(f(omsp * omc) * ebbkvl[b, n]))
                        s["epcgw"][j, n] = f(s["epcgw"][j, n] + ebpcap[b, n])
                        s["eponln"][j, n] = f(s["eponln"][j, n] + ebbkvl[b, n])

                    s["erfdce"][n] = f(f(afudc * wace) + s["erfdce"][n])
                    debtaf = f(afudc * s["eswacd"][n])
                    s["erfdcd"][n] = f(debtaf + s["erfdcd"][n])
                    s["eroffs"][n] = f(f(afudc * rbaf) + s["eroffs"][n])
                    if nstrt >= i(s, "jcapyr") and curiyr >= i(s, "icapyr"):
                        ebasvl[b, n] = f(ebasvl[b, n] + avdint)
                        s["ercidc"][n] = f(s["ercidc"][n] + avdint)
                    else:
                        debtaf = f(debtaf / f(one - s["esftxr"][n]))
                        s["ercidc"][n] = f(s["ercidc"][n] + debtaf)
                    s["epycwp"][j, n, 1] = f(s["epycwp"][j, n, 1] + ebycwp[b, n])
                    s["epafdc"][j, n] = f(s["epafdc"][j, n] + afudc)
                    s["ersltx"][n] = f(f(s["essltx"][n] * ebycwp[b, n]) + s["ersltx"][n])
                # property tax: every build from the start of construction, including builds
                # already in service (EIA quirk), on EBBKVL as it stands
                s["erprtx"][n] = f(f(s["esptxr"][n] * ebbkvl[b, n]) + s["erprtx"][n])
        s["erfdc"][n] = f(s["erfdce"][n] + s["erfdcd"][n])

        if icall == "G" and curiyr + i(s, "uhbsyr") > i(s, "efpsyr"):
            eomw, ercca, esbklf = s["eomw"], s["ercca"], s["esbklf"]
            for j in range(1, EIPROD + 1):
                # LYR is INTEGER from a REAL expression, truncated
                lyr = int(f(f(f(esbklf[j, n] - f(curiyr)) + f(i(s, "efpsyr"))) - f(i(s, "uhbsyr"))))
                lyr = max(min(lyr, i(s, "eovyrs")), 0)
                for iyr in range(1, lyr + 1):
                    capad = f(f(f(eomw[iyr, j, n, nrgn] * ercca[j]) * gdp) * shr[n])
                    _add_capital(s, ebnum, n, j, capad)
            # additions on completed production builds, each year of book life
            for b in range(1, ebnum + 1):
                j = int(ebptyp[b])
                if j <= EIPROD:
                    sy = int(ebsyr[b])
                    if curiyr >= sy and f(curiyr) < f(f(sy) + esbklf[j, n]):
                        capad = f(f(f(ebpcap[b, n] * ercca[j]) * gdp) * f(1000.0))
                        _add_capital(s, ebnum, n, j, capad)
