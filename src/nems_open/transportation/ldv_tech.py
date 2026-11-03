"""Electric-drive vehicle attributes and battery costs (tran.f).

HEVCALC, PHEVCALC, EVCALC, FCCALC  battery size, electric system cost, weight,
        horsepower, range and fuel economy of hybrids, plug-ins, battery EVs and
        fuel cell vehicles, from the gasoline vehicle in the same group and class
AFVADJ  sets up an alternative-fuel vehicle in its introduction year
FEMRANGE  driving range from tank size and fuel economy
LIONCOSTCALC  lithium-ion pack cost on a learning curve in cumulative production

Like the Fortran, these read the class, fuel and vehicle type from the module
variables ICL, ILDV and IVTYP (s["icl"], s["ildv"], s["ivtyp"]).
"""

import numpy as np

from nems_open.transportation.common import f32, fsum, logf, MAXLDV, MNUMCR, powf

BASE, PREV, CURRENT = 0, 1, 2
GAS = 1
MAXCLASS = 8
MAXGROUP = 11
CARGRP = 5
LTKGRP = 6
NIMH_LB_PER_KWH = f32(53.42)
NIMH_KWH_PER_LB = f32(0.0004989)
MPG_KWH = None  # CFMGQ(n)*1e6/42/3412 is computed in place, in EIA's order


def _carry_intro(s, igp, icl, ildv):
    """In the introduction year of a vehicle with no EPA price, copy current attributes back."""
    if int(s["grpflag"][ildv, icl, igp]) == int(s["curcalyr"]) and s["fempri"][igp, icl, int(s["epalyr"]), ildv] == 0.0:
        for k in ("weight", "fe", "hp", "tanksize", "price"):
            s[k][igp, icl, BASE:PREV, ildv] = s[k][igp, icl, CURRENT, ildv]


def _kwh_to_mpg(s):
    n = int(s["n"])
    return s["cfmgq"][n] * f32(1000000.0) / f32(42.0) * (f32(1.0) / f32(3412.0))


def hevcalc(s: dict, dsyrs: int, igp: int) -> None:
    icl, ildv, ivtyp = int(s["icl"]), int(s["ildv"]), int(s["ivtyp"])
    w, fe, hp, tank, price = s["weight"], s["fe"], s["hp"], s["tanksize"], s["price"]
    bps, bpw, esc = s["batpacksize"], s["batpackwgt"], s["elecsysinccost"]
    epalyr = int(s["epalyr"])
    lii = w[igp, icl, CURRENT, GAS] * s["lionkwh_perlb"][icl, igp, ildv] * (s["phev_dod"][epalyr] / s["phev_dod"][dsyrs])
    nmh = w[igp, icl, CURRENT, GAS] * NIMH_KWH_PER_LB
    li_cost, nimh_cost = s["li_ion_cost"][ildv, dsyrs], s["nimh_cost"][dsyrs]
    nonbatt = s["elecnonbattcst"][icl, dsyrs, ivtyp, ildv]
    if lii * li_cost < nmh * nimh_cost:
        bps[dsyrs, icl, igp, ildv] = lii
        esc[icl, igp, CURRENT, ildv] = lii * li_cost + nonbatt
        bpw[dsyrs, icl, igp, ildv] = s["lion_lb_perkwh"][ildv] * lii
    else:
        bps[dsyrs, icl, igp, ildv] = nmh
        esc[icl, igp, CURRENT, ildv] = nmh * nimh_cost + nonbatt
        bpw[dsyrs, icl, igp, ildv] = NIMH_LB_PER_KWH * nmh
    if esc[icl, igp, PREV, ildv] == 0.0:
        esc[icl, igp, PREV, ildv] = esc[icl, igp, CURRENT, ildv]
    price[igp, icl, CURRENT, ildv] = price[igp, icl, CURRENT, ildv] + esc[icl, igp, CURRENT, ildv]
    if w[igp, icl, PREV, ildv] == 0.0:
        w[igp, icl, CURRENT, ildv] = w[igp, icl, CURRENT, GAS] + bpw[dsyrs, icl, igp, ildv]
    if w[igp, icl, PREV, ildv] == 0.0:
        hp[igp, icl, CURRENT, ildv] = hp[igp, icl, CURRENT, GAS] * (w[igp, icl, CURRENT, ildv] / w[igp, icl, CURRENT, GAS])
    yrs, epa = int(s["curcalyr"]), int(s["epalyr"])
    if fe[igp, icl, PREV, ildv] == 0.0 or (int(s["grpflag"][ildv, icl, igp]) == yrs and s["fempri"][igp, icl, epa, ildv] == 0.0):
        if igp <= CARGRP:
            fe[igp, icl, CURRENT, ildv] = fe[igp, icl, CURRENT, GAS] * f32(1.646)
        if igp >= LTKGRP:
            fe[igp, icl, CURRENT, ildv] = fe[igp, icl, CURRENT, GAS] * f32(1.45)
        if yrs > epa:
            fe[igp, icl, CURRENT, ildv] = fe[igp, icl, CURRENT, ildv] * s["calratio_fe"][igp, icl, ildv]
    if tank[igp, icl, PREV, ildv] == 0.0:
        tank[igp, icl, CURRENT, ildv] = tank[igp, icl, CURRENT, GAS] * f32(0.90)
        if yrs > epa:
            tank[igp, icl, CURRENT, ildv] = tank[igp, icl, CURRENT, ildv] * s["calratio_tsz"][igp, icl, ildv]
    _carry_intro(s, igp, icl, ildv)


