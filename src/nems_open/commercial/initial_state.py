"""COMM's state before its first call (2019, first iteration), built from EIA's input files.

Every array COMM works on, declared as in state_layout.json (EIA's declarations: type, bounds,
shape), starts at zero as the Fortran's static storage does. Then:

  files      the ported readers fill the tables the first call reads (KTEK, KINTENS, KSHEFF,
             KMELS, KPARM, KSTEO, KMINFL, KBEHAV, ...), see `tables()`
  restart    arrays other modules own (prices, macro drivers, SEDS history, renewables built
             elsewhere) come from the restart file through `Inputs`, as the runner already does
  computed   everything COMM computes itself (floorspace, service demand, shares, fuel use)
             stays zero until the chain runs

`coverage()` says where each array came from.
"""

import json
from pathlib import Path

import numpy as np

from nems_open import steo
from nems_open.scedes import option
from nems_open.commercial import base_year, first_call, ktek
from nems_open.commercial import inputs as inputs_mod
from nems_open.commercial.floorspace import FloorspaceInputs
from nems_open.commercial import technology_choice_inputs as tci
from nems_open.commercial.kparm import read_kparm
from nems_open.fortran_array import FArray

FIRST_YEAR_IDX = 29    # 0-based index of 2019 in a (region, year) restart array
LAYOUT = json.loads((Path(__file__).with_name("state_layout.json")).read_text())


# Residential and utility distributed generation (BldgLrn), which CDistGen reads as its competitors' capacity.
OTHER_MODULE = ("rpv_mw", "upv_mw", "rfuelcell_mw", "rwind_mw", "rmicrotur_mw")


def zeros() -> dict:
    """Every array in the layout, zeroed. Scalars are numpy scalars."""
    s = {}
    for name, d in LAYOUT.items():
        dt = np.dtype(d["dtype"])
        if "shape" in d:
            s[name] = FArray(np.zeros(d["shape"], dtype=dt), d["lb"])
        else:
            s[name] = dt.type(0)
    return s


def put(s: dict, name: str, src) -> None:
    """Copy src into s[name] over the Fortran indices both define (src: FArray, ndarray from 1, or scalar)."""
    dst = s[name]
    if not isinstance(dst, FArray):
        s[name] = np.asarray(src).astype(np.asarray(dst).dtype).reshape(())[()]
        return
    if not isinstance(src, FArray):
        src = FArray(np.asarray(src), [1] * np.ndim(src))
    lo = [max(a, b) for a, b in zip(dst.lb, src.lb)]
    hi = [min(a + n - 1, b + m - 1) for a, n, b, m in zip(dst.lb, dst.a.shape, src.lb, src.a.shape)]
    d = tuple(slice(l - a, h - a + 1) for l, h, a in zip(lo, hi, dst.lb))
    c = tuple(slice(l - b, h - b + 1) for l, h, b in zip(lo, hi, src.lb))
    dst.a[d] = src.a[c].astype(dst.a.dtype)


