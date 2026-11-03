"""EFP cost routines that ELGLTR calls after loading a region's books (uefp.f, udat.f):
CAPCOST (cost of capital), ALLFAC and CNV1CRNR (allocation factors), ANEWBLD (the
miscellaneous build), ELTRAN and ELDIST (transmission and distribution capital),
and UNEWBLD (udat.f), which they call to add a build. All REAL*4 unless noted, so
every operation is rounded to float32 in Fortran's left-to-right order.

Builds live in a direct-access file in the Fortran. Here UNEWBLD keeps them in
s["_efpbld"] (record number -> dict of the fields it would write), and updates
LASTBLD and BLDLNK in the state, so a later reader can follow the linked lists.
GETBLD/STRBLD (udaf.f) copy the BILDIN common from/to a direct-access file; the
file is not available, so they are not ported (see capcost)."""

import numpy as np

from nems_open.emm.efp.common import f32, i, put
from nems_open.fortran_array import FArray

MNUMNR = 28
MNUMCR = 11
EIMISC, EITRAN, EIDIST = 7, 13, 14   # efpgen plant types
CATMAP = (1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 2, 3)   # udat.f UNEWBLD

_ICOM = {"G": 1, "T": 2, "D": 3}


def capcost(s, nrgn, icall, n):
    """Cost of debt, equity and preferred stock for ownership type N (1 private, 2 public).

    First iteration (CURITR=1 and EFPITR=1): computed from the macro rates. Other
    iterations: last iteration's values. Then, for generation and N=1 after the first
    iteration, the rates sent to capacity planning (EPU* of BILDIN).

    SAVEd locals relied on: ICOM (only if ICALL is not G/T/D, never in practice) and
    EWGTCE, which the final-iteration code reads but only the first-iteration code
    sets. s["_capcost_ewgtce"] holds it when the first iteration ran in this process;
    otherwise it is rebuilt from what that run left in COMMON: INTRFRT and UPBETA, or
    INTROEU (EWGTCE = ESRTCE(1) = INTROEU when UPBETA <= 0).
    GETBLD(1,NRGN) and STRBLD(1,NRGN) are not ported (the BILDIN record for year 1 is
    in a direct-access file): EBILDN is not updated, and EPUFPE keeps its state value
    when EPUROR <= 0 (the Fortran would leave the file's value there).
    """
    f = f32
    one, hundred = f(1.0), f(100.0)
    curiyr, curitr, efpitr = i(s, "curiyr"), i(s, "curitr"), i(s, "efpitr")
    fullyr = int(s["usyear"][curiyr])
    uestyr = i(s, "uestyr")
    esrtlt, esrtce, esrtps, esrtst = s["esrtlt"], s["esrtce"], s["esrtps"], s["esrtst"]
    esrtda = s["esrtda"]
    roradj = s["roradj"]
    zero = f(0.0)
    # DATA, REAL*4
    brmcf1, brmcf2 = f(-0.0080), f(0.8337)
    psrcf1, psrcf2 = f(0.0083), f(0.8842)

    for name in ("erbtxit", "xintch", "trnpl", "dstpl", "tutpl", "cwipint", "ntutpl"):
        s[name][nrgn, 4] = zero

    icom = _ICOM.get(icall, s.get("_capcost_icom", 0))   # ICOM is SAVEd
    s["_capcost_icom"] = icom

    if fullyr == uestyr:
        esrtda[icom] = esrtlt[1]

    # NUG debt premium: industrial BAA less utility AA
    put(s, "upniprm", f(f(s["mc_rmcorpbaa"][curiyr] - s["mc_rmcorppuaa"][curiyr]) / f(100.0)))

    comp = icom == 1 and curiyr > 5 and i(s, "usw_pol") >= 1

    with np.errstate(all="ignore"):
        if fullyr >= uestyr:
            if curitr == 1 and efpitr == 1:
                utaart = s["mc_rmcorppuaa"][curiyr]
                esrtlt[1] = f(utaart / hundred)
                esrtlt[2] = f(f(brmcf1 + f(brmcf2 * utaart)) / hundred)
                esrtlt[1] = f(esrtlt[1] + roradj)
                esrtlt[2] = f(esrtlt[2] + roradj)
                if comp:
                    esrtlt[1] = f(esrtlt[1] + s["capadj"])
                    esrtlt[2] = f(esrtlt[2] + s["capadj"])

                for name in ("erbtxit", "xintch", "trnpl", "dstpl", "tutpl", "cwipint", "ntutpl"):
                    a = s[name]
                    for ll in (1, 2, 3):
                        a[nrgn, 4] = f(a[nrgn, 4] + a[nrgn, ll])

                s["cstcon"][nrgn] = max(s["respct"][nrgn], s["compct"][nrgn], s["indpct"][nrgn])
                s["tmsint"][nrgn] = f(s["erbtxit"][nrgn, 4] / s["xintch"][nrgn, 4])
                s["trnpct"][nrgn] = f(s["trnpl"][nrgn, 4] / s["tutpl"][nrgn, 4])
                s["dstpct"][nrgn] = f(s["dstpl"][nrgn, 4] / s["tutpl"][nrgn, 4])
                s["bldrat"][nrgn] = f(s["cwipint"][nrgn, 4] / s["ntutpl"][nrgn, 4])
                s["nucpct"][nrgn] = f(f(s["n_pis"][nrgn] + s["ncapex"][nrgn])
                                      / f(s["s_pis"][nrgn] + s["scapex"][nrgn]))

                gdp = s["mc_jpgdp"]
                put(s, "infrat", f(f(gdp[curiyr] / gdp[curiyr - 1]) - one))
                tnote = f(s["mc_rmtcm10y"][curiyr] / hundred)

                mrkprm = f(0.0575)
                put(s, "intrfrt", tnote)
                intrfrt = s["intrfrt"]
                if s["utbeta"] > zero:
                    put(s, "intbeta", s["utbeta"])
                    put(s, "introeu", f(intrfrt + f(mrkprm * s["intbeta"])))
                else:
                    t = f(0.74)
                    t = f(t - f(f(2.834) * s["trnpct"][nrgn]))
                    t = f(t - f(f(0.189) * s["bldrat"][nrgn]))
                    t = f(t + f(f(0.0000024) * s["ntutpl"][nrgn, 4]))
                    t = f(t - f(f(0.983) * s["infrat"]))
                    t = f(t + f(f(0.73) * s["dstpct"][nrgn]))
                    t = f(t - f(f(0.046) * s["nucpct"][nrgn]))
                    t = f(t - f(f(0.027) * s["tmsint"][nrgn]))
                    t = f(t + f(f(0.321) * s["cstcon"][nrgn]))
                    put(s, "intbeta", t)
                    put(s, "introem", f(0.15))
                    put(s, "introeu", f(intrfrt + f(s["intbeta"] * f(s["introem"] - intrfrt))))
                esrtce[1] = s["introeu"]

                # cost of equity for new builds (ECP), another beta
                if s["upbeta"] > zero:
                    ewgtce = f(intrfrt + f(mrkprm * s["upbeta"]))
                else:
                    ewgtce = esrtce[1]
                s["_capcost_ewgtce"] = ewgtce

                esrtce[2] = esrtlt[2]
                esrtce[1] = f(esrtce[1] + roradj)
                if comp:
                    esrtce[1] = f(esrtce[1] + s["capadj"])

                esrtps[1] = f(psrcf1 + f(psrcf2 * esrtda[icom]))
                esrtps[1] = f(esrtps[1] + roradj)
                if comp:
                    esrtps[1] = f(esrtps[1] + s["capadj"])
                esrtps[2] = zero
                esrtst[n] = esrtlt[n]
            else:
                esrtlt[n] = s["esrtdl"][n, nrgn, icom]
                esrtce[n] = s["esrtcl"][n, nrgn, icom]
                esrtst[n] = s["esrtsl"][n, nrgn, icom]
                esrtps[n] = s["esrtpl"][n, nrgn, icom]

        s["esrtdl"][n, nrgn, icom] = esrtlt[n]
        s["esrtcl"][n, nrgn, icom] = esrtce[n]
        s["esrtsl"][n, nrgn, icom] = esrtst[n]
        s["esrtpl"][n, nrgn, icom] = esrtps[n]

        # national average new LT IOU debt, second iteration, for next year's preferred stock
        if curitr == 2:
            esrtd1 = zero
            j = 0
            for ir in range(1, MNUMNR):
                if s["esrtdl"][1, ir, icom] != zero:
                    esrtd1 = f(esrtd1 + s["esrtdl"][1, ir, icom])
                    j += 1
            esrtda[icom] = f(esrtd1 / f(j))

        if icall == "G" and n == 1:
            if fullyr == uestyr and curitr == 1:
                # GETBLD(1,NRGN) ... STRBLD(1,NRGN): file I/O, not ported
                put(s, "epuirt", f(0.08))
                put(s, "epucre", f(0.14))
            if curitr > 1:
                # GETBLD(1,NRGN): not ported
                put(s, "epuror", s["sv_prgen_esrr"][curiyr, nrgn])
                prlt, prst, prce, prps = s["esprlt"][1], s["esprst"][1], s["esprce"][1], s["esprps"][1]
                debt = f(f(esrtlt[1] * prlt) + f(esrtst[1] * prst))
                put(s, "epuirt", f(debt / f(prlt + prst)))
                put(s, "epufdt", f(prlt + prst))
                eq = f(f(esrtce[1] * prce) + f(esrtps[1] * prps))
                if s["epuror"] > zero:
                    put(s, "epufpe", f(eq / s["epuror"]))
                ewgtce = s.get("_capcost_ewgtce")
                if ewgtce is None:   # SAVEd local left by the first iteration, rebuilt from COMMON
                    if s["upbeta"] > zero:
                        ewgtce = f(s["intrfrt"] + f(f(0.0575) * s["upbeta"]))
                    else:
                        ewgtce = s["introeu"]
                put(s, "epucre", ewgtce)
                if s["upnirte"] > zero:
                    put(s, "epuirt", s["upnirte"])
                if s["upnrrte"] > zero:
                    put(s, "epucre", s["upnrrte"])
                omt = f(one - s["uptxrt"])
                put(s, "eputdscrt", f(f(eq + f(debt * omt))))
                upnfdt = s["upnfdt"]
                put(s, "epdscrt", f(f(f(upnfdt * f(s["epuirt"] + s["upniprm"])) * omt)
                                    + f(f(one - upnfdt) * f(s["epucre"] + s["upnrprm"]))))
                if i(s, "usw_rtrsk") > 0:
                    retrsk = s["extrarisk"][curiyr + i(s, "uhbsyr")]
                else:
                    retrsk = zero
                put(s, "epurorr", f(s["epuror"] + retrsk))
                esrtltr = f(esrtlt[1] + retrsk)
                esrtstr = f(esrtst[1] + retrsk)
                put(s, "epuirtr", f(f(f(esrtltr * prlt) + f(esrtstr * prst)) / f(prlt + prst)))
                esrtcer = f(esrtce[1] + retrsk)
                esrtpsr = f(esrtps[1] + retrsk)
                put(s, "epufper", f(f(f(esrtcer * prce) + f(esrtpsr * prps)) / s["epurorr"]))
                put(s, "epucrer", f(s["epucre"] + retrsk))
                # STRBLD(1,NRGN): not ported


