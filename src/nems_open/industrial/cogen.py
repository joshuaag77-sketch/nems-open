"""Combined heat and power (CHP) generation for one industry and census region: port
of CALGEN (ind.f).

Each call:
  1. averages expected natural gas and electricity prices over this year and the next
     few (LOOKAHEAD), weighted by each census division's consumption, and converts
     them to the dollar year the CHP cost data use;
  2. works out how heavily existing CHP was used in recent history (utilization);
  3. prices eight standard CHP systems (EVALCOGEN) and starts this year's arrays
     with the planned builds (COGINIT);
  4. after the last year of EIA-860 history, adds a share of the economic potential
     (steam load not already served by CHP, times the fraction that pays back fast
     enough, times a regional penetration score) as new natural gas CHP;
  5. sums generation sold to the grid (ELSALE) and used on site (ELOWN).

Works on an oracle-style state dict (FArrays keyed by lowercase Fortran name plus
scalars) and updates it in place.

Quirks kept on purpose (see SCOPE.md):
- RegCHPutil and maxRegCHPutil are cleared for every industry and region on each call;
  only the current industry and region's entries are refilled.
- The AB32 branch is always on (the runtime switch defaults to 1; the oracle never sets it).
- The paper byproduct-biomass addition is not ported: CALGEN is never called for paper.
"""

import numpy as np

from nems_open.industrial.cogen_eval import evalcogen
from nems_open.industrial.cogen_init import DIVISIONS, coginit

f32 = np.float32
BYPBEFF = f32(0.69)  # boiler efficiency for byproduct steam
REG_CHP_SCORE = (f32(0.335), f32(0.175), f32(0.235), f32(0.255))  # regional penetration adjustment
# Grid share assumed for new capacity, by industry (average of 2017-2021 EIA-860 data).
COGGRD_NEW = [0.2038, 0.8188, 0.0, 0.0, 0.4339, 0.0, 0.0326, 0.0949, 0.2653, 0.0, 0.0117, 0.2686,
              0.2729, 0.0, 0.0, 0.0039, 0.0809, 0.9352, 0.5653, 0.0181, 0.1516, 0.0, 0.0, 0.0]
STEAM_SEG = {7: "steamseg_food", 8: "steamseg_paper", 9: "steamseg_chem", 12: "steamseg_steel"}


def _prices(s, inddir, indreg, lo, hi):
    curiyr = int(s["curiyr"])
    pyr = curiyr
    look, ijump = int(s["lookahead"]), int(s["ijumpyr"])
    cs = f32(s["carbshr_ab"][inddir, indreg])  # AB32 on
    qgfin, qelin, agfin, pgfin, aelin = s["qgfin"], s["qelin"], s["agfin"], s["pgfin"], s["aelin"]
    fuel_price, elec_price = f32(0), f32(0)
    jfrac = f32(1) / (f32(1) + f32(look))
    for j in range(0, look + 1):
        escalng, escalel = f32(0), f32(0)
        totq1 = f32(sum(qgfin[i, pyr] for i in range(lo, hi + 1)))
        totq2 = f32(sum(qelin[i, pyr] for i in range(lo, hi + 1)))
        for i in range(lo, hi + 1):
            k = min(ijump, pyr + j)
            escalng = escalng + ((agfin[i, k] * cs + pgfin[i, k] * (f32(1) - cs))
                                 / (agfin[i, pyr] * cs + pgfin[i, pyr] * (f32(1) - cs))) * qgfin[i, pyr] / totq1
            escalel = escalel + (aelin[i, k] / aelin[i, pyr]) * qelin[i, pyr] / totq2
        fuel_price = fuel_price + s["prcx"][3, indreg, 1] * escalng
        elec_price = elec_price + s["prcx"][1, indreg, 1] * escalel
    deflator = s["mc_jpgdp"][int(s["dollaryearchp"]) - int(s["baseyr"]) + 1]
    fuel_price = fuel_price * jfrac * deflator
    elec_price = elec_price * jfrac * deflator
    elec_price = elec_price * (f32(1) - s["standbyfrac"])
    return f32(fuel_price), f32(elec_price)


def _utilization(s, inddir, indreg, lo, hi):
    maxcogyr = int(s["maxcogyr"])
    cap, gen = s["cogcap"], s["coggen"]
    reg, mx = s["regchputil"], s["maxregchputil"]
    reg.a[...] = 0.0
    mx.a[...] = 0.0
    w = [f32(0)] * 6  # 1-based, five years of history
    for u in range(1, 6):
        c = f32(cap[lo:hi, maxcogyr - u, inddir, 11].sum(dtype=f32))
        if c > 0:
            w[u] = f32(gen[lo:hi, maxcogyr - u, inddir, 11].sum(dtype=f32) / c / f32(8.760))
        if w[u] < 0 or w[u] > 1:
            w[u] = f32(0)
    c = f32(cap[lo:hi, maxcogyr, inddir, 11].sum(dtype=f32))
    if c > 0:
        reg[indreg, inddir] = gen[lo:hi, maxcogyr, inddir, 11].sum(dtype=f32) / c / f32(8.760)
    mx[indreg, inddir] = max(f32(0.05), reg[indreg, inddir], *w[1:])
    # quality check on the CHP data from the EIA-860 survey
    mx[indreg, inddir] = min(max(mx[indreg, inddir], f32(0.05)), f32(0.90))
    reg[indreg, inddir] = min(max(reg[indreg, inddir], f32(0.05)), f32(0.90))