def phevcalc(s: dict, dsyrs: int, igp: int) -> None:
    icl, ildv, ivtyp = int(s["icl"]), int(s["ildv"]), int(s["ivtyp"])
    n, yrs, epa = int(s["n"]), int(s["yrs"]), int(s["epalyr"])
    w, fe, hp, tank, price = s["weight"], s["fe"], s["hp"], s["tanksize"], s["price"]
    bps, esc, dod = s["batpacksize"], s["elecsysinccost"], s["phev_dod"]
    if bps[dsyrs - 1, icl, igp, ildv] > 0.0:
        bps[dsyrs, icl, igp, ildv] = bps[dsyrs - 1, icl, igp, ildv] * (dod[dsyrs - 1] / dod[dsyrs])
    else:
        bps[dsyrs, icl, igp, ildv] = w[igp, icl, CURRENT, GAS] * s["lionkwh_perlb"][icl, igp, ildv] * (dod[epa] / dod[dsyrs])
    b = bps[dsyrs, icl, igp, ildv]
    if b <= 0.0 or b != b:
        raise ValueError(f"TDM PHEVCALC: battery size {b}, group {igp} class {icl} ldv {ildv}")
    esc[icl, igp, CURRENT, ildv] = (b * s["li_ion_cost"][ildv, dsyrs]) + s["elecnonbattcst"][icl, dsyrs, ivtyp, ildv]
    if esc[icl, igp, PREV, ildv] == 0.0:
        esc[icl, igp, PREV, ildv] = esc[icl, igp, CURRENT, ildv]
    price[igp, icl, CURRENT, ildv] = price[igp, icl, CURRENT, ildv] + esc[icl, igp, CURRENT, ildv]
    if w[igp, icl, PREV, ildv] != 0.0:
        w[igp, icl, CURRENT, ildv] = w[igp, icl, PREV, ildv]
    else:
        w[igp, icl, CURRENT, ildv] = w[igp, icl, CURRENT, ildv] + (b * s["lion_lb_perkwh"][ildv])
    if hp[igp, icl, PREV, ildv] == 0.0 and w[igp, icl, CURRENT, GAS] != 0.0:
        hp[igp, icl, CURRENT, ildv] = hp[igp, icl, CURRENT, GAS] * (w[igp, icl, CURRENT, ildv] / w[igp, icl, CURRENT, GAS])
    rng = s["ev_range"]
    if bps[dsyrs - 1, icl, igp, ildv] > 0.0:
        rng[igp, icl, ildv, dsyrs] = rng[igp, icl, ildv, dsyrs - 1]
    else:
        rng[igp, icl, ildv, dsyrs] = s["ev_range_m"][ildv] * (b) + s["ev_range_b"][ildv]
    r = rng[igp, icl, ildv, dsyrs]
    if r <= 0.0 or r != r:
        raise ValueError(f"TDM PHEVCALC: EV range {r}")
    fe[igp, icl, CURRENT, ildv] = (r / (b * dod[dsyrs])) * _kwh_to_mpg(s) * s["evmpg_adj"][igp, icl, ildv]
    mpg_d, mpg_s = s["phevmpg_d"], s["phevmpg_s"]
    mpg_d[igp, icl, yrs, ildv] = fe[igp, icl, CURRENT, ildv]
    gas_fe = fe[igp, icl, CURRENT, GAS]
    if ildv == 5:
        mpg_s[igp, icl, yrs, ildv] = gas_fe * s["csratio"][icl, igp, 1] if gas_fe > 0.0 else (fe[igp, icl, CURRENT, ildv] / f32(2.464))
    elif ildv == 6:
        mpg_s[igp, icl, yrs, ildv] = gas_fe * s["csratio"][icl, igp, 2] if gas_fe > 0.0 else (fe[igp, icl, CURRENT, ildv] / f32(1.7))
    if int(s["curcalyr"]) > epa:
        mpg_s[igp, icl, yrs, ildv] = mpg_s[igp, icl, yrs, ildv] * s["calratio_fe"][igp, icl, ildv]
        mpg_d[igp, icl, yrs, ildv] = mpg_d[igp, icl, yrs, ildv] * s["calratio_fe"][igp, icl, ildv]
    evmt = s["phev_evmt"][igp, icl, dsyrs, ildv]
    fe[igp, icl, CURRENT, ildv] = f32(1.0) / (evmt / mpg_d[igp, icl, yrs, ildv] + (f32(1.0) - evmt) / mpg_s[igp, icl, yrs, ildv])
    v = fe[igp, icl, CURRENT, ildv]
    if v <= 0.0 or v != v:
        raise ValueError(f"TDM PHEVCALC: FE {v}")
    if tank[igp, icl, PREV, ildv] == 0.0:
        if ildv == 5:
            tank[igp, icl, CURRENT, ildv] = tank[igp, icl, CURRENT, GAS] * f32(0.90)
        if ildv == 6:
            tank[igp, icl, CURRENT, ildv] = tank[igp, icl, CURRENT, GAS] * f32(0.85)
        if int(s["curcalyr"]) > epa:
            tank[igp, icl, CURRENT, ildv] = tank[igp, icl, CURRENT, ildv] * s["calratio_tsz"][igp, icl, ildv]
    _carry_intro(s, igp, icl, ildv)


