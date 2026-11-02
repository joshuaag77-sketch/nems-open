"""Clothes washers and dishwashers (resd.f): RCWTEC, RCWADD, RCWCON, RDWTEC,
RDWADD and RDWCON.

TEC routines choose technologies (logit weights, new and replacement shares,
share-weighted efficiency). ADD routines count equipment added and replaced, and
vintage it into the future-year arrays. CON routines turn that into unit energy
consumption and energy use. Writes to AppBetaData.txt (unit 661) are skipped.

Inputs the oracle dump cannot hold, and what the port does about them:
- PELRSOUT is read once by the TEC and CON routines, to set PRICES(4,r,year).
- LEAPYR is set in the main RESD body (not dumped); it depends only on the year.
- COSTTRSW is a PARAMETER (rtek include), 0.
- DECAY is a static local set on the first iteration of each year; it depends only
  on two constants, so it is recomputed here.
"""

import numpy as np

from nems_open.residential.common import BASEYR, LASTSTEOYR, MNUMBLDG, NUM_DIV, RECSYEAR, expf, f32, powf, powi
from nems_open.residential.helpers import STOCK_FUTURES, eqcost, rselast, svrte, vintage_future

ENDYR = 2050
COSTTRSW = 0  # PARAMETER in the rtek include
EU_CW, EUPR_CW = 3, 5
EU_DW, EUPR_DW = 4, 9


# ----------------------------------------------------------------------------
# pieces shared by the technology-choice routines
# ----------------------------------------------------------------------------

def _decay(s: dict):
    """DECAY = annuity factor for the life-cycle cost. EIA sets it only when
    CURITR = 1 and keeps it in a static local; the inputs never change."""
    rate, tenure = f32(s["resdiscountrate"]), f32(s["tenure"])
    return f32(f32(f32(1) - powf(f32(f32(1) + rate), -tenure)) / rate)


def _map_electricity_price(s: dict, eupr: int) -> None:
    """PRICES(4,R,CurCalYr): this end use's electricity price in menu dollars."""
    Y, Y1 = int(s["curcalyr"]), int(s["curiyr"])
    gdp, pel, P = s["mc_jpgdp"], s["pelrsout"], s["prices"]
    for r in range(1, NUM_DIV + 1):
        P[4, r, Y] = pel[r, Y1, eupr] * f32(gdp[int(s["rtekdollaryr"]) - BASEYR + 1] / gdp[-2])


def _beta1dr(s: dict, recty: int, r: int) -> None:
    """BETA1DR(RECTY): the capital-cost coefficient eased when electricity is
    dearer than in the RECS year. HRDRATE, ELIGBLE and HRDADJ are shared scalars
    that keep whatever the last record wrote."""
    Y = int(s["curcalyr"])
    P, b1, b2 = s["prices"], s["rtecbta1"], s["rtecbta2"]
    alpha1 = f32(s["alpha1"])
    if Y > 2008 and P[4, r, Y] > P[4, r, RECSYEAR]:
        s["hrdrate"] = f32(b1[recty] / b2[recty])
        s["eligble"] = f32(s["hrdrate"] - f32(0.07))
        if s["eligble"] > 0.0:
            s["hrdadj"] = f32(s["eligble"] * powf(f32(P[4, r, Y] / P[4, r, RECSYEAR]), alpha1))
            s["beta1dr"][recty] = f32(s["hrdadj"] + f32(0.07)) * b2[recty]
        else:
            s["beta1dr"][recty] = b1[recty]
    else:
        s["beta1dr"][recty] = b1[recty]


def _valid(s: dict, recty: int, r: int) -> bool:
    Y = int(s["curcalyr"])
    return s["rtinityr"][recty] <= Y <= s["rtlastyr"][recty] and int(s["rtcendiv"][recty]) == r


def _capital(s: dict, recty: int):
    Y = int(s["curcalyr"])
    return eqcost(s, recty, Y, "CAP") if COSTTRSW == 1 else s["rteqcost"][recty]


def _rselast(s: dict, f, d, alpha, ef1, ef2, ef3, eupr):
    """RSELAST. Both consumption routines call it with ALPHA = 0, and x ** 0 is
    exactly 1 for any price ratio, so the (undumped) PELRSOUT history is not needed."""
    if f32(alpha) == 0.0:
        return f32(1.0)
    return rselast(s, f, d, alpha, ef1, ef2, ef3, eupr)


def _leapyr(year: int):
    """LEAPYR from the main RESD body: 366/365 in leap years up to the last STEO year."""
    if year % 4 == 0 and year <= LASTSTEOYR:
        return f32(f32(366.0) / f32(365.0))
    return f32(f32(365.0) / f32(365.0))


# ----------------------------------------------------------------------------
# clothes washers
# ----------------------------------------------------------------------------

