"""Electricity dispatch: which plants run in each hour, shaped like EFD.

For one year, every EMM region meets its load in 36 typical days of 24 hours at least cost.
Capacity by plant group, fuel prices and net load are inputs. Thermal plants (coal, gas
combined cycle, gas combustion turbines, steam) are dispatched against their fuel and variable
O&M cost, hydro is dispatched inside a monthly energy budget, batteries and pumped storage
shift energy inside each day, and nuclear, wind, solar and other renewables run at their
capacity factor unless spilled. Regions do not trade with each other yet.

Money is 1987 dollars, the unit NEMS keeps its prices in. Power is GW, energy TWh, fuel
trillion Btu, CO2 million metric tons.
"""

from dataclasses import dataclass, field

import linopy
import numpy as np
import pandas as pd
import xarray as xr

from nems_open.emm import db, demand, history, load, plants, regions, technology
from nems_open.xlsx_ranges import named_ranges

NUM_R = regions.NUM_EMM
THERMAL = ("coal", "coal_ccs", "gas_cc", "gas_ccs", "gas_ct", "steam", "cofire")
RENEWABLE = ("wind", "solar", "other")
GROUPS = THERMAL + ("nuclear", "hydro") + RENEWABLE + ("battery", "pumped")

# Restart capacity arrays (UDATOUT/UCAP<prefix><u|n>) that make up each group.
# util.f (the UCAP tally) adds each unit to its main group's array and, for some types, to a subgroup array as
# well: UCAPCC holds every combined cycle (ACC -> ac, ACS -> as, AC2 -> a2) and UCAPCT every turbine (ACT -> at,
# CTA -> t2). Summing a main group with its subgroups counts those units twice (by 2049: 161 GW of ac, 52 of as and
# 133 of at). Each group reads the main arrays only; a prefix written "-xx" is subtracted, which takes CCS out of
# combined cycle. Coal is different in this restart: upstream util.f nests CAV/COQ/CAS (ig/pq/is) inside UCAPCS,
# but the cb2026 restart keeps ig outside cs (2024: cs 162.8 GW = plant-file coal 163.5 less the 0.71 GW CAV unit),
# so coal still sums them.
CAPACITY_SUBGROUPS = {"cc": ("ac", "as", "a2"), "ct": ("at", "t2")}
CAPACITY_PREFIXES = {
    "coal": ("cs", "ig", "pq", "is", "oc"),   # less coal_ccs: sq (retrofits) is a subset of cs, not extra capacity
    "coal_ccs": ("sq",),
    "gas_cc": ("cc", "-as", "fc"),
    "gas_ccs": ("as",),
    "gas_ct": ("ct", "ic", "i2"),
    "steam": ("os", "ng"),
    "nuclear": ("nu", "sm"),
    "hydro": ("hy",),
    "wind": ("wn", "wf", "wl"),
    "solar": ("pv", "pt", "st", "so", "ss", "s2"),
    "other": ("ge", "wd", "ms", "bi", "gn", "ag", "ti", "hi", "ho"),
    "battery": ("ds", "dp", "db"),
    "pumped": ("ps", "p2"),
}

# Plant-file EFD types behind each group, for heat rates, capacity factors and fuel shares of existing plants.
EXISTING_TYPES = {
    "coal": ("COU", "CSU", "CSC", "CNC", "CN2", "CAV", "CNG", "COQ", "CAS"),
    "coal_ccs": ("COU", "CSU", "CSC", "CNC", "CN2", "CAV", "CNG", "COQ", "CAS"),
    "gas_cc": ("CCO", "CCG", "CCX", "ACC", "AC2", "FCG"),
    "gas_ccs": ("ACS",),
    "gas_ct": ("CTO", "CTG", "CTX", "CTA", "ACT", "ICE"),
    "steam": ("STO", "STG", "STX", "CTN"),
    "cofire": ("CTN",),
    "nuclear": ("CNU", "ANC", "SMR"),
    "hydro": ("HYC", "HYA", "HYI", "HYT"),
    "wind": ("WND", "WNL", "WFS"),
    "solar": ("SPV", "PVT", "STH", "STS", "ST2"),
    "other": ("GTH", "AGT", "BMS", "BIG", "MSW"),
}
OIL_TYPES = {"steam": ("STO",), "gas_ct": ("CTO",)}
# New-plant heat rate (Btu/kWh) and variable O&M come from these ECP types.
NEW_TYPE = {"coal": "PC", "coal_ccs": "PC", "gas_cc": "AC", "gas_ccs": "CS", "gas_ct": "AT", "steam": "ST", "cofire": "ST"}
# Forced outage and maximum capacity factor come from these EFD plant types in pltdata.txt.
AVAIL_TYPE = {"coal": "CSC", "coal_ccs": "CSC", "gas_cc": "CCG", "gas_ccs": "CCG", "gas_ct": "CTG", "steam": "STG", "cofire": "CTN"}

# Carbon capture: groups that capture CO2 (and the fuel they burn), the share captured, and the 45Q credit.
CAPTURE_GROUPS = {"coal_ccs": "coal", "gas_ccs": "gas"}
CAPTURE_RATE = 0.9

# Storage: (duration in hours, round-trip efficiency)
STORAGE = {"battery": (4.0, 0.85), "pumped": (12.0, 0.78)}

# Emission factors, million metric tons CO2 per trillion Btu.
CO2_PER_TBTU = {"coal": 0.0953, "gas": 0.05307, "distillate": 0.07316, "residual": 0.0751}

CCS_HEAT_RATE_MAX = 20000.0  # Btu/kWh; with-capture heat rates above this in the plant file are data outliers
BASE_YEAR = 2024             # last year of operating history in the plant file
BENCHMARK_LAST = 2026        # EIA holds the early years to the Short-Term Energy Outlook
BENCHMARK_FADE = 3           # years over which the stand-in for that benchmark fades out after BENCHMARK_LAST
UNSERVED_COST = 1000.0       # 1987$/MWh
HOURS_PER_YEAR = 8760.0

