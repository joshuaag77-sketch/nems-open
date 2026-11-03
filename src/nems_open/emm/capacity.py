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

from dataclasses import dataclass, field

import linopy
import numpy as np
import pandas as pd
import xarray as xr

from nems_open.emm import db, dispatch, history, load, plants, regions, technology
from nems_open.paths import INPUT
from nems_open.xlsx_ranges import named_ranges

NUM_R = regions.NUM_EMM
START_YEAR = 2025
FIRST_UNPLANNED_YEAR = 2027      # EIA's first model-chosen builds come online in 2027 (ECP plans about three years ahead)
RULE_YEAR = 2032                 # coal without CCS must retire from this year
RETROFIT_LIMIT_GW = 3.0          # national CCS retrofits per year (UPCQMAX in ecpdaty.xlsx)
RETROFIT_MIN_MW = 500.0          # smallest unit that can be retrofitted (UPCCSCAP)
RETROFIT_MAX_HEAT_RATE = 12000.0 # least efficient unit that can be retrofitted (UPCCSHRT)
RESERVE_SHORTFALL_COST = 2.0e5  # k$ per GW-year, about 200 1987$/kW-year, for missing the reserve margin
REAL_DISCOUNT_RATE = 0.065       # assumption: real cost of capital for new plants
# How fast the industry can build. An assumption, not EIA data: ecpdaty.xlsx sets no annual limit (999.9)
# and relies on resource supply curves that are not in the restart, so without these the LP builds
# hundreds of GW of wind in one year when the tax credit makes it nearly free. (Retirements use EIA's own
# rule, below.)
ANNUAL_BUILD_LIMIT_GW = {"gas_cc_new": 30.0, "gas_ccs": 10.0, "gas_ct_new": 30.0, "wind": 30.0, "solar": 60.0, "battery": 30.0}
CREDIT_YEARS = 12.0              # years a plant earns the 45Q credit (TCS45Q/I_45Q_DURATION)
CCS_CAPACITY_FACTOR = 0.8        # assumed, to value the credit when deciding to build
BLOCK_HOURS = 3
BLOCKS = 24 // BLOCK_HOURS

TG = ("coal", "coal_ccs", "gas_cc", "gas_cc_new", "gas_ccs", "gas_ct", "gas_ct_new", "steam")
BASE_OF = {"gas_cc_new": "gas_cc", "gas_ct_new": "gas_ct"}      # inherits fuel, outage and limits
FIXED = ("nuclear", "hydro", "other", "pumped")
STATE_GROUPS = TG + FIXED + ("wind", "solar", "battery")

# Plant types that can be built, their ECP type, and the dispatch group the new capacity joins.
BUILDS = {"gas_cc_new": "AC", "gas_ccs": "CS", "gas_ct_new": "AT", "wind": "WN", "solar": "PV", "battery": "DS"}
RETIRABLE = ("coal", "gas_cc", "gas_ct", "steam")

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


def max_retirement_rate(year: int) -> float:
    """EIA's cap on economic retirements, as a share of a region's capacity in one year.

    emmcntl.txt, %MAX RET RATE%: UPRETRT0 (3%) in the first ECP year, rising UPRETCHG (1 point) a year to
    UPRETRTL (6%). EP$RET in uecp.f applies it to each region's total capacity of every type.
    """
    lines = (INPUT / "emm" / "emmcntl.txt").read_text(encoding="latin-1").splitlines()
    row = next(l for l in lines if l.lstrip().startswith("'MAX RET'")).split()
    first, last, step = float(row[3]), float(row[4]), float(row[5])         # fields: 'MAX', 'RET', UPRETRAT, UPRETRT0, UPRETRTL, UPRETCHG
    return min(first + step * (year - START_YEAR), last)


def _crf(rate: float, years: float) -> float:
    return rate / (1.0 - (1.0 + rate) ** -years)


