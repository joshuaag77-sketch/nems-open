"""TAIREFF (tranair.f): aircraft stocks, efficiency and jet fuel.

Through the last history year, jet fuel follows seat-miles over efficiency by world
region. From then on, passenger and cargo aircraft age and retire; cargo aircraft
needed for freight demand come from parked freighters, then parked and active
passenger aircraft converted to cargo, then new ones; passenger aircraft needed for
seat-mile demand come from parked ones (within an annual limit) and then new ones;
spare capacity is parked, oldest first. New-aircraft efficiency improves each year;
stock efficiency is the harmonic mean over active vintages. Aviation gasoline decays
toward a floor.

EIA quirk kept: the oldest vintage (48) takes in last year's 47- and 48-year-olds at
the age-48 survival rate, so 48-year-olds never leave the stock entirely.
"""

import numpy as np

from nems_open.transportation.air_common import DOMINT, MAXACAGE, MAXATYP, MAXWREG, ONE, ZERO, A
from nems_open.transportation.common import expf, f32, fsum, MNUMCR
from nems_open.transportation.mean_funcs import harmonic_mean

W = slice(1, MAXWREG)
T = slice(1, MAXATYP)
D = slice(1, DOMINT)
AGES = slice(1, MAXACAGE)
MILLION = f32(1000000.)


def _rpmpg(a, n, w, t, di):
    g = a["gptm"][w, n, t, di] * a["pass_weight"] / f32(2000)
    empty = ONE - a["load_factor"][w, n, di]
    mtow = a["pct_pass_mtow"][t, n]
    pd = a["passac_rpm_dmd"][w, t, di, n]
    if pd > 0.0:
        return ONE / (g * (ONE - empty * mtow) / (ONE - empty * (ONE - (a["belly_rpm_eq"][w, t, di, n] / pd))))
    return ONE / (g * (ONE - empty * mtow) / (ONE - empty))


def _type_means(a, n, new_mpg):
    """ASMPG_STK_TYP, ASMPG_NEW_TYP and ASMPGT for year n; new_mpg(t) gives the new-aircraft MPGs."""
    asm = a["asm"]
    for t in range(1, MAXATYP + 1):
        a["asmpg_stk_typ"][t, n] = harmonic_mean(a["asmpg_avg_age"][W, t, D, n], asm[W, D, t, n])
        a["asmpg_new_typ"][t, n] = harmonic_mean(new_mpg(t), asm[W, D, t, n])
    wts = fsum(fsum(asm[W, D, T, n], axis=1), axis=0)
    a["asmpgt"][1, n] = harmonic_mean(a["asmpg_new_typ"][T, n], wts)
    a["asmpgt"][2, n] = harmonic_mean(a["asmpg_stk_typ"][T, n], wts)


