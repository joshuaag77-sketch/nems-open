"""Commercial technology choice: port of COMTechnologyChoice (comm.f), after its
first-call file reads.

For each region, major service and building type, it prices every available
technology over its life at each of 7 time-preference (hurdle rate) groups, then
models three kinds of buyer: least cost over all fuels (LC), least cost within
the fuel they already use (SF), and least cost within the technology they
already have (ST). It does this for New buildings, Replacement of retiring
equipment, and Retrofit of equipment still working, then blends the buyers by
BehaviorShare into market shares MS. From those it builds technology and fuel
shares, average efficiency, investment, and the national summaries.

Minor services (office equipment and the rest) just roll efficiency forward.

Loop order and running variables follow the Fortran exactly. EIA's searches
keep a running minimum and switch only on a strictly cheaper option, and some
of those running values carry across loops (see SCOPE.md quirks), so the order
matters for which technology wins a tie or a near tie.

Inputs: Fortran-named arrays as they stand when the routine starts (oracle
state tc_in), plus the iteration-carried values (tc_pre) and /EffInd/ arrays
from service demand. First-call file reads are not ported here; test years
after 2019 already hold the read tables.
"""

from dataclasses import dataclass

import numpy as np

from nems_open.fortran_array import FArray

f32 = np.float32
BASEYR = 1990
CBECS_YEAR = 2018
KSTEOYR = 37
NUM_DIV = 9
NUM_BLDG = 11
NUM_SERV = 10
NUM_MAJ_SERV = 7
NUM_FUEL = 3
NUM_PREF = 7
NUM_DEC = 3
NUM_HP = 5  # CMnumHeatPumpTechs
MAXCOST = f32(10.0 ** 9)
I_EXIST, I_NEW = 1, 2
I_CAP, I_MAINT, I_SUB, I_SUB111D = 1, 2, 3, 4


@dataclass
class Carry:
    """Saved variables that survive between calls and loops (Fortran SAVE)."""
    iforward: list
    ifwd: int
    ifmax: int
    ilaststeoyr: int
    elasbaseyr: int
    keq_ifwd: int = 0  # KEqCost's own saved ifwd; 0 whenever iforward is 0


def _fuel_of(fuelbytech, t):
    """Fortran 'DO f ... IF (FuelbyTech(t,f).EQ.1) iFuel=f': the last flagged fuel."""
    f = None
    for k in range(1, NUM_FUEL + 1):
        if fuelbytech[t, k] == 1:
            f = k
    return f


def _first_fuel_of(fuelbytech, t):
    for k in range(1, NUM_FUEL + 1):
        if fuelbytech[t, k] == 1:
            return k
    return 1


def _ifwd_update(ifwd, avail_first, iforward_f, last_steo):
    if avail_first <= last_steo + 50:
        ifwd = iforward_f
    if avail_first <= last_steo + 10:
        ifwd = max(-5, iforward_f)
    if avail_first <= last_steo + 5:
        ifwd = max(-3, iforward_f)
    if avail_first <= last_steo:
        ifwd = 0
    return ifwd


def keq_cost(inp, carry: Carry, r, t, v, year, ctype="CAP"):
    """KEqCost: capital (or O&M, subsidy) cost on the technology's cost-trend curve."""
    avail = inp["techavailability"]
    tc = inp["techcost"]
    f = _first_fuel_of(inp["fuelbytech"], t)
    carry.keq_ifwd = _ifwd_update(carry.keq_ifwd, int(avail[r, t, v, 1]), carry.iforward[f - 1], carry.ilaststeoyr)
    ifwd = carry.keq_ifwd
    if year < avail[r, t, v, 1] + ifwd or year > avail[r, t, v, 2]:
        return MAXCOST
    col = {"CAP": 1, "O&M": 2, "SUB": 3}[ctype]
    trend = inp["costtrend"][t, v].decode().strip()
    base = tc[r, t, v, col]
    if trend == "Mature":
        return base
    d, gamma = inp["costparam3"][t, v], inp["costparam2"][t, v]
    if trend == "Adolescent":
        y1, y0 = int(inp["costparam1"][t, v]) + ifwd, int(avail[r, t, v, 1]) + ifwd
        return f32(base * f32(2.0) * d / (f32(1.0) + (f32(year - y1) / f32(y0 - y1)) ** gamma) + (f32(1.0) - d) * base)
    if trend == "Infant":
        y1, y0 = int(avail[r, t, v, 1]) + ifwd, int(inp["costparam1"][t, v]) + ifwd
        return f32(base * d / (f32(1.0) + (f32(year - y1) / f32(y0 - y1)) ** gamma) + (f32(1.0) - d) * base)
    return MAXCOST


