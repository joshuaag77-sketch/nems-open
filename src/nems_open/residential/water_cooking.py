"""Water heating and cooking: RWHTEC, REUADD (EU = 5 and 6), RWHCON, RSTVTEC, RSTOVCON (resd.f).

RWHTEC / RSTVTEC choose equipment types (logit on life-cycle cost) and weight the
efficiency of new and replacement equipment. REUADD vintages equipment added and
replaced, for both end uses (the caller passes EU, which RESD sets in a module
variable just before the call). RWHCON / RSTOVCON turn the stock into energy.

Writes to debug units and AppBetaData.txt are skipped.

LEAPYR is set by RESD each year; it is rebuilt here from CurCalYr when absent.
"""

import numpy as np

from nems_open.residential.common import BASEYR, ENDYR, LASTSTEOYR, RECSYEAR, expf, f32, powf, powi
from nems_open.residential.helpers import eqcost, replace, rselast, svrte

COSTTRSW = 0  # PARAMETER in rtek: capital cost is the flat RSMEQP value
NM = 9  # mNumCR - 2 census divisions
NB = 3  # mNumBldg


def _name(v) -> str:
    return v.decode("latin-1").strip() if isinstance(v, bytes) else str(v).strip()


def _decay(s):
    """DECAY is computed on the first iteration and carried (SAVE) to later ones. It
    depends only on two constants, so it is recomputed every call."""
    r, tenure = f32(s["resdiscountrate"]), f32(s["tenure"])
    return f32(f32(1) - powi_real(f32(f32(1) + r), f32(-tenure))) / r


def powi_real(x, p):
    """REAL ** REAL (powf); numpy errors on 0 and inf are ignored as in Fortran."""
    with np.errstate(all="ignore"):
        return powf(x, p)


def _elec_price(s, eupr):
    """PRICES(4,R,CurCalYr) from the end-use electricity price."""
    Y, Y1 = int(s["curcalyr"]), int(s["curiyr"])
    gdp = s["mc_jpgdp"]
    for r in range(1, NM + 1):
        s["prices"][4, r, Y] = s["pelrsout"][r, Y1, eupr] * (gdp[int(s["rtekdollaryr"]) - BASEYR + 1] / gdp[-2])


def _rselast(s, f, r, alpha, ef1, ef2, ef3, eupr):
    return rselast(s, f, r, alpha, ef1, ef2, ef3, eupr)


def _leapyr(s):
    if "leapyr" in s:
        return f32(s["leapyr"])
    Y = int(s["curcalyr"])
    return f32(f32(366.0) / f32(365.0)) if (Y % 4 == 0 and Y <= LASTSTEOYR) else f32(1.0)


def _farr(n1, n2, n3, lo=1):
    from nems_open.fortran_array import FArray
    return FArray.zeros([(lo, n1), (lo, n2), (lo, n3)])


def _beta(s, recty, f, r, Y, price_check_inside):
    """BETA1 for price-induced behaviour change. RWHTEC and RSTVTEC differ only in
    whether the price test is repeated inside (water heating does)."""
    P = s["prices"]
    bta1, bta2 = s["rtecbta1"][recty], s["rtecbta2"][recty]
    if Y > 2008 and P[f, r, Y] > P[f, r, RECSYEAR]:
        s["hrdrate"] = f32(bta1 / bta2)
        s["eligble"] = f32(s["hrdrate"] - f32(0.07))
        if s["eligble"] > 0.0 and (not price_check_inside or P[f, r, Y] > P[f, r, RECSYEAR]):
            s["hrdadj"] = f32(s["eligble"] * powi_real(f32(P[f, r, Y] / P[f, r, RECSYEAR]), s["alpha1"]))
            s["beta1dr"][recty] = f32(f32(s["hrdadj"] + f32(0.07)) * bta2)
        else:
            s["beta1dr"][recty] = bta1
    else:
        s["beta1dr"][recty] = bta1


def _choice_costs(s, EU, r, b, recty, DECAY, price_check_inside, lfcy_first):
    """The per-record block shared by RWHTEC and RSTVTEC: efficiency factor, capital,
    operating and life-cycle cost, BETA1, then the two logit weights.
    Returns (eqc, eqt, eqwtn, eqwtr). lfcy_first sets the order of the LFCY and
    BETA1 steps, which differ between the two routines (no effect on values)."""
    Y = int(s["curcalyr"])
    P = s["prices"]
    eqc = int(s["rttyeqcl"][recty])
    eqt = int(s["rteqtype"][recty])
    reccl = int(s["rtcleupt"][EU]) + eqc
    f = int(s["rtfuel"][reccl])

    if s["rteqeff"][recty] != 0.0:
        rteffac1 = f32(s["eqceff"][Y, reccl] / s["rteqeff"][recty])
        rteffac2 = f32(s["rtbaseff"][RECSYEAR, reccl] / s["rteqeff"][recty])
    else:
        rteffac1 = s["rtbaseff"][RECSYEAR, reccl]
        rteffac2 = s["rtbaseff"][RECSYEAR, reccl]

    capital = eqcost(s, recty, Y, "CAP") if COSTTRSW == 1 else s["rteqcost"][recty]

    opcost1 = f32(f32(P[f, r, Y] * s["eqcuec"][r, reccl, b]) * rteffac1)
    opcost2 = f32(f32(P[f, r, Y] * s["eqcuec"][r, reccl, b]) * rteffac2)

    LFCY = s["lfcy"]
    if lfcy_first:
        LFCY[eqt, b, r, 1] = f32(capital + f32(opcost1 * DECAY))
        LFCY[eqt, b, r, 2] = f32(capital + f32(opcost2 * DECAY))
        _beta(s, recty, f, r, Y, price_check_inside)
    else:
        _beta(s, recty, f, r, Y, price_check_inside)
        LFCY[eqt, b, r, 1] = f32(capital + f32(opcost1 * DECAY))
        LFCY[eqt, b, r, 2] = f32(capital + f32(opcost2 * DECAY))

    bias, b1, b2, b3 = s["rtecbias"][recty], s["beta1dr"][recty], s["rtecbta2"][recty], s["rtecbta3"][recty]
    with np.errstate(all="ignore"):
        wtn = expf(f32(f32(f32(bias + f32(b1 * capital)) + f32(b2 * opcost2)) + f32(b3 * LFCY[eqt, b, r, 2])))
        wtr = expf(f32(f32(f32(bias + f32(b1 * capital)) + f32(b2 * opcost1)) + f32(b3 * LFCY[eqt, b, r, 1])))
    return eqc, eqt, wtn, wtr


def _valid(s, recty, Y):
    return int(s["rtinityr"][recty]) <= Y <= int(s["rtlastyr"][recty])


