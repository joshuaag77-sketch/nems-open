"""Freight drivers (tranfrt.f): TRANFRT, the per-call part of INIT, and TRUCK_NEW.

TRANFRT(0)  heat rates, lagged VMT, industrial output by freight sector, fuel prices,
            then TRUCK_NEW, TRUCK_STOCK, TRUCK_VMT, TCOMMCL_TRK, TRUCK_FUEL, and VMT
            and MPG totals by size class
TRUCK_NEW   new truck sales by class and region, five-year fuel prices, then up to
            GHGTRY tries of technology adoption, costs, powertrain choice, ACT, and
            GHG compliance; battery, fuel cell and tank production for learning

carry (saved locals): techpenyr_p2, cpm_r_ice, TRUCK_PBK's curve history, the ACT
credits and banks, ghgbank, and TRUCK_VMT's ttonmi, tvmt, temp_stk_vmt_ratio.
"""

import numpy as np

from nems_open.transportation.common import MNUMCR, f32, fsum
from nems_open.transportation import frt_act, frt_agg, frt_choice, frt_cost, frt_fuel, frt_ghg, frt_stock, frt_tech, frt_vmt
from nems_open.transportation.frt_common import AGE, CAFE19, FUEL12, NVMT, ONE, SC, V
from nems_open.transportation.mean_funcs import harmonic_mean

R9 = slice(1, MNUMCR - 2)
A11 = slice(1, MNUMCR)
CUR, LAG = 2, 1
NFT, FLT = 1, 2

# Heat rate per fuel: diesel-like (CFDSTR) or gasoline-like (CFMGQ). Fuel 4 (CNG/LNG)
# depends on the size class: LNG for class 7-8.
HRATE_DIESEL = {1, 6, 7, 9, 10, 12}


