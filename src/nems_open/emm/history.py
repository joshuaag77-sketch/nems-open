"""Historical EMM data (2009 to 2024) from the input database, on NEMS's year grid.

Every function returns an array whose last axis is year 1990..2050 (61 entries, index 0 is
1990) and whose first axis is the NEMS region (28 EMM rows or 11 census rows). Years with no
history are NaN. Units follow EIA's tables: generation in billion kWh, emissions in
thousand short tons (SO2, NOx) or short tons (CO2) as stored, fuel use in trillion Btu.
"""

import numpy as np

from nems_open.emm import db, regions

FIRST_YEAR = 1990
NUM_YEARS = 61


def _grid(rows: int, region, year, value, keep=None) -> np.ndarray:
    """Sum `value` into an (rows, 61) array at [region-1, year-1990]; NaN where nothing is stored."""
    out = np.full((rows, NUM_YEARS), np.nan)
    for i, (r, y, v) in enumerate(zip(region, year, value)):
        if (keep is not None and not keep[i]) or np.isnan(v):
            continue
        cell = out[r - 1, y - FIRST_YEAR]
        out[r - 1, y - FIRST_YEAR] = v if np.isnan(cell) else cell + v
    return out


def emissions(pollutant: str) -> np.ndarray:
    """Power-sector emissions by EMM region, shape (28, 61). pollutant: 'so2', 'nox' or 'co2'."""
    col = {"so2": "HEMSO2R", "nox": "HEMNOXR", "co2": "HEMCO2R"}[pollutant.lower()]
    t = db.table("V_EMM_ELDATYR2")
    return _grid(regions.NUM_NERC, t["EMM_REG"], t["YEAR"], t[col])


def sales(sector: str) -> np.ndarray:
    """Electricity sales by EMM region, shape (28, 61). sector: 'rs', 'cm', 'in', 'tr' or 'as' (all)."""
    t = db.table("V_EMM_ELDATYR2")
    return _grid(regions.NUM_NERC, t["EMM_REG"], t["YEAR"], t[f"HEL{sector.upper()}NR"])


def prices(sector: str) -> np.ndarray:
    """Retail electricity price by EMM region, shape (28, 61), in the base-year dollars EIA stores."""
    t = db.table("V_EMM_ELDATYR_PR")
    return _grid(regions.NUM_NERC, t["EMM_REG"], t["YEAR"], t[f"HPEL{sector.upper()}NR"])


def generation(column: str, owners=(1, 2, 3)) -> np.ndarray:
    """Generation by EMM region, shape (28, 61). `column` is a V_EMM_ELDATYR name such as 'HGENNU'
    (nuclear) or 'HGENCC' (combined cycle). `owners` picks ownership classes 1 to 3."""
    t = db.table("V_EMM_ELDATYR")
    keep = np.isin(t["OWNERSHIP"], list(owners))
    return _grid(regions.NUM_NERC, t["EMM_REG"], t["YEAR"], t[column], keep)


def fuel_use_census(fuel: str) -> np.ndarray:
    """Fuel burned for power by census division 1..9, shape (11, 61). fuel: 'cl', 'ng', 'ds' or 'rs'."""
    t = db.table("H_ELDATYR_CENSUS")
    return _grid(regions.NUM_CENSUS, t["CENSUS"], t["YEAR"], t[f"HFL{fuel.upper()}CR"])