def allfac(s, nrgn):
    """Allocation factors by class for the nine allocation techniques (DEMFAC), the
    ownership split of sales, and the peaks. Sales are TOTSECLOAD in 10^9 kWh.
    SALTOTLAST is zeroed every call and only refilled on iteration 1 (EIA quirk).
    SYSLF is left at the last class's value. CNV1CRNR is declared nearby but ALLFAC
    does not call it."""
    f = f32
    zero, one = f(0.0), f(1.0)
    curitr = i(s, "curitr")
    ncls = i(s, "nclass")
    salcls, totsec = s["salcls"], s["totsecload"]
    demfac = s["demfac"]
    saltot = zero
    saltotlast = zero
    with np.errstate(all="ignore"):
        if curitr == 1:
            for c in range(1, ncls + 1):
                saltotlast = f(saltotlast + salcls[nrgn, c])
        put(s, "saltotlast", saltotlast)

        for c in range(1, ncls + 1):
            salcls[nrgn, c] = f(totsec[nrgn, c] / f(1000.0))
            saltot = f(saltot + salcls[nrgn, c])
        put(s, "saltot", saltot)
        for c in range(1, ncls + 1):
            demfac[1, c] = f(salcls[nrgn, c] / saltot)
        put(s, "saltotold", saltot)

        s["eqtlsl"][1] = f(saltot * s["estshr"][1])
        s["eqtlsl"][2] = f(saltot * s["estshr"][2])

        def share(row, src):
            total = zero
            for c in range(1, ncls + 1):
                total = f(total + src(c))
            for c in range(1, ncls + 1):
                demfac[row, c] = f(src(c) / total)
            return total

        share(2, lambda c: s["fuelmr"][c])
        share(3, lambda c: s["fuelem"][c])
        share(4, lambda c: s["cust"][c])

        total = zero   # CP
        for c in range(1, ncls + 1):
            total = f(total + s["secannualpeak"][nrgn, c, 1])
            s["cp"][c] = s["secannualpeak"][nrgn, c, 1]
        s["cpnems"][nrgn] = total
        for c in range(1, ncls + 1):
            demfac[5, c] = f(s["secannualpeak"][nrgn, c, 1] / total)

        total = zero   # PCP
        for c in range(1, ncls + 1):
            total = f(total + s["secannpeaavpcp"][nrgn, c])
            s["pcp"][c] = s["secannpeaavpcp"][nrgn, c]
        for c in range(1, ncls + 1):
            demfac[6, c] = f(s["secannpeaavpcp"][nrgn, c] / total)

        total = zero   # NCP
        for c in range(1, ncls + 1):
            total = f(total + s["secannualpeak"][nrgn, c, 2])
            s["ncp"][c] = s["secannualpeak"][nrgn, c, 2]
        s["ncpnems"][nrgn] = total
        for c in range(1, ncls + 1):
            demfac[7, c] = f(s["secannualpeak"][nrgn, c, 2] / total)

        # average-and-excess demand, with CP and with PCP
        for c in range(1, ncls + 1):
            put(s, "syslf", s["systemlf"][nrgn])
            lf = s["systemlf"][nrgn]
            demfac[8, c] = f(f(lf * demfac[1, c]) + f(f(one - lf) * demfac[5, c]))
            demfac[9, c] = f(f(lf * demfac[1, c]) + f(f(one - lf) * demfac[6, c]))