def evcalc(s: dict, dsyrs: int, igp: int) -> None:
    icl, ildv, ivtyp = int(s["icl"]), int(s["ildv"]), int(s["ivtyp"])
    epa = int(s["epalyr"])
    w, fe, hp, price = s["weight"], s["fe"], s["hp"], s["price"]
    bps, bpw, esc, dod = s["batpacksize"], s["batpackwgt"], s["elecsysinccost"], s["ev_dod"]
    if bps[dsyrs - 1, icl, igp, ildv] > 0.0:
        bps[dsyrs, icl, igp, ildv] = bps[dsyrs - 1, icl, igp, ildv]
    else:
        bps[dsyrs, icl, igp, ildv] = w[igp, icl, CURRENT, GAS] * s["lionkwh_perlb"][icl, igp, ildv]
    b = bps[dsyrs, icl, igp, ildv]
    if b <= 0.0 or b != b:
        raise ValueError(f"TDM EVCALC: battery size {b}")
    esc[icl, igp, CURRENT, ildv] = b * s["li_ion_cost"][ildv, dsyrs] + + s["elecnonbattcst"][icl, dsyrs, ivtyp, ildv]
    if esc[icl, igp, PREV, ildv] == 0.0:
        esc[icl, igp, PREV, ildv] = esc[icl, igp, CURRENT, ildv]
    price[igp, icl, CURRENT, ildv] = price[igp, icl, CURRENT, ildv] + esc[icl, igp, CURRENT, ildv]
    bpw[dsyrs, icl, igp, ildv] = b * s["lion_lb_perkwh"][ildv]
    if w[igp, icl, PREV, ildv] == 0.0:
        w[igp, icl, CURRENT, ildv] = w[igp, icl, CURRENT, GAS] - f32(500.0) + bpw[dsyrs, icl, igp, ildv]
    if hp[igp, icl, PREV, ildv] == 0.0 and w[igp, icl, CURRENT, GAS] != 0.0:
        hp[igp, icl, CURRENT, ildv] = hp[igp, icl, CURRENT, GAS] * (w[igp, icl, CURRENT, ildv] / w[igp, icl, CURRENT, GAS])
    rng = s["ev_range"]
    if bps[dsyrs - 1, icl, igp, ildv] > 0.0:
        rng[igp, icl, ildv, dsyrs] = rng[igp, icl, ildv, dsyrs - 1] * (dod[dsyrs] / dod[dsyrs - 1])
    else:
        rng[igp, icl, ildv, dsyrs] = (s["ev_range_m"][ildv] * b + s["ev_range_b"][ildv]) * (dod[dsyrs] / dod[epa])
    r = rng[igp, icl, ildv, dsyrs]
    if r <= 0.0 or r != r:
        raise ValueError(f"TDM EVCALC: EV range {r}")
    n = int(s["n"])
    fe[igp, icl, CURRENT, ildv] = ((r / (b * dod[dsyrs]) * s["cfmgq"][n] * f32(1000000.0) / f32(42.0) * (f32(1.0) / f32(3412.0)))
                                   * s["evmpg_adj"][igp, icl, ildv])
    if int(s["curcalyr"]) > epa:
        fe[igp, icl, CURRENT, ildv] = fe[igp, icl, CURRENT, ildv] * s["calratio_fe"][igp, icl, ildv]
    v = fe[igp, icl, CURRENT, ildv]
    if v <= 0.0 or v != v:
        raise ValueError(f"TDM EVCALC: FE {v}")
    _carry_intro(s, igp, icl, ildv)


