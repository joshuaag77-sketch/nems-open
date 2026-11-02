"""Space heating: equipment added and replaced (RHTRADD) and consumption (RHTRCON).

Writes to debug units and AppBetaData.txt are skipped.

RHTRADD vintages the heating equipment stock of each class (original RECS-year
stock, its replacements, post-RECS additions and their replacements), calls
REPLACE for fuel switching in single-family homes, and builds the new-house
shell index.
"""

import math

import numpy as np

from nems_open.fortran_array import FArray
from nems_open.residential.common import (BASEYR, ENDYR, LASTSTEOYR, MNUMBLDG, MNUMFUEL, NUM_DIV,
                                          RECSYEAR, f32, powi)
from nems_open.residential.helpers import replace, rselast, svrte, vintage_future

NSHELLTYPES = 5


def _replace_ends_loop(year: int, eu: int, b: int, r: int) -> bool:
    """EIA quirk: REPLACE ends with a debug loop `DO RECCL=1,27` for 2021, EU 1,
    B 1, R 1. RECCL is the caller's DO variable, passed by reference, so it is 28
    on return and the caller's class loop stops after its first pass."""
    return year == 2021 and eu == 1 and b == 1 and r == 1


def rhtradd(s: dict) -> None:
    """RHTRADD (resd.f line 3951)."""
    CurCalYr, CURITR = int(s["curcalyr"]), int(s["curitr"])
    EU = 1  # space heating
    NHTRFL = int(s["nhtrfl"])
    eupt, typt = s["rtcleupt"], s["rttyeupt"]
    c0, c1 = int(eupt[EU]) + 1, int(eupt[EU + 1])  # RECCL range of this end use
    t0, t1 = int(typt[EU]) + 1, int(typt[EU + 1])  # RECTY range
    RTCLEQCL = s["rtcleqcl"]
    HDR = s["hdr"]
    RTALPHA, RTK, RTLAMBDA = s["rtalpha"], s["rtk"], s["rtlambda"]
    EQCADD, EQCREP, EQCSUR = s["eqcadd"], s["eqcrep"], s["eqcsur"]
    EQCRP90, EQCRP90RP, EQCSR90 = s["eqcrp90"], s["eqcrp90rp"], s["eqcsr90"]
    EQCESE, EQCRET, HSEADD = s["eqcese"], s["eqcret"], s["hseadd"]

    # SHARESN is a local in EIA's code, zeroed per class before use
    SHARESN = np.zeros((NHTRFL + 20, MNUMBLDG + 1, NUM_DIV + 1), dtype=np.float32)

    for R in range(1, NUM_DIV + 1):
        for B in range(1, MNUMBLDG + 1):
            for RECCL in range(c0, c1 + 1):
                EQC = int(RTCLEQCL[RECCL])
                SHARESN[EQC, B, R] = 0.0
                EQCRP90RP[CurCalYr, RECCL, B, R] = 0.0
                EQCSR90[CurCalYr, RECCL, B, R] = 0.0
                EQCSUR[CurCalYr, RECCL, B, R] = 0.0
                if B == 1:
                    EQCREP[CurCalYr, RECCL, B, R] = 0.0

            # heating system shares for the record types valid this year and division
            for RECTY in range(t0, t1 + 1):
                if s["rtinityr"][RECTY] <= CurCalYr <= s["rtlastyr"][RECTY]:
                    if int(s["rtcendiv"][RECTY]) == R:
                        EQC = int(s["rttyeqcl"][RECTY])
                        SHARESN[EQC, B, R] = s["hsysshr"][CurCalYr, EQC, B, R]

            for RECCL in range(c0, c1 + 1):
                EQC = int(RTCLEQCL[RECCL])
                EQCADD[CurCalYr, RECCL, B, R] = HSEADD[CurCalYr, B, R] * SHARESN[EQC, B, R]
                SA = f32(0.0)

                # replacements of the original RECS-year stock
                if CurCalYr == RECSYEAR + 1:
                    EQCRP90[CurCalYr, RECCL, B, R] = (EQCRET[CurCalYr, RECCL]
                        * EQCESE[RECSYEAR, RECCL, B, R] * powi(HDR[B], CurCalYr - RECSYEAR))
                else:
                    EQCRP90[CurCalYr, RECCL, B, R] = ((EQCRET[CurCalYr, RECCL] - EQCRET[CurCalYr - 1, RECCL])
                        * EQCESE[RECSYEAR, RECCL, B, R] * powi(HDR[B], CurCalYr - RECSYEAR))

                # vintage replacements of replacements
                if CurCalYr > RECSYEAR + 1:
                    for Y in range(RECSYEAR + 1, CurCalYr):
                        TEMP = CurCalYr - Y
                        ESR = (svrte(RTALPHA[RECCL], TEMP - 1, RTK[RECCL], RTLAMBDA[RECCL])
                               - svrte(RTALPHA[RECCL], TEMP, RTK[RECCL], RTLAMBDA[RECCL]))
                        EQCRP90RP[CurCalYr, RECCL, B, R] = (EQCRP90RP[CurCalYr, RECCL, B, R]
                            + (EQCRP90[Y, RECCL, B, R] * ESR * powi(HDR[B], TEMP)
                               + EQCRP90RP[Y, RECCL, B, R] * ESR * powi(HDR[B], TEMP)))

                # surviving replacements
                if CurCalYr > RECSYEAR + 1:
                    for Y in range(RECSYEAR + 1, CurCalYr):
                        TEMP = CurCalYr - Y
                        ESR = svrte(RTALPHA[RECCL], TEMP, RTK[RECCL], RTLAMBDA[RECCL])
                        EQCSR90[CurCalYr, RECCL, B, R] = (EQCSR90[CurCalYr, RECCL, B, R]
                            + (EQCRP90[Y, RECCL, B, R] * ESR * powi(HDR[B], TEMP)
                               + EQCRP90RP[Y, RECCL, B, R] * ESR * powi(HDR[B], TEMP)))
                        HSR = powi(HDR[B], TEMP)
                        SA = SA + EQCADD[Y, RECCL, B, R] * HSR
                        EQCSUR[CurCalYr, RECCL, B, R] = (EQCSUR[CurCalYr, RECCL, B, R]
                            + ((EQCADD[Y, RECCL, B, R] + EQCREP[Y, RECCL, B, R]) * (HSR * ESR)))

                if B == 1:
                    # what replacements would be without switching, then REPLACE spreads them
                    s["oeqcrep"][CurCalYr, RECCL, 1, R] = SA - EQCSUR[CurCalYr, RECCL, B, R]
                    replace(s, EU, R, B, RECCL, 1)
                    if _replace_ends_loop(CurCalYr, EU, B, R):
                        break
                else:
                    # no switching in multifamily or mobile homes
                    EQCREP[CurCalYr, RECCL, B, R] = SA - EQCSUR[CurCalYr, RECCL, B, R]

    # REPLACE for existing RECS-year single-family homes. B stays 1 for the rest
    # of the routine (EIA quirk: the loops below never touch multifamily or mobile).
    B = 1
    for R in range(1, NUM_DIV + 1):
        for RECCL in range(c0, c1 + 1):
            s["oeqcrp90"][CurCalYr, RECCL, B, R] = EQCRP90[CurCalYr, RECCL, 1, R]
            s["oeqcrp90r"][CurCalYr, RECCL, B, R] = EQCRP90RP[CurCalYr, RECCL, 1, R]
            replace(s, EU, R, B, RECCL, 2)
            if _replace_ends_loop(CurCalYr, EU, B, R):
                break

    SWITCHTO, SWITCHTOR = s["switchto"], s["switchtor"]
    EQCSW90, EQCSW90R = s["eqcsw90"], s["eqcsw90r"]
    SWITCHES, SWITCHESR = s["switches"], s["switchesr"]
    for R in range(1, NUM_DIV + 1):
        for RECCL in range(c0, c1 + 1):
            SWITCHTO[CurCalYr, RECCL, B, R] = 0.0
            SWITCHTOR[CurCalYr, RECCL, B, R] = 0.0
            for RECCLSW in range(c0, c1 + 1):
                if RECCLSW != RECCL:
                    SWITCHTO[CurCalYr, RECCL, B, R] = SWITCHTO[CurCalYr, RECCL, B, R] + EQCSW90[CurCalYr, RECCLSW, RECCL, B, R]
                    SWITCHTOR[CurCalYr, RECCL, B, R] = SWITCHTOR[CurCalYr, RECCL, B, R] + EQCSW90R[CurCalYr, RECCLSW, RECCL, B, R]

    for R in range(1, NUM_DIV + 1):
        for RECCL in range(c0, c1 + 1):
            EQCRP90[CurCalYr, RECCL, B, R] = EQCRP90[CurCalYr, RECCL, B, R] - SWITCHES[CurCalYr, RECCL, B, R]
            EQCRP90RP[CurCalYr, RECCL, B, R] = (EQCRP90RP[CurCalYr, RECCL, B, R] - SWITCHESR[CurCalYr, RECCL, B, R]
                                                + SWITCHTOR[CurCalYr, RECCL, B, R] + SWITCHTO[CurCalYr, RECCL, B, R])

    # SWT and SWF are locals nothing reads; kept to match the Fortran
    SWF = f32(0.0)
    SWT = f32(0.0)
    for R in range(1, NUM_DIV + 1):
        for RECCL in range(c0, c1 + 1):
            SWT = SWT + SWITCHTO[CurCalYr, RECCL, B, R] + SWITCHTOR[CurCalYr, RECCL, B, R]
            SWF = SWF + SWITCHES[CurCalYr, RECCL, B, R] + SWITCHESR[CurCalYr, RECCL, B, R]
            s["swtotal"][CurCalYr, RECCL, R] = SWITCHTO[CurCalYr, RECCL, B, R] + SWITCHTOR[CurCalYr, RECCL, B, R]
            s["swftotal"][CurCalYr, RECCL, R] = SWITCHES[CurCalYr, RECCL, B, R] + SWITCHESR[CurCalYr, RECCL, B, R]

    for R in range(1, NUM_DIV + 1):
        for RECCL in range(c0, c1 + 1):
            s["eqcnd90"][CurCalYr, RECCL, B, R] = (EQCRP90[CurCalYr, RECCL, B, R] + EQCESE[CurCalYr, RECCL, B, R]
                                                   + EQCSR90[CurCalYr, RECCL, B, R] + EQCRP90RP[CurCalYr, RECCL, B, R])

    # shell investment
    NHSHELL = s["nhshell"]
    NHSHELL[CurCalYr, 1:NHTRFL, 1:NUM_DIV, 1:MNUMBLDG] = 0.0
    NEWSHELLWT = np.zeros((7, MNUMBLDG + 1, NUM_DIV + 1), dtype=np.float32)  # [F, B, R] for this year
    NEWADDWT = np.zeros((7, MNUMBLDG + 1, NUM_DIV + 1), dtype=np.float32)
    HEATOT, HSHELL = s["heatot"], s["hshell"]
    F = 0
    for R in range(1, NUM_DIV + 1):
        for B in range(1, MNUMBLDG + 1):
            for RECCL in range(c0, c1 + 1):
                if RECCL <= 2 or RECCL == 9:
                    F = 4
                if RECCL == 3 or RECCL == 4 or RECCL == 10:
                    F = 3
                if RECCL == 5:
                    F = 2
                if RECCL == 6 or RECCL == 7:
                    F = 1
                if RECCL == 8:
                    F = 5
                EQC = int(RTCLEQCL[RECCL])
                HEATOT[CurCalYr, EQC, B, R] = (EQCESE[CurCalYr, RECCL, B, R] + EQCRP90[CurCalYr, RECCL, B, R]
                    + EQCSR90[CurCalYr, RECCL, B, R] + EQCADD[CurCalYr, RECCL, B, R]
                    + EQCREP[CurCalYr, RECCL, B, R] + EQCSUR[CurCalYr, RECCL, B, R]
                    + EQCRP90RP[CurCalYr, RECCL, B, R])
                NEWSHELLWT[F, B, R] = NEWSHELLWT[F, B, R] + EQCADD[CurCalYr, RECCL, B, R] * HSHELL[CurCalYr, RECCL, B, R]
                NEWADDWT[F, B, R] = NEWADDWT[F, B, R] + EQCADD[CurCalYr, RECCL, B, R]

    for R in range(1, NUM_DIV + 1):
        for B in range(1, MNUMBLDG + 1):
            for F in range(1, NHTRFL + 1):
                if NEWADDWT[F, B, R] > 0.0:
                    NHSHELL[CurCalYr, F, R, B] = NEWSHELLWT[F, B, R] / NEWADDWT[F, B, R]
                else:
                    NHSHELL[CurCalYr, F, R, B] = 1.0
                NHSHELL[RECSYEAR, F, R, B] = NHSHELL[RECSYEAR + 1, F, R, B]

    # house size adjustment; column 1 fossil heating, 2 electric heating, 5 furnace fans
    EL, EXS, EXA = s["elastic"], s["exsqrfoot"], s["exsqftadj"]
    for D in range(1, NUM_DIV + 1):
        for B in range(1, MNUMBLDG + 1):
            EXA[CurCalYr, B, D, 1] = (EL[1, D] * ((EXS[CurCalYr, B, D] - EXS[RECSYEAR, B, D])
                                                  / EXS[RECSYEAR, B, D]) * NHSHELL[CurCalYr, 3, D, B]) + f32(1)
            EXA[CurCalYr, B, D, 2] = (EL[2, D] * ((EXS[CurCalYr, B, D] - EXS[RECSYEAR, B, D])
                                                  / EXS[RECSYEAR, B, D]) * NHSHELL[CurCalYr, 4, D, B]) + f32(1)
            EXA[CurCalYr, B, D, 5] = (EL[5, D] * ((EXS[CurCalYr, B, D] - EXS[RECSYEAR, B, D])
                                                  / EXS[RECSYEAR, B, D]) * NHSHELL[CurCalYr, 3, D, B]) + f32(1)

    # equipment surviving into each future year
    vintage_future(s, CurCalYr, c0, c1)

    # aggregate heating systems for investment analysis
    T = CurCalYr
    HTP, SB = s["heatingtypepurch"], s["shellbuilds"]
    for B in range(1, MNUMBLDG + 1):
        for R in range(1, NUM_DIV + 1):
            for RECTY in range(t0, t1 + 1):
                if s["rtinityr"][RECTY] <= CurCalYr <= s["rtlastyr"][RECTY]:
                    if int(s["rtcendiv"][RECTY]) == R:
                        EQT = int(s["rteqtype"][RECTY])
                        EQC = int(s["rttyeqcl"][RECTY])
                        RECCL = int(eupt[EU]) + EQC
                        HTP[T, EQT, B, R, 1] = s["hveqshr"][T, EQT, B, R] * EQCADD[T, RECCL, B, R]
                        HTP[T, EQT, B, R, 2] = (s["neqtshr"][T, EQT, B, R] * (EQCREP[T, RECCL, B, R] + EQCRP90RP[T, RECCL, B, R])
                                                + s["reqtshr"][T, EQT, B, R] * EQCRP90[T, RECCL, B, R])
                        for S in range(1, NSHELLTYPES + 1):
                            SB[T, EQT, S, B, R] = s["htshellwt"][T, EQT, S, B, R] * EQCADD[T, RECCL, B, R]

    # Natural gas heating equipment counts stand in for natural gas customers
    GC = s["rsgascust"]
    for R in range(1, NUM_DIV + 1):
        GC[CurCalYr, R] = 0.0
    if CurCalYr == RECSYEAR + 1 and CURITR == 1:
        for R in range(1, NUM_DIV + 1):
            GC[RECSYEAR, R] = 0.0
            for B in range(1, MNUMBLDG + 1):
                GC[RECSYEAR, R] = (GC[RECSYEAR, R] + EQCESE[RECSYEAR, 3, B, R]
                                   + EQCESE[RECSYEAR, 4, B, R] + EQCESE[RECSYEAR, 10, B, R])
    else:
        for R in range(1, NUM_DIV + 1):
            for B in range(1, MNUMBLDG + 1):
                GC[CurCalYr, R] = (GC[CurCalYr, R] + HEATOT[CurCalYr, 3, B, R]
                                   + HEATOT[CurCalYr, 4, B, R] + HEATOT[CurCalYr, 10, B, R])


