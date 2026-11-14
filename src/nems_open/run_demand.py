"""Phase 2: the demand modules wired into one runner, fed by EIA's prices.

For a year, the runner calls each ported demand module in NEMS's order
(residential, commercial, industrial, transportation), with prices, macro
drivers and other modules' outputs taken from EIA's AEO2026 restart file, and
writes their fuel use into QBLK-style arrays. Change an input (`Inputs`
overrides) and the modules respond; leave it alone and they reproduce EIA.

How a year runs: each module starts from the oracle's state at the top of that
year's final NEMS iteration (its input tables and its own history before that
year; residential starts from its input files instead where there is no
dump), every input array is overwritten from `Inputs`, and the module's chain
runs once. `DemandRunner`
can then keep going year by year, two iterations a year, carrying each
module's state the way the Fortran does.

After the modules run, `sum_quantities` does the part of NEMS's SUMQAS
(source/util_sumqas.f90) that touches these sectors: US totals as the sum of
the nine census divisions, California as a share of the Pacific division, and
each sector's petroleum, renewable and total rows (QTP, QTR, QTS).

Transportation is ported (`TransportationSector`, about a minute and a half per
iteration) and runs when asked for. Industrial is a slot (`IndustrialSector`): asked
for by name, it supplies the industrial oracle's fuel use until IND's year loop is
ported. To add a sector, write a class like `ResidentialSector` (available, start,
iteration, quantities) and put it in SECTORS.

    python -m nems_open.run_demand 2030
"""

import sys

import numpy as np

from nems_open.fortran_array import FArray
from nems_open.snapshot import Snapshot

BASEYR = 1990
MNUMCR = 11
BASEYR_COMMERCIAL = 2019  # the first year commercial computes
MSEDYR = 34  # last year of SEDS history (2023)

# Restart-file blocks the demand modules read but do not write: end-use prices
# (AMPBLK and AEUSPRC, as the demand modules see them), expected prices, the macro
# model's drivers, SEDS history, and what electricity, transportation and
# emissions modules hand to the buildings modules.
INPUT_BLOCKS = ("AMPBLK", "AEUSPRC", "MXPBLK", "MACOUT", "QSBLK", "EMABLK", "UEFPOUT", "UECPOUT", "TRANREP")

# Electricity prices by end use. The Fortran EQUIVALENCEs PELRSOUT(r, y, eu) and
# PELCMOUT onto these arrays, in this order (includes/eusprc).
EQUIVALENCED = {
    "pelrsout": ("pelshrs", "pelclrs", "pelwhrs", "pelckrs", "pelcdrs", "pelrfrs", "pelfzrs", "pelltrs",
                 "pelotrs", "pelh2rs", "pelvhrs"),
    "pelcmout": ("pelshcm", "pelsccm", "pelwhcm", "pelvtcm", "pelckcm", "pelltcm", "pelrfcm", "pelopcm",
                 "peloncm", "pelotcm", "pelp2cm", "pelpfcm", "pelsbcm", "peltbcm", "pelibcm", "pelfncm"),
}


class Inputs:
    """The demand modules' inputs: EIA's restart file plus any overrides.

    overrides: {"BLOCK/name": array}, same shape as the restart array, for
    example {"AMPBLK/pelrs": 1.2 * snapshot["AMPBLK/pelrs"]}.
    """

    def __init__(self, snapshot: Snapshot | None = None, overrides: dict | None = None):
        self.snapshot = snapshot or Snapshot()
        self.by_var = {}
        for full in self.snapshot.names():
            block, _, var = full.partition("/")
            if block in INPUT_BLOCKS:
                assert var.lower() not in self.by_var, f"{var} is in two input blocks"
                self.by_var[var.lower()] = full
        self.overrides = {}
        for name, value in (overrides or {}).items():
            full = self.by_var.get(name.split("/")[-1].lower())
            if full is None:
                raise KeyError(f"{name} is not a demand input (blocks {INPUT_BLOCKS})")
            self.overrides[full] = np.asarray(value)

    def array(self, name: str) -> np.ndarray:
        full = self.by_var[name.split("/")[-1].lower()]
        return self.overrides.get(full, self.snapshot[full])

    def apply(self, state: dict) -> None:
        """Overwrite every input array a module's state holds."""
        for k, v in state.items():
            if not isinstance(v, FArray):
                continue
            if k in self.by_var:
                src = self.array(k)
            elif k in EQUIVALENCED:
                src = np.stack([self.array(p) for p in EQUIVALENCED[k]], axis=-1)
            else:
                continue
            if src.shape == v.a.shape:
                v.a[...] = src.astype(v.a.dtype)