def technology_choice(inp: dict, carry: Carry, y: int) -> dict:
    """One non-first call of COMTechnologyChoice for year index y. Returns the
    arrays it writes, as Fortran-indexed copies."""
    year = BASEYR - 1 + y
    techs_for, n_techs = inp["techsforservice"], inp["cmnumtechsforservice"]
    n_vint, by_model = inp["cmnumeqv"], inp["techbymodel"]
    fuelbytech, techbyservice = inp["fuelbytech"], inp["techbyservice"]
    life, tc, eff = inp["techlife"], inp["techcost"], inp["techeff"]
    avail, restrict = inp["techavailability"], inp["equiprestriction"]
    capfac, cri = inp["capacityfactor"], inp["techcri"]
    tpp, tpprem = inp["timeprefprop"], inp["timeprefprem"]
    hurdle_elas, bshare = inp["hurdleelas"], inp["behaviorshare"]
    retro_frac = inp["retrocostfract"]
    prev_tss, prev_fss, prev_ae = (inp["prevyrtechshareofservice"], inp["prevyrfuelshareofservice"],
                                   inp["prevyraverageefficiency"])
    pelcm, pngcm, pdscm, pelcmout = inp["pelcm"], inp["pngcm"], inp["pdscm"], inp["pelcmout"]
    rmgblus, jpgdp = inp["mc_rmgblusreal"], inp["mc_jpgdp"]
    shell_h, shell_c = inp["shellheatfactor"], inp["shellcoolfactor"]
    degreedays = inp["degreedays"]
    cost_trend_on = int(inp["costtrendswitch"]) == 1
    st_ret = int(inp["stretbehav"]) == 1
    cooling_hp = int(inp["coolingtechindexhp"])
    ik = int(inp["iktechcostyr"])

    out = {k: inp[k].copy() for k in (
        "ms", "nsd", "rsd", "ssd", "techshareofservice", "fuelshareofservice", "averageefficiency",
        "investcost", "fedsubsidyinvestcost", "nonfedsubsidyinvestcost", "subsidyinvestcost",
        "subsidy111dinvestcost", "decfuelshare", "decavgeff", "equipsd", "purchtechshare",
        "sdbyfuel", "whse_eff", "whse_sd", "whse_shellindex", "whse_heatindex", "whse_ventindex",
        "whse_lightindex", "cmusavgeff", "cmuspurcheff")}
    MS, NSD, RSD, SSD = out["ms"], out["nsd"], out["rsd"], out["ssd"]
    TSS, FSS, AVE = out["techshareofservice"], out["fuelshareofservice"], out["averageefficiency"]
    nsd_ns, rsd_ns, ssd_ns = inp["nsdnoshell"], inp["rsdnoshell"], inp["ssdnoshell"]

    # Per-year setup.
    out["equipsd"].a[..., y - out["equipsd"].lb[5]] = 0.0
    for name in ("investcost", "fedsubsidyinvestcost", "nonfedsubsidyinvestcost", "subsidyinvestcost",
                 "subsidy111dinvestcost"):
        out[name][:, 1:NUM_MAJ_SERV, :, y] = 0.0
    ebase = carry.elasbaseyr
    pd3 = [f32(0.0)] * 3
    if y > KSTEOYR:
        pd3[0] = f32((pelcm[11, y] + pelcm[11, y - 1] + pelcm[11, y - 2]) / f32(3.0)) / pelcm[11, ebase]
        pd3[1] = f32((pngcm[11, y] + pngcm[11, y - 1] + pngcm[11, y - 2]) / f32(3.0)) / pngcm[11, ebase]
        pd3[2] = f32((pdscm[11, y] + pdscm[11, y - 1] + pdscm[11, y - 2]) / f32(3.0)) / pdscm[11, ebase]
        for f in range(3):
            # ifwd is only reset from iforward on the first iteration.
            carry.iforward[f] = max(carry.ifmax, min(carry.ifwd, -int((pd3[f] - f32(1.0)) / f32(0.10))))
    carry.elasbaseyr = ebase = CBECS_YEAR - (BASEYR - 1)
    last_steo = carry.ilaststeoyr = KSTEOYR + BASEYR - 1

    shape_tv = (inp["techlife"].a.shape[0] + 1, inp["techlife"].a.shape[1] + 1)
    NT, NV = shape_tv
    act = np.full((NUM_PREF + 1, NT, NV, 3), MAXCOST, dtype=np.float32)   # AnnualCostTech
    acta = np.full((NUM_PREF + 1, NT, NV, 3), MAXCOST, dtype=np.float32)  # AnnualCostTechAdj
    whse_eff, whse_sd = out["whse_eff"], out["whse_sd"]

    for r in range(1, NUM_DIV + 1):
        for s in range(1, NUM_MAJ_SERV + 1):
            conv = f32(8.76)
            price_delta = [f32(0.0)] * 3
            if pelcmout[r, ebase, s] > 0.0:
                price_delta[0] = pelcmout[r, y, s] / pelcmout[r, ebase, s]
            if pngcm[r, ebase] > 0.0:
                price_delta[1] = pngcm[r, y] / pngcm[r, ebase]
            if pdscm[r, ebase] > 0.0:
                price_delta[2] = pdscm[r, y] / pdscm[r, ebase]
            tlist = [int(techs_for[s, k]) for k in range(1, int(n_techs[s]) + 1)]
            L = [(t, v) for t in tlist for v in range(1, int(n_vint[t]) + 1) if by_model[t, v] == 1]
            Lt = {t: [v for (tt, v) in L if tt == t] for t in tlist}
            fuel = {t: _fuel_of(fuelbytech, t) for t in tlist}

            def local_price(f):
                return (pelcmout[r, y, s], pngcm[r, y], pdscm[r, y])[f - 1]

            reg_fs_num = {}
            for b in range(1, NUM_BLDG + 1):
                if s < 3:
                    sh = shell_h if s == 1 else shell_c
                    shell = {I_EXIST: sh[b, r, 1, y], I_NEW: sh[b, r, 2, y]}
                else:
                    shell = {I_EXIST: f32(1.0), I_NEW: f32(1.0)}

                # Retiring and surviving shares of last year's equipment.
                rp = f32(0.0)
                for t, v in L:
                    if life[t, v] > 0.0:
                        rp += prev_tss[r, b, s, t, v] / life[t, v]
                surv_fs = [f32(0.0)] * (NUM_FUEL + 1)
                repl_fs = [f32(0.0)] * (NUM_FUEL + 1)
                surv_sh, repl_sh = {}, {}
                for t, v in L:
                    surv_sh[t, v] = f32(0.0)
                    repl_sh[t, v] = f32(0.0)
                    if life[t, v] > 0.0 and (f32(1.0) - rp) > 0.0:
                        surv_sh[t, v] = prev_tss[r, b, s, t, v] * (f32(1.0) - (f32(1.0) / life[t, v])) / (f32(1.0) - rp)
                        for f in range(1, NUM_FUEL + 1):
                            surv_fs[f] += surv_sh[t, v] * fuelbytech[t, f]
                    if life[t, v] > 0.0 and rp > 0.0:
                        repl_sh[t, v] = prev_tss[r, b, s, t, v] * (f32(1.0) / life[t, v]) / rp
                        for f in range(1, NUM_FUEL + 1):
                            repl_fs[f] += repl_sh[t, v] * fuelbytech[t, f]

                # Annualized cost of every technology (label 90).
                for t in tlist:
                    f = fuel[t]
                    for v in Lt[t]:
                        carry.ifwd = _ifwd_update(carry.ifwd, int(avail[r, t, v, 1]), carry.iforward[f - 1], last_steo)
                        unavailable = (tc[r, t, v, I_CAP] == MAXCOST or year < avail[r, t, v, 1] + carry.ifwd
                                       or year > avail[r, t, v, 2] or restrict[t, v, b, r] == 1
                                       or techbyservice[s, t] == 0)
                        for p in range(1, NUM_PREF + 1):
                            if unavailable:
                                act[p, t, v, 1:3] = MAXCOST
                                acta[p, t, v, 1:3] = MAXCOST
                                continue
                            eh = rmgblus[y] / f32(100.0) + tpprem[s, p, y]
                            if eh < 0.03:
                                eh = (f32(0.03) - eh) + eh
                            eha = eh
                            if price_delta[f - 1] > 1.0 and eh > 0.15:
                                eha = (eh - f32(0.15)) * price_delta[f - 1] ** hurdle_elas[r, s, f] + f32(0.15)
                            cap = keq_cost(inp, carry, r, t, v, year) if cost_trend_on else tc[r, t, v, I_CAP]
                            tl = life[t, v]
                            ca = cap / capfac[r, b, s] * eha / (f32(1.0) - (f32(1.0) + eha) ** (f32(-1.0) * tl))
                            c = cap / capfac[r, b, s] * eh / (f32(1.0) - (f32(1.0) + eh) ** (f32(-1.0) * tl))
                            ca = ca + tc[r, t, v, I_MAINT]
                            c = c + tc[r, t, v, I_MAINT]
                            ep = local_price(f) * jpgdp[ik] / jpgdp[-2]
                            if s == 6:
                                conv = (f32(1.0) / f32(0.03343)) / cri[r, s, t, v]
                            act[p, t, v, I_NEW], acta[p, t, v, I_NEW] = c, ca
                            fuel_e = ep / eff[r, s, t, v] * conv * shell[I_EXIST]
                            acta[p, t, v, I_EXIST] = ca + fuel_e
                            act[p, t, v, I_EXIST] = c + fuel_e
                            if s < 3:
                                fuel_n = ep / eff[r, s, t, v] * conv * shell[I_NEW]
                                acta[p, t, v, I_NEW] = ca + fuel_n
                                act[p, t, v, I_NEW] = c + fuel_n

                # New and Replacement: least-cost searches (label 100).
                sides = (I_EXIST, I_NEW) if s < 3 else (I_EXIST,)
                lc_af = {}  # (p, side) -> (t, v)
                lc_sf = {}  # (p, f, side) -> (t, v) or (0, 0)
                lcv_st = {}  # (p, t, side) -> v or 0
                for p in range(1, NUM_PREF + 1):
                    t1 = tlist[0]
                    for side in sides:
                        best, arg = act[p, t1, 1, side], (t1, 1)
                        for t, v in L:
                            if act[p, t, v, side] < best:
                                best, arg = act[p, t, v, side], (t, v)
                        lc_af[p, side] = (arg, best)
                    min_sf = {(f, sd): MAXCOST for f in range(1, 4) for sd in sides}
                    sf_arg = {(f, sd): (0, 0) for f in range(1, 4) for sd in sides}
                    fuel_started = False
                    for t in tlist:
                        f = fuel[t]
                        st_min = {sd: acta[p, t, 1, sd] for sd in sides}
                        st_arg = {sd: 1 for sd in sides}
                        if not fuel_started:  # EIA: isFuelNew=1 marks every fuel
                            fuel_started = True
                            for sd in sides:
                                min_sf[f, sd], sf_arg[f, sd] = acta[p, t, 1, sd], (t, 1)
                        for v in Lt[t]:
                            for sd in sides:
                                if acta[p, t, v, sd] < st_min[sd]:
                                    st_min[sd], st_arg[sd] = acta[p, t, v, sd], v
                                if acta[p, t, v, sd] < min_sf[f, sd]:
                                    min_sf[f, sd], sf_arg[f, sd] = acta[p, t, v, sd], (t, v)
                        for sd in sides:
                            lcv_st[p, t, sd] = 0 if st_min[sd] == MAXCOST else st_arg[sd]
                    for f in range(1, 4):
                        for sd in sides:
                            lc_sf[p, f, sd] = (0, 0) if min_sf[f, sd] == MAXCOST else sf_arg[f, sd]
                    # Second pass: cheapest adjusted cost within the cheapest fuel.
                    for sd in sides:
                        (t0, v0), best = lc_af[p, sd]
                        f_min = fuel[t0]
                        arg = (t0, v0)
                        for t in tlist:
                            if fuelbytech[t, f_min] == 1:
                                for v in Lt[t]:
                                    if acta[p, t, v, sd] < best:
                                        best, arg = acta[p, t, v, sd], (t, v)
                        lc_af[p, sd] = (arg, best)

                tp = {p: tpp[s, p, y] for p in range(1, NUM_PREF + 1)}
                lcmsn, lcmsr, sfmsn, sfmsr, stmsn, stmsr = ({tv: f32(0.0) for tv in L} for _ in range(6))
                new_side = I_NEW if s < 3 else I_EXIST
                for t, v in L:
                    for p in range(1, NUM_PREF + 1):
                        if lc_af[p, I_EXIST][0] == (t, v):
                            lcmsr[t, v] += tp[p]
                        if lc_af[p, new_side][0] == (t, v):
                            lcmsn[t, v] += tp[p]
                    for f in range(1, 4):
                        for p in range(1, NUM_PREF + 1):
                            if s < 3:
                                if lc_sf[p, f, I_EXIST] == (t, v):
                                    sfmsr[t, v] += tp[p] * repl_fs[f]
                                if lc_sf[p, f, I_NEW] == (t, v):
                                    sfmsn[t, v] += tp[p] * prev_fss[r, b, s, f]
                            elif lc_sf[p, f, I_EXIST] == (t, v):
                                sfmsn[t, v] += tp[p] * prev_fss[r, b, s, f]
                                sfmsr[t, v] += tp[p] * repl_fs[f]
                for t in tlist:
                    share_n = f32(0.0)
                    share_r = f32(0.0)
                    for v in Lt[t]:
                        share_n += prev_tss[r, b, s, t, v]
                        share_r += repl_sh[t, v]
                    for v in Lt[t]:
                        for p in range(1, NUM_PREF + 1):
                            if s < 3:
                                if lcv_st[p, t, I_EXIST] == v:
                                    stmsr[t, v] += tp[p]
                                if lcv_st[p, t, I_NEW] == v:
                                    stmsn[t, v] += tp[p]
                            elif lcv_st[p, t, I_EXIST] == v:
                                stmsn[t, v] += tp[p]
                                stmsr[t, v] += tp[p]
                        stmsn[t, v] = stmsn[t, v] * share_n
                        stmsr[t, v] = stmsr[t, v] * share_r
                for t, v in L:
                    MS[b, s, 1, t, v] = (bshare[s, b, 1, 1] * lcmsn[t, v] + bshare[s, b, 1, 2] * sfmsn[t, v]
                                         + bshare[s, b, 1, 3] * stmsn[t, v])
                for t, v in L:
                    MS[b, s, 2, t, v] = (bshare[s, b, 2, 1] * lcmsr[t, v] + bshare[s, b, 2, 2] * sfmsr[t, v]
                                         + bshare[s, b, 2, 3] * stmsr[t, v])

                # Retrofit: cost of keeping existing equipment (label 180).
                ace = {}
                for p in range(1, NUM_PREF + 1):
                    for t, v in L:
                        if year < avail[r, t, v, 1] + carry.ifwd or tc[r, t, v, I_CAP] == MAXCOST:
                            ace[t, v, p] = MAXCOST
                            continue
                        f = fuel[t]
                        cv = f32(8.76)
                        eh = rmgblus[y] / f32(100.0) + tpprem[s, p, y]
                        if price_delta[f - 1] > 1.0 and eh > 0.15:
                            eh = (eh - f32(0.15)) * price_delta[f - 1] ** hurdle_elas[r, s, f] + f32(0.15)
                        a = tc[r, t, v, I_MAINT]
                        a = a - retro_frac[t, v] * tc[r, t, v, I_CAP] / capfac[r, b, s] * eh / (
                            f32(1.0) - (f32(1.0) + eh) ** (f32(-1.0) * life[t, v]))
                        ep = local_price(f) * jpgdp[ik] / jpgdp[-2]
                        if s == 6:
                            cv = (f32(1.0) / f32(0.03343)) / cri[r, s, t, v]
                        ace[t, v, p] = a + ep / eff[r, s, t, v] * cv * shell[I_EXIST]

                ret_sf, ret_af, ret_st = {}, {}, {}
                min_af = None  # carried past this loop into the next (EIA quirk)
                for p in range(1, NUM_PREF + 1):
                    for t, v in L:
                        if ace[t, v, p] == MAXCOST:
                            ret_sf[p, t, v] = ret_af[p, t, v] = (0, 0)
                            ret_st[p, t, v] = 0
                            continue
                        f = fuel[t]
                        m_sf, a_sf = ace[t, v, p], (t, v)
                        m_af, a_af = ace[t, v, p], (t, v)
                        m_st, a_st = ace[t, v, p], v
                        if st_ret:
                            for vint in Lt[t]:
                                if acta[p, t, vint, I_EXIST] < m_st:
                                    m_st, a_st = acta[p, t, vint, I_EXIST], vint
                        for tech, vint in L:
                            if acta[p, tech, vint, I_EXIST] < m_sf and fuelbytech[tech, f] == 1:
                                m_sf, a_sf = acta[p, tech, vint, I_EXIST], (tech, vint)
                            if act[p, tech, vint, I_EXIST] < m_af:
                                m_af, a_af = act[p, tech, vint, I_EXIST], (tech, vint)
                        ret_sf[p, t, v], ret_af[p, t, v], ret_st[p, t, v] = a_sf, a_af, a_st
                        min_af = m_af
                for p in range(1, NUM_PREF + 1):
                    for t, v in L:
                        if ace[t, v, p] < MAXCOST:
                            f_min = fuel[ret_af[p, t, v][0]]
                            for tech in tlist:
                                if fuelbytech[tech, f_min] == 1:
                                    for vint in Lt[tech]:
                                        if acta[p, tech, vint, I_EXIST] < min_af:
                                            min_af = acta[p, tech, vint, I_EXIST]
                                            ret_af[p, t, v] = (tech, vint)

                lcm_ret = {tv: f32(0.0) for tv in L}
                sfm_ret = {tv: f32(0.0) for tv in L}
                stm_ret = {tv: f32(0.0) for tv in L}
                for t, v in L:
                    for tech, vint in L:
                        for p in range(1, NUM_PREF + 1):
                            if ret_af[p, tech, vint] == (t, v):
                                lcm_ret[t, v] += surv_sh[tech, vint] * tp[p]
                for t, v in L:
                    for tech, vint in L:
                        for p in range(1, NUM_PREF + 1):
                            if ret_sf[p, tech, vint] == (t, v):
                                sfm_ret[t, v] += surv_sh[tech, vint] * tp[p]
                for t, v in L:
                    if st_ret:
                        for vint in Lt[t]:
                            for p in range(1, NUM_PREF + 1):
                                if ret_st[p, t, vint] == v:
                                    stm_ret[t, v] += surv_sh[t, vint] * tp[p]
                    else:
                        stm_ret[t, v] = surv_sh[t, v]
                for t, v in L:
                    MS[b, s, 3, t, v] = (bshare[s, b, 3, 1] * lcm_ret[t, v] + bshare[s, b, 3, 2] * sfm_ret[t, v]
                                         + bshare[s, b, 3, 3] * stm_ret[t, v])

                NSD[r, b, s, y] = inp["newservdmd"][s, b, r, y]
                RSD[r, b, s, y] = inp["retireservdmd"][s, b, r, y]
                SSD[r, b, s, y] = inp["servdmdsurv"][s, b, r, y]

                # Heat pumps chosen for heating also cool (label after 240).
                if s == 2:
                    SD = {(svc, 1): NSD[r, b, svc, y] for svc in (1, 2)}
                    SD.update({(svc, 2): RSD[r, b, svc, y] for svc in (1, 2)})
                    SD.update({(svc, 3): SSD[r, b, svc, y] for svc in (1, 2)})
                    for t in range(1, NUM_HP + 1):
                        if techbyservice[1, t] == 1:
                            for v in range(1, int(n_vint[t]) + 1):
                                if by_model[t, v] == 1:
                                    for d in range(1, NUM_DEC + 1):
                                        if SD[2, d] > 0.0:
                                            MS[b, 2, d, t + NUM_HP, v] = (MS[b, 1, d, t, v] * SD[1, d]
                                                                         * degreedays[2, r, y] / degreedays[1, r, y]
                                                                         / SD[2, d])
                                        else:
                                            MS[b, 2, d, t + NUM_HP, v] = 0.0
                    hp_sd = {}
                    for d in range(1, NUM_DEC + 1):
                        acc = f32(0.0)
                        for t in range(1, NUM_HP + 1):
                            if techbyservice[1, t] == 1:
                                for v in range(1, int(n_vint[t]) + 1):
                                    if by_model[t, v] == 1:
                                        acc += MS[b, 2, d, t + NUM_HP, v] * SD[2, d]
                        hp_sd[d] = acc
                    norm = {}
                    for d in range(1, NUM_DEC + 1):
                        acc = f32(0.0)
                        for t in tlist:
                            if t > 2 * NUM_HP:
                                for v in Lt[t]:
                                    acc += MS[b, 2, d, t, v]
                        norm[d] = acc
                    for t in tlist:
                        if t > 2 * NUM_HP:
                            for v in Lt[t]:
                                for d in range(1, NUM_DEC + 1):
                                    if norm[d] > 0.0:
                                        MS[b, 2, d, t, v] = MS[b, 2, d, t, v] / norm[d]
                                    if SD[2, d] > 0.0:
                                        MS[b, 2, d, t, v] = MS[b, 2, d, t, v] * (SD[2, d] - hp_sd[d]) / SD[2, d]

                # Investment in purchased equipment (label 314).
                ird = {}
                purch_sd = f32(0.0)
                prt_sd = f32(0.0)
                for t in tlist:
                    for v in range(1, int(n_vint[t]) + 1):
                        ird[t, v] = f32(0.0)
                        if by_model[t, v] != 1:
                            continue
                        f = fuel[t]
                        carry.ifwd = _ifwd_update(carry.ifwd, int(avail[r, t, v, 1]), carry.iforward[f - 1], last_steo)
                        if (tc[r, t, v, I_CAP] == MAXCOST or year < avail[r, t, v, 1] + carry.ifwd
                                or year > avail[r, t, v, 2] or restrict[t, v, b, r] == 1 or techbyservice[s, t] == 0):
                            continue
                        ird[t, v] = max(f32(0.0), SSD[r, b, s, y] * (MS[b, s, 3, t, v] - surv_sh[t, v]))
                        invest = MS[b, s, 1, t, v] * NSD[r, b, s, y] + MS[b, s, 2, t, v] * RSD[r, b, s, y] + ird[t, v]
                        if t <= NUM_HP and s == 2:
                            continue
                        if cost_trend_on:
                            if t <= NUM_HP:
                                hp = keq_cost(inp, carry, r, cooling_hp, v, year)
                                if hp == MAXCOST:
                                    hp = tc[r, cooling_hp, v, I_CAP]
                                tic = keq_cost(inp, carry, r, t, v, year) + hp
                            else:
                                tic = keq_cost(inp, carry, r, t, v, year)
                        elif t <= NUM_HP:
                            tic = tc[r, t, v, I_CAP] + tc[r, cooling_hp, v, I_CAP]
                        else:
                            tic = tc[r, t, v, I_CAP]
                        cpk = (tic / f32(8760.0)) / capfac[r, b, s]
                        s111 = (tc[r, t, v, I_SUB111D] / f32(8760.0)) / capfac[r, b, s]
                        fi = _first_fuel_of(fuelbytech, t)
                        out["investcost"][r, s, fi, y] += invest * cpk
                        sub = (tc[r, t, v, I_SUB] / f32(8760.0)) / capfac[r, b, s]
                        if cri[r, s, t, v] == 2.0:
                            out["fedsubsidyinvestcost"][r, s, fi, y] += invest * sub
                        else:
                            out["nonfedsubsidyinvestcost"][r, s, fi, y] += invest * sub
                        out["subsidyinvestcost"][r, s, fi, y] = (out["fedsubsidyinvestcost"][r, s, fi, y]
                                                                 + out["nonfedsubsidyinvestcost"][r, s, fi, y])
                        out["subsidy111dinvestcost"][r, s, fi, y] += invest * s111
                        purch_sd += invest
                        prt_sd += ird[t, v]

                # Fuel shares and efficiency by decision (label 270).
                FS, AE, fsprt = {}, {}, {}
                for d in range(1, NUM_DEC + 1):
                    for f in range(1, NUM_FUEL + 1):
                        fs = f32(0.0)
                        fp = f32(0.0)
                        for t, v in L:
                            fs += MS[b, s, d, t, v] * fuelbytech[t, f]
                            if d == 3 and SSD[r, b, s, y] > 0.0:
                                fp += ird[t, v] / SSD[r, b, s, y] * fuelbytech[t, f]
                        den = f32(0.0)
                        for t, v in L:
                            if eff[r, s, t, v] > 0.0:
                                den += MS[b, s, d, t, v] * fuelbytech[t, f] / eff[r, s, t, v]
                        FS[d, f] = fs
                        AE[d, f] = fs / den if den > 0.0 else f32(0.0)
                        fsprt[f] = fp
                tot = NSD[r, b, s, y] + RSD[r, b, s, y] + SSD[r, b, s, y]
                for f in range(1, NUM_FUEL + 1):
                    FSS[r, b, s, f] = 0.0
                    out["sdbyfuel"][f, s, b, r, y] = 0.0
                    if tot > 0.0:
                        FSS[r, b, s, f] = (NSD[r, b, s, y] * FS[1, f] + RSD[r, b, s, y] * FS[2, f]
                                           + SSD[r, b, s, y] * FS[3, f]) / tot
                        out["sdbyfuel"][f, s, b, r, y] = (nsd_ns[r, b, s] * FS[1, f] + rsd_ns[r, b, s] * FS[2, f]
                                                          + ssd_ns[r, b, s] * FS[3, f])
                for t, v in L:
                    TSS[r, b, s, t, v] = 0.0
                    out["purchtechshare"][r, b, s, t, v] = 0.0
                    if tot > 0.0:
                        TSS[r, b, s, t, v] = (NSD[r, b, s, y] * MS[b, s, 1, t, v] + RSD[r, b, s, y] * MS[b, s, 2, t, v]
                                              + SSD[r, b, s, y] * MS[b, s, 3, t, v]) / tot
                    if purch_sd > 0.0:
                        out["purchtechshare"][r, b, s, t, v] = (
                            NSD[r, b, s, y] * MS[b, s, 1, t, v] + RSD[r, b, s, y] * MS[b, s, 2, t, v]
                            + prt_sd * (ird[t, v] / SSD[r, b, s, y])) / purch_sd
                for f in range(1, NUM_FUEL + 1):
                    den = f32(0.0)
                    for t, v in L:
                        if eff[r, s, t, v] > 0.0:
                            den += TSS[r, b, s, t, v] * fuelbytech[t, f] / eff[r, s, t, v]
                    AVE[r, b, s, f] = FSS[r, b, s, f] / den if den > 0.0 else prev_ae[r, b, s, f]
                    if b == 10:
                        whse_eff[r, s, f, y] = AVE[r, 10, s, f]
                        whse_sd[r, s, f, y] = out["sdbyfuel"][f, s, 10, r, y]
                eq = out["equipsd"]
                for t in tlist:
                    for v in range(1, int(n_vint[t]) + 1):
                        for d, dmd in ((1, NSD[r, b, s, y]), (2, RSD[r, b, s, y]), (3, SSD[r, b, s, y])):
                            add = MS[b, s, d, t, v] * dmd
                            eq[r, b, t, v, d, y] += add
                            eq[11, b, t, v, d, y] += add
                reg_fs_num[b] = (FS, AE)

            # Decision-type fuel shares and efficiency for the region (labels 340, 350).
            for f in range(1, NUM_FUEL + 1):
                for d in range(1, NUM_DEC + 1):
                    dmd = {1: NSD, 2: RSD, 3: SSD}[d]
                    num = f32(0.0)
                    den = f32(0.0)
                    for b in range(1, NUM_BLDG + 1):
                        num += reg_fs_num[b][0][d, f] * dmd[r, b, s, y]
                        den += dmd[r, b, s, y]
                    out["decfuelshare"][r, s, d, f, y] = num / den if den > 0.0 else f32(0.0)
                    num = f32(0.0)
                    den = f32(0.0)
                    for b in range(1, NUM_BLDG + 1):
                        FS, AE = reg_fs_num[b]
                        if AE[d, f] > 0.0:
                            num += FS[d, f] * dmd[r, b, s, y]
                            den += FS[d, f] * dmd[r, b, s, y] / AE[d, f]
                    out["decavgeff"][r, s, d, f, y] = num / den if den > 0.0 else f32(0.0)
            for f in range(1, NUM_FUEL + 1):
                for name in ("investcost", "subsidyinvestcost", "subsidy111dinvestcost"):
                    out[name][11, s, f, y] += out[name][r, s, f, y]

    # Warehouse indices by group of census divisions.
    sh = out["whse_shellindex"]
    sh[1, y] = shell_h[10, 1:2, 1, y].sum(dtype=np.float32) / f32(2)
    sh[2, y] = shell_h[10, 3:4, 1, y].sum(dtype=np.float32) / f32(2)
    sh[3, y] = shell_h[10, 5:7, 1, y].sum(dtype=np.float32) / f32(3)
    sh[4, y] = shell_h[10, 8:9, 1, y].sum(dtype=np.float32) / f32(2)
    groups = [(1, 2), (3, 4), (5, 7), (8, 9)]

    def index(s, f, g):
        lo, hi = g
        sd = whse_sd[lo:hi, s, f, y]
        den = (sd * whse_eff[lo:hi, s, f, y]).sum(dtype=np.float32)
        return sd.sum(dtype=np.float32) / den if den != 0.0 else f32(0.0)

    for f in range(1, 4):
        for k, g in enumerate(groups, 1):
            out["whse_heatindex"][k, f, y] = index(1, f, g)
    for k in range(1, 5):
        out["whse_heatindex"][k, 4, y] = out["whse_heatindex"][k, 3, y]
        out["whse_heatindex"][k, 5, y] = out["whse_heatindex"][k, 3, y]
    for k, g in enumerate(groups, 1):
        out["whse_ventindex"][k, y] = index(4, 1, g)
        out["whse_lightindex"][k, y] = index(6, 1, g)

    # US average efficiency of the stock and of this year's purchases (label 360).
    for s in range(1, NUM_MAJ_SERV + 1):
        tlist = [int(techs_for[s, k]) for k in range(1, int(n_techs[s]) + 1)]
        L = [(t, v) for t in tlist for v in range(1, int(n_vint[t]) + 1) if by_model[t, v] == 1]
        for f in range(1, NUM_FUEL + 1):
            num = den = nump = denp = f32(0.0)
            for r in range(1, NUM_DIV + 1):
                for b in range(1, NUM_BLDG + 1):
                    tot = NSD[r, b, s, y] + RSD[r, b, s, y] + SSD[r, b, s, y]
                    num += FSS[r, b, s, f] * tot
                    for t, v in L:
                        if eff[r, s, t, v] > 0.0:
                            den += TSS[r, b, s, t, v] * fuelbytech[t, f] / eff[r, s, t, v] * tot
            out["cmusavgeff"][s, f, y] = num / den if den > 0.0 else f32(0.0)

    # Minor services: efficiency rolls forward at a fixed rate (label 9100).
    growth = inp["effgrowthrate"]
    fs_base, inten = inp["fuelshareofservicebase"], inp["servdmdintenbase"]
    surv, newf = inp["survfloortotal"], inp["cmnewfloorspace"]
    sd_surv, nd = inp["servdmdsurv"], inp["newservdmd"]
    for s in range(NUM_MAJ_SERV + 1, NUM_SERV + 1):
        for r in range(1, NUM_DIV + 1):
            for b in range(1, NUM_BLDG + 1):
                AVE[r, b, s, 1] = prev_ae[r, b, s, 1] * (f32(1.0) + growth[s])
                FSS[r, b, s, 1] = 1.0
                if s == NUM_SERV:
                    for f in range(2, NUM_FUEL + 1):
                        FSS[r, b, s, f] = (fs_base[r, b, s, f] * inten[s, b, r] / f32(1000.0)
                                           * (surv[r, b, y] + newf[r, b, y])) / (sd_surv[s, b, r, y] + nd[s, b, r, y])
                        FSS[r, b, s, 1] = FSS[r, b, s, 1] - FSS[r, b, s, f]
            if s < NUM_SERV:
                for d in range(1, NUM_DEC + 1):
                    out["decavgeff"][r, s, d, 1, y] = AVE[r, 1, s, 1]
                    out["decfuelshare"][r, s, d, 1, y] = 1.0
            else:
                for f in range(1, NUM_FUEL + 1):
                    num = den = f32(0.0)
                    for b in range(1, NUM_BLDG + 1):
                        num += FSS[r, b, s, f] * (nd[s, b, r, y] + sd_surv[s, b, r, y])
                        den += nd[s, b, r, y] + sd_surv[s, b, r, y]
                    rfs = num / den if den > 0.0 else f32(0.0)
                    for d in range(1, NUM_DEC + 1):
                        out["decavgeff"][r, s, d, f, y] = AVE[r, 1, s, f]
                        out["decfuelshare"][r, s, d, f, y] = rfs
    return out
