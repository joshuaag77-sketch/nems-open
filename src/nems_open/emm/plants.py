"""EMM's existing plant file: every generating unit EIA tracks (EIA-860 plus planned builds).

One row per unit, 27,337 units in AEO2026. Capacity is in MW as stored; the aggregate
helpers return GW to match NEMS's UCAP/UGEN arrays.
"""

from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from nems_open.emm import db, regions

# Ownership (TFOWN): 1 private utility, 2 public utility, 3 non-utility (NUG), 4 cogeneration.
OWNER_UTILITY = (1, 2)
OWNER_NUG = (3,)
OWNER_COGEN = (4,)

# TVIN, plant vintage: 1 existing, 2 planned, 3 unplanned (model-built), 6 uprate, 7 retrofit.
VINTAGE_EXISTING, VINTAGE_PLANNED = 1, 2

NEVER = 9999


@dataclass(frozen=True)
class Units:
    """Columns of the plant file as numpy arrays, one entry per unit."""
    region: np.ndarray        # operating EMM region 1..25 (TNOPER)
    owner_region: np.ndarray  # EMM region of the owning utility (TNOWN)
    owner: np.ndarray         # TFOWN
    vintage: np.ndarray       # TVIN
    efd_type: np.ndarray      # EFDcd, EFD plant type code, e.g. "CSC"
    ecp_type: np.ndarray      # ECPcd, ECP plant type code, e.g. "C7"
    name: np.ndarray          # plant name
    state: np.ndarray         # two-letter state
    summer_mw: np.ndarray     # TC_SUM
    winter_mw: np.ndarray     # TC_WIN
    nameplate_mw: np.ndarray  # TC_NP
    heat_rate: np.ndarray     # THRATE, Btu/kWh
    online_year: np.ndarray   # T_SYR
    retire_year: np.ndarray   # T_RYR, 9999 if not scheduled
    vom: np.ndarray           # T_VOM
    fom: np.ndarray           # T_FOM
    capacity_factor: np.ndarray  # T_CF
    coal_region: np.ndarray   # T_CLRG
    gas_region: np.ndarray    # T_GR
    census: np.ndarray        # T_CR

    def __len__(self):
        return len(self.region)


@lru_cache(maxsize=1)
def load_units() -> Units:
    t = db.table("V_EMM_PLTF860")
    return Units(
        region=t["TNOPER"], owner_region=t["TNOWN"], owner=t["TFOWN"], vintage=t["TVIN"],
        efd_type=np.array([s.strip() for s in t["EFDcd"]], dtype=object),
        ecp_type=np.array([s.strip() for s in t["ECPcd"]], dtype=object),
        name=np.array([s.strip() for s in t["T_PNM"]], dtype=object),
        state=np.array([s.strip() for s in t["TSTATE"]], dtype=object),
        summer_mw=t["TC_SUM"], winter_mw=t["TC_WIN"], nameplate_mw=t["TC_NP"],
        heat_rate=t["THRATE"], online_year=t["T_SYR"], retire_year=t["T_RYR"],
        vom=t["T_VOM"], fom=t["T_FOM"], capacity_factor=t["T_CF"],
        coal_region=t["T_CLRG"], gas_region=t["T_GR"], census=t["T_CR"],
    )


def efd_types() -> list[str]:
    """EFD plant type codes present in the plant file, sorted."""
    return sorted(set(load_units().efd_type))


def online(year: int) -> np.ndarray:
    """Boolean mask of units operating in a calendar year."""
    u = load_units()
    return (u.online_year <= year) & (u.retire_year > year)


def capacity_gw(year: int, efd_types=None, owners=None, vintages=None) -> np.ndarray:
    """Summer capacity in GW by NEMS region, shape (28,). The last row is the US total.

    `efd_types`, `owners` and `vintages` filter the units; None keeps everything.
    """
    u = load_units()
    keep = online(year)
    if efd_types is not None:
        keep &= np.isin(u.efd_type, list(efd_types))
    if owners is not None:
        keep &= np.isin(u.owner, list(owners))
    if vintages is not None:
        keep &= np.isin(u.vintage, list(vintages))
    out = np.zeros(regions.NUM_NERC)
    np.add.at(out, u.region[keep] - 1, u.summer_mw[keep] / 1000.0)
    out[regions.US_ROW] = out[:regions.NUM_EMM].sum()
    return out
