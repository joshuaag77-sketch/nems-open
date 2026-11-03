"""TRAN's first-call input readers vs the oracle.

Each reader fills its arrays from EIA's input files; every array it fills must equal
the oracle's state at the top of 2020 (the first dump year), where nothing the module
did since its first call has touched those values.
"""

import numpy as np
import pytest

from nems_open.fortran_array import FArray
from nems_open.transportation import tran
from nems_open.transportation import frt_common
from nems_open.transportation.readers import air, freight, freight_stock, ldv_tables, nhtsa
from tran_harness import needs, rel_err

pytestmark = needs("tran_tail")
Y = 31  # 2020

READERS = {
    "readair": (air.readair, [
        "wld_pop", "wld_gdp", "qagtr_us", "load_factor", "shr_ftm", "shr_rpm", "rpmt_hist", "ftmac", "asmac",
        "stkpa", "stkpp", "stkca", "stkcp", "stkpavint", "stkcavint", "stkppvint", "stkcpvint", "survac",
        "stk_sup_new", "min_prk_shr", "gptm", "pct_pass_mtow", "pct_belly_pload", "pct_belly_frt",
        "air_mgmt_adj", "stk_align_mult", "intercept_rpm", "beta1_rpm", "covidmult_ref", "covidmult_lomac",
        "covidmult_himac", "intercept_ftm", "beta1_ftm", "pass_weight", "fuel_burn_red", "alphayd", "rhoyd",
        "betafueld", "betatimed", "alphayi", "rhoyi", "betafueli", "betatimei", "minage_prk_f",
        "minage_c_pprk", "minage_c_pact", "minage_prk_p", "maxage_unprk_p", "max_unprk_shr",
        "stk_sup_tot", "stkptot", "stkctot", "covid_mult"], "a_"),
}
# Arrays the reader fills only in part; the rest is the module's own later output, compared
# on the reader's part: {name: index}.
PART = {
    "readair": {"yield": (slice(None), slice(5, 33)), "ftm": (slice(None), slice(5, 33), slice(None)),
                "asmpg_vint": (slice(None), slice(None), slice(None), slice(None), 32)},
}


@pytest.fixture(scope="module")
def start():
    return tran.start_from_dump(Y)[0]


@pytest.mark.parametrize("reader", list(READERS))
def test_reader(start, reader):
    fn, names, prefix = READERS[reader]
    key = lambda k: prefix + k if prefix + k in start else k  # noqa: E731
    part = {key(k): idx for k, idx in PART[reader].items()}
    keys = [key(k) for k in names] + list(part)
    s = {k: (v.copy() if isinstance(v, FArray) else v) for k, v in start.items()}
    for k in keys:
        if isinstance(s[k], FArray):
            s[k].a[...] = 0
        else:
            s[k] = type(s[k])(0)
    fn(s)
    bad = {}
    for k in keys:
        mine, eia = s[k], start[k]
        idx = part.get(k)
        m = mine.a[idx] if idx is not None else (mine.a if isinstance(mine, FArray) else np.asarray(mine))
        e = eia.a[idx] if idx is not None else (eia.a if isinstance(eia, FArray) else np.asarray(eia))
        err = rel_err(m, e)
        if err > READ_TOL:
            bad[k] = err
    assert bad == {}


# Names CFREAD reads but does not fill.
FREIGHT_INPUTS = {"first_bat_yr"}
# Filled only in part by CFREAD; the module writes the rest later: {name: index}.
# TRUCK_VMT rescales annvmt (size classes 1-3) and annvmt_19 every year; TRUCK_NEW writes
# hdv_mpg and cltmpg_yr from 2018; cltvmtt after 2011 and cost_battkwh_trk after the first
# battery year are the module's own results.
FREIGHT_PART = {"f_annvmt": (3,), "f_annvmt_19": (slice(30, 35),),
                "f_hdv_mpg": (slice(5, 28),), "f_cltmpg_yr": (slice(5, 28),),
                "cltvmtt": (slice(None), slice(5, 22)), "cost_battkwh_trk": (slice(None), slice(5, 36))}
