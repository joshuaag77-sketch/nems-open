"""Space cooling: RCLTEC, RCLADD and RCLCON (resd.f).

RCLTEC picks cooling equipment (logit on life-cycle cost), RCLADD tracks equipment
added and replaced by vintage, and RCLCON turns the stock into consumption.
Debug WRITEs and the AppBetaData.txt output are skipped.

Inputs the oracle dumps do not hold:
  PELRSOUT   electricity price by end use. RCLTEC and RCLCON read it, and RSELAST
             reads it for electricity. Expected in s["pelrsout"].
  COSTTRSW   PARAMETER in rtek, 0 (menu costs, no EQCOST trend).
  EQCPN90    RCLADD's local array, carried between calls (static storage in the
             build). Kept in s["_eqcpn90"], created empty if absent.
"""

import math

import numpy as np

from nems_open.fortran_array import FArray
from nems_open.residential.common import BASEYR, COSTTRSW, ENDYR, RECSYEAR, f32, powi
from nems_open.residential.helpers import _text, eqcost, rselast

NDIV = 9
NBLDG = 3
EU = 2  # space cooling


def svrte(alpha, y, k, lam):
    """SVRTE as helpers.svrte, but pow and exp go through double and round once,
    which is what glibc's powf and expf return almost always. NumPy's float32 exp
    and pow can be one bit off, and RCLADD's replacements (a difference of two
    large sums) magnify that bit to 1e-5."""
    if f32(y) - f32(alpha) < 0:
        return f32(1.0)
    k1 = (f32(y) - f32(alpha)) / f32(lam)
    k2 = f32(math.pow(float(k1), float(f32(k))))
    return f32(math.exp(-float(k2)))


def _prices_elec(s: dict, eupr: int) -> None:
    """PRICES(4,R,CurCalYr) = PELRSOUT(R,CurIYr,EUPR) * (deflator ratio)."""
    Y, Y1 = int(s["curcalyr"]), int(s["curiyr"])
    gdp = s["mc_jpgdp"]
    for r in range(1, NDIV + 1):
        s["prices"][4, r, Y] = s["pelrsout"][r, Y1, eupr] * (gdp[int(s["rtekdollaryr"]) - BASEYR + 1] / gdp[-2])


def _cddfact(s: dict, r: int):
    Y = int(s["curcalyr"])
    ratio = s["cddadj"][Y, r] / s["cddadj"][RECSYEAR, r]
    return f32(ratio) ** f32(1.50)  # a 10% rise in CDD gives 15% more cooling


