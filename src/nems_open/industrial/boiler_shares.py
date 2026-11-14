"""Boiler fuel shares: port of CALBSC (ind.f).

For one industry and census region, splits boiler/steam fuel use among fuels. The
base year mix (MECS) is scaled by boiler efficiency, then natural gas and coal
shrink and electricity grows along a logistic curve centred halfway between the
base year and the last year. Each fuel's share is then weighted by its price
index raised to a fixed exponent (-2) and normalised.

Reads and writes the same arrays the Fortran does: BSCIBYR (zeroed for coal in
non-manufacturing), BSFUELSHR(industry, region, fuel) and BSSHR(fuel). BSSHR
only gets the fuels listed below, so the rest keep their earlier values, as in
the Fortran.
"""

import numpy as np

f32 = np.float32
SWITCH_BETA = f32(2.0)  # only feeds SwitchPrat, whose result CALBSC never uses
COAL_PFAC, NGAS_PFAC, OIL_PFAC, ELEC_PFAC = f32(1.33), f32(1.00), f32(1.17), f32(1.00)
COAL_SHR_2050, NG_SHR_2050 = f32(0.20), f32(0.10)
ASLOPE = f32(0.5)
ALPHA = f32(-2.0)
BOILER_FUEL_LIST = (1, 4, 7, 10, 11, 12, 16, 22, 42)
PETROLEUM = (10, 11, 12, 14, 15, 16, 20)


def calbsc(s: dict, inddir: int, indreg: int) -> None:
    """Updates s['bscibyr'], s['bsfuelshr'], s['bsshr'] in place.

    s is an oracle state (FArrays keyed by lowercase Fortran name, plus scalars)."""
    bscibyr, bsfuelshr, bsshr = s["bscibyr"], s["bsfuelshr"], s["bsshr"]
    beff, prcx, prcxibyr = s["beff"], s["prcx"], s["prcxibyr"]
    mainfuels = int(s["mainfuels"])
    ibyr, lastcalyr, curcalyr = int(s["ibyr"]), int(s["lastcalyr"]), int(s["curcalyr"])

    if inddir < 7:
        bscibyr[inddir, indreg, 7] = 0.0  # nonmanufacturing doesn't use coal
    sumall = f32(bscibyr[inddir, indreg, 1:mainfuels].sum(dtype=f32))
    bsfuelshr[inddir, indreg, 1:mainfuels] = 0.0

    xzero = ibyr + (lastcalyr - ibyr) // 2  # integer division, as in Fortran
    logistic = f32(1) / (f32(1) + np.exp(-ASLOPE * f32(curcalyr - xzero)))

    if sumall > 0:
        for f in range(1, mainfuels + 1):
            if f in BOILER_FUEL_LIST:
                bsfuelshr[inddir, indreg, f] = (bscibyr[inddir, indreg, f] / sumall) * beff[f]
            if curcalyr > ibyr:
                if f == 4:  # natural gas
                    bsfuelshr[inddir, indreg, f] = (bscibyr[inddir, indreg, 4] / sumall) * \
                        (f32(1) - logistic * NG_SHR_2050) * beff[4]
                elif f == 7:  # coal
                    bsfuelshr[inddir, indreg, f] = (bscibyr[inddir, indreg, 7] / sumall) * \
                        (f32(1) - logistic * COAL_SHR_2050) * beff[7]
                elif f == 1:  # electricity picks up what gas and coal give up
                    bsfuelshr[inddir, indreg, f] = (bscibyr[inddir, indreg, 1] / sumall) \
                        + logistic * NG_SHR_2050 * (bscibyr[inddir, indreg, 4] / sumall) * beff[1] / beff[4] \
                        + logistic * COAL_SHR_2050 * (bscibyr[inddir, indreg, 7] / sumall) * beff[1] / beff[7]

    # Indexed prices: gas, coal, residual, electricity. Floor of 0.05 keeps the
    # negative exponent finite when a price is zero.
    w = [NGAS_PFAC * prcx[4, indreg, 3] / prcxibyr[1, indreg],
         COAL_PFAC * prcx[7, indreg, 3] / prcxibyr[2, indreg],
         OIL_PFAC * prcx[10, indreg, 3] / prcxibyr[3, indreg],
         ELEC_PFAC * prcx[1, indreg, 3] / prcxibyr[4, indreg]]
    w = [f32(0.05) if x <= f32(0.05) else f32(x) for x in w]
    w1, w2, w3, w4 = w

    for f in range(1, mainfuels + 1):
        if f == 1:
            bsshr[f] = np.power(w4, ALPHA) * bsfuelshr[inddir, indreg, f]
        elif f == 4:
            bsshr[f] = np.power(w1, ALPHA) * bsfuelshr[inddir, indreg, f]
        elif f == 7:
            bsshr[f] = np.power(w2, ALPHA) * bsfuelshr[inddir, indreg, f]
            if inddir < 7:
                bsshr[f] = 0.0  # no nonmfg coal boilers
        elif f in PETROLEUM:
            bsshr[f] = np.power(w3, ALPHA) * bsfuelshr[inddir, indreg, f]

    lsum = f32(bsshr[1:mainfuels].sum(dtype=f32))
    if lsum != 0:
        bsshr[1:mainfuels] = bsshr[1:mainfuels] / lsum
    bsshr[51] = sum((bsshr[i] for i in (10, 11, 12, 14, 15, 16, 20, 22)), f32(0))  # petroleum subtotal
