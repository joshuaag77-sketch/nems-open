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
    arrays it writes, as Fortran-indexed copies.

    Runs the fast version whenever price-induced technical change is idle (iforward,
    ifwd and IFMAX all 0, as in every AEO2026 year), and the line-by-line reference
    version otherwise. Both give identical arrays."""
    idle = (carry.ifwd == 0 and carry.keq_ifwd == 0 and carry.ifmax <= 0 and not any(carry.iforward))
    return _technology_choice_fast(inp, carry, y) if idle else _technology_choice_reference(inp, carry, y)


def _pad(a: np.ndarray) -> np.ndarray:
    """A copy with one leading zero row on every axis, so Fortran's 1-based indices index it directly."""
    return np.pad(a, [(1, 0)] * a.ndim)


def _first_min(vals: np.ndarray, init):
    """A Fortran running minimum that switches only on a strictly smaller value, over `vals`
    in order, starting from `init`: (index of the winner, or -1 if init stands; the minimum)."""
    if vals.size == 0:
        return -1, init
    k = int(np.argmin(vals))  # argmin returns the first of equal minima, as the strict test keeps the first
    return (k, vals[k]) if vals[k] < init else (-1, init)


def _seq_total(terms: np.ndarray):
    """A Fortran running sum from 0.0 (float32) over `terms` in order: the last element of a
    sequential accumulate in the terms' dtype, or float32 zero if there are none."""
    return np.add.accumulate(terms)[-1] if terms.size else f32(0.0)


