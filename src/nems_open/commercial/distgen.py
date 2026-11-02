"""CDistGen: on-site generation in commercial buildings (port of CDISTGEN in comm.f).

Estimates, for each technology (rooftop solar PV, fuel cells, gas engines, coal, oil, MSW,
gas turbines, microturbines, hydro, wood, small wind), census division and building type,
how many units are installed, how much they generate, how much of that the building uses
itself, the heat recovered and the fuel burned. Through 2024 it works back from reported
cogeneration (KCOGEN). After that each year it builds a 30-year cash flow for a typical
system in each niche (building size, climate, electricity rate level), solves for its
internal rate of return, turns the payback into a maximum penetration, and moves along a
Bass diffusion curve toward it. Units added this year are summed over the niches.

Outputs the rest of NEMS reads: generation, capacity and fuel use by fuel (CGCOMM*), RPS
credit multipliers (CGCPVCOM, CGCWNCOM), clean-energy credits for gas CHP (KCHPCESGEN),
shipments for learning (CPV_MW, ...), and the generation net of own use (QCMDGSG).

Arithmetic is float32 and follows the Fortran line by line, including quirks listed in
SCOPE.md. Arrays are 1-based (index 0 unused) with the Fortran's own index in every dimension.
"""

import math
from dataclasses import dataclass

import numpy as np

from nems_open.commercial.distgen_tables import DgTables

f32 = np.float32
BASEYR = 1990
CBECS_IDX = 29
CM_FIRST_YR = 30
CM_COG_HST_YR = 35
KSTEOYR = 37
SOLAR_BM_YR = 39
MNUMCR = 11
MNUMCGF = 13
NUM_DIV = 9
NUM_BLDG = 11
NTEK = 11
MNUMYR = 61

C_003412 = f32(0.003412)
C_001 = f32(0.001)
ONE_E6 = f32(1.0e6)
ONE_E12 = f32(1.0e12)


def ipow(x, n: int):
    """x ** n for an integer n, by repeated multiplication in float32 (what compiled Fortran does)."""
    n = int(n)
    result = f32(1.0)
    base = f32(x)
    m = abs(n)
    while m > 0:
        if m & 1:
            result = f32(result * base)
        base = f32(base * base)
        m >>= 1
    return f32(f32(1.0) / result) if n < 0 else result


def fexp(x):
    return f32(math.exp(float(x)))


def flog(x):
    return f32(math.log(float(x)))


def fpow(x, y):
    return f32(math.pow(float(x), float(y)))


def ifix(x) -> int:
    return int(x)


def learn_cost(max_cost, beta, c0, cum_ship):
    """LearnCost: cost falls with cumulative shipments, never above the default cost."""
    if cum_ship <= 1.0:
        return max_cost
    if c0 == 0.0:
        return max_cost
    return min(max_cost, fexp(f32(flog(c0) - f32(beta * flog(cum_ship)))))


def xnpv(cash, disc):
    """XNPV: net present value of a 30-year cash flow (entries 1..30), discounted back to year 1."""
    npv = f32(0.0)
    for i in range(30, 1, -1):
        npv = f32(f32(npv + cash[i]) / f32(f32(1.0) + disc))
    return f32(npv + cash[1])


def _ones_div():
    """Credit multipliers start at 1 for the nine divisions (EIA sets them in the first call)."""
    a = np.zeros((12, MNUMYR + 1), dtype=f32)
    a[1:NUM_DIV + 1, :] = 1.0
    return a


@dataclass
class DgState:
    """Arrays CDISTGEN keeps from year to year. [y, div, bld, nt] unless noted; 1-based."""
    UNITS: np.ndarray
    TRILLS: np.ndarray
    capacity: np.ndarray
    TRILLSOWNUSE: np.ndarray
    fuelusage: np.ndarray
    HWBTU: np.ndarray
    SHBTU: np.ndarray
    INVEST: np.ndarray
    xCumPenSqft: np.ndarray
    QCMDGSG: np.ndarray            # [y, div]
    com111drensub: np.ndarray      # [y, div, nt]
    SolarPVTechPotentialMW: np.ndarray   # [y, div]
    SolarPVAvailRoofArea: np.ndarray     # [y, div, bld]
    SolarPVInstalledMW: np.ndarray
    SolarPVUsedRoofArea: np.ndarray
    WindTechPotentialMW: np.ndarray
    WindAvailFS: np.ndarray
    WindInstalledMW: np.ndarray
    WindBldgCount: np.ndarray
    xPVGenAdded: np.ndarray        # [div, y]
    xWindGenAdded: np.ndarray
    xpen: dict                     # {y: array [div, bld, nt, niche, rate, size]}
    # Shared with other modules:
    CGCOMMGEN: np.ndarray          # [r, y, f, 1 grid sales / 2 own use]
    CGCOMMCAP: np.ndarray          # [r, y, f]
    CGCOMMQ: np.ndarray
    CGCPVCOM: np.ndarray           # [div, y]
    CGCWNCOM: np.ndarray
    KCHPCESGEN: np.ndarray
    CFuelCell_MW: np.ndarray       # [y]
    CPV_MW: np.ndarray
    CMicroTur_MW: np.ndarray
    CWind_MW: np.ndarray
    CMUSCogen: np.ndarray          # [i, y]

    @classmethod
    def empty(cls):
        z4 = lambda: np.zeros((MNUMYR + 1, 12, 12, 12), dtype=f32)
        z3 = lambda: np.zeros((MNUMYR + 1, 12, 12), dtype=f32)
        z2 = lambda: np.zeros((MNUMYR + 1, 12), dtype=f32)
        return cls(
            UNITS=z4(), TRILLS=z4(), capacity=z4(), TRILLSOWNUSE=z4(), fuelusage=z4(), HWBTU=z4(), SHBTU=z4(),
            INVEST=z4(), xCumPenSqft=z4(), QCMDGSG=z2(), com111drensub=z3(),
            SolarPVTechPotentialMW=z2(), SolarPVAvailRoofArea=z3(), SolarPVInstalledMW=z2(),
            SolarPVUsedRoofArea=z3(), WindTechPotentialMW=z2(), WindAvailFS=z3(), WindInstalledMW=z2(),
            WindBldgCount=z3(), xPVGenAdded=np.zeros((12, MNUMYR + 1), dtype=f32),
            xWindGenAdded=np.zeros((12, MNUMYR + 1), dtype=f32), xpen={},
            CGCOMMGEN=np.zeros((MNUMCR + 1, MNUMYR + 1, MNUMCGF + 1, 3), dtype=f32),
            CGCOMMCAP=np.zeros((MNUMCR + 1, MNUMYR + 1, MNUMCGF + 1), dtype=f32),
            CGCOMMQ=np.zeros((MNUMCR + 1, MNUMYR + 1, MNUMCGF + 1), dtype=f32),
            CGCPVCOM=_ones_div(), CGCWNCOM=_ones_div(),
            KCHPCESGEN=np.zeros((MNUMCR + 1, MNUMYR + 1), dtype=f32),
            CFuelCell_MW=np.zeros(MNUMYR + 1, dtype=f32), CPV_MW=np.zeros(MNUMYR + 1, dtype=f32),
            CMicroTur_MW=np.zeros(MNUMYR + 1, dtype=f32), CWind_MW=np.zeros(MNUMYR + 1, dtype=f32),
            CMUSCogen=np.zeros((5, MNUMYR + 1), dtype=f32))