# EFD's spinning reserve rows (uefd.f ED$LOAD, 11205-11250: row SR<region><season><slice>, column SP bounded below by
# SP_RES_RQMT_IN). In every region and EFD slice (3 seasons, each cut at 1% / 49% / 50% of its hours by net load),
# reserve >= SR_RQMT_HGHT x the slice's height + SR_RQMT_DIFF x (the season's peak slice - that height), plus SR_INT
# of wind and solar output (SR_INT_REQ). The constants and the slicing are ECP's (capacity.ecp_slice_heights); the
# 2030 PassBack's SP_RES_REQ matches the formula. A thermal unit carries reserve only while it runs: in EFD's modes
# (OPBSLD,3/7/10) a committed unit's reserve is committed capacity less output and its output is at least SR_MIN_CF of
# what is committed, so reserve <= capacity in service - output and reserve <= output x (1 / SR_MIN_CF - 1). Pumped
# storage the same on discharge. Batteries do not optimise their reserve in EFD: ReStore hands it a fixed reserve per
# GW by slice (NET_STORAGE_SR_EFD), here the 2030 composite's capacity-weighted national value (EFD_BATTERY_SR, ECP
# slice order: shoulder, summer, winter, each peak / middle / base). Other renewables carry their capacity less
# output, nuclear a fixed share of its capacity (EFD_NUCLEAR_SR: the 2030 PassBack's 3.6-4.0 GW of CN reserve on
# 98.6 GW). Conventional hydro carries none (no HY in SP_ACHBYECP). No reserve over the links.
EFD_SPIN_RESERVE = True
# EFD's availability and planned maintenance. udat.f 10168-10236 (MXLFR 0) scales pltdata's forced outage and planned
# maintenance rates by one factor so that (1 - FOR) x (1 - PMR) is the maximum capacity factor (efd_outage_rates; the
# 2030 composite's UG_FOR and UG_PMR follow the rule to three decimals, coal 0.19 and 0.20). ED$PM (uefd.f 8959-9120)
# schedules the maintenance by season: a column per group and season in [0, capacity], their hours at least PMR x
# capacity x the year's hours, sharing the season's capacity row with the dispatch modes. Here the schedule is a rule
# (maintenance_season_share) and output in every hour is at most (1 - FOR) x (capacity - maintenance). EFD's reserve
# counts the forced-outage share of a committed unit (OPBSLD,3: 1 - DRAT, DRAT at most 1 - FOR), so with
# EFD_SPIN_RESERVE reserve + output <= capacity - maintenance. Off: every hour may reach (1 - FOR) x capacity, with
# pltdata's FOR, and only the year's energy is capped at the maximum capacity factor.
EFD_DERATE = True
# EFD dispatches oil turbines and oil steam (CTO, STO) as their own groups at oil prices, 3 to 7 times gas, so they
# run last: in the 2030 EFD, CTO makes 0.001 TWh on 14.7 GW and STO 1.5 TWh on 3.3 GW, close to the must-run units'
# output. With one turbine and one steam group, solve takes the group's output as gas (oil share 0) instead of
# burning the oil units' capacity share of it. DispatchCase.oil_share is unchanged, so the capacity LP is not
# affected. Off: 8% of every turbine MWh is distillate, which makes a turbine up to half again as costly to run.
OIL_UNITS_LAST = True
# Coal-gas cofiring (restart prefix ng: ECP type NG, EFD type CTN, "Coal to Gas Retrofit"). EIA's steam is mostly these
# units from 2028 (2035: ng 106 TWh on 48 GW, os 11.5 on 51), and they burn coal: the plant file's CTN units list gas
# first and a coal supply curve (B1..CX) second at 52% of Btu, ECP converts coal units with W_FSHR(2) = UEPA_CGSH (0.6
# coal, uecp.f 28148), udat.f 6457 caps every NG unit's coal at UEPA_CGSH from UEPA_GSYR, and the oracle's 2030 EFD
# passes back CTN coal shares of 0.17 to 0.60 by fuel region (FCLSH_ams). In the restart the coal share of ng
# generation is 52% in 2031 and 56-57% in 2032-2038 (UGNCLNR less UGENPC). On: ng is its own group (`cofire`), at the
# CTN units' heat rate, variable O&M and coal share, and coal units converted after the plant file at the coal fleet's
# heat rate +5% and variable O&M x0.75 (emmcntl %CL_to_NG%, capacity.CONVERT_*) with UEPA_CGSH of coal; no coal after
# UEPA_CLCFYR. Off: ng runs in the steam group on gas.
COFIRE_GROUP = True
# CCS retrofits lose capacity to the capture plant. udat.f 9265 sets a coal unit's capacity loss to 1 - WHRATE / CCSHR,
# uecp.f 27662 takes it off the retrofitted unit (CCSCAPA), and EFD dispatches what is left. The UCAP tally reports the
# unit at WC_SUM / (1 - CCSADJ) (udat.f 8421-8467: ECSCAPSQ, ECSCAP), the capacity before the loss, so restart sq (and
# cs) hold retrofits at their old nameplate. That is why EIA's CCS coal runs at 0.44 of sq in every year from 2033:
# EFD's 0.65 of a net capacity about 0.7 of sq. On: coal_ccs generates on capacity x DispatchCase.capture_net (the
# plant file's THRATE / T_CCSHR, capacity-weighted by region over the units with a capture heat rate). Off: on sq.
CCS_CAPACITY_PENALTY = True
# EFD's maximum-load mode. A coal unit's dispatch columns (uefd.f OPBSLD) are three modes per season: normal,
# minimum load (J) and maximum load (U). The highest of them, U, follows the season's load: in slice k its output per
# committed GW is DRAT_MAX = (1 - FOR) x (SR_MAX_LF + (1 - SR_MAX_LF) x height_k / the season's peak slice height),
# SR_MAX_LF 0.55 for every existing coal configuration (ecpdaty SPNRSV, B1..HC), except up to UYR_STEO + 1 (2027),
# when DRAT_MAX is the plain derate. That shape is coal's ceiling in EFD: on the oracle's 2030 EFD files the 52 GW of
# coal groups running at their ceiling make (1 - FOR)(1 - PMR) x the U shape to three decimals in every region (MISC
# 0.580 against 0.583, PJMW 0.578 / 0.581, SRCE 0.570 / 0.572, TRE 0.579 / 0.578): 0.57-0.60 of nameplate where a
# flat (1 - FOR)(1 - PMR) gives 0.65. On: coal's hourly upper bound takes the U shape on the EFD slices of
# spin_requirement (its maximum within a season is the flat bound, its average about 0.9 of it).
EFD_MAX_LOAD_SHAPE = True
MAX_LOAD_GROUPS = {"coal": "B1"}   # LP group -> ECP type whose SR_MAX_LF it takes (all existing coal configurations: 0.55)
MAX_LOAD_FIRST_YEAR = BENCHMARK_LAST + 2   # uefd.f OPBSLD: DRAT_MAX = DRAT_ORG for coal while CURIYR <= UYR_STEO + 1
COFIRE_PREFIXES = ("ng",)
COAL_FUELS = ("B", "C", "H")   # plant-file fuel codes of the coal supply curves (B1..B8, C1..CX, H1..HC)
EFD_BATTERY_SR = (0.252, 0.206, 0.460, 0.200, 0.232, 0.447, 0.222, 0.289, 0.438)
EFD_NUCLEAR_SR = 0.04
SPIN_SHORTFALL_COST = 100.0   # 1987$/MWh of missing reserve, below UNSERVED_COST so no load is shed to make reserve


@dataclass
class DispatchCase:
    year: int
    capacity: dict            # group -> (25,) GW
    heat_rate: dict           # thermal groups and nuclear -> (25,) Btu/kWh
    vom: dict                 # thermal group -> (25,) 1987$/MWh
    price: dict               # fuel -> (25,) 1987$/MMBtu
    oil_share: dict           # thermal group -> (25,) share of that group's fuel that is oil
    avail: dict               # thermal group -> (forced outage rate, max capacity factor)
    max_cf: dict              # thermal group -> (25,) maximum capacity factor (pltdata.txt MCF)
    credit_45q: float         # 1987$ per metric ton of CO2 captured (credit_share says which capacity earns it)
    monthly_cf: dict          # nuclear, hydro, other -> (25, 12)
    profile: dict             # wind, solar -> (25, 36, 24) capacity factor in each typical hour
    net_load_twh: np.ndarray  # (25,)
    shapes: np.ndarray        # (25, 36, 24) share of annual energy per typical hour
    weights: np.ndarray       # (36,) days per typical day
    links: dict = None        # exporter, importer (0-based), capacity_gw (L, 36), cost (L,) 1987$/MWh, loss
    carbon_price: float = 0.0  # 1987$ per metric ton CO2, added to each plant's cost by its emissions
    must_run_oil_gw: np.ndarray = None   # (25,) average output of must-run oil steam units, GW (taken out of `steam`)
    must_run_oil_hr: np.ndarray = None   # (25,) their heat rate, Btu/kWh
    ignition_share: float = 0.0          # share of coal Btu that is distillate (plant file fuel 2, T_FSHR_2)
    flat_twh: np.ndarray = None          # (25,) part of net_load_twh that runs flat across the year (data centers)
    flex_share: float = 0.0              # share of flat_twh that can be curtailed over the year
    credit_share: dict = None            # capture group -> (25,) share of capacity still earning 45Q (None: all)
    # wind and solar -> (25, 36, hours) capacity factor of a plant built now: WRENEW's new-build profile of the main
    # type (wn, pv) less its outage rate, as ECP values new intermittent capacity (uecp.f EP$INT: UPICFC). None: profile.
    build_profile: dict = None
    coal_share: dict = None             # thermal group -> (25,) share of its Btu that is coal (cofire; None: none)
    capture_net: np.ndarray = None      # (25,) coal_ccs capacity that generates per GW of reported capacity (None: 1)


