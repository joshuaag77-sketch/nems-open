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

What is not EIA's here: the single-site standard deviation sigma and correlation rho (IntStDdv,
IntRegCrl) come from the renewable module's windalt file, which is not in this checkout. The code uses
the cap in step 3 (V_i = (cap CF / z)^2). The cap binds whenever z sqrt(rho) sigma > CF, which for a
regional fleet with any correlation is the usual case; when it binds the two inputs drop out. DEM_ADJ
(cogeneration and Mexican trade added to load) is left out: it is under 1% of peak in most regions.
"""

import numpy as np

from nems_open.emm import regions, technology

NUM_R = regions.NUM_EMM
WEIGHT_POWER = 5.0        # PARM_CCRED
MAX_DELTA = 0.10          # hours count while the weight is at least 1 - MAX_DELTA
INTERMITTENT = ("wind", "solar")
# Our capacity groups -> the ECP type whose forced outage rate and unit size stand for them.
ECP_TYPE = {"coal": "B1", "coal_ccs": "PQ", "gas_cc": "CC", "gas_cc_new": "AC", "gas_ccs": "CS", "gas_ct": "CT",
            "gas_ct_new": "AT", "steam": "ST", "gas_conv": "ST", "nuclear": "CN", "hydro": "HY", "other": "MS",
            "pumped": "P2", "battery": "DS", "wind": "WN", "solar": "PV"}


def _z() -> float:
    from nems_open.xlsx_ranges import named_ranges
    return float(named_ranges(technology.ECPDATY, "GENERAL")["UPINTZ"][0])


def credits(load_hr: np.ndarray, cap: dict, profile: dict, weights: np.ndarray) -> dict:
    """Wind and solar credit and net peak by region.

    load_hr: (25, 36, 24) system load, GW. cap: group -> (25,) GW. profile: wind, solar -> (25, 36, 24)
    capacity factors. weights: (36,) days each typical day stands for.
    Returns {"wind": (25,), "solar": (25,), "net_peak": (25,) GW, "peak": (25,) GW}.
    """
    z = _z()
    p = technology.type_parameters()
    codes = technology.ecp_codes()
    fort = {g: float(p["forced_outage_rate"][codes.index(c)]) for g, c in ECP_TYPE.items()}
    size = {g: float(p["unit_size_mw"][codes.index(c)]) / 1000.0 for g, c in ECP_TYPE.items()}       # GW
    conv = [g for g in cap if g not in INTERMITTENT and g in ECP_TYPE]
    out = {g: np.zeros(NUM_R) for g in INTERMITTENT}
    out["net_peak"] = np.zeros(NUM_R)
    out["peak"] = load_hr.max(axis=(1, 2))
    day_w = np.broadcast_to(weights[:, None], load_hr.shape[1:])
    for r in range(NUM_R):
        cf = {g: np.clip(profile[g][r], 0.001, 0.999) for g in INTERMITTENT}
        net = load_hr[r] - sum(cap[g][r] * profile[g][r] for g in INTERMITTENT)
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
            vi = (expected / z) ** 2
            t = (expected - z * (np.sqrt(vi + v) - np.sqrt(v))) / ci
            out[i][r] = float(min(1.0, (t * w).sum() / w.sum()))
    return out
