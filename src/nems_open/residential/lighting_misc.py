"""Lighting, miscellaneous electric loads, secondary heating and other-fuel appliances
(resd.f): LTCNS, APCNS, SHTCNS and APPCNS.

All four write the year's consumption into the shared arrays. Writes to debug units,
AppBetaData.txt (ApplianceBetaSwitch blocks, LightCalcA/B/C) and the LightDiag
printouts are skipped.

Values the Fortran takes from places the oracle dumps do not hold:
  LEAPYR   set in RESD from the calendar year (366/365 in leap years through LastSTEOYr)
  EPA111D  RTOVALUE default 0 (no 111(d) subsidy), so bulbsub drops out of LTLCap and LTLSUB
  NumMELs  23, the count at the top of rsmels.txt
  NLRec    the lighting database is read in full; blank records never match an AppID
The lighting carry-over arrays (LTSTOCKEX, LTREPFUT, ...) are private SAVEd locals of
LTCNS in EIA's code. They live in the state dict under their lowercase names and are
created as zeros when missing, like static storage.
"""

import numpy as np

from nems_open.fortran_array import FArray
from nems_open.residential.common import BASEYR, LASTSTEOYR, MNUMBLDG, NUM_DIV, RECSYEAR, f32, powi
from nems_open.residential.helpers import rselast

NLREC = 100  # records in the lighting database arrays
MAXBINS = 6  # usage bins for lighting
NUMMELS = 23
ND = NUM_DIV
NB = MNUMBLDG


def _leapyr(y: int):
    if y % 4 == 0 and y <= LASTSTEOYR:
        return f32(366.0) / f32(365.0)
    return f32(365.0) / f32(365.0)


def _same(a, b) -> bool:
    return bytes(a).rstrip(b" \0") == bytes(b).rstrip(b" \0")


def _local(s: dict, name: str, bounds):
    if name not in s:
        s[name] = FArray.zeros(bounds)
    return s[name]


def _nint(x) -> int:
    # Fortran NINT: halves round away from zero
    v = float(x)
    return int(np.floor(v + 0.5)) if v >= 0 else -int(np.floor(-v + 0.5))


# ---------------------------------------------------------------------------
# LTCNS
# ---------------------------------------------------------------------------

def _lt_bounds(end_y: int):
    return [(1, 4), (RECSYEAR, end_y), (1, 4), (1, NB), (1, ND), (1, MAXBINS)]


def _lt_filter_records(s, app, year, with_costs):
    """Scan the lighting database for this application and year; fills the per-bulb-type
    tables (watts, bulbbinlife, betas and, for the projection year, costs).
    Returns the number of bulb types found."""
    appid = s["appid"][app]
    nb = int(s["numappbins"][app])
    e = 1
    for i in range(1, NLREC + 1):
        if not _same(s["lightingapp"][i], appid):
            continue
        if year >= s["firstyear"][i] and year <= s["lastyear"][i]:
            s["watts"][e] = s["bulbwatts"][i]
            for b in range(1, nb + 1):
                s["bulbbinlife"][e, b] = s["lifehours"][i] / (f32(365.0) * s["appbinhours"][app, b])
            lb1 = _local(s, "lightbeta1", [(1, 4), (RECSYEAR, 2050), (1, 4)])
            lb2 = _local(s, "lightbeta2", [(1, 4), (RECSYEAR, 2050), (1, 4)])
            cy = int(s["curcalyr"])
            lb1[app, cy, e] = s["ltlbeta1"][i]
            lb2[app, cy, e] = s["ltlbeta2"][i]
            if with_costs:
                epa111d = f32(0.0)
                for d in range(1, ND + 1):
                    s["ltlcap"][e, d, 1] = (s["bulbcost"][i] - s["bulbeesub"][i, d]) - s["bulbsub"][i, d] * epa111d
                    s["ltlsub"][e, d] = s["bulbeesub"][i, d] + s["bulbsub"][i, d] * epa111d
                    s["ltlcapinvest"][e] = s["bulbcost"][i]
                s["cribulb"][e] = s["bulbcri"][i]
                s["appbulbname"][app, e] = s["bulbtype"][i]
            e += 1
    return e - 1


