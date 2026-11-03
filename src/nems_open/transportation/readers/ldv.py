"""READLDV (tran.f): the light-duty and passenger-mode inputs from trnldvx.xlsx, sheet "trnldv".

Vehicle classes and groups, CAFE and GHG standards and footprint coefficients, credits,
attribute adjustments, battery and fuel cell costs, IRA and state credits, the choice
model, refuelling stations and chargers, fleets, survival, stock MPG and weight
history, VMT schedules, licensing and travel behaviour, rail, transit, intercity and
commuter rail, buses, boats, lubricants, motorcycles, SEDS/MER/STEO benchmark years,
fuel taxes, the technology table with its market shares and engineering notes, lidar,
and the automated taxi model.

Run switch as in the reference case (TRANEFF 0). Arrays that no ported routine reads are
not in the oracle's dumps; the reader creates them with their declared bounds.
"""

import numpy as np

from nems_open.fortran_array import FArray
from nems_open.transportation.cafe import CARGRP, LTKGRP, MAXCLASS, MAXGROUP
from nems_open.transportation.common import AGEGRP, MAXAGE, MAXHAV, MAXLDV, MAXVTYP, MF, MNUMCR, f32, logf
from nems_open.transportation.readers.getrng import Ranges
from nems_open.transportation.readers.ldv_tables import BASE, GAS, TDM

BOOK = TDM / "trnldvx.xlsx"
MAXTECH, MAXNOTE, MAXCHRG, MAXFUEL, MAXFLEET, MAXNMLM = 71, 53, 3, 8, 4, 13
MAXLIDAR, MAXPRODPHASE = 2, 4
IRAYR, BYR, LYR, MNUMYR = 2023, 1990, 2050, 61
FIRST_READ_YEAR = 1995
ALL = slice(None)

# Module arrays that are not in the dumps: their declared bounds.
DECLARED = {
    **{f"atvcocar{k}": [(1, MAXLDV), (1, MNUMCR - 2), (1, MAXCLASS)] for k in range(1, 6)},
    **{f"atvcotrk{k}": [(1, MAXLDV), (1, MNUMCR - 2), (1, MAXCLASS)] for k in range(1, 7)},
    "atvcoef_calib": [(1, MAXLDV), (1, MAXVTYP)], "cafepefmult": [(1, MAXLDV), (1, MNUMYR)],
    "htfreff": [(1, MNUMYR)], "prt_cnt_nc": [(1, MAXCHRG), (1, MNUMYR), (1, MNUMCR - 2)],
    "surv25": [(1, MNUMCR), (1, MAXAGE), (1, MAXVTYP)], "surv_adj": [(1, MNUMYR)],
    "taxi_rev_params": [(1, MAXHAV), (1, 6)], "trwtcar_hist": [(1, MNUMYR)], "trwttrk_hist": [(1, MNUMYR)],
    "vmt_sched_param": [(1, MAXLDV), (1, 2)],
}
# READLDV's own local arrays.
LOCAL = {
    "vehgroup": ([(1, MAXGROUP * MAXCLASS)], np.int16), "vehclass": ([(1, MAXGROUP * MAXCLASS)], np.int16),
    "vehgrouplabel": ([(1, MAXGROUP * MAXCLASS)], object), "vehclasslabel": ([(1, MAXGROUP * MAXCLASS)], object),
    "vehperfval": ([(1, MAXGROUP * MAXCLASS)], f32), "vehperffac": ([(1, MAXGROUP * MAXCLASS)], f32),
    "vehperfcap": ([(1, MAXGROUP * MAXCLASS)], f32), "vehusedcap": ([(1, MAXGROUP * MAXCLASS)], f32),
    "cafeyear": ([(1, MNUMYR)], np.int16), "cafe_std": ([(1, MAXVTYP), (6, MNUMYR)], f32),
    "tfcoefnrg": ([(1, 4), (1, MNUMYR)], f32), "cfcoefnrg": ([(1, 4), (1, MNUMYR)], f32),
    "tfcoefcafe": ([(1, 8), (1, MNUMYR)], f32), "cfcoefcafe": ([(1, 4), (1, MNUMYR)], f32),
    "tfcoefepa": ([(1, 8), (1, MNUMYR)], f32), "cfcoefepa": ([(1, 4), (1, MNUMYR)], f32),
    "nimhcost": ([(1, MNUMYR)], f32), "lioncost": ([(1, MNUMYR)], f32), "lioncost_phev": ([(1, MNUMYR)], f32),
    "phev_dod_fac": ([(1, MNUMYR)], f32), "ev_dod_fac": ([(1, MNUMYR)], f32),
    "cellmcst": ([(1, MNUMYR)], f32), "cellhcst": ([(1, MNUMYR)], f32),
    **{k: ([(1, MAXCLASS), (1, MNUMYR), (1, MAXVTYP)], f32) for k in ("hevsyscst", "phev20syscst", "phev50syscst", "evsyscst")},
    **{k: ([(1, MAXLDV)], f32) for k in ("packa", "packlr", "mata", "matlr")},
    "techgroup": ([(1, MAXTECH * MAXVTYP)], np.int16), "techid": ([(1, MAXTECH * MAXVTYP)], np.int16),
    "techlabin": ([(1, MAXTECH * MAXVTYP)], object), "techsystem": ([(1, MAXTECH * MAXVTYP)], object),
    **{k: ([(1, MAXTECH * MAXVTYP)], f32) for k in ("techfe", "techcosta", "techcostr", "techwgta", "techwgtr",
                                                    "techhp", "techlearn", "techlrn1", "techlrn2")},
    "techfyr": ([(1, MAXTECH * MAXVTYP)], np.int16), "techapply": ([(1, MAXTECH * MAXVTYP), (1, MAXLDV)], object),
    "mktgroup": ([(1, MAXGROUP * MAXTECH)], np.int16), "mkttech": ([(1, MAXGROUP * MAXTECH)], np.int16),
    "techmktshare": ([(1, MAXGROUP * MAXTECH), (1, MAXCLASS * 2)], f32),
    "engnotetype": ([(1, MAXNOTE)], np.int16), "engnotetech": ([(1, MAXNOTE), (1, 10)], np.int16),
    "engnoteyear": ([(1, MAXNOTE)], np.int16), "engnotepct": ([(1, MAXNOTE)], f32),
}


