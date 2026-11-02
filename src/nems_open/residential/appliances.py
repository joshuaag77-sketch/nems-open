"""Clothes dryers, refrigerators and standalone freezers (resd.f).

Each end use has three routines, as in EIA's code:
  *TEC  technology choice: life-cycle cost, logit weights, new and replacement
        market shares, share-weighted efficiency
  *ADD  equipment added and replaced, vintaged survival, purchases by type
  *CON  unit energy consumption and fuel consumption

RDRYTEC/RDRYADD/RDRYCON, RREFTEC/RREFADD/RREFCON, RFRZTEC/RFRZADD/RFRZCON.
Debug and AppBetaData.txt writes are skipped everywhere.

State the dumps do not hold, and what the port does about it:
  * DECAY is a local EIA sets only on the first NEMS iteration (CURITR = 1) and
    then keeps; it is rebuilt here from ResDiscountRate and Tenure on every call,
    which gives the same number because both are constants.
  * COSTTRSW is a PARAMETER (= 0 in the rtek include), so CAPITAL is RTEQCOST.
  * LEAPYR is a local of RESD set from the year (366/365 in leap years up to the
    last STEO year, else 1); it is rebuilt from CurCalYr.
"""

import numpy as np

from nems_open.residential.common import BASEYR, ENDYR, RECSYEAR, expf, f32, powi
from nems_open.residential.helpers import eqcost, replace, rselast, svrte

NUM_R = 9  # MNUMCR-2 census divisions
NUM_B = 3  # MNUMBLDG
COSTTRSW = 0  # PARAMETER in the rtek include
LASTSTEOYR = 2026


def _text(v) -> str:
    return v.decode("latin-1").strip() if isinstance(v, bytes) else str(v).strip()


def _decay(s):
    """DECAY = (1-((1+ResDiscountRate)**(-Tenure)))/ResDiscountRate (REAL**REAL: powf)."""
    rate, ten = f32(s["resdiscountrate"]), f32(s["tenure"])
    return (f32(1) - np.power(f32(1) + rate, -ten)) / rate


def _leapyr(y):
    # MOD(CurCalYr,4).EQ.0 .AND. CurCalYr.LE.LastSTEOYr
    return f32(366.0) / f32(365.0) if (y % 4 == 0 and y <= LASTSTEOYR) else f32(365.0) / f32(365.0)


def _map_electricity_price(s, eupr):
    """PRICES(4,R,CurCalYr) from PELRSOUT; skipped when the dump has no PELRSOUT."""
    Y, Y1 = int(s["curcalyr"]), int(s["curiyr"])
    gdp = s["mc_jpgdp"]
    for r in range(1, NUM_R + 1):
        s["prices"][4, r, Y] = s["pelrsout"][r, Y1, eupr] * (gdp[int(s["rtekdollaryr"]) - BASEYR + 1] / gdp[-2])


def _capital(s, recty, Y):
    if COSTTRSW == 1:
        return eqcost(s, recty, Y, "CAP")
    return s["rteqcost"][recty]


def _rselast_f0(s, f, r, alpha, ef1, ef2, ef3, eupr):
    """RSELAST for ALPHA = 0 (refrigerators, freezers): every factor is x**0 = 1,
    so PELRSOUT is not needed."""
    if alpha == 0.0:
        return f32(1.0)
    return rselast(s, f, r, alpha, ef1, ef2, ef3, eupr)


# ---------------------------------------------------------------------------
# Clothes dryers
# ---------------------------------------------------------------------------

def rdrytec(s: dict) -> None:
    """RDRYTEC: clothes dryer technology choice (EU = 7)."""
    EU = 7
    Y, Y1 = int(s["curcalyr"]), int(s["curiyr"])
    s["alpha1"] = ALPHA1 = f32(-0.50)
    P = s["prices"]
    eupt, typt, tyct = s["rtcleupt"], s["rttyeupt"], s["rttypect"]
    RTINITYR, RTLASTYR, RTCENDIV = s["rtinityr"], s["rtlastyr"], s["rtcendiv"]
    EQWTN = np.zeros((64, NUM_B + 1, NUM_R + 3), dtype=np.float32)
    EQWTR = np.zeros_like(EQWTN)
    TOTEWTN = np.zeros_like(EQWTN)
    TOTEWTR = np.zeros_like(EQWTN)
    OPCOST = [f32(0), f32(0), f32(0)]
    RTEFFAC = [f32(0), f32(0), f32(0)]

    with np.errstate(all="ignore"):
        _map_electricity_price(s, 5)
        DECAY = _decay(s)

        for B in range(1, NUM_B + 1):
            for R in range(1, NUM_R + 1):
                for RECCL in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                    EQC = int(s["rtcleqcl"][RECCL])
                    TOTEWTN[EQC, B, R] = 0.0
                    TOTEWTR[EQC, B, R] = 0.0

        for R in range(1, NUM_R + 1):
            for B in range(1, NUM_B + 1):
                for RECTY in range(int(typt[EU]) + 1, int(typt[EU + 1]) + 1):
                    if RTINITYR[RECTY] <= Y <= RTLASTYR[RECTY]:
                        if RTCENDIV[RECTY] == R:
                            EQC = int(s["rttyeqcl"][RECTY])
                            EQT = int(s["rteqtype"][RECTY])
                            RECCL = int(eupt[EU]) + EQC
                            F = int(s["rtfuel"][RECCL])

                            if s["rteqeff"][RECTY] != 0.0:
                                RTEFFAC[1] = s["eqceff"][Y, RECCL] / s["rteqeff"][RECTY]
                                RTEFFAC[2] = s["rtbaseff"][RECSYEAR, RECCL] / s["rteqeff"][RECTY]
                            else:
                                RTEFFAC[1] = s["rtbaseff"][RECSYEAR, RECCL]
                                RTEFFAC[2] = s["rtbaseff"][RECSYEAR, RECCL]

                            CAPITAL = _capital(s, RECTY, Y)

                            OPCOST[1] = P[F, R, Y] * s["eqcuec"][R, RECCL, B] * RTEFFAC[1]
                            OPCOST[2] = P[F, R, Y] * s["eqcuec"][R, RECCL, B] * RTEFFAC[2]

                            if Y > 2008 and P[F, R, Y] > P[F, R, RECSYEAR]:
                                HRDRATE = s["rtecbta1"][RECTY] / s["rtecbta2"][RECTY]
                                ELIGBLE = HRDRATE - f32(0.07)
                                s["hrdrate"], s["eligble"] = HRDRATE, ELIGBLE
                                if ELIGBLE > 0.0:
                                    HRDADJ = ELIGBLE * np.power(P[F, R, Y] / P[F, R, RECSYEAR], ALPHA1)
                                    s["hrdadj"] = HRDADJ
                                    s["beta1dr"][RECTY] = (HRDADJ + f32(0.07)) * s["rtecbta2"][RECTY]
                                else:
                                    s["beta1dr"][RECTY] = s["rtecbta1"][RECTY]
                            else:
                                s["beta1dr"][RECTY] = s["rtecbta1"][RECTY]

                            s["lfcy"][EQT, B, R, 1] = s["rteqcost"][RECTY] + (OPCOST[1] * DECAY)
                            s["lfcy"][EQT, B, R, 2] = s["rteqcost"][RECTY] + (OPCOST[2] * DECAY)

                            ECTEMP = s["rtecbias"][RECTY] + s["beta1dr"][RECTY] * CAPITAL

                            EQWTN[EQT, B, R] = expf(ECTEMP + (s["rtecbta2"][RECTY] * OPCOST[2])
                                                      + (s["rtecbta3"][RECTY] * s["lfcy"][EQT, B, R, 2]))
                            TOTEWTN[EQC, B, R] = TOTEWTN[EQC, B, R] + EQWTN[EQT, B, R]
                            EQWTR[EQT, B, R] = expf(ECTEMP + (s["rtecbta2"][RECTY] * OPCOST[1])
                                                      + (s["rtecbta3"][RECTY] * s["lfcy"][EQT, B, R, 1]))
                            TOTEWTR[EQC, B, R] = TOTEWTR[EQC, B, R] + EQWTR[EQT, B, R]

        # New and replacement market shares
        for R in range(1, NUM_R + 1):
            for B in range(1, NUM_B + 1):
                TYPE = int(tyct[EU])
                for RECTY in range(int(typt[EU]) + 1, int(typt[EU + 1]) + 1):
                    if RTINITYR[RECTY] <= Y <= RTLASTYR[RECTY]:
                        if RTCENDIV[RECTY] == R:
                            TYPE += 1
                            EQC = int(s["rttyeqcl"][RECTY])
                            EQT = int(s["rteqtype"][RECTY])
                            if TOTEWTN[EQC, B, R] > 0.0:
                                s["neqtshr"][Y, TYPE, B, R] = EQWTN[EQT, B, R] / TOTEWTN[EQC, B, R]
                                s["reqtshr"][Y, TYPE, B, R] = EQWTR[EQT, B, R] / TOTEWTR[EQC, B, R]
                            else:
                                s["neqtshr"][Y, TYPE, B, R] = 0.0
                                s["reqtshr"][Y, TYPE, B, R] = 0.0

        # Share-weighted efficiency (the weights are efficiency-based, so the mean is of 1/eff)
        for R in range(1, NUM_R + 1):
            for B in range(1, NUM_B + 1):
                for RECCL in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                    EQC = int(s["rtcleqcl"][RECCL])
                    DENOM = f32(0)
                    DENOM2 = f32(0)
                    RECAR, EQTAR = [], []
                    for RECTY in range(int(typt[EU]) + 1, int(typt[EU + 1]) + 1):
                        if s["rttyeqcl"][RECTY] == EQC and RTINITYR[RECTY] <= Y <= RTLASTYR[RECTY]:
                            if RTCENDIV[RECTY] == R:
                                EQT = int(s["rteqtype"][RECTY])
                                RECAR.append(RECTY)
                                EQTAR.append(EQT)
                                DENOM = DENOM + EQWTN[EQT, B, R]
                                DENOM2 = DENOM2 + EQWTR[EQT, B, R]

                    if DENOM <= 0.0:
                        s["wteqceffn"][Y, RECCL, B, R] = f32(1) / s["rtbaseff"][RECSYEAR, RECCL]
                    else:
                        SUM = f32(0.0)
                        for RECTY, EQT in zip(RECAR, EQTAR):
                            SUM = SUM + (EQWTN[EQT, B, R] / s["rteqeff"][RECTY])
                        s["wteqceffn"][Y, RECCL, B, R] = SUM / DENOM

                    if DENOM2 <= 0.0:
                        s["wteqceffr"][Y, RECCL, B, R] = f32(1) / s["rtbaseff"][RECSYEAR, RECCL]
                    else:
                        SUM2 = f32(0.0)
                        for RECTY, EQT in zip(RECAR, EQTAR):
                            SUM2 = SUM2 + (EQWTR[EQT, B, R] / s["rteqeff"][RECTY])
                        s["wteqceffr"][Y, RECCL, B, R] = SUM2 / DENOM2


