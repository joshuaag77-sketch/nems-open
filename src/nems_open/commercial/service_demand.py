"""Commercial service demand: port of the calculation part of COMServiceDemand (comm.f).

Turns floorspace into demand for each end-use service (heating, cooling, lighting,
office equipment, miscellaneous loads, ...) in surviving and new buildings, then
splits surviving demand into equipment that keeps running and equipment that
retires this year and goes to the technology choice step.

This module ports the math only. Its inputs are the arrays EIA reads from files
in the first call (intensities, shell factors, data-center factors, misc load
penetration, ...), passed in by name as Fortran-indexed arrays. Porting those
readers is separate work; tests feed this module the oracle's copies.

Names follow the Fortran so each step can be checked against comm.f.
"""

from dataclasses import dataclass

import numpy as np

from nems_open.fortran_array import FArray

BASEYR = 1990
CBECS_YEAR = 2018
CBECS_IDX = CBECS_YEAR - (BASEYR - 1)  # 29
FIRST_YEAR = CBECS_YEAR - BASEYR + 2  # CMFirstYr, 30
LAST_YEAR = 61  # CMLastYr for AEO2026 (AEOLSTYR 2050)
KSTEOYR = 37
MNUMCR = 11
NUM_DIV = MNUMCR - 2
NUM_BLDG = 11
NUM_SERV = 10  # CMnumServ; service 10 is "other", the miscellaneous loads
NUM_MAJ_SERV = 7
NUM_VAR_SDI = 6
NUM_CT = 5
NUM_SOLAR_SERV = 6

f32 = np.float32

# Miscellaneous electric loads (MELs) by kmels.txt order:
MELS = ["XfmrsDry", "KitchenVent", "Security", "LabRefFrz", "MedImaging", "LrgVidBoard",
        "CoffeeBrewers", "ElVehicles", "FumeHoods", "Laundry", "Elevators", "Escalators",
        "ITEquip", "OfficeUPS", "Shredder", "OfficePBE", "VoiceIP", "POSsystems",
        "WarehouseRobots", "Televisions"]

# Which MELs each building type carries, and how its share of the US total is set.
# "us": share of all US floorspace. "<base>": share of that floor base.
# "surv": surviving floorspace share of this building type's US surviving floorspace.
# XfmrsDry is in every building and handled separately.
MEL_SHARES = {
    1: {"Security": "us", "ElVehicles": "nowhse", "KitchenVent": "kitchen", "LrgVidBoard": "surv",
        "Elevators": "elevator", "Escalators": "escalator", "ITEquip": "us", "OfficeUPS": "us",
        "Shredder": "us", "POSsystems": "us", "Televisions": "us"},
    2: {"Security": "us", "ElVehicles": "nowhse", "KitchenVent": "kitchen", "LabRefFrz": "lab",
        "FumeHoods": "lab", "Elevators": "elevator", "Escalators": "escalator", "ITEquip": "us",
        "OfficeUPS": "us", "Shredder": "us", "POSsystems": "us", "Televisions": "us"},
    3: {"Security": "us", "ElVehicles": "nowhse", "KitchenVent": "kitchen", "ITEquip": "us",
        "OfficeUPS": "us", "Shredder": "us", "POSsystems": "us", "Televisions": "us"},
    4: {"Security": "us", "CoffeeBrewers": "brewer", "ElVehicles": "nowhse", "KitchenVent": "kitchen",
        "Elevators": "elevator", "ITEquip": "us", "OfficeUPS": "us", "Shredder": "us",
        "POSsystems": "us", "Televisions": "us"},
    5: {"Security": "us", "ElVehicles": "nowhse", "KitchenVent": "kitchen", "LabRefFrz": "lab",
        "FumeHoods": "lab", "Laundry": "laundry", "MedImaging": "med", "Elevators": "elevator",
        "Escalators": "escalator", "ITEquip": "us", "OfficeUPS": "us", "Shredder": "us",
        "POSsystems": "us", "Televisions": "us"},
    6: {"Security": "us", "ElVehicles": "nowhse", "KitchenVent": "kitchen", "Laundry": "laundry",
        "Elevators": "elevator", "Escalators": "escalator", "ITEquip": "us", "OfficeUPS": "us",
        "Shredder": "us", "POSsystems": "us", "Televisions": "us"},
    7: {"Security": "us", "CoffeeBrewers": "brewer", "ElVehicles": "nowhse", "LabRefFrz": "lab",
        "FumeHoods": "lab", "MedImaging": "med", "Elevators": "elevator", "Escalators": "escalator",
        "ITEquip": "us", "OfficeUPS": "us", "Shredder": "us", "OfficePBE": "office",
        "VoiceIP": "office", "POSsystems": "us", "Televisions": "us"},
    8: {"Security": "us", "CoffeeBrewers": "brewer", "ElVehicles": "nowhse", "LabRefFrz": "lab",
        "FumeHoods": "lab", "MedImaging": "med", "Elevators": "elevator", "ITEquip": "us",
        "OfficeUPS": "us", "Shredder": "us", "OfficePBE": "office", "VoiceIP": "office",
        "POSsystems": "us", "Televisions": "us"},
    9: {"Security": "us", "ElVehicles": "nowhse", "KitchenVent": "kitchen", "Laundry": "laundry",
        "MedImaging": "med", "Elevators": "elevator", "Escalators": "escalator", "ITEquip": "us",
        "OfficeUPS": "us", "Shredder": "us", "POSsystems": "us", "Televisions": "us"},
    10: {"Security": "us", "ElVehicles": "surv", "Elevators": "elevator", "ITEquip": "us",
         "OfficeUPS": "us", "Shredder": "us", "POSsystems": "us", "WarehouseRobots": "surv",
         "Televisions": "us"},
    11: {"Security": "us", "ElVehicles": "nowhse", "LabRefFrz": "lab", "FumeHoods": "lab",
         "Elevators": "elevator", "Escalators": "escalator", "ITEquip": "us", "OfficeUPS": "us",
         "Shredder": "us", "POSsystems": "us", "Televisions": "us"},
}
# EIA quirks kept on purpose:
# - Assembly and education compute Shredder but leave Shredder and OfficePBE out of the total.
TOTAL_SKIPS_SHREDDER_PBE = {1, 2}
# - Food sales, food service and mercantile skip the data-center adjustment for misc loads.
NO_DATACENTER_MISC = {3, 4, 9}