def _zeros(bounds, dtype):
    if dtype is object:
        shape = tuple(hi - lo + 1 for lo, hi in bounds)
        return FArray(np.full(shape, "", dtype=object), [lo for lo, _ in bounds])
    return FArray.zeros(bounds, dtype)


def _text(arr, idx, value):
    """A CHARACTER*n assignment: blank-padded to the array's length."""
    n = arr.a.dtype.itemsize if arr.a.dtype.kind == "S" else 0
    v = str(value)
    arr[idx] = (v[:n].ljust(n) if n else v).encode("latin-1") if n else v


def readldv(s: dict, traneff: int = 0, book=BOOK) -> None:
    rng = Ranges(book, "trnldv")
    L = {k: _zeros(b, t) for k, (b, t) in LOCAL.items()}
    for k, b in DECLARED.items():
        if k not in s:
            s[k] = FArray.zeros(b)
    if "sys_affect" not in s:                  # CHARACTER*15 SYS_AFFECT(MAXTECH,MAXVTYP)
        s["sys_affect"] = FArray(np.full((MAXTECH, MAXVTYP), b" " * 15, dtype="S15"))
    iy, ij = FIRST_READ_YEAR - 1990 + 1, int(s["ijumpyr"])
    ijcal = ij + 1989
    nread = ij - iy + 1
    Y = slice(iy, ij)
    jp = s["mc_jpgdp"]

    def arr(name):
        return L[name] if name in L else s[name]

    def r(name, var, idx=None, ix=1, iy_=1, iz=1, kind="r"):
        a = arr(var)
        rng.read(a, tuple(ALL for _ in a.a.shape) if idx is None else idx, name, ix, iy_, iz, kind)

    def sc(name, var, kind="r"):
        val = rng.scalar(name, kind)
        cur = s.get(var)
        s[var] = type(cur)(val) if isinstance(cur, np.generic) else (int(val) if kind == "i" else f32(val))

    n_gc = MAXGROUP * MAXCLASS
    r("VEHGROUPLABEL", "vehgrouplabel", None, 1, n_gc, 1, "c")
    r("VEHGROUP", "vehgroup", None, 1, n_gc, 1, "i")
    r("VEHCLASSLABEL", "vehclasslabel", None, 1, n_gc, 1, "c")
    r("VEHCLASS", "vehclass", None, 1, n_gc, 1, "i")
    for k in ("VEHPERFVAL", "VEHPERFFAC", "VEHPERFCAP", "VEHUSEDCAP"):
        r(k, k.lower(), None, 1, n_gc)
    sc("PBACKT", "payback", "i")
    sc("DRATET", "discount")
    sc("FINET", "reg_cost")
    r("CAFEYEAR", "cafeyear", (Y,), nread, 1, 1, "i")
    r("CAFE_STD", "cafe_std", (slice(1, MAXVTYP), Y), MAXVTYP, nread)
    for igp in range(1, MAXGROUP + 1):
        for icl in range(1, MAXCLASS + 1):
            k = (igp - 1) * MAXCLASS + icl
            if icl == 1:
                _text(s["grouplabel"], igp, L["vehgrouplabel"][k])
            _text(s["classlabel"], (icl, igp), L["vehclasslabel"][k])
            s["valueperf"][icl, igp] = L["vehperfval"][k]
            s["perffact"][icl, igp] = L["vehperffac"][k]
            s["perfcap"][icl, igp] = L["vehperfcap"][k]
            s["usedcap"][icl, igp] = L["vehusedcap"][k]
    s["discount"] = s["discount"] * f32(0.01)
    gmap = s["grpmap"]
    for i in range(iy, ij + 1):
        yr = int(L["cafeyear"][i])
        for igp in range(1, MAXGROUP + 1):
            if BYR <= yr <= LYR:
                s["cafe_stand"][igp, yr] = L["cafe_std"][int(gmap[igp]), i]
    r("TFCOEFNRG", "tfcoefnrg", (slice(1, 4), slice(19, ij)), 4, ij - 18)
    r("CFCOEFNRG", "cfcoefnrg", (slice(1, 4), slice(19, ij)), 4, ij - 18)
    r("TFCOEFCAFE", "tfcoefcafe", (slice(1, 8), slice(23, ij)), 8, ij - 22)
    r("CFCOEFCAFE", "cfcoefcafe", (slice(1, 4), slice(23, ij)), 4, ij - 22)
    r("TFCOEFEPA", "tfcoefepa", (slice(1, 8), slice(23, ij)), 8, ij - 22)
    r("CFCOEFEPA", "cfcoefepa", (slice(1, 4), slice(23, ij)), 4, ij - 22)
    r("CAFEPEFMULT", "cafepefmult", (slice(1, MAXLDV), slice(22, ij)), MAXLDV, ij - 21)
    r("EPAALTMULT", "epaaltmult", (slice(1, MAXLDV), slice(22, ij)), MAXLDV, ij - 21)
    r("AC_CO2_OFFSET", "ac_co2_offset", (slice(1, MAXGROUP), slice(23, ij)), MAXGROUP, ij - 22)
    sc("ENFORCE_EPA", "enforce_epa", "i")
    sc("ENFORCE_MY27REGS", "enforce_my27regs", "i")
    sc("ENFORCE_CAFE", "enforce_cafe", "i")
    sc("CREDBAL_EPALYR", "credbal_epalyr")
    r("LDV_VEHLIFEMI", "ldv_vehlifemi", None, 1, MAXVTYP)
    r("AC_OC_CREDIT", "ac_oc_credit", (slice(1, MAXGROUP), Y), MAXGROUP, nread)
    r("PU_CRED_ELIG", "pu_cred_elig", None, 1, MAXGROUP)
    if traneff == 3:
        s["enforce_my27regs"] = type(s["enforce_my27regs"])(0)
    if int(s["enforce_my27regs"]) == 0:
        r("AC_OC_CREDIT_NC", "ac_oc_credit", (slice(1, MAXGROUP), Y), MAXGROUP, nread)
        y26 = 2026 - 1989
        s["ac_co2_offset"][:, y26 + 1:MNUMYR] = s["ac_co2_offset"][:, y26][:, None]
        for i in range(1, 9):
            if i <= 4:
                for k in ("tfcoefnrg", "cfcoefnrg", "cfcoefcafe", "cfcoefepa"):
                    L[k][i, y26 + 1:MNUMYR] = L[k][i, y26]
            for k in ("tfcoefcafe", "tfcoefepa"):
                L[k][i, y26 + 1:MNUMYR] = L[k][i, y26]
    acc = s["ac_oc_credit"].a
    s["ac_oc_credit_expanded"].a[...] = np.broadcast_to(acc[:, None, None, :], s["ac_oc_credit_expanded"].a.shape)
    s["ac_oc_credit_expanded_adj"].a[...] = s["ac_oc_credit_expanded"].a
    for il in (4, 7, 15):
        s["ac_oc_credit_expanded_adj"][1:MAXGROUP, 1:MAXCLASS, il, 1:MNUMYR] = 0.0
    pef = s["cafepefmult"].a
    s["cafepefmult_expanded"].a[...] = np.broadcast_to(pef[None, None, :, :], s["cafepefmult_expanded"].a.shape)
    J19, J23 = slice(19, ij), slice(23, ij)
    for j, c in enumerate("ABCD", start=1):
        s[f"cfcoef{c.lower()}"][J19] = L["cfcoefnrg"][j, J19]
        s[f"tfcoef{c.lower()}"][J19] = L["tfcoefnrg"][j, J19]
        s[f"cfcoef{c.lower()}2"][J23] = L["cfcoefcafe"][j, J23]
        s[f"cfcoefepa{c.lower()}2"][J23] = L["cfcoefepa"][j, J23]
    for j, c in enumerate("ABCDEFGH", start=1):
        s[f"tfcoef{c.lower()}2"][J23] = L["tfcoefcafe"][j, J23]
        s[f"tfcoefepa{c.lower()}2"][J23] = L["tfcoefepa"][j, J23]
    for k in ("COEF_A", "COEF_B", "COEF_C", "COEF_P"):
        r(k, k.lower(), None, MAXCLASS, MAXGROUP)
    for k in ("AFVADJHP", "AFVADJFE", "AFVADJWT", "AFVADJPR"):
        r(k, k.lower(), None, MAXLDV, MAXVTYP)
    gf = (slice(1, MAXLDV), slice(1, MAXCLASS), slice(1, MAXGROUP))
    r("GRPFLAG", "grpflag", gf, MAXLDV, MAXCLASS, MAXGROUP, "i")
    r("SALES_PER_MODEL", "sales_per_model", None, MAXCLASS, MAXGROUP)
    if int(s["enforce_my27regs"]) == 0:
        r("SALES_PER_MDL_NC", "sales_per_model", None, MAXCLASS, MAXGROUP)
        r("GRPFLAG_ALT", "grpflag", gf, MAXLDV, MAXCLASS, MAXGROUP, "i")
        g = s["grpflag"]
        for igp in range(1, MAXGROUP + 1):
            for icl in range(1, MAXCLASS + 1):
                pair = (g[5, icl, igp], g[6, icl, igp])
                if g[16, icl, igp] == 0 and max(pair) > 0:
                    g[16, icl, igp] = min(pair)
    r("NIMHCOST", "nimhcost", (Y,), nread)
    r("LIONCOST", "lioncost", (Y,), nread)
    r("LIONCOST_PHEV", "lioncost_phev", (Y,), nread)
    gbp = s["global_batt_prod"]
    for name, row in (("BATT_DMD_NUSLDV", 1), ("BATT_DMD_NUSNLDV", 2), ("BATT_DMD_CONS", 6)):
        rng.read(gbp, (row, 2, Y), name, nread, 1, 1)
    r("PHEV_DOD_FAC", "phev_dod_fac", (Y,), nread)
    csr = s["csratio"]
    r("CSRATIO", "csratio", None, MAXCLASS, MAXGROUP, csr.a.shape[2])
    r("PCTPHEV20", "pctphev20", (Y,), nread)
    r("PCTPHEV50", "pctphev50", (Y,), nread)
    r("EV_DOD_FAC", "ev_dod_fac", (Y,), nread)
    r("CELLMCST", "cellmcst", (Y,), nread)
    r("CELLHCST", "cellhcst", (Y,), nread)
    for k in ("HEVSYSCST", "PHEV20SYSCST", "PHEV50SYSCST", "EVSYSCST"):
        r(k, k.lower(), (slice(1, MAXCLASS), Y, slice(1, MAXVTYP)), MAXCLASS, nread, MAXVTYP)
    sc("FIRST_BAT_YR", "first_bat_yr", "i")
    for k in ("PACKA", "PACKLR", "MATA", "MATLR"):
        r(k, k.lower(), None, 1, MAXLDV)
    r("MAT_MARKUP", "mat_markup", (slice(33, ij),), ij - 32)
    r("LIONKWH_PERLB", "lionkwh_perlb", None, MAXCLASS, MAXGROUP, MAXLDV)
    r("LION_LB_PERKWH", "lion_lb_perkwh", None, 1, MAXLDV)
    r("EV_RANGE_B", "ev_range_b", None, 1, MAXLDV)
    r("EV_RANGE_M", "ev_range_m", None, 1, MAXLDV)
    fr = FIRST_READ_YEAR
    s["mat_markup"][fr - 1989:2021 - 1989] = 1.0
    s["fuelcell_d_kw"][fr:ijcal, 13] = L["cellmcst"][fr - 1989:ijcal - 1989]
    s["fuelcell_d_kw"][fr:ijcal, 14] = L["cellhcst"][fr - 1989:ijcal - 1989]
    s["nimh_cost"][fr:ijcal] = L["nimhcost"][fr - 1989:ijcal - 1989] / jp[11] * jp[1]
    s["phev_dod"][fr:ijcal] = L["phev_dod_fac"][fr - 1989:ijcal - 1989]
    s["ev_dod"][fr:ijcal] = L["ev_dod_fac"][fr - 1989:ijcal - 1989]
    li, nb = s["li_ion_cost"], s["elecnonbattcst"]
    C, V = slice(1, MAXCLASS), slice(1, MAXVTYP)
    for yr in range(fr, ijcal + 1):
        li[1:MAXLDV, yr] = L["lioncost"][yr - 1989] / jp[31] * jp[1]
        for il in (5, 6, 16):
            li[il, yr] = L["lioncost_phev"][yr - 1989] / jp[31] * jp[1]
        for il, k in ((4, "evsyscst"), (5, "phev20syscst"), (6, "phev50syscst"), (7, "evsyscst"), (15, "evsyscst"),
                      (16, "hevsyscst")):
            nb[C, yr, V, il] = L[k][C, yr - 1989, V] / jp[11] * jp[1]
    ln2 = logf(f32(2.0))
    for il in list(range(4, 9)) + list(range(13, MAXLDV + 1)):
        s["pack_a"][il] = L["packa"][il] / jp[31] * jp[1]
        s["mat_a"][il] = L["mata"][il] / jp[31] * jp[1]
        s["pack_b"][il] = -logf(f32(1.0) - L["packlr"][il]) / ln2
        s["mat_b"][il] = -logf(f32(1.0) - L["matlr"][il]) / ln2
    r("STATE_CRED", "state_cred", (slice(1, MNUMCR - 2), slice(2023, LYR), slice(1, 3)), MNUMCR - 2, LYR - 2023 + 1, 3)
    r("IRA_BAT_SHR", "ira_bat_shr", (slice(1, 2), slice(IRAYR, LYR), slice(1, 2)), 2, LYR - IRAYR + 1, 2)
    r("IRA_VEH_SHR", "ira_veh_shr", (slice(1, 2), slice(IRAYR, LYR), slice(1, 2)), 2, LYR - IRAYR + 1, 2)
    sc("SWITCHLDV_HR1", "switchldv_hr1", "i")
    if traneff == 4:
        s["switchldv_hr1"] = type(s["switchldv_hr1"])(0)
    if int(s["switchldv_hr1"]) == 0:
        s["enforce_cafe"] = type(s["enforce_cafe"])(1)
    r("NMLMCOCAR", "nmlmco", (slice(1, MAXNMLM), slice(1, MAXCLASS), slice(1, CARGRP)), MAXNMLM, MAXCLASS, CARGRP)
    r("NMLMCOTRK", "nmlmco", (slice(1, MAXNMLM), slice(1, MAXCLASS), slice(LTKGRP, MAXGROUP)), MAXNMLM, MAXCLASS, LTKGRP)
    for k in [f"ATVCOCAR{j}" for j in range(1, 6)] + [f"ATVCOTRK{j}" for j in range(1, 7)]:
        r(k, k.lower(), None, MAXLDV, MNUMCR - 2, MAXCLASS)
    r("ATVCOEF_CALIB", "atvcoef_calib", None, MAXLDV, MAXVTYP)
    if "brcost25" in s:
        s["brcost25"][1:MAXGROUP, 1:MAXLDV, 1:MAXCLASS, :] = 0.0
    sc("GAS_PUMP_PER_STA", "gas_pump_per_sta")
    sc("GAS_HRLY_THRUPUT", "gas_hrly_thruput")
    r("INITSTA", "initsta", (slice(1, MAXFUEL), Y, slice(1, MNUMCR - 2)), MAXFUEL, nread, MNUMCR - 2)
    r("STA_RAT", "sta_rat", None, MAXFUEL)
    sc("CHR_STR_YR", "chr_str_yr", "i")
    sc("CHR_LST_YR", "chr_lst_yr", "i")
    sc("ELAS_FAVL", "elas_favl")
    c0, c1 = int(s["chr_str_yr"]), int(s["chr_lst_yr"])
    pidx = (slice(1, MAXCHRG), slice(c0, c1), slice(1, MNUMCR - 2))
    r("PRT_CNT", "prt_cnt", pidx, MAXCHRG, c1 - c0 + 1, MNUMCR - 2)
    r("PRT_CNT_NC", "prt_cnt_nc", pidx, MAXCHRG, c1 - c0 + 1, MNUMCR - 2)
    r("PRT_RT", "prt_rt", None, MAXCHRG)
    r("CHGCSTMULT", "chgcstmult", None, MAXCHRG)
    r("CHG_DIST", "chg_dist", (slice(1, MNUMCR - 2), slice(1, MAXCHRG), 2023 - 1989), MNUMCR - 2, MAXCHRG)
    r("MAINTGRP", "maintgrp", (slice(1, MAXLDV), slice(1, MAXCLASS), slice(1, MAXVTYP)), MAXLDV, MAXCLASS, MAXVTYP)
    if int(s["enforce_my27regs"]) == 0:
        s["prt_cnt"].a[...] = s["prt_cnt_nc"].a
    cd = s["chg_dist"]
    cd[1:MNUMCR - 2, 1:MAXCHRG, 1:2022 - 1989] = cd[1:MNUMCR - 2, 1:MAXCHRG, 2023 - 1989][:, :, None]
    r("FLTTRANSPC", "flttrans", (slice(1, MAXFLEET), slice(1, MAXAGE), 1), MAXFLEET, MAXAGE)
    r("FLTTRANSLT", "flttrans", (slice(1, MAXFLEET), slice(1, MAXAGE), 2), MAXFLEET, MAXAGE)
    r("SURVFLT", "survflt", None, MAXFLEET, MAXAGE, MAXVTYP)
    r("FLTVMTYR", "fltvmtyr", (slice(1, MAXFLEET), Y, slice(1, MAXVTYP)), MAXFLEET, nread, MAXVTYP)
    r("SURV25", "surv25", None, MNUMCR, MAXAGE, MAXVTYP)
    r("SURV_ADJ", "surv_adj", (Y,), nread)
    sv, ss = s["surv25"], s["ssurv25"]
    ss[1:MNUMCR, 1, V] = sv[1:MNUMCR, 1, V]
    ss[1:MNUMCR, 2:MAXAGE, V] = sv[1:MNUMCR, 2:MAXAGE, V] / sv[1:MNUMCR, 1:MAXAGE - 1, V]
    r("CMPGSTKGAS95", "cmpgstkgas95", None, MAXVTYP, MAXAGE)
    r("STKAVGWGT", "stkavgwgt", None, MAXVTYP, MAXAGE)
    r("TRWTCAR_HIST", "trwtcar_hist", (Y,), nread)
    r("TRWTTRK_HIST", "trwttrk_hist", (Y,), nread)
    s["trwtcar_stock"][1:16] = s["trwtcar_hist"][1:16]
    s["trwttrk_stock"][1:16] = s["trwttrk_hist"][1:16]
    r("VMT_SCHED_PARAM", "vmt_sched_param", (slice(1, MAXLDV), slice(1, 2)), MAXLDV, 2)
    R9 = slice(1, MNUMCR - 2)
    for k in ("M_CD_AGE_DIST", "F_CD_AGE_DIST", "M_CD_AGE_DIST_L", "F_CD_AGE_DIST_L", "M_CD_AGE_DIST_H", "F_CD_AGE_DIST_H"):
        r(k, k.lower(), (slice(1, AGEGRP), Y, R9), AGEGRP, nread, MNUMCR - 2)
    for k in ("AGE_ADJ", "AGE_ADJ_L", "AGE_ADJ_H"):
        r(k, k.lower(), (slice(1, MF), slice(30, 61)), MF, 32)
    for k in ("BETACOST", "BETAINC", "BETAVMT", "BETAVPLD", "BETAEMP", "ALPHA"):
        r(k, k.lower(), None, MF, AGEGRP)
    r("LICRATE_M", "licrate_m", (slice(1, AGEGRP), Y, R9), AGEGRP, nread, MNUMCR - 2)
    r("LICRATE_F", "licrate_f", (slice(1, AGEGRP), Y, R9), AGEGRP, nread, MNUMCR - 2)
    r("LIC_TREND", "lic_trend", None, AGEGRP, MF, MNUMCR - 2)
    r("LIC_MAX", "lic_max", None, AGEGRP, MF, MNUMCR - 2)
    r("LIC_ELAS", "lic_elas", None, MNUMCR - 2, AGEGRP)
    sc("LICRHISTYR", "licrhistyr", "i")
    r("VMTLD", "vmtld", (slice(1, AGEGRP), Y, slice(1, MF)), AGEGRP, nread, MF)
    sc("VMTLDHISTYR", "vmtldhistyr", "i")
    r("RAIL_FUEL", "rail_fuel", None, 4)
    r("LNG_MAXPEN", "lng_maxpen", None, 1, 40)
    r("LOCOM_LIFE", "locom_life", None, 1, 30)
    sc("NGYEAR", "ngyear", "i")
    for k in ("CIDISCOUNT", "LOCOMBTU", "DISCRT"):
        sc(k, k.lower())
    sc("PAYBK", "paybk", "i")
    sc("RLNG_INCCOST", "rlng_inccost")
    sc("RLNG_LEARN", "rlng_learn")
    sc("RAILHISTYR", "railhistyr", "i")
    rh = int(s["railhistyr"])
    for k in ("RHIST_NCTONMI", "RHIST_CTONMI"):
        r(k, k.lower(), (slice(iy, rh), R9), rh - iy + 1, MNUMCR - 2)
    r("RTM_SHARES", "rtm_shares", (R9, slice(1, 16)), MNUMCR - 2, 16)
    r("FREFF", "freff", (Y,), nread)
    r("HTFREFF", "htfreff", (Y,), nread)
    r("MFDH", "mfdh", (slice(1, 4), Y), 4, nread)
    sc("MILTHISTYR", "milthistyr", "i")
    r("MILTRSHR90", "miltrshr90", None, 4, MNUMCR - 2)
    sc("TRHISTYEAR", "trhistyear", "i")
    r("TR_COEF", "tr_coef", (R9, slice(1, 4)), MNUMCR - 2, 4)
    for k in ("TRCOVID", "TRRPMHIST", "TREFFHIST", "TREDHIST"):
        r(k, k.lower(), (R9, Y), MNUMCR - 2, nread)
    r("TR_CAV_ADJ", "tr_cav_adj", (Y,), nread)
    sc("CRHISTYEAR", "crhistyear", "i")
    r("CR_COEF", "cr_coef", (R9, slice(1, 4)), MNUMCR - 2, 4)
    r("CRCOVID", "crcovid", (R9, Y), MNUMCR - 2, nread)
    r("CREDDSHR", "creddshr", None, MNUMCR - 2)
    for k in ("CRRPMHIST", "CREFFHIST", "CREDDHIST", "CREDEHIST"):
        r(k, k.lower(), (R9, Y), MNUMCR - 2, nread)
    r("CR_CAV_ADJ", "cr_cav_adj", (Y,), nread)
    sc("IRHISTYEAR", "irhistyear", "i")
    for k in ("IRRPMHIST", "IREDDHIST", "IREDEHIST"):
        r(k, k.lower(), (Y,), nread)
    r("IRREGSHR", "irregshr", None, MNUMCR - 2)
    r("RECFDH", "recfdh", (slice(1, 2), Y), 2, nread)
    sc("RBHISTYR", "rbhistyr", "i")
    r("RBBOAT_COEF", "rbboat_coef", None, 2)
    r("RBMG_COEF", "rbmg_coef", None, 2)
    sc("RBDS_COEF", "rbds_coef")
    r("LUBFDH", "lubfdh", (Y,), nread)
    sc("LUBHISTYR", "lubhistyr", "i")
    r("CYC_RPM", "cyc_rpm", (Y,), nread)
    r("CYC_MPG", "cyc_mpg", (Y,), nread)
    sc("CYCHISTYR", "cychistyr", "i")
    r("TBPMTHIST", "tbpmthist", (R9, Y), MNUMCR - 2, nread)
    r("TBCOVID", "tbcovid", (R9, Y), MNUMCR - 2, nread)
    r("TB_COEF", "tb_coef", (R9, slice(1, 4)), MNUMCR - 2, 4)
    sc("TBHISTYEAR", "tbhistyear", "i")
    r("TBPMTPC08", "tbpmtpc08", None, 9)
    r("TBBTUPMHIST", "tbbtupmhist", (R9, Y), MNUMCR - 2, nread)
    r("TBSYSEFF", "tbsyseff", None, 9)
    r("TB_CAV_ADJ", "tb_cav_adj", (Y,), nread)
    r("TBFSHRHIST", "tbfshrhist", (slice(1, 8), Y, R9), 8, nread, MNUMCR - 2)
    r("TMODINIT", "tmodinit", (slice(1, 2), Y), 2, nread)
    r("TMCOVID", "tmcovid", (slice(1, 2), Y), 2, nread)
    r("TMEFFINIT", "tmeffinit", (slice(1, 2), Y), 2, nread)
    r("QMODFSHRH", "qmodfshrh", (slice(1, 8), Y, slice(1, 2)), 8, nread, 2)
    r("SCHBUS_SHR", "schbus_shr", None, MNUMCR - 2)
    r("EFF_ADJ", "eff_adj", None, 8)
    r("SCHBUS_EV_SHR", "schbus_ev_shr", (R9, Y), MNUMCR - 2, nread)
    r("SBCOEFF", "sbcoeff", None, 2)
    sc("IBSBHISTYEAR", "ibsbhistyear", "i")
    r("IBCOEFF", "ibcoeff", None, 2)
    r("LTSPLIT", "ltsplit", (Y,), nread)
    r("DUMM", "dumm", (Y,), nread)
    for k in ("CCONSTANT", "CRHO", "CINC", "CFUEL", "CHP", "CWGT", "CMPG", "CDUMM",
              "TCONSTANT", "TRHO", "TINC", "TFUEL", "THP", "TWGT", "TMPG", "TDUMM"):
        r(k, k.lower(), None, MNUMCR - 2)
    if traneff == 3:
        r("TBFSHRHISTNC", "tbfshrhist", (slice(1, 8), Y, R9), 8, nread, MNUMCR - 2)
        r("SCHBUS_EV_SHRNC", "schbus_ev_shr", (R9, Y), MNUMCR - 2, nread)
    r("MER_TRAN", "mer_tran", None, 4)
    sc("YMER", "ymer", "i")
    sc("YSTEO", "ysteo", "i")
    r("FUELTAX", "fueltax", (Y,), nread)
    _technologies(s, L, r, jp)
    _lidar_and_taxis(s, r, sc, jp, nread)


