"""TRUCK_INCCOST (tranfrt.f): incremental purchase cost of each alternative truck.

Against the diesel or gasoline truck of the same class: the ICE technology cost,
low-NOx rule cost, CNG tanks, battery packs sized to daily range (BEV, PHEV),
fuel cell stacks and hydrogen tanks on learning curves, motors, chargers and
depot equipment, IRA 45W credits, and the federal excise tax.

EIA quirk kept: the FCHEV refueling-time penalty subtracts 2 tank-fills a day where
FCEV and H2 ICE subtract 1.
"""

import math

import numpy as np

from nems_open.transportation.common import f32, fsum, MNUMCR, powf
from nems_open.transportation.frt_common import CAFE19, NVMT, ONE, V, ZERO
from nems_open.transportation.misc_modes import powi

VM = slice(1, NVMT)


def _ira(v, k, c19, n, cost, yrs):
    """IRA 45W credit for powertrain k, capped by the cost it offsets."""
    cred = v["ira_credit"]
    if 2023 <= yrs <= 2032:
        if v.i("switchhdv_hr1") == 0 or yrs <= 2025:
            cap = v["ira_45w_max"][c19, k] / v["mc_jpgdp"][n] * v["mc_jpgdp"][1]
            cred[k, VM, c19, n] = np.maximum(ZERO, np.minimum(cap, cost))
        return cred[k, VM, c19, n]
    return None


