"""Production by process step and capacity vintage: port of CALPROD (ind.f).

Each process step has old, mid-vintage and new capacity. Each year old capacity retires
at a rate that rises with the step's energy price, last year's new capacity becomes mid,
and idled capacity comes back. Final demand (the industry's production index, or
shipments by sub-industry for chemicals) is pushed back through the step-to-step flow
matrices (I minus A, old and new) to get the output each step must make; whatever old
and mid capacity cannot cover is built new, and a surplus is idled.

Works on an oracle-style state dict and updates it in place.

Quirks kept on purpose:
- PRODXIBYR, a local that persists between calls, is set in the base-year call and not
  used further here (it feeds only a debug print).
- The matrix inverse uses numpy in float64 and rounds to float32, where EIA's MINVERT is
  a hand-written elimination in double precision (same result to rounding; a singular
  matrix leaves the identity, as MINVERT's early exit does).
- Food (industry 7) rewrites its first-link flows from sub-industry shipments every call.
- Industries 10, 11 and 13 (glass, cement, aluminum) have extra flow, emission and
  regional-share logic that is not ported; 8 and 12 use other routines entirely.
"""

import numpy as np

f32 = np.float32


def avesprc(s: dict, ir: int, jy: int, iy: int, istep: int) -> np.float32:
    """Change in the price of the fuels a step uses, weighted by last year's use, since year jy."""
    if iy <= jy:
        return f32(1.0)
    enpintlag, prodlag, prcxyr, ifloc = s["enpintlag"], s["prodlag"], s["prcxyr"], s["ifloc"]
    sum_iy = sum_jy = sum_q = f32(0.0)
    for f in range(1, int(s["ifmax"][istep]) + 1):
        q = f32(enpintlag[1, f, istep]) * f32(prodlag[1, istep]) + f32(enpintlag[2, f, istep]) * f32(prodlag[2, istep]) \
            + f32(enpintlag[3, f, istep]) * f32(prodlag[3, istep])
        sum_q = sum_q + q
        ifx = int(ifloc[f, istep])
        sum_iy = sum_iy + q * f32(prcxyr[ifx, ir, iy, 3])
        sum_jy = sum_jy + q * f32(prcxyr[ifx, ir, jy, 3])
    if sum_q <= 0.0:
        return f32(1.0)
    ave_iy, ave_jy = f32(sum_iy / sum_q), f32(sum_jy / sum_q)
    if ave_jy == 0.0:
        return f32(1.0)
    return f32(ave_iy / ave_jy)


def _inverse(a: np.ndarray) -> np.ndarray:
    try:
        return np.linalg.inv(a.astype(np.float64)).astype(f32)
    except np.linalg.LinAlgError:
        return np.eye(a.shape[0], dtype=f32)


