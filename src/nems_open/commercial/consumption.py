"""Commercial energy consumption: port of COMConsumption (comm.f), after its
first-call file reads.

Turns each service's demand into fuel use: service demand x fuel share /
efficiency, then adjusts for short-run price response, a rebound effect from
more efficient equipment, building shells, weather and lighting units. Nets out
on-site generation (rooftop solar, fuel cells and other distributed generation),
adds district steam, applies an efficiency standard for pre-rinse spray valves,
estimates minor fuels from price regressions, and builds the regional and
national totals that the rest of NEMS reads.

Loop order and leftover variables follow the Fortran; see SCOPE.md for the
quirks kept on purpose.
"""

import numpy as np

f32 = np.float32
BASEYR = 1990
CBECS_IDX = 29
FIRST_YEAR = 30
MSEDYR = 34
LAST_YR_2PCT = 38
NUM_DIV = 9
NUM_BLDG = 11
NUM_SERV = 10
NUM_MAJ_SERV = 7
NUM_MAJ_FL = 3
NUM_MIN_FL = 5
NUM_RENEW = 3
NUM_ALL_FL = 8
NUM_SD_ELAS = 10
NUM_DH_SERV = 3
NUM_SOLAR_SERV = 6


def kelast(inp, f, r, s, alpha, ef, ebase, y):
    """KELAST: short-run price response, compounding this year's and the two
    previous years' prices against the base year."""
    fac = [f32(1.0), f32(1.0), f32(1.0)]
    if y >= ebase + 1:
        if f == 1:
            p = lambda yy: inp["pelcmout"][r, yy, s]
        elif f == 2:
            p = lambda yy: inp["pngcm"][r, yy]
        else:
            p = lambda yy: inp["pdscm"][r, yy]
        if p(ebase) > 0.0:
            for k in range(3):
                fac[k] = (p(y - k) / p(ebase)) ** (alpha * ef[k])
        if y < ebase + 3:
            fac[2] = f32(1.0)
        if y < ebase + 2:
            fac[1] = f32(1.0)
    return fac[0] * fac[1] * fac[2]


