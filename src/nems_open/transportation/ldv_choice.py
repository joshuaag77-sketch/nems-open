"""Refueling availability and powertrain choice (tran.f): TALT2, TALT2X.

TALT2   stations by fuel grow with the predicted stock of vehicles that use them,
        split by region with last year's sales; fuel availability by powertrain
TALT2X  nested multinomial logit for each region, size class and manufacturer
        group: powertrains within five nests (conventional, hybrid, gaseous, fuel
        cell, battery electric), then across nests; sales by powertrain

TALT2X does its logit in REAL*8 like the Fortran, rounding to REAL*4 where the
Fortran stores into single-precision arrays.
"""

import numpy as np

from nems_open.transportation.common import f32, fmax, fmin, fsum, logf, MAXLDV, MNUMCR, STOCKYR

MAXCLASS = 8
MAXGROUP = 11
MAXFUEL = 8
MAXCHRG = 3
R9 = slice(1, MNUMCR - 2)
f64 = np.float64

# Powertrains in each nest (EIA's L2GROUP).
L2GROUP = [[1, 2, 3, 9, 10, 16], [5, 6, 8], [11, 12], [13, 14], [4, 7, 15]]


def _pred_stock(ldvstk, n):
    m = f32(1000000.0)
    s = lambda *k: fsum([ldvstk[i, n - 1] for i in k])  # noqa: E731
    return {
        1: (s(3, 5, 6, 9, 10, 16) * f32(0.75) + s(1, 16)) * m,
        2: s(2, 8) * m,
        3: (ldvstk[3, n - 1] * f32(0.25)) * m,
        4: ldvstk[13, n - 1] * m,
        5: ((ldvstk[9, n - 1] * f32(0.25)) + ldvstk[11, n - 1]) * m,
        6: ((ldvstk[10, n - 1] * f32(0.25)) + ldvstk[12, n - 1]) * m,
        7: ((ldvstk[5, n - 1] * f32(0.1) + ldvstk[6, n - 1]) * f32(0.25) + ldvstk[4, n - 1] + ldvstk[7, n - 1] + ldvstk[15, n - 1]) * m,
        8: ldvstk[14, n - 1] * m,
    }