def ltcns_recs_init(s: dict) -> None:
    """The first post-RECS year, first iteration part of LTCNS: RECS-year stocks and
    consumption, bin shares of energy, and the surviving RECS stock by year (LTSTOCKEX)."""
    cy = int(s["curcalyr"])
    napps = int(s["numapps"])
    end_y = int(s["lastyr"]) + BASEYR - 1
    bl = _lt_bounds(end_y)
    LTSTOCKEX = _local(s, "ltstockex", bl)
    LTSTOCKEXCONS = _local(s, "ltstockexcons", bl)
    LTNEEDED = _local(s, "ltneeded", bl)
    LTREPFUT = _local(s, "ltrepfut", bl)
    LTREP = _local(s, "ltrep", bl)
    LTTOTSTOCK = _local(s, "lttotstock", [(1, 4), (RECSYEAR, end_y), (1, NB), (1, ND), (1, MAXBINS)])
    EH, HDR = s["eh"], s["hdr"]
    C365, C3412, C1E6 = f32(365.0), f32(3.412), f32(1000000.0)
    iy = RECSYEAR - BASEYR + 1
    for d in range(1, ND + 1):
        s["ltcon"][iy, d] = 0.0
        for b in range(1, NB + 1):
            s["ltconwt"][iy, d, b] = 0.0
            s["ltconin"][iy, d, b] = 0.0

    for app in range(1, napps + 1):
        for y in range(RECSYEAR, end_y + 1):
            for d in range(1, ND + 1):
                for b in range(1, NB + 1):
                    s["ltnuec"][app, y, d, b] = 0.0

        e = _lt_filter_records(s, app, cy - 1, False)
        nbins = int(s["numappbins"][app])
        ntypes = int(s["numtypes"][app])
        # EIA only writes a message if e does not match numtypes

        for b in range(1, nbins + 1):
            s["ltbinshare"][app, b] = 0.0

        for d in range(1, ND + 1):
            for b in range(1, NB + 1):
                s["lteqp"][app, RECSYEAR, b, d] = s["bulbsperhh"][app, b] * EH[RECSYEAR, b, d]
                s["ltuec"][app, d, b] = 0.0
                for bin_ in range(1, nbins + 1):
                    for e in range(1, ntypes + 1):
                        t = s["appbinhours"][app, bin_] * C365 * s["binshares"][app, bin_] \
                            * s["bulbbinshares"][app, e, bin_] * s["basewattsbulbs"][app, e] * C3412 / C1E6
                        s["ltuec"][app, d, b] = s["ltuec"][app, d, b] + t
                        s["ltbinshare"][app, bin_] = s["ltbinshare"][app, bin_] + t

        temp = f32(0.0)
        for bin_ in range(1, nbins + 1):
            temp = temp + s["ltbinshare"][app, bin_]
        for bin_ in range(1, nbins + 1):
            s["ltbinshare"][app, bin_] = s["ltbinshare"][app, bin_] / temp

        for d in range(1, ND + 1):
            for b in range(1, NB + 1):
                s["lteqcn"][RECSYEAR - BASEYR + 1, app, b, d] = s["lteqp"][app, RECSYEAR, b, d] * s["ltuec"][app, d, b]
                s["ltcon"][iy, d] = s["ltcon"][iy, d] + (s["lteqp"][app, RECSYEAR, b, d] * s["ltuec"][app, d, b])

        for d in range(1, ND + 1):
            for b in range(1, NB + 1):
                for bin_ in range(1, nbins + 1):
                    LTTOTSTOCK[app, RECSYEAR, b, d, bin_] = 0.0
                    for e in range(1, ntypes + 1):
                        v = s["lteqp"][app, RECSYEAR, b, d] * s["binshares"][app, bin_] * s["bulbbinshares"][app, e, bin_]
                        s["ltstock"][app, RECSYEAR, e, b, d, bin_] = v
                        LTSTOCKEX[app, RECSYEAR, e, b, d, bin_] = v
                        LTSTOCKEXCONS[app, RECSYEAR, e, b, d, bin_] = LTSTOCKEX[app, RECSYEAR, e, b, d, bin_] \
                            * s["appbinhours"][app, bin_] * C365 * s["basewattsbulbs"][app, e] * C3412 / C1E6
                        LTNEEDED[app, RECSYEAR, e, b, d, bin_] = 0.0
                        LTREPFUT[app, RECSYEAR, e, b, d, bin_] = 0.0
                        LTREP[app, RECSYEAR, e, b, d, bin_] = 0.0
                        LTTOTSTOCK[app, RECSYEAR, b, d, bin_] = LTTOTSTOCK[app, RECSYEAR, b, d, bin_] \
                            + s["ltstock"][app, RECSYEAR, e, b, d, bin_]

        # The RECS-year stock still standing in later years; reaches zero once the
        # bulbs have worn out (bulbbinlife).
        for d in range(1, ND + 1):
            for b in range(1, NB + 1):
                for bin_ in range(1, nbins + 1):
                    for y1 in range(RECSYEAR + 1, end_y + 1):
                        for e in range(1, ntypes + 1):
                            v = LTSTOCKEX[app, y1 - 1, e, b, d, bin_] \
                                - LTSTOCKEX[app, RECSYEAR, e, b, d, bin_] * powi(HDR[b], y1 - RECSYEAR) \
                                / s["bulbbinlife"][e, bin_]
                            LTSTOCKEX[app, y1, e, b, d, bin_] = max(f32(0.0), v)
                            LTSTOCKEXCONS[app, y1, e, b, d, bin_] = LTSTOCKEX[app, y1, e, b, d, bin_] \
                                * s["appbinhours"][app, bin_] * C365 * s["basewattsbulbs"][app, e] * C3412 / C1E6


def ltcns(s: dict) -> None:
    """LTCNS: lighting. Chooses bulb types by logit on cost, tracks purchases and the
    surviving stock by bin, and turns the weighted bulb wattage into consumption."""
    with np.errstate(all="ignore"):
        _ltcns(s)


