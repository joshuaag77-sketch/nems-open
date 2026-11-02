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


def _vlog(x):
    """flog on an array: log in double, rounded to float32 (as Fortran's single-precision LOG here)."""
    return np.log(np.asarray(x, dtype=np.float64)).astype(f32)


def _vexp(x):
    return np.exp(np.asarray(x, dtype=np.float64)).astype(f32)


def _pymin(*xs):
    """Python's min, elementwise: keep the first value unless a later one is strictly smaller."""
    out = xs[0]
    for x in xs[1:]:
        out = np.where(x < out, x, out)
    return out


def _pymax(*xs):
    out = xs[0]
    for x in xs[1:]:
        out = np.where(x > out, x, out)
    return out


def _fix(x):
    """f32(float(ifix(x))): truncate toward zero."""
    return np.trunc(x).astype(f32)


def xnpv(cash, disc):
    """XNPV: net present value of a 30-year cash flow (entries 1..30), discounted back to year 1.
    Works on arrays of cash flows (one per niche) and one discount rate each."""
    npv = np.zeros_like(cash[1])
    d1 = f32(1.0) + disc
    for i in range(30, 1, -1):
        npv = (npv + cash[i]) / d1
    return npv + cash[1]


def _cash_flow(p: dict, ceq, kw, fuel_cost, vs_base, vs_adj, vs_norps, comtx):
    """30-year cash flow of one system in every niche and its internal rate of return.
    Scalars in `p` are the technology's; the arrays are per niche. Returns xIRR per niche."""
    xdownpaypct, xintrate, xterm, xinflation = p["xdownpaypct"], p["xintrate"], p["xterm"], p["xinflation"]
    xtaxrate = p["xtaxrate"]
    maint_base = p["xmaintcst"] * kw
    xtaxcreditpct = p["xtxcrpct"]
    xtaxcreditmax = p["xtxcrmaxpersys"]
    xlife, xdegradation, xtaxlife = p["xeqlife"], p["xdegrad"], p["xtxlife"]
    xdownpay = xdownpaypct * ceq
    xpayment = f32(xintrate / f32(f32(1.0) - fpow(f32(f32(1.0) + xintrate), f32(f32(-1.0) * xterm)))) * (ceq - xdownpay)

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

    tot_credit = ceq * xtaxcreditpct
    if xtaxcreditmax > 0.0:
        tot_credit = _pymin(tot_credit, xtaxcreditmax)
    tot_credit = tot_credit + ceq * comtx
    basis = ceq - tot_credit * f32(0.5)
    interval_to_use = int(p["iintervalyrs"])

    zero = np.zeros_like(ceq)
    xoutlay, xvalesave, xdepr, xmaintcost, xintamt, xfuelcost, xtaxcredit, net = ([zero] * 31 for _ in range(8))
    xoutlay = list(xoutlay); xvalesave = list(xvalesave); xdepr = list(xdepr); xmaintcost = list(xmaintcost)
    xintamt = list(xintamt); xfuelcost = list(xfuelcost); xtaxcredit = list(xtaxcredit); net = list(net)
    xoutlay[1] = xdownpaypct * ceq
    loanbal = ceq * (f32(1.0) - xdownpaypct)
    net[1] = -xoutlay[1]
    carry = np.ones(ceq.shape, dtype=bool)
    claimed = zero
    infl1 = f32(f32(1.0) + xinflation)
    deg1 = f32(f32(1.0) - xdegradation)
    start, phase_out = p["irpsstartyear"], p["irpsphaseoutyear"]
    rps_tech = p["nt"] == 1 or p["nt"] == 11 or p["ifueltype"] == 2
    for iyr in range(2, 31):
        if iyr >= 3:
            credit = _pymax(_pymin(tot_credit - claimed, f32(25000.0)), f32(0.0))
            xtaxcredit[iyr] = np.where(carry, credit, f32(0.0))
            claimed = np.where(carry, claimed + credit, claimed)
            carry = carry & (tot_credit > claimed)
        in_term = f32(iyr) <= f32(xterm + f32(1.0))
        if in_term:
            xoutlay[iyr] = xpayment
        xintamt[iyr] = loanbal * xintrate
        prin = xpayment - xintamt[iyr] if in_term else zero
        loanbal = loanbal - prin
        if f32(iyr) <= f32(xtaxlife + f32(1.0)):
            depr = ((basis * p["xdep"]) / f32(100.0)) / xtaxlife
            straight = basis / f32(f32(xtaxlife - f32(iyr)) + f32(2.0))
            xdepr[iyr] = np.where(depr <= straight, straight, depr)
            basis = basis - xdepr[iyr]
        life_ok = f32(iyr) <= f32(xlife + f32(1.0))
        grow, decay = ipow(infl1, iyr - 2), ipow(deg1, iyr - 2)
        if life_ok:
            xfuelcost[iyr] = fuel_cost * grow
        if iyr > 2 and (iyr - 2) % interval_to_use == 0 and iyr != 29 and iyr != 30:
            if life_ok:
                xmaintcost[iyr] = (maint_base + p["xintervalcst"] * kw) * grow
            interval_to_use = 2 * interval_to_use + iyr
        elif life_ok:
            xmaintcost[iyr] = maint_base * grow
        if life_ok:
            vs = vs_base
            if rps_tech:
                if cal + iyr - 1 > phase_out:
                    vs = vs_norps
                if cal >= start and iyr > p["inumyrsatrpsbaserate"]:
                    vs = vs_adj
                if cal >= start and iyr > p["inumrpscredityrs"]:
                    vs = vs_norps
                if cal < start:
                    vs = vs_norps
            xvalesave[iyr] = (vs * grow) * decay
        xtaxdeduct = xtaxrate * (((xintamt[iyr - 1] + xmaintcost[iyr - 1]) + xdepr[iyr - 1])
                                 + (xfuelcost[iyr - 1] - xvalesave[iyr - 1])) + xtaxcredit[iyr]
        net[iyr] = (((-xoutlay[iyr]) - xfuelcost[iyr]) - xmaintcost[iyr]) + xtaxdeduct + xvalesave[iyr]

    # IRR by false position between 0.01% and 30%, per niche.
    xirr = zero.copy()
    npv_l = xnpv(net, f32(0.0001))
    act = np.nonzero(npv_l > 0)[0]
    if act.size == 0:
        return xirr
    cash = [None] + [c[act] for c in net[1:]]
    npv_l = npv_l[act]
    disc_l = np.full(act.size, f32(0.0001), dtype=f32)
    disc_u = np.full(act.size, f32(0.3), dtype=f32)
    npv_u = xnpv(cash, disc_u)
    cur = np.zeros(act.size, dtype=f32)
    for _ in range(100):
        prev = cur
        cur = disc_l - (npv_l * (disc_u - disc_l)) / (npv_u - npv_l)
        npv_new = xnpv(cash, cur)
        xirr[act] = cur
        done = (np.abs(npv_new) < 1.0) | (np.abs(prev - cur) < f32(0.0005))
        keep = np.nonzero(~done)[0]
        if keep.size == 0:
            break
        if keep.size < act.size:
            act, cash = act[keep], [None] + [c[keep] for c in cash[1:]]
            npv_l, npv_u, disc_l, disc_u = npv_l[keep], npv_u[keep], disc_l[keep], disc_u[keep]
            cur, npv_new = cur[keep], npv_new[keep]
        up = npv_new > 0.0
        npv_l = np.where(up, npv_new, npv_l)
        disc_l = np.where(up, cur, disc_l)
        npv_u = np.where(up, npv_u, npv_new)
        disc_u = np.where(up, disc_u, cur)
    return xirr


