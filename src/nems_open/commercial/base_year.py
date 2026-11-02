"""Base-year service demand intensities: the rest of the first call in COMServiceDemand (comm.f).

After the KTEK table is read, EIA indexes the technologies, normalises the base-year
market shares, restricts equipment to the buildings it can go in, and turns the energy
use intensities (kBtu/sqft, from KINTENS) into service demand intensities (service
delivered per sqft) using each technology's efficiency. Those intensities,
ServDmdIntenBASE, are what the yearly service demand calculation grows from.

Names follow the Fortran so each step can be checked against comm.f.
"""

import numpy as np

from nems_open.commercial.inputs import CBECS_YEAR, NUM_BLDG, NUM_DIV, NUM_MAJ_FL, NUM_MAJ_SERV, NUM_SERV
from nems_open.commercial.ktek import (
    BASEYR, CM_BASE_YEAR, EPSILON, NUM_EQ_VINT, NUM_TECHS, Ktek,
)
from nems_open.fortran_array import FArray

f32 = np.float32
NUM_HEAT_PUMP_TECHS = 5


def index_technologies(k: Ktek) -> None:
    """TechsforService, CMnumEqV and CMnumTechsforService: shortcuts so loops skip unused technologies."""
    k.TechsforService = FArray.zeros([(1, NUM_SERV), (1, NUM_TECHS)], dtype=np.int32)
    k.CMnumEqV = FArray.zeros([(1, NUM_TECHS)], dtype=np.int32)
    k.CMnumTechsforService = FArray.zeros([(1, NUM_SERV)], dtype=np.int32)
    for s in range(1, NUM_MAJ_SERV + 1):
        count = 0
        for t in range(1, NUM_TECHS + 1):
            if k.TechbyService[s, t] == 1:
                count += 1
                k.TechsforService[s, count] = t
                vmax = 0
                for v in range(1, NUM_EQ_VINT + 1):
                    if k.TechLife[t, v] > 0.0 and v > vmax:
                        vmax = v
                k.CMnumEqV[t] = vmax
        k.CMnumTechsforService[s] = count


def normalize_base_shares(k: Ktek) -> None:
    """Base-year market shares must add to 1 within a service; if not, divide by the sum.

    Most services have identical shares across building types (checked by division);
    ventilation, lighting and refrigeration have identical shares across divisions
    (checked by building type).
    """
    eps = EPSILON[0]
    for r in range(1, NUM_DIV + 1):
        for s in range(1, NUM_MAJ_SERV + 1):
            if s >= 6 or s == 4:
                continue
            total = f32(0.0)
            for t in range(1, NUM_TECHS + 1):
                for v in range(1, k.CMnumEqV[t] + 1):
                    if k.TechbyService[s, t] == 1 and k.TechAvailability[r, t, v, 1] <= CM_BASE_YEAR:
                        total = f32(total + k.TechShareofServiceBASE[r, 1, s, t, v])
            if total == 0.0:
                continue
            if total > f32(1.0) + eps or total < f32(1.0) - eps:
                for t in range(1, NUM_TECHS + 1):
                    for v in range(1, k.CMnumEqV[t] + 1):
                        if k.TechbyService[s, t] == 1 and total > 0.0 and k.TechAvailability[r, t, v, 1] <= CM_BASE_YEAR:
                            k.TechShareofServiceBASE[r, 1, s, t, v] = f32(k.TechShareofServiceBASE[r, 1, s, t, v] / total)
                        for b in range(2, NUM_BLDG + 1):
                            k.TechShareofServiceBASE[r, b, s, t, v] = k.TechShareofServiceBASE[r, 1, s, t, v]

    for b in range(1, NUM_BLDG + 1):
        for s in range(4, 8):
            if s == 5:
                continue
            total = f32(0.0)
            for t in range(1, NUM_TECHS + 1):
                for v in range(1, k.CMnumEqV[t] + 1):
                    if k.TechbyService[s, t] == 1 and k.TechAvailability[b, t, v, 1] <= CM_BASE_YEAR:
                        total = f32(total + k.TechShareofServiceBASE[1, b, s, t, v])
            if total == 0.0:
                continue
            if total > f32(1.0) + eps or total < f32(1.0) - eps:
                for t in range(1, NUM_TECHS + 1):
                    for v in range(1, k.CMnumEqV[t] + 1):
                        if k.TechbyService[s, t] == 1 and total > 0.0 and k.TechAvailability[b, t, v, 1] <= CM_BASE_YEAR:
                            k.TechShareofServiceBASE[1, b, s, t, v] = f32(k.TechShareofServiceBASE[1, b, s, t, v] / total)
                        for r in range(2, NUM_DIV + 1):
                            k.TechShareofServiceBASE[r, b, s, t, v] = k.TechShareofServiceBASE[1, b, s, t, v]