def tranfrt_pre(s: dict) -> None:
    """TRANFRT up to TRUCK_NEW: lagged VMT, heat rates, and INIT's per-call part."""
    v = V(s)
    n = v.i("curiyr")
    s.update({v.key("iyr"): n, v.key("itr"): v.i("curitr"), v.key("n"): n, v.key("yrs"): v.i("curcalyr"),
              v.key("first_read_year"): 1995, v.key("iy"): 1995 - 1990 + 1,
              v.key("num_to_read"): v.i("ijumpyr") - (1995 - 1990)})
    vmt = v["vmtflt"]
    if v.i("curitr") == 1:
        vmt[LAG, :, :, :, :] = vmt[CUR, :, :, :, :]
    hr = v["hrate"]
    ds = v["cfdstr"][n] / f32(42) * f32(1000000)
    mg = v["cfmgq"][n] / f32(42) * f32(1000000)
    for f in range(1, FUEL12 + 1):
        if f == 4:
            hr[1, 4], hr[2, 4], hr[3, 4], hr[4, 4] = mg, mg, ds, mg
        else:
            hr[:, f] = ds if f in HRATE_DIESEL else mg

    iyr = n
    rev, ser, tsic = v["mc_revind"], v["mc_revser"], v["tsic"]
    tsic[:, :, iyr] = 0.0
    r = lambda k: rev[A11, k, iyr]  # noqa: E731
    rs = lambda a, b: fsum(rev[A11, a:b, iyr], axis=1)  # noqa: E731
    tsic[1, A11, iyr] = rs(15, 20) - r(17) - r(19) - r(21)
    tsic[2, A11, iyr] = rs(33, 35)
    tsic[3, A11, iyr] = rs(2, 5)
    tsic[4, A11, iyr] = rs(11, 13)
    tsic[5, A11, iyr] = rs(25, 26)
    tsic[6, A11, iyr] = r(28) + r(30) + r(32)
    tsic[7, A11, iyr] = rs(36, 40) - r(38)
    tsic[8, A11, iyr] = rs(7, 8) + r(14) + r(41)
    tsic[9, A11, iyr] = rs(42, 44)
    tsic[10, A11, iyr] = rs(45, 47)
    for k, col in ((11, 6), (12, 21), (13, 19), (14, 27), (15, 38), (16, 9)):
        tsic[k, A11, iyr] = r(col)
    tsic[17, A11, iyr] = fsum(ser[A11, 3:4, iyr], axis=1)
    tsic[18, A11, iyr] = ser[A11, 10, iyr]
    tsic[1:16, :, iyr] = tsic[1:16, :, iyr] * f32(1000.)

    d = v["cltvmtdist"]
    R = lambda k: rev[11, k, n]  # noqa: E731
    S = lambda a, b: fsum(rev[11, a:b, n])  # noqa: E731
    v["cltsic"][n] = (R(42) * d[1] + S(45, 47) * d[2] + R(48) * d[3]
                      + (S(1, 41) - S(2, 5) - S(11, 13) - S(21, 24) - R(17) - R(29)) * d[4]
                      + fsum(ser[11, 3:4, n]) * d[5]
                      + (fsum(v["vmthh"][n, R9, :, :]) + fsum(v["fltechvmt"][MNUMCR, :, :, :, :]) / f32(1000000000.0)) * d[6])

    fp, jp = v["fuelprice_r"], v["mc_jpgdp"][1]
    pmg, pds, pel = v["pmgtr"][A11, iyr], v["pdstr"][A11, iyr], v["pelibcm"][A11, iyr]
    adj, cs = v["ng_priceadj"], v["cng_shrof_ng"][n]
    phev = fsum(v["phevelecvmt"][:]) / f32(CAFE19)
    fp[iyr, 1, A11] = pds * jp
    fp[iyr, 2, A11] = pmg * jp
    fp[iyr, 3, A11] = v["plgtr"][A11, iyr] * jp
    fp[iyr, 4, A11] = (((v["pgftrfv"][A11, iyr] + v["pgftrpv"][A11, iyr]) * adj[1] * cs
                        + (v["pgltrfv"][A11, iyr] + v["pgltrpv"][A11, iyr]) * adj[2] * (ONE - cs)) * jp)
    fp[iyr, 5, A11] = np.minimum(v["pettr"][A11, iyr], pmg) * jp
    fp[iyr, 6, A11] = pel * jp
    fp[iyr, 7, A11] = (phev * pel + (ONE - phev) * pds) * jp
    fp[iyr, 8, A11] = (phev * pel + (ONE - phev) * pmg) * jp
    fp[iyr, 9, A11] = v["ph2tr"][A11, iyr] * jp
    fp[iyr, 10, A11] = v["ph2tr"][A11, iyr] * jp
    fp[iyr, 11, A11] = pmg * jp
    fp[iyr, 12, A11] = v["ph2tr"][A11, iyr] * jp * (ONE - v["h2ice_fueldisc"])