def rdryadd(s: dict) -> None:
    """RDRYADD: clothes dryers added and replaced (EU = 7). Includes the electric
    dryer catch-up (EQCND90) and switching between fuels in single-family homes
    through REPLACE."""
    EU = 7
    CY = int(s["curcalyr"])
    max_eldry_pen = f32(0.90)
    eupt, typt, tyct = s["rtcleupt"], s["rttyeupt"], s["rttypect"]
    RTINITYR, RTLASTYR, RTCENDIV = s["rtinityr"], s["rtlastyr"], s["rtcendiv"]
    HDR = s["hdr"]
    EQCADD, EQCSR90, EQCRP90RP, EQCSUR, EQCREP = (s[k] for k in ("eqcadd", "eqcsr90", "eqcrp90rp", "eqcsur", "eqcrep"))
    EQCRP90, EQCND90, EQCESE, EQCRET = s["eqcrp90"], s["eqcnd90"], s["eqcese"], s["eqcret"]
    NEWDRYSAT = s["newdrysat"]

    with np.errstate(all="ignore"):
        for R in range(1, NUM_R + 1):
            for B in range(1, NUM_B + 1):
                for RECCL in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                    EQCADD[CY, RECCL, B, R] = 0.0
                    EQCSR90[CY, RECCL, B, R] = 0.0
                    EQCRP90RP[CY, RECCL, B, R] = 0.0
                    EQCSUR[CY, RECCL, B, R] = 0.0
                    EQCREP[CY, RECCL, B, R] = 0.0

        # Dryers added this year. EIA updates NEWDRYSAT inside the record loop, so it
        # is redone for every valid record; each pass starts from last year's value,
        # so the result is the same.
        for R in range(1, NUM_R + 1):
            for B in range(1, NUM_B + 1):
                TYPE = int(tyct[EU])
                for RECTY in range(int(typt[EU]) + 1, int(typt[EU + 1]) + 1):
                    if RTINITYR[RECTY] <= CY <= RTLASTYR[RECTY]:
                        if RTCENDIV[RECTY] == R:
                            TYPE += 1
                            EQC = int(s["rttyeqcl"][RECTY])
                            RECCL = int(eupt[EU]) + EQC
                            if CY > RECSYEAR + 1:
                                NEWDRYSAT[CY, 2, B, R] = NEWDRYSAT[CY - 1, 2, B, R] * f32(1.0064)
                                NEWDRYSAT[CY, 1, B, R] = NEWDRYSAT[CY - 1, 1, B, R]
                            if (NEWDRYSAT[CY, 1, B, R] + NEWDRYSAT[CY, 2, B, R]) > f32(1.0000):
                                NEWDRYSAT[CY, 2, B, R] = f32(1.0000)
                            EQCADD[CY, RECCL, B, R] = (EQCADD[CY, RECCL, B, R] + (
                                s["neqtshr"][CY, TYPE, B, R] * s["hseadd"][CY, B, R] * NEWDRYSAT[CY, EQC, B, R]))

        for R in range(1, NUM_R + 1):
            for B in range(1, NUM_B + 1):
                for RECCL in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                    SA = f32(0.0)
                    if _text(s["rtclname"][RECCL]) == "ELEC_DRY":
                        if (EQCND90[CY, RECCL, B, R] / s["eh"][CY, B, R]) >= max_eldry_pen:
                            EQCND90[CY, RECCL, B, R] = (EQCESE[RECSYEAR, RECCL, B, R] * powi(HDR[B], CY - RECSYEAR)
                                                        - EQCESE[RECSYEAR, RECCL, B, R] * powi(HDR[B], CY - RECSYEAR))
                        else:
                            EQCND90[CY, RECCL, B, R] = (
                                EQCESE[RECSYEAR, RECCL, B, R] * powi(HDR[B], CY - RECSYEAR) * (f32(1.) + s["eldrypr"][B, R])
                                - EQCESE[RECSYEAR, RECCL, B, R] * powi(HDR[B], CY - RECSYEAR))
                    else:
                        EQCND90[CY, RECCL, B, R] = 0.0

                    if CY == RECSYEAR + 1:
                        EQCRP90[CY, RECCL, B, R] = (EQCRET[CY, RECCL]
                                                    * EQCESE[RECSYEAR, RECCL, B, R] * powi(HDR[B], CY - RECSYEAR))
                    else:
                        EQCRP90[CY, RECCL, B, R] = ((EQCRET[CY, RECCL] - EQCRET[CY - 1, RECCL])
                                                    * EQCESE[RECSYEAR, RECCL, B, R] * powi(HDR[B], CY - RECSYEAR))

                    alpha, k, lam = s["rtalpha"][RECCL], s["rtk"][RECCL], s["rtlambda"][RECCL]
                    if CY > RECSYEAR + 1:
                        for Y in range(RECSYEAR + 1, CY):
                            TEMP = CY - Y
                            ESR = svrte(alpha, TEMP - 1, k, lam) - svrte(alpha, TEMP, k, lam)
                            EQCRP90RP[CY, RECCL, B, R] = (EQCRP90RP[CY, RECCL, B, R] + (
                                EQCRP90[Y, RECCL, B, R] * ESR * powi(HDR[B], TEMP)
                                + EQCRP90RP[Y, RECCL, B, R] * ESR * powi(HDR[B], TEMP)
                                + EQCND90[Y, RECCL, B, R] * ESR * powi(HDR[B], TEMP)))
                    EQCRP90RP[CY, RECCL, B, R] = EQCRP90RP[CY, RECCL, B, R] + EQCND90[CY, RECCL, B, R]
                    if CY > RECSYEAR + 1:
                        for Y in range(RECSYEAR + 1, CY):
                            TEMP = CY - Y
                            ESR = svrte(alpha, TEMP, k, lam)
                            EQCSR90[CY, RECCL, B, R] = (EQCSR90[CY, RECCL, B, R] + (
                                EQCRP90[Y, RECCL, B, R] * ESR * powi(HDR[B], TEMP)
                                + EQCRP90RP[Y, RECCL, B, R] * ESR * powi(HDR[B], TEMP)
                                + EQCND90[Y, RECCL, B, R] * ESR * powi(HDR[B], TEMP)))
                            HSR = powi(HDR[B], TEMP)
                            SA = SA + EQCADD[Y, RECCL, B, R] * HSR
                            EQCSUR[CY, RECCL, B, R] = (EQCSUR[CY, RECCL, B, R] + (
                                (EQCADD[Y, RECCL, B, R] + EQCREP[Y, RECCL, B, R]) * (HSR * ESR)))

                    # Replacements of the new vintage. Single-family homes may switch
                    # fuel (REPLACE); other buildings replace with like.
                    if B == 1:
                        s["oeqcrep"][CY, RECCL, 1, R] = SA - EQCSUR[CY, RECCL, B, R]
                        replace(s, EU, R, B, RECCL, 1)
                    else:
                        EQCREP[CY, RECCL, B, R] = SA - EQCSUR[CY, RECCL, B, R]

        # Replacements in RECS-year single-family homes
        B = 1
        for R in range(1, NUM_R + 1):
            for RECCL in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                s["oeqcrp90"][CY, RECCL, B, R] = EQCRP90[CY, RECCL, 1, R]
                s["oeqcrp90r"][CY, RECCL, B, R] = EQCRP90RP[CY, RECCL, 1, R]
                replace(s, EU, R, B, RECCL, 2)

        B = 1
        for R in range(1, NUM_R + 1):
            for RECCL in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                s["switchto"][CY, RECCL, B, R] = 0.0
                s["switchtor"][CY, RECCL, B, R] = 0.0
                for RECCLSW in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                    if RECCLSW != RECCL:
                        s["switchto"][CY, RECCL, B, R] = s["switchto"][CY, RECCL, B, R] + s["eqcsw90"][CY, RECCLSW, RECCL, B, R]
                        s["switchtor"][CY, RECCL, B, R] = s["switchtor"][CY, RECCL, B, R] + s["eqcsw90r"][CY, RECCLSW, RECCL, B, R]

        B = 1
        for R in range(1, NUM_R + 1):
            for RECCL in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                EQCRP90[CY, RECCL, B, R] = EQCRP90[CY, RECCL, B, R] - s["switches"][CY, RECCL, B, R]
                EQCRP90RP[CY, RECCL, B, R] = (EQCRP90RP[CY, RECCL, B, R] - s["switchesr"][CY, RECCL, B, R]
                                              + s["switchtor"][CY, RECCL, B, R] + s["switchto"][CY, RECCL, B, R])

        # SWF and SWT (switch totals) are locals EIA never uses again; not kept.

        _vintage_future(s, EU)
        _purchases(s, EU)

        # Gas dryer count as a proxy for gas customers
        if CY == RECSYEAR + 1 and int(s["curitr"]) == 1:
            for R in range(1, NUM_R + 1):
                s["dryertot"][RECSYEAR, R] = 0.0
                for B in range(1, NUM_B + 1):
                    s["dryertot"][RECSYEAR, R] = s["dryertot"][RECSYEAR, R] + EQCESE[RECSYEAR, 26, B, R]
        else:
            for R in range(1, NUM_R + 1):
                s["dryertot"][CY, R] = 0.0
                for B in range(1, NUM_B + 1):
                    s["dryertot"][CY, R] = (s["dryertot"][CY, R] + EQCESE[CY, 26, B, R] + EQCADD[CY, 26, B, R]
                                            + EQCRP90[CY, 26, B, R] + EQCRP90RP[CY, 26, B, R] + EQCSUR[CY, 26, B, R]
                                            + EQCREP[CY, 26, B, R] + EQCSR90[CY, 26, B, R])

        for R in range(1, NUM_R + 1):
            if CY == RECSYEAR + 1 and int(s["curitr"]) == 1:
                if s["dryertot"][RECSYEAR, R] > s["rsgascust"][RECSYEAR, R]:
                    s["rsgascust"][RECSYEAR, R] = s["dryertot"][RECSYEAR, R]
            else:
                if s["dryertot"][CY, R] > s["rsgascust"][CY, R]:
                    s["rsgascust"][CY, R] = s["dryertot"][CY, R]


