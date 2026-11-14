"""Boiler/steam/cogeneration fuel totals: port of CALSTOT (ind.f).

For one industry and census region: totals the fuel burned by combined heat and
power (CHP) units, works out the process steam that CHP and biomass boilers do
not cover, and turns what is left into fossil boiler fuel using the boiler fuel
shares from CALBSC. Writes ENSQTY (fuel for steam, by fuel), the regional CHP
sums (GENFUEL, RPTCAP, RPTGEN), COGSTEAM and the biomass steam carried to next
year.

Works on an oracle-style state dict (FArrays keyed by lowercase Fortran name, plus
scalars) and updates it in place, indexing as the Fortran does.

Quirks kept on purpose (see SCOPE.md):
- After the fuel loop, NonCogFosFuel holds the value for the LAST main fuel, and the
  petroleum entry FuelFosSteam(51) is built from that, not from the petroleum share.
- The base-year block (calibration factors) runs only when yr = ibyr - baseyr; the
  oracle dumps do not cover that year, so it is ported but not tested.
"""

import numpy as np

f32 = np.float32
CHP_EFF = f32(0.8)
DIVISIONS = {1: (1, 2), 2: (3, 4), 3: (5, 7), 4: (8, 9)}  # census divisions in each region
# main fuel index -> CHP fuel index (exstcap/plancap order); 0 = none
CHP_FUEL = {7: 1, 11: 2, 4: 3, 41: 4, 44: 5, 48: 6, 42: 7, 46: 8, 34: 9}
SIZE_COL = ((4, 1), (7, 2), (51, 3), (42, 4), (1, 5))  # (fuel, column of sizeshr)


def calstot(s: dict, inddir: int, indreg: int) -> None:
    iyr, curcalyr, ibyr, baseyr = int(s["iyr"]), int(s["curcalyr"]), int(s["ibyr"]), int(s["baseyr"])
    numflchp, mainfuels, maxcogyr = int(s["numflchp"]), int(s["mainfuels"]), int(s["maxcogyr"])
    beff, bscibyr, bsshr = s["beff"], s["bscibyr"], s["bsshr"]
    cogthr, cogelf, coggrd, cogcap, coggen = s["cogthr"], s["cogelf"], s["coggrd"], s["cogcap"], s["coggen"]

    for k in ("genfuel", "rptcap", "rptgen"):
        s[k].a[...] = 0.0
    yr = iyr - 1989
    lo, hi = DIVISIONS[indreg]

    fuelsys = np.zeros(numflchp + 1, f32)  # 1-based like the Fortran
    fuelcogsteam = np.zeros(numflchp + 1, f32)
    for i in range(lo, hi + 1):
        for f in range(1, numflchp + 1):
            j = min(4, f)  # 1 coal, 2 oil, 3 natural gas, 4 other/renewable
            thr = cogthr[i, yr, inddir, f]
            fuelcogsteam[f] = fuelcogsteam[f] + thr / CHP_EFF
            fuel3 = cogelf[i, yr, inddir, f] + thr / CHP_EFF
            fuelsys[f] = fuelsys[f] + fuel3
            s["genfuel"][j] = s["genfuel"][j] + fuel3
            s["rptcap"][j] = s["rptcap"][j] + cogcap[i, yr, inddir, f]
            s["rptgen"][j] = s["rptgen"][j] + coggen[i, yr, inddir, f]

    cogsteam = f32(fuelcogsteam[1:numflchp + 1].sum(dtype=f32) * CHP_EFF)
    s["cogsteam"] = cogsteam

    # Boiler fuel for bulk chemicals is reported under food (issue 1369).
    if inddir == 7:
        bscibyr[inddir, indreg, 42] = bscibyr[inddir, indreg, 42] + bscibyr[9, indreg, 42]
    if inddir == 9:
        bscibyr[inddir, indreg, 42] = 0.0

    if curcalyr <= ibyr:
        biosteam = f32(bscibyr[inddir, indreg, 42] * beff[42])
    else:
        biosteam = f32(s["biosteamlag"] * (s["prodvx"] / s["prodvxlag"]))
    s["biosteamlag"] = biosteam
    s["biosteam"] = biosteam

    stemcur = f32(s["stemcur"])
    noncogsteam = f32(max(f32(0), stemcur - cogsteam))
    noncogfossteam = f32(max(f32(0), noncogsteam - biosteam))
    s["noncogsteam"], s["noncogfossteam"] = noncogsteam, noncogfossteam

    if yr == ibyr - baseyr:  # base-year calibration so CHP + non-CHP fuel match MECS
        s["stemcuribyr"][inddir, indreg] = stemcur
        s["cogsteamibyr"][inddir, indreg] = cogsteam
        s["biosteamibyr"][inddir, indreg] = biosteam
        cbio, cfos, boil = s["calibibyr_bio"], s["calibibyr_fos"], s["boilibyr"]
        cbio[inddir, indreg] = 1.0
        cfos[inddir, indreg] = 1.0
        if boil[inddir, indreg, 42] > 0:
            estimated = biosteam / beff[42]
            if estimated > 0:
                cbio[inddir, indreg] = boil[inddir, indreg, 42] / estimated
        if boil[inddir, indreg, 4] + boil[inddir, indreg, 7] + boil[inddir, indreg, 51] == 0 and noncogfossteam > 0:
            boil[inddir, indreg, 4] = f32(.0333)
            boil[inddir, indreg, 7] = f32(.0333)
            boil[inddir, indreg, 51] = f32(.0333)
        implied = boil[inddir, indreg, 4] + boil[inddir, indreg, 7] + boil[inddir, indreg, 51]
        if implied > 0:
            estimated = noncogfossteam / CHP_EFF
            if estimated > 0:
                cfos[inddir, indreg] = implied / estimated

    cogboilfuel = s["cogboilfuel"]  # declared (0:11)
    cogboilfuel.a[...] = 0.0
    cogboilfuel[1:numflchp] = fuelsys[1:numflchp + 1]
    if inddir < 7:
        cogboilfuel[1] = 0.0  # no steam coal for nonmanufacturing

    calib = s["calibibyr_fos"][inddir, indreg]
    fuelfossteam = s["fuelfossteam"]
    fuelfossteam.a[...] = 0.0
    noncogfosfuel = f32(0)
    for f in range(1, mainfuels + 1):
        noncogfosfuel = f32(noncogfossteam * bsshr[f])
        if beff[f] > 0:
            fuelfossteam[f] = (noncogfosfuel / beff[f]) * calib
    fuelfossteam[51] = (noncogfosfuel / f32(0.8)) * calib  # uses the last main fuel's value, as in Fortran

    sizeshr, size = s["sizeshr"], s["fosfuelsteamsize"]
    for b in (1, 2):  # 1: 10 MMBtu/hr or less, 2: larger
        for fuel, col in SIZE_COL:
            size[inddir, fuel, b, indreg] = fuelfossteam[fuel] * sizeshr[inddir, col, b]

    ensqty = s["ensqty"]
    for f in range(1, 51):
        ensqty[f] = fuelfossteam[f] + cogboilfuel[CHP_FUEL.get(f, 0)]

    s["enprqty"][2] = s["enprqty"][2] + biosteam / beff[42]  # wood used for biomass steam

    if yr == maxcogyr:
        s["cogsteamhist"][inddir, indreg] = f32(max(f32(0), stemcur - noncogfossteam))