def _ltcns(s: dict) -> None:
    cy = int(s["curcalyr"])
    iyr = int(s["curiyr"])
    itr = int(s["curitr"])
    napps = int(s["numapps"])
    end_y = int(s["lastyr"]) + BASEYR - 1
    bl = _lt_bounds(end_y)
    b5 = [(1, 4), (RECSYEAR, end_y), (1, NB), (1, ND), (1, MAXBINS)]

    iy0 = cy - BASEYR + 1
    for d in range(1, ND + 1):
        s["ltcon"][iy0, d] = 0.0
        for b in range(1, NB + 1):
            s["ltconwt"][iy0, d, b] = 0.0
            s["ltconin"][iy0, d, b] = 0.0

    if cy == RECSYEAR + 1 and itr == 1:
        ltcns_recs_init(s)

    LTSTOCKEX = _local(s, "ltstockex", bl)
    LTSTOCKEXCONS = _local(s, "ltstockexcons", bl)
    LTNEEDED = _local(s, "ltneeded", bl)
    LTNEEDEDFUT = _local(s, "ltneededfut", bl)
    LTREPFUT = _local(s, "ltrepfut", bl)
    LTREPSTK = _local(s, "ltrepstk", bl)
    LTREPCONS = _local(s, "ltrepcons", bl)
    LTNEEDEDFUTLY = _local(s, "ltneededfutly", bl)
    LTREPFUTLY = _local(s, "ltrepfutly", bl)
    LTREPCONSLY = _local(s, "ltrepconsly", bl)
    LTREPSTKLY = _local(s, "ltrepstkly", bl)
    LTREP = _local(s, "ltrep", bl)
    LTREPTOT = _local(s, "ltreptot", b5)
    LTTOTSTOCK = _local(s, "lttotstock", b5)
    WTLEFF = _local(s, "wtleff", b5)
    LTMSHR = _local(s, "ltmshr", [(RECSYEAR, end_y), (1, 4), (1, NB), (1, ND), (1, MAXBINS)])
    TOTEWTN = _local(s, "totewtn", [(1, NB), (1, ND), (1, MAXBINS)])
    EQWTN = _local(s, "eqwtn", [(1, 4), (1, NB), (1, ND), (1, MAXBINS)])
    LB1 = _local(s, "lightbeta1", [(1, 4), (RECSYEAR, 2050), (1, 4)])
    LB2 = _local(s, "lightbeta2", [(1, 4), (RECSYEAR, 2050), (1, 4)])
    OPCOST = np.zeros(5, dtype=np.float32)

    EH, NH, HDR = s["eh"], s["nh"], s["hdr"]
    HSEADD, SQRFOOT, EXSQ, SQNEW = s["hseadd"], s["sqrfoot"], s["exsqrfoot"], s["sqnew"]
    PRICES = s["prices"]
    watts, bulbbinlife = s["watts"], s["bulbbinlife"]
    C365, C3412, C1E6 = f32(365.0), f32(3.412), f32(1000000.0)

    # Electricity price into the technology menu's dollar year, $/MMBtu
    EUPR = 8
    gdp = s["mc_jpgdp"]
    for d in range(1, ND + 1):
        PRICES[4, d, cy] = s["pelrsout"][d, iyr, EUPR] * (gdp[int(s["rtekdollaryr"]) - BASEYR + 1] / gdp[-2])

    ALPHA = f32(-0.15)
    ef1, ef2, ef3 = f32(0.50), f32(0.35), f32(0.15)
    ALPHA1 = f32(-0.01)
    FACTOR = f32(3.412) / f32(1000000.0)
    LEAPYR = _leapyr(cy)
    f007 = f32(0.07)

    for app in range(1, napps + 1):
        nbins = int(s["numappbins"][app])
        ntypes = int(s["numtypes"][app])
        _lt_filter_records(s, app, cy, True)

        # CRI adjustment, and extra capital cost where a bulb wears out in under a year
        for d in range(1, ND + 1):
            for e in range(1, ntypes + 1):
                temp = s["ltlcap"][e, d, 1]
                for bin_ in range(1, nbins + 1):
                    cri = s["cribulb"][e] / f32(100.0)
                    s["ltlcap"][e, d, bin_] = temp / powi(cri, 2)
                    if bulbbinlife[e, bin_] < 1.0:
                        s["ltlcap"][e, d, bin_] = (temp / bulbbinlife[e, bin_]) / powi(cri, 2)

        # Operating cost and logit shares
        for d in range(1, ND + 1):
            for b in range(1, NB + 1):
                for bin_ in range(1, nbins + 1):
                    TOTEWTN[b, d, bin_] = 0.0
                    for e in range(1, ntypes + 1):
                        if cy > 2008 and PRICES[4, d, cy] > PRICES[4, d, RECSYEAR]:
                            LHRATE = LB1[app, cy, e] / LB2[app, cy, e]
                            ELIGL = LHRATE - f007
                            if ELIGL > 0.0:
                                LHRDADJ = ELIGL * np.power(PRICES[4, d, cy] / PRICES[4, d, RECSYEAR], ALPHA1)
                                LTLBeta1DR = (LHRDADJ + f007) * LB2[app, cy, e]
                            else:
                                LTLBeta1DR = LB1[app, cy, e]
                        else:
                            LTLBeta1DR = LB1[app, cy, e]

                        OPCOST[e] = PRICES[4, d, cy] * watts[e] * FACTOR * s["appbinhours"][app, bin_] * C365
                        EQWTN[e, b, d, bin_] = np.exp(LTLBeta1DR * s["ltlcap"][e, d, bin_] + LB2[app, cy, e] * OPCOST[e])
                        TOTEWTN[b, d, bin_] = TOTEWTN[b, d, bin_] + EQWTN[e, b, d, bin_]

        # EIA loops over 6 bins here whatever the application has, reading stale
        # TOTEWTN/EQWTN for the extra ones; those shares are never used.
        for d in range(1, ND + 1):
            for b in range(1, NB + 1):
                for e in range(1, ntypes + 1):
                    for bin_ in range(1, MAXBINS + 1):
                        if TOTEWTN[b, d, bin_] != 0.0:
                            LTMSHR[cy, e, b, d, bin_] = EQWTN[e, b, d, bin_] / TOTEWTN[b, d, bin_]
                        else:
                            LTMSHR[cy, e, b, d, bin_] = 0.0

        # Future streams restart from the first iteration's values on later iterations
        # (whole-block copies; the Fortran copies them element by element)
        blk = (app, slice(cy, end_y), slice(1, ntypes), slice(1, NB), slice(1, ND), slice(1, nbins))
        uec = (app, slice(cy, end_y), slice(1, ND), slice(1, NB))
        pairs = [(LTNEEDEDFUTLY, LTNEEDEDFUT), (LTREPFUTLY, LTREPFUT), (LTREPCONSLY, LTREPCONS),
                 (LTREPSTKLY, LTREPSTK)]
        if itr == 1:
            for saved, live in pairs:
                saved[blk] = live[blk]
            s["ltnuecly"][uec] = s["ltnuec"][uec]
        else:
            for saved, live in pairs:
                live[blk] = saved[blk]
            s["ltnuec"][uec] = s["ltnuecly"][uec]

        # Bulbs for new construction and floorspace added to surviving RECS homes
        for bin_ in range(1, nbins + 1):
            for d in range(1, ND + 1):
                for b in range(1, NB + 1):
                    for e in range(1, ntypes + 1):
                        LTNEEDED[app, cy, e, b, d, bin_] = (
                            HSEADD[cy, b, d] * (SQRFOOT[cy, b, d] / SQRFOOT[RECSYEAR, b, d])
                            * s["bulbsperhh"][app, b] * LTMSHR[cy, e, b, d, bin_] * s["binshares"][app, bin_]
                            + EH[cy, b, d] * ((EXSQ[cy, b, d] / EXSQ[cy - 1, b, d]) - f32(1.0))
                            * s["bulbsperhh"][app, b] * LTMSHR[cy, e, b, d, bin_] * s["binshares"][app, bin_])

        # Bulbs needed this year for all reasons
        for d in range(1, ND + 1):
            for b in range(1, NB + 1):
                for bin_ in range(1, nbins + 1):
                    LTREPTOT[app, cy, b, d, bin_] = 0.0
                    for e in range(1, ntypes + 1):
                        LTREPTOT[app, cy, b, d, bin_] = LTREPTOT[app, cy, b, d, bin_] \
                            + LTSTOCKEX[app, cy - 1, e, b, d, bin_] * HDR[b] - LTSTOCKEX[app, cy, e, b, d, bin_] \
                            + LTREPFUT[app, cy, e, b, d, bin_] + LTNEEDED[app, cy, e, b, d, bin_]

        # Split purchases by bulb type, accumulate stock and consumption
        for d in range(1, ND + 1):
            for b in range(1, NB + 1):
                for bin_ in range(1, nbins + 1):
                    for e in range(1, ntypes + 1):
                        LTREP[app, cy, e, b, d, bin_] = LTREPTOT[app, cy, b, d, bin_] * LTMSHR[cy, e, b, d, bin_]
                        LTREPSTK[app, cy, e, b, d, bin_] = LTREPSTK[app, cy, e, b, d, bin_] + LTREP[app, cy, e, b, d, bin_]
                        LTREPCONS[app, cy, e, b, d, bin_] = LTREPCONS[app, cy, e, b, d, bin_] \
                            + LTREP[app, cy, e, b, d, bin_] * C365 * s["appbinhours"][app, bin_] * watts[e] * C3412 / C1E6

        # Spread this year's purchases into future replacement needs and remaining stock
        for d in range(1, ND + 1):
            for b in range(1, NB + 1):
                for bin_ in range(1, nbins + 1):
                    for e in range(1, ntypes + 1):
                        cumrep = f32(0.0)
                        rep = LTREP[app, cy, e, b, d, bin_] / max(f32(1.0), bulbbinlife[e, bin_])
                        ilife = _nint(bulbbinlife[e, bin_] + f32(0.5)) + 1
                        ilast = min(end_y, cy + ilife)
                        for y1 in range(cy + 1, ilast + 1):
                            maxrep = LTREP[app, cy, e, b, d, bin_]
                            maxrep = maxrep * HDR[b]
                            annrep = max(f32(0.0), min(maxrep - cumrep, rep))
                            if annrep > 0.0:
                                LTREPFUT[app, y1, e, b, d, bin_] = LTREPFUT[app, y1, e, b, d, bin_] \
                                    + annrep * powi(HDR[b], y1 - cy)
                                cumrep = cumrep + annrep
                                LTREPSTK[app, y1, e, b, d, bin_] = LTREPSTK[app, y1, e, b, d, bin_] + maxrep - cumrep
                                LTREPCONS[app, y1, e, b, d, bin_] = LTREPCONS[app, y1, e, b, d, bin_] \
                                    + (maxrep - cumrep) * C365 * s["appbinhours"][app, bin_] * watts[e] * C3412 / C1E6

        # Total stock is surviving RECS stock plus replacements still in service
        for d in range(1, ND + 1):
            for b in range(1, NB + 1):
                for bin_ in range(1, nbins + 1):
                    for e in range(1, ntypes + 1):
                        s["ltstock"][app, cy, e, b, d, bin_] = LTSTOCKEX[app, cy, e, b, d, bin_] \
                            + LTREPSTK[app, cy, e, b, d, bin_]

        for d in range(1, ND + 1):
            for b in range(1, NB + 1):
                s["lteqp"][app, cy, b, d] = 0.0
                for bin_ in range(1, nbins + 1):
                    LTTOTSTOCK[app, cy, b, d, bin_] = 0.0
                    for e in range(1, ntypes + 1):
                        LTTOTSTOCK[app, cy, b, d, bin_] = LTTOTSTOCK[app, cy, b, d, bin_] \
                            + s["ltstock"][app, cy, e, b, d, bin_]
                        s["lteqp"][app, cy, b, d] = s["lteqp"][app, cy, b, d] + s["ltstock"][app, cy, e, b, d, bin_]

        # Investment and subsidy; bulbs lasting under a year are bought several times a year
        for d in range(1, ND + 1):
            for b in range(1, NB + 1):
                for e in range(1, ntypes + 1):
                    s["ltinvest"][app, cy, e, b, d, 1] = 0.0
                    s["ltinvest"][app, cy, e, b, d, 2] = 0.0
                    s["ltsubsidy"][app, cy, e, b, d, 1] = 0.0
                    s["ltsubsidy"][app, cy, e, b, d, 2] = 0.0
                    s["ltneededbyapp"][app, cy, e, b, d] = 0.0
                    s["ltrepbyapp"][app, cy, e, b, d] = 0.0
                    for bin_ in range(1, nbins + 1):
                        s["ltneededbyapp"][app, cy, e, b, d] = s["ltneededbyapp"][app, cy, e, b, d] \
                            + LTNEEDED[app, cy, e, b, d, bin_]
                        s["ltrepbyapp"][app, cy, e, b, d] = s["ltrepbyapp"][app, cy, e, b, d] \
                            + LTREP[app, cy, e, b, d, bin_]
                        temp = s["ltlcapinvest"][e] - s["ltlsub"][e, d]
                        if bulbbinlife[e, bin_] < 1.0:
                            temp = temp / bulbbinlife[e, bin_]
                        s["ltinvest"][app, cy, e, b, d, 1] = s["ltinvest"][app, cy, e, b, d, 1] \
                            + LTNEEDED[app, cy, e, b, d, bin_] * temp
                        s["ltinvest"][app, cy, e, b, d, 2] = s["ltinvest"][app, cy, e, b, d, 2] \
                            + LTREP[app, cy, e, b, d, bin_] * temp
                        temp = s["ltlsub"][e, d]
                        if bulbbinlife[e, bin_] < 1.0:
                            temp = temp / bulbbinlife[e, bin_]
                        s["ltsubsidy"][app, cy, e, b, d, 1] = s["ltsubsidy"][app, cy, e, b, d, 1] \
                            + LTNEEDED[app, cy, e, b, d, bin_] * temp
                        s["ltsubsidy"][app, cy, e, b, d, 2] = s["ltsubsidy"][app, cy, e, b, d, 2] \
                            + LTREP[app, cy, e, b, d, bin_] * temp

        # Weighted efficiency: total watts of this year's and surviving stock, then per bulb
        for d in range(1, ND + 1):
            for b in range(1, NB + 1):
                for bin_ in range(1, nbins + 1):
                    WTLEFF[app, cy, b, d, bin_] = 0.0
                    for e in range(1, ntypes + 1):
                        den = C365 * s["appbinhours"][app, bin_] * C3412 / C1E6
                        WTLEFF[app, cy, b, d, bin_] = WTLEFF[app, cy, b, d, bin_] \
                            + LTREPCONS[app, cy, e, b, d, bin_] / den \
                            + LTSTOCKEXCONS[app, cy, e, b, d, bin_] / den

        for d in range(1, ND + 1):
            for b in range(1, NB + 1):
                for bin_ in range(1, nbins + 1):
                    WTLEFF[app, cy, b, d, bin_] = WTLEFF[app, cy, b, d, bin_] / LTTOTSTOCK[app, cy, b, d, bin_]

        for d in range(1, ND + 1):
            for b in range(1, NB + 1):
                s["wtleffbyapp"][app, cy, b, d] = 0.0
                for bin_ in range(1, nbins + 1):
                    s["wtleffbyapp"][app, cy, b, d] = s["wtleffbyapp"][app, cy, b, d] \
                        + ((WTLEFF[app, cy, b, d, bin_] * LTTOTSTOCK[app, cy, b, d, bin_]) / s["lteqp"][app, cy, b, d])

        # UEC adjusted for efficiency and rebound. ALPHA is still -0.15 for the first
        # application and -0.30 for the rest (EIA resets it at the end of the first pass).
        for d in range(1, ND + 1):
            for b in range(1, NB + 1):
                for bin_ in range(1, nbins + 1):
                    s["ltnuec"][app, cy, d, b] = s["ltnuec"][app, cy, d, b] \
                        + s["ltbinshare"][app, bin_] * s["ltuec"][app, d, b] \
                        * np.power(WTLEFF[app, cy, b, d, bin_] / s["basewattbins"][app, bin_], f32(1.0) + ALPHA)

        # UEC and consumption
        y = iyr
        ALPHA = f32(-0.30)
        for d in range(1, ND + 1):
            for b in range(1, NB + 1):
                rs = rselast(s, 4, d, ALPHA, ef1, ef2, ef3, EUPR)
                s["lteqcn"][y, app, b, d] = LEAPYR * s["lteqp"][app, cy, b, d] * s["ltnuec"][app, cy, d, b] * rs
                s["ltcon"][y, d] = s["ltcon"][y, d] + s["lteqcn"][y, app, b, d]
                s["ltconwt"][y, d, b] = s["ltconwt"][y, d, b] + s["lteqcn"][y, app, b, d]
                s["ltconin"][y, d, b] = s["ltconin"][y, d, b] + (s["ltconwt"][y, d, b] / rs) / (
                    EH[cy, b, d] * EXSQ[cy, b, d] + HSEADD[cy, b, d] * SQRFOOT[cy, b, d]
                    + SQNEW[cy - 1, b, d] * NH[cy - 1, b, d])


