"""Space heating: RSHVAC (HVAC package and shell choice) and RHTRTEC (equipment choice).

RSHVAC runs just before RHTRTEC each year. It prices every heating equipment and
shell package combination for new homes (equipment + shell + central AC cost, plus
heating and cooling operating cost), turns that into logit weights, and from them
the shell-package shares, the weighted heating and cooling shell factors and the
share-weighted efficiency and floor-area factors of new heating and cooling
equipment. RHTRTEC does the equipment choice itself: logit weights for replacement
and new equipment, shares by equipment type, weighted efficiencies, and the
fuel-system (class) shares of new homes with a lagged logit.

Writes to the debug units (RDM_OUT.txt, AppBetaData.txt) are skipped.

EIA's locals are all SAVEd (the oracle builds with -fno-automatic, zero-initialised),
so a few of them carry between calls. They live in s["_hv"] and s["heatsys"]:
see the module notes in each routine. Both routines read PELRSOUT, which the
oracle did not dump; the caller supplies s["pelrsout"] as [division, iyr, end use].
"""

import numpy as np

from nems_open.fortran_array import FArray
from nems_open.residential.common import BASEYR, MNUMBLDG, NUM_DIV, RECSYEAR, f32, powi

MNUMHVAC = 3500
N_HEAT_TYPES = 30
N_HEAT_CLASSES = 10
N_COOL_TYPES = 16
N_COOL_CLASSES = 5
N_SHELL_TYPES = 5
COSTTRSW = 0  # PARAMETER in rtek: the EQCOST cost trend function is switched off
EPA111D = 0  # RTOVALUE("EPA111D") from the run's options file


def _ones_based(a):
    """A Fortran 1-based Python list of a 1-D FArray's values: ints as Python ints,
    reals as float32 scalars so that arithmetic on them stays single precision."""
    return [None] + (a.a.tolist() if a.a.dtype.kind == "i" else list(a.a))


def _decay(s):
    """DECAY: annuity factor for life-cycle cost, from the discount rate and tenure.
    EIA sets it on iteration 1 only and the SAVEd value carries; it never changes,
    so it is recomputed here on every call."""
    rate, tenure = f32(s["resdiscountrate"]), f32(s["tenure"])
    return f32(f32(f32(1.0) - np.power(f32(f32(1.0) + rate), f32(-tenure))) / rate)


def _private(s):
    """EIA's SAVEd locals and COMMON arrays that RSHVAC reads before (or without)
    writing them in the same call."""
    p = s.get("_hv")
    if p is None:
        yr = (RECSYEAR, 2050)
        p = s["_hv"] = dict(
            hveqwtn=FArray.zeros([yr, (1, N_HEAT_TYPES), (1, N_SHELL_TYPES), (1, MNUMBLDG), (1, 9)]),
            htsq=FArray.zeros([yr, (1, N_HEAT_TYPES), (1, 9), (1, MNUMBLDG)]),
            clsq=FArray.zeros([yr, (1, N_HEAT_TYPES), (1, 9), (1, MNUMBLDG)]),
            eqpeff=[f32(0.0)] * (N_HEAT_TYPES + 1),
            effweight=FArray.zeros([yr, (1, N_HEAT_TYPES), (1, MNUMBLDG), (1, 9)]),
            sqftweight=FArray.zeros([yr, (1, N_HEAT_TYPES), (1, MNUMBLDG), (1, 9)]),
            effweightc=FArray.zeros([yr, (1, N_COOL_TYPES), (1, MNUMBLDG), (1, 9)]),
            sqftweightc=FArray.zeros([yr, (1, N_COOL_TYPES), (1, MNUMBLDG), (1, 9)]),
        )
    return p


def _shllearn(s, Y):
    """SHLLEARN(Y, B, R), EIA's learning factor on ENERGY STAR shell betas. A SAVEd
    local that builds on last year's value, but last year's value is just this same
    recursion, so it is rebuilt from LEARNFACT."""
    lf = s["learnfact"]
    out = {(b, r): f32(1.0) for b in range(1, MNUMBLDG + 1) for r in range(1, NUM_DIV + 1)}
    for y in range(RECSYEAR + 2, Y + 1):
        for r in range(1, NUM_DIV + 1):
            for b in range(1, MNUMBLDG + 1):
                out[b, r] = f32(out[b, r] * powi(lf[b, r], y - (RECSYEAR + 1)))
    return out


