"""Plant technologies: the 80 ECP build types and the EFD dispatch plant types.

ECP (capacity planning) chooses among 80 plant types. Their codes, lives, O&M and heat rates
are in the COSTPERF sheet of ecpdaty.xlsx, in type order. Regional overnight and O&M costs
sit in the input database, one row per region and type. EFD (dispatch) uses the plant types
in pltdata.txt.
"""

import zipfile
from dataclasses import dataclass
from functools import lru_cache

import numpy as np

from nems_open.emm import db, regions
from nems_open.paths import INPUT
from nems_open.xlsx_ranges import _sheet_cells, named_ranges

ECPDATY = INPUT / "emm" / "ecpdaty.xlsx"
PLTDATA = INPUT / "emm" / "pltdata.txt"

NUM_ECP_TYPES = 80
FIRST_TYPE_ROW = 17     # COSTPERF row of ECP type 1 (B1) in the first table


@lru_cache(maxsize=1)
def ecp_codes() -> tuple[str, ...]:
    """The 80 ECP plant type codes in model order, e.g. ('B1', 'B2', ..., 'DP')."""
    with zipfile.ZipFile(ECPDATY) as z:
        _, cells = _sheet_cells(z, "COSTPERF")
    codes = tuple(str(cells[(2, FIRST_TYPE_ROW + i)]).strip() for i in range(NUM_ECP_TYPES))
    return codes


@lru_cache(maxsize=1)
def type_parameters() -> dict[str, np.ndarray]:
    """Per-type parameters from ecpdaty.xlsx COSTPERF, each of shape (80,) unless noted.

    availability_year: first calendar year the type can be built
    economic_life, tax_life: years
    vom: variable O&M, 1987$ per MWh; fom: fixed O&M, 1987$ per kW-year
    heat_rate: Btu per kWh
    forced_outage_rate, planned_maintenance_rate, max_capacity_factor: fractions
    construction_profile: shape (80, 10), share of cost spent in each construction year
    overnight_cost: UPOVR, $/kW before regional multipliers; 9999 means the type cannot be built
    unit_size_mw: UPMSSIZ, typical unit size; project_contingency: UPLRPC
    learning_start_year, learning_end_year: UPLRSYR, UPLRLYR, the years cost learning applies
    """
    r = named_ranges(ECPDATY, "COSTPERF")

    def col(name, width=1):
        a = np.array(r[name], dtype=np.float64)
        return a if width == 1 else a.reshape(-1, width)

    return {
        "availability_year": col("UPAVLYR"), "economic_life": col("UPECLF"), "tax_life": col("UPTXLF"),
        "vom": col("UPVOM"), "fom": col("UPFOM"), "heat_rate": col("UPHTRT"),
        "forced_outage_rate": col("UPFORT"), "planned_maintenance_rate": col("UPPMRT"),
        "max_capacity_factor": col("UPMCF"), "construction_profile": col("UPCPRO", 10),
        "overnight_cost": col("UPOVR"), "unit_size_mw": col("UPMSSIZ"), "project_contingency": col("UPLRPC"),
        "learning_start_year": col("UPLRSYR"), "learning_end_year": col("UPLRLYR"),
    }


@lru_cache(maxsize=1)
def regional_costs() -> dict[str, np.ndarray]:
    """Regional cost table from the database, each of shape (28, 80): NEMS region (25 EMM,
    Alaska, Hawaii, US row) by ECP type.

    regional_multiplier (EPRGM) and area_multiplier (EPACM) scale a type's overnight cost.
    The transmission_* entries are the cost of connecting a new plant (EPCOVR overnight $/kW,
    EPCCRF charge rate, EPCFOM fixed O&M); they are not plant costs. Blank cells are NaN.
    """
    t = db.table("V_EMM_ECPDAT_REG_ECPT")
    out = {}
    for name, col in (("regional_multiplier", "EPRGM"), ("area_multiplier", "EPACM"),
                      ("transmission_overnight_cost", "EPCOVR"), ("transmission_charge_rate", "EPCCRF"),
                      ("transmission_fom", "EPCFOM")):
        a = np.full((regions.NUM_NERC, NUM_ECP_TYPES), np.nan)
        a[t["EMM_REG"] - 1, t["ECP_TYP"] - 1] = t[col]
        out[name] = a
    return out


@lru_cache(maxsize=1)
def region_links() -> dict[str, np.ndarray]:
    """Which gas region, coal region and census division each EMM region buys from, shape (25,)."""
    t = db.table("V_EMM_ECPDAT_REG")
    order = np.argsort(t["EMM_REG"])
    keep = order[t["EMM_REG"][order] <= regions.NUM_EMM]
    return {"gas_region": t["EPNGRG"][keep], "coal_region": t["EPCLRG"][keep], "carbon_region": t["EPCARG"][keep]}


@dataclass(frozen=True)
class EfdPlantType:
    number: int
    code: str                 # e.g. 'CSC'
    name: str
    planned_maintenance: float
    forced_outage: float
    max_capacity_factor: float
    fuels: tuple[str, ...]    # fuel codes in use, e.g. ('B1', 'DS', 'WD')
    fuel_shares: tuple[float, ...]


@lru_cache(maxsize=1)
def efd_plant_types() -> tuple[EfdPlantType, ...]:
    """EFD plant types from pltdata.txt."""
    out = []
    for line in PLTDATA.read_text(encoding="latin-1").splitlines():
        if not line.strip() or line.lstrip().startswith(("#", "%")):
            continue
        num, rest = line.split(None, 1)
        if not num.isdigit():
            continue
        q1 = rest.index("'")
        code = rest[q1 + 1:rest.index("'", q1 + 1)]
        rest = rest[rest.index("'", q1 + 1) + 1:]
        q2 = rest.index("'")
        name = rest[q2 + 1:rest.index("'", q2 + 1)].strip()
        tail = rest[rest.index("'", q2 + 1) + 1:].split()
        pmr, forced, mcf = (float(x) for x in tail[:3])
        fuels, shares = [], []
        toks = [x.strip("'") for x in tail[3:]]
        # three fuel codes then three shares (a fuel code of NA means unused)
        for f, s in zip(toks[:3], toks[3:6]):
            if f != "NA":
                fuels.append(f)
                shares.append(float(s))
        out.append(EfdPlantType(int(num), code, name, pmr, forced, mcf, tuple(fuels), tuple(shares)))
    return tuple(out)