def cnv1crnr(inerc, census, shares, unrgns=MNUMNR - 3):
    """Census-division data to one EMM (NERC) region: sum over divisions 1..MNUMCR-1
    of CENSUS(d) * SHARES(INERC,d) / (sum of SHARES(1..UNRGNS,d)), for divisions
    whose SHARES(MNUMNR,d) > 1e-6. CENSUS is REAL*4, SHARES REAL*8, TOT REAL*4;
    mixed expressions run in double and round when stored. census: FArray (1..MNUMCR);
    shares: FArray (1..MNUMNR, 1..MNUMCR) float64. Returns NERC as float32.
    (Not called by ALLFAC in this source; UNRGNS defaults to MNUMNR-3 = 25.)"""
    nerc = f32(0.0)
    with np.errstate(all="ignore"):
        for d in range(1, MNUMCR):
            tot = f32(0.0)
            for r in range(1, unrgns + 1):
                tot = f32(np.float64(tot) + shares[r, d])
            if shares[MNUMNR, d] > np.float64(f32(0.000001)):
                nerc = f32(np.float64(nerc) + np.float64(census[d]) * (shares[inerc, d] / np.float64(tot)))
    return nerc


def unewbld(s, irg, ditc, afdc, bkvl, asvl, bcwp, rcwp, ptyp, syr, pcst, pcap, serp, abde):
    """Add a build to region IRG's linked list (udat.f). The Fortran appends a record
    to a direct-access file; here the record goes into s["_efpbld"]. The five
    two-element arguments are lists/arrays indexed 0..1 for ownership 1..2."""
    lastbld = i(s, "lastbld") + 1 if "lastbld" in s else len(s.setdefault("_efpbld", {})) + 1
    put(s, "lastbld", lastbld)
    if "bldlnk" not in s:
        s["bldlnk"] = FArray.zeros([(1, MNUMNR - 3), (1, 6)], np.int32)
    bldlnk = s["bldlnk"]
    recs = s.setdefault("_efpbld", {})
    icat = (CATMAP[ptyp - 1] - 1) * 2 + 1   # array index of the first link for this category
    if bldlnk[irg, icat] == 0:
        bldlnk[irg, icat] = lastbld   # first build on the list
    else:
        last = int(bldlnk[irg, icat + 1])
        if last in recs:
            recs[last]["blink"] = lastbld
    recs[lastbld] = dict(blink=0, ditc=list(ditc), afdc=list(afdc), bkvl=list(bkvl), asvl=list(asvl),
                         bcwp=list(bcwp), rcwp=list(rcwp), pcst=pcst, pcap=list(pcap), serp=serp,
                         abde=list(abde), ptyp=ptyp, syr=syr, region=irg)
    bldlnk[irg, icat + 1] = lastbld


