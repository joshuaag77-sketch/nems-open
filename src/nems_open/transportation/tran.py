"""SUBROUTINE TRAN (tran.f): one call of the transportation module for a year.

`tran(s, carry)` runs the routines in TRAN's order on the state dict, after the input
reads that the Fortran does once (not ported: tests and runs start from the oracle).

`start_from_dump(y)` builds the state at the top of year y's first iteration from the
oracle's dumps: each variable is taken from the first dump point of the year that holds
it (a routine that writes a variable has it in its own dump, so nothing earlier in the
year changed it). `carry` holds the routines' saved local arrays as they stood when the
year began.

`tran(..., check=y)` compares the state with the oracle after every routine and
returns the worst relative error per routine; that is the whole-TRAN year check.
"""

import numpy as np

from nems_open import oracle_state
from nems_open.fortran_array import FArray
from nems_open.transportation import (air_report, bench, frt_new, frt_rpt, frt_ship, misc_modes, newldv, report,
                                      tmac, tmpgnew)
from nems_open.transportation.common import f32
from nems_open.transportation.fleet import tfltstks
from nems_open.transportation.fleet_mpg import tfltmpgs
from nems_open.transportation.hav import flthav
from nems_open.transportation.small import tcurb, tfltvmts, tmpgag, treg
from nems_open.transportation.stock import tsmod
from nems_open.transportation.stock_mpg import tmpgstk
from nems_open.transportation.totals import tcons, tinteg
from nems_open.transportation.travel import tfltcons, tvmt

RUN = "run_tran"
BASEYR = 1990

# Dump points in the order TRAN reaches them (the tags in oracle/hooks_tran.py).
ORDER = ["tmac", "newldv", "tmpgnew", "tmpg_lion", "tmpg_fem1", "tmpg_cgs1", "tmpg_att1", "tmpg_alt1", "tmpg_altx1",
         "tmpg_cafe0", "tmpg_cafe1", "treg", "tfltstks", "flthav", "tfltvmts", "tsmod", "tmpgstk", "tcurb",
         "tfltmpgs", "tfltcons", "tvmt", "tranfrt", "frt_new", "frt_tech", "frt_inc", "frt_choice", "frt_act",
         "frt_agg", "frt_ghg", "frt_stock", "frt_vmt", "frt_clt", "frt_fuel", "tfrtrpt", "tmpgag", "trail",
         "tship", "tranair", "tmisc", "tcons", "tinteg", "tbenchmark", "treport", "tran_tail"]

# Saved local arrays with a year axis: (dump, names). Years from y on are cleared.
YEARLY_PRIVATE = [("tmpgnew_out", ("altstat", "predstk")),
                  ("trail_out", ("rail_fuel_shr", "lng_locom_inccost", "adoptlng")),
                  ("tmisc_out", ("hyway", "ftvmt")),
                  ("tship_out", ("isfdt_b", "lsfo_upgrade", "temp_prhtr")),
                  ("tranair_out", ("pjftr_us",))]


class Carry(dict):
    """Saved local arrays by routine: carry["tmpgnew"], carry["tranfrt"], ..."""


def _clear_from(a: FArray, y: int) -> FArray:
    a = a.copy()
    axis = max(i for i, (lo, n) in enumerate(zip(a.lb, a.a.shape)) if lo == 1 and n == 61)
    idx = [slice(None)] * a.a.ndim
    idx[axis] = slice(y - 1, None)
    a.a[tuple(idx)] = 0
    return a


def start_from_dump(y: int) -> tuple[dict, Carry]:
    """(state, carry) at the top of year index y's first iteration (y a dump year)."""
    s = {}
    for tag in ORDER:
        if not oracle_state.available(f"{tag}_in", y, run=RUN):
            continue
        for k, v in oracle_state.load(f"{tag}_in", y, run=RUN).items():
            if k not in s:
                s[k] = v.copy() if isinstance(v, FArray) else v
    c = Carry()
    flat = {}
    for dump, names in YEARLY_PRIVATE:
        out = oracle_state.load(dump, y, run=RUN)
        for k in names:
            flat[k] = _clear_from(out[f"p_{k}"], y)
    c["tmpgnew"] = {k: flat[k] for k in ("altstat", "predstk")}
    c["trail"] = {k: flat[k] for k in ("rail_fuel_shr", "lng_locom_inccost", "adoptlng")}
    c["tmisc"] = {k: flat[k] for k in ("hyway", "ftvmt")}
    c["tship"] = {k: flat[k] for k in ("isfdt_b", "lsfo_upgrade", "temp_prhtr")}
    c["tranair"] = {"pjftr_us": flat["pjftr_us"]}
    c["tranfrt"] = freight_carry(y)
    # MER_STEO_regn has no year axis; it changes only in the last SEDS year.
    c["tbenchmark"] = {"mer_steo_regn": oracle_state.load("tbenchmark_out", y, run=RUN)["p_mer_steo_regn"].copy()}
    c["treport"] = {k: np.zeros(17, dtype=f32) for k in ("cmpg_2", "tmpg_2", "lmpg_2")}
    return s, c