def rcwtec(s: dict) -> None:
    """RCWTEC: clothes washer choice. Top-load types (EQT <= 3) share TCW_SHR of
    new sales and front-load types FCW_SHR, each split by logit weight.
    Writes to AppBetaData.txt are skipped."""
    EU, EUPR = EU_CW, EUPR_CW
    Y = int(s["curcalyr"])
    s["alpha1"] = f32(-0.50)
    BASEMEF = f32(1.57)  # RECS base-year top-load MEF
    BASEUSE = f32(4.0125)

    _map_electricity_price(s, EUPR)
    DECAY = _decay(s)

    P, LFCY = s["prices"], s["lfcy"]
    eupt, tyeupt, typect, cleqcl = s["rtcleupt"], s["rttyeupt"], s["rttypect"], s["rtcleqcl"]
    NEQTSHR, REQTSHR = s["neqtshr"], s["reqtshr"]
    WTN, WTR = s["wteqceffn"], s["wteqceffr"]
    EQWTN, EQWTR, TOTEWTN, TOTEWTR = {}, {}, {}, {}
    TCWSHR, FCWSHR = {}, {}

    with np.errstate(all="ignore"):
        for r in range(1, NUM_DIV + 1):
            for b in range(1, MNUMBLDG + 1):
                s["ncwload"][Y, r, b] = 0.0
                for reccl in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                    eqc = int(cleqcl[reccl])
                    TOTEWTN[eqc, b, r] = f32(0.0)
                    TOTEWTR[eqc, b, r] = f32(0.0)
                    WTN[Y, reccl, b, r] = 0.0
                    WTR[Y, reccl, b, r] = 0.0

        # Operating cost, life-cycle cost and logit weights.
        # RTEFFAC is computed in EIA's code but never used for washers, so it is left out.
        for r in range(1, NUM_DIV + 1):
            for b in range(1, MNUMBLDG + 1):
                for recty in range(int(tyeupt[EU]) + 1, int(tyeupt[EU + 1]) + 1):
                    if not _valid(s, recty, r):
                        continue
                    eqt, eqc = int(s["rteqtype"][recty]), int(s["rttyeqcl"][recty])
                    reccl = int(eupt[EU]) + eqc
                    f = int(s["rtfuel"][reccl])
                    CAPITAL = _capital(s, recty)
                    # Both operating costs are identical for washers (EIA copy and paste).
                    OPCOST1 = f32(P[f, r, Y] * f32(BASEUSE * f32(BASEMEF / s["cwmef"][recty])))
                    OPCOST2 = f32(P[f, r, Y] * f32(BASEUSE * f32(BASEMEF / s["cwmef"][recty])))
                    _beta1dr(s, recty, r)
                    LFCY[eqt, b, r, 1] = CAPITAL + f32(OPCOST1 * DECAY)
                    LFCY[eqt, b, r, 2] = CAPITAL + f32(OPCOST2 * DECAY)
                    bias, b1, b2, b3 = s["rtecbias"][recty], s["beta1dr"][recty], s["rtecbta2"][recty], s["rtecbta3"][recty]
                    EQWTN[eqt, b, r] = expf(f32(f32(f32(bias + f32(b1 * CAPITAL)) + f32(b2 * OPCOST2))
                                                      + f32(b3 * LFCY[eqt, b, r, 2])))
                    TOTEWTN[eqc, b, r] = f32(TOTEWTN[eqc, b, r] + EQWTN[eqt, b, r])
                    EQWTR[eqt, b, r] = expf(f32(f32(f32(bias + f32(b1 * CAPITAL)) + f32(b2 * OPCOST1))
                                                      + f32(b3 * LFCY[eqt, b, r, 1])))
                    TOTEWTR[eqc, b, r] = f32(TOTEWTR[eqc, b, r] + EQWTR[eqt, b, r])

        # Total top-load and front-load weights
        for r in range(1, NUM_DIV + 1):
            for b in range(1, MNUMBLDG + 1):
                TCWSHR[b, r] = f32(0.0)
                FCWSHR[b, r] = f32(0.0)
                for recty in range(int(tyeupt[EU]) + 1, int(tyeupt[EU + 1]) + 1):
                    if not _valid(s, recty, r):
                        continue
                    eqt = int(s["rteqtype"][recty])
                    if eqt <= 3:  # CL_WASH_T records in RSMEQP
                        TCWSHR[b, r] = f32(TCWSHR[b, r] + EQWTN[eqt, b, r])
                    else:  # CL_WASH_F
                        FCWSHR[b, r] = f32(FCWSHR[b, r] + EQWTN[eqt, b, r])

        # Market shares and share-weighted efficiency
        for r in range(1, NUM_DIV + 1):
            for b in range(1, MNUMBLDG + 1):
                TYPE = int(typect[EU])
                for recty in range(int(tyeupt[EU]) + 1, int(tyeupt[EU + 1]) + 1):
                    if not _valid(s, recty, r):
                        continue
                    TYPE += 1
                    eqt = int(s["rteqtype"][recty])
                    if eqt <= 3:
                        NEQTSHR[Y, TYPE, b, r] = f32(f32(EQWTN[eqt, b, r] / TCWSHR[b, r]) * s["tcw_shr"])
                    else:
                        NEQTSHR[Y, TYPE, b, r] = f32(f32(EQWTN[eqt, b, r] / FCWSHR[b, r]) * s["fcw_shr"])
                    REQTSHR[Y, TYPE, b, r] = NEQTSHR[Y, TYPE, b, r]  # choices the same for clothes washers

                for reccl in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                    eqc = int(cleqcl[reccl])
                    DENOM, DENOM2 = f32(0), f32(0)
                    COUNT = 0
                    RECAR, EQTAR = {}, {}
                    TYPE = int(typect[EU])
                    for recty in range(int(tyeupt[EU]) + 1, int(tyeupt[EU + 1]) + 1):
                        if not _valid(s, recty, r):
                            continue
                        TYPE += 1
                        if int(s["rttyeqcl"][recty]) == eqc:
                            COUNT += 1
                            RECAR[COUNT] = recty
                            EQTAR[COUNT] = TYPE
                            DENOM = f32(DENOM + NEQTSHR[Y, TYPE, b, r])
                            DENOM2 = f32(DENOM2 + REQTSHR[Y, TYPE, b, r])

                    if DENOM <= 0.0:
                        WTN[Y, reccl, b, r] = s["rtbaseff"][RECSYEAR, reccl]
                    else:
                        SUM, SUM1 = f32(0.0), f32(0.0)
                        for L in range(1, COUNT + 1):
                            recty, TYPE = RECAR[L], EQTAR[L]
                            SUM = f32(SUM + f32(NEQTSHR[Y, TYPE, b, r] * s["rteqeff"][recty]))
                            SUM1 = f32(SUM1 + f32(NEQTSHR[Y, TYPE, b, r] * s["loadadj"][recty]))
                        WTN[Y, reccl, b, r] = f32(SUM / DENOM)
                        s["ncwload"][Y, r, b] = f32(SUM1 / DENOM)

                    if DENOM2 <= 0.0:
                        WTR[Y, reccl, b, r] = s["rtbaseff"][RECSYEAR, reccl]
                    else:
                        SUM = f32(0.0)
                        for L in range(1, COUNT + 1):
                            recty, TYPE = RECAR[L], EQTAR[L]
                            SUM = f32(SUM + f32(REQTSHR[Y, TYPE, b, r] * s["rteqeff"][recty]))
                        WTR[Y, reccl, b, r] = f32(SUM / DENOM2)