def _vintage_future(s, EU):
    """Vintage the equipment bought this year into every future year (EQR90FUT,
    EQR90RPFUT, EQREPFUT, EQADDFUT); the same block ends RDRYADD, RREFADD, RFRZADD."""
    CY = int(s["curcalyr"])
    eupt, HDR = s["rtcleupt"], s["hdr"]
    for B in range(1, NUM_B + 1):
        for R in range(1, NUM_R + 1):
            for RECCL in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                for Y in range(CY, ENDYR + 1):
                    TEMP = Y - CY
                    HSR = powi(HDR[B], TEMP)
                    ESR = svrte(s["rtalpha"][RECCL], TEMP, s["rtk"][RECCL], s["rtlambda"][RECCL])
                    s["eqr90fut"][CY, Y, RECCL, B, R] = (s["eqcrp90"][CY, RECCL, B, R] * ESR * HSR)
                    s["eqr90rpfut"][CY, Y, RECCL, B, R] = (s["eqcrp90rp"][CY, RECCL, B, R] * ESR * HSR)
                    s["eqrepfut"][CY, Y, RECCL, B, R] = (s["eqcrep"][CY, RECCL, B, R] * ESR * HSR)
                    s["eqaddfut"][CY, Y, RECCL, B, R] = (s["eqcadd"][CY, RECCL, B, R] * ESR * HSR)


def _purchases(s, EU):
    """HEATINGTYPEPURCH by equipment type, for investment analysis (all three ADD routines)."""
    Y = int(s["curcalyr"])
    eupt, typt, tyct = s["rtcleupt"], s["rttyeupt"], s["rttypect"]
    H = s["heatingtypepurch"]
    for B in range(1, NUM_B + 1):
        for R in range(1, NUM_R + 1):
            TYPE = int(tyct[EU])
            for RECTY in range(int(typt[EU]) + 1, int(typt[EU + 1]) + 1):
                if s["rtinityr"][RECTY] <= Y <= s["rtlastyr"][RECTY]:
                    if s["rtcendiv"][RECTY] == R:
                        TYPE += 1
                        EQC = int(s["rttyeqcl"][RECTY])
                        RECCL = int(eupt[EU]) + EQC
                        H[Y, TYPE, B, R, 1] = (s["neqtshr"][Y, TYPE, B, R] * s["eqcadd"][Y, RECCL, B, R])
                        H[Y, TYPE, B, R, 2] = (s["neqtshr"][Y, TYPE, B, R]
                                               * (s["eqcrep"][Y, RECCL, B, R] + s["eqcrp90rp"][Y, RECCL, B, R])
                                               + s["reqtshr"][Y, TYPE, B, R] * s["eqcrp90"][Y, RECCL, B, R])


