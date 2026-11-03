"""TRUCK_GHGMEET (tranfrt.f): Phase 2/3 heavy-duty GHG compliance by averaging set.

New-truck CO2 per ton-mile against the standard gives credits (with advanced
technology multipliers), summed by averaging set. A set that comes up short on the
last try spends banked base credits (five-year life) and then advanced ones; from
the spend-all year, sets 2-3 may also use set 1's bank.

EIA quirks kept:
- MAX_SPEND_SHR is an INTEGER set to 0.5, so it is 0 and cross-set credit trading
  does nothing.
- The bank (GHGBank) is a saved local and past years' credits are spent on every
  NEMS iteration, not once per year.
"""

import numpy as np

from nems_open.transportation.common import expf, f32, fsum, MNUMCR
from nems_open.transportation.frt_common import CAFE14, CAFE19, CAFE4, FUEL12, ONE, V, ZERO
from nems_open.transportation.frt_common import NVMT as NVMT_

CRED_LIFE = 5
NONZEVS = [1, 2, 3, 4, 5, 11, 12]
ZEVS = [6, 7, 8, 9, 10]


def truck_ghgmeet(s: dict, carry: dict) -> None:
    """carry: ghgbank(MNUMYR, CAFE4, 2) as it stood when the routine was entered."""
    v = V(s)
    iyr, yrs, itry = v.i("iyr"), v.i("yrs"), v.i("itryghg")
    ghgtry = v["ghgtry"]
    bank = carry["ghgbank"]
    creds = v.priv("ghg_creds", lambda: np.zeros((62, CAFE14 + 1, FUEL12 + 1), dtype=f32))
    avgset = v.priv("ghg_creds_avgset", lambda: np.zeros((62, CAFE4 + 1, FUEL12 + 1), dtype=f32))
    agg = v["ghg_creds_agg"]
    creds[6:2017 - 1989 + 1] = 0.0
    bank[6:2017 - 1989, :, :] = 0.0
    avgset[6:2017 - 1989 + 1] = 0.0
    agg[6:2017 - 1989, :] = 0.0
    v["techshare"][6:2017 - 1989, :, :, :] = 0.0
    std = v["hdv_ghgstd"]
    spendall = 2030 if std[2, 2032 - 1989, 1] == std[2, 2027 - 1989, 1] else 2032

    creds[iyr] = 0.0
    p219, p24 = v["p219map"], v["p24map"]
    mpg, gco2, pay = v["new_mpg_19"], v["gco2_gal"], v["epa_payload"]
    tonmi, stk = v["new_gco2tonmi_p2"], v["trkstk_19r"]
    afv, life = v["hdv_afv_credits"], v["hdv_usefullife"]
    for c19 in range(1, CAFE19 + 1):
        c14 = int(p219[c19])
        v["icafe14"], v["icafe4"] = c14, int(p24[c14])
        for ifuel in range(1, FUEL12 + 1):
            m = mpg[iyr, ifuel, c19]
            if m == 0.0:
                continue
            tonmi[iyr, ifuel, c19] = ONE / m * gco2[ifuel, c14] / (pay[c14] / f32(2000.0))
            creds[iyr, c14, ifuel] = creds[iyr, c14, ifuel] + (
                (std[c14, iyr, ifuel] - tonmi[iyr, ifuel, c19]) * (pay[c14] / f32(2000.0))
                * fsum(stk[iyr, c19, 1, ifuel, :, 1:MNUMCR - 2]) * afv[ifuel, iyr] * life[ifuel, c14] * f32(1.0e-6))
        v["ifuel"] = FUEL12 + 1
    v["icafe19"] = CAFE19 + 1

    avgset[iyr] = 0.0
    agg[iyr, :] = 0.0
    for c14 in range(1, CAFE14 + 1):
        c4 = int(p24[c14])
        avgset[iyr, c4, 1:] = avgset[iyr, c4, 1:] + creds[iyr, c14, 1:]
        agg[iyr, c4] = agg[iyr, c4] + fsum(creds[iyr, c14, 1:])
    v["icafe14"], v["icafe4"] = CAFE14 + 1, int(p24[CAFE14])

    passed = v["hdv_passghg"]
    sal_p2 = v["trksal_p2"]
    bank[iyr, :, :] = 0.0
    for c4 in range(1, CAFE4 + 1):
        v["icafe4"] = c4
        if yrs == 2030 and itry == 1:
            # Advanced credits from 2027 and before turn into base credits at the average multiplier.
            for i in range(3, CRED_LIFE + 1):
                cred_sum = sales = ZERO
                for c14 in range(1, CAFE14 + 1):
                    if int(p24[c14]) != c4:
                        continue
                    cred_sum = cred_sum + fsum(np.array([sal_p2[iyr - i, c14, k] * afv[k, iyr - i] for k in ZEVS], dtype=f32))
                    sales = sales + fsum(np.array([sal_p2[iyr - i, c14, k] for k in ZEVS], dtype=f32))
                avg = cred_sum / sales
                bank[iyr - i, c4, 1] = bank[iyr - i, c4, 1] + bank[iyr - i, c4, 2] / avg
                bank[iyr - i, c4, 2] = 0.0
        if agg[iyr, c4] >= 0.0:
            passed[iyr, c4] = 1
            if (afv[1:FUEL12, iyr] == 1.0).all():
                bank[iyr, c4, 1] = agg[iyr, c4]
            else:
                base = fsum(np.array([avgset[iyr, c4, k] for k in NONZEVS], dtype=f32))
                adv = fsum(np.array([avgset[iyr, c4, k] for k in ZEVS], dtype=f32))
                if base < 0.0:
                    bank[iyr, c4, 1] = 0.0
                    bank[iyr, c4, 2] = adv + base
                else:
                    bank[iyr, c4, 1] = base
                    bank[iyr, c4, 2] = adv
        elif itry == ghgtry:
            max_cred = 1 if yrs >= spendall else 5
            base_sum = fsum(bank[iyr - CRED_LIFE:iyr - max_cred, c4, 1])
            if base_sum > 0.0:
                if base_sum > -agg[iyr, c4]:
                    for i in range(CRED_LIFE, max_cred - 1, -1):
                        if bank[iyr - i, c4, 1] >= -agg[iyr, c4]:
                            bank[iyr - i, c4, 1] = bank[iyr - i, c4, 1] + agg[iyr, c4]
                            agg[iyr, c4] = 0.0
                            passed[iyr, c4] = 1
                            break
                        elif bank[iyr - i, c4, 1] > 0.0:
                            agg[iyr, c4] = agg[iyr, c4] + bank[iyr - i, c4, 1]
                            bank[iyr - i, c4, 1] = 0.0
                    if passed[iyr, c4]:
                        continue
                else:
                    agg[iyr, c4] = agg[iyr, c4] + base_sum
                    bank[iyr - CRED_LIFE:iyr - max_cred, c4, 1] = 0.0
            adv_sum = fsum(bank[iyr - CRED_LIFE:iyr - 1, c4, 2])
            if adv_sum > 0.0:
                if adv_sum > -agg[iyr, c4]:
                    for i in range(CRED_LIFE, 0, -1):
                        if bank[iyr - i, c4, 2] >= -agg[iyr, c4]:
                            bank[iyr - i, c4, 2] = bank[iyr - i, c4, 2] + agg[iyr, c4]
                            agg[iyr, c4] = 0.0
                            passed[iyr, c4] = 1
                            break
                        elif bank[iyr - i, c4, 2] > 0.0:
                            agg[iyr, c4] = agg[iyr, c4] + bank[iyr - i, c4, 2]
                            bank[iyr - i, c4, 2] = 0.0
                else:
                    agg[iyr, c4] = agg[iyr, c4] + adv_sum
                    bank[iyr - CRED_LIFE:iyr - 1, c4, 2] = 0.0
    v["icafe4"] = CAFE4 + 1

    if yrs >= spendall and itry == ghgtry:
        for c4 in (2, 3):
            v["icafe4"] = c4
            set1 = fsum(bank[iyr - CRED_LIFE:iyr - 1, 1, 1])
            if not passed[iyr, c4] and set1 > 0.0:
                if set1 > -agg[iyr, c4]:
                    for i in range(1, CRED_LIFE + 1):
                        if bank[iyr - i, 1, 1] >= -agg[iyr, c4]:
                            bank[iyr - i, 1, 1] = bank[iyr - i, 1, 1] - agg[iyr, c4]
                            agg[iyr, c4] = 0.0
                            passed[iyr, c4] = 1
                        else:
                            agg[iyr, c4] = agg[iyr, c4] + bank[iyr - i, 1, 1]
                            bank[iyr - i, 1, 1] = 0.0
                else:
                    agg[iyr, c4] = agg[iyr, c4] + fsum(bank[iyr - CRED_LIFE:iyr - 1, 1, 1])
                    bank[iyr - CRED_LIFE:iyr - 1, 1, 1] = 0.0
        v["icafe4"] = 4
        # Cross-set trading, with MAX_SPEND_SHR an INTEGER 0: every branch adds or keeps zero.
        max_cred, share = 3, 0
        if fsum(bank[iyr - CRED_LIFE:iyr - max_cred, 2:4, 1]) > 0.0:
            for c4 in range(2, CAFE4 + 1):
                v["icafe4"] = c4
                if passed[iyr, c4]:
                    continue
                for i in range(2, CAFE4 + 1):
                    if i == c4:
                        continue
                    tot = fsum(bank[iyr - CRED_LIFE:iyr - max_cred, i, 1])
                    if tot > 0.0:
                        if tot * share > -agg[iyr, c4]:
                            for itrade in range(max_cred, CRED_LIFE + 1):
                                if bank[iyr - itrade, i, 1] * share >= -agg[iyr, c4]:
                                    bank[iyr - itrade, i, 1] = bank[iyr - itrade, i, 1] - agg[iyr, c4]
                                    agg[iyr, c4] = 0.0
                                    passed[iyr, c4] = 1
                                else:
                                    agg[iyr, c4] = agg[iyr, c4] + bank[iyr - itrade, i, 1] * f32(share)
                                    bank[iyr - itrade, i, 1] = bank[iyr - itrade, i, 1] * f32(1 - share)
                        else:
                            agg[iyr, c4] = agg[iyr, c4] + fsum(bank[iyr - CRED_LIFE:iyr - 1, i, 1]) * f32(share)
                            bank[iyr - CRED_LIFE:iyr - max_cred, i, 1] = bank[iyr - CRED_LIFE:iyr - max_cred, i, 1] * f32(1 - share)
            v["icafe4"] = CAFE4 + 1