@dataclass
class DispatchResult:
    year: int
    case: DispatchCase
    status: str
    generation_twh: dict = field(default_factory=dict)      # group -> (25,)
    fuel_tbtu: dict = field(default_factory=dict)           # coal, gas, distillate, residual, uranium -> (25,)
    co2_mt: np.ndarray = None                               # (25,)
    unserved_twh: np.ndarray = None                         # (25,)
    curtailed_twh: np.ndarray = None                        # (25,) flexible load the LP chose to cut
    spilled_twh: np.ndarray = None                          # (25,)
    price: np.ndarray = None                                # (25, 36, 24) 1987$/MWh
    spin_price: np.ndarray = None                           # (25, 36, 24) 1987$/MWh of reserve (EFD_SPIN_RESERVE)
    spin_gw: dict = None             # reserve carried (EFD_SPIN_RESERVE): thermal group, battery, pumped, idle, required -> (25, 36, 24) GW
    objective: float = 0.0
    trade_twh: np.ndarray = None                            # (links,) energy sent on each link

    def total_generation_twh(self) -> float:
        return float(sum(v.sum() for v in self.generation_twh.values()))

    def average_price(self) -> np.ndarray:
        """Load-weighted marginal cost by region, 1987$/MWh."""
        w = self.case.weights[None, :, None] * self.case.shapes
        return (self.price * w).sum(axis=(1, 2)) / w.sum(axis=(1, 2))


def existing_types(group: str) -> tuple:
    """Plant-file EFD types of a group's existing units: EXISTING_TYPES, with the cofired units (CTN) out of steam
    when they are their own group (COFIRE_GROUP)."""
    if group == "steam" and COFIRE_GROUP:
        return tuple(t for t in EXISTING_TYPES["steam"] if t not in EXISTING_TYPES["cofire"])
    return EXISTING_TYPES[group]


def _ucap_mid(snapshot, prefixes, y) -> np.ndarray:
    """Capacity in service on average through the year: the mean of last year's and this year's year-end
    capacity, which assumes builds and retirements are spread evenly through the year."""
    return 0.5 * (_ucap(snapshot, prefixes, y) + _ucap(snapshot, prefixes, y - 1))


def _in_service(snapshot, prefixes, types, year) -> np.ndarray:
    """Capacity in service on average through the year, using the plant file's in-service and retirement months.

    Start from last year's year-end capacity. Add each planned unit for the part of the year after its
    in-service month and take off each retiring unit for the part after its retirement month. What the
    restart shows beyond that has no date in the plant file. A net loss is EMM's own retirements: ECP dates
    an economic retirement in year Y to December of Y - 1 (uecp.f 27095-27098, W_RYR = YEAR - 1, W_RMO = 12),
    so the unit is in UCAP(Y - 1), which counts units retiring in December (udat.f 8261-8300), but gone for
    all of Y; it leaves the whole year. A net gain (EMM's own builds) is assumed to arrive mid-year, which
    keeps wind and solar on EIA's generation.
    """
    y = year - history.FIRST_YEAR
    start, end = _ucap(snapshot, prefixes, y - 1), _ucap(snapshot, prefixes, y)
    if types is None:
        return 0.5 * (start + end)
    u = plants.load_units()
    tb = db.table("V_EMM_PLTF860")
    in_group = np.isin(u.efd_type, list(types))
    adds = in_group & (u.online_year == year)
    rets = in_group & (u.retire_year == year)
    add_gw, ret_gw, add_avg, ret_avg = (np.zeros(NUM_R) for _ in range(4))
    np.add.at(add_gw, u.region[adds] - 1, u.summer_mw[adds] / 1000.0)
    np.add.at(add_avg, u.region[adds] - 1, u.summer_mw[adds] / 1000.0 * (13 - np.clip(tb["T_SMO"][adds], 1, 12)) / 12.0)
    np.add.at(ret_gw, u.region[rets] - 1, u.summer_mw[rets] / 1000.0)
    np.add.at(ret_avg, u.region[rets] - 1, u.summer_mw[rets] / 1000.0 * (13 - np.clip(tb["T_RMO"][rets], 1, 12)) / 12.0)
    undated = (end - start) - add_gw + ret_gw
    undated = np.where(undated < 0.0, undated, 0.5 * undated)
    return np.maximum(start + add_avg - ret_avg + undated, 0.0)


def _ucap(snapshot, prefixes, y) -> np.ndarray:
    """Year-end restart capacity (UDATOUT/UCAP<prefix><u|n>) summed over `prefixes`, GW by region. A prefix
    written "-xx" is subtracted (a subgroup already inside a main group, see CAPACITY_SUBGROUPS)."""
    total = np.zeros(NUM_R)
    for p in prefixes:
        sign = -1.0 if p.startswith("-") else 1.0
        for o in ("u", "n"):
            try:
                total += sign * np.nan_to_num(snapshot[f"UDATOUT/ucap{p.lstrip('-')}{o}"][:NUM_R, y].astype(float))
            except KeyError:
                pass
    return np.maximum(total, 0.0) if any(p.startswith("-") for p in prefixes) else total


def _weighted(values, weights, types, region_arr, year, fallback):
    """Capacity-weighted mean of a plant-file column by region for the given EFD types, national mean where a region has none."""
    u = plants.load_units()
    on = plants.online(year) & np.isin(u.efd_type, list(types))
    out = np.full(NUM_R, np.nan)
    for r in range(1, NUM_R + 1):
        m = on & (region_arr == r)
        if weights[m].sum() > 0:
            out[r - 1] = np.average(values[m], weights=weights[m])
    nat = np.average(values[on], weights=weights[on]) if weights[on].sum() > 0 else fallback
    return np.where(np.isnan(out), nat, out)


def _weighted_mask(values, weights, mask, region_arr, fallback):
    out = np.full(NUM_R, np.nan)
    for r in range(1, NUM_R + 1):
        m = mask & (region_arr == r)
        if weights[m].sum() > 0:
            out[r - 1] = np.average(values[m], weights=weights[m])
    nat = np.average(values[mask], weights=weights[mask]) if weights[mask].sum() > 0 else fallback
    return np.where(np.isnan(out), nat, out)


def _monthly_cf(types, year) -> np.ndarray:
    t = db.table("V_EMM_PLTF860")
    u = plants.load_units()
    out = np.zeros((NUM_R, 12))
    for i, mo in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]):
        out[:, i] = _weighted(t[f"M_CF_{mo}"], u.summer_mw, types, u.region, year, 0.3)
    return out


# Wind and solar hourly capacity factors EIA's renewable module hands to EMM (WRENEW block), cut by the
# plant type's outage rate (UEFDOUT/UP_XFOR): (capacity prefix, WRENEW array, EFD plant type).
WRENEW_PROFILES = {
    "wind": (("wn", "wsfwiel_cf", "WND"), ("wf", "wsfwfel_cf", "WFS"), ("wl", "wsfwlel_cf", "WNL")),
    "solar": (("pv", "wsspvel_cf", "SPV"), ("pt", "wssptel_cf", "PVT"), ("st", "wssstel_cf", "STH")),
}


