"""CFREAD (tranfrt.f): the freight truck, rail and ship inputs, read on the first call.

Two CSV tables (stock fuel economy by class, fuel and vintage; base technology shares)
and four sheets of trnhdvx.xlsx: "trnhdv" (fleet shares, VMT schedules, survival,
history, commercial light trucks, marine), "tech_adopt" (powertrain choice), "ACT"
(Advanced Clean Trucks) and "Phase_2" (GHG standards and technologies). Then the
derived tables: VMT per truck by class, survival for every fuel, maintenance and repair
costs, component costs and learning, charging efficiency, and the technology notes.

Run switches as in the reference case (TRANEFF 0, LEGIRA 1).
EIA quirks kept:
- The REQUIRES note loop tests TECH_SUP for the second and third technologies, not TECH_REQ.
- SURV_ND is read into fuel 2 and then again into every fuel from 2 on.
"""

import numpy as np

from nems_open.paths import INPUT
from nems_open.transportation.common import MNUMCR, f32, logf, powf
from nems_open.transportation.frt_common import AGE, CAFE14, CAFE19, FUEL12, SC4, V
from nems_open.transportation.readers.getrng import Ranges

TDM = INPUT / "tdm"
BOOK = TDM / "trnhdvx.xlsx"
TECHP2, PBK_YR, NVMT, VOC, SEC = 83, 7, 11, 2, 18
BSYR_STK, BSYR_VMT = 2024, 34
FLT, NFT = 2, 1
ALL = slice(None)


def _csv_rows(path):
    """The data rows of an EIA CSV input (one header line), as lists of numbers."""
    with open(path, encoding="latin-1") as f:
        next(f)
        return [[float(x) for x in line.replace(",", " ").split()] for line in f if line.strip()]


def _whole(arr):
    return tuple(ALL for _ in arr.a.shape) if arr.a.ndim else ()


class _Reader:
    def __init__(self, s, sheet, book=BOOK):
        self.v = V(s, angtdm=False)
        self.rng = Ranges(book, sheet)

    def r(self, name, var, idx=None, ix=1, iy=1, iz=1, kind="r"):
        arr = self.v[var]
        if not hasattr(arr, "a"):                          # a scalar variable
            val = self.rng.scalar(name, kind)
            self.v[var] = type(arr)(val) if not isinstance(arr, (int, float)) else val
            return
        self.rng.read(arr, _whole(arr) if idx is None else idx, name, ix, iy, iz, kind)

    def scalar(self, name, var, kind="r"):
        cur = self.v[var]
        val = self.rng.scalar(name, kind)
        self.v[var] = type(cur)(val) if isinstance(cur, np.generic) else (int(val) if kind == "i" else f32(val))