class ResidentialSector:
    """SUBROUTINE RESD (src/nems_open/residential/resd.py)."""
    name = "residential"
    suffix = "rs"

    def __init__(self, levers=None):
        self.levers = levers            # residential.levers.ResidentialLevers

    @staticmethod
    def available(year: int) -> bool:
        """Any year from 2021: from the oracle's dump where there is one, else from the files."""
        return year > 2020

    @staticmethod
    def dumped(year: int) -> bool:
        """Whether the oracle dumped the state this module starts from in that year."""
        from nems_open import oracle_state
        return oracle_state.available("yb_in", year - BASEYR + 1, "resd")

    def start(self, year: int, inputs: Inputs | None = None):
        """The state at the top of year's final iteration: the oracle's dump, or with no dump,
        the input files run from 2020 through year's first iteration (about 2 s a year)."""
        from nems_open.residential import resd
        if self.dumped(year):
            return resd.start_from_dump(year - BASEYR + 1)
        inputs = inputs or Inputs()
        s = resd.start_from_files(inputs)
        for y in range(2021, year + 1):
            for itr in ((1, 2) if y < year else (1,)):
                self.iteration(s, y, itr, inputs)
        return s

    def iteration(self, s, year: int, itr: int, inputs: Inputs) -> None:
        from nems_open.residential import resd
        from nems_open.residential.reports import nhtshr, resdrp2
        s["curcalyr"], s["curiyr"], s["curitr"] = year, year - BASEYR + 1, itr
        inputs.apply(s)
        if self.levers and year >= self.levers.year and not s.get("_levers_applied"):
            from nems_open.residential import levers
            s["_levers_applied"] = levers.apply(self.levers, s)
        resd.projection_year(s)
        if year == resd.LASTYEAR and itr == 2:
            nhtshr(s)
            resdrp2(s)

    def quantities(self, s) -> dict:
        return {k: s[k] for k in SECTOR_QUANTITIES["rs"] if k in s}


class CommercialSector:
    """SUBROUTINE COMM (src/nems_open/commercial/comm.py)."""
    name = "commercial"
    suffix = "cm"

    def __init__(self, from_files: bool = False, levers=None):
        self.from_files = from_files
        self.levers = levers            # commercial.levers.CommercialLevers; implies from_files

    @staticmethod
    def available(year: int) -> bool:
        """Always: with no oracle dump for the year, commercial starts from the input files."""
        return True

    def start(self, year: int, inputs=None):
        """The state at the top of `year`. From the oracle's dump when there is one (and no lever or
        from_files asks otherwise); else from the input files, run forward from 2019 with this runner's
        inputs, which takes about 4 s a year. A file start has not run `year` yet, so the runner
        gives it both iterations."""
        from nems_open import oracle_state
        from nems_open.commercial.comm import Commercial
        y = year - BASEYR + 1
        if not (self.from_files or self.levers) and oracle_state.available("sd_in", y):
            return Commercial.start_from_dump(y)
        inputs = inputs or Inputs()
        c = Commercial.start_from_files(inputs, self.levers)
        for yy in range(BASEYR_COMMERCIAL, year):
            for itr in (1, 2):
                self.iteration(c, yy, itr, inputs)
        c.needs_first_iteration = True
        return c

    def iteration(self, c, year: int, itr: int, inputs: Inputs) -> None:
        inputs.apply(c.s)
        c.iteration(year - BASEYR + 1, itr, inputs.array("MACOUT/mc_commflsp"))

    def quantities(self, c) -> dict:
        return c.qblk()