def drop_eisa_standards(k: Ktek) -> None:
    """With the Dec 2007 energy bill switch off, push the lamp and refrigeration standards out to 2050."""
    for b in range(1, NUM_BLDG + 1):
        k.TechAvailability[b, 24, 1, 2] = 2050
        k.TechAvailability[b, 24, 3, 2] = 2050
        k.TechAvailability[b, 27, 2, 2] = 2050
        k.TechAvailability[b, 28, 2, 2] = 2050
        for t in (39, 40):
            for v in (1, 2):
                k.TechAvailability[b, t, v, 2] = 2050


def base_year_intensities(k: Ktek, eui: FArray, cm_total_flspc: FArray) -> dict:
    """Restrict base-year shares by building type, then convert EUIs to service demand intensities.

    `eui` is ComEUI as read from KINTENS (its total column is rebuilt here) and
    `cm_total_flspc` is CMTotalFlspc (r, b, y) for the CBECS year. Changes `k` and `eui` in place.
    Returns ServDmdIntenBASE (s, b, r), FuelShareofServiceBASE and AverageEfficiencyBASE (r, b, s, f).
    """
    nf = NUM_MAJ_FL
    cbecs_idx = CBECS_YEAR - (BASEYR - 1)
    tsb = k.TechShareofServiceBASE

    # Equipment restrictions: shares in buildings the equipment can go in are scaled up to
    # carry the consumption of all buildings, and shares in other buildings are zeroed.
    for r in range(1, NUM_DIV + 1):
        for s in range(1, NUM_MAJ_SERV + 1):
            c_for_s_total = f32(0.0)
            for b in range(1, NUM_BLDG + 1):
                eui[r, b, s, nf + 1] = f32(0.0)
                for f in range(1, nf + 1):
                    eui[r, b, s, nf + 1] = f32(eui[r, b, s, nf + 1] + eui[r, b, s, f])
            base_restrict = [1] * (NUM_BLDG + 1)
            for b in range(1, NUM_BLDG + 1):
                c_for_s_total = f32(c_for_s_total + f32(eui[r, b, s, nf + 1] * cm_total_flspc[r, b, cbecs_idx]))
            for ts in range(1, k.CMnumTechsforService[s] + 1):
                t = int(k.TechsforService[s, ts])
                for v in range(1, k.CMnumEqV[t] + 1):
                    if k.TechbyModel[t, v] == 1 and k.TechAvailability[r, t, v, 1] <= CBECS_YEAR:
                        c_restrict = f32(0.0)
                        for b in range(1, NUM_BLDG + 1):
                            if s == 2 and t <= NUM_HEAT_PUMP_TECHS * 2:
                                base_restrict[b] = int(k.EquipRestriction[t - NUM_HEAT_PUMP_TECHS, v, b, r])
                            else:
                                base_restrict[b] = int(k.EquipRestriction[t, v, b, r])
                            if base_restrict[b] == 0:
                                c_restrict = f32(c_restrict + f32(eui[r, b, s, nf + 1] * cm_total_flspc[r, b, cbecs_idx]))
                        for b in range(1, NUM_BLDG + 1):
                            if base_restrict[b] == 0:
                                if c_restrict > 0.0:
                                    tsb[r, b, s, t, v] = f32(f32(tsb[r, b, s, t, v] * c_for_s_total) / c_restrict)
                            else:
                                tsb[r, b, s, t, v] = f32(0.0)
                            base_restrict[b] = 1
            # Renormalise so shares in each building add to 1.
            for b in range(1, NUM_BLDG + 1):
                denominator = f32(0.0)
                for ts in range(1, k.CMnumTechsforService[s] + 1):
                    t = int(k.TechsforService[s, ts])
                    for v in range(1, k.CMnumEqV[t] + 1):
                        if k.TechbyModel[t, v] == 1 and k.TechAvailability[r, t, v, 1] <= CBECS_YEAR:
                            denominator = f32(denominator + tsb[r, b, s, t, v])
                if denominator > 0.0:
                    for ts in range(1, k.CMnumTechsforService[s] + 1):
                        t = int(k.TechsforService[s, ts])
                        for v in range(1, k.CMnumEqV[t] + 1):
                            if k.TechbyModel[t, v] == 1 and k.TechAvailability[r, t, v, 1] <= CBECS_YEAR:
                                tsb[r, b, s, t, v] = f32(tsb[r, b, s, t, v] / denominator)

    fuel_share = FArray.zeros([(1, 11), (1, NUM_BLDG), (1, NUM_SERV), (1, nf)])
    avg_eff = FArray.zeros([(1, 11), (1, NUM_BLDG), (1, NUM_SERV), (1, nf)])
    sdi = FArray.zeros([(1, NUM_SERV), (1, NUM_BLDG), (1, 11)])
    kscale = [f32(0.0)] * (nf + 1)

    # Scale each fuel's shares so the fuel mix implied by the EUIs is honoured, then divide
    # each EUI by the harmonic efficiency of the equipment to get a service demand intensity.
    for r in range(1, NUM_DIV + 1):
        for b in range(1, NUM_BLDG + 1):
            for s in range(1, NUM_SERV + 1):
                eui[r, b, s, nf + 1] = f32(0.0)
                for f in range(1, nf + 1):
                    eui[r, b, s, nf + 1] = f32(eui[r, b, s, nf + 1] + eui[r, b, s, f])
                    fuel_share[r, b, s, f] = f32(0.0)
                    avg_eff[r, b, s, f] = f32(0.0)
                    denominator = f32(0.0)
                    for ts in range(1, k.CMnumTechsforService[s] + 1):
                        t = int(k.TechsforService[s, ts])
                        if k.FuelbyTech[t, f] == 1:
                            for v in range(1, k.CMnumEqV[t] + 1):
                                if k.TechbyModel[t, v] == 1:
                                    fuel_share[r, b, s, f] = f32(fuel_share[r, b, s, f] + tsb[r, b, s, t, v])
                                    if k.TechEff[r, s, t, v] > 0.0:
                                        denominator = f32(denominator + f32(tsb[r, b, s, t, v] / k.TechEff[r, s, t, v]))
                    if denominator > 0.0:
                        avg_eff[r, b, s, f] = f32(fuel_share[r, b, s, f] / denominator)
                for f in range(1, nf + 1):
                    denominator = f32(0.0)
                    for ifuel in range(1, nf + 1):
                        if eui[r, b, s, nf + 1] > 0.0:
                            denominator = f32(denominator + f32(f32(eui[r, b, s, ifuel] / eui[r, b, s, nf + 1])
                                                                * avg_eff[r, b, s, ifuel]))
                    kscale[f] = f32(0.0)
                    if fuel_share[r, b, s, f] > 0.0 and denominator > 0.0:
                        kscale[f] = f32(f32(f32(f32(eui[r, b, s, f] / eui[r, b, s, nf + 1]) * avg_eff[r, b, s, f])
                                            / fuel_share[r, b, s, f]) / denominator)
                for f in range(1, nf + 1):
                    for ts in range(1, k.CMnumTechsforService[s] + 1):
                        t = int(k.TechsforService[s, ts])
                        if k.FuelbyTech[t, f] == 1:
                            for v in range(1, k.CMnumEqV[t] + 1):
                                if k.TechbyModel[t, v] == 1:
                                    tsb[r, b, s, t, v] = f32(tsb[r, b, s, t, v] * kscale[f])
                # A service with no equipment is a minor service: its EUI is used as is.
                sdi[s, b, r] = eui[r, b, s, nf + 1]
                denominator = f32(0.0)
                for ts in range(1, k.CMnumTechsforService[s] + 1):
                    t = int(k.TechsforService[s, ts])
                    for v in range(1, k.CMnumEqV[t] + 1):
                        if k.TechbyModel[t, v] == 1 and k.TechEff[r, s, t, v] > 0.0:
                            denominator = f32(denominator + f32(tsb[r, b, s, t, v] / k.TechEff[r, s, t, v]))
                if denominator > 0.0:
                    sdi[s, b, r] = f32(eui[r, b, s, nf + 1] / denominator)

    # Fuel shares again, from the scaled technology shares.
    for r in range(1, NUM_DIV + 1):
        for b in range(1, NUM_BLDG + 1):
            for s in range(1, NUM_SERV + 1):
                for f in range(1, nf + 1):
                    fuel_share[r, b, s, f] = f32(0.0)
                    for ts in range(1, k.CMnumTechsforService[s] + 1):
                        t = int(k.TechsforService[s, ts])
                        if k.FuelbyTech[t, f] == 1:
                            for v in range(1, k.CMnumEqV[t] + 1):
                                if k.TechbyModel[t, v] == 1:
                                    fuel_share[r, b, s, f] = f32(fuel_share[r, b, s, f] + tsb[r, b, s, t, v])

    # Minor services are all electric (efficiency 1); miscellaneous follows the EUIs.
    with np.errstate(divide="ignore", invalid="ignore"):
        for r in range(1, NUM_DIV + 1):
            for b in range(1, NUM_BLDG + 1):
                for s in range(NUM_MAJ_SERV + 1, NUM_SERV):
                    avg_eff[r, b, s, 1] = f32(1.0)
                    fuel_share[r, b, s, 1] = f32(1.0)
                for f in range(1, nf + 1):
                    avg_eff[r, b, NUM_SERV, f] = f32(1.0)
                    fuel_share[r, b, NUM_SERV, f] = f32(eui[r, b, NUM_SERV, f] / eui[r, b, NUM_SERV, nf + 1])
    return {"ServDmdIntenBASE": sdi, "FuelShareofServiceBASE": fuel_share, "AverageEfficiencyBASE": avg_eff}