def anewbld(s, nrgn):
    """A zero-value build of the miscellaneous plant type for this year (capital
    additions, phase-ins, sale-leasebacks and life extensions are booked on it)."""
    f = f32
    z = [f(0.0), f(0.0)]
    unewbld(s, nrgn, list(z), list(z), list(z), list(z), list(z), list(z), EIMISC, i(s, "curiyr"),
            f(0.0), list(z), f(1.0), list(z))


def eltran(s, nrgn):
    """Transmission capital for the year as a new build: CPTCST = (CPTSLP * EFDPEAK +
    CPTCON + CPTADDER) * CAPTSCALE, millions of $, spread over the construction period
    of the transmission plant type. ETLCP is REAL*4 here, so SYR is truncated from a
    real sum. Nothing happens when the cost is exactly zero."""
    f = f32
    curiyr = i(s, "curiyr")
    etlcp = f(s["eslcp"][EITRAN] - f(1.0))
    with np.errstate(all="ignore"):
        cptcst = f(f(f(f(s["cptslp"] * s["efdpeak"][nrgn]) + s["cptcon"]) + s["cptadder"][nrgn, curiyr])
                   * s["captscale"][nrgn, curiyr])
    if cptcst != f(0.0):
        syr = int(f(f(curiyr) + etlcp))
        shr = s["estshr"]
        z = [f(0.0), f(0.0)]
        unewbld(s, nrgn, list(z), list(z), list(z), list(z), list(z), list(z), EITRAN, syr, cptcst,
                [shr[1], shr[2]], f(1.0), list(z))


def eldist(s, nrgn):
    """Distribution capital for the year as a new build: CPDCST = (CPDSLP * EFDPEAK +
    CPDCON) * CAPDSCALE. EDLCP is INTEGER, so ESLCP - 1 is truncated first."""
    f = f32
    curiyr = i(s, "curiyr")
    edlcp = int(f(s["eslcp"][EIDIST] - f(1.0)))
    with np.errstate(all="ignore"):
        cpdcst = f(f(f(s["cpdslp"] * s["efdpeak"][nrgn]) + s["cpdcon"]) * s["capdscale"][nrgn, curiyr])
    if cpdcst != f(0.0):
        shr = s["estshr"]
        z = [f(0.0), f(0.0)]
        unewbld(s, nrgn, list(z), list(z), list(z), list(z), list(z), list(z), EIDIST, curiyr + edlcp, cpdcst,
                [shr[1], shr[2]], f(1.0), list(z))
