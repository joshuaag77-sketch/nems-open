"""Phase 2: the demand modules wired into one runner, fed by EIA's prices.

For a year, the runner calls each ported demand module in NEMS's order
(residential, commercial, industrial, transportation), with prices, macro
drivers and other modules' outputs taken from EIA's AEO2026 restart file, and
writes their fuel use into QBLK-style arrays. Change an input (`Inputs`
overrides) and the modules respond; leave it alone and they reproduce EIA.

How a year runs: each module starts from the oracle's state at the top of that
year's final NEMS iteration (its input tables and its own history before that
year; the file readers are not all ported yet), every input array is
overwritten from `Inputs`, and the module's chain runs once. `DemandRunner`
can then keep going year by year, two iterations a year, carrying each
module's state the way the Fortran does.

After the modules run, `sum_quantities` does the part of NEMS's SUMQAS
(source/util_sumqas.f90) that touches these sectors: US totals as the sum of
the nine census divisions, California as a share of the Pacific division, and
each sector's petroleum, renewable and total rows (QTP, QTR, QTS).

Transportation is not ported yet: its QBLK arrays keep EIA's values. Industrial is
a slot (`IndustrialSector`): asked for by name, it supplies the industrial oracle's
fuel use until IND's year loop is ported. To add a sector, write a class like
`ResidentialSector` (available, start, iteration, quantities) and put it in SECTORS.

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

    @staticmethod
    def available(year: int) -> bool:
        """Whether the oracle dumped the state this module starts from in that year."""
        from nems_open import oracle_state
        return oracle_state.available("yb_in", year - BASEYR + 1, "resd")

    def start(self, year: int, inputs=None):
        from nems_open.residential import resd
        return resd.start_from_dump(year - BASEYR + 1)

    def iteration(self, s, year: int, itr: int, inputs: Inputs) -> None:
        from nems_open.residential import resd
        from nems_open.residential.reports import nhtshr, resdrp2
        s["curcalyr"], s["curiyr"], s["curitr"] = year, year - BASEYR + 1, itr
        inputs.apply(s)
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

    Ported so far (branch `industrial`): CALBSC, CALSTOT and INDTOTAL, the boiler and
    fuel accounting inside ISEAM's loop over 24 industries and 4 Census regions. The
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
    ported = ("CALBSC", "CALSTOT", "INDTOTAL")

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

    def start(self, year: int, inputs=None) -> dict:
        d = self.oracle_out()
        if d is None:
            raise FileNotFoundError("industrial oracle output not found (oracle/run_ind/out/q*in.bin)")
        rows = {}
        for k in SECTOR_QUANTITIES["in"]:
            raw = np.fromfile(d / f"{k}.bin", dtype=np.float32)
            rows[k] = FArray(raw.reshape((MNUMCR, raw.size // MNUMCR), order="F"))
        return rows

    def iteration(self, rows, year: int, itr: int, inputs: Inputs) -> None:
        pass  # fixed at the oracle's values until IND's year loop is ported

    def quantities(self, rows) -> dict:
        return rows


# NEMS calls the demand modules in this order (RESD, COMM, IND, TRAN). None marks
# a module not ported yet; its QBLK arrays keep EIA's values. Industrial is a slot
# (see IndustrialSector): it runs only when asked for by name.
SECTORS = {
    "residential": ResidentialSector,
    "commercial": CommercialSector,
    "industrial": IndustrialSector,
    "transportation": None,  # source/tran*.f, being ported
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
}
# SUMQAS shares the Pacific division to California for these rows.
CALIFORNIA_SHARED = ("qelrs", "qelcm", "qngrs", "qngcm", "qclrs", "qclcm", "qmgcm", "qdsrs", "qdscm", "qksrs",
                     "qkscm", "qlgrs", "qlgcm", "qrscm", "qgers", "qbmrs", "qbmcm", "qstrs", "qstcm", "qpvrs", "qpvcm",
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
                 sectors=("residential", "commercial"), commercial_from_files: bool = False, commercial_levers=None):
        self.inputs = inputs or Inputs()
        self.year = year
        self.first_iteration = 2
        self.sectors = []
        for name in SECTORS:
            if name in sectors:
                if SECTORS[name] is None:
                    raise NotImplementedError(f"{name} demand is not ported yet")
                sector = (SECTORS[name](commercial_from_files, commercial_levers) if name == "commercial"
                          else SECTORS[name]())
                self.sectors.append((sector, sector.start(year, self.inputs)))
        self.q = eia_quantities(self.inputs.snapshot)

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