def cfread(s: dict, traneff: int = 0, legira: int = 1, tdm=TDM) -> None:
    v = V(s, angtdm=False)
    iy, ij = 1995 - 1990 + 1, int(s["ijumpyr"])
    nread = ij - iy + 1
    bs = BSYR_STK - 1989
    jp = s["mc_jpgdp"]

    # Stock MPG by size class, fuel and vintage, 1995 to the stock base year.
    hdv = v["hdv_mpg"]
    for row in _csv_rows(tdm / "trnhdv_bmpgstk.csv"):
        sc, f, a = int(row[0]), int(row[1]), int(row[2])
        hdv[iy:bs, sc, a, f] = np.array(row[3:3 + bs - iy + 1], dtype=f32)
    clt = v["cltmpg_yr"]
    clt[iy:bs, 2, 1:AGE] = hdv[iy:bs, 4, 1:AGE, 1]
    clt[iy:bs, 1, 1:AGE] = hdv[iy:bs, 4, 1:AGE, 2]
    for f in range(3, 7):
        clt[iy:bs, f, 1:AGE] = hdv[iy:bs, 4, 1:AGE, f]
    base = v["techbase_p2"]
    for row in _csv_rows(tdm / "trnhdv_techbase_p2.csv"):
        base[int(row[1]), 1:CAFE19, int(row[0])] = np.array(row[2:2 + CAFE19], dtype=f32)

    x = _Reader(s, "trnhdv")
    r = x.r
    r("FLTSHR_SALES", "fltshr_sales", (slice(iy, bs), slice(1, CAFE19)), BSYR_STK - 1995 + 1, CAFE19)
    r("FLTSHR_STK", "fltshr_stk", (slice(iy, bs), slice(1, CAFE19)), BSYR_STK - 1995 + 1, CAFE19)
    for k in ("fltshr_sales", "fltshr_stk"):
        a = v[k]
        a[bs + 1:61, :] = a[bs, :][None, :]
    r("FRT_LOAD_FACT", "frt_load_fact", None, 1, 3)
    vmt = {}
    from nems_open.fortran_array import FArray
    for k in ("VMTCLS2b", "VMTCLS2bV", "VMTCLS3V", "VMTCLS46V", "VMTCLS78V", "VMTCLS78"):
        vmt[k] = FArray.zeros([(1, AGE), (1, 4)])
        x.rng.read(vmt[k], (ALL, ALL), k, AGE, 4, 1)
    ann, a19 = v["annvmt"], v["annvmt_19"]
    A4 = slice(1, 4)
    for ivoc in range(1, VOC + 1):
        ann[1, 1:AGE, A4, ivoc] = vmt["VMTCLS3V"].a
        ann[2, 1:AGE, A4, ivoc] = vmt["VMTCLS46V"].a
    ann[3, 1:AGE, A4, 1] = vmt["VMTCLS78"].a
    ann[3, 1:AGE, A4, 2] = vmt["VMTCLS78V"].a
    ann[4, 1:AGE, A4, 1] = vmt["VMTCLS2b"].a
    ann[4, 1:AGE, A4, 2] = vmt["VMTCLS2bV"].a
    for isc in range(1, SC4 + 1):
        for f in range(5, FUEL12 + 1):
            ann[isc, 1:AGE, f, 1:VOC] = ann[isc, 1:AGE, 2, 1:VOC]
            if isc == 3 and f >= 6:
                ann[isc, 1:AGE, f, 1:VOC] = ann[isc, 1:AGE, 1, 1:VOC]
    # (class 19 group, size class, vocational) for each of the 19 classes
    src = [None, (4, 1), (4, 2), (1, 1), (1, 2), (2, 2), (2, 2), (2, 2), (3, 2), (3, 1), (3, 1), (3, 1), (3, 2),
           (3, 1), (3, 1), (3, 1), (3, 1), (3, 1), (3, 1), (3, 2)]
    for c in range(1, CAFE19 + 1):
        isc, ivoc = src[c]
        a19[1:bs, c, 1:AGE, 1:FUEL12] = ann[isc, 1:AGE, 1:FUEL12, ivoc][None, :, :]
    surv = v["surv_rate"]
    r("SURV_D", "surv_rate", (slice(1, AGE), slice(1, 9), slice(1, 11), 1), AGE, MNUMCR - 2, 11)
    r("SURV_ND", "surv_rate", (slice(1, AGE), slice(1, 9), slice(1, 11), 2), AGE, MNUMCR - 2, 11)
    for i in range(2, FUEL12 + 1):
        r("SURV_ND", "surv_rate", (slice(1, AGE), slice(1, 9), slice(1, 11), i), AGE, MNUMCR - 2, 11)
    del surv
    r("TFFXGRT", "tffxgrt", None, AGE, SC4)
    r("THIST_VMT", "thist_vmt", (slice(6, BSYR_VMT), slice(1, 9)), BSYR_VMT - 6 + 1, MNUMCR - 2)
    r("TTONMI_ORIG", "ttonmi_orig", (slice(1, 9), slice(1, 16)), MNUMCR - 2, SEC - 2)
    r("CLTVMTDIST", "cltvmtdist", None, 1, 6)
    r("CLTSALESPER", "cltsalesper", (slice(1, 6), slice(6, 22)), 6, 17)
    r("CLTVMT_H", "cltvmtt", (slice(1, 6), slice(6, 22)), 6, 17)
    veh, lts = s["mc_vehicles"], s["ltsplit"]
    for f in range(1, 7):
        s["cltsalt"][f, 6:22] = (veh[1, 6:22] + veh[2, 6:22]) * (f32(1) - lts[6:22]) * v["cltsalesper"][f, 6:22] * f32(1000000.)
    Y = slice(iy, ij)
    r("DOMSHIP_FUEL_SHR", "domship_fuel_shr", (slice(1, 4), Y), 4, nread)
    r("INTSHIP_FUEL_SHR", "intship_fuel_shr", (slice(1, 5), Y), 5, nread)
    r("INTSHIPLOGIT_FAC", "intshiplogit_fac", (slice(1, 5), slice(1, 3)), 5, 3)
    r("LSFORISK", "lsforisk", (Y,), nread, 1)
    x.scalar("SHIPHISTYR", "shiphistyr", "i")
    sh = v.i("shiphistyr")
    r("DSHIST_TONMI", "dshist_tonmi", (slice(iy, sh), slice(1, 9)), sh - iy + 1, MNUMCR - 2)
    r("DTM_SHARES", "dtm_shares", (slice(1, 9), slice(1, 16)), MNUMCR - 2, SEC - 2)
    for k in ("ANN_DECLINE", "DSEFF", "HTDSEFF", "Q_SHIPBUNKDS"):
        r(k, k.lower(), (Y,), nread, 1)
    r("FUELCONS", "fuelcons", None, MNUMCR - 2, 9)
    r("FLEETTO", "fleetto", None, 1, 9)
    r("EFFINC", "effinc", None, 1, 9)
    x.scalar("TOONYEAR", "toonyear", "i")
    ty = v.i("toonyear")
    r("TOONSHR", "toonshr", (slice(ty - 1, 61),), 1, 61 - ty + 2)

    x = _Reader(s, "tech_adopt")
    r = x.r
    r("PRAFDFXG", "prafdfxg", None, SC4, FUEL12)
    r("CYAFVXGF", "cyafvxg", (ALL, ALL, FLT), SC4, FUEL12, 1, "i")
    r("CYAFVXGN", "cyafvxg", (ALL, ALL, NFT), SC4, FUEL12, 1, "i")
    r("TRGSHXGF", "trgshxg", (ALL, ALL, FLT), CAFE19, FUEL12, 1, "i")
    r("TRGSHXGN", "trgshxg", (ALL, ALL, NFT), CAFE19, FUEL12, 1, "i")
    for k, fl in (("BFSHXGF", FLT), ("BFSHXGN", NFT)):
        r(k, "bfshxg", (ALL, ALL, fl), SC4, FUEL12)
    for k, fl in (("EFSHXGF", FLT), ("EFSHXGN", NFT)):
        r(k, "efshxg", (ALL, ALL, fl), SC4, FUEL12)
    if traneff == 3:
        v["cyafvxg"].a[...] += 5
    r("CSTDXG", "cstdxg", None, SC4, FLT)
    r("CSTDVXG", "cstdvxg", None, SC4, FLT)
    r("PAYBACK_SHR", "pback_shr", None, PBK_YR, CAFE19)
    for c in range(1, CAFE19 + 1):
        tag = "2" if c <= 2 else "3" if c <= 4 else "46" if c <= 7 else "78V" if c in (8, 12) else "78"
        r(f"VMT_VEH_{tag}", "vmt_veh", (slice(1, NVMT), slice(1, 2), c), 11, FLT)
        r(f"VEH_SHR_{tag}", "veh_shr", (slice(1, NVMT), slice(1, 2), c), 11, FLT)
    v["icafe19"] = CAFE19 + 1
    for k in ("ANN_UPTIME_DAYS", "MAX_DROP", "MAX_RISE", "EVSE_MAINT", "INSURE_RATE", "MR_MGMULT", "H2_REFUEL_TIME",
              "REFUEL_TIMEVAL", "USABLE_H2", "TRK_BEV_DOD", "MIN_REQ_RNG", "DEF_DOSE", "DEF_DOSE_LONOX",
              "EVSE_30CTAXCRED"):
        x.scalar(k, k.lower())
    r("SALES_TAX_RATE", "sales_tax_rate", None, 1, 9)
    r("FET_RATE", "fet_rate", None, 1, CAFE19)
    r("PT_EMOTORKW", "pt_emotorkw", None, CAFE19, FUEL12)
    r("PT_BATTKWH_HEV", "pt_battkwh_hev", None, 1, CAFE19)
    for k in ("PT_TANKSIZE_CNG", "PT_BATTKWH_FCEV", "PT_FCKW_FCEV", "PT_BATTKWH_FCHEV", "PT_FCKW_FCHEV"):
        r(k, k.lower(), None, 11, CAFE19)
    r("COST_OBC", "cost_obc", (slice(2022 - 1989, 61),), 1, 29)
    r("MR_SLOPE", "mr_slope", None, 1, CAFE19)
    r("MR_INTERCEPT", "mr_intercept", None, 1, CAFE19)
    r("MR_BEVMULT", "mr_bevmult", (slice(1, CAFE19), slice(33, 61)), CAFE19, 29)
    r("MR_FCVMULT", "mr_fcvmult", (slice(1, CAFE19), slice(33, 61)), CAFE19, 29)
    r("H2_MAX_TANKS", "h2_max_tanks", None, CAFE19, 3)
    r("H2_KG_PER_TANK", "h2_kg_per_tank", None, CAFE19, 3)
    imp = FArray.zeros([(1, 61)])
    x.rng.read(imp, (slice(34, 61),), "BATT_ENDEN_IMP", 1, 2050 - 2022, 1)
    r("CHARGING_SPEED", "charging_speed", None, 1, CAFE19)
    cap = v["max_kwh_cap"]
    r("MAX_KWH_CAP", "max_kwh_cap", (slice(1, CAFE19), 2027 - 1989), 1, CAFE19)
    for i in range(2023, 61 + 1989 + 1):
        cap[1:CAFE19, i - 1989] = cap[1:CAFE19, 2027 - 1989] * imp[i - 1989] / imp[2027 - 1989]
    r("BATTSIZE_A_PHEV", "battsize_a_phev", None, 1, CAFE19)
    r("BATTSIZE_B_PHEV", "battsize_b_phev", None, 1, CAFE19)
    r("NG_PRICEADJ", "ng_priceadj", None, 1, 2)
    r("CNG_SHROF_NG", "cng_shrof_ng", (slice(1995 - 1989, 61),), 1, 56)
    r("COST_ICE", "cost_ice", (slice(1, CAFE19), bs), 1, CAFE19)
    r("COST_ICE_CNG", "cost_ice_cng", None, 1, CAFE19)
    r("COST_NGTANK_DGE", "cost_ngtank_dge", (slice(1, SC4), slice(25, 61)), SC4, 37)
    r("COST_ICE_HEV", "cost_ice_hev", (slice(1, CAFE19), bs), 1, CAFE19)
    r("COST_ICE_H2ICE", "cost_ice_h2ice", (slice(1, CAFE19), bs), 1, CAFE19)
    r("COST_ICE_PHEV", "cost_ice_phev", (slice(1, CAFE19), slice(1, 2), bs), CAFE19, 2)
    r("BEV_INFRA_COST", "bev_infra_cost", (slice(1, CAFE19), 34), CAFE19, 1)
    r("BEV_ELEC_MARKUP", "bev_elec_markup", None, 1, CAFE19)
    r("COST_DEF", "cost_def", (slice(2012 - 1989, 61),), 1, 39)
    x.scalar("SWITCHHDV_IRA", "switchhdv_ira", "i")
    x.scalar("SWITCHHDV_HR1", "switchhdv_hr1", "i")
    r("IRA_45W_MAX", "ira_45w_max", None, CAFE19, FUEL12)
    if v.i("switchhdv_ira") == 0 or legira == 0:
        v["ira_45w_max"].a[...] = 0.0
        v["evse_30ctaxcred"] = f32(0.0)
    if traneff == 4:
        v["switchhdv_hr1"] = type(v["switchhdv_hr1"])(0)
    x.scalar("NOX_SWITCH", "nox_switch", "i")
    r("COST_LONOX", "cost_lonox", None, CAFE19, FUEL12)
    if traneff == 3:
        v["nox_switch"] = type(v["nox_switch"])(0)
    for k in ("COST_BATTPACK_A", "COST_BATTPACK_LR", "COST_BATTMAT_A", "COST_BATTMAT_LR", "TRK_BATTC_HIST"):
        r(k, k.lower(), None, 1, 5)
    for k in ("COST_H2TANK_A", "COST_H2TANK_LR", "COST_FCSTACK_A", "COST_FCSTACK_LR", "COST_EMOTOR_A", "COST_FCSTK_RD",
              "COST_H2TANK_RD", "CHRG_EFF_IMP", "H2ICE_FUELDISC", "PHEV_MPG_ADJ"):
        x.scalar(k, k.lower())
    r("COST_H2TANK_INIT", "cumulative_h2_tanks", (slice(33, 33),), 1, 1)
    r("COST_FCSTK_INIT", "cumulative_fc_stacks", (slice(33, 33),), 1, 1)
    r("CHRG_EFF", "chrg_eff", (slice(2024 - 1989, 2024 - 1989),), 1, 1)
    r("PHEV_CHGSUS_MULT", "phev_chgsus_mult", None, CAFE19, 2)
    x.scalar("PHEV_DOD", "trk_phev_dod")

    ln2 = logf(f32(2.0))
    v["cost_fcstack_b"] = -logf(f32(1.0) - v["cost_fcstack_lr"]) / ln2
    v["cost_h2tank_b"] = -logf(f32(1.0) - v["cost_h2tank_lr"]) / ln2
    v["cost_battpack_b"].a[...] = -logf(f32(1.0) - v["cost_battpack_lr"].a) / ln2
    v["cost_battmat_b"].a[...] = -logf(f32(1.0) - v["cost_battmat_lr"].a) / ln2
    from nems_open.transportation.misc_modes import powi
    tanks, stacks = v["cumulative_h2_tanks"], v["cumulative_fc_stacks"]
    for i in range(34, bs + 1):
        tanks[i] = tanks[33] * powi(f32(1.1), i - 33)
        stacks[i] = stacks[33] * powi(f32(1.05), i - 33)
    fb = v.i("first_bat_yr")
    li = s["li_ion_cost"]
    for j in range(1, 6):
        v["cost_battkwh_trk"][j, 6:fb] = li[15, 6 + 1989:fb + 1989] * v["trk_battc_hist"][j]
    v["cost_fckw"][6:bs] = (v["cost_fcstack_a"] * powf(stacks[bs], -v["cost_fcstack_b"])) / jp[31] * jp[1]
    v["cost_h2tank"][6:bs] = (v["cost_h2tank_a"] * powf(tanks[bs], -v["cost_h2tank_b"])) / jp[31] * jp[1]
    v["cost_motorkw"][6:bs] = v["cost_emotor_a"] / jp[31] * jp[1]
    for k in ("cost_battpack_a", "cost_battmat_a"):
        v[k].a[...] = v[k].a / jp[31] * jp[1]
    d22, d23 = jp[2022 - 1989], jp[2023 - 1989]
    v["cost_ice_cng"].a[...] = v["cost_ice_cng"].a / d22 * jp[1]
    v["cost_ngtank_dge"].a[...] = v["cost_ngtank_dge"].a / jp[2009 - 1989] * jp[1]
    for k in ("cost_ice", "cost_ice_hev", "cost_ice_h2ice"):
        v[k][:, bs] = v[k][:, bs] / d23 * jp[1]
    v["cost_ice_phev"][:, :, bs] = v["cost_ice_phev"][:, :, bs] / d23 * jp[1]
    for k in ("cost_obc", "cost_def", "mr_slope", "mr_intercept", "cost_lonox"):
        v[k].a[...] = v[k].a / d22 * jp[1]
    for k in ("evse_maint", "refuel_timeval"):
        v[k] = v[k] / d22 * jp[1]
    mk = v["cost_motorkw"]
    for i in range(6, 62):
        if i <= 2025 - 1989:
            mk[i] = (f32(-2.2) * f32(i + 1989) + f32(4483.0)) / jp[31] * jp[1]
        elif i <= 2030 - 1989:
            mk[i] = mk[i - 1] * f32(.97)
        elif i <= 2035 - 1989:
            mk[i] = mk[i - 1] * f32(.98)
        else:
            mk[i] = mk[i - 1] * f32(.99)
    mr = v["mr_cost"]
    bev, fcv, mg = v["mr_bevmult"], v["mr_fcvmult"], v["mr_mgmult"]
    icpt, slope = v["mr_intercept"], v["mr_slope"]
    for i in range(iy, 62):
        for c in range(1, CAFE19 + 1):
            for f in range(1, FUEL12 + 1):
                for j in range(1, PBK_YR + 1):
                    m = icpt[c] + slope[c] * f32(j)
                    if f == 2 and c < 8:
                        m = m * mg
                    if f == 6:
                        m = m * bev[c, i]
                    if f == 7:
                        m = (mr[c, 1, j, i] + mr[c, 6, j, i]) / f32(2)
                    if f == 8:
                        m = (mr[c, 2, j, i] + mr[c, 6, j, i]) / f32(2)
                    if f in (9, 10):
                        m = m * fcv[c, i]
                    if f == 11:
                        m = mr[c, 2, j, i]
                    if f == 12:
                        m = (mr[c, 1, j, i] + mr[c, 2, j, i]) / f32(2)
                    mr[c, f, j, i] = m
    infra = v["bev_infra_cost"]
    for c in range(1, CAFE19 + 1):
        infra[c, :] = infra[c, 2023 - 1989] / jp[32] * jp[1]
    cred = v["evse_30ctaxcred"]
    hi = 2026 - 1989 if v.i("switchhdv_hr1") == 1 else 2032 - 1989
    infra[:, 2023 - 1989:hi] = infra[:, 2023 - 1989:hi] * (f32(1) - cred)
    ce = v["chrg_eff"]
    ce[iy:2024 - 1989] = ce[2024 - 1989]
    for i in range(2025 - 1989, 2032 - 1989 + 1):
        ce[i] = ce[2024 - 1989] * powi(f32(v["chrg_eff_imp"]), i - (2024 - 1989))
    ce[2033 - 1989:61] = ce[2032 - 1989]
    r("PHEVELECVMT", "phevelecvmt", None, 1, CAFE19)
    v["icafe19"], v["ifuel"] = CAFE19 + 1, FUEL12 + 1

    x = _Reader(s, "ACT")
    r = x.r
    for k in ("ACT_REQ_2B3", "ACT_REQ_48V", "ACT_REQ_78TRAC"):
        r(k, k.lower(), (slice(1, MNUMCR - 2), slice(35, 61)), MNUMCR - 2, 2050 - 2024 + 1)
    r("ACT_WGTMOD", "act_wgtmod", None, 1, CAFE19)
    r("ZEVREQSHR78", "zevreqshr78", None, 1, 2)
    x.scalar("PHEV_FACTOR", "phev_factor")
    x.scalar("ACT_SWITCH", "act_switch", "i")
    if traneff == 3:
        v["act_switch"] = type(v["act_switch"])(0)

    x = _Reader(s, "Phase_2")
    r = x.r
    x.scalar("CAFE_P3_SWITCH", "cafe_p3_switch", "i")
    r("BASE_MPG_P2", "base_mpg_p2", None, FUEL12, CAFE19)
    r("BASE_MKT_P2", "base_mkt_p2", None, FUEL12, CAFE19)
    r("TECHFYR_P2", "techfyr_p2", None, TECHP2, CAFE14, FUEL12, "i")
    r("PAYBACK_P2", "payback_p2", None, 1, CAFE14, 1, "i")
    r("HDV_DF", "hdv_df", None, FUEL12, CAFE14)
    for k in ("TECHEFF_P2", "TECHCOST_P2", "TECHVAR_P2", "TECHMID_P2", "TECHSHAPE_P2", "TECHMAX_P2"):
        r(k, k.lower(), None, TECHP2, CAFE14)
    std = v["hdv_ghgstd"]
    r("HDV_GHGSTD_CI", "hdv_ghgstd", (slice(1, CAFE14), slice(28, 61), 1), CAFE14, 34)
    r("HDV_GHGSTD_SI", "hdv_ghgstd", (slice(1, CAFE14), slice(28, 61), 2), CAFE14, 34)
    if traneff == 3:
        v["cafe_p3_switch"] = type(v["cafe_p3_switch"])(0)
    if v.i("cafe_p3_switch") == 0:
        r("HDV_GHGSTD_CI_NC", "hdv_ghgstd", (slice(1, CAFE14), slice(28, 61), 1), CAFE14, 34)
        r("HDV_GHGSTD_SI_NC", "hdv_ghgstd", (slice(1, CAFE14), slice(28, 61), 2), CAFE14, 34)
    r("HDV_STD_MAP", "hdv_std_map", None, FUEL12, CAFE14, 1, "i")
    smap = v["hdv_std_map"]
    for f in range(1, FUEL12 + 1):
        for c in range(1, CAFE14 + 1):
            if f >= 3:
                std[c, :, f] = std[c, :, int(smap[f, c])]
    r("SUPERSCEDE_P2", "superscede_p2", None, 1, 1, TECHP2, "i")
    r("TECH_SUP", "tech_sup", None, TECHP2, 9, 1, "i")
    r("SYNERGY_P2", "synergy_p2", None, TECHP2, 1, 1, "i")
    r("TECH_SYN", "tech_syn", None, TECHP2, 1, 1, "i")
    r("TECH_PER", "tech_per", None, TECHP2, 1)
    r("REQUIRED_P2", "required_p2", None, TECHP2, 1, 1, "i")
    r("TECH_REQ", "tech_req", None, TECHP2, 2, 1, "i")
    r("REQUIRED_ANY_P2", "required_any_p2", None, TECHP2, 1, 1, "i")
    r("TECH_R_ANY", "tech_r_any", None, TECHP2, 3, 1, "i")
    r("TECH_NUM", "tech_num", None, TECHP2, 1, 1, "i")
    r("LEARNING_P2", "learning_p2", (slice(1, 14), slice(25, 61)), 14, 37)
    r("TECHLEARN_P2", "techlearn_p2", None, TECHP2, CAFE14, 1, "i")
    x.scalar("DISCRTXG_P2", "discrtxg_p2")
    x.scalar("DISCRTXGL_P2", "discrtxgl_p2")
    if traneff == 3:
        v["discrtxg_p2"] = v["discrtxgl_p2"]
    r("EPA_PAYLOAD", "epa_payload", None, CAFE14, 1)
    r("GCO2_PER_GAL", "gco2_gal", None, FUEL12, CAFE14)
    r("HDV_USEFULLIFE", "hdv_usefullife", None, FUEL12, CAFE14)
    r("HDV_AFV_CREDITS", "hdv_afv_credits", (slice(1, FUEL12), slice(2017 - 1989, 2050 - 1989)), FUEL12, 34)
    v["techcost_p2"].a[...] = v["techcost_p2"].a / jp[2015 - 1989] * jp[1]
    lrn = v["learning_p2"]
    for i in range(1, 25):
        lrn[:, i] = lrn[:, 25]
    _notes(v)
    v["ifuel"], v["icafe14"] = FUEL12 + 1, CAFE14 + 1