def calprod(s: dict, stepnames: list | None = None) -> None:
    inddir, ir, curiyr, curcalyr = int(s["inddir"]), int(s["indreg"]), int(s["curiyr"]), int(s["curcalyr"])
    if inddir in (8, 10, 11, 12, 13):
        raise NotImplementedError("process-flow industries are not ported")
    n = int(s["mpastp"])
    ibyr, ibyr2, techstrtyr, iyr = int(s["ibyr"]), int(s["ibyr2"]), int(s["techstrtyr"]), int(s["iyr"])
    prodcur, prodlag, idlcap, idlcaplag = s["prodcur"], s["prodlag"], s["idlcap"], s["idlcaplag"]
    prodretr = s["prodretr"]
    prodflow, ntmax, ipastp = s["prodflow"], s["ntmax"], s["ipastp"]
    OLD, MID, NEU, TOT = 1, 2, 3, 4

    prat = {i: avesprc(s, ir, ibyr2 - 1989, curiyr, i) for i in range(1, n + 1)}
    if int(s["iretire"]) == 1 and curcalyr == ibyr + 2:
        for i in range(1, n + 1):
            prodretr[i] = min(f32(0.9), f32(s["retrate"]) * f32(prodretr[i]))
    rate = {i: f32(prodretr[i]) for i in range(1, n + 1)}
    for i in range(1, n + 1):
        x = f32(prat[i] ** f32(2.0))
        fac = f32(x / (f32(1.0) + x))
        if curcalyr > techstrtyr:
            if int(s["frztech"]) == 1:
                rate[i] = f32(prodretr[i]) * fac
            elif int(s["hitech"]) == 1:
                rate[i] = f32(3.0) * f32(prodretr[i]) * fac
            else:
                rate[i] = f32(2.0) * f32(prodretr[i]) * fac

    prodcur.a[...] = prodlag.a
    idlcap.a[...] = idlcaplag.a
    for i in range(1, n + 1):
        prodcur[MID, i] = f32(prodcur[MID, i]) + f32(prodcur[NEU, i])
        prodcur[OLD, i] = f32(prodcur[OLD, i]) + f32(idlcap[i])
        idlcap[i] = 0.0
        prodcur[NEU, i] = 0.0
        prodcur[OLD, i] = f32(prodcur[OLD, i]) * (f32(1.0) - rate[i])
        prodcur[TOT, i] = f32(prodcur[OLD, i]) + f32(prodcur[MID, i])

    idval = int(s["idval"])
    if idval == 1:
        s["prodx"] = f32(s["phdrat"]) * f32(s["prodvx"])
    elif idval == 2:
        s["prodx"] = f32(s["prodvx"])
    prodx = f32(s["prodx"])

    if inddir == 7:
        fs = s["foodship"]
        for i in range(1, n + 1):
            isub = (i - 1) // 6 + 1
            prodflow[1, i, 1] = f32(fs[isub, ir, iyr]) / f32(fs[5, ir, iyr])
            prodflow[2, i, 1] = prodflow[1, i, 1]

    m = n + 1
    d = np.zeros(m + 1, dtype=f32)
    if inddir != 9:
        d[1] = prodx
    else:
        if stepnames is None:
            raise ValueError("chemicals need the step names (steps called STEAM get no final demand)")
        for i in range(1, n + 1):
            if "STEAM" not in stepnames[i].upper():
                d[i + 1] = f32(s["chemship"][(i - 1) // 6 + 1, ir, curcalyr])

    ia_old = np.zeros((m + 1, m + 1), dtype=f32)
    ia_new = np.zeros((m + 1, m + 1), dtype=f32)
    ia_old[1, 1] = ia_new[1, 1] = 1.0
    for i in range(1, n + 1):
        ia_old[i + 1, i + 1] = ia_new[i + 1, i + 1] = 1.0
        for it in range(1, int(ntmax[i]) + 1):
            down = int(ipastp[i, it])
            ia_old[i + 1, down + 1] = f32(0.0) - f32(prodflow[1, i, it])
            ia_new[i + 1, down + 1] = f32(0.0) - f32(prodflow[2, i, it])
    inv_new = np.zeros_like(ia_new)
    inv_old = np.zeros_like(ia_old)
    inv_new[1:m + 1, 1:m + 1] = _inverse(ia_new[1:m + 1, 1:m + 1])
    inv_old[1:m + 1, 1:m + 1] = _inverse(ia_old[1:m + 1, 1:m + 1])

    xsurv = np.zeros(m + 1, dtype=f32)
    xsurv[1] = d[1]
    for i in range(1, n + 1):
        xsurv[i + 1] = prodcur[OLD, i]
    dsurv = (ia_old[1:m + 1, 1:m + 1] @ xsurv[1:m + 1]).astype(f32)
    dnew = np.zeros(m + 1, dtype=f32)
    dnew[1:m + 1] = d[1:m + 1] - dsurv
    xnew = (inv_new[1:m + 1, 1:m + 1] @ dnew[1:m + 1]).astype(f32)
    for i in range(1, n + 1):
        prodcur[NEU, i] = xnew[i] - f32(prodcur[MID, i])  # xnew is 0-based over rows 1..m, so row i+1 is index i
    for i in range(1, n + 1):
        if prodcur[NEU, i] < 0.0:
            idlcap[i] = f32(-1.0) * f32(prodcur[NEU, i])
            prodcur[NEU, i] = 0.0
        idled_old = min(f32(prodcur[OLD, i]), f32(idlcap[i]))
        idled_mid = min(f32(prodcur[MID, i]), f32(idlcap[i]) - idled_old)
        idlcap[i] = idled_old + idled_mid
        prodcur[OLD, i] = f32(prodcur[OLD, i]) - idled_old
        prodcur[MID, i] = f32(prodcur[MID, i]) - idled_mid
        prodcur[TOT, i] = f32(prodcur[OLD, i]) + f32(prodcur[MID, i]) + f32(prodcur[NEU, i])
