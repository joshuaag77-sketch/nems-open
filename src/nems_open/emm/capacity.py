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

from nems_open.emm import (capacity_credit, db, dispatch, ecp_cost, ecp_load, history, load, plants, regions, retire_groups, rps,
                           technology)
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
# The conversion cost is each unit's own from the plant file, T_NG_COST plus T_NG_TRAN (the gas lateral), as ECP's
# OV_CLtNG (uecp.f EP$COAL; udat.f 9302); units with no cost there cannot convert. CONVERT_COST_KW (1987$/kW) is
# only the fallback for a region whose eligible units carry no cost.
CONVERT_FOM_ADJ, CONVERT_VOM_ADJ, CONVERT_HR_PENALTY = 0.67, 0.75, 0.05
CONVERT_COST_KW = 200.0
RETIREMENT_HURDLE = 0.05         # emmcntl.txt %RET HURDLE RATES%, fossil (UPRETFHU)
AGE_ADDER_1987 = 5.0 / 1.336922   # $/kW-year for units 30+ years old: UPXTRA (%XTRA OandM%, 1999$) in 1987$
# k$ per GW for missing the reserve margin: EP$MRM,4's escape RDBLDX costs 1500 1987$/kW (undiscounted, so a little more
# against planning year 2's rows). The LP had 200, below ECP's own step 2 turbine once steps cost their lifetime.
RESERVE_SHORTFALL_COST = 1.5e6
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
    "gas_ct_new": (("gas_ct", "gas_ct_new"), ("ct", "ic")), "wind": (("wind",), ("wn", "wl")),
    "solar": (("solar",), ("pv", "pt", "st")), "battery": (("battery",), ("ds",)),
}


# Plant-file ECP types (ECPcd) whose planned units fill each build type's first step: ESTYRPLN is kept by the unit's
# own ECP type, with PT counted as PV and WL as WN (udat.f 8273-8278). Planned gas units are EC/ET, not AC/AT, and
# offshore wind is WF, so none of them use up the LP's combined cycle, turbine or onshore wind steps.
PLANNED_STEP_TYPES = {"gas_cc_new": ("AC",), "gas_ccs": ("CS",), "gas_ct_new": ("AT",), "wind": ("WN", "WL"),
                      "solar": ("PV", "PT"), "battery": ("DS",)}


# State mandates (plants.floors): offshore wind, 27 GW in 2030-2050, and batteries, 11 GW in 2026-2035. Off: plant file only.
STATE_FLOORS = True
FLOOR_GROUP = {"WF": "wind", "DS": "battery"}


def planned_in_step(year: int, group: str) -> float:
    """National GW of plant-file units and state floors online in `year` that sit in build group `group`'s first ECP step."""
    u = plants.load_units()
    m = (u.online_year == year) & np.isin(u.ecp_type, PLANNED_STEP_TYPES.get(group, ()))
    gw = float(u.summer_mw[m].sum()) / 1000.0
    if STATE_FLOORS:
        gw += float(plants.floor_adds_gw(year, PLANNED_STEP_TYPES.get(group, ())).sum())
    return gw


def offshore_adds(group: str, year: int) -> float:
    """National GW of offshore wind (plant file and floors) online in `year`: in the LP's wind group, but WF keeps its own
    ESTYRADD (udat.f 8273-8278), so it is no part of WN's build-step history. 0 for other groups."""
    if group != "wind":
        return 0.0
    u = plants.load_units()
    gw = float(u.summer_mw[(u.online_year == year) & (u.ecp_type == "WF")].sum()) / 1000.0
    return gw + (float(plants.floor_adds_gw(year, ("WF",)).sum()) if STATE_FLOORS else 0.0)


def offshore_gw(year: int) -> np.ndarray:
    """Offshore wind in service at the end of `year` from the plant file and the floors, (25,) GW."""
    out = plants.capacity_gw(year, ("WFS",))[:NUM_R].copy()
    if STATE_FLOORS:
        f = plants.floors()
        m = (f["ecp_type"] == "WF") & (f["online_year"] <= year) & (f["retire_year"] > year)
        np.add.at(out, f["region"][m] - 1, f["mw"][m] / 1000.0)
    return out


STEP_FLOOR_OF = {"AC": "CC", "AT": "CT"}     # advanced type -> conventional type whose ESTCPADD it may not fall below
# ucape.f ELSTCAP keeps a history per ECP type (ESTYRADD, udat.f 8276, from each unit's own ECPcd): AC counts only AC,
# CC counts CC plus EC (ucape.f 62), and then ESTCPADD(AC) = max(ESTCPADD(AC), ESTCPADD(CC)) (ucape.f 72-73; AT and CT
# alike, CT counting ET). The LP pooled them: the gas_cc_new history was the plan's EC units plus its own AC builds in
# one sum per year, and the CC floor was ESTMNADD alone. On: the advanced type's history is its own (LP builds plus
# plant-file units of that ECP type), the conventional type's is the plant file's CC + EC (CT + ET) units by online
# year, and the steps use the larger ESTCPADD. Off: pooled.
STEP_SEPARATE_HISTORY = True
# ECP builds a second combined cycle, CC, beside AC: the same heat rate, its own UPOVR and its own ESTCPLIM steps and
# history (CC + EC). The oracle's ECP builds it online in 2028, 2029, 2032 and 2039, up to its 5 GW first step. It shares
# the gas_cc_new group here. Tried and dropped when the steps cost a year's premium (docs/capacity.md, ecp-lookahead);
# with the lifetime premium the 2032 reserve row is short without it. Off: AC only.
CONVENTIONAL_CC = True
STEP_CONVENTIONAL_TYPES = {"gas_cc_new": ("CC", "EC"), "gas_ct_new": ("CT", "ET")}
STEP_OWN_TYPES = {"gas_cc_new": ("AC",), "gas_ct_new": ("AT",)}


def plant_file_adds(year: int, ecp_types) -> float:
    """National GW of plant-file units of these ECP types online in `year`, with ESTYRADD's vintage filter
    (WVIN 1, 2, 3 or above 9, not 15; udat.f 8273)."""
    u = plants.load_units()
    vin = np.asarray(u.vintage)
    ok = ((vin == 1) | (vin == 2) | (vin == 3) | (vin > 9)) & (vin != 15)
    m = ok & (u.online_year == year) & np.isin(u.ecp_type, ecp_types)
    return float(u.summer_mw[m].sum()) / 1000.0

# ECP's battery build columns (uecp.f CALC_STORAGE_VAL,11-12): one column per region in the first elasticity step only
# (IS = 1, row LUDSST1), so batteries never reach the 1.4 x and 2.25 x steps, and each region's column is bounded by
# the ReStore test battery it used, at most BatteryIncrement = MAX_PERCENT x MAX_LOAD (uecp.f 37838-37896: 1% of the
# region's top hourly load in 2017, a point a year to 5% from 2021; emmcntl.txt %DS PARAMS%). MAX_LOAD is ECP year E's
# DUCK_SYSTEM_LOAD + DEM_ADJ (uecp.f 860), and E's year-1 builds come online in E + 1. ReStore's own use of the test
# battery (less than all of it in a few western regions) is not ported; the bound is the whole increment.
ECP_STORAGE_BUILDS = True


def battery_increment_share(ecp_year: int) -> float:
    """MAX_PERCENT for ECP year `ecp_year`: Battery_Initial_Percent in 2017, plus Battery_Incremental_Percent a year,
    at most Battery_Maximum_Percent (emmcntl.txt %DS PARAMS%, uecp.f 37838-37842)."""
    lines = (INPUT / "emm" / "emmcntl.txt").read_text(encoding="latin-1").splitlines()
    k = next(i for i, l in enumerate(lines) if l.startswith("%DS PARAMS"))
    row = next(l for l in lines[k + 1:] if not l.lstrip().startswith("#")).split()
    first, step, top = float(row[5]), float(row[6]), float(row[7])
    if ecp_year < 2017:
        return 0.0
    return min(first + step * (ecp_year - 2017), top)


def battery_build_limit(snapshot, year: int, case) -> np.ndarray:
    """(25,) GW: the most batteries ECP lets a region build online in `year` (its year-1 columns of the year - 1 solve),
    BatteryIncrement = MAX_PERCENT x MAX_LOAD. MAX_LOAD is the top hour of LDSM's system load for year - 1 plus
    DEM_ADJ (firm contracts, less cogeneration, plus Mexico), moved to this run's demand as the reserve row's load is;
    without the LDSM dumps, the LP's own load shape for `year`."""
    e = year - 1
    sy = ecp_load.system_load(e)
    if sy is None:
        hourly = case.net_load_twh[:, None, None] * 1000.0 * case.shapes
    else:
        hourly = ecp_load.follow_run(sy, case.net_load_twh, _reference_case(snapshot, year).net_load_twh, case.flat_twh)
    adj = ecp_load.firm_contracts(e) + ecp_load.cogen_adjustment(snapshot, e)
    top = (hourly.reshape(NUM_R, -1) + adj[:, None]).max(axis=1)
    return battery_increment_share(e) * np.maximum(top, 0.0)


def build_steps(code: str, recent: list, planned: float = 0.0, floor_recent: list | None = None) -> list:
    """[(GW bound, capital cost multiplier)] for this year's national builds of ECP type `code`, from the last five
    years' national additions (GW, oldest first), as ucape.f ELSTCAP and ELSTELA. `planned`: the plant file's
    additions of the type online this year (GW); ECP puts them in the first step (uecp.f EP$ELAST,2-3: a fixed
    column of min(ESTCPLIM step 1, ESTYRPLN) in the step-1 row), so the model's own builds get only what is left
    of it. Without that, 2027's 26 GW of planned solar left the LP a full 44 GW first step on top. `floor_recent`:
    the conventional type's own five years (STEP_SEPARATE_HISTORY), whose ESTCPADD the advanced type may not fall
    below; without it, only the conventional type's ESTMNADD floor."""
    b = named_ranges(technology.ECPDATY, "BLDINFO")
    i = technology.ecp_codes().index(code)
    stp = np.array(b["ESTCPSTP"], dtype=float).reshape(len(b["ESTSWTCH"]), -1)[i]
    csinc, cpinc = float(b["ESTCSINC"][i]), float(b["ESTCPINC"][i])
    add = float(b["ESTMNADD"][i]) / 1000.0 / (1.0 + stp[0])
    n = len(recent)
    for k, a in enumerate(recent):
        add = max(add, float(a) * (0.5 + 0.5 * (k + 1) / n))
    if code in STEP_FLOOR_OF:
        # ucape.f ELSTCAP: ESTCPADD(AC) = max(ESTCPADD(AC), ESTCPADD(CC)), likewise AT and CT. The conventional type's
        # ESTCPADD is at least its ESTMNADD / (1 + ESTCPSTP step 1), 5,000 MW / 1.25 = 4 GW, or its own weighted history
        # (CC + EC units, `floor_recent`), so the advanced type's steps never fall below 4 GW. Without it, five years
        # with no turbine builds shrank the turbine steps to 1.2 GW and the 2039 cofiring retirements went to CC.
        j = technology.ecp_codes().index(STEP_FLOOR_OF[code])
        stp_j = np.array(b["ESTCPSTP"], dtype=float).reshape(len(b["ESTSWTCH"]), -1)[j]
        add_j = float(b["ESTMNADD"][j]) / 1000.0 / (1.0 + stp_j[0])
        if floor_recent is not None:
            for k, a in enumerate(floor_recent):
                add_j = max(add_j, float(a) * (0.5 + 0.5 * (k + 1) / len(floor_recent)))
        add = max(add, add_j)
    out, cum, done = [], 1.0, 0.0
    for s, frac in enumerate(stp):
        cum += frac
        bound = add * cum - done
        mult = 1.0 if s == 0 else ((done + bound / 2.0) / add - stp[0]) ** (np.log(1.0 + csinc) / np.log(1.0 + cpinc))
        out.append((bound, float(mult)))
        done += bound
    out[0] = (max(out[0][0] - max(float(planned), 0.0), 0.0), out[0][1])
    return out


CREDIT_YEARS = 12.0              # years a plant earns the 45Q credit (TCS45Q/I_45Q_DURATION)
CCS_CAPACITY_FACTOR = 0.8        # assumed, to value the credit when deciding to build
# ECP's planning horizon (emmcntl.txt %ECP PARAMS%: UNFPH 30 years, UNXPH 3 explicit). The third explicit year
# stands for years 3 to 30; it is modelled as the year TAIL_OFFSET out (see solve_year).
HORIZON = False                   # off: see docs/capacity.md (horizon runs did not close the build gap)
HORIZON_YEARS = 30
TAIL_OFFSET = 10
LAST_MODEL_YEAR = 2050
HORIZON_SOLVER_OPTIONS = {"user_objective_scale": -3}   # HiGHS: the weighted tail costs are large (at -2 the 2032 solve stalled in dual simplex for over an hour on the new load; -3 takes 139 s)
# ECP's tail year in the LP (planning year 3: the present value of years E + 2 to E + 29, uecp.f UNXPH, UNFPH), with
# its planning year 2 build columns: step 1 cost, unbounded (EP$ELAST "LET YEAR 3 ELASTICITY BE UNBOUNDED"), in the tail
# only. This year's columns pay their whole present value (ecp_cost first) and sit in both periods, so whether to wait
# is the LP's choice and ecp_cost.one_year_cost and retirement_tail_proxy are not used. The tail is the reference run's year TAIL_OFFSET out, about the present-value mean of those years, in one day a
# month of 6-hour blocks (ECP has 9 slices), weighted by the annuity of years 2 to 29; its own reserve, resource, gas
# curve and intermittent rows; existing plants may retire for the tail only.
ECP_TAIL = True
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
# (uecp.f EP$ETT CAPACITY_DERATE). Used only with ECP_RESERVE off, for the existing links.
FIRM_TRANSFER_SHARE = 0.75
# ECP's reserve accounting (uecp.f EP$MRM, EP$ETT, EP$BRNW, CALC_STORAGE_VAL): hydro and pumped storage at 0.70,
# batteries at the CAP_CREDIT_LDC credit, and no firm capacity lent over existing links. ECP credits a transfer only
# on a line it builds (0.75 of it), and carries the lines built in earlier years as UTRELADJ on the requirement; this
# LP builds no lines, so it takes EIA's UTRELADJ (UETTOUT/utreladj) as given. Off: the earlier load-shape credits
# (hydro up to 1.0, batteries 0.74) and free lending up to FIRM_TRANSFER_SHARE of every existing link.
ECP_RESERVE = True
# The requirement on ECP's own load (ecp_load): LDSM's system load for EPPEAK and EP_NET_PEAK, plus PKADJ's firm
# contracts and cogeneration terms. Off, or without the LDSM dumps: the LP's net-energy shape, about 5% lower.
ECP_PEAK = True
# ECP's spinning reserve rows (uecp.f EP$MRM,8-13, rRSRge in ecp.ams), with ECP's build capacity factor for new wind
# and solar (ECP_BUILD_CF): the two go in together (docs/capacity.md, branch ecp-spin-reserve). In every region and
# time slice, spinning reserve >= SR_RQMT_HGHT x load + SR_RQMT_DIFF x (the season's peak load - load), plus SR_INT of
# the slice's wind and solar output (EP$INT,8/23/52: intermittents carry -SR_INT x their output on the row).
# Off: with ECP_BUILD_CF the 2027-2040 chain's wind runs away (2040: 591 GW against EIA's 404); alone (with
# ECP_STORAGE_SR) it ends the chain with fewer turbines and less wind (2040 CT 244, wind 325). Its duals are about a
# third of ECP's once both are in 1987$ (median regional sum 2.1 against 7.6 for 2031), and a year takes 150 to 680 s
# instead of 20 to 50 (docs/capacity.md, branch ecp-reserve).
SPIN_RESERVE = False
SR_RQMT_HGHT, SR_RQMT_DIFF, SR_INT = 0.1, 0.3, 0.25      # composite_2030 (the same in all 25 regions and every type)
# ECP's load seasons (LDSM ECPSGFH/ECPSGLH, months 1-based): winter Dec-Mar, summer Jun-Sep, the rest shoulder.
ECP_SEASON_MONTHS = ((12, 1, 2, 3), (6, 7, 8, 9), (4, 5, 10, 11))
# ECP type whose SR_MIN_CF (ecpdaty.xlsx SPNRSV) each LP group takes: the share of its capacity a committed unit
# must generate (EP$ODSP min-load mode). Coal and steam 0.3, combined cycle 0.2, turbines and pumped storage 0.1.
SPIN_TYPE = {"coal": "PC", "coal_ccs": "PQ", "gas_cc": "EC", "gas_cc_new": "AC", "gas_ccs": "CS", "gas_ct": "ET",
             "gas_ct_new": "AT", "steam": "ST", "gas_conv": "NG", "cofire": "NG", "pumped": "PS"}
