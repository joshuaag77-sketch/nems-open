"""TSHIP (tranfrt.f): domestic and international marine fuel demand.

Domestic ton-miles grow with industrial output by region and sector; fuel follows
an efficiency index and fixed fuel shares. International shipping fuel is a base
level growing with trade; its fuel mix comes from a logit over indexed fuel prices,
weighted by fuel use in emission-control areas (vessel fleets turning over and
growing with trade by vessel type).

carry: TSHIP's saved isfdt_b, lsfo_upgrade and temp_prhtr (years before n filled).
"""

import numpy as np

from nems_open.transportation.common import expf, f32, fsum, MNUMCR, powf
from nems_open.transportation.frt_common import ONE, V

R9 = slice(1, MNUMCR - 2)
SIC = 16
VTYPE = 9
IFO = f32(.88)
IMO2020 = f32(.60)
UPGRADE_COST = f32(.43)
AVEMEFF = np.array([0, 0.50, 0.48, 0.28, 0.50, 0.48], dtype=f32)
ENPEN = np.array([0, 0.0, 0.02, 0.0, 0.0, 0.0], dtype=f32)
ALPHA = f32(-0.5)
FAF = 28        # iFAFyear, a PARAMETER in tranmain


def _logit_fac(fac, k, yrs, slope):
    return fac[k, 1] + (fac[k, 2] - fac[k, 1]) / (ONE + expf(slope * (f32(yrs) - fac[k, 3])))


