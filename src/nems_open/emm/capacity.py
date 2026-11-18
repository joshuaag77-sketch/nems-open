"""Capacity expansion: which plants get built and retired each year, shaped like ECP.

A myopic loop. Each year starts from last year's capacity, adds the units the plant file already
dates for that year and takes off the ones it dates to retire, then solves one linear program
that picks the rest:

- builds of gas combined cycle, gas combined cycle with CCS, gas turbines, wind, solar and
  batteries, at ECP's overnight costs (UPOVR) times the regional multipliers, annualized, less
  the year's tax credits (SUBSIDY sheet);
- economic retirements of coal, steam, turbines and combined cycle, which save fixed O&M;
- CCS retrofits of large, efficient coal units, which earn the 45Q credit;
- the dispatch of the whole fleet in 36 typical days of 8 three-hour blocks, with trade over the
  regional links, so a plant's value comes from the energy it displaces.

A national reserve margin keeps enough firm capacity for the peak. From 2032 coal without CCS has
to retire (EIA's reference case drops 60 GW of coal that year; the rule behind it is the
power-plant carbon rule, E111D). Everything in the demand and fuel side comes from the reference
run: net load from sales, fuel prices from the supply modules.

Money is 1987 dollars. Power is GW, energy TWh.
"""

from dataclasses import dataclass, field, replace

import linopy
import numpy as np
import pandas as pd
import xarray as xr

from nems_open.emm import capacity_credit, db, dispatch, history, load, plants, regions, retire_groups, technology
from nems_open.paths import INPUT
from nems_open.xlsx_ranges import named_ranges

NUM_R = regions.NUM_EMM
START_YEAR = 2025
FIRST_UNPLANNED_YEAR = 2027      # EIA's first model-chosen builds come online in 2027 (ECP plans about three years ahead)
RULE_YEAR = 2032                 # coal without CCS must retire from this year
RETROFIT_LIMIT_GW = 3.0          # national CCS retrofits per year (UPCQMAX in ecpdaty.xlsx)
RETROFIT_MIN_MW = 500.0          # smallest unit that can be retrofitted (UPCCSCAP)
RETROFIT_MAX_HEAT_RATE = 12000.0 # least efficient unit that can be retrofitted (UPCCSHRT)
# Coal-to-gas conversion (emmcntl.txt %CL_to_NG%, allowed since 2014): fixed O&M x0.67, variable O&M x0.75, heat rate +5%.
# The conversion cost is an assumption, not EIA data: 100 1987$/kW (about 230 2024$/kW, the range EPA cites).
CONVERT_FOM_ADJ, CONVERT_VOM_ADJ, CONVERT_HR_PENALTY = 0.67, 0.75, 0.05
CONVERT_COST_KW = 100.0
RETIREMENT_HURDLE = 0.05         # emmcntl.txt %RET HURDLE RATES%, fossil (UPRETFHU)
AGE_ADDER_1987 = 5.0 / 1.336922   # $/kW-year for units 30+ years old: UPXTRA (%XTRA OandM%, 1999$) in 1987$
RESERVE_SHORTFALL_COST = 2.0e5  # k$ per GW-year, about 200 1987$/kW-year, for missing the reserve margin
REAL_DISCOUNT_RATE = 0.065       # only for the 45Q credit-life share (_credit_lost_share); builds use discount_rate()
# How fast the industry can build. An assumption, not EIA data: ecpdaty.xlsx sets no annual limit (999.9)
# and relies on resource supply curves that are not in the restart, so without these the LP builds
# hundreds of GW of wind in one year when the tax credit makes it nearly free. (Retirements use EIA's own
# rule, below.)
ANNUAL_BUILD_LIMIT_GW = {"gas_cc_new": 30.0, "gas_ccs": 10.0, "gas_ct_new": 30.0, "wind": 30.0, "solar": 60.0, "battery": 30.0}
# ECP's short-term build elasticities (ucape.f ELSTCAP/ELSTELA, ecpdaty.xlsx BLDINFO), in place of the flat
# ANNUAL_BUILD_LIMIT_GW: each build type's national additions this year come in three cost steps sized from the
# largest recent year of additions (ESTCPADD: the previous five years, later years weighted up to 1, at least
# ESTMNADD). Up to 1.25 x ESTCPADD costs the plant's own capital; the next 0.75 x at about 1.4 x and the last 1.0 x
# at about 2.25 x the capital charge (ESTELAST with ESTCSINC = ESTCPINC: the cost ratio is the capacity ratio less
# ESTCPSTP(1)). Nothing beyond 3 x ESTCPADD. EIA sets no annual limit (UPANNLMT 999.9).
BUILD_STEPS = True
STEP_CODES = {"gas_cc_new": "AC", "gas_ccs": "CS", "gas_ct_new": "AT", "wind": "WN", "solar": "PV", "battery": "DS"}
STEP_HISTORY = {   # build group -> (state groups whose planned adds count, restart UADD prefixes before the path)
    "gas_cc_new": (("gas_cc", "gas_cc_new"), ("cc", "-as")), "gas_ccs": (("gas_ccs",), ("as",)),
    "gas_ct_new": (("gas_ct", "gas_ct_new"), ("ct", "ic")), "wind": (("wind",), ("wn", "wf", "wl")),
    "solar": (("solar",), ("pv", "pt", "st")), "battery": (("battery",), ("ds",)),
}


def build_steps(code: str, recent: list) -> list:
    """[(GW bound, capital cost multiplier)] for this year's national builds of ECP type `code`, from the last five
    years' national additions (GW, oldest first), as ucape.f ELSTCAP and ELSTELA."""
    b = named_ranges(technology.ECPDATY, "BLDINFO")
    i = technology.ecp_codes().index(code)
    stp = np.array(b["ESTCPSTP"], dtype=float).reshape(len(b["ESTSWTCH"]), -1)[i]
    csinc, cpinc = float(b["ESTCSINC"][i]), float(b["ESTCPINC"][i])
    add = float(b["ESTMNADD"][i]) / 1000.0 / (1.0 + stp[0])
    n = len(recent)
    for k, a in enumerate(recent):
        add = max(add, float(a) * (0.5 + 0.5 * (k + 1) / n))
    out, cum, done = [], 1.0, 0.0
    for s, frac in enumerate(stp):
        cum += frac
        bound = add * cum - done
        mult = 1.0 if s == 0 else ((done + bound / 2.0) / add - stp[0]) ** (np.log(1.0 + csinc) / np.log(1.0 + cpinc))
        out.append((bound, float(mult)))
        done += bound
    return out


CREDIT_YEARS = 12.0              # years a plant earns the 45Q credit (TCS45Q/I_45Q_DURATION)
CCS_CAPACITY_FACTOR = 0.8        # assumed, to value the credit when deciding to build
# ECP's planning horizon (emmcntl.txt %ECP PARAMS%: UNFPH 30 years, UNXPH 3 explicit). The third explicit year
# stands for years 3 to 30; it is modelled as the year TAIL_OFFSET out (see solve_year).
HORIZON = False                   # off: see docs/capacity.md (horizon runs did not close the build gap)
HORIZON_YEARS = 30
TAIL_OFFSET = 10
LAST_MODEL_YEAR = 2050
HORIZON_SOLVER_OPTIONS = {"user_objective_scale": -2}   # HiGHS: the weighted tail costs are large
BLOCK_HOURS = 3
FUTURE_BLOCK_HOURS = 6         # the horizon's later periods in 6-hour blocks (half the size; this year keeps 3)
BLOCKS = 24 // BLOCK_HOURS

TG = ("coal", "coal_ccs", "gas_cc", "gas_cc_new", "gas_ccs", "gas_ct", "gas_ct_new", "steam", "gas_conv")
BASE_OF = {"gas_cc_new": "gas_cc", "gas_ct_new": "gas_ct"}      # inherits fuel, outage and limits
FIXED = ("nuclear", "hydro", "other", "pumped")
STATE_GROUPS = TG + FIXED + ("wind", "solar", "battery")

# Plant types that can be built, their ECP type, and the dispatch group the new capacity joins.
BUILDS = {"gas_cc_new": "AC", "gas_ccs": "CS", "gas_ct_new": "AT", "wind": "WN", "solar": "PV", "battery": "DS"}
RETIRABLE = ("coal", "gas_cc", "gas_ct", "steam")
# Capacity the LP itself made (CCS retrofits, coal converted to gas): no plant-file units, so no retirement groups;
# it retires as a whole, saving what it costs to keep (the coal plant's cost plus the capture plant's fixed O&M, or
# the converted plant's lower fixed O&M). EIA's run retires all of its CCS coal by 2050 once 45Q has ended.
RETIRABLE_MADE = ("coal_ccs", "gas_conv")

