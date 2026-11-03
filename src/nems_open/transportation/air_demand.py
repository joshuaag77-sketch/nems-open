"""TAIRT (tranair.f): air travel demand.

Passenger yields from jet fuel prices; revenue passenger-miles per capita by world
region grow with GDP per capita (with COVID adjustments); freight ton-miles grow with
GDP, aligned to the last history year; belly freight carried on passenger aircraft;
seat-mile demand by region and aircraft type.

carry: TAIRT's saved pjftr_us (years before n filled).
EIA quirk kept: LFDOMAVG and LFINTAVG add up on every call, so each year holds the sum
over that year's iterations.
"""

import numpy as np

from nems_open.transportation.air_common import DOM, DOMINT, INT, MAXATYP, MAXWREG, ONE, US, A
from nems_open.transportation.common import expf, f32, fsum, MNUMCR, powf
from nems_open.transportation.misc_modes import powi

W = slice(1, MAXWREG)
T = slice(1, MAXATYP)
D = slice(1, DOMINT)


def tairt(s: dict, carry: dict) -> None:
    a = A(s)
    n, yrs = a.i("n"), a.i("yrs")
    pj = carry["pjftr_us"]
    pj[n] = a["pjftr"][11, n]
    iy, last_idx = a.i("iy"), a.i("last_hist_index")
    if a.i("curcalyr") == a.i("first_read_year"):
        q = a["qagtr"]
        for i in range(iy, last_idx + 1):
            q[11, i] = a["qagtr_us"][1, i]
            q[1:MNUMCR - 2, i] = q[11, i] * a["sedshrjf"][1:MNUMCR - 2, iy]
            a["stk_sup"][W, T, 1, i] = a["stk_sup_new"][W, i, T]

    lf, shr_rpm = a["load_factor"], a["shr_rpm"]
    a["lfdomavg"][n] = a["lfdomavg"][n] + lf[US, n, DOM] * fsum(shr_rpm[US, n, T, DOM])
    a["lfintavg"][n] = a["lfintavg"][n] + lf[US, n, INT] * fsum(shr_rpm[US, n, T, INT])

    first_fcst, last_hist = a.i("first_fcst_yr"), a.i("last_hist_yr")
    yld, yield_ = a["yld"], a["yield"]
    if yrs >= first_fcst:
        if yrs == first_fcst:
            yld[DOM, n - 1] = yield_[DOM, n - 1]
        rho, rhoi = a["rhoyd"], a["rhoyi"]
        yld[DOM, n] = (a["alphayd"] * (ONE - rho) + rho * yld[DOM, n - 1] + a["betafueld"] * (pj[n] - rho * pj[n - 1])
                       + a["betatimed"] * (f32(n + 11) - rho * f32(n + 10)))
        yield_[DOM, n] = yld[DOM, n]
        yield_[INT, n] = (a["alphayi"] * (ONE - rhoi) + rhoi * yield_[INT, n - 1] + a["betafueli"] * (pj[n] - rhoi * pj[n - 1])
                          + a["betatimei"] * (f32(n + 11) - rhoi * f32(n + 10)))

    rpmt, pc, rpm = a["rpmt"], a["rpmt_pc"], a["rpm"]
    gdp, pop = a["wld_gdp"], a["wld_pop"]
    if yrs < first_fcst:
        rpmt[W, D, n] = f32(1000.) * a["rpmt_hist"][W, n, D]
        pc[W, D, n] = rpmt[W, D, n] / pop[W, n][:, None]
        for t in range(1, MAXATYP + 1):
            rpm[W, D, t, n] = rpmt[W, D, n] * shr_rpm[W, n, t, D]
    else:
        cov = a["covid_mult"]
        for di in range(1, DOMINT + 1):
            pc[W, di, n] = (pc[W, di, n - 1] * expf(a["intercept_rpm"][W, di])
                            * powf((gdp[W, n] / pop[W, n]) / (gdp[W, n - 1] / pop[W, n - 1]), a["beta1_rpm"][W, di]))
            rpmt[W, di, n] = pc[W, di, n] * pop[W, n]
            m = cov[W, n, di] != 0
            rpmt[W, di, n] = np.where(m, rpmt[W, di, 30] * (ONE - cov[W, n, di]), rpmt[W, di, n])
            pc[W, di, n] = np.where(m, rpmt[W, di, n] / pop[W, n], pc[W, di, n])
            for t in range(1, MAXATYP + 1):
                rpm[W, di, t, n] = rpmt[W, di, n] * shr_rpm[W, n, t, di]

    ftm, align = a["ftm"], a["ftm_alignhist"]
    est = expf(a["intercept_ftm"][W, D]) * powf(gdp[W, n][:, None], a["beta1_ftm"][W, D])
    if yrs == last_hist:
        align[...] = 0.0
        align[W, D] = est - ftm[W, n, D]
    elif yrs >= first_fcst:
        ftm[W, n, D] = est - align[W, D] * powi(f32(0.85), n - 32)

    pw = a["pass_weight"]
    belly, pdmd, cdmd = a["belly_rpm_eq"], a["passac_rpm_dmd"], a["cargoac_ftm_dmd"]
    bp, bf, gptm, mtow = a["pct_belly_pload"], a["pct_belly_frt"], a["gptm"], a["pct_pass_mtow"]
    rpmpg, asmpg = a["rpmpg"], a["asmpg_avg_age"]
    for w in range(1, MAXWREG + 1):
        fw = fsum(ftm[w, n, :])
        for t in range(1, MAXATYP + 1):
            for di in range(1, DOMINT + 1):
                p = bp[t, n, di]
                belly[w, t, di, n] = min(rpm[w, di, t, n] * p / (ONE - p), fw * bf[t, n, di] * f32(2000) / pw)
                pdmd[w, t, di, n] = rpm[w, di, t, n] + belly[w, t, di, n]
                if yrs <= last_hist:
                    g = gptm[w, n, t, di] * pw / f32(2000)
                    empty = ONE - lf[w, n, di]
                    if pdmd[w, t, di, n] > 0.0:
                        rpmpg[w, t, di, n] = ONE / (g * (ONE - empty * mtow[t, n]) / (ONE - empty * (ONE - (belly[w, t, di, n] / pdmd[w, t, di, n]))))
                    else:
                        rpmpg[w, t, di, n] = ONE / (g * (ONE - empty * mtow[t, n]) / (ONE - empty))
                    asmpg[w, t, di, n] = ONE / (gptm[w, n, t, di] * pw / f32(2000))
        for t in range(1, MAXATYP + 1):
            for di in range(1, DOMINT + 1):
                c = (ftm[w, n, di] - fsum(belly[w, :, di, n]) * pw / f32(2000)) * a["shr_ftm"][w, n, t, di]
                cdmd[w, t, di, n] = max(f32(0.0), c)
    s.update({a.key("iwreg"): MAXWREG + 1, a.key("iatyp"): MAXATYP + 1, a.key("di"): DOMINT + 1})

    smd, tot, asm, asmd = a["smdemd"], a["smd_tot"], a["asm"], a["asmdemd"]
    smd[:, n] = 0.0
    tot[:, n] = 0.0
    asm[:, :, :, n] = 0.0
    asmd[:, :, n] = 0.0
    asm[W, D, T, n] = rpm[W, D, T, n] / lf[W, n, D][:, :, None]
    smd[W, n] = fsum(fsum(asm[W, D, T, n], axis=2), axis=1)
    asmd[W, T, n] = fsum(asm[W, D, T, n], axis=1)
    tot[W, n] = (smd[W, n] + fsum(ftm[W, n, D], axis=1) * f32(2000.0) / pw) * f32(0.001)