def calgen(s: dict, inddir: int, indreg: int) -> None:
    curiyr, curcalyr, iyr = int(s["curiyr"]), int(s["curcalyr"]), int(s["iyr"])
    maxcogyr, numflchp, nload = int(s["maxcogyr"]), int(s["numflchp"]), int(s["nload"])
    lo, hi = DIVISIONS[indreg]
    steamseg = s[STEAM_SEG.get(inddir, "steamseg_other")]

    s["cogfuelprice"], s["cogelecprice"] = _prices(s, inddir, indreg, lo, hi)
    _utilization(s, inddir, indreg, lo, hi)
    evalcogen(s, curcalyr)

    # Steam demand from buildings (HVAC) plus process and assembly
    stemcur = f32(s["enbqty"][2, 3] + s["enpiqty"][1])
    if curcalyr == int(s["ibyr2"]):
        s["stemcurlag"] = stemcur
    if stemcur < 0:
        stemcur = f32(0)
    s["stemcur"] = stemcur

    # Steam from byproduct fuels
    bypstmm = bypstmi = bypstmr = f32(0)
    for k in range(1, int(s["ifsbyp"]) + 1):
        ifx = int(s["ifslocby"][k])
        if ifx <= 30:
            bypstmm = bypstmm + s["bypbscm"][ifx] * BYPBEFF
        elif ifx <= 40:
            bypstmi = bypstmi + s["bypbsci"][ifx - 30] * BYPBEFF
        else:
            bypstmr = bypstmr + s["bypbscr"][ifx - 40] * BYPBEFF
    s["bypstmm"], s["bypstmi"], s["bypstmr"] = bypstmm, bypstmi, bypstmr
    s["bypstm"] = f32(bypstmm + bypstmi + bypstmr)

    coginit(s, inddir, indreg)

    coggen, cogcap, cogthr, cogelf, coggrd = (s[k] for k in ("coggen", "cogcap", "cogthr", "cogelf", "coggrd"))
    if curiyr > maxcogyr:
        # Economic potential from steam load not already met by CHP or biofuels
        noncogstm = max(f32(0), f32(s["stemcur"] - s["cogsteamhist"][inddir, indreg]))
        sl = slice(1, nload)
        cogsys = [int(s["cogsys"][il]) for il in range(1, nload + 1)]
        powersteam = np.array([s["powersteam"][k] for k in cogsys], dtype=f32)
        cheatrate = np.array([s["cheatrate"][k] for k in cogsys], dtype=f32)
        techpot = (noncogstm * steamseg[sl] / f32(.008760)) * powersteam / f32(3.412)
        econpot = techpot * s["econfrac"][sl]
        penetrate = s["penetration"][sl] * REG_CHP_SCORE[indreg - 1]
        in_itc = int(s["capcostmultstart"]) <= iyr <= int(s["capcostmultend"])
        for il in range(nload):
            if in_itc and s["capcostmult"][cogsys[il]] < f32(0.97):
                penetrate[il] = penetrate[il] * f32(1.25)  # speeds the usual 1/20 a year to 1/16 during tax credits
        capaddmw = f32((econpot * penetrate).sum(dtype=f32))
        reg, mx = s["regchputil"][indreg, inddir], s["maxregchputil"][indreg, inddir]
        gen = (econpot * penetrate) * f32(8.670) * (reg + ((mx - reg) / f32(int(s["ieyr"]) - 2011)) * f32(curcalyr - 2011))
        capaddgwh = f32(gen.sum(dtype=f32))
        stmaddtril = f32(((gen * f32(s["cfelq"]) / f32(10.0 ** 6)) / powersteam).sum(dtype=f32))
        avehtrt = f32((gen * cheatrate).sum(dtype=f32))
        if capaddgwh > 0:
            avehtrt = avehtrt / capaddgwh

        dshr = f32(1) / f32(hi - lo + 1)
        fuel = 3  # natural gas
        for i in range(lo, hi + 1):
            newgen = capaddgwh * dshr
            oldgrd = coggen[i, curiyr, inddir, fuel] * coggrd[i, curiyr, inddir, fuel]
            newgrd = newgen * f32(COGGRD_NEW[inddir - 1])
            if newgen + coggen[i, curiyr, inddir, fuel] > 0:
                coggrd[i, curiyr, inddir, fuel] = (oldgrd + newgrd) / (coggen[i, curiyr, inddir, fuel] + newgen)
            coggen[i, curiyr, inddir, fuel] = capaddgwh * dshr + coggen[i, curiyr, inddir, fuel]
            cogcap[i, curiyr, inddir, fuel] = capaddmw * dshr + cogcap[i, curiyr, inddir, fuel]
            cogthr[i, curiyr, inddir, fuel] = stmaddtril * dshr + cogthr[i, curiyr, inddir, fuel]
            cogelf[i, curiyr, inddir, fuel] = ((capaddgwh * avehtrt / f32(10.0 ** 6)) - (stmaddtril / f32(.8))) * dshr \
                + cogelf[i, curiyr, inddir, fuel]

    if inddir <= 21:  # generation sold to the grid and used on site, all fuels and divisions
        g = coggen[lo:hi, curiyr, inddir, 1:numflchp]
        r = coggrd[lo:hi, curiyr, inddir, 1:numflchp]
        s["elsale"] = f32((g * r).sum(dtype=f32))
        s["elown"] = f32((g * (f32(1) - r)).sum(dtype=f32))
