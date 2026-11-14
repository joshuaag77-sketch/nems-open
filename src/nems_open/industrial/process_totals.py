"""Process and assembly energy totals: port of CALPATOT (ind.f), end-use industries.

Energy by vintage and step is production times unit energy consumption (UEC); the total
vintage (4) is the sum of the three. Steps with special treatment: hydrogen feedstock
for inorganic and agricultural chemicals, and corn ethanol / nitrogen fertilizer fuel
(CORNCALC). Everything is then summed into main (ENPMQTY), intermediate (ENPIQTY) and
renewable (ENPRQTY) fuel arrays by the fuel's location index.

Only the end-use (non process-flow) path is ported: industries 8 and 12 and the 'tech'
version for 10, 11, 13 use their own models and raise NotImplementedError.

Works on an oracle-style state dict and updates it in place.
"""

import numpy as np

f32 = np.float32
ICURIYR = 33  # parameter in MODULE I_
END_YR_FEEDSTOCK = 2027  # parameter in MODULE I_


def corncalc(s: dict, i_s: int, ifuel: int, ifx: int) -> None:
    inddir, ir, curiyr = int(s["inddir"]), int(s["indreg"]), int(s["curiyr"])
    q = s["enpqty"]
    bushel = s["bushel"]
    if inddir == 1:
        d = f32(bushel[curiyr, ir]) - f32(bushel[ICURIYR, ir])
        fac = (f32(1.10), f32(3.05), f32(6.65), f32(3.32), f32(1.64))
        idx = {1: 0, 3: 1, 11: 2, 12: 3, 14: 4}
        if ifx in idx:
            add = fac[idx[ifx]] * d / f32(1000.0)
            q[3, ifuel, i_s] = f32(q[3, ifuel, i_s]) + add
            q[4, ifuel, i_s] = f32(q[4, ifuel, i_s]) + add
    elif inddir == 9 and int(s["curcalyr"]) > END_YR_FEEDSTOCK:
        nitro = f32(23.4) * (f32(bushel[curiyr, ir]) - f32(bushel[END_YR_FEEDSTOCK - 1989, ir]))
        if ifx == 5:
            q[4, ifuel, i_s] = f32(q[4, ifuel, i_s]) + nitro / f32(1000.0)


def calpatot(s: dict, version: str = "original") -> None:
    inddir, ir, curiyr, curcalyr = int(s["inddir"]), int(s["indreg"]), int(s["curiyr"]), int(s["curcalyr"])
    if inddir in (8, 12) or (version == "tech" and inddir in (10, 11, 13)):
        raise NotImplementedError("process-flow industries are not ported")
    mpastp, mainfuels, idval = int(s["mpastp"]), int(s["mainfuels"]), int(s["idval"])
    ifmax, ifloc = s["ifmax"], s["ifloc"]
    prodcur, enpint, q = s["prodcur"], s["enpint"], s["enpqty"]

    for i_s in range(1, mpastp + 1):
        for f in range(1, int(ifmax[i_s]) + 1):
            for iv in (1, 2, 3):
                q[iv, f, i_s] = f32(prodcur[iv, i_s]) * f32(enpint[iv, f, i_s])
            q[4, f, i_s] = q[1:3, f, i_s].sum(dtype=f32)
            if inddir == 9 and i_s == 6 and f == 1:
                q[1:2, f, i_s] = 0.0
                q[3, f, i_s] = f32(s["chemship"][7, ir, curcalyr]) * f32(enpint[3, f, i_s])
                q[4, f, i_s] = q[1:3, f, i_s].sum(dtype=f32)
            if inddir == 9 and i_s == 24 and f == 1:
                if curcalyr <= int(s["steolastyr"]) - 2:
                    q[1:2, f, i_s] = 0.0
                    q[3, f, i_s] = f32(s["fertilizer_h2"][curiyr, ir])
                    q[4, f, i_s] = q[1:3, f, i_s].sum(dtype=f32)

    for i_s in range(1, mpastp + 1):
        for f in range(1, int(ifmax[i_s]) + 1):
            ifx = int(ifloc[f, i_s])
            if inddir == 1 and i_s == 1:
                corncalc(s, i_s, f, ifx)
            if inddir == 9 and i_s == 24 and ifx == 5:
                corncalc(s, i_s, f, ifx)

    if idval in (1, 3):
        for i_s in range(1, mpastp + 1):
            for f in range(1, 11):
                for iv in range(1, 5):
                    q[iv, f, i_s] = f32(q[iv, f, i_s]) / f32(1000000.0)

    for i_s in range(1, mpastp + 1):
        for iv in range(1, 5):
            q[iv, 18, i_s] = 0.0
            for f in range(1, int(ifmax[i_s]) + 1):
                q[iv, 18, i_s] = f32(q[iv, 18, i_s]) + f32(q[iv, f, i_s])

    em, ei, er = s["enpmqty"], s["enpiqty"], s["enprqty"]
    em[1:mainfuels] = 0.0
    ei[1:7] = 0.0
    er[1:9] = 0.0
    for i_s in range(1, mpastp + 1):
        for f in range(1, int(ifmax[i_s]) + 1):
            ifx = int(ifloc[f, i_s])
            v = f32(q[4, f, i_s])
            if ifx <= 30:
                em[ifx] = f32(em[ifx]) + v
            elif ifx <= 40:
                ei[ifx - 30] = f32(ei[ifx - 30]) + v
            else:
                er[ifx - 40] = f32(er[ifx - 40]) + v
