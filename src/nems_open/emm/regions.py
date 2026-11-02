"""EMM regions and how they map to census divisions.

NEMS numbers its 25 EMM regions 1..25, then 26 Alaska, 27 Hawaii and 28 for the US total
(MNUMNR=28). Census arrays have 11 slots: divisions 1..9, 10 California, 11 US total.
Python indices here are zero-based, so EMM region 1 (TRE) is index 0 and the US row is 27.
"""

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from nems_open.emm import db

NUM_EMM = 25          # contiguous-US EMM regions (UNRGNS)
NUM_NERC = 28         # MNUMNR: 25 + Alaska + Hawaii + US total
US_ROW = 27           # zero-based index of the US total
NUM_CENSUS = 11       # MNUMCR: 9 divisions + California + US total
NUM_SECTORS = 4       # residential, commercial, industrial, transportation


@dataclass(frozen=True)
class Region:
    number: int       # NEMS region number, 1..28
    name: str         # four-letter EMM name, e.g. "TRE"
    code: str         # one-character code used in EIA's text files

    @property
    def index(self) -> int:
        return self.number - 1


@lru_cache(maxsize=1)
def regions() -> tuple[Region, ...]:
    """All 28 rows, ordered by NEMS region number."""
    t = db.table("V_EMM_DIMS")
    rows = sorted(zip(t["EMM_REG"], t["RGN_NAM"], t["UPRGCD"]))
    return tuple(Region(int(n), str(name), str(code)) for n, name, code in rows)


def names() -> list[str]:
    return [r.name for r in regions()]


@lru_cache(maxsize=1)
def census_to_emm_weights() -> np.ndarray:
    """Base-year load weights, shape (28, 11, 4): EMM region, census division, sector.

    These are the raw numbers EIA stores in V_EMM_LDSMSTR_RGN_CEN (MappCtoN).
    """
    t = db.table("V_EMM_LDSMSTR_RGN_CEN")
    w = np.zeros((NUM_NERC, NUM_CENSUS, NUM_SECTORS))
    w[t["EMM_REG"] - 1, t["CENSUS"] - 1, t["SECTOR"] - 1] = t["MappCtoN"]
    return w


@lru_cache(maxsize=1)
def emm_share_of_census() -> np.ndarray:
    """Share of each EMM region's load that sits in each census division, shape (28, 11, 4).

    Divisions 1..10 (California is slot 10) sum to one for every region and sector.
    This is NEMS's MAPPNTOC; multiply it by regional sales to get sales by division.
    """
    w = census_to_emm_weights().copy()
    w[:, 10:, :] = 0.0
    total = w.sum(axis=1, keepdims=True)
    return np.divide(w, total, out=np.zeros_like(w), where=total > 0)