def rwhtec(s: dict) -> None:
    """RWHTEC: water heater choice. NEQTSHR/REQTSHR (shares of new and replacement
    purchases by type), WTEQCEFFN/R (the 1/efficiency-style weighted figure), LFCY."""
    EU, EUPR, EUHT = 5, 3, 1
    Y = int(s["curcalyr"])
    s["alpha1"] = f32(-0.50)
    _elec_price(s, EUPR)
    DECAY = _decay(s)

    cleupt, cleqcl = s["rtcleupt"], s["rtcleqcl"]
    tyeupt, cendiv, tyeqcl = s["rttyeupt"], s["rtcendiv"], s["rttyeqcl"]
    TOTN = _farr(NB, NM, 1)
    TOTEWTN = _farr(40, NB, NM)
    TOTEWTR = _farr(40, NB, NM)
    EQFSHRN = _farr(64, NB, NM)
    EQFSHRR = _farr(64, NB, NM)
    EQWTN = _farr(64, NB, NM)
    EQWTR = _farr(64, NB, NM)

    for b in range(1, NB + 1):
        for r in range(1, NM + 1):
            TOTN[b, r, 1] = 0.0
            for reccl in range(int(cleupt[EU]) + 1, int(cleupt[EU + 1]) + 1):
                eqc = int(cleqcl[reccl])
                TOTEWTN[eqc, b, r] = 0.0
                TOTEWTR[eqc, b, r] = 0.0
                s["nh2osh"][Y, eqc, b, r] = 0.0
            for reccl in range(int(cleupt[EUHT]) + 1, int(cleupt[EUHT + 1]) + 1):
                eqcht = int(cleqcl[reccl])
                TOTN[b, r, 1] = f32(TOTN[b, r, 1] + s["hsysshr"][Y, eqcht, b, r])

    for r in range(1, NM + 1):
        for b in range(1, NB + 1):
            # Water heaters take the shares of the space heaters whose RTCLPNTR points to them.
            for reccl in range(int(cleupt[EU]) + 1, int(cleupt[EU + 1]) + 1):
                eqc = int(cleqcl[reccl])
                for recclht in range(int(cleupt[EUHT]) + 1, int(cleupt[EUHT + 1]) + 1):
                    if int(s["rtclpntr"][recclht]) == eqc:
                        eqcht = int(cleqcl[recclht])
                        if TOTN[b, r, 1] > 0.0:
                            s["nh2osh"][Y, eqc, b, r] = f32(
                                s["nh2osh"][Y, eqc, b, r] + f32(s["hsysshr"][Y, eqcht, b, r] / TOTN[b, r, 1]))
                        else:
                            s["nh2osh"][Y, eqc, b, r] = 0.0

            for recty in range(int(tyeupt[EU]) + 1, int(tyeupt[EU + 1]) + 1):
                if _valid(s, recty, Y) and int(cendiv[recty]) == r:
                    eqc, eqt, wtn, wtr = _choice_costs(s, EU, r, b, recty, DECAY, True, True)
                    EQWTN[eqt, b, r] = wtn
                    TOTEWTN[eqc, b, r] = f32(TOTEWTN[eqc, b, r] + EQWTN[eqt, b, r])
                    EQWTR[eqt, b, r] = wtr
                    TOTEWTR[eqc, b, r] = f32(TOTEWTR[eqc, b, r] + EQWTR[eqt, b, r])

            # New and replacement market shares.
            TYPE = int(s["rttypect"][EU])
            for recty in range(int(tyeupt[EU]) + 1, int(tyeupt[EU + 1]) + 1):
                if _valid(s, recty, Y) and int(cendiv[recty]) == r:
                    TYPE += 1
                    eqc, eqt = int(tyeqcl[recty]), int(s["rteqtype"][recty])
                    EQFSHRN[eqt, b, r] = f32(EQWTN[eqt, b, r] / TOTEWTN[eqc, b, r]) if TOTEWTN[eqc, b, r] > 0.0 else 0.0
                    EQFSHRR[eqt, b, r] = f32(EQWTR[eqt, b, r] / TOTEWTR[eqc, b, r]) if TOTEWTR[eqc, b, r] > 0.0 else 0.0
                    s["neqtshr"][Y, TYPE, b, r] = EQFSHRN[eqt, b, r]
                    s["reqtshr"][Y, TYPE, b, r] = EQFSHRR[eqt, b, r]

            if Y >= 2015:
                _wh_standard_2015(s, EU, b, r, EQFSHRN, EQFSHRR)

            # Weighted efficiency of new and replacement equipment.
            for reccl in range(int(cleupt[EU]) + 1, int(cleupt[EU + 1]) + 1):
                eqc = int(cleqcl[reccl])
                denom, denom2 = f32(0), f32(0)
                recar, eqtar = [], []
                for recty in range(int(tyeupt[EU]) + 1, int(tyeupt[EU + 1]) + 1):
                    if int(tyeqcl[recty]) == eqc and _valid(s, recty, Y) and int(cendiv[recty]) == r:
                        eqt = int(s["rteqtype"][recty])
                        recar.append(recty)
                        eqtar.append(eqt)
                        denom = f32(denom + EQFSHRN[eqt, b, r])
                        denom2 = f32(denom2 + EQFSHRR[eqt, b, r])
                base = s["rtbaseff"][RECSYEAR, reccl]
                with np.errstate(all="ignore"):
                    if denom <= 0.0:
                        s["wteqceffn"][Y, reccl, b, r] = f32(f32(1) / base)
                    else:
                        sm = f32(0.0)
                        for recty, eqt in zip(recar, eqtar):
                            sm = f32(sm + f32(EQFSHRN[eqt, b, r] / s["rteqeff"][recty]))
                        s["wteqceffn"][Y, reccl, b, r] = f32(sm / denom)
                        if s["wteqceffn"][Y, reccl, b, r] == 0.0:
                            s["wteqceffn"][Y, reccl, b, r] = f32(f32(1) / base)
                    if denom2 <= 0.0:
                        s["wteqceffr"][Y, reccl, b, r] = f32(f32(1) / base)
                    else:
                        sm = f32(0.0)
                        for recty, eqt in zip(recar, eqtar):
                            sm = f32(sm + f32(EQFSHRR[eqt, b, r] / s["rteqeff"][recty]))
                        s["wteqceffr"][Y, reccl, b, r] = f32(sm / denom2)
                    if s["wteqceffr"][Y, reccl, b, r] == 0.0:
                        s["wteqceffr"][Y, reccl, b, r] = f32(f32(1) / base)


