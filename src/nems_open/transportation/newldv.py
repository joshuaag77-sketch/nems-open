"""NEWLDV (tran.f): new car and light truck sales by census division.

Through the last stock history year (2024), sales and the car/truck split come
from the registration stock. After it, sales follow licensed drivers and the
car/truck split is a regional partial-adjustment logit on income, gasoline price,
horsepower, weight and fuel economy.
"""

from nems_open.transportation.common import MAXHAV, MAXLDV, MAXOWNER, MAXVTYP, MNUMCR, STOCKYR, f32, fsum

import numpy as np

R9 = slice(1, MNUMCR - 2)  # census divisions 1-9


def gas_price_00(s, y):
    """PMGTR00_D_C_regn(1:9, y): gasoline in 2000 cents per gallon. A saved local in
    the Fortran; last year's value is what last year's call computed."""
    return s["pmgtr"][R9, y] * s["cfmgq"][y] / f32(42.0) * s["mc_jpgdp"][11] * f32(100.0)


def newldv(s: dict) -> None:
    n, yrs = int(s["n"]), int(s["curcalyr"])
    pm = s["pmgtr"]
    p00 = gas_price_00(s, n)
    for iregn in range(1, MNUMCR - 1):
        v = pm[iregn, n]
        if v <= 0.0 or v != v:
            raise ValueError(f"TDM: PMGTR busted, {yrs} region {iregn}")
    s["iregn"] = MNUMCR - 1  # DO-loop variable after the loop

    veh = s["mc_vehicles"]
    tempcls12a = (veh[1, n] + veh[2, n]) * s["ltsplit"][n]

    ctsplit, newldvs, ld = s["cartrksplit"], s["newldvs"], s["licdriver"]
    stock = s["ldv_stock"]
    if yrs <= STOCKYR:
        # New vehicles are the age-1, non-automated slice of the stock.
        new = stock[R9, 1:MAXVTYP, 1:MAXOWNER, 1:MAXLDV, 1, 1, n]          # (9, 2, 5, 16)
        by_type = fsum(fsum(new, axis=3), axis=2)                          # (9, 2)
        newldvs[1:MAXVTYP, R9, n] = by_type.T
        newldvs[1:MAXVTYP, MNUMCR, n] = fsum(by_type, axis=0)
        ctsplit[R9, 1:MAXVTYP, n] = by_type / fsum(by_type, axis=1)[:, None]
        # EIA quirk: the car numerator sums all automation levels, the denominator only level 1.
        ctsplit[MNUMCR, 1, n] = (fsum(stock[MNUMCR, 1, 1:MAXOWNER, 1:MAXLDV, 1, 1:MAXHAV, n])
                                 / fsum(stock[MNUMCR, 1:MAXVTYP, 1:MAXOWNER, 1:MAXLDV, 1, 1, n]))
        ctsplit[MNUMCR, 2, n] = f32(1.0) - ctsplit[MNUMCR, 1, n]
        drivers = fsum(fsum(ld[1:5, 1:2, R9, n], axis=1), axis=0)
        s["newldvperld"][R9, n] = fsum(newldvs[1:MAXVTYP, R9, n], axis=0) / drivers

    if yrs > STOCKYR:
        drivers = fsum(fsum(ld[1:5, 1:2, R9, n], axis=1), axis=0)
        templdvsales = s["newldvperld"][R9, STOCKYR - 1989] * drivers
        regn_shr = templdvsales / fsum(templdvsales)

        inc, p_prev = s["inc00_d_16"], gas_price_00(s, n - 1)
        log, exp = np.log, np.exp

        def share(c, rho, inc_c, fuel_c, hp_c, wgt_c, mpg_c, dum_c, ivtyp, hp, wgt):
            c, rho, inc_c, fuel_c, hp_c, wgt_c, mpg_c, dum_c = (x[R9] for x in (c, rho, inc_c, fuel_c, hp_c, wgt_c, mpg_c, dum_c))
            return exp(c * (f32(1.0) - rho) + (rho * log(ctsplit[R9, ivtyp, n - 1]))
                       + inc_c * (log(inc[R9, n]) - (rho * log(inc[R9, n - 1])))
                       + fuel_c * (log(p00) - (rho * log(p_prev)))
                       + hp_c * (log(hp[R9, n - 1]) - (rho * log(hp[R9, n - 2])))
                       + wgt_c * (log(wgt[R9, n - 1]) - (rho * log(wgt[R9, n - 2])))
                       + mpg_c * (log(s["truempg_regn"][R9, ivtyp, n - 1]) - (rho * log(s["truempg_regn"][R9, ivtyp, n - 2])))
                       + dum_c * (log(s["dumm"][n]) - (rho * log(s["dumm"][n - 1]))))

        car = share(s["cconstant"], s["crho"], s["cinc"], s["cfuel"], s["chp"], s["cwgt"], s["cmpg"], s["cdumm"],
                    1, s["ahpcar"], s["awtcar"])
        trk = share(s["tconstant"], s["trho"], s["tinc"], s["tfuel"], s["thp"], s["twgt"], s["tmpg"], s["tdumm"],
                    2, s["ahptruck"], s["awttruck"])
        ctsplit[R9, 1, n] = car / (car + trk)
        ctsplit[R9, 2, n] = f32(1.0) - ctsplit[R9, 1, n]

        total = s["mc_suva"][n] + tempcls12a
        for ivtyp in range(1, MAXVTYP + 1):
            newldvs[ivtyp, R9, n] = total * regn_shr * ctsplit[R9, ivtyp, n]
            newldvs[ivtyp, MNUMCR, n] = fsum(newldvs[ivtyp, R9, n])
            if ivtyp == 2:
                ctsplit[MNUMCR, 1, n] = newldvs[1, MNUMCR, n] / fsum(newldvs[1:MAXVTYP, MNUMCR, n])
                ctsplit[MNUMCR, 2, n] = f32(1.0) - ctsplit[MNUMCR, 1, n]
        s["ivtyp"] = MAXVTYP + 1
