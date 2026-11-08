"""Building energy for one industry and region: port of CALBTOT (ind.f).

ENBQTY(use, fuel): lighting, HVAC, facility support, transport, conventional power
and other nonprocess use, for electricity, natural gas, steam, distillate and
propane. Each cell blends an employment term and a production term, times a price
factor (price since the base year, elasticity -0.5).

Works on an oracle-style state dict and updates it in place.

Quirk kept on purpose: PRODVXIBYR and EMPLXIBYR are local arrays that only get
set in the base-year call (CURIYR = IBYR2 - BASEYR + 1) and are read in every later
call. EIA's routine relies on them keeping their values between calls; pass the
same `base` dict to every call (it is filled in the base-year call).
"""

import numpy as np

f32 = np.float32
EWEIGHT = f32(0.7)
PWEIGHT = f32(1.0) - EWEIGHT
BLD_ELAS = f32(-0.5)
IBLDLOC = (1, 3, 31, 11, 12)  # elec, core ng, steam, dist, propane


def avefprc(s: dict, ir: int, jy: int, iy: int, ifx: int) -> np.float32:
    """Price ratio of fuel ifx in year iy to year jy (1.0 when iy <= jy or the base price is 0)."""
    if iy <= jy:
        return f32(1.0)
    pr = s["prcxyr"]
    prc_iy, prc_jy = f32(pr[ifx, ir, iy, 3]), f32(pr[ifx, ir, jy, 3])
    if prc_jy == 0.0:
        return f32(1.0)
    return f32(prc_iy / prc_jy)


def calbtot(s: dict, base: dict) -> None:
    inddir, ir, iy = int(s["inddir"]), int(s["indreg"]), int(s["curiyr"])
    ibyr2, baseyr = int(s["ibyr2"]), int(s["baseyr"])
    emplx, prodvx = f32(s["emplx"]), f32(s["prodvx"])
    enbint, enbqty = s["enbint"], s["enbqty"]

    if iy == ibyr2 - baseyr + 1:
        base[(inddir, ir)] = (prodvx, emplx)
    pb, eb = base.get((inddir, ir), (f32(0.0), f32(0.0)))

    uec = np.zeros((7, 6), dtype=f32)  # 1-based (use, fuel)
    if pb > 0.0 and eb > 0.0:
        for i in range(1, 7):
            for j in range(1, 6):
                uec[i, j] = f32(enbint[i, j]) * f32(eb / pb)

    for i in range(1, 7):
        for j in range(1, 6):
            ifx = IBLDLOC[j - 1]
            prat = avefprc(s, ir, ibyr2 - 1989, iy, ifx)
            pfac = f32(prat ** BLD_ELAS)
            enbqty[i, j] = pfac * (EWEIGHT * emplx * f32(enbint[i, j]) + PWEIGHT * prodvx * uec[i, j])
    for j in range(1, 6):
        enbqty[7, j] = enbqty[1:6, j].sum(dtype=f32)