# ---------------------------------------------------------------------------
# APCNS
# ---------------------------------------------------------------------------

# Miscellaneous electric loads in EIA's order; the position is the INCOME index.
MELS = ["tvs", "stb", "hts", "ott", "vgc", "dpc", "lpc", "mon", "net", "bat", "cfn", "cof",
        "deh", "mco", "plp", "plh", "sec", "spa", "wcl", "spk", "phn", "tab", "kit"]


def apcns(s: dict) -> None:
    """APCNS: miscellaneous electric loads and other electric appliances (MELs):
    income effect, unit consumption, equipment stocks, consumption and the TV, PC
    and other aggregates with their weighted intensities."""
    with np.errstate(all="ignore"):
        _apcns(s)


def _apcns(s: dict) -> None:
    cy, iyr = int(s["curcalyr"]), int(s["curiyr"])
    Y = cy - BASEYR + 1
    ef1, ef2, ef3 = f32(0.5), f32(0.35), f32(0.15)
    EUPR = 9
    EH, NH = s["eh"], s["nh"]
    INCOME, PRICES = s["income"], s["prices"]
    ypdr, np16 = s["mc_ypdr"], s["mc_np16a"]
    iy0 = RECSYEAR - BASEYR + 1

    gdp = s["mc_jpgdp"]
    for d in range(1, ND + 1):
        PRICES[4, d, cy] = s["pelrsout"][d, iyr, EUPR] * (gdp[int(s["rtekdollaryr"]) - BASEYR + 1] / gdp[-2])

    # Higher disposable income means more annual use of a MEL
    for i in range(1, NUMMELS + 1):
        for d in range(1, ND + 1):
            if s["melsincomeeffect"][i] < 1:
                INCOME[d, cy, i] = 1.0
            else:
                INCOME[d, cy, i] = np.power(ypdr[d, iyr] / ypdr[d, iy0], f32(0.05))

    # Penetration of electric other follows disposable income per person over 16
    elotpen = {}
    for d in range(1, ND + 1):
        elotpen[d] = f32(1.0) * ((ypdr[d, Y] / np16[d, Y]) / (ypdr[d, iy0] / np16[d, iy0]))

    nuec, niuec = {}, {}
    for d in range(1, ND + 1):
        for b in range(1, NB + 1):
            for k, m in enumerate(MELS, start=1):
                uec = s[m + "uec"][d, b]
                eff = s[m + "eff"][cy]
                if m == "cfn":
                    # EIA applies the cooling-degree-day ratio squared to ceiling fans
                    cdd = s["cddadj"][cy, d] / s["cddadj"][RECSYEAR, d]
                    nuec[m, d, b] = uec * eff * (cdd * cdd) * INCOME[d, cy, k]
                else:
                    nuec[m, d, b] = uec * eff * INCOME[d, cy, k]
                niuec[m, d, b] = uec * eff
            nuec["ea", d, b] = s["eauec"][d, b] * elotpen[d]
            niuec["ea", d, b] = s["eauec"][d, b] * elotpen[d]

    # Equipment stocks
    for d in range(1, ND + 1):
        for b in range(1, NB + 1):
            for m in MELS:
                eqp = s[m + "eqp"]
                eqp[cy, b, d] = (eqp[RECSYEAR, b, d] / EH[RECSYEAR, b, d]) * s[m + "pen"][cy] * (EH[cy, b, d] + NH[cy, b, d])
            s["eaeqp"][cy, b, d] = s["eaeqp"][RECSYEAR, b, d] + NH[cy, b, d]

    # Consumption
    ALPHA = f32(-0.30)
    LEAPYR = _leapyr(cy)
    conwt, conin = {}, {}
    for d in range(1, ND + 1):
        rs = rselast(s, 4, d, ALPHA, ef1, ef2, ef3, EUPR)
        for b in range(1, NB + 1):
            for m in MELS + ["ea"]:
                eqp = s[m + "eqp"][cy, b, d]
                conwt[m, d, b] = LEAPYR * (eqp * nuec[m, d, b]) * rs
                conin[m, d, b] = f32(0.0)
                if eqp > 0.0:
                    conin[m, d, b] = (eqp * niuec[m, d, b]) / eqp
                s[m + "eqcn"][Y, 1, b, d] = LEAPYR * (eqp * nuec[m, d, b]) * rs

    TV = ["tvs", "stb", "hts", "ott", "vgc"]
    PC = ["dpc", "lpc", "mon", "net"]
    AP = ["bat", "cfn", "cof", "deh", "mco", "plp", "sec", "spa", "wcl", "plh", "ea", "spk", "phn", "tab", "kit"]
    # EIA's weighted-intensity sum lists the same loads in another order
    APIN = ["bat", "cfn", "cof", "deh", "mco", "plp", "sec", "spa", "wcl", "spk", "phn", "tab", "kit", "ea", "plh"]

    for d in range(1, ND + 1):
        s["tvrcon"][Y, d] = 0.0
        s["pcrcon"][Y, d] = 0.0
        s["apcon"][Y, d] = 0.0
        for b in range(1, NB + 1):
            t = s["tvrcon"][Y, d]
            for m in TV:
                t = t + s[m + "eqcn"][Y, 1, b, d]
            s["tvrcon"][Y, d] = t
            t = conwt[TV[0], d, b]
            for m in TV[1:]:
                t = t + conwt[m, d, b]
            s["tvrconwt"][Y, d, b] = t
            t = s["pcrcon"][Y, d]
            for m in PC:
                t = t + s[m + "eqcn"][Y, 1, b, d]
            s["pcrcon"][Y, d] = t
            t = conwt[PC[0], d, b]
            for m in PC[1:]:
                t = t + conwt[m, d, b]
            s["pcrconwt"][Y, d, b] = t
            t = s["apcon"][Y, d]
            for m in AP:
                t = t + s[m + "eqcn"][Y, 1, b, d]
            s["apcon"][Y, d] = t
            t = conwt[AP[0], d, b]
            for m in AP[1:]:
                t = t + conwt[m, d, b]
            s["apconwt"][Y, d, b] = t

    # Efficiency of the other electric appliances from weighted equipment intensities
    for d in range(1, ND + 1):
        for b in range(1, NB + 1):
            t = conin[TV[0], d, b] * conwt[TV[0], d, b]
            for m in TV[1:]:
                t = t + conin[m, d, b] * conwt[m, d, b]
            s["tvrconin"][Y, d, b] = t / s["tvrconwt"][Y, d, b]
            t = conin[PC[0], d, b] * conwt[PC[0], d, b]
            for m in PC[1:]:
                t = t + conin[m, d, b] * conwt[m, d, b]
            s["pcrconin"][Y, d, b] = t / s["pcrconwt"][Y, d, b]
            t = conin[APIN[0], d, b] * conwt[APIN[0], d, b]
            for m in APIN[1:]:
                t = t + conin[m, d, b] * conwt[m, d, b]
            s["apconin"][Y, d, b] = t / s["apconwt"][Y, d, b]