def talt2(s: dict, carry: dict) -> None:
    """carry: altstat(MAXFUEL, MNUMYR), predstk(MAXFUEL, MNUMYR), year n-1 filled."""
    n, yrs, epa = int(s["n"]), int(s["yrs"]), int(s["epalyr"])
    altstat, predstk = carry["altstat"], carry["predstk"]
    init, ldvstk = s["initsta"], s["ldvstk"]
    altsta = np.zeros((MAXFUEL + 1, MNUMCR - 1), dtype=f32)
    F = slice(1, MAXFUEL)
    if yrs <= 1995:
        altsta[1:, 1:] = init[F, 6, R9]
    elif yrs <= 2012:
        altsta[1:, 1:] = init[F, n, R9]
        altstat[F, n] = fsum(altsta[1:, 1:], axis=1)
        s["cngavail"][R9, n] = altsta[5, 1:] / altsta[1, 1:]
        if yrs == 2012:
            for k, v in _pred_stock(ldvstk, n).items():
                predstk[k, n] = v
    if yrs <= 2012 and "sta_rat_base" in carry:
        carry["sta_rat_base"][...] = s["sta_rat"].a          # STA_RAT_BASE, a saved local
    if yrs > 2012:
        for k, v in _pred_stock(ldvstk, n).items():
            predstk[k, n] = v
        rat = s["sta_rat"]
        if yrs <= STOCKYR:
            # STA_RAT_BASE is a saved local holding the input ratios from 2012. A run from the
            # first call carries it; a start from a dump (first iteration) rebuilds it, since
            # STA_RAT(2:) has since been base + (last year's predicted stock ratio) * STA_RAT(1).
            if "sta_rat_base" in carry:
                base = carry["sta_rat_base"][1:MAXFUEL]
            else:
                base = rat[2:MAXFUEL] - (predstk[2:MAXFUEL, n - 1] / predstk[1, n - 1]) * rat[1]
            rat[2:MAXFUEL] = base + (predstk[2:MAXFUEL, n] / predstk[1, n]) * rat[1]
        altstat[F, n] = altstat[F, n - 1] + ((predstk[F, n] - predstk[F, n - 1]) / rat[F])
        sales = s["ldv_sales"]

        def vs(*ldv):
            return fsum(fsum(fsum(np.stack([sales[1:MAXGROUP, 1:MAXCLASS, k, R9, n - 1] for k in ldv], axis=2),
                                  axis=2), axis=1), axis=0)
        fvs = {1: vs(1, 16), 2: vs(2, 8), 3: vs(3), 4: vs(13), 5: vs(9, 11), 6: vs(10, 12), 7: vs(4, 5, 6, 7, 15), 8: vs(14)}
        for k in range(1, MAXFUEL + 1):
            tot = fsum(fvs[k])
            shr = fvs[k] / tot if tot != 0.0 else np.zeros(MNUMCR - 2, dtype=f32)
            altsta[k, 1:] = altstat[k, n] * shr
        s.update(ifuel=MAXFUEL + 1, iregn=MNUMCR - 1)

    fav, stock = s["favail"], s["ldv_stock"]
    chr_str, chr_lst = int(s["chr_str_yr"]), int(s["chr_lst_yr"])
    for iregn in range(1, MNUMCR - 1):
        for ifuel in range(1, MAXFUEL + 1):
            if ifuel == 7:
                if chr_str <= n <= chr_lst and not (int(s["enforce_my27regs"]) == 0 and yrs > epa + 2):
                    gas = (init[1, n, iregn] * s["gas_pump_per_sta"]) * s["gas_hrly_thruput"]
                    port = s["prt_cnt"][1:MAXCHRG, n, iregn] / s["prt_rt"][1:MAXCHRG]
                    fav[ifuel, n, iregn] = fsum(port) / gas
                else:
                    def ev_share(y):
                        sub = stock[iregn, :, :, :, :, :, y]          # (type, owner, ldv, age, hav)
                        return fsum(sub[:, :, [3, 6, 14]]) / fsum(sub)
                    fav[ifuel, n, iregn] = fav[ifuel, n - 1, iregn] * ((ev_share(n - 1) / ev_share(n - 2) - f32(1.0)) * s["elas_favl"] + f32(1.0))
            else:
                if altsta[1, iregn] > 0.0:
                    fav[ifuel, n, iregn] = altsta[ifuel, iregn] / altsta[1, iregn]
                    if ifuel == 8:
                        fav[ifuel, n, iregn] = fmin(fav[ifuel, n, iregn], fav[ifuel, n - 1, iregn] * f32(1.1))
                if yrs > 2012:
                    fav[ifuel, n, iregn] = fmax(fav[ifuel, n, iregn], fav[ifuel, n - 1, iregn])
            if yrs > 2012 and ifuel == 5:
                fav[ifuel, n, iregn] = fmax(fav[ifuel, n, iregn], s["cngavail"][iregn, n])
            # gfortran's MIN: 1995's EV availability is 0 * NaN (no stock before 1995) and ends
            # at gasoline's.
            fav[ifuel, n, iregn] = fmin(fav[ifuel, n, iregn], fav[1, n, iregn])
    s.update(ifuel=MAXFUEL + 1, iregn=MNUMCR - 1)

    favl = s["favl"]
    a = lambda k: fav[k, n, R9]  # noqa: E731
    mx = np.maximum
    for k, v in {1: a(1), 2: a(2), 3: mx(a(3), a(1)), 4: a(7), 5: mx(a(7), a(1)), 6: mx(a(7), a(1)), 7: a(7),
                 8: mx(a(7), a(2)), 9: mx(a(5), a(1)), 10: mx(a(6), a(1)), 11: a(5), 12: a(6), 13: a(4), 14: a(8),
                 15: a(7), 16: a(1)}.items():
        favl[k, R9, yrs] = v


