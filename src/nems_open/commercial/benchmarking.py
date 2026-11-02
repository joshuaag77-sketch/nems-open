"""Commercial benchmarking: port of COMBenchmarking (comm.f).

Fuel use from the building model covers only buildings. For historical years (through
2025, SEDS) EIA adds the gap between SEDS and the model as "non-building use". For the
STEO years it ties the model to the short-term outlook, and after that it carries the gap
forward, growing electricity with floorspace, and fades any remaining STEO gap
(STEOMistie) out by a decay factor. The rest of the routine turns the benchmarked
commercial fuel use into emissions and into the fuel quantities (QELCM, QNGCM, ...)
that the rest of NEMS reads.

Loop order and leftover variables follow the Fortran; see SCOPE.md for the quirks kept
on purpose.
"""

from pathlib import Path

import numpy as np

from nems_open.commercial.inputs import CDM, _header
from nems_open.fortran_array import FArray

f32 = np.float32
BASEYR = 1990
CBECS_YEAR = 2018
CBECS_IDX = CBECS_YEAR - (BASEYR - 1)  # 29
CM_FIRST_YR = 30
MSEDYR = 34
KSTEOYR = 37
LAST_YR_2PCT = 38
MNUMCR = 11
NUM_DIV = 9
NUM_BLDG = 11
NUM_MAJ_FL = 3
NUM_MIN_FL = 5
NUM_RENEW = 3
NUM_FL = NUM_MAJ_FL + NUM_MIN_FL  # fuels that get benchmarked
NUM_FL_RENEW = NUM_FL + NUM_RENEW
NUM_EMISS = 8


def read_kemfac(cdm_dir: Path = CDM) -> FArray:
    """EmissionFactor (f, e): pounds of each pollutant per MMBtu of fuel f."""
    ef = FArray.zeros([(1, NUM_FL_RENEW), (1, NUM_EMISS)])
    rd = _header(Path(cdm_dir) / "kemfac.txt")
    try:
        for f in range(1, NUM_FL_RENEW + 1):
            vals = rd.read(NUM_EMISS)
            if vals is not None:
                ef[f, :] = np.array(vals, dtype=f32)
    except EOFError:
        pass
    return ef


def kelast2(inp, f, r, s, alpha, ef, ebase, y):
    """KELAST2: short-run price response spread over this year and the two before it."""
    fac = [f32(1.0), f32(1.0), f32(1.0)]
    if y >= ebase + 1:
        if f == 1:
            p = lambda yy: inp["pelcmout"][r, yy, s]
        elif f == 2:
            p = lambda yy: inp["pngcm"][r, yy]
        elif f == 3:
            p = lambda yy: inp["pdscm"][r, yy]
        else:
            p = None
        if p is not None and p(ebase) > 0.0:
            for k in range(3):
                fac[k] = f32(f32(p(y - k) / p(ebase)) ** f32(alpha * ef[k]))
        if y < ebase + 3:
            fac[2] = f32(1.0)
        if y < ebase + 2:
            fac[1] = f32(1.0)
    return f32(f32(fac[0] * fac[1]) * fac[2])


def _services_q(y, r, coeffs, mc_np):
    """Water or telecom services electricity: a cubic in years since 2008, split by population."""
    a, b, c, d = (f32(v) for v in coeffs)
    x = f32(y - 22)
    cubic = f32(a * f32(x ** f32(3.0)))
    cubic = f32(cubic + f32(b * f32(x ** f32(2.0))))
    cubic = f32(cubic + f32(c * x))
    cubic = f32(cubic + d)
    return f32(cubic * f32(mc_np[r, y] / mc_np[11, y]))