def consumption(inp: dict, y: int) -> dict:
    """One call of COMConsumption's calculation for year index y."""
    out = {k: inp[k].copy() for k in (
        "enduseconsump", "euconwithdg", "cmeffind", "finalendusecon",
        "unbenchedcon", "cmfinalenduse", "cmfinalunbenchuse", "cmusconsumption", "cmusavgeff",
        "distservconsump", "distservsteam", "cmusdistserv", "cmfinalendusecon", "solarpvcontrib",
        "solarrenewablecontrib", "cmseds", "minfuelbeta", "cmnonbldguse")}
    EUC, DG, EI = out["enduseconsump"], out["euconwithdg"], out["cmeffind"]
    FEUC, UB = out["finalendusecon"], out["unbenchedcon"]
    CMF, CMFU = out["cmfinalenduse"], out["cmfinalunbenchuse"]
    ef = (inp["ef1"], inp["ef2"], inp["ef3"])
    ebase = CBECS_IDX
    fss, ave, ave_base = inp["fuelshareofservice"], inp["averageefficiency"], inp["averageefficiencybase"]
    nsd, rsd, ssd = inp["newservdmd"], inp["retireservdmd"], inp["servdmdsurv"]
    sdbyfuel, srel = inp["sdbyfuel"], inp["shortrunpriceelasofdmd"]
    shell_h, shell_c, dd = inp["shellheatfactor"], inp["shellcoolfactor"], inp["degreedays"]
    surv, newf = inp["survfloortotal"], inp["cmnewfloorspace"]

    for r in range(1, NUM_DIV + 1):
        for b in range(1, NUM_BLDG + 1):
            for f in range(1, NUM_MAJ_FL + NUM_MIN_FL + NUM_RENEW + 1):
                UB[f, b, r, y] = 0.0
                FEUC[f, b, r, y] = 0.0
        for f in range(1, NUM_MAJ_FL + NUM_MIN_FL + NUM_RENEW + 1):
            CMFU[f, r, y] = 0.0
            CMF[f, r, y] = 0.0
        out["solarpvcontrib"][y, r] = 0.0

    # End-use consumption (label 105).
    for r in range(1, NUM_DIV + 1):
        for f in range(1, NUM_MAJ_FL + 1):
            for b in range(1, NUM_BLDG + 1):
                for s in range(1, NUM_SERV + 1):
                    EUC[f, s, b, r, y] = 0.0
                    DG[f, s, b, r, y] = 0.0
                    EI[f, s, b, r, y] = 1.0
                    if ave[r, b, s, f] > 0.0:
                        x = fss[r, b, s, f] / ave[r, b, s, f] * (nsd[s, b, r, y] + rsd[s, b, r, y] + ssd[s, b, r, y])
                        if sdbyfuel[f, s, b, r, y] > 0.0 and x > 0.0:
                            EI[f, s, b, r, y] = x / sdbyfuel[f, s, b, r, y]
                        if s <= NUM_SD_ELAS and x > 0.0:
                            x = x * kelast(inp, f, r, s, srel[r, s, f], ef, ebase, y)
                            if s <= 6 and ave_base[r, b, s, f] > 0.0 and y > FIRST_YEAR:
                                rebound = f32(-0.15) * (f32(1.0) - ave[r, b, s, f] / ave_base[r, b, s, f])
                                if abs(rebound) > 0.25:
                                    rebound = f32(0.25) if rebound > 0.0 else f32(-0.25)
                                x = x * (f32(1.0) + rebound)
                            if s == 1:
                                x = x * (f32(1.0) + (f32(-0.15) * (shell_h[b, r, 1, y] - f32(1.0))))
                            if s == 2:
                                x = x * (f32(1.0) + (f32(-0.15) * (shell_c[b, r, 1, y] - f32(1.0))))
                        EUC[f, s, b, r, y] = x
                    if s == 6:
                        EUC[f, s, b, r, y] = EUC[f, s, b, r, y] / f32(0.03343)
                    if s in (1, 2) and dd[s, r, CBECS_IDX] > 0.0:
                        ratio = dd[s, r, y] / dd[s, r, CBECS_IDX]
                        EUC[f, s, b, r, y] = EUC[f, s, b, r, y] * (ratio if s == 1 else ratio ** f32(1.10))

    # Distributed generation netting (label 106).
    own, shb, hwb, fu = inp["trillsownuse"], inp["shbtu"], inp["hwbtu"], inp["fuelusage"]
    own_adj = {}
    for b in range(1, NUM_BLDG + 1):
        for r in range(1, NUM_DIV + 1):
            for s in range(1, 11):
                DG[1, s, b, r, y] = EUC[1, s, b, r, y]
            own_adj[b, r] = (own[y, r, b, 1] + own[y, r, b, 4] + own[y, r, b, 6] + own[y, r, b, 9]
                             + own[y, r, b, 10] + own[y, r, b, 11])
            ngo = own[y, r, b, 2] + own[y, r, b, 3] + own[y, r, b, 5] + own[y, r, b, 7] + own[y, r, b, 8]
            EUC[1, 10, b, r, y] = EUC[1, 10, b, r, y] - ngo
            sh_adj = shb[y, r, b, 2] + shb[y, r, b, 3] + shb[y, r, b, 7] + shb[y, r, b, 8]
            hw_adj = hwb[y, r, b, 2] + hwb[y, r, b, 3] + hwb[y, r, b, 7] + hwb[y, r, b, 8]
            fu_adj = fu[y, r, b, 2] + fu[y, r, b, 3] + fu[y, r, b, 7] + fu[y, r, b, 8]
            for s, adj in ((1, sh_adj), (3, hw_adj)):
                before = EUC[2, s, b, r, y]
                EUC[2, s, b, r, y] = before - adj
                if EUC[2, s, b, r, y] > 0.0:
                    EI[2, s, b, r, y] = EI[2, s, b, r, y] * before / EUC[2, s, b, r, y]
            EUC[2, 10, b, r, y] = EUC[2, 10, b, r, y] + fu_adj
            for s, adj in ((1, shb[y, r, b, 5]), (3, hwb[y, r, b, 5])):
                before = EUC[3, s, b, r, y]
                EUC[3, s, b, r, y] = max(before - adj, f32(0.0))
                if EUC[3, s, b, r, y] > 0.0:
                    EI[3, s, b, r, y] = EI[3, s, b, r, y] * before / EUC[3, s, b, r, y]
            EUC[3, 10, b, r, y] = EUC[3, 10, b, r, y] + fu[y, r, b, 5]

    # District services: steam bought from district systems (after label 106).
    ds_eui, ds_fs, ds_eff = inp["distservsteameui"], inp["distservfuelshr"], inp["distservboilereff"]
    DSC = out["distservconsump"]
    steam = f32(0.0)
    sr_left = None  # EIA reuses the last SRElas of the loop above (quirk)
    for b in range(1, NUM_BLDG + 1):
        for s in range(1, NUM_DH_SERV + 1):
            for r in range(1, NUM_DIV + 1):
                adj = f32(0.0)
                for f in range(1, NUM_MAJ_FL + 1):
                    sr_left = srel[r, s, f]
                    adj += ds_fs[r, s, f] * kelast(inp, f, r, s, sr_left, ef, ebase, y)
                floor = (surv[r, b, y] + newf[r, b, y]) / f32(1000.0)
                if s < 3:
                    if dd[s, r, CBECS_IDX] > 0.0:
                        steam += ds_eui[r, b, s] * floor * adj * dd[s, r, y] / dd[s, r, CBECS_IDX]
                else:
                    steam += ds_eui[r, b, s] * floor * adj
            for f in range(1, NUM_MAJ_FL + 1):
                DSC[11, b, s, f, y] = 0.0
                for r in range(1, NUM_DIV + 1):
                    base = (ds_eui[r, b, s] * (surv[r, b, y] + newf[r, b, y]) * ds_fs[r, s, f] / ds_eff[f]
                            * kelast(inp, f, r, s, sr_left, ef, ebase, y))
                    if s < 3:
                        if dd[s, r, CBECS_IDX] > 0.0:
                            DSC[r, b, s, f, y] = base * dd[s, r, y] / dd[s, r, CBECS_IDX] / f32(1000.0)
                    else:
                        DSC[r, b, s, f, y] = base / f32(1000.0)
                    DSC[11, b, s, f, y] = DSC[11, b, s, f, y] + DSC[r, b, s, f, y]
                    EUC[f, s, b, r, y] = EUC[f, s, b, r, y] + DSC[r, b, s, f, y]
                    if f == 1:
                        DG[f, s, b, r, y] = DG[f, s, b, r, y] + DSC[r, b, s, f, y]
    out["distservsteam"][y] = steam
    for s in range(1, NUM_DH_SERV + 1):
        for f in range(1, NUM_MAJ_FL + 1):
            acc = f32(0.0)
            for b in range(1, NUM_BLDG + 1):
                acc += DSC[11, b, s, f, y] / f32(1000.0)
            out["cmusdistserv"][s, f, y] = acc

    # Clamp, pre-rinse spray valve standard, and building totals (label 109).
    nrgbill = int(inp["nrgbill"]) > 0
    savings = inp["prsvstdsavings"]
    food_floor = inp["foodsvchlthldgfloortot"]
    for f in range(1, NUM_MAJ_FL + 1):
        for b in range(1, NUM_BLDG + 1):
            for s in range(1, NUM_SERV + 1):
                EUC[f, s, b, 11, y] = 0.0
                DG[f, s, b, 11, y] = 0.0
                for r in range(1, NUM_DIV + 1):
                    EUC[f, s, b, r, y] = max(EUC[f, s, b, r, y], f32(0.0))
                    el_ng_ds = f32(0.0)
                    if s == 3:
                        el_ng_ds = el_ng_ds + EUC[1, s, b, r, y] + EUC[2, s, b, r, y] + EUC[3, s, b, r, y]
                    if f == 1:
                        DG[f, s, b, r, y] = max(DG[f, s, b, r, y], f32(0.0))
                    if nrgbill and s == 3 and y > 29 and 3 < b < 7:
                        EUC[f, s, b, r, y] = EUC[f, s, b, r, y] - savings * (
                            (newf[r, b, y] + surv[r, b, y]) / food_floor) * (EUC[f, s, b, r, y] / el_ng_ds)
                    EUC[f, s, b, r, y] = max(EUC[f, s, b, r, y], f32(0.0))
                    EUC[f, s, b, 11, y] = EUC[f, s, b, 11, y] + EUC[f, s, b, r, y]
                    FEUC[f, b, r, y] = FEUC[f, b, r, y] + EUC[f, s, b, r, y]
                    UB[f, b, r, y] = FEUC[f, b, r, y]
                    if f == 1:
                        DG[f, s, b, 11, y] = DG[f, s, b, 11, y] + DG[f, s, b, r, y]
    for b in range(1, NUM_BLDG + 1):
        for r in range(1, NUM_DIV + 1):
            FEUC[1, b, r, y] = FEUC[1, b, r, y] - own_adj[b, r]
            UB[1, b, r, y] = FEUC[1, b, r, y]

    US = out["cmusconsumption"]
    for f in range(1, NUM_MAJ_FL + 1):
        US[11, f, y] = 0.0
        for s in range(1, NUM_SERV + 1):
            acc = f32(0.0)
            for r in range(1, NUM_DIV + 1):
                for b in range(1, NUM_BLDG + 1):
                    acc += EUC[f, s, b, r, y]
            US[s, f, y] = acc / f32(1000.0)
            US[11, f, y] = US[11, f, y] + US[s, f, y]
    for s in range(NUM_MAJ_SERV + 1, NUM_SERV):
        for f in range(1, NUM_MAJ_FL + 1):
            out["cmusavgeff"][s, f, y] = 0.0
            num = f32(0.0)
            for r in range(1, NUM_DIV + 1):
                for b in range(1, NUM_BLDG + 1):
                    num += fss[r, b, s, f] * (nsd[s, b, r, y] + rsd[s, b, r, y] + ssd[s, b, r, y])
            den = US[s, f, y] * f32(1000.0)
            if den > 0.0:
                out["cmusavgeff"][s, f, y] = num / den

    # Minor fuels from price regressions.
    prices = {4: inp["prscm"], 5: inp["plgcm"], 6: inp["pclcm"], 7: inp["pmgcm"], 8: inp["pkscm"]}
    alpha, beta = inp["minfuelalpha"], out["minfuelbeta"]
    jpgdp, floor_adj = inp["mc_jpgdp"], inp["flooradj"]
    for r in range(1, NUM_DIV + 1):
        for f in range(NUM_MAJ_FL + 1, NUM_MAJ_FL + NUM_MIN_FL + 1):
            price = f32(0.0)
            if prices[f][r, y] > 0.0:
                price = prices[f][r, y]
            if price == 0.0:
                price = inp["defaultprices"][f]
            if beta[r, f - NUM_MAJ_FL] > 0.0:
                beta[r, f - NUM_MAJ_FL] = 0.0
            temp = np.exp(alpha[r, f - NUM_MAJ_FL] + np.log(price / jpgdp[-2] * jpgdp[2012 - BASEYR + 1])
                          * beta[r, f - NUM_MAJ_FL]) * floor_adj[r]
            temp = f32(temp)
            for b in range(1, NUM_BLDG + 1):
                if f == 6:
                    FEUC[f, b, r, y] = temp * (surv[r, b, CBECS_IDX] + newf[r, b, CBECS_IDX])
                    if FEUC[f, b, r, y] > FEUC[f, b, r, y - 1] * (f32(1.0) + f32(0.03)):
                        FEUC[f, b, r, y] = FEUC[f, b, r, y - 1] * (f32(1.0) + f32(0.03))
                elif f == 8:
                    # EIA quirk: missing parentheses, so new floorspace is added unscaled.
                    FEUC[f, b, r, y] = temp * surv[r, b, CBECS_IDX] + newf[r, b, CBECS_IDX]
                else:
                    FEUC[f, b, r, y] = temp * (surv[r, b, y] + newf[r, b, y])
        for b in range(1, NUM_BLDG + 1):
            for nt in range(1, int(inp["ntek"]) + 1):
                f = int(inp["ifueltype"][nt])
                if f <= 8:
                    continue
                FEUC[f, b, r, y] = FEUC[f, b, r, y] + fu[y, r, b, nt]

    for r in range(1, NUM_DIV + 1):
        for b in range(1, NUM_BLDG + 1):
            for f in range(1, NUM_MAJ_FL + 1):
                CMFU[f, r, y] = CMFU[f, r, y] + UB[f, b, r, y]
                CMF[f, r, y] = CMF[f, r, y] + FEUC[f, b, r, y]
            for f in range(NUM_MAJ_FL + 1, NUM_MAJ_FL + NUM_MIN_FL + NUM_RENEW + 1):
                CMF[f, r, y] = CMF[f, r, y] + FEUC[f, b, r, y]

    # Regional STEO targets for minor fuels, shared by last year's regional split.
    if MSEDYR < y <= LAST_YR_2PCT:
        flag, steo, cmseds = inp["flagregsteo"], inp["steodat"], out["cmseds"]
        nonbldg = out["cmnonbldguse"]
        for f in range(3, NUM_ALL_FL + 1):
            if flag[f] == 0.0 and y >= MSEDYR + 1:
                CMF[f, 11, y] = 0.0
                CMF[f, 11, y - 1] = 0.0
                nonbldg[f, 11, y - 1] = 0.0
                for r in range(1, NUM_DIV + 1):
                    CMF[f, 11, y] = CMF[f, 11, y] + CMF[f, r, y]
                    CMF[f, 11, y - 1] = CMF[f, 11, y - 1] + CMF[f, r, y - 1]
                    nonbldg[f, 11, y - 1] = nonbldg[f, 11, y - 1] + nonbldg[f, r, y - 1]
                for r in range(1, NUM_DIV + 1):
                    cmseds[f, r, y] = steo[f, y - MSEDYR] * (CMF[f, r, y - 1] / CMF[f, 11, y - 1])

    # Solar water heating from technology 20, then building-type totals (label 210).
    src = out["solarrenewablecontrib"]
    eq = inp["equipsd"]
    for r in range(1, NUM_DIV + 1):
        for v in range(1, int(inp["cmnumeqv"][20]) + 1):
            for d in range(1, 4):
                for b in range(1, NUM_BLDG + 1):
                    src[r, 3, y] = src[r, 3, y] + eq[r, b, 20, v, d, y] * f32(0.6) / f32(0.83)
    trills, efficacy = inp["trills"], inp["sunlightefficacy"]
    for b in range(1, NUM_BLDG + 1):
        tot = f32(0.0)
        for r in range(1, NUM_DIV + 1):
            for f in range(1, NUM_MAJ_FL + NUM_MIN_FL + NUM_RENEW + 1):
                tot += FEUC[f, b, r, y]
            for s in range(1, NUM_SOLAR_SERV + 1):
                if s == 6:
                    tot += src[r, s, y] / f32(NUM_BLDG) * (f32(29.916) / efficacy)
                else:
                    tot += src[r, s, y] / f32(NUM_BLDG)
            tot += trills[y, r, b, 1]
            out["solarpvcontrib"][y, r] = out["solarpvcontrib"][y, r] + trills[y, r, b, 1]
        out["cmfinalendusecon"][b, y] = tot / f32(1000.0)
    return out
