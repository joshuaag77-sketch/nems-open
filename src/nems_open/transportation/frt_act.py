"""TRUCK_ACT (tranfrt.f): California's Advanced Clean Trucks rule in adopting regions.

ZEV and near-ZEV credits against deficits for class 2b-3, 4-8 vocational and 7-8
tractors, five-year banks, limits on near-ZEV credit use, then the remaining
deficit becomes required ZEV sales, taken from conventional (and if needed hybrid)
trucks bin by bin and split among BEV, FCEV and FCHEV by a logit on their NPV.
Credits are recomputed after the shift; the banks keep the pre-shift values.

carry: the saved credit and bank arrays (MNUMCR, MNUMYR), year n-1 and before.
"""

import numpy as np

from nems_open.transportation.common import expf, f32, fsum, MNUMCR
from nems_open.transportation.frt_common import CAFE19, FUEL12, NVMT, ONE, V, ZERO

CONV = [1, 2, 3, 4, 5]
CONVHEV = [1, 2, 3, 4, 5, 11]
ZEV = [6, 9, 10]
TRACTORS = [9, 10, 11, 13, 14, 15, 16, 17, 18, 19]
CARRY = ["credit_2b3_zev", "credit_48v_zev", "credit_78t_zev", "credit_2b3_nzev", "credit_48v_nzev",
         "credit_78t_nzev", "bank_2b8v_zev", "bank_2b8v_nzev", "bank_78t_zev", "bank_78t_nzev"]


def _sum_over(stk, iyr, classes, fuels, iregn):
    """sum(TRKSTK_19R(iyr, classes, 1, fuels, 1:2, iregn)) in Fortran element order."""
    sub = stk.a[iyr - 1, :, 0, :, 0:2, iregn - 1]            # (cafe19, fuel, flt)
    sub = sub[[c - 1 for c in classes]][:, [f - 1 for f in fuels]]
    return fsum(sub)


def _credits(v, s_iyr, n, iregn, local, c):
    stk, wm, pf = v["trkstk_19r"], v["act_wgtmod"], v["phev_factor"]
    allf = list(range(1, FUEL12 + 1))

    def group(classes, w):
        tot = _sum_over(stk, s_iyr, classes, allf, iregn)
        bev = _sum_over(stk, s_iyr, classes, [6], iregn)
        phev = _sum_over(stk, s_iyr, classes, [7, 8], iregn)
        fcv = _sum_over(stk, s_iyr, classes, [9, 10], iregn)
        zev = (bev + fcv) * w
        nzev = phev * w * pf if n <= 2035 - 1989 else ZERO
        return tot, zev, nzev

    tot, c["credit_2b3_zev"][iregn, n], c["credit_2b3_nzev"][iregn, n] = group([1, 2, 3, 4], wm[1])
    local["d2b3"][iregn] = tot * wm[1] * v["act_req_2b3"][iregn, n]
    tot, z45, nz45 = group([5, 6], wm[5])
    d45 = tot * wm[5]
    tot, z67, nz67 = group([7, 8], wm[7])
    d67 = tot * wm[7]
    tot, z8, nz8 = group([12], wm[12])
    d8 = tot * wm[12]
    local["d48v"][iregn] = (d45 + d67 + d8) * v["act_req_48v"][iregn, n]
    c["credit_48v_zev"][iregn, n] = z45 + z67 + z8
    c["credit_48v_nzev"][iregn, n] = nz45 + nz67 + nz8
    tot, c["credit_78t_zev"][iregn, n], c["credit_78t_nzev"][iregn, n] = group(TRACTORS, wm[13])
    local["d78t"][iregn] = tot * wm[13] * v["act_req_78trac"][iregn, n]