def _eqcauec(s, RECCL, B, D):
    """EQCAUEC, the stock-average UEC from the vintaged equipment (same in all CON routines)."""
    CY = int(s["curcalyr"])
    if CY == RECSYEAR + 1:
        s["eqcauec"][CY, RECCL, B, D] = s["eqcnuec"][CY, RECCL, B, D]
    else:
        TEMP = f32(0.0)
        for Y in range(RECSYEAR, CY):
            TEMP = (TEMP + s["eqr90fut"][Y, CY, RECCL, B, D] + s["eqaddfut"][Y, CY, RECCL, B, D]
                    + s["eqrepfut"][Y, CY, RECCL, B, D] + s["eqr90rpfut"][Y, CY, RECCL, B, D])
        if TEMP <= 0.0:
            s["eqcauec"][CY, RECCL, B, D] = s["eqcnuec"][CY, RECCL, B, D]
        else:
            s["eqcauec"][CY, RECCL, B, D] = 0.0
            for Y in range(RECSYEAR, CY):
                s["eqcauec"][CY, RECCL, B, D] = s["eqcauec"][CY, RECCL, B, D] + (
                    (s["eqr90fut"][Y, CY, RECCL, B, D] * s["eqcruec"][Y, RECCL, B, D])
                    + ((s["eqaddfut"][Y, CY, RECCL, B, D] + s["eqrepfut"][Y, CY, RECCL, B, D]
                        + s["eqr90rpfut"][Y, CY, RECCL, B, D]) * s["eqcnuec"][Y, RECCL, B, D])) / TEMP


def _wteqceffa(s, EU):
    """WTEQCEFFA, the stock-average efficiency (same in all CON routines)."""
    CY = int(s["curcalyr"])
    eupt = s["rtcleupt"]
    for B in range(1, NUM_B + 1):
        for D in range(1, NUM_R + 1):
            for RECCL in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                if CY == RECSYEAR + 1:
                    s["wteqceffa"][RECSYEAR + 1, RECCL, B, D] = s["wteqceffn"][RECSYEAR + 1, RECCL, B, D]
                else:
                    TEMP = f32(0.0)
                    for Y in range(RECSYEAR, CY):
                        TEMP = (TEMP + s["eqr90fut"][Y, CY, RECCL, B, D] + s["eqaddfut"][Y, CY, RECCL, B, D]
                                + s["eqrepfut"][Y, CY, RECCL, B, D] + s["eqr90rpfut"][Y, CY, RECCL, B, D])
                    if TEMP > 0.0:
                        s["wteqceffa"][CY, RECCL, B, D] = 0.0
                        for Y in range(RECSYEAR, CY):
                            s["wteqceffa"][CY, RECCL, B, D] = s["wteqceffa"][CY, RECCL, B, D] + (
                                (s["eqr90fut"][Y, CY, RECCL, B, D] * s["wteqceffr"][Y, RECCL, B, D])
                                + ((s["eqaddfut"][Y, CY, RECCL, B, D] + s["eqrepfut"][Y, CY, RECCL, B, D]
                                    + s["eqr90rpfut"][Y, CY, RECCL, B, D]) * s["wteqceffn"][Y, RECCL, B, D])) / TEMP
                    else:
                        s["wteqceffa"][CY, RECCL, B, D] = s["wteqceffn"][CY, RECCL, B, D]


def _stock_efficiency(s, EU):
    """RTBASEFF(CurCalYr) follows the stock efficiency once past the RECS year."""
    CY = int(s["curcalyr"])
    eupt = s["rtcleupt"]
    if CY >= RECSYEAR + 1:
        for RECCL in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
            s["rtbaseff"][CY, RECCL] = s["stkeff"][CY, RECCL]


def rdrycon(s: dict) -> None:
    """RDRYCON: clothes dryer UECs and consumption by fuel (EU = 7).
    Needs PELRSOUT in the state for electric dryers (RSELAST)."""
    EU, EUPR = 7, 5
    CY, IY = int(s["curcalyr"]), int(s["curiyr"])
    eupt = s["rtcleupt"]
    ef1, ef2, ef3 = f32(.5), f32(.35), f32(.15)
    ALPHA = f32(-.15)
    LEAPYR = _leapyr(CY)
    RTBASEFF = s["rtbaseff"]

    with np.errstate(all="ignore"):
        _map_electricity_price(s, EUPR)
        _stock_efficiency(s, EU)

        for D in range(1, NUM_R + 1):
            for B in range(1, NUM_B + 1):
                for RECCL in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                    # Dryers use eff(RECS)/eff(now): a dryer rating is energy per load, not a COP
                    s["eqcsuec"][CY, RECCL, B, D] = s["eqcuec"][D, RECCL, B] * (RTBASEFF[RECSYEAR, RECCL] / RTBASEFF[CY, RECCL])
                    if s["wteqceffn"][CY, RECCL, B, D] > 0.0:
                        s["eqcnuec"][CY, RECCL, B, D] = (s["eqcuec"][D, RECCL, B]
                                                         * s["wteqceffn"][CY, RECCL, B, D] * RTBASEFF[RECSYEAR, RECCL])
                    else:
                        s["eqcnuec"][CY, RECCL, B, D] = s["eqcuec"][D, RECCL, B]

                    if s["wteqceffr"][CY, RECCL, B, D] > 0.0:
                        s["eqcruec"][CY, RECCL, B, D] = (s["eqcuec"][D, RECCL, B]
                                                         * s["wteqceffr"][CY, RECCL, B, D] * RTBASEFF[RECSYEAR, RECCL])
                    else:
                        s["eqcruec"][CY, RECCL, B, D] = s["eqcuec"][D, RECCL, B]

                    _eqcauec(s, RECCL, B, D)

        _wteqceffa(s, EU)

        ndry = int(s["ndryfl"])
        s["drycon"][IY, 1:ndry, 1:NUM_R] = 0.0
        s["dryconin"][IY, 1:ndry, 1:NUM_R, 1:NUM_B] = 0.0
        s["driver"][IY, 1:ndry, 1:NUM_R, 1:NUM_B] = 0.0
        s["dryconwt"][IY, 1:ndry, 1:NUM_R, 1:NUM_B] = 0.0

        for D in range(1, NUM_R + 1):
            for B in range(1, NUM_B + 1):
                for RECCL in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                    F = int(s["rtfuel"][RECCL])
                    FCON = int(s["fdrycon"][F])
                    ESE, ADD = s["eqcese"][CY, RECCL, B, D], s["eqcadd"][CY, RECCL, B, D]
                    RP90, RP90RP = s["eqcrp90"][CY, RECCL, B, D], s["eqcrp90rp"][CY, RECCL, B, D]
                    SR90, REP, SUR = s["eqcsr90"][CY, RECCL, B, D], s["eqcrep"][CY, RECCL, B, D], s["eqcsur"][CY, RECCL, B, D]
                    SUEC, NUEC = s["eqcsuec"][CY, RECCL, B, D], s["eqcnuec"][CY, RECCL, B, D]
                    RUEC, AUEC = s["eqcruec"][CY, RECCL, B, D], s["eqcauec"][CY, RECCL, B, D]

                    if CY == RECSYEAR + 1:
                        tot = ((ESE * SUEC) + (ADD * NUEC) + (RP90RP * NUEC) + (RP90 * RUEC))
                        sel = rselast(s, F, D, ALPHA, ef1, ef2, ef3, EUPR)
                        s["drycon"][IY, FCON, D] = s["drycon"][IY, FCON, D] + LEAPYR * tot * sel
                        s["dryconwt"][IY, FCON, D, B] = s["dryconwt"][IY, FCON, D, B] + LEAPYR * tot * sel
                        if ESE + ADD + RP90RP + RP90 > 0.:
                            s["dryconin"][IY, FCON, D, B] = s["dryconin"][IY, FCON, D, B] + tot
                            s["driver"][IY, FCON, D, B] = s["driver"][IY, FCON, D, B] + (ESE + ADD + RP90RP + RP90)
                        s["eqceqcn"][IY, RECCL, B, D] = LEAPYR * tot * sel
                    else:
                        if F == 4:
                            ALPHA = f32(-0.30)  # was -0.15 before ARRA 2009; permanent
                        else:
                            ALPHA = f32(-0.15)
                        tot = ((ESE * SUEC) + (ADD * NUEC) + (RP90 * RUEC) + (RP90RP * NUEC)
                               + (SR90 * AUEC) + (REP * NUEC) + (SUR * AUEC))
                        sel = rselast(s, F, D, ALPHA, ef1, ef2, ef3, EUPR)
                        s["drycon"][IY, FCON, D] = s["drycon"][IY, FCON, D] + LEAPYR * tot * sel
                        s["dryconwt"][IY, FCON, D, B] = s["dryconwt"][IY, FCON, D, B] + LEAPYR * tot * sel
                        if ESE + ADD + RP90RP + RP90 + SR90 + REP + SUR > 0.:
                            s["dryconin"][IY, FCON, D, B] = s["dryconin"][IY, FCON, D, B] + tot
                            s["driver"][IY, FCON, D, B] = s["driver"][IY, FCON, D, B] + (
                                ESE + ADD + RP90RP + RP90 + SR90 + REP + SUR)
                        s["eqceqcn"][IY, RECCL, B, D] = LEAPYR * tot * sel

        for R in range(1, NUM_R + 1):
            for FCON in range(1, ndry + 1):
                for B in range(1, NUM_B + 1):
                    if s["driver"][IY, FCON, R, B] > 0:
                        s["dryconin"][IY, FCON, R, B] = s["dryconin"][IY, FCON, R, B] / s["driver"][IY, FCON, R, B]