def _zero_year(st: DgState, y: int) -> None:
    """Start of every call: clear this year's results (EIA does it inside the NT loop; same effect)."""
    for idiv in range(1, NUM_DIV + 1):
        st.SolarPVTechPotentialMW[y, idiv] = 0.0
        st.WindTechPotentialMW[y, idiv] = 0.0
        st.WindInstalledMW[y, idiv] = 0.0
        st.SolarPVInstalledMW[y, idiv] = 0.0
        st.QCMDGSG[y, idiv] = 0.0
        for ibld in range(1, NUM_BLDG + 1):
            st.SolarPVAvailRoofArea[y, idiv, ibld] = 0.0
            st.WindAvailFS[y, idiv, ibld] = 0.0
            st.SolarPVUsedRoofArea[y, idiv, ibld] = 0.0
            for nt in range(1, NTEK + 1):
                for arr in (st.UNITS, st.xCumPenSqft, st.TRILLS, st.capacity, st.HWBTU, st.SHBTU, st.fuelusage,
                            st.TRILLSOWNUSE):
                    arr[y, idiv, ibld, nt] = 0.0
        for nt in range(1, NTEK + 1):
            st.com111drensub[y, idiv, nt] = 0.0


def _historical_cogen(t: DgTables, st: DgState, cogen_el: np.ndarray, y: int) -> None:
    """Through 2024, units come from reported cogeneration by fuel (KCOGEN)."""
    calyear = y + BASEYR - 1
    for r in range(1, NUM_DIV + 1):
        for b in range(1, NUM_BLDG + 1):
            for f in range(1, 15):
                if cogen_el[r, b, f, y] == 0.0:
                    continue
                if f not in (2, 3, 6, 9, 10, 11, 14):
                    continue                      # not a traditional cogeneration fuel
                nt = None
                for cand in range(3, 7):          # gas engines, coal, oil and MSW
                    if t.IFUELTYPE[cand] == f:
                        nt = cand
                        break
                if nt is None:
                    if f == 14:
                        nt = 7                    # gas turbines
                    else:
                        for cand in range(9, 11):  # hydro and wood
                            if t.IFUELTYPE[cand] == f:
                                nt = cand
                                break
                if nt is None:
                    raise RuntimeError(f"Error in Cogen Calcs f = {f}")
                for nv in range(1, t.NVINT + 1):
                    if t.IFIRSTYR[nt, nv] > calyear or t.ILASTYR[nt, nv] < calyear:
                        continue
                    st.UNITS[y, r, b, nt] = f32(f32(cogen_el[r, b, f, y] * f32(1.0e12)) / f32(
                        f32(f32(f32(t.XOPERHOURS[nt] * t.XKW[nt, nv]) * t.XLOSSFAC[nt, nv]) * t.XAVAIL[nt, nv])
                        * f32(3412.0)))


def _cash_flow(p: dict) -> np.float32:
    """30-year cash flow of one system and its internal rate of return. Returns xIRR."""
    xcalceqcost, xcalckw = p["xcalceqcost"], p["xcalckw"]
    xdownpaypct, xintrate, xterm, xinflation = p["xdownpaypct"], p["xintrate"], p["xterm"], p["xinflation"]
    xtaxrate = p["xtaxrate"]
    xmaintcostbase = f32(p["xmaintcst"] * xcalckw)
    xtaxcreditpct = p["xtxcrpct"]
    xtaxcreditmax = p["xtxcrmaxpersys"]
    xlife, xdegradation, xtaxlife = p["xeqlife"], p["xdegrad"], p["xtxlife"]
    xdownpay = f32(xdownpaypct * xcalceqcost)
    xpayment = f32(f32(xintrate / f32(f32(1.0) - fpow(f32(f32(1.0) + xintrate), f32(f32(-1.0) * xterm))))
                   * f32(xcalceqcost - xdownpay))

    # Tax credit phase-down after the Inflation Reduction Act's appropriation year.
    upira = p["upira_appyr"]
    cal = p["curiyr"] + BASEYR - 1
    if upira == 9999 or upira <= 2032:
        pass
    elif cal == upira + 1:
        xtaxcreditpct = f32(xtaxcreditpct * f32(0.75))
    elif cal == upira + 2:
        xtaxcreditpct = f32(xtaxcreditpct * f32(0.50))
    elif cal >= upira + 3:
        xtaxcreditpct = f32(0.0)

    xtottaxcredit = f32(xcalceqcost * xtaxcreditpct)
    if xtaxcreditmax > 0.0:
        xtottaxcredit = min(xtottaxcredit, xtaxcreditmax)
    xtottaxcredit = f32(xtottaxcredit + f32(xcalceqcost * p["comtxcrpct_div"]))
    basis = f32(xcalceqcost - f32(xtottaxcredit * f32(0.5)))
    interval_to_use = int(p["iintervalyrs"])

    n = 31
    xoutlay = [f32(0.0)] * n
    xvalesave = [f32(0.0)] * n
    xprin = [f32(0.0)] * n
    xdepr = [f32(0.0)] * n
    xmaintcost = [f32(0.0)] * n
    xintamt = [f32(0.0)] * n
    xfuelcost = [f32(0.0)] * n
    xtaxcredit = [f32(0.0)] * n
    xloanbal = [f32(0.0)] * n
    net = [f32(0.0)] * n
    xoutlay[1] = f32(xdownpaypct * xcalceqcost)
    xloanbal[1] = f32(xcalceqcost * f32(f32(1.0) - xdownpaypct))
    net[1] = f32(-xoutlay[1])
    carry = 1
    claimed = f32(0.0)
    infl1 = f32(f32(1.0) + xinflation)
    deg1 = f32(f32(1.0) - xdegradation)
    start, phase_out = p["irpsstartyear"], p["irpsphaseoutyear"]
    rps_tech = p["nt"] == 1 or p["nt"] == 11 or p["ifueltype"] == 2
    for iyr in range(2, 31):
        if carry == 1 and iyr >= 3:
            xtaxcredit[iyr] = min(f32(xtottaxcredit - claimed), f32(25000.0))
            xtaxcredit[iyr] = max(xtaxcredit[iyr], f32(0.0))
            claimed = f32(claimed + xtaxcredit[iyr])
            carry = 0
            if xtottaxcredit > claimed:
                carry = 1
        if f32(iyr) <= f32(xterm + f32(1.0)):
            xoutlay[iyr] = xpayment
        xintamt[iyr] = f32(xloanbal[iyr - 1] * xintrate)
        if f32(iyr) <= f32(xterm + f32(1.0)):
            xprin[iyr] = f32(xpayment - xintamt[iyr])
        xloanbal[iyr] = f32(xloanbal[iyr - 1] - xprin[iyr])
        if f32(iyr) <= f32(xtaxlife + f32(1.0)):
            xdepr[iyr] = f32(f32(f32(basis * p["xdep"]) / f32(100.0)) / xtaxlife)
            straight = f32(basis / f32(f32(xtaxlife - f32(iyr)) + f32(2.0)))
            if xdepr[iyr] <= straight:
                xdepr[iyr] = straight
            basis = f32(basis - xdepr[iyr])
        life_ok = f32(iyr) <= f32(xlife + f32(1.0))
        if life_ok:
            xfuelcost[iyr] = f32(p["xbaseyrfuelcost"] * ipow(infl1, iyr - 2))
        if iyr > 2 and (iyr - 2) % interval_to_use == 0 and iyr != 29 and iyr != 30:
            if life_ok:
                xmaintcost[iyr] = f32(f32(xmaintcostbase + f32(p["xintervalcst"] * xcalckw)) * ipow(infl1, iyr - 2))
            interval_to_use = 2 * interval_to_use + iyr
        elif life_ok:
            xmaintcost[iyr] = f32(xmaintcostbase * ipow(infl1, iyr - 2))
        if life_ok:
            xvalesave[iyr] = f32(f32(p["xvalesavebase"] * ipow(infl1, iyr - 2)) * ipow(deg1, iyr - 2))
            if rps_tech:
                def at(v):
                    return f32(f32(v * ipow(infl1, iyr - 2)) * ipow(deg1, iyr - 2))
                if cal + iyr - 1 > phase_out:
                    xvalesave[iyr] = at(p["xvalesavebasenorps"])
                if cal >= start and iyr > p["inumyrsatrpsbaserate"]:
                    xvalesave[iyr] = at(p["xvalesavebaseadjrps"])
                if cal >= start and iyr > p["inumrpscredityrs"]:
                    xvalesave[iyr] = at(p["xvalesavebasenorps"])
                if cal < start:
                    xvalesave[iyr] = at(p["xvalesavebasenorps"])
        xtaxdeduct = f32(f32(xtaxrate * f32(f32(f32(xintamt[iyr - 1] + xmaintcost[iyr - 1]) + xdepr[iyr - 1])
                                            + f32(xfuelcost[iyr - 1] - xvalesave[iyr - 1]))) + xtaxcredit[iyr])
        net[iyr] = f32(f32(f32(f32(-xoutlay[iyr]) - xfuelcost[iyr]) - xmaintcost[iyr]) + xtaxdeduct)
        net[iyr] = f32(net[iyr] + xvalesave[iyr])

    xirr = f32(0.0)
    disc_l = f32(0.0001)
    npv_l = xnpv(net, disc_l)
    if npv_l <= 0:
        return xirr
    disc_u = f32(0.3)
    npv_u = xnpv(net, disc_u)
    for _ in range(100):
        xirr_prev = xirr
        xirr = f32(disc_l - f32(f32(npv_l * f32(disc_u - disc_l)) / f32(npv_u - npv_l)))
        npv_new = xnpv(net, xirr)
        if abs(npv_new) < 1.0:
            break
        if abs(f32(xirr_prev - xirr)) < f32(0.0005):
            break
        if npv_new > 0.0:
            npv_l = npv_new
            disc_l = xirr
        else:
            npv_u = npv_new
            disc_u = xirr
    return xirr


