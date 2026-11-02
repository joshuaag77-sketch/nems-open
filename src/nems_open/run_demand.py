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

Industrial and transportation are not ported yet: their QBLK arrays keep EIA's
values. To add one, write a class like `ResidentialSector` and put it in SECTORS.

    python -m nems_open.run_demand 2030
"""

import sys

import numpy as np

from nems_open.fortran_array import FArray
from nems_open.snapshot import Snapshot

BASEYR = 1990
MNUMCR = 11
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

    def start(self, year: int):
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

    def start(self, year: int):
        from nems_open.commercial.comm import Commercial
        return Commercial.start_from_dump(year - BASEYR + 1)

    def iteration(self, c, year: int, itr: int, inputs: Inputs) -> None:
        inputs.apply(c.s)
        c.iteration(year - BASEYR + 1, itr, inputs.array("MACOUT/mc_commflsp"))

    def quantities(self, c) -> dict:
        return c.qblk()


# NEMS calls the demand modules in this order (RESD, COMM, IND, TRAN). None marks
# a module not ported yet; its QBLK arrays keep EIA's values.
SECTORS = {
    "residential": ResidentialSector,
    "commercial": CommercialSector,
    "industrial": None,      # source/ind.f, being ported
    "transportation": None,  # source/tran*.f, being ported
}

# The fuel rows each sector owns in QBLK (QPRxx is in QMORE).
SECTOR_QUANTITIES = {
    "rs": ("qelrs", "qngrs", "qgfrs", "qgirs", "qclrs", "qdsrs", "qksrs", "qlgrs", "qprrs", "qbmrs", "qgers",
           "qstrs", "qpvrs"),
    "cm": ("qelcm", "qngcm", "qgfcm", "qgicm", "qclcm", "qmgcm", "qdscm", "qkscm", "qlgcm",
           "qprcm", "qrlcm", "qrscm", "qbmcm", "qstcm", "qpvcm"),
}
# SUMQAS shares the Pacific division to California for these rows.
CALIFORNIA_SHARED = ("qelrs", "qelcm", "qngrs", "qngcm", "qclrs", "qclcm", "qmgcm", "qdsrs", "qdscm", "qksrs",
                     "qkscm", "qlgrs", "qlgcm", "qrscm", "qgers", "qbmrs", "qbmcm", "qstrs", "qstcm", "qpvrs", "qpvcm")


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
    else:
        q["qtpcm"][:, j] = g("qmgcm") + g("qdscm") + g("qkscm") + g("qlgcm") + g("qrscm")
        q["qtrcm"][:, j] = g("qbmcm") + g("qstcm") + g("qpvcm")
        q["qtscm"][:, j] = g("qelcm") + g("qngcm") + g("qclcm") + g("qtpcm") + g("qtrcm")


class DemandRunner:
    """The demand side of NEMS for a run of years, on fixed prices.

    Starts at `year` from the oracle's state at the top of that year's final
    iteration. `run_year()` finishes that iteration; each later call runs the
    next year with NEMS's two iterations.
    """

    def __init__(self, year: int, inputs: Inputs | None = None,
                 sectors=("residential", "commercial")):
        self.inputs = inputs or Inputs()
        self.year = year
        self.first_iteration = 2
        self.sectors = []
        for name in SECTORS:
            if name in sectors:
                if SECTORS[name] is None:
                    raise NotImplementedError(f"{name} demand is not ported yet")
                sector = SECTORS[name]()
                self.sectors.append((sector, sector.start(year)))
        self.q = eia_quantities(self.inputs.snapshot)

    def run_year(self) -> int:
        """Run the current year; returns it. Results are in `self.q`."""
        year, y = self.year, self.year - BASEYR + 1
        for itr in range(self.first_iteration, 3):
            for sector, state in self.sectors:
                sector.iteration(state, year, itr, self.inputs)
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