# ----------------------------------------------------------------------------
# RCLTEC
# ----------------------------------------------------------------------------
def rcltec(s: dict) -> None:
    """RCLTEC: new (NEQTSHR) and replacement (REQTSHR) shares of cooling equipment
    types, life-cycle costs LFCY, and weighted efficiencies WTEQCEFFN/R."""
    Y = int(s["curcalyr"])
    alpha1 = f32(-0.50)
    s["alpha1"] = alpha1
    _prices_elec(s, 2)

    cddfact = {r: _cddfact(s, r) for r in range(1, NDIV + 1)}

    # EIA computes DECAY on the first iteration only and keeps it in a saved
    # local; it depends on two constants, so recomputing it each call is the same.
    rate, tenure = f32(s["resdiscountrate"]), f32(s["tenure"])
    decay = (f32(1) - (f32(1) + rate) ** (-tenure)) / rate

    cleupt, typeupt, typect = s["rtcleupt"], s["rttyeupt"], s["rttypect"]
    P, LFCY = s["prices"], s["lfcy"]
    costtrsw = COSTTRSW
    eqwtn, eqwtr = {}, {}
    totewtn, totewtr = {}, {}
    ecbta1, ecbta2, ecbta3 = s["rtecbta1"], s["rtecbta2"], s["rtecbta3"]

    for r in range(1, NDIV + 1):
        for b in range(1, NBLDG + 1):
            for reccl in range(int(cleupt[EU]) + 1, int(cleupt[EU + 1]) + 1):
                eqc = int(s["rtcleqcl"][reccl])
                totewtn[eqc, b, r] = f32(0.0)
                totewtr[eqc, b, r] = f32(0.0)

            for recty in range(int(typeupt[EU]) + 1, int(typeupt[EU + 1]) + 1):
                if not (Y >= s["rtinityr"][recty] and Y <= s["rtlastyr"][recty]):
                    continue
                if s["rtcendiv"][recty] != r:
                    continue
                eqc = int(s["rttyeqcl"][recty])
                eqt = int(s["rteqtype"][recty])
                reccl = int(cleupt[EU]) + eqc
                # Heat pumps reuse the heating data (RTTYPNTR points at the heater)
                if s["rttypntr"][recty] > 0:
                    continue
                f = int(s["rtfuel"][reccl])

                if s["rteqeff"][recty] != 0.0:
                    rteffac1 = s["eqceff"][Y, reccl] / s["rteqeff"][recty]
                    rteffac2 = s["rtbaseff"][RECSYEAR, reccl] / s["rteqeff"][recty]
                else:
                    rteffac1 = s["rtbaseff"][RECSYEAR, reccl]
                    rteffac2 = s["rtbaseff"][RECSYEAR, reccl]

                if costtrsw == 1:
                    capital = eqcost(s, recty, Y, "CAP")
                else:
                    capital = s["rteqcost"][recty]

                # Price-induced behavior change: a higher real price lowers the
                # implicit discount rate.
                if Y > 2008 and P[f, r, Y] > P[f, r, RECSYEAR]:
                    s["hrdrate"] = ecbta1[recty] / ecbta2[recty]
                    s["eligble"] = s["hrdrate"] - f32(0.07)
                    if s["eligble"] > 0.0:
                        s["hrdadj"] = s["eligble"] * ((P[f, r, Y] / P[f, r, RECSYEAR]) ** alpha1)
                        s["beta1dr"][recty] = (s["hrdadj"] + f32(0.07)) * ecbta2[recty]
                    else:
                        s["beta1dr"][recty] = ecbta1[recty]
                else:
                    s["beta1dr"][recty] = ecbta1[recty]

                ectemp = s["rtecbias"][recty] + (s["beta1dr"][recty] * capital)

                if Y == RECSYEAR + 1:
                    opcost1 = P[f, r, Y] * s["eqcuec"][r, reccl, b] * rteffac1 * cddfact[r]
                    opcost2 = P[f, r, Y] * s["eqcuec"][r, reccl, b] * rteffac2 * cddfact[r]
                else:
                    opcost1 = (P[f, r, Y] * s["eqcuec"][r, reccl, b] * rteffac1 * cddfact[r]
                               * (s["ecshell"][Y - 1, r, b] / s["ecshell"][RECSYEAR, r, b]))
                    opcost2 = (P[f, r, Y] * s["eqcuec"][r, reccl, b] * rteffac2 * cddfact[r]
                               * (s["ncshell"][Y - 1, r, b] / s["ecshell"][RECSYEAR, r, b]))

                LFCY[eqt, b, r, 1] = capital + (opcost1 * decay)
                LFCY[eqt, b, r, 2] = capital + (opcost2 * decay)

                with np.errstate(all="ignore"):
                    eqwtn[eqt, b, r] = np.exp(ectemp + (ecbta2[recty] * opcost2) + (ecbta3[recty] * LFCY[eqt, b, r, 2]))
                    totewtn[eqc, b, r] = totewtn[eqc, b, r] + eqwtn[eqt, b, r]
                    eqwtr[eqt, b, r] = np.exp(ectemp + (ecbta2[recty] * opcost1) + (ecbta3[recty] * LFCY[eqt, b, r, 1]))
                    totewtr[eqc, b, r] = totewtr[eqc, b, r] + eqwtr[eqt, b, r]

            # new and replacement market shares
            typ = int(typect[EU])
            for recty in range(int(typeupt[EU]) + 1, int(typeupt[EU + 1]) + 1):
                if Y >= s["rtinityr"][recty] and Y <= s["rtlastyr"][recty]:
                    if s["rtcendiv"][recty] == r:
                        typ += 1
                        eqc = int(s["rttyeqcl"][recty])
                        eqt = int(s["rteqtype"][recty])
                        if s["rttypntr"][recty] > 0:
                            typeht = int(s["rttypntr"][recty])
                            s["neqtshr"][Y, typ, b, r] = s["neqtshr"][Y, typeht, b, r]
                            s["reqtshr"][Y, typ, b, r] = s["reqtshr"][Y, typeht, b, r]
                        else:
                            if totewtn[eqc, b, r] > 0.0:
                                s["neqtshr"][Y, typ, b, r] = eqwtn[eqt, b, r] / totewtn[eqc, b, r]
                            else:
                                s["neqtshr"][Y, typ, b, r] = f32(0.0)
                            if totewtr[eqc, b, r] > 0.0:
                                s["reqtshr"][Y, typ, b, r] = eqwtr[eqt, b, r] / totewtr[eqc, b, r]
                            else:
                                s["reqtshr"][Y, typ, b, r] = f32(0.0)

            # weighted efficiency of new and replacement equipment
            for reccl in range(int(cleupt[EU]) + 1, int(cleupt[EU + 1]) + 1):
                eqc = int(s["rtcleqcl"][reccl])
                denom, denom2 = f32(0), f32(0)
                recar, eqtar = [], []
                typ = int(typect[EU])
                for recty in range(int(typeupt[EU]) + 1, int(typeupt[EU + 1]) + 1):
                    if Y >= s["rtinityr"][recty] and Y <= s["rtlastyr"][recty]:
                        if s["rtcendiv"][recty] == r:
                            typ += 1
                            if s["rttyeqcl"][recty] == eqc:
                                recar.append(recty)
                                eqtar.append(typ)
                                denom = denom + s["neqtshr"][Y, typ, b, r]
                                denom2 = denom2 + s["reqtshr"][Y, typ, b, r]

                base = s["rtbaseff"][RECSYEAR, reccl]
                if denom <= 0.0:
                    s["wteqceffn"][Y, reccl, b, r] = f32(1) / base
                else:
                    tot = f32(0.0)
                    for recty, typ in zip(recar, eqtar):
                        tot = tot + (s["neqtshr"][Y, typ, b, r] / s["rteqeff"][recty])
                    s["wteqceffn"][Y, reccl, b, r] = tot / denom
                if s["wteqceffn"][Y, reccl, b, r] == 0.0:
                    s["wteqceffn"][Y, reccl, b, r] = f32(1) / base

                if denom2 <= 0.0:
                    s["wteqceffr"][Y, reccl, b, r] = f32(1) / base
                else:
                    tot = f32(0.0)
                    for recty, typ in zip(recar, eqtar):
                        tot = tot + (s["reqtshr"][Y, typ, b, r] / s["rteqeff"][recty])
                    s["wteqceffr"][Y, reccl, b, r] = tot / denom2
                if s["wteqceffr"][Y, reccl, b, r] == 0.0:
                    s["wteqceffr"][Y, reccl, b, r] = f32(1) / base