TANKCOST = {13: f32(0.0), 14: f32(3500.0)}
GALPERMILE = {13: f32(0.00625), 14: f32(0.00570)}


def fccalc(s: dict, dsyrs: int, igp: int) -> None:
    icl, ildv = int(s["icl"]), int(s["ildv"])
    w, fe, price = s["weight"], s["fe"], s["price"]
    bps, esc, cell = s["batpacksize"], s["elecsysinccost"], s["fuelcell"]
    cell[icl, igp, CURRENT, ildv] = w[igp, icl, CURRENT, GAS] * f32(0.028) * s["fuelcell_d_kw"][dsyrs, ildv]
    if w[igp, icl, CURRENT, GAS] > 0.0:
        bps[dsyrs, icl, igp, ildv] = w[igp, icl, CURRENT, GAS] * s["lionkwh_perlb"][icl, igp, ildv]
    esc[icl, igp, CURRENT, ildv] = (cell[icl, igp, CURRENT, ildv] + bps[dsyrs, icl, igp, ildv] * s["li_ion_cost"][ildv, dsyrs]
                                    + TANKCOST[ildv])
    price[igp, icl, CURRENT, ildv] = price[igp, icl, CURRENT, ildv] + esc[icl, igp, CURRENT, ildv]
    if fe[igp, icl, PREV, ildv] == 0.0:
        fe[igp, icl, CURRENT, ildv] = f32(1.0) / (GALPERMILE[ildv] * (w[igp, icl, CURRENT, GAS] / f32(1000.0)))
    if int(s["curcalyr"]) > int(s["epalyr"]):
        fe[igp, icl, CURRENT, ildv] = fe[igp, icl, CURRENT, ildv] * s["calratio_fe"][igp, icl, ildv]