def rcwadd(s: dict) -> None:
    """RCWADD: washers added to new homes, replaced from the RECS-year stock, and
    replaced again; then vintaged into the future-year arrays. LOADTOT is unused in
    EIA's code and left out."""
    EU = EU_CW
    Y0 = int(s["curcalyr"])
    eupt, tyeupt, typect = s["rtcleupt"], s["rttyeupt"], s["rttypect"]
    HDR, ALPHA, K, LAM = s["hdr"], s["rtalpha"], s["rtk"], s["rtlambda"]
    ESE, RET = s["eqcese"], s["eqcret"]
    RP90, SR90, ADD, REP, SUR, RP90RP = (s[k] for k in ("eqcrp90", "eqcsr90", "eqcadd", "eqcrep", "eqcsur", "eqcrp90rp"))
    WASHNEW, HSEADD = s["washnew"], s["hseadd"]

    for r in range(1, NUM_DIV + 1):
        for b in range(1, MNUMBLDG + 1):
            for reccl in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                SR90[Y0, reccl, b, r] = 0.0
                SUR[Y0, reccl, b, r] = 0.0
                RP90RP[Y0, reccl, b, r] = 0.0
                s["ecwload"][Y0, r, b] = 0.0

            if Y0 > RECSYEAR + 1:
                WASHNEW[Y0, b, r] = WASHNEW[Y0 - 1, b, r] * f32(1.0000)  # penetration held flat
            if WASHNEW[Y0, b, r] > 1.0000:
                WASHNEW[Y0, b, r] = 1.0000  # no more than 100% of new homes

            for reccl in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                ADD[Y0, reccl, b, r] = HSEADD[Y0, b, r] * WASHNEW[Y0, b, r]
                SA = f32(0.0)
                # Replacements from the original (RECS-year) stock
                if Y0 == RECSYEAR + 1:
                    RP90[Y0, reccl, b, r] = RET[Y0, reccl] * ESE[RECSYEAR, reccl, b, r] * powi(HDR[b], Y0 - RECSYEAR)
                else:
                    RP90[Y0, reccl, b, r] = (f32(RET[Y0, reccl] - RET[Y0 - 1, reccl])
                                             * ESE[RECSYEAR, reccl, b, r] * powi(HDR[b], Y0 - RECSYEAR))

                # Replacements of replacements
                if Y0 > RECSYEAR + 1:
                    for y in range(RECSYEAR + 1, Y0):
                        temp = Y0 - y
                        ESR = f32(svrte(ALPHA[reccl], temp - 1, K[reccl], LAM[reccl])
                                  - svrte(ALPHA[reccl], temp, K[reccl], LAM[reccl]))
                        RP90RP[Y0, reccl, b, r] = RP90RP[Y0, reccl, b, r] + (
                            f32(f32(RP90[y, reccl, b, r] * ESR) * powi(HDR[b], temp))
                            + f32(f32(RP90RP[y, reccl, b, r] * ESR) * powi(HDR[b], temp)))

                if Y0 > RECSYEAR + 1:
                    for y in range(RECSYEAR + 1, Y0):
                        temp = Y0 - y
                        ESR = svrte(ALPHA[reccl], temp, K[reccl], LAM[reccl])
                        SR90[Y0, reccl, b, r] = SR90[Y0, reccl, b, r] + (
                            f32(f32(RP90[y, reccl, b, r] * ESR) * powi(HDR[b], temp))
                            + f32(f32(RP90RP[y, reccl, b, r] * ESR) * powi(HDR[b], temp)))
                        HSR = powi(HDR[b], temp)
                        SA = f32(SA + f32(ADD[y, reccl, b, r] * HSR))
                        SUR[Y0, reccl, b, r] = SUR[Y0, reccl, b, r] + f32(
                            f32(ADD[y, reccl, b, r] + REP[y, reccl, b, r]) * f32(HSR * ESR))

                # Replacements for the new vintage of CurCalYr-1
                REP[Y0, reccl, b, r] = f32(SA - SUR[Y0, reccl, b, r])

    # Vintage this year's equipment into every future year
    vintage_future(s, Y0, int(eupt[EU]) + 1, int(eupt[EU + 1]), STOCK_FUTURES + (("eqcesefut", "eqcese"),))

    _aggregate_purchases(s, EU)