def distgen(t: DgTables, st: DgState, shared: dict, cogen_el: np.ndarray, y: int) -> DgState:
    """One call of CDISTGEN for year index y (after its first-call reads). Changes `st` in place.

    `shared` holds what other modules supply, as plain 1-based arrays: PELME, PELCM, PELCMOUT, PNGCM,
    PDSCM, PCLIN, PCLCM [div, y] (PELCMOUT [div, y, 2]), MC_JPGDP (dict by index, includes -2),
    EPRPSPR, EPRPSTGT [y], UPIRA_APPYR, SurvFloorTotal and CMNewFloorSpace [div, bld, y],
    COMEUI [div, bld, s, f], RPV_MW, UPV_MW, RFuelCell_MW, RWind_MW, RMicroTur_MW [y].
    """
    sh = shared
    calyear = y + BASEYR - 1
    _zero_year(st, y)
    if y <= CM_COG_HST_YR:
        _historical_cogen(t, st, cogen_el, y)

    prev = st.xpen.get(y - 1)
    cur = np.zeros((12, 12, 12, 6, 11, 7), dtype=f32)  # [div, bld, nt, niche, rate, size]
    st.xpen[y] = cur
    if y == CM_FIRST_YR:
        st.xpen[y - 1] = np.zeros_like(cur)
        prev = st.xpen[y - 1]
    jp_ratio_num = sh["MC_JPGDP"][t.iGenCapCostYr - BASEYR + 1]
    jp_den = sh["MC_JPGDP"][-2]
    eprpspr, eprpstgt = sh["EPRPSPR"][y], sh["EPRPSTGT"][y]
    ceschp_const = f32(f32(53.06) / f32(0.82))
    xsqftperkw = f32(0.0)
    xpct_wind = t.xpctWindSuitable

    xcalckw = f32(0.0)
    xannualkwh = f32(0.0)
    xfuelinput = f32(0.0)
    xwaterhtg = f32(0.0)
    xspacehtg = f32(0.0)
    xfuelprice = f32(0.0)
    xcalceqcost = f32(0.0)
    xsolarins = f32(0.0)

    for nt in range(1, t.NUMTECHS + 1):
        for nv in range(1, t.NVINT + 1):
            if t.IFIRSTYR[nt, nv] > calyear or t.ILASTYR[nt, nv] < calyear:
                continue
            # Learning lowers the capital cost of technologies with cumulative shipments.
            name = t.AEQUIPNAME[nt, nv]
            xcapcost = t.XCAPCOST[nt, nv]
            if name == "Fuel_Cell":
                cumship = f32(st.CFuelCell_MW[y - 1] + sh["RFuelCell_MW"][y - 1])
                xadjcost = learn_cost(xcapcost, t.XBeta[nt], t.Xc0[nt], cumship)
            elif name == "Solar_PV":
                if t.GlobalLearn:
                    cumship = f32(f32(st.CPV_MW[y - 1] + sh["RPV_MW"][y - 1]) + sh["UPV_MW"][y - 1])
                else:
                    cumship = f32(st.CPV_MW[y - 1] + sh["RPV_MW"][y - 1])
                xadjcost = learn_cost(xcapcost, t.XBeta[nt], t.Xc0[nt], cumship)
            elif name == "Wind":
                cumship = f32(st.CWind_MW[y - 1] + sh["RWind_MW"][y - 1])
                xadjcost = learn_cost(xcapcost, t.XBeta[nt], t.Xc0[nt], cumship)
            elif name == "Micro_Tur":
                cumship = f32(st.CMicroTur_MW[y - 1] + sh["RMicroTur_MW"][y - 1])
                xadjcost = learn_cost(xcapcost, t.XBeta[nt], t.Xc0[nt], cumship)
            else:
                xadjcost = xcapcost
            xadjcost2 = xadjcost
            fuel_type = int(t.IFUELTYPE[nt])
            xrps = t.xRPS[nt, y]
            eleff, loss, kw_menu = t.XELEFF[nt, nv], t.XLOSSFAC[nt, nv], t.XKW[nt, nv]

            for idiv in range(1, t.NUMDIV + 1):
                # xSalestoGridPRnoRPS = PELME*.003412*J1/J2, left to right
                sales_norps_base = f32(f32(f32(sh["PELME"][idiv, y] * C_003412) * jp_ratio_num) / jp_den)
                for ibld in range(1, t.NUMBLDG + 1):
                    xunits = xtrills = xcapacity = xtrillsownuse = xfuelusage = xhwbtu = xshbtu = xinvest = f32(0.0)
                    floor = f32(sh["SurvFloorTotal"][idiv, ibld, y] + sh["CMNewFloorSpace"][idiv, ibld, y])
                    for isize in range(1, 7):
                        for iniche in range(1, int(t.NumPVNiche[idiv]) + 1):
                            for irate in range(1, 11):
                                rate_sc = t.xRateScalar[idiv, iniche, irate]
                                retail_norps = f32(f32(f32(f32(sh["PELCM"][idiv, y] * rate_sc) * C_003412)
                                                       * jp_ratio_num) / jp_den)
                                cat_share = t.cbecsFlspcCatShare[ibld, idiv, isize]
                                if cat_share == 0.0:
                                    continue
                                avg_sqft = t.cbecsAVGSQFT[ibld, idiv, isize]
                                elec_avg = t.xelecavgkwh[ibld, idiv, isize]
                                sqft_share = t.xSqftShare[idiv, iniche, irate]
                                sales_norps = sales_norps_base
                                if fuel_type == 0 and nt != 11:
                                    # ---- Solar PV ----
                                    pelcmout = sh["PELCMOUT"][idiv, y, 2]
                                    retail = f32(f32(f32(f32(f32(pelcmout * rate_sc) * C_003412)
                                                         + f32(f32(C_001 * eprpspr) * xrps)) * jp_ratio_num) / jp_den)
                                    sales = f32(f32(f32(f32(sh["PELME"][idiv, y] * C_003412)
                                                        + f32(f32(C_001 * eprpspr) * xrps)) * jp_ratio_num) / jp_den)
                                    retail_norps = f32(f32(f32(f32(pelcmout * rate_sc) * C_003412) * jp_ratio_num) / jp_den)
                                    sales_adj = f32(f32(f32(f32(sh["PELME"][idiv, y] * C_003412)
                                                            + f32(f32(C_001 * eprpspr) * f32(1.0))) * jp_ratio_num) / jp_den)
                                    retail_adj = f32(f32(f32(f32(f32(pelcmout * rate_sc) * C_003412)
                                                             + f32(f32(C_001 * eprpspr) * f32(1.0))) * jp_ratio_num) / jp_den)
                                    if calyear < t.iRPSStartYear[nt]:
                                        retail, sales = retail_norps, sales_norps
                                    st.SolarPVAvailRoofArea[y, idiv, ibld] = f32(
                                        st.SolarPVAvailRoofArea[y, idiv, ibld]
                                        + f32(f32(f32(f32(floor * cat_share) * sqft_share)
                                                  * t.xRoofAreatoSqftRatio[idiv, ibld, iniche, irate])
                                              * t.xpctPVSuitable[isize]))
                                    xsqftperkw = f32(f32(f32(77.0) * f32(0.14)) / eleff)
                                    if calyear > 2000:
                                        ins = t.xSolarInsolation[idiv, iniche, irate]
                                        xsolarins = f32(f32(f32(-1.0686) + f32(f32(1.4421) * ins))
                                                        - f32(f32(0.0645) * ipow(ins, 2)))
                                        roof_ratio = t.xRoofAreatoSqftRatio[idiv, ibld, iniche, irate]
                                        size_roof = f32(f32(f32(f32(avg_sqft * roof_ratio) * t.xpctPVSuitable[isize])
                                                            / xsqftperkw) / f32(1.75))
                                        size_kwh = f32(elec_avg / f32(f32(f32(f32(f32(f32(eleff * xsolarins)
                                                                                      * f32(365.25)) / f32(10.8))
                                                                              * xsqftperkw) * loss)))
                                        size_max, size_min = t.xkwmax[nt], t.xkwMin[nt]
                                        xcalckw = f32(float(ifix(max(min(size_roof, size_kwh, size_max), size_min))))
                                        xadjcost2 = fexp(f32(flog(xadjcost) - f32(t.xScaleFac[nt] * flog(f32(xcalckw / kw_menu)))))
                                    else:
                                        xcalckw = kw_menu
                                        xadjcost2 = xadjcost
                                    xannualkwh = f32(f32(f32(f32(f32(f32(eleff * xsolarins) * f32(365.25)) / f32(10.8))
                                                             * xsqftperkw) * xcalckw) * loss)
                                    xexcess = f32(xannualkwh - elec_avg)
                                    xvalesave_base, xvalesave_adj, xvalesave_norps = _value_of_savings(
                                        xannualkwh, xexcess, elec_avg, retail, sales, retail_adj, sales_adj,
                                        retail_norps, sales_norps)
                                    xbaseyrfuelcost = f32(0.0)
                                    xfuelinput = xwaterhtg = xspacehtg = xfuelprice = f32(0.0)
                                elif fuel_type == 0:
                                    # ---- Wind ----
                                    retail = f32(f32(f32(f32(f32(sh["PELCM"][idiv, y] * rate_sc) * C_003412)
                                                         + f32(f32(C_001 * eprpspr) * xrps)) * jp_ratio_num) / jp_den)
                                    sales = f32(f32(f32(f32(sh["PELME"][idiv, y] * C_003412)
                                                        + f32(f32(C_001 * eprpspr) * xrps)) * jp_ratio_num) / jp_den)
                                    sales_adj = f32(f32(f32(f32(sh["PELME"][idiv, y] * C_003412)
                                                            + f32(f32(C_001 * eprpspr) * f32(1.0))) * jp_ratio_num) / jp_den)
                                    retail_adj = f32(f32(f32(f32(f32(sh["PELCMOUT"][idiv, y, 2] * rate_sc) * C_003412)
                                                             + f32(f32(C_001 * eprpspr) * f32(1.0))) * jp_ratio_num) / jp_den)
                                    if calyear < t.iRPSStartYear[nt]:
                                        retail, sales = retail_norps, sales_norps
                                    st.WindAvailFS[y, idiv, ibld] = f32(
                                        st.WindAvailFS[y, idiv, ibld] + f32(f32(f32(floor * cat_share) * sqft_share) * xpct_wind))
                                    mps = t.xWindSpeed[idiv, iniche, irate]
                                    poly = f32(f32(f32(f32(0.0645) - f32(f32(0.0670) * mps)) + f32(f32(0.0210) * ipow(mps, 2)))
                                               - f32(f32(0.0011) * ipow(mps, 3)))
                                    eff_ratio = f32(eleff / t.XELEFF[nt, 1])
                                    if calyear > 2000:
                                        size_kwh = f32(elec_avg / f32(f32(f32(eff_ratio * poly) * f32(8760.0)) * loss))
                                        size_max, size_min = t.xkwmax[nt], t.xkwMin[nt]
                                        xcalckw = f32(float(ifix(max(min(size_kwh, size_max), size_min))))
                                    else:
                                        xcalckw = kw_menu
                                    xannualkwh = f32(f32(f32(f32(eff_ratio * poly) * xcalckw) * f32(8760.0)) * loss)
                                    xexcess = f32(xannualkwh - elec_avg)
                                    xvalesave_base, xvalesave_adj, xvalesave_norps = _value_of_savings(
                                        xannualkwh, xexcess, elec_avg, retail, sales, retail_adj, sales_adj,
                                        retail_norps, sales_norps)
                                    xbaseyrfuelcost = f32(0.0)
                                    xfuelinput = xwaterhtg = xspacehtg = xfuelprice = f32(0.0)
                                    xadjcost2 = xadjcost
                                else:
                                    # ---- Fuel-fired: fuel cells, engines, turbines, coal, oil, MSW, hydro, wood ----
                                    if fuel_type == 2:
                                        xfuelprice = f32(f32(f32(f32(sh["PNGCM"][idiv, y] * jp_ratio_num) / jp_den)
                                                             * t.xNGRateScalar[idiv, iniche, irate]))
                                    if fuel_type == 3:
                                        xfuelprice = f32(f32(sh["PDSCM"][idiv, y] * jp_ratio_num) / jp_den)
                                    if fuel_type == 6:
                                        coal = sh["PCLIN"][idiv, y] if idiv == 1 else sh["PCLCM"][idiv, y]
                                        xfuelprice = f32(f32(coal * jp_ratio_num) / jp_den)
                                    coal = sh["PCLIN"][idiv, y] if idiv == 1 else sh["PCLCM"][idiv, y]
                                    if fuel_type == 10:
                                        xfuelprice = f32(f32(coal * jp_ratio_num) / jp_den)
                                    if fuel_type == 11:
                                        xfuelprice = f32(0.0)
                                    if fuel_type == 9:
                                        xfuelprice = f32(f32(coal * jp_ratio_num) / jp_den)
                                    xwaterhtg = f32(f32(avg_sqft / f32(1000.0)) * sh["COMEUI"][idiv, ibld, 3, 2])
                                    xspacehtg = f32(f32(avg_sqft / f32(1000.0)) * sh["COMEUI"][idiv, ibld, 1, 2])
                                    if calyear > CM_COG_HST_YR + (BASEYR - 1):
                                        size_heat = f32(
                                            f32(f32(f32(f32(eleff / C_003412) * f32(xwaterhtg + xspacehtg)) * f32(1.00))
                                                / t.XWHRECOVERY[nt, nv])
                                            / f32(f32(t.XOPERHOURS[nt] * t.XAVAIL[nt, nv])
                                                  * f32(f32(1.0) - f32(eleff * loss))))
                                        size_kwh = f32(f32(elec_avg * f32(0.6)) / f32(f32(t.XOPERHOURS[nt] * t.XAVAIL[nt, nv]) * loss))
                                        size_max, size_min = t.xkwmax[nt], t.xkwMin[nt]
                                        xcalckw = f32(float(ifix(min(max(size_heat, size_kwh, size_min), size_max))))
                                        xadjcost2 = fexp(f32(flog(xadjcost) - f32(t.xScaleFac[nt] * flog(f32(xcalckw / kw_menu)))))
                                    else:
                                        xcalckw = kw_menu
                                        xadjcost2 = xadjcost
                                    xannualkwh = f32(f32(f32(t.XOPERHOURS[nt] * t.XAVAIL[nt, nv]) * xcalckw) * loss)
                                    xfuelinput = f32(f32(f32(f32(C_003412 * xcalckw) * t.XOPERHOURS[nt]) * t.XAVAIL[nt, nv]) / eleff)
                                    xwasteheat = f32(f32(xfuelinput - f32(C_003412 * xannualkwh)) * t.XWHRECOVERY[nt, nv])
                                    if xwasteheat > xwaterhtg:
                                        xtemp = f32(xwaterhtg + xspacehtg)
                                        if xwasteheat < xtemp:
                                            xspacehtg = f32(xwasteheat - xwaterhtg)
                                    else:
                                        xwaterhtg = xwasteheat
                                        xspacehtg = f32(0.0)
                                    xbaseyrfuelcost = f32(f32(f32(xfuelinput - xwaterhtg) - xspacehtg) * xfuelprice)
                                    xexcess = f32(xannualkwh - elec_avg)
                                    if xexcess < 0.0:
                                        xvalesave_base = f32(xannualkwh * retail_norps)
                                    else:
                                        xvalesave_base = f32(f32(xexcess * sales_norps) + f32(elec_avg * retail_norps))
                                    xvalesave_norps = xvalesave_base
                                    xvalesave_adj = f32(0.0)
                                    if fuel_type == 2:
                                        xvalesave_norps = xvalesave_base
                                        if xexcess < 0.0:
                                            own = f32(xannualkwh)
                                        else:
                                            own = f32(xannualkwh - xexcess)
                                        carbon = f32(xannualkwh * f32(f32(1.0) - f32(ceschp_const * f32(xfuelinput / xannualkwh))))
                                        credit = f32(carbon - f32(eprpstgt * own))
                                        xvalesave_base = f32(xvalesave_norps + f32(f32(f32(C_001 * eprpspr) * xrps) * credit))
                                        xvalesave_adj = f32(xvalesave_norps + f32(f32(f32(C_001 * eprpspr) * f32(1.0)) * credit))
                                        if xvalesave_base < xvalesave_norps:
                                            xvalesave_base = xvalesave_norps
                                        if xvalesave_adj < xvalesave_norps:
                                            xvalesave_base = xvalesave_norps

                                # ---- Cash flow, IRR and penetration (label 200) ----
                                xtemp = f32(0.0)
                                skip = (y < CM_COG_HST_YR and nt not in (1, 2, 8, 11)) or (
                                    y >= CM_COG_HST_YR and t.ISKIP[nt] == 0)
                                if not skip:
                                    xcalceqcost = f32(f32(xadjcost2 + t.XINSTCOST[nt, nv]) * xcalckw)
                                    xirr = _cash_flow({
                                        "xcalceqcost": xcalceqcost, "xcalckw": xcalckw,
                                        "xdownpaypct": t.XDOWNPAYPCT, "xintrate": t.XINTRATE, "xterm": t.XTERM,
                                        "xinflation": t.XINFLATION, "xtaxrate": t.XTAXRATE,
                                        "xmaintcst": t.XMAINTCST[nt, nv], "xtxcrpct": t.XTXCRPCT[nt, nv],
                                        "xtxcrmaxpersys": t.xTXCrMaxPerSys[nt, nv], "xeqlife": t.XEQLIFE[nt, nv],
                                        "xdegrad": t.XDEGRAD[nt, nv], "xtxlife": t.xtxlife[nt, nv],
                                        "xdep": t.xdep[nt, nv], "upira_appyr": int(sh["UPIRA_APPYR"]), "curiyr": y,
                                        "comtxcrpct_div": t.ComTxCrPct_Div[nv, idiv, nt],
                                        "iintervalyrs": t.iIntervalYrs[nt, nv], "xintervalcst": t.xIntervalCst[nt, nv],
                                        "nt": nt, "ifueltype": fuel_type,
                                        "xbaseyrfuelcost": xbaseyrfuelcost, "xvalesavebase": xvalesave_base,
                                        "xvalesavebaseadjrps": xvalesave_adj, "xvalesavebasenorps": xvalesave_norps,
                                        "irpsstartyear": int(t.iRPSStartYear[nt]),
                                        "irpsphaseoutyear": int(t.iRPSPhaseOutYear[nt]), "calyear": calyear,
                                        "inumyrsatrpsbaserate": int(t.iNumYrsatRPSBaseRate[nt, y]),
                                        "inumrpscredityrs": int(t.iNumRPSCreditYrs[nt, y])})
                                    if xirr > 0.0:
                                        payback = min(f32(29.0), f32(flog(f32(2.0)) / flog(f32(f32(1.0) + xirr))))
                                    else:
                                        payback = f32(29.0)
                                    xmaxpen = min(f32(0.9), f32(t.XPENPARM[nt] / payback))
                                    if payback > 10.0:
                                        xmaxpen = f32(0.01)
                                    if payback > 10.0 and nt == 11:
                                        xmaxpen = f32(0.0)
                                    start_yr = 10 if nt in (1, 2, 11) else 9 if nt == 8 else -20
                                    xb, xa, xc = t.XB[nt, idiv], t.XA[nt, idiv], t.XC[nt, idiv]
                                    expo = fexp(f32(f32(-xb) * f32(y - start_yr)))
                                    pen = f32(f32(xmaxpen * f32(xc * f32(f32(1.0) - expo))) / f32(f32(1.0) + f32(xa * expo)))
                                    cur[idiv, ibld, nt, iniche, irate, isize] = pen
                                    exog = t.XEXOGPEN
                                    if y >= KSTEOYR:
                                        per = f32(avg_sqft / ONE_E6)
                                        flr_prev = f32(sh["CMNewFloorSpace"][idiv, ibld, y - 1] + sh["SurvFloorTotal"][idiv, ibld, y - 1])
                                        xtemp = f32(f32(f32(pen * f32(sh["CMNewFloorSpace"][idiv, ibld, y] + sh["SurvFloorTotal"][idiv, ibld, y])) / per)
                                                    - f32(f32(prev[idiv, ibld, nt, iniche, irate, isize] * flr_prev) / per))
                                        xtemp = f32(xtemp + f32(f32(t.XBLDGSHARE[nt, ibld] * f32(exog[y, idiv, nt] - exog[y - 1, idiv, nt])) / xcalckw))
                                        floor_lim = f32(st.UNITS[y - 1, idiv, ibld, nt] * f32(f32(-1.0) / t.XEQLIFE[nt, nv]))
                                        if xtemp < floor_lim:
                                            xtemp = floor_lim
                                    else:
                                        xtemp = f32(f32(t.XBLDGSHARE[nt, ibld] * f32(exog[y, idiv, nt] - exog[y - 1, idiv, nt])) / xcalckw)
                                    if y <= SOLAR_BM_YR and nt == 1:
                                        xtemp = f32(f32(t.XBLDGSHARE[nt, ibld] * f32(exog[y, idiv, nt] - exog[y - 1, idiv, nt])) / xcalckw)
                                    xtemp = f32(f32(xtemp * cat_share) * sqft_share)
                                    xtemp = f32(f32(ifix(f32(f32(f32(100.0) * xtemp) + f32(0.5)))) / f32(100.0))
                                # label 350
                                if y <= CM_COG_HST_YR and nt not in (1, 2, 8, 11):
                                    xtemp = f32(f32(f32(st.UNITS[y, idiv, ibld, nt] - st.UNITS[y - 1, idiv, ibld, nt])
                                                    * cat_share) * sqft_share)
                                if f32(xtemp * xcalckw) < 0.0 and nt == 1:
                                    pass
                                else:
                                    xunits = f32(xunits + xtemp)
                                    xcapacity = f32(xcapacity + f32(xtemp * xcalckw))
                                    xtrills = f32(xtrills + f32(f32(f32(xtemp * xannualkwh) * f32(3412.0)) / ONE_E12))
                                    if xannualkwh > elec_avg:
                                        xtrillsownuse = f32(xtrillsownuse + f32(f32(f32(xtemp * elec_avg) * f32(3412.0)) / ONE_E12))
                                    else:
                                        xtrillsownuse = f32(xtrillsownuse + f32(f32(f32(xtemp * xannualkwh) * f32(3412.0)) / ONE_E12))
                                    xfuelusage = f32(xfuelusage + f32(f32(xtemp * xfuelinput) / ONE_E6))
                                    xhwbtu = f32(xhwbtu + f32(f32(xtemp * xwaterhtg) / ONE_E6))
                                    xshbtu = f32(xshbtu + f32(f32(xtemp * xspacehtg) / ONE_E6))
                                    xinvest = f32(xinvest + f32(f32(xtemp * xcalceqcost) / ONE_E6))
                                if nt == 11:
                                    st.WindTechPotentialMW[y, idiv] = f32(
                                        st.WindTechPotentialMW[y, idiv]
                                        + f32(f32(f32(f32(f32(f32(floor * ONE_E6) * cat_share) / avg_sqft) * sqft_share)
                                                  * xpct_wind) * f32(xcalckw / f32(1000.0))))
                    # ---- end of size, niche, rate loops: roll up to the building type ----
                    st.UNITS[y, idiv, ibld, nt] = f32(st.UNITS[y - 1, idiv, ibld, nt] + xunits)
                    st.TRILLS[y, idiv, ibld, nt] = f32(st.TRILLS[y - 1, idiv, ibld, nt] + xtrills)
                    st.capacity[y, idiv, ibld, nt] = f32(st.capacity[y - 1, idiv, ibld, nt] + xcapacity)
                    st.TRILLSOWNUSE[y, idiv, ibld, nt] = f32(st.TRILLSOWNUSE[y - 1, idiv, ibld, nt] + xtrillsownuse)
                    st.fuelusage[y, idiv, ibld, nt] = f32(st.fuelusage[y - 1, idiv, ibld, nt] + xfuelusage)
                    st.HWBTU[y, idiv, ibld, nt] = f32(st.HWBTU[y - 1, idiv, ibld, nt] + xhwbtu)
                    st.SHBTU[y, idiv, ibld, nt] = f32(st.SHBTU[y - 1, idiv, ibld, nt] + xshbtu)
                    st.INVEST[y, idiv, ibld, nt] = xinvest
                    for isize in range(1, 7):
                        st.xCumPenSqft[y, idiv, ibld, nt] = f32(
                            st.xCumPenSqft[y, idiv, ibld, nt]
                            + f32(f32(st.UNITS[y, idiv, ibld, nt] * t.cbecsFlspcCatShare[ibld, idiv, isize])
                                  * f32(t.cbecsAVGSQFT[ibld, idiv, isize] / ONE_E6)))
                    if nt == 1:
                        st.SolarPVInstalledMW[y, idiv] = f32(st.SolarPVInstalledMW[y, idiv] + f32(st.capacity[y, idiv, ibld, nt] / f32(1000.0)))
                        st.SolarPVUsedRoofArea[y, idiv, ibld] = f32(
                            st.SolarPVUsedRoofArea[y, idiv, ibld]
                            + f32(f32(f32(st.capacity[y, idiv, ibld, nt] * xsqftperkw) / ONE_E6) / f32(1.75)))
                        st.SolarPVTechPotentialMW[y, idiv] = f32(
                            st.SolarPVTechPotentialMW[y, idiv]
                            + f32(f32(f32(st.SolarPVAvailRoofArea[y, idiv, ibld] * ONE_E6) / f32(xsqftperkw * f32(1000.0))) / f32(1.75)))
                    if nt == 11:
                        st.WindInstalledMW[y, idiv] = f32(st.WindInstalledMW[y, idiv] + f32(st.capacity[y, idiv, ibld, nt] / f32(1000.0)))
                        st.WindBldgCount[y, idiv, ibld] = f32(st.WindBldgCount[y, idiv, ibld] + st.UNITS[y - 1, idiv, ibld, nt])
                    st.com111drensub[y, idiv, nt] = f32(
                        st.com111drensub[y, idiv, nt] + f32(st.INVEST[y, idiv, ibld, nt] * t.ComTxCrPct_Div[nv, idiv, nt]))
                    if y == CM_FIRST_YR:
                        st.INVEST[y, idiv, ibld, nt] = f32(0.0)
                # ---- RPS credit multipliers for PV and wind ----
                if nt in (1, 11):
                    added = st.xPVGenAdded if nt == 1 else st.xWindGenAdded
                    out_credit = st.CGCPVCOM if nt == 1 else st.CGCWNCOM
                    xtr = f32(0.0)
                    for ibld in range(1, t.NUMBLDG + 1):
                        xtr = f32(xtr + f32(st.TRILLS[y, idiv, ibld, nt] - st.TRILLS[y - 1, idiv, ibld, nt]))
                    added[idiv, y] = xtr
                    comp_credit = comp_gen = f32(0.0)
                    credit = f32(1.0)
                    for iyr in range(CM_FIRST_YR, y + 1):
                        icalyr = iyr + BASEYR - 1
                        bonus = f32(0.0)
                        comp_gen = f32(comp_gen + added[idiv, iyr])
                        if calyear < t.iRPSStartYear[nt] and icalyr >= t.iRPSGrandFatherYear[nt]:
                            bonus = f32(t.xRPS[nt, y] - f32(1.0))
                        elif y < iyr + t.iNumYrsatRPSBaseRate[nt, iyr] and calyear < t.iRPSPhaseOutYear[nt]:
                            bonus = f32(t.xRPS[nt, iyr] - f32(1.0))
                        elif y < iyr + t.iNumRPSCreditYrs[nt, iyr] and calyear < t.iRPSPhaseOutYear[nt]:
                            bonus = f32(t.xRPS[nt, y] - f32(1.0))
                        comp_credit = f32(comp_credit + f32(added[idiv, iyr] * f32(credit + bonus)))
                    if comp_gen > 0.0:
                        out_credit[idiv, y] = f32(comp_credit / comp_gen)

    _finish_year(t, st, cogen_el, y, eprpstgt)
    return st