def femrange(s: dict) -> None:
    n, yrs = int(s["n"]), int(s["yrs"])
    rng, tank, fe, deg = s["range"], s["tanksize"], s["fe"], s["degfacgrp"]
    G, C, L = slice(1, MAXGROUP), slice(1, MAXCLASS), slice(1, MAXLDV)
    rng[G, C, CURRENT, L] = tank[G, C, CURRENT, L] * fe[G, C, CURRENT, L] * deg[G, C, L, n]
    for k in (5, 6):
        rng[G, C, CURRENT, k] = (tank[G, C, CURRENT, k] * s["phevmpg_s"][G, C, yrs, k] * deg[G, C, k, n]
                                 + s["ev_range"][G, C, k, yrs])
    for k in (4, 7, 15):
        rng[G, C, CURRENT, k] = s["ev_range"][G, C, k, yrs]
    rng[G, C, CURRENT, L] = np.where(s["classflag"][G, C, L] != 0, rng[G, C, CURRENT, L], f32(0.0))


def afvadj(s: dict, zyr: int, igp: int) -> None:
    icl, ildv = int(s["icl"]), int(s["ildv"])
    ivtyp = int(s["grpmap"][igp])
    s["ivtyp"] = ivtyp
    xyr, flag = 2022, s["classflag"][igp, icl, ildv] != 0
    intro = int(s["grpflag"][ildv, icl, igp]) == zyr
    numtech = int(s["numtech"])
    w, fe, hp, tank, price, pen = s["weight"], s["fe"], s["hp"], s["tanksize"], s["price"], s["mkt_pen"]
    adj_wt, adj_fe, adj_hp, adj_pr = s["afvadjwt"], s["afvadjfe"], s["afvadjhp"], s["afvadjpr"]
    if zyr > xyr and flag and intro:
        w[igp, icl, BASE, ildv] = w[igp, icl, CURRENT, GAS] * adj_wt[ildv, ivtyp]
        fe[igp, icl, BASE, ildv] = fe[igp, icl, CURRENT, GAS] * adj_fe[ildv, ivtyp]
        hp[igp, icl, BASE, ildv] = hp[igp, icl, CURRENT, GAS] * adj_hp[ildv, ivtyp]
        tank[igp, icl, BASE, ildv] = tank[igp, icl, CURRENT, GAS]
        price[igp, icl, BASE, ildv] = price[igp, icl, CURRENT, GAS] + adj_pr[ildv, ivtyp]
        pen[igp, icl, 1:numtech, BASE, ildv] = pen[igp, icl, 1:numtech, BASE, GAS]
    if flag and zyr > xyr and intro:
        price[igp, icl, CURRENT, ildv] = price[igp, icl, CURRENT, GAS] + adj_pr[ildv, ivtyp]
        fe[igp, icl, CURRENT, ildv] = fe[igp, icl, CURRENT, GAS] * adj_fe[ildv, ivtyp]
        w[igp, icl, CURRENT, ildv] = w[igp, icl, CURRENT, GAS] * adj_wt[ildv, ivtyp]
        hp[igp, icl, CURRENT, ildv] = hp[igp, icl, CURRENT, GAS] * adj_hp[ildv, ivtyp]
        tank[igp, icl, CURRENT, ildv] = tank[igp, icl, CURRENT, GAS]
        if (4 <= ildv <= 8) or ildv >= 13:
            if ildv in (4, 7, 15):
                evcalc(s, zyr, igp)
            if ildv in (5, 6):
                phevcalc(s, zyr, igp)
            if ildv in (8, 16):
                hevcalc(s, zyr, igp)
            if 13 <= ildv <= 14:
                fccalc(s, zyr, igp)
        pen[igp, icl, 1:numtech, CURRENT, ildv] = pen[igp, icl, 1:numtech, CURRENT, GAS]
        s["mkt_max"][icl, igp, 1:numtech, ildv] = s["mkt_max"][icl, igp, 1:numtech, GAS]