def _wh_standard_2015(s, EU, b, r, EQFSHRN, EQFSHRR):
    """2015 water heater standard: floor the share of condensing gas (type 3) at 4%
    and of heat pump water heaters (types 6-8) at 9%, rescaling the other types.
    The type numbers are hard-coded in EIA's code and kept."""
    Y = int(s["curcalyr"])
    c04, c09, one = f32(0.04), f32(0.09), f32(1.0)
    for E in (EQFSHRN, EQFSHRR):
        if E[3, b, r] < c04:
            temp = f32(one + f32(f32(E[3, b, r] - c04) / f32(one - E[3, b, r])))
            E[1, b, r] = f32(E[1, b, r] * temp)
            E[2, b, r] = f32(E[2, b, r] * temp)
            E[3, b, r] = c04
    for E in (EQFSHRN, EQFSHRR):
        hp = f32(f32(E[6, b, r] + E[7, b, r]) + E[8, b, r])
        if hp < c09:
            temp = f32(one + f32(f32(hp - c09) / f32(f32(f32(one - E[6, b, r]) - E[7, b, r]) - E[8, b, r])))
            E[4, b, r] = f32(E[4, b, r] * temp)
            E[5, b, r] = f32(E[5, b, r] * temp)
            temp = f32(c09 / f32(f32(E[6, b, r] + E[7, b, r]) + E[8, b, r]))
            E[6, b, r] = f32(E[6, b, r] * temp)
            E[7, b, r] = f32(E[7, b, r] * temp)
            E[8, b, r] = f32(E[8, b, r] * temp)
    # Reset the shares from the revised EQFSHR arrays.
    TYPE = int(s["rttypect"][EU])
    for recty in range(int(s["rttyeupt"][EU]) + 1, int(s["rttyeupt"][EU + 1]) + 1):
        if _valid(s, recty, Y) and int(s["rtcendiv"][recty]) == r:
            TYPE += 1
            eqt = int(s["rteqtype"][recty])
            s["neqtshr"][Y, TYPE, b, r] = EQFSHRN[eqt, b, r]
            s["reqtshr"][Y, TYPE, b, r] = EQFSHRR[eqt, b, r]


def rstvtec(s: dict) -> None:
    """RSTVTEC: cooking equipment choice. Also sets NCKSH, the new cooking share,
    from the new water heater shares (gas cooking follows gas water heating)."""
    EU, EUPR, EUHW = 6, 4, 5
    Y = int(s["curcalyr"])
    s["alpha1"] = f32(-0.50)
    ngngfact = {1: f32(0.46), 2: f32(0.46), 3: f32(0.64)}
    _elec_price(s, EUPR)
    DECAY = _decay(s)

    cleupt, cleqcl = s["rtcleupt"], s["rtcleqcl"]
    tyeupt, cendiv, tyeqcl = s["rttyeupt"], s["rtcendiv"], s["rttyeqcl"]
    TOTEWTN = _farr(40, NB, NM)
    TOTEWTR = _farr(40, NB, NM)
    EQFSHRN = _farr(64, NB, NM)
    EQFSHRR = _farr(64, NB, NM)
    EQWTN = _farr(64, NB, NM)
    EQWTR = _farr(64, NB, NM)

    for r in range(1, NM + 1):
        for b in range(1, NB + 1):
            for reccl in range(int(cleupt[EU]) + 1, int(cleupt[EU + 1]) + 1):
                eqc = int(cleqcl[reccl])
                s["ncksh"][Y, eqc, b, r] = 0.0
                TOTEWTN[eqc, b, r] = 0.0
                TOTEWTR[eqc, b, r] = 0.0

    for r in range(1, NM + 1):
        for b in range(1, NB + 1):
            for reccl in range(int(cleupt[EU]) + 1, int(cleupt[EU + 1]) + 1):
                eqc = int(cleqcl[reccl])
                for recclhw in range(int(cleupt[EUHW]) + 1, int(cleupt[EUHW + 1]) + 1):
                    if int(s["rtclpntr"][recclhw]) == eqc or int(s["rtclrepl"][recclhw]) == eqc:
                        eqchw = int(cleqcl[recclhw])
                        whn, stv = _name(s["rtclname"][recclhw]), _name(s["rtclname"][reccl])
                        sh = s["nh2osh"][Y, eqchw, b, r]
                        if whn == "NG_WH" and stv == "NG_STV":
                            s["ncksh"][Y, eqc, b, r] = f32(s["ncksh"][Y, eqc, b, r] + f32(sh * ngngfact[b]))
                        elif whn == "NG_WH" and stv == "ELEC_STV":
                            s["ncksh"][Y, eqc, b, r] = f32(s["ncksh"][Y, eqc, b, r] + f32(sh * f32(f32(1) - ngngfact[b])))
                        else:
                            s["ncksh"][Y, eqc, b, r] = f32(s["ncksh"][Y, eqc, b, r] + sh)

            for recty in range(int(tyeupt[EU]) + 1, int(tyeupt[EU + 1]) + 1):
                if _valid(s, recty, Y) and int(cendiv[recty]) == r:
                    eqc, eqt, wtn, wtr = _choice_costs(s, EU, r, b, recty, DECAY, False, False)
                    EQWTN[eqt, b, r] = wtn
                    TOTEWTN[eqc, b, r] = f32(TOTEWTN[eqc, b, r] + EQWTN[eqt, b, r])
                    EQWTR[eqt, b, r] = wtr
                    TOTEWTR[eqc, b, r] = f32(TOTEWTR[eqc, b, r] + EQWTR[eqt, b, r])

            TYPE = int(s["rttypect"][EU])
            for recty in range(int(tyeupt[EU]) + 1, int(tyeupt[EU + 1]) + 1):
                if _valid(s, recty, Y) and int(cendiv[recty]) == r:
                    TYPE += 1
                    eqc, eqt = int(tyeqcl[recty]), int(s["rteqtype"][recty])
                    EQFSHRN[eqt, b, r] = f32(EQWTN[eqt, b, r] / TOTEWTN[eqc, b, r]) if TOTEWTN[eqc, b, r] > 0.0 else 0.0
                    EQFSHRR[eqt, b, r] = f32(EQWTR[eqt, b, r] / TOTEWTR[eqc, b, r]) if TOTEWTR[eqc, b, r] > 0.0 else 0.0
                    s["neqtshr"][Y, TYPE, b, r] = EQFSHRN[eqt, b, r]
                    s["reqtshr"][Y, TYPE, b, r] = EQFSHRR[eqt, b, r]

            for reccl in range(int(cleupt[EU]) + 1, int(cleupt[EU + 1]) + 1):
                eqc = int(cleqcl[reccl])
                denom, denom2 = f32(0), f32(0)
                recar, eqtar = [], []
                for recty in range(int(tyeupt[EU]) + 1, int(tyeupt[EU + 1]) + 1):
                    if int(tyeqcl[recty]) == eqc and _valid(s, recty, Y) and int(cendiv[recty]) == r:
                        eqt = int(s["rteqtype"][recty])
                        recar.append(recty)
                        eqtar.append(eqt)
                        denom = f32(denom + EQFSHRN[eqt, b, r])
                        denom2 = f32(denom2 + EQFSHRR[eqt, b, r])
                base = s["rtbaseff"][RECSYEAR, reccl]
                if denom <= 0.0:
                    s["wteqceffn"][Y, reccl, b, r] = base
                else:
                    sm = f32(0.0)
                    for recty, eqt in zip(recar, eqtar):
                        sm = f32(sm + f32(EQFSHRN[eqt, b, r] * s["rteqeff"][recty]))
                    s["wteqceffn"][Y, reccl, b, r] = f32(sm / denom)
                if denom2 <= 0.0:
                    s["wteqceffr"][Y, reccl, b, r] = base
                else:
                    sm = f32(0.0)
                    for recty, eqt in zip(recar, eqtar):
                        sm = f32(sm + f32(EQFSHRR[eqt, b, r] * s["rteqeff"][recty]))
                    s["wteqceffr"][Y, reccl, b, r] = f32(sm / denom2)