def _spend_nzev(bank, d48, d2b3, mx):
    """Near-ZEV credits from one bank against the 4-8 vocational, then 2b-3, deficits."""
    if bank >= mx:
        if d48 <= mx:
            bank = bank - d48
            mx = mx - d48
            d48 = ZERO
            d2b3 = d2b3 - mx
            bank = bank - mx
            mx = ZERO
        else:
            bank = bank - mx
            d48 = d48 - mx
            mx = ZERO
    else:
        if bank >= d48:
            bank = bank - d48
            d48 = ZERO
            d2b3 = d2b3 - bank
        else:
            d48 = d48 - bank
            bank = ZERO
    return bank, d48, d2b3, mx


def truck_act(s: dict, carry: dict) -> None:
    v = V(s)
    iyr, n, yrs = v.i("iyr"), v.i("n"), v.i("yrs")
    c = carry
    if n == 2021 - 1989:
        for k in ("bank_2b8v_zev", "bank_2b8v_nzev", "bank_78t_zev", "bank_78t_nzev"):
            c[k].a[...] = 0.0
    local = {k: np.zeros(MNUMCR + 1, dtype=f32) for k in ("d2b3", "d48v", "d78t")}
    for iregn in range(1, MNUMCR - 1):
        v["iregn"] = iregn
        _credits(v, iyr, n, iregn, local, c)
        b2z, b2n, b7z, b7n = (c[k] for k in ("bank_2b8v_zev", "bank_2b8v_nzev", "bank_78t_zev", "bank_78t_nzev"))
        b2z[iregn, n] = b2z[iregn, n - 1] + c["credit_48v_zev"][iregn, n] + c["credit_2b3_zev"][iregn, n]
        b2n[iregn, n] = b2n[iregn, n - 1] + c["credit_48v_nzev"][iregn, n] + c["credit_2b3_nzev"][iregn, n]
        b7z[iregn, n] = b7z[iregn, n - 1] + c["credit_78t_zev"][iregn, n]
        b7n[iregn, n] = b7n[iregn, n - 1] + c["credit_78t_nzev"][iregn, n]
        if yrs > 2030:
            w = lambda k: fsum(c[k][iregn, n - 5:n])  # noqa: E731
            b2z[iregn, n] = max(ZERO, min(b2z[iregn, n], w("credit_48v_zev") + w("credit_2b3_zev")))
            b2n[iregn, n] = max(ZERO, min(b2n[iregn, n], w("credit_48v_nzev") + w("credit_2b3_nzev")))
            b7z[iregn, n] = max(ZERO, min(b7z[iregn, n], w("credit_78t_zev")))
            b7n[iregn, n] = max(ZERO, min(b7n[iregn, n], w("credit_78t_nzev")))
        if n >= 2024 - 1989:
            d2b3, d48, d78 = local["d2b3"][iregn], local["d48v"][iregn], local["d78t"][iregn]
            mx2 = (d48 + d2b3) * f32(0.5)
            mx78 = d78 * f32(0.5)
            if b7n[iregn, n] >= mx78:
                b7n[iregn, n] = b7n[iregn, n] - mx78
                d78 = d78 - mx78
            else:
                d78 = d78 - b7n[iregn, n]
                b7n[iregn, n] = 0.0
            if mx2 > 0.0:
                b2n[iregn, n], d48, d2b3, mx2 = _spend_nzev(b2n[iregn, n], d48, d2b3, mx2)
            if mx2 > 0.0:
                b7n[iregn, n], d48, d2b3, mx2 = _spend_nzev(b7n[iregn, n], d48, d2b3, mx2)
            if b7z[iregn, n] >= d78:
                b7z[iregn, n] = b7z[iregn, n] - d78
                d78 = ZERO
            else:
                d78 = d78 - b7z[iregn, n]
                b7z[iregn, n] = 0.0
            if b2z[iregn, n] >= (d48 + d2b3):
                b2z[iregn, n] = b2z[iregn, n] - d48 - d2b3
                d48 = d2b3 = ZERO
            else:
                bk = b2z[iregn, n]
                s2 = bk * d2b3 / (d2b3 + d48)
                s48 = bk - s2
                if s2 > d2b3:
                    b2z[iregn, n] = b2z[iregn, n] - d2b3
                    d2b3 = ZERO
                else:
                    d2b3 = d2b3 - s2
                    b2z[iregn, n] = b2z[iregn, n] - s2
                if s48 > d48:
                    b2z[iregn, n] = b2z[iregn, n] - d48
                    d48 = ZERO
                else:
                    d48 = d48 - s48
                    b2z[iregn, n] = b2z[iregn, n] - s48
            if b7z[iregn, n] >= (d48 + d2b3):
                b7z[iregn, n] = b7z[iregn, n] - d48 - d2b3
                d48 = d2b3 = ZERO
            else:
                if b7z[iregn, n] >= d48:
                    b7z[iregn, n] = b7z[iregn, n] - d48
                    d48 = ZERO
                else:
                    d48 = d48 - b7z[iregn, n]
                    b7z[iregn, n] = 0.0
                if b7z[iregn, n] >= d2b3:
                    b7z[iregn, n] = b7z[iregn, n] - d2b3
                    d2b3 = ZERO
                else:
                    d2b3 = d2b3 - b7z[iregn, n]
                    b7z[iregn, n] = 0.0
            local["d2b3"][iregn], local["d48v"][iregn], local["d78t"][iregn] = d2b3, d48, d78
    v["iregn"] = MNUMCR - 1

    stk = v["trkstk_19r"]
    if n >= 2024 - 1989:
        _force_zevs(v, iyr, n, local)
        for iregn in range(1, MNUMCR - 1):
            _credits(v, iyr, n, iregn, local, c)
        v["iregn"] = MNUMCR - 1

    shr_r, shr_v, sc19 = v["fuel_shr_regn"], v["fuel_shr_ivmt"], v["sc19map"]
    for iregn in range(1, MNUMCR - 1):
        for iflt in (1, 2):
            for c19 in range(1, CAFE19 + 1):
                v["isc4"] = int(sc19[c19])
                for ifuel in range(1, FUEL12 + 1):
                    shr_r[iyr, c19, ifuel, iflt, iregn] = 0.0
                    tot = fsum(stk[iyr, c19, 1, :, iflt, iregn])
                    if tot > 0.0:
                        shr_r[iyr, c19, ifuel, iflt, iregn] = fsum(shr_v[iyr, :, iflt, c19, ifuel, iregn])
                    stk[iyr, c19, 1, ifuel, iflt, iregn] = shr_r[iyr, c19, ifuel, iflt, iregn] * fsum(stk[iyr, c19, 1, :, iflt, iregn])
                    if iregn == MNUMCR - 2:
                        stk[iyr, c19, 1, ifuel, iflt, MNUMCR] = fsum(stk[iyr, c19, 1, ifuel, iflt, 1:MNUMCR - 2])
    v.s.update({v.key("iregn"): MNUMCR - 1, v.key("iflt"): 3, v.key("icafe19"): CAFE19 + 1, v.key("ifuel"): FUEL12 + 1})


