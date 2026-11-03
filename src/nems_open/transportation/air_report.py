"""TAREPORT (tranair.f) and the TRANAIR driver.

TAREPORT copies air results into the report arrays: AIROUT rows by world region,
the travel table (TRTRAVLD), seat-mile demand, and new and stock aircraft efficiency.
TRANAIR sets the year and history constants, then runs TAIRT, TAIREFF and TAREPORT
(READAIR's file reads happen once, before the first year, and are not ported).
"""

from nems_open.transportation import air_demand, air_stock
from nems_open.transportation.air_common import DOM, INT, US, A
from nems_open.transportation.common import f32, fsum

K = f32(1000.0)


def tareport(s: dict) -> None:
    a = A(s)
    n = a.i("n")
    out = a["airout"]
    rpmt, ftm, smd, asmd = a["rpmt"], a["ftm"], a["smdemd"], a["asmdemd"]
    sup, suptot, pa, pp, ctot = a["stk_sup"], a["stk_sup_tot"], a["stkpa"], a["stkpp"], a["stkctot"]
    out[1, n] = a["pjftr"][11, n]
    out[2, n] = a["load_factor"][US, n, DOM]
    out[3, n] = a["load_factor"][US, n, INT]
    for j in range(16):
        w = j + 1
        out[4 + j, n] = rpmt[w, DOM, n] / K
        out[5 + 15 + j, n] = rpmt[w, INT, n] / K
        out[39 + j, n] = fsum(ftm[w, n, :]) / K
        out[58 + 4 * j, n] = smd[w, n] / K
        for t in (1, 2, 3):
            out[58 + t + 4 * j, n] = asmd[w, t, n] / K
        out[126 + 4 * j, n] = sup[w, 1, 1, n] + sup[w, 2, 1, n] + sup[w, 3, 1, n]
        out[194 + 4 * j, n] = suptot[w, 1, n] + suptot[w, 2, n] + suptot[w, 3, n]
        out[262 + 4 * j, n] = pa[w, n, 1] + pa[w, n, 2] + pa[w, n, 3]
        out[330 + 4 * j, n] = pp[w, n, 1] + pp[w, n, 2] + pp[w, n, 3]
        for t in (1, 2, 3):
            out[126 + t + 4 * j, n] = sup[w, t, 1, n]
            out[194 + t + 4 * j, n] = suptot[w, t, n]
            out[262 + t + 4 * j, n] = pa[w, n, t]
            out[330 + t + 4 * j, n] = pp[w, n, t]
        out[398 + j, n] = fsum(ctot[w, :, n])
        out[415 + j, n] = a["qjetr_nus"][w, n]
    out[36, n] = fsum(rpmt[:, DOM, n]) / K
    out[37, n] = fsum(rpmt[:, INT, n]) / K
    out[38, n] = fsum(rpmt[:, :, n]) / K
    out[55, n] = fsum(ftm[:, n, DOM]) / K
    out[56, n] = fsum(ftm[:, n, INT]) / K
    out[57, n] = fsum(ftm[:, n, :]) / K
    out[122, n] = fsum(smd[:, n]) / K
    for t in (1, 2, 3):
        out[122 + t, n] = fsum(asmd[:, t, n]) / K
    out[190, n] = fsum(sup[:, :, 1, n])
    out[258, n] = fsum(suptot[:, :, n])
    out[326, n] = fsum(pa[:, n, :])
    out[394, n] = fsum(pp[:, n, :])
    for t in (1, 2, 3):
        out[190 + t, n] = fsum(sup[:, t, 1, n])
        out[258 + t, n] = fsum(suptot[:, t, n])
        out[326 + t, n] = fsum(pa[:, n, t])
        out[394 + t, n] = fsum(pp[:, n, t])
    out[414, n] = fsum(ctot[:, :, n])

    tr = a["trtravld"]
    tr[3, n] = a["lfdomavg"][n]
    tr[4, n] = rpmt[US, INT, n] / K
    tr[5, n] = a["lfintavg"][n]
    tr[6, n] = fsum(ftm[1, n, :]) / K
    tr[7, n] = a["wld_gdp"][1, n]
    tr[8, n] = a["mc_xgr"][n]
    tr[9, n] = a["yield"][1, n]
    tr[10, n] = a["mc_ypdr"][11, n]
    tr[11, n] = a["pjftr"][11, n]
    a["trstmdem"][1, n] = smd[1, n] / K
    for t in (1, 2, 3):
        a["traireffn"][t, n] = a["asmpg_new_typ"][t, n]
        a["traireffs"][t, n] = a["asmpg_stk_typ"][t, n]
    a["traireffn"][4, n] = a["asmpgt"][1, n]
    a["traireffs"][4, n] = a["asmpgt"][2, n]


def tranair(s: dict, carry: dict) -> None:
    """TRANAIR after the first call (READAIR done). carry: TAIRT's pjftr_us."""
    a = A(s)
    first_read, first_fcst = 1995, 2023
    n = a.i("curiyr")
    s.update({a.key("first_read_year"): first_read, a.key("iy"): first_read - 1990 + 1,
              a.key("first_fcst_yr"): first_fcst, a.key("last_hist_yr"): first_fcst - 1,
              a.key("first_fcst_index"): first_fcst - 1989, a.key("last_hist_index"): first_fcst - 1 - 1989,
              a.key("n"): n, a.key("yrs"): n + 1989,
              a.key("num_to_read"): a.i("ijumpyr") - (first_read - 1990)})
    air_demand.tairt(s, carry)
    air_stock.taireff(s)
    tareport(s)