def reuadd(s: dict, EU: int) -> None:
    """REUADD: equipment added, replaced and surviving for water heating (EU = 5) or
    cooking (EU = 6), the vintages of each for later years, the equipment-type
    purchase totals, and the gas customer count. The dead SWF/SWT/SWFT locals
    (written, never read) are skipped."""
    Y = int(s["curcalyr"])
    itr = int(s["curitr"])
    cleupt, cleqcl = s["rtcleupt"], s["rtcleqcl"]
    HDR = s["hdr"]
    lo, hi = int(cleupt[EU]) + 1, int(cleupt[EU + 1])

    for r in range(1, NM + 1):
        for b in range(1, NB + 1):
            for reccl in range(lo, hi + 1):
                s["eqcsr90"][Y, reccl, b, r] = 0.0
                s["eqcrp90rp"][Y, reccl, b, r] = 0.0
                s["eqcsur"][Y, reccl, b, r] = 0.0
                if b == 1:
                    s["eqcrep"][Y, reccl, b, r] = 0.0

    for r in range(1, NM + 1):
        for b in range(1, NB + 1):
            for reccl in range(lo, hi + 1):
                eqc = int(cleqcl[reccl])
                share = f32(1.0)
                if EU == 5:
                    share = s["nh2osh"][Y, eqc, b, r]
                if EU == 6:
                    share = s["ncksh"][Y, eqc, b, r]
                s["eqcadd"][Y, reccl, b, r] = f32(s["hseadd"][Y, b, r] * share)
                SA = f32(0.0)

                # Replacements from the original base-year stock.
                if Y == RECSYEAR + 1:
                    s["eqcrp90"][Y, reccl, b, r] = f32(f32(s["eqcret"][Y, reccl] * s["eqcese"][RECSYEAR, reccl, b, r])
                                                       * powi(HDR[b], Y - RECSYEAR))
                else:
                    s["eqcrp90"][Y, reccl, b, r] = f32(
                        f32(f32(s["eqcret"][Y, reccl] - s["eqcret"][Y - 1, reccl]) * s["eqcese"][RECSYEAR, reccl, b, r])
                        * powi(HDR[b], Y - RECSYEAR))

                alpha, k, lam = s["rtalpha"][reccl], s["rtk"][reccl], s["rtlambda"][reccl]
                # Replacements of replacements, by vintage.
                if Y > RECSYEAR + 1:
                    for y in range(RECSYEAR + 1, Y + 1):
                        temp = Y - y
                        esr = f32(svrte(alpha, temp - 1, k, lam) - svrte(alpha, temp, k, lam))
                        h = powi(HDR[b], temp)
                        a1 = f32(f32(s["eqcrp90"][y, reccl, b, r] * esr) * h)
                        a2 = f32(f32(s["eqcrp90rp"][y, reccl, b, r] * esr) * h)
                        s["eqcrp90rp"][Y, reccl, b, r] = f32(s["eqcrp90rp"][Y, reccl, b, r] + f32(a1 + a2))

                if Y > RECSYEAR + 1:
                    for y in range(RECSYEAR + 1, Y):
                        temp = Y - y
                        esr = svrte(alpha, temp, k, lam)
                        h = powi(HDR[b], temp)
                        a1 = f32(f32(s["eqcrp90"][y, reccl, b, r] * esr) * h)
                        a2 = f32(f32(s["eqcrp90rp"][y, reccl, b, r] * esr) * h)
                        s["eqcsr90"][Y, reccl, b, r] = f32(s["eqcsr90"][Y, reccl, b, r] + f32(a1 + a2))
                        hsr = h
                        SA = f32(SA + f32(s["eqcadd"][y, reccl, b, r] * hsr))
                        s["eqcsur"][Y, reccl, b, r] = f32(
                            s["eqcsur"][Y, reccl, b, r]
                            + f32(f32(s["eqcadd"][y, reccl, b, r] + s["eqcrep"][y, reccl, b, r]) * f32(hsr * esr)))

                # REPLACE spreads single-family replacements across classes; multifamily and
                # mobile homes replace with like.
                if b == 1:
                    s["oeqcrep"][Y, reccl, 1, r] = f32(SA - s["eqcsur"][Y, reccl, b, r])
                    replace(s, EU, r, b, reccl, 1)
                else:
                    s["eqcrep"][Y, reccl, b, r] = f32(SA - s["eqcsur"][Y, reccl, b, r])

    # REPLACE for existing single-family homes. B is 1 from here on in EIA's code.
    b = 1
    for r in range(1, NM + 1):
        for reccl in range(lo, hi + 1):
            s["oeqcrp90"][Y, reccl, b, r] = s["eqcrp90"][Y, reccl, 1, r]
            s["oeqcrp90r"][Y, reccl, b, r] = s["eqcrp90rp"][Y, reccl, 1, r]
            replace(s, EU, r, b, reccl, 2)

    for r in range(1, NM + 1):
        for reccl in range(lo, hi + 1):
            s["switchto"][Y, reccl, b, r] = 0.0
            s["switchtor"][Y, reccl, b, r] = 0.0
            for recclsw in range(lo, hi + 1):
                if recclsw != reccl:
                    s["switchto"][Y, reccl, b, r] = f32(s["switchto"][Y, reccl, b, r] + s["eqcsw90"][Y, recclsw, reccl, b, r])
                    s["switchtor"][Y, reccl, b, r] = f32(s["switchtor"][Y, reccl, b, r] + s["eqcsw90r"][Y, recclsw, reccl, b, r])

    for r in range(1, NM + 1):
        for reccl in range(lo, hi + 1):
            s["eqcrp90"][Y, reccl, b, r] = f32(s["eqcrp90"][Y, reccl, b, r] - s["switches"][Y, reccl, b, r])
            s["eqcrp90rp"][Y, reccl, b, r] = f32(
                f32(f32(s["eqcrp90rp"][Y, reccl, b, r] - s["switchesr"][Y, reccl, b, r]) + s["switchtor"][Y, reccl, b, r])
                + s["switchto"][Y, reccl, b, r])

    # Vintages of this year's equipment for later years' average-stock accounting.
    for b in range(1, NB + 1):
        for r in range(1, NM + 1):
            for reccl in range(lo, hi + 1):
                alpha, k, lam = s["rtalpha"][reccl], s["rtk"][reccl], s["rtlambda"][reccl]
                for y in range(Y, ENDYR + 1):
                    temp = y - Y
                    hsr = powi(HDR[b], temp)
                    esr = svrte(alpha, temp, k, lam)
                    s["eqr90fut"][Y, y, reccl, b, r] = f32(f32(s["eqcrp90"][Y, reccl, b, r] * esr) * hsr)
                    s["eqr90rpfut"][Y, y, reccl, b, r] = f32(f32(s["eqcrp90rp"][Y, reccl, b, r] * esr) * hsr)
                    s["eqrepfut"][Y, y, reccl, b, r] = f32(f32(s["eqcrep"][Y, reccl, b, r] * esr) * hsr)
                    s["eqaddfut"][Y, y, reccl, b, r] = f32(f32(s["eqcadd"][Y, reccl, b, r] * esr) * hsr)

    # Purchases by equipment type, for investment analysis.
    for b in range(1, NB + 1):
        for r in range(1, NM + 1):
            TYPE = int(s["rttypect"][EU])
            for recty in range(int(s["rttyeupt"][EU]) + 1, int(s["rttyeupt"][EU + 1]) + 1):
                if _valid(s, recty, Y) and int(s["rtcendiv"][recty]) == r:
                    TYPE += 1
                    eqc = int(s["rttyeqcl"][recty])
                    reccl = int(cleupt[EU]) + eqc
                    HP = s["heatingtypepurch"]
                    HP[Y, TYPE, b, r, 1] = f32(s["neqtshr"][Y, TYPE, b, r] * s["eqcadd"][Y, reccl, b, r])
                    HP[Y, TYPE, b, r, 2] = f32(
                        f32(s["neqtshr"][Y, TYPE, b, r] * f32(s["eqcrep"][Y, reccl, b, r] + s["eqcrp90rp"][Y, reccl, b, r]))
                        + f32(s["reqtshr"][Y, TYPE, b, r] * s["eqcrp90"][Y, reccl, b, r]))

    # Natural gas equipment count (class 18 = NG_WH, 23 = NG_STV, hard-coded in EIA's code).
    cls, tot = (18, "watertot") if EU == 5 else (23, "cooktot")
    first = Y == RECSYEAR + 1 and itr == 1
    for r in range(1, NM + 1):
        if first:
            s[tot][RECSYEAR, r] = 0.0
            for b in range(1, NB + 1):
                s[tot][RECSYEAR, r] = f32(s[tot][RECSYEAR, r] + s["eqcese"][RECSYEAR, cls, b, r])
        else:
            s[tot][Y, r] = 0.0
            for b in range(1, NB + 1):
                v = f32(s[tot][Y, r] + s["eqcese"][Y, cls, b, r])
                for name in ("eqcadd", "eqcrp90", "eqcrp90rp", "eqcsur", "eqcrep", "eqcsr90"):
                    v = f32(v + s[name][Y, cls, b, r])
                s[tot][Y, r] = v

    for r in range(1, NM + 1):
        yy = RECSYEAR if first else Y
        if s[tot][yy, r] > s["rsgascust"][yy, r]:
            s["rsgascust"][yy, r] = s[tot][yy, r]