def _technology_choice_fast(inp: dict, carry: Carry, y: int) -> dict:
    """technology_choice with the searches done by argmin and the per-building work on plain arrays.

    With iforward and ifwd at 0 the availability tests and KEqCost do not depend on loop order,
    so costs are computed once per region and service and reused for every building type. The
    running-minimum searches become first-argmin lookups (same winner, same value), and the share
    sums add each contribution to its target in the same order as the Fortran's nested loops.
    Arithmetic keeps the reference version's numpy types, including the float64 that int flags
    bring in, so every array comes out identical."""
    year = BASEYR - 1 + y
    P = lambda k: _pad(inp[k].a)
    techs_for, n_techs, n_vint, by_model = P("techsforservice"), P("cmnumtechsforservice"), P("cmnumeqv"), P("techbymodel")
    fuelbytech, techbyservice = P("fuelbytech"), P("techbyservice")
    life, tc, eff = P("techlife"), P("techcost"), P("techeff")
    avail, restrict = P("techavailability"), P("equiprestriction")
    capfac, cri = P("capacityfactor"), P("techcri")
    tpp, tpprem = P("timeprefprop"), P("timeprefprem")
    hurdle_elas, bshare = P("hurdleelas"), P("behaviorshare")
    retro_frac = P("retrocostfract")
    prev_tss, prev_fss, prev_ae = P("prevyrtechshareofservice"), P("prevyrfuelshareofservice"), P("prevyraverageefficiency")
    pelcm, pngcm, pdscm, pelcmout = P("pelcm"), P("pngcm"), P("pdscm"), P("pelcmout")
    rmgblus = P("mc_rmgblusreal")
    jpgdp = inp["mc_jpgdp"]
    yl = lambda k: inp[k].a[..., y - inp[k].lb[-1]]  # this year's slice of an array whose last axis is year
    sh_h = _pad(yl("shellheatfactor"))
    sh_c = _pad(yl("shellcoolfactor"))
    degreedays = P("degreedays")
    nd_in, rd_in, sd_in = _pad(yl("newservdmd")), _pad(yl("retireservdmd")), _pad(yl("servdmdsurv"))
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
    nsd_ns, rsd_ns, ssd_ns = P("nsdnoshell"), P("rsdnoshell"), P("ssdnoshell")

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
            carry.iforward[f] = max(carry.ifmax, min(carry.ifwd, -int((pd3[f] - f32(1.0)) / f32(0.10))))
    carry.elasbaseyr = ebase = CBECS_YEAR - (BASEYR - 1)
    carry.ilaststeoyr = KSTEOYR + BASEYR - 1

    # Work on padded copies of what is written, put back at the end.
    MS, TSS, FSS, AVE = _pad(out["ms"].a), _pad(out["techshareofservice"].a), _pad(out["fuelshareofservice"].a), \
        _pad(out["averageefficiency"].a)
    PTS = _pad(out["purchtechshare"].a)
    NSD, RSD, SSD = _pad(yl("nsd").copy()), _pad(yl("rsd").copy()), _pad(yl("ssd").copy())
    ys = {k: _pad(out[k].a[..., y - out[k].lb[-1]]) for k in (
        "investcost", "fedsubsidyinvestcost", "nonfedsubsidyinvestcost", "subsidyinvestcost",
        "subsidy111dinvestcost", "decfuelshare", "decavgeff", "sdbyfuel", "whse_eff", "whse_sd", "cmusavgeff")}
    eqy = _pad(out["equipsd"].a[..., y - out["equipsd"].lb[5]])
    whse_eff, whse_sd, sdbyfuel = ys["whse_eff"], ys["whse_sd"], ys["sdbyfuel"]

    NT, NV = life.shape
    act = np.full((NUM_PREF + 1, NT, NV, 3), MAXCOST, dtype=np.float32)   # AnnualCostTech
    acta = np.full((NUM_PREF + 1, NT, NV, 3), MAXCOST, dtype=np.float32)  # AnnualCostTechAdj
    keq = {}

    def keq_cached(r, t, v):
        if (r, t, v) not in keq:
            keq[r, t, v] = keq_cost(inp, carry, r, t, v, year)
        return keq[r, t, v]

    prefs = range(1, NUM_PREF + 1)
    P7 = np.arange(NUM_PREF)
    powc = {}

    def crf_den(rate, tl):
        """1 - (1 + rate) ** -life, computed once per distinct pair (numpy float32 scalars)."""
        key = (float(rate), float(tl))
        if key not in powc:
            powc[key] = f32(1.0) - (f32(1.0) + rate) ** (f32(-1.0) * tl)
        return powc[key]
    for r in range(1, NUM_DIV + 1):
        for s in range(1, NUM_MAJ_SERV + 1):
            conv0 = f32(8.76)
            price_delta = [f32(0.0)] * 3
            if pelcmout[r, ebase, s] > 0.0:
                price_delta[0] = pelcmout[r, y, s] / pelcmout[r, ebase, s]
            if pngcm[r, ebase] > 0.0:
                price_delta[1] = pngcm[r, y] / pngcm[r, ebase]
            if pdscm[r, ebase] > 0.0:
                price_delta[2] = pdscm[r, y] / pdscm[r, ebase]
            tlist = [int(techs_for[s, k]) for k in range(1, int(n_techs[s]) + 1)]
            L = [(t, v) for t in tlist for v in range(1, int(n_vint[t]) + 1) if by_model[t, v] == 1]
            nL = len(L)
            pos = {tv: i for i, tv in enumerate(L)}
            Lt = {t: [v for (tt, v) in L if tt == t] for t in tlist}
            fuel = {t: _fuel_of(fuelbytech, t) for t in tlist}
            T = np.array([t for t, _ in L])
            V = np.array([v for _, v in L])
            ep_f = {f: (pelcmout[r, y, s], pngcm[r, y], pdscm[r, y])[f - 1] * jpgdp[ik] / jpgdp[-2] for f in (1, 2, 3)}
            fuel_L = np.array([fuel[t] for t, _ in L], dtype=int)

            # What does not depend on building type, per preference group p and technology (t, v).
            eh_p, eha_pf, ehr_pf = {}, {}, {}
            for p in prefs:
                eh = rmgblus[y] / f32(100.0) + tpprem[s, p, y]
                eh_r = eh
                if eh < 0.03:
                    eh = (f32(0.03) - eh) + eh
                eh_p[p] = eh
                for f in (1, 2, 3):
                    eha = eh
                    if price_delta[f - 1] > 1.0 and eh > 0.15:
                        eha = (eh - f32(0.15)) * price_delta[f - 1] ** hurdle_elas[r, s, f] + f32(0.15)
                    eha_pf[p, f] = eha
                    er = eh_r
                    if price_delta[f - 1] > 1.0 and er > 0.15:
                        er = (er - f32(0.15)) * price_delta[f - 1] ** hurdle_elas[r, s, f] + f32(0.15)
                    ehr_pf[p, f] = er
            unavail_tv = np.array([tc[r, t, v, I_CAP] == MAXCOST or year < avail[r, t, v, 1]
                                   or year > avail[r, t, v, 2] or techbyservice[s, t] == 0 for t, v in L], dtype=bool)
            ret_unavail = np.array([year < avail[r, t, v, 1] or tc[r, t, v, I_CAP] == MAXCOST for t, v in L], dtype=bool)
            cap_L = np.array([keq_cached(r, t, v) if cost_trend_on else tc[r, t, v, I_CAP] for t, v in L], dtype=f32)
            maint_L = tc[r, T, V, I_MAINT]
            capr_L = tc[r, T, V, I_CAP]
            eff_L = eff[r, s, T, V]
            conv_L = np.array([((f32(1.0) / f32(0.03343)) / cri[r, s, t, v]) if s == 6 else conv0 for t, v in L], dtype=f32)
            ep_L = np.array([ep_f[f] for f in fuel_L], dtype=f32)
            fpe_L = ep_L / eff_L * conv_L  # (ep / eff) * conv, as written left to right
            eh_PL = np.array([[eh_p[p]] * nL for p in prefs], dtype=f32)
            eha_PL = np.array([[eha_pf[p, f] for f in fuel_L] for p in prefs], dtype=f32)
            ehr_PL = np.array([[ehr_pf[p, f] for f in fuel_L] for p in prefs], dtype=f32)
            den_PL = np.array([[crf_den(eh_p[p], life[t, v]) for t, v in L] for p in prefs], dtype=f32)
            dena_PL = np.array([[crf_den(eha_pf[p, fuel[t]], life[t, v]) for t, v in L] for p in prefs], dtype=f32)
            denr_PL = np.array([[crf_den(ehr_pf[p, fuel[t]], life[t, v]) for t, v in L] for p in prefs], dtype=f32)
            life_L = life[T, V]
            retro_L = retro_frac[T, V]
            tp = {p: tpp[s, p, y] for p in prefs}
            tp_P = np.array([tp[p] for p in prefs], dtype=f32)
            fb_L = {f: fuelbytech[T, f] for f in (1, 2, 3)}
            eff_pos = eff_L > 0.0
            TH = np.array([t for t in range(1, NUM_HP + 1) if techbyservice[1, t] == 1
                           for v in range(1, int(n_vint[t]) + 1) if by_model[t, v] == 1], dtype=int)
            VH = np.array([v for t in range(1, NUM_HP + 1) if techbyservice[1, t] == 1
                           for v in range(1, int(n_vint[t]) + 1) if by_model[t, v] == 1], dtype=int)
            TB = np.array([t for t, _ in L if t > 2 * NUM_HP], dtype=int)
            VB = np.array([v for t, v in L if t > 2 * NUM_HP], dtype=int)
            skip_hp = (T <= NUM_HP) & (s == 2)
            fi_L = np.array([_first_fuel_of(fuelbytech, t) for t, _ in L], dtype=int)
            cri2_L = cri[r, s, T, V] == 2.0
            sub_L, s111_L = tc[r, T, V, I_SUB], tc[r, T, V, I_SUB111D]

            def tic(t, v):
                if cost_trend_on:
                    if t <= NUM_HP:
                        hp = keq_cached(r, cooling_hp, v)
                        if hp == MAXCOST:
                            hp = tc[r, cooling_hp, v, I_CAP]
                        return keq_cached(r, t, v) + hp
                    return keq_cached(r, t, v)
                if t <= NUM_HP:
                    return tc[r, t, v, I_CAP] + tc[r, cooling_hp, v, I_CAP]
                return tc[r, t, v, I_CAP]
            tic_L = np.array([tic(t, v) if not ((t <= NUM_HP and s == 2) or unavail_tv[i]) else f32(0.0)
                              for i, (t, v) in enumerate(L)], dtype=f32)
            TA = np.array([t for t in tlist for v in range(1, int(n_vint[t]) + 1)], dtype=int)
            VA = np.array([v for t in tlist for v in range(1, int(n_vint[t]) + 1)], dtype=int)

            # Candidate sets for the searches, as positions in L.
            same_fuel = {f: np.array([i for i, (t, _) in enumerate(L) if fuelbytech[t, f] == 1], dtype=int)
                         for f in (1, 2, 3)}
            fuel_seq = {f: np.array([i for i, (t, _) in enumerate(L) if fuel[t] == f], dtype=int) for f in (1, 2, 3)}
            of_tech = {t: np.array([pos[t, v] for v in Lt[t]], dtype=int) for t in tlist}
            t1 = tlist[0]
            sides = (I_EXIST, I_NEW) if s < 3 else (I_EXIST,)
            new_side = I_NEW if s < 3 else I_EXIST
            reg_fs_num = {}

            for b in range(1, NUM_BLDG + 1):
                if s < 3:
                    shf = sh_h if s == 1 else sh_c
                    shell = {I_EXIST: shf[b, r, 1], I_NEW: shf[b, r, 2]}
                else:
                    shell = {I_EXIST: f32(1.0), I_NEW: f32(1.0)}

                # Retiring and surviving shares of last year's equipment.
                ptss = prev_tss[r, b, s, T, V]
                has_life = life_L > 0.0
                rp = _seq_total((ptss / life_L)[has_life])
                surv_ok = has_life & ((f32(1.0) - rp) > 0.0)
                repl_ok = has_life & (rp > 0.0)
                with np.errstate(divide="ignore", invalid="ignore"):
                    surv_L = np.where(surv_ok, ptss * (f32(1.0) - (f32(1.0) / life_L)) / (f32(1.0) - rp), f32(0.0)).astype(f32)
                    repl_L = np.where(repl_ok, ptss * (f32(1.0) / life_L) / rp, f32(0.0)).astype(f32)
                # float32 times an int fuel flag is float64, as in the reference version
                repl_fs = [None] + [_seq_total((repl_L * fb_L[f])[repl_ok]) for f in (1, 2, 3)]

                # Annualized cost of every technology (label 90).
                ok = ~(unavail_tv | (restrict[T, V, b, r] == 1))
                cf = capfac[r, b, s]
                ca = cap_L / cf * eha_PL / dena_PL + maint_L
                c = cap_L / cf * eh_PL / den_PL + maint_L
                fuel_e = fpe_L * shell[I_EXIST]
                a_ex, c_ex = np.where(ok, ca + fuel_e, MAXCOST), np.where(ok, c + fuel_e, MAXCOST)
                if s < 3:
                    fuel_n = fpe_L * shell[I_NEW]
                    a_nw, c_nw = np.where(ok, ca + fuel_n, MAXCOST), np.where(ok, c + fuel_n, MAXCOST)
                else:
                    a_nw, c_nw = np.where(ok, ca, MAXCOST), np.where(ok, c, MAXCOST)
                acta[1:, T, V, I_EXIST], act[1:, T, V, I_EXIST] = a_ex, c_ex
                acta[1:, T, V, I_NEW], act[1:, T, V, I_NEW] = a_nw, c_nw
                AC = {I_EXIST: act[:, T, V, I_EXIST], I_NEW: act[:, T, V, I_NEW]}
                ACA = {I_EXIST: acta[:, T, V, I_EXIST], I_NEW: acta[:, T, V, I_NEW]}

                # New and Replacement: least-cost searches (label 100), all preference groups at once.
                lc_af, lc_sf, lcv_st = {}, {}, {}
                for sd in sides:
                    ac, aca = AC[sd][1:], ACA[sd][1:]                 # [p, position]
                    k = np.argmin(ac, axis=1)
                    m = ac[P7, k]
                    init = act[1:, t1, 1, sd]
                    win = m < init
                    best = np.where(win, m, init)
                    first = [L[k[i]] if win[i] else (t1, 1) for i in range(NUM_PREF)]
                    sfk, sfm = {}, {}
                    for f in (1, 2, 3):
                        cand = same_fuel[f]
                        if cand.size:
                            kf = cand[np.argmin(aca[:, cand], axis=1)]
                            sfk[f], sfm[f] = kf, aca[P7, kf]
                    for i, p in enumerate(prefs):
                        f = fuel[first[i][0]]
                        lc_af[p, sd] = L[sfk[f][i]] if f in sfk and sfm[f][i] < best[i] else first[i]
                    for f in (1, 2, 3):
                        seq = fuel_seq[f]
                        init = acta[1:, t1, 1, sd] if f == fuel[t1] else np.full(NUM_PREF, MAXCOST, dtype=f32)
                        iarg = (t1, 1) if f == fuel[t1] else (0, 0)
                        if seq.size:
                            kf = seq[np.argmin(aca[:, seq], axis=1)]
                            mf = aca[P7, kf]
                        else:
                            kf, mf = None, init
                        for i, p in enumerate(prefs):
                            if seq.size and mf[i] < init[i]:
                                lc_sf[p, f, sd] = L[kf[i]]
                            else:
                                lc_sf[p, f, sd] = (0, 0) if init[i] == MAXCOST else iarg
                    for t in tlist:
                        idx = of_tech[t]
                        init = acta[1:, t, 1, sd]
                        if idx.size:
                            kk = np.argmin(aca[:, idx], axis=1)
                            mt = aca[P7, idx[kk]]
                        for i, p in enumerate(prefs):
                            if idx.size and mt[i] < init[i]:
                                lcv_st[p, t, sd] = Lt[t][kk[i]]
                            else:
                                lcv_st[p, t, sd] = 0 if init[i] == MAXCOST else 1

                zero_L = lambda: [f32(0.0)] * nL
                lcmsn, lcmsr, sfmsn, sfmsr, stmsn, stmsr = (zero_L() for _ in range(6))
                for p in prefs:
                    i = pos.get(lc_af[p, I_EXIST])
                    if i is not None:
                        lcmsr[i] += tp[p]
                    i = pos.get(lc_af[p, new_side])
                    if i is not None:
                        lcmsn[i] += tp[p]
                for f in range(1, 4):
                    pf = prev_fss[r, b, s, f]
                    for p in prefs:
                        if s < 3:
                            i = pos.get(lc_sf[p, f, I_EXIST])
                            if i is not None:
                                sfmsr[i] += tp[p] * repl_fs[f]
                            i = pos.get(lc_sf[p, f, I_NEW])
                            if i is not None:
                                sfmsn[i] += tp[p] * pf
                        else:
                            i = pos.get(lc_sf[p, f, I_EXIST])
                            if i is not None:
                                sfmsn[i] += tp[p] * pf
                                sfmsr[i] += tp[p] * repl_fs[f]
                for t in tlist:
                    share_n = f32(0.0)
                    share_r = f32(0.0)
                    for i in of_tech[t]:
                        share_n += ptss[i]
                        share_r += repl_L[i]
                    for p in prefs:
                        if s < 3:
                            i = pos.get((t, lcv_st[p, t, I_EXIST]))
                            if i is not None:
                                stmsr[i] += tp[p]
                            i = pos.get((t, lcv_st[p, t, I_NEW]))
                            if i is not None:
                                stmsn[i] += tp[p]
                        else:
                            i = pos.get((t, lcv_st[p, t, I_EXIST]))
                            if i is not None:
                                stmsn[i] += tp[p]
                                stmsr[i] += tp[p]
                    for i in of_tech[t]:
                        stmsn[i] = stmsn[i] * share_n
                        stmsr[i] = stmsr[i] * share_r
                bs = bshare[s, b]
                for i, (t, v) in enumerate(L):
                    MS[b, s, 1, t, v] = bs[1, 1] * lcmsn[i] + bs[1, 2] * sfmsn[i] + bs[1, 3] * stmsn[i]
                for i, (t, v) in enumerate(L):
                    MS[b, s, 2, t, v] = bs[2, 1] * lcmsr[i] + bs[2, 2] * sfmsr[i] + bs[2, 3] * stmsr[i]

                # Retrofit: cost of keeping existing equipment (label 180), then for every
                # preference group and existing technology the same-fuel (SF), all-fuel (AF)
                # and same-technology (ST) winners, as positions in L (-1: no choice).
                ace = maint_L - retro_L * capr_L / cf * ehr_PL / denr_PL + fpe_L * shell[I_EXIST]
                ace = np.where(ret_unavail, MAXCOST, ace)
                aca_P, ac_P = ACA[I_EXIST][1:], AC[I_EXIST][1:]          # [p, position]
                live = ace < MAXCOST
                me = np.broadcast_to(np.arange(nL), (NUM_PREF, nL))
                sf_m = np.empty((NUM_PREF, 4), dtype=f32)                  # cheapest same-fuel cost, by fuel
                sf_k = np.zeros((NUM_PREF, 4), dtype=int)
                for f in (1, 2, 3):
                    cand = same_fuel[f]
                    if cand.size:
                        kk = np.argmin(aca_P[:, cand], axis=1)
                        sf_k[:, f] = cand[kk]
                        sf_m[:, f] = aca_P[np.arange(NUM_PREF), cand[kk]]
                ret_sf = np.where(sf_m[:, fuel_L] < ace, sf_k[:, fuel_L], me)
                kaf = np.argmin(ac_P, axis=1)
                maf = ac_P[np.arange(NUM_PREF), kaf]
                beat = maf[:, None] < ace
                ret_af = np.where(beat, kaf[:, None], me)
                m_af = np.where(beat, maf[:, None], ace)
                if st_ret:
                    st_m, st_k = np.empty((NUM_PREF, nL), dtype=f32), np.zeros((NUM_PREF, nL), dtype=int)
                    for t in tlist:
                        idx = of_tech[t]
                        kk = np.argmin(aca_P[:, idx], axis=1)
                        st_k[:, idx] = idx[kk][:, None]
                        st_m[:, idx] = aca_P[np.arange(NUM_PREF), idx[kk]][:, None]
                    ret_st = np.where(st_m < ace, st_k, me)
                else:
                    ret_st = me.copy()
                ret_sf, ret_af, ret_st = (np.where(live, x, -1) for x in (ret_sf, ret_af, ret_st))
                # Second all-fuel pass: cheapest adjusted cost within the winner's fuel. Its running
                # minimum is never reset (EIA quirk): it starts from the last first-pass minimum and
                # only falls, across every preference group and technology in turn.
                pi, ii = np.nonzero(live)
                if pi.size:
                    fmin = fuel_L[ret_af[pi, ii]]
                    c = sf_m[pi, fmin]
                    run = np.minimum.accumulate(np.concatenate([[m_af[pi[-1], ii[-1]]], c]))
                    hit = c < run[:-1]
                    ret_af[pi[hit], ii[hit]] = sf_k[pi[hit], fmin[hit]]

                # Shares of the surviving stock each technology wins, summed in the Fortran's order
                # (existing technology, then preference group); np.add.at adds repeats in order.
                contrib = (surv_L[:, None] * tp_P[None, :]).reshape(-1)     # [position, p]
                def won(ret):
                    tgt = ret.T.reshape(-1)
                    keep = tgt >= 0
                    acc = np.zeros(nL, dtype=f32)
                    np.add.at(acc, tgt[keep], contrib[keep])
                    return acc
                lcm_ret, sfm_ret = won(ret_af), won(ret_sf)
                stm_ret = won(ret_st) if st_ret else surv_L
                MS[b, s, 3, T, V] = bs[3, 1] * lcm_ret + bs[3, 2] * sfm_ret + bs[3, 3] * stm_ret

                NSD[r, b, s] = nd_in[s, b, r]
                RSD[r, b, s] = rd_in[s, b, r]
                SSD[r, b, s] = sd_in[s, b, r]
                nsd, rsd, ssd = NSD[r, b, s], RSD[r, b, s], SSD[r, b, s]

                # Heat pumps chosen for heating also cool (label after 240).
                if s == 2:
                    SD = {(svc, 1): NSD[r, b, svc] for svc in (1, 2)}
                    SD.update({(svc, 2): RSD[r, b, svc] for svc in (1, 2)})
                    SD.update({(svc, 3): SSD[r, b, svc] for svc in (1, 2)})
                    for d in range(1, NUM_DEC + 1):
                        if SD[2, d] > 0.0:
                            MS[b, 2, d, TH + NUM_HP, VH] = (MS[b, 1, d, TH, VH] * SD[1, d]
                                                           * degreedays[2, r, y] / degreedays[1, r, y] / SD[2, d])
                        else:
                            MS[b, 2, d, TH + NUM_HP, VH] = 0.0
                    for d in range(1, NUM_DEC + 1):
                        hp_sd = _seq_total(MS[b, 2, d, TH + NUM_HP, VH] * SD[2, d])
                        norm = _seq_total(MS[b, 2, d, TB, VB])
                        if norm > 0.0:
                            MS[b, 2, d, TB, VB] = MS[b, 2, d, TB, VB] / norm
                        if SD[2, d] > 0.0:
                            MS[b, 2, d, TB, VB] = MS[b, 2, d, TB, VB] * (SD[2, d] - hp_sd) / SD[2, d]

                # Investment in purchased equipment (label 314), summed in L's order.
                ms1, ms2, ms3 = MS[b, s, 1, T, V], MS[b, s, 2, T, V], MS[b, s, 3, T, V]
                gain = ssd * (ms3 - surv_L)
                ird_L = np.where(ok & (gain > 0.0), gain, f32(0.0))
                invest = ms1 * nsd + ms2 * rsd + ird_L
                cnt = ok & ~skip_hp
                purch_sd = _seq_total(invest[cnt])
                prt_sd = _seq_total(ird_L[cnt])
                inv, fed, nonfed, subt, s111d = (ys[k] for k in ("investcost", "fedsubsidyinvestcost",
                                                                 "nonfedsubsidyinvestcost", "subsidyinvestcost",
                                                                 "subsidy111dinvestcost"))
                np.add.at(inv[r, s], fi_L[cnt], (invest * (tic_L / f32(8760.0) / cf))[cnt])
                sub_v = invest * (sub_L / f32(8760.0) / cf)
                np.add.at(fed[r, s], fi_L[cnt & cri2_L], sub_v[cnt & cri2_L])
                np.add.at(nonfed[r, s], fi_L[cnt & ~cri2_L], sub_v[cnt & ~cri2_L])
                for fi in set(fi_L[cnt].tolist()):
                    subt[r, s, fi] = fed[r, s, fi] + nonfed[r, s, fi]
                np.add.at(s111d[r, s], fi_L[cnt], (invest * (s111_L / f32(8760.0) / cf))[cnt])

                # Fuel shares and efficiency by decision (label 270). MS (float32) times the int
                # fuel flag is float64 in numpy, so these sums run in float64, in L's order.
                FS, AE = {}, {}
                for d in range(1, NUM_DEC + 1):
                    ms_d = MS[b, s, d, T, V]
                    for f in range(1, NUM_FUEL + 1):
                        terms = ms_d * fb_L[f]
                        fs = _seq_total(terms)
                        den = _seq_total((terms / eff_L)[eff_pos])
                        FS[d, f] = fs
                        AE[d, f] = fs / den if den > 0.0 else f32(0.0)
                tot = nsd + rsd + ssd
                for f in range(1, NUM_FUEL + 1):
                    FSS[r, b, s, f] = 0.0
                    sdbyfuel[f, s, b, r] = 0.0
                    if tot > 0.0:
                        FSS[r, b, s, f] = (nsd * FS[1, f] + rsd * FS[2, f] + ssd * FS[3, f]) / tot
                        sdbyfuel[f, s, b, r] = (nsd_ns[r, b, s] * FS[1, f] + rsd_ns[r, b, s] * FS[2, f]
                                                + ssd_ns[r, b, s] * FS[3, f])
                tss_L = (nsd * ms1 + rsd * ms2 + ssd * ms3) / tot if tot > 0.0 else np.zeros(nL, dtype=f32)
                TSS[r, b, s, T, V] = tss_L
                PTS[r, b, s, T, V] = ((nsd * ms1 + rsd * ms2 + prt_sd * (ird_L / ssd)) / purch_sd
                                      if purch_sd > 0.0 else f32(0.0))
                tss_L = TSS[r, b, s, T, V]
                for f in range(1, NUM_FUEL + 1):
                    den = _seq_total((tss_L * fb_L[f] / eff_L)[eff_pos])
                    AVE[r, b, s, f] = FSS[r, b, s, f] / den if den > 0.0 else prev_ae[r, b, s, f]
                    if b == 10:
                        whse_eff[r, s, f] = AVE[r, 10, s, f]
                        whse_sd[r, s, f] = sdbyfuel[f, s, 10, r]
                for d, dmd in ((1, nsd), (2, rsd), (3, ssd)):
                    add = MS[b, s, d, TA, VA] * dmd
                    eqy[r, b, TA, VA, d] += add
                    eqy[11, b, TA, VA, d] += add
                reg_fs_num[b] = (FS, AE)

            # Decision-type fuel shares and efficiency for the region (labels 340, 350).
            for f in range(1, NUM_FUEL + 1):
                for d in range(1, NUM_DEC + 1):
                    dmd = {1: NSD, 2: RSD, 3: SSD}[d]
                    num = f32(0.0)
                    den = f32(0.0)
                    for b in range(1, NUM_BLDG + 1):
                        num += reg_fs_num[b][0][d, f] * dmd[r, b, s]
                        den += dmd[r, b, s]
                    ys["decfuelshare"][r, s, d, f] = num / den if den > 0.0 else f32(0.0)
                    num = f32(0.0)
                    den = f32(0.0)
                    for b in range(1, NUM_BLDG + 1):
                        FS, AE = reg_fs_num[b]
                        if AE[d, f] > 0.0:
                            num += FS[d, f] * dmd[r, b, s]
                            den += FS[d, f] * dmd[r, b, s] / AE[d, f]
                    ys["decavgeff"][r, s, d, f] = num / den if den > 0.0 else f32(0.0)
            for f in range(1, NUM_FUEL + 1):
                for name in ("investcost", "subsidyinvestcost", "subsidy111dinvestcost"):
                    ys[name][11, s, f] += ys[name][r, s, f]

    # Put the working copies back.
    out["ms"].a[...] = MS[1:, 1:, 1:, 1:, 1:]
    out["techshareofservice"].a[...] = TSS[1:, 1:, 1:, 1:, 1:]
    out["fuelshareofservice"].a[...] = FSS[1:, 1:, 1:, 1:]
    out["averageefficiency"].a[...] = AVE[1:, 1:, 1:, 1:]
    out["purchtechshare"].a[...] = PTS[1:, 1:, 1:, 1:, 1:]
    for k, arr in (("nsd", NSD), ("rsd", RSD), ("ssd", SSD)):
        out[k].a[..., y - out[k].lb[-1]] = arr[1:, 1:, 1:]
    for k, arr in ys.items():
        out[k].a[..., y - out[k].lb[-1]] = arr[(slice(1, None),) * arr.ndim]
    out["equipsd"].a[..., y - out["equipsd"].lb[5]] = eqy[1:, 1:, 1:, 1:, 1:]

    _warehouse_and_us(inp, out, y)
    _minor_services(inp, out, y)
    return out