def _value_of_savings(annual, excess, elec_avg, retail, sales):
    """Value of a year's output: all of it at the retail rate if it is all used on site, else the excess is sold."""
    return np.where(excess < 0.0, annual * retail, excess * sales + elec_avg * retail)


def _seq_sum(start, terms, mask):
    """start + terms[..., 0] + terms[..., 1] + ..., in float32 and in that order, skipping masked-out terms
    (what the Fortran's running sums do). Sums over the last axis."""
    t = np.where(mask, terms, f32(0.0)).astype(f32)
    t = np.concatenate([np.broadcast_to(start, t.shape[:-1])[..., None].astype(f32), t], axis=-1)
    return np.add.accumulate(t, axis=-1)[..., -1]


def distgen(t: DgTables, st: DgState, shared: dict, cogen_el: np.ndarray, y: int) -> DgState:
    """One call of CDISTGEN for year index y (after its first-call reads). Changes `st` in place.

    `shared` holds what other modules supply, as plain 1-based arrays: PELME, PELCM, PELCMOUT, PNGCM,
    PDSCM, PCLIN, PCLCM [div, y] (PELCMOUT [div, y, 2]), MC_JPGDP (dict by index, includes -2),
    EPRPSPR, EPRPSTGT [y], UPIRA_APPYR, SurvFloorTotal and CMNewFloorSpace [div, bld, y],
    COMEUI [div, bld, s, f], RPV_MW, UPV_MW, RFuelCell_MW, RWind_MW, RMicroTur_MW [y].

    The Fortran loops over technology, vintage, division, building type, and then every niche
    (building size, climate niche, rate level). Here each technology and vintage is one block:
    every niche of every division and building type is computed at once as float32 arrays,
    with the same operations in the same order, and the running sums are taken in the
    Fortran's loop order, so the results are identical.
    """
    assert y >= CM_FIRST_YR
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
    jp_num = sh["MC_JPGDP"][t.iGenCapCostYr - BASEYR + 1]
    jp_den = sh["MC_JPGDP"][-2]
    eprpspr, eprpstgt = sh["EPRPSPR"][y], sh["EPRPSTGT"][y]
    ceschp_const = f32(f32(53.06) / f32(0.82))
    xpct_wind = t.xpctWindSuitable

    # The niche grid: [div, bld, size, niche, rate], 0-based, broadcast from each table's own axes.
    D, B, NN = t.NUMDIV, t.NUMBLDG, int(t.NumPVNiche[1:t.NUMDIV + 1].max())
    g = lambda a: a.astype(f32)
    DNR = lambda a: g(a[1:D + 1, 1:NN + 1, 1:11])[:, None, None, :, :]
    BDS = lambda a: g(a[1:B + 1, 1:D + 1, 1:7]).transpose(1, 0, 2)[:, :, :, None, None]
    Dv = lambda a: g(a[1:D + 1])[:, None, None, None, None]
    DBv = lambda a: g(a)[:, :, None, None, None]
    rate_sc = DNR(t.xRateScalar)
    sqft_share = DNR(t.xSqftShare)
    cat_share = BDS(t.cbecsFlspcCatShare)
    avg_sqft = BDS(t.cbecsAVGSQFT)
    elec_avg = BDS(t.xelecavgkwh)
    roof_ratio = g(t.xRoofAreatoSqftRatio[1:D + 1, 1:B + 1, 1:NN + 1, 1:11])[:, :, None, :, :]
    pct_pv = g(t.xpctPVSuitable[1:7])[None, None, :, None, None]
    niche_ok = (np.arange(1, NN + 1)[None, :] <= t.NumPVNiche[1:D + 1, None])[:, None, None, :, None]
    valid = np.broadcast_to((cat_share != 0.0) & niche_ok, (D, B, 6, NN, 10))
    shape = valid.shape
    flr = g(sh["SurvFloorTotal"][1:D + 1, 1:B + 1, y] + sh["CMNewFloorSpace"][1:D + 1, 1:B + 1, y])
    flr_prev = g(sh["CMNewFloorSpace"][1:D + 1, 1:B + 1, y - 1] + sh["SurvFloorTotal"][1:D + 1, 1:B + 1, y - 1])
    pelme, pelcm = Dv(sh["PELME"][:, y]), Dv(sh["PELCM"][:, y])
    pelcmout = Dv(sh["PELCMOUT"][:, y, 2])
    sales_norps = ((pelme * C_003412) * jp_num) / jp_den
    retail_norps_cm = (((pelcm * rate_sc) * C_003412) * jp_num) / jp_den
    coal = Dv(sh["PCLCM"][:, y]).copy()
    coal[0] = sh["PCLIN"][1, y]

    grid = dict(valid=valid, shape=shape, rate_sc=rate_sc, sqft_share=sqft_share, cat_share=cat_share,
                avg_sqft=avg_sqft, elec_avg=elec_avg, roof_ratio=roof_ratio, pct_pv=pct_pv, flr=flr,
                flr_prev=flr_prev, pelme=pelme, pelcm=pelcm, pelcmout=pelcmout, sales_norps=sales_norps,
                retail_norps_cm=retail_norps_cm, coal=coal, jp_num=jp_num, jp_den=jp_den, eprpspr=eprpspr,
                eprpstgt=eprpstgt, ceschp_const=ceschp_const, xpct_wind=xpct_wind, DNR=DNR, Dv=Dv, DBv=DBv)
    last_ceq = f32(0.0)    # xCalcEqCost: a skipped block keeps the last one computed (only used times 0)
    xsqftperkw = f32(0.0)  # carried the same way
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        for nt in range(1, t.NUMTECHS + 1):
            for nv in range(1, t.NVINT + 1):
                if t.IFIRSTYR[nt, nv] > calyear or t.ILASTYR[nt, nv] < calyear:
                    continue
                last_ceq, xsqftperkw = _block(t, st, sh, nt, nv, y, calyear, prev, cur, grid, last_ceq,
                                              xsqftperkw)

    _finish_year(t, st, cogen_el, y, eprpstgt)
    return st