@dataclass
class ServiceDemandResult:
    ServDmdExBldg: FArray
    NewServDmd: FArray
    ServDmdSurv: FArray
    RetireServDmd: FArray
    ShellHeatFactor: FArray
    ShellCoolFactor: FArray
    SSDnoShell: FArray
    NSDnoShell: FArray
    RSDnoShell: FArray
    TotExplicitMiscElQ: FArray
    mel_totals: dict
    DatCtrShare: float


def datacenter_share(y: int) -> float:
    """Data centers' growing share of commercial floorspace (DatCtrShare)."""
    x = f32(y - FIRST_YEAR)
    return f32(f32(0.000002) * x ** f32(3.0) - f32(0.00002) * x ** f32(2.0)
               + f32(0.0173) * x + f32(0.001626))


def floor_bases(S, N, USS, USN, y, *, med_typo=False):
    """Floor bases (million sqft) that MELs are shared over. S, N: CMSurvFloorTot and
    CMNewFlrSpace (billion sqft) by building type. Some bases subtract surviving
    floorspace where new floorspace was surely meant; EIA's formula is kept as is.
    med_typo: the in-loop copy of MedFlrBase counts small-office new floorspace
    twice and mercantile new floorspace not at all."""
    s = lambda i: S[i, y]
    n = lambda i: N[i, y]
    us = USS[y] + USN[y]
    med_last = n(8) if med_typo else n(9)
    return {
        "brewer": (s(4) + s(7) + s(8) + n(4) + n(7) + n(8)) * f32(1000.0),
        "laundry": (s(5) + s(6) + s(9) + n(5) + n(6) + n(9)) * f32(1000.0),
        "med": (s(5) + s(7) + s(8) + s(9) + n(5) + n(7) + n(8) + med_last) * f32(1000.0),
        "elevator": us * f32(1000.0),
        "escalator": (USS[y] - s(3) - s(4) - s(8) - s(10) + USN[y] - n(3) - s(4) - s(8) - s(10)) * f32(1000.0),
        "nowhse": (USS[y] - s(10) + USN[y] - n(10)) * f32(1000.0),
        "kitchen": (USS[y] - s(7) - s(8) - s(10) - s(11) + USN[y] - n(7) - s(8) - s(10) - s(11)) * f32(1000.0),
        "lab": (s(2) + s(5) + s(7) + s(8) + s(11) + n(2) + n(5) + n(7) + n(8) + n(11)) * f32(1000.0),
        "office": (s(7) + s(8) + n(7) + n(8)) * f32(1000.0),
    }


