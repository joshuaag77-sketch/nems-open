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
from functools import lru_cache

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
# Capture rate by group. EFD releases (1 - ECSEQS) of a capturing unit's CO2 (uefd.f 3122-3232) and reports the rest
# to CCATS (SUP_EMM_45Q / SUP_EMM_NTC, uefd.f 2876-2895). ECSEQS is the unit's WSEQEF (udat.f 10401): 0.90 for a coal
# retrofit (udat.f 9262 ECL_CCS_R, uecp.f 27648) and UPPCEF of the ECP type for a new plant (uecp.f 25645), 0.95 for
# gas with CCS (CS, ecpdaty.xlsx COSTPERF). Once its 45Q years end a unit may run in a reduced-capture mode at
# UPPCEF_MIN, but with EPA 111 on UPPCEF_MIN = UPPCEF for existing coal from UEPA_CLYR and new gas from UEPA_NWGSYR
# (udat.f 5175-5183), so in cb2026 every capturing unit keeps its full rate. On: those rates. Off: CAPTURE_RATE for both.
CAPTURE_BY_TYPE = True
COAL_RETROFIT_CAPTURE = 0.90
# EPA 111 holds new combined cycle without CCS to UEPA_NWGSCF (0.4) of its capacity from UEPA_NWGSYR (2029): udat.f
# 6444-6446 sets W_CF = MIN(W_CF, UEPA_NWGSCF) for every unit of ECP type AC or CC with WVIN > 1, which is the
# combined cycle ECP builds (the plant file's are EC and FC). The capacity LP holds gas_cc_new to it already. Here
# gas_cc is one group at one heat rate, and a cap on the group's mean let the old units' idle share carry the new
# ones' output at the group's blended heat rate, so combined cycle undercut gas with CCS everywhere. On, from
# UEPA_NWGSYR: gas_cc is two heat-rate tiers (HEAT_RATE_TIERS' machinery), the plant file's units at their mean heat
# rate and CCG's maximum capacity factor, and the capacity beyond them at the new AC heat rate and
# min(CCG's, UEPA_NWGSCF) (DispatchCase.tier_max_cf). Gas with CCS (7,239 Btu/kWh) then sits between new CC (6,226)
# and the old fleet (about 7,490), as it does in EFD. Off: one gas_cc tier with no cap.
EPA111_NEW_CC_CF = True
# With EPA111_NEW_CC_CF: the plant file's combined cycle in N_TIERS heat-rate tiers (heat_rate_tiers) instead of one.
GAS_CC_OLD_TIERS = True
# EFD holds the capped units to UEPA_NWGSCF through their availability, not an energy row. udat.f 6446 lowers the
# unit's W_CF; W_CFA (7023) and so AVGCF (8852) follow; for a new unit MAXCF = AVGCF (10189-10193); and 10194-10224
# then moves its FOR and PMR by one factor so that (1 - FOR)(1 - PMR) = MAXCF (MXLFR 0, udat.f 5240). For the new
# combined cycle at 0.4 that is FOR 0.37 and PMR 0.36, against CCG's 0.074 and 0.060 (pltdata's 0.055 and 0.041
# moved to its 0.87 maximum). Those rates are the unit's hourly ceiling and, through ED$PM, its maintenance, and the
# forced outage share is not reserve. On (with EPA111_NEW_CC_CF): the new-CC tier's hourly ceiling and committable capacity
# use those rates; its energy row stays (it no longer binds). Off: the tier has the group's rates and only the energy
# row caps it (Codex finding 11).
EPA111_DERATE = True