# ----------------------------------------------------------------------------
# RCLADD
# ----------------------------------------------------------------------------
def rcladd(s: dict) -> None:
    """RCLADD: cooling equipment added (EQCADD), replaced (EQCREP, EQCRP90,
    EQCRP90RP), surviving (EQCSR90, EQCSUR) and the new-shell index, plus the
    by-vintage future-year arrays and HEATINGTYPEPURCH."""
    Yc = int(s["curcalyr"])
    cleupt, typeupt, typect = s["rtcleupt"], s["rttyeupt"], s["rttypect"]
    lo, hi = int(cleupt[EU]) + 1, int(cleupt[EU + 1])
    cacfact = f32(0.1)
    max_cenac_pen = f32(0.90)

    # EQCPN90 is a local of RCLADD that persists between calls in the build
    pn = s.get("_eqcpn90")
    if pn is None:
        pn = s["_eqcpn90"] = FArray.zeros([(RECSYEAR, ENDYR), (1, 40), (1, NBLDG), (1, 11)])
    SA = {}

    eqcsr90, eqcsur, rp90rp = s["eqcsr90"], s["eqcsur"], s["eqcrp90rp"]
    eqcadd, eqcrep, eqcrp90 = s["eqcadd"], s["eqcrep"], s["eqcrp90"]
    hdr = s["hdr"]

    for r in range(1, NDIV + 1):
        for b in range(1, NBLDG + 1):
            for reccl in range(lo, hi + 1):
                eqc = int(s["rtcleqcl"][reccl])
                eqcsr90[Yc, reccl, b, r] = f32(0.0)
                eqcsur[Yc, reccl, b, r] = f32(0.0)
                SA[eqc, b, r] = f32(0.0)
                rp90rp[Yc, reccl, b, r] = f32(0.0)

    # equipment added this year
    reccl_cac = reccl_ehp = 0  # leftovers across loops, as in the Fortran
    for r in range(1, NDIV + 1):
        for b in range(1, NBLDG + 1):
            sumhp = f32(0.0)
            for reccl in range(lo, hi + 1):
                eqc = int(s["rtcleqcl"][reccl])
                name = _text(s["rtclname"][reccl])
                if name == "ROOM_AIR":
                    eqcadd[Yc, reccl, b, r] = s["hseadd"][Yc, b, r] * s["racsat"][b, r] * s["racunits"][b, r]
                elif name == "CENT_AIR":
                    reccl_cac = eqc + int(cleupt[EU])
                    eqcadd[Yc, reccl, b, r] = s["hseadd"][Yc, b, r] * s["cacsat"][b, r]
                else:
                    # not room or central AC, so a heat pump: copy the heating subroutine's figure
                    if name == "ELEC_HP":
                        reccl_ehp = eqc + int(cleupt[EU])
                    reccl_hhp = int(s["rtclpntr"][reccl])
                    eqcadd[Yc, reccl, b, r] = eqcadd[Yc, reccl_hhp, b, r]
                    sumhp = sumhp + eqcadd[Yc, reccl, b, r]
            if eqcadd[Yc, reccl_cac, b, r] <= sumhp:
                eqcadd[Yc, reccl_cac, b, r] = eqcadd[Yc, reccl_ehp, b, r] * cacfact
            else:
                eqcadd[Yc, reccl_cac, b, r] = eqcadd[Yc, reccl_cac, b, r] - sumhp

    # surviving RECS-year equipment and replacements of replacements
    for r in range(1, NDIV + 1):
        for b in range(1, NBLDG + 1):
            for reccl in range(lo, hi + 1):
                eqc = int(s["rtcleqcl"][reccl])
                if s["rtclpntr"][reccl] > 0:
                    reccl_hhp = int(s["rtclpntr"][reccl])
                    eqcsr90[Yc, reccl, b, r] = eqcsr90[Yc, reccl_hhp, b, r]
                    eqcsur[Yc, reccl, b, r] = eqcsur[Yc, reccl_hhp, b, r]
                    continue
                if Yc == RECSYEAR + 1:
                    s["eqcnd90"][Yc, reccl, b, r] = s["eqcese"][RECSYEAR, reccl, b, r] * hdr[b]
                else:
                    s["eqcnd90"][Yc, reccl, b, r] = s["eqcnd90"][Yc - 1, reccl, b, r] * hdr[b]
                nd = s["eqcnd90"][Yc, reccl, b, r]

                if b == 1 and _text(s["rtclname"][reccl]) == "CENT_AIR":
                    # reads last call's EQCPN90 for this year (static storage)
                    if (pn[Yc, reccl, b, r] / s["eh"][Yc, b, r]) >= max_cenac_pen:
                        pn[Yc, reccl, b, r] = nd - nd
                    else:
                        pn[Yc, reccl, b, r] = nd * (f32(1.0) + s["cacpr"][r]) - nd
                else:
                    pn[Yc, reccl, b, r] = f32(0.0)

                n0 = Yc - RECSYEAR
                if Yc == RECSYEAR + 1:
                    eqcrp90[Yc, reccl, b, r] = (s["eqcret"][Yc, reccl] * s["eqcese"][RECSYEAR, reccl, b, r]
                                                * powi(hdr[b], n0))
                else:
                    eqcrp90[Yc, reccl, b, r] = ((s["eqcret"][Yc, reccl] - s["eqcret"][Yc - 1, reccl])
                                                * s["eqcese"][RECSYEAR, reccl, b, r] * powi(hdr[b], n0))

                alpha, k, lam = s["rtalpha"][reccl], s["rtk"][reccl], s["rtlambda"][reccl]
                if Yc > RECSYEAR + 1:
                    for y in range(RECSYEAR + 1, Yc):
                        temp = Yc - y
                        esr = svrte(alpha, temp - 1, k, lam) - svrte(alpha, temp, k, lam)
                        hpw = powi(hdr[b], temp)
                        rp90rp[Yc, reccl, b, r] = (rp90rp[Yc, reccl, b, r] +
                                                   (eqcrp90[y, reccl, b, r] * esr * hpw
                                                    + rp90rp[y, reccl, b, r] * esr * hpw
                                                    + pn[y, reccl, b, r] * esr * hpw))
                else:
                    rp90rp[Yc, reccl, b, r] = pn[Yc, reccl, b, r]

                if Yc > RECSYEAR + 1:
                    rp90rp[Yc, reccl, b, r] = rp90rp[Yc, reccl, b, r] + pn[Yc, reccl, b, r]

                if Yc > RECSYEAR + 1:
                    for y in range(RECSYEAR + 1, Yc):
                        hsr = powi(hdr[b], Yc - y)
                        esr = svrte(alpha, Yc - y, k, lam)
                        eqcsr90[Yc, reccl, b, r] = (eqcsr90[Yc, reccl, b, r] + eqcrp90[y, reccl, b, r]
                                                    * esr * hsr + rp90rp[y, reccl, b, r] * esr * hsr
                                                    + pn[y, reccl, b, r] * esr * hsr)
                        # SA is the surviving houses; replacements = SA - surviving equipment
                        SA[eqc, b, r] = SA[eqc, b, r] + eqcadd[y, reccl, b, r] * hsr
                        eqcsur[Yc, reccl, b, r] = (eqcsur[Yc, reccl, b, r] +
                                                   ((eqcadd[y, reccl, b, r] + eqcrep[y, reccl, b, r]) * (hsr * esr)))

    # replacements for the current year
    for r in range(1, NDIV + 1):
        for b in range(1, NBLDG + 1):
            for reccl in range(lo, hi + 1):
                eqc = int(s["rtcleqcl"][reccl])
                if s["rtclpntr"][reccl] > 0:
                    reccl_hhp = int(s["rtclpntr"][reccl])
                    eqcrp90[Yc, reccl, b, r] = eqcrp90[Yc, reccl_hhp, b, r]
                    rp90rp[Yc, reccl, b, r] = rp90rp[Yc, reccl_hhp, b, r]
                    if b == 1:
                        s["oeqcrp90"][Yc, reccl, b, r] = eqcrp90[Yc, reccl_hhp, b, r]
                        s["oeqcrp90r"][Yc, reccl, b, r] = rp90rp[Yc, reccl_hhp, b, r]
                    eqcrep[Yc, reccl, b, r] = eqcrep[Yc, reccl_hhp, b, r]
                    if b == 1:
                        s["oeqcrep"][Yc, reccl, b, r] = eqcrep[Yc, reccl_hhp, b, r]
                else:
                    if b == 1:
                        s["oeqcrp90"][Yc, reccl, b, r] = eqcrp90[Yc, reccl, b, r]
                        s["oeqcrp90r"][Yc, reccl, b, r] = rp90rp[Yc, reccl, b, r]
                    eqcrep[Yc, reccl, b, r] = SA[eqc, b, r] - eqcsur[Yc, reccl, b, r]
                    if b == 1:
                        s["oeqcrep"][Yc, reccl, b, r] = SA[eqc, b, r] - eqcsur[Yc, reccl, b, r]

    # equipment by vintage for average stock accounting
    for b in range(1, NBLDG + 1):
        for r in range(1, NDIV + 1):
            for reccl in range(lo, hi + 1):
                alpha, k, lam = s["rtalpha"][reccl], s["rtk"][reccl], s["rtlambda"][reccl]
                for y in range(Yc, ENDYR + 1):
                    temp = y - Yc
                    hsr = powi(hdr[b], temp)
                    esr = svrte(alpha, temp, k, lam)
                    s["eqr90fut"][Yc, y, reccl, b, r] = eqcrp90[Yc, reccl, b, r] * esr * hsr
                    s["eqr90rpfut"][Yc, y, reccl, b, r] = rp90rp[Yc, reccl, b, r] * esr * hsr
                    s["eqrepfut"][Yc, y, reccl, b, r] = eqcrep[Yc, reccl, b, r] * esr * hsr
                    s["eqaddfut"][Yc, y, reccl, b, r] = eqcadd[Yc, reccl, b, r] * esr * hsr

    # new shell index
    ncshell = s["ncshell"]
    for r in range(1, NDIV + 1):
        for b in range(1, NBLDG + 1):
            ncshell[Yc, r, b] = f32(0.0)
    newshellwtc = {(b, r): f32(0.0) for b in range(1, NBLDG + 1) for r in range(1, NDIV + 1)}
    newaddwtc = dict(newshellwtc)
    anumc = {(r, b): f32(0.0) for r in range(1, NDIV + 1) for b in range(1, NBLDG + 1)}
    adenc = dict(anumc)

    for r in range(1, NDIV + 1):
        for b in range(1, NBLDG + 1):
            # starts at the second class, skipping the first (EIA's choice)
            for reccl in range(int(cleupt[EU]) + 2, hi + 1):
                eqc = int(s["rtcleqcl"][reccl])
                newshellwtc[b, r] = newshellwtc[b, r] + eqcadd[Yc, reccl, b, r] * s["cshell"][Yc, eqc, b, r]
                newaddwtc[b, r] = newaddwtc[b, r] + eqcadd[Yc, reccl, b, r]

    for r in range(1, NDIV + 1):
        for b in range(1, NBLDG + 1):
            if newaddwtc[b, r] > 0.0:
                ncshell[Yc, r, b] = newshellwtc[b, r] / newaddwtc[b, r]
            else:
                ncshell[Yc, r, b] = f32(1.0)

    ex, el = s["exsqrfoot"], s["elastic"]
    for d in range(1, NDIV + 1):
        for b in range(1, NBLDG + 1):
            s["exsqftadj"][Yc, b, d, 3] = (el[3, d] * ((ex[Yc, b, d] - ex[RECSYEAR, b, d]) / ex[RECSYEAR, b, d])
                                           * ncshell[Yc, d, b]) + f32(1)
            s["exsqftadj"][Yc, b, d, 4] = (el[4, d] * ((ex[Yc, b, d] - ex[RECSYEAR, b, d]) / ex[RECSYEAR, b, d])
                                           * ncshell[Yc, d, b]) + f32(1)

    # average new cooling shell index
    for r in range(1, NDIV + 1):
        for b in range(1, NBLDG + 1):
            for reccl in range(lo, hi + 1):
                if Yc > RECSYEAR + 1:
                    for y in range(RECSYEAR + 1, Yc):
                        anumc[r, b] = anumc[r, b] + (ncshell[y, r, b] * eqcadd[y, reccl, b, r])
                        adenc[r, b] = adenc[r, b] + eqcadd[y, reccl, b, r]

    acshell = s["acshell"]
    for r in range(1, NDIV + 1):
        for b in range(1, NBLDG + 1):
            if adenc[r, b] <= 0:
                acshell[Yc, r, b] = acshell[Yc - 1, r, b]
            else:
                acshell[Yc, r, b] = anumc[r, b] / adenc[r, b]
            if acshell[Yc, r, b] < s["limit"]:
                acshell[Yc, r, b] = s["limit"]
            if Yc <= RECSYEAR + 1:
                acshell[Yc, r, b] = ncshell[Yc, r, b]

    # aggregate cooling systems for investment analysis
    htp = s["heatingtypepurch"]
    ns, rs = s["neqtshr"], s["reqtshr"]
    for b in range(1, NBLDG + 1):
        for r in range(1, NDIV + 1):
            typ = int(typect[EU])
            for recty in range(int(typeupt[EU]) + 1, int(typeupt[EU + 1]) + 1):
                if Yc >= s["rtinityr"][recty] and Yc <= s["rtlastyr"][recty]:
                    if s["rtcendiv"][recty] == r:
                        typ += 1
                        eqt = int(s["rteqtype"][recty])
                        eqc = int(s["rttyeqcl"][recty])
                        reccl = int(cleupt[EU]) + eqc
                        if reccl == 11:  # ROOM_AIR is record 11 (10 heating classes + 1)
                            htp[Yc, typ, b, r, 1] = ns[Yc, typ, b, r] * eqcadd[Yc, reccl, b, r]
                        else:
                            htp[Yc, typ, b, r, 1] = s["neqtshrc"][Yc, eqt, b, r] * eqcadd[Yc, reccl, b, r]
                        htp[Yc, typ, b, r, 2] = (ns[Yc, typ, b, r] * (eqcrep[Yc, reccl, b, r] + rp90rp[Yc, reccl, b, r])
                                                 + rs[Yc, typ, b, r] * eqcrp90[Yc, reccl, b, r])