def mel_totals(inp, y):
    """US total demand for each explicit misc load this year (trillion Btu)."""
    S, N = inp["cmsurvfloortot"], inp["cmnewflrspace"]
    USS, USN = inp["cmussurvfloortot"], inp["cmusnewfloortot"]
    pen, elq = inp["marketpenetrationmels"], inp["melselq"]
    fb = floor_bases(S, N, USS, USN, y)
    us = USS[y] + USN[y]
    base = {i + 1: pen[i + 1, y] * elq[i + 1] / f32(1000.0) for i in range(len(MELS))}
    k = lambda b: fb[b] / f32(1000.0)
    t = {
        "XfmrsDry": base[1] * us, "KitchenVent": base[2] * k("kitchen"), "Security": base[3] * us,
        "LabRefFrz": base[4] * k("lab"), "MedImaging": base[5] * k("med"),
        "LrgVidBoard": base[6] * (S[1, y] + N[1, y]), "CoffeeBrewers": base[7] * k("brewer"),
        "ElVehicles": base[8] * (f32(0.6) * (S[10, y] + N[10, y]) + f32(0.4) * fb["nowhse"] / f32(1000.0)),
        "FumeHoods": base[9] * k("lab"), "Laundry": base[10] * k("laundry"),
        "Elevators": base[11] * k("elevator"), "Escalators": base[12] * k("escalator"),
        "ITEquip": base[13] * us, "OfficeUPS": base[14] * us, "Shredder": base[15] * us,
        "OfficePBE": base[16] * k("office"), "VoiceIP": base[17] * k("office"),
        "POSsystems": base[18] * us, "WarehouseRobots": base[19] * (S[10, y] + N[10, y]),
        "Televisions": base[20] * us,
    }
    return {name: f32(v) for name, v in t.items()}


def _dc(x, factor, share):
    return x * (f32(1.0) - share) + x * factor * share