def _value_of_savings(annual, excess, elec_avg, retail, sales, retail_adj, sales_adj, retail_norps, sales_norps):
    """Value of a year's output: all of it at the retail rate if it is all used on site, else the excess is sold."""
    if excess < 0.0:
        return f32(annual * retail), f32(annual * retail_adj), f32(annual * retail_norps)
    return (f32(f32(excess * sales) + f32(elec_avg * retail)),
            f32(f32(excess * sales_adj) + f32(elec_avg * retail_adj)),
            f32(f32(excess * sales_norps) + f32(elec_avg * retail_norps)))


def _finish_year(t: DgTables, st: DgState, cogen_el: np.ndarray, y: int, eprpstgt) -> None:
    """Totals the rest of NEMS reads: QCMDGSG, shipments, and generation, capacity and fuel use by fuel."""
    nd, nb, ntk = t.NUMDIV, t.NUMBLDG, t.NUMTECHS
    for idiv in range(1, nd + 1):
        for ibld in range(1, nb + 1):
            for nt in range(1, ntk + 1):
                st.QCMDGSG[y, idiv] = f32(f32(st.QCMDGSG[y, idiv] + st.TRILLS[y, idiv, ibld, nt])
                                          - st.TRILLSOWNUSE[y, idiv, ibld, nt])
    st.CFuelCell_MW[y] = st.CPV_MW[y] = st.CMicroTur_MW[y] = st.CWind_MW[y] = f32(0.0)
    G = f32(f32(1000.0) / f32(3.412))
    cap, own, tr, fu = st.capacity, st.TRILLSOWNUSE, st.TRILLS, st.fuelusage
    gen, capv, q = st.CGCOMMGEN, st.CGCOMMCAP, st.CGCOMMQ
    k1000 = f32(1000.0)
    for r in range(1, nd + 1):
        gen[r, y, 1:MNUMCGF + 1, 1:3] = 0.0
        q[r, y, 1:MNUMCGF + 1] = 0.0
        capv[r, y, 1:MNUMCGF + 1] = 0.0
        for b in range(1, nb + 1):
            def add_cap(k, techs):
                for tt in techs:
                    capv[r, y, k] = f32(capv[r, y, k] + f32(cap[y, r, b, tt] / k1000))
            add_cap(1, (4,))
            add_cap(2, (5,))
            for tt in (2, 3, 7, 8):                # gas: fuel cells, engines, turbines, microturbines
                capv[r, y, 3] = f32(capv[r, y, 3] + f32(cap[y, r, b, tt] / k1000))
            add_cap(6, (6,))
            add_cap(4, (9,))
            add_cap(7, (10,))
            add_cap(8, (1,))
            add_cap(11, (11,))
            st.CFuelCell_MW[y] = f32(st.CFuelCell_MW[y] + f32(cap[y, r, b, 2] / k1000))
            st.CPV_MW[y] = f32(st.CPV_MW[y] + f32(cap[y, r, b, 1] / k1000))
            st.CMicroTur_MW[y] = f32(st.CMicroTur_MW[y] + f32(cap[y, r, b, 8] / k1000))
            st.CWind_MW[y] = f32(st.CWind_MW[y] + f32(cap[y, r, b, 11] / k1000))
            # own use
            gen[r, y, 1, 2] = f32(gen[r, y, 1, 2] + f32(own[y, r, b, 4] * G))
            gen[r, y, 2, 2] = f32(gen[r, y, 2, 2] + f32(own[y, r, b, 5] * G))
            gen[r, y, 3, 2] = f32(gen[r, y, 3, 2] + f32(f32(f32(f32(own[y, r, b, 2] + own[y, r, b, 3]) + own[y, r, b, 7])
                                                          + own[y, r, b, 8]) * G))
            gen[r, y, 6, 2] = f32(gen[r, y, 6, 2] + f32(own[y, r, b, 6] * G))
            gen[r, y, 4, 2] = f32(gen[r, y, 4, 2] + f32(own[y, r, b, 9] * G))
            gen[r, y, 7, 2] = f32(gen[r, y, 7, 2] + f32(own[y, r, b, 10] * G))
            gen[r, y, 8, 2] = f32(gen[r, y, 8, 2] + f32(own[y, r, b, 1] * G))
            gen[r, y, 9, 2] = f32(gen[r, y, 9, 2] + f32(f32(cogen_el[r, b, 13, y] * f32(0.02)) * G))
            gen[r, y, 10, 2] = f32(gen[r, y, 10, 2] + f32(f32(cogen_el[r, b, 12, y] * f32(0.68)) * G))
            gen[r, y, 11, 2] = f32(gen[r, y, 11, 2] + f32(own[y, r, b, 11] * G))
            hist = y <= CM_COG_HST_YR
            gen[r, y, 1, 1] = f32(gen[r, y, 1, 1] + f32((cogen_el[r, b, 6, y] if hist else tr[y, r, b, 4]) * G))
            gen[r, y, 2, 1] = f32(gen[r, y, 2, 1] + f32((cogen_el[r, b, 3, y] if hist else tr[y, r, b, 5]) * G))
            gen[r, y, 3, 1] = f32(gen[r, y, 3, 1] + f32(f32(f32(f32(tr[y, r, b, 2] + tr[y, r, b, 3]) + tr[y, r, b, 7])
                                                          + tr[y, r, b, 8]) * G))
            gen[r, y, 6, 1] = f32(gen[r, y, 6, 1] + f32((cogen_el[r, b, 10, y] if hist else tr[y, r, b, 6]) * G))
            gen[r, y, 4, 1] = f32(gen[r, y, 4, 1] + f32((cogen_el[r, b, 11, y] if hist else tr[y, r, b, 9]) * G))
            gen[r, y, 7, 1] = f32(gen[r, y, 7, 1] + f32((cogen_el[r, b, 9, y] if hist else tr[y, r, b, 10]) * G))
            gen[r, y, 8, 1] = f32(gen[r, y, 8, 1] + f32(tr[y, r, b, 1] * G))
            gen[r, y, 9, 1] = f32(gen[r, y, 9, 1] + f32((cogen_el[r, b, 13, y] if hist else cogen_el[r, b, 13, CM_COG_HST_YR]) * G))
            gen[r, y, 10, 1] = f32(gen[r, y, 10, 1] + f32((cogen_el[r, b, 12, y] if hist else cogen_el[r, b, 12, CM_COG_HST_YR]) * G))
            gen[r, y, 11, 1] = f32(gen[r, y, 11, 1] + f32(tr[y, r, b, 11] * G))
            q[r, y, 1] = f32(q[r, y, 1] + fu[y, r, b, 4])
            q[r, y, 2] = f32(q[r, y, 2] + fu[y, r, b, 5])
            q[r, y, 3] = f32(f32(f32(f32(q[r, y, 3] + fu[y, r, b, 2]) + fu[y, r, b, 3]) + fu[y, r, b, 7]) + fu[y, r, b, 8])
            q[r, y, 6] = f32(q[r, y, 6] + fu[y, r, b, 6])
            q[r, y, 4] = f32(q[r, y, 4] + fu[y, r, b, 9])
            q[r, y, 7] = f32(q[r, y, 7] + fu[y, r, b, 10])
            q[r, y, 8] = f32(q[r, y, 8] + tr[y, r, b, 1])
            q[r, y, 11] = f32(q[r, y, 11] + tr[y, r, b, 11])
        for k in (1, 2, 3, 6, 4, 7, 8, 9, 10, 11):
            gen[r, y, k, 1] = f32(gen[r, y, k, 1] - gen[r, y, k, 2])
        st.KCHPCESGEN[r, y] = f32(0.0)
        gf = int(t.iRPSGrandFatherYear[3])
        if y + BASEYR - 1 >= gf:
            pre_own = gen[r, gf - BASEYR, 3, 2]
            pre_gen = f32(pre_own + gen[r, gf - BASEYR, 3, 1])
            pre_q = q[r, gf - BASEYR, 3]
            xgen = f32(f32(gen[r, y, 3, 1] + gen[r, y, 3, 2]) - pre_gen)
            xgenown = f32(gen[r, y, 3, 2] - pre_own)
            xfu = f32(q[r, y, 3] - pre_q)
            if xgen > 0.0:
                st.KCHPCESGEN[r, y] = f32(f32(xgen * f32(f32(1.0) - f32(f32(f32(53.06) / f32(0.82)) * f32(xfu / xgen))))
                                          - f32(eprpstgt * xgenown))
            if st.KCHPCESGEN[r, y] < 0.0:
                st.KCHPCESGEN[r, y] = f32(0.0)
            st.KCHPCESGEN[r, y] = f32(f32(f32(f32(st.KCHPCESGEN[r, y] + gen[r, y, 8, 1]) + gen[r, y, 8, 2])
                                          + gen[r, y, 11, 1]) + gen[r, y, 11, 2])
    st.KCHPCESGEN[MNUMCR, y] = f32(0.0)
    for r in range(1, nd + 1):
        st.KCHPCESGEN[MNUMCR, y] = f32(st.KCHPCESGEN[MNUMCR, y] + st.KCHPCESGEN[r, y])
    for f in range(1, MNUMCGF + 1):
        q[MNUMCR, y, f] = f32(0.0)
        gen[MNUMCR, y, f, 1] = f32(0.0)
        gen[MNUMCR, y, f, 2] = f32(0.0)
        capv[MNUMCR, y, f] = f32(0.0)
        for r in range(1, nd + 1):
            q[MNUMCR, y, f] = f32(q[MNUMCR, y, f] + q[r, y, f])
            gen[MNUMCR, y, f, 1] = f32(gen[MNUMCR, y, f, 1] + gen[r, y, f, 1])
            gen[MNUMCR, y, f, 2] = f32(gen[MNUMCR, y, f, 2] + gen[r, y, f, 2])
            capv[MNUMCR, y, f] = f32(capv[MNUMCR, y, f] + capv[r, y, f])
    st.CMUSCogen[1, y] = f32(q[MNUMCR, y, 1] / k1000)
    st.CMUSCogen[2, y] = f32(q[MNUMCR, y, 2] / k1000)
    st.CMUSCogen[3, y] = f32(q[MNUMCR, y, 3] / k1000)
    st.CMUSCogen[4, y] = f32(q[MNUMCR, y, 6] / k1000)