SPIN_SHORTFALL_COST = 1000.0    # 1987$/MWh of missing spinning reserve; ECP has no slack (cSR is bounded below)
# ECP values a new wind or solar plant at WRENEW's capacity factor of the year before its solve, with no outage
# derate (uecp.f 38880-39035, UPICFC1). This LP's step for year y is ECP's year 2 of its y - 1 solve, so y - 2.
# On since the regional resource, vintage and build-cost ports: 2040 wind no longer runs away (2027-2040 chain 350 GW with it
# and the resource bounds alone, EIA 404).
ECP_BUILD_CF = True
# ECP's regional resource bound on new onshore wind and solar (rows L(region)WNINT(year) and L(region)PVINT(year),
# rLINTle in ecp.ams): builds in a region and planning year <= EPBLDBND (uecp.f EP$INT,32, 19610-19640; ecp.ams
# 26834), which RENOVR fills with WCAWIEL / WCAPVEL x 0.001 (udat.f 16711-16725, 16826-16843), the capacity renew.f
# has left in the resource classes on offer (2600, ConsCap). Florida (FRCC) and SRSE have none for wind: in the
# oracle's 2030 ECP solve their bound is 0 with a dual of -548 and -276. Without it this LP put 79 GW of wind in
# Florida by 2040, where EIA has none. Off: 100 GW in every region.
RENEW_BUILD_BOUND = True
# Wind's bound, cost multiplier and capacity factor from this path's own builds (emm/wind_resource.py, renew.f's classes).
# Off: the reference run's. The same for PV (emm/solar_resource.py, renew.f's land classes).
OWN_WIND_RESOURCE = True
OWN_SOLAR_RESOURCE = True
RENEW_BOUND_ARRAY = {"wind": "wcawiel", "solar": "wcapvel"}
RENEW_BOUND_TAIL = 5.0     # EP$INT,32: 5 x EPBLDBND in the last planning year
# ECP's cap on intermittent generation (rows L(region)XXINT(year), rLXXINTle; uecp.f EP$LINT 14407-14502, UPINTSW = 2):
# wind and solar output before curtailment, end-use PV included, at most UPINTMAX + UPINTINC (10 points) of the region's
# load in planning year 2, never above UPINTBND (85%) or below UPINTBD0 (15%). UPINTMAX is the largest share so far
# (EPO$INT's IRNWACT of the solve before). It binds in SPPS, SPPC, BASN and CANO in EIA's 2030 solve. Off: no cap.
INTERMITTENT_CAP = True
INT_BND, INT_INC, INT_BD0 = 0.85, 0.10, 0.15        # composite_2030 UPINTBND, UPINTINC, UPINTBD0 (ecpdaty.xlsx)
INT_ESCAPE_COST = 2000.0                             # 1987$/MWh, EP$LINT,4
# ECP's state RPS rows (rps.py; uecp.f EP$ST_RPS, rGRPSge): 49 tranches, each a share of its state's sales to be met with
# credits from its own older units, from its regions' other wind, solar and the rest, from linked regions as far as power
# flows over the link, from end-use generation, or at the compliance payment.
STATE_RPS = True
INT_UTILITY = ("wn", "wl", "wf", "pv", "pt", "so")
# ECP's battery spinning reserve (ecp.ams ccalc_cEXXX_INT_rRSRge and ccalc_cIX_rRSRge, EP$INT,23/52, CALC_STORAGE_VAL,
# 5/14): batteries do not choose their reserve in ECP. ReStore hands it a fixed reserve per GW by ECP slice, one for
# existing storage (NET_STORAGE_SR_EX, on the existing column) and one for a new build (NET_STORAGE_SR_NW, on the
# step-1 build column). Here the 2030 composite's values (ECP's 2031 matrix) for every year, in ECP slice order
# (shoulder, summer, winter, each peak / middle / base): existing weighted by each region's NET_STORAGE_CAP_EX, new
# the plain mean of the 25 regions (a missing entry is zero). With SPIN_RESERVE. Off: a battery carries its discharge
# headroom up to one hour of stored energy, about 1.0 per GW whenever it is idle.
ECP_STORAGE_SR = True
# ECP's national gas supply curve for the power sector (ecp.ams cSUNGX and rFUELNGXle, ELNGSCRV_Function, PDEL with
# UPCRVSW = 2): the sector's gas comes in UPCRVSTP = 20 steps below and 20 above the expected burn QBASE (QNGEL, last
# iteration), each UPCRVSIZ = 2% of QBASE wide, priced at the wellhead price times NGMM's supply curve (NGSCRV_Q0, P0,
# PER, ELAS) at the step over its value at no change. This LP pays the step's price less the curve's own (ECP's
# WHDEX x (PDEL - 1)) on top of the delivered price, with QBASE at EIA's dispatched burn (QNGEL less cogeneration).
# On. ECP's planning dispatch burns about 10% more gas than EFD (2031: 13.35 against 12.18 quads), which puts its
# marginal gas 12% above the curve's centre and its energy prices about that much above this LP's. This LP burns what
# EFD burns in 2031 (10.9 against 11.0 quads), so the curve moves 2031-2034 little; from 2035 it lifts wind toward
# EIA's (2040: 362 -> 414 GW against 404), other types within 1% (docs/capacity.md).
ECP_GAS_CURVE = True
GAS_CURVE_STEPS, GAS_CURVE_SIZE = 20, 0.02          # composite_2030 UPCRVSTP, UPCRVSIZ
# ECP bounds every step after the first at QSIZE, the last one too (uecp.f 6185-6200 EP$FLCRV,7; ecp.ams
# ccalc_cSUNGX_UBOUND), so the sector can burn at most QBASE + UPCRVSTP x QSIZE (40% over QBASE). On: so here. Off: the
# last step is unbounded.
GAS_CURVE_LAST_BOUNDED = True


def ngmm_gas_price(snapshot, year: int, extra_tbtu) -> np.ndarray:
    """ecp.ams ELNGSCRV_Function: NGMM's gas supply curve price (1987$/MMBtu) at national consumption NGSCRV_Q
    plus `extra_tbtu` (TBtu, converted to Bcf with CFNGU), constant elasticity in five bands around NGSCRV_Q0."""
    y = year - 1990
    q0, p0 = float(snapshot["NGTDMREP/ngscrv_q0"][y]), float(snapshot["NGTDMREP/ngscrv_p0"][y])
    per, el = np.asarray(snapshot["NGTDMREP/ngscrv_per"], float), np.asarray(snapshot["NGTDMREP/ngscrv_elas"], float)
    q = float(snapshot["NGTDMREP/ngscrv_q"][y]) + np.asarray(extra_tbtu, float) / float(snapshot["CONVFACT/cfngu"][y])
    aq, bq = q0 * (1 - per[0]), q0 * (1 + per[0])
    ap, bp = p0 * (1 - per[0] / el[2]), p0 * (1 + per[0] / el[2])
    cq, dq = aq * (1 - per[1]), bq * (1 + per[1])
    cp, dp = ap * (1 - per[1] / el[1]), bp * (1 + per[1] / el[3])
    qb = np.select([q <= cq, q <= aq, q >= dq, q >= bq], [cq, aq, dq, bq], q0)
    pb = np.select([q <= cq, q <= aq, q >= dq, q >= bq], [cp, ap, dp, bp], p0)
    e = np.select([q <= cq, q <= aq, q >= dq, q >= bq], [el[0], el[1], el[4], el[3]], el[2])
    out = pb * ((q - qb) / qb / e + 1.0)
    return np.where(out <= 0.0, p0, out)      # XPBASE where the curve would go below zero


def gas_curve_steps(snapshot, year: int) -> tuple:
    """ECP's power-sector gas steps for `year`: (upper bound TBtu of each of the 2 x GAS_CURVE_STEPS + 1 steps, the
    last bounded like the others with GAS_CURVE_LAST_BOUNDED; the price ratio PDEL of each). Step 1 holds everything up to 20 steps below QBASE; step k > 1 is
    the k - 21st 2% step away from it (step 21 ends at QBASE)."""
    from . import dispatch_report
    qbase = dispatch_report.reference(snapshot, year)["fuel_gas"]
    w = GAS_CURVE_SIZE * float(snapshot["QBLK/qngel"][10, year - 1990])
    n = 2 * GAS_CURVE_STEPS + 1
    k = np.arange(1, n + 1)
    dev = (k - (GAS_CURVE_STEPS + 1)) * w
    ratio = ngmm_gas_price(snapshot, year, dev) / ngmm_gas_price(snapshot, year, 0.0)
    bound = np.full(n, w)
    bound[0] = qbase - GAS_CURVE_STEPS * w
    if not GAS_CURVE_LAST_BOUNDED:
        bound[-1] = np.inf
    return bound, ratio


# The price ECP scales by PDEL / PBASE: WHDEX = XOGWPRNG(MNUMOR) / CFNGU (uecp.f 6258, 6266-6269), the wellhead price
# NGMM hands EMM, in 1987$ per MMBtu (UPGNPD and PWF only move it to ECP's nominal present value). The port used
# NGSCRV_P, the supply curve's own price (2030: 1.4416 against WHDEX's 1.4248). On: WHDEX. Off: NGSCRV_P.
GAS_CURVE_WHDEX = True


def gas_curve_wellhead(snapshot, year: int) -> float:
    """1987$/MMBtu the gas curve's step premiums scale: WHDEX (GAS_CURVE_WHDEX) or NGSCRV_P."""
    if not GAS_CURVE_WHDEX:
        return float(snapshot["NGTDMREP/ngscrv_p"][year - 1990])
    k = min(year, LAST_MODEL_YEAR) - 1990
    return float(snapshot["MXPBLK/xogwprng"][-1, year - 1990]) / float(snapshot["CONVFACT/cfngu"][k])


ECP_BATTERY_SR_EX = (0.241, 0.285, 0.416, 0.220, 0.227, 0.460, 0.283, 0.213, 0.455)
ECP_BATTERY_SR_NW = (0.097, 0.067, 0.065, 0.125, 0.187, 0.199, 0.087, 0.064, 0.090)


def spin_min_cf() -> dict:
    """SR_MIN_CF by LP group (ecpdaty.xlsx SPNRSV), the minimum load of a unit carrying spinning reserve."""
    r = named_ranges(technology.ECPDATY, "SPNRSV")
    codes = technology.ecp_codes()
    return {g: float(r["SR_MIN_CF"][codes.index(c)]) for g, c in SPIN_TYPE.items()}


def ecp_season_of_month() -> np.ndarray:
    """ECP season (0, 1, 2) of each month (0-based), shape (12,)."""
    out = np.zeros(12, dtype=int)
    for s, months in enumerate(ECP_SEASON_MONTHS):
        for mo in months:
            out[mo - 1] = s
    return out


ECP_SLICE_SHARES = (0.01, 0.49, 0.50)     # EPWDTH: each season's peak, middle and base slices (29, 1435, 1464 hours)


def ecp_slice_heights(load_hr: np.ndarray, weights: np.ndarray, month_of_day: np.ndarray, net_hr=None):
    """LDSM's ECP load slices (uldsm.f DSMLCP) cut from an hourly load (25, 36, 24) GW: in each season the hours
    sorted by net load `net_hr` (NL_SLICE_SW: load less wind and solar; the load itself when None) and split at
    ECP_SLICE_SHARES of the season's hours; each slice's height is the average load (not net load) of its hours,
    the peak slice's too (ECP's 2030 composite EPHGHT: TRE's summer peak slice 90.1 GW, below LDSM's top hour).
    Returns (slice of every hour, (25, 36, 24), 0-8 as ECP numbers them; heights (25, 9) GW)."""
    season = ecp_season_of_month()[month_of_day]
    R = load_hr.shape[0]
    slice_of = np.zeros(load_hr.shape, dtype=int)
    height = np.zeros((R, 9))
    w = np.broadcast_to(weights[:, None], load_hr.shape[1:]).ravel()
    for r in range(R):
        flat = load_hr[r].ravel()
        key = flat if net_hr is None else net_hr[r].ravel()
        sl = np.zeros(flat.size, dtype=int)
        for s in range(3):
            # ECP numbers its slice groups from LDSM's last season down: shoulder 1-3, summer 4-6, winter 7-9
            base = 3 * (2 - s)
            idx = np.flatnonzero(np.repeat(season == s, load_hr.shape[2]))
            order = idx[np.argsort(-key[idx], kind="stable")]
            cum = np.cumsum(w[order]) / w[order].sum()
            mid = cum - 0.5 * w[order] / w[order].sum()
            k = np.searchsorted(np.cumsum(ECP_SLICE_SHARES), mid, side="right").clip(max=2)
            sl[order] = base + k
            for j in range(3):
                pick = order[k == j]
                if pick.size == 0:
                    continue
                height[r, base + j] = float(np.average(flat[pick], weights=w[pick]))
        slice_of[r] = sl.reshape(load_hr.shape[1:])
    return slice_of, height