def _sqft_factors(s, p, Y, R, B, rows, cand, hvhteqty, hvcleqty, hvheatfactor, hvcoolfactor, rteqtype):
    """Write HTSQRFOOTFAC and CLSQRFOOTFAC for one (R, B) the way RSHVAC's first pass
    does: one write per shell record, from SQRFOOT and the record's area factors."""
    sq = s["sqrfoot"]
    for hv in rows:
        if not (s["hvfyear"][hv] <= Y <= s["hvlyear"][hv]):
            continue
        HVT, HVCT = hvhteqty[hv], hvcleqty[hv]
        if not any(rteqtype[r] == HVT for r in cand):
            continue
        ratio = f32(f32(sq[Y, B, R] / sq[RECSYEAR + 1, B, R]) - f32(1.0))
        p["htsq"][Y, HVT, R, B] = f32(f32(1.0) + f32(ratio * f32(hvheatfactor[hv] / f32(1.10))))
        p["clsq"][Y, HVCT, R, B] = f32(f32(1.0) + f32(ratio * f32(hvcoolfactor[hv] / f32(1.10))))


def rshvac(s: dict) -> None:
    """RSHVAC. Reads s["pelrsout"] for the heating (1) and cooling (2) electricity prices.

    Carried between calls, kept in s["_hv"]: HVEQWTN, HTSQRFOOTFAC, CLSQRFOOTFAC (COMMON,
    so they keep last iteration's values), EQPEFF, EFFWEIGHT, SQFTWEIGHT, EFFWEIGHTC,
    SQFTWEIGHTC (SAVEd). On iterations after the first, the two square-footage factor
    arrays are first filled the way the previous iteration left them, because
    EIA reads CLSQRFOOTFAC(Y, HVT, ...) with a heating index before it is written
    this pass.
    """
    Y, Y1, itr = int(s["curcalyr"]), int(s["curiyr"]), int(s["curitr"])
    EU, EUPR = 1, 1
    s["alpha1"] = f32(-0.50)
    p = _private(s)
    with np.errstate(all="ignore"):
        _rshvac(s, p, Y, Y1, itr, EU, EUPR)


