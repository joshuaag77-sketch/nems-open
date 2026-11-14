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


def tier1_bound(year: int, keys: list, macro: Macro | None = None, data=None) -> np.ndarray:
    """TrubndScrubbed + TrubndUnscrubbed (coal.ams 12921-13042): first-tier electricity transport volume
    by supply curve and demand region, (len(keys), 16) TBtu. Each unit contributes
    TranspProfile(Plant_T_Prof(pu_id, curve), year) * EMM_CL_BTUS in its region (EMM_CL_CLRG), if it sits
    in an active plant group that year. Above it, deliveries pay the second-tier premium. The scrubbed and
    unscrubbed bounds enter the LP only through their sum (BalanceScrubUnscrubTier1 lets the split float),
    so only the sum is returned."""
    macro, data = macro or Macro(), data or inputs.load()
    s, yi = macro.s, year - 1990
    names = unit_names(s)
    n = int(np.asarray(s["COALEMM/num_cmm_units"]))
    btus = np.asarray(s["COALEMM/emm_cl_btus"], float)[:, yi]
    ecpt = np.asarray(s["COALEMM/emm_cl_ecpt"])[:, yi].astype(int)
    clrg = np.asarray(s["COALEMM/emm_cl_clrg"]).astype(int)
    prof = data.param("transpprofile")
    curve = {tuple(k[1:]): i for i, k in enumerate(keys)}
    by_unit: dict = {}
    for (pu, *ck), tnum in data.param("plant_t_prof").items():
        if tuple(ck) in curve:
            by_unit.setdefault(pu, []).append((curve[tuple(ck)], int(tnum)))
    out = np.zeros((len(keys), NREG))
    for u in range(n):
        pu, t, r = names[u], ecpt[u], clrg[u]
        if not pu or t < 1 or t > NTYPE or not 1 <= r <= NREG:
            continue
        for ci, tnum in by_unit.get(pu, ()):
            out[ci, r - 1] += prof.get((tnum, year), 0.0) * btus[u]
    return out


def contract_floor(year: int, keys: list, macro: Macro | None = None, data=None) -> np.ndarray:
    """Copy8c_CdyrsScrubbed + Copy9c_CdyrsUnscrubbed (coal.ams 13193-13245): minimum electricity deliveries
    by supply curve and demand region, (len(keys), 16) TBtu, from the contracts in cmmProfiles.txt.

        ActiveCont(pu_id, curve, yr) = ContSupCrvBtus_B(pu_id, nci) * ContractProfile(Plant_C_Prof(pltnum, nci), yr)
        for units in an active plant group that year, summed over units in each demand region (EMM_CL_CLRG).

    EIA's quirk kept: ContSupCrvBtus_B gives every unit of a plant the plant's whole contract quantity
    (sum over pltnum, not a unit share), so a plant's contract counts once per active unit. The scrubbed
    and unscrubbed floors bind only through their sum (the split of deliveries floats), so the sum is
    returned. Contracts on curves beyond the 14 domestic ones (imports) are left out."""
    macro, data = macro or Macro(), data or inputs.load()
    s, yi = macro.s, year - 1990
    names = unit_names(s)
    n = int(np.asarray(s["COALEMM/num_cmm_units"]))
    ecpt = np.asarray(s["COALEMM/emm_cl_ecpt"])[:, yi].astype(int)
    clrg = np.asarray(s["COALEMM/emm_cl_clrg"]).astype(int)
    curve = {tuple(k[1:]): i for i, k in enumerate(keys)}
    nci = {k[0]: curve[tuple(k[1:])] for k in data.param("map_mxnci_coaltype") if tuple(k[1:]) in curve}
    plant = {pu: plt for (pu, plt) in data.param("map_pltnum_puid")}
    prof, cprof = data.param("contractprofile"), data.param("plant_c_prof")
    by_plant: dict = {}
    for (plt, c), q in data.param("contsupcrvbtus").items():
        if c in nci:
            by_plant.setdefault(plt, []).append((nci[c], q, int(cprof.get((plt, c), 0))))
    out = np.zeros((len(keys), NREG))
    for u in range(n):
        pu, t, r = names[u], ecpt[u], clrg[u]
        if not pu or t < 1 or t > NTYPE or not 1 <= r <= NREG or pu not in plant:
            continue
        for ci, q, cnum in by_plant.get(plant[pu], ()):
            out[ci, r - 1] += q * prof.get((cnum, year), 0.0)
    return out


MATS_YEAR = 2015          # MercuryRemovalUpperBound: the rule applies for cyr > 2015
MATS_MEF_LIMIT = 0.101    # MercuryRemoval: step 1 (no activated carbon) only if EMM_MEF(1, rank, type) <= this
RANK_M4 = {"1B": 1, "2S": 2, "3L": 3, "5G": 3, "4P": 4}   # Map_Rank_M4 (cdsRegionRef); 4 is beyond MX_RNK


def mats_adder(year: int, keys: list, macro: Macro | None = None) -> np.ndarray:
    """Extra cost of delivering a curve's coal to a plant type under MATS, (len(keys), 38), 1987$/MMBtu.

    In the CMM LP each power delivery has two steps (ElectricityTransportAC, nsteps 1 and 2). Step 1 is coal
    burned without activated carbon; after 2015 its upper bound is 0 where the plant type's mercury emission
    factor for that rank, COALEMM EMM_MEF(1, rank, NUTSEC), exceeds 0.101 (MercuryRemoval,
    MercuryRemovalUpperBound, coal.ams 15835-15873). Step 2 pays the same rate plus
    ACI_CST(2, rank, NUTSEC) / 10 (ElectricityTransport1Cost). The mercury cap itself (Mercp02) does not bind
    in cb2026 (EMEL_QHG 999.9 tons), so step 2 is never cheaper than an allowed step 1, and the two steps
    reduce to one delivery whose cost carries this adder: 0 where step 1 is allowed, the ACI cost where not.
    EIA codes ACI_CST as 100 where a plant type cannot take a rank at all, which makes the adder 10."""
    macro = macro or Macro()
    mef = np.asarray(macro.s["COALEMM/emm_mef"], float)     # (NSTEPS, MX_RNK, NUTSEC)
    aci = np.asarray(macro.s["COALEMM/aci_cst"], float)
    out = np.zeros((len(keys), NTYPE))
    if year <= MATS_YEAR:
        return out
    for i, k in enumerate(keys):
        m4 = RANK_M4.get(k[4], 0)
        if not 1 <= m4 <= mef.shape[1]:
            continue          # no factor for this rank: Copy_emm_mef is 0, step 1 allowed
        blocked = mef[0, m4 - 1, :NTYPE] > MATS_MEF_LIMIT
        out[i] = np.where(blocked, aci[1, m4 - 1, :NTYPE] / 10.0, 0.0)
    return out