def _aggregate_purchases(s: dict, EU: int) -> None:
    """Purchases by equipment type for investment analysis (HEATINGTYPEPURCH:
    1 = new homes, 2 = replacements)."""
    Y = int(s["curcalyr"])
    eupt, tyeupt, typect = s["rtcleupt"], s["rttyeupt"], s["rttypect"]
    NS, RS, H = s["neqtshr"], s["reqtshr"], s["heatingtypepurch"]
    ADD, REP, RP90RP, RP90 = s["eqcadd"], s["eqcrep"], s["eqcrp90rp"], s["eqcrp90"]
    for b in range(1, MNUMBLDG + 1):
        for r in range(1, NUM_DIV + 1):
            TYPE = int(typect[EU])
            for recty in range(int(tyeupt[EU]) + 1, int(tyeupt[EU + 1]) + 1):
                if not _valid(s, recty, r):
                    continue
                TYPE += 1
                reccl = int(eupt[EU]) + int(s["rttyeqcl"][recty])
                H[Y, TYPE, b, r, 1] = f32(NS[Y, TYPE, b, r] * ADD[Y, reccl, b, r])
                H[Y, TYPE, b, r, 2] = (f32(NS[Y, TYPE, b, r] * f32(REP[Y, reccl, b, r] + RP90RP[Y, reccl, b, r]))
                                       + f32(RS[Y, TYPE, b, r] * RP90[Y, reccl, b, r]))


def rcwcon(s: dict) -> None:
    """RCWCON: clothes washer unit energy consumption and energy use. ALPHA = 0, so
    the price response RSELAST is exactly 1."""
    EU, EUPR = EU_CW, EUPR_CW
    Y, Y1 = int(s["curcalyr"]), int(s["curiyr"])
    ALPHA, EF1, EF2, EF3 = f32(0.0), f32(0.5), f32(0.35), f32(0.15)
    LEAPYR = _leapyr(Y)
    eupt, cleqcl = s["rtcleupt"], s["rtcleqcl"]
    _map_electricity_price(s, EUPR)

    # Stock-average efficiency of the RECS-year equipment
    if Y >= RECSYEAR + 1:
        for reccl in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
            s["rtbaseff"][Y, reccl] = s["stkeff"][Y, reccl]

    BASEFF, UEC = s["rtbaseff"], s["eqcuec"]
    SUEC, NUEC, RUEC, AUEC = s["eqcsuec"], s["eqcnuec"], s["eqcruec"], s["eqcauec"]
    WN, WR, WA = s["wteqceffn"], s["wteqceffr"], s["wteqceffa"]
    ESE, ADD, RP90, RP90RP, SR90, REP, SUR = (s[k] for k in ("eqcese", "eqcadd", "eqcrp90", "eqcrp90rp", "eqcsr90", "eqcrep", "eqcsur"))
    R90F, ADDF, REPF, R90RPF, ESEF = (s[k] for k in ("eqr90fut", "eqaddfut", "eqrepfut", "eqr90rpfut", "eqcesefut"))
    NCWLOAD, ECWLOAD = s["ncwload"], s["ecwload"]

    with np.errstate(all="ignore"):
        # New, replacement and average unit consumption
        for d in range(1, NUM_DIV + 1):
            for b in range(1, MNUMBLDG + 1):
                for reccl in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                    SUEC[Y, reccl, b, d] = f32(UEC[d, reccl, b] * f32(BASEFF[Y, reccl] / BASEFF[RECSYEAR, reccl]))
                    NUEC[Y, reccl, b, d] = f32(UEC[d, reccl, b] * f32(WN[Y, reccl, b, d] / BASEFF[RECSYEAR, reccl]))
                    RUEC[Y, reccl, b, d] = f32(UEC[d, reccl, b] * f32(WR[Y, reccl, b, d] / BASEFF[RECSYEAR, reccl]))
                    if Y == RECSYEAR + 1:
                        AUEC[Y, reccl, b, d] = NUEC[Y, reccl, b, d]
                        # Written for every class in turn, so the last class wins (one class here).
                        ECWLOAD[Y, d, b] = f32(
                            f32(ESE[Y, reccl, b, d] + f32(f32(ADD[Y, reccl, b, d] + RP90[Y, reccl, b, d]) * NCWLOAD[Y, d, b]))
                            / f32(f32(ESE[Y, reccl, b, d] + ADD[Y, reccl, b, d]) + RP90[Y, reccl, b, d]))
                    else:
                        TEMP, TEMP1 = f32(0.0), f32(0.0)
                        for y in range(RECSYEAR, Y):
                            TEMP = f32(f32(f32(f32(TEMP + R90F[y, Y, reccl, b, d]) + ADDF[y, Y, reccl, b, d])
                                           + REPF[y, Y, reccl, b, d]) + R90RPF[y, Y, reccl, b, d])
                            TEMP1 = f32(f32(f32(f32(f32(TEMP1 + R90F[y, Y, reccl, b, d]) + ADDF[y, Y, reccl, b, d])
                                             + REPF[y, Y, reccl, b, d]) + R90RPF[y, Y, reccl, b, d]) + ESEF[y, Y, reccl, b, d])
                        if TEMP <= 0.0:
                            AUEC[Y, reccl, b, d] = NUEC[Y, reccl, b, d]
                        else:
                            AUEC[Y, reccl, b, d] = 0.0
                            for y in range(RECSYEAR, Y):
                                new_add = f32(f32(ADDF[y, Y, reccl, b, d] + REPF[y, Y, reccl, b, d]) + R90RPF[y, Y, reccl, b, d])
                                AUEC[Y, reccl, b, d] = AUEC[Y, reccl, b, d] + f32(
                                    f32(f32(R90F[y, Y, reccl, b, d] * RUEC[y, reccl, b, d])
                                        + f32(new_add * NUEC[y, reccl, b, d])) / TEMP)
                                ECWLOAD[Y, d, b] = ECWLOAD[Y, d, b] + f32(
                                    f32(ESEF[y, Y, reccl, b, d]
                                        + f32(_vint4(R90F, ADDF, REPF, R90RPF, y, Y, reccl, b, d) * NCWLOAD[y, d, b]))
                                    / TEMP1)

        # Average efficiency
        for b in range(1, MNUMBLDG + 1):
            for d in range(1, NUM_DIV + 1):
                for reccl in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                    if Y == RECSYEAR + 1:
                        WA[RECSYEAR + 1, reccl, b, d] = WN[RECSYEAR + 1, reccl, b, d]
                    else:
                        TEMP = f32(0.0)
                        for y in range(RECSYEAR, Y):
                            TEMP = f32(f32(f32(f32(TEMP + R90F[y, Y, reccl, b, d]) + ADDF[y, Y, reccl, b, d])
                                           + REPF[y, Y, reccl, b, d]) + R90RPF[y, Y, reccl, b, d])
                        if TEMP > 0.0:
                            WA[Y, reccl, b, d] = 0.0
                            for y in range(RECSYEAR, Y):
                                new_add = f32(f32(ADDF[y, Y, reccl, b, d] + REPF[y, Y, reccl, b, d]) + R90RPF[y, Y, reccl, b, d])
                                WA[Y, reccl, b, d] = WA[Y, reccl, b, d] + f32(
                                    f32(f32(R90F[y, Y, reccl, b, d] * WR[y, reccl, b, d])
                                        + f32(new_add * WN[y, reccl, b, d])) / TEMP)
                        else:
                            WA[Y, reccl, b, d] = WN[Y, reccl, b, d]

        # Consumption
        for d in range(1, NUM_DIV + 1):
            s["cswcon"][Y1, d] = 0.0
            for b in range(1, MNUMBLDG + 1):
                s["cswconin"][Y1, d, b] = 0.0
                s["driver2"][Y1, d, b] = 0.0
                s["cswconwt"][Y1, d, b] = 0.0
        _consumption(s, EU, EUPR, "cswcon", "cswconin", "cswconwt", LEAPYR, (ALPHA, EF1, EF2, EF3))