def _learned_cost(t, st, sh, nt, nv, y):
    """Capital cost after learning from cumulative shipments (commercial plus residential, plus utility for PV)."""
    name, xcapcost = t.AEQUIPNAME[nt, nv], t.XCAPCOST[nt, nv]
    if name == "Fuel_Cell":
        cumship = f32(st.CFuelCell_MW[y - 1] + sh["RFuelCell_MW"][y - 1])
    elif name == "Solar_PV":
        if t.GlobalLearn:
            cumship = f32(f32(st.CPV_MW[y - 1] + sh["RPV_MW"][y - 1]) + sh["UPV_MW"][y - 1])
        else:
            cumship = f32(st.CPV_MW[y - 1] + sh["RPV_MW"][y - 1])
    elif name == "Wind":
        cumship = f32(st.CWind_MW[y - 1] + sh["RWind_MW"][y - 1])
    elif name == "Micro_Tur":
        cumship = f32(st.CMicroTur_MW[y - 1] + sh["RMicroTur_MW"][y - 1])
    else:
        return xcapcost
    return learn_cost(xcapcost, t.XBeta[nt], t.Xc0[nt], cumship)


def _block(t, st, sh, nt, nv, y, calyear, prev, cur, v, last_ceq, xsqftperkw):
    """One technology and vintage, every niche at once (the inner loops of CDISTGEN, labels 100-350)."""
    D, B = t.NUMDIV, t.NUMBLDG
    valid, shape = v["valid"], v["shape"]
    rate_sc, sqft_share, cat_share = v["rate_sc"], v["sqft_share"], v["cat_share"]
    avg_sqft, elec_avg, flr = v["avg_sqft"], v["elec_avg"], v["flr"]
    jp_num, jp_den, eprpspr, eprpstgt = v["jp_num"], v["jp_den"], v["eprpspr"], v["eprpstgt"]
    sales_norps, retail_norps = v["sales_norps"], v["retail_norps_cm"]
    xadjcost = _learned_cost(t, st, sh, nt, nv, y)
    fuel_type = int(t.IFUELTYPE[nt])
    xrps = t.xRPS[nt, y]
    eleff, loss, kw_menu = t.XELEFF[nt, nv], t.XLOSSFAC[nt, nv], t.XKW[nt, nv]
    rps = f32(f32(C_001 * eprpspr) * xrps)
    rps1 = f32(f32(C_001 * eprpspr) * f32(1.0))
    zero = np.zeros(shape, dtype=f32)
    full = lambda a: np.broadcast_to(a, shape)
    fuelinput = water = space = base_fuel = zero
    flr5 = flr[:, :, None, None, None]

    if fuel_type == 0 and nt != 11:
        # ---- Solar PV ----
        pelme, pelcmout = v["pelme"], v["pelcmout"]
        retail = ((((pelcmout * rate_sc) * C_003412) + rps) * jp_num) / jp_den
        sales = (((pelme * C_003412) + rps) * jp_num) / jp_den
        retail_norps = (((pelcmout * rate_sc) * C_003412) * jp_num) / jp_den
        sales_adj = (((pelme * C_003412) + rps1) * jp_num) / jp_den
        retail_adj = ((((pelcmout * rate_sc) * C_003412) + rps1) * jp_num) / jp_den
        if calyear < t.iRPSStartYear[nt]:
            retail, sales = retail_norps, sales_norps
        area = (((flr5 * cat_share) * sqft_share) * v["roof_ratio"]) * v["pct_pv"]
        st.SolarPVAvailRoofArea[y, 1:D + 1, 1:B + 1] = _seq_sum(
            st.SolarPVAvailRoofArea[y, 1:D + 1, 1:B + 1], full(area).reshape(D, B, -1), valid.reshape(D, B, -1))
        xsqftperkw = f32(f32(f32(77.0) * f32(0.14)) / eleff)
        ins = v["DNR"](t.xSolarInsolation)
        solarins = (f32(-1.0686) + f32(1.4421) * ins) - f32(0.0645) * (ins * ins)
        size_roof = (((avg_sqft * v["roof_ratio"]) * v["pct_pv"]) / xsqftperkw) / f32(1.75)
        size_kwh = elec_avg / (((((eleff * solarins) * f32(365.25)) / f32(10.8)) * xsqftperkw) * loss)
        kw = _fix(_pymax(_pymin(size_roof, size_kwh, t.xkwmax[nt]), t.xkwMin[nt]))
        adjcost2 = _vexp(flog(xadjcost) - t.xScaleFac[nt] * _vlog(kw / kw_menu))
        annual = (((((eleff * solarins) * f32(365.25)) / f32(10.8)) * xsqftperkw) * kw) * loss
        excess = annual - elec_avg
        vs_base = _value_of_savings(annual, excess, elec_avg, retail, sales)
        vs_adj = _value_of_savings(annual, excess, elec_avg, retail_adj, sales_adj)
        vs_norps = _value_of_savings(annual, excess, elec_avg, retail_norps, sales_norps)
    elif fuel_type == 0:
        # ---- Wind ----
        pelme, pelcm, pelcmout = v["pelme"], v["pelcm"], v["pelcmout"]
        retail = ((((pelcm * rate_sc) * C_003412) + rps) * jp_num) / jp_den
        sales = (((pelme * C_003412) + rps) * jp_num) / jp_den
        sales_adj = (((pelme * C_003412) + rps1) * jp_num) / jp_den
        retail_adj = ((((pelcmout * rate_sc) * C_003412) + rps1) * jp_num) / jp_den
        if calyear < t.iRPSStartYear[nt]:
            retail, sales = retail_norps, sales_norps
        avail = ((flr5 * cat_share) * sqft_share) * v["xpct_wind"]
        st.WindAvailFS[y, 1:D + 1, 1:B + 1] = _seq_sum(
            st.WindAvailFS[y, 1:D + 1, 1:B + 1], full(avail).reshape(D, B, -1), valid.reshape(D, B, -1))
        mps = v["DNR"](t.xWindSpeed)
        poly = ((f32(0.0645) - f32(0.0670) * mps) + f32(0.0210) * (mps * mps)) - f32(0.0011) * ((mps * mps) * mps)
        eff_ratio = f32(eleff / t.XELEFF[nt, 1])
        size_kwh = elec_avg / (((eff_ratio * poly) * f32(8760.0)) * loss)
        kw = _fix(_pymax(_pymin(size_kwh, t.xkwmax[nt]), t.xkwMin[nt]))
        annual = (((eff_ratio * poly) * kw) * f32(8760.0)) * loss
        excess = annual - elec_avg
        vs_base = _value_of_savings(annual, excess, elec_avg, retail, sales)
        vs_adj = _value_of_savings(annual, excess, elec_avg, retail_adj, sales_adj)
        vs_norps = _value_of_savings(annual, excess, elec_avg, retail_norps, sales_norps)
        adjcost2 = full(xadjcost)
    else:
        # ---- Fuel-fired: fuel cells, engines, turbines, coal, oil, MSW, hydro, wood ----
        Dv = v["Dv"]
        if fuel_type == 2:
            price = (((Dv(sh["PNGCM"][:, y]) * jp_num) / jp_den) * v["DNR"](t.xNGRateScalar))
        elif fuel_type == 3:
            price = (Dv(sh["PDSCM"][:, y]) * jp_num) / jp_den
        elif fuel_type in (6, 9, 10):
            price = (v["coal"] * jp_num) / jp_den
        elif fuel_type == 11:
            price = f32(0.0)
        else:
            raise NotImplementedError(f"CDISTGEN fuel type {fuel_type}")
        eui = v["DBv"](sh["COMEUI"][1:D + 1, 1:B + 1, 3, 2]), v["DBv"](sh["COMEUI"][1:D + 1, 1:B + 1, 1, 2])
        water = (avg_sqft / f32(1000.0)) * eui[0]
        space = (avg_sqft / f32(1000.0)) * eui[1]
        oph, av, whr = t.XOPERHOURS[nt], t.XAVAIL[nt, nv], t.XWHRECOVERY[nt, nv]
        if calyear > CM_COG_HST_YR + (BASEYR - 1):
            size_heat = ((((eleff / C_003412) * (water + space)) * f32(1.00)) / whr) / (
                f32(oph * av) * f32(f32(1.0) - f32(eleff * loss)))
            size_kwh = (elec_avg * f32(0.6)) / f32(f32(oph * av) * loss)
            kw = _fix(_pymin(_pymax(size_heat, size_kwh, t.xkwMin[nt]), t.xkwmax[nt]))
            adjcost2 = _vexp(flog(xadjcost) - t.xScaleFac[nt] * _vlog(kw / kw_menu))
        else:
            kw = full(kw_menu)
            adjcost2 = full(xadjcost)
        annual = (f32(oph * av) * kw) * loss
        fuelinput = (((C_003412 * kw) * oph) * av) / eleff
        waste = (fuelinput - C_003412 * annual) * whr
        over = waste > water
        space = np.where(over, np.where(waste < water + space, waste - water, space), f32(0.0))
        water = np.where(over, water, waste)
        base_fuel = ((fuelinput - water) - space) * price
        excess = annual - elec_avg
        vs_base = np.where(excess < 0.0, annual * retail_norps, excess * sales_norps + elec_avg * retail_norps)
        vs_norps = vs_base
        vs_adj = zero
        if fuel_type == 2:
            own = np.where(excess < 0.0, annual, annual - excess)
            carbon = annual * (f32(1.0) - ceschp_const * (fuelinput / annual)) if False else \
                annual * (f32(1.0) - v["ceschp_const"] * (fuelinput / annual))
            credit = carbon - eprpstgt * own
            base = vs_norps + rps * credit
            vs_adj = vs_norps + rps1 * credit
            base = np.where(base < vs_norps, vs_norps, base)
            vs_base = np.where(vs_adj < vs_norps, vs_norps, base)  # EIA tests the adjusted value, resets the base

    kw, annual = full(kw), full(annual)
    elec5 = full(elec_avg)
    cells = np.nonzero(valid.reshape(-1))[0]  # in the Fortran's loop order

    # ---- Cash flow, IRR and penetration (label 200) ----
    skip = (y < CM_COG_HST_YR and nt not in (1, 2, 8, 11)) or (y >= CM_COG_HST_YR and t.ISKIP[nt] == 0)
    xtemp = zero
    if skip:
        ceq = full(last_ceq)
    else:
        ceq = full((adjcost2 + t.XINSTCOST[nt, nv]) * kw)
        if cells.size:
            last_ceq = ceq.reshape(-1)[cells[-1]]
        pick = lambda a: full(a).reshape(-1)[cells]
        comtx = full(v["Dv"](t.ComTxCrPct_Div[nv, :, nt]))
        xirr_c = _cash_flow({
            "xdownpaypct": t.XDOWNPAYPCT, "xintrate": t.XINTRATE, "xterm": t.XTERM,
            "xinflation": t.XINFLATION, "xtaxrate": t.XTAXRATE,
            "xmaintcst": t.XMAINTCST[nt, nv], "xtxcrpct": t.XTXCRPCT[nt, nv],
            "xtxcrmaxpersys": t.xTXCrMaxPerSys[nt, nv], "xeqlife": t.XEQLIFE[nt, nv],
            "xdegrad": t.XDEGRAD[nt, nv], "xtxlife": t.xtxlife[nt, nv],
            "xdep": t.xdep[nt, nv], "upira_appyr": int(sh["UPIRA_APPYR"]), "curiyr": y,
            "iintervalyrs": t.iIntervalYrs[nt, nv], "xintervalcst": t.xIntervalCst[nt, nv],
            "nt": nt, "ifueltype": fuel_type,
            "irpsstartyear": int(t.iRPSStartYear[nt]), "irpsphaseoutyear": int(t.iRPSPhaseOutYear[nt]),
            "inumyrsatrpsbaserate": int(t.iNumYrsatRPSBaseRate[nt, y]),
            "inumrpscredityrs": int(t.iNumRPSCreditYrs[nt, y])},
            pick(ceq), pick(kw), pick(base_fuel), pick(vs_base), pick(vs_adj), pick(vs_norps), pick(comtx))
        xirr = np.zeros(valid.size, dtype=f32)
        xirr[cells] = xirr_c
        xirr = xirr.reshape(shape)
        payback = np.where(xirr > 0.0, _pymin(f32(29.0), flog(f32(2.0)) / _vlog(f32(1.0) + xirr)), f32(29.0))
        maxpen = _pymin(f32(0.9), t.XPENPARM[nt] / payback)
        maxpen = np.where(payback > 10.0, f32(0.0) if nt == 11 else f32(0.01), maxpen)
        start_yr = 10 if nt in (1, 2, 11) else 9 if nt == 8 else -20
        xb, xa, xc = (v["Dv"](a[nt, :]) for a in (t.XB, t.XA, t.XC))
        expo = _vexp(-xb * f32(y - start_yr))
        pen = (maxpen * (xc * (f32(1.0) - expo))) / (f32(1.0) + xa * expo)
        # cur is [div, bld, nt, niche, rate, size]; the grid is [div, bld, size, niche, rate]
        tgt = cur[1:D + 1, 1:B + 1, nt, 1:pen.shape[3] + 1, 1:11, 1:7].transpose(0, 1, 4, 2, 3)
        tgt[valid] = pen[valid]
        exog = t.XEXOGPEN
        dexog = v["Dv"](exog[y, :, nt] - exog[y - 1, :, nt])
        bshare = g5b(t.XBLDGSHARE[nt, 1:B + 1])
        exog_term = (bshare * dexog) / kw
        if y >= KSTEOYR:
            per = avg_sqft / ONE_E6
            pen_prev = prev[1:D + 1, 1:B + 1, nt, 1:pen.shape[3] + 1, 1:11, 1:7].transpose(0, 1, 4, 2, 3)
            fp = v["flr_prev"][:, :, None, None, None]
            xtemp = ((pen * flr5) / per) - ((pen_prev * fp) / per)
            xtemp = xtemp + exog_term
            floor_lim = st.UNITS[y - 1, 1:D + 1, 1:B + 1, nt][:, :, None, None, None] * f32(f32(-1.0) / t.XEQLIFE[nt, nv])
            xtemp = np.where(xtemp < floor_lim, floor_lim, xtemp)
        else:
            xtemp = exog_term
        if y <= SOLAR_BM_YR and nt == 1:
            xtemp = exog_term
        xtemp = (xtemp * cat_share) * sqft_share
        xtemp = _fix((f32(100.0) * xtemp) + f32(0.5)) / f32(100.0)
    # label 350
    if y <= CM_COG_HST_YR and nt not in (1, 2, 8, 11):
        du = (st.UNITS[y, 1:D + 1, 1:B + 1, nt] - st.UNITS[y - 1, 1:D + 1, 1:B + 1, nt])[:, :, None, None, None]
        xtemp = (du * cat_share) * sqft_share
    xtemp = full(xtemp)
    ok = valid & ~((xtemp * kw < 0.0) & (nt == 1))
    flat = lambda a: full(a).reshape(D, B, -1)
    okf = ok.reshape(D, B, -1)
    acc = lambda term: _seq_sum(f32(0.0), flat(term), okf)
    tr = ((xtemp * annual) * f32(3412.0)) / ONE_E12
    sums = {
        "xunits": acc(xtemp), "xcapacity": acc(xtemp * kw), "xtrills": acc(tr),
        "xtrillsownuse": acc(np.where(annual > elec5, ((xtemp * elec5) * f32(3412.0)) / ONE_E12, tr)),
        "xfuelusage": acc((xtemp * fuelinput) / ONE_E6), "xhwbtu": acc((xtemp * water) / ONE_E6),
        "xshbtu": acc((xtemp * space) / ONE_E6), "xinvest": acc((xtemp * ceq) / ONE_E6)}
    if nt == 11:
        term = (((((flr5 * ONE_E6) * cat_share) / avg_sqft) * sqft_share) * v["xpct_wind"]) * (kw / f32(1000.0))
        st.WindTechPotentialMW[y, 1:D + 1] = _seq_sum(st.WindTechPotentialMW[y, 1:D + 1], full(term).reshape(D, -1),
                                                      valid.reshape(D, -1))
    _roll_up(t, st, nt, nv, y, sums, xsqftperkw)
    return last_ceq, xsqftperkw