# ---------------------------------------------------------------------------
# Refrigerators
# ---------------------------------------------------------------------------

def rreftec(s: dict) -> None:
    """RREFTEC: refrigerator technology choice (EU = 8). New and replacement
    choices are the same; types compete within top-, side- and bottom-mount groups."""
    EU, EUPR = 8, 6
    Y = int(s["curcalyr"])
    s["alpha1"] = ALPHA1 = f32(-0.50)
    FACTOR = f32(.003412)  # efficiency to UEC
    P = s["prices"]
    eupt, typt, tyct = s["rtcleupt"], s["rttyeupt"], s["rttypect"]
    RTINITYR, RTLASTYR, RTCENDIV = s["rtinityr"], s["rtlastyr"], s["rtcendiv"]
    EQWTN = np.zeros((64, NUM_B + 1, NUM_R + 3), dtype=np.float32)
    EQWTR = np.zeros_like(EQWTN)
    TOTEWTN = np.zeros_like(EQWTN)
    TOTEWTR = np.zeros_like(EQWTN)
    TMFSHR = np.zeros((NUM_B + 1, NUM_R + 1), dtype=np.float32)
    SMFSHR = np.zeros_like(TMFSHR)
    BMFSHR = np.zeros_like(TMFSHR)
    UEC = {}

    with np.errstate(all="ignore"):
        _map_electricity_price(s, EUPR)
        DECAY = _decay(s)

        for R in range(1, NUM_R + 1):
            for B in range(1, NUM_B + 1):
                for RECCL in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                    EQC = int(s["rtcleqcl"][RECCL])
                    TOTEWTN[EQC, B, R] = 0.0
                    TOTEWTR[EQC, B, R] = 0.0
                    s["wteqceffn"][Y, RECCL, B, R] = 0.0
                    s["wteqceffr"][Y, RECCL, B, R] = 0.0

        for R in range(1, NUM_R + 1):
            for B in range(1, NUM_B + 1):
                for RECTY in range(int(typt[EU]) + 1, int(typt[EU + 1]) + 1):
                    if RTINITYR[RECTY] <= Y <= RTLASTYR[RECTY]:
                        if RTCENDIV[RECTY] == R:
                            EQT = int(s["rteqtype"][RECTY])
                            EQC = int(s["rttyeqcl"][RECTY])
                            RECCL = int(eupt[EU]) + EQC
                            F = int(s["rtfuel"][RECCL])
                            UEC[RECTY] = s["rteqeff"][RECTY] * FACTOR

                            CAPITAL = _capital(s, RECTY, Y)
                            OPCOST1 = P[F, R, Y] * UEC[RECTY]

                            if Y > 2008 and P[F, R, Y] > P[F, R, RECSYEAR]:
                                HRDRATE = s["rtecbta1"][RECTY] / s["rtecbta2"][RECTY]
                                ELIGBLE = HRDRATE - f32(0.07)
                                s["hrdrate"], s["eligble"] = HRDRATE, ELIGBLE
                                if ELIGBLE > 0.0:
                                    HRDADJ = ELIGBLE * np.power(P[4, R, Y] / P[4, R, RECSYEAR], ALPHA1)
                                    s["hrdadj"] = HRDADJ
                                    s["beta1dr"][RECTY] = (HRDADJ + f32(0.07)) * s["rtecbta2"][RECTY]
                                else:
                                    s["beta1dr"][RECTY] = s["rtecbta1"][RECTY]
                            else:
                                s["beta1dr"][RECTY] = s["rtecbta1"][RECTY]

                            LFCYCLE = CAPITAL + (OPCOST1 * DECAY)
                            # EQWTR is the same expression as EQWTN: replacement choices equal new ones
                            EQWTN[EQT, B, R] = expf(s["rtecbias"][RECTY] + (s["beta1dr"][RECTY] * CAPITAL)
                                                      + (s["rtecbta2"][RECTY] * OPCOST1) + (s["rtecbta3"][RECTY] * LFCYCLE))
                            TOTEWTN[EQC, B, R] = TOTEWTN[EQC, B, R] + EQWTN[EQT, B, R]
                            EQWTR[EQT, B, R] = expf(s["rtecbias"][RECTY] + (s["beta1dr"][RECTY] * CAPITAL)
                                                      + (s["rtecbta2"][RECTY] * OPCOST1) + (s["rtecbta3"][RECTY] * LFCYCLE))
                            TOTEWTR[EQC, B, R] = TOTEWTR[EQC, B, R] + EQWTR[EQT, B, R]

        # Weight of each configuration group
        for R in range(1, NUM_R + 1):
            for B in range(1, NUM_B + 1):
                TMFSHR[B, R] = 0.
                BMFSHR[B, R] = 0.
                SMFSHR[B, R] = 0.
                for RECTY in range(int(typt[EU]) + 1, int(typt[EU + 1]) + 1):
                    if RTINITYR[RECTY] <= Y <= RTLASTYR[RECTY]:
                        if RTCENDIV[RECTY] == R:
                            EQT = int(s["rteqtype"][RECTY])
                            if EQT <= 4:  # REFR_TF in RSMEQP
                                TMFSHR[B, R] = TMFSHR[B, R] + EQWTN[EQT, B, R]
                            elif 5 <= EQT <= 8:  # REFR_SF
                                SMFSHR[B, R] = SMFSHR[B, R] + EQWTN[EQT, B, R]
                            else:  # REFR_BF
                                BMFSHR[B, R] = BMFSHR[B, R] + EQWTN[EQT, B, R]

        for R in range(1, NUM_R + 1):
            for B in range(1, NUM_B + 1):
                TYPE = int(tyct[EU])
                for RECTY in range(int(typt[EU]) + 1, int(typt[EU + 1]) + 1):
                    if RTINITYR[RECTY] <= Y <= RTLASTYR[RECTY]:
                        if RTCENDIV[RECTY] == R:
                            TYPE += 1
                            EQT = int(s["rteqtype"][RECTY])
                            if EQT <= 4:
                                s["neqtshr"][Y, TYPE, B, R] = (EQWTN[EQT, B, R] / TMFSHR[B, R]) * s["tmf_shr"]
                            elif 5 <= EQT <= 8:
                                s["neqtshr"][Y, TYPE, B, R] = (EQWTN[EQT, B, R] / SMFSHR[B, R]) * s["smf_shr"]
                            else:
                                s["neqtshr"][Y, TYPE, B, R] = (EQWTN[EQT, B, R] / BMFSHR[B, R]) * s["bmf_shr"]
                            s["reqtshr"][Y, TYPE, B, R] = s["neqtshr"][Y, TYPE, B, R]

                _weighted_efficiency(s, EU, B, R)