# Plant-file EFD type -> group, for dated additions and retirements.
FILE_GROUP = {}
for _g, _types in dispatch.EXISTING_TYPES.items():
    if _g in ("coal_ccs",):
        continue
    for _t in _types:
        FILE_GROUP.setdefault(_t, _g)
FILE_GROUP.update({"ACS": "gas_ccs", "HYR": "pumped", "DST": "battery"})

# Share of a plant's capacity that counts toward the reserve margin. Thermal plants count their availability.
# Nuclear and "other" are fixed assumptions. Wind, solar, hydro and storage come from the year's load shape:
# see capacity_credits().
FIRM_CREDIT = {"nuclear": 0.95, "other": 0.8}
STORAGE_HOURS = {"battery": (4.0, 0.85), "pumped": (12.0, 0.78)}
PEAK_HOURS = 88.0                # the top 1% of hours of net load define the peak the reserve margin protects
NEAR_PEAK = 0.9                  # storage must carry the hours where net load is within this share of its peak
# Firm capacity one region can lend another toward its reserve margin: share of the link's transfer capacity
# (uecp.f EP$ETT CAPACITY_DERATE, applied there to new lines; used here for the existing ones too).
FIRM_TRANSFER_SHARE = 0.75
# Debt share and tax rate of a new plant's financing (ecpdaty.xlsx FINANCIAL UPNFDT, UPTXRT). EIA adds its
# EXTRARISK premium (restart EMISSION/extrarisk, 3 points from 2008) to both the debt and equity rates of the
# types marked UPRSKSW (util.f 893-902: coal and combined cycle), so their after-tax discount rate rises by
# EXTRARISK x (UPNFDT x (1 - UPTXRT) + 1 - UPNFDT) (uefp.f EPDSCRT).
DEBT_SHARE, TAX_RATE = 0.6, 0.24


def discount_rate(snapshot, year: int) -> float:
    """ECP's after-tax cost of capital for new plants, EPDSCRT (uefp.f ELCOST, efp/capcost.py):
    UPNFDT x debt x (1 - UPTXRT) + (1 - UPNFDT) x equity, with debt the utility AA bond rate (ESRTLT) and
    equity the 10-year Treasury plus a 5.75% market premium times UPBETA (EWGTCE), both from the restart's macro
    block. About 7% in the reference case. It is a nominal rate; a level annuity at it is what ECP charges in
    the first year, which is what a one-year decision compares."""
    fin = named_ranges(technology.ECPDATY, "FINANCIAL")
    i = year - 1990
    debt = float(snapshot["MACOUT/mc_rmcorppuaa"][i]) / 100.0
    equity = float(snapshot["MACOUT/mc_rmtcm10y"][i]) / 100.0 + 0.0575 * float(fin["UPBETA"][0])
    share = float(fin["UPNFDT"][0])
    return share * debt * (1.0 - float(fin["UPTXRT"][0])) + (1.0 - share) * equity


def risk_premium(snapshot, year: int, code: str) -> float:
    """Discount rate premium for building ECP type `code` in `year`."""
    fin = named_ranges(technology.ECPDATY, "FINANCIAL")
    if fin["UPRSKSW"][technology.ecp_codes().index(code)] <= 0:
        return 0.0
    extra = float(snapshot["EMISSION/extrarisk"][year - 1990])
    return extra * (DEBT_SHARE * (1.0 - TAX_RATE) + 1.0 - DEBT_SHARE)


@dataclass
class YearResult:
    year: int
    status: str
    capacity: dict                  # group -> (25,) GW at the end of the year
    builds: dict                    # group -> (25,) GW built by the LP
    planned_adds: dict              # group -> (25,) GW from the plant file
    planned_retire: dict            # group -> (25,) GW from the plant file
    economic_retire: dict           # group -> (25,) GW retired by the LP (includes the rule)
    retrofit: np.ndarray            # (25,) GW coal moved to CCS
    generation_twh: dict = field(default_factory=dict)
    objective: float = 0.0
    unserved_twh: float = 0.0
    reserve_shortfall_gw: float = 0.0
    credits: dict = field(default_factory=dict)
    converted: np.ndarray = field(default_factory=lambda: np.zeros(NUM_R))     # GW coal moved to gas
    price: np.ndarray = None        # (25, 36, BLOCKS) energy price, 1987$/MWh (duals of the regional balance)
    reserve_price: np.ndarray = None  # (25,) 1987$/kW-year, dual of each region's reserve margin (EIA: RMAVG)
    group_retire: dict = field(default_factory=dict)  # group -> (25, 4) GW retired from each retirement group
    group_share: dict = field(default_factory=dict)   # group -> (25, 4) share of each retirement group retired
    rule_retire: np.ndarray = field(default_factory=lambda: np.zeros(NUM_R))  # GW coal the 2032 rule forced out


def max_retirement_rate(year: int) -> float:
    """EIA's cap on economic retirements, as a share of a region's capacity in one year.

    emmcntl.txt, %MAX RET RATE%: UPRETRT0 (3%) in the first ECP year, rising UPRETCHG (1 point) a year to
    UPRETRTL (6%). EP$RET in uecp.f applies it to each region's total capacity of every type.
    """
    lines = (INPUT / "emm" / "emmcntl.txt").read_text(encoding="latin-1").splitlines()
    row = next(l for l in lines if l.lstrip().startswith("'MAX RET'")).split()
    first, last, step = float(row[3]), float(row[4]), float(row[5])         # fields: 'MAX', 'RET', UPRETRAT, UPRETRT0, UPRETRTL, UPRETCHG
    rate = first + step * (year - START_YEAR)
    return rate if rate <= last + 1e-9 else float("inf")        # uecp.f 1176: past UPRETRTL the limit is switched off (RETYR = 0)


def epa111() -> dict:
    """EPA's 2024 power plant rule as EMM applies it (emmcntl.txt %EPA 111 SW%, read in udat.f): switch, last year coal
    can switch to gas (UEPA_GSYR), coal's largest share in a coal-gas cofiring plant from then (UEPA_CGSH), last year
    a plant may cofire coal (UEPA_CLCFYR: cofiring plants retire at the end of it, udat.f 6451), the year existing
    coal must retire or add CCS (UEPA_CLYR), and the year from which new gas combined cycle without CCS is held to a
    capacity factor of UEPA_NWGSCF (udat.f 6446)."""
    lines = (INPUT / "emm" / "emmcntl.txt").read_text(encoding="latin-1").splitlines()
    row = next(l for l in lines if l.lstrip().startswith("'EPA111 SW'")).split()[2:]
    keys = ("switch", "gas_switch_last", "cofire_coal_share", "cofire_last", "coal_rule", "new_cc_year", "new_cc_cf")
    vals = [float(v) for v in row[:7]]
    out = dict(zip(keys, vals))
    for k in ("switch", "gas_switch_last", "cofire_last", "coal_rule", "new_cc_year"):
        out[k] = int(out[k])
    return out


def cofiring_existing(snapshot, start_year: int) -> np.ndarray:
    """Coal-gas cofiring capacity already in the reference run's steam (restart prefix ng) when the loop starts, that
    EPA 111 retires after its last cofiring year: what the reference run itself still has in that prefix the year
    after (full gas conversions) stays. GW by region."""
    e = epa111()
    at_start = dispatch._ucap(snapshot, ("ng",), start_year - 1 - history.FIRST_YEAR)
    after = dispatch._ucap(snapshot, ("ng",), e["cofire_last"] + 1 - history.FIRST_YEAR)
    return np.maximum(at_start - after, 0.0) if e["switch"] else np.zeros(NUM_R)


def epa111_retirements(snapshot, year: int, cap_in: dict, rets: dict) -> dict:
    """`rets` plus EPA 111's cofiring retirements in `year`: plants still cofiring coal retire at the end of UEPA_CLCFYR.
    The LP's own conversions (gas_conv) cofire, and so do the reference run's existing ones in steam (prefix ng, less
    the full gas conversions it keeps)."""
    rule = epa111()
    if not rule["switch"] or year != rule["cofire_last"] + 1:
        return rets
    rets = dict(rets)
    rets["gas_conv"] = rets["gas_conv"] + cap_in["gas_conv"]
    rets["steam"] = rets["steam"] + np.minimum(cofiring_existing(snapshot, START_YEAR), cap_in["steam"])
    return rets


def _crf(rate: float, years: float) -> float:
    return rate / (1.0 - (1.0 + rate) ** -years)