def _rshvac(s, p, Y, Y1, itr, EU, EUPR):
    NR = NUM_DIV
    shllearn = _shllearn(s, Y)

    # MAP ELECTRICITY PRICE ARRAY INTO RESIDENTIAL PRICE ARRAY
    gdp = s["mc_jpgdp"]
    infl = f32(gdp[int(s["rtekdollaryr"]) - BASEYR + 1] / gdp[-2])
    EPRICE = {}
    for R in range(1, NR + 1):
        s["prices"][4, R, Y] = f32(s["pelrsout"][R, Y1, EUPR] * infl)
        EPRICE[R] = f32(s["pelrsout"][R, Y1, 2] * infl)

    # COMPUTE WEATHER ADJUSTMENT FACTORS
    HDDFACT, CDDFACT = {}, {}
    for R in range(1, NR + 1):
        h = f32(s["hddadj"][Y, R] / s["hddadj"][RECSYEAR, R])
        HDDFACT[R] = f32(h * h)  # **2.00
        c = f32(s["cddadj"][Y, R] / s["cddadj"][RECSYEAR, R])
        CDDFACT[R] = f32(np.power(c, f32(1.50)))

    DECAY = _decay(s)

    # INITIALIZE ARRAYS
    TOTEWTN = {}
    for B in range(1, MNUMBLDG + 1):
        for R in range(1, NR + 1):
            for c in range(1, N_HEAT_CLASSES + 1):
                s["hshell"][Y, c, B, R] = 0.0
            for c in range(1, N_COOL_CLASSES + 1):
                s["cshell"][Y, c, B, R] = 0.0
    TOTEWTNC, EQWTNCA, COOLSHWT = {}, {}, {}

    def g(d, k):
        return d.get(k, f32(0.0))

    # input tables as 1-based lists, so the per-record loops stay fast
    rscendiv, rsbtype = _ones_based(s["rscendiv"]), _ones_based(s["rsbtype"])
    hvhteqty, hvhteqcl = _ones_based(s["hvhteqty"]), _ones_based(s["hvhteqcl"])
    hvcleqty, hvcleqcl = _ones_based(s["hvcleqty"]), _ones_based(s["hvcleqcl"])
    hvfyear, hvlyear = _ones_based(s["hvfyear"]), _ones_based(s["hvlyear"])
    hvpackg = _ones_based(s["hvpackg"])
    hvheatfactor, hvcoolfactor = _ones_based(s["hvheatfactor"]), _ones_based(s["hvcoolfactor"])
    htsheff, clsheff = _ones_based(s["htsheff"]), _ones_based(s["clsheff"])
    htshbase, clshbase = _ones_based(s["htshbase"]), _ones_based(s["clshbase"])
    shelcost, shelsub, shelsub111d = _ones_based(s["shelcost"]), _ones_based(s["shelsub"]), _ones_based(s["shelsub111d"])
    rtinityr, rtlastyr, rtcendiv = _ones_based(s["rtinityr"]), _ones_based(s["rtlastyr"]), _ones_based(s["rtcendiv"])
    rteqtype, rttyeqcl, rtfuel = _ones_based(s["rteqtype"]), _ones_based(s["rttyeqcl"]), _ones_based(s["rtfuel"])
    rteqeff, rteqcost = _ones_based(s["rteqeff"]), _ones_based(s["rteqcost"])
    rtcleupt, rttyeupt = _ones_based(s["rtcleupt"]), _ones_based(s["rttyeupt"])
    rtcleqcl = _ones_based(s["rtcleqcl"])

    rows_by = {(R, B): [] for R in range(1, NR + 1) for B in range(1, MNUMBLDG + 1)}
    for hv in range(1, MNUMHVAC + 1):
        k = (rscendiv[hv], rsbtype[hv])
        if k in rows_by:
            rows_by[k].append(hv)

    def cands(R, lo, hi):
        return [r for r in range(lo, hi + 1) if rtinityr[r] <= Y <= rtlastyr[r] and rtcendiv[r] == R]

    htsq, clsq = p["htsq"], p["clsq"]
    if itr != 1:
        for R in range(1, NR + 1):
            cand = cands(R, rttyeupt[EU] + 1, rttyeupt[EU + 1])
            for B in range(1, MNUMBLDG + 1):
                _sqft_factors(s, p, Y, R, B, rows_by[R, B], cand, hvhteqty, hvcleqty,
                              hvheatfactor, hvcoolfactor, rteqtype)

    hveqwtn, eqpeff = p["hveqwtn"], p["eqpeff"]
    HTSHELLFAC, CLSHELLFAC = {}, {}
    HVBETA2A = {}
    ESTARHISTYR = int(s["estarhistyr"])
    yb = min(Y, ESTARHISTYR)

    for R in range(1, NR + 1):
        cand = cands(R, rttyeupt[EU] + 1, rttyeupt[EU + 1])
        for B in range(1, MNUMBLDG + 1):
            rows = rows_by[R, B]
            for HVRCTY in rows:
                HVT, HVC = hvhteqty[HVRCTY], hvhteqcl[HVRCTY]
                HVCT, HVCC = hvcleqty[HVRCTY], hvcleqcl[HVRCTY]
                S = hvpackg[HVRCTY]
                if not (hvfyear[HVRCTY] <= Y <= hvlyear[HVRCTY]):
                    continue
                for RECTY in cand:
                    EQT, EQC = rteqtype[RECTY], rttyeqcl[RECTY]
                    RECCL = rtcleupt[EU] + EQC
                    F = rtfuel[RECCL]
                    # RECCL1 maps the heating class to its cooling class
                    if RECCL == 2:
                        RECCL1 = 13
                    elif RECCL == 9:
                        RECCL1 = 14
                    elif RECCL == 10:
                        RECCL1 = 15
                    else:
                        RECCL1 = 12
                    if EQT != HVT:
                        continue
                    s["shlevelh"][Y, HVC, S, B, R] = 0.0
                    eqpeff[HVT] = rteqeff[RECTY]
                    if rteqeff[RECTY] != 0.0:
                        RTEFFAC2 = f32(s["rtbaseff"][RECSYEAR, RECCL] / rteqeff[RECTY])
                    else:
                        RTEFFAC2 = s["rtbaseff"][RECSYEAR, RECCL]
                    if s["aceff"][HVCT, Y, R] != 0.0:
                        RTEFFAC3 = f32(s["rtbaseff"][RECSYEAR, HVCC] / s["aceff"][HVCT, Y, R])
                    else:
                        RTEFFAC3 = s["rtbaseff"][RECSYEAR, HVCC]

                    HTSHELLFAC[R, B] = f32(htsheff[HVRCTY] / htshbase[HVRCTY])
                    CLSHELLFAC[R, B] = f32(clsheff[HVRCTY] / clshbase[HVRCTY])

                    ratio = f32(f32(s["sqrfoot"][Y, B, R] / s["sqrfoot"][RECSYEAR + 1, B, R]) - f32(1.0))
                    htsq[Y, HVT, R, B] = f32(f32(1.0) + f32(ratio * f32(hvheatfactor[HVRCTY] / f32(1.10))))
                    clsq[Y, HVCT, R, B] = f32(f32(1.0) + f32(ratio * f32(hvcoolfactor[HVRCTY] / f32(1.10))))

                    # COSTTRSW = 0: constant capital cost from the equipment file
                    CAPITAL = f32(f32(rteqcost[RECTY] + shelcost[HVRCTY]) + s["acicost"][HVCT, Y, R])
                    s["shellsubsidy"][Y, RECCL, S, B, R] = f32(
                        shelsub[HVRCTY] + f32(shelsub111d[HVRCTY] * f32(EPA111D)))
                    s["shellsubsidy111d"][Y, RECCL, S, B, R] = f32(shelsub111d[HVRCTY] * f32(EPA111D))

                    s["shellinvest"][Y, RECCL, S, B, R] = f32(
                        f32(CAPITAL - rteqcost[RECTY]) - s["acicost"][HVCT, Y, R])

                    # CLSQRFOOTFAC is read with the heating type index (EIA quirk)
                    heat = f32(f32(f32(f32(f32(f32(s["prices"][F, R, Y] * s["newheatuec"][RECCL, B, R])
                                                / s["baseload"][RECCL]) * RTEFFAC2) * HDDFACT[R])
                                   * htsq[Y, HVT, R, B]) * HTSHELLFAC[R, B])
                    cool = f32(f32(f32(f32(f32(f32(EPRICE[R] * s["newcooluec"][B, R])
                                                / s["baseload"][RECCL1]) * RTEFFAC3) * CDDFACT[R])
                                   * clsq[Y, HVT, R, B]) * CLSHELLFAC[R, B])
                    HVOPCOST = f32(heat + cool)
                    HVLFCY = f32(CAPITAL + f32(HVOPCOST * DECAY))

                    if S > 2:
                        HVBETA2A[HVRCTY] = f32(s["hvbeta2"][yb, B, S, R] * shllearn[B, R])
                    else:
                        HVBETA2A[HVRCTY] = s["hvbeta2"][yb, B, S, R]

                    # B = 1 and CurCalYr > RECSYear always holds here, so both branches compute
                    hveqwtn[Y, HVT, S, B, R] = f32(np.exp(f32(
                        HVBETA2A[HVRCTY] + f32(s["hvbeta1"][yb, B, S, R] * HVLFCY))))

                    w = hveqwtn[Y, HVT, S, B, R]
                    TOTEWTN[HVC, B, R] = f32(g(TOTEWTN, (HVC, B, R)) + w)
                    EQWTNCA[HVCT, B, R] = f32(g(EQWTNCA, (HVCT, B, R)) + w)
                    COOLSHWT[HVCT, B, R] = f32(g(COOLSHWT, (HVCT, B, R)) + f32(w * clsheff[HVRCTY]))
                    TOTEWTNC[HVCC, B, R] = f32(g(TOTEWTNC, (HVCC, B, R)) + w)

            # raw logit exponents are in; compute shares
            for HE in range(1, N_HEAT_TYPES + 1):
                EQFSHRN = f32(0.0)
                s["hveqshr"][Y, HE, B, R] = 0.0
                for HVRCTY in rows:
                    HVC, HVT = hvhteqcl[HVRCTY], hvhteqty[HVRCTY]
                    S = hvpackg[HVRCTY]
                    if hvfyear[HVRCTY] <= Y <= hvlyear[HVRCTY] and HE == HVT:
                        tot = g(TOTEWTN, (HVC, B, R))
                        if tot > 0.0:
                            s["htshellwt"][Y, HVT, S, B, R] = f32(hveqwtn[Y, HVT, S, B, R] / tot)
                            s["htshelleffwt"][Y, HVT, S, B, R] = f32(s["htshellwt"][Y, HVT, S, B, R] * htsheff[HVRCTY])
                        else:
                            s["htshelleffwt"][Y, HVT, S, B, R] = 0.0
                            s["htshellwt"][Y, HVT, S, B, R] = 0.0
                        s["hshell"][Y, HVC, B, R] = f32(s["hshell"][Y, HVC, B, R] + s["htshelleffwt"][Y, HVT, S, B, R])
                        s["shlevelh"][Y, HVC, S, B, R] = f32(
                            s["shlevelh"][Y, HVC, S, B, R] + f32(hveqwtn[Y, HVT, S, B, R] / tot))
                        if tot > 0.0:
                            EQFSHRN = f32(EQFSHRN + f32(hveqwtn[Y, HVT, S, B, R] / tot))
                        else:
                            EQFSHRN = f32(0.0)
                        s["hveqshr"][Y, HE, B, R] = EQFSHRN

            # weighted efficiency and square-footage factor for each heating type
            for HVT in range(1, N_HEAT_TYPES + 1):
                if eqpeff[HVT] > 0.0:
                    p["effweight"][Y, HVT, B, R] = f32(s["hveqshr"][Y, HVT, B, R] / eqpeff[HVT])
                p["sqftweight"][Y, HVT, B, R] = f32(s["hveqshr"][Y, HVT, B, R] * htsq[Y, HVT, R, B])

    # WEIGHTED EFFICIENCY FOR NEW AND REPLACEMENT SPACE HEATING EQUIPMENT
    for R in range(1, NR + 1):
        cand = cands(R, rttyeupt[EU] + 1, rttyeupt[EU + 1])
        for B in range(1, MNUMBLDG + 1):
            for RECCL in range(rtcleupt[EU] + 1, rtcleupt[EU + 1] + 1):
                EQC = rtcleqcl[RECCL]
                DENOM = f32(0.0)
                recar, eqtar = [], []
                for RECTY in cand:
                    if rttyeqcl[RECTY] == EQC:
                        EQT = rteqtype[RECTY]
                        recar.append(RECTY)
                        eqtar.append(EQT)
                        DENOM = f32(DENOM + s["hveqshr"][Y, EQT, B, R])
                if DENOM <= 0.0:
                    s["wteqceffhv"][Y, RECCL, B, R] = f32(f32(1.0) / s["rtbaseff"][RECSYEAR, RECCL])
                    s["wteqcsqfhv"][Y, RECCL, B, R] = 1.0
                else:
                    SUM, SUM1 = f32(0.0), f32(0.0)
                    for TYPE in eqtar:
                        SUM = f32(SUM + p["effweight"][Y, TYPE, B, R])
                        SUM1 = f32(SUM1 + p["sqftweight"][Y, TYPE, B, R])
                    s["wteqcsqfhv"][Y, RECCL, B, R] = f32(SUM1 / DENOM)
                    s["wteqceffhv"][Y, RECCL, B, R] = f32(SUM / DENOM)

    # DONE WITH SPACE HEATING; SWITCH TO SPACE COOLING CALCULATIONS
    EU = 2
    effc, sqftc = p["effweightc"], p["sqftweightc"]
    CLSHELLWT_known = {}
    for B in range(1, MNUMBLDG + 1):
        for R in range(1, NR + 1):
            EQFSHRNC = {}
            for HC in range(4, N_COOL_TYPES + 1):
                EQFSHRNC[HC] = f32(0.0)
                s["neqtshrc"][Y, HC, B, R] = 0.0
                if HC < 8:
                    HVCC = 2
                if 7 < HC < 12:
                    HVCC = 3
                if 11 < HC < 16:
                    HVCC = 4
                if HC == 16:
                    HVCC = 5
                tot = g(TOTEWTNC, (HVCC, B, R))
                if tot > 0.0:
                    s["clshellwt"][Y, HC, B, R] = f32(g(COOLSHWT, (HC, B, R)) / tot)
                else:
                    s["clshellwt"][Y, HC, B, R] = 0.0
                s["cshell"][Y, HVCC, B, R] = f32(s["cshell"][Y, HVCC, B, R] + s["clshellwt"][Y, HC, B, R])
                if tot > 0.0:
                    EQFSHRNC[HC] = f32(g(EQWTNCA, (HC, B, R)) / tot)
                else:
                    EQFSHRNC[HC] = f32(0.0)
                s["neqtshrc"][Y, HC, B, R] = EQFSHRNC[HC]

            for HVCT in range(4, N_COOL_TYPES + 1):
                if s["aceff"][HVCT, Y, R] > 0.0:
                    effc[Y, HVCT, B, R] = f32(s["neqtshrc"][Y, HVCT, B, R] / s["aceff"][HVCT, Y, R])
                sqftc[Y, HVCT, B, R] = f32(s["neqtshrc"][Y, HVCT, B, R] * clsq[Y, HVCT, R, B])

            # processes the cooling classes, skipping the first (ROOM_AIR)
            for RECCL in range(rtcleupt[EU] + 2, rtcleupt[EU + 1] + 1):
                EQC = rtcleqcl[RECCL]
                DENOM = f32(0.0)
                recar, eqtar = [], []
                # EIA starts at RTTYEUPT(EU), the last heating record, not at the first cooling one
                for RECTY in range(rttyeupt[EU], rttyeupt[EU + 1] + 1):
                    if rtinityr[RECTY] <= Y <= rtlastyr[RECTY]:
                        if rtcendiv[RECTY] == R:
                            if rttyeqcl[RECTY] == EQC:
                                EQT = rteqtype[RECTY]
                                recar.append(RECTY)
                                eqtar.append(EQT)
                                DENOM = f32(DENOM + s["neqtshrc"][Y, EQT, B, R])
                if DENOM <= 0.0:
                    s["wteqceffhv"][Y, RECCL, B, R] = f32(f32(1.0) / s["rtbaseff"][RECSYEAR, RECCL])
                    s["wteqcsqfhv"][Y, RECCL, B, R] = 1.0
                else:
                    SUM, SUM1 = f32(0.0), f32(0.0)
                    for TYPE in eqtar:
                        SUM = f32(SUM + effc[Y, TYPE, B, R])
                        SUM1 = f32(SUM1 + sqftc[Y, TYPE, B, R])
                    s["wteqcsqfhv"][Y, RECCL, B, R] = f32(SUM1 / DENOM)
                    s["wteqceffhv"][Y, RECCL, B, R] = f32(SUM / DENOM)
                if s["wteqceffhv"][Y, RECCL, B, R] == 0.0:
                    s["wteqceffhv"][Y, RECCL, B, R] = f32(f32(1.0) / s["rtbaseff"][RECSYEAR, RECCL])


