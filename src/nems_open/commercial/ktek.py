"""KTEK technology table: port of the first-call technology read in COMServiceDemand (comm.f).

ktekx.xlsx lists every equipment technology (heat pumps, boilers, lamps, ...) by
vintage and region: efficiency, costs, service life, availability years, base-year
market share and which buildings it is restricted to. EIA reads the sheet's named
ranges, one record per row, and fills the technology arrays the rest of the module uses.
Records that fail a check are skipped, and the checks and their order are EIA's.

Names follow the Fortran so each step can be checked against comm.f.
"""

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from nems_open.commercial.inputs import CDM, NUM_BLDG, NUM_DIV, NUM_MAJ_FL, NUM_MAJ_SERV, NUM_SERV
from nems_open.fortran_array import FArray
from nems_open.xlsx_ranges import named_ranges

f32 = np.float32

NUM_TECHS = 62
NUM_EQ_VINT = 44
MNUMCR = 11
CM_BASE_YEAR = 2019
BASEYR = 1990
MAXCOST = f32(1.0e9)
EPSILON = (f32(0.00001), f32(0.001))  # Epsilon(1), Epsilon(2)

# Range names, in the order EIA reads them. Integer ranges are rounded (inint), reals stay REAL*4.
INT_RANGES = ["TCH", "VNT", "REG", "SERV", "FUEL", "LIFE", "YINTRO", "YLAST", "RETROFIT",
              "RESTRICT1", "RESTRICT2", "RESTRICT3", "RESTRICT4", "RESTRICT5", "RESTRICT6",
              "RESTRICT7", "RESTRICT8", "RESTRICT9", "RESTRICT10", "RESTRICT11", "TRNDSTART", "TRNDSHAPE"]


def inint(x: float) -> int:
    """Fortran NINT: nearest integer, halves away from zero."""
    return int(np.floor(abs(x) + 0.5)) * (1 if x >= 0 else -1)


@dataclass
class Ktek:
    TechEff: FArray
    TechCRI: FArray
    TechCost: FArray
    TechAvailability: FArray
    TechLife: FArray
    RetroCostFract: FArray
    EquipName: np.ndarray        # (r, t, v) text, 44 characters
    CostTrend: np.ndarray        # (t, v) text, 10 characters
    CostParam1: FArray
    CostParam2: FArray
    CostParam3: FArray
    EquipRestriction: FArray     # (t, v, b, r)
    FuelbyTech: FArray
    TechbyService: FArray
    TechbyModel: FArray
    TechShareofServiceBASE: FArray
    TechCostYr1: int = 0
    TechsforService: FArray = None
    CMnumEqV: FArray = None
    CMnumTechsforService: FArray = None


def _empty() -> Ktek:
    z = FArray.zeros
    k = Ktek(
        TechEff=z([(1, MNUMCR), (1, NUM_SERV), (1, NUM_TECHS), (1, NUM_EQ_VINT)]),
        TechCRI=z([(1, MNUMCR), (1, NUM_SERV), (1, NUM_TECHS), (1, NUM_EQ_VINT)]),
        TechCost=z([(1, MNUMCR), (1, NUM_TECHS), (1, NUM_EQ_VINT), (1, 4)]),
        TechAvailability=z([(1, MNUMCR), (1, NUM_TECHS), (1, NUM_EQ_VINT), (1, 2)], dtype=np.int32),
        TechLife=z([(1, NUM_TECHS), (1, NUM_EQ_VINT)]),
        RetroCostFract=z([(1, NUM_TECHS), (1, NUM_EQ_VINT)]),
        EquipName=np.full((MNUMCR, NUM_TECHS, NUM_EQ_VINT), "", dtype="U44"),
        CostTrend=np.full((NUM_TECHS, NUM_EQ_VINT), "", dtype="U10"),
        CostParam1=z([(1, NUM_TECHS), (1, NUM_EQ_VINT)]),
        CostParam2=z([(1, NUM_TECHS), (1, NUM_EQ_VINT)]),
        CostParam3=z([(1, NUM_TECHS), (1, NUM_EQ_VINT)]),
        EquipRestriction=z([(1, NUM_TECHS), (1, NUM_EQ_VINT), (1, NUM_BLDG), (1, NUM_BLDG)], dtype=np.int8),
        FuelbyTech=z([(1, NUM_TECHS), (1, NUM_MAJ_FL)], dtype=np.int32),
        TechbyService=z([(1, NUM_SERV), (1, NUM_TECHS)], dtype=np.int32),
        TechbyModel=z([(1, NUM_TECHS), (1, NUM_EQ_VINT)], dtype=np.int32),
        TechShareofServiceBASE=z([(1, MNUMCR), (1, NUM_BLDG), (1, NUM_SERV), (1, NUM_TECHS), (1, NUM_EQ_VINT)]),
    )
    # Costs start at a huge number so the least-cost search never picks a technology that
    # has no record; restrictions start at 1 (not allowed) until a record says otherwise.
    k.TechCost[:, :, :, 1:2] = MAXCOST
    k.EquipRestriction[:, :, :, :] = 1
    return k