def lioncostcalc(s: dict) -> None:
    n, yrs = int(s["n"]), int(s["yrs"])
    first = int(s["first_bat_yr"])
    sales, bps, prod = s["ldv_sales"], s["batpacksize"], s["global_batt_prod"]

    def gwh(ic):
        tot = f32(0.0)
        for ildv in range(1, MAXLDV + 1):
            for igp in range(1, MAXGROUP + 1):
                for icl in range(1, MAXCLASS + 1):
                    p = bps[ic + 1989 - 1, icl, igp, ildv]
                    if p == 0.0:
                        continue
                    if (4 <= ildv <= 7) or ildv >= 15:
                        tot = tot + sales[igp, icl, ildv, MNUMCR, ic - 1] * p
        return tot

    if n <= first:
        prod[1:2, 1, :] = 0.0
        for ic in range(6, n + 1):
            # The Fortran loops group, class, fuel here; the sum is per element so order only
            # matters within one year's total, which runs group-class-fuel.
            tot = f32(0.0)
            for igp in range(1, MAXGROUP + 1):
                for icl in range(1, MAXCLASS + 1):
                    for ildv in range(1, MAXLDV + 1):
                        p = bps[ic + 1989 - 1, icl, igp, ildv]
                        if p == 0.0:
                            continue
                        if (4 <= ildv <= 7) or ildv >= 15:
                            tot = tot + sales[igp, icl, ildv, MNUMCR, ic - 1] * p
            prod[1, 1, ic] = prod[1, 1, ic - 1] + tot
        s.update(igp=MAXGROUP + 1, icl=MAXCLASS + 1, ildv=MAXLDV + 1)
    else:
        prod[1, 1, n] = prod[1, 1, n - 1] + gwh(n)
        s.update(ildv=MAXLDV + 1, igp=MAXGROUP + 1, icl=MAXCLASS + 1)

    if n >= first:
        cost, pa, pb, ma, mb = s["li_ion_cost"], s["pack_a"], s["pack_b"], s["mat_a"], s["mat_b"]
        mark = s["mat_markup"][n]
        tot_prev, tot_now = fsum(prod[:, :, n - 1]), fsum(prod[:, :, n])
        e0 = -(-logf(f32(1.0)) / logf(f32(2.0)))
        e1 = -(-logf(f32(1.0) - f32(0.165)) / logf(f32(2.0)))
        for ildv in range(1, MAXLDV + 1):
            if (4 <= ildv <= 8) or ildv >= 13:
                if n == first:
                    pa[ildv] = (cost[ildv, yrs] - ma[ildv] * mark * powf(tot_prev, e0)) / powf(tot_prev, e1)
                elif n == first + 1:
                    cost[ildv, yrs] = pa[ildv] * powf(tot_now, e1) + ma[ildv] * mark * powf(tot_now, e0)
                else:
                    if n == first + 2:
                        pa[ildv] = (cost[ildv, yrs - 1] - ma[ildv] * mark * powf(tot_prev, -mb[ildv])) / powf(tot_prev, -pb[ildv])
                    cost[ildv, yrs] = pa[ildv] * powf(tot_now, -pb[ildv]) + ma[ildv] * mark * powf(tot_now, -mb[ildv])
        s["ildv"] = MAXLDV + 1