def _notes(v) -> None:
    """Supersede, requires and synergy notes from the technology table."""
    sup, rq, syn = v["superscede_p2"], v["required_p2"], v["synergy_p2"]
    tsup, treq, tsyn, tper, tnum = v["tech_sup"], v["tech_req"], v["tech_syn"], v["tech_per"], v["tech_num"]
    st, cs = v["supersedes_tech"], v["tech_cnt_sup"]
    rt, cr = v["requires_tech"], v["tech_cnt_req"]
    yt, yp = v["synergy_tech"], v["syn_per"]
    ns = nr = ny = 0
    for t in range(1, TECHP2 + 1):
        if sup[t] == 1:
            ns += 1
            st[1, ns], st[2, ns] = tnum[t], tsup[t, 1]
            cs[ns] = 2
            for j in range(2, 10):
                if tsup[t, j] == 0:
                    continue
                cs[ns] = cs[ns] + 1
                st[int(cs[ns]), ns] = tsup[t, j]
        if rq[t] == 1:
            nr += 1
            rt[1, nr], rt[2, nr] = tnum[t], treq[t, 1]
            cr[nr] = 2
            for j in range(2, 4):
                if tsup[t, j] == 0:        # EIA quirk: TECH_SUP, not TECH_REQ
                    continue
                cr[nr] = cr[nr] + 1
                rt[int(cr[nr]), nr] = treq[t, j]
        if syn[t] == 1:
            ny += 1
            yt[1, ny], yt[2, ny] = tnum[t], tsyn[t, 1]
            yp[2, ny] = tper[t, 1]
    v["num_sup"], v["num_req"], v["num_syn"] = ns, nr, ny
    v["itechp2"] = TECHP2 + 1
