"""Fleet fuel use and household travel (tran.f): TFLTCONS, TVMT.

TFLTCONS  fleet fuel use (gallons and Btu) by fuel type and region, splitting
          flex-fuel, bi-fuel and plug-in hybrids by their alternative-fuel shares
TVMT      cost of driving per mile, VMT per licensed driver by age group and sex
          (a log-linear regression), household VMT by vintage, scaled so household
          plus fleet VMT matches total driver demand
"""

import numpy as np

from nems_open.transportation.common import AGEGRP, MAXAGE, MAXHAV, MAXLDV, MAXVTYP, MF, MNUMCR, f32, fsum
from nems_open.transportation.mean_funcs import weighted_mean

MAXFLEET = 4
MAXFUEL = 8
R9 = slice(1, MNUMCR - 2)


def tfltcons(s: dict) -> None:
    n = int(s["n"])
    gge, btu, mpg = s["fltechgge"], s["fltechbtu"], s["mpgfltstk"]
    gge[1:MNUMCR, 1:MAXVTYP, 1:MAXFLEET, 1:MAXLDV, n] = 0.0
    btu[1:MNUMCR, 1:MAXVTYP, 1:MAXFLEET, 1:MAXLDV, n] = 0.0
    m = mpg[1:MNUMCR, 1:MAXVTYP, 1:MAXFLEET, 1:MAXLDV, n]
    vmt = fsum(s["fltechvmt"][1:MNUMCR, 1:MAXVTYP, 1:MAXFLEET, 1:MAXLDV, 1:MAXHAV], axis=4)
    ok = m != 0.0
    with np.errstate(divide="ignore", invalid="ignore"):
        g = (vmt / f32(1000000.0)) / m
        gge[1:MNUMCR, 1:MAXVTYP, 1:MAXFLEET, 1:MAXLDV, n] = np.where(ok, g, f32(0.0))
        btu[1:MNUMCR, 1:MAXVTYP, 1:MAXFLEET, 1:MAXLDV, n] = np.where(ok, g * s["cfmgq"][n] / f32(42.0), f32(0.0))

    s["fltldvbtu"][1:MNUMCR, 1:MAXVTYP, 1:MAXLDV, n] = fsum(btu[1:MNUMCR, 1:MAXVTYP, 1:MAXFLEET, 1:MAXLDV, n], axis=2)
    s["fltldvbtut"][1:MNUMCR, 1:MAXLDV, n] = fsum(s["fltldvbtu"][1:MNUMCR, 1:MAXVTYP, 1:MAXLDV, n], axis=1)

    t = lambda ildv: s["fltldvbtut"][R9, ildv, n]  # noqa: E731
    af = s["pctaf"]
    p20, p50 = s["pctphev20"][n], s["pctphev50"][n]
    one = f32(1.0)
    fuel = s["fltfuelbtu"]
    fuel[R9, 1:MAXFUEL, n] = 0.0
    fuel[R9, 1, n] = (t(1) + t(3) * (one - af[2, R9, n]) + t(5) * (one - p20) + t(6) * (one - p50)
                      + t(9) * (one - af[3, R9, n]) + t(10) * (one - af[4, R9, n]) + t(16))
    fuel[R9, 2, n] = t(13)
    fuel[R9, 3, n] = t(3) * af[2, R9, n]
    fuel[R9, 4, n] = t(9) * af[3, R9, n] + t(11)
    fuel[R9, 5, n] = t(10) * af[4, R9, n] + t(12)
    fuel[R9, 6, n] = t(5) * p20 + t(6) * p50 + t(7) + t(4) + t(15)
    fuel[R9, 7, n] = t(14)
    fuel[R9, 8, n] = t(2) + t(8)
    s["ifuel"] = MAXFUEL + 1
    fuel[MNUMCR, 1:MAXFUEL, n] = fsum(fuel[R9, 1:MAXFUEL, n], axis=0)


