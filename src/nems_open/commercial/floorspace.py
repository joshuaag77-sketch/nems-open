"""Commercial floorspace: port of COMFloorspace and CMSurvRate in source/comm.f.

Starts from the 2018 CBECS survey stock, backcasts each age cohort to the floorspace
originally built, then rolls forward year by year: old buildings retire on a
logistic survival curve, and new construction fills the gap so total floorspace
grows at the macro model's rate for the matching building type.

Units are million square feet unless noted. Indexing follows NEMS: year index
y = calendar year - 1989 (1990 is y=1), regions 1-9 are census divisions,
region 11 is the US total.
"""

from dataclasses import dataclass

import numpy as np

from nems_open.fortran_io import HEADER_RECORDS, ListDirectedReader
from nems_open.paths import INPUT

BASEYR = 1990
MNUMCR = 11  # 9 census divisions, California, US
MNUMYR = 61  # 1990-2050
NUM_DIV = MNUMCR - 2
CBECS_YEAR = 2018
OLDEST_VINTAGE = 1824
NUM_BLDG = 11
NUM_VINTAGE = 10
FIRST_YEAR = CBECS_YEAR - BASEYR + 2  # CMFirstYr, first projected year (2019)

# NEMS building types, CBECS order:
# assembly, education, food sales, food service, health care, lodging,
# large office, small office, mercantile and service, warehouse, other.
#
# Each NEMS type grows at a blend of macro-model (MAM) floorspace growth rates.
# MAM types: 1 amusement and religion, 2 education, 3 health care, 4 hotel and dorm,
# 5 office, 6 automotive, 7 stores, 8 warehouse, 9 public and misc nonresidential.
GROWTH_MAP = [
    {1: 1.0},
    {2: 1.0},
    {7: 1.0},
    {7: 1.0},
    {3: 1.0},
    {4: 0.7776, 3: 0.2224},
    {5: 0.9344, 3: 0.0656},
    {5: 0.8625, 3: 0.1375},
    {6: 0.2763, 7: 0.7237},
    {8: 1.0},
    {9: 1.0},
]


def _yidx(calendar_year: int) -> int:
    return calendar_year - (BASEYR - 1)


@dataclass
class FloorspaceInputs:
    cbecs: np.ndarray  # (div, bldg, vintage) CBECS 2018 floorspace
    vintage: np.ndarray  # (div, bldg, vintage) median construction year
    avg_age: np.ndarray  # (bldg,) median lifetime, years
    gamma: np.ndarray  # (bldg,) survival curve shape

    @classmethod
    def load(cls, cdm_dir=INPUT / "cdm"):
        cbecs = np.zeros((NUM_DIV, NUM_BLDG, NUM_VINTAGE))
        r = ListDirectedReader(cdm_dir / "kflspc.txt", HEADER_RECORDS)
        for b in range(NUM_BLDG):
            for v in range(NUM_VINTAGE):
                row = r.read(NUM_DIV)
                if row is not None:
                    cbecs[:, b, v] = row

        vintage = np.full((NUM_DIV, NUM_BLDG, NUM_VINTAGE), OLDEST_VINTAGE, dtype=int)
        r = ListDirectedReader(cdm_dir / "kvint.txt", HEADER_RECORDS)
        for b in range(NUM_BLDG):
            for d in range(NUM_DIV):
                row = r.read(NUM_VINTAGE, int)
                if row is not None:
                    vintage[d, b, :] = np.maximum(row, OLDEST_VINTAGE)

        r = ListDirectedReader(cdm_dir / "kbldg.txt", HEADER_RECORDS)
        avg_age = np.array(r.read(NUM_BLDG))
        r.skip()
        gamma = np.array(r.read(NUM_BLDG))
        return cls(cbecs, vintage, avg_age, gamma)


def survival(age, avg_age, gamma):
    """CMSurvRate: share of floorspace still standing at a given age."""
    return 1.0 / (1.0 + (age / avg_age) ** gamma)