# ---------------------------------------------------------------------------
# SHTCNS
# ---------------------------------------------------------------------------

def shtcns(s: dict) -> None:
    """SHTCNS: secondary heating consumption by fuel (1 gas, 2 electricity,
    3 distillate, 4 propane, 5 wood)."""
    with np.errstate(all="ignore"):
        _shtcns(s)


def _shtcns(s: dict) -> None:
    cy = int(s["curcalyr"])
    Y = cy - BASEYR + 1
    ef1, ef2, ef3 = f32(0.5), f32(0.35), f32(0.15)
    EUPR = 10
    EH, NH = s["eh"], s["nh"]
    EHS, AHS = s["ehshell"], s["ahshell"]
    SHTSHR, NSHTSHR, SHTUEC = s["shtshr"], s["nshtshr"], s["shtuec"]
    LEAPYR = _leapyr(cy)

    for f in range(1, 6):
        for d in range(1, ND + 1):
            s["shtcon"][Y, f, d] = 0.0
            for b in range(1, NB + 1):
                s["sheqcn"][Y, f, b, d] = 0.0
                s["shtconin"][Y, f, d, b] = 0.0
                s["shtconwt"][Y, f, d, b] = 0.0

    HDDFACT = {}
    for d in range(1, ND + 1):
        HDDFACT[d] = s["hddadj"][cy, d] / s["hddadj"][RECSYEAR, d]

    ALPHA = f32(-0.15)
    for f in range(1, 6):
        # F is the secondary heating fuel; F2 is the price/elasticity fuel
        # (1 distillate, 2 propane, 3 natural gas, 4 electricity, 5 wood).
        ALPHA = f32(-0.30) if f == 4 else f32(-0.15)
        fshell = f
        if f == 1:
            f2 = 3
        if f == 2:
            f2 = 4
        if f == 3:
            f2 = 1
        if f == 4:
            f2 = 2
        if f == 5:
            # wood is priced to distillate, has no shell of its own, and responds positively
            f2 = 1
            fshell = 3
            ALPHA = f32(0.50)

        for d in range(1, ND + 1):
            rs = rselast(s, f2, d, ALPHA, ef1, ef2, ef3, EUPR)
            for b in range(1, NB + 1):
                s["shteqp"][cy, b, d, f] = SHTSHR[b, d, f] * EH[cy, b, d] + NSHTSHR[b, d, f] * NH[cy, b, d]

                existing = SHTSHR[b, d, f] * EH[cy, b, d] * SHTUEC[d, f, b] * HDDFACT[d] \
                    * (EHS[cy, fshell, d, b] / EHS[RECSYEAR, fshell, d, b])
                added = NSHTSHR[b, d, f] * NH[cy, b, d] * SHTUEC[d, f, b] * HDDFACT[d] \
                    * (AHS[cy, fshell, d, b] / EHS[RECSYEAR, fshell, d, b])

                s["shtcon"][Y, f, d] = s["shtcon"][Y, f, d] + LEAPYR * (existing + added) * rs
                s["shtconwt"][Y, f, d, b] = s["shtconwt"][Y, f, d, b] + LEAPYR * (existing + added) * rs

                if ((EH[cy, b, d] + NH[cy, b, d]) > 0.0 and EHS[RECSYEAR, fshell, d, b] > 0.0
                        and SHTSHR[b, d, f] > 0.0 and AHS[cy, fshell, d, b] > 0.0 and NSHTSHR[b, d, f] > 0.0):
                    # EIA leaves HDDFACT out of the existing-home term here
                    ex_in = SHTSHR[b, d, f] * EH[cy, b, d] * SHTUEC[d, f, b] \
                        * (EHS[cy, fshell, d, b] / EHS[RECSYEAR, fshell, d, b])
                    s["shtconin"][Y, f, d, b] = s["shtconin"][Y, f, d, b] + (ex_in + added) / (EH[cy, b, d] + NH[cy, b, d])

                s["sheqcn"][Y, f, b, d] = LEAPYR * (existing + added) * rs


