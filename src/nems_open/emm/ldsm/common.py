"""Parameters shared by the LDSM routines (dsmdimen, parametr, comparm).

LDSM works on shared COMMON blocks. A port gets the state as a dict of FArrays and
scalars keyed by lowercase Fortran name, from the oracle's dumps, and changes it in
place. Scalars are NumPy scalars of the Fortran type; `put` keeps that type.
"""

import numpy as np

from nems_open.residential.common import expf, logf, powf, powi  # noqa: F401 (shared float32 helpers)

f32 = np.float32
f64 = np.float64

# parametr
MNUMYR = 61
MNUMCR = 11
MNUMNR = 28
MNUMCGF = 13
MSEDYR = 34      # historical SEDS years
# dispinyr
HSTYEAR = 2010   # first year of historical overwrites
# comparm
CMNUMSERV = 10
CMNUMBLDG = 11
# dsmdimen
RES, COM, IND, TRA = 1, 2, 3, 4
MAXCRG = 9
ELINDEX, ELHEATX, ELWHEAX, ELCOOLX = 1, 2, 2, 1
ELSTOVX, ELDRYEX, ELSECHX = 3, 2, 2
UNCONFA = f32(292.83)       # 1 TBtu = 292.83 GWh
UNCONFAR = f32(292.83e-06)  # 1 MBtu = 292.83E-06 GWh


def put(s: dict, name: str, value):
    """Store a scalar with the Fortran type it was dumped with."""
    old = s.get(name)
    s[name] = old.dtype.type(value) if isinstance(old, np.generic) else value


def i(s: dict, name: str) -> int:
    """An integer scalar from the state, as a Python int for indexing."""
    return int(s[name])