def rhtrtec(s: dict) -> None:
    """RHTRTEC. Reads s["pelrsout"] for the heating electricity price.

    HEATSYS(year, type, B, R) is a SAVEd local that builds on last year's value
    (a 0.9 lag), so it carries across years. It is kept in s["heatsys"] and must
    hold last year's values on entry (zero before the first model year).
    HTYSSHR (COMMON TESTHT) is kept in s["htysshr"]; only HSYSSHR leaves the routine.
    """
    Y, Y1 = int(s["curcalyr"]), int(s["curiyr"])
    EU, EUPR = 1, 1
    s["alpha1"] = f32(-0.50)
    if "heatsys" not in s:
        s["heatsys"] = FArray.zeros([(RECSYEAR, 2050), (1, N_HEAT_TYPES), (1, MNUMBLDG), (1, 9)])
    if "htysshr" not in s:
        s["htysshr"] = FArray.zeros([(RECSYEAR, 2050), (1, N_HEAT_CLASSES), (1, MNUMBLDG), (1, 9)])
    with np.errstate(all="ignore"):
        _rhtrtec(s, Y, Y1, EU, EUPR)


def _rhtrtec(s, Y, Y1, EU, EUPR):
    NR = NUM_DIV
    ALPHA1 = s["alpha1"]
    BLDRWT = f32(6.0)  # discounts the fuel price impact in the builders' fuel choice

    # MAP ELECTRICITY PRICE ARRAY INTO RESIDENTIAL PRICE ARRAY
    gdp = s["mc_jpgdp"]
    infl = f32(gdp[int(s["rtekdollaryr"]) - BASEYR + 1] / gdp[-2])
    for R in range(1, NR + 1):
        s["prices"][4, R, Y] = f32(s["pelrsout"][R, Y1, EUPR] * infl)

    HDDFACT = {}
    for R in range(1, NR + 1):
        h = f32(s["hddadj"][Y, R] / s["hddadj"][RECSYEAR, R])
        HDDFACT[R] = f32(h * h)  # **2.00

    DECAY = _decay(s)

    rtinityr, rtlastyr, rtcendiv = _ones_based(s["rtinityr"]), _ones_based(s["rtlastyr"]), _ones_based(s["rtcendiv"])
    rteqtype, rttyeqcl = _ones_based(s["rteqtype"]), _ones_based(s["rttyeqcl"])
    rtfuel, rteqeff = _ones_based(s["rtfuel"]), _ones_based(s["rteqeff"])
    rteqcost, rtrecost = _ones_based(s["rteqcost"]), _ones_based(s["rtrecost"])
    rtecbias, rtecbta1 = _ones_based(s["rtecbias"]), _ones_based(s["rtecbta1"])
    rtecbta2, rtecbta3 = _ones_based(s["rtecbta2"]), _ones_based(s["rtecbta3"])
    rtcleupt, rttyeupt, rttypect = _ones_based(s["rtcleupt"]), _ones_based(s["rttyeupt"]), _ones_based(s["rttypect"])
    rtcleqcl, rtcltypt = _ones_based(s["rtcleqcl"]), _ones_based(s["rtcltypt"])
    rtfcbeta = _ones_based(s["rtfcbeta"])
    P = s["prices"]
    LFCY, BETA1DR = s["lfcy"], s["beta1dr"]
    HEATSYS = s["heatsys"]

    for R in range(1, NR + 1):
        cand = [r for r in range(rttyeupt[EU] + 1, rttyeupt[EU + 1] + 1)
                if rtinityr[r] <= Y <= rtlastyr[r] and rtcendiv[r] == R]
        for B in range(1, MNUMBLDG + 1):
            TOTEWTR, TOTEWTN, EQWTR, EQWTN = {}, {}, {}, {}
            for RECCL in range(rtcleupt[EU] + 1, rtcleupt[EU + 1] + 1):
                TOTEWTR[RECCL] = f32(0.0)
                TOTEWTN[RECCL] = f32(0.0)

            for RECTY in cand:
                EQT, EQC = rteqtype[RECTY], rttyeqcl[RECTY]
                RECCL = rtcleupt[EU] + EQC
                F = rtfuel[RECCL]

                # RTEFFAC(1) adjusts UECs of replacements for RECS-year stock, (2) new construction
                if rteqeff[RECTY] != 0.0:
                    RTEFFAC1 = f32(s["eqceff"][Y, RECCL] / rteqeff[RECTY])
                    RTEFFAC2 = f32(s["rtbaseff"][RECSYEAR, RECCL] / rteqeff[RECTY])
                else:
                    RTEFFAC1 = s["rtbaseff"][RECSYEAR, RECCL]
                    RTEFFAC2 = s["rtbaseff"][RECSYEAR, RECCL]

                # COSTTRSW = 0: constant capital cost; central AC cost added unless a heat pump
                CAPITAL = rteqcost[RECTY]
                if EQC != 2 and EQC != 9 and EQC != 10:
                    CAPITAL1 = f32(rtrecost[RECTY] + f32(2760.0))
                else:
                    CAPITAL1 = rtrecost[RECTY]

                # reduce implicit discount rates as real prices increase
                if Y > 2008 and P[F, R, Y] > P[F, R, RECSYEAR]:
                    HRDRATE = f32(rtecbta1[RECTY] / rtecbta2[RECTY])
                    ELIGBLE = f32(HRDRATE - f32(0.07))
                    s["hrdrate"], s["eligble"] = HRDRATE, ELIGBLE
                    if ELIGBLE > 0.0:
                        HRDADJ = f32(ELIGBLE * np.power(f32(P[F, R, Y] / P[F, R, RECSYEAR]), ALPHA1))
                        s["hrdadj"] = HRDADJ
                        BETA1DR[RECTY] = f32(f32(HRDADJ + f32(0.07)) * rtecbta2[RECTY])
                    else:
                        BETA1DR[RECTY] = rtecbta1[RECTY]
                else:
                    BETA1DR[RECTY] = rtecbta1[RECTY]

                ECTEMP = f32(rtecbias[RECTY] + f32(BETA1DR[RECTY] * CAPITAL))

                price = P[F, R, Y]
                if Y == RECSYEAR + 1:
                    OPCOST1 = f32(f32(f32(price * s["eqcuec"][R, RECCL, B]) * RTEFFAC1) * HDDFACT[R])
                    OPCOST2 = f32(f32(f32(f32(price * f32(s["newheatuec"][RECCL, B, R] / s["baseload"][RECCL]))
                                          * RTEFFAC2) * HDDFACT[R]) / BLDRWT)
                    OPCOST3 = f32(f32(f32(f32(price * s["newheatuec"][RECCL, B, R]) / s["baseload"][RECCL])
                                      * RTEFFAC2) * HDDFACT[R])
                else:
                    EH = s["ehshell"]
                    OPCOST1 = f32(f32(f32(f32(price * s["eqcuec"][R, RECCL, B]) * RTEFFAC1) * HDDFACT[R])
                                  * f32(EH[Y - 1, F, R, B] / EH[RECSYEAR, F, R, B]))
                    OPCOST2 = f32(f32(f32(f32(price * f32(s["newheatuec"][RECCL, B, R] / s["baseload"][RECCL]))
                                          * RTEFFAC2) * HDDFACT[R]) / BLDRWT)
                    OPCOST3 = f32(f32(f32(f32(price * s["eqcahvuec"][Y - 1, RECCL, B, R])
                                          * f32(s["ahshell"][Y - 1, F, R, B] / EH[RECSYEAR, F, R, B]))
                                      * RTEFFAC2) * HDDFACT[R])

                # LIFE-CYCLE COSTS
                LFCY[EQT, B, R, 1] = f32(CAPITAL + f32(OPCOST1 * DECAY))
                LFCY[EQT, B, R, 2] = f32(CAPITAL1 + f32(OPCOST2 * DECAY))
                LFCY[EQT, B, R, 3] = f32(CAPITAL1 + f32(OPCOST3 * DECAY))

                EQWTR[EQT] = f32(np.exp(f32(f32(ECTEMP + f32(rtecbta2[RECTY] * OPCOST1))
                                            + f32(rtecbta3[RECTY] * LFCY[EQT, B, R, 1]))))
                TOTEWTR[EQC] = f32(TOTEWTR.get(EQC, f32(0.0)) + EQWTR[EQT])
                EQWTN[EQT] = f32(np.exp(f32(f32(ECTEMP + f32(rtecbta2[RECTY] * OPCOST3))
                                            + f32(rtecbta3[RECTY] * LFCY[EQT, B, R, 3]))))
                TOTEWTN[EQC] = f32(TOTEWTN.get(EQC, f32(0.0)) + EQWTN[EQT])

            # NEW AND REPLACEMENT MARKET SHARES
            TYPE = rttypect[EU]
            for RECTY in cand:
                TYPE += 1
                EQC, EQT = rttyeqcl[RECTY], rteqtype[RECTY]
                if TOTEWTN[EQC] > 0.0:
                    EQFSHRN = f32(EQWTN[EQT] / TOTEWTN[EQC])
                else:
                    EQFSHRN = f32(0.0)
                s["neqtshr"][Y, TYPE, B, R] = EQFSHRN
                if TOTEWTR[EQC] > 0.0:
                    EQFSHRR = f32(EQWTR[EQT] / TOTEWTR[EQC])
                else:
                    EQFSHRR = f32(0.0)
                s["reqtshr"][Y, TYPE, B, R] = EQFSHRR

            # WEIGHTED EFFICIENCY FOR NEW AND REPLACEMENT SPACE HEATING EQUIPMENT
            for RECCL in range(rtcleupt[EU] + 1, rtcleupt[EU + 1] + 1):
                EQC = rtcleqcl[RECCL]
                DENOM, DENOM2 = f32(0.0), f32(0.0)
                recar, eqtar = [], []
                TYPE = rttypect[EU]
                for RECTY in cand:
                    TYPE += 1  # counts valid types
                    if rttyeqcl[RECTY] == EQC:
                        recar.append(RECTY)
                        eqtar.append(TYPE)
                        DENOM = f32(DENOM + s["neqtshr"][Y, TYPE, B, R])
                        DENOM2 = f32(DENOM2 + s["reqtshr"][Y, TYPE, B, R])

                if DENOM <= 0.0:
                    s["wteqceffn"][Y, RECCL, B, R] = f32(f32(1.0) / s["rtbaseff"][RECSYEAR, RECCL])
                else:
                    SUM = f32(0.0)
                    for RECTY, TYPE in zip(recar, eqtar):
                        SUM = f32(SUM + f32(s["neqtshr"][Y, TYPE, B, R] / rteqeff[RECTY]))
                    s["wteqceffn"][Y, RECCL, B, R] = f32(SUM / DENOM)
                if s["wteqceffn"][Y, RECCL, B, R] == 0.0:
                    s["wteqceffn"][Y, RECCL, B, R] = f32(f32(1.0) / s["rtbaseff"][RECSYEAR, RECCL])

                if DENOM2 <= 0.0:
                    s["wteqceffr"][Y, RECCL, B, R] = f32(f32(1.0) / s["rtbaseff"][RECSYEAR, RECCL])
                else:
                    SUM = f32(0.0)
                    for RECTY, TYPE in zip(recar, eqtar):
                        SUM = f32(SUM + f32(s["reqtshr"][Y, TYPE, B, R] / rteqeff[RECTY]))
                    s["wteqceffr"][Y, RECCL, B, R] = f32(SUM / DENOM2)
                if s["wteqceffr"][Y, RECCL, B, R] == 0.0:
                    s["wteqceffr"][Y, RECCL, B, R] = f32(f32(1.0) / s["rtbaseff"][RECSYEAR, RECCL])

            # LOGIT VALUES FOR EACH SPACE HEATING SYSTEM AND SUM OVER TYPE
            SYSTOT = f32(0.0)
            LAGFACTOR = f32(0.9)
            for RECCL in range(rtcleupt[EU] + 1, rtcleupt[EU + 1] + 1):
                EQT = rtcltypt[RECCL]
                HEATSYS[Y, EQT, B, R] = f32(
                    f32(LAGFACTOR * HEATSYS[Y - 1, EQT, B, R])
                    + f32(f32(f32(1.0) - LAGFACTOR)
                          * np.exp(f32(s["rtfcbias"][RECCL, B, R] + f32(rtfcbeta[RECCL] * LFCY[EQT, B, R, 2])))))
                SYSTOT = f32(SYSTOT + HEATSYS[Y, EQT, B, R])

            # NORMALIZED SHARES FOR EACH FUEL SYSTEM CHOICE
            for RECCL in range(rtcleupt[EU] + 1, rtcleupt[EU + 1] + 1):
                EQC, EQT = rtcleqcl[RECCL], rtcltypt[RECCL]
                if SYSTOT != 0.0:
                    s["htysshr"][Y, EQC, B, R] = f32(HEATSYS[Y, EQT, B, R] / SYSTOT)
                else:
                    s["htysshr"][Y, EQC, B, R] = 0.0
                # historical years keep the shares read from RSHTSHR.txt
                if Y > int(s["htshryr"]):
                    s["hsysshr"][Y, EQC, B, R] = s["htysshr"][Y, EQC, B, R]