def _vint4(R90F, ADDF, REPF, R90RPF, y, Y, reccl, b, d):
    """EQR90FUT + EQADDFUT + EQREPFUT + EQR90RPFUT for vintage y arriving in year Y."""
    return f32(f32(f32(R90F[y, Y, reccl, b, d] + ADDF[y, Y, reccl, b, d]) + REPF[y, Y, reccl, b, d])
               + R90RPF[y, Y, reccl, b, d])


def _consumption(s, EU, EUPR, con, conin, conwt, LEAPYR, rs):
    """The consumption loop shared by RCWCON and RDWCON (the two are line for line
    the same apart from the array names): energy use, intensity and driver."""
    Y, Y1 = int(s["curcalyr"]), int(s["curiyr"])
    ALPHA, EF1, EF2, EF3 = rs
    eupt = s["rtcleupt"]
    SUEC, NUEC, RUEC, AUEC = s["eqcsuec"], s["eqcnuec"], s["eqcruec"], s["eqcauec"]
    ESE, ADD, RP90, RP90RP, SR90, REP, SUR = (s[k] for k in ("eqcese", "eqcadd", "eqcrp90", "eqcrp90rp", "eqcsr90", "eqcrep", "eqcsur"))
    for d in range(1, NUM_DIV + 1):
        for b in range(1, MNUMBLDG + 1):
            for reccl in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                f = int(s["rtfuel"][reccl])
                a = f32(ESE[Y, reccl, b, d] * SUEC[Y, reccl, b, d])
                c1 = f32(ADD[Y, reccl, b, d] * NUEC[Y, reccl, b, d])
                c2 = f32(RP90RP[Y, reccl, b, d] * NUEC[Y, reccl, b, d])
                c3 = f32(RP90[Y, reccl, b, d] * RUEC[Y, reccl, b, d])
                sel = _rselast(s, f, d, ALPHA, EF1, EF2, EF3, EUPR)
                if Y == RECSYEAR + 1:
                    tot = f32(f32(f32(a + c1) + c2) + c3)
                    s[con][Y1, d] = s[con][Y1, d] + f32(LEAPYR * f32(tot * sel))
                    s[conwt][Y1, d, b] = s[conwt][Y1, d, b] + f32(LEAPYR * f32(tot * sel))
                    cnt = f32(f32(f32(ESE[Y, reccl, b, d] + ADD[Y, reccl, b, d]) + RP90RP[Y, reccl, b, d]) + RP90[Y, reccl, b, d])
                    if cnt > 0.0:
                        s[conin][Y1, d, b] = s[conin][Y1, d, b] + tot
                        s["driver2"][Y1, d, b] = s["driver2"][Y1, d, b] + cnt
                    s["eqceqcn"][Y1, reccl, b, d] = f32(LEAPYR * f32(tot * sel))
                else:
                    c3 = f32(RP90[Y, reccl, b, d] * RUEC[Y, reccl, b, d])
                    c4 = f32(RP90RP[Y, reccl, b, d] * NUEC[Y, reccl, b, d])
                    c5 = f32(SR90[Y, reccl, b, d] * AUEC[Y, reccl, b, d])
                    c6 = f32(REP[Y, reccl, b, d] * NUEC[Y, reccl, b, d])
                    c7 = f32(SUR[Y, reccl, b, d] * AUEC[Y, reccl, b, d])
                    tot = f32(f32(f32(f32(f32(f32(a + c1) + c3) + c4) + c5) + c6) + c7)
                    s[con][Y1, d] = s[con][Y1, d] + f32(LEAPYR * f32(tot * sel))
                    s[conwt][Y1, d, b] = s[conwt][Y1, d, b] + f32(LEAPYR * f32(tot * sel))
                    cnt = f32(f32(f32(f32(f32(f32(ESE[Y, reccl, b, d] + ADD[Y, reccl, b, d]) + RP90RP[Y, reccl, b, d])
                                          + RP90[Y, reccl, b, d]) + SR90[Y, reccl, b, d]) + REP[Y, reccl, b, d]) + SUR[Y, reccl, b, d])
                    if cnt > 0.0:
                        s[conin][Y1, d, b] = s[conin][Y1, d, b] + tot
                        s["driver2"][Y1, d, b] = s["driver2"][Y1, d, b] + cnt
                    s["eqceqcn"][Y1, reccl, b, d] = f32(LEAPYR * f32(tot * sel))

    # Intensity for the report writer
    for r in range(1, NUM_DIV + 1):
        for b in range(1, MNUMBLDG + 1):
            if s["driver2"][Y1, r, b] > 0:
                s[conin][Y1, r, b] = f32(s[conin][Y1, r, b] / s["driver2"][Y1, r, b])