class Floorspace:
    """Holds the floorspace state that COMFloorspace keeps across years.

    Arrays use 1-based NEMS indices on purpose so contributors can check each line
    against the Fortran. Construction years run from 1824, so `new` is offset.
    """

    NEW_OFFSET = -_yidx(OLDEST_VINTAGE)  # position of year index 0

    def __init__(self, inputs: FloorspaceInputs):
        self.inp = inputs
        n_new = MNUMYR + 1 + self.NEW_OFFSET
        self.new = np.zeros((MNUMCR + 1, NUM_BLDG + 1, n_new))  # CMNewFloorSpace
        self.total = np.zeros((MNUMCR + 1, NUM_BLDG + 2, MNUMYR + 1))  # CMTotalFlspc
        self.surviving = np.zeros((MNUMCR + 1, NUM_BLDG + 1, MNUMYR + 1))  # SurvFloorTotal
        self.aged_new = np.zeros((MNUMCR + 1, NUM_BLDG + 1, MNUMYR + 1))  # AgedNew
        self._initialise()

    def _new_ix(self, y: int) -> int:
        return y + self.NEW_OFFSET

    def _surv(self, b: int, age) -> np.ndarray:
        return survival(age, self.inp.avg_age[b - 1], self.inp.gamma[b - 1])

    def _initialise(self):
        """First-year setup: backcast CBECS stock to original construction."""
        inp = self.inp
        y_cbecs = _yidx(CBECS_YEAR)
        for r in range(1, NUM_DIV + 1):
            for b in range(1, NUM_BLDG + 1):
                for v in range(NUM_VINTAGE):
                    orig = int(inp.vintage[r - 1, b - 1, v])
                    frac = self._surv(b, float(CBECS_YEAR - orig))
                    self.new[r, b, self._new_ix(_yidx(orig))] = inp.cbecs[r - 1, b - 1, v] / frac
        for r in range(1, NUM_DIV + 1):
            for b in range(1, NUM_BLDG + 1):
                self.total[r, b, y_cbecs] = inp.cbecs[r - 1, b - 1, :].sum()
            self.total[r, NUM_BLDG + 1, y_cbecs] = self.total[r, 1 : NUM_BLDG + 1, y_cbecs].sum()

    def step(self, y: int, mc_commflsp: np.ndarray) -> None:
        """Project year y. mc_commflsp is MACOUT/mc_commflsp, shape (11, 14, 61)."""
        first = _yidx(OLDEST_VINTAGE)
        years = np.arange(first, y)
        ages = (y - years).astype(float)
        post_cbecs = years > _yidx(CBECS_YEAR)
        for r in range(1, NUM_DIV + 1):
            for b in range(1, NUM_BLDG + 1):
                built = self.new[r, b, self._new_ix(first) : self._new_ix(y)]
                alive = built * self._surv(b, ages)
                self.surviving[r, b, y] = alive.sum()
                self.aged_new[r, b, y] = alive[post_cbecs].sum()

            for b in range(1, NUM_BLDG + 1):
                rate = sum(w * mc_commflsp[r - 1, m - 1, y - 1] for m, w in GROWTH_MAP[b - 1].items())
                added = self.total[r, b, y - 1] * (rate + 1.0) - self.surviving[r, b, y]
                added = max(added, 0.0)
                self.new[r, b, self._new_ix(y)] = added
                self.total[r, b, y] = added + self.surviving[r, b, y]
            self.total[r, NUM_BLDG + 1, y] = self.total[r, 1 : NUM_BLDG + 1, y].sum()

        for b in range(1, NUM_BLDG + 1):
            self.surviving[MNUMCR, b, y] = self.surviving[1 : NUM_DIV + 1, b, y].sum()
            self.new[MNUMCR, b, self._new_ix(y)] = self.new[1 : NUM_DIV + 1, b, self._new_ix(y)].sum()

    def run(self, mc_commflsp: np.ndarray, last_year: int = MNUMYR) -> "Floorspace":
        for y in range(FIRST_YEAR, last_year + 1):
            self.step(y, mc_commflsp)
        return self

    # National report totals (COMMREP), billion square feet.
    def us_surviving(self, y: int) -> float:
        return self.surviving[MNUMCR, 1 : NUM_BLDG + 1, y].sum() / 1000.0

    def us_new(self, y: int) -> float:
        return self.new[MNUMCR, 1 : NUM_BLDG + 1, self._new_ix(y)].sum() / 1000.0