def freight_carry(y: int) -> dict:
    """TRANFRT's saved locals as they stood when year y began (see tests/test_tran_freight.py)."""
    from nems_open.transportation import frt_act
    yearly = ["techpenyr_p2", "cpm_r_ice", "ttonmi", "tvmt", "temp_stk_vmt_ratio"] + frt_act.CARRY
    out = oracle_state.load("tranfrt_out", y, run=RUN)
    src = out
    if "p_start_curve" not in out:
        later = [z for z in (31, 36, 41, 51, 61) if z > y and oracle_state.available("tranfrt_out", z, run=RUN)]
        src = oracle_state.load("tranfrt_out", later[0], run=RUN) if later else out
    c = {k: _clear_from(src[f"p_{k}"], y) for k in yearly if f"p_{k}" in src}
    if "p0_ghgbank" in src:
        c["ghgbank"] = _clear_from(src["p0_ghgbank"], y) if src is not out else out["p0_ghgbank"].copy()
    if "p_start_curve" in src:
        # TRUCK_PBK's curve history is dumped after the first GHG try: undo the curves that
        # started this year (midpoint = this year + half the curve length).
        st = {k: src[f"p_{k}"].copy() for k in ("start_curve", "midyr_choice", "slope_choice")}
        st["midyr_adj"] = src["p0_midyr_adj"].copy()
        if oracle_state.available("frt_choice_in", y, run=RUN):
            ch = oracle_state.load("frt_choice_in", y, run=RUN)
            cy, sc19, yrs = ch["f_cyafvxg"], ch["f_sc19map"], BASEYR - 1 + y
            a, mid = st["start_curve"].a, st["midyr_choice"].a
            for c19 in range(1, 20):
                isc4 = int(sc19[c19])
                for f in range(1, 13):
                    for fl in (1, 2):
                        now = np.float32(yrs) + np.float32(cy[isc4, f, fl]) / np.float32(2.0)
                        a[c19 - 1, f - 1, fl - 1, (a[c19 - 1, f - 1, fl - 1, :] != 0) & (mid[c19 - 1, f - 1, fl - 1, :] == now)] = 0
        elif src is not out:
            st["start_curve"].a[...] = 0
        c.update(st)
    return c


def _setup(s: dict) -> None:
    """TRAN's statements before TMAC (run switches as in the reference case)."""
    yrs = int(s["curcalyr"])
    for k, v in (("roundoff_error", f32(0.002)), ("first_read_year", 1995), ("iy", 1995 - BASEYR + 1),
                 ("ibank", 1), ("traneff", 0), ("tranab32", 1), ("legira", 1), ("ira_stim", f32(1.0)),
                 ("yrs", yrs), ("n", yrs - BASEYR + 1)):
        if k in s:
            s[k] = v


def _err(mine, eia) -> float:
    from nems_open.fortran_array import FArray as FA
    a = np.asarray(mine.a if isinstance(mine, FA) else mine)
    b = np.asarray(eia.a if isinstance(eia, FA) else eia)
    if b.dtype.kind in "SU" or a.shape != b.shape:
        return 0.0 if np.array_equal(a, b) else np.inf
    a, b = a.astype(np.float64), b.astype(np.float64)
    both = np.isnan(a) & np.isnan(b)
    if (np.isnan(a) ^ np.isnan(b)).any():
        return np.inf
    a, b = np.where(both, 0, a), np.where(both, 0, b)
    scale = np.abs(b[np.isfinite(b)]).max(initial=0.0)
    d = np.abs(a - b)
    with np.errstate(invalid="ignore", divide="ignore"):
        r = np.where(d == 0, 0.0, d / np.maximum(np.abs(b), 1e-3 * scale))
    return float(r.max(initial=0.0))


def tran(s: dict, carry: Carry, check: int | None = None) -> dict:
    """One TRAN call. With check=y (a dump year, first iteration), returns
    {routine: (worst relative error, array)} against the oracle after each routine."""
    worst = {}

    def compare(tag):
        if check is None or not oracle_state.available(f"{tag}_out", check, run=RUN):
            return
        out = oracle_state.load(f"{tag}_out", check, run=RUN)
        e = [(_err(s[k], v), k) for k, v in out.items() if k in s and not k.startswith(("p_", "p0_"))]
        worst[tag] = max(e, default=(0.0, ""))

    _setup(s)
    steps = [
        ("tmac", lambda: tmac.tmac(s)),
        ("newldv", lambda: newldv.newldv(s)),
        ("tmpgnew", lambda: tmpgnew.tmpgnew(s, carry["tmpgnew"])),
        ("treg", lambda: treg(s)),
        ("tfltstks", lambda: tfltstks(s)),
        ("flthav", lambda: flthav(s) if int(s["yrs"]) >= int(np.min(_raw(s["first_lidar_year"]))) else None),
        ("tfltvmts", lambda: tfltvmts(s)),
        ("tsmod", lambda: tsmod(s)),
        ("tmpgstk", lambda: tmpgstk(s)),
        ("tcurb", lambda: tcurb(s)),
        ("tfltmpgs", lambda: tfltmpgs(s)),
        ("tfltcons", lambda: tfltcons(s)),
        ("tvmt", lambda: tvmt(s)),
        ("tranfrt", lambda: frt_new.tranfrt(s, carry["tranfrt"])),
        ("tfrtrpt", lambda: frt_rpt.tranfrt_report(s)),
        ("tmpgag", lambda: tmpgag(s)),
        ("trail", lambda: misc_modes.trail(s, carry["trail"])),
        ("tship", lambda: frt_ship.tship(s, carry["tship"])),
        ("tranair", lambda: air_report.tranair(s, carry["tranair"])),
        ("tmisc", lambda: misc_modes.tmisc(s, carry["tmisc"])),
        ("tcons", lambda: tcons(s)),
        ("tinteg", lambda: tinteg(s)),
        ("tbenchmark", lambda: bench.tbenchmark(s, carry["tbenchmark"])),
        ("treport", lambda: report.treport(s, carry["treport"])),
        ("tran_tail", lambda: report.tran_tail(s)),
    ]
    with np.errstate(divide="ignore", invalid="ignore", over="ignore"):
        for tag, step in steps:
            step()
            compare(tag)
    return worst


def _raw(v):
    return v.a if isinstance(v, FArray) else np.asarray(v)
