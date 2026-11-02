"""Automated vehicles in taxi and ride-hail fleets (tran.f): FLTHAV, HAVCALC, LIDARCOSTCALC.

LIDARCOSTCALC  lidar cost on a production learning curve by phase
HAVCALC        automation system cost by level (system, battery, lidar)
FLTHAV         fleets choose an automation level by a logit on the lifetime net
               revenue of a taxi (fares, salary, maintenance, fuel with a price
               trend, insurance), damped for new technology; taxi sales and new
               fleet stock by automation level

EIA quirks kept: the fuel price average adds four years and divides by three; a
level not yet available exits the level loop, leaving later levels' utilities
from an earlier call (a saved local, kept in s["_flthav_taxi_util"]), which can
reach the all-utilities-negative check.
"""

import math

import numpy as np

from nems_open.transportation.common import MAXAGE, MAXHAV, MAXLDV, MAXVTYP, MNUMCR, f32, fsum
from nems_open.transportation.misc_modes import powi

MAXCLASS = 8
MAXGROUP = 11
CARGRP = 5
LTKGRP = 6
MAXLIDAR = 2
MAXPRODPHASE = 4
IAVG = 3
ONE = f32(1.0)


def lidarcostcalc(s: dict) -> None:
    yrs = int(s["yrs"])
    sales, cum, rnd = s["lidarsales"], s["cumul_lidar_prod"], s["lidar_rnd_prod"]
    first, lmap = s["first_lidar_year"], s["hav_lidar_map"]
    thr, ca, cb = s["lidar_prod_thrsh"], s["lidar_coef_a"], s["lidar_coef_b"]
    temp = s.setdefault("_lidar_cost_temp", {})
    taxi = s["taxi_sales"]
    sales[:, yrs - 1] = 0.0
    for il in range(1, MAXLIDAR + 1):
        fy = int(first[il])
        if yrs < fy:
            continue
        for ihav in range(2, MAXHAV + 1):
            if int(lmap[ihav - 1]) == il:
                sales[il, yrs - 1] = sales[il, yrs - 1] + fsum(taxi[:, :, :, :, yrs - 1, ihav])
        s["ihav"] = MAXHAV + 1
        fr = int(s["first_read_year"])
        if yrs == fy:
            cum[il, fr] = 0
            for ic in range(fr + 1, fy):
                cum[il, ic] = cum[il, ic - 1] + rnd[il, ic]
        elif yrs > fy:
            add = rnd[il, yrs - 1] if sales[il, yrs - 1] <= rnd[il, yrs - 1] else sales[il, yrs - 1]
            cum[il, yrs - 1] = cum[il, yrs - 2] + add
        c = cum[il, yrs - 1]
        if c > thr[MAXPRODPHASE, il]:
            temp[il, yrs] = ca[MAXPRODPHASE, il] * c ** (-cb[MAXPRODPHASE, il])
            s["lidar_phase"][il, yrs] = MAXPRODPHASE
        else:
            for iphase in range(1, MAXPRODPHASE):
                s["iphase"] = iphase
                if c <= thr[iphase + 1, il]:
                    temp[il, yrs] = ca[iphase, il] * c ** (-cb[iphase, il])
                    s["lidar_phase"][il, yrs] = iphase
                    break
            else:
                s["iphase"] = MAXPRODPHASE
    for ihav in range(2, MAXHAV + 1):
        for il in range(1, MAXLIDAR + 1):
            if int(lmap[ihav - 1]) == il:
                s["lidar_cost"][ihav, yrs] = temp.get((il, yrs), f32(0.0))
    s["ihav"] = MAXHAV + 1


def havcalc(s: dict) -> None:
    yrs = int(s["yrs"])
    lidarcostcalc(s)
    tmap, frst = s["hav_techmap"], s["frstyear"]
    for ihav in range(2, MAXHAV + 1):
        t = int(tmap[ihav - 1])
        if yrs >= frst[t, :].min():
            s["hav_sys_cost"][ihav, yrs] = (s["hav_sys_lrn"][ihav - 1, yrs] * s["del_costabs"][t, 1]
                                            + s["li_ion_cost"][16, yrs] * s["hav_battery_kwh"][ihav - 1]
                                            + s["lidar_cost"][ihav, yrs])
    s["ihav"] = MAXHAV + 1


