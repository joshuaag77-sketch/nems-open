"""Capacity credit of wind and solar (ECP's EPIRCCR) and the net peak (EP_NET_PEAK), region by region.

A port of CAP_CREDIT (uecp.f 40065). For each region:

1. Net load in each of the 864 typical hours (12 months x 3 day types x 24 hours, the same 36 days by 24
   hours the dispatch case carries) is system load less intermittent capacity times its hourly capacity
   factor.
2. Hours are taken in falling net load while the weight (net / max net) ** 5 is at least 0.9, that is
   while net load is within about 2% of its maximum. Each counts with that weight times the days it
   stands for (IDAYTQ).
3. In each such hour the reliable capacity of the fleet is its expected output less UPINTZ (3.19)
   standard deviations. Conventional type j: expected cap(1 - FOR), variance cap^2 FOR(1 - FOR) / N,
   N = cap / unit size (UPMSSIZ). Intermittent type i: expected cap x CF; its own variance is
   ((1 - rho) N + rho N^2)(sigma x size)^2 but capped at (cap x CF / z)^2; seen by the other types its
   variance is cap^2 CF(1 - CF) / N.
   Credit of i in that hour = [reliable(all) - reliable(all but i)] / cap_i
                            = [cap_i CF_i - z (sqrt(V_i + V) - sqrt(V))] / cap_i,
   V = the variance of everything else.
4. EPIRCCR = weighted average over those hours, at most 1. EP_NET_PEAK = the weighted average of
   system (gross) load over the same hours.

The single-plant variance V_i. uecp.f takes it from IntStDdv and IntRegCrl (wwind), which renew.f reads from
input/rfm/wesarea.txt (sigma 0.38 for wind, 0.10 for solar, rho about 0.85). With those inputs the cap in step 3
binds for wind in every region and the credit falls to about half the net-peak capacity factor (TRE 0.08). ECP's
own EPIRCCR say otherwise: in the AIMMS oracle's 2030 composite input (ec::EPIRCCR, written by CAP_CREDIT before the
solve) wind's credit is the net-peak capacity factor, 0.19 to 0.34 by region (TRE 0.24, SPPS 0.31, NWPP 0.34), and
EIA's own year-end fleets come much closer to ECP's requirement region by region at those credits (docs/capacity.md). So
the credit here drops V_i (SINGLE_SITE_VARIANCE False), which puts it within 0.03 of ECP's on average for wind and
solar, against 0.11 for wind with the cap. A likely reason the variance is absent: renew.f is not part of the oracle
build, so its wwind block stays zero there. SINGLE_SITE_VARIANCE True restores the capped version (and the
wesarea inputs, wesarea()).

Net load, which picks the hours, uses ECP's adjusted capacities (PV_CAP_ADJ, WN_CAP_ADJ and the rest: each unit
scaled by its own capacity factor over the regional average, udat.f 7770-7810; uecp.f 39987 and 40200) when the
caller passes them (net_cap); the credit itself still divides by installed capacity. DEM_ADJ (cogeneration and
Mexican trade added to load) is left out: it is under 1% of peak in most regions.
"""

import numpy as np

from nems_open.emm import regions, technology

NUM_R = regions.NUM_EMM
WEIGHT_POWER = 5.0        # PARM_CCRED
MAX_DELTA = 0.10          # hours count while the weight is at least 1 - MAX_DELTA
INTERMITTENT = ("wind", "solar")
SINGLE_SITE_VARIANCE = False   # see the module docstring: ECP's own EPIRCCR carry no single-plant variance
# ECP's adjusted intermittent capacities by our group (UECPOUT/<type>_cap_adj): the types in CAP_CREDIT's net load.
CAP_ADJ_TYPES = {"wind": ("wn", "wf"), "solar": ("pv", "pt", "so")}
# Our capacity groups -> the ECP type whose forced outage rate and unit size stand for them.
ECP_TYPE = {"coal": "B1", "coal_ccs": "PQ", "gas_cc": "CC", "gas_cc_new": "AC", "gas_ccs": "CS", "gas_ct": "CT",
            "gas_ct_new": "AT", "steam": "ST", "gas_conv": "ST", "nuclear": "CN", "hydro": "HY", "other": "MS",
            "pumped": "P2", "battery": "DS", "wind": "WN", "solar": "PV"}