# The dispatched fleet is ownership classes 1 to 3. util.f's UCAP tally (7465-7510 for combined cycle, the same for
# every type) puts IOWN 1-2 in UCAP*U, 3 in UCAP*N and 4, the electric power sector's CHP, in UCAP*C and CGNTCAP. The
# dispatch takes its capacity from *U and *N and the CHP units' output off the load (demand.nontraditional_cogen_twh),
# so plant-file units of class 4 are not in it. On: the plant-file reads that size and describe the existing fleet
# (existing capacity against the restart's, heat rates, VOM, heat-rate tiers, in-service dates, cofired units, the
# old fleet's capacity factor) keep classes 1 to 3. In 2030 that takes about 20 GW of CHP combined cycle out of
# gas_cc's existing tiers, which had counted it as old capacity and pushed the new-build share (and its EPA 111 cap)
# down. Off: every class, as before (Codex finding 4).
FLEET_OWNERS_ONLY = True
FLEET_OWNERS = (1, 2, 3)

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
# Coal heat rates follow each unit's load. The plant file's THRATE is a unit's average heat rate at its historical
# capacity factor (T_CF). udat.f CRPGRP (7210-7262) stores WHRATE x Target_EFF(W_CFA) / Max_EFF as the group heat
# rate (UG_HTRT): the heat rate moved to full load on emmcntl's efficiency curve for the unit's coal region and
# configuration (HTRT_ADJUSTMENT in uefd.f; the curves follow %HAWAII RPS% in emmcntl.txt, read by udat.f 3845-3900,
# a configuration without a curve taking the one before it). Each dispatch mode then burns at UG_HTRT x Max_EFF /
# Target_EFF(its output per committed GW) (uefd.f OPBSLD 9970-9985, ECDSPF 13861). So a coal unit burns THRATE x
# Target(T_CF) / Target(L) at load L. The oracle's 2030 EFD files bear both steps out: Northampton (B3, coal region
# 2, T_CF 0.40) is UG_HTRT 10,052 = 11,868 x 0.847; the PJME C7 group is 9,230 against THRATE 10,116-10,427; and
# fuel / UG_HTRT gives the load each group's modes ran at, generation-weighted 0.74 (PART_LOAD_LEVEL; most groups
# 0.70-0.75, the maximum-load mode's (1 - FOR) x its mean shape). On: coal and coal_ccs heat rates are THRATE (or
# T_CCSHR) x that factor at PART_LOAD_LEVEL, capacity-weighted as before; coal converted to cofiring keeps the plain
# coal heat rate (ECP type NG has no curve). Against EIA's own 2030 coal burn (restart UFLCLNR / UGNCLNR) in the
# eight regions where coal units make nearly all the coal power, capacity-weighted THRATE is 3.6% high
# (generation-weighted; mean absolute error 3.7%) and this is 1.7% low (2.1%). It moves PJM's coal onto EIA's (2030
# PJME 7.9 -> 20.8 TWh, EIA 21.7). Dropping the units EIA retired, worst heat rate first, made the fit worse.
# Off: THRATE.
COAL_PART_LOAD_HEAT_RATE = True
PART_LOAD_LEVEL = 0.74
MAX_LOAD_GROUPS = {"coal": "B1"}   # LP group -> ECP type whose SR_MAX_LF it takes (all existing coal configurations: 0.55)
MAX_LOAD_FIRST_YEAR = BENCHMARK_LAST + 2   # uefd.f OPBSLD: DRAT_MAX = DRAT_ORG for coal while CURIYR <= UYR_STEO + 1
MAX_LOAD_STEO_LAST = "IS"   # that exemption covers ECP types up to WIIS (the coal configurations, PC, OC, IG, I2, PQ, IS)
# The cofired units take the same mode. OPBSLD gives every type with SR_CREDIT its U mode, and the STEO exemption
# stops at WIIS, so ECP type NG (the CTN units) has DRAT_MAX = (1 - FOR)(SR_MAX_LF + (1 - SR_MAX_LF) x height / peak)
# with SR_MAX_LF 0.5 in every year. On: cofire's hourly upper bound takes that shape. Off: the flat derate.
COFIRE_MAX_LOAD_SHAPE = True
COFIRE_MAX_LOAD_TYPE = "NG"
COFIRE_PREFIXES = ("ng",)
# EFD dispatches coal by configuration (ECP type B1..HC) and coal region, and buys each one's coal in its own coal LP
# (uefd.f ED$COL): supply steps per curve, transport per route, and sub-bituminous and lignite deliveries capped at what
# the configuration's units burned (EFD_SB_DVLIM, EFD_LG_DVLIM: the CMM writes them from EFD's own unit burn,
# EMM_CL_BTUS). Beyond its cap a western unit pays for bituminous coal from far away (0.3-0.5 1987$/MMBtu more in Texas,
# SPP, Colorado and the Southwest), the 9.9 escape where there is no bituminous route (Montana, Wyoming, the Dakotas),
# or, for Utah and Colorado bituminous, the 9.999 step above a curve's base production. In EIA's 2030 restart every
# capped configuration burns its cap; in the oracle's 2030 EFD MT C4 burns 4.45 TBtu on a 4.43 cap at a capacity
# factor of 0.05 while CU B7 runs at its ceiling. On: the coal group's output in each region is split into its units'
# classes (coal region, configuration; coal_supply.coal_classes), each with its share of the capacity and hourly
# ceiling, its own heat rate and VOM, and its coal bought in that LP. Dispatch only (the capacity LP keeps one coal
# price). Off: one coal group per region at the regional price.
COAL_BY_CONFIGURATION = True
# How a class's LP price meets the regional price (UPCOALAVG). False: each class at EIA's own burn pays the regional
# price (the LP adds what moving off that burn costs: a cap, a scarce curve). True: a region's classes pay the LP's
# delivered prices, shifted so EIA's mix pays the regional price; that also prices bituminous from northern
# Appalachia (S1, 1.44) against Ohio (1.08) and Kentucky (0.90), which with the dispatch's lower eastern marginal
# costs (PJMW 15.5 1987$/MWh load-weighted against the oracle EFD's 18.0) idles WV units EIA runs. 2030 coal against
# EIA: -1.7% (False) and -2.9% (True); 2025 -4.8% and -8.6%.
COAL_PRICE_BY_CLASS = False
COAL_CONFIG_LAST = "HC"         # the coal configurations are the ECP types up to HC
COAL_FUELS = ("B", "C", "H")   # plant-file fuel codes of the coal supply curves (B1..B8, C1..CX, H1..HC)
# EFD's dispatch modes (uefd.f OPBSLD 9715-9870). EFD commits a thermal group per season, not per hour: one column
# per mode L (it runs in the season's slices 1..L, the peak slice first; UPPCFB's low bound keeps coal and combined
# cycle from running peak-only) and per shape, each a FIXED output per committed GW in every slice it covers:
# O, normal (base-load types, UPPCFB low bound above 0.001: max((1 - FOR) x FOS_CF_EFD, SR_MIN_CF), ReStore's
# capacity factor by slice; turbines (1 - FOR) x height / the season's peak height), J, minimum load (SR_MIN_CF x
# height / the season's lowest height), U, maximum load ((1 - FOR) x (SR_MAX_LF + (1 - SR_MAX_LF) x height / peak);
# coal until UYR_STEO + 1 the plain derate). Every column puts 1 - its output on the slice's reserve row, so a
# group's reserve in a slice is its committed capacity less its output there. The shapes tie a group's output
# across the season's slices: a combined cycle group running near full in the peak slice runs near full in the
# base slice too, and holds 0.2 GW of reserve per GW there, not the 0.7 an hour-by-hour dispatch leaves idle at
# night. On (needs EFD_SPIN_RESERVE): per region, thermal group and season, commitment by mode and shape within
# the season's committable capacity; in every slice the hour-weighted output of its hours equals the shapes'
# output, every hour's output is at most the hourly ceiling on the committed share; the reserve rows are EFD's 9
# slices per region, thermal reserve committed less output, pumped storage, batteries, nuclear and other
# renewables as before at their slice averages, against the slice requirement plus SR_INT of the slice's wind and
# solar. Off: hourly reserve rows, each group's reserve at most its idle capacity in that hour.
EFD_DISPATCH_MODES = False
MODE_TYPE = {"coal": "B1", "coal_ccs": "PQ", "gas_cc": "EC", "gas_ccs": "CS", "gas_ct": "ET", "steam": "ST", "cofire": "NG"}
# ReStore's base-load fossil capacity factor by EFD slice (FOS_CF_EFD, uecp.f 39134-39236), the O shape of the
# base-load types: the 2030 EFD composite's (iterations 1 and 2 agree), by region, in ECP slice order (shoulder,
# summer, winter, each peak / middle / base). A stand-in for every year: this model has no ReStore.
FOS_CF_EFD = (
    (0.706, 0.542, 0.245, 0.958, 0.783, 0.622, 0.463, 0.453, 0.193),
    (0.918, 0.651, 0.206, 0.973, 0.837, 0.463, 0.799, 0.658, 0.208),
    (0.720, 0.723, 0.486, 0.972, 0.919, 0.729, 0.902, 0.844, 0.696),
    (0.902, 0.839, 0.697, 0.983, 0.913, 0.789, 0.906, 0.894, 0.799),
    (0.448, 0.435, 0.255, 0.888, 0.669, 0.396, 0.694, 0.569, 0.391),
    (0.902, 0.734, 0.609, 0.951, 0.876, 0.680, 0.759, 0.745, 0.681),
    (0.501, 0.190, 0.004, 0.815, 0.580, 0.131, 0.493, 0.372, 0.105),
    (0.045, 0.018, 0.000, 0.606, 0.231, 0.005, 0.274, 0.083, 0.009),
    (0.000, 0.000, 0.000, 0.565, 0.103, 0.000, 0.072, 0.004, 0.000),
    (0.803, 0.726, 0.397, 0.980, 0.829, 0.586, 0.812, 0.769, 0.549),
    (0.864, 0.845, 0.729, 0.976, 0.900, 0.757, 0.890, 0.879, 0.827),
    (0.546, 0.433, 0.132, 0.957, 0.876, 0.466, 0.860, 0.698, 0.499),
    (0.957, 0.938, 0.827, 0.972, 0.945, 0.863, 0.959, 0.949, 0.806),
    (0.942, 0.828, 0.520, 0.986, 0.938, 0.643, 0.929, 0.883, 0.477),
    (0.934, 0.827, 0.594, 0.976, 0.903, 0.788, 0.885, 0.878, 0.653),
    (0.735, 0.660, 0.461, 0.986, 0.884, 0.651, 0.859, 0.748, 0.536),
    (0.793, 0.431, 0.300, 0.981, 0.827, 0.441, 0.586, 0.493, 0.367),
    (0.574, 0.388, 0.215, 0.941, 0.776, 0.531, 0.587, 0.561, 0.429),
    (0.750, 0.416, 0.331, 0.968, 0.888, 0.498, 0.807, 0.602, 0.367),
    (0.577, 0.481, 0.170, 0.943, 0.753, 0.543, 0.538, 0.491, 0.154),
    (0.497, 0.405, 0.170, 0.928, 0.793, 0.476, 0.654, 0.589, 0.242),
    (0.643, 0.544, 0.193, 0.915, 0.811, 0.601, 0.699, 0.615, 0.197),
    (0.893, 0.817, 0.733, 0.951, 0.859, 0.791, 0.890, 0.847, 0.775),
    (0.878, 0.810, 0.576, 0.982, 0.908, 0.793, 0.875, 0.826, 0.612),
    (0.673, 0.661, 0.509, 0.934, 0.810, 0.731, 0.751, 0.732, 0.583),
)
# Heat-rate tiers for the gas groups. EFD dispatches each plant group at its own heat rate (UG_HTRT); this LP has one
# combined cycle and one turbine group per region at the capacity-weighted mean. With one group, a combined cycle
# group running part loaded in low-load hours leaves its idle capacity as spinning reserve for free: the energy it
# would give up is made by the same group at the same cost. In EFD the idle combined cycle capacity is the least
# efficient, so committing it for reserve burns gas above the energy price, and turbines at minimum load compete.
# The coal classes (COAL_BY_CONFIGURATION) then carry reserve class by class too. On: TIER_GROUPS' existing capacity in N_TIERS equal-capacity heat-rate tiers per region (heat_rate_tiers), plus
# one tier for capacity beyond the plant file at the new-build heat rate; each tier has its own output, cost and
# spinning reserve (EFD_SPIN_RESERVE). The group's mean heat rate is unchanged. Off: one tier at the mean.
HEAT_RATE_TIERS = True
TIER_GROUPS = ("gas_ct",)     # with gas_cc too, 2030 combined cycle falls another 1.2% under EIA and steam goes 6% over
N_TIERS = 3
EFD_BATTERY_SR = (0.252, 0.206, 0.460, 0.200, 0.232, 0.447, 0.222, 0.289, 0.438)
EFD_NUCLEAR_SR = 0.04
# The load behind EFD's spinning reserve requirement and the maximum-load shapes. ED$LOAD (uefd.f 9179-9227) sets
# SP_RES_RQMT_IN = SR_RQMT_HGHT x LOAD + SR_RQMT_DIFF x (MAX_HGHT - LOAD) with LOAD = UTHGHT, and OPBSLD's DRAT_MAX
# (uefd.f 9769) uses UTHGHT / MAX_SP_LOAD. UTHGHT is LDSM's load: sales grossed up for losses. End-use generators'
# grid sales (BTCOGEN, a fixed column on the load rows), the electric power sector's CHP and imports supply part of
# that load as columns of the LP; they do not lower it. On: the requirement and the shapes are built on that gross
# load, the hourly net load x the case's gross_ratio (demand.gross_load_twh over net_load_twh, so it follows the
# loop's and the capacity LP's load); the balance keeps the net load.
# Off: both on the net load (Codex finding 8).
GROSS_LOAD_HEIGHTS = True
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
    coal_classes: object = None         # coal_supply.CoalClasses (COAL_BY_CONFIGURATION; None: one coal group per region)
    tiers: dict = None                  # group -> (share (25, T), heat rate (25, T)) (HEAT_RATE_TIERS; None: one tier)
    tier_max_cf: dict = None            # tiered group -> (25, T) maximum capacity factor of each tier (None: the group's)
    tier_vom: dict = None               # tiered group -> (25, T) variable O&M of each tier (None: the group's)
    gross_ratio: np.ndarray = None      # (25,) LDSM's load before outside supply over net_load_twh (None: 1)
    tier_outage: dict = None            # tiered group -> (forced outage, planned maintenance), each (25, T) (None: the group's)


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
    tier_hr: dict = None             # tiered group -> (25,) heat rate of its output (HEAT_RATE_TIERS)
    spin_gw: dict = None             # reserve carried (EFD_SPIN_RESERVE): thermal group, battery, pumped, idle, required -> (25, 36, 24) GW
    objective: float = 0.0
    trade_twh: np.ndarray = None                            # (links,) energy sent on each link
    coal_class_twh: np.ndarray = None                       # (pairs,) coal group TWh by region and class (COAL_BY_CONFIGURATION)
    coal_class_price: np.ndarray = None                     # (classes,) delivered coal price in EFD's coal LP, 1987$/MMBtu

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