def truck_inccost(s: dict) -> None:
    v = V(s)
    iyr, n, yrs = v.i("iyr"), v.i("n"), v.i("yrs")
    bsyr = v.i("bsyr_stk")
    b = bsyr - 1989
    stk = v["trkstk_19r"]
    ice, icetech, itc = v["cost_ice"], v["cost_icetech"], v["inc_tech_cost_19"]
    v["ira_credit"][:, :, :, n] = 0.0
    if yrs != bsyr:
        ice[:, iyr] = 0.0
    tot12 = lambda c19, f: fsum(stk[iyr - 1, c19, 1, f, :, MNUMCR])  # noqa: E731
    for c19 in range(1, CAFE19 + 1):
        both = fsum(stk[iyr - 1, c19, 1, 1:2, :, MNUMCR])
        if both == 0.0:
            ice[c19, iyr] = ice[c19, iyr - 1]
        else:
            if c19 <= 7:
                icetech[c19, iyr] = (itc[iyr, c19, 1] * tot12(c19, 1) + itc[iyr, c19, 2] * tot12(c19, 2)) / both
            else:
                icetech[c19, iyr] = itc[iyr, c19, 1]
            if yrs > bsyr:
                ice[c19, iyr] = ice[c19, b] + (icetech[c19, iyr] - icetech[c19, b])
    v["icafe19"] = CAFE19 + 1
    C = slice(1, CAFE19)
    if yrs > bsyr:
        v["cost_ice_hev"][C, iyr] = v["cost_ice_hev"][C, b] + (itc[iyr, C, 2] - itc[b, C, 2])
        v["cost_ice_phev"][C, 1, iyr] = v["cost_ice_phev"][C, 1, b] + (itc[iyr, C, 1] - itc[b, C, 1])
        v["cost_ice_phev"][C, 2, iyr] = v["cost_ice_phev"][C, 2, b] + (itc[iyr, C, 2] - itc[b, C, 2])
        v["cost_ice_h2ice"][C, iyr] = v["cost_ice_h2ice"][C, b] + (itc[iyr, C, 1] - itc[b, C, 1])

    lonox, clonox = v["lonox_cost"], v["cost_lonox"]
    nox = v.i("nox_switch") == 1
    lonox[:, iyr] = 0.0
    if iyr >= 2027 - 1989 and nox:
        for c19 in range(1, CAFE19 + 1):
            both = fsum(stk[iyr - 1, c19, 1, 1:2, :, MNUMCR])
            if both == 0.0:
                lonox[c19, iyr] = lonox[c19, iyr - 1]
            elif c19 <= 7:
                lonox[c19, iyr] = (clonox[c19, 1] * tot12(c19, 1) + clonox[c19, 2] * tot12(c19, 2)) / both
            else:
                lonox[c19, iyr] = clonox[c19, 1]
        v["icafe19"] = CAFE19 + 1

    fet, sc19 = v["fet_rate"], v["sc19map"]
    cng = v["inc_cost_cng"]
    cng[:, :, n] = 0.0
    for c19 in range(1, CAFE19 + 1):
        isc4 = int(sc19[c19])
        v["isc4"] = isc4
        x = (v["cost_ngtank_dge"][isc4, iyr] * v["pt_tanksize_cng"][VM, c19] + (itc[iyr, c19, 4] - itc[b, c19, 4])
             - v["cost_ice_cng"][c19] - icetech[c19, iyr])
        if iyr >= 2027 - 1989 and nox:
            x = x - (lonox[c19, iyr] - clonox[c19, 4])
        cng[VM, c19, n] = x * (ONE + fet[c19])
    v["icafe19"] = CAFE19 + 1

    first = v.i("first_bat_yr")
    batt, prod = v["cost_battkwh_trk"], v["global_batt_prod"]
    if iyr > first:
        tot = fsum(prod[:, :, n])
        pa, pb, ma, mb = v["cost_battpack_a"], v["cost_battpack_b"], v["cost_battmat_a"], v["cost_battmat_b"]
        if iyr == first + 1:
            pa[1:5] = (batt[1:5, iyr] - ma[1:5] * powf(tot, -mb[1:5])) / powf(tot, -pb[1:5])
        batt[1:5, iyr] = pa[1:5] * powf(tot, -pb[1:5]) + ma[1:5] * powf(tot, -mb[1:5])

    if yrs <= bsyr:
        return
    jp = v["mc_jpgdp"]
    fckw, h2t = v["cost_fckw"], v["cost_h2tank"]
    fckw[iyr] = min((v["cost_fcstack_a"] * powf(v["cumulative_fc_stacks"][iyr - 1], -v["cost_fcstack_b"])) / jp[31] * jp[1],
                    fckw[33] * powi(ONE - v["cost_fcstk_rd"], iyr - 33))
    h2t[iyr] = min((v["cost_h2tank_a"] * powf(v["cumulative_h2_tanks"][iyr - 1], -v["cost_h2tank_b"])) / jp[31] * jp[1],
                   h2t[33] * powi(ONE - v["cost_h2tank_rd"], iyr - 33))

    vmt, days, mpg, hrate = v["vmt_veh"], v["ann_uptime_days"], v["new_mpg_19"], v["hrate"]
    motor, ekw = v["cost_motorkw"][iyr], v["pt_emotorkw"]
    infra, obc = v["bev_infra_cost"], v["cost_obc"][iyr]
    daily = lambda c19: (fsum(vmt[VM, :, c19], axis=1) / f32(2)) / days  # noqa: E731

    bev = v["inc_cost_bev"]
    bev[:, :, n] = 0.0
    nom, opc = v["kwh_nominal"], v["bev_refuelopcost"]
    dod = v["trk_bev_dod"]
    for c19 in range(1, CAFE19 + 1):
        isc4 = int(sc19[c19])
        v["isc4"] = isc4
        ibatt = 4 if c19 <= 4 else 1 if c19 <= 6 else 2 if (c19 <= 8 or c19 == 12) else 3
        used = (fsum(vmt[VM, :, c19], axis=1) / f32(2)) / days / mpg[iyr - 1, 6, c19] / f32(3412) * (hrate[isc4, 6])
        need = (np.maximum(v["min_req_rng"], (fsum(vmt[VM, :, c19], axis=1) / f32(2)) / days)) / mpg[iyr - 1, 6, c19] / f32(3412) * (hrate[isc4, 6])
        nom[VM, c19, iyr] = np.minimum(v["max_kwh_cap"][c19, iyr], need / dod)
        usable = nom[VM, c19, iyr] * dod
        hours = np.maximum(ZERO, used - usable) / v["charging_speed"][c19]
        opc[VM, c19, iyr] = hours * v["refuel_timeval"] * days
        x = (ekw[c19, 6] * motor + batt[ibatt, iyr] * nom[VM, c19, iyr] + (itc[iyr, c19, 6] - itc[b, c19, 6])
             + infra[c19, iyr] + obc - ice[c19, iyr] - lonox[c19, iyr])
        bev[VM, c19, n] = x
        cr = _ira(v, 6, c19, n, x - infra[c19, iyr], yrs)
        if cr is not None:
            bev[VM, c19, n] = bev[VM, c19, n] - cr
        bev[VM, c19, n] = bev[VM, c19, n] + (bev[VM, c19, n] - infra[c19, iyr]) * fet[c19]

    hev = v["inc_cost_hev"]
    hev[:, :, n] = 0.0
    for c19 in range(1, CAFE19 + 1):
        x = (ekw[c19, 11] * motor + batt[5, iyr] * v["pt_battkwh_hev"][c19] + (itc[iyr, c19, 11] - itc[b, c19, 11])
             - v["cost_ice_hev"][c19, iyr] - lonox[c19, iyr])
        if n >= 2027 - 1989 and nox:
            x = x + clonox[c19, 11]
        hev[:, c19, n] = x

    h2 = v["inc_cost_h2ice"]
    h2[:, :, n] = 0.0
    cfh2 = v["cfh2q_kg"]
    usable_h2, kgt, maxt = v["usable_h2"], v["h2_kg_per_tank"], v["h2_max_tanks"]
    refuel = v["h2_refuelopcost"]
    rtime, rval = v["h2_refuel_time"], v["refuel_timeval"]

    def tanks(fuel, kind, kg_key, cnt_key, c19, isc4, minus):
        kg = (daily(c19) / mpg[iyr - 1, fuel, c19]) * cfh2 * (hrate[isc4, fuel] * f32(1e-6))
        kg = kg / usable_h2
        v[kg_key][VM, c19] = kg
        cnt = np.minimum(maxt[c19, kind], np.ceil(kg / kgt[c19, kind]).astype(f32))
        v[cnt_key][VM, c19] = cnt
        r = kg / (cnt * kgt[c19, kind])
        refuel[VM, c19, kind] = np.maximum(ZERO, (r - f32(minus)) * days * rtime * rval)
        return cnt

    for c19 in range(1, CAFE19 + 1):
        isc4 = int(sc19[c19])
        v["isc4"] = isc4
        cnt = tanks(12, 3, "pt_tankkg_h2ice", "pt_tankcnt_h2ice", c19, isc4, 1)
        x = h2t[iyr] * cnt * kgt[c19, 3] + (itc[iyr, c19, 12] - itc[b, c19, 12]) - v["cost_ice_h2ice"][c19, iyr]
        if n >= 2027 - 1989 and nox:
            x = x - lonox[c19, iyr] + clonox[c19, 12]
        h2[VM, c19, n] = x * (ONE + fet[c19])

    pd, pg = v["inc_cost_phevd"], v["inc_cost_phevg"]
    pd[:, :, n] = 0.0
    pg[:, :, n] = 0.0
    pbk = v["pt_battkwh_phev"]
    for c19 in range(1, CAFE19 + 1):
        evmt = daily(c19) * v["phevelecvmt"][c19]
        pbk[VM, c19] = v["battsize_a_phev"][c19] * powf(evmt, v["battsize_b_phev"][c19])
        pbk[VM, c19] = pbk[VM, c19] * mpg[b, 6, c19] / mpg[iyr, 6, c19]
        xd = (ekw[c19, 7] * motor + batt[2, iyr] * pbk[VM, c19] + (itc[iyr, c19, 7] - itc[b, c19, 7]) + obc
              - v["cost_ice_phev"][c19, 1, iyr])
        xg = (ekw[c19, 8] * motor + batt[2, iyr] * pbk[VM, c19] + (itc[iyr, c19, 8] - itc[b, c19, 8]) + obc
              - v["cost_ice_phev"][c19, 2, iyr])
        if n >= 2027 - 1989 and nox:
            xd = xd - (lonox[c19, iyr] - clonox[c19, 7])
            xg = xg - (lonox[c19, iyr] - clonox[c19, 8])
        pd[VM, c19, n], pg[VM, c19, n] = xd, xg
        cd = _ira(v, 7, c19, n, xd, yrs)
        cg = _ira(v, 8, c19, n, xg, yrs)
        if cd is not None:
            pd[VM, c19, n] = pd[VM, c19, n] - cd
            pg[VM, c19, n] = pg[VM, c19, n] - cg
        pd[VM, c19, n] = pd[VM, c19, n] * (ONE + fet[c19])
        pg[VM, c19, n] = pg[VM, c19, n] * (ONE + fet[c19])

    fc, fch = v["inc_cost_fcev"], v["inc_cost_fchev"]
    fc[:, :, n] = 0.0
    fch[:, :, n] = 0.0
    for c19 in range(1, CAFE19 + 1):
        isc4 = int(sc19[c19])
        v["isc4"] = isc4
        kg1 = (daily(c19) / mpg[iyr - 1, 9, c19]) * cfh2 * (hrate[isc4, 9] * f32(1e-6))
        kg2 = (daily(c19) / mpg[iyr - 1, 10, c19]) * cfh2 * (hrate[isc4, 10] * f32(1e-6))
        kg1, kg2 = kg1 / usable_h2, kg2 / usable_h2
        v["pt_tankkg_fcev"][VM, c19], v["pt_tankkg_fchev"][VM, c19] = kg1, kg2
        c1 = np.minimum(maxt[c19, 1], np.ceil(kg1 / kgt[c19, 1]).astype(f32))
        c2 = np.minimum(maxt[c19, 2], np.ceil(kg2 / kgt[c19, 2]).astype(f32))
        v["pt_tankcnt_fcev"][VM, c19], v["pt_tankcnt_fchev"][VM, c19] = c1, c2
        r1 = kg1 / (c1 * kgt[c19, 1])
        r2 = kg2 / (c2 * kgt[c19, 2])
        refuel[VM, c19, 1] = np.maximum(ZERO, (r1 - f32(1)) * days * rtime * rval)
        refuel[VM, c19, 2] = np.maximum(ZERO, (r2 - f32(2)) * days * rtime * rval)
        x1 = (fckw[iyr] * v["pt_fckw_fcev"][VM, c19] + motor * ekw[c19, 9] + h2t[iyr] * c1 * kgt[c19, 1]
              + batt[2, iyr] * v["pt_battkwh_fcev"][VM, c19] + (itc[iyr, c19, 9] - itc[b, c19, 9]) - ice[c19, iyr] - lonox[c19, iyr])
        x2 = (fckw[iyr] * v["pt_fckw_fchev"][VM, c19] + motor * ekw[c19, 10] + h2t[iyr] * c2 * kgt[c19, 2]
              + batt[2, iyr] * v["pt_battkwh_fchev"][VM, c19] + (itc[iyr, c19, 10] - itc[b, c19, 10]) - ice[c19, iyr] - lonox[c19, iyr])
        fc[VM, c19, n], fch[VM, c19, n] = x1, x2
        k1 = _ira(v, 9, c19, n, x1, yrs)
        k2 = _ira(v, 10, c19, n, x2, yrs)
        if k1 is not None:
            fc[VM, c19, n] = fc[VM, c19, n] - k1
            fch[VM, c19, n] = fch[VM, c19, n] - k2
        fc[VM, c19, n] = fc[VM, c19, n] * (ONE + fet[c19])
        fch[VM, c19, n] = fch[VM, c19, n] * (ONE + fet[c19])
    v["icafe19"] = CAFE19 + 1