def g5b(a):
    """A per-building-type vector on the niche grid."""
    return a.astype(f32)[None, :, None, None, None]


def _roll_up(t, st, nt, nv, y, s, xsqftperkw):
    """End of the niche loops: add this year's units to last year's stock, by division and building type."""
    D, B = t.NUMDIV, t.NUMBLDG
    ix = (y, slice(1, D + 1), slice(1, B + 1), nt)
    px = (y - 1, slice(1, D + 1), slice(1, B + 1), nt)
    st.UNITS[ix] = st.UNITS[px] + s["xunits"]
    st.TRILLS[ix] = st.TRILLS[px] + s["xtrills"]
    st.capacity[ix] = st.capacity[px] + s["xcapacity"]
    st.TRILLSOWNUSE[ix] = st.TRILLSOWNUSE[px] + s["xtrillsownuse"]
    st.fuelusage[ix] = st.fuelusage[px] + s["xfuelusage"]
    st.HWBTU[ix] = st.HWBTU[px] + s["xhwbtu"]
    st.SHBTU[ix] = st.SHBTU[px] + s["xshbtu"]
    st.INVEST[ix] = s["xinvest"]
    units = st.UNITS[ix]
    cum = st.xCumPenSqft[ix]
    for isize in range(1, 7):
        cum = cum + (units * t.cbecsFlspcCatShare[1:B + 1, 1:D + 1, isize].T.astype(f32)) * (
            t.cbecsAVGSQFT[1:B + 1, 1:D + 1, isize].T.astype(f32) / ONE_E6)
    st.xCumPenSqft[ix] = cum
    cap = st.capacity[ix]
    if nt == 1:
        st.SolarPVInstalledMW[y, 1:D + 1] = _seq_sum(st.SolarPVInstalledMW[y, 1:D + 1], cap / f32(1000.0), True)
        st.SolarPVUsedRoofArea[y, 1:D + 1, 1:B + 1] = st.SolarPVUsedRoofArea[y, 1:D + 1, 1:B + 1] + (
            ((cap * xsqftperkw) / ONE_E6) / f32(1.75))
        st.SolarPVTechPotentialMW[y, 1:D + 1] = _seq_sum(
            st.SolarPVTechPotentialMW[y, 1:D + 1],
            ((st.SolarPVAvailRoofArea[y, 1:D + 1, 1:B + 1] * ONE_E6) / f32(xsqftperkw * f32(1000.0))) / f32(1.75), True)
    if nt == 11:
        st.WindInstalledMW[y, 1:D + 1] = _seq_sum(st.WindInstalledMW[y, 1:D + 1], cap / f32(1000.0), True)
        st.WindBldgCount[y, 1:D + 1, 1:B + 1] = st.WindBldgCount[y, 1:D + 1, 1:B + 1] + st.UNITS[px]
    st.com111drensub[y, 1:D + 1, nt] = _seq_sum(
        st.com111drensub[y, 1:D + 1, nt], st.INVEST[ix] * t.ComTxCrPct_Div[nv, 1:D + 1, nt][:, None].astype(f32), True)
    if y == CM_FIRST_YR:
        st.INVEST[ix] = f32(0.0)
    # ---- RPS credit multipliers for PV and wind ----
    if nt in (1, 11):
        calyear = y + BASEYR - 1
        added = st.xPVGenAdded if nt == 1 else st.xWindGenAdded
        out_credit = st.CGCPVCOM if nt == 1 else st.CGCWNCOM
        added[1:D + 1, y] = _seq_sum(f32(0.0), st.TRILLS[ix] - st.TRILLS[px], True)
        for idiv in range(1, D + 1):
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