# Last-bit differences between numpy's and gfortran's log and pow (CHRG_EFF, FC stack costs).
READ_TOL = 1e-6


def _touched(fn, start, inputs=FREIGHT_INPUTS):
    seen = []
    orig = frt_common.V.key

    def key(self, name):
        k = orig(self, name)
        seen.append(k)
        return k
    frt_common.V.key = key
    try:
        s = {k: (v.copy() if isinstance(v, FArray) else v) for k, v in start.items()}
        fn(s)
    finally:
        frt_common.V.key = orig
    return sorted({k for k in seen if k in start and k.removeprefix("f_") not in inputs})


def _check_touched(fn, start, part, inputs=FREIGHT_INPUTS):
    keys = _touched(fn, start, inputs)
    s = {k: (v.copy() if isinstance(v, FArray) else v) for k, v in start.items()}
    for k in keys:
        if isinstance(s[k], FArray):
            s[k].a[...] = 0
        else:
            s[k] = type(s[k])(0)
    fn(s)
    bad = {}
    for k in keys:
        idx = part.get(k)
        m, e = s[k], start[k]
        m = m.a[idx] if idx is not None else (m.a if isinstance(m, FArray) else np.asarray(m))
        e = e.a[idx] if idx is not None else (e.a if isinstance(e, FArray) else np.asarray(e))
        err = rel_err(m, e)
        if err > READ_TOL:
            bad[k] = err
    return keys, bad


def test_cfread(start):
    keys, bad = _check_touched(freight.cfread, start, FREIGHT_PART)
    assert len(keys) > 150
    assert bad == {}


# TRUCK_STOCK fills the commercial light truck stocks from 2012 on; CFREADSTOCK sets
# fuel_shr_ivmt only for 2012 to the stock base year.
STOCK_PART = {"f_cltstk": (slice(5, 22),), "f_fuel_shr_ivmt": (slice(22, 35),), "cltstkt": (slice(None), slice(5, 22))}
# Loop indexes: CFREADSTOCK leaves them where the Fortran loops do, but other routines
# reset them before 2020.
STOCK_SKIP = {"f_iregn", "f_icafe19", "f_ifuel", "f_iflt", "f_ivmt", "f_isc4"}


# CFREAD's tables that CFREADSTOCK reads.
STOCK_INPUTS = {"fltshr_stk", "fltshr_sales", "base_mkt_p2", "tffxgrt", "sc19map", "veh_shr"}


def test_cfreadstock(start):
    keys, bad = _check_touched(freight_stock.cfreadstock, start, STOCK_PART, STOCK_INPUTS)
    assert {"f_trkstk_19r", "f_trkstk", "f_cltstk"} <= set(keys)
    assert {k: e for k, e in bad.items() if k not in STOCK_SKIP} == {}


def _check_names(fn, start, names, part=None):
    part = part or {}
    s = {k: (v.copy() if isinstance(v, FArray) else v) for k, v in start.items()}
    for k in names:
        s[k].a[...] = 0
    fn(s)
    bad = {}
    for k in names:
        idx = part.get(k, ...)
        err = rel_err(s[k].a[idx], start[k].a[idx])
        if err > READ_TOL:
            bad[k] = err
    return bad


def test_readstock(start):
    assert _check_names(ldv_tables.readstock, start, ["ldv_stock", "flt_stock"]) == {}


HIST = ["fempri", "femmpg", "mpgadj", "mpgcomp", "femhp", "femtsz", "femrng", "femwgt", "batpacksize",
        "fprt", "phev_evmt", "cafesales", "fe", "weight", "price", "hp", "tanksize", "range", "ldv_sales",
        "elecsysinccost"]


NHTSA = ["epampg", "epatsz", "epalug", "epapri", "epahp", "epawgt", "eparng", "phevmpg_s", "phevmpg_d", "nameplate",
         "x210", "evmpg_adj", "luggavg", "fprint", "own_sales", "ownsalesshr", "ownsaletemp", "ev_range"]
# TSMOD writes the regional sales from 2020, and later years of X210 come from the readers'
# EPA year on: compare the readers' years.
LDV_PART = {"ldv_sales": (Ellipsis, slice(5, 30))}