def _credit_lost_share(life: float) -> float:
    """Share of a flat annual 45Q credit that a plant of this life does not get, because the credit
    lasts only I_45Q_DURATION (12) years. The dispatch model pays the credit every year; a build
    decision spreads the capital cost over the whole life, so the unpaid part is charged back."""
    annuity = lambda n: (1.0 - (1.0 + REAL_DISCOUNT_RATE) ** -n)
    return 1.0 - annuity(CREDIT_YEARS) / annuity(life)


def initial_capacity(snapshot, year_before: int) -> dict:
    """Year-end capacity by group in the year before the first solve, from the reference run."""
    y = year_before - history.FIRST_YEAR
    cap = {g: dispatch._ucap(snapshot, p, y) for g, p in dispatch.CAPACITY_PREFIXES.items()}
    cap["coal"] = np.maximum(cap["coal"] - cap["coal_ccs"], 0.0)
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


def _blocks(a: np.ndarray) -> np.ndarray:
    """Average the 24 hours of a (..., 36, 24) array into BLOCKS blocks."""
    return a.reshape(a.shape[:-1] + (BLOCKS, BLOCK_HOURS)).mean(axis=-1)


def solve_year(snapshot, year: int, cap_in: dict, solver: str = "highs", progress: bool = False) -> YearResult:
    y = year - history.FIRST_YEAR
    case = dispatch.build_case(snapshot, year, "none")
    adds, rets = dated_changes(year)
    cap0 = {g: np.maximum(cap_in[g] + adds[g] - rets[g], 0.0) for g in STATE_GROUPS}

    # --- costs of building ---
    params = technology.type_parameters()
    codes = technology.ecp_codes()
    reg = technology.regional_costs()
    sub = named_ranges(technology.ECPDATY, "SUBSIDY")
    itc_tab = np.array(sub["UPCSBYR"]).reshape(80, -1)
    ptc_tab = np.array(sub["UPGSUBYR"]).reshape(80, -1)
    col = year - 2010
    hr_new_all = np.array(named_ranges(technology.ECPDATY, "OPTLRN")["UPPHRTN"])

    capital = {}      # group -> (25,) k$ per GW-year, net of ITC and PTC
    for g, code in BUILDS.items():
        i = codes.index(code)
        ovn = params["overnight_cost"][i] * reg["regional_multiplier"][:NUM_R, i] * reg["area_multiplier"][:NUM_R, i]
        itc = max(itc_tab[i, col], 0.0)
        annual = ovn * (1.0 - itc) * _crf(REAL_DISCOUNT_RATE, params["economic_life"][i]) + params["fom"][i]
        ptc = max(ptc_tab[i, col], 0.0)
        if g in ("wind", "solar"):
            cf = case.profile[g].mean(axis=(1, 2))
            annual = annual - ptc * cf * 8.76         # $/MWh x GWh per MW-year -> $/kW-year
        if g in dispatch.CAPTURE_GROUPS:
            tons = case.heat_rate[g] / 1000.0 * dispatch.CO2_PER_TBTU[dispatch.CAPTURE_GROUPS[g]] * dispatch.CAPTURE_RATE
            annual = annual + _credit_lost_share(params["economic_life"][i]) * case.credit_45q * tons * CCS_CAPACITY_FACTOR * 8.76
        capital[g] = annual * 1.0e3                   # $/kW-year -> k$ per GW-year

    # --- characteristics of the groups ---
    heat, vom, oil_share = dict(case.heat_rate), dict(case.vom), dict(case.oil_share)
    avail = dict(case.avail)
    for g, base in BASE_OF.items():
        i = codes.index(BUILDS[g])
        heat[g] = np.full(NUM_R, float(hr_new_all[i]))
        vom[g] = np.full(NUM_R, float(params["vom"][i]))
        oil_share[g] = np.zeros(NUM_R)
        avail[g] = avail[base]
    heat["gas_ccs"] = np.full(NUM_R, float(hr_new_all[codes.index("CS")]))
    vom["gas_ccs"] = np.full(NUM_R, float(params["vom"][codes.index("CS")]))
    max_cf = {g: np.full(NUM_R, avail[g][1]) for g in TG}

    # --- existing plant fixed O&M, CCS retrofit data ---
    u = plants.load_units()
    tb = db.table("V_EMM_PLTF860")
    on = plants.online(year)
    fom_exist = {}
    for g in RETIRABLE:
        mask = on & np.isin(u.efd_type, dispatch.EXISTING_TYPES[g])
        fom_exist[g] = _weighted_by_region(tb["T_FOM"], u.summer_mw, mask, 20.0) * 1.0e3        # k$ per GW-year
    coal_mask = on & np.isin(u.efd_type, dispatch.EXISTING_TYPES["coal"])
    elig = coal_mask & (u.summer_mw >= RETROFIT_MIN_MW) & (u.heat_rate <= RETROFIT_MAX_HEAT_RATE) & (tb["T_CCSHR"] > 0) \
        & (tb["T_CCSHR"] < dispatch.CCS_HEAT_RATE_MAX)
    elig_gw = np.zeros(NUM_R)
    np.add.at(elig_gw, u.region[elig] - 1, u.summer_mw[elig] / 1000.0)
    elig_gw = np.minimum(elig_gw, cap0["coal"])
    retro_cost = _weighted_by_region(tb["T_CCSROV"], u.summer_mw, elig, 1100.0)
    retro_fom = _weighted_by_region(tb["T_CCSF"], u.summer_mw, elig, 8.0)
    retro_tons = case.heat_rate["coal_ccs"] / 1000.0 * dispatch.CO2_PER_TBTU["coal"] * dispatch.CAPTURE_RATE
    retro_lost = _credit_lost_share(20.0) * case.credit_45q * retro_tons * 0.6 * 8.76     # coal runs about 60%
    retro_annual = (retro_cost * _crf(REAL_DISCOUNT_RATE, 20.0) + retro_fom + retro_lost) * 1.0e3

    # --- time slices ---
    R = pd.Index(np.arange(1, NUM_R + 1), name="region")
    D = pd.Index(np.arange(36), name="day")
    Bk = pd.Index(np.arange(BLOCKS), name="block")
    T = pd.Index(list(TG), name="group")
    MO = pd.Index(np.arange(12), name="month")
    month_of_day = np.repeat(np.arange(12), 3)
    hours_w = xr.DataArray(case.weights * BLOCK_HOURS, coords=[D])       # hours per year each slice stands for
    ones = xr.DataArray(np.ones((NUM_R, 36, BLOCKS)), coords=[R, D, Bk])

    def by_region(a):
        return xr.DataArray(np.asarray(a, dtype=float), coords=[R]) * ones

    load_hr = case.net_load_twh[:, None, None] * 1000.0 * case.shapes            # GW in each hour
    # EIA sets reserve margins region by region, so the capacity to cover is the sum of the regions' own peaks
    # (about 6% above the national coincident peak), not the coincident peak.
    peak_gw = float(load_hr.max(axis=(1, 2)).sum())
    credits = capacity_credits(case, cap0, load_hr, np.repeat(np.arange(12), 3))
    load_gw = xr.DataArray(_blocks(load_hr), coords=[R, D, Bk])
    prof = {k: xr.DataArray(_blocks(v), coords=[R, D, Bk]) for k, v in case.profile.items()}

    def cf_of(group):
        return xr.DataArray(case.monthly_cf[group][:, month_of_day], coords=[R, D]) * ones

    m = linopy.Model()
    cap_const = xr.DataArray(np.stack([cap0[g] for g in TG], axis=1), coords=[R, T])
    room = 100.0 if year >= FIRST_UNPLANNED_YEAR else 0.0
    buildable = xr.DataArray(np.stack([np.full(NUM_R, room if g in BUILDS else 0.0) for g in TG], axis=1), coords=[R, T])
    retirable = xr.DataArray(np.stack([cap0[g] if g in RETIRABLE else np.zeros(NUM_R) for g in TG], axis=1), coords=[R, T])
    build = m.add_variables(lower=0, upper=buildable, name="build")
    retire = m.add_variables(lower=0, upper=retirable, name="retire")
    retrofit = m.add_variables(lower=0, upper=xr.DataArray(elig_gw * (room > 0), coords=[R]), name="retrofit")
    bw = m.add_variables(lower=0, upper=room, coords=[R], name="build_wind")
    bs = m.add_variables(lower=0, upper=room, coords=[R], name="build_solar")
    bb = m.add_variables(lower=0, upper=room, coords=[R], name="build_battery")
    m.add_constraints(retrofit.sum() <= RETROFIT_LIMIT_GW, name="retrofit_limit")
    m.add_constraints(bw.sum() <= ANNUAL_BUILD_LIMIT_GW["wind"], name="limit_build_wind")
    m.add_constraints(bs.sum() <= ANNUAL_BUILD_LIMIT_GW["solar"], name="limit_build_solar")
    m.add_constraints(bb.sum() <= ANNUAL_BUILD_LIMIT_GW["battery"], name="limit_build_battery")
    to_ccs = xr.DataArray(np.array([1.0 if g == "coal_ccs" else (-1.0 if g == "coal" else 0.0) for g in TG]), coords=[T])
    cap_th = cap_const + build - retire + retrofit * to_ccs
    for g, limit in ANNUAL_BUILD_LIMIT_GW.items():
        if g in TG:
            m.add_constraints(build.sel(group=g).sum() <= limit, name=f"limit_build_{g}")
    # EIA's cap: economic retirements in a region may not exceed a share of its total capacity (the carbon rule's
    # forced coal retirements from RULE_YEAR are exempt, as they are policy, not economics).
    rate = max_retirement_rate(year)
    region_total = xr.DataArray(sum(cap0[g] for g in STATE_GROUPS), coords=[R])
    econ = retire.sel(group=[g for g in TG if g != "coal"]).sum("group")
    if year < RULE_YEAR:
        econ = econ + retire.sel(group="coal")
    m.add_constraints(econ <= rate * region_total, name="retirement_rate")
    capv = m.add_variables(lower=0, coords=[R, T], name="capacity")
    m.add_constraints(capv - cap_th == 0, name="capacity_def")
    if year >= RULE_YEAR:
        coal_only = xr.DataArray(np.array([1.0 if g == "coal" else 0.0 for g in TG]), coords=[T])
        m.add_constraints((capv * coal_only).sum("group") == 0, name="coal_rule")

    one_minus_for = xr.DataArray(np.array([1.0 - avail[g][0] for g in TG]), coords=[T])
    g_th = m.add_variables(lower=0, coords=[R, T, D, Bk], name="gen")
    m.add_constraints(g_th - capv * one_minus_for <= 0, name="gen_limit")
    mcf = xr.DataArray(np.stack([max_cf[g] for g in TG], axis=1), coords=[R, T])
    m.add_constraints((g_th * hours_w).sum(["day", "block"]) - capv * (mcf * 8760.0) <= 0, name="energy_limit")

    cost = np.zeros((NUM_R, len(TG)))
    for k, g in enumerate(TG):
        oil_price = case.price["residual"] if g == "steam" else case.price["distillate"]
        is_coal = g.startswith("coal")
        fuel = (1 - oil_share[g]) * case.price["coal" if is_coal else "gas"] + oil_share[g] * oil_price
        cost[:, k] = heat[g] / 1000.0 * fuel + vom[g]
        if g in dispatch.CAPTURE_GROUPS:
            cost[:, k] -= case.credit_45q * heat[g] / 1000.0 * dispatch.CO2_PER_TBTU[dispatch.CAPTURE_GROUPS[g]] * dispatch.CAPTURE_RATE
    cost_da = xr.DataArray(cost, coords=[R, T])

    # wind, solar, battery: existing plus new
    wind_out = (bw + xr.DataArray(cap0["wind"], coords=[R])) * prof["wind"]
    solar_out = (bs + xr.DataArray(cap0["solar"], coords=[R])) * prof["solar"]
    fixed = by_region(cap0["nuclear"]) * cf_of("nuclear") + by_region(cap0["other"]) * cf_of("other")

    hy_cap = by_region(cap0["hydro"])
    g_hy = m.add_variables(lower=0, upper=hy_cap, name="hydro")
    month_w = xr.DataArray(np.eye(12)[month_of_day], coords=[D, MO])
    days_in_month = np.array([case.weights[month_of_day == mo].sum() for mo in range(12)])
    budget = xr.DataArray(case.monthly_cf["hydro"] * cap0["hydro"][:, None] * days_in_month[None, :] * 24.0, coords=[R, MO])
    m.add_constraints((g_hy * (hours_w * month_w)).sum(["day", "block"]) <= budget, name="hydro_budget")

    net_storage = 0
    sto_cap = {"battery": xr.DataArray(cap0["battery"], coords=[R]) + bb, "pumped": xr.DataArray(cap0["pumped"], coords=[R])}
    for name, (dur, rte) in STORAGE_HOURS.items():
        eta = np.sqrt(rte)
        ch = m.add_variables(lower=0, coords=[R, D, Bk], name=f"{name}_charge")
        di = m.add_variables(lower=0, coords=[R, D, Bk], name=f"{name}_discharge")
        soc = m.add_variables(lower=0, coords=[R, D, Bk], name=f"{name}_soc")
        m.add_constraints(ch - sto_cap[name] <= 0, name=f"{name}_ch_cap")
        m.add_constraints(di - sto_cap[name] <= 0, name=f"{name}_di_cap")
        m.add_constraints(soc - dur * sto_cap[name] <= 0, name=f"{name}_soc_cap")
        m.add_constraints(soc - soc.roll(block=1) - BLOCK_HOURS * eta * ch + BLOCK_HOURS * di / eta == 0, name=f"{name}_balance")
        net_storage = net_storage + di - ch

    links = case.links
    L = pd.Index(np.arange(len(links["exporter"])), name="link")
    cap_l = xr.DataArray(links["capacity_gw"], coords=[L, D]) * xr.DataArray(np.ones(BLOCKS), coords=[Bk])
    trade = m.add_variables(lower=0, upper=cap_l.transpose("link", "day", "block"), name="trade")
    into = np.zeros((NUM_R, len(L)))
    outof = np.zeros((NUM_R, len(L)))
    into[links["importer"], np.arange(len(L))] = 1.0 - links["loss"]
    outof[links["exporter"], np.arange(len(L))] = 1.0
    trade_in = (trade * xr.DataArray(into, coords=[R, L])).sum("link")
    trade_out = (trade * xr.DataArray(outof, coords=[R, L])).sum("link")

    spill = m.add_variables(lower=0, coords=[R, D, Bk], name="spill")
    unserved = m.add_variables(lower=0, coords=[R, D, Bk], name="unserved")
    m.add_constraints(g_th.sum("group") + g_hy + net_storage + unserved - spill + trade_in - trade_out
                      + wind_out + solar_out + fixed == load_gw, name="balance")

    # national reserve margin on firm capacity
    rm = float(np.mean(db.table("V_EMM_ECPDAT_REG")["EPMRM"][db.table("V_EMM_ECPDAT_REG")["EMM_REG"] <= NUM_R]))
    firm = (capv * one_minus_for).sum()
    firm = firm + (bw + xr.DataArray(cap0["wind"], coords=[R])).sum() * credits["wind"]
    firm = firm + (bs + xr.DataArray(cap0["solar"], coords=[R])).sum() * credits["solar"]
    firm = firm + (bb + xr.DataArray(cap0["battery"], coords=[R])).sum() * credits["battery"]
    const_firm = sum(float(cap0[g].sum()) * FIRM_CREDIT[g] for g in ("nuclear", "other"))
    const_firm += float(cap0["hydro"].sum()) * credits["hydro"] + float(cap0["pumped"].sum()) * credits["pumped"]
    shortfall = m.add_variables(lower=0, name="reserve_shortfall")
    m.add_constraints(firm + shortfall >= (1.0 + rm) * peak_gw - const_firm, name="reserve_margin")

    capex = (build * xr.DataArray(np.stack([capital.get(g, np.zeros(NUM_R)) for g in TG], axis=1), coords=[R, T])).sum()
    capex = capex + (bw * xr.DataArray(capital["wind"], coords=[R])).sum() + (bs * xr.DataArray(capital["solar"], coords=[R])).sum()
    capex = capex + (bb * xr.DataArray(capital["battery"], coords=[R])).sum()
    saved = (retire * xr.DataArray(np.stack([fom_exist.get(g, np.zeros(NUM_R)) for g in TG], axis=1), coords=[R, T])).sum()
    retro = (retrofit * xr.DataArray(retro_annual, coords=[R])).sum()
    operating = (g_th * cost_da * hours_w).sum() + (unserved * (dispatch.UNSERVED_COST * hours_w)).sum() \
        + (trade * (xr.DataArray(links["cost"], coords=[L]) * hours_w)).sum() + (g_hy * (0.01 * hours_w)).sum()
    m.add_objective(operating + capex - saved + retro + shortfall * RESERVE_SHORTFALL_COST)
    status, cond = m.solve(solver_name=solver, progress=progress)

    out = YearResult(year, f"{status}:{cond}", {}, {}, adds, rets, {}, np.zeros(NUM_R))
    if status != "ok":
        out.capacity = cap0
        return out
    sol = lambda v: np.asarray(v.solution.values)
    bld = sol(build)
    ret = sol(retire)
    rf = sol(retrofit)
    builds = {g: np.zeros(NUM_R) for g in STATE_GROUPS}
    econ = {g: np.zeros(NUM_R) for g in STATE_GROUPS}
    for k, g in enumerate(TG):
        builds[g] = bld[:, k]
        econ[g] = ret[:, k]
    builds["wind"], builds["solar"], builds["battery"] = sol(bw), sol(bs), sol(bb)
    cap_out = {g: cap0[g] + builds[g] - econ[g] for g in STATE_GROUPS}
    cap_out["coal"] = cap_out["coal"] - rf
    cap_out["coal_ccs"] = cap_out["coal_ccs"] + rf
    for g in cap_out:
        cap_out[g] = np.maximum(cap_out[g], 0.0)
    out.capacity, out.builds, out.economic_retire, out.retrofit = cap_out, builds, econ, rf
    w = case.weights[None, :, None] * BLOCK_HOURS
    gth = np.asarray(g_th.solution.transpose("region", "group", "day", "block").values)
    out.generation_twh = {g: (gth[:, k] * w).sum(axis=(1, 2)) / 1000.0 for k, g in enumerate(TG)}
    out.objective = float(m.objective.value)
    out.unserved_twh = float((sol(unserved) * w).sum() / 1000.0)
    out.reserve_shortfall_gw = float(shortfall.solution)
    out.credits = credits
    return out


def run(snapshot, first: int = START_YEAR, last: int = 2035, solver: str = "highs") -> list:
    """The myopic loop. Returns one YearResult per year."""
    cap = initial_capacity(snapshot, first - 1)
    results = []
    for yr in range(first, last + 1):
        res = solve_year(snapshot, yr, cap, solver)
        if not res.status.startswith("ok"):
            raise RuntimeError(f"{yr}: {res.status}")
        results.append(res)
        cap = res.capacity
    return results
