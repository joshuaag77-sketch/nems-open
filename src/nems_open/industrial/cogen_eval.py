"""Economic screening of combined heat and power (CHP) systems: port of EVALCOGEN
and ACCEPTANCE (ind.f).

For eight standard CHP systems, one per steam-load segment, prices the electricity
a system would make against the extra fuel it burns, and turns the payback period
into the fraction of the technical potential that firms would accept. CALGEN uses
EconFrac and PowerSteam to size each year's new CHP capacity.

Works on an oracle-style state dict (FArrays keyed by lowercase Fortran name plus
scalars) and updates it in place.
"""

import numpy as np

f32 = np.float32


def acceptance(accept_frac, n: int, payback) -> np.float32:
    """Fraction accepting at a payback period, interpolated between whole years."""
    if np.isnan(payback) or payback < 0:
        return f32(0)
    i = int(np.floor(payback)) + 1
    if i > n:
        return f32(0)
    top = accept_frac[i]
    bot = accept_frac[i + 1] if i <= n - 1 else f32(0)
    frac = f32(payback - np.floor(payback))
    return f32(top - frac * (top - bot))


def evalcogen(s: dict, year: int) -> None:
    nsys, nload = int(s["nsys"]), int(s["nload"])
    indreg, inddir, curiyr = int(s["indreg"]), int(s["inddir"]), int(s["curiyr"])
    cfelq = f32(s["cfelq"])
    ix = slice(1, nsys)  # FArray slices are inclusive, as in Fortran

    s["cogcapcostkw"][ix] = s["capcostyearly"][year, ix]
    s["cheatrate"][ix] = s["cheatrateyearly"][year, ix]
    s["overalleff"][ix] = s["overalleffyearly"][year, ix]
    s["elecgeneff"][ix] = cfelq / s["cheatrate"][ix]
    qelas = s["qelas"]
    util = f32(s["maxregchputil"][indreg, inddir]) * (qelas[11, curiyr] / qelas[11, 22])
    capfac, sizekw = s["capfac"], s["cogsizekw"]
    s["elecsizemwh"][ix] = sizekw[ix] * f32(8.760) * np.minimum(capfac[ix], util)
    s["fueluse"][ix] = s["elecsizemwh"][ix] * s["cheatrate"][ix] / f32(10.0 ** 6)
    s["powersteam"][ix] = s["elecgeneff"][ix] / (s["overalleff"][ix] - s["elecgeneff"][ix])
    s["steamoutput"][ix] = sizekw[ix] * (cfelq / f32(10 ** 6)) / s["powersteam"][ix]
    s["eboileff"][1:nload] = f32(0.8)

    price_fuel, price_elec = f32(s["cogfuelprice"]), f32(s["cogelecprice"])
    in_itc = int(s["capcostmultstart"]) <= year <= int(s["capcostmultend"])
    disrate = f32((s["mc_rmtcm10y"][curiyr]
                   - ((s["mc_cpi"][11, curiyr] / s["mc_cpi"][11, curiyr - 1]) - 1) * 100
                   + 2.0) / 100.0)
    for il in range(1, nload + 1):
        s["cogsys"][il] = il
        isys = il
        fuelcost = s["fueluse"][isys] * price_fuel
        existfueluse = s["steamoutput"][isys] * f32(8.76) * min(capfac[isys], util) / s["eboileff"][il]
        existfuelcost = existfueluse * price_fuel
        elecvalue = s["elecsizemwh"][isys] * price_elec * cfelq / f32(10 ** 6)
        incrfuelcost = fuelcost - existfuelcost
        operprofit = elecvalue - incrfuelcost
        capcost = s["cogcapcostkw"][isys]
        if in_itc:
            capcost = s["cogcapcostkw"][isys] * s["capcostmult"][isys]
        investment = sizekw[isys] * capcost * f32(.001)
        s["fuelcost"][il], s["existfueluse"][il], s["existfuelcost"][il] = fuelcost, existfueluse, existfuelcost
        s["elecvalue"][il], s["incrfuelcost"][il], s["investment"][il] = elecvalue, incrfuelcost, investment
        if operprofit <= 0.5:
            s["operprofit"][il], s["cpayback"][il], s["econfrac"][il] = f32(-0.5), f32(99), f32(0)
        else:
            s["operprofit"][il] = operprofit
            payback, pvsav = f32(99), f32(0)
            for t in range(1, 100):
                chpyr = f32(t)
                pvsav = f32(operprofit / (f32(1 + disrate) ** chpyr) + pvsav)
                if pvsav >= investment:
                    payback = f32(chpyr - (pvsav - investment) / (operprofit / (f32(1 + disrate) ** chpyr)))
                    break
            s["cpayback"][il] = payback
            table = s["acceptfrac"] if il <= 6 else s["acceptfrac2"]
            s["econfrac"][il] = acceptance(table, 13, payback)