# ----------------------------------------------------------------------------
# dishwashers
# ----------------------------------------------------------------------------

def rdwtec(s: dict) -> None:
    """RDWTEC: dishwasher choice. Plain logit shares within each class; efficiency
    is carried as a use-per-output ratio (shares divided by RTEQEFF), the
    opposite of the other end uses. Writes to AppBetaData.txt are skipped."""
    EU, EUPR = EU_DW, EUPR_DW
    Y = int(s["curcalyr"])
    s["alpha1"] = f32(-0.50)

    _map_electricity_price(s, EUPR)
    DECAY = _decay(s)

    P, LFCY, UEC = s["prices"], s["lfcy"], s["eqcuec"]
    eupt, tyeupt, typect, cleqcl = s["rtcleupt"], s["rttyeupt"], s["rttypect"], s["rtcleqcl"]
    NEQTSHR, REQTSHR = s["neqtshr"], s["reqtshr"]
    WTN, WTR = s["wteqceffn"], s["wteqceffr"]
    EQWTN, EQWTR, TOTEWTN, TOTEWTR = {}, {}, {}, {}

    with np.errstate(all="ignore"):
        for r in range(1, NUM_DIV + 1):
            for b in range(1, MNUMBLDG + 1):
                for reccl in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                    eqc = int(cleqcl[reccl])
                    TOTEWTN[eqc, b, r] = f32(0.0)
                    TOTEWTR[eqc, b, r] = f32(0.0)
                    WTN[Y, reccl, b, r] = 0.0
                    WTR[Y, reccl, b, r] = 0.0

        for r in range(1, NUM_DIV + 1):
            for b in range(1, MNUMBLDG + 1):
                for recty in range(int(tyeupt[EU]) + 1, int(tyeupt[EU + 1]) + 1):
                    if not _valid(s, recty, r):
                        continue
                    eqt, eqc = int(s["rteqtype"][recty]), int(s["rttyeqcl"][recty])
                    reccl = int(eupt[EU]) + eqc
                    f = int(s["rtfuel"][reccl])
                    if s["rteqeff"][recty] != 0.0:
                        EFFAC1 = f32(s["eqceff"][Y, reccl] / s["rteqeff"][recty])
                        EFFAC2 = f32(s["rtbaseff"][RECSYEAR, reccl] / s["rteqeff"][recty])
                    else:
                        EFFAC1 = s["rtbaseff"][RECSYEAR, reccl]
                        EFFAC2 = s["rtbaseff"][RECSYEAR, reccl]
                    CAPITAL = _capital(s, recty)
                    OPCOST1 = f32(f32(P[f, r, Y] * UEC[r, reccl, b]) * EFFAC1)
                    OPCOST2 = f32(f32(P[f, r, Y] * UEC[r, reccl, b]) * EFFAC2)
                    _beta1dr(s, recty, r)
                    LFCY[eqt, b, r, 1] = CAPITAL + f32(OPCOST1 * DECAY)
                    LFCY[eqt, b, r, 2] = CAPITAL + f32(OPCOST2 * DECAY)
                    bias, b1, b2, b3 = s["rtecbias"][recty], s["beta1dr"][recty], s["rtecbta2"][recty], s["rtecbta3"][recty]
                    EQWTN[eqt, b, r] = expf(f32(f32(f32(bias + f32(b1 * CAPITAL)) + f32(b2 * OPCOST2))
                                                      + f32(b3 * LFCY[eqt, b, r, 2])))
                    TOTEWTN[eqc, b, r] = f32(TOTEWTN[eqc, b, r] + EQWTN[eqt, b, r])
                    EQWTR[eqt, b, r] = expf(f32(f32(f32(bias + f32(b1 * CAPITAL)) + f32(b2 * OPCOST1))
                                                      + f32(b3 * LFCY[eqt, b, r, 1])))
                    TOTEWTR[eqc, b, r] = f32(TOTEWTR[eqc, b, r] + EQWTR[eqt, b, r])

        for r in range(1, NUM_DIV + 1):
            for b in range(1, MNUMBLDG + 1):
                TYPE = int(typect[EU])
                for recty in range(int(tyeupt[EU]) + 1, int(tyeupt[EU + 1]) + 1):
                    if not _valid(s, recty, r):
                        continue
                    TYPE += 1
                    eqt, eqc = int(s["rteqtype"][recty]), int(s["rttyeqcl"][recty])
                    NEQTSHR[Y, TYPE, b, r] = f32(EQWTN[eqt, b, r] / TOTEWTN[eqc, b, r])
                    REQTSHR[Y, TYPE, b, r] = f32(EQWTR[eqt, b, r] / TOTEWTR[eqc, b, r])

                for reccl in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                    eqc = int(cleqcl[reccl])
                    DENOM, DENOM2 = f32(0), f32(0)
                    COUNT = 0
                    RECAR, EQTAR = {}, {}
                    TYPE = int(typect[EU])
                    for recty in range(int(tyeupt[EU]) + 1, int(tyeupt[EU + 1]) + 1):
                        if not _valid(s, recty, r):
                            continue
                        TYPE += 1
                        if int(s["rttyeqcl"][recty]) == eqc:
                            COUNT += 1
                            RECAR[COUNT] = recty
                            EQTAR[COUNT] = TYPE
                            DENOM = f32(DENOM + NEQTSHR[Y, TYPE, b, r])
                            DENOM2 = f32(DENOM2 + REQTSHR[Y, TYPE, b, r])

                    # SUM1 (share-weighted LOADADJ) is accumulated in EIA's code but never used.
                    if DENOM <= 0.0:
                        WTN[Y, reccl, b, r] = f32(f32(1) / s["rtbaseff"][RECSYEAR, reccl])
                    else:
                        SUM = f32(0.0)
                        for L in range(1, COUNT + 1):
                            recty, TYPE = RECAR[L], EQTAR[L]
                            SUM = f32(SUM + f32(NEQTSHR[Y, TYPE, b, r] / s["rteqeff"][recty]))
                        WTN[Y, reccl, b, r] = f32(SUM / DENOM)

                    if DENOM2 <= 0.0:
                        WTR[Y, reccl, b, r] = f32(f32(1) / s["rtbaseff"][RECSYEAR, reccl])
                    else:
                        SUM = f32(0.0)
                        for L in range(1, COUNT + 1):
                            recty, TYPE = RECAR[L], EQTAR[L]
                            SUM = f32(SUM + f32(REQTSHR[Y, TYPE, b, r] / s["rteqeff"][recty]))
                        WTR[Y, reccl, b, r] = f32(SUM / DENOM2)


