"""Prices, new housing and floor area: RDPR, NEWHSE and SQFTCALC (resd.f).

RDPR converts NEMS residential fuel prices to the equipment menu's dollar year.
NEWHSE adds this year's housing starts to the surviving stock of post-RECS homes.
SQFTCALC tracks average floor area of existing, new and total homes.
"""

from nems_open.residential.common import BASEYR, MNUMBLDG, MNUMYR, NUM_DIV, RECSYEAR, f32, powi


def rdpr(s: dict) -> None:
    """RDPR: PRICES(fuel, division, calendar year) in RTEKDOLLARYR dollars.
    Fuels: 1 distillate, 2 propane, 3 natural gas, 4 electricity, 5 wood."""
    P, gdp = s["prices"], s["mc_jpgdp"]
    y_cal, y = int(s["curcalyr"]), int(s["curiyr"])
    infl = f32(gdp[int(s["rtekdollaryr"]) - BASEYR + 1] / gdp[-2])
    if y_cal == RECSYEAR:
        for d in range(1, NUM_DIV + 1):
            for yy in range(1, MNUMYR + 1):
                y1 = yy + BASEYR - 1
                P[1, d, y1] = s["pdsrs"][d, yy] * infl
                P[2, d, y1] = s["plgrs"][d, yy] * infl
                P[3, d, y1] = s["pngrs"][d, yy] * infl
                P[4, d, y1] = s["pelrs"][d, yy] * infl
                P[5, d, y1] = s["pdsrs"][d, yy] * infl  # wood priced to distillate in the RECS year
        return
    for d in range(1, NUM_DIV + 1):
        P[1, d, y_cal] = s["pdsrs"][d, y] * infl
        P[2, d, y_cal] = s["plgrs"][d, y] * infl
        P[3, d, y_cal] = s["pngrs"][d, y] * infl
        P[4, d, y_cal] = s["pelrs"][d, y] * infl
        # After the RECS year wood follows natural gas less any carbon tax (EIA quirk:
        # distillate in the RECS year, gas after).
        P[5, d, y_cal] = f32(s["pngrs"][d, y] - s["jngrs"][y]) * infl
        for f in range(1, 6):
            if P[f, d, y_cal] <= 0.0:
                P[f, d, y_cal] = P[f, d, y_cal - 1]


def newhse(s: dict) -> None:
    """NEWHSE: NH(year, building, division), homes built after the RECS year still
    standing, from housing starts and the survival rate HDR."""
    Y, Y1 = int(s["curcalyr"]), int(s["curiyr"])
    NH, HSEADD, HDR = s["nh"], s["hseadd"], s["hdr"]
    starts = {1: s["mc_husps1"], 2: s["mc_husps2a"], 3: s["mc_husmfg"]}
    for d in range(1, NUM_DIV + 1):
        if Y == RECSYEAR + 1:
            for b in (1, 2, 3):
                NH[RECSYEAR, b, d] = 0.0
        for b in (1, 2, 3):
            HSEADD[Y, b, d] = f32(1000000.0) * starts[b][d, Y1]
            NH[Y, b, d] = f32(1000000.0) * starts[b][d, Y1] + NH[Y - 1, b, d] * HDR[b]
    # EIA quirks kept: ALLNEW keeps only the last building type, and the household
    # count divides the running total by a million on every pass.
    for d in range(1, NUM_DIV + 1):
        for b in range(1, MNUMBLDG + 1):
            s["allnew"][Y, d] = NH[Y, b, d]
    H = s["hhstockbydiv"]
    for d in range(1, NUM_DIV + 1):
        H[Y, d] = 0.0
        for b in range(1, MNUMBLDG + 1):
            H[Y, d] = (H[Y, d] + NH[Y, b, d] + s["eh"][Y, b, d]) / f32(1000000.0)


def sqftcalc(s: dict) -> None:
    """SQFTCALC: floor area per home. Existing homes grow by a fixed renovation
    allowance a year; new homes carry the size of the year they were built."""
    Y, Y1 = int(s["curcalyr"]), int(s["curiyr"])
    EH, NH, HSEADD, HDR = s["eh"], s["nh"], s["hseadd"], s["hdr"]
    SQ, EXSQ, SQNEW, STOCK = s["sqrfoot"], s["exsqrfoot"], s["sqnew"], s["stocksqrfoot"]
    renovate = f32(7.18)

    old, new = f32(0.0), f32(0.0)
    for b in range(1, MNUMBLDG + 1):
        for d in range(1, NUM_DIV + 1):
            old = f32(old + EH[Y, b, d])
            new = f32(new + NH[Y, b, d])
    s["oldhses"][Y], s["newhses"][Y] = old, new

    if Y == RECSYEAR + 1:
        tot = f32(0.0)
        for d in range(1, NUM_DIV + 1):
            for b in range(1, MNUMBLDG + 1):
                tot = f32(tot + SQ[RECSYEAR, b, d] * EH[RECSYEAR, b, d])
                EXSQ[RECSYEAR, b, d] = SQ[RECSYEAR, b, d]
        s["sqftavg"][Y1 - 1] = tot / s["oldhses"][RECSYEAR]

    for d in range(1, NUM_DIV + 1):
        for b in range(1, MNUMBLDG + 1):
            EXSQ[Y, b, d] = SQ[RECSYEAR, b, d] + renovate * f32(Y - RECSYEAR)

    for b in range(1, MNUMBLDG + 1):
        for d in range(1, NUM_DIV + 1):
            if Y == RECSYEAR + 1:
                SQNEW[RECSYEAR, b, d] = 0.0
            else:
                acc = f32(0.0)
                for t in range(RECSYEAR + 1, Y):
                    acc = f32(acc + (HSEADD[t, b, d] * powi(HDR[b], Y - 1 - t)) * SQ[t, b, d] / NH[Y - 1, b, d])
                SQNEW[Y - 1, b, d] = acc

    for b in range(1, MNUMBLDG + 1):
        for d in range(1, NUM_DIV + 1):
            if Y == RECSYEAR + 1:
                STOCK[Y - 1, b, d] = EXSQ[Y - 1, b, d]
                STOCK[Y, b, d] = (EH[Y, b, d] * EXSQ[Y, b, d] + HSEADD[Y, b, d] * SQ[Y, b, d]) / (EH[Y, b, d] + HSEADD[Y, b, d])
            else:
                STOCK[Y, b, d] = (EH[Y, b, d] * EXSQ[Y, b, d] + HSEADD[Y, b, d] * SQ[Y, b, d]
                                  + SQNEW[Y - 1, b, d] * NH[Y - 1, b, d]) / (EH[Y, b, d] + NH[Y, b, d])

    tot = f32(0.0)
    for d in range(1, NUM_DIV + 1):
        for b in range(1, MNUMBLDG + 1):
            tot = f32(tot + (SQ[Y, b, d] * HSEADD[Y, b, d] + SQNEW[Y - 1, b, d] * NH[Y - 1, b, d]
                             + EXSQ[Y, b, d] * EH[Y, b, d]))
    s["sqftavg"][Y1] = tot / (s["oldhses"][Y] + s["newhses"][Y])