def truck_new_pre(s: dict) -> None:
    v = V(s)
    iyr, yrs = v.i("iyr"), v.i("yrs")
    new, stk = v["newtrucks_regn"], v["trkstk_19r"]
    if yrs > v.i("bsyr_stk"):
        new[iyr, 1:CAFE19, 1:2, 1:MNUMCR] = 0.0
        veh, lt, suv = v["mc_vehicles"], v["ltsplit"], v["mc_suvtham"]
        fs = v["fltshr_sales"]
        for iregn in range(1, MNUMCR - 1):
            for c19 in range(1, CAFE19 + 1):
                prev = fsum(stk[iyr - 1, c19, 1, :, :, iregn])
                if c19 <= 2:
                    base = fsum(veh[1:2, iyr]) * (ONE - lt[iyr]) * f32(1000000.) * prev / fsum(stk[iyr - 1, 1:2, 1, :, :, MNUMCR])
                elif c19 <= 4:
                    base = veh[3, iyr] * f32(1000000.) * prev / fsum(stk[iyr - 1, 3:4, 1, :, :, MNUMCR])
                else:
                    base = suv[iyr] * f32(1000000.) * prev / fsum(stk[iyr - 1, 5:19, 1, :, :, MNUMCR])
                new[iyr, c19, FLT, iregn] = base * fs[iyr, c19]
                new[iyr, c19, NFT, iregn] = new[iyr, c19, FLT, iregn] / fs[iyr, c19] * (ONE - fs[iyr, c19])
            if iregn == 9:
                for iflt in (1, 2):
                    for c19 in range(1, CAFE19 + 1):
                        new[iyr, c19, iflt, 11] = fsum(new[iyr, c19, iflt, R9])
                v.s.update({v.key("iflt"): 3})
        v.s.update({v.key("iregn"): MNUMCR - 1, v.key("icafe19"): CAFE19 + 1})
    fp, avg = v["fuelprice_r"], v["fuelprice_r_avg"]
    for ifuel in range(1, FUEL12 + 1):
        for iregn in range(1, MNUMCR - 1):
            avg[ifuel, iregn] = fsum(fp[iyr - 4:iyr, ifuel, iregn]) / f32(5.0)
        avg[ifuel, MNUMCR] = fsum(fp[iyr - 4:iyr, ifuel, MNUMCR]) / f32(5.0)
    v.s.update({v.key("ifuel"): FUEL12 + 1, v.key("iregn"): MNUMCR - 1})


def truck_new_loop(s: dict, carry: dict) -> None:
    """The GHG retry loop."""
    v = V(s)
    iyr, yrs = v.i("iyr"), v.i("yrs")
    if yrs <= 2017:
        return
    passed = v["hdv_passghg"]
    ghgtry = v["ghgtry"]
    for itry in range(1, ghgtry + 1):
        v["itryghg"] = itry
        if itry == 1:
            passed[iyr, :] = 0
        frt_tech.truck_techadopt(s, carry)
        if yrs > v.i("bsyr_stk"):
            frt_cost.truck_inccost(s)
            frt_choice.truck_choice(s, carry)
        if v.i("act_switch") == 1 and yrs >= 2021:
            frt_act.truck_act(s, carry)
        frt_agg.truck_aggvars(s)
        frt_ghg.truck_ghgmeet(s, carry)
        if passed[iyr, :].all():
            return
        if itry == ghgtry and yrs >= 2021:
            frt_ghg.truck_ghgzev(s)
            frt_agg.truck_aggvars(s)
            if passed[iyr, :].all():
                return
            v["icafe4"] = 5
    v["itryghg"] = ghgtry + 1