def rdwadd(s: dict) -> None:
    """RDWADD: dishwashers added, replaced and vintaged. Differs from RCWADD by a
    growing penetration into new homes (capped at 100%), and EQCND90, the stock of
    RECS-year homes that gain a dishwasher up to a 90% ceiling."""
    EU = EU_DW
    Y0 = int(s["curcalyr"])
    new_dw_pen, max_dw_pen = f32(1.0048), f32(0.90)
    eupt = s["rtcleupt"]
    HDR, ALPHA, K, LAM = s["hdr"], s["rtalpha"], s["rtk"], s["rtlambda"]
    ESE, RET, EH, DWPR = s["eqcese"], s["eqcret"], s["eh"], s["dwpr"]
    RP90, SR90, ADD, REP, SUR, RP90RP, ND90 = (s[k] for k in ("eqcrp90", "eqcsr90", "eqcadd", "eqcrep", "eqcsur", "eqcrp90rp", "eqcnd90"))
    DISHNEW, HSEADD = s["dishnew"], s["hseadd"]

    for r in range(1, NUM_DIV + 1):
        for b in range(1, MNUMBLDG + 1):
            for reccl in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                SR90[Y0, reccl, b, r] = 0.0
                RP90RP[Y0, reccl, b, r] = 0.0
                SUR[Y0, reccl, b, r] = 0.0

            if Y0 > RECSYEAR + 1:
                DISHNEW[Y0, b, r] = DISHNEW[Y0 - 1, b, r] * new_dw_pen
            if DISHNEW[Y0, b, r] > 1.0000:
                DISHNEW[Y0, b, r] = 1.0000  # no more than 100% of new homes

            for reccl in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                ADD[Y0, reccl, b, r] = HSEADD[Y0, b, r] * DISHNEW[Y0, b, r]
                SA = f32(0.0)
                stock = f32(ESE[RECSYEAR, reccl, b, r] * powi(HDR[b], Y0 - RECSYEAR))
                if f32(ND90[Y0, reccl, b, r] / EH[Y0, b, r]) >= max_dw_pen:
                    ND90[Y0, reccl, b, r] = f32(stock - stock)
                else:
                    ND90[Y0, reccl, b, r] = f32(f32(stock * f32(f32(1.0) + DWPR[b, r])) - stock)

                if Y0 == RECSYEAR + 1:
                    RP90[Y0, reccl, b, r] = RET[Y0, reccl] * ESE[RECSYEAR, reccl, b, r] * powi(HDR[b], Y0 - RECSYEAR)
                else:
                    RP90[Y0, reccl, b, r] = (f32(RET[Y0, reccl] - RET[Y0 - 1, reccl])
                                             * ESE[RECSYEAR, reccl, b, r] * powi(HDR[b], Y0 - RECSYEAR))

                if Y0 > RECSYEAR + 1:
                    for y in range(RECSYEAR + 1, Y0):
                        temp = Y0 - y
                        ESR = f32(svrte(ALPHA[reccl], temp - 1, K[reccl], LAM[reccl])
                                  - svrte(ALPHA[reccl], temp, K[reccl], LAM[reccl]))
                        RP90RP[Y0, reccl, b, r] = RP90RP[Y0, reccl, b, r] + f32(
                            f32(f32(f32(RP90[y, reccl, b, r] * ESR) * powi(HDR[b], temp))
                                + f32(f32(RP90RP[y, reccl, b, r] * ESR) * powi(HDR[b], temp)))
                            + f32(f32(ND90[y, reccl, b, r] * ESR) * powi(HDR[b], temp)))

                RP90RP[Y0, reccl, b, r] = RP90RP[Y0, reccl, b, r] + ND90[Y0, reccl, b, r]

                if Y0 > RECSYEAR + 1:
                    for y in range(RECSYEAR + 1, Y0):
                        temp = Y0 - y
                        ESR = svrte(ALPHA[reccl], temp, K[reccl], LAM[reccl])
                        SR90[Y0, reccl, b, r] = SR90[Y0, reccl, b, r] + f32(
                            f32(f32(f32(RP90[y, reccl, b, r] * ESR) * powi(HDR[b], temp))
                                + f32(f32(RP90RP[y, reccl, b, r] * ESR) * powi(HDR[b], temp)))
                            + f32(f32(ND90[y, reccl, b, r] * ESR) * powi(HDR[b], temp)))
                        HSR = powi(HDR[b], temp)
                        SA = f32(SA + f32(ADD[y, reccl, b, r] * HSR))
                        SUR[Y0, reccl, b, r] = SUR[Y0, reccl, b, r] + f32(
                            f32(ADD[y, reccl, b, r] + REP[y, reccl, b, r]) * f32(HSR * ESR))

                REP[Y0, reccl, b, r] = f32(SA - SUR[Y0, reccl, b, r])

    vintage_future(s, Y0, int(eupt[EU]) + 1, int(eupt[EU + 1]))

    _aggregate_purchases(s, EU)