def service_demand(inp: dict, y: int) -> ServiceDemandResult:
    """One call of COMServiceDemand's calculation for year index y, after the first
    iteration (the previous-year arrays in `inp` are already set).

    inp: Fortran-named arrays as they stand when the routine starts, plus the
    routine's own input tables (see oracle/hooks.py for the full list).
    """
    surv, new = inp["survfloortotal"], inp["cmnewfloorspace"]
    total = inp["cmtotalflspc"]
    inten = inp["servdmdintenbase"]
    sfp = inp["servicedflrspcprop"]
    dcf = inp["dcf"]
    ramp = int(inp["applyramp"])
    shell_h, shell_c = inp["shellheatfactor"].copy(), inp["shellcoolfactor"].copy()
    sd, nd = inp["servdmdexbldg"].copy(), inp["newservdmd"].copy()
    sd_surv, retire = inp["servdmdsurv"].copy(), inp["retireservdmd"].copy()
    ssd_ns = inp["ssdnoshell"].copy()
    nsd_ns = inp["nsdnoshell"].copy()
    rsd_ns = inp["rsdnoshell"].copy()
    tot_misc = inp["totexplicitmiscelq"].copy()

    # Shell efficiency of the existing stock: pre-2018 buildings improve along a
    # path to their 2050 index; post-2018 construction keeps the shell it was built with.
    for b in range(1, NUM_BLDG + 1):
        for r in range(1, NUM_DIV + 1):
            span = f32(LAST_YEAR + (BASEYR - 1) - CBECS_YEAR)
            age = f32(y + (BASEYR - 1) - CBECS_YEAR)
            exist_h = (inp["existimprvht"][b, r] ** (f32(1.0) / span)) ** age
            exist_c = (inp["existimprvcl"][b, r] ** (f32(1.0) / span)) ** age
            tot_new = f32(0.0)
            new_h = f32(0.0)
            new_c = f32(0.0)
            for iy in range(CBECS_IDX, y):
                tot_new += new[r, b, iy]
                new_h += new[r, b, iy] * shell_h[b, r, 2, iy]
                new_c += new[r, b, iy] * shell_c[b, r, 2, iy]
            shell_h[b, r, 1, y] = (exist_h * (surv[r, b, y] - tot_new) + new_h) / surv[r, b, y]
            shell_c[b, r, 1, y] = (exist_c * (surv[r, b, y] - tot_new) + new_c) / surv[r, b, y]

    share = datacenter_share(y)
    mels = mel_totals(inp, y)
    S, N = inp["cmsurvfloortot"], inp["cmnewflrspace"]
    USS, USN = inp["cmussurvfloortot"], inp["cmusnewfloortot"]
    fb_loop = floor_bases(S, N, USS, USN, y, med_typo=True)
    qelcm, final_use, eui = inp["qelcm"], inp["finalendusecon"], inp["comeui"]
    fs_base = inp["fuelshareofservicebase"]

    base_el_tot = {}
    if y == FIRST_YEAR:
        for r in range(1, NUM_DIV + 1):
            acc = f32(0.0)
            for nb in range(1, NUM_BLDG + 1):
                acc += eui[r, nb, 10, 1] * total[r, nb, y - 1]
            base_el_tot[r] = acc

    for s in range(1, NUM_SERV + 1):
        for b in range(1, NUM_BLDG + 1):
            for r in range(1, NUM_DIV + 1):
                if s <= NUM_MAJ_SERV:
                    x = inten[s, b, r] / f32(1000.0) * surv[r, b, y]
                    if b == 11 and ramp == 1:
                        if y <= KSTEOYR + 3:
                            x = _dc(x, dcf[12, s], share)
                        elif KSTEOYR + 3 < y < KSTEOYR + 10:
                            x = _dc(x, dcf[b, s] * f32((y - KSTEOYR) / f32(10.0)), share)
                        else:
                            x = _dc(x, dcf[b, s], share)
                    else:
                        x = _dc(x, dcf[b, s], share)
                    ssd_ns[r, b, s] = x
                    if s == 1:
                        x = x * shell_h[b, r, 1, y]
                    if s == 2:
                        x = x * shell_c[b, r, 1, y]
                    n = inten[s, b, r] / f32(1000.0) * new[r, b, y]
                    n = _dc(n, dcf[b, s], share)
                    nsd_ns[r, b, s] = n
                    if s <= NUM_VAR_SDI:
                        n = n * sfp[b, s, 2] / sfp[b, s, 1]
                    if s == 1:
                        n = n * shell_h[b, r, 2, y]
                    if s == 2:
                        n = n * shell_c[b, r, 2, y]
                    for ct in range(1, NUM_CT + 1):
                        save = inp["ct_flag"][ct, s] * inp["pctscsavings"][ct]
                        mp = inp["marketpenetrationsc"]
                        adj = (f32(1) - save * mp[ct, b, y]) / (f32(1) - save * mp[ct, b, CBECS_IDX])
                        x = x * adj
                        n = n * adj
                elif s < NUM_SERV:
                    x = inten[s, b, r] / f32(1000.0) * surv[r, b, y]
                    n = inten[s, b, r] / f32(1000.0) * new[r, b, y]
                    if s == 8:
                        x, n = x * inp["datactrservpenetration"][y], n * inp["datactrservpenetration"][y]
                    if s == 9:
                        x, n = x * inp["officepcpenetration"][y], n * inp["officepcpenetration"][y]
                    if b == 11 and ramp == 1:
                        if y <= KSTEOYR + 3:
                            fac = dcf[12, s]
                        elif s == 9 and KSTEOYR + 3 < y <= KSTEOYR + 10:
                            fac = dcf[11, 9] * f32((y - KSTEOYR) / f32(10.0))
                        else:
                            fac = dcf[b, s]
                    else:
                        fac = dcf[b, s]
                    x, n = _dc(x, fac, share), _dc(n, fac, share)
                else:
                    # Other: unspecified misc loads grow with a services index,
                    # then the explicit MELs are shared out to this building.
                    mix = (inp["servicesindex"][y] * (f32(1) - inp["xplicitmiscshr"][b]) * fs_base[r, b, s, 1]
                           + fs_base[r, b, s, 2] + fs_base[r, b, s, 3])
                    x = inten[s, b, r] / f32(1000.0) * mix * surv[r, b, y]
                    n = inten[s, b, r] / f32(1000.0) * mix * new[r, b, y]
                    surv_b = surv[r, b, y] / f32(1000.0)
                    new_b = new[r, b, y] / f32(1000.0)
                    us = (USS[y] + USN[y])
                    F = total[r, b, y]
                    if y == FIRST_YEAR:
                        xf = mels["XfmrsDry"] * (qelcm[r, y - 1] / qelcm[11, y - 1]) * (
                            (eui[r, b, 10, 1] * total[r, b, y - 1]) / base_el_tot[r])
                    else:
                        xf = mels["XfmrsDry"] * (final_use[1, b, r, y - 1] / qelcm[11, y - 1])
                    elq = {"XfmrsDry": xf}
                    for name, how in MEL_SHARES[b].items():
                        if how == "us":
                            elq[name] = mels[name] * (F / us / f32(1000))
                        elif how == "surv":
                            elq[name] = mels[name] * (surv_b / S[b, y])
                        else:
                            elq[name] = mels[name] * (F / fb_loop[how])
                    names = [m for m in MELS if not (b in TOTAL_SKIPS_SHREDDER_PBE and m in ("Shredder", "OfficePBE"))]
                    tot = f32(0.0)
                    for m in names:
                        tot += f32(elq.get(m, 0.0))
                    tot_misc[r, b, y] = tot
                    x = x + tot * (surv_b / (surv_b + new_b))
                    n = n + tot * (new_b / (surv_b + new_b))
                    if b not in NO_DATACENTER_MISC:
                        x, n = _dc(x, dcf[b, s], share), _dc(n, dcf[b, s], share)
                sd[s, b, r, y] = x
                nd[s, b, r, y] = n

    # Rooftop solar water heating etc. displaces part of the service demand.
    solar = inp["solarrenewablecontrib"].copy()
    for r in range(1, NUM_DIV + 1):
        solar[r, 3, y] = 0.0
    for r in range(1, NUM_DIV + 1):
        for b in range(1, NUM_BLDG + 1):
            for s in range(1, NUM_SOLAR_SERV + 1):
                denom = surv[r, b, y] + new[r, b, y]
                part = solar[r, s, y] / f32(NUM_BLDG)
                sd[s, b, r, y] = max(f32(0.0), sd[s, b, r, y] - part * surv[r, b, y] / denom)
                nd[s, b, r, y] = max(f32(0.0), nd[s, b, r, y] - part * new[r, b, y] / denom)

    # Equipment retiring this year: last year's technology shares over their lifetimes.
    prev_share = inp["prevyrtechshareofservice"]
    techs_for, n_techs = inp["techsforservice"], inp["cmnumtechsforservice"]
    n_vint, by_model, life = inp["cmnumeqv"], inp["techbymodel"], inp["techlife"]
    for s in range(1, NUM_SERV + 1):
        for b in range(1, NUM_BLDG + 1):
            for r in range(1, NUM_DIV + 1):
                rp = f32(0.0)
                for ts in range(1, int(n_techs[s]) + 1):
                    t = int(techs_for[s, ts])
                    for v in range(1, int(n_vint[t]) + 1):
                        if by_model[t, v] == 1 and life[t, v] > 0.0:
                            rp += prev_share[r, b, s, t, v] / life[t, v]
                retire[s, b, r, y] = sd[s, b, r, y] * rp
                sd_surv[s, b, r, y] = sd[s, b, r, y] - retire[s, b, r, y]
                rsd_ns[r, b, s] = ssd_ns[r, b, s] * rp
                ssd_ns[r, b, s] = ssd_ns[r, b, s] - rsd_ns[r, b, s]

    for s in range(1, NUM_SERV + 1):
        for b in range(1, NUM_BLDG + 1):
            retire[s, b, 11, y] = retire[s, b, 1:NUM_DIV, y].sum(dtype=np.float32)
            sd_surv[s, b, 11, y] = sd_surv[s, b, 1:NUM_DIV, y].sum(dtype=np.float32)
            nd[s, b, 11, y] = nd[s, b, 1:NUM_DIV, y].sum(dtype=np.float32)

    return ServiceDemandResult(sd, nd, sd_surv, retire, shell_h, shell_c, ssd_ns, nsd_ns,
                               rsd_ns, tot_misc, mels, float(share))