def _wrenew_profile(snapshot, key, y) -> np.ndarray:
    """Capacity factor by region, typical day (month * 3 + day type) and hour, shape (25, 36, 24)."""
    a = snapshot[f"WRENEW/{key}"][:NUM_R, y].astype(float)               # (25, day type 3, month 12, hour 24)
    return a.transpose(0, 2, 1, 3).reshape(NUM_R, 36, 24)


def build_links(snapshot, year: int) -> dict:
    """Transmission between EMM regions from the ETT pre-processor table (V_EMM_PRETTIN).

    Each row is a link between an exporting and an importing region with a summer and a winter
    capacity in MW and a markup in 1987 dollars per MWh (PT1 + PT2). DIRSW 2 means the link works
    both ways. Rows for the same pair add up. New transmission that EMM built (UETTOUT/UTNEWTRN, GW)
    is added to the pair's capacity. Summer is June to September.
    """
    t = db.table("V_EMM_PRETTIN")
    live = (t["IRGEX"] <= NUM_R) & (t["IRGIM"] <= NUM_R) & (t["STRTYR"] <= year) & (t["ENDYEAR"] >= year)
    summer = np.isin(np.repeat(np.arange(12), 3), (5, 6, 7, 8))
    pairs = {}
    for ex, im, dirsw, c1, c2, p1, p2 in zip(t["IRGEX"][live], t["IRGIM"][live], t["DIRSW"][live],
                                              t["TEMPC1"][live], t["TEMPC2"][live], t["PT1"][live], t["PT2"][live]):
        for a, b in ((ex, im), (im, ex)) if dirsw == 2 else ((ex, im),):
            entry = pairs.setdefault((int(a) - 1, int(b) - 1), [np.zeros(36), 0.0])
            entry[0] = entry[0] + np.where(summer, c1, c2) / 1000.0
            entry[1] = p1 + p2
    new = snapshot["UETTOUT/utnewtrn"][:NUM_R, :NUM_R, year - history.FIRST_YEAR].astype(float)
    for a in range(NUM_R):
        for b in range(NUM_R):
            add = max(new[a, b], new[b, a])
            if add > 0 and a != b:
                entry = pairs.setdefault((a, b), [np.zeros(36), 2.44])
                entry[0] = entry[0] + add
    keys = sorted(pairs)
    loss = float(db.table("V_EMM_NUGPIPE_PARM")["LINELOSS"][0])
    return {"exporter": np.array([k[0] for k in keys]), "importer": np.array([k[1] for k in keys]),
            "capacity_gw": np.stack([pairs[k][0] for k in keys]), "cost": np.array([pairs[k][1] for k in keys]),
            "loss": loss}


def _fill_prices(a: np.ndarray, y: int) -> np.ndarray:
    v = a[:NUM_R, y].astype(float)
    ok = v > 0
    return np.where(ok, v, v[ok].mean() if ok.any() else 1.0)


def benchmark_weight(year: int) -> float:
    """1 through BENCHMARK_LAST, then down to 0 over BENCHMARK_FADE years."""
    return float(np.clip(1.0 - (year - BENCHMARK_LAST) / BENCHMARK_FADE, 0.0, 1.0))


def credit_share(year_end: dict, year: int, rule: tuple) -> dict:
    """Share of each capture group's capacity that still earns 45Q in `year`, by region.

    EIA's rule (udat.f, UL_45Q_YR and EC_45Q): a unit group earns the credit from the year it starts capturing,
    if that year is between I_45Q_SYR and I_45Q_LYR_RET (retrofits; LYR_NEW for new plants, the same 2038 in
    cb2026), for I_45Q_DURATION (12) years. Capacity has no unit dates here, so each year's increase in a group's
    year-end capacity is a cohort that started capturing that year.
    year_end: {year: {group: (25,) GW at year end}}, covering the years before `year` that have capacity.
    rule: (first year, last start year, duration).
    """
    first, last, duration = rule
    out = {}
    for g in CAPTURE_GROUPS:
        now = year_end[year][g]
        credited = np.zeros(NUM_R)
        for t in range(max(first, year - duration + 1), min(year, last) + 1):
            if t in year_end and t - 1 in year_end:
                credited += np.maximum(year_end[t][g] - year_end[t - 1][g], 0.0)
        out[g] = np.clip(credited / np.maximum(now, 1e-9), 0.0, 1.0)
    return out


def credit_rule(snapshot) -> tuple:
    return (int(snapshot["TCS45Q/i_45q_syr"]), int(snapshot["TCS45Q/i_45q_lyr_ret"]),
            int(snapshot["TCS45Q/i_45q_duration"]))


def restart_capture_capacity(snapshot, year: int) -> dict:
    """Year-end capacity of the capture groups in the reference run: {group: (25,) GW}."""
    y = year - history.FIRST_YEAR
    return {g: _ucap(snapshot, CAPACITY_PREFIXES[g], y) for g in CAPTURE_GROUPS}


