"""Byproduct energy from the process and assembly steps: port of CALBYPROD (ind.f).

Byproduct intensities (biomass and pulping liquor above all) grow each year at a rate
that rises with the price of the fuel they replace; production is throughput times
intensity, summed over steps and sorted into main, intermediate and renewable fuels.

Works on an oracle-style state dict and updates it in place.

Quirks kept on purpose:
- The sorting loop is written with the fuel loop outside the step loop and the loop
  bound IFBYP(IS) read after the step loop has ended, so IS is MPASTP+1 there. The
  port uses IFBYP(MPASTP+1) (0 when it lies outside the array), as the Fortran does.
- BYPADIBYR is set to 1 just before use; in the base year it is rescaled from the
  base-year renewable boiler fuel (BSCIBYR fuel 42) over the wood byproduct.
- TPC1/TPC3 are rewritten to fixed values (0.003, then 0.004 / 0.005) every call.
"""

import numpy as np

from nems_open.industrial.buildings import avefprc

f32 = np.float32
BEHAVE = 2  # rtovalue('BEHAVE', 2): the default is what a normal run uses


def calbyprod(s: dict, behave: int = BEHAVE, hirenew: int = 0, lorenew: int = 0) -> None:
    ir, inddir, curiyr = int(s["indreg"]), int(s["inddir"]), int(s["curiyr"])
    curcalyr, ibyr, ibyr2 = int(s["curcalyr"]), int(s["ibyr"]), int(s["ibyr2"])
    techstrtyr = int(s["techstrtyr"])
    mpastp, mainfuels, idval = int(s["mpastp"]), int(s["mainfuels"]), int(s["idval"])
    ifbyp, iflocby = s["ifbyp"], s["iflocby"]
    bypcsc, bypint, bypintlag = s["bypcsc"], s["bypint"], s["bypintlag"]
    prodlag, prodcur, bypqty = s["prodlag"], s["prodcur"], s["bypqty"]

    for i_s in range(1, mpastp + 1):
        for ifuel in range(1, int(ifbyp[i_s]) + 1):
            bypcsc[1, ifuel, i_s] = f32(0.003)
            bypcsc[3, ifuel, i_s] = f32(0.003)

    beta = f32(4.0)
    for i_s in range(1, mpastp + 1):
        for ifuel in range(1, int(ifbyp[i_s]) + 1):
            ifx = int(iflocby[ifuel, i_s])
            prat = avefprc(s, ir, ibyr2 - 1989, curiyr, ifx)
            if ifx in (42, 43):
                if prat >= f32(1.1) and behave == 2:
                    v = f32(0.004)
                elif curcalyr > techstrtyr and behave == 2:
                    v = f32(0.007)
                elif hirenew == 1 and curcalyr > techstrtyr and behave == 2:
                    v = f32(0.013)
                else:
                    v = f32(0.005)
                bypcsc[1, ifuel, i_s] = v
                bypcsc[3, ifuel, i_s] = v
            tpc1, tpc3 = f32(bypcsc[1, ifuel, i_s]), f32(bypcsc[3, ifuel, i_s])
            with np.errstate(all="ignore"):
                x = f32(prat ** beta)
                fac = f32(x / (f32(1.0) + x))
            if np.isnan(fac):
                fac = f32(0.5)
            rate1 = f32(2.0) * tpc1 * fac
            rate3 = f32(2.0) * tpc3 * fac
            for iv, rate in ((1, rate1), (3, rate3)):
                bypint[iv, ifuel, i_s] = f32(bypintlag[iv, ifuel, i_s]) * np.exp(rate, dtype=f32)
                if f32(prodlag[2, i_s]) + f32(prodlag[3, i_s]) > 0.0:
                    num = f32(prodlag[2, i_s]) * f32(bypintlag[2, ifuel, i_s]) + f32(prodlag[3, i_s]) * f32(bypintlag[3, ifuel, i_s])
                    den = f32(prodlag[2, i_s]) + f32(prodlag[3, i_s])
                    bypint[2, ifuel, i_s] = f32(num / den) * np.exp(rate1, dtype=f32)

    bypqty.a[...] = 0.0
    for i_s in range(1, mpastp + 1):
        for ifuel in range(1, int(ifbyp[i_s]) + 1):
            for iv in (1, 2, 3):
                bypqty[iv, ifuel, i_s] = f32(prodcur[iv, i_s]) * f32(bypint[iv, ifuel, i_s])
            bypqty[4, ifuel, i_s] = bypqty[1:3, ifuel, i_s].sum(dtype=f32)
    if idval == 1:
        for i_s in range(1, mpastp + 1):
            for ifuel in range(1, int(ifbyp[i_s]) + 1):
                for iv in range(1, 5):
                    bypqty[iv, ifuel, i_s] = f32(bypqty[iv, ifuel, i_s]) / f32(1000000.0)
    for i_s in range(1, mpastp + 1):
        for iv in range(1, 5):
            bypqty[iv, 6, i_s] = 0.0
            for ifuel in range(1, int(ifbyp[i_s]) + 1):
                bypqty[iv, 6, i_s] = f32(bypqty[iv, 6, i_s]) + f32(bypqty[iv, ifuel, i_s])

    bm, bi, br, adj = s["bypbscm"], s["bypbsci"], s["bypbscr"], s["bypadibyr"]
    for f in range(1, mainfuels + 1):
        bm[f] = 0.0
    for f in range(1, 8):
        bi[f] = 0.0
    for f in range(1, 10):
        br[f] = 0.0
        adj[f] = 1.0

    after = mpastp + 1  # value of IS once the step loop has finished
    lo, hi = ifbyp.lb[0], ifbyp.lb[0] + ifbyp.a.shape[0] - 1
    nfuel = int(ifbyp[after]) if lo <= after <= hi else 0
    for ifuel in range(1, nfuel + 1):
        for i_s in range(1, mpastp + 1):
            ifx = int(iflocby[ifuel, i_s])
            q = f32(bypqty[4, ifuel, i_s])
            if ifx <= 30:
                bm[ifx] = f32(bm[ifx]) + q
            elif ifx <= 40:
                bi[ifx - 30] = f32(bi[ifx - 30]) + q
            else:
                br[ifx - 40] = f32(br[ifx - 40]) + q

    if curcalyr <= ibyr:
        for f in range(1, 10):
            adj[f] = 1.0
        tot = br[2:3].sum(dtype=f32)
        if tot != 0.0:
            for f in (2, 3):
                adj[f] = max(f32(s["bscibyr"][inddir, ir, 42]) / tot, f32(1.0))
    for f in range(1, 10):
        br[f] = f32(adj[f]) * f32(br[f])