def _wsum(u, cwl, load, q):
    """((1.-CWLOAD)*UEC + (UEC*CWLOAD*LOAD)) * quantity, the water heating building block."""
    return f32(f32(f32(f32(1.0) - cwl) * u + f32(f32(u * cwl) * load)) * q)


def rwhcon(s: dict) -> None:
    """RWHCON: water heating UECs, average efficiency, hot water quantity and
    consumption by fuel (H2OCON), including the solar credit."""
    EU, EUPR = 5, 3
    Y, Y1 = int(s["curcalyr"]), int(s["curiyr"])
    ALPHA = f32(-0.15)
    ef1, ef2, ef3 = f32(0.5), f32(0.35), f32(0.15)
    HHSELAS = f32(0.315)
    LEAP = _leapyr(s)
    cleupt, cleqcl = s["rtcleupt"], s["rtcleqcl"]
    lo, hi = int(cleupt[EU]) + 1, int(cleupt[EU + 1])
    _elec_price(s, EUPR)

    if Y >= RECSYEAR + 1:
        for reccl in range(lo, hi + 1):
            s["rtbaseff"][Y, reccl] = s["stkeff"][Y, reccl]

    # HHSIZE(RECSYear) is set once, in RECSYear+1, and carried. It depends only on
    # RECS-year inputs, so it is rebuilt every call.
    HHSIZE = {}
    for d in range(1, NM + 1):
        houses = f32(0.0)
        for b in range(1, NB + 1):
            houses = f32(houses + s["eh"][RECSYEAR, b, d])
        HHSIZE[RECSYEAR, d] = f32(s["mc_np16a"][d, RECSYEAR - BASEYR + 1] / houses)
    for d in range(1, NM + 1):
        houses = f32(0.0)
        for b in range(1, NB + 1):
            houses = f32(f32(houses + s["eh"][Y, b, d]) + s["nh"][Y, b, d])
        HHSIZE[Y, d] = f32(s["mc_np16a"][d, Y1] / houses)

    UEC = s["eqcuec"]
    for d in range(1, NM + 1):
        for b in range(1, NB + 1):
            for reccl in range(lo, hi + 1):
                pw = powi_real(f32(HHSIZE[Y, d] / HHSIZE[RECSYEAR, d]), HHSELAS)
                ratio_base = f32(s["rtbaseff"][RECSYEAR, reccl] / s["rtbaseff"][Y, reccl])
                s["eqcsuec"][Y, reccl, b, d] = f32(f32(UEC[d, reccl, b] * pw) * ratio_base)
                s["eqcsiuec"][Y, reccl, b, d] = f32(UEC[d, reccl, b] * ratio_base)

                # EIA repeats the same formulas in both branches for new equipment.
                wn = s["wteqceffn"][Y, reccl, b, d]
                base0 = s["rtbaseff"][RECSYEAR, reccl]
                if wn > 0.0:
                    s["eqcnuec"][Y, reccl, b, d] = f32(f32(f32(UEC[d, reccl, b] * pw) * wn) * base0)
                    s["eqcniuec"][Y, reccl, b, d] = f32(f32(UEC[d, reccl, b] * wn) * base0)
                else:
                    s["eqcnuec"][Y, reccl, b, d] = f32(UEC[d, reccl, b] * pw)
                    s["eqcniuec"][Y, reccl, b, d] = UEC[d, reccl, b]

                wr = s["wteqceffr"][Y, reccl, b, d]
                if wr > 0.0:
                    s["eqcruec"][Y, reccl, b, d] = f32(f32(f32(UEC[d, reccl, b] * pw) * wr) * base0)
                    s["eqcriuec"][Y, reccl, b, d] = f32(f32(UEC[d, reccl, b] * wr) * base0)
                else:
                    s["eqcruec"][Y, reccl, b, d] = f32(UEC[d, reccl, b] * pw)
                    s["eqcriuec"][Y, reccl, b, d] = UEC[d, reccl, b]

                if Y == RECSYEAR + 1:
                    s["eqcauec"][Y, reccl, b, d] = s["eqcnuec"][Y, reccl, b, d]
                else:
                    temp = f32(0.0)
                    for y in range(RECSYEAR + 1, Y):
                        temp = f32(temp + s["eqr90fut"][y, Y, reccl, b, d] + s["eqaddfut"][y, Y, reccl, b, d]
                                   + s["eqrepfut"][y, Y, reccl, b, d] + s["eqr90rpfut"][y, Y, reccl, b, d])
                    if temp <= 0.0:
                        s["eqcauec"][Y, reccl, b, d] = s["eqcnuec"][Y, reccl, b, d]
                    else:
                        s["eqcauec"][Y, reccl, b, d] = 0.0
                        for y in range(RECSYEAR + 1, Y):
                            s["eqcauec"][Y, reccl, b, d] = f32(s["eqcauec"][Y, reccl, b, d] + f32(
                                f32(s["eqr90fut"][y, Y, reccl, b, d] * s["eqcruec"][y, reccl, b, d])
                                + f32(f32(f32(s["eqaddfut"][y, Y, reccl, b, d] + s["eqrepfut"][y, Y, reccl, b, d])
                                          + s["eqr90rpfut"][y, Y, reccl, b, d]) * s["eqcnuec"][y, reccl, b, d])) / temp)

    # Average efficiency of the stock.
    for b in range(1, NB + 1):
        for d in range(1, NM + 1):
            for reccl in range(lo, hi + 1):
                if Y == RECSYEAR + 1:
                    s["wteqceffa"][RECSYEAR + 1, reccl, b, d] = s["wteqceffn"][RECSYEAR + 1, reccl, b, d]
                else:
                    temp = f32(0.0)
                    for y in range(RECSYEAR + 1, Y):
                        temp = f32(temp + s["eqr90fut"][y, Y, reccl, b, d] + s["eqaddfut"][y, Y, reccl, b, d]
                                   + s["eqrepfut"][y, Y, reccl, b, d] + s["eqr90rpfut"][y, Y, reccl, b, d])
                    if temp > 0.0:
                        s["wteqceffa"][Y, reccl, b, d] = 0.0
                        for y in range(RECSYEAR + 1, Y):
                            s["wteqceffa"][Y, reccl, b, d] = f32(s["wteqceffa"][Y, reccl, b, d] + f32(
                                f32(s["eqr90fut"][y, Y, reccl, b, d] * s["wteqceffr"][y, reccl, b, d])
                                + f32(f32(f32(s["eqaddfut"][y, Y, reccl, b, d] + s["eqrepfut"][y, Y, reccl, b, d])
                                          + s["eqr90rpfut"][y, Y, reccl, b, d]) * s["wteqceffn"][y, reccl, b, d])) / temp)
                    else:
                        s["wteqceffa"][Y, reccl, b, d] = s["wteqceffn"][Y, reccl, b, d]

    # Hot water quantity, used by the dishwasher and clothes washer routines.
    for d in range(1, NM + 1):
        for b in range(1, NB + 1):
            s["hotwatq"][Y, b, d] = 0.0
            for reccl in range(lo, hi + 1):
                v = f32(s["hotwatq"][Y, b, d] + s["eqcese"][Y, reccl, b, d])
                for name in ("eqcrp90", "eqcrp90rp", "eqcrep", "eqcsur", "eqcsr90"):
                    v = f32(v + s[name][Y, reccl, b, d])
                s["hotwatq"][Y, b, d] = v

    # Consumption.
    s["h2oconwt"].a[Y1 - 1, 0:5, 0:NM, 0:NB] = 0.0
    s["h2oconin"].a[Y1 - 1, 0:5, 0:NM, 0:NB] = 0.0
    s["driver"].a[Y1 - 1, 0:5, 0:NM, 0:NB] = 0.0
    for d in range(1, NM + 1):
        for reccl in range(lo, hi + 1):
            s["h2ocon"][Y1, int(cleqcl[reccl]), d] = 0.0

    # Rows of the electric and solar water heaters, found by name. (Left undefined in
    # EIA's code if a name is missing; both exist in every run.)
    for reccl in range(lo, hi + 1):
        nm = _name(s["rtclname"][reccl])
        if nm == "ELEC_WH":
            recclewh = int(cleqcl[reccl]) + lo - 1
        elif nm == "SOLAR_WH":
            recclswh = int(cleqcl[reccl]) + lo - 1

    cw = s["cwload"][RECSYEAR]
    ecw, ncw = s["ecwload"], s["ncwload"]
    for d in range(1, NM + 1):
        for b in range(1, NB + 1):
            E, N = ecw[Y, d, b], ncw[Y, d, b]
            for reccl in range(lo, hi + 1):
                f = int(s["rtfuel"][reccl])
                fcon = int(s["fwhcon"][f])
                ese, add, rp90, rp90rp = (s["eqcese"][Y, reccl, b, d], s["eqcadd"][Y, reccl, b, d],
                                          s["eqcrp90"][Y, reccl, b, d], s["eqcrp90rp"][Y, reccl, b, d])
                sr90, rep, sur = s["eqcsr90"][Y, reccl, b, d], s["eqcrep"][Y, reccl, b, d], s["eqcsur"][Y, reccl, b, d]
                suec, siuec = s["eqcsuec"][Y, reccl, b, d], s["eqcsiuec"][Y, reccl, b, d]
                nuec, niuec = s["eqcnuec"][Y, reccl, b, d], s["eqcniuec"][Y, reccl, b, d]
                ruec, riuec = s["eqcruec"][Y, reccl, b, d], s["eqcriuec"][Y, reccl, b, d]
                auec = s["eqcauec"][Y, reccl, b, d]
                if Y == RECSYEAR + 1:
                    big = f32(f32(_wsum(suec, cw, E, ese) + _wsum(nuec, cw, N, add)) + _wsum(ruec, cw, N, rp90))
                    el = _rselast(s, f, d, ALPHA, ef1, ef2, ef3, EUPR)
                    s["h2ocon"][Y1, fcon, d] = f32(s["h2ocon"][Y1, fcon, d] + f32(f32(LEAP * big) * el))
                    s["h2oconwt"][Y1, fcon, d, b] = f32(s["h2oconwt"][Y1, fcon, d, b] + f32(f32(LEAP * big) * el))
                    if f32(f32(f32(ese + add) + rp90rp) + rp90) > 0.0:
                        inn = f32(f32(_wsum(siuec, cw, E, ese) + _wsum(niuec, cw, N, add)) + _wsum(riuec, cw, N, rp90))
                        s["h2oconin"][Y1, fcon, d, b] = f32(s["h2oconin"][Y1, fcon, d, b] + inn)
                        s["driver"][Y1, fcon, d, b] = f32(s["driver"][Y1, fcon, d, b] + f32(f32(f32(ese + add) + rp90rp) + rp90))
                    s["eqceqcn"][Y1, reccl, b, d] = f32(f32(LEAP * big) * el)
                else:
                    ALPHA = f32(-0.30) if f == 4 else f32(-0.15)
                    addrp = f32(add + rp90rp)
                    reps = f32(f32(rep + sur) + sr90)
                    big = f32(f32(f32(_wsum(suec, cw, E, ese) + _wsum(nuec, cw, N, addrp)) + _wsum(ruec, cw, N, rp90))
                              + _wsum(auec, cw, E, reps))
                    el = _rselast(s, f, d, ALPHA, ef1, ef2, ef3, EUPR)
                    s["h2ocon"][Y1, fcon, d] = f32(s["h2ocon"][Y1, fcon, d] + f32(f32(LEAP * big) * el))
                    s["h2oconwt"][Y1, fcon, d, b] = f32(s["h2oconwt"][Y1, fcon, d, b] + f32(f32(LEAP * big) * el))
                    tot = f32(f32(f32(f32(f32(f32(ese + add) + rp90rp) + rp90) + sr90) + rep) + sur)
                    if tot > 0.0:
                        inn = f32(f32(f32(_wsum(siuec, cw, E, ese) + _wsum(niuec, cw, N, addrp)) + _wsum(riuec, cw, N, rp90))
                                  + _wsum(auec, cw, E, reps))
                        s["h2oconin"][Y1, fcon, d, b] = f32(s["h2oconin"][Y1, fcon, d, b] + inn)
                        s["driver"][Y1, fcon, d, b] = f32(s["driver"][Y1, fcon, d, b] + tot)
                    s["eqceqcn"][Y1, reccl, b, d] = f32(f32(LEAP * big) * el)

                # Solar is computed differently. Added once per class, as in EIA's code.
                fcon = int(s["fwhcon"][5])
                solar = _solar(s, Y, Y1, d, b, recclswh, recclewh)
                s["h2ocon"][Y1, 5, d] = f32(s["h2ocon"][Y1, 5, d] + f32(LEAP * solar))
                s["sleqcn"][Y1, 1, b, d] = f32(LEAP * solar)

    for d in range(1, NM + 1):
        s["slcon"][Y1, d] = 0.0
        for b in range(1, NB + 1):
            s["slcon"][Y1, d] = f32(s["slcon"][Y1, d] + f32(LEAP * _solar(s, Y, Y1, d, b, recclswh, recclewh)))

    for r in range(1, NM + 1):
        for fcon in range(1, 6):
            for b in range(1, NB + 1):
                if s["driver"][Y1, fcon, r, b] > 0:
                    s["h2oconin"][Y1, fcon, r, b] = f32(s["h2oconin"][Y1, fcon, r, b] / s["driver"][Y1, fcon, r, b])


