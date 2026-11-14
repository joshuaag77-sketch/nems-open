"""Power-sector coal demand by plant type, and EIA's sub-bituminous and lignite diversity caps.

The CMM LP (coal.ams, PartialLeastCostDomesticCoal) meets electricity demand per plant type pt2 and
demand region, not per region alone (DomesticElectricityDemandRequirement), and caps each cell's
sub-bituminous and lignite deliveries at what EMM's coal units of that type can burn:

    SubbituminousDiversity (coal.ams 14659):  sum over rank 2S <= EMM_max_SubBitBtus_D(DReg, pt2)
        generated only where 0 < Sdvconct_2(pt2, DReg) < 999
    LigniteDiversity (coal.ams 14673):        sum over ranks 3L, 5G <= EMM_max_LigBtus_D(DReg, pt2)
        generated wherever Ldvconct_2 < 9999, i.e. every cell

    EMM_max_SubBitBtus(NDREGN, NUTSEC, yr) = sum over units of EMM_CL_BTUS * SubBit_share(pu_id) + 0.05
    EMM_max_LigBtus(NDREGN, NUTSEC, yr)    = sum over units of EMM_CL_BTUS * max(Lig_share, GOB_share) + 0.05
        (coal.ams 10536-10580; units sit in NDReg_plant(pu_id) and in the plant group EMM assigns them
        that year, COALEMM EMM_CL_ECPT; NUTSEC 99 and years up to 2008 give 0)
    Sdvconct_2(pt2, DReg, yr) = sum over units in DReg (EMM_CL_CLRG) of type pt2 of
        SubDivProfile(Plant_S_Prof(pu_id), yr) * EMM_CL_BTUS * CMM_CL_BTUs_A / TBTU

pt2 is NUTSEC + 14 (map_nutsec_pt3) and demand region DReg is NDREGN (map_ndregn), so arrays here are
(16 regions, 38 plant groups). Demand is COALEMM QCLCLNR (Copy2_Qdutzr), without the STEO-year stock
draw (Stockreg2). One substitution: CMM_CL_BTUs_A is Plant_BaseYear_Btu from CMM.mdb's Contracts table,
which is not shipped. Summed over a plant's curves and divided by its total (TBTU) it is 1 for a plant
with base-year deliveries, else 0; a plant has base-year deliveries here when it has a row in the
plant-to-curve transport profile (cmmProfiles.txt Plant_T_Prof, the same table's keys).
"""

from dataclasses import dataclass

import numpy as np

from nems_open.coal import inputs
from nems_open.coal.macro import Macro

NREG, NTYPE = 16, 38
FIRST_DIVERSITY_YEAR = 2009     # MNUMYR > 19
SUB_ACTIVE_MAX = 999.0
CAP_FLOOR = 0.05


@dataclass
class PowerDemand:
    demand: np.ndarray          # (16, 38) TBtu, QCLCLNR for the year
    sub_cap: np.ndarray         # (16, 38) TBtu, EMM_max_SubBitBtus_D
    lig_cap: np.ndarray         # (16, 38) TBtu, EMM_max_LigBtus_D
    sub_active: np.ndarray      # (16, 38) bool, 0 < Sdvconct_2 < 999
    sdvconct: np.ndarray        # (16, 38) TBtu, Sdvconct_2


def unit_names(s) -> list[str]:
    """COALEMM EMM_CL_UNITS as pu_id strings ("3     4" -> "3_4"). The character array is stored
    column-major, ten characters per unit."""
    u = np.asarray(s["COALEMM/emm_cl_units"])
    flat = b"".join(u.flatten(order="F")).decode("latin-1")
    out = []
    for i in range(u.shape[0]):
        parts = flat[i * 10:(i + 1) * 10].split()
        out.append("_".join(parts) if len(parts) == 2 else "")
    return out


def power_demand(year: int, macro: Macro | None = None, data=None) -> PowerDemand:
    macro, data = macro or Macro(), data or inputs.load()
    s, yi = macro.s, year - 1990
    demand = np.asarray(s["COALEMM/qclclnr"], float)[:, yi, :NTYPE].copy()
    sub_cap = np.zeros((NREG, NTYPE))
    lig_cap = np.zeros((NREG, NTYPE))
    sdv = np.zeros((NREG, NTYPE))
    if year >= FIRST_DIVERSITY_YEAR:
        sub_cap += CAP_FLOOR
        lig_cap += CAP_FLOOR
    names = unit_names(s)
    n = int(np.asarray(s["COALEMM/num_cmm_units"]))
    btus = np.asarray(s["COALEMM/emm_cl_btus"], float)[:, yi]
    ecpt = np.asarray(s["COALEMM/emm_cl_ecpt"])[:, yi].astype(int)
    clrg = np.asarray(s["COALEMM/emm_cl_clrg"]).astype(int)
    delivered = {k[0] for k in data.param("plant_t_prof")}
    ndreg = data.param("ndreg_plant")
    subsh, ligsh, gobsh = data.param("subbit_share"), data.param("lig_share"), data.param("gob_share")
    sprof, subdiv = data.param("plant_s_prof"), data.param("subdivprofile")
    for u in range(n):
        pu, t = names[u], ecpt[u]
        if not pu or t < 1 or t > NTYPE:      # NUTSEC 99: not an active coal group this year
            continue
        b = btus[u]
        if year >= FIRST_DIVERSITY_YEAR and (pu,) in ndreg:
            r = int(ndreg[(pu,)]) - 1
            sub_cap[r, t - 1] += b * subsh.get((pu,), 0.0)
            lig_cap[r, t - 1] += b * max(ligsh.get((pu,), 0.0), gobsh.get((pu,), 0.0))
        if pu in delivered and 1 <= clrg[u] <= NREG and (pu,) in sprof:
            sdv[clrg[u] - 1, t - 1] += subdiv.get((int(sprof[(pu,)]), year), 0.0) * b
    return PowerDemand(demand, sub_cap, lig_cap, (sdv > 0) & (sdv < SUB_ACTIVE_MAX), sdv)
