"""COAL_EXPECT: fill the electricity planners' coal expectations horizon.

From source/util_tools.f90. ECP looks ECP_D_FPH (30) years ahead. For each coal supply curve and coal
demand region, the transport escalators for the current model year's future slots 1..30 are copied from
the current-year values of those future years, using "prior run values, or perfect foresight". Beyond the
last year of the AEO (AEOLSTYR, 2050) the last year's value is used.

Arrays are (curve, slot, year, region) with slot 0 the current year, as USO2GRP/XCL_1TESC and XCL_2TESC
in the restart file. Year index 0 is 1990.
"""

import numpy as np

BASE_YEAR = 1990
HORIZON = 30
LAST_YEAR = 2050


def coal_expect(array: np.ndarray, curiyr: int, last_year: int = LAST_YEAR) -> np.ndarray:
    """Return `array` with slots 1..30 of year index `curiyr` (1-based, as NEMS's CURIYR) filled in.

    Does not modify its argument. Fortran: xcl_1tesc(icl,iy,curiyr,j) = xcl_1tesc(icl,0,curiyr+iy,j) while
    curiyr+iy <= ilast, else the value at ilast, where ilast = AEOLSTYR - BASEYR + 1.
    """
    out = array.copy()
    ilast = last_year - BASE_YEAR + 1
    for iy in range(1, HORIZON + 1):
        src = curiyr + iy if curiyr + iy <= ilast else ilast
        out[:, iy, curiyr - 1, :] = array[:, 0, src - 1, :]
    return out