def rdwcon(s: dict) -> None:
    """RDWCON: dishwasher unit energy consumption and energy use. Kept as in EIA:
    efficiency enters as a use ratio, so SUEC divides the RECS-year value by the
    current one but NUEC and RUEC multiply by it. ALPHA = 0, so RSELAST is 1."""
    EU, EUPR = EU_DW, EUPR_DW
    Y, Y1 = int(s["curcalyr"]), int(s["curiyr"])
    ALPHA, EF1, EF2, EF3 = f32(0.0), f32(0.5), f32(0.35), f32(0.15)
    LEAPYR = _leapyr(Y)
    eupt = s["rtcleupt"]
    _map_electricity_price(s, EUPR)

    if Y >= RECSYEAR + 1:
        for reccl in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
            s["rtbaseff"][Y, reccl] = s["stkeff"][Y, reccl]

    BASEFF, UEC = s["rtbaseff"], s["eqcuec"]
    SUEC, NUEC, RUEC, AUEC = s["eqcsuec"], s["eqcnuec"], s["eqcruec"], s["eqcauec"]
    WN, WR, WA = s["wteqceffn"], s["wteqceffr"], s["wteqceffa"]
    R90F, ADDF, REPF, R90RPF = (s[k] for k in ("eqr90fut", "eqaddfut", "eqrepfut", "eqr90rpfut"))

    with np.errstate(all="ignore"):
        for d in range(1, NUM_DIV + 1):
            for b in range(1, MNUMBLDG + 1):
                for reccl in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                    SUEC[Y, reccl, b, d] = f32(UEC[d, reccl, b] * f32(BASEFF[RECSYEAR, reccl] / BASEFF[Y, reccl]))
                    NUEC[Y, reccl, b, d] = f32(UEC[d, reccl, b] * f32(WN[Y, reccl, b, d] * BASEFF[RECSYEAR, reccl]))
                    RUEC[Y, reccl, b, d] = f32(UEC[d, reccl, b] * f32(WR[Y, reccl, b, d] * BASEFF[RECSYEAR, reccl]))
                    if Y == RECSYEAR + 1:
                        AUEC[Y, reccl, b, d] = NUEC[Y, reccl, b, d]
                    else:
                        TEMP = f32(0.0)
                        for y in range(RECSYEAR, Y):
                            TEMP = f32(f32(f32(f32(TEMP + R90F[y, Y, reccl, b, d]) + ADDF[y, Y, reccl, b, d])
                                           + REPF[y, Y, reccl, b, d]) + R90RPF[y, Y, reccl, b, d])
                        if TEMP <= 0.0:
                            AUEC[Y, reccl, b, d] = NUEC[Y, reccl, b, d]
                        else:
                            AUEC[Y, reccl, b, d] = 0.0
                            for y in range(RECSYEAR, Y):
                                new_add = f32(f32(ADDF[y, Y, reccl, b, d] + REPF[y, Y, reccl, b, d]) + R90RPF[y, Y, reccl, b, d])
                                AUEC[Y, reccl, b, d] = AUEC[Y, reccl, b, d] + f32(
                                    f32(f32(R90F[y, Y, reccl, b, d] * RUEC[y, reccl, b, d])
                                        + f32(new_add * NUEC[y, reccl, b, d])) / TEMP)

        for b in range(1, MNUMBLDG + 1):
            for d in range(1, NUM_DIV + 1):
                for reccl in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                    if Y == RECSYEAR + 1:
                        WA[RECSYEAR + 1, reccl, b, d] = WN[RECSYEAR + 1, reccl, b, d]
                    else:
                        TEMP = f32(0.0)
                        for y in range(RECSYEAR, Y):
                            TEMP = f32(f32(f32(f32(TEMP + R90F[y, Y, reccl, b, d]) + ADDF[y, Y, reccl, b, d])
                                           + REPF[y, Y, reccl, b, d]) + R90RPF[y, Y, reccl, b, d])
                        if TEMP > 0.0:
                            WA[Y, reccl, b, d] = 0.0
                            for y in range(RECSYEAR, Y):
                                new_add = f32(f32(ADDF[y, Y, reccl, b, d] + REPF[y, Y, reccl, b, d]) + R90RPF[y, Y, reccl, b, d])
                                WA[Y, reccl, b, d] = WA[Y, reccl, b, d] + f32(
                                    f32(f32(R90F[y, Y, reccl, b, d] * WR[y, reccl, b, d])
                                        + f32(new_add * WN[y, reccl, b, d])) / TEMP)
                        else:
                            WA[Y, reccl, b, d] = WN[Y, reccl, b, d]

        for d in range(1, NUM_DIV + 1):
            s["dswcon"][Y1, d] = 0.0
            for b in range(1, MNUMBLDG + 1):
                s["dswconin"][Y1, d, b] = 0.0
                s["driver2"][Y1, d, b] = 0.0
                s["dswconwt"][Y1, d, b] = 0.0
        _consumption(s, EU, EUPR, "dswcon", "dswconin", "dswconwt", LEAPYR, (ALPHA, EF1, EF2, EF3))
