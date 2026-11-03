"""READAIR (tranair.f): the air module's inputs from trnairx.xlsx, sheet "trnair".

Fills AIRMOD arrays in the state: world population and GDP (the US row from the
macro model), load factors, RPM and FTM shares and history, aircraft capacity, stocks
by status and vintage, survival, yields, efficiency, COVID multipliers and the
regression coefficients; then totals, vintage seat-miles per gallon in the last history
year, and the COVID case for the macro scenario (MMAC).

EIA quirk kept: the stock totals (STK_SUP_TOT, STKPTOT, STKCTOT) assign arrays laid out
(region, year, type) to ones laid out (region, type, year). The shapes do not conform, so
the result is what gfortran's loops give: three year slots filled, the rest zero.
"""

import numpy as np

from nems_open.paths import INPUT
from nems_open.transportation.air_common import DOMINT, MAXACAGE, MAXATYP, MAXWREG, US, A
from nems_open.transportation.common import f32
from nems_open.transportation.readers.getrng import Ranges

BOOK = INPUT / "tdm" / "trnairx.xlsx"
W, T, D, G = slice(1, MAXWREG), slice(1, MAXATYP), slice(1, DOMINT), slice(1, MAXACAGE)
LAST_HIST_INDEX = 2022 - 1989


def readair(s: dict, book=BOOK) -> None:
    a = A(s)
    rng = Ranges(book, "trnair")
    iy, ij = 1995 - 1990 + 1, int(s["ijumpyr"])
    n = ij - iy + 1
    nh = LAST_HIST_INDEX - iy + 1
    Y, H = slice(iy, ij), slice(iy, LAST_HIST_INDEX)
    r = lambda name, arr, idx, ix, iy_, iz=1, kind="r": rng.read(a[arr], idx, name, ix, iy_, iz, kind)  # noqa: E731
    r("WLD_POP", "wld_pop", (W, Y), MAXWREG, n)
    r("WLD_GDP", "wld_gdp", (W, Y), MAXWREG, n)
    r("QAGTR_US", "qagtr_us", (slice(1, 1), Y), 1, n)
    r("LOAD_FACTOR", "load_factor", (W, Y, D), MAXWREG, n, DOMINT)
    r("SHR_FTMD", "shr_ftm", (W, Y, T, 1), MAXWREG, n, MAXATYP)
    r("SHR_FTMI", "shr_ftm", (W, Y, T, 2), MAXWREG, n, MAXATYP)
    r("SHR_RPMD", "shr_rpm", (W, Y, T, 1), MAXWREG, n, MAXATYP)
    r("SHR_RPMI", "shr_rpm", (W, Y, T, 2), MAXWREG, n, MAXATYP)
    r("RPMT_HIST", "rpmt_hist", (W, H, D), MAXWREG, nh, DOMINT)
    r("FTM_HIST", "ftm", (W, H, D), MAXWREG, nh, DOMINT)
    r("FTMAC", "ftmac", (W, Y, T), MAXWREG, n, MAXATYP)
    r("ASMAC", "asmac", (W, Y, T), MAXWREG, n, MAXATYP)
    for k in ("STKPA", "STKPP", "STKCA", "STKCP"):
        r(k, k.lower(), (W, Y, T), MAXWREG, n, MAXATYP)
    for k in ("STKPAVINT", "STKCAVINT", "STKPPVINT", "STKCPVINT"):
        r(k, k.lower(), (W, G, T), MAXWREG, MAXACAGE, MAXATYP)
    r("SURVAC", "survac", (T, G, slice(1, 2)), MAXATYP, MAXACAGE, 2)
    r("STK_SUP_NEW", "stk_sup_new", (W, Y, T), MAXWREG, n, MAXATYP)
    r("MIN_PRK_SHR", "min_prk_shr", (W, T), MAXWREG, MAXATYP)
    r("YIELD", "yield", (D, Y), DOMINT, n)
    from nems_open.fortran_array import FArray
    vint = {k: FArray.zeros([(1, MAXWREG), (1, MAXACAGE), (1, MAXATYP)]) for k in ("d", "i")}
    rng.read(vint["d"], (W, G, T), "GPTMD_PASS_VINT", MAXWREG, MAXACAGE, MAXATYP)
    rng.read(vint["i"], (W, G, T), "GPTMI_PASS_VINT", MAXWREG, MAXACAGE, MAXATYP)
    r("GPTMD_PASS", "gptm", (W, Y, T, 1), MAXWREG, n, MAXATYP)
    r("GPTMI_PASS", "gptm", (W, Y, T, 2), MAXWREG, n, MAXATYP)
    r("PCT_PASS_MTOW", "pct_pass_mtow", (T, Y), MAXATYP, n)
    r("PCT_BELLY_PLOAD", "pct_belly_pload", (T, Y, D), MAXATYP, n, DOMINT)
    r("PCT_BELLY_FRT", "pct_belly_frt", (T, Y, D), MAXATYP, n, DOMINT)
    r("AIR_MGMT_ADJ", "air_mgmt_adj", (W, Y, D), MAXWREG, n, DOMINT)
    r("STK_ALIGN_MULT", "stk_align_mult", (W, slice(31, 37), T), MAXWREG, 7, MAXATYP)
    r("INTERCEPT_RPM", "intercept_rpm", (W, D), MAXWREG, DOMINT)
    r("BETA1_RPM", "beta1_rpm", (W, D), MAXWREG, DOMINT)
    for k in ("COVIDMULT_REF", "COVIDMULT_LOMAC", "COVIDMULT_HIMAC"):
        r(k, k.lower(), (W, slice(30, 41), D), MAXWREG, 12, DOMINT)
    r("INTERCEPT_FTM", "intercept_ftm", (W, D), MAXWREG, DOMINT)
    r("BETA1_FTM", "beta1_ftm", (W, D), MAXWREG, DOMINT)
    for k in ("PASS_WEIGHT", "FUEL_BURN_RED", "ALPHAYD", "RHOYD", "BETAFUELD", "BETATIMED", "ALPHAYI", "RHOYI",
              "BETAFUELI", "BETATIMEI"):
        a[k.lower()] = f32(rng.scalar(k))
    for k in ("MINAGE_PRK_F", "MINAGE_C_PPRK", "MINAGE_C_PACT", "MINAGE_PRK_P", "MAXAGE_UNPRK_P"):
        a[k.lower()] = rng.scalar(k, "i")
    a["max_unprk_shr"] = f32(rng.scalar("MAX_UNPRK_SHR"))

    a["wld_pop"][US, Y] = s["mc_np"][11, Y]
    jp = s["mc_jpgdp"]
    a["wld_gdp"][US, Y] = s["mc_gdpr"][Y] * (jp[26] / jp[23])
    # EIA quirk: the left side is (region, type, year), the right (region, year, type), and
    # nothing checks the shapes. gfortran runs the left side's loops and indexes the right
    # with the same counters, so the right's type index runs past 3, into memory that is
    # zero in the oracle: only three year slots get values, all from 1995-1997 stocks.
    tot = {k: a[k] for k in ("stk_sup_tot", "stkptot", "stkctot")}
    for k in tot.values():
        k[W, T, Y] = 0.0
    st = {k: a[k] for k in ("stkpa", "stkpp", "stkca", "stkcp")}
    for j in range(1, MAXATYP + 1):
        for kk in range(1, min(MAXATYP, n) + 1):
            y = iy + kk - 1
            pa, pp, ca, cp = (st[k][W, iy + j - 1, kk] for k in ("stkpa", "stkpp", "stkca", "stkcp"))
            tot["stk_sup_tot"][W, j, y] = pa + pp + ca + cp
            tot["stkptot"][W, j, y] = pa + pp
            tot["stkctot"][W, j, y] = ca + cp
    pw = a["pass_weight"]
    vi = a["asmpg_vint"]
    for age in range(1, MAXACAGE + 1):
        vi[W, T, age, 1, LAST_HIST_INDEX] = f32(1) / (vint["d"][W, age, T] * pw / f32(2000))
        vi[W, T, age, 2, LAST_HIST_INDEX] = f32(1) / (vint["i"][W, age, T] * pw / f32(2000))
    mmac = int(s["mmac"]) if "mmac" in s else 3
    src = {4: "covidmult_lomac", 5: "covidmult_himac"}.get(mmac, "covidmult_ref")
    a["covid_mult"].a[...] = a[src].a
    a["iage"] = MAXACAGE + 1