def _z() -> float:
    from nems_open.xlsx_ranges import named_ranges
    return float(named_ranges(technology.ECPDATY, "GENERAL")["UPINTZ"][0])


def wesarea() -> dict:
    """IntStDdv and IntRegCrl (renew.f 1320-1341) for wind (WN) and solar (PV): group -> (sigma (25,), rho (25,))."""
    from nems_open.paths import INPUT
    lines = (INPUT / "rfm" / "wesarea.txt").read_text(errors="replace").splitlines()

    def block(tag):
        i = next(k for k, ln in enumerate(lines) if ln.strip().startswith(tag))
        rows = []
        for ln in lines[i + 1:]:
            if ln.startswith("#") or not ln.strip():
                if rows:
                    break
                continue
            rows.append([float(x) for x in ln.split("!")[0].split()])
            if len(rows) == NUM_R:
                break
        return np.array(rows)
    sd, rho = block("%INTSTANDDV%"), block("%INTREGCORL%")
    return {"wind": (sd[:, 0], rho[:, 0]), "solar": (sd[:, 6], rho[:, 6])}


def cap_adjustment(snapshot, year: int) -> dict:
    """EIA's adjusted capacity less its installed capacity, wind and solar, (25,) GW, for `year` (capped at 2050):
    what net_cap adds to a fleet so CAP_CREDIT's net load sees the reference run's adjustment."""
    from nems_open.emm import dispatch
    y = min(year, 2050) - 1990
    out = {}
    for g, types in CAP_ADJ_TYPES.items():
        adj = sum(np.asarray(snapshot[f"UECPOUT/{t}_cap_adj"], dtype=float)[:NUM_R, y] for t in types)
        out[g] = adj - dispatch._ucap(snapshot, dispatch.CAPACITY_PREFIXES[g], y)
    return out


def credits(load_hr: np.ndarray, cap: dict, profile: dict, weights: np.ndarray, net_cap: dict = None) -> dict:
    """Wind and solar credit and net peak by region.

    load_hr: (25, 36, 24) system load, GW. cap: group -> (25,) GW. profile: wind, solar -> (25, 36, 24)
    capacity factors. weights: (36,) days each typical day stands for. net_cap: wind, solar -> (25,) GW used for
    the net load that picks the hours (ECP's CAP_ADJ), default cap.
    Returns {"wind": (25,), "solar": (25,), "net_peak": (25,) GW, "peak": (25,) GW}.
    """
    z = _z()
    p = technology.type_parameters()
    codes = technology.ecp_codes()
    fort = {g: float(p["forced_outage_rate"][codes.index(c)]) for g, c in ECP_TYPE.items()}
    size = {g: float(p["unit_size_mw"][codes.index(c)]) / 1000.0 for g, c in ECP_TYPE.items()}       # GW
    conv = [g for g in cap if g not in INTERMITTENT and g in ECP_TYPE]
    if SINGLE_SITE_VARIANCE:
        w = wesarea()
        sigma, rho = {g: w[g][0] for g in INTERMITTENT}, {g: w[g][1] for g in INTERMITTENT}
    out = {g: np.zeros(NUM_R) for g in INTERMITTENT}
    out["net_peak"] = np.zeros(NUM_R)
    out["peak"] = load_hr.max(axis=(1, 2))
    day_w = np.broadcast_to(weights[:, None], load_hr.shape[1:])
    for r in range(NUM_R):
        cf = {g: np.clip(profile[g][r], 0.001, 0.999) for g in INTERMITTENT}
        sub = cap if net_cap is None else net_cap
        net = load_hr[r] - sum(sub[g][r] * profile[g][r] for g in INTERMITTENT)
        wght = (np.maximum(net, 0.0) / net.max()) ** WEIGHT_POWER
        sel = wght >= 1.0 - MAX_DELTA
        w = (wght * day_w)[sel]
        out["net_peak"][r] = float((load_hr[r][sel] * w).sum() / w.sum())
        # variance of the conventional fleet (same in every hour)
        v_conv = 0.0
        for g in conv:
            c = cap[g][r]
            if c > 1e-6:
                v_conv += c * c * fort[g] * (1 - fort[g]) / (c / size[g])
        for i in INTERMITTENT:
            ci = cap[i][r]
            if ci <= 1e-6:
                out[i][r] = float((cf[i][sel] * w).sum() / w.sum())
                continue
            v = v_conv
            for j in INTERMITTENT:
                if j != i and cap[j][r] > 1e-6:
                    cj, fj = cap[j][r], cf[j][sel]
                    v = v + cj * cj * fj * (1 - fj) / (cj / size[j])          # (hours,)
            v = np.broadcast_to(v, cf[i][sel].shape)
            expected = ci * cf[i][sel]
            if SINGLE_SITE_VARIANCE:     # uecp.f 40405-40407 on wesarea's sigma and rho, capped at (cap CF / z)^2
                n = ci / size[i]
                full = ((1 - rho[i][r]) * n + rho[i][r] * n * n) * (sigma[i][r] * size[i]) ** 2
                vi = np.where(z * np.sqrt(full) > expected, (expected / z) ** 2, full)
            else:
                vi = 0.0
            t = (expected - z * (np.sqrt(vi + v) - np.sqrt(v))) / ci
            out[i][r] = float(min(1.0, (t * w).sum() / w.sum()))
    return out