def build_case(snapshot, year: int, trade: str = "none") -> DispatchCase:
    """Assemble a year's inputs from the reference run's capacity and fuel prices.

    trade="none": regions meet their own net load from sales (demand.net_load_twh).
    trade="reference": each region's net load is the reference run's generation in that
    region, which fixes the interregional exchange at EIA's result.
    """
    y = year - history.FIRST_YEAR
    cap = {g: _in_service(snapshot, p, EXISTING_TYPES.get(g), year) for g, p in CAPACITY_PREFIXES.items()}
    cap["coal"] = np.maximum(cap["coal"] - cap["coal_ccs"], 0.0)
    types_of = {g: existing_types(g) for g in THERMAL}
    if COFIRE_GROUP:
        cap["cofire"] = np.minimum(_in_service(snapshot, COFIRE_PREFIXES, EXISTING_TYPES["cofire"], year), cap["steam"])
        cap["steam"] = cap["steam"] - cap["cofire"]
    else:
        cap["cofire"] = np.zeros(NUM_R)
    u = plants.load_units()
    ptype = {t.code: t for t in technology.efd_plant_types()}
    params = technology.type_parameters()
    codes = technology.ecp_codes()
    hr_new_all = technology.new_heat_rate(year)        # UPHTRT (ucape.f 625-641): UPPHRT0 for every gas type

    heat, vom, oil, avail = {}, {}, {}, {}
    for g in THERMAL:
        types = types_of[g]
        existing = plants.capacity_gw(year, types)[:NUM_R]
        hr_ex = _weighted(u.heat_rate, u.summer_mw, types, u.region, year, 10000.0)
        vom_ex = _weighted(u.vom, u.summer_mw, types, u.region, year, 2.0)
        i = codes.index(NEW_TYPE[g])
        hr_new, vom_new = float(hr_new_all[i]), float(params["vom"][i])
        total = np.maximum(cap[g], 1e-9)
        ex_used = np.minimum(existing, total)
        new = np.maximum(total - ex_used, 0.0)
        heat[g] = (ex_used * hr_ex + new * hr_new) / total
        vom[g] = (ex_used * vom_ex + new * vom_new) / total
        if g in OIL_TYPES:
            oil_cap = plants.capacity_gw(year, OIL_TYPES[g])[:NUM_R]
            oil[g] = np.divide(oil_cap, existing, out=np.zeros(NUM_R), where=existing > 0)
        else:
            oil[g] = np.zeros(NUM_R)
        pt = ptype[AVAIL_TYPE[g]]
        avail[g] = (pt.forced_outage, pt.max_capacity_factor)
    # Coal that captures CO2 burns more fuel per kWh and costs more to run: use the plant file's own
    # with-capture heat rate and variable O&M (T_CCSHR, T_CCSV) for the captured share.
    tb = db.table("V_EMM_PLTF860")
    coal_u = np.isin(u.efd_type, EXISTING_TYPES["coal"]) & (tb["T_CCSHR"] > 0) & (tb["T_CCSHR"] < CCS_HEAT_RATE_MAX)
    ccs_hr = _weighted_mask(tb["T_CCSHR"], u.summer_mw, coal_u, u.region, 14000.0)
    ccs_vom = _weighted_mask(tb["T_CCSV"], u.summer_mw, coal_u, u.region, 1.5)
    heat["coal_ccs"] = ccs_hr
    capture_net = _weighted_mask(u.heat_rate / np.where(coal_u, tb["T_CCSHR"], 1.0), u.summer_mw, coal_u, u.region, 0.7)
    vom["coal_ccs"] = vom["coal"] + ccs_vom
    heat["gas_ccs"] = np.full(NUM_R, float(hr_new_all[codes.index("CS")]))
    coal_share = cofire_case(year, cap["cofire"], heat, vom)
    heat["nuclear"] = _weighted(u.heat_rate, u.summer_mw, EXISTING_TYPES["nuclear"], u.region, year, 10400.0)

    price = {
        "coal": _fill_prices(snapshot["UEFDOUT/upcoalavg"], y),
        "gas": _fill_prices(snapshot["UEFDOUT/upgasprc"], y),
        "distillate": _fill_prices(snapshot["UEFDOUT/updisprc"], y),
        "residual": _fill_prices(snapshot["UEFDOUT/upresprc"], y),
        "uranium": _fill_prices(snapshot["UEFDOUT/upnucprc"], y),
    }
    mcf = {g: _monthly_cf(EXISTING_TYPES[g], year) for g in ("nuclear", "hydro", "other")}
    efd_index = {pt.code: i for i, pt in enumerate(technology.efd_plant_types())}
    profiles, build_profiles = {}, {}
    for group, parts in WRENEW_PROFILES.items():
        caps = [_in_service(snapshot, (prefix,), (code,), year) for prefix, _, code in parts]
        outage = [snapshot["UEFDOUT/up_xfor"][efd_index[code], :NUM_R, y].astype(float) for _, _, code in parts]
        cfs = [_wrenew_profile(snapshot, key, y) * (1.0 - o)[:, None, None] for (_, key, _), o in zip(parts, outage)]
        build_profiles[group] = cfs[0]
        total = np.maximum(sum(caps), 1e-9)
        new_profile = sum(c[:, None, None] * f for c, f in zip(caps, cfs)) / total[:, None, None]
        cap[group] = sum(caps)
        # WRENEW's profiles are for new builds. In EIA's run the wind, solar and hydro generation of the first years is
        # held to the Short-Term Energy Outlook (benchmark constraints within 2%, emmcntl.txt and
        # steo_benchmark_emm.csv), which sits well below what the new-build profiles give for the old fleet (solar
        # 20% capacity factor against 27%). Standing in for that, the fleet running at the end of the history (units
        # online by BASE_YEAR) keeps its plant-file capacity factor, with WRENEW's hourly shape, for BENCHMARK_LAST
        # years, fading out by BENCHMARK_FADE. Later years, and all new capacity, use WRENEW's level.
        types = EXISTING_TYPES[group]
        old_fleet = plants.online(year) & np.isin(u.efd_type, list(types)) & (u.online_year <= BASE_YEAR)
        file_cap = np.zeros(NUM_R)
        np.add.at(file_cap, u.region[old_fleet] - 1, u.summer_mw[old_fleet] / 1000.0)
        file_cf = _weighted_mask(u.capacity_factor, u.summer_mw, old_fleet, u.region, 0.3)
        day_w = load.day_weights().reshape(36).astype(float)
        level = (new_profile * day_w[None, :, None]).sum(axis=(1, 2)) / (24.0 * day_w.sum())
        shape = new_profile / np.maximum(level, 1e-9)[:, None, None]
        share = benchmark_weight(year) * np.minimum(file_cap / total, 1.0)[:, None, None]
        profiles[group] = share * file_cf[:, None, None] * shape + (1.0 - share) * new_profile

    shapes = load.regional_shapes().reshape(NUM_R, 36, 24)
    w = load.day_weights().reshape(36).astype(float)
    nl = demand.net_load_twh(snapshot, year)
    if trade == "reference":
        nl = snapshot["UEFDOUT/ugntlnr"][:, :NUM_R, y].sum(axis=0).astype(float)
    links = build_links(snapshot, year) if trade != "reference" else None
    credit = float(snapshot["TCS45Q/ccs_saline_45q"][y])
    # Oil steam units flagged must-run (plant file T_MRUN at or after the year) burn residual oil at their
    # historical capacity factor whatever it costs, as EFD's minimum-run rows force them to. They leave the
    # dispatchable steam capacity. Coal units list distillate as their second fuel (1% of Btu): ignition fuel.
    on = plants.online(year)
    sto = on & (u.efd_type == "STO") & (tb["T_MRUN"] >= year) & (tb["T_MRUN"] > 0)
    mr_cap, mr_gw = np.zeros(NUM_R), np.zeros(NUM_R)
    np.add.at(mr_cap, u.region[sto] - 1, u.summer_mw[sto] / 1000.0)
    np.add.at(mr_gw, u.region[sto] - 1, u.summer_mw[sto] / 1000.0 * tb["T_CF"][sto])
    mr_hr = _weighted_mask(u.heat_rate, u.summer_mw, sto, u.region, 11000.0)
    cap["steam"] = np.maximum(cap["steam"] - mr_cap, 0.0)
    coal_on = on & np.isin(u.efd_type, EXISTING_TYPES["coal"])
    second = np.array([x.strip() for x in tb["CFL_2"]], dtype=object)
    ignition = float(np.average(np.where(second == "DS", tb["T_FSHR_2"], 0.0)[coal_on], weights=u.summer_mw[coal_on])) if coal_on.any() else 0.0
    rule = credit_rule(snapshot)
    year_end = {t: restart_capture_capacity(snapshot, t) for t in range(rule[0] - 1, year + 1)}
    return DispatchCase(year, cap, heat, vom, price, oil, avail, {g: np.full(NUM_R, avail[g][1]) for g in THERMAL}, credit, mcf,
                        profiles, nl, shapes, w, links, 0.0, mr_gw, mr_hr, ignition,
                        credit_share=credit_share(year_end, year, rule), build_profile=build_profiles,
                        coal_share=coal_share, capture_net=capture_net)


def cofire_case(year: int, cap_cofire: np.ndarray, heat: dict, vom: dict) -> dict:
    """Heat rate, variable O&M (set in `heat` and `vom`) and coal share of the cofire group (COFIRE_GROUP).

    The plant file's CTN units keep their own heat rate, variable O&M and coal share (fuel 2 when it is a coal curve,
    capped at UEPA_CGSH from UEPA_GSYR, udat.f 6457). Capacity beyond them is coal EIA converted after the plant file:
    the coal group's heat rate +5% and variable O&M x0.75 (capacity.CONVERT_HR_PENALTY, CONVERT_VOM_ADJ) at UEPA_CGSH
    of coal (uecp.f 28148). After UEPA_CLCFYR no unit cofires coal. Returns {"cofire": (25,) coal share of Btu}."""
    from nems_open.emm import capacity as ecp     # imported here: capacity imports this module
    rule = ecp.epa111()
    u = plants.load_units()
    tb = db.table("V_EMM_PLTF860")
    on = plants.online(year) & np.isin(u.efd_type, EXISTING_TYPES["cofire"])
    second = np.array([str(x).strip() for x in tb["CFL_2"]], dtype=object)
    coal2 = np.array([len(f) == 2 and f[0] in COAL_FUELS for f in second])
    share_u = np.where(coal2, np.asarray(tb["T_FSHR_2"], dtype=float), 0.0)
    cap_share = rule["cofire_coal_share"]
    if rule["switch"] and year >= rule["gas_switch_last"]:
        share_u = np.minimum(share_u, cap_share)
    existing = np.zeros(NUM_R)
    np.add.at(existing, u.region[on] - 1, u.summer_mw[on] / 1000.0)
    total = np.maximum(cap_cofire, 1e-9)
    ex_used = np.minimum(existing, cap_cofire)
    new = np.maximum(cap_cofire - ex_used, 0.0)
    hr_ex = _weighted_mask(u.heat_rate, u.summer_mw, on, u.region, 10800.0)
    vom_ex = _weighted_mask(u.vom, u.summer_mw, on, u.region, 0.55)
    sh_ex = _weighted_mask(share_u, u.summer_mw, on, u.region, cap_share)
    heat["cofire"] = (ex_used * hr_ex + new * heat["coal"] * (1.0 + ecp.CONVERT_HR_PENALTY)) / total
    vom["cofire"] = (ex_used * vom_ex + new * vom["coal"] * ecp.CONVERT_VOM_ADJ) / total
    share = (ex_used * sh_ex + new * cap_share) / total
    if rule["switch"] and year > rule["cofire_last"]:
        share = np.zeros(NUM_R)
    return {"cofire": np.where(cap_cofire > 0, share, 0.0)}