def spin_requirement(load_hr: np.ndarray, weights: np.ndarray, month_of_day: np.ndarray, hours: int = BLOCK_HOURS,
                     adjust=None, net_hr=None) -> np.ndarray:
    """EP$MRM,8-10's requirement before intermittents, (25, 36, 24 // hours) GW. On ECP's slices of the load
    (ecp_slice_heights, plus ADJ_HGHT `adjust`, GW by region): SR_RQMT_HGHT x the slice's height plus SR_RQMT_DIFF x
    the gap to the season's peak slice. Each hour takes its slice's requirement; a block averages its hours."""
    slice_of, height = ecp_slice_heights(load_hr, weights, month_of_day, net_hr)
    if adjust is not None:
        height = height + np.asarray(adjust, dtype=float)[:, None]
    peak = height[:, (np.arange(9) // 3) * 3]
    req_slice = SR_RQMT_HGHT * height + SR_RQMT_DIFF * (peak - height)
    req_hr = np.take_along_axis(req_slice, slice_of.reshape(slice_of.shape[0], -1), axis=1).reshape(slice_of.shape)
    return _blocks(req_hr, hours)


# ECP's dispatch modes (uecp.f EP$ODSP, ecp.ams cO_DISP / cJ / cU): with SPIN_RESERVE, thermal units are committed
# by ECP season and mode instead of block by block, and the spinning reserve rows are ECP's 9 slices (rRSRge) rather
# than every block. A mode of a season runs in its slices 1..L (L = 1 peak only, 2 peak and middle, 3 all three;
# EPFRST order, the peak first), so a unit committed for the base slice is committed in the whole season, and the
# committed capacity of a slice is the sum of the modes that reach it. A committed unit generates between its
# min-reserve mode (cJ: SR_MIN_CF x (SR_MIN_LF + (1 - SR_MIN_LF) x slice height / the season's lowest)) and its
# derated capacity in every block of the slice, and its reserve is committed capacity less output (EP$ODSP,34/44/52:
# SR_CREDIT x (1 - output)), averaged over the slice as ECP's slice row does. Which modes a type may use comes from
# UPPCFB (COSTPERF: coal and combined cycle not peak-only). Generation counts only from committed capacity.
ECP_DISPATCH_MODES = False
ECP_SLICE_CF = (0.0, 0.01, 0.50, 1.0)       # cumulative slice shares of a season, peak first (CF in EP$ODSP)


def allowed_modes() -> dict:
    """Modes L (1-3, the number of slices from the peak a mode runs in) each LP group may use: EP$ODSP's test
    UPPCFB(2) >= CF(L) and UPPCFB(1) <= CF(L + 1) on the type's UPPCFB (COSTPERF, low and high capacity factor)."""
    pcfb = named_ranges(technology.ECPDATY, "COSTPERF")["UPPCFB"]
    codes = technology.ecp_codes()
    out = {}
    for g in TG:
        i = codes.index(SPIN_TYPE[g])
        lo, hi = float(pcfb[2 * i]), float(pcfb[2 * i + 1])
        out[g] = tuple(L for L in (1, 2, 3) if hi >= ECP_SLICE_CF[L - 1] and lo <= ECP_SLICE_CF[L])
    return out


# The most a committed GW generates in ECP (cU, maximum load: uecp.f EP$ODSP,46; ecp.ams VALUE_MAX_SR_ODSP) is not its
# availability but (1 - FOR) x (SR_MAX_LF + (1 - SR_MAX_LF) x slice height / season peak), SR_MAX_LF 0.7 for existing
# combined cycle, 0.9 for new and for coal, 0.5 for turbines and steam; and planned maintenance takes whole capacity out
# of the seasons it is put in (EP$PM$LF: cPX, rows rMXXge, UPPMRT of the year's hours). In TRE's 2031 summer ECP's existing
# combined cycle gives 0.85 to 0.88 of capacity in the 2,900 hours below the peak slice, not 0.945, is committed in full
# and turbines set the price. Off: availability alone, with UPMCF over the year.
ECP_MAX_LOAD = False


def max_load_factor(height: np.ndarray, max_lf: float) -> np.ndarray:
    """VALUE_MAX_SR_ODSP over 1 - FOR in each ECP slice, (25, 9) from the slice heights (25, 9)."""
    peak = height[:, (np.arange(9) // 3) * 3]
    return max_lf + (1.0 - max_lf) * np.divide(height, peak, out=np.ones_like(height), where=peak > 0)


def block_slice(slice_of: np.ndarray, hours: int = BLOCK_HOURS) -> np.ndarray:
    """ECP slice of each block (the slice most of its hours fall in), (25, 36, 24 // hours) from (25, 36, 24)."""
    R, Dn, H = slice_of.shape
    s = slice_of.reshape(R, Dn, H // hours, hours)
    counts = np.stack([(s == k).sum(axis=-1) for k in range(9)], axis=-1)
    return counts.argmax(axis=-1)


def mode_min_factor(height: np.ndarray, min_cf: float, min_lf: float = 0.0) -> np.ndarray:
    """cJ's output per committed GW in each slice (VALUE_MIN_SR_ODSP): SR_MIN_CF x (SR_MIN_LF + (1 - SR_MIN_LF) x
    the slice's height over the lowest of its season), (25, 9) from heights (25, 9)."""
    low = height.reshape(height.shape[0], 3, 3).min(axis=2)
    low = np.repeat(low, 3, axis=1)
    return min_cf * (min_lf + (1.0 - min_lf) * np.divide(height, low, out=np.ones_like(height), where=low > 0))


def dispatch_modes(m, tag, cs, load_rm, net_hr, adj, bh, g_th, capv_p, one_minus_for, mins, other_sr, hours_w,
                   R, T, D, Bk) -> dict:
    """ECP's dispatch modes and its 9-slice spinning reserve rows (ECP_DISPATCH_MODES), on the LP's blocks.
    `other_sr` is the reserve of everything but thermal units per block (storage, nuclear and other renewables, less
    SR_INT of wind and solar output). Returns the rows' shortfall cost and what the result needs."""
    month_of_day = np.repeat(np.arange(12), 3)
    slice_of, height = ecp_slice_heights(load_rm, cs.weights, month_of_day, net_hr)
    if adj is not None:
        height = height + np.asarray(adj, dtype=float)[:, None]
    blk = block_slice(slice_of, bh)
    peak = height[:, (np.arange(9) // 3) * 3]
    req = SR_RQMT_HGHT * height + SR_RQMT_DIFF * (peak - height)          # cSR's lower bound by slice
    allowed = allowed_modes()
    S = pd.Index(np.arange(3), name="season")
    L = pd.Index([1, 2, 3], name="mode")
    ok = np.zeros((len(T), 3, 3))
    for j, g in enumerate(T):
        for L_ in allowed[g]:
            ok[j, :, L_ - 1] = np.inf
    u = m.add_variables(lower=0, upper=xr.DataArray(np.broadcast_to(ok, (len(R),) + ok.shape).copy(), coords=[R, T, S, L]),
                        name=f"mode{tag}")
    m.add_constraints(u.sum("mode") - capv_p <= 0, name=f"mode_capacity{tag}")
    wts = np.broadcast_to(np.asarray(hours_w.values)[None, :, None], blk.shape)
    shortfall = m.add_variables(lower=0, coords=[R, pd.Index(np.arange(9), name="slice")], name=f"spin_shortfall{tag}")
    lf = named_ranges(technology.ECPDATY, "SPNRSV")["SR_MIN_LF"]
    codes = technology.ecp_codes()
    min_lf = {g: float(lf[codes.index(c)]) for g, c in SPIN_TYPE.items()}
    cost = 0
    for k in range(9):
        season, rank = 2 - k // 3, k % 3                  # slices numbered shoulder 0-2, summer 3-5, winter 6-8
        committed = u.sel(season=season, mode=[x for x in (1, 2, 3) if x >= rank + 1]).sum("mode")      # [R, T]
        mask = xr.DataArray(blk == k, coords=[R, D, Bk])
        if not mask.values.any():
            continue
        fmin = xr.DataArray(np.stack([mode_min_factor(height, mins[g], min_lf[g])[:, k] for g in T], axis=1), coords=[R, T])
        m.add_constraints(g_th - committed * one_minus_for <= 0, name=f"mode_max{tag}_{k}", mask=mask)
        m.add_constraints(g_th - committed * fmin >= 0, name=f"mode_min{tag}_{k}", mask=mask)
        w_k = np.where(blk == k, wts, 0.0)
        tot = w_k.sum(axis=(1, 2))
        share = xr.DataArray(np.divide(w_k, tot[:, None, None], out=np.zeros_like(w_k), where=tot[:, None, None] > 0),
                             coords=[R, D, Bk])
        supply = committed.sum("group") - (g_th.sum("group") * share).sum(["day", "block"])             + (other_sr * share).sum(["day", "block"])
        need = xr.DataArray(np.where(tot > 0, req[:, k], 0.0), coords=[R])
        m.add_constraints(supply + shortfall.sel(slice=k) >= need, name=f"spin_reserve{tag}_{k}")
        cost = cost + (shortfall.sel(slice=k) * xr.DataArray(SPIN_SHORTFALL_COST * tot, coords=[R])).sum()
    return {"requirement": req, "shortfall": shortfall, "cost": cost, "slices": 9}


def ecp_build_profile(snapshot, year: int) -> dict:
    """ECP's UPICFC1 for a new wind or solar plant online in `year`: WRENEW's profile (main type, WN and PV) of
    year - 2, without the outage derate, (25, 36, 24)."""
    y = max(year - 2 - history.FIRST_YEAR, 0)
    out = {}
    for group, parts in dispatch.WRENEW_PROFILES.items():
        out[group] = dispatch._wrenew_profile(snapshot, parts[0][1], y)
    return out


def end_use_pv(snapshot, year: int) -> np.ndarray:
    """End-use solar generation, (25,) TWh: on the load rows and in the PV column of ECP (DPVDISPATCH)."""
    return np.asarray(snapshot["COGEN/cgtotgennr"], dtype=float)[:NUM_R, year - 1990, 9, :].sum(axis=1) / 1000.0


def reference_intermittent_share(snapshot, year: int) -> np.ndarray:
    """(25,) wind and solar share of generation in `year` of the reference run, end-use PV included."""
    y = year - 1990
    gen = sum(np.asarray(snapshot[f"UEFDOUT/ugn{p}nr"], dtype=float)[:, :NUM_R, y].sum(axis=0) for p in INT_UTILITY)
    tot = np.asarray(snapshot["UEFDOUT/ugntlnr"], dtype=float)[:, :NUM_R, y].sum(axis=0)
    pv = end_use_pv(snapshot, year)
    return np.divide(gen + pv, tot + pv, out=np.zeros(NUM_R), where=tot + pv > 0)


def intermittent_limit(shares: list) -> np.ndarray:
    """EP$LINT's cap for planning year 2 from the shares of the years so far."""
    return np.maximum(np.minimum(np.max(np.stack(shares), axis=0) + INT_INC, INT_BND), INT_BD0)


def renewable_build_bound(snapshot, group: str, year: int) -> np.ndarray:
    """EPBLDBND: new wind (WN) or solar (PV) capacity a region can add in `year`, (25,) GW. RENOVR reads
    RYR = CURIYR - 1 in the solve of CURIYR = year - 1 (udat.f 16168-16176), so the restart's year - 2, as in
    ecp_build_profile. These are EIA's remaining resources along the reference run; OWN_WIND_RESOURCE and OWN_SOLAR_RESOURCE replace them."""
    y = max(year - 2 - history.FIRST_YEAR, 0)
    return np.maximum(snapshot[f"WRENEW/{RENEW_BOUND_ARRAY[group]}"][:NUM_R, y].astype(float), 0.0) * 1.0e-3


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
    debt, equity, share, tax = _financing(snapshot, year)
    return share * debt * (1.0 - tax) + (1.0 - share) * equity


def _financing(snapshot, year: int) -> tuple:
    """(debt rate, equity rate, debt share UPNFDT, tax rate UPTXRT) of a new plant's financing in `year`."""
    fin = named_ranges(technology.ECPDATY, "FINANCIAL")
    i = year - 1990
    debt = float(snapshot["MACOUT/mc_rmcorppuaa"][i]) / 100.0
    equity = float(snapshot["MACOUT/mc_rmtcm10y"][i]) / 100.0 + 0.0575 * float(fin["UPBETA"][0])
    return debt, equity, float(fin["UPNFDT"][0]), float(fin["UPTXRT"][0])


# The rate ECP carries work in progress at (uread.f EPINCST's ROR). Every EMM region builds as a non-utility
# (UPBLDTYP = 2 in NEMS_INPUT.db V_EMM_ECPDAT_REG), so EP$BDSP,62 passes EWGROR = EWGROE x (1 - DEBT_F) + EWGINT x DEBT_F
# (uecp.f 16269, 16301): the pre-tax cost of capital, with UPNIRTEA and UPNRRTEA, which carry EXTRARISK for the UPRSKSW
# types (util.f 895-900), on both parts. The annuity that follows (EPCNBLD, CRF) is at the after-tax EPDSCRT, as in
# capital_costs. On: construction interest at that pre-tax rate. Off: at the after-tax discount rate, which understated
# the interest by about UPNFDT x debt x UPTXRT (0.8 points in 2030).
CONSTRUCTION_PRE_TAX = True


# ECP's own cost of a build column (ecp_cost): EPCNBLD's capacity payment, transmission (EPCOVR, EPCFOM), the spread of
# BAA over AA on debt, and the 3 points on debt and equity of new wind (online to 2029), solar (to 2028) and storage (to
# 2036) that ecpdaty.xlsx FINANCIAL carries (UPNIRTEY, UPNRRTEY; uecp.f EP$SUBFIN), which the LP left out. The formula
# gives every column of EIA's 2030 solve within 2% (wind and solar where the resource cost is the same). The charge for
# the one year the LP decides is ecp_cost.one_year_cost. A storage build online in 2031 pays the 3 points for life where
# one planned for the tail pays almost none: 119 $/kW-year, where the level annuity had 46. Off: a level annuity at the
# after-tax cost of capital.
ECP_BUILD_COST = True
# ECP's second and third build steps raise the whole column's installed cost (EPCCSUP, ESTCPCST), paid for the 29 years
# online, while waiting a year costs step 1 (year-2 columns are unbounded). So the premium is the lifetime cost, not a
# year of it: 0.375 x 1,320 nominal $/kW for a 2031 combined cycle against a one-year cost of 116 (2030 solve, TRE: steps
# 1,738 / 2,234 / 3,391). The LP charged one year of it, a twelfth. ecp_cost.one_year_cost per step, which gives the
# one-year premium back where waiting loses a tax credit. With ECP_BUILD_COST. Off: one year everywhere.
STEP_PREMIUM_LIFETIME = True
TAX_FCF_ADJ = 0.015      # TAXFCFTT + TAXFCFTD off the transmission charge rate (uecp.f 737; emmcntl.txt %TAXDEPR Y1%)


def construction_rate(snapshot, year: int, code: str) -> float:
    """EPINCST's rate for building ECP type `code` in `year`: EWGROR, the pre-tax cost of capital (with
    CONSTRUCTION_PRE_TAX), else the after-tax discount rate plus the risk premium."""
    if not CONSTRUCTION_PRE_TAX:
        return discount_rate(snapshot, year) + risk_premium(snapshot, year, code)
    debt, equity, share, _ = _financing(snapshot, year)
    fin = named_ranges(technology.ECPDATY, "FINANCIAL")
    extra = float(snapshot["EMISSION/extrarisk"][year - 1990]) if fin["UPRSKSW"][technology.ecp_codes().index(code)] > 0 else 0.0
    return share * (debt + extra) + (1.0 - share) * (equity + extra)


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
    rps_price: dict = field(default_factory=dict)   # (state, tranche id) -> 1987$/MWh credit price
    converted: np.ndarray = field(default_factory=lambda: np.zeros(NUM_R))     # GW coal moved to gas
    price: np.ndarray = None        # (25, 36, BLOCKS) energy price, 1987$/MWh (duals of the regional balance)
    reserve_price: np.ndarray = None  # (25,) 1987$/kW-year, dual of each region's reserve margin (EIA: RMAVG)
    reserve_payment: np.ndarray = None  # (25,) 1987$/kW-year, what EIA prices capacity at (RMAVG; ECP_TAIL only)
    group_retire: dict = field(default_factory=dict)  # group -> (25, 4) GW retired from each retirement group
    group_share: dict = field(default_factory=dict)   # group -> (25, 4) share of each retirement group retired
    rule_retire: np.ndarray = field(default_factory=lambda: np.zeros(NUM_R))  # GW coal the 2032 rule forced out
    spin_price: np.ndarray = None   # (25, 36, BLOCKS) 1987$/kW-year per slice, dual of the spinning reserve rows
    spin_requirement: np.ndarray = None   # (25, 36, BLOCKS) GW, before intermittents (SPIN_RESERVE)
    spin_slice_price: np.ndarray = None   # (25, 9) 1987$/kW-year by ECP slice (ECP_DISPATCH_MODES)
    intermittent_share: np.ndarray = None   # (25,) wind and solar output before curtailment over load, end-use PV included
    conventional_cc: float = 0.0    # national GW of gas_cc_new built as ECP's CC type (CONVENTIONAL_CC)
    spin_shortfall_gw: float = 0.0  # largest shortfall in any region and slice on the spinning reserve rows


def max_retirement_rate(year: int) -> float:
    """EIA's cap on economic retirements taking effect in `year`, as a share of a region's capacity.

    emmcntl.txt, %MAX RET RATE%: UPRETRT0 (3%) rising UPRETCHG (1 point) a year to UPRETRTL (6%). EP$RET in uecp.f
    applies it to each region's total capacity in planning year UPRTLT + 1, so ECP year E sets the cap for
    retirements in E + UPRTLT (%ECONOMIC RETIRE SW%, 1 year) at UPRETRT0 + UPRETCHG x ((E + UPRTLT - 1) - (UPSTYR + 1))
    (uecp.f 1171-1178). With UPSTYR = START_YEAR that is 3% for 2027, 4% for 2028, 6% for 2030 and no cap from 2031.
    (In ECP's first year, E = UPSTYR, UPRETRAT keeps its input 0 and there is no cap on 2026; this model keeps the
    first rate for years before START_YEAR + 2.)
    """
    lines = (INPUT / "emm" / "emmcntl.txt").read_text(encoding="latin-1").splitlines()
    row = next(l for l in lines if l.lstrip().startswith("'MAX RET'")).split()
    first, last, step = float(row[3]), float(row[4]), float(row[5])         # fields: 'MAX', 'RET', UPRETRAT, UPRETRT0, UPRETRTL, UPRETCHG
    lead = int(next(l for l in lines if l.lstrip().startswith("'ERET SW'")).split()[3])      # UPRTLT
    decided = year - lead                                                    # ECP year E whose plan retires in `year`
    rate = first + step * max((decided + lead - 1) - (START_YEAR + 1), 0)
    return rate if rate <= last + 1e-9 else float("inf")        # uecp.f 1177: past UPRETRTL the limit is switched off (RETYR = 0)


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
    if not dispatch.COFIRE_GROUP:     # on, initial_capacity put them in gas_conv
        rets["steam"] = rets["steam"] + np.minimum(cofiring_existing(snapshot, START_YEAR), cap_in["steam"])
    return rets


def _crf(rate: float, years: float) -> float:
    return rate / (1.0 - (1.0 + rate) ** -years)


def conversion_credit(year: int, firm_annual, keep_annual, rate: float, horizon: int = HORIZON_YEARS,
                      last: int | None = None) -> np.ndarray:
    """What a coal-to-gas conversion made in `year` is worth each year, beyond this year, as ECP's planning horizon
    sees it (k$ per GW-year, levelized over the horizon).

    ECP's conversion column (uecp.f EP$COAL,19-28) moves the unit into gas steam for the rest of its UNFPH (30) year
    horizon and puts it in every horizon year's reserve-margin row; its cost is the conversion capital spread over
    that horizon plus the converted fixed O&M. Unconverted coal has to retire from RULE_YEAR, so from then each
    converted GW is firm capacity the plan does not have to build. A one-year LP sees none of that and never
    converts (EIA's run converts 36 GW in 2028-2030). The credit is that avoided build, `firm_annual` (the annual
    cost of a new turbine, the cheapest firm type) less `keep_annual` (the converted unit's own fixed O&M), for each
    horizon year from RULE_YEAR (to `last` if given), discounted at `rate` and levelized over the horizon."""
    gain = np.maximum(np.asarray(firm_annual, dtype=float) - np.asarray(keep_annual, dtype=float), 0.0)
    pv = sum((1.0 + rate) ** -(k + 1) for k in range(horizon) if year + k >= RULE_YEAR and (last is None or year + k <= last))
    return gain * pv * _crf(rate, horizon)


# When ECP converts (ecp.ams Calculate_CL_NNGCOSTS, EP$COAL,19): conversion columns cNNG exist only for planning years
# 2 and 3 (ord(PlanYear) > 1; emmcntl %CL RET VN% UCL_VIN 0 / 1 / 2: year 1 cannot change) and, with EPA 111 on, only
# while E + PlanYear - 1 <= UEPA_GSYR (OV_CLtNG = 0 past it). Year 2 (online E + 1) is the one carried out; year 3 is
# the tail. Both put the unit in every later reserve row, so the horizon's firm value is the same for both and cancels:
# converting now has to pay for itself in E + 1 alone, unless the tail column is gone (E + 2 > UEPA_GSYR). This LP's
# year is ECP's E + 1, so the horizon credit applies only when year + 1 > UEPA_GSYR (2030). Before this, the credit
# applied from 2028 and the LP converted 30.7 GW in 2028 (EIA: 4.3, 12.7, 18.9 in 2028-2030). On, the 2027-2040 chain
# converts 0 / 0 / 12.4 GW: the timing is ECP's, but the one-year economics of 2028-2029 and the 2030 volume are not,
# and steam falls 16 to 22 GW under EIA's in 2030-2035 (docs/capacity.md). Off until those are found: credit every year.
ECP_CONVERT_TIMING = False


# ECP's conversion columns are per coal group (uecp.f EP$COAL,19-28: cNNG bounded at the group's capacity, its cost the
# group's own ECL_CL_NG_COST + ECL_CL_NG_TRAN, its converted fixed O&M the group's own ECL_FOM x UCL_CL_NG_FOM_ADJ,
# where ECL_FOM is fixed O&M + G&A + capital additions + age adder, udat.f 9424). A region-average column converts all of
# a region's eligible coal or none; the cheap units EIA converts in 2028-2029 (4.3 and 12.7 GW, spread over 5 and 11
# regions) never pay on the average. On: each region's eligible units are sorted by their own one-year cost (conversion
# capital annualized, less the fixed O&M the conversion saves) and split into CONVERT_STEPS steps of equal capacity, each
# with its units' capacity-weighted capital and keep cost.
CONVERT_BY_UNIT = False
CONVERT_STEPS = 5
# How ECP dispatches a cofired conversion (EP$COAL,20a/28b-d, 35a/81a/87a): the conversion column cNNG puts the unit in
# the gas steam capacity rows (it burns gas), and the cofiring column GCL keeps a coal part in the coal capacity and fuel
# rows, with row GCF (0.6 cNNG - 0.4 GCL >= 0) holding the coal part to at most 60% of the capacity. So the coal part
# runs on coal at coal cost and only output above it burns gas: a split of capacity, not a fuel blend in every MWh.
# This LP blended 60% coal and 40% gas into every MWh, so a cofired unit at a coal unit's 50-60% capacity factor burned
# 40% gas where ECP's burns almost none. On: gas_conv runs at coal cost up to UEPA_CGSH of its available capacity in
# each block, and pays the gas premium above that.
CONVERT_SPLIT_FUEL = False
# ECP plans a converted unit (type NG) as gas steam: its fuel rows take gas alone (rFXXle(*,NG,*) is supplied only by the
# GS fuel column in the 2030 solve, 19 TWh from 21 GW), whatever coal EFD lets it burn (UEPA_CGSH, udat.f 6457). Blended
# at 60% coal here it ran at 55% in front of combined cycle, 221 TWh in 2031, which took 1.4 quads of gas out of the
# planning dispatch. On: gas_conv pays the gas price in the LP. (EIA's own dispatch, dispatch.py, keeps the blend.)
ECP_CONVERTED_BURNS_GAS = True
# How far the conversion's horizon credit runs. ECP's gas part (cNNG) sits in every later reserve row at full capacity
# (EP$COAL,23: no year limit). Its coal part (cNNGCL, at most UEPA_CGSH of the unit through row NGCLCF, EP$COAL,28c)
# sits in the explicit years' reserve rows in full but in the tail row only at EPA_YRSHR, the discounted share of the
# tail years up to UEPA_CLCFYR (ecp.ams EP_COAL_Calculations 11604-11609, ccalc_cNNGCL_rRXXXXXge 12187-12201). So in
# ECP the coal part's credit stops at UEPA_CLCFYR and the gas part's does not. (EIA then retires the whole cofiring
# plant at UEPA_CLCFYR, udat.f 6451 and uecp.f 28161, but ECP's LP does not price that.) On: the credit is
# (1 - UEPA_CGSH) x the full-horizon credit + UEPA_CGSH x the credit to UEPA_CLCFYR. Off: full horizon for all of it.
CONVERT_CREDIT_TO_CLCFYR = True


def cofired_conversion_credit(year: int, firm_annual, keep_annual, rate: float, rule: dict) -> np.ndarray:
    """conversion_credit for a cofired conversion as ECP's columns see it (CONVERT_CREDIT_TO_CLCFYR): the gas part
    (1 - UEPA_CGSH) to the end of the horizon, the coal part (UEPA_CGSH) only to UEPA_CLCFYR."""
    full = conversion_credit(year, firm_annual, keep_annual, rate)
    if not (CONVERT_CREDIT_TO_CLCFYR and rule["switch"]):
        return full
    share = float(rule["cofire_coal_share"])
    cut = conversion_credit(year, firm_annual, keep_annual, rate, last=rule["cofire_last"])
    return (1.0 - share) * full + share * cut


def conversion_steps(capital, keep, mw, region, crf: float, steps: int = CONVERT_STEPS, num_r: int = NUM_R):
    """Split each region's eligible coal units into `steps` steps of about equal capacity, cheapest one-year
    conversion first. capital, keep: $/kW and $/kW-year per unit; mw: unit capacity (only eligible units);
    region: 1-based. Returns (gw, capital, keep), each (num_r, steps), capital and keep capacity-weighted."""
    capital, keep, mw, region = (np.asarray(a, dtype=float) for a in (capital, keep, mw, region))
    gw, cap_k, keep_k = np.zeros((num_r, steps)), np.zeros((num_r, steps)), np.zeros((num_r, steps))
    net = capital * crf - (1.0 - CONVERT_FOM_ADJ) * keep
    for r in range(num_r):
        idx = np.flatnonzero((region == r + 1) & (mw > 0))
        if idx.size == 0:
            continue
        idx = idx[np.argsort(net[idx], kind="stable")]
        cum = np.cumsum(mw[idx]) - 0.5 * mw[idx]
        k = np.minimum((cum / mw[idx].sum() * steps).astype(int), steps - 1)
        for j in range(steps):
            sel = idx[k == j]
            w = mw[sel].sum()
            if w <= 0:
                continue
            gw[r, j] = w / 1000.0
            cap_k[r, j] = (capital[sel] * mw[sel]).sum() / w
            keep_k[r, j] = (keep[sel] * mw[sel]).sum() / w
    return gw, cap_k, keep_k


def conversion_is_last_chance(year: int, rule: dict) -> bool:
    """True when converting in `year` is the last option ECP has (no tail conversion column after it), so the
    conversion earns the horizon's firm-capacity credit; False when it could also convert a year later."""
    if not ECP_CONVERT_TIMING:
        return True
    return bool(rule["switch"]) and year + 1 > rule["gas_switch_last"]


# ECP keeps or retires an existing plant with option columns that span its horizon. For gas CC and steam (EP$NGBS,
# uecp.f 36373-36690) each plant group has three columns sharing its capacity: run period 1 only (it retires), periods
# 1-2, or the whole horizon. The last pays fixed O&M (GRP_FOM) for all UNFPH years and sits in the reserve row of the
# tail year, which stands for years 3 to 30 (EP$NGBS,9). Turbines (EP$BDSP,5-8) and coal (EP$COAL) have the same
# shape. So keeping a plant is worth the tail reserve row's dual, the present value of whatever firm capacity the tail
# would otherwise build, less the horizon's fixed O&M. The dual is ECP's own: zero where the tail row is slack.
#
# This LP has no tail period, so it does not have that dual. RETIRE_TAIL_PROXY is an approximation of it, not ECP's
# method: it prices the tail's firm capacity at a new turbine's annual cost (capital plus fixed O&M, no energy margin)
# in every region and every year, as if the tail row always bound. In ECP's 2030 solve the tail row binds in 21 of 25
# regions and steam's value of keeping is about a turbine's annual cost, which is why the proxy fits on average. It
# overstates where the tail is slack and wherever a turbine earns energy margin. Its effect: without it the 2027-2033
# chain retires 25 GW of CC, CT and steam (plus 3.5 of converted coal) where EIA retires about 3; with it, 3.1
# (2026-11-22, docs/capacity.md). The faithful port is a
# tail period in this LP: a reserve row for ECP's year 3 (load and capacity credits of E + 2, every existing and kept
# group, year-2 build columns paying the horizon's present value) and, per retirement group, the three option columns
# with their horizon fixed O&M. That is the HORIZON code path plus option columns, a few hundred lines and a tail
# solve per year (HORIZON's own years took 20 to 140 s; it is off because it did not close the build gap). On: proxy.
# Off: retirements see only this year.
RETIRE_TAIL_PROXY = True
# Coal (EP$COAL's commit vectors also run to the end of the horizon) counts only the years before the 2032 rule, and
# coal cofired with gas (gas_conv) only to UEPA_CLCFYR. (ECP's option 3 exists while the group's retirement year is at
# least E + 2 and then counts the whole tail, so cutting gas_conv at UEPA_CLCFYR is a further approximation.)
RETIRE_TAIL_PROXY_GROUPS = ("gas_cc", "gas_ct", "steam", "gas_conv", "coal")


def retirement_tail_proxy(year: int, firm_annual, keep_annual, rate: float, last_year: int | None = None,
                          horizon: int = HORIZON_YEARS) -> np.ndarray:
    """What retiring a GW of existing gas or oil capacity in `year` gives up in the rest of ECP's horizon, in this year's
    money (k$ per GW): each later year to `last_year` in which the plant could still run, the firm capacity the plan
    would then have to build, `firm_annual` (a new turbine's annual cost, the cheapest firm type), less the plant's own
    `keep_annual`, never below zero, discounted at `rate`. Charged on the retirement column, it makes the one-year LP
    keep a plant whenever keeping it is cheaper than a new turbine later. An approximation of ECP's option-3 test
    (RETIRE_TAIL_PROXY): ECP values the tail's firm capacity at its own tail reserve dual, not a turbine's cost."""
    gain = np.maximum(np.asarray(firm_annual, dtype=float) - np.asarray(keep_annual, dtype=float), 0.0)
    last = year + horizon - 1 if last_year is None else last_year
    pv = sum((1.0 + rate) ** -k for k in range(1, horizon) if year + k <= last)
    return gain * pv


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


def _capture_charge(case, group: str, life: float, year: int, snapshot):
    """The 45Q credit dispatch overpays a new capture plant (_credit_overpaid), 1987$/kW-year."""
    tons = case.heat_rate[group] / 1000.0 * dispatch.CO2_PER_TBTU[dispatch.CAPTURE_GROUPS[group]] * dispatch.capture_rate(group)
    return _credit_overpaid(case, group, life, year, snapshot) * case.credit_45q * tons * CCS_CAPACITY_FACTOR * 8.76


def initial_capacity(snapshot, year_before: int) -> dict:
    """Year-end capacity by group in the year before the first solve, from the reference run."""
    y = year_before - history.FIRST_YEAR
    cap = {g: dispatch._ucap(snapshot, p, y) for g, p in dispatch.CAPACITY_PREFIXES.items()}
    cap["coal"] = np.maximum(cap["coal"] - cap["coal_ccs"], 0.0)
    cap["gas_conv"] = np.zeros(NUM_R)
    if dispatch.COFIRE_GROUP:
        # The reference run's coal-gas cofiring units (prefix ng, less what it keeps after UEPA_CLCFYR) cofire like the
        # LP's own conversions, so they start in gas_conv: coal share UEPA_CGSH, retired after UEPA_CLCFYR.
        cof = np.minimum(cofiring_existing(snapshot, year_before + 1), cap["steam"])
        cap["steam"] = cap["steam"] - cof
        cap["gas_conv"] = cof
    cap["gas_cc_new"] = np.zeros(NUM_R)
    cap["gas_ct_new"] = np.zeros(NUM_R)
    return {g: cap[g] for g in STATE_GROUPS}


def dated_changes(year: int):
    """Plant-file additions and retirements dated to `year`, with the state floors, by group and region, GW."""
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
    if STATE_FLOORS:
        for code, g in FLOOR_GROUP.items():
            adds[g] += plants.floor_adds_gw(year, (code,))
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
        return (cap[:, None, None] * (case.credit_profile or case.profile)[group]).sum(axis=0) / cap.sum()       # national CF by day and hour

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
    if ECP_RESERVE:      # ECP's own reserve coefficients (capacity_credit: RNWFAC, UPCCR(PS), CAP_CREDIT_LDC)
        credits["hydro"] = capacity_credit.HYDRO_CREDIT
        credits["pumped"] = capacity_credit.PUMPED_CREDIT
        credits["battery"] = capacity_credit.storage_credits(load_hr, cap0, case.credit_profile or case.profile)
    return credits


def reliability_adjustment(snapshot, year: int) -> np.ndarray:
    """UTRELADJ (GW by region): firm capacity rights on the interregional lines ECP built in earlier years, 0.75 of
    each line, added to the exporter's reserve requirement and taken off the importer's (uecp.f 32118-32166, EP$MRM
    PKADJ). From EIA's run, since this LP builds no lines."""
    a = np.asarray(snapshot["UETTOUT/utreladj"], dtype=float)
    return a[:NUM_R, min(year - 1990, a.shape[1] - 1)]


def _blocks(a: np.ndarray, hours: int = BLOCK_HOURS) -> np.ndarray:
    """Average the 24 hours of a (..., 36, 24) array into blocks of `hours` hours."""
    return a.reshape(a.shape[:-1] + (24 // hours, hours)).mean(axis=-1)


def monthly_days(cs):
    """The dispatch case `cs` with each month's three day types averaged into one (12 typical days)."""
    w = cs.weights.reshape(12, 3)
    tot = w.sum(axis=1)

    def mean(a):
        b = np.asarray(a, dtype=float)
        b = b.reshape(b.shape[0], 12, 3, -1)
        return (b * (w / tot[:, None])[None, :, :, None]).sum(axis=2)

    prof = lambda d: None if d is None else {k: mean(v) for k, v in d.items()}
    links = dict(cs.links, capacity_gw=mean(cs.links["capacity_gw"][:, :, None])[:, :, 0])
    return replace(cs, weights=tot, shapes=mean(cs.shapes), profile=prof(cs.profile),
                   build_profile=prof(cs.build_profile), links=links)


def capacity_payment(dual: np.ndarray, tail_dual: np.ndarray, annuity: float, turbine: np.ndarray) -> np.ndarray:
    """RMAVG (uecp.f EP$RELRM 1534 and 29966-30015): the reserve price EIA passes on, 1987$/kW-year. Half is NETCON (85%)
    of a new turbine's levelized cost; a quarter is the duals of planning years 2 and 3 levelized over the horizon; a
    quarter is planning year 2's dual, capped at that. Weights from ldsmstr.txt. `dual`, `tail_dual`: this year's and the
    tail's reserve row duals, 1987$/kW (the tail's a present value)."""
    lines = (INPUT / "emm" / "ldsmstr.txt").read_text(encoding="latin-1").splitlines()
    k = next(i for i, l in enumerate(lines) if "NET CONE" in l)
    netcon, w1, w2, w3, w4 = [float(v) for v in lines[k + 1].split()[:5]]
    level = (dual + tail_dual) / annuity
    return w1 * netcon * turbine + w2 * level + w3 * dual + w4 * np.minimum(dual, level)


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


# Interest during construction (uread.f EPINCST, called for every build column in uecp.f EP$BDSP,62): ECP spends the
# overnight cost over the construction years by the type's COSTPERF profile UPCPRO, each year's spending in that year's
# dollars, and carries the work in progress at the plant's rate of return, EWGROR (construction_rate; half a year on
# that year's spending) to the online year. The book value it then annualizes is overnight x this factor. A combined cycle (3 years, 25/50/25%)
# carries about 7% more than a turbine (2 years, 35/65%) or a battery (1 year). Off: overnight cost only.
CONSTRUCTION_INTEREST = True


def construction_factor(snapshot, code: str, year: int, rate: float) -> float:
    """Installed cost over overnight cost for ECP type `code` coming online in `year` (EPINCST's BVBOOK), in the online
    year's real dollars: spending in year online - UPCLYR + k at the price level of that year (MC_JPGDP), work in
    progress compounding at `rate` with half a year on each year's spending."""
    params = technology.type_parameters()
    codes = technology.ecp_codes()
    i = codes.index(code)
    clt = int(params["construction_lead_years"][i])
    prof = np.asarray(named_ranges(technology.ECPDATY, "COSTPERF")["UPCPRO"], dtype=float).reshape(len(codes), -1)[i]
    jp = np.asarray(snapshot["MACOUT/mc_jpgdp"], dtype=float).ravel()
    at = lambda y: jp[min(max(y - 1987, 0), jp.size - 1)]
    book = 0.0
    for k in range(clt):
        spend = float(prof[k]) * at(year - clt + k) / at(year)
        book = book + spend + (book + 0.5 * spend) * rate
    return book if book > 0 else 1.0


def capital_costs(snapshot, year: int, case, parts: dict | None = None, resource: dict | None = None,
                  codes_of: dict | None = None, columns: dict | None = None) -> dict:
    """Annual cost of a new plant built in `year`, by build group: {group: (25,) k$ per GW-year}, net of the ITC
    and PTC, with ECP's learned overnight cost and the year's financing (ECP_BUILD_COST, else a level annuity).
    codes_of: {group: ECP type} to cost in place of BUILDS. `parts` gets what a build step of cost multiple mu adds: a function of mu (STEP_PREMIUM_LIFETIME), or the year's
    capital charge the multiple scales."""
    params = technology.type_parameters()
    codes = technology.ecp_codes()
    reg = technology.regional_costs()
    sub = named_ranges(technology.ECPDATY, "SUBSIDY")
    itc_tab = np.array(sub["UPCSBYR"]).reshape(80, -1)
    ptc_tab = np.array(sub["UPGSUBYR"]).reshape(80, -1)
    col = min(year, 2050) - 2010
    cost_year = min(year, 2050)
    capital = {}
    for g, code in (codes_of or BUILDS).items():
        i = codes.index(code)
        ovn = learned_overnight(snapshot, code, cost_year)
        if ovn is None:
            ovn = params["overnight_cost"][i] * reg["regional_multiplier"][:NUM_R, i] * reg["area_multiplier"][:NUM_R, i]
        itc = max(itc_tab[i, col], 0.0)
        if ECP_BUILD_COST:
            if resource is not None and g in resource:
                ovn = ovn * resource[g]["cost"]
            wires = reg["transmission_overnight_cost"][:NUM_R, i] * (
                reg["transmission_charge_rate"][:NUM_R, i] - TAX_FCF_ADJ)
            renewable = g in ("wind", "solar")
            cf = (case.build_profile or case.profile)[g].mean(axis=(1, 2)) if renewable else 0.0
            ptc = tuple(max(ptc_tab[i, min(col + k, ptc_tab.shape[1] - 1)], 0.0) if renewable else 0.0 for k in (0, 1))
            column = ecp_cost.build_column(snapshot, code, cost_year, ovn * (1.0 - itc), params["fom"][i], wires,
                                           0.0 if g == "battery" else reg["transmission_fom"][:NUM_R, i], ptc, cf,
                                           int(sub["UPGSYD"][i]) or 1992, int(sub["UPGSYR"][i]))
            annual = ecp_cost.one_year_cost(column)
            if columns is not None:
                columns[g] = column
            if parts is not None:
                if STEP_PREMIUM_LIFETIME:
                    parts[g] = lambda mu, column=column, annual=annual: 1.0e3 * (ecp_cost.one_year_cost(column, mu) - annual)
                else:
                    parts[g] = column["capital"] * 1.0e3 / column["annuity"]
            if g in dispatch.CAPTURE_GROUPS:
                annual = annual + _capture_charge(case, g, params["economic_life"][i], year, snapshot)
            capital[g] = annual * 1.0e3
            continue
        rate = discount_rate(snapshot, cost_year) + risk_premium(snapshot, cost_year, code)
        if CONSTRUCTION_INTEREST:
            ovn = ovn * construction_factor(snapshot, code, cost_year, construction_rate(snapshot, cost_year, code))
        if resource is not None and g in resource:
            ovn = ovn * resource[g]["cost"]      # UPWNCCST and UPPVCCST hold renew.f's ConsLT of the reference path
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
            annual = annual + _capture_charge(case, g, params["economic_life"][i], year, snapshot)
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
               recent_adds: dict | None = None, resource: dict | None = None,
               intermittent_cap: np.ndarray | None = None) -> YearResult:
    """One year of the loop. `groups` (dispatch group -> retire_groups.Groups) splits retirements into ECP's
    retirement groups; without it a whole region and type retires at one cost. decide=False solves dispatch
    only (no builds, retirements, retrofits or conversions), to get prices. horizon: plan over ECP's horizon
    (HORIZON, the default) or this year only. recent_adds: build group -> the last five years' national additions
    (GW, oldest first) for ECP's build steps (BUILD_STEPS); without it the steps start from ESTMNADD. resource:
    {wind, solar: for_build_year} of this path (CapacityPath.resources); without it the reference run's resource.
    intermittent_cap: (25,) the most wind and solar output over load (intermittent_limit); without it no cap."""
    horizon = HORIZON if horizon is None else horizon
    y = year - history.FIRST_YEAR
    case = case if case is not None else dispatch.build_case(snapshot, year, "none")
    if ECP_BUILD_CF and case.build_profile is not None and case.build_profile["wind"].shape[-1] == 24:
        case = replace(case, build_profile=ecp_build_profile(snapshot, year))
    if resource is not None and case.build_profile is not None:
        scaled = {g: np.minimum(case.build_profile[g] * v["cf"][:, None, None], 1.0) for g, v in resource.items()}
        case = replace(case, build_profile=dict(case.build_profile, **scaled))
    adds, rets = dated_changes(year)
    rule = epa111()
    rets = epa111_retirements(snapshot, year, cap_in, rets)
    cap0 = {g: np.maximum(cap_in[g] + adds[g] - rets[g], 0.0) for g in STATE_GROUPS}

    # --- costs of building ---
    params = technology.type_parameters()
    codes = technology.ecp_codes()
    hr_new_all = technology.new_heat_rate(year)        # UPHTRT (ucape.f 625-641): UPPHRT0 for every gas type
    capital_only = {}
    columns: dict = {}
    capital = capital_costs(snapshot, year, case, capital_only, resource, columns=columns)
    tail_on = ECP_TAIL and ECP_BUILD_COST and decide and not horizon and year >= FIRST_UNPLANNED_YEAR
    life = (lambda col: 1.0) if STEP_PREMIUM_LIFETIME else (lambda col: col["annuity"])

    # --- characteristics of the groups ---
    heat, vom, oil_share = dict(case.heat_rate), dict(case.vom), dict(case.oil_share)
    avail = dict(case.avail)
    for g, base in BASE_OF.items():
        i = codes.index(BUILDS[g])
        heat[g] = np.full(NUM_R, float(hr_new_all[i]))
        vom[g] = np.full(NUM_R, float(params["vom"][i]))
        oil_share[g] = np.zeros(NUM_R)
        avail[g] = avail[base]
    # ECP's conversion column burns gas at the coal group's ECP heat rate times 1 + UCL_CL_NG_HR_PEN (ecp.ams EP$COAL,27:
    # ULHTRT_ECP x (1 + pen) less the gas steam average). ULHTRT_ECP is WHRATEA x Target_EFF / Max_EFF (udat.f
    # 7280-7285), the part-load heat rate, which is what heat["coal"] carries here (dispatch.COAL_PART_LOAD_HEAT_RATE).
    # EFD differs on purpose: uecp.f 28113 writes WHRATE x (1 + pen) into the converted unit's record, and the
    # converted type has no part-load curve, so dispatch uses the plain coal heat rate (coal_plain).
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
        mask = on & np.isin(u.efd_type, dispatch.existing_types(g))
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
    conv_unit = np.asarray(tb["T_NG_COST"], dtype=float) + np.asarray(tb["T_NG_TRAN"], dtype=float)
    conv_elig = coal_mask & (np.asarray(tb["T_NG_COST"], dtype=float) > 0)
    conv_gw = np.zeros(NUM_R)
    np.add.at(conv_gw, u.region[conv_elig] - 1, u.summer_mw[conv_elig] / 1000.0)
    conv_gw = np.minimum(conv_gw, cap0["coal"])
    conv_capital = _weighted_by_region(conv_unit, u.summer_mw, conv_elig, CONVERT_COST_KW)
    by_unit = CONVERT_BY_UNIT or tail_on      # ECP's conversion columns are per coal group
    if by_unit:
        age_c = np.maximum(year - u.online_year, 0)
        keep_u = (np.asarray(tb["T_FOM"], dtype=float) + np.asarray(tb["T_CAPAD"], dtype=float)
                  + np.where(age_c >= 30, AGE_ADDER_1987, 0.0)) * (1.0 - RETIREMENT_HURDLE)
        conv_step_gw, conv_step_capital, conv_step_keep = conversion_steps(
            conv_unit[conv_elig], keep_u[conv_elig], u.summer_mw[conv_elig], u.region[conv_elig],
            _crf(discount_rate(snapshot, year), HORIZON_YEARS))
        # the plant file's eligible units can exceed this year's coal in the LP: scale every step down alike
        tot = conv_step_gw.sum(axis=1)
        conv_step_gw = conv_step_gw * np.where(tot > conv_gw, conv_gw / np.maximum(tot, 1e-9), 1.0)[:, None]
    else:
        conv_step_gw = conv_gw[:, None]
    retro_cost = _weighted_by_region(tb["T_CCSROV"], u.summer_mw, elig, 1100.0)
    retro_fom = _weighted_by_region(tb["T_CCSF"], u.summer_mw, elig, 8.0)
    retro_tons = case.heat_rate["coal_ccs"] / 1000.0 * dispatch.CO2_PER_TBTU["coal"] * dispatch.capture_rate("coal_ccs")
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
    def renewable_upper(g, limit, build_year, times=1.0):
        bound = np.inf
        if RENEW_BUILD_BOUND:
            own = (resource or {}).get(g)
            bound = times * (own["bound"] if own is not None else renewable_build_bound(snapshot, g, build_year))
        return xr.DataArray(np.minimum(np.full(NUM_R, limit), bound), coords=[R])

    bw = m.add_variables(lower=0, upper=renewable_upper("wind", room * can_build["wind"], year), name="build_wind")
    bs = m.add_variables(lower=0, upper=renewable_upper("solar", room * can_build["solar"], year), name="build_solar")
    bb_upper = np.full(NUM_R, room * can_build["battery"])
    if ECP_STORAGE_BUILDS and room > 0:
        bb_upper = np.minimum(bb_upper, battery_build_limit(snapshot, year, case))
    bb = m.add_variables(lower=0, upper=xr.DataArray(bb_upper, coords=[R]), name="build_battery")
    # UCL_CL_NG_SYR = max(2014, first ECP year + the conversion's lead time (NG, UPCLYR 2) + 1) (udat.f 13042): 2028
    first_convert = START_YEAR + int(lead[codes.index("NG")]) + 1
    can_convert = year >= first_convert and decide and (not rule["switch"] or year <= rule["gas_switch_last"])
    CS = pd.Index(np.arange(conv_step_gw.shape[1]), name="cstep")
    convert_k = m.add_variables(lower=0, upper=xr.DataArray(conv_step_gw * can_convert, coords=[R, CS]),
                                name="convert")
    convert = convert_k.sum("cstep")
    m.add_constraints(retrofit.sum() <= RETROFIT_LIMIT_GW, name="retrofit_limit")
    step_premium = 0
    if BUILD_STEPS and room > 0:
        renewable = {"wind": bw, "solar": bs, "battery": bb}
        for g, code in STEP_CODES.items():
            total = renewable[g].sum() if g in renewable else build.sel(group=g).sum()
            steps = build_steps(code, (recent_adds or {}).get(g, [0.0] * 5), planned_in_step(year, g),
                                (recent_adds or {}).get(f"{g}/floor"))
            if g == "battery" and ECP_STORAGE_BUILDS:
                steps = steps[:1]          # ECP builds batteries in the first step only (CALC_STORAGE_VAL,12)
            S = pd.Index(range(len(steps)), name="step")
            sv = m.add_variables(lower=0, upper=xr.DataArray([b for b, _ in steps], coords=[S]), name=f"build_step_{g}")
            if g == "gas_cc_new" and CONVENTIONAL_CC and ECP_BUILD_COST:
                conv_cost: dict = {}
                cc_col: dict = {}
                conv = capital_costs(snapshot, year, case, conv_cost, resource, {g: "CC"}, cc_col)[g]
                if tail_on:
                    conv_cost[g] = lambda mu: (mu - 1.0) * cc_col["gas_cc_new"]["capital"] * 1.0e3 / life(cc_col["gas_cc_new"])
                    conv = capital[g] + (cc_col[g]["first"] - columns[g]["first"]) * 1.0e3
                cc_steps = build_steps("CC", (recent_adds or {}).get("gas_cc_new/floor", [0.0] * 5))
                C = pd.Index(range(len(cc_steps)), name="step")
                cc_sv = m.add_variables(lower=0, upper=xr.DataArray([b for b, _ in cc_steps], coords=[C]), name="build_step_cc")
                over_cc = conv_cost[g] if callable(conv_cost[g]) else (lambda mu: (mu - 1.0) * conv_cost[g])
                base_gap = float(np.mean(conv - capital[g]))
                step_premium = step_premium + (cc_sv * xr.DataArray(
                    [base_gap + float(np.mean(over_cc(mu))) for _, mu in cc_steps], coords=[C])).sum()
                total = total - cc_sv.sum()
            m.add_constraints(total - sv.sum() == 0, name=f"build_steps_{g}")
            if tail_on:
                capital_only[g] = lambda mu, col=columns[g]: (mu - 1.0) * col["capital"] * 1.0e3 / life(col)
            over = capital_only[g] if callable(capital_only[g]) else (lambda mu, base=capital_only[g]: (mu - 1.0) * base)
            premium = xr.DataArray([float(np.mean(over(mu))) for _, mu in steps], coords=[S])
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
    if year < RULE_YEAR:            # conversions are not retirements (ECP leaves them out of MXRET, EP$COAL,24)
        econ = econ + retire.sel(group="coal")
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

    def operate(tag: str, cs, c0: dict, capv_p, wind_tot, solar_tot, batt_tot, bh: int = BLOCK_HOURS, new_w=0, new_s=0, new_b=0,
                lp=None, short_cost: float = RESERVE_SHORTFALL_COST, mcf=mcf, int_cap=None):
        """Dispatch and reserve margin of one planning period: case `cs` (its load, fuel prices and profiles),
        existing capacity `c0`, thermal capacity `capv_p` and wind, solar and battery totals (expressions in the
        decision variables). Returns its operating cost (1987 k$ for one year) and the pieces the result needs."""
        lp = cs if lp is None else lp          # the typical days of the dispatch (monthly_days in the tail)
        D = pd.Index(np.arange(len(lp.weights)), name="day")
        month_of_day = np.repeat(np.arange(12), len(lp.weights) // 12)
        Bk = pd.Index(np.arange(24 // bh), name="block")
        ones = xr.DataArray(np.ones((NUM_R, len(D), 24 // bh)), coords=[R, D, Bk])
        hours_w = xr.DataArray(lp.weights * bh, coords=[D])                    # hours per year each slice stands for

        def by_region(a):
            return xr.DataArray(np.asarray(a, dtype=float), coords=[R]) * ones

        def cf_of(group):
            return xr.DataArray(cs.monthly_cf[group][:, month_of_day], coords=[R, D]) * ones

        load_hr = cs.net_load_twh[:, None, None] * 1000.0 * cs.shapes           # GW in each hour
        credits = capacity_credits(cs, c0, load_hr, np.repeat(np.arange(12), 3))
        load_gw = xr.DataArray(_blocks(cs.net_load_twh[:, None, None] * 1000.0 * lp.shapes, bh), coords=[R, D, Bk])
        prof = {k: xr.DataArray(_blocks(v, bh), coords=[R, D, Bk]) for k, v in lp.profile.items()}

        g_th = m.add_variables(lower=0, coords=[R, T, D, Bk], name=f"gen{tag}")
        max_load = ECP_MAX_LOAD and decide and tag in ("", "_tail")
        if not max_load:
            m.add_constraints(g_th - capv_p * one_minus_for <= 0, name=f"gen_limit{tag}")
        m.add_constraints((g_th * hours_w).sum(["day", "block"]) - capv_p * (mcf * 8760.0) <= 0, name=f"energy_limit{tag}")

        cost = np.zeros((NUM_R, len(TG)))
        gas_frac = np.zeros((NUM_R, len(TG)))
        for k, g in enumerate(TG):
            oil_price = cs.price["residual"] if g == "steam" else cs.price["distillate"]
            is_coal = g.startswith("coal")
            fuel = (1 - oil_share[g]) * cs.price["coal" if is_coal else "gas"] + oil_share[g] * oil_price
            if g == "gas_conv" and ECP_CONVERTED_BURNS_GAS and decide:
                fuel = cs.price["gas"]
            elif g == "gas_conv" and rule["switch"] and CONVERT_SPLIT_FUEL:
                fuel = cs.price["coal"]           # the coal part's cost; output above it pays the gas premium below
            elif g == "gas_conv" and rule["switch"]:
                # EPA 111 cofiring: at most UEPA_CGSH of the fuel is coal (udat.f 6457), the rest gas
                fuel = rule["cofire_coal_share"] * cs.price["coal"] + (1.0 - rule["cofire_coal_share"]) * cs.price["gas"]
            cost[:, k] = heat[g] / 1000.0 * fuel + vom[g]
            if not is_coal:
                gas_frac[:, k] = (1.0 - rule["cofire_coal_share"]) if (g == "gas_conv" and rule["switch"]) else 1 - oil_share[g]
                if g == "gas_conv" and ECP_CONVERTED_BURNS_GAS and decide:
                    gas_frac[:, k] = 1.0
                elif g == "gas_conv" and rule["switch"] and CONVERT_SPLIT_FUEL:
                    gas_frac[:, k] = 0.0          # its gas burn is conv_gas below
            if g in dispatch.CAPTURE_GROUPS:
                share = cs.credit_share[g] if cs.credit_share is not None else 1.0
                cost[:, k] -= cs.credit_45q * share * heat[g] / 1000.0 * dispatch.CO2_PER_TBTU[dispatch.CAPTURE_GROUPS[g]] * dispatch.capture_rate(g)
        cost_da = xr.DataArray(cost, coords=[R, T])
        heat_arr = np.stack([heat[g] for g in TG], axis=1)

        wind_out = wind_tot * prof["wind"]
        solar_out = solar_tot * prof["solar"]
        if cs.build_profile is not None:      # capacity built by the LP runs on the new-build profile, not the fleet's
            bprof = {k: xr.DataArray(_blocks(v, bh), coords=[R, D, Bk]) for k, v in lp.build_profile.items()}
            wind_out = wind_out + new_w * (bprof["wind"] - prof["wind"])
            solar_out = solar_out + new_s * (bprof["solar"] - prof["solar"])
        fixed = by_region(c0["nuclear"]) * cf_of("nuclear") + by_region(c0["other"]) * cf_of("other")

        g_hy = m.add_variables(lower=0, upper=by_region(c0["hydro"]), name=f"hydro{tag}")
        month_w = xr.DataArray(np.eye(12)[month_of_day], coords=[D, MO])
        days_in_month = np.array([lp.weights[month_of_day == mo].sum() for mo in range(12)])
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

        links = lp.links
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
        load_rm = load_hr
        if ECP_RESERVE and ECP_PEAK:
            sy = ecp_load.system_load(cs.year)
            if sy is not None:     # LDSM's load, moved to this run's demand (scaled shape plus flat added load)
                ref = _reference_case(snapshot, cs.year).net_load_twh
                load_rm = ecp_load.follow_run(sy, cs.net_load_twh, ref, cs.flat_twh)
        if max_load:
            sub = {g: np.maximum(c0[g], 0.0) for g in capacity_credit.INTERMITTENT}
            prof36 = cs.credit_profile or cs.profile
            net36 = load_rm - sum(sub[g][:, None, None] * prof36[g] for g in capacity_credit.INTERMITTENT)
            if len(lp.weights) == 12:       # the tail's one day a month
                w3 = cs.weights.reshape(12, 3)
                mean3 = lambda a: (a.reshape(NUM_R, 12, 3, 24) * (w3 / w3.sum(axis=1)[:, None])[None, :, :, None]).sum(axis=2)
                slice_of, height = ecp_slice_heights(mean3(load_rm), lp.weights, np.arange(12), mean3(net36))
            else:
                slice_of, height = ecp_slice_heights(load_rm, cs.weights, month_of_day, net36)
            blk = block_slice(slice_of, bh)
            lf_tab = named_ranges(technology.ECPDATY, "SPNRSV")["SR_MAX_LF"]
            pmr_tab = named_ranges(technology.ECPDATY, "COSTPERF")["UPPMRT"]
            SE = pd.Index(np.arange(3), name="season")
            season_of = ecp_season_of_month()[month_of_day]
            hours_se = xr.DataArray(np.array([(lp.weights[season_of == q] * 24.0).sum() for q in range(3)]), coords=[SE])
            pm = m.add_variables(lower=0, coords=[R, T, SE], name=f"maintenance{tag}")
            pmr = xr.DataArray(np.array([float(pmr_tab[codes.index(SPIN_TYPE[g])]) for g in TG]), coords=[T])
            m.add_constraints((pm * hours_se).sum("season") - capv_p * (pmr * 8760.0) >= 0, name=f"maintenance_hours{tag}")
            fac = np.stack([np.take_along_axis(max_load_factor(height, float(lf_tab[codes.index(SPIN_TYPE[g])])),
                                               blk.reshape(NUM_R, -1), axis=1).reshape(blk.shape) for g in TG], axis=1)
            fac = xr.DataArray(fac, coords=[R, T, D, Bk]) * one_minus_for
            for q in range(3):
                days = np.flatnonzero(season_of == q)
                f_q = fac.isel(day=days)
                m.add_constraints(g_th.isel(day=days) - capv_p * f_q + pm.sel(season=q) * f_q <= 0, name=f"max_load{tag}_{q}")
        net_cap = None
        if ECP_RESERVE:      # CAP_CREDIT's net load on ECP's adjusted capacities (the reference run's adjustment)
            off = capacity_credit.cap_adjustment(snapshot, cs.year)
            net_cap = {g: np.maximum(c0[g] + off[g], 0.0) for g in capacity_credit.INTERMITTENT}
        icc = capacity_credit.credits(load_rm, c0, cs.credit_profile or cs.profile, cs.weights, net_cap)
        credits.update({"wind_by_region": icc["wind"], "solar_by_region": icc["solar"]})
        req = margin * icc["peak"] + icc["net_peak"]
        if ECP_RESERVE:
            req = req + reliability_adjustment(snapshot, cs.year)
            if ECP_PEAK and load_rm is not load_hr:
                req = req + ecp_load.firm_contracts(cs.year) + ecp_load.cogen_adjustment(snapshot, cs.year)
        credits["requirement"] = req
        requirement = xr.DataArray(req, coords=[R])
        firm = capv_p.sum("group")
        firm = firm + wind_tot * xr.DataArray(icc["wind"], coords=[R])
        firm = firm + solar_tot * xr.DataArray(icc["solar"], coords=[R])
        firm = firm + batt_tot * xr.DataArray(np.broadcast_to(credits["battery"], (NUM_R,)).copy(), coords=[R])
        const_firm = c0["nuclear"] + c0["other"] + c0["hydro"] * credits["hydro"] + c0["pumped"] * credits["pumped"]
        lend_share = 0.0 if ECP_RESERVE else FIRM_TRANSFER_SHARE
        lend = m.add_variables(lower=0, upper=xr.DataArray(lend_share * links["capacity_gw"].mean(axis=1), coords=[L]),
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
            + (shortfall * short_cost).sum()
        conv_gas = None
        if CONVERT_SPLIT_FUEL and rule["switch"] and not (ECP_CONVERTED_BURNS_GAS and decide):
            # the gas part of gas_conv output: whatever runs above the coal part (UEPA_CGSH of available capacity)
            conv_gas = m.add_variables(lower=0, coords=[R, D, Bk], name=f"conv_gas{tag}")
            gc = g_th.sel(group="gas_conv")
            coal_part = capv_p.sel(group="gas_conv") * float(one_minus_for.sel(group="gas_conv")) * rule["cofire_coal_share"]
            m.add_constraints(gc - conv_gas - coal_part <= 0, name=f"conv_coal_part{tag}")
            m.add_constraints(conv_gas - gc <= 0, name=f"conv_gas_part{tag}")
            premium = heat["gas_conv"] / 1000.0 * (cs.price["gas"] - cs.price["coal"])
            operating = operating + (conv_gas * xr.DataArray(premium, coords=[R]) * hours_w).sum()
        pot = ((wind_out + solar_out) * hours_w).sum(["day", "block"])
        if int_cap is not None:
            # EP$LINT: no dearer than the escape column, 2000 $/MWh (GWh x $/MWh = k$)
            pv_gwh = end_use_pv(snapshot, min(cs.year, LAST_MODEL_YEAR)) * 1000.0
            over = m.add_variables(lower=0, coords=[R], name=f"intermittent_over{tag}")
            m.add_constraints(pot - over <= xr.DataArray(int_cap * (cs.net_load_twh * 1000.0 + pv_gwh) - pv_gwh, coords=[R]),
                              name=f"intermittent_cap{tag}")
            operating = operating + (over * INT_ESCAPE_COST).sum()
        if STATE_RPS and decide and tag in ("", "_tail"):
            ry = min(cs.year, LAST_MODEL_YEAR)
            ref_net = _reference_case(snapshot, ry).net_load_twh
            sales = np.asarray(snapshot["UDATOUT/qelasn"], dtype=float)[:NUM_R, ry - 1990] / 1000.0 \
                * np.divide(cs.net_load_twh, ref_net, out=np.ones(NUM_R), where=ref_net > 0)
            mean_cf = {g: (_blocks(lp.profile[g], bh) * (lp.weights * bh)[None, :, None]).sum(axis=(1, 2)) / 8760.0 for g in ("wind", "solar")}
            new_cf = {g: (_blocks((lp.build_profile or lp.profile)[g], bh) * (lp.weights * bh)[None, :, None]).sum(axis=(1, 2)) / 8760.0
                      for g in ("wind", "solar")}
            hy = (cs.monthly_cf["hydro"] * days_in_month[None, :]).sum(axis=1) / days_in_month.sum()
            data = rps.rows(snapshot, ry, ry if tag == "" else min(year + 1, LAST_MODEL_YEAR), sales, links,
                            {"WN": mean_cf["wind"], "WF": mean_cf["wind"], "PV": mean_cf["solar"], "PT": mean_cf["solar"], "HY": hy},
                            lambda y_: ecp_cost.deflator(snapshot, y_))
            floors_wf = np.maximum(offshore_gw(ry) - plants.capacity_gw(ry, ("WFS",))[:NUM_R], 0.0) * mean_cf["wind"] * 8.76
            data["left"]["WF"] = data["left"].get("WF", np.zeros(NUM_R)) + floors_wf
            wf_all = offshore_gw(ry) * mean_cf["wind"] * 8.76
            other_pv = sum(data["pool"].get(k, np.zeros(NUM_R)) for k in ("PT", "SO"))
            none = np.zeros(NUM_R)
            base = {"WN": np.maximum(c0["wind"] * mean_cf["wind"] * 8.76 - wf_all - data["used"].get("WN", none), 0.0),
                    "PV": np.maximum(c0["solar"] * mean_cf["solar"] * 8.76 - other_pv - data["used"].get("PV", none), 0.0)}
            fresh = {"WN": new_w * xr.DataArray(new_cf["wind"] * 8.76, coords=[R]), "PV": new_s * xr.DataArray(new_cf["solar"] * 8.76, coords=[R])}
            J = pd.Index(np.arange(len(data["cols"])), name="rcol")
            I_ = pd.Index(np.arange(len(data["tranches"])), name="tranche")
            rq = m.add_variables(lower=0, coords=[J], name=f"rps_credit{tag}")
            esc = m.add_variables(lower=0, coords=[I_], name=f"rps_escape{tag}")
            m.add_constraints((rq * xr.DataArray(data["coef"], coords=[I_, J])).sum("rcol") + esc
                              >= xr.DataArray(data["need"] - data["const"], coords=[I_]), name=f"state_rps{tag}")
            for k in sorted({c[1] for c in data["cols"]}):
                use = np.zeros((NUM_R, len(J)))
                for j, (_, kind, a, _b) in enumerate(data["cols"]):
                    if kind == k:
                        use[a, j] = 1.0
                lhs = (rq * xr.DataArray(use, coords=[R, J])).sum("rcol")
                if k in fresh:
                    m.add_constraints(lhs - fresh[k] <= xr.DataArray(base[k], coords=[R]), name=f"rps_pool_{k}{tag}")
                else:
                    m.add_constraints(lhs <= xr.DataArray(data["left"][k], coords=[R]), name=f"rps_pool_{k}{tag}")
            pairs = sorted({(a, b) for _, _, a, b in data["cols"] if b >= 0})
            if pairs:
                Q = pd.Index(np.arange(len(pairs)), name="pair")
                use = np.zeros((len(pairs), len(J)))
                on_link = np.zeros((len(pairs), len(L)))
                for q_, (a, b) in enumerate(pairs):
                    for j, (_, _, x_, y_) in enumerate(data["cols"]):
                        use[q_, j] = 1.0 if (x_, y_) == (a, b) else 0.0
                    on_link[q_, data["link"][(a, b)]] = 1.0
                flow = (trade * hours_w).sum(["day", "block"]) * 1.0e-3
                m.add_constraints((rq * xr.DataArray(use, coords=[Q, J])).sum("rcol")
                                  - (flow * xr.DataArray(on_link, coords=[Q, L])).sum("link") <= 0, name=f"rps_trade{tag}")
            operating = operating + (esc * xr.DataArray(data["price"] * 1000.0, coords=[I_])).sum()
        gas_steps = None
        if ECP_GAS_CURVE and tag in ("", "_tail"):
            # ECP's gas supply steps (cSUNGX on rFUELNGXle): the burn fills them cheapest first; each step adds
            # WHDEX x (PDEL - 1) to the delivered price already in `cost` (k$ = TBtu x $/MMBtu x 1000).
            gy = min(cs.year, LAST_MODEL_YEAR) if tag else year
            bound, ratio = gas_curve_steps(snapshot, gy)
            wh = gas_curve_wellhead(snapshot, gy)
            S = pd.Index(np.arange(len(bound)), name="gas_step")
            gas_steps = m.add_variables(lower=0, upper=xr.DataArray(bound, coords=[S]), name=f"gas_step{tag}")
            burn = (g_th * xr.DataArray(heat_arr * gas_frac / 1.0e6, coords=[R, T]) * hours_w).sum()
            if conv_gas is not None:
                burn = burn + (conv_gas * xr.DataArray(heat["gas_conv"] / 1.0e6, coords=[R]) * hours_w).sum()
            m.add_constraints(gas_steps.sum() - burn == 0, name=f"gas_curve{tag}")
            operating = operating + (gas_steps * xr.DataArray(wh * (ratio - 1.0) * 1000.0, coords=[S])).sum()
        spin = {}
        if SPIN_RESERVE and tag != "_tail":
            # ECP's spinning reserve rows (EP$MRM,8-13). A dispatchable unit carries reserve only while it runs: in
            # ECP's dispatch modes (EP$ODSP,34-53) a committed unit generates between SR_MIN_CF and its derated
            # capacity and its headroom (SR_CREDIT 1 for every type) is reserve, so reserve <= capacity - output and
            # reserve <= output x (1 / SR_MIN_CF - 1). Conventional hydro carries none: ecp.ams leaves WIHY out of
            # every hydro reserve coefficient (EP$ORNW,113-116). Pumped storage runs like a thermal unit in its
            # min-load mode (EP$ORNW,116: output SR_MIN_CF, reserve 1 - SR_MIN_CF); batteries their discharge
            # headroom (CALC_STORAGE_VAL,5/14, ReStore's StoSR), here up to one hour of stored energy. Nuclear and
            # other renewables their capacity less output (EP$NUC,24, EP$ORNW,28). Wind and solar raise the
            # requirement by SR_INT of their output. No reserve over the links (SR_TRAN_CREDIT is 0).
            mins = spin_min_cf()
            # ECP's slice heights are LDSM's load (EPHGHT) plus ADJ_HGHT, of which the firm contracts are ported
            adj = ecp_load.firm_contracts(cs.year) if load_rm is not load_hr else None
            # LDSM slices on net load, ECP's restart intermittent capacity (net_cap) on this year's profiles
            sub = net_cap if net_cap is not None else c0
            net_hr = load_rm - sum(sub[g][:, None, None] * (cs.credit_profile or cs.profile)[g] for g in capacity_credit.INTERMITTENT)
            storage_sr = {}
            for name in STORAGE_HOURS:
                if name == "battery" and ECP_STORAGE_SR:
                    # ReStore's fixed reserve per GW by ECP slice: existing storage at the EX share, this year's
                    # builds at the NW share
                    blk = block_slice(ecp_slice_heights(load_rm, cs.weights, month_of_day, net_hr)[0], bh)
                    ex = xr.DataArray(np.asarray(ECP_BATTERY_SR_EX)[blk], coords=[R, D, Bk])
                    nw = xr.DataArray(np.asarray(ECP_BATTERY_SR_NW)[blk], coords=[R, D, Bk])
                    storage_sr[name] = (batt_tot - new_b) * ex + new_b * nw
                    continue
                ss = m.add_variables(lower=0, coords=[R, D, Bk], name=f"spin_{name}{tag}")
                di = m.variables[f"{name}_discharge{tag}"]
                m.add_constraints(ss + di - sto_cap[name] <= 0, name=f"spin_{name}_headroom{tag}")
                if name == "pumped":
                    m.add_constraints(ss - di * (1.0 / mins["pumped"] - 1.0) <= 0, name=f"spin_{name}_committed{tag}")
                else:
                    m.add_constraints(ss - m.variables[f"{name}_soc{tag}"] <= 0, name=f"spin_{name}_energy{tag}")
                storage_sr[name] = ss
            const_sp = by_region(c0["nuclear"]) * (1.0 - cf_of("nuclear")) + by_region(c0["other"]) * (1.0 - cf_of("other"))
            if ECP_DISPATCH_MODES:
                spin = dispatch_modes(m, tag, cs, load_rm, net_hr, adj, bh, g_th, capv_p, one_minus_for, mins,
                                      sum(storage_sr.values()) + const_sp - SR_INT * (wind_out + solar_out), hours_w,
                                      R, T, D, Bk)
                operating = operating + spin["cost"]
            else:
                inv = xr.DataArray(np.array([1.0 / mins[g] - 1.0 for g in TG]), coords=[T])
                sp = m.add_variables(lower=0, coords=[R, T, D, Bk], name=f"spin{tag}")
                m.add_constraints(sp + g_th - capv_p <= 0, name=f"spin_headroom{tag}")
                m.add_constraints(sp - g_th * inv <= 0, name=f"spin_committed{tag}")
                supply = sp.sum("group") + sum(storage_sr.values())
                sr_req = xr.DataArray(spin_requirement(load_rm, cs.weights, month_of_day, bh, adj, net_hr), coords=[R, D, Bk])
                sp_short = m.add_variables(lower=0, coords=[R, D, Bk], name=f"spin_shortfall{tag}")
                m.add_constraints(supply - SR_INT * (wind_out + solar_out) + sp_short >= sr_req - const_sp,
                                  name=f"spin_reserve{tag}")
                operating = operating + (sp_short * (SPIN_SHORTFALL_COST * hours_w)).sum()
                spin = {"requirement": np.asarray(sr_req.values), "shortfall": sp_short}
        return {"operating": operating, "g_th": g_th, "unserved": unserved, "shortfall": shortfall, "credits": credits,
                "spin": spin, "potential": pot}

    def totals(c0, extra_w, extra_s, extra_b):
        return (xr.DataArray(c0["wind"], coords=[R]) + extra_w, xr.DataArray(c0["solar"], coords=[R]) + extra_s,
                xr.DataArray(c0["battery"], coords=[R]) + extra_b)

    p1 = operate("", case, cap0, capv, *totals(cap0, bw, bs, bb), new_w=bw, new_s=bs, new_b=bb,
                 int_cap=intermittent_cap)
    g_th, unserved, shortfall, credits = p1["g_th"], p1["unserved"], p1["shortfall"], p1["credits"]
    operating = p1["operating"]
    def add_tail(w: float, rate: float):
        """ECP's planning year 3 (ECP_TAIL): its variables and rows, and their cost in this year's money."""
        yf = year + TAIL_OFFSET
        c0f = dict(cap0)
        for yy in range(year + 1, yf + 1):
            a, r_ = dated_changes(yy)
            c0f = {g: np.maximum(c0f[g] + a[g] - r_[g], 0.0) for g in STATE_GROUPS}
        # shares of the tail's weight: 45Q for a plant online now (its years 2 to 12), coal in a cofiring unit (to UEPA_CLCFYR)
        pw = np.array([(1.0 + rate) ** -k for k in range(1, HORIZON_YEARS - 1)])
        last_credit, duration = dispatch.credit_rule(snapshot)[1:3]
        q45 = float(pw[: max(int(duration) - 1, 0)].sum() / pw.sum()) if year <= last_credit else 0.0
        cofire = float(sum(p for k, p in enumerate(pw, 1) if year + k <= rule["cofire_last"]) / pw.sum()) if rule["switch"] else 1.0
        f_conv = 1.0 - rule["cofire_coal_share"] * (1.0 - cofire) if rule["switch"] else 1.0
        # Coal without CCS is not in the tail: ECP's whole-horizon coal columns (cRETRO, commit year C) pay 28 years of fixed
        # O&M and sit in the tail rows at EPA_YRSHR only, and none is chosen in EIA's 2026 and 2030 solves (131.6 GW commit to
        # planning year 2, 0 GW to the tail in 2026).
        f_coal = 0.0
        cs = future_case(snapshot, year, yf, case)
        cs = replace(cs, profile=case.profile, build_profile=case.build_profile, credit_profile=case.credit_profile,
                     credit_share={g: np.full(NUM_R, q45) for g in dispatch.CAPTURE_GROUPS})
        lim = 100.0
        fb = m.add_variables(lower=0, upper=xr.DataArray(np.stack([np.full(NUM_R, lim if g in BUILDS else 0.0) for g in TG], axis=1),
                                                         coords=[R, T]), name="build_tail")
        fw = m.add_variables(lower=0, upper=renewable_upper("wind", lim, year + 1, RENEW_BOUND_TAIL), name="build_wind_tail")
        fs = m.add_variables(lower=0, upper=renewable_upper("solar", lim, year + 1, RENEW_BOUND_TAIL), name="build_solar_tail")
        fbb = m.add_variables(lower=0, upper=xr.DataArray(bb_upper, coords=[R]), name="build_battery_tail")
        # plants kept this year and retired for the tail, saving the tail's fixed O&M
        saved_tail, gone = 0, 0
        for g in ("gas_cc", "gas_ct", "steam", "coal_ccs", "gas_conv"):
            part = {"coal": f_coal, "gas_conv": f_conv}.get(g, 1.0)
            one = xr.DataArray(np.array([1.0 if x == g else 0.0 for x in TG]), coords=[T])
            if use_groups and g in RETIRABLE:
                j = RETIRABLE.index(g)
                cap_g = xr.DataArray(gcap[:, j, :], coords=[R, K])
                v = m.add_variables(lower=0, upper=cap_g, name=f"retire_tail_{g}")
                both = v + rg.sel(group=g)
                m.add_constraints(both <= cap_g, name=f"retire_tail_cap_{g}")
                saved_tail = saved_tail + (both * xr.DataArray(gcost[:, j, :] * (w * part), coords=[R, K])).sum()
                gone = gone + v.sum("rgrp") * (one * part)
            else:
                keep = fom_exist[g] if g in fom_exist else fom_made[g]
                v = m.add_variables(lower=0, upper=xr.DataArray(cap0[g], coords=[R]), name=f"retire_tail_{g}")
                both = v + retire.sel(group=g)
                m.add_constraints(both <= xr.DataArray(cap0[g], coords=[R]), name=f"retire_tail_cap_{g}")
                saved_tail = saved_tail + (both * xr.DataArray(keep * (w * part), coords=[R])).sum()
                gone = gone + v * (one * part)
        # conversions: this year's serve the tail too; the tail's own column exists only while E + 2 <= UEPA_GSYR
        can_later = decide and year + 1 >= first_convert and (not rule["switch"] or year + 1 <= rule["gas_switch_last"])
        ct_k = m.add_variables(lower=0, upper=xr.DataArray(conv_step_gw * can_later, coords=[R, CS]), name="convert_tail")
        m.add_constraints(ct_k + convert_k <= xr.DataArray(conv_step_gw, coords=[R, CS]), name="convert_tail_cap")
        ct = ct_k.sum("cstep")
        keep_conv = CONVERT_FOM_ADJ * f_conv * conv_step_keep * 1.0e3 * w
        conv_tail_cost = conv_step_capital * _crf(rate, HORIZON_YEARS) * 1.0e3 * w + keep_conv
        scale = xr.DataArray(np.array([{"gas_conv": f_conv, "coal": f_coal}.get(g, 1.0) for g in TG]), coords=[T])
        added = xr.DataArray(np.stack([np.maximum(c0f[g] - cap0[g], 0.0) for g in TG], axis=1), coords=[R, T])
        path = xr.DataArray(np.stack([c0f[g] for g in TG], axis=1), coords=[R, T])
        to_conv = xr.DataArray(np.array([1.0 if g == "gas_conv" else 0.0 for g in TG]), coords=[T])
        capv_f = m.add_variables(lower=0, coords=[R, T], name="capacity_tail")
        from_coal = xr.DataArray(np.array([f_coal if g == "coal" else 0.0 for g in TG]), coords=[T])
        m.add_constraints(capv_f - capv * scale - fb - ct * (to_conv * f_conv) + ct * from_coal + gone <= added * scale,
                          name="capacity_def_tail")
        m.add_constraints(capv_f - build * scale - fb - retrofit * to_ccs.clip(min=0) - (convert + ct) * (to_conv * f_conv)
                          <= path * scale, name="capacity_path_tail")
        cf_tail = dict(max_cf)
        if rule["switch"]:
            cf_tail["gas_cc_new"] = np.minimum(cf_tail["gas_cc_new"], rule["new_cc_cf"])
        mcf_f = xr.DataArray(np.stack([cf_tail[g] for g in TG], axis=1), coords=[R, T])
        pf = operate("_tail", cs, c0f, capv_f, *totals(c0f, bw + fw, bs + fs, bb + fbb), bh=FUTURE_BLOCK_HOURS, new_w=bw + fw,
                     new_s=bs + fs, lp=monthly_days(cs), short_cost=RESERVE_SHORTFALL_COST / w, mcf=mcf_f,
                     int_cap=np.full(NUM_R, INT_BND) if intermittent_cap is not None else None)
        second = {g: columns[g]["second"] * 1.0e3 for g in BUILDS}
        out = w * pf["operating"] - saved_tail + (ct_k * xr.DataArray(conv_tail_cost, coords=[R, CS])).sum()
        out = out + (convert_k * xr.DataArray(keep_conv, coords=[R, CS])).sum()
        out = out + w * (retrofit * xr.DataArray(retro_annual + (1.0 - f_coal) * fom_exist["coal"], coords=[R])).sum()
        out = out + (fb * xr.DataArray(np.stack([second.get(g, np.zeros(NUM_R)) for g in TG], axis=1), coords=[R, T])).sum()
        for v, g in ((fw, "wind"), (fs, "solar"), (fbb, "battery")):
            out = out + (v * xr.DataArray(second[g], coords=[R])).sum()
        return out

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
            times = RENEW_BOUND_TAIL if offset == TAIL_OFFSET else 1.0
            # wind's second and last explicit year reads BYR = RYR + 1 (oracle 2030: BASN 5 x 6.72, WCAWIEL of 2030)
            fw = m.add_variables(lower=0, upper=renewable_upper("wind", 100.0 * span * okb["wind"], year + 1, times),
                                 name=f"build_wind_p{offset}")
            fs = m.add_variables(lower=0, upper=renewable_upper("solar", 100.0 * span * okb["solar"], year + 1, times),
                                 name=f"build_solar_p{offset}")
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

    one_year = capital
    if tail_on:
        # this year's columns at their whole present value (the capture charge only for the year itself)
        capital = {g: columns[g]["first"] * 1.0e3 for g in BUILDS}
        for g in BUILDS:
            if g in dispatch.CAPTURE_GROUPS:
                paid = case.credit_share[g] if case.credit_share is not None else 1.0
                earned = 1.0 if year <= dispatch.credit_rule(snapshot)[1] else 0.0
                tons = case.heat_rate[g] / 1000.0 * dispatch.CO2_PER_TBTU[dispatch.CAPTURE_GROUPS[g]] * dispatch.capture_rate(g)
                capital[g] = capital[g] + (paid - earned) * case.credit_45q * tons * CCS_CAPACITY_FACTOR * 8.76 * 1.0e3
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
    rate_now = discount_rate(snapshot, year)
    tail = 0
    if tail_on:
        w_tail = columns["gas_ct_new"]["annuity"] - 1.0
        tail = add_tail(w_tail, rate_now)
    if RETIRE_TAIL_PROXY and decide and not horizon and not tail_on:
        # Proxy for ECP's option-3 columns (RETIRE_TAIL_PROXY): retiring now also gives up the plant's firm capacity
        # later, priced at a new turbine's annual cost less the plant's own fixed cost in each later year.
        firm = one_year["gas_ct_new"][:, None]
        for g in RETIRE_TAIL_PROXY_GROUPS:
            last = rule["cofire_last"] if (g == "gas_conv" and rule["switch"]) else (RULE_YEAR - 1 if g == "coal" else None)
            if use_groups and g in RETIRABLE:
                j = RETIRABLE.index(g)
                tv = retirement_tail_proxy(year, firm, gcost[:, j, :], rate_now, last)
                tail = tail + (rg.sel(group=g) * xr.DataArray(tv, coords=[R, K])).sum()
            else:
                keep = fom_exist[g] if g in fom_exist else fom_made[g]
                tv = retirement_tail_proxy(year, firm[:, 0], keep, rate_now, last)
                tail = tail + (retire.sel(group=g) * xr.DataArray(tv, coords=[R])).sum()
    if tail_on:      # the tail's own rows value the conversion: whole-horizon capital, this year's fixed O&M saved
        conv_cost = conv_step_capital * _crf(rate_now, HORIZON_YEARS) * 1.0e3 * (1.0 + w_tail) - (1.0 - CONVERT_FOM_ADJ) * conv_step_keep * 1.0e3
    elif CONVERT_BY_UNIT:
        keep_k = conv_step_keep * 1.0e3                           # k$ per GW-year, hurdle already in
        conv_cost = conv_step_capital * _crf(rate_now, HORIZON_YEARS) * 1.0e3 - (1.0 - CONVERT_FOM_ADJ) * keep_k
        if conversion_is_last_chance(year, rule):
            conv_cost = conv_cost - cofired_conversion_credit(year, capital["gas_ct_new"][:, None],
                                                              CONVERT_FOM_ADJ * keep_k, rate_now, rule)
    else:
        conv_cost = conv_capital * _crf(rate_now, HORIZON_YEARS) * 1.0e3 - (1.0 - CONVERT_FOM_ADJ) * fom_exist["coal"]
        if conversion_is_last_chance(year, rule):
            conv_cost = conv_cost - cofired_conversion_credit(year, capital["gas_ct_new"], fom_made["gas_conv"], rate_now,
                                                              rule)
        conv_cost = conv_cost[:, None]
    retro = retro + (convert_k * xr.DataArray(conv_cost, coords=[R, CS])).sum()
    m.add_objective(operating + weight_now * (capex - saved + retro) + future_capex + (weight_now - coal_weight) * saved_coal
                    + tail)
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
    if "build_step_cc" in m.variables:
        out.conventional_cc = float(m.variables["build_step_cc"].solution.sum())
    pv = end_use_pv(snapshot, min(year, LAST_MODEL_YEAR))
    out.intermittent_share = (np.asarray(p1["potential"].solution.values) / 1000.0 + pv) / (case.net_load_twh + pv)
    hours = (case.weights * BLOCK_HOURS)[None, :, None]
    out.price = np.asarray(m.constraints["balance"].dual.transpose("region", "day", "block").values) / hours
    out.reserve_price = np.asarray(m.constraints["reserve_margin"].dual.values) / 1000.0     # k$/GW -> $/kW
    if tail_on and "reserve_margin_tail" in m.constraints:
        ct_col = columns["gas_ct_new"]
        out.reserve_payment = capacity_payment(out.reserve_price, np.asarray(m.constraints["reserve_margin_tail"].dual.values) / 1000.0,
                                               ct_col["annuity"], ct_col["first"] / ct_col["annuity"])
    if "state_rps" in m.constraints:
        trs = [tr for tr in rps.tranches() if rps.requirement_share(tr, min(year, LAST_MODEL_YEAR)).sum() > 0]
        out.rps_price = {(tr.state, tr.id): float(v) / 1000.0 for tr, v in zip(trs, m.constraints["state_rps"].dual.values)}
    if p1["spin"] and "slices" in p1["spin"]:
        dual = np.zeros((NUM_R, 9))
        for k in range(9):
            if f"spin_reserve_{k}" in m.constraints:
                dual[:, k] = np.asarray(m.constraints[f"spin_reserve_{k}"].dual.values)
        out.spin_slice_price = dual / 1000.0
        out.spin_requirement = p1["spin"]["requirement"]
        out.spin_shortfall_gw = float(sol(p1["spin"]["shortfall"]).max())
    elif p1["spin"]:
        out.spin_price = np.asarray(m.constraints["spin_reserve"].dual.transpose("region", "day", "block").values) / 1000.0
        out.spin_requirement = p1["spin"]["requirement"]
        out.spin_shortfall_gw = float(sol(p1["spin"]["shortfall"]).max())
    if use_groups:
        g_ret = sol(rg)
        out.group_retire = {g: g_ret[:, j, :] for j, g in enumerate(RETIRABLE)}
        share = np.divide(g_ret, gcap, out=np.zeros_like(gcap), where=gcap > 1e-9)
        out.group_share = {g: np.clip(share[:, j, :], 0.0, 1.0) for j, g in enumerate(RETIRABLE)}
        out.rule_retire = sol(forced)
    return out


# Capacity-LP groups folded into the dispatch model's groups. Converted coal cofires: it is the dispatch's cofire group
# (dispatch.COFIRE_GROUP), or steam, where the restart keeps EIA's conversions (prefix ng), with the switch off.
TO_DISPATCH = {"gas_cc_new": "gas_cc", "gas_ct_new": "gas_ct", "gas_conv": "cofire"}


def dispatch_capacity(capacity: dict) -> dict:
    """A year's capacity (STATE_GROUPS) in the dispatch model's groups (dispatch.GROUPS), GW by region."""
    to = dict(TO_DISPATCH, gas_conv="cofire" if dispatch.COFIRE_GROUP else "steam")
    out = {g: np.zeros(NUM_R) for g in dispatch.GROUPS}
    for g, v in capacity.items():
        out[to.get(g, g)] = out[to.get(g, g)] + v
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
        if dispatch.FLEET_VINTAGE_CF and case.profile["wind"].shape[-1] == 24:
            # the plants standing when the year is planned, at their own vintages
            case = replace(case, profile=dispatch.fleet_profiles(snap, year, self.cap, self.renewable_builds()))
        grp = None
        if self.groups:
            if self.price is None:
                self.price = solve_year(snap, year, self.cap, self.solver, decide=False, case=case).price
            hours = np.broadcast_to((case.weights * BLOCK_HOURS)[:, None], self.price.shape[1:]).ravel()
            flat = self.price.reshape(NUM_R, -1)
            grp = {g: retire_groups.build(year, g, self.alive, unit_costs(case, g), flat, hours, 1.0 - case.avail[g][0])
                   for g in RETIRABLE}
        res = solve_year(snap, year, self.cap, self.solver, groups=grp, case=case, recent_adds=self.recent_adds(year),
                         resource=self.resources(year) or None,
                         intermittent_cap=self.intermittent_cap(year) if INTERMITTENT_CAP else None)
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

    def renewable_builds(self) -> dict:
        """{wind, solar: {online year: (25,) GW}}: the reference run's builds before this path, then its own."""
        out = {}
        first = min(self.results, default=self.next_year)
        for g in dispatch.WRENEW_PROFILES:
            out[g] = dispatch.reference_builds(self.snapshot, g, first - 1)
            out[g].update({t: r.builds[g] for t, r in self.results.items()})
        return out

    def resources(self, year: int) -> dict:
        """{wind, solar: for_build_year of that resource} for the types that follow this path's builds."""
        out = {}
        if OWN_WIND_RESOURCE:
            out["wind"] = self.wind_resource(year)
        if OWN_SOLAR_RESOURCE:
            from nems_open.emm import solar_resource
            first = min(self.results, default=year)
            out["solar"] = solar_resource.for_build_year(self.snapshot, year, first,
                                                         {t: r.capacity["solar"] for t, r in self.results.items()},
                                                         {t: r.builds["solar"] for t, r in self.results.items()})
        return out

    def intermittent_cap(self, year: int) -> np.ndarray:
        """EP$LINT's cap for `year`: the largest share of the years since 2024, the reference run's before this path."""
        first = min(self.results, default=self.next_year)
        shares = [reference_intermittent_share(self.snapshot, t) for t in range(START_YEAR - 1, first)]
        return intermittent_limit(shares + [r.intermittent_share for r in self.results.values()])

    def wind_resource(self, year: int) -> dict:
        """renew.f's wind resource for `year` with this path's builds: onshore capacity is the wind group less the
        offshore plant-file units and floors."""
        from nems_open.emm import wind_resource
        first = min(self.results, default=year)
        gw = {t: r.capacity["wind"] - offshore_gw(t) for t, r in self.results.items()}
        return wind_resource.for_build_year(self.snapshot, year, first, gw, {t: r.builds["wind"] for t, r in self.results.items()})

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
                    vals.append(sum(float(r.planned_adds.get(s, np.zeros(NUM_R)).sum()) for s in state) - offshore_adds(g, yr)
                                + float(r.builds.get(g, np.zeros(NUM_R)).sum()))
                else:
                    vals.append(max(capacity_report.eia_additions(self.snapshot, yr, prefixes)
                                    - capacity_report.eia_additions(self.snapshot, yr - 1, prefixes), 0.0))
            out[g] = vals
            if STEP_SEPARATE_HISTORY and g in STEP_OWN_TYPES:
                own = []
                for yr in range(year - n, year):
                    r = self.results.get(yr)
                    built = float(r.builds.get(g, np.zeros(NUM_R)).sum()) if r is not None else 0.0
                    if r is not None and g == "gas_cc_new":
                        built -= getattr(r, "conventional_cc", 0.0)
                    own.append(built + plant_file_adds(yr, STEP_OWN_TYPES[g]))
                out[g] = own
                cc = (lambda yr: getattr(self.results.get(yr), "conventional_cc", 0.0)) if g == "gas_cc_new" else (lambda yr: 0.0)
                out[f"{g}/floor"] = [plant_file_adds(yr, STEP_CONVENTIONAL_TYPES[g]) + cc(yr) for yr in range(year - n, year)]
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