def tvmt(s: dict) -> None:
    n, yrs = int(s["n"]), int(s["curcalyr"])
    jp, cost = s["mc_jpgdp"], s["costmi"]
    hhvmt, fltvmt = s["vmt_stk_hh"], s["fltechvmt"]
    hhmpg, fltmpg = s["hhmpgstk_ldv"], s["fltmpgstk_ldv"]

    def counted(ildv):
        # EIA's .OR./.AND. precedence: powertrains 1-7 always count; 15-16 only with both MPGs.
        return ildv <= 7 or (ildv >= 15 and hhmpg[ildv, n] > 0.0 and fltmpg[ildv, n] > 0.0)

    def hh_sum(ildv, iregn):
        return fsum(hhvmt[1:MAXVTYP, ildv, :, 1:MAXHAV, iregn])

    def flt_sum(ildv, iregn):
        return fsum(fltvmt[iregn, 1:MAXVTYP, 1:MAXFLEET, ildv, 1:MAXHAV])

    if yrs < 2013:
        for iregn in range(1, MNUMCR + 1):
            if iregn == 10:
                continue
            cost[iregn, n] = ((s["pmgtr"][iregn, n] * s["cfmgq"][n] / f32(42.0)) / s["trldmpgf"][3, n]) * f32(100.0) * jp[11]
    else:
        temp = {ildv: f32(0.0) for ildv in range(1, MAXLDV + 1)}
        for ildv in range(1, MAXLDV + 1):
            if counted(ildv):
                h, f = hh_sum(ildv, MNUMCR), flt_sum(ildv, MNUMCR)
                temp[ildv] = (h + f) / (h / hhmpg[ildv, n] + f / fltmpg[ildv, n])
        fprice = s["fprice"]
        for iregn in range(1, MNUMCR + 1):
            if iregn == 10:
                continue
            num1 = num2 = f32(0.0)
            for ildv in range(1, MAXLDV + 1):
                if counted(ildv):
                    h, f = hh_sum(ildv, iregn), flt_sum(ildv, iregn)
                    num1 = num1 + (fprice[ildv, iregn, yrs] / temp[ildv] * (h + f))
                    num2 = num2 + h + f
            # FPRICE is 1990 cents per gallon; COSTMI is 2000 cents per mile.
            cost[iregn, n] = num1 / num2 * jp[11] / jp[1]
        s["ildv"] = MAXLDV + 1
    s["iregn"] = MNUMCR + 1

    emp = s["emp_rate_vmt"]
    emp[n] = s["mc_eea"][n] / s["mc_np16a"][11, n]

    vmtld = s["vmtld"]
    log = np.log
    hist = int(s["vmtldhistyr"])
    if yrs > hist:
        for imf in range(1, MF + 1):
            vmtld[1:AGEGRP, n, imf] = (s["alpha"][imf, 1:AGEGRP] + s["betavmt"][imf, 1:AGEGRP] * log(vmtld[1:AGEGRP, n - 1, imf])
                                       + s["betainc"][imf, 1:AGEGRP] * log(s["inc00_d_16"][11, n])
                                       + s["betacost"][imf, 1:AGEGRP] * log(cost[MNUMCR, n])
                                       + s["betavpld"][imf, 1:AGEGRP] * log(s["vpld"][n])
                                       + s["betaemp"][imf, 1:AGEGRP] * log(emp[n]))
        s["imf"] = MF + 1
    if yrs > hist + 1:
        # Drivers 65 and over: the cohort ages.
        mmac = int(s["mmac"])
        for imf in range(1, MF + 1):
            vmtld[5, n, imf] = vmtld[5, n, imf] * s["age_adj"][imf, n]
            if mmac == 4:
                vmtld[5, n, imf] = vmtld[5, n, imf] * s["age_adj_l"][imf, n]
            if mmac == 5:
                vmtld[5, n, imf] = vmtld[5, n, imf] * s["age_adj_h"][imf, n]
        s["imf"] = MF + 1

    vmtldv, ld = s["vmtldv"], s["licdriver"]
    for imf in range(1, MF + 1):
        for iagr in range(1, AGEGRP + 1):
            vmtldv[iagr, n, imf, R9] = vmtld[iagr, n, imf] * ld[iagr, imf, R9, n]
    s.update(imf=MF + 1, iagr=AGEGRP + 1)
    vmtldv[1:AGEGRP, n, 1:MF, MNUMCR] = fsum(vmtldv[1:AGEGRP, n, 1:MF, R9], axis=2)

    pvmt, lvmt, stock = s["pvmt"], s["lvmt"], s["ldv_stock"]
    for iage in range(1, MAXAGE + 1):
        for ildv in range(1, MAXLDV + 1):
            pvmt[iage, n, MNUMCR, ildv] = weighted_mean(pvmt[iage, n, R9, ildv], stock[R9, 1, 1, ildv, iage, 1, n], "PVMT(mnumcr)")
            lvmt[iage, n, MNUMCR, ildv] = weighted_mean(lvmt[iage, n, R9, ildv], stock[R9, 2, 1, ildv, iage, 1, n], "PVMT(mnumcr)")

    hht = s["hhtechvmt"]
    hht.a[...] = 0.0
    for ildv in range(1, MAXLDV + 1):
        hht[R9, 1, ildv, 1:MAXAGE] = stock[R9, 1, 1, ildv, 1:MAXAGE, 1, n] * pvmt[1:MAXAGE, n, R9, ildv].T
        hht[R9, 2, ildv, 1:MAXAGE] = stock[R9, 2, 1, ildv, 1:MAXAGE, 1, n] * lvmt[1:MAXAGE, n, R9, ildv].T
        for ivtyp in range(1, MAXVTYP + 1):
            hht[MNUMCR, ivtyp, ildv, 1:MAXAGE] = fsum(hht[R9, ivtyp, ildv, 1:MAXAGE], axis=0)

    # Scale household VMT so household plus fleet matches driver demand.
    fleet = fsum(fsum(fsum(fsum(fltvmt[R9, 1:MAXVTYP, 1:MAXFLEET, 1:MAXLDV, 1:MAXHAV], axis=4), axis=3), axis=2), axis=1)
    vmtldvhh = fsum(fsum(vmtldv[1:AGEGRP, n, 1:MF, R9], axis=1), axis=0) - fleet / f32(1000000000.0)
    hhvmtadj = vmtldvhh / (fsum(fsum(fsum(hht[R9, 1:MAXVTYP, 1:MAXLDV, 1:MAXAGE], axis=3), axis=2), axis=1) / f32(1000.0))
    for ivtyp in range(1, MAXVTYP + 1):
        for ildv in range(1, MAXLDV + 1):
            for iage in range(1, MAXAGE + 1):
                hht[R9, ivtyp, ildv, iage] = hht[R9, ivtyp, ildv, iage] * hhvmtadj
                hht[MNUMCR, ivtyp, ildv, iage] = fsum(hht[R9, ivtyp, ildv, iage])

    for ivtyp in range(1, MAXVTYP + 1):
        s["vmthh"][n, 1:MNUMCR, 1:MAXLDV, ivtyp] = fsum(hht[1:MNUMCR, ivtyp, 1:MAXLDV, 1:MAXAGE], axis=2) / f32(1000.0)

    s["pe"][n] = f32(1.0)
    s["ie"][n] = f32(1.0)
    s["de"][n] = f32(1.0)
    s.update(iregn=MNUMCR - 1, iage=MAXAGE + 1, ildv=MAXLDV + 1, ivtyp=MAXVTYP + 1)