def _weighted_efficiency(s, EU, B, R):
    """Share-weighted rated efficiency of new and replacement equipment per class
    (RREFTEC and RFRZTEC; RDRYTEC weighs by EQWT/eff instead and is inline)."""
    Y = int(s["curcalyr"])
    eupt, typt, tyct = s["rtcleupt"], s["rttyeupt"], s["rttypect"]
    for RECCL in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
        EQC = int(s["rtcleqcl"][RECCL])
        DENOM = f32(0)
        DENOM2 = f32(0)
        RECAR, EQTAR = [], []
        TYPE = int(tyct[EU])
        for RECTY in range(int(typt[EU]) + 1, int(typt[EU + 1]) + 1):
            if s["rtinityr"][RECTY] <= Y <= s["rtlastyr"][RECTY]:
                if s["rtcendiv"][RECTY] == R:
                    TYPE += 1
                    if s["rttyeqcl"][RECTY] == EQC:
                        RECAR.append(RECTY)
                        EQTAR.append(TYPE)
                        DENOM = DENOM + s["neqtshr"][Y, TYPE, B, R]
                        DENOM2 = DENOM2 + s["reqtshr"][Y, TYPE, B, R]

        if DENOM <= 0.0:
            s["wteqceffn"][Y, RECCL, B, R] = s["rtbaseff"][RECSYEAR, RECCL]
        else:
            SUM = f32(0.0)
            for RECTY, TYPE in zip(RECAR, EQTAR):
                SUM = SUM + (s["neqtshr"][Y, TYPE, B, R] * s["rteqeff"][RECTY])
            s["wteqceffn"][Y, RECCL, B, R] = SUM / DENOM

        if DENOM2 <= 0.0:
            s["wteqceffr"][Y, RECCL, B, R] = s["rtbaseff"][RECSYEAR, RECCL]
        else:
            SUM = f32(0.0)
            for RECTY, TYPE in zip(RECAR, EQTAR):
                SUM = SUM + (s["reqtshr"][Y, TYPE, B, R] * s["rteqeff"][RECTY])
            s["wteqceffr"][Y, RECCL, B, R] = SUM / DENOM2


def _cooling_add(s, EU, sat_name):
    """RREFADD and RFRZADD are the same routine with a different saturation array
    (REFSAT, FRZSAT): equipment bought for new homes, survivors of the RECS-year
    stock and of earlier purchases, replacements of the new-home vintage."""
    CY = int(s["curcalyr"])
    eupt = s["rtcleupt"]
    HDR = s["hdr"]
    EQCADD, EQCSR90, EQCRP90RP, EQCSUR, EQCREP = (s[k] for k in ("eqcadd", "eqcsr90", "eqcrp90rp", "eqcsur", "eqcrep"))
    EQCRP90, EQCESE, EQCRET = s["eqcrp90"], s["eqcese"], s["eqcret"]
    with np.errstate(all="ignore"):
        for R in range(1, NUM_R + 1):
            for B in range(1, NUM_B + 1):
                for RECCL in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                    EQCADD[CY, RECCL, B, R] = (s["hseadd"][CY, B, R] * s[sat_name][B, R])

                    EQCSR90[CY, RECCL, B, R] = 0.0
                    EQCSUR[CY, RECCL, B, R] = 0.0
                    EQCRP90RP[CY, RECCL, B, R] = 0.0
                    SA = f32(0.0)

                    if CY == RECSYEAR + 1:
                        EQCRP90[CY, RECCL, B, R] = (EQCRET[CY, RECCL]
                                                    * EQCESE[RECSYEAR, RECCL, B, R] * powi(HDR[B], CY - RECSYEAR))
                    else:
                        EQCRP90[CY, RECCL, B, R] = ((EQCRET[CY, RECCL] - EQCRET[CY - 1, RECCL])
                                                    * EQCESE[RECSYEAR, RECCL, B, R] * powi(HDR[B], CY - RECSYEAR))

                    alpha, k, lam = s["rtalpha"][RECCL], s["rtk"][RECCL], s["rtlambda"][RECCL]
                    if CY > RECSYEAR + 1:
                        for Y in range(RECSYEAR + 1, CY):
                            TEMP = CY - Y
                            ESR = svrte(alpha, TEMP - 1, k, lam) - svrte(alpha, TEMP, k, lam)
                            EQCRP90RP[CY, RECCL, B, R] = (EQCRP90RP[CY, RECCL, B, R] + (
                                EQCRP90[Y, RECCL, B, R] * ESR * powi(HDR[B], TEMP)
                                + EQCRP90RP[Y, RECCL, B, R] * ESR * powi(HDR[B], TEMP)))

                    if CY > RECSYEAR + 1:
                        for Y in range(RECSYEAR + 1, CY):
                            TEMP = CY - Y
                            ESR = svrte(alpha, TEMP, k, lam)
                            EQCSR90[CY, RECCL, B, R] = (EQCSR90[CY, RECCL, B, R] + (
                                EQCRP90[Y, RECCL, B, R] * ESR * powi(HDR[B], TEMP)
                                + EQCRP90RP[Y, RECCL, B, R] * ESR * powi(HDR[B], TEMP)))
                            HSR = powi(HDR[B], TEMP)
                            SA = SA + EQCADD[Y, RECCL, B, R] * HSR
                            EQCSUR[CY, RECCL, B, R] = (EQCSUR[CY, RECCL, B, R] + (
                                (EQCADD[Y, RECCL, B, R] + EQCREP[Y, RECCL, B, R]) * (HSR * ESR)))

                    EQCREP[CY, RECCL, B, R] = SA - EQCSUR[CY, RECCL, B, R]

        _vintage_future(s, EU)
        _purchases(s, EU)


def rrefadd(s: dict) -> None:
    """RREFADD: refrigerators added and replaced (EU = 8)."""
    _cooling_add(s, 8, "refsat")