def _solar(s, Y, Y1, d, b, sw, ew):
    """The bracketed solar energy credit of RWHCON (electric UEC minus solar UEC, in
    fossil terms), before the LEAPYR factor."""
    uec, who = s["eqcuec"], s["whrfoss"][d, Y1]
    k = f32(3412.0)
    e = uec[d, ew, b]

    def part(q, u):
        return f32(q * f32(f32(f32(e - u) * who) / k))

    t = part(s["eqcese"][Y, sw, b, d], uec[d, sw, b])
    t = f32(t + part(s["eqcrp90"][Y, sw, b, d], s["eqcruec"][Y, sw, b, d]))
    t = f32(t + part(s["eqcadd"][Y, sw, b, d], s["eqchvuec"][Y, sw, b, d]))
    t = f32(t + part(f32(s["eqcrep"][Y, sw, b, d] + s["eqcrp90rp"][Y, sw, b, d]), s["eqcnuec"][Y, sw, b, d]))
    t = f32(t + part(f32(s["eqcsr90"][Y, sw, b, d] + s["eqcsur"][Y, sw, b, d]), s["eqcauec"][Y, sw, b, d]))
    return t


def rstovcon(s: dict) -> None:
    """RSTOVCON: cooking UECs, average efficiency and consumption by fuel (CKCON)."""
    EU, EUPR = 6, 4
    Y, Y1 = int(s["curcalyr"]), int(s["curiyr"])
    ALPHA = f32(0.0)
    ef1, ef2, ef3 = f32(0.5), f32(0.35), f32(0.15)
    LEAP = _leapyr(s)
    cleupt, cleqcl = s["rtcleupt"], s["rtcleqcl"]
    lo, hi = int(cleupt[EU]) + 1, int(cleupt[EU + 1])
    nfl = int(s["nstvfl"])
    _elec_price(s, EUPR)

    if Y >= RECSYEAR + 1:
        for reccl in range(lo, hi + 1):
            s["rtbaseff"][Y, reccl] = s["stkeff"][Y, reccl]

    UEC = s["eqcuec"]
    for d in range(1, NM + 1):
        for b in range(1, NB + 1):
            for reccl in range(lo, hi + 1):
                base0 = s["rtbaseff"][RECSYEAR, reccl]
                s["eqcsuec"][Y, reccl, b, d] = f32(UEC[d, reccl, b] * f32(base0 / s["rtbaseff"][Y, reccl]))
                wn = s["wteqceffn"][Y, reccl, b, d]
                s["eqcnuec"][Y, reccl, b, d] = f32(UEC[d, reccl, b] * f32(base0 / wn)) if wn > 0.0 else UEC[d, reccl, b]
                wr = s["wteqceffr"][Y, reccl, b, d]
                s["eqcruec"][Y, reccl, b, d] = f32(UEC[d, reccl, b] * f32(base0 / wr)) if wr > 0.0 else UEC[d, reccl, b]
                if Y == RECSYEAR + 1:
                    s["eqcauec"][Y, reccl, b, d] = s["eqcnuec"][Y, reccl, b, d]
                else:
                    # Unlike water heating, the vintage sums start at RECSYear (kept).
                    temp = f32(0.0)
                    for y in range(RECSYEAR, Y):
                        temp = f32(temp + s["eqr90fut"][y, Y, reccl, b, d] + s["eqaddfut"][y, Y, reccl, b, d]
                                   + s["eqrepfut"][y, Y, reccl, b, d] + s["eqr90rpfut"][y, Y, reccl, b, d])
                    if temp <= 0.0:
                        s["eqcauec"][Y, reccl, b, d] = s["eqcnuec"][Y, reccl, b, d]
                    else:
                        s["eqcauec"][Y, reccl, b, d] = 0.0
                        for y in range(RECSYEAR, Y):
                            s["eqcauec"][Y, reccl, b, d] = f32(s["eqcauec"][Y, reccl, b, d] + f32(
                                f32(s["eqr90fut"][y, Y, reccl, b, d] * s["eqcruec"][y, reccl, b, d])
                                + f32(f32(f32(s["eqaddfut"][y, Y, reccl, b, d] + s["eqrepfut"][y, Y, reccl, b, d])
                                          + s["eqr90rpfut"][y, Y, reccl, b, d]) * s["eqcnuec"][y, reccl, b, d])) / temp)

    for b in range(1, NB + 1):
        for d in range(1, NM + 1):
            for reccl in range(lo, hi + 1):
                if Y == RECSYEAR + 1:
                    s["wteqceffa"][RECSYEAR + 1, reccl, b, d] = s["wteqceffn"][RECSYEAR + 1, reccl, b, d]
                else:
                    temp = f32(0.0)
                    for y in range(RECSYEAR, Y):
                        temp = f32(temp + s["eqr90fut"][y, Y, reccl, b, d] + s["eqaddfut"][y, Y, reccl, b, d]
                                   + s["eqrepfut"][y, Y, reccl, b, d] + s["eqr90rpfut"][y, Y, reccl, b, d])
                    if temp > 0.0:
                        s["wteqceffa"][Y, reccl, b, d] = 0.0
                        for y in range(RECSYEAR, Y):
                            s["wteqceffa"][Y, reccl, b, d] = f32(s["wteqceffa"][Y, reccl, b, d] + f32(
                                f32(s["eqr90fut"][y, Y, reccl, b, d] * s["wteqceffr"][y, reccl, b, d])
                                + f32(f32(f32(s["eqaddfut"][y, Y, reccl, b, d] + s["eqrepfut"][y, Y, reccl, b, d])
                                          + s["eqr90rpfut"][y, Y, reccl, b, d]) * s["wteqceffn"][y, reccl, b, d])) / temp)
                    else:
                        s["wteqceffa"][Y, reccl, b, d] = s["wteqceffn"][Y, reccl, b, d]

    s["ckcon"].a[Y1 - 1, 0:nfl, 0:NM] = 0.0
    for name in ("ckconwt", "driver", "ckconin"):
        s[name].a[Y1 - 1, 0:nfl, 0:NM, 0:NB] = 0.0

    for d in range(1, NM + 1):
        for b in range(1, NB + 1):
            for reccl in range(lo, hi + 1):
                f = int(s["rtfuel"][reccl])
                fcon = int(s["fstvcon"][f])
                ese, add, rp90, rp90rp = (s["eqcese"][Y, reccl, b, d], s["eqcadd"][Y, reccl, b, d],
                                          s["eqcrp90"][Y, reccl, b, d], s["eqcrp90rp"][Y, reccl, b, d])
                sr90, rep, sur = s["eqcsr90"][Y, reccl, b, d], s["eqcrep"][Y, reccl, b, d], s["eqcsur"][Y, reccl, b, d]
                suec, nuec, ruec, auec = (s["eqcsuec"][Y, reccl, b, d], s["eqcnuec"][Y, reccl, b, d],
                                          s["eqcruec"][Y, reccl, b, d], s["eqcauec"][Y, reccl, b, d])
                el = _rselast(s, f, d, ALPHA, ef1, ef2, ef3, EUPR)
                if Y == RECSYEAR + 1:
                    big = f32(f32(f32(f32(ese * suec) + f32(add * nuec)) + f32(rp90rp * nuec)) + f32(rp90 * ruec))
                    s["ckcon"][Y1, fcon, d] = f32(s["ckcon"][Y1, fcon, d] + f32(f32(LEAP * big) * el))
                    s["ckconwt"][Y1, fcon, d, b] = f32(s["ckconwt"][Y1, fcon, d, b] + f32(f32(LEAP * big) * el))
                    q = f32(f32(f32(ese + add) + rp90rp) + rp90)
                    if q > 0.0:
                        s["ckconin"][Y1, fcon, d, b] = f32(s["ckconin"][Y1, fcon, d, b] + big)
                        s["driver"][Y1, fcon, d, b] = f32(s["driver"][Y1, fcon, d, b] + q)
                    # Same terms in a different order than the CKCON sum (rounding only).
                    s["eqceqcn"][Y1, reccl, b, d] = f32(f32(LEAP * f32(f32(f32(f32(ese * suec) + f32(rp90rp * nuec))
                                                                          + f32(add * nuec)) + f32(rp90 * ruec))) * el)
                else:
                    big = f32(f32(f32(f32(f32(f32(f32(ese * suec) + f32(add * nuec)) + f32(rp90 * ruec))
                                          + f32(rp90rp * nuec)) + f32(sr90 * auec)) + f32(rep * nuec)) + f32(sur * auec))
                    s["ckcon"][Y1, fcon, d] = f32(s["ckcon"][Y1, fcon, d] + f32(f32(LEAP * big) * el))
                    s["ckconwt"][Y1, fcon, d, b] = f32(s["ckconwt"][Y1, fcon, d, b] + f32(f32(LEAP * big) * el))
                    q = f32(f32(f32(f32(f32(f32(ese + add) + rp90rp) + rp90) + sr90) + rep) + sur)
                    if q > 0.0:
                        s["ckconin"][Y1, fcon, d, b] = f32(s["ckconin"][Y1, fcon, d, b] + big)
                        s["driver"][Y1, fcon, d, b] = f32(s["driver"][Y1, fcon, d, b] + q)
                    s["eqceqcn"][Y1, reccl, b, d] = f32(f32(LEAP * big) * el)

    for r in range(1, NM + 1):
        for fcon in range(1, nfl + 1):
            for b in range(1, NB + 1):
                if s["driver"][Y1, fcon, r, b] > 0:
                    s["ckconin"][Y1, fcon, r, b] = f32(s["ckconin"][Y1, fcon, r, b] / s["driver"][Y1, fcon, r, b])
