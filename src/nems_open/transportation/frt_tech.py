"""TRUCK_TECHADOPT (tranfrt.f): fuel-saving technology adoption by heavy trucks.

For each of 19 truck classes and 12 powertrains, each Phase 2 technology has a
trigger fuel price (its cost over discounted fuel savings in the payback period);
above it the technology climbs an S-curve toward its maximum share, below it the
share decays. Supersede and required-technology notes cap the shares, then the
shares set new-truck fuel economy and the added technology cost.

EIA quirks kept: PREFF_P2 = 1.0 resets the whole array on every technology, so only
the last one set survives in it; mild hybrid techs (68, 69, 71) are capped by the
sum of three others; the "temporary" TEMP_TRIG_P2 = 1.0 (EIA's own comment says it
inflates savings) is kept.
"""

import numpy as np

from nems_open.transportation.common import expf, f32, fsum
from nems_open.transportation.frt_common import CAFE14, CAFE19, FUEL12, ONE, V, ZERO
from nems_open.transportation.misc_modes import powi

LEARN_YR = [None, 2014, 2014, 2015, 2014, 2014, 2017, 2014, 2015, 2016, 2014, 2021, 2018, 2021, 2021]
SLOWTECHS = {7, 21, 22, 23, 64, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 81}


def truck_techadopt(s: dict, carry: dict) -> None:
    """carry: techpenyr_p2(MNUMYR, techp2, CAFE19, FUEL12), years before iyr filled."""
    v = V(s)
    iyr, yrs, itry = v.i("iyr"), v.i("yrs"), v.i("itryghg")
    techp2 = v.i("techp2")
    pen_yr = carry["techpenyr_p2"]
    shr, base = v["techshr_p2"], v["techbase_p2"]
    new_mpg, base_mpg = v["new_mpg_19"], v["base_mpg_p2"]
    T, C19, F12 = slice(1, techp2), slice(1, CAFE19), slice(1, FUEL12)
    if yrs == 2018:
        new_mpg[iyr - 1, F12, C19] = base_mpg[F12, C19]
        pen_yr[:, T, C19, F12] = 0.0
        shr[iyr - 1, T, C19, F12] = base[T, C19, F12]

    learn, fyr_p2 = v["techlearn_p2"], v["techfyr_p2"]
    once = v.priv("tech_once", lambda: np.zeros((techp2 + 1, CAFE19 + 1, FUEL12 + 1), dtype=bool))
    fyr = v.priv("fyr_p2", lambda: np.zeros((techp2 + 1, CAFE14 + 1), dtype=np.int16))
    ladj = v.priv("learn_adj", lambda: np.zeros((techp2 + 1, CAFE14 + 1), dtype=np.int16))
    btu = v.priv("temp_btu", lambda: np.zeros((CAFE14 + 1, FUEL12 + 1), dtype=f32))
    costyr = v.priv("techcostyr", lambda: np.zeros((techp2 + 1, CAFE19 + 1), dtype=f32))
    mpgeff = v.priv("mpgeff", lambda: np.zeros((FUEL12 + 1, CAFE19 + 1), dtype=f32))
    p219, p24, sc19 = v["p219map"], v["p24map"], v["sc19map"]
    annvmt, stk, hrate = v["annvmt_19"], v["trkstk_19"], v["hrate"]

    if itry == 1:
        once[...] = False
        for it in range(1, techp2 + 1):
            for c14 in range(1, CAFE14 + 1):
                if learn[it, c14] > 1:
                    fyr[it, c14] = fyr_p2[it, c14, F12].min()
        for ifuel in range(1, FUEL12 + 1):
            btu[:, ifuel] = 0.0
            sales = np.zeros(CAFE14 + 1, dtype=f32)
            term = ((annvmt[iyr, C19, 1, ifuel] / new_mpg[iyr - 1, ifuel, C19]
                     * np.array([hrate[int(sc19[c]), ifuel] for c in range(1, CAFE19 + 1)], dtype=f32) * f32(1.0e-6))
                    * stk[iyr - 1, C19, 1, ifuel])
            for c19 in range(1, CAFE19 + 1):
                c14 = int(p219[c19])
                v["icafe14"], v["isc4"] = c14, int(sc19[c19])
                btu[c14, ifuel] = btu[c14, ifuel] + term[c19 - 1]
                sales[c14] = sales[c14] + stk[iyr - 1, c19, 1, ifuel]
            v["icafe19"] = CAFE19 + 1
            ok = sales[1:] > 0.0
            btu[1:, ifuel] = np.where(ok, btu[1:, ifuel] / np.where(ok, sales[1:], ONE), btu[1:, ifuel])
        v["ifuel"] = FUEL12 + 1
        cost, lrn = v["techcost_p2"], v["learning_p2"]
        for c19 in range(1, CAFE19 + 1):
            c14 = int(p219[c19])
            v["icafe14"] = c14
            for it in range(1, techp2 + 1):
                if learn[it, c14] > 1:
                    ladj[it, c14] = 0
                    ly = LEARN_YR[int(learn[it, c14])]
                    if fyr[it, c14] > ly:
                        ladj[it, c14] = fyr[it, c14] - ly
                    costyr[it, c19] = cost[it, c14] * lrn[int(learn[it, c14]), iyr - int(ladj[it, c14])]
                else:
                    costyr[it, c19] = cost[it, c14]
            v["itechp2"] = techp2 + 1
        v["icafe19"] = CAFE19 + 1

    passed = v["hdv_passghg"]
    pay, pay1, disc = v["payback_p2"], v["payback1_p2"], v["discrtxg_p2"]
    teff, tvar, tmid, tshape, tmax = v["techeff_p2"], v["techvar_p2"], v["techmid_p2"], v["techshape_p2"], v["techmax_p2"]
    trig, preff = v["trigger_price_p2"], v["preff_p2"]
    favg = v["fuelprice_r_avg"]
    sup, cnt_sup, num_sup = v["supersedes_tech"], v["tech_cnt_sup"], v.i("num_sup")
    num_req, num_syn = v.i("num_req"), v.i("num_syn")
    cost_inc = v["inc_tech_cost_19"]
    trig_tmp = v.priv("temp_trig", lambda: np.zeros((techp2 + 1, CAFE19 + 1), dtype=f32))
    mid_adj = v.priv("techmid_adj", lambda: np.zeros((techp2 + 1, CAFE14 + 1), dtype=f32))
    # Start as if the previous call ended on the last class (true unless it was skipped).
    max_s = v.priv("max_share_s", lambda: np.array([ZERO] + [tmax[k, int(p219[CAFE19])] for k in range(1, techp2 + 1)], dtype=f32))
    notes = {}
    for inote in range(1, num_sup + 1):
        notes.setdefault(int(sup[1, inote]), []).append([int(sup[i, inote]) for i in range(2, int(cnt_sup[inote]) + 1)])
    notes = sorted((it, ns) for it, ns in notes.items() if 1 <= it <= techp2)
    for c19 in range(1, CAFE19 + 1):
        v["icafe19"] = c19
        c14 = int(p219[c19])
        c4 = int(p24[c14])
        v["icafe14"], v["icafe4"] = c14, c4
        if passed[iyr, c4]:
            continue
        for ifuel in range(1, FUEL12 + 1):
            v["ifuel"] = ifuel
            shr[iyr, :, c19, ifuel] = 0.0
            # Every technology at once: each one's trigger price, price factor and S-curve share
            # are its own. PREFF_P2 = 1.0 resets the whole array for every technology, so only
            # the last technology's factor is left in it.
            trig_tmp[1:, c19] = ONE
            preff.a[...] = 1.0
            idx = np.nonzero(yrs >= fyr_p2[T, c14, ifuel])[0]      # technology idx + 1
            if idx.size:
                its = idx + 1
                pb = int(pay[c14]) + min(5, itry - 1)
                pay1.a[idx, c19 - 1] = pb
                a1 = annvmt[iyr, c19, 1, ifuel]
                if a1 > 0:
                    num = ((btu[c14, ifuel] * annvmt[iyr, c19, 1:pb, ifuel]) / a1)[None, :] * teff[T, c14][idx][:, None]
                    den = np.float64(ONE + disc) ** np.arange(1, pb + 1, dtype=np.float64)
                    acc = np.add.accumulate(num.astype(np.float64) / den, axis=1)[:, -1] + 0.0
                    trig_tmp[its, c19] = acc.astype(f32)
                tr = costyr[its, c19] / trig_tmp[its, c19]
                trig.a[idx, c19 - 1, ifuel - 1] = tr
                fa = favg[ifuel, 11]
                pf = ONE + tvar[T, c14][idx] * ((fa / tr) - ONE)
                pr = np.where(f32(1.1) < pf, f32(1.1), pf)
                if idx[-1] == techp2 - 1:
                    preff[techp2, c19, ifuel] = pr[-1]
                prev = shr[iyr - 1, T, c19, ifuel][idx]
                bs = base[T, c19, ifuel][idx]
                py_prev = pen_yr[iyr - 1, T, c19, ifuel][idx]
                py = pen_yr[iyr, T, c19, ifuel][idx]
                new = shr[iyr, T, c19, ifuel][idx]
                up = fa >= tr
                first = up & ~once[its, c19, ifuel]
                py = np.where(first, py_prev + ONE, py)
                once[its[first], c19, ifuel] = True
                if up.any():
                    u = its[up]
                    fac = powi(f32(0.95), itry - 1)
                    fac = fac if fac > f32(0.5) else f32(0.5)
                    slow = np.isin(u, list(SLOWTECHS))
                    mid_adj[u, c14] = np.where(slow, tmid[T, c14][u - 1], tmid[T, c14][u - 1] * fac)
                    p = ONE / (ONE + expf(f32(-1.0) * (py[up] - mid_adj[u, c14]) / tshape[T, c14][u - 1]))
                    lo = np.where(bs[up] < prev[up], bs[up], prev[up])
                    tm = tmax[T, c14][u - 1]
                    p = lo + (tm - bs[up]) * p
                    x = pr[up] * p
                    x = np.where(x < tm, x, tm)
                    new[up] = np.where(x > ZERO, x, ZERO)
                down = ~up & (prev > 0.0)
                py = np.where(down & (py_prev > 0.0), py_prev - ONE, py)
                new[down] = prev[down] * pr[down]
                pen_yr.a[iyr - 1, idx, c19 - 1, ifuel - 1] = py
                shr.a[iyr - 1, idx, c19 - 1, ifuel - 1] = new
                if np.isnan(new).any():
                    raise ValueError("TDM TRUCK_TECHADOPT: STOP 903, NaN technology share")
            v["itechp2"] = techp2 + 1

            # MAX_SHARE_S is a saved local: entries for technologies later in the list still
            # hold the previous fuel's or class's values when a supersede note reads them.
            # Only technologies with notes do anything; MAX_SHARE_S is filled in technology
            # order up to each one, so later entries keep their old values as in the loop.
            row = shr.a[iyr - 1, :, c19 - 1, ifuel - 1]          # technology it at it - 1
            tm, fy = tmax.a[:, c14 - 1], fyr_p2.a[:, c14 - 1, ifuel - 1]
            done = 0
            for it, its_notes in notes:
                max_s[done + 1:it + 1] = tm[done:it]
                done = it
                if yrs < fy[it - 1]:
                    continue
                for others in its_notes:
                    tot = row[it - 1]
                    mx = max(tm[it - 1], max(max_s[k] for k in others))
                    for k in others:
                        tot = tot + row[k - 1]
                        if tot > mx:
                            row[k - 1] = max(ZERO, row[k - 1] - (tot - mx))
                            tot = mx
            max_s[done + 1:techp2 + 1] = tm[done:techp2]
            if num_req > 0:
                req = v["requires_tech"]
                for it in range(1, techp2 + 1):
                    if yrs < fyr_p2[it, c14, ifuel]:
                        continue
                    required, req_mkt = False, ZERO
                    for inote in range(1, num_req + 1):
                        if int(req[1, inote]) == it:
                            required = True
                            req_mkt = req_mkt + shr[iyr, int(req[2, inote]), c19, ifuel]
                    if required:
                        shr[iyr, it, c19, ifuel] = min(shr[iyr, it, c19, ifuel], min(req_mkt, ONE))
            cap = shr[iyr, 62, c19, ifuel] + shr[iyr, 66, c19, ifuel] + shr[iyr, 67, c19, ifuel]
            for it in (68, 69, 71):
                shr[iyr, it, c19, ifuel] = min(shr[iyr, it, c19, ifuel], cap)
            syn = np.zeros(techp2 + 1, dtype=f32)
            if num_syn > 0:
                st, cnt_syn, per = v["synergy_tech"], v["tech_cnt_syn"], v["syn_per"]
                for it in range(1, techp2 + 1):
                    if yrs < fyr_p2[it, c14, ifuel]:
                        continue
                    for inote in range(1, num_syn + 1):
                        if int(st[1, inote]) == it:
                            for i in range(2, int(cnt_syn[inote]) + 1):
                                k = int(st[i, inote])
                                dm = ((shr[iyr, it, c19, ifuel] * shr[iyr, k, c19, ifuel])
                                      - (shr[iyr - 1, it, c19, ifuel] * shr[iyr - 1, k, c19, ifuel]))
                                syn[it] = syn[it] + (dm * per[i, inote])
            if ifuel == 5:
                shr[iyr, T, c19, ifuel] = shr[iyr, T, c19, 2]
            if ifuel == 7:
                shr[iyr, 1:17, c19, ifuel] = shr[iyr, 1:17, c19, 1]
            if ifuel == 8:
                shr[iyr, 1:17, c19, ifuel] = shr[iyr, 1:17, c19, 2]
            # MPGEFF: a running product, capped at 1 after each factor. Where the cap never binds
            # the product is a sequential multiply.accumulate; otherwise the loop as written.
            brow, te = base.a[:, c19 - 1, ifuel - 1], teff.a[:, c14 - 1]
            idx = np.nonzero(yrs >= fy)[0]
            a, b = row[idx], brow[idx]
            d = a - b
            ad = np.where(a > 0.0, np.where(f32(-1.0) * b > d, f32(-1.0) * b, d), ZERO)
            fac = ONE - ((te[idx] + syn[idx + 1]) * ad)
            prod = np.multiply.accumulate(np.concatenate(([ONE], fac)).astype(f32), dtype=f32)
            if (prod > ONE).any():
                m = ONE
                for x in fac:
                    m = min(m * x, ONE)
            else:
                m = prod[-1]
            mpgeff[ifuel, c19] = m
            v["itechp2"] = techp2 + 1
            cost_inc[iyr, c19, ifuel] = fsum(shr[iyr, T, c19, ifuel] * costyr[1:, c19])
        v["ifuel"] = FUEL12 + 1
    v["icafe19"] = CAFE19 + 1
    new_mpg[iyr, F12, C19] = base_mpg[F12, C19] / mpgeff[1:, 1:]