def tables(ab32sw: int | None = None, epa111d: int | None = None, nrg2007: int | None = None,
           stimulus: int | None = None):
    """Name -> array for everything the first call reads from a file or sets from a constant.

    The switches are scedes options (RTOVALUE, nems_open.scedes); pass a value to override one.
    """
    ab32sw = option("AB32SW") if ab32sw is None else ab32sw
    epa111d = option("EPA111D") if epa111d is None else epa111d
    nrg2007 = option("NRG2007") if nrg2007 is None else nrg2007
    stimulus = option("STIMULUS") if stimulus is None else stimulus
    t = {"steobm": option("STEOBM"), "stimulus": stimulus}
    k = ktek.read_ktek(epa111d=epa111d, ab32sw=ab32sw)
    base_year.index_technologies(k)
    base_year.normalize_base_shares(k)
    for name in ("TechEff", "TechCRI", "TechCost", "TechAvailability", "TechLife", "RetroCostFract", "CostParam1",
                 "CostParam2", "CostParam3", "EquipRestriction", "FuelbyTech", "TechbyService", "TechbyModel",
                 "TechsforService", "CMnumEqV", "CMnumTechsforService", "EquipName", "CostTrend",
                 "TechShareofServiceBASE"):
        t[name.lower()] = getattr(k, name)
    t["iktechcostyr"] = k.TechCostYr1 - ktek.BASEYR + 1
    t["comeui"] = inputs_mod.read_kintens()
    t["distservsteameui"] = inputs_mod.read_kdsstm()
    t["distservboilereff"] = inputs_mod.read_kdseff()
    t["distservfuelshr"] = inputs_mod.read_kdsfs()
    t["shortrunpriceelasofdmd"] = inputs_mod.read_ksdela()
    t["hurdleelas"] = inputs_mod.read_khurela()
    t["servicedflrspcprop"] = inputs_mod.read_kvarsdi()
    t["sunlightefficacy"], t["solarrenewablecontrib"] = inputs_mod.read_krenew()
    t["behaviorshare"] = tci.read_kbehav()
    eff = tci.read_kdeleff()
    t["effgrowthrate"], t["ceffgrowth"] = eff, eff
    t["capacityfactor"] = tci.read_kcapfac()
    t["timeprefprop"], t["timeprefprem"] = tci.read_kprem(nrg2007=nrg2007, stimulus=stimulus)
    t["coolingtechindexhp"] = tci.read_kparm_cooling_index()
    # TC first call: the cooling cost comes off heat pump capital costs (techcost edited in place).
    tci.heat_pump_cost_edit(t["techcost"], t["techbyservice"], t["techbymodel"], t["cmnumeqv"], t["coolingtechindexhp"])
    kparm = read_kparm()
    for name in ("dbgr", "dbgb", "dbgs", "dbgy1", "dbgy2", "comsteobm", "ksteocls", "ifmax"):
        t[name] = kparm[name]
    return t, k


def initial_state(inputs=None) -> dict:
    """The state COMM holds when it is first called (2019, first iteration), from files and the restart file."""
    from nems_open.commercial.comm import FIRST_YEAR, floorspace
    from nems_open.run_demand import Inputs

    inputs = inputs or Inputs()
    s = zeros()
    t, k = tables()
    for name, v in t.items():
        put(s, name, v)
    floorspace(s, FIRST_YEAR, inputs.array("MACOUT/mc_commflsp"), first_call=True)     # COMFloorspace runs before COMServiceDemand
    for name, v in base_year.base_year_intensities(k, t["comeui"], s["cmtotalflspc"]).items():
        put(s, name.lower(), v)
    put(s, "techshareofservicebase", k.TechShareofServiceBASE)        # normalized in place above
    for name, v in first_call.input_tables(inputs.array("MACOUT/mc_revser")).items():
        put(s, name, v)
    inputs.apply(s)
    floorspace_inputs(s)
    put(s, "degreedays", inputs_mod.read_kdegday(FArray(inputs.array("MACOUT/mc_np"), [1, 1])))
    steo_tables(s, inputs)
    put(s, "elasbaseyr", 29)          # CBECSyear - (BASEYR - 1)
    put(s, "ilaststeoyr", 2026)       # KSTEOYR + BASEYR - 1
    # Fuel use in QBLK/QMORE: history to 2018 is SEDS, and the chain writes 2019 on. (A scalar
    # block variable such as UPIRA_APPYR is a one-element array in the restart file.)
    snap = inputs.snapshot
    for full in snap.names():
        block, _, var = full.partition("/")
        if block in ("QBLK", "QMORE") and var.lower() in s and isinstance(s[var.lower()], FArray):
            hist = snap[full].copy()
            hist[..., FIRST_YEAR_IDX:] = 0       # the chain writes 2019 on
            put(s, var.lower(), hist)
    for name in OTHER_MODULE:
        put(s, name, snap[next(n for n in snap.names(name) if n.split("/")[1].lower() == name)])
    put(s, "whrfoss", snap["COGEN/whrfoss"])     # waste heat from fossil cogeneration, an input from the electricity module
    for name in ("upira_appyr",):
        put(s, name, inputs.array(name)[()] if np.ndim(inputs.array(name)) == 0 else inputs.array(name).ravel()[0])
    return s