# ---------------------------------------------------------------------------
# APPCNS
# ---------------------------------------------------------------------------

def _lpg_grill_table(s: dict):
    """Share of homes with propane grills by year: 0.34 in the RECS year, rising in
    equal steps to 0.60 in ijumpcalyr. EIA builds it on the first iteration of the
    first post-RECS year and keeps it in a SAVEd local."""
    ij = int(s["ijumpcalyr"])
    t = FArray.zeros([(RECSYEAR, 2050)])
    t[RECSYEAR] = f32(0.34)
    t[ij] = f32(0.60)
    for y1 in range(RECSYEAR + 1, ij + 1):
        t[y1] = t[y1 - 1] + ((t[ij] - t[RECSYEAR]) / f32(ij - RECSYEAR))
    return t


def appcns(s: dict) -> None:
    """APPCNS: other-fuel appliances (gas, propane, distillate): equipment stocks and consumption."""
    with np.errstate(all="ignore"):
        _appcns(s)


def _appcns(s: dict) -> None:
    cy = int(s["curcalyr"])
    itr = int(s["curitr"])
    Y = cy - BASEYR + 1
    ij = int(s["ijumpcalyr"])
    ef1, ef2, ef3 = f32(0.5), f32(0.35), f32(0.15)
    ALPHA = f32(-0.15)
    EUPR = 10
    EH, NH = s["eh"], s["nh"]
    APPEQP, APLEQP, APPUEC = s["appeqp"], s["apleqp"], s["appuec"]
    LEAPYR = _leapyr(cy)

    if "lpggrill" not in s:
        s["lpggrill"] = _lpg_grill_table(s)
    LPG = s["lpggrill"]
    LPG[RECSYEAR] = f32(0.34)
    LPG[ij] = f32(0.60)

    if cy == RECSYEAR + 1:
        for d in range(1, ND + 1):
            for b in range(1, NB + 1):
                for f in range(1, 4):
                    APLEQP[RECSYEAR, b, d, f] = APPEQP[RECSYEAR, b, d, f]

    if cy == RECSYEAR + 1 and itr == 1:
        for y1 in range(RECSYEAR + 1, ij + 1):
            LPG[y1] = LPG[y1 - 1] + ((LPG[ij] - LPG[RECSYEAR]) / f32(ij - RECSYEAR))

    for d in range(1, ND + 1):
        for b in range(1, NB + 1):
            for f in range(1, 4):
                if f == 2:  # propane
                    APLEQP[cy, b, d, f] = (APPEQP[RECSYEAR, b, d, f] / EH[RECSYEAR, b, d]) \
                        * (EH[cy, b, d] + NH[cy, b, d]) * (LPG[cy] / LPG[RECSYEAR])
                else:
                    APLEQP[cy, b, d, f] = (APPEQP[RECSYEAR, b, d, f] / EH[RECSYEAR, b, d]) * EH[cy, b, d]

    for d in range(1, ND + 1):
        for f in range(1, 4):
            if f == 1:
                f1 = 3
            if f == 2:
                f1 = 2
            if f == 3:
                f1 = 1
            rs = rselast(s, f1, d, ALPHA, ef1, ef2, ef3, EUPR)
            s["aplcon"][Y, f, d] = 0.0
            for b in range(1, NB + 1):
                s["aplcon"][Y, f, d] = s["aplcon"][Y, f, d] + LEAPYR * APLEQP[cy, b, d, f] * APPUEC[d, f, b] * rs
                s["aplconwt"][Y, f, d, b] = LEAPYR * APLEQP[cy, b, d, f] * APPUEC[d, f, b] * rs
                if (EH[cy, b, d] + NH[cy, b, d]) > 0.0:
                    s["aplconin"][Y, f, d, b] = (APLEQP[cy, b, d, f] * APPUEC[d, f, b]) / (EH[cy, b, d] + NH[cy, b, d])
                s["apeqcn"][Y, f, b, d] = LEAPYR * APLEQP[cy, b, d, f] * APPUEC[d, f, b] * rs