def _technology_choice_reference(inp: dict, carry: Carry, y: int) -> dict:
    """COMTechnologyChoice line by line, every loop as the Fortran has it. Used when
    price-induced technical change moves ifwd; otherwise technology_choice runs the fast version."""
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

    _warehouse_and_us(inp, out, y)
    _minor_services(inp, out, y)
    return out


def _warehouse_and_us(inp: dict, out: dict, y: int) -> None:
    """Warehouse indices by group of census divisions, and the US average efficiency of the stock (label 360)."""
    shell_h = inp["shellheatfactor"]
    whse_eff, whse_sd = out["whse_eff"], out["whse_sd"]
    P = lambda a: _pad(a.a)
    techs_for, n_techs, n_vint, by_model = (P(inp[k]) for k in ("techsforservice", "cmnumtechsforservice",
                                                               "cmnumeqv", "techbymodel"))
    fuelbytech, eff = P(inp["fuelbytech"]), P(inp["techeff"])
    FSS, TSS = P(out["fuelshareofservice"]), P(out["techshareofservice"])
    yl = lambda k: _pad(out[k].a[..., y - out[k].lb[-1]])
    NSD, RSD, SSD = yl("nsd"), yl("rsd"), yl("ssd")
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
                    tot = NSD[r, b, s] + RSD[r, b, s] + SSD[r, b, s]
                    num += FSS[r, b, s, f] * tot
                    for t, v in L:
                        if eff[r, s, t, v] > 0.0:
                            den += TSS[r, b, s, t, v] * fuelbytech[t, f] / eff[r, s, t, v] * tot
            out["cmusavgeff"][s, f, y] = num / den if den > 0.0 else f32(0.0)


def _minor_services(inp: dict, out: dict, y: int) -> None:
    """Minor services: efficiency rolls forward at a fixed rate (label 9100)."""
    prev_ae = inp["prevyraverageefficiency"]
    FSS, AVE = out["fuelshareofservice"], out["averageefficiency"]
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