def benchmarking(inp: dict, y: int, itr: int, emission_factor: FArray, nrgbill: int = 1, stebobm: int = 1) -> dict:
    """One call of COMBenchmarking for year index y, iteration itr.

    `inp` holds the state before the call, the switches (ComSTEOBM, KSTEOCLS, NoHist,
    DecayBM, LastDecayYr, STEOBM2pct) and what other modules supply; returns the arrays
    the routine writes.
    """
    keys = ("cmnonbldguse", "sedsmistie", "steomistie", "cmfinalenduse", "qelcm", "qngcm", "qgfcm", "qgicm", "qdscm", "qrscm", "qrlcm",
            "qlgcm", "qprcm", "qclcm", "qmgcm", "qkscm", "qstcm", "qpvcm", "qbmcm", "emcm", "emcmc")
    out = {k: inp[k].copy() for k in keys}
    # Carried between calls; zero if the caller has no earlier value (it is reset for every year through 2023).
    out["diffqbm"] = inp["diffqbm"].copy() if "diffqbm" in inp else FArray.zeros([(1, MNUMCR)])
    out["waterserviceselq"] = FArray.zeros([(1, NUM_DIV), (1, 61)])
    out["telecomserviceselq"] = FArray.zeros([(1, NUM_DIV), (1, 61)])
    out["cmemissions"] = FArray.zeros([(1, NUM_FL_RENEW + 1), (1, NUM_EMISS), (1, MNUMCR)])
    nonbldg, sedsm, steom = out["cmnonbldguse"], out["sedsmistie"], out["steomistie"]
    final = out["cmfinalenduse"]
    seds, flspc = inp["cmseds"], inp["cmtotalflspc"]
    mc_np = inp["mc_np"]
    ef = (f32(0.5), f32(0.35), f32(0.15))
    elasbaseyr = CBECS_IDX
    steobm_on = stebobm == 1 and int(inp["comsteobm"]) == 1
    nohist = int(inp["nohist"])
    ksteocls = int(inp["ksteocls"])
    steobm2pct = inp["steobm2pct"]
    sr_elas = f32(0.0)

    water, telecom = out["waterserviceselq"], out["telecomserviceselq"]
    # The first year after SEDS is the reference for growth; EIA computed it on an earlier call.
    for yy in sorted({y, MSEDYR + 1}):
        for r in range(1, NUM_DIV + 1):
            water[r, yy] = _services_q(yy, r, (-0.00019, 0.022, -0.066, 203.977), mc_np)
            telecom[r, yy] = _services_q(yy, r, (0.003, -0.076, 1.892, 10.914), mc_np)

    for f in range(1, NUM_FL + 1):
        if y <= MSEDYR + 1:
            for r in range(1, NUM_DIV + 1):
                sedsm[f, r] = f32(seds[f, r, y] - final[f, r, y])
                nonbldg[f, r, y] = sedsm[f, r]
                if nohist == 1:
                    nonbldg[f, r, y] = 0.0
        elif y > MSEDYR + 1 and (y <= KSTEOYR or (y <= LAST_YR_2PCT and steobm2pct[f] == 1)):
            for r in range(1, NUM_DIV + 1):
                water_growth = f32(water[r, y] - water[r, MSEDYR + 1])
                telecom_growth = f32(telecom[r, y] - telecom[r, MSEDYR + 1])
                if y == MSEDYR + 2 and itr == 1:
                    sedsm[f, r] = 0.0
                    n = 3 if f == 7 else 5
                    for y2 in range(1, n + 1):
                        sedsm[f, r] = f32(sedsm[f, r] + nonbldg[f, r, y - y2])
                    sedsm[f, r] = f32(sedsm[f, r] / f32(float(n)))
                if f < 4:
                    sr_elas = inp["shortrunpriceelasofdmd"][r, 10, f]
                if f == 1:
                    growth = f32(f32(f32(f32(flspc[r, NUM_BLDG + 1, y] - flspc[r, NUM_BLDG + 1, MSEDYR + 1])
                                         / flspc[r, NUM_BLDG + 1, MSEDYR + 1])
                                     * abs(f32(f32(sedsm[f, r] - water[r, MSEDYR + 1]) - telecom[r, MSEDYR + 1]))))
                    phase = f32(f32(1.0) - f32(f32(0.0008148) * f32(y - 16)))
                    base = f32(f32(f32(f32(sedsm[f, r] * phase) + growth) + water_growth) + telecom_growth)
                    steom[f, r] = f32(seds[f, r, y] - f32(final[f, r, y] + base))
                    nonbldg[f, r, y] = base
                else:
                    steom[f, r] = f32(seds[f, r, y] - f32(final[f, r, y] + sedsm[f, r]))
                    nonbldg[f, r, y] = sedsm[f, r]
                if steobm_on:
                    if y > MSEDYR + 1 and ((y <= KSTEOYR and ksteocls == 1)
                                           or (y > KSTEOYR and y <= LAST_YR_2PCT and steobm2pct[f] == 1)):
                        gap = f32(steom[f, r] / seds[f, r, y])
                        if gap < -0.02:
                            steom[f, r] = f32(steom[f, r] + f32(f32(0.02) * seds[f, r, y]))
                        elif gap > 0.02:
                            steom[f, r] = f32(steom[f, r] - f32(f32(0.02) * seds[f, r, y]))
                        else:
                            steom[f, r] = 0.0
                    nonbldg[f, r, y] = f32(nonbldg[f, r, y] + steom[f, r])
                    if nohist == 1:
                        nonbldg[f, r, y] = 0.0
        else:
            calendar_year = f32(BASEYR - 1 + y)
            last_steo_year = f32(BASEYR - 1 + KSTEOYR)
            first_non_bench_year = f32(inp["lastdecayyr"])
            if int(inp["decaybm"]) == 0:
                decay = f32(1.0)
            else:
                decay = f32(f32(1.0) - f32(f32(calendar_year - last_steo_year)
                                            / f32(first_non_bench_year - last_steo_year)))
            if decay < 0.0:
                decay = f32(0.0)
            for r in range(1, NUM_DIV + 1):
                water_growth = f32(water[r, y] - water[r, MSEDYR + 1])
                telecom_growth = f32(telecom[r, y] - telecom[r, MSEDYR + 1])
                tot_flr = f32(0.0)
                for b in range(1, NUM_BLDG + 1):
                    tot_flr = f32(tot_flr + f32(inp["survfloortotal"][r, b, MSEDYR + 1]
                                                + inp["cmnewfloorspace"][r, b, MSEDYR + 1]))
                if f == 1:
                    sr_elas = inp["shortrunpriceelasofdmd"][r, 10, f]
                    growth = f32(f32(f32(f32(flspc[r, NUM_BLDG + 1, y] - flspc[r, NUM_BLDG + 1, MSEDYR + 1])
                                         / flspc[r, NUM_BLDG + 1, MSEDYR + 1])
                                     * abs(f32(f32(sedsm[f, r] - water[r, MSEDYR + 1]) - telecom[r, MSEDYR + 1]))))
                    elast = kelast2(inp, f, r, 10, sr_elas, ef, elasbaseyr, y)
                    if nrgbill == 0 or y <= 16:
                        scale = f32(sedsm[f, r])
                    elif y <= 26:
                        scale = f32(sedsm[f, r] * f32(f32(1.0) - f32(f32(0.0008148) * f32(y - 16))))
                    else:
                        scale = f32(sedsm[f, r] * f32(0.9918518))
                    nonbldg[f, r, y] = f32(f32(f32(f32(scale + growth) + water_growth) + telecom_growth) * elast)
                elif f == 2:
                    sr_elas = inp["shortrunpriceelasofdmd"][r, 10, f]
                    nonbldg[f, r, y] = f32(sedsm[f, r] * kelast2(inp, f, r, 10, sr_elas, ef, elasbaseyr, y))
                elif f == 3:
                    # EIA leaves SRElas from the last electricity/gas region here.
                    nonbldg[f, r, y] = f32(sedsm[f, r] * kelast2(inp, f, r, 10, sr_elas, ef, elasbaseyr, y))
                else:
                    nonbldg[f, r, y] = sedsm[f, r]
                if steobm_on:
                    if f != 6:
                        nonbldg[f, r, y] = f32(nonbldg[f, r, y] + f32(steom[f, r] * decay))
                    else:
                        nonbldg[f, r, y] = f32(nonbldg[f, r, y] + steom[f, r])
                if nohist == 1:
                    nonbldg[f, r, y] = 0.0

    for r in range(1, NUM_DIV + 1):
        for f in range(1, NUM_FL + 1):
            final[f, r, y] = f32(final[f, r, y] + nonbldg[f, r, y])
            if f == 1:
                final[f, r, y] = max(final[f, r, y], f32(0.1))
            else:
                final[f, r, y] = max(final[f, r, y], f32(0.0))

    # Emissions, in the units NEMS reports.
    em = out["cmemissions"]
    for f in range(1, NUM_FL_RENEW + 1):
        for e in range(1, NUM_EMISS + 1):
            for r in range(1, NUM_DIV + 1):
                em[f, e, r] = f32(f32(final[f, r, y] * emission_factor[f, e]) / f32(2204.62))
    for e in range(1, NUM_EMISS + 1):
        for r in range(1, NUM_DIV + 1):
            em[NUM_FL_RENEW + 1, e, r] = 0.0
            for f in range(1, NUM_FL_RENEW + 1):
                em[NUM_FL_RENEW + 1, e, r] = f32(em[NUM_FL_RENEW + 1, e, r] + em[f, e, r])
    for f in range(1, NUM_FL_RENEW + 2):
        for e in range(1, NUM_EMISS + 1):
            em[f, e, MNUMCR] = 0.0
            for r in range(1, NUM_DIV + 1):
                em[f, e, MNUMCR] = f32(em[f, e, MNUMCR] + em[f, e, r])
    emcm, emcmc = out["emcm"], out["emcmc"]
    for e in range(1, NUM_EMISS + 1):
        emcm[1, e, y] = em[2, e, MNUMCR]
        emcm[2, e, y] = f32(f32(f32(f32(f32(em[3, e, MNUMCR] + em[4, e, MNUMCR]) + em[5, e, MNUMCR])
                                  + em[7, e, MNUMCR]) + em[8, e, MNUMCR]))
        emcm[3, e, y] = em[6, e, MNUMCR]
        emcm[4, e, y] = em[9, e, MNUMCR]
        emcm[5, e, y] = em[10, e, MNUMCR]
        for r in range(1, MNUMCR + 1):
            emcmc[r, e, y] = em[NUM_FL_RENEW + 1, e, r]

    # Fuel quantities for the rest of NEMS.
    names = ("qelcm", "qngcm", "qgfcm", "qgicm", "qdscm", "qrscm", "qrlcm", "qlgcm", "qclcm", "qmgcm",
             "qkscm", "qstcm", "qpvcm", "qbmcm")
    for n in names:
        out[n][MNUMCR, y] = 0.0
    if final[6, 1, y] == 0.0:
        final[6, 1, y] = f32(0.0001)
    trq, q = inp["trq_elec"], out
    for r in range(1, NUM_DIV + 1):
        elec = final[1, r, y]
        for k in range(2, 10):
            elec = f32(elec + trq[k, r, y])
        q["qelcm"][r, y] = elec
        q["qelcm"][MNUMCR, y] = f32(q["qelcm"][MNUMCR, y] + q["qelcm"][r, y])
        for name, fuel, scale in (("qngcm", 2, None), ("qgfcm", 2, f32(1.0)), ("qgicm", 2, f32(0.0)),
                                  ("qdscm", 3, None), ("qrscm", 4, None), ("qrlcm", 4, None), ("qlgcm", 5, None)):
            q[name][r, y] = final[fuel, r, y] if scale is None else f32(final[fuel, r, y] * scale)
            q[name][MNUMCR, y] = f32(q[name][MNUMCR, y] + q[name][r, y])
            if name == "qlgcm":
                q["qprcm"][r, y] = q["qlgcm"][r, y]
        for name, fuel in (("qclcm", 6), ("qmgcm", 7), ("qkscm", 8)):
            q[name][r, y] = final[fuel, r, y]
            q[name][MNUMCR, y] = f32(q[name][MNUMCR, y] + q[name][r, y])
        q["qbmcm"][r, y] = f32(final[9, r, y] + final[10, r, y])
        if y <= MSEDYR:
            q["diffqbm"][r] = f32(inp["qsbmcm"][r, y] - q["qbmcm"][r, y])
            q["qbmcm"][r, y] = inp["qsbmcm"][r, y]
        else:
            if y == CM_FIRST_YR:
                q["diffqbm"][r] = f32(inp["qsbmcm"][r, MSEDYR] - q["qbmcm"][r, y])
            if q["qbmcm"][r, y] < inp["qsbmcm"][r, MSEDYR]:
                q["qbmcm"][r, y] = f32(q["qbmcm"][r, y] + q["diffqbm"][r])
        q["qbmcm"][MNUMCR, y] = f32(q["qbmcm"][MNUMCR, y] + q["qbmcm"][r, y])
        src = inp["solarrenewablecontrib"]
        thermal = f32(f32(f32(src[r, 1, y] + src[r, 2, y]) + src[r, 3, y])
                      + f32(src[r, 6, y] * f32(f32(29.916) / inp["sunlightefficacy"])))
        q["qstcm"][r, y] = f32(thermal * f32(inp["whrfoss"][r, y] / f32(3412.0)))
        q["qstcm"][MNUMCR, y] = f32(q["qstcm"][MNUMCR, y] + q["qstcm"][r, y])
        q["qpvcm"][r, y] = inp["solarpvcontrib"][y, r]
        q["qpvcm"][MNUMCR, y] = f32(q["qpvcm"][MNUMCR, y] + q["qpvcm"][r, y])
    q["qprcm"][MNUMCR, y] = q["qlgcm"][MNUMCR, y]
    return out