# ----------------------------------------------------------------------------
# RCLCON
# ----------------------------------------------------------------------------
def rclcon(s: dict) -> None:
    """RCLCON: unit energy consumption by vintage, average efficiency, and cooling
    consumption COOLCN (plus the weighted/intensity versions and the driver)."""
    Y = int(s["curcalyr"])
    Y1 = int(s["curiyr"])
    eupr = 2
    alpha = f32(-.15)
    ef1, ef2, ef3 = f32(.5), f32(.35), f32(.15)
    alpha2 = f32(-.15)
    cleupt = s["rtcleupt"]
    lo, hi = int(cleupt[EU]) + 1, int(cleupt[EU + 1])
    nclfl = int(s["nclfl"])

    _prices_elec(s, eupr)
    cddfact = {d: _cddfact(s, d) for d in range(1, NDIV + 1)}

    if Y >= RECSYEAR + 1:
        for reccl in range(lo, hi + 1):
            s["rtbaseff"][Y, reccl] = s["stkeff"][Y, reccl]

    rb = s["rtbaseff"]
    r90, r90rp = s["eqr90fut"], s["eqr90rpfut"]
    addf, repf = s["eqaddfut"], s["eqrepfut"]
    S = 0
    eqcuec = s["eqcuec"]
    for d in range(1, NDIV + 1):
        for b in range(1, NBLDG + 1):
            for reccl in range(lo, hi + 1):
                eqc = int(s["rtcleqcl"][reccl])
                # S picks the square-footage elasticity: 3 room and central AC, 4 heat pumps
                S = 3 if eqc < 3 else 4
                u = eqcuec[d, reccl, b]
                ratio = rb[RECSYEAR, reccl] / rb[Y, reccl]
                s["eqcsuec"][Y, reccl, b, d] = u * s["exsqftadj"][Y, b, d, S] * ratio
                s["eqcsiuec"][Y, reccl, b, d] = u * ratio
                if s["wteqceffn"][Y, reccl, b, d] > 0.0:
                    s["eqcnuec"][Y, reccl, b, d] = u * s["wteqceffn"][Y, reccl, b, d] * rb[RECSYEAR, reccl]
                    s["eqcniuec"][Y, reccl, b, d] = u * s["wteqceffn"][Y, reccl, b, d] * rb[RECSYEAR, reccl]
                else:
                    s["eqcnuec"][Y, reccl, b, d] = u
                    s["eqcniuec"][Y, reccl, b, d] = u

                if s["wteqceffhv"][Y, reccl, b, d] > 0.0:
                    s["eqchvuec"][Y, reccl, b, d] = (u * s["wteqceffhv"][Y, reccl, b, d] * rb[RECSYEAR, reccl]
                                                     * s["wteqcsqfhv"][Y, reccl, b, d])
                    s["eqchviuec"][Y, reccl, b, d] = u * s["wteqceffhv"][Y, reccl, b, d] * rb[RECSYEAR, reccl]
                else:
                    s["eqchvuec"][Y, reccl, b, d] = u * s["wteqcsqfhv"][Y, reccl, b, d]
                    s["eqchviuec"][Y, reccl, b, d] = u

                if s["wteqceffr"][Y, reccl, b, d] > 0.0:
                    s["eqcruec"][Y, reccl, b, d] = (u * s["wteqceffr"][Y, reccl, b, d] * rb[RECSYEAR, reccl]
                                                    * s["exsqftadj"][Y, b, d, S])
                    s["eqcriuec"][Y, reccl, b, d] = u * s["wteqceffr"][Y, reccl, b, d] * rb[RECSYEAR, reccl]
                else:
                    s["eqcruec"][Y, reccl, b, d] = u
                    s["eqcriuec"][Y, reccl, b, d] = u

                if Y == RECSYEAR + 1:
                    s["eqcauec"][Y, reccl, b, d] = s["eqcnuec"][Y, reccl, b, d]
                    s["eqcahvuec"][Y, reccl, b, d] = s["eqchvuec"][Y, reccl, b, d]
                else:
                    temp = temp1 = temp2 = f32(0.0)
                    for y in range(RECSYEAR, Y):
                        temp = temp + r90[y, Y, reccl, b, d] + r90rp[y, Y, reccl, b, d]
                        temp1 = temp1 + addf[y, Y, reccl, b, d] + repf[y, Y, reccl, b, d]
                        temp2 = (temp2 + r90[y, Y, reccl, b, d] + r90rp[y, Y, reccl, b, d]
                                 + addf[y, Y, reccl, b, d] + repf[y, Y, reccl, b, d])
                    auec = s["eqcauec"]
                    if eqc == 1:
                        if temp2 <= 0.0:
                            auec[Y, reccl, b, d] = s["eqcnuec"][Y, reccl, b, d]
                        else:
                            auec[Y, reccl, b, d] = f32(0.0)
                            for y in range(RECSYEAR, Y):
                                auec[Y, reccl, b, d] = auec[Y, reccl, b, d] + (
                                    (r90[y, Y, reccl, b, d] * s["eqcruec"][y, reccl, b, d])
                                    + (addf[y, Y, reccl, b, d] + repf[y, Y, reccl, b, d]) * s["eqcnuec"][y, reccl, b, d]
                                    + r90rp[y, Y, reccl, b, d] * s["eqcniuec"][y, reccl, b, d]) / temp2
                    else:
                        if temp <= 0.0:
                            auec[Y, reccl, b, d] = s["eqcnuec"][Y, reccl, b, d]
                        else:
                            auec[Y, reccl, b, d] = f32(0.0)
                            for y in range(RECSYEAR, Y):
                                auec[Y, reccl, b, d] = auec[Y, reccl, b, d] + (
                                    r90[y, Y, reccl, b, d] * s["eqcruec"][y, reccl, b, d]
                                    + r90rp[y, Y, reccl, b, d] * s["eqcniuec"][y, reccl, b, d]) / temp

                    if eqc > 1:
                        if temp1 <= 0.0:
                            s["eqcahvuec"][Y, reccl, b, d] = s["eqchvuec"][Y, reccl, b, d]
                        else:
                            s["eqcahvuec"][Y, reccl, b, d] = f32(0.0)
                            for y in range(RECSYEAR, Y):
                                s["eqcahvuec"][Y, reccl, b, d] = s["eqcahvuec"][Y, reccl, b, d] + (
                                    addf[y, Y, reccl, b, d] * s["eqchvuec"][y, reccl, b, d]
                                    + repf[y, Y, reccl, b, d] * s["eqcnuec"][y, reccl, b, d]) / temp1

    # average equipment efficiency
    wa = s["wteqceffa"]
    for b in range(1, NBLDG + 1):
        for d in range(1, NDIV + 1):
            for reccl in range(lo, hi + 1):
                eqc = int(s["rtcleqcl"][reccl])
                if Y == RECSYEAR + 1:
                    wa[RECSYEAR + 1, reccl, b, d] = s["wteqceffn"][RECSYEAR + 1, reccl, b, d]
                else:
                    temp = f32(0.0)
                    for y in range(RECSYEAR, Y):
                        temp = (temp + r90[y, Y, reccl, b, d] + addf[y, Y, reccl, b, d]
                                + repf[y, Y, reccl, b, d] + r90rp[y, Y, reccl, b, d])
                    if temp > 0.0:
                        wa[Y, reccl, b, d] = f32(0.0)
                        for y in range(RECSYEAR, Y):
                            if eqc == 1:
                                wa[Y, reccl, b, d] = wa[Y, reccl, b, d] + (
                                    (r90[y, Y, reccl, b, d] * s["wteqceffr"][y, reccl, b, d])
                                    + ((addf[y, Y, reccl, b, d] + repf[y, Y, reccl, b, d] + r90rp[y, Y, reccl, b, d])
                                       * s["wteqceffn"][y, reccl, b, d])) / temp
                            else:
                                wa[Y, reccl, b, d] = wa[Y, reccl, b, d] + (
                                    r90[y, Y, reccl, b, d] * s["wteqceffr"][y, reccl, b, d]
                                    + addf[y, Y, reccl, b, d] * s["wteqceffhv"][y, reccl, b, d]
                                    + (repf[y, Y, reccl, b, d] + r90rp[y, Y, reccl, b, d])
                                    * s["wteqceffn"][y, reccl, b, d]) / temp
                    else:
                        wa[Y, reccl, b, d] = s["wteqceffn"][Y, reccl, b, d]

    # initialize consumption variables
    COOLCN, COOLCNWT, COOLCNIN, DRIVER = s["coolcn"], s["coolcnwt"], s["coolcnin"], s["driver"]
    for fc in range(1, nclfl + 1):
        for d in range(1, NDIV + 1):
            COOLCN[Y1, fc, d] = f32(0.0)
            for b in range(1, NBLDG + 1):
                DRIVER[Y1, fc, d, b] = f32(0.0)
                COOLCNWT[Y1, fc, d, b] = f32(0.0)
                COOLCNIN[Y1, fc, d, b] = f32(0.0)

    # (EIA also finds the GEO_HP and ELEC_HP records here; neither is used afterwards)

    ese, add, rp90rp, rp90 = s["eqcese"], s["eqcadd"], s["eqcrp90rp"], s["eqcrp90"]
    sr90, rep, sur = s["eqcsr90"], s["eqcrep"], s["eqcsur"]
    ecs, ncs, acs = s["ecshell"], s["ncshell"], s["acshell"]
    exs = s["exsqftadj"]

    for d in range(1, NDIV + 1):
        for b in range(1, NBLDG + 1):
            for reccl in range(lo, hi + 1):
                eqc = int(s["rtcleqcl"][reccl])
                f = int(s["rtfuel"][reccl])
                fcon = int(s["fclcon"][f])
                s["eqceqcn"][Y1, reccl, b, d] = f32(0.0)
                cdd = cddfact[d]
                e0 = ecs[RECSYEAR, d, b]
                er = ecs[Y, d, b] / e0
                nr = ncs[Y, d, b] / e0
                if Y == RECSYEAR + 1:
                    sel = rselast(s, f, d, alpha, ef1, ef2, ef3, eupr)
                    # S below is the value left over from the UEC loop above
                    add_uec = s["eqcnuec"][Y, reccl, b, d] if eqc == 1 else s["eqchvuec"][Y, reccl, b, d]
                    add_iuec = s["eqcnuec"][Y, reccl, b, d] if eqc == 1 else s["eqchviuec"][Y, reccl, b, d]
                    base = ((ese[Y, reccl, b, d] * s["eqcsuec"][Y, reccl, b, d] * er)
                            + (add[Y, reccl, b, d] * add_uec * nr)
                            + (rp90rp[Y, reccl, b, d] * s["eqcniuec"][Y, reccl, b, d] * exs[Y, b, d, S] * er)
                            + (rp90[Y, reccl, b, d] * s["eqcruec"][Y, reccl, b, d] * er))
                    COOLCN[Y1, fcon, d] = COOLCN[Y1, fcon, d] + cdd * (base * sel)
                    COOLCNWT[Y1, fcon, d, b] = COOLCNWT[Y1, fcon, d, b] + cdd * (base * sel)
                    COOLCNIN[Y1, fcon, d, b] = COOLCNIN[Y1, fcon, d, b] + (
                        (ese[Y, reccl, b, d] * s["eqcsiuec"][Y, reccl, b, d] * er)
                        + (add[Y, reccl, b, d] * add_iuec * nr)
                        + (rp90rp[Y, reccl, b, d] * s["eqcniuec"][Y, reccl, b, d] * er)
                        + (rp90[Y, reccl, b, d] * s["eqcriuec"][Y, reccl, b, d] * er))
                    DRIVER[Y1, fcon, d, b] = DRIVER[Y1, fcon, d, b] + (
                        ese[Y, reccl, b, d] + add[Y, reccl, b, d] + rp90rp[Y, reccl, b, d] + rp90[Y, reccl, b, d])
                    # EQCEQCN lists its terms in a different order from COOLCN
                    s["eqceqcn"][Y1, reccl, b, d] = cdd * (
                        ((ese[Y, reccl, b, d] * s["eqcsuec"][Y, reccl, b, d] * er)
                         + (rp90rp[Y, reccl, b, d] * s["eqcniuec"][Y, reccl, b, d] * exs[Y, b, d, S] * er)
                         + (add[Y, reccl, b, d] * add_uec * nr)
                         + (rp90[Y, reccl, b, d] * s["eqcruec"][Y, reccl, b, d] * er)) * sel)
                else:
                    alpha = f32(-0.30) if f == 4 else f32(-0.15)
                    p = f32(1.0) + alpha2
                    wb = rb[RECSYEAR, reccl]
                    rba = (wb * s["wteqceffa"][Y, reccl, b, d]) ** alpha2
                    rbr = (wb * s["wteqceffr"][Y, reccl, b, d]) ** alpha2
                    rbn = (wb * s["wteqceffn"][Y, reccl, b, d]) ** alpha2
                    sel = rselast(s, f, d, alpha, ef1, ef2, ef3, eupr)
                    ep = (ecs[Y, d, b] / e0) ** p
                    npw = (ncs[Y, d, b] / e0) ** p
                    ap = (acs[Y, d, b] / e0) ** p
                    ar = acs[Y, d, b] / e0
                    if eqc == 1:
                        add_uec, add_iuec = s["eqcnuec"][Y, reccl, b, d], s["eqcniuec"][Y, reccl, b, d]
                        sur_uec = s["eqcauec"][Y, reccl, b, d]
                    else:
                        add_uec, add_iuec = s["eqchvuec"][Y, reccl, b, d], s["eqchviuec"][Y, reccl, b, d]
                        sur_uec = s["eqcahvuec"][Y, reccl, b, d]

                    def terms(suec):
                        return ((ese[Y, reccl, b, d] * suec * ep)
                                + (add[Y, reccl, b, d] * add_uec * npw) * rbn
                                + (rp90[Y, reccl, b, d] * s["eqcruec"][Y, reccl, b, d] * ep) * rbr
                                + (rp90rp[Y, reccl, b, d] * s["eqcniuec"][Y, reccl, b, d] * exs[Y, b, d, S] * ep) * rbn
                                + (sr90[Y, reccl, b, d] * s["eqcauec"][Y, reccl, b, d] * ep) * rba
                                + (rep[Y, reccl, b, d] * s["eqcnuec"][Y, reccl, b, d] * ap) * rbn
                                + (sur[Y, reccl, b, d] * sur_uec * ap) * rba)

                    # EIA's COOLCNWT uses the intensity UEC for room AC only
                    wt_uec = s["eqcsiuec"][Y, reccl, b, d] if eqc == 1 else s["eqcsuec"][Y, reccl, b, d]
                    COOLCN[Y1, fcon, d] = COOLCN[Y1, fcon, d] + cdd * (terms(s["eqcsuec"][Y, reccl, b, d]) * sel)
                    COOLCNWT[Y1, fcon, d, b] = COOLCNWT[Y1, fcon, d, b] + cdd * (terms(wt_uec) * sel)
                    COOLCNIN[Y1, fcon, d, b] = COOLCNIN[Y1, fcon, d, b] + (
                        (ese[Y, reccl, b, d] * s["eqcsiuec"][Y, reccl, b, d] * er)
                        + (add[Y, reccl, b, d] * add_iuec * nr)
                        + (rp90[Y, reccl, b, d] * s["eqcriuec"][Y, reccl, b, d] * er)
                        + (rp90rp[Y, reccl, b, d] * s["eqcniuec"][Y, reccl, b, d] * er)
                        + (sr90[Y, reccl, b, d] * s["eqcauec"][Y, reccl, b, d] * er)
                        + (rep[Y, reccl, b, d] * s["eqcniuec"][Y, reccl, b, d] * ar)
                        + (sur[Y, reccl, b, d] * sur_uec * ar))
                    DRIVER[Y1, fcon, d, b] = DRIVER[Y1, fcon, d, b] + (
                        ese[Y, reccl, b, d] + add[Y, reccl, b, d] + rp90rp[Y, reccl, b, d] + rp90[Y, reccl, b, d]
                        + sr90[Y, reccl, b, d] + rep[Y, reccl, b, d] + sur[Y, reccl, b, d])
                    s["eqceqcn"][Y1, reccl, b, d] = cdd * (terms(s["eqcsuec"][Y, reccl, b, d]) * sel)

    for r in range(1, NDIV + 1):
        for fc in range(1, nclfl + 1):
            for b in range(1, NBLDG + 1):
                if DRIVER[Y1, fc, r, b] > 0:
                    COOLCNIN[Y1, fc, r, b] = COOLCNIN[Y1, fc, r, b] / DRIVER[Y1, fc, r, b]
