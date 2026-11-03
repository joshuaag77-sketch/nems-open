"""Short light-duty routines from tran.f: TREG, TFLTVMTS, TCURB, TMPGAG.

TREG       regional shares of each fuel: SEDS history, then grown with income
TFLTVMTS   fleet VMT by vehicle type, fleet, fuel and automation level
TCURB      average curb weight of the car and light truck stock, by vintage
TMPGAG     fleet average stock fuel economy (household weighted by VMT, plus fleets)
"""

from nems_open.transportation.common import MAXAGE, MAXHAV, MAXLDV, MAXVTYP, MNUMCR, f32, fsum
from nems_open.transportation.mean_funcs import weighted_mean

MSEDYR = 34  # last SEDS history year index (2023)
MAXFLEET = 4

# (TRANMAIN share name, SEDS quantity) in the order TREG handles them.
SEDS = [("sedshrel", "qseltr"), ("sedshrmg", "qsmgtr"), ("sedshrjf", "qsjftr"), ("sedshrds", "qsdstr"),
        ("sedshrlg", "qslgtr"), ("sedshrrs", "qsrstr"), ("sedshrot", "qsottr")]
NO_SEDS = ["sedshrng", "sedshrme", "sedshret", "sedshrhy"]
ALL = ["sedshrel", "sedshrng", "sedshrmg", "sedshrjf", "sedshrds", "sedshrlg", "sedshrrs",
       "sedshrot", "sedshrme", "sedshret", "sedshrhy"]


def treg(s: dict) -> None:
    n = int(s["n"])
    if int(s["curiyr"]) <= MSEDYR:
        for ir in range(1, MNUMCR - 1):
            for shr, q in SEDS:
                if s[q][11, n] != 0.0:
                    s[shr][ir, n] = s[q][ir, n] / s[q][11, n]
            # Fuels with no SEDS split get 1/9 each for now.
            for shr in NO_SEDS:
                s[shr][ir, n] = f32(0.1111)
    else:
        ypdr = s["mc_ypdr"]
        for ir in range(1, MNUMCR - 1):
            inc_growth = ypdr[ir, n] / ypdr[ir, n - 1]
            for shr in ALL:
                if s[shr][ir, n - 1] < 0.0001:
                    s[shr][ir, n - 1] = f32(0.0001)
            for shr in ALL:
                s[shr][ir, n] = s[shr][ir, n - 1] * inc_growth
    for shr in ALL:
        s[shr][MNUMCR, n] = fsum(s[shr][1:MNUMCR - 2, n])
    # Region 11 is divided last, by itself, so it ends at 1.
    for ir in range(1, MNUMCR + 1):
        for shr in ALL:
            s[shr][ir, n] = s[shr][ir, n] / s[shr][MNUMCR, n]


def tfltvmts(s: dict) -> None:
    n = int(s["n"])
    vmt, stk, yr = s["fltechvmt"], s["fltechstk"], s["fltvmtyr"]
    for ivtyp in range(1, MAXVTYP + 1):
        for ifleet in range(1, MAXFLEET + 1):
            vmt[1:MNUMCR, ivtyp, ifleet, 1:MAXLDV, 1:MAXHAV] = (
                stk[1:MNUMCR, ivtyp, ifleet, 1:MAXLDV, 1:MAXHAV] * yr[ifleet, n, ivtyp])
    s["ivtyp"], s["ifleet"] = MAXVTYP + 1, MAXFLEET + 1


def tcurb(s: dict) -> None:
    if int(s["curcalyr"]) < 1995:
        return
    n = int(s["n"])
    w, stock = s["stkavgwgt"], s["ldv_stock"]
    if int(s["curitr"]) == 1 and int(s["curcalyr"]) > 2006:
        # Once a year: fold the oldest two vintages together, then age everything a year.
        for ivtyp in range(1, MAXVTYP + 1):
            w[ivtyp, MAXAGE] = ((w[ivtyp, MAXAGE] * fsum(stock[MNUMCR, ivtyp, 1, 1:MAXLDV, MAXAGE, 1, n])
                                 + w[ivtyp, MAXAGE - 1] * fsum(stock[MNUMCR, ivtyp, 1, 1:MAXLDV, MAXAGE - 1, 1, n]))
                                / fsum(stock[MNUMCR, ivtyp, 1, 1:MAXLDV, MAXAGE - 1:MAXAGE, 1, n]))
        s["ivtyp"] = MAXVTYP + 1
        for iage in range(MAXAGE - 1, 1, -1):
            w[1:2, iage] = w[1:2, iage - 1]
        s["iage"] = 1
    w[1, 1] = s["awtcar"][11, n]
    w[2, 1] = s["awttruck"][11, n]
    s["trwtcar_stock"][n] = weighted_mean(w[1, 1:MAXAGE], fsum(stock[MNUMCR, 1, 1, 1:MAXLDV, 1:MAXAGE, 1, n], axis=0),
                                          "TRWTCAR_STOCK")
    s["trwttrk_stock"][n] = weighted_mean(w[2, 1:MAXAGE], fsum(stock[MNUMCR, 2, 1, 1:MAXLDV, 1:MAXAGE, 1, n], axis=0),
                                          "TRWTTRK_STOCK")


def tmpgag(s: dict) -> None:
    n = int(s["n"])
    hh, eff, cf = s["hhmpgstk_typ"], s["treffflt"], s["cfmgq"]
    vmt, stock, fltcar = s["vmt_stk_hh"], s["ldv_stock"], s["totfltcar"]
    sum1 = [f32(0.0), f32(0.0)]
    for k, irow in ((0, 3), (1, 4)):
        if hh[k + 1, n] != 0.0 and eff[irow, n] != 0.0:
            sum1[k] = ((fsum(vmt[k + 1, 1:MAXLDV, 1:MAXAGE, 1, 1:MNUMCR - 2]) / (hh[k + 1, n] * (cf[n] / cf[18])))
                       + (fltcar[k + 1] / (eff[irow, n] * (cf[n] / cf[18]))))
    sum2 = [fsum(stock[MNUMCR, k, 1, 1:MAXLDV, 1:MAXAGE, 1, n]) + fltcar[k] for k in (1, 2)]
    mpg = s["trldmpgf"]
    for ivtyp in range(1, MAXVTYP + 1):
        mpg[ivtyp, n] = f32(0.0)
        if sum1[ivtyp - 1] != 0.0 and sum2[ivtyp - 1] != 0.0:
            mpg[ivtyp, n] = f32(1.0) / (sum1[ivtyp - 1] / sum2[ivtyp - 1])
    s["ivtyp"] = MAXVTYP + 1
    mpg[3, n] = f32(0.0)
    if sum1[0] + sum1[1] != 0.0 and sum2[0] + sum2[1] != 0.0:
        mpg[3, n] = f32(1.0) / ((sum1[0] + sum1[1]) / (sum2[0] + sum2[1]))