def read_ktek(book: Path = CDM / "ktekx.xlsx", epa111d: int = 0, ab32sw: int = 0) -> Ktek:
    """Read ktekx.xlsx into the technology arrays, record by record."""
    rng = named_ranges(book, "ktek")
    k = _empty()
    k.TechCostYr1 = inint(rng["TECHCOSTYR1"][0])
    max_rec = inint(rng["MAXREC"][0])

    def ints(name):
        return [inint(v) for v in rng[name][:max_rec]]

    def reals(name):
        return [f32(v) for v in rng[name][:max_rec]]

    tch, vnt, reg, serv, fuel = ints("TCH"), ints("VNT"), ints("REG"), ints("SERV"), ints("FUEL")
    share, eff = reals("SHARE"), reals("EFFICIENCY")
    capcst, maintcst, subcst, sub111dcst = reals("CAPCST"), reals("MAINTCST"), reals("SUBCST"), reals("SUB111DCST")
    life, yintro, ylast, retrofit = ints("LIFE"), ints("YINTRO"), ints("YLAST"), ints("RETROFIT")
    techname = [str(s)[:44] for s in rng["TECHNAME"][:max_rec]]
    restrict = [ints(f"RESTRICT{i}") for i in range(1, NUM_BLDG + 1)]
    trndtype = [str(s)[:10] for s in rng["TRNDTYPE"][:max_rec]]
    trndstart, trndshape, trndpct = ints("TRNDSTART"), ints("TRNDSHAPE"), reals("TRNDPCT")
    cri = reals("CRI")

    for count in range(max_rec):
        t, v, r, s, f = tch[count], vnt[count], reg[count], serv[count], fuel[count]
        markshar, effic = share[count], eff[count]
        cctemp, omtemp, sbtemp = capcst[count], maintcst[count], subcst[count]
        sb111dtemp = sub111dcst[count]
        inityrtemp, lastyrtemp, sltemp = yintro[count], ylast[count], f32(life[count])
        retrotemp = f32(retrofit[count])

        # EIA stores the restrictions and cost trend before any check, so records that
        # are skipped later still leave these behind.
        if 1 <= t <= NUM_TECHS and 1 <= v <= NUM_EQ_VINT and 1 <= r <= NUM_BLDG:
            for b in range(1, NUM_BLDG + 1):
                k.EquipRestriction[t, v, b, r] = restrict[b - 1][count]
        if 1 <= t <= NUM_TECHS and 1 <= v <= NUM_EQ_VINT:
            k.CostTrend[t - 1, v - 1] = trndtype[count]
            k.CostParam1[t, v] = f32(trndstart[count])
            k.CostParam2[t, v] = f32(trndshape[count])
            k.CostParam3[t, v] = trndpct[count]
        cri_for_lighting = cri[count]

        if t < 1 or t > NUM_TECHS or v < 1 or v > NUM_EQ_VINT:
            continue
        rbound = NUM_DIV
        if s >= 6 or s == 4:
            rbound = NUM_BLDG  # lighting, refrigeration and ventilation are by building type
        if r < 1 or r > rbound or s < 1 or s > NUM_MAJ_SERV or f < 1 or f > NUM_MAJ_FL:
            continue
        # A second record for the same r, s, t, v is a duplicate, except in services listed by building.
        if k.TechEff[r, s, t, v] > 0.0 and s < 6 and s != 4:
            continue
        if effic <= 0.0 or cctemp <= 0.0 or omtemp <= 0.0 or sbtemp < 0.0 or sb111dtemp < 0.0:
            continue

        # Service life, first year and last year are kept by technology and vintage, not region.
        if k.TechLife[t, v] > 0.0 and k.TechLife[t, v] != sltemp:
            if sltemp < 1.0:
                sltemp = k.TechLife[t, v]
        elif sltemp < 1.0:
            continue

        if k.TechAvailability[r, t, v, 1] > 0 and k.TechAvailability[r, t, v, 1] != inityrtemp:
            if inityrtemp > lastyrtemp:
                inityrtemp = int(k.TechAvailability[r, t, v, 1])
        if k.TechAvailability[r, t, v, 2] > 0 and k.TechAvailability[r, t, v, 2] != lastyrtemp:
            if lastyrtemp < inityrtemp:
                lastyrtemp = int(k.TechAvailability[r, t, v, 2])
        if lastyrtemp < inityrtemp:
            continue
        if retrotemp < 0.0:
            continue

        # Market shares apply only to technologies available in the base year.
        flag = markshar < 0.0 or markshar > 1.0
        if inityrtemp > CM_BASE_YEAR and markshar > 0.0:
            flag = True
        if flag:
            markshar = f32(0.0)

        def store(rr, sb111d):
            """Costs for one region; EIA's subsidy switches decide what comes off the capital cost."""
            k.TechEff[rr, s, t, v] = effic
            if epa111d == 1:
                cap = f32(f32(cctemp - sbtemp) - sb111d)
            elif ab32sw == 0:
                sb111d = f32(sb111d * f32(epa111d))
                cap = f32(cctemp - sbtemp)
            elif rr == 9:
                cap = f32(f32(cctemp - sbtemp) - sb111d)
            else:
                sb111d = f32(sb111d * f32(epa111d))
                cap = f32(cctemp - sbtemp)
            k.TechCost[rr, t, v, 1] = cap
            k.TechCost[rr, t, v, 2] = omtemp
            k.TechCost[rr, t, v, 3] = sbtemp
            k.TechCost[rr, t, v, 4] = sb111d
            k.TechAvailability[rr, t, v, 1] = inityrtemp
            k.TechAvailability[rr, t, v, 2] = lastyrtemp
            k.EquipName[rr - 1, t - 1, v - 1] = techname[count]
            return sb111d

        if s < 6 and s != 4:
            if ab32sw == 1 and r == 9:
                sb111dtemp = f32(sb111dtemp * f32(2))
            if cri_for_lighting == 2.0:
                k.TechCRI[r, s, t, v] = cri_for_lighting
            store(r, sb111dtemp)
        else:
            for realr in range(1, NUM_DIV + 1):
                sb111dtemp = sub111dcst[count]
                if ab32sw == 1 and realr == 9:
                    sb111dtemp = f32(sb111dtemp * f32(2))
                k.TechCRI[realr, s, t, v] = cri_for_lighting
                store(realr, sb111dtemp)
        k.TechLife[t, v] = sltemp
        k.RetroCostFract[t, v] = retrotemp

        k.FuelbyTech[t, f] = 1
        k.TechbyService[s, t] = 1
        k.TechbyModel[t, v] = 1

        # Shares: constant over building type for most services, constant over division for the
        # services listed by building type (ventilation, lighting, refrigeration).
        if s < 6 and s != 4:
            for b in range(1, NUM_BLDG + 1):
                k.TechShareofServiceBASE[r, b, s, t, v] = markshar
        else:
            for realr in range(1, NUM_DIV + 1):
                k.TechShareofServiceBASE[realr, r, s, t, v] = markshar
    return k