class IndustrialSector:
    """SUBROUTINE IND (source/ind.f): the slot industrial fills as its port lands.

    Ported so far: CALBSC, CALSTOT and INDTOTAL (boiler and fuel accounting inside ISEAM's
    loop over 24 industries and 4 Census regions) and COGINIT, EVALCOGEN and CALGEN (combined
    heat and power). The
    steps that carry those results to QBLK (MODCAL, NATTOTAL, WRQTY, and WEXOG's
    history and STEO benchmarking) are not ported, so the ported routines cannot move
    QBLK yet. Until they are, the sector's fuel use is the industrial oracle's: EIA's
    ind.f run on EIA's restart file (oracle/run_ind/out/q*in.bin, every year). It is
    fixed, so it does not respond to prices, and it differs from EIA's restart file from
    2024 (SCOPE.md, industrial oracle status). When the year loop is ported, iteration()
    runs it and quantities() reads its QBLK rows, as for the other sectors.
    """
    name = "industrial"
    suffix = "in"
    ported = ("CALBSC", "CALSTOT", "INDTOTAL", "COGINIT", "EVALCOGEN", "CALGEN")
    DUMP_YEARS = (2025, 2026, 2027, 2030, 2040, 2050)  # years the oracle dumped IND's state at the top of the first iteration

    def __init__(self, ind: str = "oracle"):
        """ind="oracle": EIA's fuel use from the industrial oracle, fixed. ind="ported": the ported year loop
        (industrial/year.py): end-use industries computed, process-flow industries and oil and gas mining
        replayed from EIA's reference path scaled by output (industrial/standin.py)."""
        if ind not in ("oracle", "ported"):
            raise ValueError(f"ind must be 'oracle' or 'ported', not {ind!r}")
        self.ind = ind

    @staticmethod
    def oracle_out():
        """The industrial oracle's output folder: the shared cache, else the clone's own."""
        from nems_open import oracle_state
        from nems_open.paths import REPO_ROOT
        for d in (oracle_state.ORACLE_DIR / "ind" / "out", REPO_ROOT / "oracle" / "run_ind" / "out"):
            if (d / "qelin.bin").exists():
                return d
        return None

    @classmethod
    def available(cls, year: int) -> bool:
        return cls.oracle_out() is not None

    def start(self, year: int, inputs=None):
        if self.ind == "ported":
            return self._start_ported(year, inputs)
        d = self.oracle_out()
        if d is None:
            raise FileNotFoundError("industrial oracle output not found (oracle/run_ind/out/q*in.bin)")
        rows = {}
        for k in SECTOR_QUANTITIES["in"]:
            raw = np.fromfile(d / f"{k}.bin", dtype=np.float32)
            rows[k] = FArray(raw.reshape((MNUMCR, raw.size // MNUMCR), order="F"))
        return rows

    def _start_ported(self, year: int, inputs=None):
        from nems_open import oracle_state
        from nems_open.industrial.standin import Reference, make_standin
        from nems_open.industrial.year import run_year, start_state
        dumps = [y for y in self.DUMP_YEARS if y <= year and oracle_state.available("ys_in", y - BASEYR + 1, "ind")]
        if not dumps:
            raise FileNotFoundError("the ported industrial year loop starts from the oracle's IND state (oracle/build_wsl.sh ind): "
                                    f"no 'ys_in' dump at or before {year}")
        first = max(dumps)
        s, bufs = start_state(oracle_state.load("ys_in", first - BASEYR + 1, "ind"))
        standin = make_standin(Reference.load())
        state = IndustrialState(s, bufs, standin)
        for y in range(first, year):  # years between the dump and the start year, with EIA's inputs
            _set_year(s, y)
            inputs.apply(s) if inputs is not None else None
            run_year(s, bufs, 2, standin)
        state.needs_first_iteration = True
        return state

    def iteration(self, state, year: int, itr: int, inputs: Inputs) -> None:
        if self.ind != "ported":
            return  # fixed at the oracle's values
        from nems_open.industrial.year import calibrate, run_iteration
        _set_year(state.s, year)
        inputs.apply(state.s)
        run_iteration(state.s, state.bufs, itr, itr == 2, state.standin)
        if itr == 2:
            state.s["ncrl"] = np.int32(1)
            calibrate(state.s, state.bufs)  # the reporting call that leaves next year's starting state

    def quantities(self, rows) -> dict:
        if self.ind != "ported":
            return rows
        s = rows.s
        return {k: s[k] for k in SECTOR_QUANTITIES["in"] if k in s}


class IndustrialState:
    """The ported industrial module's state: the working variables and the per-industry-region buffers."""

    def __init__(self, s: dict, bufs: dict, standin):
        self.s, self.bufs, self.standin = s, bufs, standin
        self.needs_first_iteration = False


def _set_year(s: dict, year: int) -> None:
    s["curiyr"] = np.int32(year - BASEYR + 1)
    s["curcalyr"] = np.int32(year)
    s["iyr"] = np.int32(year)


class InProcess:
    """A sector run in a worker process, so it can run while the next sector runs here.

    Same calls as the sector (iteration, quantities) on a handle; iteration() only sends
    the work, quantities() waits for it. The worker holds the sector's state and its own
    copy of the restart file; each iteration it gets the caller's input overrides."""

    def __init__(self, name: str, year: int, snapshot_path, options: dict | None = None):
        import multiprocessing as mp
        ctx = mp.get_context("spawn")
        self.conn, child = ctx.Pipe()
        self.proc = ctx.Process(target=_sector_worker, args=(child, name, year, str(snapshot_path), options),
                                daemon=True)
        # The worker needs only this package. Hide the caller's script from the spawn, which
        # would otherwise re-run its top level in the worker (a script with no main guard
        # would start a second run there).
        main = sys.modules["__main__"]
        saved = {k: main.__dict__[k] for k in ("__file__", "__spec__") if k in main.__dict__}
        main.__dict__.pop("__file__", None)
        main.__spec__ = None
        try:
            self.proc.start()
        finally:
            main.__dict__.update(saved)
        child.close()
        sector = SECTORS[name]
        self.name, self.suffix = sector.name, sector.suffix

    def iteration(self, handle, year: int, itr: int, inputs: Inputs) -> None:
        self.conn.send(("iteration", year, itr, inputs.overrides))

    def quantities(self, handle) -> dict:
        self.conn.send(("quantities",))
        ok, value = self.conn.recv()
        if not ok:
            raise RuntimeError(f"{self.name} worker failed: {value}")
        return value

    def close(self) -> None:
        if self.proc.is_alive():
            try:
                self.conn.send(("stop",))
            except OSError:
                pass
            self.proc.join(5)
            if self.proc.is_alive():
                self.proc.terminate()


def _sector_worker(conn, name: str, year: int, snapshot_path: str, options: dict | None = None) -> None:
    import traceback
    error = None
    try:
        inputs = Inputs(Snapshot(snapshot_path))
        sector = SECTORS[name](**(options or {}))
        state = sector.start(year, inputs)
    except Exception:
        error = traceback.format_exc()
    while True:
        msg = conn.recv()
        if msg[0] == "stop":
            return
        if error is not None:
            if msg[0] == "quantities":
                conn.send((False, error))
            continue
        try:
            if msg[0] == "iteration":
                _, y, itr, overrides = msg
                inputs.overrides = overrides
                sector.iteration(state, y, itr, inputs)
            else:
                conn.send((True, sector.quantities(state)))
        except Exception:
            error = traceback.format_exc()
            if msg[0] == "quantities":
                conn.send((False, error))


class TransportationSector:
    """SUBROUTINE TRAN (src/nems_open/transportation/tran.py).

    The oracle's transportation dumps are at the top of a year's first iteration, so a
    run that starts mid-year does that iteration first.

    ev_share: {calendar year: plug-in share of new LDV sales}, the EV lever. It shifts the
    plug-ins' utility in TALT2X (the powertrain choice) until consumers choose that share,
    from 2025 (TALT2X's first year); CAFE and GHG compliance can still hold the share
    above it, as in EIA's model, and stocks, VMT and fuel use follow."""
    name = "transportation"
    suffix = "tr"

    def __init__(self, ev_share: dict | None = None):
        self.ev_share = dict(ev_share or {})

    @staticmethod
    def dumped(year: int) -> bool:
        """Whether the oracle dumped the state this module starts from in that year."""
        from nems_open import oracle_state
        return oracle_state.available("tran_tail_out", year - BASEYR + 1, "tran")

    @classmethod
    def start_year(cls, year: int):
        """The latest dumped year at or before year, or None (then TRAN starts from files)."""
        return next((d for d in range(year, BASEYR, -1) if cls.dumped(d)), None)

    @classmethod
    def available(cls, year: int) -> bool:
        return True  # from files when there is no dump

    def start(self, year: int, inputs: Inputs | None = None):
        """From the dump for year, or from the latest earlier dump run forward on EIA's inputs
        (about 25 s an iteration). With no dump at or before year, from EIA's files: TRAN's
        first call in 1995 and three calls a year to year (transportation/initial_state.py,
        matches the oracle's state; about 30 min to 2025)."""
        from nems_open.transportation import initial_state, tran
        d = self.start_year(year)
        if d is None:
            s, carry = initial_state.initial_state()
            if self.ev_share:
                s["_ev_share_target"] = self.ev_share
            initial_state.run(year, state=(s, carry))
            return {"s": s, "carry": carry, "next_itr": 1}
        s, carry = tran.start_from_dump(d - BASEYR + 1)
        if self.ev_share:
            s["_ev_share_target"] = self.ev_share
        t = {"s": s, "carry": carry, "next_itr": 1}
        if d < year:
            inputs = inputs or Inputs()
            for y in range(d, year):
                self.iteration(t, y, 2, inputs)  # both iterations from a fresh start
                t["next_itr"] = 1
        return t

    def iteration(self, t, year: int, itr: int, inputs: Inputs) -> None:
        from nems_open.transportation import tran
        s = t["s"]
        # A fresh start is at iteration 1 even when the runner asks for iteration 2.
        for i in range(min(t["next_itr"], itr), itr + 1):
            s["curcalyr"], s["curiyr"], s["curitr"] = year, year - BASEYR + 1, i
            apply_transportation(inputs, s)
            tran.tran(s, t["carry"])
            if self.ev_share:
                share_ev_charging(inputs, s)
        t["next_itr"] = itr + 1

    def quantities(self, t) -> dict:
        return {k: t["s"][k] for k in SECTOR_QUANTITIES["tr"] if k in t["s"]}


# Inputs TRAN writes itself: TRANREP is its own report block (an input only to the
# buildings modules), and TMPGNEW fills zero E85 prices from gasoline (PETTR) and TMISC
# the US methanol price (PMETR), so EIA's restart copies of those differ from TRAN's.
TRAN_WRITES = ("pettr", "pmetr")


def share_ev_charging(inputs: Inputs, s: dict) -> None:
    """Hand this year's TRQ_ELEC from TRAN to the buildings modules. EV charging reaches the
    grid through them (EIA's QELRS and QELCM add TRQ_ELEC; QELTR is passenger rail only), and
    they otherwise read EIA's copy, so an EV share target would cut gasoline and add no load.
    As in NEMS's module order they see it on their next iteration. Only with a target: without
    one the buildings keep EIA's copy and stay bit-identical to the oracle."""
    full = inputs.by_var["trq_elec"]
    trq = inputs.overrides.get(full)
    if trq is None:
        trq = inputs.overrides[full] = np.array(inputs.snapshot[full])
    j = int(s["curiyr"]) - 1
    trq[:, :, j] = s["trq_elec"].a[:, :, j]


def apply_transportation(inputs: Inputs, s: dict) -> None:
    """Inputs.apply for TRAN's state. Routines that include AEUSPRC or ANGTDM see those
    blocks under a prefix (oracle/hooks_tran.py ALT_INCLUDES); the plain names are EUSPRC
    and NGTDMOUT, which are not demand inputs, so an AEUSPRC input goes to the prefixed copy."""
    plain = {k: v for k, v in s.items() if not k.startswith("aeusprc__") and k not in TRAN_WRITES}
    aeus = {k[len("aeusprc__"):]: v for k, v in s.items() if k.startswith("aeusprc__")}
    inputs.apply({k: v for k, v in plain.items()
                  if not inputs.by_var.get(k, "").startswith(("AEUSPRC/", "TRANREP/"))})
    inputs.apply({k: v for k, v in aeus.items() if inputs.by_var.get(k, "").startswith("AEUSPRC/")})


# NEMS calls the demand modules in this order (RESD, COMM, IND, TRAN). None marks
# a module not ported yet; its QBLK arrays keep EIA's values. Industrial is a slot
# (see IndustrialSector): it runs only when asked for by name.
SECTORS = {
    "residential": ResidentialSector,
    "commercial": CommercialSector,
    "industrial": IndustrialSector,
    "transportation": TransportationSector,
}

# The fuel rows each sector owns in QBLK (QPRxx is in QMORE).
SECTOR_QUANTITIES = {
    "rs": ("qelrs", "qngrs", "qgfrs", "qgirs", "qclrs", "qdsrs", "qksrs", "qlgrs", "qprrs", "qbmrs", "qgers",
           "qstrs", "qpvrs"),
    "cm": ("qelcm", "qngcm", "qgfcm", "qgicm", "qclcm", "qmgcm", "qdscm", "qkscm", "qlgcm",
           "qprcm", "qrlcm", "qrscm", "qbmcm", "qstcm", "qpvcm"),
    "in": ("qelin", "qngin", "qgfin", "qgiin", "qngpin", "qlpin", "qclin", "qmcin", "qciin", "qmgin", "qdsin",
           "qksin", "qlgin", "qetin", "qbuin", "qprin", "qisin", "qppin", "qrsin", "qrlin", "qpfin", "qsgin",
           "qpcin", "qasin", "qotin", "qluin", "qsulfurin", "qh2in", "qhoin", "qgein", "qbmin", "qmsin", "qstin",
           "qpvin", "qwiin"),
    # TINTEG's QBLK rows (QPRTR is in QMORE), and TRAN's natural gas and residual splits.
    "tr": ("qmgtr", "qmetr", "qettr", "qngtr", "qgftr", "qlgtr", "qprtr", "qeltr", "qh2tr", "qdstr", "qjftr",
           "qottr", "qrltr", "qrhtr", "qrstr"),
}
# SUMQAS shares the Pacific division to California for these rows.
CALIFORNIA_SHARED = ("qelrs", "qelcm", "qngrs", "qngcm", "qclrs", "qclcm", "qmgcm", "qdsrs", "qdscm", "qksrs",
                     "qkscm", "qlgrs", "qlgcm", "qrscm", "qgers", "qbmrs", "qbmcm", "qstrs", "qstcm", "qpvrs", "qpvcm",
                     "qeltr", "qngtr", "qmgtr", "qjftr", "qdstr", "qlgtr", "qrstr", "qottr", "qmetr", "qettr",
                     "qelin", "qngin", "qlpin", "qclin", "qmcin", "qmgin", "qdsin", "qksin", "qlgin", "qrsin", "qpfin",
                     "qsgin", "qpcin", "qasin", "qotin", "qhoin", "qgein", "qbmin", "qmsin", "qstin", "qpvin", "qwiin",
                     "qciin")


def eia_quantities(snapshot: Snapshot) -> dict:
    """Every QBLK and QMORE array from EIA's run, as float32 copies keyed by lowercase name."""
    out = {}
    for full in snapshot.names():
        block, _, var = full.partition("/")
        if block in ("QBLK", "QMORE"):
            out[var.lower()] = snapshot[full].astype(np.float32).copy()
    return out


def sum_quantities(q: dict, suffix: str, y: int, calshr) -> None:
    """SUMQAS for one sector's rows in year index y (q arrays are 0-based (region, year))."""
    j = y - 1
    for k in SECTOR_QUANTITIES[suffix]:
        a = q[k]
        a[MNUMCR - 1, j] = np.float32(0.0)
        for r in range(MNUMCR - 2):
            a[MNUMCR - 1, j] = np.float32(a[MNUMCR - 1, j] + a[r, j])
        a[9, j] = 0.0
        if y >= MSEDYR and k in CALIFORNIA_SHARED:
            a[9, j] = np.float32(a[8, j] * calshr(k[1:] + "_shr")[j])
    g = lambda k: q[k][:, j]
    if suffix == "rs":
        q["qtprs"][:, j] = g("qdsrs") + g("qksrs") + g("qlgrs")
        q["qtrrs"][:, j] = g("qbmrs") + g("qstrs") + g("qpvrs") + g("qgers")
        q["qtsrs"][:, j] = g("qelrs") + g("qngrs") + g("qclrs") + g("qtprs") + g("qtrrs")
    elif suffix == "tr":
        # SUMQAS rebuilds residual from its two grades after the California shares, so
        # California's QRSTR ends up QRLTR + QRHTR = 0.
        q["qrstr"][:, j] = g("qrltr") + g("qrhtr")
        q["qtptr"][:, j] = g("qmgtr") + g("qjftr") + g("qdstr") + g("qlgtr") + g("qrstr") + g("qottr")
        q["qtrtr"][:, j] = g("qettr")
        q["qtstr"][:, j] = (g("qeltr") + g("qngtr") + g("qgptr") + g("qtptr") + g("qmetr") + g("qettr") + g("qh2tr")
                            + g("qnglq"))
    elif suffix == "cm":
        q["qtpcm"][:, j] = g("qmgcm") + g("qdscm") + g("qkscm") + g("qlgcm") + g("qrscm")
        q["qtrcm"][:, j] = g("qbmcm") + g("qstcm") + g("qpvcm")
        q["qtscm"][:, j] = g("qelcm") + g("qngcm") + g("qclcm") + g("qtpcm") + g("qtrcm")
    elif suffix == "in":
        q["qtpin"][:, j] = (g("qmgin") + g("qdsin") + g("qksin") + g("qlgin") + g("qrsin")
                            + g("qpfin") + g("qsgin") + g("qpcin") + g("qasin") + g("qotin"))
        q["qtrin"][:, j] = g("qhoin") + g("qgein") + g("qbmin") + g("qmsin") + g("qstin") + g("qpvin") + g("qwiin")
        q["qtsin"][:, j] = (g("qelin") + g("qngin") + g("qlpin") + g("qclin") + g("qmcin") + g("qciin")
                            + g("qtpin") + g("qtrin"))


class DemandRunner:
    """The demand side of NEMS for a run of years, on fixed prices.

    Starts at `year` from the oracle's state at the top of that year's final
    iteration. `run_year()` finishes that iteration; each later call runs the
    next year with NEMS's two iterations.
    """

    def __init__(self, year: int, inputs: Inputs | None = None,
                 sectors=("residential", "commercial"), parallel: bool = False,
                 commercial_from_files: bool = False, commercial_levers=None, ev_share: dict | None = None,
                 residential_levers=None, ind: str = "oracle"):
        self.inputs = inputs or Inputs()
        self.year = year
        self.first_iteration = 2
        self.sectors = []
        names = [name for name in SECTORS if name in sectors]
        for name in names:
            if SECTORS[name] is None:
                raise NotImplementedError(f"{name} demand is not ported yet")
        # parallel: every sector but the last runs in a worker process (started first, so
        # it loads while this process starts the last one). Results are the same.
        options = {"residential": {"levers": residential_levers},
                   "commercial": {"from_files": commercial_from_files, "levers": commercial_levers},
                   "transportation": {"ev_share": ev_share}, "industrial": {"ind": ind}}
        workers = {name: InProcess(name, year, self.inputs.snapshot.path, options.get(name))
                   for name in names[:-1]} if parallel else {}
        for name in names:
            if name in workers:
                self.sectors.append((workers[name], None))
            else:
                sector = SECTORS[name](**options.get(name, {}))
                self.sectors.append((sector, sector.start(year, self.inputs)))
        self.q = eia_quantities(self.inputs.snapshot)

    def close(self) -> None:
        """Stop the worker processes (parallel=True)."""
        for sector, _ in self.sectors:
            if isinstance(sector, InProcess):
                sector.close()

    def run_year(self) -> int:
        """Run the current year; returns it. Results are in `self.q`."""
        year, y = self.year, self.year - BASEYR + 1
        for itr in range(1, 3):
            for sector, state in self.sectors:
                # a module started from the files has not run this year at all: it takes iteration 1 too
                if itr < self.first_iteration and not getattr(state, "needs_first_iteration", False):
                    continue
                sector.iteration(state, year, itr, self.inputs)
        for _, state in self.sectors:
            if hasattr(state, "needs_first_iteration"):
                state.needs_first_iteration = False
        calshr = lambda name: self.inputs.snapshot[f"CALSHR/{name}"]
        for sector, state in self.sectors:
            for k, v in sector.quantities(state).items():
                self.q[k][:MNUMCR - 2, y - 1] = v[1:MNUMCR - 2, y]
            sum_quantities(self.q, sector.suffix, y, calshr)
        self.year += 1
        self.first_iteration = 1
        return year

    def run_to(self, last_year: int) -> None:
        while self.year <= last_year:
            self.run_year()

    def totals(self, year: int) -> dict:
        """US delivered energy by sector (QTSxx), trillion Btu."""
        return {name: float(self.q[f"qts{SUFFIX[name]}"][MNUMCR - 1, year - BASEYR]) for name in SUFFIX}


SUFFIX = {"residential": "rs", "commercial": "cm", "industrial": "in", "transportation": "tr"}


def run_year(year: int, inputs: Inputs | None = None, sectors=("residential", "commercial")) -> dict:
    """Run the ported demand modules for one year. Returns the QBLK-style arrays
    {name: (region, year) array}: the modules' rows for that year, EIA's elsewhere."""
    runner = DemandRunner(year, inputs, sectors)
    runner.run_year()
    return runner.q


def main(argv=None) -> None:
    year = int((argv or sys.argv[1:] or ["2030"])[0])
    runner = DemandRunner(year)
    runner.run_year()
    eia = eia_quantities(runner.inputs.snapshot)
    j = year - BASEYR
    print(f"{year}, US, trillion Btu        ours        EIA     error")
    for sector, _ in runner.sectors:
        for k in SECTOR_QUANTITIES[sector.suffix] + tuple(f"qt{x}{sector.suffix}" for x in "prs"):
            ours, ref = float(runner.q[k][MNUMCR - 1, j]), float(eia[k][MNUMCR - 1, j])
            err = abs(ours - ref) / abs(ref) if ref else 0.0
            print(f"{sector.name:12} {k:8} {ours:11.2f} {ref:10.2f} {err:9.2e}")


if __name__ == "__main__":
    main()