def _powf(x, y):
    """REAL**REAL as libm's powf gives it: computed in double, rounded once."""
    try:
        return f32(math.pow(float(x), float(y)))
    except (ValueError, ZeroDivisionError):
        return f32(math.nan)


def _carried(s: dict) -> dict:
    """RHTRCON's SAVEd locals (the oracle is built with -fno-automatic, so they are
    zero at the start and keep their values between calls and iterations)."""
    c = s.get("_rhtrcon")
    if c is None:
        yrs, rb = (RECSYEAR, ENDYR), [(1, NUM_DIV), (1, MNUMBLDG)]
        c = s["_rhtrcon"] = {
            "nfanuec": FArray.zeros([yrs] + rb), "efanuec": FArray.zeros([yrs] + rb),
            "afanuec": FArray.zeros([yrs] + rb), "nfaniuec": FArray.zeros([yrs] + rb),
            "faneff": FArray.zeros([yrs]), "nfaneff": FArray.zeros([yrs]),
            "hddfact": FArray.zeros([(1, 11)]),
        }
    return c


def rhtrcon(s: dict) -> None:
    """RHTRCON (resd.f line 4249): space heating consumption by fuel and division,
    the unit energy consumptions it needs, and the report-writer weights.

    The electricity price for end use 1 (PELRSOUT) is read from s["pelrsout"];
    LEAPYR is worked out from the year as RESD does."""
    CurCalYr, CurIYr, CURITR = int(s["curcalyr"]), int(s["curiyr"]), int(s["curitr"])
    EU = 1
    EUPR = 1
    NHTRFL = int(s["nhtrfl"])
    eupt = s["rtcleupt"]
    c0, c1 = int(eupt[EU]) + 1, int(eupt[EU + 1])
    c = _carried(s)
    NFANUEC, EFANUEC, AFANUEC, NFANIUEC = c["nfanuec"], c["efanuec"], c["afanuec"], c["nfaniuec"]
    FANEFF, NFANEFF, HDDFACT = c["faneff"], c["nfaneff"], c["hddfact"]
    ALPHA, ef1, ef2, ef3 = f32(-0.15), f32(0.5), f32(0.35), f32(0.15)  # own-price elasticity and its lag shares
    ALPHA2 = f32(-0.05)  # heating shell adjustment
    EXPO = f32(1.0) + ALPHA2  # the (1.0+ALPHA2) exponent
    if CurCalYr % 4 == 0 and CurCalYr <= LASTSTEOYR:
        LEAPYR = f32(366.0) / f32(365.0)
    else:
        LEAPYR = f32(365.0) / f32(365.0)

    PRICES, PELRSOUT, GDP = s["prices"], s["pelrsout"], s["mc_jpgdp"]
    infl = GDP[int(s["rtekdollaryr"]) - BASEYR + 1] / GDP[-2]
    for R in range(1, NUM_DIV + 1):
        PRICES[4, R, CurCalYr] = PELRSOUT[R, CurIYr, EUPR] * infl

    # weather elasticity: a 10% rise in heating degree days gives 21% more heating
    HDDADJ = s["hddadj"]
    if CurCalYr <= int(s["ijumpcalyr"]):
        for R in range(1, NUM_DIV + 1):
            HDDFACT[R] = _powf(HDDADJ[CurCalYr, R] / HDDADJ[RECSYEAR, R], f32(2.0))

    # furnace fan standard effective 2019
    if CurCalYr == RECSYEAR + 1:
        for Y in range(RECSYEAR, ENDYR + 1):
            if Y <= 2018:
                NFANEFF[Y] = 1.0
                FANEFF[Y] = 1.0
            else:
                NFANEFF[Y] = 0.75
                FANEFF[Y] = 1.0

    FANUEC, FANIUEC, EXSQFTADJ = s["fanuec"], s["faniuec"], s["exsqftadj"]
    if CURITR == 1:
        for R in range(1, NUM_DIV + 1):
            for B in range(1, MNUMBLDG + 1):
                EFANUEC[CurCalYr, R, B] = FANUEC[R, B] * FANEFF[CurCalYr] * EXSQFTADJ[CurCalYr, B, R, 5]
                FANIUEC[R, B] = FANUEC[R, B] * FANEFF[CurCalYr]

    for R in range(1, NUM_DIV + 1):
        for B in range(1, MNUMBLDG + 1):
            NFANUEC[CurCalYr, R, B] = FANUEC[R, B] * NFANEFF[CurCalYr] * EXSQFTADJ[CurCalYr, B, R, 5]
            NFANIUEC[CurCalYr, R, B] = FANUEC[R, B] * NFANEFF[CurCalYr]

    # moving average stock efficiency of RECS-year equipment
    RTBASEFF, STKEFF = s["rtbaseff"], s["stkeff"]
    if CurCalYr >= RECSYEAR + 1:
        for RECCL in range(c0, c1 + 1):
            RTBASEFF[CurCalYr, RECCL] = STKEFF[CurCalYr, RECCL]

    # existing (RECS-year) heating and cooling shell indexes before weatherization
    EHSHELL, ECSHELL, TECHG = s["ehshell"], s["ecshell"], s["techg"]
    for R in range(1, NUM_DIV + 1):
        for B in range(1, MNUMBLDG + 1):
            for F in range(1, MNUMFUEL + 1):
                EHSHELL[CurCalYr, F, R, B] = 0.0
                if F != 5:  # no price response for wood
                    EHSHELL[CurCalYr, F, R, B] = (EHSHELL[RECSYEAR, F, R, B]
                        * rselast(s, F, R, ALPHA2, ef1, ef2, ef3, EUPR) - TECHG[CurCalYr, R, B])
                else:
                    EHSHELL[CurCalYr, F, R, B] = EHSHELL[RECSYEAR, F, R, B] - TECHG[CurCalYr, R, B]
            ECSHELL[CurCalYr, R, B] = ECSHELL[RECSYEAR, R, B] - (
                (EHSHELL[RECSYEAR, 1, R, B] - EHSHELL[CurCalYr, 1, R, B]) * f32(0.1)
                + (EHSHELL[RECSYEAR, 3, R, B] - EHSHELL[CurCalYr, 3, R, B]) * f32(0.6)
                + (EHSHELL[RECSYEAR, 4, R, B] - EHSHELL[CurCalYr, 4, R, B]) * f32(0.3)) * f32(0.38)

    # weatherization
    ANUM = np.zeros((MNUMFUEL + 1, NUM_DIV + 1, MNUMBLDG + 1), dtype=np.float32)
    ADEN = np.zeros((MNUMFUEL + 1, NUM_DIV + 1, MNUMBLDG + 1), dtype=np.float32)
    WTHRZTN, LIMIT = s["wthrztn"], s["limit"]
    for R in range(1, NUM_DIV + 1):
        for B in range(1, MNUMBLDG + 1):
            for F in range(1, MNUMFUEL + 1):
                ANUM[F, R, B] = 0.0
                ADEN[F, R, B] = 0.0
                EHSHELL[CurCalYr, F, R, B] = EHSHELL[CurCalYr, F, R, B] + WTHRZTN[CurCalYr, 1, R, B]
                if EHSHELL[CurCalYr, F, R, B] > EHSHELL[CurCalYr - 1, F, R, B]:
                    EHSHELL[CurCalYr, F, R, B] = EHSHELL[CurCalYr - 1, F, R, B]
                if EHSHELL[CurCalYr, F, R, B] < LIMIT:
                    EHSHELL[CurCalYr, F, R, B] = LIMIT
            ECSHELL[CurCalYr, R, B] = ECSHELL[CurCalYr, R, B] + WTHRZTN[CurCalYr, 2, R, B]
            if ECSHELL[CurCalYr, R, B] > ECSHELL[CurCalYr - 1, R, B]:
                ECSHELL[CurCalYr, R, B] = ECSHELL[CurCalYr - 1, R, B]
            if ECSHELL[CurCalYr, R, B] < LIMIT:
                ECSHELL[CurCalYr, R, B] = LIMIT

    # shell index of equipment added after the RECS year, except this year's
    NHSHELL, AHSHELL = s["nhshell"], s["ahshell"]
    EQCADD, EQCREP, EQCSUR = s["eqcadd"], s["eqcrep"], s["eqcsur"]
    EQCESE, EQCRP90, EQCSR90, EQCRP90RP = s["eqcese"], s["eqcrp90"], s["eqcsr90"], s["eqcrp90rp"]
    RTFUEL, RTFFAN = s["rtfuel"], s["rtffan"]
    for R in range(1, NUM_DIV + 1):
        for B in range(1, MNUMBLDG + 1):
            for RECCL in range(c0, c1 + 1):
                F = int(RTFUEL[RECCL])
                if CurCalYr > RECSYEAR + 1:
                    for Y in range(RECSYEAR + 1, CurCalYr):
                        ANUM[F, R, B] = ANUM[F, R, B] + NHSHELL[Y, F, R, B] * EQCADD[Y, RECCL, B, R]
                        ADEN[F, R, B] = ADEN[F, R, B] + EQCADD[Y, RECCL, B, R]

    for R in range(1, NUM_DIV + 1):
        for B in range(1, MNUMBLDG + 1):
            for F in range(1, MNUMFUEL + 1):
                if ADEN[F, R, B] <= 0:
                    AHSHELL[CurCalYr, F, R, B] = AHSHELL[CurCalYr - 1, F, R, B]
                else:
                    AHSHELL[CurCalYr, F, R, B] = ANUM[F, R, B] / ADEN[F, R, B]
                if AHSHELL[CurCalYr, F, R, B] < LIMIT:
                    AHSHELL[CurCalYr, F, R, B] = LIMIT
                if CurCalYr <= RECSYEAR + 1:
                    AHSHELL[CurCalYr, F, R, B] = NHSHELL[CurCalYr, F, R, B]

    # new, replacement and average UECs
    EQCUEC = s["eqcuec"]
    EQCSUEC, EQCSIUEC, EQCNUEC, EQCNIUEC = s["eqcsuec"], s["eqcsiuec"], s["eqcnuec"], s["eqcniuec"]
    EQCHVUEC, EQCHVIUEC, EQCRUEC, EQCRIUEC = s["eqchvuec"], s["eqchviuec"], s["eqcruec"], s["eqcriuec"]
    EQCAUEC, EQCAHVUEC = s["eqcauec"], s["eqcahvuec"]
    WTEQCEFFN, WTEQCEFFHV, WTEQCEFFR = s["wteqceffn"], s["wteqceffhv"], s["wteqceffr"]
    WTEQCSQFHV, WTEQCEFFA = s["wteqcsqfhv"], s["wteqceffa"]
    EQR90FUT, EQR90RPFUT = s["eqr90fut"], s["eqr90rpfut"]
    EQREPFUT, EQADDFUT = s["eqrepfut"], s["eqaddfut"]
    for R in range(1, NUM_DIV + 1):
        for B in range(1, MNUMBLDG + 1):
            for RECCL in range(c0, c1 + 1):
                FAN = int(RTFFAN[RECCL])
                F = int(RTFUEL[RECCL])
                # S picks the square-footage adjustment: electric (2) or fossil (1)
                S = 2 if F == 4 else 1

                EQCSUEC[CurCalYr, RECCL, B, R] = (EQCUEC[R, RECCL, B] * RTBASEFF[RECSYEAR, RECCL]
                    / RTBASEFF[CurCalYr, RECCL] * EXSQFTADJ[CurCalYr, B, R, S])
                EQCSIUEC[CurCalYr, RECCL, B, R] = (EQCUEC[R, RECCL, B] * RTBASEFF[RECSYEAR, RECCL]
                    / RTBASEFF[CurCalYr, RECCL])

                if WTEQCEFFN[CurCalYr, RECCL, B, R] > 0.0:
                    EQCNUEC[CurCalYr, RECCL, B, R] = (EQCUEC[R, RECCL, B]
                        * WTEQCEFFN[CurCalYr, RECCL, B, R] * RTBASEFF[RECSYEAR, RECCL])
                    EQCNIUEC[CurCalYr, RECCL, B, R] = (EQCUEC[R, RECCL, B]
                        * WTEQCEFFN[CurCalYr, RECCL, B, R] * RTBASEFF[RECSYEAR, RECCL])
                else:
                    EQCNUEC[CurCalYr, RECCL, B, R] = EQCUEC[R, RECCL, B]
                    EQCNIUEC[CurCalYr, RECCL, B, R] = EQCUEC[R, RECCL, B]

                if WTEQCEFFHV[CurCalYr, RECCL, B, R] > 0.0:
                    EQCHVUEC[CurCalYr, RECCL, B, R] = (EQCUEC[R, RECCL, B] * WTEQCEFFHV[CurCalYr, RECCL, B, R]
                        * RTBASEFF[RECSYEAR, RECCL] * WTEQCSQFHV[CurCalYr, RECCL, B, R])
                    EQCHVIUEC[CurCalYr, RECCL, B, R] = (EQCUEC[R, RECCL, B]
                        * WTEQCEFFHV[CurCalYr, RECCL, B, R] * RTBASEFF[RECSYEAR, RECCL])
                else:
                    EQCHVUEC[CurCalYr, RECCL, B, R] = EQCUEC[R, RECCL, B] * WTEQCSQFHV[CurCalYr, RECCL, B, R]
                    EQCHVIUEC[CurCalYr, RECCL, B, R] = EQCUEC[R, RECCL, B]

                if WTEQCEFFR[CurCalYr, RECCL, B, R] > 0.0:
                    EQCRUEC[CurCalYr, RECCL, B, R] = (EQCUEC[R, RECCL, B] * WTEQCEFFR[CurCalYr, RECCL, B, R]
                        * RTBASEFF[RECSYEAR, RECCL] * EXSQFTADJ[CurCalYr, B, R, S])
                    EQCRIUEC[CurCalYr, RECCL, B, R] = (EQCUEC[R, RECCL, B]
                        * WTEQCEFFR[CurCalYr, RECCL, B, R] * RTBASEFF[RECSYEAR, RECCL])
                else:
                    EQCRUEC[CurCalYr, RECCL, B, R] = EQCUEC[R, RECCL, B] * EXSQFTADJ[CurCalYr, B, R, S]
                    EQCRIUEC[CurCalYr, RECCL, B, R] = EQCUEC[R, RECCL, B]

                # average UECs of replaced RECS-year stock and of post-RECS stock
                if CurCalYr - 1 == RECSYEAR:
                    EQCAUEC[CurCalYr, RECCL, B, R] = EQCNUEC[CurCalYr, RECCL, B, R]
                    EQCAHVUEC[CurCalYr, RECCL, B, R] = EQCHVUEC[CurCalYr, RECCL, B, R]
                    AFANUEC[RECSYEAR + 1, R, B] = NFANUEC[RECSYEAR + 1, R, B]
                else:
                    TEMP = f32(0.0)
                    TEMP1 = f32(0.0)
                    TEMP2 = f32(0.0)
                    for Y in range(RECSYEAR, CurCalYr):
                        TEMP = TEMP + EQR90FUT[Y, CurCalYr, RECCL, B, R] + EQR90RPFUT[Y, CurCalYr, RECCL, B, R]
                        TEMP1 = TEMP1 + (EQR90FUT[Y, CurCalYr, RECCL, B, R] + EQADDFUT[Y, CurCalYr, RECCL, B, R]
                                         + EQREPFUT[Y, CurCalYr, RECCL, B, R] + EQR90RPFUT[Y, CurCalYr, RECCL, B, R]) * FAN
                        TEMP2 = TEMP2 + EQADDFUT[Y, CurCalYr, RECCL, B, R] + EQREPFUT[Y, CurCalYr, RECCL, B, R]

                    if TEMP <= 0.0:
                        EQCAUEC[CurCalYr, RECCL, B, R] = EQCNUEC[CurCalYr, RECCL, B, R]
                    else:
                        EQCAUEC[CurCalYr, RECCL, B, R] = 0.0
                        for Y in range(RECSYEAR, CurCalYr):
                            EQCAUEC[CurCalYr, RECCL, B, R] = EQCAUEC[CurCalYr, RECCL, B, R] + (
                                EQR90FUT[Y, CurCalYr, RECCL, B, R] * EQCRUEC[Y, RECCL, B, R]
                                + EQR90RPFUT[Y, CurCalYr, RECCL, B, R] * EQCNIUEC[Y, RECCL, B, R]) / TEMP

                    # EIA quirk: AFANUEC is rewritten for every class, so the value the
                    # consumption loop uses comes from the last class (and its TEMP1)
                    if TEMP1 <= 0.0:
                        AFANUEC[CurCalYr, R, B] = NFANUEC[CurCalYr, R, B]
                    else:
                        AFANUEC[CurCalYr, R, B] = 0.0
                        for Y in range(RECSYEAR, CurCalYr):
                            AFANUEC[CurCalYr, R, B] = AFANUEC[CurCalYr, R, B] + (
                                EQR90FUT[Y, CurCalYr, RECCL, B, R] * EFANUEC[Y, R, B] * FAN
                                + EQADDFUT[Y, CurCalYr, RECCL, B, R] * NFANUEC[Y, R, B] * FAN
                                + EQREPFUT[Y, CurCalYr, RECCL, B, R] * NFANUEC[Y, R, B] * FAN
                                + EQR90RPFUT[Y, CurCalYr, RECCL, B, R] * NFANUEC[Y, R, B] * FAN) / TEMP1

                    if TEMP2 <= 0.0:
                        EQCAHVUEC[CurCalYr, RECCL, B, R] = EQCHVUEC[CurCalYr, RECCL, B, R]
                    else:
                        EQCAHVUEC[CurCalYr, RECCL, B, R] = 0.0
                        for Y in range(RECSYEAR, CurCalYr):
                            EQCAHVUEC[CurCalYr, RECCL, B, R] = EQCAHVUEC[CurCalYr, RECCL, B, R] + (
                                EQADDFUT[Y, CurCalYr, RECCL, B, R] * EQCHVUEC[Y, RECCL, B, R]
                                + EQREPFUT[Y, CurCalYr, RECCL, B, R] * EQCNUEC[Y, RECCL, B, R]) / TEMP2

    # average equipment efficiency
    for R in range(1, NUM_DIV + 1):
        for B in range(1, MNUMBLDG + 1):
            for RECCL in range(c0, c1 + 1):
                if CurCalYr == RECSYEAR + 1:
                    WTEQCEFFA[RECSYEAR + 1, RECCL, B, R] = WTEQCEFFN[RECSYEAR + 1, RECCL, B, R]
                else:
                    TEMP = f32(0.0)
                    for Y in range(RECSYEAR, CurCalYr):
                        TEMP = (TEMP + EQR90FUT[Y, CurCalYr, RECCL, B, R] + EQADDFUT[Y, CurCalYr, RECCL, B, R]
                                + EQREPFUT[Y, CurCalYr, RECCL, B, R] + EQR90RPFUT[Y, CurCalYr, RECCL, B, R])
                    if TEMP > 0.0:
                        WTEQCEFFA[CurCalYr, RECCL, B, R] = 0.0
                        for Y in range(RECSYEAR, CurCalYr):
                            WTEQCEFFA[CurCalYr, RECCL, B, R] = WTEQCEFFA[CurCalYr, RECCL, B, R] + (
                                (EQR90FUT[Y, CurCalYr, RECCL, B, R] * WTEQCEFFR[Y, RECCL, B, R])
                                + ((EQADDFUT[Y, CurCalYr, RECCL, B, R] * WTEQCEFFHV[Y, RECCL, B, R])
                                   + (EQREPFUT[Y, CurCalYr, RECCL, B, R] + EQR90RPFUT[Y, CurCalYr, RECCL, B, R])
                                   * WTEQCEFFN[Y, RECCL, B, R])) / TEMP
                    else:
                        WTEQCEFFA[CurCalYr, RECCL, B, R] = WTEQCEFFN[CurCalYr, RECCL, B, R]

    # clear this year's consumption variables
    HTRCON, FANCON = s["htrcon"], s["fancon"]
    Driver, Driver2 = s["driver"], s["driver2"]
    HTRCONWT, HTRCONIN = s["htrconwt"], s["htrconin"]
    FANCONWT, FANCONIN = s["fanconwt"], s["fanconin"]
    HTRCON[CurIYr, 1:NHTRFL, 1:NUM_DIV] = 0.0
    FANCON[CurIYr, 1:NUM_DIV] = 0.0
    Driver[CurIYr, 1:NHTRFL, 1:NUM_DIV, 1:MNUMBLDG] = 0.0
    Driver2[CurIYr, 1:NUM_DIV, 1:MNUMBLDG] = 0.0
    HTRCONWT[CurIYr, 1:NHTRFL, 1:NUM_DIV, 1:MNUMBLDG] = 0.0
    HTRCONIN[CurIYr, 1:NHTRFL, 1:NUM_DIV, 1:MNUMBLDG] = 0.0
    FANCONWT[CurIYr, 1:NUM_DIV, 1:MNUMBLDG] = 0.0
    FANCONIN[CurIYr, 1:NUM_DIV, 1:MNUMBLDG] = 0.0

    # the heat pump class lookups in EIA's code feed nothing and are skipped

    FHTRCON, FANEQCN, FANEQP, EQCEQCN = s["fhtrcon"], s["faneqcn"], s["faneqp"], s["eqceqcn"]
    for R in range(1, NUM_DIV + 1):
        for B in range(1, MNUMBLDG + 1):
            FANEQCN[CurIYr, 1, B, R] = 0.0
            FANEQP[CurCalYr, B, R] = 0.0
            for RECCL in range(c0, c1 + 1):
                F = int(RTFUEL[RECCL])
                FAN = int(RTFFAN[RECCL])
                S = 2 if F == 4 else 1
                FCON = int(FHTRCON[F])  # RTEK fuel number to NEMS consumption fuel number

                if F == 4:
                    ALPHA = f32(-0.30)  # was -0.15 before the 2009 stimulus act (smart grid)
                else:
                    ALPHA = f32(-0.15)

                # wood is priced like distillate and responds with a positive elasticity
                F2 = F
                if F == 5:
                    ALPHA = f32(0.50)
                if F == 5:
                    F2 = 1

                # efficiency rebound
                if CurCalYr > RECSYEAR + 1:
                    RBA = _powf(RTBASEFF[RECSYEAR, RECCL] * WTEQCEFFA[CurCalYr, RECCL, B, R], ALPHA)
                    RBR = _powf(RTBASEFF[RECSYEAR, RECCL] * WTEQCEFFR[CurCalYr, RECCL, B, R], ALPHA)
                    RBN = _powf(RTBASEFF[RECSYEAR, RECCL] * WTEQCEFFN[CurCalYr, RECCL, B, R], ALPHA)
                else:
                    RBA = f32(1.0)
                    RBR = f32(1.0)
                    RBN = f32(1.0)

                EH0 = EHSHELL[RECSYEAR, F, R, B]
                ehr = EHSHELL[CurCalYr, F, R, B] / EH0
                nhr = NHSHELL[CurCalYr, F, R, B] / EH0
                ahr = AHSHELL[CurCalYr, F, R, B] / EH0
                ese, add, rp90 = EQCESE[CurCalYr, RECCL, B, R], EQCADD[CurCalYr, RECCL, B, R], EQCRP90[CurCalYr, RECCL, B, R]
                rp90rp, sr90 = EQCRP90RP[CurCalYr, RECCL, B, R], EQCSR90[CurCalYr, RECCL, B, R]
                rep, sur = EQCREP[CurCalYr, RECCL, B, R], EQCSUR[CurCalYr, RECCL, B, R]

                # one value serves HTRCON, HTRCONWT and EQCEQCN: EIA writes the same expression three times
                core = (
                    (ese * EQCSUEC[CurCalYr, RECCL, B, R] * _powf(ehr, EXPO))
                    + (add * EQCHVUEC[CurCalYr, RECCL, B, R] * _powf(nhr, EXPO)) * RBN
                    + (rp90 * EQCRUEC[CurCalYr, RECCL, B, R] * _powf(ehr, EXPO)) * RBR
                    + (rp90rp * EQCNIUEC[CurCalYr, RECCL, B, R] * EXSQFTADJ[CurCalYr, B, R, S] * _powf(ehr, EXPO)) * RBN
                    + (sr90 * EQCAUEC[CurCalYr, RECCL, B, R] * _powf(ehr, EXPO)) * RBA
                    + (rep * EQCNUEC[CurCalYr, RECCL, B, R] * _powf(ahr, EXPO)) * RBN
                    + (sur * EQCAHVUEC[CurCalYr, RECCL, B, R] * _powf(ahr, EXPO)) * RBA)
                cons = HDDFACT[R] * LEAPYR * (core * rselast(s, F2, R, ALPHA, ef1, ef2, ef3, EUPR))

                HTRCON[CurIYr, FCON, R] = HTRCON[CurIYr, FCON, R] + cons
                HTRCONWT[CurIYr, FCON, R, B] = HTRCONWT[CurIYr, FCON, R, B] + cons

                HTRCONIN[CurIYr, FCON, R, B] = HTRCONIN[CurIYr, FCON, R, B] + (
                    (ese * EQCSIUEC[CurCalYr, RECCL, B, R] * ehr)
                    + (add * EQCHVIUEC[CurCalYr, RECCL, B, R] * nhr)
                    + (rp90 * EQCRIUEC[CurCalYr, RECCL, B, R] * ehr)
                    + (rp90rp * EQCNIUEC[CurCalYr, RECCL, B, R] * ehr)
                    + (sr90 * EQCAUEC[CurCalYr, RECCL, B, R] * ehr)
                    + (rep * EQCNIUEC[CurCalYr, RECCL, B, R] * ahr)
                    + (sur * EQCAHVUEC[CurCalYr, RECCL, B, R] * ahr))

                Driver[CurIYr, FCON, R, B] = Driver[CurIYr, FCON, R, B] + (ese + add + rp90rp + rp90 + sr90 + rep + sur)

                EQCEQCN[CurIYr, RECCL, B, R] = cons

                if F != 5:  # no fans for wood
                    rsf = rselast(s, F, R, ALPHA, ef1, ef2, ef3, EUPR)
                    fansum = (ese * FAN * EFANUEC[CurCalYr, R, B]
                              + (rp90 + rp90rp) * FAN * NFANUEC[CurCalYr, R, B]
                              + sr90 * FAN * AFANUEC[CurCalYr, R, B]
                              + (add + rep) * FAN * NFANUEC[CurCalYr, R, B]
                              + sur * FAN * AFANUEC[CurCalYr, R, B])
                    FANEQCN[CurIYr, 1, B, R] = FANEQCN[CurIYr, 1, B, R] + HDDFACT[R] * LEAPYR * fansum * rsf
                    # FANCON and FANCONWT write the first term as EQCESE*EFANUEC*FAN
                    fansum2 = (ese * EFANUEC[CurCalYr, R, B] * FAN
                               + (rp90 + rp90rp) * FAN * NFANUEC[CurCalYr, R, B]
                               + sr90 * FAN * AFANUEC[CurCalYr, R, B]
                               + (add + rep) * FAN * NFANUEC[CurCalYr, R, B]
                               + sur * FAN * AFANUEC[CurCalYr, R, B])
                    FANCON[CurIYr, R] = FANCON[CurIYr, R] + HDDFACT[R] * LEAPYR * fansum2 * rsf
                    FANCONWT[CurIYr, R, B] = FANCONWT[CurIYr, R, B] + HDDFACT[R] * LEAPYR * fansum2 * rsf
                    FANEQP[CurCalYr, B, R] = FANEQP[CurCalYr, B, R] + (ese + rp90 + sr90 + sur + rp90rp + rep + add) * FAN
                    FANCONIN[CurIYr, R, B] = FANCONIN[CurIYr, R, B] + (
                        (ese * FAN * FANIUEC[R, B]
                         + (add + rep + rp90 + rp90rp) * FAN * NFANIUEC[CurCalYr, R, B]
                         + (sur + sr90) * FAN * AFANUEC[CurCalYr, R, B]))
                    Driver2[CurIYr, R, B] = Driver2[CurIYr, R, B] + ese + add + rp90rp + rp90 + sr90 + rep + sur

    # intensity for the report writer: divide by the driver
    for R in range(1, NUM_DIV + 1):
        for FCON in range(1, NHTRFL + 1):
            for B in range(1, MNUMBLDG + 1):
                if Driver[CurIYr, FCON, R, B] > 0:
                    HTRCONIN[CurIYr, FCON, R, B] = HTRCONIN[CurIYr, FCON, R, B] / Driver[CurIYr, FCON, R, B]
                # EIA quirk: this sits inside the FCON loop, so FANCONIN is divided NHTRFL times
                if Driver2[CurIYr, R, B] > 0:
                    FANCONIN[CurIYr, R, B] = FANCONIN[CurIYr, R, B] / Driver2[CurIYr, R, B]
