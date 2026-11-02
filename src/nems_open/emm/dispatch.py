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
THERMAL = ("coal", "coal_ccs", "gas_cc", "gas_ccs", "gas_ct", "steam")
RENEWABLE = ("wind", "solar", "other")
GROUPS = THERMAL + ("nuclear", "hydro") + RENEWABLE + ("battery", "pumped")

# Restart capacity arrays (UDATOUT/UCAP<prefix><u|n>) that make up each group.
CAPACITY_PREFIXES = {
    "coal": ("cs", "ig", "pq", "is", "oc"),   # less coal_ccs: sq (retrofits) is a subset of cs, not extra capacity
    "coal_ccs": ("sq",),
    "gas_cc": ("cc", "ac", "a2", "fc"),
    "gas_ccs": ("as",),
    "gas_ct": ("ct", "at", "ic", "t2", "i2"),
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
    "nuclear": ("CNU", "ANC", "SMR"),
    "hydro": ("HYC", "HYA", "HYI", "HYT"),
    "wind": ("WND", "WNL", "WFS"),
    "solar": ("SPV", "PVT", "STH", "STS", "ST2"),
    "other": ("GTH", "AGT", "BMS", "BIG", "MSW"),
}
OIL_TYPES = {"steam": ("STO",), "gas_ct": ("CTO",)}
# New-plant heat rate (Btu/kWh) and variable O&M come from these ECP types.
NEW_TYPE = {"coal": "PC", "coal_ccs": "PC", "gas_cc": "AC", "gas_ccs": "CS", "gas_ct": "AT", "steam": "ST"}
# Forced outage and maximum capacity factor come from these EFD plant types in pltdata.txt.
AVAIL_TYPE = {"coal": "CSC", "coal_ccs": "CSC", "gas_cc": "CCG", "gas_ccs": "CCG", "gas_ct": "CTG", "steam": "STG"}

# Carbon capture: groups that capture CO2 (and the fuel they burn), the share captured, and the 45Q credit.
CAPTURE_GROUPS = {"coal_ccs": "coal", "gas_ccs": "gas"}
CAPTURE_RATE = 0.9

# Storage: (duration in hours, round-trip efficiency)
STORAGE = {"battery": (4.0, 0.85), "pumped": (12.0, 0.78)}

# Emission factors, million metric tons CO2 per trillion Btu.
CO2_PER_TBTU = {"coal": 0.0953, "gas": 0.05307, "distillate": 0.07316, "residual": 0.0751}

CCS_HEAT_RATE_MAX = 20000.0  # Btu/kWh; with-capture heat rates above this in the plant file are data outliers
UNSERVED_COST = 1000.0       # 1987$/MWh
HOURS_PER_YEAR = 8760.0


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
    credit_45q: float         # 1987$ per metric ton of CO2 captured
    monthly_cf: dict          # nuclear, hydro, other -> (25, 12)
    profile: dict             # wind, solar -> (25, 36, 24) capacity factor in each typical hour
    net_load_twh: np.ndarray  # (25,)
    shapes: np.ndarray        # (25, 36, 24) share of annual energy per typical hour
    weights: np.ndarray       # (36,) days per typical day
    links: dict = None        # exporter, importer (0-based), capacity_gw (L, 36), cost (L,) 1987$/MWh, loss


@dataclass
class DispatchResult:
    year: int
    case: DispatchCase
    status: str
    generation_twh: dict = field(default_factory=dict)      # group -> (25,)
    fuel_tbtu: dict = field(default_factory=dict)           # coal, gas, distillate, residual, uranium -> (25,)
    co2_mt: np.ndarray = None                               # (25,)
    unserved_twh: np.ndarray = None                         # (25,)
    spilled_twh: np.ndarray = None                          # (25,)
    price: np.ndarray = None                                # (25, 36, 24) 1987$/MWh
    objective: float = 0.0
    trade_twh: np.ndarray = None                            # (links,) energy sent on each link

    def total_generation_twh(self) -> float:
        return float(sum(v.sum() for v in self.generation_twh.values()))

    def average_price(self) -> np.ndarray:
        """Load-weighted marginal cost by region, 1987$/MWh."""
        w = self.case.weights[None, :, None] * self.case.shapes
        return (self.price * w).sum(axis=(1, 2)) / w.sum(axis=(1, 2))


def _ucap_mid(snapshot, prefixes, y) -> np.ndarray:
    """Capacity in service on average through the year: the mean of last year's and this year's year-end
    capacity, which assumes builds and retirements are spread evenly through the year."""
    return 0.5 * (_ucap(snapshot, prefixes, y) + _ucap(snapshot, prefixes, y - 1))