# Plug-in powertrains: EV100, PHEV20, PHEV50, EV200, EV300.
PLUG_IN = (4, 5, 6, 7, 15)


def _talt2x_shares(s: dict, n: int, yrs: int, shift: float = 0.0) -> np.ndarray:
    """TALT2X's logit: shares [group, class, powertrain, region] (0-based, REAL*4), with
    `shift` added to every plug-in's utility (0: EIA's model exactly).

    Every group, class and region at once, as (group, class, powertrain, region) arrays:
    the utility terms are added in the Fortran's order in double precision, and each nest's
    sum adds its powertrains in order, so every element is the scalar loop's."""
    G, C, L = slice(1, MAXGROUP), slice(1, MAXCLASS), slice(1, MAXLDV)
    R = slice(1, MNUMCR - 2)
    gcl = lambda a: np.transpose(a, (0, 2, 1, 3))  # noqa: E731  [igp, ildv, icl, iregn] -> [igp, icl, ildv, iregn]
    avail = gcl(s["mmavail"][G, L, C, R, yrs])
    pspr = gcl(s["pspr"][G, L, C, R, yrs])
    if ((avail > 0.0) & (pspr < 0.0)).any():
        raise ValueError("TDM TALT2X: STOP 450, negative vehicle price")
    co = s["nmlmco"]
    c = [None] + [f64(np.transpose(co[k, C, G]))[:, :, None, None] for k in range(1, 13)]   # [igp, icl]
    on = avail > 0.0
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        mm_log = f64(logf(np.where(on, avail, f32(1.0))))
        vr_inv = f64(f32(1.0) / gcl(s["vrng"][G, L, C, R, yrs]))
        br = f64(np.transpose(s["brcost25"][G, L, C, yrs], (0, 2, 1)))[:, :, :, None]
        favl = f64(s["favl"][L, R, yrs])[None, None, :, :]
        u = (c[1] * f64(pspr) + c[2] * f64(gcl(s["flcost"][G, L, C, R, yrs]))
             + c[3] * vr_inv + c[4] * br + c[5] * f64(gcl(s["accl"][G, L, C, R, yrs]))
             + c[6] * f64(gcl(s["hfuel"][G, L, C, R, yrs])) + c[7] * f64(gcl(s["maint"][G, L, C, R, yrs]))
             + c[8] * f64(gcl(s["lugg"][G, L, C, R])) + c[9] * np.exp(c[10] * favl)
             + c[11] * mm_log + f64(s["x210"][G, C, L, R, n]))
        shift = f64(shift)
        if shift != 0.0:
            plug = np.zeros(MAXLDV, dtype=bool)
            plug[[k - 1 for k in PLUG_IN]] = True
            u = np.where(plug[None, None, :, None], u + shift, u)
        e = np.where(on & (u != 0.0), np.exp(np.where(on, u, 0.0)), f64(0.0))
        inv1 = f64(f32(1.0) / np.transpose(co[1, C, G]))[:, :, None]
        xshare = np.zeros_like(e)
        gcost = []
        for nest in L2GROUP:
            k = [x - 1 for x in nest]
            etot = np.zeros(e.shape[:2] + e.shape[3:], dtype=f64)
            for x in k:
                etot = etot + e[:, :, x, :]
            ok = etot != 0.0
            xshare[:, :, k, :] = np.where(ok[:, :, None, :], (e[:, :, k, :] / np.where(ok, etot, 1.0)[:, :, None, :]) * 100.0, 0.0)
            gcost.append(np.where(ok, inv1 * np.log(np.where(ok, etot, 1.0)), f64(0.0)))
        c12 = c[12][:, :, :, 0]
        esum = [np.where(c12 * g != 0.0, np.exp(c12 * g), f64(0.0)) for g in gcost]
        etot = np.zeros_like(esum[0])
        for x in esum:
            etot = etot + x
        ok = etot != 0.0
        out = np.zeros((MAXGROUP, MAXCLASS, MAXLDV, MNUMCR - 2), dtype=f32)
        for jg, nest in enumerate(L2GROUP):
            yshare = np.where(ok, (esum[jg] / np.where(ok, etot, 1.0)) * 100.0, 0.0)
            for ildv in nest:
                xgs = f32(xshare[:, :, ildv - 1, :] * yshare / 100.0)
                out[:, :, ildv - 1, :] = xgs / f32(100.0)
    return out