def _credit_lost_share(life: float) -> float:
    """Share of a flat annual 45Q credit that a plant of this life does not get, because the credit
    lasts only I_45Q_DURATION (12) years. The dispatch model pays the credit every year; a build
    decision spreads the capital cost over the whole life, so the unpaid part is charged back."""
    annuity = lambda n: (1.0 - (1.0 + REAL_DISCOUNT_RATE) ** -n)
    return 1.0 - annuity(CREDIT_YEARS) / annuity(life)


def learned_overnight(snapshot, code: str, year: int):
    """ECP's overnight cost for a new plant of `code` in `year`, by region (1987$/kW): the COSTPERF cost with the
    regional and area multipliers and ECP's technology learning, as the reference run records it
    (UECPOUT/UP<code>CCST). Learning cuts batteries by about a quarter by 2027 and solar by a third by 2050, so a
    fixed COSTPERF cost stops renewable and storage builds once the tax credits end. None where the run has no
    cost for the type and year (the caller then uses COSTPERF)."""
    try:
        a = np.asarray(snapshot[f"UECPOUT/up{code.lower()}ccst"], dtype=float)[:NUM_R, year - history.FIRST_YEAR]
    except (KeyError, IndexError):
        return None
    return a if np.all(a > 0) else None


def _credit_overpaid(case, group: str, life: float, year: int, snapshot):
    """Share of the annual 45Q credit that the dispatch pays a new plant (or retrofit) of `group` built in `year`
    but that the plant does not earn, charged back in its annual cost. Dispatch pays the group's credited share
    (case.credit_share) every year; the plant earns the credit for its first I_45Q_DURATION years if it starts by
    I_45Q_LYR_NEW / _RET (2038), and nothing if it starts later."""
    paid = case.credit_share[group] if case.credit_share is not None else 1.0
    earned = 1.0 - _credit_lost_share(life) if year <= dispatch.credit_rule(snapshot)[1] else 0.0
    return paid - earned


def initial_capacity(snapshot, year_before: int) -> dict:
    """Year-end capacity by group in the year before the first solve, from the reference run."""
    y = year_before - history.FIRST_YEAR
    cap = {g: dispatch._ucap(snapshot, p, y) for g, p in dispatch.CAPACITY_PREFIXES.items()}
    cap["coal"] = np.maximum(cap["coal"] - cap["coal_ccs"], 0.0)
    cap["gas_conv"] = np.zeros(NUM_R)
    cap["gas_cc_new"] = np.zeros(NUM_R)
    cap["gas_ct_new"] = np.zeros(NUM_R)
    return {g: cap[g] for g in STATE_GROUPS}


def dated_changes(year: int):
    """Plant-file additions and retirements dated to `year`, by group and region, GW."""
    u = plants.load_units()
    adds = {g: np.zeros(NUM_R) for g in STATE_GROUPS}
    rets = {g: np.zeros(NUM_R) for g in STATE_GROUPS}
    for kind, sel_year, out in (("add", u.online_year, adds), ("ret", u.retire_year, rets)):
        for code in np.unique(u.efd_type):
            g = FILE_GROUP.get(code)
            if g is None:
                continue
            m = (sel_year == year) & (u.efd_type == code)
            np.add.at(out[g], u.region[m] - 1, u.summer_mw[m] / 1000.0)
    return adds, rets


def _weighted_by_region(values, weights, mask, fallback):
    u = plants.load_units()
    return dispatch._weighted_mask(values, weights, mask, u.region, fallback)


def capacity_credits(case, cap0: dict, load_hr: np.ndarray, month_of_day: np.ndarray) -> dict:
    """Capacity credit of wind, solar, hydro and storage from the year's load shape.

    Net load is national load less the wind and solar already in service. The peak is its top
    PEAK_HOURS hours. Wind and solar earn their average capacity factor over those hours, so solar's
    credit falls as more of it is built and the peak moves to the evening. Storage earns the share of
    the near-peak window (hours with net load within NEAR_PEAK of the peak on the peak day) that its
    duration can cover, less round-trip loss. Hydro earns what its monthly energy lets it deliver
    over that window. Returns the credits and the window's length in hours.
    """
    w = case.weights
    load_nat = load_hr.sum(axis=0)                                           # (36, 24)

    def mix(group):
        cap = cap0[group]
        if cap.sum() <= 0:
            cap = np.ones(NUM_R)
        return (cap[:, None, None] * case.profile[group]).sum(axis=0) / cap.sum()       # national CF by day and hour

    cf = {g: mix(g) for g in ("wind", "solar")}
    net = load_nat - cap0["wind"].sum() * cf["wind"] - cap0["solar"].sum() * cf["solar"]
    hours = np.broadcast_to(w[:, None], net.shape).ravel()
    order = np.argsort(-net.ravel())
    cum = np.cumsum(hours[order])
    top = order[: int(np.searchsorted(cum, PEAK_HOURS)) + 1]
    top_hours = hours[top].sum()
    credits = {g: float((hours[top] * cf[g].ravel()[top]).sum() / top_hours) for g in ("wind", "solar")}
    day = int(np.argmax(net.max(axis=1)))
    width = max(int((net[day] >= NEAR_PEAK * net[day].max()).sum()), 1)
    for name, (dur, rte) in STORAGE_HOURS.items():
        credits[name] = float(min(1.0, dur / width) * np.sqrt(rte))
    peak_month = int(month_of_day[day])
    hydro_cf = float(np.average(case.monthly_cf["hydro"][:, peak_month], weights=np.maximum(cap0["hydro"], 1e-9)))
    credits["hydro"] = float(min(1.0, hydro_cf * 24.0 / width))
    credits["window_hours"] = float(width)
    return credits


