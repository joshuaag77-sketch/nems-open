"""This year's unit energy consumption by vintage: port of CALCSC (ind.f).

Old and new plants improve each year by the ratio of this year's to last year's
"REI adjustment", which grows with energy prices. Mid-vintage UEC is the
production-weighted mean of last year's mid and new vintages, with no new progress.

Works on an oracle-style state dict and updates it in place.

Quirks kept on purpose:
- REI_Adj and REI_Adj_Lag are local arrays in EIA's routine that persist between
  calls and are indexed only by fuel and step, so the "lag" is whatever the previous
  industry and region left. The port reads and writes s["rei_adj"] the same way.
- The time term is an integer division, (year - base - 4) / (15 - base - 4), with a
  negative denominator, so it truncates to 0 for every model year: only price drives
  the adjustment.
- INDBMOVR2 is a local that is never set (0).
- Oil and gas mining (industry 4) also calls OGSMTPC; that is not ported.
"""

import numpy as np

from nems_open.industrial.buildings import avefprc

f32 = np.float32


def calcsc(s: dict, ifuel: int, istep: int) -> None:
    inddir, ir, curiyr, curcalyr = int(s["inddir"]), int(s["indreg"]), int(s["curiyr"]), int(s["curcalyr"])
    if inddir == 4:
        raise NotImplementedError("OGSMTPC (oil and gas mining) is not ported")
    ibyr, ibyr2, techstrtyr = int(s["ibyr"]), int(s["ibyr2"]), int(s["techstrtyr"])
    frz = int(s["frztech"]) == 1 and curcalyr > techstrtyr
    beta, alpha1, alpha2 = f32(2.0), f32(1.0), f32(1.0)
    t_shift, t_mid = 4, 15
    if frz:
        alpha1 = alpha2 = f32(0.0)
    bcsc, rei_adj, rei_lag = s["bcsc"], s["rei_adj"], s["rei_adj_lag"]
    rei = {}
    for iv in (1, 3):
        rei[iv] = f32((f32(1.0) + f32(bcsc[iv, ifuel, istep])) ** f32(float(int(s["ijumpcalyr"]) - ibyr)))
    rei[2] = rei[3]

    ifx = int(s["ifloc"][ifuel, istep])
    prat = avefprc(s, ir, ibyr2 - 1989, curiyr, ifx)
    if curcalyr == ibyr:
        for iv in (1, 2, 3):
            rei_adj[iv, ifuel, istep] = 1.0
    for iv in (1, 2, 3):
        rei_lag[iv, ifuel, istep] = rei_adj[iv, ifuel, istep]
    # integer division truncating toward zero
    num, den = max(curcalyr - ibyr2 - t_shift, 0), t_mid - ibyr2 - t_shift
    tterm = int(num / den)
    rate = {}
    for iv in (1, 3):
        x = alpha1 * f32(tterm) + alpha2 * max(f32(prat - f32(1.0)), f32(0.0))
        adj = f32(1.0) + (rei[iv] - f32(1.0)) * (f32(1.0) - f32(1.0) / (f32(1.0) + f32(x ** beta)))
        rei_adj[iv, ifuel, istep] = adj
        rate[iv] = min(f32(adj / f32(rei_lag[iv, ifuel, istep])), f32(1.0))
    rate[2] = rate[3]

    if curcalyr > int(s["steolastyr"]) and int(s["itpc"]) == 1:
        bcsc[1, ifuel, istep] = f32(s["tpc1"]) * f32(bcsc[1, ifuel, istep])
        bcsc[3, ifuel, istep] = f32(s["tpc2"]) * f32(bcsc[3, ifuel, istep])

    lag, enpint, pl = s["enpintlag"], s["enpint"], s["prodlag"]
    for iv in (1, 3):
        enpint[iv, ifuel, istep] = f32(lag[iv, ifuel, istep]) * rate[iv]
    if f32(pl[2, istep]) + f32(pl[3, istep]) > 0.0:
        enpint[2, ifuel, istep] = (f32(pl[2, istep]) * f32(lag[2, ifuel, istep]) + f32(pl[3, istep]) * f32(lag[3, ifuel, istep])) \
            / (f32(pl[2, istep]) + f32(pl[3, istep]))
    if frz:
        enpint[1, ifuel, istep] = lag[1, ifuel, istep]
        enpint[3, ifuel, istep] = lag[3, ifuel, istep]