def _in_service(snapshot, prefixes, types, year) -> np.ndarray:
    """Capacity in service on average through the year, using the plant file's in-service and retirement months.

    Start from last year's year-end capacity. Add each planned unit for the part of the year after its
    in-service month and take off each retiring unit for the part after its retirement month. What the
    restart shows beyond that (builds EMM chose itself, which have no date) is assumed to arrive mid-year.
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
    return np.maximum(start + add_avg - ret_avg + 0.5 * undated, 0.0)


def _ucap(snapshot, prefixes, y) -> np.ndarray:
    total = np.zeros(NUM_R)
    for p in prefixes:
        for o in ("u", "n"):
            try:
                total += np.nan_to_num(snapshot[f"UDATOUT/ucap{p}{o}"][:NUM_R, y].astype(float))
            except KeyError:
                pass
    return total


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


def build_case(snapshot, year: int, trade: str = "none") -> DispatchCase:
    """Assemble a year's inputs from the reference run's capacity and fuel prices.

    trade="none": regions meet their own net load from sales (demand.net_load_twh).
    trade="reference": each region's net load is the reference run's generation in that
    region, which fixes the interregional exchange at EIA's result.
    """
    y = year - history.FIRST_YEAR
    cap = {g: _in_service(snapshot, p, EXISTING_TYPES.get(g), year) for g, p in CAPACITY_PREFIXES.items()}
    cap["coal"] = np.maximum(cap["coal"] - cap["coal_ccs"], 0.0)
    u = plants.load_units()
    ptype = {t.code: t for t in technology.efd_plant_types()}
    params = technology.type_parameters()
    codes = technology.ecp_codes()
    hr_new_all = np.array(named_ranges(technology.ECPDATY, "OPTLRN")["UPPHRTN"])

    heat, vom, oil, avail = {}, {}, {}, {}
    for g in THERMAL:
        types = EXISTING_TYPES[g]
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
    vom["coal_ccs"] = vom["coal"] + ccs_vom
    heat["gas_ccs"] = np.full(NUM_R, float(hr_new_all[codes.index("CS")]))
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
    profiles = {}
    for group, parts in WRENEW_PROFILES.items():
        caps = [_in_service(snapshot, (prefix,), (code,), year) for prefix, _, code in parts]
        outage = [snapshot["UEFDOUT/up_xfor"][efd_index[code], :NUM_R, y].astype(float) for _, _, code in parts]
        cfs = [_wrenew_profile(snapshot, key, y) * (1.0 - o)[:, None, None] for (_, key, _), o in zip(parts, outage)]
        total = np.maximum(sum(caps), 1e-9)
        profiles[group] = sum(c[:, None, None] * f for c, f in zip(caps, cfs)) / total[:, None, None]
        cap[group] = sum(caps)

    shapes = load.regional_shapes().reshape(NUM_R, 36, 24)
    w = load.day_weights().reshape(36).astype(float)
    nl = demand.net_load_twh(snapshot, year)
    if trade == "reference":
        nl = snapshot["UEFDOUT/ugntlnr"][:, :NUM_R, y].sum(axis=0).astype(float)
    links = build_links(snapshot, year) if trade != "reference" else None
    credit = float(snapshot["TCS45Q/ccs_saline_45q"][y])
    return DispatchCase(year, cap, heat, vom, price, oil, avail, {g: np.full(NUM_R, avail[g][1]) for g in THERMAL}, credit, mcf, profiles, nl, shapes, w, links)


def solve(case: DispatchCase, solver: str = "highs", progress: bool = False) -> DispatchResult:
    R = pd.Index(np.arange(1, NUM_R + 1), name="region")
    D = pd.Index(np.arange(36), name="day")
    H = pd.Index(np.arange(24), name="hour")
    TH = pd.Index(list(THERMAL), name="group")
    MO = pd.Index(np.arange(12), name="month")
    month_of_day = np.repeat(np.arange(12), 3)
    w = xr.DataArray(case.weights, coords=[D])
    ones = xr.DataArray(np.ones((NUM_R, 36, 24)), coords=[R, D, H])

    def by_region(a):
        return xr.DataArray(np.asarray(a, dtype=float), coords=[R]) * ones

    load_gw = xr.DataArray(case.net_load_twh[:, None, None] * 1000.0 * case.shapes, coords=[R, D, H])
    m = linopy.Model()

    # Thermal plants
    cap_th = xr.DataArray(np.stack([case.capacity[g] * (1 - case.avail[g][0]) for g in THERMAL], axis=1), coords=[R, TH])
    upper = (cap_th * ones).transpose("region", "group", "day", "hour")
    g_th = m.add_variables(lower=0, upper=upper, name="gen_thermal")
    e_lim_np = np.stack([case.capacity[g] * case.max_cf[g] * HOURS_PER_YEAR for g in THERMAL], axis=1)    # GWh
    e_lim = xr.DataArray(e_lim_np, coords=[R, TH])
    energy_out = (g_th * w).sum(["day", "hour"])
    m.add_constraints(energy_out <= e_lim, name="thermal_energy")
    cost = np.zeros((NUM_R, len(THERMAL)))
    for k, g in enumerate(THERMAL):
        oil_price = case.price["residual"] if g == "steam" else case.price["distillate"]
        is_coal = g.startswith("coal")
        fuel = (1 - case.oil_share[g]) * case.price["coal" if is_coal else "gas"] + case.oil_share[g] * oil_price
        cost[:, k] = case.heat_rate[g] / 1000.0 * fuel + case.vom[g]
        if g in CAPTURE_GROUPS:
            # 45Q pays per ton captured; tons per MWh = MMBtu per MWh x tons of CO2 per MMBtu.
            tons = case.heat_rate[g] / 1000.0 * CO2_PER_TBTU[CAPTURE_GROUPS[g]] * CAPTURE_RATE
            cost[:, k] -= case.credit_45q * tons
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

    # Hydro within a monthly energy budget
    g_hy = m.add_variables(lower=0, upper=by_region(case.capacity["hydro"]), name="gen_hydro")
    month_w = xr.DataArray(np.eye(12)[month_of_day], coords=[D, MO])
    days_in_month = np.array([case.weights[month_of_day == mo].sum() for mo in range(12)])
    budget = xr.DataArray(case.monthly_cf["hydro"] * case.capacity["hydro"][:, None] * days_in_month[None, :] * 24.0, coords=[R, MO])
    m.add_constraints((g_hy * (w * month_w)).sum(["day", "hour"]) <= budget, name="hydro_budget")

    # Storage, cyclic inside each typical day
    net_storage = 0
    sto = {}
    for name, (dur, rte) in STORAGE.items():
        c = by_region(case.capacity[name])
        eta = np.sqrt(rte)
        ch = m.add_variables(lower=0, upper=c, name=f"{name}_charge")
        di = m.add_variables(lower=0, upper=c, name=f"{name}_discharge")
        soc = m.add_variables(lower=0, upper=c * dur, name=f"{name}_soc")
        m.add_constraints(soc - soc.roll(hour=1) - eta * ch + di / eta == 0, name=f"{name}_balance")
        net_storage = net_storage + di - ch
        sto[name] = (ch, di)

    trade_in = trade_out = 0
    trade = None
    if case.links is not None:
        L = pd.Index(np.arange(len(case.links["exporter"])), name="link")
        cap_l = xr.DataArray(case.links["capacity_gw"], coords=[L, D]) * xr.DataArray(np.ones(24), coords=[H])
        trade = m.add_variables(lower=0, upper=cap_l.transpose("link", "day", "hour"), name="trade")
        into = np.zeros((NUM_R, len(L)))
        outof = np.zeros((NUM_R, len(L)))
        into[case.links["importer"], np.arange(len(L))] = 1.0 - case.links["loss"]
        outof[case.links["exporter"], np.arange(len(L))] = 1.0
        trade_in = (trade * xr.DataArray(into, coords=[R, L])).sum("link")
        trade_out = (trade * xr.DataArray(outof, coords=[R, L])).sum("link")
    spill = m.add_variables(lower=0, coords=[R, D, H], name="spill")
    unserved = m.add_variables(lower=0, coords=[R, D, H], name="unserved")
    bal = m.add_constraints(g_th.sum("group") + g_hy + net_storage + unserved - spill + trade_in - trade_out == load_gw - fixed, name="balance")

    objective = (g_th * cost_da * w).sum() + (g_hy * w).sum() * 0.01 + (unserved * (UNSERVED_COST * w)).sum()
    if trade is not None:
        objective = objective + (trade * (xr.DataArray(case.links["cost"], coords=[L]) * w)).sum()
    m.add_objective(objective)
    status, cond = m.solve(solver_name=solver, progress=progress)

    res = DispatchResult(year=case.year, case=case, status=f"{status}:{cond}")
    if status != "ok":
        return res
    wd = case.weights[None, :, None]
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
    res.generation_twh = gen
    if trade is not None:
        flow = trade.solution.transpose("link", "day", "hour").values
        res.trade_twh = (flow * case.weights[None, :, None]).sum(axis=(1, 2)) / 1000.0
    res.spilled_twh = spilled
    res.unserved_twh = energy(unserved.solution.transpose("region", "day", "hour").values)

    # TWh x Btu/kWh = 1e9 Btu = 1e-3 trillion Btu
    fuel = {k: np.zeros(NUM_R) for k in ("coal", "gas", "distillate", "residual", "uranium")}
    for g in THERMAL:
        btu = gen[g] * case.heat_rate[g] * 1e-3
        if g.startswith("coal"):
            fuel["coal"] += btu
        else:
            o = case.oil_share[g]
            fuel["gas"] += btu * (1 - o)
            fuel["residual" if g == "steam" else "distillate"] += btu * o
    fuel["uranium"] = gen["nuclear"] * case.heat_rate["nuclear"] * 1e-3
    res.fuel_tbtu = fuel
    co2 = sum(fuel[k] * CO2_PER_TBTU[k] for k in CO2_PER_TBTU)
    # Capture groups release only (1 - rate) of their CO2.
    for g, fuel_key in CAPTURE_GROUPS.items():
        co2 = co2 - CAPTURE_RATE * gen[g] * case.heat_rate[g] * 1e-3 * CO2_PER_TBTU[fuel_key]
    res.co2_mt = co2
    res.price = bal.dual.transpose("region", "day", "hour").values / np.maximum(wd, 1e-9)
    res.objective = float(m.objective.value)
    return res