def taireff(s: dict) -> None:
    a = A(s)
    n, yrs = a.i("n"), a.i("yrs")
    first_fcst, last_hist = a.i("first_fcst_yr"), a.i("last_hist_yr")
    q, nus = a["qjetr_di"], a["qjetr_nus"]
    nus[:, n] = 0.0
    q[:, :, :, n] = 0.0
    pdmd, mgmt, rpmpg = a["passac_rpm_dmd"], a["air_mgmt_adj"], a["rpmpg"]
    cdmd, gptm, cf = a["cargoac_ftm_dmd"], a["gptm"], a["cfjfk"]
    asm, qjetr, sedjf = a["asm"], a["qjetr"], a["sedshrjf"]
    vint = a["asmpg_vint"]

    if yrs <= last_hist:
        age = last_hist - yrs + 1
        _type_means(a, n, lambda t: vint[W, t, age, D, last_hist - 1989])
        for w in range(1, MAXWREG + 1):
            for t in range(1, MAXATYP + 1):
                for di in range(1, DOMINT + 1):
                    if asm[w, di, t, n] != 0.0:
                        q[w, di, 1, n] = q[w, di, 1, n] + ((pdmd[w, t, di, n] * mgmt[w, n, di] / rpmpg[w, t, di, n]) / f32(42.0)) * cf
                        q[w, di, 2, n] = q[w, di, 2, n] + ((cdmd[w, t, di, n] * gptm[w, n, t, di]) / f32(42.0)) * cf
            nus[w, n] = fsum(q[w, :, :, n])
            qjetr[11, n] = nus[1, n]
            for r in range(1, MNUMCR - 1):
                qjetr[r, n] = qjetr[11, n] * sedjf[r, n]
        s.update({a.key("iwreg"): MAXWREG + 1, a.key("iatyp"): MAXATYP + 1, a.key("di"): DOMINT + 1,
                  a.key("iregn"): MNUMCR - 1})
    if yrs < last_hist:
        return

    names = ["stkcargo", "stkpass", "scrapped_total", "stkcargo_parked", "stkcargo_active", "stkpass_parked", "stkpass_active"]
    stk = {k: a[k] for k in names}
    for k in names:
        stk[k][:, :, :, n] = 0.0
    sp, sc = stk["stkpass"], stk["stkcargo"]
    pp, pa = stk["stkpass_parked"], stk["stkpass_active"]
    cp, ca = stk["stkcargo_parked"], stk["stkcargo_active"]
    scr = stk["scrapped_total"]
    stkpa, stkpp, stkca, stkcp = a["stkpa"], a["stkpp"], a["stkca"], a["stkcp"]
    stkptot, stkctot, sup, suptot = a["stkptot"], a["stkctot"], a["stk_sup"], a["stk_sup_tot"]
    ftmac, asmac, asmd = a["ftmac"], a["asmac"], a["asmdemd"]

    if yrs == last_hist:
        lhi = a.i("last_hist_index")
        for w in range(1, MAXWREG + 1):
            for t in range(1, MAXATYP + 1):
                sp[w, t, AGES, n] = a["stkpavint"][w, AGES, t] + a["stkppvint"][w, AGES, t]
                sc[w, t, AGES, n] = a["stkcavint"][w, AGES, t] + a["stkcpvint"][w, AGES, t]
                pp[w, t, AGES, n] = a["stkppvint"][w, AGES, t]
                cp[w, t, AGES, n] = a["stkcpvint"][w, AGES, t]
                pa[w, t, AGES, n] = a["stkpavint"][w, AGES, t]
                ca[w, t, AGES, n] = a["stkcavint"][w, AGES, t]
                pa[w, t, 1, 6:lhi - 1] = a["stk_sup_new"][w, 6:lhi - 1, t]
                cd = fsum(cdmd[w, t, :, 32])
                if stkctot[w, t, 32] != 0.0 and cd != 0.0:
                    adj = (cd * MILLION / stkctot[w, t, 32]) / ftmac[w, 32, t]
                    ftmac[w, 32:, t] = adj * ftmac[w, 32:, t]
                if stkpa[w, 32, t] != 0.0:
                    adj = (asmd[w, t, 32] * f32(1000000) / stkpa[w, 32, t]) / asmac[w, 32, t]
                    asmac[w, 32:, t] = adj * asmac[w, 32:, t]
        s.update({a.key("iwreg"): MAXWREG + 1, a.key("iatyp"): MAXATYP + 1, a.key("iage"): MAXACAGE + 1})
    else:
        suptot[:, :, n] = 0.0
        sup[:, :, :, n] = 0.0
        for arr in (stkpa, stkpp, stkca, stkcp):
            arr[:, n, :] = 0.0
        stkptot[:, :, n] = 0.0
        stkctot[:, :, n] = 0.0
        for k in ("unparked", "converted", "parked"):
            a[k][:, :, :, n] = 0.0
        unparked, converted, parked = a["unparked"], a["converted"], a["parked"]
        surv, min_shr = a["survac"], a["min_prk_shr"]
        min_park = np.zeros((MAXWREG + 1, MAXATYP + 1), dtype=f32)
        for w in range(1, MAXWREG + 1):
            for t in range(1, MAXATYP + 1):
                for age in range(MAXACAGE, 1, -1):
                    for act, prk, tot, kind in ((ca, cp, sc, 2), (pa, pp, sp, 1)):
                        if age == MAXACAGE:
                            x = (act[w, t, age - 1, n - 1] * (ONE - surv[t, age, kind])
                                 + act[w, t, age, n - 1] * (ONE - surv[t, age, kind]))
                            prk[w, t, age, n] = prk[w, t, age - 1, n - 1] + prk[w, t, age, n - 1]
                            act[w, t, age, n] = act[w, t, age - 1, n - 1] + act[w, t, age, n - 1] - x
                        else:
                            x = act[w, t, age - 1, n - 1] * (ONE - surv[t, age, kind])
                            act[w, t, age, n] = act[w, t, age - 1, n - 1] - x
                            prk[w, t, age, n] = prk[w, t, age - 1, n - 1]
                        tot[w, t, age, n] = act[w, t, age, n] + prk[w, t, age, n]
                        scr[w, t, kind, n] = scr[w, t, kind, n] + x
                    sup[w, t, age, n] = sc[w, t, age, n] + sp[w, t, age, n]
                min_park[w, t] = max(ZERO, (fsum(pp[w, t, :, n]) + fsum(pa[w, t, :, n])) * min_shr[w, t])
        ia = 1

        c_need = np.zeros((MAXWREG + 1, MAXATYP + 1), dtype=f32)
        for w in range(1, MAXWREG + 1):
            for t in range(1, MAXATYP + 1):
                cd = fsum(cdmd[w, t, :, n])
                if fsum(ca[w, t, :, n - 1]) != 0.0:
                    c_need[w, t] = cd * MILLION / ftmac[w, n, t] - fsum(ca[w, t, :, n])
                elif cd > 0.0:
                    c_need[w, t] = cd * MILLION / ftmac[w, n, t]

        prk_f, c_pprk, c_pact = a.i("minage_prk_f"), a.i("minage_c_pprk"), a.i("minage_c_pact")
        for w in range(1, MAXWREG + 1):
            for t in range(1, MAXATYP + 1):
                need = c_need[w, t]
                if need <= 0.0:
                    for ia in range(MAXACAGE, prk_f - 1, -1):
                        if ca[w, t, ia, n] == 0.0:
                            continue
                        if ca[w, t, ia, n] >= abs(need):
                            cp[w, t, ia, n] = cp[w, t, ia, n] + abs(need)
                            ca[w, t, ia, n] = ca[w, t, ia, n] - abs(need)
                            parked[w, t, 2, n] = parked[w, t, 2, n] + abs(need)
                            need = ZERO
                            break
                        cp[w, t, ia, n] = cp[w, t, ia, n] + ca[w, t, ia, n]
                        parked[w, t, 2, n] = parked[w, t, 2, n] + ca[w, t, ia, n]
                        ca[w, t, ia, n] = 0.0
                    else:
                        ia = prk_f - 1
                else:
                    done = False
                    for ia in range(1, MAXACAGE + 1):
                        if cp[w, t, ia, n] == 0.0:
                            continue
                        if cp[w, t, ia, n] >= need:
                            ca[w, t, ia, n] = ca[w, t, ia, n] + need
                            cp[w, t, ia, n] = cp[w, t, ia, n] - need
                            unparked[w, t, 2, n] = unparked[w, t, 2, n] + need
                            need = ZERO
                            done = True
                            break
                        ca[w, t, ia, n] = ca[w, t, ia, n] + cp[w, t, ia, n]
                        need = need - cp[w, t, ia, n]
                        unparked[w, t, 2, n] = unparked[w, t, 2, n] + cp[w, t, ia, n]
                        cp[w, t, ia, n] = 0.0
                    else:
                        ia = MAXACAGE + 1
                    if not done and fsum(pp[w, t, :, n]) - min_park[w, t] > 0.0:
                        for ia in range(MAXACAGE, c_pprk - 1, -1):
                            if pp[w, t, ia, n] == 0.0:
                                continue
                            if pp[w, t, ia, n] >= need:
                                un = min(max(ZERO, fsum(pp[w, t, :, n]) - min_park[w, t]), need)
                                pp[w, t, ia, n] = pp[w, t, ia, n] - un
                                ca[w, t, ia, n] = ca[w, t, ia, n] + un
                                converted[w, t, 1, n] = converted[w, t, 1, n] + un
                                need = need - un
                                if need == 0.0:
                                    done = True
                                    break
                            else:
                                un = min(pp[w, t, ia, n], max(ZERO, fsum(pp[w, t, :, n]) - min_park[w, t]))
                                pp[w, t, ia, n] = pp[w, t, ia, n] - un
                                ca[w, t, ia, n] = ca[w, t, ia, n] + un
                                need = need - un
                                converted[w, t, 1, n] = converted[w, t, 1, n] + un
                            if fsum(pp[w, t, :, n]) <= min_park[w, t]:
                                break
                        else:
                            ia = c_pprk - 1
                    if not done:
                        for ia in range(MAXACAGE, c_pact - 1, -1):
                            if pa[w, t, ia, n] == 0.0:
                                continue
                            if pa[w, t, ia, n] >= need:
                                ca[w, t, ia, n] = ca[w, t, ia, n] + need
                                pa[w, t, ia, n] = pa[w, t, ia, n] - need
                                converted[w, t, 2, n] = converted[w, t, 2, n] + need
                                need = ZERO
                                done = True
                                break
                            ca[w, t, ia, n] = ca[w, t, ia, n] + pa[w, t, ia, n]
                            need = need - pa[w, t, ia, n]
                            converted[w, t, 2, n] = converted[w, t, 2, n] + pa[w, t, ia, n]
                            pa[w, t, ia, n] = 0.0
                        else:
                            ia = c_pact - 1
                        if not done:
                            ca[w, t, 1, n] = ca[w, t, 1, n] + need
                c_need[w, t] = need
                stkpa[w, n, t] = fsum(pa[w, t, :, n])
                stkpp[w, n, t] = fsum(pp[w, t, :, n])
                stkca[w, n, t] = fsum(ca[w, t, :, n])
                stkcp[w, n, t] = fsum(cp[w, t, :, n])
                stkptot[w, t, n] = stkpa[w, n, t] + stkpp[w, n, t]
                stkctot[w, t, n] = stkca[w, n, t] + stkcp[w, n, t]
                suptot[w, t, n] = stkptot[w, t, n] + stkctot[w, t, n]

        p_need = np.zeros((MAXWREG + 1, MAXATYP + 1), dtype=f32)
        for w in range(1, MAXWREG + 1):
            for t in range(1, MAXATYP + 1):
                if fsum(pa[w, t, :, n - 1]) != 0.0:
                    p_need[w, t] = asmd[w, t, n] * MILLION / asmac[w, n, t] - fsum(pa[w, t, :, n])
                elif asmd[w, t, n] > 0.0:
                    p_need[w, t] = asmd[w, t, n] * MILLION / asmac[w, n, t]

        prk_p, max_age_un, un_shr = a.i("minage_prk_p"), a.i("maxage_unprk_p"), a["max_unprk_shr"]
        avg = a["stk_avgage_pa"]
        for w in range(1, MAXWREG + 1):
            for t in range(1, MAXATYP + 1):
                need = p_need[w, t]
                if need <= 0.0:
                    for ia in range(MAXACAGE, prk_p - 1, -1):
                        if pa[w, t, ia, n] == 0.0:
                            continue
                        if pa[w, t, ia, n] >= abs(need):
                            pp[w, t, ia, n] = pp[w, t, ia, n] + abs(need)
                            pa[w, t, ia, n] = pa[w, t, ia, n] - abs(need)
                            parked[w, t, 1, n] = parked[w, t, 1, n] + abs(need)
                            need = ZERO
                            break
                        pp[w, t, ia, n] = pp[w, t, ia, n] + pa[w, t, ia, n]
                        parked[w, t, 1, n] = parked[w, t, 1, n] + pa[w, t, ia, n]
                        pa[w, t, ia, n] = 0.0
                    else:
                        ia = prk_p - 1
                else:
                    tot_pp = fsum(pp[w, t, :, n])
                    max_un = tot_pp * un_shr
                    if yrs in (2022, 2023):
                        max_un = (tot_pp - min_park[w, t]) * f32(0.9)
                    if yrs == 2024:
                        max_un = (tot_pp - min_park[w, t]) * f32(0.6)
                    met = False
                    if tot_pp - min_park[w, t] > 0.0:
                        for ia in range(1, max_age_un + 1):
                            if pp[w, t, ia, n] == 0.0:
                                continue
                            spare = max(ZERO, fsum(pp[w, t, :, n]) - min_park[w, t])
                            if pp[w, t, ia, n] >= need:
                                un = min(max_un, spare, need)
                                pa[w, t, ia, n] = pa[w, t, ia, n] + un
                                pp[w, t, ia, n] = pp[w, t, ia, n] - un
                                max_un = max_un - un
                                need = need - un
                                unparked[w, t, 1, n] = unparked[w, t, 1, n] + un
                            else:
                                un = min(pp[w, t, ia, n], max_un, spare)
                                pa[w, t, ia, n] = pa[w, t, ia, n] + un
                                pp[w, t, ia, n] = pp[w, t, ia, n] - un
                                unparked[w, t, 1, n] = unparked[w, t, 1, n] + un
                                need = need - un
                                max_un = max_un - un
                            if need == 0.0:
                                met = True
                                break
                            if max_un == 0.0:
                                break
                        else:
                            ia = max_age_un + 1
                    if not met:
                        pa[w, t, 1, n] = pa[w, t, 1, n] + need
                p_need[w, t] = need
                stkpa[w, n, t] = fsum(pa[w, t, :, n])
                stkpp[w, n, t] = fsum(pp[w, t, :, n])
                stkca[w, n, t] = fsum(ca[w, t, :, n])
                stkcp[w, n, t] = fsum(cp[w, t, :, n])
                stkptot[w, t, n] = stkpa[w, n, t] + stkpp[w, n, t]
                stkctot[w, t, n] = stkca[w, n, t] + stkcp[w, n, t]
                sup[w, t, 1, n] = pa[w, t, 1, n] + ca[w, t, 1, n]
                suptot[w, t, n] = stkptot[w, t, n] + stkctot[w, t, n]
                avg[w, t, n] = 0.0
                tpa = fsum(pa[w, t, :, n])
                if tpa > 0.0:
                    acc = ZERO
                    for k in range(1, MAXACAGE + 1):
                        acc = acc + pa[w, t, k, n] * f32(k)
                    avg[w, t, n] = acc / tpa
                    ia = MAXACAGE + 1
        s.update({a.key("iwreg"): MAXWREG + 1, a.key("iatyp"): MAXATYP + 1, a.key("iage"): ia})

    if yrs >= first_fcst:
        red = a["fuel_burn_red"]
        vint[W, T, 1, D, n] = ONE / (ONE / vint[W, T, 1, D, n - 1] * (ONE - red))
        vint[W, T, 2:MAXACAGE, D, n] = vint[W, T, 1:MAXACAGE - 1, D, n - 1]
        for k in (10, 20, 30, 40):
            vint[W, T, k, D, n] = f32(1.01) * vint[W, T, k, D, n]
    avg_age, pw = a["asmpg_avg_age"], a["pass_weight"]
    align = a["stk_align_mult"]
    for w in range(1, MAXWREG + 1):
        for t in range(1, MAXATYP + 1):
            for di in range(1, DOMINT + 1):
                avg_age[w, t, di, n] = harmonic_mean(vint[w, t, AGES, di, n], pa[w, t, AGES, n])
                gptm[w, n, t, di] = ONE / (avg_age[w, t, di, n] * pw / f32(2000.0))
                if 2020 <= yrs <= 2026:
                    gptm[w, n, t, di] = gptm[w, n, t, di] * align[w, n, t]
                rpmpg[w, t, di, n] = _rpmpg(a, n, w, t, di)
    _type_means(a, n, lambda t: vint[W, t, 1, D, n])
    q[:, :, :, n] = 0.0
    for w in range(1, MAXWREG + 1):
        for t in range(1, MAXATYP + 1):
            for di in range(1, DOMINT + 1):
                q[w, di, 1, n] = q[w, di, 1, n] + ((pdmd[w, t, di, n] * mgmt[w, n, di] / rpmpg[w, t, di, n]) / f32(42.0)) * cf
                q[w, di, 2, n] = q[w, di, 2, n] + ((cdmd[w, t, di, n] * gptm[w, n, t, di]) / f32(42.0)) * cf
        if yrs >= first_fcst:
            nus[w, n] = fsum(q[w, :, :, n])
    if yrs >= first_fcst:
        qjetr[11, n] = nus[1, n]
    s.update({a.key("iwreg"): MAXWREG + 1, a.key("iatyp"): MAXATYP + 1, a.key("di"): DOMINT + 1})

    qag = a["qagtr"]
    if yrs >= first_fcst:
        qag[11, n] = qag[11, 24] + f32(220.0) * expf(-f32(0.1895) * f32(yrs - 1979))
    for r in range(1, MNUMCR - 1):
        qjetr[r, n] = qjetr[11, n] * sedjf[r, n]
        qag[r, n] = qag[11, n] * sedjf[r, n]
    a["iregn"] = MNUMCR - 1