def _blocks(a: np.ndarray, hours: int = BLOCK_HOURS) -> np.ndarray:
    """Average the 24 hours of a (..., 36, 24) array into blocks of `hours` hours."""
    return a.reshape(a.shape[:-1] + (24 // hours, hours)).mean(axis=-1)


def unit_costs(case, group: str) -> np.ndarray:
    """Variable cost of every plant-file unit as if it were in `group`, 1987$/MWh (own heat rate and VOM)."""
    u = plants.load_units()
    r0 = np.clip(u.region - 1, 0, NUM_R - 1)
    oil = case.price["residual"] if group == "steam" else case.price["distillate"]
    base = case.price["coal"] if group.startswith("coal") else case.price["gas"]
    share = case.oil_share.get(group, np.zeros(NUM_R))
    fuel = (1 - share) * base + share * oil                     # (25,) 1987$/MMBtu
    tons = retire_groups.CO2_TONS_PER_MMBTU["coal" if group.startswith("coal") else "gas"]
    hr = np.where(u.heat_rate > 0, u.heat_rate, 10000.0)
    return hr / 1000.0 * (fuel[r0] + case.carbon_price * tons) + u.vom


def ptc_annual(ptc: float, dollar_year: int, years: int, rate: float, life: float, year: int, snapshot) -> float:
    """A production tax credit as ECP's EP$INT values it (uecp.f 19466-19500), in 1987 $/MWh of a level annual
    credit over the plant's life: the online year's UPGSUBYR (dollars of UPGSYD, made 1987 dollars as udat.f does),
    held for UPGSYR years and rising with inflation (UPGNPD), grossed up for tax (/(1 - UPTXRT)), discounted at the
    plant's rate and spread over its economic life. Charging the table value every year of the life overstated a
    2028 wind plant's credit by about half and pulled builds into 2027-2029."""
    if ptc <= 0 or years <= 0:
        return 0.0
    jp = np.asarray(snapshot["MACOUT/mc_jpgdp"], dtype=float).ravel()     # 1987 = index 0 (MC_JPGDP from 1987)
    at = lambda y: jp[min(max(y - 1987, 0), jp.size - 1)]
    real87 = ptc / at(dollar_year)
    infl = (at(year + years) / at(year)) ** (1.0 / years) - 1.0
    pv = sum((1.0 + infl) ** (k - 1) / (1.0 + rate) ** k for k in range(1, int(years) + 1))
    return real87 / (1.0 - TAX_RATE) * pv * _crf(rate, life)


def capital_costs(snapshot, year: int, case, parts: dict | None = None) -> dict:
    """Annual cost of a new plant built in `year`, by build group: {group: (25,) k$ per GW-year}, net of the ITC
    and PTC, with ECP's learned overnight cost and the year's discount rate."""
    params = technology.type_parameters()
    codes = technology.ecp_codes()
    reg = technology.regional_costs()
    sub = named_ranges(technology.ECPDATY, "SUBSIDY")
    itc_tab = np.array(sub["UPCSBYR"]).reshape(80, -1)
    ptc_tab = np.array(sub["UPGSUBYR"]).reshape(80, -1)
    col = min(year, 2050) - 2010
    cost_year = min(year, 2050)
    capital = {}
    for g, code in BUILDS.items():
        i = codes.index(code)
        ovn = learned_overnight(snapshot, code, cost_year)
        if ovn is None:
            ovn = params["overnight_cost"][i] * reg["regional_multiplier"][:NUM_R, i] * reg["area_multiplier"][:NUM_R, i]
        itc = max(itc_tab[i, col], 0.0)
        rate = discount_rate(snapshot, cost_year) + risk_premium(snapshot, cost_year, code)
        annual = ovn * (1.0 - itc) * _crf(rate, params["economic_life"][i]) + params["fom"][i]
        if parts is not None:      # the capital charge alone, k$ per GW-year (what ECP's build steps scale)
            parts[g] = ovn * (1.0 - itc) * _crf(rate, params["economic_life"][i]) * 1.0e3
        ptc = max(ptc_tab[i, col], 0.0)
        if g in ("wind", "solar"):
            cf = (case.build_profile or case.profile)[g].mean(axis=(1, 2))
            credit = ptc_annual(ptc, int(sub["UPGSYD"][i]), int(sub["UPGSYR"][i]), rate, params["economic_life"][i],
                                cost_year, snapshot)
            annual = annual - credit * cf * 8.76      # $/MWh x GWh per MW-year -> $/kW-year
        if g in dispatch.CAPTURE_GROUPS:
            tons = case.heat_rate[g] / 1000.0 * dispatch.CO2_PER_TBTU[dispatch.CAPTURE_GROUPS[g]] * dispatch.CAPTURE_RATE
            annual = annual + _credit_overpaid(case, g, params["economic_life"][i], year, snapshot) * case.credit_45q * tons * CCS_CAPACITY_FACTOR * 8.76
        capital[g] = annual * 1.0e3                   # $/kW-year -> k$ per GW-year
    return capital


def future_case(snapshot, year: int, future: int, case):
    """The dispatch case ECP expects for a later planning year: the reference run's case for that year (its load,
    fuel prices, profiles and links), moved by how far this year's case (the loop's own demand and prices) is from
    the reference's this year, so a shock now persists in what the plan expects. Past the last model year the load
    keeps the reference's growth of its last five years and prices stay at the last year's."""
    last = min(future, LAST_MODEL_YEAR)
    ref = _reference_case(snapshot, last)
    ref_now = _reference_case(snapshot, year)
    load_ratio = np.divide(case.net_load_twh, ref_now.net_load_twh, out=np.ones(NUM_R), where=ref_now.net_load_twh > 0)
    net = ref.net_load_twh * load_ratio
    if future > last:
        back = _reference_case(snapshot, last - 5).net_load_twh
        growth = np.divide(ref.net_load_twh, back, out=np.ones(NUM_R), where=back > 0) ** (1.0 / 5.0)
        net = net * growth ** (future - last)
    price = {}
    for k, v in ref.price.items():
        r = np.divide(case.price[k], ref_now.price[k], out=np.ones_like(np.asarray(v, dtype=float)), where=np.asarray(ref_now.price[k]) > 0)
        price[k] = v * r
    rule = dispatch.credit_rule(snapshot)
    share = None
    if case.credit_share is not None:
        # capacity credited now: what is left of it in the later year (cohorts age out); nothing new is credited
        share = {g: np.clip(case.credit_share[g] * (1.0 if future < year + rule[2] else 0.0), 0.0, 1.0)
                 for g in case.credit_share}
    return replace(ref, net_load_twh=net, price=price, carbon_price=case.carbon_price, credit_share=share)


_REF_CASES: dict = {}


def _reference_case(snapshot, year: int):
    key = (id(snapshot), year)
    if key not in _REF_CASES:
        _REF_CASES[key] = dispatch.build_case(snapshot, year, "none")
    return _REF_CASES[key]


def solve_year(snapshot, year: int, cap_in: dict, solver: str = "highs", progress: bool = False,
               groups: dict | None = None, decide: bool = True, case=None, horizon: bool | None = None,
               recent_adds: dict | None = None) -> YearResult:
    """One year of the loop. `groups` (dispatch group -> retire_groups.Groups) splits retirements into ECP's
    retirement groups; without it a whole region and type retires at one cost. decide=False solves dispatch
    only (no builds, retirements, retrofits or conversions), to get prices. horizon: plan over ECP's horizon
    (HORIZON, the default) or this year only. recent_adds: build group -> the last five years' national additions
    (GW, oldest first) for ECP's build steps (BUILD_STEPS); without it the steps start from ESTMNADD."""
    horizon = HORIZON if horizon is None else horizon
    y = year - history.FIRST_YEAR
    case = case if case is not None else dispatch.build_case(snapshot, year, "none")
    adds, rets = dated_changes(year)
    rule = epa111()
    rets = epa111_retirements(snapshot, year, cap_in, rets)
    cap0 = {g: np.maximum(cap_in[g] + adds[g] - rets[g], 0.0) for g in STATE_GROUPS}

    # --- costs of building ---
    params = technology.type_parameters()
    codes = technology.ecp_codes()
    hr_new_all = np.array(named_ranges(technology.ECPDATY, "OPTLRN")["UPPHRTN"])
    capital_only = {}
    capital = capital_costs(snapshot, year, case, capital_only)

    # --- characteristics of the groups ---
    heat, vom, oil_share = dict(case.heat_rate), dict(case.vom), dict(case.oil_share)
    avail = dict(case.avail)
    for g, base in BASE_OF.items():
        i = codes.index(BUILDS[g])
        heat[g] = np.full(NUM_R, float(hr_new_all[i]))
        vom[g] = np.full(NUM_R, float(params["vom"][i]))
        oil_share[g] = np.zeros(NUM_R)
        avail[g] = avail[base]
    heat["gas_conv"] = heat["coal"] * (1.0 + CONVERT_HR_PENALTY)
    vom["gas_conv"] = vom["coal"] * CONVERT_VOM_ADJ
    oil_share["gas_conv"] = np.zeros(NUM_R)
    avail["gas_conv"] = avail["coal"]
    heat["gas_ccs"] = np.full(NUM_R, float(hr_new_all[codes.index("CS")]))
    vom["gas_ccs"] = np.full(NUM_R, float(params["vom"][codes.index("CS")]))
    max_cf = {g: np.full(NUM_R, avail[g][1]) for g in TG}
    if rule["switch"] and year >= rule["new_cc_year"]:
        max_cf["gas_cc_new"] = np.minimum(max_cf["gas_cc_new"], rule["new_cc_cf"])     # EPA 111: new CC without CCS

    # --- existing plant fixed O&M, CCS retrofit data ---
    u = plants.load_units()
    tb = db.table("V_EMM_PLTF860")
    on = plants.online(year)
    fom_exist = {}
    for g in RETIRABLE:
        mask = on & np.isin(u.efd_type, dispatch.EXISTING_TYPES[g])
        # What ECP charges an existing plant for staying (udat.f RET_FOM): fixed O&M, capital additions and the
        # age-dependent adder; the retirement hurdle rate (UPRETFHU) then discounts that cost by 5%.
        age = np.maximum(year - u.online_year, 0)
        adder = np.where(age >= 30, AGE_ADDER_1987, 0.0)
        stay = tb["T_FOM"] + tb["T_CAPAD"] + adder
        fom_exist[g] = _weighted_by_region(stay, u.summer_mw, mask, 20.0) * 1.0e3 * (1.0 - RETIREMENT_HURDLE)       # k$ per GW-year
    coal_mask = on & np.isin(u.efd_type, dispatch.EXISTING_TYPES["coal"])
    elig = coal_mask & (u.summer_mw >= RETROFIT_MIN_MW) & (u.heat_rate <= RETROFIT_MAX_HEAT_RATE) & (tb["T_CCSHR"] > 0) \
        & (tb["T_CCSHR"] < dispatch.CCS_HEAT_RATE_MAX)
    elig_gw = np.zeros(NUM_R)
    np.add.at(elig_gw, u.region[elig] - 1, u.summer_mw[elig] / 1000.0)
    elig_gw = np.minimum(elig_gw, cap0["coal"])
    retro_cost = _weighted_by_region(tb["T_CCSROV"], u.summer_mw, elig, 1100.0)
    retro_fom = _weighted_by_region(tb["T_CCSF"], u.summer_mw, elig, 8.0)
    retro_tons = case.heat_rate["coal_ccs"] / 1000.0 * dispatch.CO2_PER_TBTU["coal"] * dispatch.CAPTURE_RATE
    retro_lost = _credit_overpaid(case, "coal_ccs", 20.0, year, snapshot) * case.credit_45q * retro_tons * 0.6 * 8.76     # coal runs about 60%
    retro_annual = (retro_cost * _crf(discount_rate(snapshot, year), 20.0) + retro_fom + retro_lost) * 1.0e3
    fom_made = {"coal_ccs": fom_exist["coal"] + retro_fom * 1.0e3 * (1.0 - RETIREMENT_HURDLE),
                "gas_conv": fom_exist["coal"] * CONVERT_FOM_ADJ}

    # --- time slices ---
    R = pd.Index(np.arange(1, NUM_R + 1), name="region")
    D = pd.Index(np.arange(36), name="day")
    Bk = pd.Index(np.arange(BLOCKS), name="block")
    T = pd.Index(list(TG), name="group")
    MO = pd.Index(np.arange(12), name="month")
    month_of_day = np.repeat(np.arange(12), 3)
    ones = xr.DataArray(np.ones((NUM_R, 36, BLOCKS)), coords=[R, D, Bk])

    def by_region(a):
        return xr.DataArray(np.asarray(a, dtype=float), coords=[R]) * ones

    m = linopy.Model()
    cap_const = xr.DataArray(np.stack([cap0[g] for g in TG], axis=1), coords=[R, T])
    room = 100.0 if (year >= FIRST_UNPLANNED_YEAR and decide) else 0.0
    # ECP's first planning year is START_YEAR; a type chosen then comes online after its construction lead time
    # (COSTPERF UPCLYR: turbines and solar 2 years, combined cycle and wind 3, CCS 4, batteries 1).
    lead = params["construction_lead_years"]
    can_build = {g: year >= START_YEAR + lead[codes.index(c)] for g, c in BUILDS.items()}
    buildable = xr.DataArray(np.stack([np.full(NUM_R, room if can_build.get(g) else 0.0) for g in TG], axis=1), coords=[R, T])
    retirable = xr.DataArray(np.stack([cap0[g] if ((g in RETIRABLE or g in RETIRABLE_MADE) and decide) else np.zeros(NUM_R) for g in TG], axis=1),
                             coords=[R, T])
    build = m.add_variables(lower=0, upper=buildable, name="build")
    retire = m.add_variables(lower=0, upper=retirable, name="retire")
    use_groups = groups is not None and decide
    if use_groups:
        # ECP's retirement groups: each group's capacity (scaled to the LP's own capacity where the plant file and
        # the restart differ) can retire, saving its EPGFOM. What is not in a group (must-run, cogeneration owners)
        # stays, except that the carbon rule can force coal out from RULE_YEAR.
        TR = pd.Index(list(RETIRABLE), name="group")
        K = pd.Index(np.arange(retire_groups.NUM_GROUPS), name="rgrp")
        gcap = np.zeros((NUM_R, len(TR), retire_groups.NUM_GROUPS))
        gcost = np.zeros_like(gcap)
        for j, g in enumerate(RETIRABLE):
            grp = groups[g]
            tot = grp.capacity.sum(axis=1)
            scale = np.divide(cap0[g], tot, out=np.zeros(NUM_R), where=tot > 0)
            gcap[:, j, :] = grp.capacity * np.minimum(scale, 1.0)[:, None]
            gcost[:, j, :] = np.maximum(grp.cost, 0.0) * 1.0e3 * (1.0 - RETIREMENT_HURDLE)     # k$ per GW-year
        rg = m.add_variables(lower=0, upper=xr.DataArray(gcap, coords=[R, TR, K]), name="retire_group")
        forced = m.add_variables(lower=0, upper=xr.DataArray(cap0["coal"] * (year >= RULE_YEAR), coords=[R]),
                                 name="rule_retire")
        is_coal = xr.DataArray(np.array([1.0 if g == "coal" else 0.0 for g in RETIRABLE]), coords=[TR])
        m.add_constraints(retire.sel(group=list(RETIRABLE)) - rg.sum("rgrp") - forced * is_coal == 0, name="retire_groups")
    retrofit = m.add_variables(lower=0, upper=xr.DataArray(elig_gw * (room > 0), coords=[R]), name="retrofit")
    bw = m.add_variables(lower=0, upper=room * can_build["wind"], coords=[R], name="build_wind")
    bs = m.add_variables(lower=0, upper=room * can_build["solar"], coords=[R], name="build_solar")
    bb = m.add_variables(lower=0, upper=room * can_build["battery"], coords=[R], name="build_battery")
    can_convert = year >= START_YEAR and decide and (not rule["switch"] or year <= rule["gas_switch_last"])
    convert = m.add_variables(lower=0, upper=xr.DataArray(cap0["coal"] * can_convert, coords=[R]),
                              name="convert")
    m.add_constraints(retrofit.sum() <= RETROFIT_LIMIT_GW, name="retrofit_limit")
    step_premium = 0
    if BUILD_STEPS and room > 0:
        renewable = {"wind": bw, "solar": bs, "battery": bb}
        for g, code in STEP_CODES.items():
            total = renewable[g].sum() if g in renewable else build.sel(group=g).sum()
            steps = build_steps(code, (recent_adds or {}).get(g, [0.0] * 5))
            S = pd.Index(range(len(steps)), name="step")
            sv = m.add_variables(lower=0, upper=xr.DataArray([b for b, _ in steps], coords=[S]), name=f"build_step_{g}")
            m.add_constraints(total - sv.sum() == 0, name=f"build_steps_{g}")
            premium = float(np.mean(capital_only[g])) * xr.DataArray([mu - 1.0 for _, mu in steps], coords=[S])
            step_premium = step_premium + (sv * premium).sum()
    elif not BUILD_STEPS:
        m.add_constraints(bw.sum() <= ANNUAL_BUILD_LIMIT_GW["wind"], name="limit_build_wind")
        m.add_constraints(bs.sum() <= ANNUAL_BUILD_LIMIT_GW["solar"], name="limit_build_solar")
        m.add_constraints(bb.sum() <= ANNUAL_BUILD_LIMIT_GW["battery"], name="limit_build_battery")
    to_ccs = xr.DataArray(np.array([1.0 if g == "coal_ccs" else (-1.0 if g == "coal" else 0.0) for g in TG]), coords=[T])
    to_gas = xr.DataArray(np.array([1.0 if g == "gas_conv" else (-1.0 if g == "coal" else 0.0) for g in TG]), coords=[T])
    cap_th = cap_const + build - retire + retrofit * to_ccs + convert * to_gas
    for g, limit in ANNUAL_BUILD_LIMIT_GW.items():
        if g in TG and not BUILD_STEPS:
            m.add_constraints(build.sel(group=g).sum() <= limit, name=f"limit_build_{g}")
    # EIA's cap: economic retirements in a region may not exceed a share of its total capacity (the carbon rule's
    # forced coal retirements from RULE_YEAR are exempt, as they are policy, not economics).
    rate = max_retirement_rate(year)
    region_total = xr.DataArray(sum(cap0[g] for g in STATE_GROUPS), coords=[R])
    econ = retire.sel(group=[g for g in TG if g != "coal"]).sum("group")
    if year < RULE_YEAR:
        econ = econ + retire.sel(group="coal") + convert
    if np.isfinite(rate):
        m.add_constraints(econ <= rate * region_total, name="retirement_rate")
    capv = m.add_variables(lower=0, coords=[R, T], name="capacity")
    m.add_constraints(capv - cap_th == 0, name="capacity_def")
    if year >= RULE_YEAR and decide:
        coal_only = xr.DataArray(np.array([1.0 if g == "coal" else 0.0 for g in TG]), coords=[T])
        m.add_constraints((capv * coal_only).sum("group") == 0, name="coal_rule")

    one_minus_for = xr.DataArray(np.array([1.0 - avail[g][0] for g in TG]), coords=[T])
    mcf = xr.DataArray(np.stack([max_cf[g] for g in TG], axis=1), coords=[R, T])
    tab = db.table("V_EMM_ECPDAT_REG")
    order = np.argsort(tab["EMM_REG"])
    keep = order[tab["EMM_REG"][order] <= NUM_R]
    margin = np.nan_to_num(np.asarray(tab["EPMRM"], dtype=float)[keep])

    def operate(tag: str, cs, c0: dict, capv_p, wind_tot, solar_tot, batt_tot, bh: int = BLOCK_HOURS, new_w=0, new_s=0):
        """Dispatch and reserve margin of one planning period: case `cs` (its load, fuel prices and profiles),
        existing capacity `c0`, thermal capacity `capv_p` and wind, solar and battery totals (expressions in the
        decision variables). Returns its operating cost (1987 k$ for one year) and the pieces the result needs."""
        Bk = pd.Index(np.arange(24 // bh), name="block")
        ones = xr.DataArray(np.ones((NUM_R, 36, 24 // bh)), coords=[R, D, Bk])
        hours_w = xr.DataArray(cs.weights * bh, coords=[D])                    # hours per year each slice stands for

        def by_region(a):
            return xr.DataArray(np.asarray(a, dtype=float), coords=[R]) * ones

        def cf_of(group):
            return xr.DataArray(cs.monthly_cf[group][:, month_of_day], coords=[R, D]) * ones

        load_hr = cs.net_load_twh[:, None, None] * 1000.0 * cs.shapes           # GW in each hour
        credits = capacity_credits(cs, c0, load_hr, np.repeat(np.arange(12), 3))
        load_gw = xr.DataArray(_blocks(load_hr, bh), coords=[R, D, Bk])
        prof = {k: xr.DataArray(_blocks(v, bh), coords=[R, D, Bk]) for k, v in cs.profile.items()}

        g_th = m.add_variables(lower=0, coords=[R, T, D, Bk], name=f"gen{tag}")
        m.add_constraints(g_th - capv_p * one_minus_for <= 0, name=f"gen_limit{tag}")
        m.add_constraints((g_th * hours_w).sum(["day", "block"]) - capv_p * (mcf * 8760.0) <= 0, name=f"energy_limit{tag}")

        cost = np.zeros((NUM_R, len(TG)))
        for k, g in enumerate(TG):
            oil_price = cs.price["residual"] if g == "steam" else cs.price["distillate"]
            is_coal = g.startswith("coal")
            fuel = (1 - oil_share[g]) * cs.price["coal" if is_coal else "gas"] + oil_share[g] * oil_price
            if g == "gas_conv" and rule["switch"]:
                # EPA 111 cofiring: at most UEPA_CGSH of the fuel is coal (udat.f 6457), the rest gas
                fuel = rule["cofire_coal_share"] * cs.price["coal"] + (1.0 - rule["cofire_coal_share"]) * cs.price["gas"]
            cost[:, k] = heat[g] / 1000.0 * fuel + vom[g]
            if g in dispatch.CAPTURE_GROUPS:
                share = cs.credit_share[g] if cs.credit_share is not None else 1.0
                cost[:, k] -= cs.credit_45q * share * heat[g] / 1000.0 * dispatch.CO2_PER_TBTU[dispatch.CAPTURE_GROUPS[g]] * dispatch.CAPTURE_RATE
        cost_da = xr.DataArray(cost, coords=[R, T])

        wind_out = wind_tot * prof["wind"]
        solar_out = solar_tot * prof["solar"]
        if cs.build_profile is not None:      # capacity built by the LP runs on the new-build profile, not the fleet's
            bprof = {k: xr.DataArray(_blocks(v, bh), coords=[R, D, Bk]) for k, v in cs.build_profile.items()}
            wind_out = wind_out + new_w * (bprof["wind"] - prof["wind"])
            solar_out = solar_out + new_s * (bprof["solar"] - prof["solar"])
        fixed = by_region(c0["nuclear"]) * cf_of("nuclear") + by_region(c0["other"]) * cf_of("other")

        g_hy = m.add_variables(lower=0, upper=by_region(c0["hydro"]), name=f"hydro{tag}")
        month_w = xr.DataArray(np.eye(12)[month_of_day], coords=[D, MO])
        days_in_month = np.array([cs.weights[month_of_day == mo].sum() for mo in range(12)])
        budget = xr.DataArray(cs.monthly_cf["hydro"] * c0["hydro"][:, None] * days_in_month[None, :] * 24.0, coords=[R, MO])
        m.add_constraints((g_hy * (hours_w * month_w)).sum(["day", "block"]) <= budget, name=f"hydro_budget{tag}")

        net_storage = 0
        sto_cap = {"battery": batt_tot, "pumped": xr.DataArray(c0["pumped"], coords=[R])}
        for name, (dur, rte) in STORAGE_HOURS.items():
            eta = np.sqrt(rte)
            ch = m.add_variables(lower=0, coords=[R, D, Bk], name=f"{name}_charge{tag}")
            di = m.add_variables(lower=0, coords=[R, D, Bk], name=f"{name}_discharge{tag}")
            soc = m.add_variables(lower=0, coords=[R, D, Bk], name=f"{name}_soc{tag}")
            m.add_constraints(ch - sto_cap[name] <= 0, name=f"{name}_ch_cap{tag}")
            m.add_constraints(di - sto_cap[name] <= 0, name=f"{name}_di_cap{tag}")
            m.add_constraints(soc - dur * sto_cap[name] <= 0, name=f"{name}_soc_cap{tag}")
            m.add_constraints(soc - soc.roll(block=1) - bh * eta * ch + bh * di / eta == 0,
                              name=f"{name}_balance{tag}")
            net_storage = net_storage + di - ch

        links = cs.links
        L = pd.Index(np.arange(len(links["exporter"])), name="link")
        cap_l = xr.DataArray(links["capacity_gw"], coords=[L, D]) * xr.DataArray(np.ones(24 // bh), coords=[Bk])
        trade = m.add_variables(lower=0, upper=cap_l.transpose("link", "day", "block"), name=f"trade{tag}")
        into = np.zeros((NUM_R, len(L)))
        outof = np.zeros((NUM_R, len(L)))
        into[links["importer"], np.arange(len(L))] = 1.0 - links["loss"]
        outof[links["exporter"], np.arange(len(L))] = 1.0
        trade_in = (trade * xr.DataArray(into, coords=[R, L])).sum("link")
        trade_out = (trade * xr.DataArray(outof, coords=[R, L])).sum("link")

        spill = m.add_variables(lower=0, coords=[R, D, Bk], name=f"spill{tag}")
        unserved = m.add_variables(lower=0, coords=[R, D, Bk], name=f"unserved{tag}")
        m.add_constraints(g_th.sum("group") + g_hy + net_storage + unserved - spill + trade_in - trade_out
                          + wind_out + solar_out + fixed == load_gw, name=f"balance{tag}")

        # Reserve margin region by region, as ECP writes it (uecp.f EP$MRM): capacity >= EPMRM x peak + net peak.
        # Dispatchable capacity counts in full; wind and solar at EPIRCCR (capacity_credit, CAP_CREDIT's variance
        # method); storage and hydro at the load-shape credits above. A region can count firm capacity lent by a
        # neighbour, up to FIRM_TRANSFER_SHARE of the link, less line losses.
        icc = capacity_credit.credits(load_hr, c0, cs.profile, cs.weights)
        credits.update({"wind_by_region": icc["wind"], "solar_by_region": icc["solar"]})
        requirement = xr.DataArray(margin * icc["peak"] + icc["net_peak"], coords=[R])
        firm = capv_p.sum("group")
        firm = firm + wind_tot * xr.DataArray(icc["wind"], coords=[R])
        firm = firm + solar_tot * xr.DataArray(icc["solar"], coords=[R])
        firm = firm + batt_tot * credits["battery"]
        const_firm = c0["nuclear"] + c0["other"] + c0["hydro"] * credits["hydro"] + c0["pumped"] * credits["pumped"]
        lend = m.add_variables(lower=0, upper=xr.DataArray(FIRM_TRANSFER_SHARE * links["capacity_gw"].mean(axis=1), coords=[L]),
                               name=f"firm_transfer{tag}")
        into_f = np.zeros((NUM_R, len(L)))
        out_f = np.zeros((NUM_R, len(L)))
        into_f[links["importer"], np.arange(len(L))] = 1.0 - links["loss"]
        out_f[links["exporter"], np.arange(len(L))] = 1.0
        lent = (lend * xr.DataArray(into_f, coords=[R, L])).sum("link") - (lend * xr.DataArray(out_f, coords=[R, L])).sum("link")
        shortfall = m.add_variables(lower=0, coords=[R], name=f"reserve_shortfall{tag}")
        m.add_constraints(firm + lent + shortfall >= requirement - xr.DataArray(const_firm, coords=[R]), name=f"reserve_margin{tag}")
        operating = (g_th * cost_da * hours_w).sum() + (unserved * (dispatch.UNSERVED_COST * hours_w)).sum() \
            + (trade * (xr.DataArray(links["cost"], coords=[L]) * hours_w)).sum() + (g_hy * (0.01 * hours_w)).sum() \
            + (shortfall * RESERVE_SHORTFALL_COST).sum()
        return {"operating": operating, "g_th": g_th, "unserved": unserved, "shortfall": shortfall, "credits": credits}

    def totals(c0, extra_w, extra_s, extra_b):
        return (xr.DataArray(c0["wind"], coords=[R]) + extra_w, xr.DataArray(c0["solar"], coords=[R]) + extra_s,
                xr.DataArray(c0["battery"], coords=[R]) + extra_b)

    p1 = operate("", case, cap0, capv, *totals(cap0, bw, bs, bb), new_w=bw, new_s=bs)
    g_th, unserved, shortfall, credits = p1["g_th"], p1["unserved"], p1["shortfall"], p1["credits"]
    operating = p1["operating"]
    weight_now = 1.0                       # present-value weight of the annual costs of this year's decisions
    future_capex = 0
    coal_weight = 1.0

    # ECP's planning horizon (UNXPH = 3 explicit years of UNFPH = 30, emmcntl.txt %ECP PARAMS%): the next year and a
    # tail year that stands for years 3 to 30, weighted by present value, each with its own load, fuel prices,
    # dispatch, reserve margin and builds. Only this year's decisions are carried out; the later periods make a
    # plant built now pay for itself over the load growth and prices it will see. In EIA's 2030 run the tail's
    # reserve requirement (1,120 GW) is about this model's 2040 one, hence a tail TAIL_OFFSET years out.
    if horizon and decide:
        rate = discount_rate(snapshot, year)
        weights = {1: 1.0 / (1.0 + rate), TAIL_OFFSET: sum((1.0 + rate) ** -k for k in range(2, HORIZON_YEARS))}
        # coal without CCS saves its fixed costs by retiring only until the rule would retire it anyway
        coal_weight = 1.0 + sum(w for o, w in weights.items() if year + o < RULE_YEAR)
        later_th = later_w = later_s = later_b = 0
        c0f = dict(cap0)
        done = year
        for offset, wgt in weights.items():
            yf = year + offset
            cs = future_case(snapshot, year, yf, case)
            for yy in range(done + 1, yf + 1):                 # plant-file changes up to the period's year
                a, r_ = dated_changes(yy)
                c0f = {g: np.maximum(c0f[g] + a[g] - r_[g], 0.0) for g in STATE_GROUPS}
            # ECP builds only in its explicit years: the last chance is year 3 (this year + 2), and what is built by
            # then must serve the tail's load. So the tail's builds happen in year + 2, at that year's cost and limits.
            yb = min(yf, year + 2)
            span = 1
            done = yf
            # A type chosen in a later explicit year comes online only after its lead time, so it can serve this
            # period only if the lead fits: batteries (1 year) in year 2; batteries, turbines and solar (2) in year 3.
            # Combined cycle, wind and CCS (3 to 4 years) for these periods must be chosen now, which is how ECP
            # commits capacity ahead of the tail's peak.
            okb = {g: yb >= START_YEAR + lead[codes.index(c)] and lead[codes.index(c)] <= yb - year
                   for g, c in BUILDS.items()}
            fb = m.add_variables(lower=0, upper=xr.DataArray(np.stack([np.full(NUM_R, 100.0 * span if okb.get(g) else 0.0)
                                                                         for g in TG], axis=1), coords=[R, T]),
                                 name=f"build_p{offset}")
            fw = m.add_variables(lower=0, upper=100.0 * span * okb["wind"], coords=[R], name=f"build_wind_p{offset}")
            fs = m.add_variables(lower=0, upper=100.0 * span * okb["solar"], coords=[R], name=f"build_solar_p{offset}")
            fbb = m.add_variables(lower=0, upper=100.0 * span * okb["battery"], coords=[R], name=f"build_battery_p{offset}")
            for g, limit in ANNUAL_BUILD_LIMIT_GW.items():
                v = {"wind": fw, "solar": fs, "battery": fbb}.get(g)
                expr = v.sum() if v is not None else fb.sel(group=g).sum()
                m.add_constraints(expr <= limit * span, name=f"limit_{g}_p{offset}")
            later_th = later_th + fb
            later_w, later_s, later_b = later_w + fw, later_s + fs, later_b + fbb
            # this year's thermal capacity carries forward, plus later builds and the plant file's dated changes
            # At most this year's capacity carried forward plus the plant file's later additions, and at most the
            # plant file's own path (its dated retirements) plus what the LP adds; capacity the 2032 rule or an early
            # retirement takes out is simply not there. Both bounds stay at or above zero, so the period is feasible.
            added = xr.DataArray(np.stack([np.maximum(c0f[g] - cap0[g], 0.0) for g in TG], axis=1), coords=[R, T])
            path = xr.DataArray(np.stack([c0f[g] for g in TG], axis=1), coords=[R, T])
            capv_f = m.add_variables(lower=0, coords=[R, T], name=f"capacity_p{offset}")
            m.add_constraints(capv_f - capv - later_th <= added, name=f"capacity_def_p{offset}")
            m.add_constraints(capv_f - build - later_th - retrofit * to_ccs.clip(min=0) - convert * to_gas.clip(min=0) <= path,
                              name=f"capacity_path_p{offset}")
            if yf >= RULE_YEAR:
                coal_only = xr.DataArray(np.array([1.0 if g == "coal" else 0.0 for g in TG]), coords=[T])
                m.add_constraints((capv_f * coal_only).sum("group") <= 0, name=f"coal_rule_p{offset}")
            if rule["switch"] and yf > rule["cofire_last"]:      # EPA 111: no coal cofiring after UEPA_CLCFYR
                conv_only = xr.DataArray(np.array([1.0 if g == "gas_conv" else 0.0 for g in TG]), coords=[T])
                m.add_constraints((capv_f * conv_only).sum("group") <= 0, name=f"cofire_rule_p{offset}")
            ren = totals(c0f, bw + later_w, bs + later_s, bb + later_b)
            pf = operate(f"_p{offset}", cs, c0f, capv_f, *ren, bh=FUTURE_BLOCK_HOURS, new_w=bw + later_w, new_s=bs + later_s)
            operating = operating + wgt * pf["operating"]
            weight_now += wgt
            # a plant built in this period pays its annual capital charge from here to the end of the horizon
            cap_f = capital_costs(snapshot, yb, cs)
            rest = sum(w2 for o2, w2 in weights.items() if o2 >= offset)
            future_capex = future_capex + rest * (
                (fb * xr.DataArray(np.stack([cap_f.get(g, np.zeros(NUM_R)) for g in TG], axis=1), coords=[R, T])).sum()
                + (fw * xr.DataArray(cap_f["wind"], coords=[R])).sum() + (fs * xr.DataArray(cap_f["solar"], coords=[R])).sum()
                + (fbb * xr.DataArray(cap_f["battery"], coords=[R])).sum())

    capex = (build * xr.DataArray(np.stack([capital.get(g, np.zeros(NUM_R)) for g in TG], axis=1), coords=[R, T])).sum()
    capex = capex + (bw * xr.DataArray(capital["wind"], coords=[R])).sum() + (bs * xr.DataArray(capital["solar"], coords=[R])).sum()
    capex = capex + (bb * xr.DataArray(capital["battery"], coords=[R])).sum() + step_premium
    if use_groups:
        saved = (rg * xr.DataArray(gcost, coords=[R, TR, K])).sum() + (forced * xr.DataArray(fom_exist["coal"], coords=[R])).sum()
        saved = saved + sum((retire.sel(group=g) * xr.DataArray(fom_made[g], coords=[R])).sum() for g in RETIRABLE_MADE)
        saved_coal = (rg.sel(group="coal") * xr.DataArray(gcost[:, RETIRABLE.index("coal"), :], coords=[R, K])).sum() \
            + (forced * xr.DataArray(fom_exist["coal"], coords=[R])).sum()
    else:
        saved = (retire * xr.DataArray(np.stack([fom_exist.get(g, fom_made.get(g, np.zeros(NUM_R))) for g in TG], axis=1), coords=[R, T])).sum()
        saved_coal = (retire.sel(group="coal") * xr.DataArray(fom_exist["coal"], coords=[R])).sum()
    retro = (retrofit * xr.DataArray(retro_annual, coords=[R])).sum()
    conv_cost = CONVERT_COST_KW * _crf(discount_rate(snapshot, year), 20.0) * 1.0e3 - (1.0 - CONVERT_FOM_ADJ) * fom_exist["coal"]
    retro = retro + (convert * xr.DataArray(conv_cost, coords=[R])).sum()
    m.add_objective(operating + weight_now * (capex - saved + retro) + future_capex + (weight_now - coal_weight) * saved_coal)
    opts = HORIZON_SOLVER_OPTIONS if (solver == "highs" and horizon and decide) else {}
    status, cond = m.solve(solver_name=solver, progress=progress, **opts)

    out = YearResult(year, f"{status}:{cond}", {}, {}, adds, rets, {}, np.zeros(NUM_R))
    if status != "ok":
        out.capacity = cap0
        return out
    sol = lambda v: np.asarray(v.solution.values)
    bld = sol(build)
    ret = sol(retire)
    rf = sol(retrofit)
    cv = sol(convert)
    builds = {g: np.zeros(NUM_R) for g in STATE_GROUPS}
    econ = {g: np.zeros(NUM_R) for g in STATE_GROUPS}
    for k, g in enumerate(TG):
        builds[g] = bld[:, k]
        econ[g] = ret[:, k]
    builds["wind"], builds["solar"], builds["battery"] = sol(bw), sol(bs), sol(bb)
    cap_out = {g: cap0[g] + builds[g] - econ[g] for g in STATE_GROUPS}
    cap_out["coal"] = cap_out["coal"] - rf
    cap_out["coal_ccs"] = cap_out["coal_ccs"] + rf
    cap_out["coal"] = cap_out["coal"] - cv
    cap_out["gas_conv"] = cap_out["gas_conv"] + cv
    for g in cap_out:
        cap_out[g] = np.maximum(cap_out[g], 0.0)
    out.capacity, out.builds, out.economic_retire, out.retrofit = cap_out, builds, econ, rf
    out.converted = cv
    w = case.weights[None, :, None] * BLOCK_HOURS
    gth = np.asarray(g_th.solution.transpose("region", "group", "day", "block").values)
    out.generation_twh = {g: (gth[:, k] * w).sum(axis=(1, 2)) / 1000.0 for k, g in enumerate(TG)}
    out.objective = float(m.objective.value)
    out.unserved_twh = float((sol(unserved) * w).sum() / 1000.0)
    out.reserve_shortfall_gw = float(sol(shortfall).sum())
    out.credits = credits
    hours = (case.weights * BLOCK_HOURS)[None, :, None]
    out.price = np.asarray(m.constraints["balance"].dual.transpose("region", "day", "block").values) / hours
    out.reserve_price = np.asarray(m.constraints["reserve_margin"].dual.values) / 1000.0     # k$/GW -> $/kW
    if use_groups:
        g_ret = sol(rg)
        out.group_retire = {g: g_ret[:, j, :] for j, g in enumerate(RETIRABLE)}
        share = np.divide(g_ret, gcap, out=np.zeros_like(gcap), where=gcap > 1e-9)
        out.group_share = {g: np.clip(share[:, j, :], 0.0, 1.0) for j, g in enumerate(RETIRABLE)}
        out.rule_retire = sol(forced)
    return out


# Capacity-LP groups folded into the dispatch model's groups. Steam in the restart already holds EIA's coal-to-gas
# conversions (prefix ng), so converted coal joins steam.
TO_DISPATCH = {"gas_cc_new": "gas_cc", "gas_ct_new": "gas_ct", "gas_conv": "steam"}


def dispatch_capacity(capacity: dict) -> dict:
    """A year's capacity (STATE_GROUPS) in the dispatch model's groups (dispatch.GROUPS), GW by region."""
    out = {g: np.zeros(NUM_R) for g in dispatch.GROUPS}
    for g, v in capacity.items():
        out[TO_DISPATCH.get(g, g)] = out[TO_DISPATCH.get(g, g)] + v
    return out


class CapacityPath:
    """The myopic loop, one year at a time, so a caller (run_model) can hand each year its own demand and prices.

    groups=True builds ECP's retirement groups each year from the year before's prices (the first year's come
    from a dispatch-only solve of that year) and tracks which plant-file units the LP has retired, so the
    cheapest-to-lose units go first.
    """

    def __init__(self, snapshot, first: int = START_YEAR, solver: str = "highs", groups: bool = True):
        self.snapshot, self.solver, self.groups = snapshot, solver, groups
        self.cap = initial_capacity(snapshot, first - 1)
        self.next_year = first
        u = plants.load_units()
        self.alive = np.ones(len(u.summer_mw))
        self.price = None
        self.results: dict[int, YearResult] = {}

    def step(self, year: int, case=None) -> YearResult:
        """Solve `year` (the next one in order). `case` overrides the reference run's dispatch case (net load,
        fuel and carbon prices); without it the year runs on the reference case."""
        if year in self.results:
            return self.results[year]
        if year != self.next_year:
            raise ValueError(f"capacity path is at {self.next_year}, asked for {year}")
        snap, u = self.snapshot, plants.load_units()
        case = case if case is not None else dispatch.build_case(snap, year, "none")
        case = replace(case, credit_share=self.credit_share(year))
        grp = None
        if self.groups:
            if self.price is None:
                self.price = solve_year(snap, year, self.cap, self.solver, decide=False, case=case).price
            hours = np.broadcast_to((case.weights * BLOCK_HOURS)[:, None], self.price.shape[1:]).ravel()
            flat = self.price.reshape(NUM_R, -1)
            grp = {g: retire_groups.build(year, g, self.alive, unit_costs(case, g), flat, hours, 1.0 - case.avail[g][0])
                   for g in RETIRABLE}
        res = solve_year(snap, year, self.cap, self.solver, groups=grp, case=case, recent_adds=self.recent_adds(year))
        if not res.status.startswith("ok"):
            raise RuntimeError(f"{year}: {res.status}")
        if self.groups:
            for g in RETIRABLE:
                self.alive = retire_groups.retire_units(self.alive, grp[g], res.group_share[g])
            on = np.isin(u.efd_type, dispatch.EXISTING_TYPES["coal"]) & plants.online(year) & (u.retire_year >= 9999)
            base = np.zeros(NUM_R)
            np.add.at(base, u.region[on] - 1, u.summer_mw[on] * self.alive[on] / 1000.0)
            self.alive = retire_groups.take_pro_rata(self.alive, on, res.retrofit + res.converted + res.rule_retire, base)
        self.price = res.price
        self.cap = res.capacity
        self.results[year] = res
        self.next_year = year + 1
        return res

    def recent_adds(self, year: int, n: int = 5) -> dict:
        """Build group -> national GW added in each of the n years before `year` (oldest first), for ECP's build
        steps: this path's planned adds and builds, and the reference run's additions for years before it."""
        from nems_open.emm import capacity_report
        out = {}
        for g, (state, prefixes) in STEP_HISTORY.items():
            vals = []
            for yr in range(year - n, year):
                r = self.results.get(yr)
                if r is not None:
                    vals.append(sum(float(r.planned_adds.get(s, np.zeros(NUM_R)).sum()) for s in state)
                                + float(r.builds.get(g, np.zeros(NUM_R)).sum()))
                else:
                    vals.append(max(capacity_report.eia_additions(self.snapshot, yr, prefixes)
                                    - capacity_report.eia_additions(self.snapshot, yr - 1, prefixes), 0.0))
            out[g] = vals
        return out

    def credit_share(self, year: int) -> dict:
        """Share of each capture group's capacity still earning 45Q in `year` (dispatch.credit_share), from this
        path's own year-end capacity, and the reference run's before the path starts. A year not yet solved counts
        at last year's capacity: its own retrofits start in it and earn the credit only up to 2038, when no
        retrofit after that earns any."""
        rule = dispatch.credit_rule(self.snapshot)
        first = min(self.results, default=self.next_year)
        year_end = {}
        for t in range(rule[0] - 1, year + 1):
            if t in self.results:
                c = dispatch_capacity(self.results[t].capacity)
                year_end[t] = {g: c[g] for g in dispatch.CAPTURE_GROUPS}
            elif t < first:
                year_end[t] = dispatch.restart_capture_capacity(self.snapshot, t)
        if year not in year_end:
            c = dispatch_capacity(self.cap)
            year_end[year] = {g: c[g] for g in dispatch.CAPTURE_GROUPS}
        return dispatch.credit_share(year_end, year, rule)


def run(snapshot, first: int = START_YEAR, last: int = 2035, solver: str = "highs", groups: bool = True,
        log=None) -> list:
    """The myopic loop on the reference run's demand and prices. Returns one YearResult per year."""
    path = CapacityPath(snapshot, first, solver, groups)
    results = []
    for yr in range(first, last + 1):
        res = path.step(yr)
        results.append(res)
        if log:
            log(res)
    return results