def _fleet_owner() -> np.ndarray:
    """Plant-file units that belong to the dispatched fleet (FLEET_OWNERS_ONLY): ownership classes 1 to 3."""
    u = plants.load_units()
    return np.isin(u.owner, FLEET_OWNERS) if FLEET_OWNERS_ONLY else np.ones(len(u.owner), dtype=bool)


def _online(year: int) -> np.ndarray:
    """Plant-file units in service in `year` that are in the dispatched fleet."""
    return plants.online(year) & _fleet_owner()


def _capacity_gw(year: int, efd_types) -> np.ndarray:
    """plants.capacity_gw over the dispatched fleet's ownership classes."""
    return plants.capacity_gw(year, efd_types, owners=FLEET_OWNERS if FLEET_OWNERS_ONLY else None)


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
    in_group = np.isin(u.efd_type, list(types)) & _fleet_owner()
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
    on = _online(year) & np.isin(u.efd_type, list(types))
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


_CURVES = {}


def heat_rate_curves() -> dict:
    """emmcntl.txt's coal efficiency curves (udat.f 3845-3900, HR_EFF / HR_LL): {(coal region, ECP code): (load levels,
    efficiencies)}. Within a coal region a configuration without a curve takes the last one listed before it."""
    if not _CURVES:
        from nems_open.paths import INPUT
        lines = (INPUT / "emm" / "emmcntl.txt").read_text(encoding="latin-1").splitlines()
        i = next(k for k, l in enumerate(lines) if l.startswith("#Coal")) + 2
        raw = {}
        for line in lines[i:]:
            t = line.split()
            if int(t[0]) == 0:
                break
            n = int(t[3])
            v = np.array(t[4:4 + 2 * n], dtype=float)
            raw[(int(t[0]), t[1])] = (v[1::2], v[0::2])
        codes = technology.ecp_codes()
        configs = codes[:codes.index(COAL_CONFIG_LAST) + 1]          # B1 .. HC, one UPTTYP
        for rg in sorted({k[0] for k in raw}):
            last = None
            for c in configs:
                last = raw.get((rg, c), last)
                if last is not None:
                    _CURVES[(rg, c)] = last
    return _CURVES


def _efficiency(curve, level: float) -> float:
    """HTRT_ADJUSTMENT's Target_EFF: the curve's efficiency at `level` (its first point below, linear between)."""
    ll, eff = curve
    return float(np.interp(min(level, 1.0), ll, eff))


def part_load_factor(level: float = None) -> np.ndarray:
    """Per plant-file unit, the heat rate at `level` (default PART_LOAD_LEVEL) over THRATE: Target_EFF(T_CF) /
    Target_EFF(level) on the unit's coal region and configuration curve (COAL_PART_LOAD_HEAT_RATE); 1 without one."""
    level = PART_LOAD_LEVEL if level is None else level
    tb = db.table("V_EMM_PLTF860")
    curves = heat_rate_curves()
    keys = zip(np.asarray(tb["T_CLRG"]).astype(int), (str(x).strip() for x in tb["ECPcd"]), np.asarray(tb["T_CF"], dtype=float))
    return np.array([_efficiency(curves[(r, c)], cf) / _efficiency(curves[(r, c)], level) if (r, c) in curves else 1.0
                     for r, c, cf in keys])


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