def reduce_hours(case: DispatchCase, hours_per_block: int = 3) -> DispatchCase:
    """The same case with the 24 hours of each typical day averaged into blocks, so the LP is smaller.

    Load shapes and wind and solar profiles are averaged over each block; `solve` weights each block by its
    length. Three-hour blocks cut the solve to about a third of the time and move the totals by under 1%.
    """
    from dataclasses import replace

    def blocks(a):
        return a.reshape(a.shape[:-1] + (24 // hours_per_block, hours_per_block)).mean(axis=-1)

    bp = None if case.build_profile is None else {k: blocks(v) for k, v in case.build_profile.items()}
    return replace(case, shapes=blocks(case.shapes), profile={k: blocks(v) for k, v in case.profile.items()}, build_profile=bp)


def spin_requirement(load_gw: np.ndarray, weights: np.ndarray, net_gw: np.ndarray) -> np.ndarray:
    """EFD's spinning reserve requirement before intermittents (SP_RES_RQMT_IN), GW in every typical hour or block of
    `load_gw` (25, 36, n): on the season's slices by net load (capacity.ecp_slice_heights), SR_RQMT_HGHT x the slice's
    height + SR_RQMT_DIFF x (the season's peak slice - that height). Returns (slice of every hour, 0-8 in ECP order;
    the requirement), both (25, 36, n)."""
    from nems_open.emm import capacity as ecp
    slice_of, height = ecp.ecp_slice_heights(load_gw, weights, np.repeat(np.arange(12), 3), net_gw)
    peak = height[:, (np.arange(9) // 3) * 3]
    req = ecp.SR_RQMT_HGHT * height + ecp.SR_RQMT_DIFF * (peak - height)
    return slice_of, np.take_along_axis(req, slice_of.reshape(slice_of.shape[0], -1), axis=1).reshape(slice_of.shape)


def max_load_shape(slice_of: np.ndarray, height: np.ndarray, year: int) -> dict:
    """EFD's maximum-load mode (EFD_MAX_LOAD_SHAPE): per LP group in MAX_LOAD_GROUPS, the share of (1 - FOR) x the
    committable capacity a unit can produce in every hour, SR_MAX_LF + (1 - SR_MAX_LF) x its slice's height / the
    season's peak slice height (uefd.f OPBSLD DRAT_MAX). slice_of (25, 36, n) and height (25, 9) are
    capacity.ecp_slice_heights'. Before MAX_LOAD_FIRST_YEAR, ones."""
    from nems_open.emm import capacity as ecp
    if year < MAX_LOAD_FIRST_YEAR:
        return {g: np.ones(slice_of.shape) for g in MAX_LOAD_GROUPS}
    lf = ecp.named_ranges(technology.ECPDATY, "SPNRSV")["SR_MAX_LF"]
    codes = technology.ecp_codes()
    peak = height[:, (np.arange(9) // 3) * 3]
    rel = np.divide(height, peak, out=np.ones_like(height), where=peak > 0).clip(0.0, 1.0)
    rel_h = np.take_along_axis(rel, slice_of.reshape(slice_of.shape[0], -1), axis=1).reshape(slice_of.shape)
    out = {}
    for g, code in MAX_LOAD_GROUPS.items():
        a = float(lf[codes.index(code)])
        out[g] = a + (1.0 - a) * rel_h
    return out


def efd_outage_rates() -> dict:
    """(forced outage, planned maintenance) by thermal group as EFD uses them: pltdata's rates for AVAIL_TYPE scaled
    by one factor so that (1 - FOR)(1 - PMR) is the type's maximum capacity factor (udat.f 10168-10236); left as they
    are where the maximum is at or above (1 - FOR)(1 - PMR)."""
    pt = {t.code: t for t in technology.efd_plant_types()}
    out = {}
    for g in THERMAL:
        t = pt[AVAIL_TYPE[g]]
        f, p, mcf = t.forced_outage, t.planned_maintenance, t.max_capacity_factor
        k = np.sqrt(mcf / ((1.0 - f) * (1.0 - p)))
        out[g] = (1.0 - k * (1.0 - f), 1.0 - k * (1.0 - p)) if k < 1.0 else (f, p)
    return out


def maintenance_season_share(load_gw: np.ndarray, weights: np.ndarray) -> np.ndarray:
    """Planned maintenance per unit of PMR in every typical day, (25, 36): ED$PM's schedule taken as a rule. The year's
    PMR x 8760 hours of maintenance go into the two EFD seasons (capacity.ECP_SEASON_MONTHS) other than the one with
    the region's highest load, spread evenly over their hours. EFD's LP picks the seasons itself; on EIA's 2031 fleet
    that LP choice (tried as columns: 60 s a solve instead of 6) left the summer free and put coal's 0.20 at 0.24 of
    capacity in winter and 0.35 in the shoulder months, against 0.29 in both here."""
    from nems_open.emm import capacity as ecp
    season = ecp.ecp_season_of_month()[np.repeat(np.arange(12), 3)]                 # (36,)
    hours = np.array([weights[season == k].sum() * 24.0 for k in range(3)])
    out = np.zeros((load_gw.shape[0], season.size))
    for r in range(load_gw.shape[0]):
        peak = int(np.argmax([load_gw[r][season == k].max() for k in range(3)]))
        share = HOURS_PER_YEAR / (hours.sum() - hours[peak])
        out[r] = np.where(season == peak, 0.0, share)
    return out


def coal_share(case: DispatchCase, g: str) -> np.ndarray:
    """Share of a non-coal thermal group's Btu that is coal (the cofire group), by region."""
    cs = (case.coal_share or {}).get(g)
    return np.zeros(NUM_R) if cs is None else np.asarray(cs, dtype=float)


def emissions_per_mwh(case: DispatchCase, g: str, oil_share: dict = None) -> np.ndarray:
    """Metric tons of CO2 released per MWh by a thermal group, by region (after capture)."""
    heat = case.heat_rate[g] / 1000.0                       # MMBtu per MWh
    if g.startswith("coal"):
        tons = heat * CO2_PER_TBTU["coal"]
    else:
        oil = CO2_PER_TBTU["residual" if g == "steam" else "distillate"]
        o = (case.oil_share if oil_share is None else oil_share).get(g, np.zeros(NUM_R))
        c = coal_share(case, g)
        tons = heat * ((1 - o - c) * CO2_PER_TBTU["gas"] + o * oil + c * CO2_PER_TBTU["coal"])
    return tons * (1.0 - CAPTURE_RATE) if g in CAPTURE_GROUPS else tons


def generating_capacity(case: DispatchCase) -> dict:
    """Thermal capacity that can generate, GW by group and region: case.capacity, with CCS coal net of its capture plant
    (CCS_CAPACITY_PENALTY)."""
    out = {g: np.asarray(case.capacity[g], dtype=float) for g in THERMAL}
    if CCS_CAPACITY_PENALTY and case.capture_net is not None:
        out["coal_ccs"] = out["coal_ccs"] * case.capture_net
    return out


def solve(case: DispatchCase, solver: str = "highs", progress: bool = False) -> DispatchResult:
    R = pd.Index(np.arange(1, NUM_R + 1), name="region")
    D = pd.Index(np.arange(36), name="day")
    nh = case.shapes.shape[-1]
    hp = 24 // nh                         # hours in each block
    H = pd.Index(np.arange(nh), name="hour")
    TH = pd.Index(list(THERMAL), name="group")
    MO = pd.Index(np.arange(12), name="month")
    month_of_day = np.repeat(np.arange(12), 3)
    oil_share = {g: np.zeros(NUM_R) for g in THERMAL} if OIL_UNITS_LAST else case.oil_share
    w = xr.DataArray(case.weights * hp, coords=[D])
    ones = xr.DataArray(np.ones((NUM_R, 36, nh)), coords=[R, D, H])

    def by_region(a):
        return xr.DataArray(np.asarray(a, dtype=float), coords=[R]) * ones

    flat = case.flat_twh if case.flat_twh is not None else np.zeros(NUM_R)
    flat_gw = flat * 1000.0 / HOURS_PER_YEAR
    load_gw = xr.DataArray((case.net_load_twh - flat)[:, None, None] * 1000.0 * case.shapes + flat_gw[:, None, None], coords=[R, D, H])
    m = linopy.Model()

    # Thermal plants
    capg = generating_capacity(case)
    cap_th = xr.DataArray(np.stack([capg[g] * (1 - case.avail[g][0]) for g in THERMAL], axis=1), coords=[R, TH])
    if EFD_DERATE:
        rates = efd_outage_rates()
        season = maintenance_season_share(load_gw.transpose("region", "day", "hour").values, case.weights)   # (25, 36)
        pmr = np.array([rates[g][1] for g in THERMAL])
        out = np.clip(pmr[None, :, None] * season[:, None, :], 0.0, 1.0)                                   # (25, groups, 36)
        cap_g = np.stack([capg[g] for g in THERMAL], axis=1)
        avail = np.array([1.0 - rates[g][0] for g in THERMAL])
        committable = xr.DataArray(cap_g[:, :, None, None] * (1.0 - out)[..., None] * np.ones(nh), coords=[R, TH, D, H])
        upper = committable * xr.DataArray(avail, coords=[TH])
        if EFD_MAX_LOAD_SHAPE:
            load_np = load_gw.transpose("region", "day", "hour").values
            wind_solar = sum(case.capacity[k][:, None, None] * case.profile[k] for k in ("wind", "solar"))
            from nems_open.emm import capacity as ecp
            sl, ht = ecp.ecp_slice_heights(load_np, case.weights, month_of_day, load_np - wind_solar)
            shape = np.ones((NUM_R, len(THERMAL), 36, nh))
            for g, a in max_load_shape(sl, ht, case.year).items():
                shape[:, THERMAL.index(g)] = a
            upper = upper * xr.DataArray(shape, coords=[R, TH, D, H])
    else:
        upper = (cap_th * ones).transpose("region", "group", "day", "hour")
        committable = upper
    g_th = m.add_variables(lower=0, upper=upper, name="gen_thermal")
    e_lim_np = np.stack([capg[g] * case.max_cf[g] * HOURS_PER_YEAR for g in THERMAL], axis=1)    # GWh
    e_lim = xr.DataArray(e_lim_np, coords=[R, TH])
    energy_out = (g_th * w).sum(["day", "hour"])
    m.add_constraints(energy_out <= e_lim, name="thermal_energy")
    cost = np.zeros((NUM_R, len(THERMAL)))
    for k, g in enumerate(THERMAL):
        oil_price = case.price["residual"] if g == "steam" else case.price["distillate"]
        is_coal = g.startswith("coal")
        o, c = oil_share.get(g, np.zeros(NUM_R)), coal_share(case, g)
        fuel = (1 - o - c) * case.price["coal" if is_coal else "gas"] + o * oil_price + c * case.price["coal"]
        cost[:, k] = case.heat_rate[g] / 1000.0 * fuel + case.vom[g] + case.carbon_price * emissions_per_mwh(case, g, oil_share)
        if g in CAPTURE_GROUPS:
            # 45Q pays per ton captured; tons per MWh = MMBtu per MWh x tons of CO2 per MMBtu.
            tons = case.heat_rate[g] / 1000.0 * CO2_PER_TBTU[CAPTURE_GROUPS[g]] * CAPTURE_RATE
            share = case.credit_share[g] if case.credit_share is not None else 1.0
            cost[:, k] -= case.credit_45q * share * tons
    cost_da = xr.DataArray(cost, coords=[R, TH])

    # Fixed-profile plants
    def profile(group):
        return xr.DataArray(case.monthly_cf[group][:, month_of_day], coords=[R, D]) * ones

    nuc_gw = by_region(case.capacity["nuclear"]) * profile("nuclear")
    ren_gw = {
        "wind": by_region(case.capacity["wind"]) * xr.DataArray(case.profile["wind"], coords=[R, D, H]),
        "solar": by_region(case.capacity["solar"]) * xr.DataArray(case.profile["solar"], coords=[R, D, H]),
        "other": by_region(case.capacity["other"]) * profile("other"),
    }
    fixed = nuc_gw + ren_gw["wind"] + ren_gw["solar"] + ren_gw["other"]
    oil_gw = by_region(case.must_run_oil_gw if case.must_run_oil_gw is not None else np.zeros(NUM_R))

    # Hydro within a monthly energy budget
    g_hy = m.add_variables(lower=0, upper=by_region(case.capacity["hydro"]), name="gen_hydro")
    month_w = xr.DataArray(np.eye(12)[month_of_day], coords=[D, MO])
    days_in_month = np.array([case.weights[month_of_day == mo].sum() for mo in range(12)])
    budget = xr.DataArray(case.monthly_cf["hydro"] * case.capacity["hydro"][:, None] * days_in_month[None, :] * 24.0, coords=[R, MO])
    m.add_constraints((g_hy * (w * month_w)).sum(["day", "hour"]) <= budget, name="hydro_budget")

    # Storage, cyclic inside each typical day
    net_storage = 0
    sto, spin_sto = {}, {}
    for name, (dur, rte) in STORAGE.items():
        c = by_region(case.capacity[name])
        eta = np.sqrt(rte)
        ch = m.add_variables(lower=0, upper=c, name=f"{name}_charge")
        di = m.add_variables(lower=0, upper=c, name=f"{name}_discharge")
        soc = m.add_variables(lower=0, upper=c * dur, name=f"{name}_soc")
        m.add_constraints(soc - soc.roll(hour=1) - hp * eta * ch + hp * di / eta == 0, name=f"{name}_balance")
        net_storage = net_storage + di - ch
        sto[name] = (ch, di)
        spin_sto[name] = (c, di, soc)

    trade_in = trade_out = 0
    trade = None
    if case.links is not None:
        L = pd.Index(np.arange(len(case.links["exporter"])), name="link")
        cap_l = xr.DataArray(case.links["capacity_gw"], coords=[L, D]) * xr.DataArray(np.ones(nh), coords=[H])
        trade = m.add_variables(lower=0, upper=cap_l.transpose("link", "day", "hour"), name="trade")
        into = np.zeros((NUM_R, len(L)))
        outof = np.zeros((NUM_R, len(L)))
        into[case.links["importer"], np.arange(len(L))] = 1.0 - case.links["loss"]
        outof[case.links["exporter"], np.arange(len(L))] = 1.0
        trade_in = (trade * xr.DataArray(into, coords=[R, L])).sum("link")
        trade_out = (trade * xr.DataArray(outof, coords=[R, L])).sum("link")
    spill = m.add_variables(lower=0, coords=[R, D, H], name="spill")
    unserved = m.add_variables(lower=0, coords=[R, D, H], name="unserved")
    curtail = 0
    if case.flex_share > 0:
        # Flexible load: cut up to the flat load in any hour, within a yearly energy budget by region.
        curtail = m.add_variables(lower=0, upper=xr.DataArray(flat_gw[:, None, None] * np.ones((NUM_R, 36, nh)), coords=[R, D, H]), name="curtail")
        m.add_constraints((curtail * w).sum(["day", "hour"]) <= xr.DataArray(flat * 1000.0 * case.flex_share, coords=[R]), name="curtail_budget")
    bal = m.add_constraints(g_th.sum("group") + g_hy + net_storage + unserved + curtail - spill + trade_in - trade_out == load_gw - fixed - oil_gw, name="balance")

    objective = (g_th * cost_da * w).sum() + (g_hy * w).sum() * 0.01 + (unserved * (UNSERVED_COST * w)).sum()
    spin = spin_row = None
    if EFD_SPIN_RESERVE:
        from nems_open.emm import capacity as ecp     # imported here: capacity imports this module
        mins = ecp.spin_min_cf()
        inv = xr.DataArray(np.array([1.0 / mins[g] - 1.0 for g in THERMAL]), coords=[TH])
        spin = m.add_variables(lower=0, coords=[R, TH, D, H], name="spin")
        m.add_constraints(spin + g_th - committable <= 0, name="spin_headroom")
        m.add_constraints(spin - g_th * inv <= 0, name="spin_committed")
        supply = spin.sum("group")
        c, di, soc = spin_sto["pumped"]
        ss = m.add_variables(lower=0, coords=[R, D, H], name="spin_pumped")
        m.add_constraints(ss + di - c <= 0, name="spin_pumped_headroom")
        m.add_constraints(ss - di * (1.0 / mins["pumped"] - 1.0) <= 0, name="spin_pumped_committed")
        supply = supply + ss
        intermittent = (ren_gw["wind"] + ren_gw["solar"]).transpose("region", "day", "hour")
        load_np = load_gw.transpose("region", "day", "hour").values
        slice_of, req = spin_requirement(load_np, case.weights, load_np - intermittent.values)
        battery_sr = xr.DataArray(np.asarray(EFD_BATTERY_SR)[slice_of] * case.capacity["battery"][:, None, None], coords=[R, D, H])
        idle = (by_region(case.capacity["nuclear"]) * EFD_NUCLEAR_SR + by_region(case.capacity["other"]) - ren_gw["other"]
                + battery_sr)
        short = m.add_variables(lower=0, coords=[R, D, H], name="spin_shortfall")
        spin_row = m.add_constraints(supply + short >= xr.DataArray(req, coords=[R, D, H]) + ecp.SR_INT * intermittent - idle,
                                     name="spin_reserve")
        objective = objective + (short * (SPIN_SHORTFALL_COST * w)).sum()
    if trade is not None:
        objective = objective + (trade * (xr.DataArray(case.links["cost"], coords=[L]) * w)).sum()
    m.add_objective(objective)
    status, cond = m.solve(solver_name=solver, progress=progress)

    res = DispatchResult(year=case.year, case=case, status=f"{status}:{cond}")
    if status != "ok":
        return res
    wd = case.weights[None, :, None] * hp
    energy = lambda gw: (np.asarray(gw) * wd).sum(axis=(1, 2)) / 1000.0         # GW x hours -> TWh
    gth = g_th.solution.transpose("region", "group", "day", "hour").values
    gen = {g: energy(gth[:, k]) for k, g in enumerate(THERMAL)}
    gen["hydro"] = energy(g_hy.solution.transpose("region", "day", "hour").values)
    for name, (ch, di) in sto.items():
        gen[name] = energy((di.solution - ch.solution).transpose("region", "day", "hour").values)
    fx = lambda a: energy(a.transpose("region", "day", "hour").values)
    spilled = energy(spill.solution.transpose("region", "day", "hour").values)
    fixed_tot = fx(fixed)
    keep = np.divide(fixed_tot - spilled, fixed_tot, out=np.ones(NUM_R), where=fixed_tot > 0)
    gen["nuclear"] = fx(nuc_gw) * keep
    for g in RENEWABLE:
        gen[g] = fx(ren_gw[g]) * keep
    gen["oil_must_run"] = np.zeros(NUM_R) if case.must_run_oil_gw is None else case.must_run_oil_gw * 8.76
    res.generation_twh = gen
    if trade is not None:
        flow = trade.solution.transpose("link", "day", "hour").values
        res.trade_twh = (flow * case.weights[None, :, None]).sum(axis=(1, 2)) / 1000.0
    res.spilled_twh = spilled
    res.unserved_twh = energy(unserved.solution.transpose("region", "day", "hour").values)
    res.curtailed_twh = energy(curtail.solution.transpose("region", "day", "hour").values) if case.flex_share > 0 else np.zeros(NUM_R)

    # TWh x Btu/kWh = 1e9 Btu = 1e-3 trillion Btu
    fuel = {k: np.zeros(NUM_R) for k in ("coal", "gas", "distillate", "residual", "uranium")}
    for g in THERMAL:
        btu = gen[g] * case.heat_rate[g] * 1e-3
        if g.startswith("coal"):
            fuel["coal"] += btu
        else:
            o, c = oil_share.get(g, np.zeros(NUM_R)), coal_share(case, g)
            fuel["coal"] += btu * c
            fuel["gas"] += btu * (1 - o - c)
            fuel["residual" if g == "steam" else "distillate"] += btu * o
    fuel["uranium"] = gen["nuclear"] * case.heat_rate["nuclear"] * 1e-3
    if case.must_run_oil_gw is not None:
        fuel["residual"] = fuel["residual"] + gen["oil_must_run"] * case.must_run_oil_hr * 1e-3
    ignition = case.ignition_share * fuel["coal"]
    fuel["coal"] = fuel["coal"] - ignition
    fuel["distillate"] = fuel["distillate"] + ignition
    res.fuel_tbtu = fuel
    co2 = sum(fuel[k] * CO2_PER_TBTU[k] for k in CO2_PER_TBTU)
    # Capture groups release only (1 - rate) of their CO2.
    for g, fuel_key in CAPTURE_GROUPS.items():
        co2 = co2 - CAPTURE_RATE * gen[g] * case.heat_rate[g] * 1e-3 * CO2_PER_TBTU[fuel_key]
    res.co2_mt = co2
    res.price = bal.dual.transpose("region", "day", "hour").values / np.maximum(wd, 1e-9)
    if spin_row is not None:
        res.spin_price = spin_row.dual.transpose("region", "day", "hour").values / np.maximum(wd, 1e-9)
        sp = spin.solution.transpose("region", "group", "day", "hour").values
        res.spin_gw = {g: sp[:, k] for k, g in enumerate(THERMAL)}
        res.spin_gw["pumped"] = m.variables["spin_pumped"].solution.transpose("region", "day", "hour").values
        res.spin_gw["idle"] = idle.transpose("region", "day", "hour").values
        res.spin_gw["required"] = spin_row.rhs.transpose("region", "day", "hour").values + res.spin_gw["idle"]
    res.objective = float(m.objective.value)
    return res