def _technologies(s, L, r, jp):
    nt = MAXTECH * MAXVTYP
    for k in ("TECHGROUP", "TECHID"):
        r(k, k.lower(), None, 1, nt, 1, "i")
    r("TECHLABIN", "techlabin", None, 1, nt, 1, "c")
    r("TECHSYSTEM", "techsystem", None, 1, nt, 1, "c")
    for k in ("TECHFE", "TECHCOSTA", "TECHCOSTR", "TECHWGTA", "TECHWGTR"):
        r(k, k.lower(), None, 1, nt)
    r("TECHFYR", "techfyr", None, 1, nt, 1, "i")
    for k in ("TECHHP", "TECHLEARN", "TECHLRN1", "TECHLRN2"):
        r(k, k.lower(), None, 1, nt)
    r("TECHAPPLY", "techapply", None, nt, MAXLDV, 1, "c")
    frst = np.zeros((MAXTECH + 1, MAXVTYP + 1), dtype=np.int16)
    numtech = 0
    for iv in range(1, MAXVTYP + 1):
        last = 0
        for it in range(1, MAXTECH + 1):
            k = (iv - 1) * MAXTECH + it
            tid = int(L["techid"][k])
            if tid == 0:
                continue
            last = tid
            _text(s["techlabel"], (tid, iv), L["techlabin"][k])
            _text(s["sys_affect"], (tid, iv), L["techsystem"][k])
            s["del_fe"][tid, iv] = L["techfe"][k] * f32(0.01)
            s["del_costabs"][tid, iv] = L["techcosta"][k] / jp[32] * jp[1]
            s["del_costwgt"][tid, iv] = L["techcostr"][k] / jp[32] * jp[1]
            s["del_wgtabs"][tid, iv] = L["techwgta"][k]
            s["del_wgtwgt"][tid, iv] = L["techwgtr"][k] * f32(0.01)
            frst[tid, iv] = L["techfyr"][k]
            s["del_hp"][tid, iv] = L["techhp"][k] * f32(0.01)
            s["coeff_learn"][tid, iv] = L["techlearn"][k]
            s["coeff_lrn1"][tid, iv] = L["techlrn1"][k]
            s["coeff_lrn2"][tid, iv] = L["techlrn2"][k]
            for il in range(1, MAXLDV + 1):
                s["tech_applic"][tid, iv, il] = str(L["techapply"][k, il]).strip().upper() == "YES"
        if iv == 1:
            numtech = last
    s["numtech"] = type(s["numtech"])(numtech)
    gmap = s["grpmap"]
    for it in range(1, numtech + 1):
        for g in range(1, MAXGROUP + 1):
            s["frstyear"][it, g] = frst[it, int(gmap[g])]
    r("MKTGROUP", "mktgroup", None, 1, MAXGROUP * MAXTECH, 1, "i")
    r("MKTTECH", "mkttech", None, 1, MAXGROUP * MAXTECH, 1, "i")
    r("TECHMKTSHARE", "techmktshare", None, MAXGROUP * MAXTECH, MAXCLASS * 2)
    pen, mx = s["mkt_pen"], s["mkt_max"]
    share = L["techmktshare"]
    for g in range(1, MAXGROUP + 1):
        for it in range(1, numtech + 1):
            k = (g - 1) * MAXTECH + it
            for icl in range(1, MAXCLASS + 1):
                pen[g, icl, it, BASE, GAS] = share[k, 2 * icl - 1] * f32(0.01)
                mx[icl, g, it, GAS] = share[k, 2 * icl] * f32(0.01)
    r("ENGNOTETYPE", "engnotetype", None, 1, MAXNOTE, 1, "i")
    eng = L["engnotetech"]
    for j, name in ((1, "ENGNOTETECH01"), (2, "ENGNOTETECH02")):
        r(name, "engnotetech", (slice(1, MAXNOTE), j), 1, MAXNOTE, 1, "i")
    r("ENGNOTEYEAR", "engnoteyear", None, 1, MAXNOTE, 1, "i")
    r("ENGNOTEPCT", "engnotepct", None, 1, MAXNOTE)
    for j in range(3, 11):
        r(f"ENGNOTETECH{j:02d}", "engnotetech", (slice(1, MAXNOTE), j), 1, MAXNOTE, 1, "i")
    typ, yr, pct = L["engnotetype"], L["engnoteyear"], L["engnotepct"]
    sup, cnt, req, syn, sdel = s["supersedes"], s["tech_cnt"], s["requires"], s["synergy"], s["synr_del"]
    myr, msh, mor = s["mandyear"], s["mandmksh"], s["mand_oride"]
    ns = nr = ny = nm = 0
    for i in range(1, MAXNOTE + 1):
        t = int(typ[i])
        if t == 0:
            continue
        if t == 1:
            ns += 1
            sup[1, ns], sup[2, ns] = eng[i, 1], eng[i, 2]
            cnt[ns] = 2
            for j in range(3, 11):
                if eng[i, j] == 0:
                    continue
                cnt[ns] = cnt[ns] + 1
                sup[int(cnt[ns]), ns] = eng[i, j]
        elif t == 2:
            nr += 1
            req[1, nr], req[2, nr] = eng[i, 1], eng[i, 2]
        elif t == 3:
            ny += 1
            syn[1, ny], syn[2, ny] = eng[i, 1], eng[i, 2]
            sdel[ny] = pct[i] * f32(0.01)
        else:
            nm += 1
            sign = -1 if eng[i, 2] < 0 else 1
            mor[nm] = eng[i, 2] < 0
            myr[1, nm], myr[2, nm], myr[3, nm] = eng[i, 1], yr[i], eng[i, 2] * sign
            msh[nm] = pct[i] * f32(0.01)
    for k, val in (("num_sup", ns), ("num_req", nr), ("num_syn", ny), ("num_man", nm)):
        s[k] = type(s[k])(val) if k in s else val
    req.a[...] = 0
    mor.a[...] = False