def rrefcon(s: dict) -> None:
    """RREFCON: refrigerator UECs and consumption (EU = 8). ALPHA is 0 so the
    short-run price response is exactly 1."""
    EU, EUPR = 8, 6
    CY, IY = int(s["curcalyr"]), int(s["curiyr"])
    eupt = s["rtcleupt"]
    ef1, ef2, ef3 = f32(.5), f32(.35), f32(.15)
    ALPHA = f32(0.0)
    LEAPYR = _leapyr(CY)
    RTBASEFF = s["rtbaseff"]

    with np.errstate(all="ignore"):
        _map_electricity_price(s, EUPR)
        _stock_efficiency(s, EU)

        for D in range(1, NUM_R + 1):
            for B in range(1, NUM_B + 1):
                for RECCL in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                    s["eqcsuec"][CY, RECCL, B, D] = s["eqcuec"][D, RECCL, B] * (RTBASEFF[CY, RECCL] / RTBASEFF[RECSYEAR, RECCL])
                    s["eqcnuec"][CY, RECCL, B, D] = (
                        (s["eqcuec"][D, RECCL, B] * (s["wteqceffn"][CY, RECCL, B, D] / RTBASEFF[RECSYEAR, RECCL]))
                        * (f32(1.0) / s["refsat"][B, D])
                        + s["eqcuec"][D, RECCL, B] * (f32(1.0) - (f32(1.0) / s["refsat"][B, D])))
                    s["eqcruec"][CY, RECCL, B, D] = s["eqcuec"][D, RECCL, B] * (
                        s["wteqceffr"][CY, RECCL, B, D] / RTBASEFF[RECSYEAR, RECCL])
                    _eqcauec(s, RECCL, B, D)

        _wteqceffa(s, EU)

        s["refcon"][IY, 1:NUM_R] = 0.0
        s["refconwt"][IY, 1:NUM_R, 1:NUM_B] = 0.
        s["driver2"][IY, 1:NUM_R, 1:NUM_B] = 0.
        s["refconin"][IY, 1:NUM_R, 1:NUM_B] = 0.

        for D in range(1, NUM_R + 1):
            for B in range(1, NUM_B + 1):
                for RECCL in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                    F = int(s["rtfuel"][RECCL])
                    ESE, ADD = s["eqcese"][CY, RECCL, B, D], s["eqcadd"][CY, RECCL, B, D]
                    RP90, RP90RP = s["eqcrp90"][CY, RECCL, B, D], s["eqcrp90rp"][CY, RECCL, B, D]
                    SR90, REP, SUR = s["eqcsr90"][CY, RECCL, B, D], s["eqcrep"][CY, RECCL, B, D], s["eqcsur"][CY, RECCL, B, D]
                    SUEC, NUEC = s["eqcsuec"][CY, RECCL, B, D], s["eqcnuec"][CY, RECCL, B, D]
                    RUEC, AUEC = s["eqcruec"][CY, RECCL, B, D], s["eqcauec"][CY, RECCL, B, D]
                    sel = _rselast_f0(s, F, D, ALPHA, ef1, ef2, ef3, EUPR)

                    if CY == RECSYEAR + 1:
                        tot = ((ESE * SUEC) + (RP90RP * NUEC) + (ADD * NUEC) + (RP90 * RUEC))
                        s["refcon"][IY, D] = s["refcon"][IY, D] + LEAPYR * (tot * sel)
                        s["refconwt"][IY, D, B] = s["refconwt"][IY, D, B] + LEAPYR * (tot * sel)
                        if ESE + ADD + RP90RP + RP90 > 0.:
                            s["refconin"][IY, D, B] = s["refconin"][IY, D, B] + tot
                            s["driver2"][IY, D, B] = s["driver2"][IY, D, B] + (ESE + ADD + RP90RP + RP90)
                        s["eqceqcn"][IY, RECCL, B, D] = LEAPYR * (tot * sel)
                    else:
                        tot = ((ESE * SUEC) + (ADD * NUEC) + (RP90 * RUEC) + (RP90RP * NUEC)
                               + (SR90 * AUEC) + (REP * NUEC) + (SUR * AUEC))
                        s["refcon"][IY, D] = s["refcon"][IY, D] + LEAPYR * (tot * sel)
                        s["refconwt"][IY, D, B] = s["refconwt"][IY, D, B] + LEAPYR * (tot * sel)
                        if ESE + ADD + RP90RP + RP90 + SR90 + REP + SUR > 0.:
                            s["refconin"][IY, D, B] = s["refconin"][IY, D, B] + tot
                            s["driver2"][IY, D, B] = s["driver2"][IY, D, B] + (
                                ESE + ADD + RP90RP + RP90 + SR90 + REP + SUR)
                        s["eqceqcn"][IY, RECCL, B, D] = LEAPYR * (tot * sel)

        for R in range(1, NUM_R + 1):
            for B in range(1, NUM_B + 1):
                if s["driver2"][IY, R, B] > 0:
                    s["refconin"][IY, R, B] = s["refconin"][IY, R, B] / s["driver2"][IY, R, B]


# ---------------------------------------------------------------------------
# Standalone freezers
# ---------------------------------------------------------------------------

def rfrztec(s: dict) -> None:
    """RFRZTEC: standalone freezer technology choice (EU = 9). Chest and upright
    types compete within their own group."""
    EU, EUPR = 9, 7
    Y = int(s["curcalyr"])
    s["alpha1"] = ALPHA1 = f32(-0.50)
    FACTOR = f32(.003412)
    P = s["prices"]
    eupt, typt, tyct = s["rtcleupt"], s["rttyeupt"], s["rttypect"]
    RTINITYR, RTLASTYR, RTCENDIV = s["rtinityr"], s["rtlastyr"], s["rtcendiv"]
    EQWTN = np.zeros((64, NUM_B + 1, NUM_R + 3), dtype=np.float32)
    EQWTR = np.zeros_like(EQWTN)
    TOTEWTN = np.zeros_like(EQWTN)
    TOTEWTR = np.zeros_like(EQWTN)
    CHSHR = np.zeros((NUM_B + 1, NUM_R + 1), dtype=np.float32)
    UPSHR = np.zeros_like(CHSHR)
    UEC = {}

    with np.errstate(all="ignore"):
        _map_electricity_price(s, EUPR)
        DECAY = _decay(s)

        for R in range(1, NUM_R + 1):
            for B in range(1, NUM_B + 1):
                for RECCL in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                    EQC = int(s["rtcleqcl"][RECCL])
                    TOTEWTN[EQC, B, R] = 0.0
                    TOTEWTR[EQC, B, R] = 0.0
                    s["wteqceffn"][Y, RECCL, B, R] = 0.0
                    s["wteqceffr"][Y, RECCL, B, R] = 0.0

        for R in range(1, NUM_R + 1):
            for B in range(1, NUM_B + 1):
                for RECTY in range(int(typt[EU]) + 1, int(typt[EU + 1]) + 1):
                    if RTINITYR[RECTY] <= Y <= RTLASTYR[RECTY]:
                        if RTCENDIV[RECTY] == R:
                            EQT = int(s["rteqtype"][RECTY])
                            EQC = int(s["rttyeqcl"][RECTY])
                            RECCL = int(eupt[EU]) + EQC
                            F = int(s["rtfuel"][RECCL])
                            UEC[RECTY] = s["rteqeff"][RECTY] * FACTOR

                            CAPITAL = _capital(s, RECTY, Y)
                            OPCOST2 = P[F, R, Y] * UEC[RECTY]

                            if Y > 2008 and P[4, R, Y] > P[4, R, RECSYEAR]:
                                HRDRATE = s["rtecbta1"][RECTY] / s["rtecbta2"][RECTY]
                                ELIGBLE = HRDRATE - f32(0.07)
                                s["hrdrate"], s["eligble"] = HRDRATE, ELIGBLE
                                if ELIGBLE > 0.0:
                                    HRDADJ = ELIGBLE * np.power(P[4, R, Y] / P[4, R, RECSYEAR], ALPHA1)
                                    s["hrdadj"] = HRDADJ
                                    s["beta1dr"][RECTY] = (HRDADJ + f32(0.07)) * s["rtecbta2"][RECTY]
                                else:
                                    s["beta1dr"][RECTY] = s["rtecbta1"][RECTY]
                            else:
                                s["beta1dr"][RECTY] = s["rtecbta1"][RECTY]

                            LFCYCLE1 = CAPITAL + (OPCOST2 * DECAY)
                            EQWTN[EQT, B, R] = expf(s["rtecbias"][RECTY] + (s["beta1dr"][RECTY] * CAPITAL)
                                                      + (s["rtecbta2"][RECTY] * OPCOST2) + (s["rtecbta3"][RECTY] * LFCYCLE1))
                            TOTEWTN[EQC, B, R] = TOTEWTN[EQC, B, R] + EQWTN[EQT, B, R]
                            EQWTR[EQT, B, R] = expf(s["rtecbias"][RECTY] + (s["beta1dr"][RECTY] * CAPITAL)
                                                      + (s["rtecbta2"][RECTY] * OPCOST2) + (s["rtecbta3"][RECTY] * LFCYCLE1))
                            TOTEWTR[EQC, B, R] = TOTEWTR[EQC, B, R] + EQWTR[EQT, B, R]

        for R in range(1, NUM_R + 1):
            for B in range(1, NUM_B + 1):
                CHSHR[B, R] = 0.
                UPSHR[B, R] = 0.
                for RECTY in range(int(typt[EU]) + 1, int(typt[EU + 1]) + 1):
                    if RTINITYR[RECTY] <= Y <= RTLASTYR[RECTY]:
                        if RTCENDIV[RECTY] == R:
                            EQT = int(s["rteqtype"][RECTY])
                            if EQT <= 3:  # FREZ_C in RSMEQP
                                CHSHR[B, R] = CHSHR[B, R] + EQWTN[EQT, B, R]
                            else:  # FREZ_U
                                UPSHR[B, R] = UPSHR[B, R] + EQWTN[EQT, B, R]

        for R in range(1, NUM_R + 1):
            for B in range(1, NUM_B + 1):
                TYPE = int(tyct[EU])
                for RECTY in range(int(typt[EU]) + 1, int(typt[EU + 1]) + 1):
                    if RTINITYR[RECTY] <= Y <= RTLASTYR[RECTY]:
                        if RTCENDIV[RECTY] == R:
                            TYPE += 1
                            EQT = int(s["rteqtype"][RECTY])
                            if EQT <= 3:
                                s["neqtshr"][Y, TYPE, B, R] = (EQWTN[EQT, B, R] / CHSHR[B, R]) * s["ch_shr"]
                            else:
                                s["neqtshr"][Y, TYPE, B, R] = (EQWTN[EQT, B, R] / UPSHR[B, R]) * s["up_shr"]
                            s["reqtshr"][Y, TYPE, B, R] = s["neqtshr"][Y, TYPE, B, R]

                _weighted_efficiency(s, EU, B, R)