def truck_new_post(s: dict) -> None:
    v = V(s)
    iyr, yrs = v.i("iyr"), v.i("yrs")
    stk = v["trkstk_19r"]
    if yrs > v.i("bsyr_stk"):
        names = ["avg_batt_kwh_bev", "avg_batt_kwh_phevd", "avg_batt_kwh_phevg", "avg_batt_kwh_fcev",
                 "avg_tank_cnt_fcev", "avg_batt_kwh_fchev", "avg_tank_cnt_fchev", "avg_tank_cnt_h2ice"]
        for k in names:
            v[k][iyr, :, :, :] = 0.0
        share = v["phev_evmt_share"]
        share[iyr, :, :, :, :] = 0.0
        shr_v, sc19 = v["fuel_shr_ivmt"], v["sc19map"]
        nom, pbk = v["kwh_nominal"], v["pt_battkwh_phev"]
        hr, mpg19, vveh = v["hrate"], v["new_mpg_19"], v["vmt_veh"]
        dod, adj, days = v["trk_phev_dod"], v["phev_mpg_adj"], v["ann_uptime_days"]
        for iregn in range(1, MNUMCR - 1):
            for iflt in (1, 2):
                for c19 in range(1, CAFE19 + 1):
                    isc = int(sc19[c19])
                    v["isc"] = isc
                    for ifuel in range(6, FUEL12 + 1):
                        tot = fsum(shr_v[iyr, 1:NVMT, iflt, c19, ifuel, iregn])
                        if not tot > 0.0:
                            continue
                        for ivmt in range(1, NVMT + 1):
                            w = shr_v[iyr, ivmt, iflt, c19, ifuel, iregn] / tot
                            key = (iyr, iflt, c19, iregn)
                            if ifuel == 6:
                                v["avg_batt_kwh_bev"][key] = v["avg_batt_kwh_bev"][key] + w * nom[ivmt, c19, iyr]
                            elif ifuel in (7, 8):
                                kk = "avg_batt_kwh_phevd" if ifuel == 7 else "avg_batt_kwh_phevg"
                                v[kk][key] = v[kk][key] + w * pbk[ivmt, c19]
                                uf = min(ONE, ((pbk[ivmt, c19] * dod * f32(3412.0) / hr[isc, 6]) * mpg19[iyr, 6, c19] * adj) * days
                                         / vveh[ivmt, iflt, c19])
                                share[iyr, iflt, c19, iregn, ifuel - 6] = share[iyr, iflt, c19, iregn, ifuel - 6] + w * uf
                            elif ifuel == 9:
                                v["avg_batt_kwh_fcev"][key] = v["avg_batt_kwh_fcev"][key] + w * v["pt_battkwh_fcev"][ivmt, c19]
                                v["avg_tank_cnt_fcev"][key] = v["avg_tank_cnt_fcev"][key] + w * v["pt_tankcnt_fcev"][ivmt, c19]
                            elif ifuel == 10:
                                v["avg_batt_kwh_fchev"][key] = v["avg_batt_kwh_fchev"][key] + w * v["pt_battkwh_fchev"][ivmt, c19]
                                v["avg_tank_cnt_fchev"][key] = v["avg_tank_cnt_fchev"][key] + w * v["pt_tankcnt_fchev"][ivmt, c19]
                            elif ifuel == 12:
                                v["avg_tank_cnt_h2ice"][key] = v["avg_tank_cnt_h2ice"][key] + w * v["pt_tankcnt_h2ice"][ivmt, c19]
                        v["ivmt"] = NVMT + 1
                    v["ifuel"] = FUEL12 + 1
        v.s.update({v.key("iregn"): MNUMCR - 1, v.key("iflt"): 3, v.key("icafe19"): CAFE19 + 1})
        gwh = tanks = f32(0.0)
        C = slice(1, CAFE19)
        for iflt in (1, 2):
            t = lambda f, k: fsum(stk[iyr, C, 1, f, iflt, R9] * v[k][iyr, iflt, C, R9])  # noqa: E731
            hev = np.broadcast_to(v["pt_battkwh_hev"][C][:, None], (CAFE19, MNUMCR - 2))
            gwh = (gwh + t(6, "avg_batt_kwh_bev") + t(7, "avg_batt_kwh_phevd") + t(8, "avg_batt_kwh_phevg")
                   + t(9, "avg_batt_kwh_fcev") + t(10, "avg_batt_kwh_fchev") + fsum(stk[iyr, C, 1, 11, iflt, R9] * hev))
            tanks = tanks + t(9, "avg_tank_cnt_fcev") + t(10, "avg_tank_cnt_fchev") + t(12, "avg_tank_cnt_h2ice")
        v["iflt"] = 3
        sub = stk.a[iyr - 1, 0:CAFE19, 0, :, 0:2, 0:9][:, [8, 9]]          # (cafe19, [9,10], flt, regn)
        stacks = fsum(sub)
        v["global_batt_prod"][2, 1, iyr] = v["global_batt_prod"][2, 1, iyr - 1] + gwh / f32(1000000.0)
        v["cumulative_fc_stacks"][iyr] = v["cumulative_fc_stacks"][iyr - 1] + stacks
        v["cumulative_h2_tanks"][iyr] = v["cumulative_h2_tanks"][iyr - 1] + tanks

    if yrs > 2017:
        ts, shr19, stk19, rmap = v["techshare"], v["techshr_p2"], v["trkstk_19"], v["techrptmap"]
        techp2 = v["techp2"]
        ts[iyr, :, :, :] = 0.0
        for it in range(1, techp2 + 1):
            sal = np.zeros((11, FUEL12 + 1), dtype=f32)
            for ifuel in (1, 2):
                for c19 in range(1, CAFE19 + 1):
                    r = int(rmap[c19])
                    ts[iyr, it, r, ifuel] = ts[iyr, it, r, ifuel] + shr19[iyr, it, c19, ifuel] * stk19[iyr, c19, 1, ifuel]
                    sal[r, ifuel] = sal[r, ifuel] + stk19[iyr, c19, 1, ifuel]
            ts[iyr, it, :, :] = ts[iyr, it, :, :] / fsum(sal[1:, 1:])
        v.s.update({v.key("itechp2"): techp2 + 1, v.key("ifuel"): 3, v.key("icafe19"): CAFE19 + 1,
                    v.key("itechrpt19"): int(rmap[CAFE19])})