def build_case(snapshot, year: int, trade: str = "none", capacity: dict = None) -> DispatchCase:
    """Assemble a year's inputs from the reference run's capacity and fuel prices.

    trade="none": regions meet their own net load from sales (demand.net_load_twh).
    trade="reference": each region's net load is the reference run's generation in that
    region, which fixes the interregional exchange at EIA's result.
    capacity: {group: (25,) GW} in place of the reference run's (the capacity LP's fleet, a lever). Everything that
    depends on the fleet's make-up is built on it: the existing / new split behind each group's heat rate and VOM,
    the heat-rate tiers, the new-CC share EPA 111 caps, the cofired units' coal share. The case's capacity is
    `capacity` itself.
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
    if capacity is not None:
        cap.update({g: np.asarray(v, dtype=float) for g, v in capacity.items()})
    u = plants.load_units()
    ptype = {t.code: t for t in technology.efd_plant_types()}
    params = technology.type_parameters()
    codes = technology.ecp_codes()
    hr_new_all = technology.new_heat_rate(year)        # UPHTRT (ucape.f 625-641): UPPHRT0 for every gas type

    heat, vom, oil, avail, new_cap, hr_old, vom_old = {}, {}, {}, {}, {}, {}, {}
    part_load = part_load_factor() if COAL_PART_LOAD_HEAT_RATE else np.ones(len(u.heat_rate))
    for g in THERMAL:
        types = types_of[g]
        existing = _capacity_gw(year, types)[:NUM_R]
        hr_unit = u.heat_rate * part_load if g == "coal" else u.heat_rate
        hr_ex = _weighted(hr_unit, u.summer_mw, types, u.region, year, 10000.0)
        vom_ex = _weighted(u.vom, u.summer_mw, types, u.region, year, 2.0)
        i = codes.index(NEW_TYPE[g])
        hr_new, vom_new = float(hr_new_all[i]), float(params["vom"][i])
        total = np.maximum(cap[g], 1e-9)
        ex_used = np.minimum(existing, total)
        new = np.maximum(total - ex_used, 0.0)
        new_cap[g] = np.where(cap[g] > 0, new, 0.0)
        hr_old[g] = np.asarray(hr_ex, dtype=float) * np.ones(NUM_R)
        vom_old[g] = np.asarray(vom_ex, dtype=float) * np.ones(NUM_R)
        heat[g] = (ex_used * hr_ex + new * hr_new) / total
        if g == "coal":    # the plain coal heat rate, which conversions to cofiring start from
            coal_plain = (ex_used * _weighted(u.heat_rate, u.summer_mw, types, u.region, year, 10000.0) + new * hr_new) / total
        vom[g] = (ex_used * vom_ex + new * vom_new) / total
        if g in OIL_TYPES:
            oil_cap = _capacity_gw(year, OIL_TYPES[g])[:NUM_R]
            oil[g] = np.divide(oil_cap, existing, out=np.zeros(NUM_R), where=existing > 0)
        else:
            oil[g] = np.zeros(NUM_R)
        pt = ptype[AVAIL_TYPE[g]]
        avail[g] = (pt.forced_outage, pt.max_capacity_factor)
    # Coal that captures CO2 burns more fuel per kWh and costs more to run: use the plant file's own
    # with-capture heat rate and variable O&M (T_CCSHR, T_CCSV) for the captured share.
    tb = db.table("V_EMM_PLTF860")
    coal_u = _fleet_owner() & np.isin(u.efd_type, EXISTING_TYPES["coal"]) & (tb["T_CCSHR"] > 0) & (tb["T_CCSHR"] < CCS_HEAT_RATE_MAX)
    ccs_hr = _weighted_mask(tb["T_CCSHR"] * part_load, u.summer_mw, coal_u, u.region, 14000.0)
    ccs_vom = _weighted_mask(tb["T_CCSV"], u.summer_mw, coal_u, u.region, 1.5)
    heat["coal_ccs"] = ccs_hr
    capture_net = _weighted_mask(u.heat_rate / np.where(coal_u, tb["T_CCSHR"], 1.0), u.summer_mw, coal_u, u.region, 0.7)
    vom["coal_ccs"] = vom["coal"] + ccs_vom
    heat["gas_ccs"] = np.full(NUM_R, float(hr_new_all[codes.index("CS")]))
    coal_share = cofire_case(year, cap["cofire"], heat, vom, coal_heat=coal_plain)
    heat["nuclear"] = _weighted(u.heat_rate, u.summer_mw, EXISTING_TYPES["nuclear"], u.region, year, 10400.0)
    tiers = None
    if HEAT_RATE_TIERS:
        tiers = {g: heat_rate_tiers(year, types_of[g], cap[g], float(hr_new_all[codes.index(NEW_TYPE[g])]), heat[g])
                 for g in TIER_GROUPS}

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
        old_fleet = _online(year) & np.isin(u.efd_type, list(types)) & (u.online_year <= BASE_YEAR)
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
    gross = np.divide(demand.gross_load_twh(snapshot, year), nl, out=np.ones(NUM_R), where=nl > 0)
    credit = float(snapshot["TCS45Q/ccs_saline_45q"][y])
    # Oil steam units flagged must-run (plant file T_MRUN at or after the year) burn residual oil at their
    # historical capacity factor whatever it costs, as EFD's minimum-run rows force them to. They leave the
    # dispatchable steam capacity. Coal units list distillate as their second fuel (1% of Btu): ignition fuel.
    on = _online(year)
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
    classes = None
    if COAL_BY_CONFIGURATION:
        from nems_open.emm import coal_supply
        classes = coal_supply.coal_classes(snapshot, year, heat["coal"], vom["coal"])
    max_cf = {g: np.full(NUM_R, avail[g][1]) for g in THERMAL}
    tier_max_cf = tier_vom = tier_outage = None
    if EPA111_NEW_CC_CF:
        from nems_open.emm import capacity as ecp     # imported here: capacity imports this module
        epa = ecp.epa111()
        if epa["switch"] and year >= epa["new_cc_year"]:
            mcf_cc = avail["gas_cc"][1]
            total = np.maximum(cap["gas_cc"], 1e-9)
            new_share = np.clip(new_cap["gas_cc"] / total, 0.0, 1.0)
            hr_new_cc = float(hr_new_all[codes.index(NEW_TYPE["gas_cc"])])
            tiers = dict(tiers or {})
            if GAS_CC_OLD_TIERS:
                tiers["gas_cc"] = heat_rate_tiers(year, types_of["gas_cc"], cap["gas_cc"], hr_new_cc, heat["gas_cc"])
            else:
                tiers["gas_cc"] = (np.stack([1.0 - new_share, new_share], axis=1),
                                   np.stack([hr_old["gas_cc"], np.full(NUM_R, hr_new_cc)], axis=1))
            n_old = tiers["gas_cc"][0].shape[1] - 1
            vom_new_cc = float(params["vom"][codes.index(NEW_TYPE["gas_cc"])])
            tier_max_cf = {"gas_cc": np.column_stack([np.full((NUM_R, n_old), mcf_cc), np.full(NUM_R, min(mcf_cc, epa["new_cc_cf"]))])}
            tier_vom = {"gas_cc": np.column_stack([np.repeat(vom_old["gas_cc"][:, None], n_old, axis=1), np.full(NUM_R, vom_new_cc)])}
            max_cf["gas_cc"] = (1.0 - new_share) * mcf_cc + new_share * min(mcf_cc, epa["new_cc_cf"])
            if EPA111_DERATE:
                f, p = efd_outage_rates()["gas_cc"]
                f_new, p_new = capped_outage_rates(f, p, min(mcf_cc, epa["new_cc_cf"]))
                tier_outage = {"gas_cc": (np.column_stack([np.full((NUM_R, n_old), f), np.full(NUM_R, f_new)]),
                                          np.column_stack([np.full((NUM_R, n_old), p), np.full(NUM_R, p_new)]))}
    if capacity is not None:
        cap.update({g: np.asarray(v, dtype=float) for g, v in capacity.items()})
    return DispatchCase(year, cap, heat, vom, price, oil, avail, max_cf, credit, mcf,
                        profiles, nl, shapes, w, links, 0.0, mr_gw, mr_hr, ignition,
                        credit_share=credit_share(year_end, year, rule), build_profile=build_profiles,
                        coal_share=coal_share, capture_net=capture_net, coal_classes=classes, tiers=tiers,
                        tier_max_cf=tier_max_cf, tier_vom=tier_vom, gross_ratio=gross, tier_outage=tier_outage)


def heat_rate_tiers(year: int, types, total: np.ndarray, hr_new: float, mean_hr: np.ndarray) -> tuple:
    """A group's capacity in heat-rate tiers (HEAT_RATE_TIERS): by region, the existing units online in `year`
    sorted by heat rate and cut into N_TIERS tiers of equal capacity (a unit straddling a cut is split), each at
    its units' capacity-weighted heat rate, plus a last tier for capacity beyond the plant file at `hr_new`.
    Shares of `total` (25,) and heat rates, both (25, N_TIERS + 1); scaled so the capacity-weighted heat rate is
    `mean_hr`, the group's single heat rate."""
    u = plants.load_units()
    on = _online(year) & np.isin(u.efd_type, list(types))
    existing = _capacity_gw(year, types)[:NUM_R]
    T = N_TIERS + 1
    share, hr = np.zeros((NUM_R, T)), np.tile(np.asarray(mean_hr, dtype=float)[:, None], (1, T))
    hr[:, -1] = hr_new
    for r in range(NUM_R):
        tot = max(float(total[r]), 1e-9)
        ex = min(float(existing[r]), tot)
        share[r, -1] = (tot - ex) / tot
        m = on & (u.region == r + 1) & (u.summer_mw > 0)
        if ex <= 0 or not m.any():
            share[r, 0] += ex / tot
            continue
        order = np.argsort(u.heat_rate[m], kind="stable")
        mw, h = u.summer_mw[m][order].astype(float), u.heat_rate[m][order].astype(float)
        edges = np.cumsum(mw) / mw.sum()
        lo = np.concatenate(([0.0], edges[:-1]))
        for k in range(N_TIERS):
            a, b = k / N_TIERS, (k + 1) / N_TIERS
            part = np.clip(np.minimum(edges, b) - np.maximum(lo, a), 0.0, None)
            hr[r, k] = np.average(h, weights=part) if part.sum() > 0 else float(mean_hr[r])
            share[r, k] = ex / tot / N_TIERS
    w = (share * hr).sum(axis=1)
    hr = hr * np.divide(np.asarray(mean_hr, dtype=float), w, out=np.ones(NUM_R), where=w > 0)[:, None]
    return share, hr