def floorspace_inputs(s: dict) -> None:
    """What the first call reads from KFLSPC, KVINT and KBLDG, and the CBECS floorspace sums."""
    f32 = np.float32
    fi = FloorspaceInputs.load()
    put(s, "cbecsflrspc", FArray(fi.cbecs.astype(f32), [1, 1, 1]))
    put(s, "cmvintage", FArray(fi.vintage.astype(np.int32), [1, 1, 1]))
    put(s, "cmavgage", fi.avg_age.astype(f32))
    put(s, "cmgamma", fi.gamma.astype(f32))
    put(s, "cmfirstyr", 30)           # CBECSyear - BASEYR + 2
    put(s, "cmlastyr", 61)            # AEOLSTYR - BASEYR + 1
    rxb = s["cbecsflrrxb"]
    nb = fi.cbecs.shape[1]
    for b in range(1, nb + 1):
        us = f32(0.0)
        for r in range(1, fi.cbecs.shape[0] + 1):
            tot = f32(0.0)
            for v in range(fi.cbecs.shape[2]):
                tot = f32(tot + f32(fi.cbecs[r - 1, b - 1, v]))
            rxb[r, b] = tot
            us = f32(us + tot)
        rxb[11, b] = us


STEO_FIRST, STEO_LAST = 35, 38    # MSEDYR + 1 to LastYr2pct
REGIONS = ("nec", "mac", "enc", "wnc", "sac", "esc", "wsc", "mtn", "pac")


def steo_tables(s: dict, inputs) -> None:
    """The macro-supplied part of COMConsumption's first call (comm.f 7826 to 7950): SEDS history and the
    electricity and gas STEO rows (fuels 1 and 2). Fuels 3 to 8 come from KSTEO."""
    f32 = np.float32
    v = steo.load()
    qs = ("qselcm", "qsngcm", "qsdscm", "qsrscm", "qslgcm", "qsclcm", "qsmgcm", "qskscm")
    for f, name in enumerate(qs, start=1):
        hist = inputs.array(name)
        for r in range(1, 10):
            for y in range(1, 35):
                s["cmseds"][f, r, y] = f32(hist[r - 1, y - 1])
    for y in range(STEO_FIRST, STEO_LAST + 1):
        s["steodat"][1, y - 34] = f32(f32(v["exccpus"][y - 1]) * f32(3.412))
        for r, reg in enumerate(REGIONS, start=1):
            val = v[f"exccp_{reg}"][y - 1]
            if reg == "pac":
                val = f32(val + v["exccp_hak"][y - 1])
            s["cmseds"][1, r, y] = f32(f32(val) * f32(3.412))
        s["steodat"][2, y - 34] = f32(f32(v["ngccbus"][y - 1]) * f32(1000.0))
        total = f32(0.0)
        for reg in REGIONS:
            total = f32(total + f32(v[f"ngccp_{reg}"][y - 1]))
        for r, reg in enumerate(REGIONS, start=1):
            s["cmseds"][2, r, y] = f32(f32(f32(v[f"ngccp_{reg}"][y - 1]) / total) * f32(v["ngccbus"][y - 1]) * f32(1000.0))


def coverage(inputs=None) -> dict:
    """Where each array in the layout gets its starting value: files, restart or computed (zero until the chain runs)."""
    from nems_open.run_demand import EQUIVALENCED, Inputs

    inputs = inputs or Inputs()
    t, _ = tables()
    files = set(t) | set(first_call.input_tables(inputs.array("MACOUT/mc_revser"))) | {
        "cbecsflrspc", "cmvintage", "cmavgage", "cmgamma", "cmfirstyr", "cmlastyr", "cbecsflrrxb", "degreedays",
        "servdmdintenbase", "fuelshareofservicebase", "averageefficiencybase", "techshareofservicebase",
        "elasbaseyr", "ilaststeoyr", "cmnewfloorspace", "cmtotalflspc", "steodat", "cmseds"}
    restart = {k for k in LAYOUT if k in inputs.by_var or k in EQUIVALENCED} | {"whrfoss", "upira_appyr"} | set(OTHER_MODULE)
    restart |= {full.partition("/")[2].lower() for full in inputs.snapshot.names()
                if full.partition("/")[0] in ("QBLK", "QMORE")} & set(LAYOUT)
    out = {"files": sorted(files & set(LAYOUT)), "restart": sorted(restart - files)}
    out["computed"] = sorted(set(LAYOUT) - set(out["files"]) - set(out["restart"]))
    return out