def truck_new(s: dict, carry: dict) -> None:
    truck_new_pre(s)
    truck_new_loop(s, carry)
    truck_new_post(s)


def tranfrt_post(s: dict) -> None:
    v = V(s)
    iyr = v.i("iyr")
    sf, saf, vfr = v["vmtflt_sf_tr"], v["vmtflt_saf_tr"], v["vmtfltr"]
    saff = np.zeros(SC + 1, dtype=f32)
    for isc in range(1, SC + 1):
        for ifuel in range(1, FUEL12 + 1):
            for iregn in range(1, MNUMCR + 1):
                for iage in range(1, AGE + 1):
                    sf[isc, iage, ifuel, iregn] = fsum(vfr[CUR, isc, iage, ifuel, 1:2, iregn])
                saf[isc, ifuel, iregn] = fsum(sf[isc, 1:AGE, ifuel, iregn])
        saff[isc] = fsum(saf[isc, 1:FUEL12, R9])
    v["vmt_tr"][iyr] = fsum(saf[1:SC, 1:FUEL12, R9])
    hdv, sff, ss = v["hdv_mpg"], v["hdv_mpg_s_f"], v["hdv_mpg_s"]
    for isc in range(1, SC + 1):
        for ifuel in range(1, FUEL12 + 1):
            sff[iyr, isc, ifuel] = harmonic_mean(hdv[iyr, isc, 1:AGE, ifuel], sf[isc, 1:AGE, ifuel, 11])
            if sff[iyr, isc, ifuel] == 0:
                sff[iyr, isc, ifuel] = sff[iyr - 1, isc, ifuel]
        ss[iyr, isc] = harmonic_mean(sff[iyr, isc, 1:FUEL12], saf[isc, 1:FUEL12, 11])
        if ss[iyr, isc] == 0:
            ss[iyr, isc] = ss[iyr - 1, isc]
    v["trftmpg"][iyr] = harmonic_mean(ss[iyr, 1:SC], saff[1:])
    v.s.update({v.key("isc"): SC + 1, v.key("ifuel"): FUEL12 + 1, v.key("iregn"): MNUMCR + 1, v.key("iage"): AGE + 1})


def tranfrt(s: dict, carry: dict) -> None:
    """TRANFRT(0) after the first call's file reads."""
    tranfrt_pre(s)
    if V(s).i("yrs") > 2017:
        truck_new(s, carry)
    frt_stock.truck_stock(s)
    frt_vmt.truck_vmt(s, carry)
    frt_vmt.tcommcl_trk(s)
    frt_fuel.truck_fuel(s)
    tranfrt_post(s)