def cofire_case(year: int, cap_cofire: np.ndarray, heat: dict, vom: dict, coal_heat: np.ndarray = None) -> dict:
    """Heat rate, variable O&M (set in `heat` and `vom`) and coal share of the cofire group (COFIRE_GROUP).

    The plant file's CTN units keep their own heat rate, variable O&M and coal share (fuel 2 when it is a coal curve,
    capped at UEPA_CGSH from UEPA_GSYR, udat.f 6457). Capacity beyond them is coal EIA converted after the plant file:
    the coal group's heat rate +5% and variable O&M x0.75 (capacity.CONVERT_HR_PENALTY, CONVERT_VOM_ADJ) at UEPA_CGSH
    of coal (uecp.f 28148). After UEPA_CLCFYR no unit cofires coal. coal_heat is the coal heat rate conversions start
    from (default heat["coal"]). Returns {"cofire": (25,) coal share of Btu}."""
    from nems_open.emm import capacity as ecp     # imported here: capacity imports this module
    rule = ecp.epa111()
    u = plants.load_units()
    tb = db.table("V_EMM_PLTF860")
    on = _online(year) & np.isin(u.efd_type, EXISTING_TYPES["cofire"])
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
    coal_heat = heat["coal"] if coal_heat is None else coal_heat
    heat["cofire"] = (ex_used * hr_ex + new * coal_heat * (1.0 + ecp.CONVERT_HR_PENALTY)) / total
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
    capacity.ecp_slice_heights'. Groups: MAX_LOAD_GROUPS, and cofire with COFIRE_MAX_LOAD_SHAPE. Before
    MAX_LOAD_FIRST_YEAR, ones for ECP types up to MAX_LOAD_STEO_LAST (coal)."""
    from nems_open.emm import capacity as ecp
    groups = dict(MAX_LOAD_GROUPS)
    if COFIRE_MAX_LOAD_SHAPE:
        groups["cofire"] = COFIRE_MAX_LOAD_TYPE
    lf = ecp.named_ranges(technology.ECPDATY, "SPNRSV")["SR_MAX_LF"]
    codes = technology.ecp_codes()
    peak = height[:, (np.arange(9) // 3) * 3]
    rel = np.divide(height, peak, out=np.ones_like(height), where=peak > 0).clip(0.0, 1.0)
    rel_h = np.take_along_axis(rel, slice_of.reshape(slice_of.shape[0], -1), axis=1).reshape(slice_of.shape)
    out = {}
    for g, code in groups.items():
        if year < MAX_LOAD_FIRST_YEAR and codes.index(code) <= codes.index(MAX_LOAD_STEO_LAST):
            out[g] = np.ones(slice_of.shape)
            continue
        a = float(lf[codes.index(code)])
        out[g] = a + (1.0 - a) * rel_h
    return out


def efd_mode_shapes(height: np.ndarray, year: int, avail: dict) -> dict:
    """EFD's dispatch modes (EFD_DISPATCH_MODES): per thermal group, (allowed modes L, output per committed GW of each
    shape O, J, U in every slice, (3, 25, 9)). `height` (25, 9) is capacity.ecp_slice_heights' in ECP order,
    `avail` 1 - FOR by group. uefd.f OPBSLD: DRAT, DRAT_MIN, DRAT_MAX; the modes from UPPCFB as in capacity."""
    from nems_open.emm import capacity as ecp
    sp = ecp.named_ranges(technology.ECPDATY, "SPNRSV")
    pcfb = ecp.named_ranges(technology.ECPDATY, "COSTPERF")["UPPCFB"]
    codes = technology.ecp_codes()
    h3 = height.reshape(height.shape[0], 3, 3)
    peak = np.repeat(h3.max(axis=2), 3, axis=1)
    low = np.repeat(h3.min(axis=2), 3, axis=1)
    rel_max = np.divide(height, peak, out=np.ones_like(height), where=peak > 0)
    rel_min = np.divide(height, low, out=np.ones_like(height), where=low > 0)
    fos = np.asarray(FOS_CF_EFD)
    out = {}
    for g in THERMAL:
        i = codes.index(MODE_TYPE[g])
        lo, hi = float(pcfb[2 * i]), float(pcfb[2 * i + 1])
        modes = tuple(L for L in (1, 2, 3) if hi >= ecp.ECP_SLICE_CF[L - 1] and lo <= ecp.ECP_SLICE_CF[L])
        a = float(avail[g])
        min_cf, min_lf, max_lf = (float(sp[k][i]) for k in ("SR_MIN_CF", "SR_MIN_LF", "SR_MAX_LF"))
        o = np.maximum(a * fos, min_cf) if lo > 0.001 else a * rel_max
        j = min_cf * (min_lf + (1.0 - min_lf) * rel_min)
        if year < MAX_LOAD_FIRST_YEAR and codes.index(MODE_TYPE[g]) <= codes.index(MAX_LOAD_STEO_LAST):
            u = np.full_like(height, a)
        else:
            u = a * (max_lf + (1.0 - max_lf) * rel_max)
        out[g] = (modes, np.clip(np.stack([o, j, u]), 0.01, 1.0))
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


def capped_outage_rates(f: float, p: float, max_cf: float) -> tuple:
    """Forced outage and planned maintenance of a unit whose maximum capacity factor is held to `max_cf` (EPA111_DERATE):
    udat.f 10194-10224 with MXLFR 0. The unit's FOR and PMR (f, p, already consistent with the type's WMXCP) move by
    one factor so that (1 - FOR)(1 - PMR) = max_cf; the load-following reduction stays 0."""
    k = np.sqrt(max_cf / ((1.0 - f) * (1.0 - p)))
    if k >= 1.0:
        return f, p
    return 1.0 - k * (1.0 - f), 1.0 - k * (1.0 - p)


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


@lru_cache(maxsize=None)
def _uppcef(code: str) -> float:
    r = named_ranges(technology.ECPDATY, "COSTPERF")["UPPCEF"]
    return float(r[technology.ecp_codes().index(code)])


def capture_rate(g: str) -> float:
    """Share of a capture group's CO2 that is captured (CAPTURE_BY_TYPE)."""
    if not CAPTURE_BY_TYPE:
        return CAPTURE_RATE
    return COAL_RETROFIT_CAPTURE if g == "coal_ccs" else _uppcef(NEW_TYPE[g])


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
    return tons * (1.0 - capture_rate(g)) if g in CAPTURE_GROUPS else tons


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
    # The load EFD's reserve requirement and maximum-load shapes read: UTHGHT, LDSM's load before the supply that
    # comes from outside the dispatched fleet (GROSS_LOAD_HEIGHTS).
    height_np = load_gw.transpose("region", "day", "hour").values
    if GROSS_LOAD_HEIGHTS and case.gross_ratio is not None:
        height_np = height_np * np.asarray(case.gross_ratio, dtype=float)[:, None, None]
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
            load_np = height_np
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
            tons = case.heat_rate[g] / 1000.0 * CO2_PER_TBTU[CAPTURE_GROUPS[g]] * capture_rate(g)
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
    cl = case.coal_classes if COAL_BY_CONFIGURATION else None
    gc = None
    if cl is not None:
        from nems_open.emm import coal_supply
        # The coal group's output is split over its region's classes (region and class pairs P), each with its share
        # of the hourly ceiling, its units' heat rate and VOM. Coal, TBtu = GWh x MMBtu/MWh x 1e-3 less the ignition
        # distillate, is bought in EFD's coal LP at its delivered price, on top of the regional price less the class's
        # (COAL_PRICE_BY_CLASS: the region's) price at EIA's burn (1987$/MMBtu; TBtu x $/MMBtu = 1e6 $ = 1e3 objective
        # units of GWh x $/MWh). Each region's rest pays the regional price. The coal row of cost_da gives way.
        P = pd.Index(np.arange(len(cl.region)), name="coal_pair")
        reg_of = xr.DataArray(cl.region, coords=[P], name="region")
        lp = np.flatnonzero(cl.klass >= 0)
        PL = pd.Index(lp, name="coal_pair")
        base = cl.ref[cl.region - 1] if COAL_PRICE_BY_CLASS else cl.pay[np.maximum(cl.klass, 0)]
        mmbtu = cl.heat_rate / 1000.0
        pc = mmbtu * (case.price["coal"][cl.region - 1] - np.where(cl.klass >= 0, base, 0.0)) + cl.vom \
            + case.carbon_price * mmbtu * CO2_PER_TBTU["coal"]
        up = upper.sel(group="coal", drop=True).sel(region=reg_of) * xr.DataArray(cl.share, coords=[P])
        gc = m.add_variables(lower=0, upper=up.transpose("coal_pair", "day", "hour"), name="coal_class_gen")
        m.add_constraints(g_th.sel(group="coal", drop=True) - gc.groupby(reg_of).sum() == 0, name="coal_classes")
        objective = objective - (g_th.sel(group="coal", drop=True) * cost_da.sel(group="coal", drop=True) * w).sum() \
            + (gc * xr.DataArray(pc, coords=[P]) * w).sum()
        burn = (gc.sel(coal_pair=PL) * w).sum(["day", "hour"]) * xr.DataArray(mmbtu[lp] * (1.0 - case.ignition_share) * 1e-3, coords=[PL])
        # EFD's coal LP: supply steps per curve, deliveries per route, demand per class, the diversity caps.
        C = pd.Index(np.arange(len(cl.curves)), name="coal_curve")
        S = pd.Index(np.arange(12), name="coal_step")
        RT = pd.Index(np.arange(len(cl.route_curve)), name="coal_route")
        steps = m.add_variables(lower=0, upper=xr.DataArray(cl.step_qty, coords=[C, S]), name="coal_steps")
        tr = m.add_variables(lower=0, coords=[RT], name="coal_routes")
        k_of_route = xr.DataArray(cl.route_class, coords=[RT], name="coal_class")
        k_of_pair = xr.DataArray(cl.klass[lp], coords=[PL], name="coal_class")
        demand_row = m.add_constraints(tr.groupby(k_of_route).sum() - burn.groupby(k_of_pair).sum() == 0, name="coal_class_demand")
        used = np.unique(cl.route_curve)
        c_of_route = xr.DataArray(cl.route_curve, coords=[RT], name="coal_curve")
        m.add_constraints(tr.groupby(c_of_route).sum() - steps.sel(coal_curve=used).sum("coal_step")
                          <= xr.DataArray(-cl.other[used], coords=[pd.Index(used, name="coal_curve")]), name="coal_curve_supply")
        objective = objective + (steps * xr.DataArray(cl.step_price * 1000.0, coords=[C, S])).sum() \
            + (tr * xr.DataArray(cl.route_cost * 1000.0, coords=[RT])).sum()
        for rank, cap, name in ((2, cl.sub_cap, "sub"), (3, cl.lig_cap, "lig")):
            idx = np.flatnonzero(cl.route_rank == rank)
            if not len(idx):
                continue
            ks = np.unique(cl.route_class[idx])
            K = pd.Index(ks, name="coal_class")
            dx = m.add_variables(lower=0, coords=[K], name=f"coal_{name}_escape")
            grp = xr.DataArray(cl.route_class[idx], coords=[pd.Index(idx, name="coal_route")], name="coal_class")
            m.add_constraints(tr.sel(coal_route=idx).groupby(grp).sum() - dx <= xr.DataArray(cap[ks], coords=[K]), name=f"coal_{name}_cap")
            objective = objective + (dx * (coal_supply.ESCAPE * 1000.0)).sum()
    tier_vars, tier_com = {}, {}
    if case.tiers is not None:
        for g, (share, hr_t) in case.tiers.items():
            k = THERMAL.index(g)
            TI = pd.Index(np.arange(share.shape[1]), name="tier")
            hr_g = np.asarray(case.heat_rate[g], dtype=float)
            per_mmbtu = np.divide(cost[:, k] - case.vom[g], hr_g / 1000.0, out=np.zeros(NUM_R), where=hr_g > 0)  # fuel + carbon
            vom_t = case.tier_vom[g] if case.tier_vom is not None and g in case.tier_vom else case.vom[g][:, None]
            ct = vom_t + hr_t / 1000.0 * per_mmbtu[:, None]                                                      # (25, T)
            up = upper.sel(group=g, drop=True) * xr.DataArray(share, coords=[R, TI])
            com_fac = None
            if case.tier_outage is not None and g in case.tier_outage:
                # a tier with its own FOR and PMR (EPA111_DERATE): ceiling and committable capacity relative to the group's
                f_t, p_t = case.tier_outage[g]
                f_g = rates[g][0] if EFD_DERATE else case.avail[g][0]
                if EFD_DERATE:
                    p_g = rates[g][1]
                    s_ = season[:, None, :, None]                                                     # (25, 1, 36, 1)
                    keep_g = np.clip(1.0 - p_g * s_, 1e-9, 1.0)
                    keep_t = np.clip(1.0 - p_t[:, :, None, None] * s_, 0.0, 1.0)
                    com_fac = keep_t / keep_g * np.ones(nh)
                else:
                    com_fac = np.ones((NUM_R, share.shape[1], 36, nh))
                fac = com_fac * ((1.0 - f_t) / (1.0 - f_g))[:, :, None, None]
                up = up * xr.DataArray(fac, coords=[R, TI, D, H])
                com_fac = xr.DataArray(com_fac, coords=[R, TI, D, H])
            gt = m.add_variables(lower=0, upper=up.transpose("region", "tier", "day", "hour"), name=f"tier_gen_{g}")
            m.add_constraints(g_th.sel(group=g, drop=True) - gt.sum("tier") == 0, name=f"tiers_{g}")
            if case.tier_max_cf is not None and g in case.tier_max_cf:
                lim = capg[g][:, None] * share * case.tier_max_cf[g] * HOURS_PER_YEAR      # GWh
                m.add_constraints((gt * w).sum(["day", "hour"]) <= xr.DataArray(lim, coords=[R, TI]), name=f"tier_energy_{g}")
            objective = objective - (g_th.sel(group=g, drop=True) * cost_da.sel(group=g, drop=True) * w).sum()                 + (gt * xr.DataArray(ct, coords=[R, TI]) * w).sum()
            tier_vars[g] = (gt, TI, share, hr_t)
            tier_com[g] = com_fac
    spin = spin_row = None
    modes_on = EFD_SPIN_RESERVE and EFD_DISPATCH_MODES and EFD_DERATE
    if modes_on:
        from nems_open.emm import capacity as ecp
        mins = ecp.spin_min_cf()
        intermittent = (ren_gw["wind"] + ren_gw["solar"]).transpose("region", "day", "hour")
        load_np = height_np
        slice_of, height = ecp.ecp_slice_heights(load_np, case.weights, month_of_day, load_np - intermittent.values)
        peak = height[:, (np.arange(9) // 3) * 3]
        req = ecp.SR_RQMT_HGHT * height + ecp.SR_RQMT_DIFF * (peak - height)                  # (25, 9) GW
        hw = np.broadcast_to((case.weights * hp)[None, :, None], slice_of.shape)
        K = pd.Index(np.arange(9), name="slice")
        onehot = np.stack([(slice_of == k) * hw for k in range(9)], axis=1)                     # (25, 9, 36, nh) hours
        width = onehot.sum(axis=(2, 3))                                                          # (25, 9)
        avg = xr.DataArray(np.divide(onehot, width[:, :, None, None], out=np.zeros_like(onehot),
                                     where=width[:, :, None, None] > 0), coords=[R, K, D, H])     # slice average weights
        shapes = efd_mode_shapes(height, case.year, {g: avail[k] for k, g in enumerate(THERMAL)})
        S = pd.Index(np.arange(3), name="season")                  # ECP seasons: winter, summer, shoulder
        SH = pd.Index(["O", "J", "U"], name="shape")
        LM = pd.Index([1, 2, 3], name="mode")
        ok = np.zeros((len(THERMAL), 3, 3, 3))
        for k, g in enumerate(THERMAL):
            for L_ in shapes[g][0]:
                ok[k, :, :, L_ - 1] = np.inf
        season_of_day = ecp.ecp_season_of_month()[month_of_day]
        cap_s = np.stack([committable.values[:, :, season_of_day == s, 0].max(axis=2) for s in range(3)], axis=2)  # (25, groups, 3)
        commit = m.add_variables(lower=0, upper=xr.DataArray(np.broadcast_to(ok, (NUM_R,) + ok.shape).copy(), coords=[R, TH, S, SH, LM]),
                                 name="commit")
        m.add_constraints(commit.sum(["shape", "mode"]) <= xr.DataArray(cap_s, coords=[R, TH, S]), name="commit_capacity")
        # slice k: season 2 - k // 3, rank k % 3 (0 peak); the modes reaching it are L >= rank + 1
        sea = np.array([2 - k // 3 for k in range(9)])
        reach = np.array([[1.0 if L_ >= k % 3 + 1 else 0.0 for L_ in (1, 2, 3)] for k in range(9)])     # (9, 3)
        sel_season = xr.DataArray(np.eye(3)[sea], coords=[K, S])
        reach_da = xr.DataArray(reach, coords=[K, LM])
        shape_np = np.stack([shapes[g][1] for g in THERMAL], axis=1)                                     # (3, groups, 25, 9)
        shape_da = xr.DataArray(shape_np.transpose(2, 1, 0, 3), coords=[R, TH, SH, K])
        committed = m.add_variables(lower=0, coords=[R, TH, K], name="committed")                        # GW by slice
        out_k = m.add_variables(lower=0, coords=[R, TH, K], name="mode_output")                          # GW, slice average
        for k in range(9):
            ck = commit.sel(season=sea[k], mode=[L_ for L_ in (1, 2, 3) if reach[k, L_ - 1] > 0])
            m.add_constraints(committed.sel(slice=k) - ck.sum(["shape", "mode"]) == 0, name=f"committed_{k}")
            m.add_constraints(out_k.sel(slice=k) - (ck * shape_da.sel(slice=k)).sum(["shape", "mode"]) == 0, name=f"mode_output_{k}")
        up_np = upper.transpose("region", "group", "day", "hour").values
        cm_np = committable.transpose("region", "group", "day", "hour").values
        frac = xr.DataArray(np.divide(up_np, cm_np, out=np.zeros_like(up_np), where=cm_np > 0), coords=[R, TH, D, H])
        for k in range(9):
            mask = xr.DataArray(slice_of == k, coords=[R, D, H])
            m.add_constraints((g_th * avg.sel(slice=k)).sum(["day", "hour"]) - out_k.sel(slice=k) == 0, name=f"mode_energy_{k}")
            m.add_constraints(g_th - committed.sel(slice=k) * frac <= 0, name=f"mode_hourly_{k}", mask=mask)
        for g, (gt, TI, share, _) in tier_vars.items():
            # a tiered group commits tier by tier, each on its own capacity, at the group's shapes
            j = THERMAL.index(g)
            okt = np.broadcast_to(ok[j], (NUM_R, len(TI)) + ok[j].shape).copy()
            ct_ = m.add_variables(lower=0, upper=xr.DataArray(okt, coords=[R, TI, S, SH, LM]), name=f"commit_{g}")
            m.add_constraints(ct_.sum(["shape", "mode"]) <= xr.DataArray(cap_s[:, j, None, :] * share[:, :, None], coords=[R, TI, S]),
                              name=f"commit_capacity_{g}")
            cmt = m.add_variables(lower=0, coords=[R, TI, K], name=f"committed_{g}")
            outt = m.add_variables(lower=0, coords=[R, TI, K], name=f"mode_output_{g}")
            sh_g = shape_da.sel(group=g, drop=True)
            fr_g = frac.sel(group=g, drop=True)
            for k in range(9):
                ck = ct_.sel(season=sea[k], mode=[L_ for L_ in (1, 2, 3) if reach[k, L_ - 1] > 0])
                m.add_constraints(cmt.sel(slice=k) - ck.sum(["shape", "mode"]) == 0, name=f"committed_{g}_{k}")
                m.add_constraints(outt.sel(slice=k) - (ck * sh_g.sel(slice=k)).sum(["shape", "mode"]) == 0, name=f"mode_output_{g}_{k}")
                mask = xr.DataArray(slice_of == k, coords=[R, D, H])
                m.add_constraints((gt * avg.sel(slice=k)).sum(["day", "hour"]) - outt.sel(slice=k) == 0, name=f"mode_energy_{g}_{k}")
                m.add_constraints(gt - cmt.sel(slice=k) * fr_g <= 0, name=f"mode_hourly_{g}_{k}", mask=mask)
            m.add_constraints(committed.sel(group=g, drop=True) - cmt.sum("tier") == 0, name=f"committed_tiers_{g}")
            m.add_constraints(out_k.sel(group=g, drop=True) - outt.sum("tier") == 0, name=f"mode_output_tiers_{g}")
        c, di, soc = spin_sto["pumped"]
        ss = m.add_variables(lower=0, coords=[R, D, H], name="spin_pumped")
        m.add_constraints(ss + di - c <= 0, name="spin_pumped_headroom")
        m.add_constraints(ss - di * (1.0 / mins["pumped"] - 1.0) <= 0, name="spin_pumped_committed")
        battery_sr = xr.DataArray(np.asarray(EFD_BATTERY_SR)[slice_of] * case.capacity["battery"][:, None, None], coords=[R, D, H])
        idle = (by_region(case.capacity["nuclear"]) * EFD_NUCLEAR_SR + by_region(case.capacity["other"]) - ren_gw["other"]
                + battery_sr)
        thermal_sr = (committed - out_k).sum("group")
        short = m.add_variables(lower=0, coords=[R, K], name="spin_shortfall")
        rhs = xr.DataArray(req, coords=[R, K]) + ((ecp.SR_INT * intermittent - idle) * avg).sum(["day", "hour"])
        spin_row = m.add_constraints(thermal_sr + (ss * avg).sum(["day", "hour"]) + short >= rhs, name="spin_reserve")
        objective = objective + (short * xr.DataArray(SPIN_SHORTFALL_COST * width, coords=[R, K])).sum()
    elif EFD_SPIN_RESERVE:
        from nems_open.emm import capacity as ecp     # imported here: capacity imports this module
        mins = ecp.spin_min_cf()
        inv = xr.DataArray(np.array([1.0 / mins[g] - 1.0 for g in THERMAL]), coords=[TH])
        spin = m.add_variables(lower=0, coords=[R, TH, D, H], name="spin")
        m.add_constraints(spin + g_th - committable <= 0, name="spin_headroom")
        m.add_constraints(spin - g_th * inv <= 0, name="spin_committed")
        supply = spin.sum("group")
        for g, (gt, TI, share, _) in tier_vars.items():
            # each tier carries reserve only on its own running capacity
            st = m.add_variables(lower=0, coords=[R, TI, D, H], name=f"tier_spin_{g}")
            com_g = committable.sel(group=g, drop=True) * xr.DataArray(share, coords=[R, TI])
            if tier_com.get(g) is not None:
                com_g = com_g * tier_com[g]
            m.add_constraints(st + gt - com_g <= 0, name=f"tier_spin_headroom_{g}")
            m.add_constraints(st - gt * float(inv.sel(group=g)) <= 0, name=f"tier_spin_committed_{g}")
            m.add_constraints(spin.sel(group=g, drop=True) - st.sum("tier") <= 0, name=f"tier_spin_{g}")
        if case.tiers is not None and gc is not None:
            # the coal classes are tiers too: each carries reserve only on its own running capacity
            com_c = committable.sel(group="coal", drop=True).sel(region=reg_of) * xr.DataArray(cl.share, coords=[P])
            sc = m.add_variables(lower=0, coords=[P, D, H], name="class_spin")
            m.add_constraints(sc + gc - com_c.transpose("coal_pair", "day", "hour") <= 0, name="class_spin_headroom")
            m.add_constraints(sc - gc * float(inv.sel(group="coal")) <= 0, name="class_spin_committed")
            m.add_constraints(spin.sel(group="coal", drop=True) - sc.groupby(reg_of).sum() <= 0, name="class_spin")
        c, di, soc = spin_sto["pumped"]
        ss = m.add_variables(lower=0, coords=[R, D, H], name="spin_pumped")
        m.add_constraints(ss + di - c <= 0, name="spin_pumped_headroom")
        m.add_constraints(ss - di * (1.0 / mins["pumped"] - 1.0) <= 0, name="spin_pumped_committed")
        supply = supply + ss
        intermittent = (ren_gw["wind"] + ren_gw["solar"]).transpose("region", "day", "hour")
        load_np = height_np
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
    coal_hr = case.heat_rate["coal"]
    if gc is not None:
        e = (gc.solution.transpose("coal_pair", "day", "hour").values * wd[0]).sum(axis=(1, 2)) / 1000.0
        res.coal_class_twh = e
        dual = demand_row.dual
        res.coal_class_price = np.full(len(cl.classes), np.nan)
        res.coal_class_price[dual["coal_class"].values] = dual.values / 1000.0
        fuel_r = np.bincount(cl.region - 1, weights=e * cl.heat_rate, minlength=NUM_R)
        coal_hr = np.divide(fuel_r, gen["coal"], out=np.asarray(case.heat_rate["coal"], dtype=float).copy(), where=gen["coal"] > 1e-9)
    tier_hr = {}
    for g, (gt, TI, share, hr_t) in tier_vars.items():
        e = (gt.solution.transpose("region", "tier", "day", "hour").values * wd[:, None]).sum(axis=(2, 3)) / 1000.0
        tier_hr[g] = np.divide((e * hr_t).sum(axis=1), gen[g], out=np.asarray(case.heat_rate[g], dtype=float).copy(), where=gen[g] > 1e-9)
    res.tier_hr = tier_hr
    for g in THERMAL:
        btu = gen[g] * (coal_hr if g == "coal" else tier_hr.get(g, case.heat_rate[g])) * 1e-3
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
        co2 = co2 - capture_rate(g) * gen[g] * case.heat_rate[g] * 1e-3 * CO2_PER_TBTU[fuel_key]
    res.co2_mt = co2
    res.price = bal.dual.transpose("region", "day", "hour").values / np.maximum(wd, 1e-9)
    if spin_row is not None and modes_on:
        price_k = spin_row.dual.transpose("region", "slice").values / np.maximum(width, 1e-9)            # 1987$/MWh
        res.spin_price = np.take_along_axis(price_k, slice_of.reshape(NUM_R, -1), axis=1).reshape(slice_of.shape)
        on_hours = lambda a: np.take_along_axis(a, slice_of.reshape(NUM_R, -1), axis=1).reshape(slice_of.shape)
        cm = committed.solution.transpose("region", "group", "slice").values
        ok_ = out_k.solution.transpose("region", "group", "slice").values
        res.spin_gw = {g: on_hours(cm[:, k] - ok_[:, k]) for k, g in enumerate(THERMAL)}
        res.spin_gw["pumped"] = m.variables["spin_pumped"].solution.transpose("region", "day", "hour").values
        res.spin_gw["idle"] = idle.transpose("region", "day", "hour").values
        res.spin_gw["required"] = on_hours(req) + (ecp.SR_INT * intermittent).transpose("region", "day", "hour").values
        res.spin_gw["shortfall"] = on_hours(short.solution.transpose("region", "slice").values)
    elif spin_row is not None:
        res.spin_price = spin_row.dual.transpose("region", "day", "hour").values / np.maximum(wd, 1e-9)
        sp = spin.solution.transpose("region", "group", "day", "hour").values
        res.spin_gw = {g: sp[:, k] for k, g in enumerate(THERMAL)}
        res.spin_gw["pumped"] = m.variables["spin_pumped"].solution.transpose("region", "day", "hour").values
        res.spin_gw["idle"] = idle.transpose("region", "day", "hour").values
        res.spin_gw["required"] = spin_row.rhs.transpose("region", "day", "hour").values + res.spin_gw["idle"]
    res.objective = float(m.objective.value)
    return res