def flthav(s: dict) -> None:
    n, yrs = int(s["n"]), int(s["yrs"])
    if yrs < s["first_lidar_year"].a.min():
        return  # TRAN calls FLTHAV only once lidar is available
    shares = s["flt_hav_shares"]
    shares[:, :, :, :, yrs, :] = 0.0
    shares[:, :, :, :, yrs, 1] = 1.0

    flag = s["classflag"]
    hav_ok = np.zeros((MAXVTYP + 1, MAXCLASS + 1, MAXLDV + 1), dtype=bool)
    for ildv in range(1, MAXLDV + 1):
        for icl in range(1, MAXCLASS + 1):
            if ildv in (1, 15, 16):
                hav_ok[1, icl, ildv] = bool(np.any(flag[1:CARGRP, icl, ildv]))
                hav_ok[2, icl, ildv] = bool(np.any(flag[LTKGRP:MAXGROUP, icl, ildv]))

    tmap = [int(t) for t in s["hav_techmap"].a]
    applic, frst = s["tech_applic"], s["frstyear"]
    hav_first = [None] + [frst[t, :].min() for t in tmap]  # first year of automation level ihav+1
    taxi, ftech, fstock = s["taxi_sales"], s["fltechsal"], s["flt_stock"]
    util = s.setdefault("_flthav_taxi_util", np.zeros((MNUMCR - 1, MAXHAV + 1), dtype=f32))
    fprice = s["fprice"]
    p = {k: s[k] for k in ("taxi_maint_cost", "taxi_data_fee", "taxi_insur", "taxi_shifts", "taxi_mi_ann",
                           "taxi_maint_mi", "taxi_idle_gph", "taxi_idle_hrs", "taxi_live_frac", "taxi_rev_permi",
                           "taxi_mi_life", "hav_newtech_lim", "hav_oper_limit")}
    salary, disc, rev_coef = s["taxi_salary"], s["taxi_disc_r"], s["taxi_rev_coef"]

    for ivtyp in range(1, MAXVTYP + 1):
        s["ivtyp"] = ivtyp
        for icl in range(1, MAXCLASS + 1):
            s["icl"] = icl
            for ildv in range(1, MAXLDV + 1):
                s["ildv"] = ildv
                if not hav_ok[ivtyp, icl, ildv] or not any(applic[t, ivtyp, ildv] for t in tmap):
                    taxi[MNUMCR, ivtyp, icl, ildv, yrs, 1] = ftech[MNUMCR, ivtyp, 4, icl, ildv, 1]
                    continue
                havcalc(s)
                price = {h: s["ldvpri"][ivtyp, ildv, icl, yrs] + s["hav_sys_cost"][h, yrs] for h in range(1, MAXHAV + 1)}
                mpg = {h: s["ldvmpg"][ivtyp, ildv, icl, yrs] * s["hav_mpgdeg"][h, yrs] for h in range(1, MAXHAV + 1)}
                first_new = f32(min(hav_first[1:])) + f32(s["hav_newtech_lag"])
                f_wb = ONE
                if yrs > first_new:
                    f_wb = np.exp(-((f32(yrs) - first_new) / s["taxi_newtech_pd"]) ** s["taxi_newtech_r"])

                for iregn in range(1, MNUMCR - 1):
                    s["iregn"] = iregn
                    sum_exp = f32(0.0)
                    for ihav in range(1, MAXHAV + 1):
                        s["ihav"] = ihav
                        if ihav > 1 and yrs < hav_first[ihav - 1]:
                            util[iregn, ihav] = f32(-1000000.0)
                            break
                        avg1 = avg2 = f32(0.0)
                        for iyr in range(yrs - IAVG - 1, yrs):
                            avg1 = avg1 + fprice[ildv, iregn, iyr] / f32(100)
                            avg2 = avg2 + fprice[ildv, iregn, iyr - 1] / f32(100)
                        s["iyr"] = yrs
                        avg1, avg2 = avg1 / f32(IAVG), avg2 / f32(IAVG)
                        dfp = max(f32(0.0), avg1 - avg2) / f32(12.0)
                        ann = p["taxi_mi_ann"][iregn, ihav]
                        cost = (p["taxi_maint_cost"][ihav] + p["taxi_data_fee"][ihav] + p["taxi_insur"][ihav]
                                + p["taxi_shifts"][iregn, ihav] * salary / f32(12.0) + (ann / f32(12.0)) * p["taxi_maint_mi"][iregn, ihav])
                        fuel = (ann / f32(12.0)) / mpg[ihav] + p["taxi_idle_gph"][ihav] * p["taxi_idle_hrs"][iregn, ihav]
                        rev = p["taxi_live_frac"][iregn, ihav] * (ann / f32(12.0)) * p["taxi_rev_permi"][iregn, ihav]
                        life = math.ceil(f32(12.0) * p["taxi_mi_life"][ihav] / ann)
                        npv = -price[ihav]
                        base = ONE + disc / f32(12.0)
                        for ipv in range(1, life + 1):
                            proj = avg1 + f32(ipv) * dfp
                            npv = npv + (powi(base, -ipv)) * (rev - cost - proj * fuel)
                        util[iregn, ihav] = (f_wb * p["hav_newtech_lim"][ihav] + p["hav_oper_limit"][iregn, ihav]
                                             + rev_coef * npv / f32(1000.0))
                        sum_exp = sum_exp + np.exp(util[iregn, ihav])
                    else:
                        s["ihav"] = MAXHAV + 1

                    logit = True
                    if util[iregn, 1] <= 0.0:
                        pass  # bTaxiUtilErr only limits diagnostic writes
                        if util[iregn, 1:].max() <= 0.0:
                            logit = False
                    if logit:
                        for ihav in range(1, MAXHAV + 1):
                            shares[iregn, ivtyp, icl, ildv, yrs, ihav] = np.exp(util[iregn, ihav]) / sum_exp
                            if ihav > 1 and yrs < hav_first[ihav - 1]:
                                shares[iregn, ivtyp, icl, ildv, yrs, ihav] = 0.0
                        shares[iregn, ivtyp, icl, ildv, yrs, 1] = ONE - fsum(shares[iregn, ivtyp, icl, ildv, yrs, 2:MAXHAV])
                    taxi[iregn, ivtyp, icl, ildv, yrs, :] = shares[iregn, ivtyp, icl, ildv, yrs, :] * ftech[iregn, ivtyp, 4, icl, ildv, 1]
                    for ihav in range(1, MAXHAV + 1):
                        ftech[iregn, ivtyp, 4, icl, ildv, ihav] = taxi[iregn, ivtyp, icl, ildv, yrs, ihav]
                        fstock[iregn, ivtyp, 4, ildv, 1, ihav, n] = fsum(ftech[iregn, ivtyp, 4, 1:MAXCLASS, ildv, ihav])
                    s["ihav"] = MAXHAV + 1
                s["iregn"] = MNUMCR - 1
                for ihav in range(1, MAXHAV + 1):
                    taxi[MNUMCR, ivtyp, icl, ildv, yrs, ihav] = fsum(taxi[1:MNUMCR - 2, ivtyp, icl, ildv, yrs, ihav])
                    ftech[MNUMCR, ivtyp, 4, icl, ildv, ihav] = fsum(ftech[1:MNUMCR - 2, ivtyp, 4, icl, ildv, ihav])
                    fstock[MNUMCR, ivtyp, 4, ildv, 1, ihav, n] = fsum(ftech[MNUMCR, ivtyp, 4, 1:MAXCLASS, ildv, ihav])
                    s["fltechstk"][MNUMCR, ivtyp, 4, ildv, ihav] = fsum(fstock[MNUMCR, ivtyp, 4, ildv, 1:MAXAGE, ihav, n])
                s["ihav"] = MAXHAV + 1
            s["ildv"] = MAXLDV + 1
        s["icl"] = MAXCLASS + 1
    s["ivtyp"] = MAXVTYP + 1
