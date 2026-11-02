"""Load shapes and load-model inputs (LDSM).

EIA describes a year of load as 36 typical days: 12 months times 3 day types (1 and 2 are
the common days, 3 is the peak day), each with 24 hours. Every day type has a weight, the
number of calendar days it stands for (they add to 365). A load shape gives each hour's
share of annual energy, so shape * weight summed over all hours is 1.
"""

from functools import lru_cache

import numpy as np

from nems_open.emm import db, regions

MONTHS, DAY_TYPES, HOURS = 12, 3, 24
HOURS_PER_YEAR = 8760


@lru_cache(maxsize=1)
def day_weights() -> np.ndarray:
    """Calendar days represented by each typical day, shape (12, 3). Adds to 365."""
    t = db.table("V_SYS_LOAD_WEIGHTS")
    w = np.zeros((MONTHS, DAY_TYPES))
    w[t["Month"] - 1, t["DAY"] - 1] = t["WEIGHTS"]
    return w


@lru_cache(maxsize=1)
def regional_shapes() -> np.ndarray:
    """Share of annual energy in each typical hour, shape (25, 12, 3, 24), for the 25 EMM regions.

    Each region's shape times `day_weights()`, summed, is 1 (to float32 rounding).
    """
    t = db.table("V_SYS_LOAD_by_EMM_REGION")
    shape = np.zeros((regions.NUM_EMM, MONTHS, DAY_TYPES, HOURS))
    shape[t["EMM_REG"] - 1, t["Month"] - 1, t["DAY"] - 1, t["HOUR"] - 1] = t["PCT"]
    return shape


def load_factor() -> np.ndarray:
    """Annual load factor implied by each region's shape (average load over the peak hour), shape (25,)."""
    return 1.0 / (HOURS_PER_YEAR * regional_shapes().max(axis=(1, 2, 3)))


def hourly_profile(region: int, scale_gwh: float = 1.0) -> np.ndarray:
    """A region's 8760-hour chronological load for a given annual energy, in the same unit as scale_gwh per hour.

    Typical days are laid out month by month: the weekday-type days, then the second day type,
    then the peak day, repeated by weight. This is a convenience for plots and tests; the
    optimization works on the 36 typical days directly.
    """
    shape = regional_shapes()[region - 1]
    w = day_weights().astype(int)
    hours = [shape[m, d] for m in range(MONTHS) for d in range(DAY_TYPES) for _ in range(w[m, d])]
    return np.concatenate(hours) * scale_gwh


@lru_cache(maxsize=1)
def end_use_shapes() -> dict[int, np.ndarray]:
    """Load shape of each end use, {shape index: array (12, 3, 24)}, in the same units as regional shapes."""
    t = db.table("V_SYS_LOAD_by_EndUse")
    out = {}
    for idx in np.unique(t["LS_INDEX"]):
        sel = t["LS_INDEX"] == idx
        a = np.zeros((MONTHS, DAY_TYPES, HOURS))
        a[t["Month"][sel] - 1, t["DAY"][sel] - 1, t["HOUR"][sel] - 1] = t["PCT"][sel]
        out[int(idx)] = a
    return out


@lru_cache(maxsize=1)
def end_use_table() -> dict[str, np.ndarray]:
    """Base-year load by EMM region, sector and end use (V_EMM_LDSMSTR_EU_SECT).

    Columns: region (1..25), sector (1 residential, 2 commercial, 3 industrial, 4 transport),
    end_use (index within the sector), shape_name (LDSM region shape), base_year_load, name.
    The input file stores zeros for base_year_load; NEMS fills it from the demand modules.
    """
    t = db.table("V_EMM_LDSMSTR_EU_SECT")
    return {"region": t["EMM_REG"], "sector": t["SECTOR"], "end_use": t["EUSE"],
            "shape_name": t["LSRnam"], "base_year_load": t["BSYRLD"], "name": t["EMM_NM"]}


@lru_cache(maxsize=1)
def region_parameters() -> dict[str, np.ndarray]:
    """Per-region LDSM scalars, shape (25,): transmission and distribution loss fraction and the
    reserve-margin efficiency factor, ordered by EMM region number."""
    t = db.table("V_EMM_LDSMSTR_RGN")
    order = np.argsort(t["EMM_REG"])
    return {"td_loss": t["UQTDLS"][order], "mefac": t["MEFAC"][order]}