def _lidar_and_taxis(s, r, sc, jp, nread):
    P, Lr = slice(1, MAXPRODPHASE), slice(1, MAXLIDAR)
    r("LIDAR_PROD_THRSH", "lidar_prod_thrsh", (P, Lr), MAXPRODPHASE, 1, MAXLIDAR)
    r("LIDAR_COEF_A", "lidar_coef_a", (P, Lr), MAXPRODPHASE, 1, MAXLIDAR)
    r("LIDAR_COEF_B", "lidar_coef_b", (P, Lr), MAXPRODPHASE, 1, MAXLIDAR)
    r("FIRST_LIDAR_YEAR", "first_lidar_year", None, 1, MAXLIDAR, 1, "i")
    r("LIDAR_RND_PROD", "lidar_rnd_prod", (Lr, slice(FIRST_READ_YEAR, LYR)), MAXLIDAR, nread)
    s["lidar_coef_a"].a[...] = s["lidar_coef_a"].a / jp[26] * jp[1]
    H1 = slice(1, MAXHAV - 1)
    r("HAV_LIDAR_MAP", "hav_lidar_map", None, 1, MAXHAV - 1, 1, "i")
    r("HAV_SYS_LRN", "hav_sys_lrn", (H1, slice(FIRST_READ_YEAR, LYR)), MAXHAV - 1, nread)
    r("HAV_BATTERY_KWH", "hav_battery_kwh", None, MAXHAV - 1)
    r("HAV_TECHMAP", "hav_techmap", None, MAXHAV - 1)
    r("TAXI_REV_PARAMS", "taxi_rev_params", None, MAXHAV, 6)
    p = s["taxi_rev_params"]
    H = slice(1, MAXHAV)
    s["taxi_mi_life"][H] = p[H, 1]
    s["taxi_idle_gph"][H] = p[H, 2]
    for k, col in (("taxi_maint_cost", 3), ("taxi_data_fee", 4), ("taxi_insur", 5)):
        s[k][H] = p[H, col] / jp[26] * jp[1]
    for k in ("TAXI_MI_ANN", "TAXI_SHIFTS", "TAXI_IDLE_HRS", "TAXI_LIVE_FRAC", "TAXI_MAINT_MI", "TAXI_REV_PERMI",
              "HAV_OPER_LIMIT"):
        r(k, k.lower(), None, MNUMCR - 2, MAXHAV)
    for k in ("taxi_rev_permi", "taxi_maint_mi"):
        s[k].a[...] = s[k].a / jp[26] * jp[1]
    sc("TAXI_DISC_R", "taxi_disc_r")
    sc("TAXI_SALARY", "taxi_salary")
    r("HAV_NEWTECH_LIM", "hav_newtech_lim", None, MAXHAV)
    for k in ("TAXI_REV_COEF", "TAXI_NEWTECH_PD", "TAXI_NEWTECH_R"):
        sc(k, k.lower())
    sc("HAV_NEWTECH_LAG", "hav_newtech_lag", "i")
    s["taxi_salary"] = s["taxi_salary"] / jp[26] * jp[1]
    r("HAV_MPGDEG", "hav_mpgdeg", (H, slice(FIRST_READ_YEAR, LYR)), MAXHAV, nread)