def _force_zevs(v, iyr, n, local):
    stk, req = v["trkstk_19r"], v["zevreq"]
    wm, shr78 = v["act_wgtmod"], v["zevreqshr78"]
    req[:, :, :, n] = 0.0

    def tot_of(classes, fuels, iflt, iregn):
        sub = stk.a[iyr - 1, :, 0, :, :, iregn - 1]          # (cafe19, fuel, flt)
        sub = sub[[cc - 1 for cc in classes]][:, [f - 1 for f in fuels]]
        if iflt is not None:
            sub = sub[:, :, iflt - 1]
        return fsum(sub)

    for iregn in range(1, MNUMCR - 1):
        for iflt in (1, 2):
            for c19 in range(1, 5):
                req[iregn, iflt, c19, n] = (tot_of([c19], CONVHEV, iflt, iregn) / tot_of([1, 2, 3, 4], CONVHEV, None, iregn)
                                            * local["d2b3"][iregn] / wm[c19])
            t48 = tot_of([5, 6], CONVHEV, None, iregn) + tot_of([7, 8], CONVHEV, None, iregn) + tot_of([12], CONVHEV, None, iregn)
            for c19 in range(5, 13):
                if 9 <= c19 <= 11:
                    continue
                req[iregn, iflt, c19, n] = local["d48v"][iregn] * (tot_of([c19], CONVHEV, iflt, iregn) / t48) / wm[c19]
            day = tot_of([9, 10, 11, 13, 14, 15], CONVHEV, None, iregn)
            sleep = tot_of([16, 17, 18], CONVHEV, None, iregn)
            for c19 in range(9, 19):
                if c19 == 12:
                    continue
                if c19 <= 15:
                    req[iregn, iflt, c19, n] = (local["d78t"][iregn] * shr78[1]) * (tot_of([c19], CONVHEV, iflt, iregn) / day) / wm[c19]
                else:
                    req[iregn, iflt, c19, n] = (local["d78t"][iregn] * shr78[2]) * (tot_of([c19], CONVHEV, iflt, iregn) / sleep) / wm[c19]

    shr_r, shr_v, veh = v["fuel_shr_regn"], v["fuel_shr_ivmt"], v["veh_shr"]
    npv, pback = v["npv_choice"], v["pback_shr"]
    bev, fcev, fchev, infra = v["inc_cost_bev"], v["inc_cost_fcev"], v["inc_cost_fchev"], v["bev_infra_cost"]
    comp = v["act_comp_cost"]
    ice_shr = v.priv("ice_shr", lambda: np.zeros(NVMT + 1, dtype=f32))
    icehev_shr = v.priv("icehev_shr", lambda: np.zeros(NVMT + 1, dtype=f32))
    ice_iv = v.priv("ice_shr_ivmt", lambda: np.zeros((NVMT + 1, len(CONV)), dtype=f32))
    icehev_iv = v.priv("icehev_shr_ivmt", lambda: np.zeros((NVMT + 1, len(CONVHEV)), dtype=f32))
    for iregn in range(1, MNUMCR - 1):
        v["iregn"] = iregn
        for c19 in range(1, CAFE19 + 1):
            v["icafe19"] = c19
            comp[c19, iregn, iyr] = 0.0
            for iflt in (1, 2):
                v["iflt"] = iflt
                pre = fsum(stk[iyr, c19, 1, :, iflt, iregn])
                if req[iregn, iflt, c19, n] == 0.0:
                    continue
                carry_req = ZERO
                avail = pre * fsum(np.array([shr_r[iyr, c19, k, iflt, iregn] for k in CONV], dtype=f32))
                use_hev = req[iregn, iflt, c19, n] > avail
                ice_iv[...] = 0.0
                icehev_iv[...] = 0.0
                for ivmt in range(1, NVMT + 1):
                    v["ivmt"] = ivmt
                    if veh[ivmt, iflt, c19] == 0.0:
                        continue
                    if ivmt == 1:
                        for i in range(1, NVMT + 1):
                            for k, f in enumerate(CONV):
                                ice_iv[i, k] = shr_v[iyr, i, iflt, c19, f, iregn]
                            for k, f in enumerate(CONVHEV):
                                icehev_iv[i, k] = shr_v[iyr, i, iflt, c19, f, iregn]
                        t1, t2 = fsum(ice_iv[1:]), fsum(icehev_iv[1:])
                        for i in range(1, NVMT + 1):
                            ice_shr[i] = fsum(ice_iv[i]) / t1
                            icehev_shr[i] = fsum(icehev_iv[i]) / t2
                    zr = req[iregn, iflt, c19, n] * ice_shr[ivmt] + carry_req
                    avail = pre * fsum(ice_iv[ivmt])
                    if use_hev:
                        zr = req[iregn, iflt, c19, n] * icehev_shr[ivmt] + carry_req
                        avail = pre * fsum(icehev_iv[ivmt])
                    if zr < 0.5:
                        continue
                    if zr > avail:
                        if ivmt < NVMT and veh[ivmt + 1, iflt, c19] > 0.0:
                            carry_req = zr - avail
                            zr = avail
                        elif iflt == 1 and veh[1, iflt + 1, c19] > 0.0:
                            req[iregn, 2, c19, n] = req[iregn, 2, c19, n] + (zr - avail)
                            zr = avail
                        elif c19 < 18:
                            req[iregn, 1, c19, n] = req[iregn, 1, c19, n] + (zr - avail) * wm[c19] / wm[c19 + 1]
                            zr = avail
                    avg = []
                    for f in ZEV:
                        v["ifuel"] = f
                        avg.append(fsum(pback[:, c19] * npv[c19, f, ivmt, :, iregn, iyr]))
                    a = np.zeros(3, dtype=f32)
                    if iflt == 1 or c19 >= 16:
                        a[0] = avg[0] - (bev[ivmt, c19, iyr] - infra[c19, iyr])
                    else:
                        a[0] = avg[0] - bev[ivmt, c19, iyr]
                    a[1] = avg[1] - fcev[ivmt, c19, iyr]
                    a[2] = avg[2] - fchev[ivmt, c19, iyr]
                    a = a / f32(10000)
                    tot = (expf(a[0]) + expf(a[1]) + expf(a[2]))
                    a = np.array([expf(a[i]) / tot for i in range(3)], dtype=f32)
                    if c19 <= 4:
                        a = np.array([ONE, ZERO, ZERO], dtype=f32)
                    comp[c19, iregn, iyr] = comp[c19, iregn, iyr] + fsum(a * np.array(avg, dtype=f32)) * zr
                    if use_hev:
                        zr_hev = zr - fsum(ice_iv[ivmt]) * pre
                        for k, f in enumerate(CONV):
                            stk[iyr, c19, 1, f, iflt, iregn] = stk[iyr, c19, 1, f, iflt, iregn] - ice_iv[ivmt, k] * pre
                            shr_v[iyr, ivmt, iflt, c19, f, iregn] = 0.0
                        stk[iyr, c19, 1, 11, iflt, iregn] = stk[iyr, c19, 1, 11, iflt, iregn] - zr_hev
                        shr_v[iyr, ivmt, iflt, c19, 11, iregn] = shr_v[iyr, ivmt, iflt, c19, 11, iregn] - zr_hev / pre
                    else:
                        tice = fsum(ice_iv[ivmt])
                        for k, f in enumerate(CONV):
                            stk[iyr, c19, 1, f, iflt, iregn] = stk[iyr, c19, 1, f, iflt, iregn] - ice_iv[ivmt, k] / tice * zr
                            shr_v[iyr, ivmt, iflt, c19, f, iregn] = (shr_v[iyr, ivmt, iflt, c19, f, iregn]
                                                                     - ice_iv[ivmt, k] / tice * zr / pre)
                    for k, f in enumerate(ZEV):
                        stk[iyr, c19, 1, f, iflt, iregn] = stk[iyr, c19, 1, f, iflt, iregn] + zr * a[k]
                    for k, f in enumerate(ZEV):
                        shr_v[iyr, ivmt, iflt, c19, f, iregn] = shr_v[iyr, ivmt, iflt, c19, f, iregn] + zr * a[k] / pre
                    for i in range(1, FUEL12 + 1):
                        if i in (6, 9, 10):
                            continue
                        x = stk[iyr, c19, 1, i, iflt, iregn]
                        if x < 0.0 and x > -1.0:
                            stk[iyr, c19, 1, i, iflt, iregn] = 0.0
                    if np.isnan(fsum(stk[iyr, c19, 1, :, iflt, iregn])) and v.i("fcrl") == 1:
                        raise ValueError("TDM TRUCK_ACT: STOP 902, NaN truck sales")
                v["ivmt"] = NVMT + 1