@pytest.fixture(scope="module")
def after_readldv(start):
    """The 2020 start with READLDV's tables added (some are in no dump: nothing ported reads them)."""
    from nems_open.transportation.readers import ldv
    s = {k: (v.copy() if isinstance(v, FArray) else v) for k, v in start.items()}
    ldv.readldv(s)
    for k, v in start.items():          # keep the oracle's values where both exist
        s[k] = v.copy() if isinstance(v, FArray) else v
    return s


def test_readvmt(after_readldv):
    # TVMT rewrites the US row (region 11) of each year it runs; compare the census divisions
    # every year and the US row from 2020.
    regions = (slice(None), slice(None), slice(0, 9), slice(None))
    us_ahead = (slice(None), slice(30, None), 10, slice(None))
    for part in (regions, us_ahead):
        assert _check_names(ldv_tables.readvmt, after_readldv, ["pvmt", "lvmt"],
                            {"pvmt": part, "lvmt": part}) == {}


def _readhist_and_nhtsa(s):
    ldv_tables.readhist(s)
    nhtsa.readnhtsa(s)


def test_readhist_readnhtsa(after_readldv):
    names = [k for k in HIST + NHTSA if k in after_readldv]
    assert _check_names(_readhist_and_nhtsa, after_readldv, names, LDV_PART) == {}


# READHIST alone: its years (through 2023); READNHTSA fills 2024 and the 2019-2024 sales.
HIST_YEARS = (slice(None), slice(None), slice(0, 34), slice(None))


def test_readhist(start):
    part = {k: HIST_YEARS for k in HIST}
    part["batpacksize"] = (slice(0, 34),)
    part["ldv_sales"] = (Ellipsis, slice(5, 29))
    for k in ("fe", "weight", "price", "hp", "tanksize", "range", "elecsysinccost"):
        part[k] = Ellipsis
    assert _check_names(ldv_tables.readhist, start, [k for k in HIST if k in start], part) == {}


class _Tracking(dict):
    """A state dict that records the names a reader looks up."""

    def __init__(self, *a):
        super().__init__(*a)
        self.seen = set()

    def __getitem__(self, k):
        self.seen.add(k)
        return super().__getitem__(k)

    def get(self, k, d=None):
        self.seen.add(k)
        return super().get(k, d)


def _check_tracked(fn, start, inputs, part=None):
    part = part or {}
    t = _Tracking({k: (v.copy() if isinstance(v, FArray) else v) for k, v in start.items()})
    fn(t)
    keys = sorted(k for k in t.seen if k in start and k not in inputs)
    s = {k: (v.copy() if isinstance(v, FArray) else v) for k, v in start.items()}
    for k in keys:
        if isinstance(s[k], FArray):
            s[k].a[...] = 0
        else:
            s[k] = type(s[k])(0)
    fn(s)
    bad = {}
    for k in keys:
        idx = part.get(k, Ellipsis)
        m, e = s[k], start[k]
        m = m.a[idx] if isinstance(m, FArray) else np.asarray(m)
        e = e.a[idx] if isinstance(e, FArray) else np.asarray(e)
        err = rel_err(m, e)
        if err > READ_TOL:
            bad[k] = err
    return keys, bad


LDV_INPUTS = {"mc_jpgdp", "ijumpyr", "grpmap"}
# Rewritten by the module before 2020: TMPGNEW's technology penetration (MKT_PEN) and
# TALT2's station ratios (STA_RAT) every year, TCURB's stock weights (STKAVGWGT, and
# TRWT*_STOCK from 1995), and TRAN's battery production (GLOBAL_BATT_PROD column 1).
LDV_SKIP = {"mkt_pen", "sta_rat", "stkavgwgt"}
LDV_PART = {"trwtcar_stock": (slice(0, 5),), "trwttrk_stock": (slice(0, 5),),
            "global_batt_prod": (slice(None), 1, slice(None))}


def test_readldv(start):
    from nems_open.transportation.readers import ldv
    keys, bad = _check_tracked(ldv.readldv, start, LDV_INPUTS | LDV_SKIP, LDV_PART)
    assert len(keys) > 200
    assert bad == {}