def rfrzadd(s: dict) -> None:
    """RFRZADD: standalone freezers added and replaced (EU = 9)."""
    _cooling_add(s, 9, "frzsat")


def rfrzcon(s: dict) -> None:
    """RFRZCON: standalone freezer UECs and consumption (EU = 9). ALPHA is 0 so
    the short-run price response is exactly 1."""
    EU, EUPR = 9, 7
    CY, IY = int(s["curcalyr"]), int(s["curiyr"])
    eupt = s["rtcleupt"]
    ef1, ef2, ef3 = f32(.5), f32(.35), f32(.15)
    ALPHA = f32(0.0)
    LEAPYR = _leapyr(CY)
    RTBASEFF = s["rtbaseff"]

    with np.errstate(all="ignore"):
        _map_electricity_price(s, EUPR)
        _stock_efficiency(s, EU)

        for D in range(1, NUM_R + 1):
            for B in range(1, NUM_B + 1):
                for RECCL in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                    s["eqcsuec"][CY, RECCL, B, D] = s["eqcuec"][D, RECCL, B] * (RTBASEFF[CY, RECCL] / RTBASEFF[RECSYEAR, RECCL])
                    s["eqcnuec"][CY, RECCL, B, D] = s["eqcuec"][D, RECCL, B] * (
                        s["wteqceffn"][CY, RECCL, B, D] / RTBASEFF[RECSYEAR, RECCL])
                    s["eqcruec"][CY, RECCL, B, D] = s["eqcuec"][D, RECCL, B] * (
                        s["wteqceffr"][CY, RECCL, B, D] / RTBASEFF[RECSYEAR, RECCL])
                    _eqcauec(s, RECCL, B, D)

        _wteqceffa(s, EU)

        s["frzcon"][IY, 1:NUM_R] = 0.0
        s["frzconin"][IY, 1:NUM_R, 1:NUM_B] = 0.
        s["driver2"][IY, 1:NUM_R, 1:NUM_B] = 0.
        s["frzconwt"][IY, 1:NUM_R, 1:NUM_B] = 0.

        for D in range(1, NUM_R + 1):
            for B in range(1, NUM_B + 1):
                for RECCL in range(int(eupt[EU]) + 1, int(eupt[EU + 1]) + 1):
                    F = int(s["rtfuel"][RECCL])
                    ESE, ADD = s["eqcese"][CY, RECCL, B, D], s["eqcadd"][CY, RECCL, B, D]
                    RP90, RP90RP = s["eqcrp90"][CY, RECCL, B, D], s["eqcrp90rp"][CY, RECCL, B, D]
                    SR90, REP, SUR = s["eqcsr90"][CY, RECCL, B, D], s["eqcrep"][CY, RECCL, B, D], s["eqcsur"][CY, RECCL, B, D]
                    SUEC, NUEC = s["eqcsuec"][CY, RECCL, B, D], s["eqcnuec"][CY, RECCL, B, D]
                    RUEC, AUEC = s["eqcruec"][CY, RECCL, B, D], s["eqcauec"][CY, RECCL, B, D]
                    sel = _rselast_f0(s, F, D, ALPHA, ef1, ef2, ef3, EUPR)

                    if CY == RECSYEAR + 1:
                        # EIA orders the four terms differently in FRZCON and in the other three
                        tot_con = ((ESE * SUEC) + (RP90RP * NUEC) + (ADD * NUEC) + (RP90 * RUEC))
                        tot = ((ESE * SUEC) + (ADD * NUEC) + (RP90RP * NUEC) + (RP90 * RUEC))
                        s["frzcon"][IY, D] = s["frzcon"][IY, D] + LEAPYR * (tot_con * sel)
                        s["frzconwt"][IY, D, B] = s["frzconwt"][IY, D, B] + LEAPYR * (tot * sel)
                        if ESE + ADD + RP90RP + RP90 > 0.:
                            s["frzconin"][IY, D, B] = s["frzconin"][IY, D, B] + tot
                            s["driver2"][IY, D, B] = s["driver2"][IY, D, B] + (ESE + ADD + RP90RP + RP90)
                        s["eqceqcn"][IY, RECCL, B, D] = LEAPYR * (tot * sel)
                    else:
                        tot = ((ESE * SUEC) + (ADD * NUEC) + (RP90 * RUEC) + (RP90RP * NUEC)
                               + (SR90 * AUEC) + (REP * NUEC) + (SUR * AUEC))
                        s["frzcon"][IY, D] = s["frzcon"][IY, D] + LEAPYR * (tot * sel)
                        s["frzconwt"][IY, D, B] = s["frzconwt"][IY, D, B] + LEAPYR * (tot * sel)
                        if ESE + ADD + RP90RP + RP90 + SR90 + REP + SUR > 0.:
                            s["frzconin"][IY, D, B] = s["frzconin"][IY, D, B] + tot
                            s["driver2"][IY, D, B] = s["driver2"][IY, D, B] + (
                                ESE + ADD + RP90RP + RP90 + SR90 + REP + SUR)
                        s["eqceqcn"][IY, RECCL, B, D] = LEAPYR * (tot * sel)

        for R in range(1, NUM_R + 1):
            for B in range(1, NUM_B + 1):
                if s["driver2"][IY, R, B] > 0:
                    s["frzconin"][IY, R, B] = s["frzconin"][IY, R, B] / s["driver2"][IY, R, B]