ICE_MAP = [1, 2, 4, 11]
ZEV_MAP = [6, 9, 10, 12]


def truck_ghgzev(s: dict) -> None:
    """Last GHG try: convert ICE sales to ZEVs in failing averaging sets, in proportion
    to each class's and powertrain's share of the deficit."""
    v = V(s)
    iyr = v.i("iyr")
    passed, agg = v["hdv_passghg"], v["ghg_creds_agg"]
    p219, p24 = v["p219map"], v["p24map"]
    mpg, gco2, pay, std, life = v["new_mpg_19"], v["gco2_gal"], v["epa_payload"], v["hdv_ghgstd"], v["hdv_usefullife"]
    stk, shr_v, shr_r = v["trkstk_19r"], v["fuel_shr_ivmt"], v["fuel_shr_regn"]
    deficit = v.priv("ghgzev_deficit", lambda: np.zeros((CAFE19 + 1, 5, MNUMCR + 1, 3), dtype=f32))
    for iregn in range(1, MNUMCR - 1):
        for iflt in (1, 2):
            for c19 in range(1, CAFE19 + 1):
                c14 = int(p219[c19])
                c4 = int(p24[c14])
                if passed[iyr, c4]:
                    continue
                for iice, ifuel in enumerate(ICE_MAP, start=1):
                    d = max(ZERO, (ONE / mpg[iyr, ifuel, c19] * gco2[ifuel, c14] * (pay[c14] / f32(2000.0)) - std[c14, iyr, ifuel])
                            * stk[iyr, c19, 1, ifuel, iflt, iregn] * life[ifuel, c14] * f32(1.0e-6))
                    deficit[c19, iice, iregn, iflt] = ZERO if c19 == CAFE19 else d
    tot = np.zeros(CAFE4 + 1, dtype=f32)
    for c19 in range(1, CAFE19 + 1):
        c4 = int(p24[int(p219[c19])])
        tot[c4] = tot[c4] + fsum(deficit[c19, 1:, 1:MNUMCR - 1, 1:])
    cred = np.zeros(CAFE4 + 1, dtype=f32)
    npv, pback = v["npv_choice"], v["pback_shr"]
    bev, fcev, fchev, h2ice, infra = v["inc_cost_bev"], v["inc_cost_fcev"], v["inc_cost_fchev"], v["inc_cost_h2ice"], v["bev_infra_cost"]
    comp = v["ghg_comp_cost"]
    for iregn in range(1, MNUMCR - 1):
        v["iregn"] = iregn
        for c19 in range(1, CAFE19 + 1):
            v["icafe19"] = c19
            if c19 == CAFE19:
                continue
            c14 = int(p219[c19])
            c4 = int(p24[c14])
            v["icafe14"], v["icafe4"] = c14, c4
            if passed[iyr, c4]:
                continue
            comp[c19, iregn, iyr] = 0.0
            for iflt in (1, 2):
                v["iflt"] = iflt
                pre = fsum(stk[iyr, c19, 1, :, iflt, iregn])
                need = np.zeros(5, dtype=f32)
                for iice, ifuel in enumerate(ICE_MAP, start=1):
                    x = deficit[c19, iice, iregn, iflt] / tot[c4] * (-agg[iyr, c4])
                    need[iice] = x / life[ifuel, c14] / f32(1.0e-6) / (ONE / mpg[iyr, ifuel, c19] * gco2[ifuel, c14])
                temp = np.zeros(5, dtype=f32)
                ice = np.zeros(5, dtype=f32)
                for ivmt in range(1, NVMT_ + 1):
                    v["ivmt"] = ivmt
                    for iice, ifuel in enumerate(ICE_MAP, start=1):
                        if ivmt == 1:
                            temp[iice] = fsum(shr_v[iyr, :, iflt, c19, ifuel, iregn])
                        ice[iice] = shr_v[iyr, ivmt, iflt, c19, ifuel, iregn] / temp[iice] if temp[iice] > 0.0 else ZERO
                    avg = np.zeros(4, dtype=f32)
                    for izev, ifuel in enumerate(ZEV_MAP):
                        v["ifuel"] = ifuel
                        avg[izev] = fsum(pback[:, c19] * npv[c19, ifuel, ivmt, :, iregn, iyr])
                    g = np.zeros(4, dtype=f32)
                    g[0] = avg[0] - (bev[ivmt, c19, iyr] - infra[c19, iyr]) if (iflt == 1 or c19 >= 16) else avg[0] - bev[ivmt, c19, iyr]
                    g[1] = avg[1] - fcev[ivmt, c19, iyr]
                    g[2] = avg[2] - fchev[ivmt, c19, iyr]
                    g[3] = avg[3] - h2ice[ivmt, c19, iyr]
                    g = g / f32(10000)
                    e = expf(g)
                    g = e / (e[0] + e[1] + e[2] + e[3])
                    if c19 <= 4:
                        g = np.array([ONE, ZERO, ZERO, ZERO], dtype=f32)
                    comp[c19, iregn, iyr] = comp[c19, iregn, iyr] + fsum(g * avg) * fsum(need[1:] * ice[1:])
                    shifted = ZERO
                    for iice, ifuel in enumerate(ICE_MAP, start=1):
                        moved = need[iice] * ice[iice]
                        stk[iyr, c19, 1, ifuel, iflt, iregn] = stk[iyr, c19, 1, ifuel, iflt, iregn] - moved
                        cred[c4] = cred[c4] + (moved) * (ONE / mpg[iyr, ifuel, c19] * gco2[ifuel, c14] * life[ifuel, c14]) * f32(1.0e-6)
                        shifted = shifted + moved
                        shr_v[iyr, ivmt, iflt, c19, ifuel, iregn] = shr_v[iyr, ivmt, iflt, c19, ifuel, iregn] - moved / pre
                    for izev, ifuel in enumerate(ZEV_MAP):
                        stk[iyr, c19, 1, ifuel, iflt, iregn] = stk[iyr, c19, 1, ifuel, iflt, iregn] + shifted * g[izev]
                        shr_v[iyr, ivmt, iflt, c19, ifuel, iregn] = shr_v[iyr, ivmt, iflt, c19, ifuel, iregn] + shifted * g[izev] / pre
                    v["ifuel"] = ZEV_MAP[-1]
                v["ivmt"] = NVMT_ + 1

    sc19 = v["sc19map"]
    for iregn in range(1, MNUMCR - 1):
        for iflt in (1, 2):
            for c19 in range(1, CAFE19 + 1):
                v["isc4"] = int(sc19[c19])
                for ifuel in range(1, FUEL12 + 1):
                    shr_r[iyr, c19, ifuel, iflt, iregn] = 0.0
                    t = fsum(stk[iyr, c19, 1, :, iflt, iregn])
                    if t > 0.0:
                        shr_r[iyr, c19, ifuel, iflt, iregn] = fsum(shr_v[iyr, :, iflt, c19, ifuel, iregn])
                    stk[iyr, c19, 1, ifuel, iflt, iregn] = shr_r[iyr, c19, ifuel, iflt, iregn] * fsum(stk[iyr, c19, 1, :, iflt, iregn])
                    if iregn == MNUMCR - 2:
                        stk[iyr, c19, 1, ifuel, iflt, MNUMCR] = fsum(stk[iyr, c19, 1, ifuel, iflt, 1:MNUMCR - 2])
    v.s.update({v.key("iregn"): MNUMCR - 1, v.key("iflt"): 3, v.key("icafe19"): CAFE19 + 1, v.key("ifuel"): FUEL12 + 1})
    for c4 in range(1, CAFE4 + 1):
        if not passed[iyr, c4]:
            agg[iyr, c4] = agg[iyr, c4] + cred[c4]
            if agg[iyr, c4] >= -1000.0:
                passed[iyr, c4] = 1
    v["icafe4"] = CAFE4 + 1