def tship(s: dict, carry: dict) -> None:
    v = V(s)
    n, yrs, curitr = v.i("n"), v.i("curcalyr"), v.i("curitr")
    isfdt_b, lsfo, tprh = carry["isfdt_b"], carry["lsfo_upgrade"], carry["temp_prhtr"]
    faf, histyr = FAF, v.i("shiphistyr")
    tsic, out, hist = v["tsic"], v["dstm_output"], v["dshist_tonmi"]
    if n == faf:
        out[R9, 1:SIC] = 0.0
        tt = tsic[1:SIC, R9, faf].T
        val = (hist[n, R9][:, None] * v["dtm_shares"][R9, 1:SIC]) / tt
        out[R9, 1:SIC] = np.where(tt > 0.0, val, out[R9, 1:SIC])
    stmtt, add, decl = v["stmtt"], v["dsadd_tonmi"], v["ann_decline"]
    if n <= histyr:
        stmtt[n, R9] = hist[n, R9]
    else:
        add[n, R9, 1:SIC] = tsic[1:SIC, R9, n].T * (out[R9, 1:SIC] * (ONE - decl[n]))
        stmtt[n, R9] = fsum(add[n, R9, 1:SIC], axis=1)
    if faf <= n <= histyr:
        add[n, R9, 1:SIC] = tsic[1:SIC, R9, n].T * (out[R9, 1:SIC] * (ONE - decl[n]))
        stmtt[n, R9] = 0.0
        tot = fsum(add[n, R9, 1:SIC])
        if tot > 0.0:
            stmtt[n, R9] = fsum(hist[n, R9]) * (fsum(add[n, R9, 1:SIC], axis=1) / tot)
    stmtt[n, 11] = fsum(stmtt[n, R9])
    v["tqdshipt"][n, 1:MNUMCR] = stmtt[n, 1:MNUMCR] * v["dseff"][n]
    dr = v["tqdshipr"]
    for m in range(1, 5):
        dr[m, 1:MNUMCR, n] = v["tqdshipt"][n, 1:MNUMCR] * v["domship_fuel_shr"][m, n]

    xr, mr = v["mc_xr"], v["mc_mr"]
    if n <= 2020 - 1989:
        isfdt_b[n] = (v["qsrstr"][11, n] - fsum(dr[2, R9, n])) + (v["q_shipbunkds"][n] - fsum(dr[1, R9, n]))
    elif n <= 2023 - 1989:
        isfdt_b[n] = isfdt_b[n - 1] * (xr[n] + mr[n]) / (xr[n - 1] + mr[n - 1])
    else:
        isfdt_b[n] = isfdt_b[n - 1] * (ONE + ((xr[n] + mr[n]) / (xr[n - 1] + mr[n - 1]) - ONE) * f32(0.5))

    g = np.zeros(VTYPE + 1, dtype=f32)

    def imports(y):
        return (v["rfqicrd"][10, y] + v["rfsprim"][y] + v["rfpqiprdt"][10, y, 2] + v["ethimp"][11, y] / f32(1000.)
                + v["biodimp"][11, y] / f32(1000.) + v["rfipqcbob"][10, y, 2] / f32(1000.)
                + v["rfipqrbob"][10, y, 2] / f32(1000.) + v["rfmtbi"][10, y] + v["rfpqufc"][10, y, 2])

    def ngl(y):
        q = v["qprdex"]
        return q[27, y] + q[1, y] + q[15, y] + q[28, y] + q[29, y] + q[14, y]

    g[1] = imports(n) / imports(23)
    g[2] = v["mc_xginr"][n] / v["mc_xginr"][23]
    g[3] = v["mc_mgcr"][n] / v["mc_mgcr"][23]
    g[4] = v["ngexpvol"][3, n] / v["ngexpvol"][3, 23]
    g[5] = ngl(n) / ngl(23)
    g[6] = v["mc_mgautor"][n] / v["mc_mgautor"][23]
    g[7] = v["cqdbfb"][11, 5, n] / v["cqdbfb"][11, 5, 23]
    g[8] = v["mc_xgffbr"][n] / v["mc_xgffbr"][23]
    g[9] = v["mc_mgkr"][n] / v["mc_mgkr"][23]
    eca = np.zeros(MNUMCR + 1, dtype=f32)
    if yrs >= 2012:
        to, eff, fc = v["fleetto"], v["effinc"], v["fuelcons"]
        for mv in range(1, VTYPE + 1):
            surv = max(f32(0.), ONE - (f32(yrs - 2012) * to[mv]))
            meff = powf(ONE - eff[mv], f32(yrs - 2012) * f32(.5))
            c = fc[R9, mv]
            eca[1:MNUMCR - 1] = eca[1:MNUMCR - 1] + ((c * surv) + (c * (ONE - surv) * meff)) * g[mv]

    shr = v["intship_fuel_shr"]
    prof31 = np.zeros(6, dtype=f32)
    for m in (5, 4, 2, 1):
        prof31[m] = shr[m, 31]
    prof = np.zeros((6, MNUMCR + 1), dtype=f32)
    if yrs > 2020:
        fac = v["intshiplogit_fac"]
        pfac = [None, _logit_fac(fac, 1, yrs, f32(-1.)), _logit_fac(fac, 2, yrs, f32(-.5)),
                _logit_fac(fac, 3, yrs, f32(-.5)), _logit_fac(fac, 4, yrs, f32(-.5)), _logit_fac(fac, 5, yrs, f32(-.5))]
    lsfo[:, n] = 0.0
    up = UPGRADE_COST / v["mc_jpgdp"][11] * v["mc_jpgdp"][1]
    prl, prh, pds = v["prltr"], v["prhtr"], v["pdstr"]
    lng, cng = v["pgltrship"], v["pgftrship"]
    for iregn in range(1, MNUMCR - 1):
        if prl[iregn, n] > 0.0:
            lsfo[iregn, n] = up + prl[iregn, n]
        if yrs <= 2020:
            continue
        w = np.zeros(6, dtype=f32)
        pl = lng[3, iregn, n]
        w[1] = pfac[1] * max(ONE, pds[iregn, n] / pl) * pds[iregn, n - 2:n].max() / pds[iregn, 26:27].max()
        if iregn == 9:
            w[2] = pfac[2] * max(ONE, prh[iregn, n] / pl) * prh[iregn, n - 2:n].max() / prh[iregn, 26:27].max()
        else:
            tprh[iregn, n] = prh[9, n] / prl[9, n] * prl[iregn, n]
            w[2] = pfac[2] * max(ONE, tprh[iregn, n] / pl) * tprh[iregn, n - 2:n].max() / prh[iregn, 26:27].max()
        w[3] = pfac[3] * cng[3, iregn, n] / cng[3, iregn, 27]
        w[4] = pfac[4] * lng[3, iregn, n - 2:n].max() / lng[3, iregn, 26:27].max()
        w[5] = pfac[5] * max(ONE, lsfo[iregn, n] / pl) * lsfo[iregn, n - 2:n].max() / lsfo[iregn, 26:27].max()
        lsum = f32(0.0)
        for m in range(1, 6):
            if w[m] <= f32(0.05):
                w[m] = f32(.05)
            lsum = lsum + ((powf(w[m], ALPHA) * prof31[m]) * AVEMEFF[m])
        if lsum > 0:
            for m in range(1, 6):
                prof[m, iregn] = (powf(w[m], ALPHA) * prof31[m] * AVEMEFF[m]) / lsum
        lsum = f32(0.)
        for m in range(1, 6):
            lsum = lsum + prof[m, iregn]
        if lsum != 0 and abs(lsum - ONE) > f32(0.001):
            for m in range(1, 6):
                prof[m, iregn] = prof[m, iregn] / lsum
    v["iregn"] = MNUMCR - 1

    mar = np.zeros((VTYPE + 1, MNUMCR + 1), dtype=f32)
    for m in range(1, 6):
        mar[m, 1:MNUMCR - 1] = eca[1:MNUMCR - 1] * prof[m, 1:MNUMCR - 1] * (ONE + ENPEN[m]) * f32(.001)
    isfd = v["isfd"]
    for m in range(1, 6):
        if yrs > 2020:
            shr[m, n] = fsum(mar[m, 1:MNUMCR - 1]) / fsum(mar[1:, 1:MNUMCR - 1])
        isfd[m, n] = isfdt_b[n] * shr[m, n]
    ir = v["tqishipr"]
    for m in range(1, 6):
        reg = v["sedshrds"][R9, n] if m == 1 else v["sedshrrs"][R9, n]
        ir[m, R9, n] = isfd[m, n] * reg
        if m == 2:
            ir[1, R9, n] = ir[1, R9, n] + (ir[m, R9, n] * (ONE - IFO))
            ir[m, R9, n] = ir[m, R9, n] * IFO
        if m == 5:
            ir[1, R9, n] = ir[1, R9, n] + ir[m, R9, n] * (ONE - IMO2020)
            ir[m, R9, n] = ir[m, R9, n] * IMO2020
            ir[1, R9, n] = ir[1, R9, n] + (ir[m, R9, n] * (v["lsforisk"][n]))
            ir[m, R9, n] = ir[m, R9, n] * (ONE - v["lsforisk"][n])
    for m in range(1, 6):
        ir[m, 11, n] = fsum(ir[m, R9, n])