# ECP's reserve credit for hydro and pumped storage. Conventional hydro counts RNWFAC (dsmsectr, 0.70) in the reserve
# row (uecp.f EP$BRNW,18 and 55); pumped storage (PS) its UPCCR, 0.70 in ecpdaty.xlsx COSTPERF.
HYDRO_CREDIT = 0.70
PUMPED_CREDIT = 0.70
# Diurnal storage (emmcntl.txt storage line: hoursToBuy, hoursToSell, batteryEfficiency).
HOURS_TO_SELL = 4.0
BATTERY_EFFICIENCY = 0.85
TOP_HOURS = 8             # CAP_CREDIT_LDC: the top 8 of the 864 hours, about 1% of them


def battery_soc(net: np.ndarray, power: float, hours: float = HOURS_TO_SELL,
                efficiency: float = BATTERY_EFFICIENCY) -> np.ndarray:
    """Stand-in for the EFD's battery state of charge (Rep_StorageLevel, GWh) over (36, 24) typical hours.

    Each typical day the battery discharges at full power in the `hours` highest net-load hours and recharges the
    energy (plus round-trip loss) in the lowest ones; the day is a cycle, so the level is the running sum of charge
    less discharge, shifted to be empty at its lowest point."""
    if power <= 1e-9:
        return np.zeros_like(net)
    days, n = net.shape
    k = int(round(hours))
    order = np.argsort(net, axis=1)
    flow = np.zeros_like(net)
    rows = np.arange(days)[:, None]
    flow[rows, order[:, n - k:]] = -power                         # discharge, GW out of the store
    need = power * k / np.sqrt(efficiency)                       # energy drawn from the grid to put that back
    full, part = divmod(need / power, 1.0)
    full = int(full)
    flow[rows, order[:, :full]] = power * np.sqrt(efficiency)
    if part > 1e-9 and full < n - k:
        flow[rows, order[:, full:full + 1]] = part * power * np.sqrt(efficiency)
    level = np.cumsum(flow, axis=1)
    return level - level.min(axis=1, keepdims=True)


def storage_credits(load_hr: np.ndarray, cap: dict, profile: dict) -> np.ndarray:
    """ECP's diurnal storage capacity credit by region (CAP_CREDIT_LDC, uecp.f 39834-40060).

    Net load is load less wind and solar output in each of the 864 typical hours. The storage term is the battery's
    stored energy over hoursToSell (ENERGY_STORED_HOURLY = StoLevel / 4, from the EFD's last solve; battery_soc here).
    The credit is the mean of the top 8 hours of (net load - storage term) over the mean of the top 8 hours of net
    load, each sorted on its own, between 0 and 1. It applies to existing and new batteries alike (CALC_STORAGE_VAL,4
    and 13). It is close to 1 while batteries are small next to the peak and falls as they grow."""
    out = np.ones(NUM_R)
    for r in range(NUM_R):
        net = load_hr[r] - sum(cap[g][r] * profile[g][r] for g in INTERMITTENT)
        stored = battery_soc(net, float(cap["battery"][r])) / HOURS_TO_SELL
        dem = np.abs(np.sort(net.ravel())[-TOP_HOURS:].sum())
        num = np.abs(np.sort((net - stored).ravel())[-TOP_HOURS:].sum())
        out[r] = float(np.clip(num / dem, 0.0, 1.0)) if dem > 1e-9 else 1.0
    return out