def plugin_share(shares: np.ndarray, mfr: np.ndarray) -> float:
    """National plug-in share of new LDV sales. mfr: sales by [region, group, class] (0-based)."""
    sales = shares.astype(f64) * np.moveaxis(mfr.astype(f64), 0, 2)[:, :, None, :]
    tot = sales.sum()
    return float(sales[:, :, [k - 1 for k in PLUG_IN], :].sum() / tot) if tot > 0 else 0.0


def ev_shift(s: dict, n: int, yrs: int, target: float) -> float:
    """The utility shift on plug-ins that gives `target` national plug-in share of new sales."""
    mfr = s["mfr_sales"][R9, 1:MAXGROUP, 1:MAXCLASS, n]
    target = min(max(float(target), 1e-6), 1.0 - 1e-6)
    lo, hi = -30.0, 30.0
    for _ in range(60):
        mid = 0.5 * (lo + hi)
        if plugin_share(_talt2x_shares(s, n, yrs, mid), mfr) < target:
            lo = mid
        else:
            hi = mid
        if hi - lo < 1e-7:
            break
    return 0.5 * (lo + hi)


def talt2x(s: dict) -> None:
    """With s["_ev_share_target"] = {calendar year: share}, the plug-ins' utilities shift so
    their national share of new LDV sales hits the target that year (the EV lever);
    everything downstream (CAFE, stocks, VMT, fuel) follows from the shifted choice."""
    n, yrs = int(s["n"]), int(s["yrs"])
    shr, sales, mfr = s["apshrgrp"], s["ldv_sales"], s["mfr_sales"]
    G, C, L = slice(1, MAXGROUP), slice(1, MAXCLASS), slice(1, MAXLDV)
    shr[G, C, L, 1:MNUMCR, n] = 0.0
    target = (s.get("_ev_share_target") or {}).get(yrs)
    shift = ev_shift(s, n, yrs, target) if target is not None else 0.0
    if target is not None:
        s.setdefault("_ev_shift", {})[yrs] = shift
    shares = _talt2x_shares(s, n, yrs, shift)
    for iregn in range(1, MNUMCR - 1):
        shr[G, C, L, iregn, n] = shares[:, :, :, iregn - 1]
        sales[G, C, L, iregn, n] = shr[G, C, L, iregn, n] * mfr[iregn, G, C, n][:, :, None]
    s.update(iregn=MNUMCR - 1, icl=MAXCLASS + 1, igp=MAXGROUP + 1, ildv=15, ifuelx=17)

    reg = sales[G, C, L, R9, n]
    if np.isnan(reg).any() or (reg < 0.0).any():
        raise ValueError("TDM TALT2X: NaN or negative LDV sales")
    sales[G, C, L, MNUMCR, n] = fsum(reg, axis=3)
    s["cafesales"][G, C, yrs, L] = sales[G, C, L, MNUMCR, n]
    tot = fsum(sales[G, C, L, MNUMCR, n], axis=2)
    with np.errstate(divide="ignore", invalid="ignore"):
        shr[G, C, L, MNUMCR, n] = sales[G, C, L, MNUMCR, n] / tot[:, :, None]
