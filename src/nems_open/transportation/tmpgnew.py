"""TMPGNEW (tran.f): new light-duty vehicle fuel economy, price and sales.

The routine runs in stages, each its own function here so each can be tested
against the oracle's dump at that point:

  setup        PHEV electric VMT shares, FEM attributes in the EPA calibration years
  (LIONCOSTCALC, in ldv_tech)
  nameplates   new nameplates by fuel type, make/model availability, gasoline price
               terms, then the start of FEM pass 1
  pass 1       FEMCALC, CGSHARE, TATTRIB, TALT2, TALT2X, CAFECALC(0) and (1)
  passes       pass 2 raises the regulatory cost signal step by step, pass 3 gives
               back horsepower, then CAFEGHG_MEET forces compliance if still short
"""

import numpy as np

from nems_open.transportation.common import MAXLDV, MNUMCR, f32, fsum
from nems_open.transportation import cafe, cafe_meet, femcalc, ldv_attrib, ldv_choice
from nems_open.transportation.common import STOCKYR
from nems_open.transportation.ldv_tech import afvadj, lioncostcalc
from nems_open.transportation.mean_funcs import weighted_mean

BASE, PREV, CURRENT = 0, 1, 2
GAS = 1
MAXCLASS = 8
MAXGROUP = 11
CARGRP = 5
LTKGRP = 6
XYR = 2022
FEM_ATTRS = [("fe", "femmpg", "epampg"), ("weight", "femwgt", "epawgt"), ("price", "fempri", "epapri"),
             ("hp", "femhp", "epahp"), ("tanksize", "femtsz", "epatsz"), ("range", "femrng", "eparng")]


def setup(s: dict) -> None:
    yrs, epa = int(s["curcalyr"]), int(s["epalyr"])
    evmt, sales = s["phev_evmt"], s["cafesales"]
    G, C = slice(1, MAXGROUP), slice(1, MAXCLASS)
    if yrs == epa:
        avg = {}
        for ildv in (5, 6):
            avg[ildv] = [None,
                         weighted_mean(evmt[1:CARGRP, C, yrs, ildv], sales[1:CARGRP, C, yrs, ildv]),
                         weighted_mean(evmt[LTKGRP:MAXGROUP, C, yrs, ildv], sales[LTKGRP:MAXGROUP, C, yrs, ildv])]
        for igp in range(1, MAXGROUP + 1):
            ivtyp = int(s["grpmap"][igp])
            for icl in range(1, MAXCLASS + 1):
                for ildv in (5, 6):
                    if evmt[igp, icl, yrs, ildv] == 0.0:
                        evmt[igp, icl, yrs, ildv] = avg[ildv][ivtyp]
        s.update(igp=MAXGROUP + 1, icl=MAXCLASS + 1, ildv=7, ivtyp=ivtyp)
    if yrs > epa:
        evmt[G, C, yrs, 5:6] = evmt[G, C, yrs - 1, 5:6]

    if XYR <= yrs <= epa:
        flag, pen = s["classflag"], s["mkt_pen"]
        for ildv in range(1, MAXLDV + 1):
            for icl in range(1, MAXCLASS + 1):
                for igp in range(1, MAXGROUP + 1):
                    flag[igp, icl, ildv] = 0
                    if yrs == XYR and s["femmpg"][igp, icl, yrs, ildv] != 0.0:
                        flag[igp, icl, ildv] = 1
                    elif not flag[igp, icl, ildv] and yrs > XYR:
                        if yrs < epa and s["femmpg"][igp, icl, yrs, ildv] != 0.0:
                            flag[igp, icl, ildv] = 1
                            for i in range(BASE, CURRENT + 1):
                                for attr, fem, _ in FEM_ATTRS:
                                    s[attr][igp, icl, i, ildv] = s[fem][igp, icl, yrs, ildv]
                                pen[igp, icl, :, i, ildv] = pen[igp, icl, :, i, GAS]
                            s["i"] = CURRENT + 1
                            for _, fem, epa_k in FEM_ATTRS:
                                s[epa_k][igp, icl, yrs, ildv] = s[fem][igp, icl, yrs, ildv]
                        elif yrs == epa and s["epampg"][igp, icl, yrs, ildv] != 0.0:
                            flag[igp, icl, ildv] = 1
                            for i in range(BASE, CURRENT + 1):
                                for attr, _, epa_k in FEM_ATTRS:
                                    s[attr][igp, icl, i, ildv] = s[epa_k][igp, icl, yrs, ildv]
                                pen[igp, icl, :, i, ildv] = pen[igp, icl, :, i, GAS]
                            s["i"] = CURRENT + 1
                            for _, fem, epa_k in FEM_ATTRS:
                                s[fem][igp, icl, yrs, ildv] = s[epa_k][igp, icl, yrs, ildv]
                    if flag[igp, icl, ildv] and s["femmpg"][igp, icl, yrs, ildv] == 0.0:
                        flag[igp, icl, ildv] = 0
                        for attr, fem, _ in FEM_ATTRS:
                            s[attr][igp, icl, BASE:CURRENT, ildv] = 0.0
                            s[fem][igp, icl, yrs, ildv] = 0.0
        s.update(ildv=MAXLDV + 1, icl=MAXCLASS + 1, igp=MAXGROUP + 1)


def nameplates(s: dict) -> None:
    n, yrs, epa = int(s["n"]), int(s["curcalyr"]), int(s["epalyr"])
    regs = int(s["enforce_my27regs"])
    sens = {k: f32(2.0) for k in range(1, MAXLDV + 1)}
    if epa + 2 <= yrs <= 2032 and regs == 1:
        sens = {k: f32(1.0) for k in sens}
    elif regs != 1:
        # Makers are even less likely to add BEV nameplates when future rules don't require them.
        for k in (4, 7, 15):
            sens[k] = f32(3.0)

    flag, plate, grpflag = s["classflag"], s["nameplate"], s["grpflag"]
    if yrs >= epa:
        if yrs > epa:
            for ildv in range(1, MAXLDV + 1):
                for icl in range(1, MAXCLASS + 1):
                    for igp in range(1, MAXGROUP + 1):
                        s.update(ildv=ildv, icl=icl, igp=igp)
                        if int(grpflag[ildv, icl, igp]) == yrs and ildv > 1:
                            if flag[igp, icl, ildv]:
                                plate[igp, icl, yrs, ildv] = plate[igp, icl, yrs - 1, ildv] + f32(1.0)
                            elif flag[igp, icl, GAS]:
                                flag[igp, icl, ildv] = 1
                                afvadj(s, yrs, igp)
                                plate[igp, icl, yrs, ildv] = f32(1.0)
                            else:
                                lo, hi = (1, CARGRP) if igp <= CARGRP else (LTKGRP, MAXGROUP)
                                if any(flag[lo:hi, icl, GAS]):
                                    # EIA quirk: the count is over car groups even for trucks.
                                    cnt = f32(np.count_nonzero(flag[1:CARGRP, icl, GAS]))
                                    for jgp in range(lo, hi + 1):
                                        if flag[jgp, icl, GAS]:
                                            if flag[jgp, icl, ildv]:
                                                plate[jgp, icl, yrs, ildv] = plate[jgp, icl, yrs, ildv] + f32(1.0) / cnt
                                            else:
                                                flag[jgp, icl, ildv] = 1
                                                grpflag[ildv, icl, jgp] = yrs
                                                afvadj(s, yrs, jgp)
                                                plate[jgp, icl, yrs, ildv] = f32(1.0) / cnt
                        else:
                            if plate[igp, icl, yrs - 1, ildv] > 0.0:
                                per = s["cafesales"][igp, icl, yrs - 1, ildv] / plate[igp, icl, yrs - 1, ildv]
                                if yrs > epa + 2 and per >= (s["sales_per_model"][icl, igp] * sens[ildv]):
                                    plate[igp, icl, yrs, ildv] = plate[igp, icl, yrs - 1, ildv] + f32(1.0)
                                else:
                                    plate[igp, icl, yrs, ildv] = plate[igp, icl, yrs - 1, ildv]
            s.update(ildv=MAXLDV + 1, icl=MAXCLASS + 1, igp=MAXGROUP + 1)

        avail, sales = s["mmavail"], s["ldv_sales"]
        for igp in range(1, MAXGROUP + 1):
            for icl in range(1, MAXCLASS + 1):
                sum_epa = fsum(plate[igp, icl, epa, 1:MAXLDV])
                for ildv in range(1, MAXLDV + 1):
                    for iregn in range(1, MNUMCR - 1):
                        avail[igp, ildv, icl, iregn, yrs] = 0.0
                        if yrs == epa and sales[igp, icl, ildv, iregn, n] > 0.0:
                            if ildv == 1:
                                avail[igp, ildv, icl, iregn, yrs] = f32(1.0)
                            elif sum_epa != 0.0:
                                avail[igp, ildv, icl, iregn, yrs] = plate[igp, icl, epa, ildv] / sum_epa
                        elif yrs > epa:
                            if ildv == 1 and plate[igp, icl, yrs, ildv] > 0.0:
                                avail[igp, ildv, icl, iregn, yrs] = f32(1.0)
                            elif sum_epa > 0.0:
                                avail[igp, ildv, icl, iregn, yrs] = min(plate[igp, icl, yrs, ildv] / sum_epa, f32(1.0))
        s.update(igp=MAXGROUP + 1, icl=MAXCLASS + 1, ildv=MAXLDV + 1, iregn=MNUMCR - 1)

    s["cafepass"][1:MAXGROUP] = 0
    d, inv = s["pmgtr90_d_"], s["pmgtr90_invgr"]
    d[1:MNUMCR, yrs] = (s["pmgtr"][1:MNUMCR, n] * s["cfmgq"][n] / f32(42.0)) * s["mc_jpgdp"][1]
    inv[1:MNUMCR, yrs] = d[1:MNUMCR, yrs - 1] / d[1:MNUMCR, yrs]
    for iregn in range(1, MNUMCR + 1):
        if iregn == 10:
            continue
        p = s["pmgtr"][iregn, n]
        if p != p or p == 0.0:
            raise ValueError(f"TDM TMPGNEW: PMGTR is {p} in region {iregn}")
    s["iregn"] = MNUMCR + 1
    s["fem_pass"] = 1
    s["regcost"][1:MAXGROUP] = 0.0


MAX_CAFETEST_PASS = 30


def _round(s, carry, yrs):
    """One FEM pass: FEMCALC through CAFECALC(0)."""
    if yrs > XYR:
        femcalc.femcalc(s)
    ldv_attrib.cgshare(s)
    ldv_attrib.tattrib(s)
    ldv_choice.talt2(s, carry)
    if yrs > STOCKYR:
        ldv_choice.talt2x(s)
    cafe.cafecalc(s, 0)


def pass1(s: dict, carry: dict) -> None:
    yrs = int(s["curcalyr"])
    if yrs > XYR:
        femcalc.femcalc(s)
    ldv_attrib.cgshare(s)
    ldv_attrib.tattrib(s)
    ldv_choice.talt2(s, carry)
    if yrs > STOCKYR:
        ldv_choice.talt2x(s)
    cafe.cafecalc(s, 0)
    cafe.cafecalc(s, 1)


def passes(s: dict, carry: dict) -> None:
    """FEM passes 2 and 3, then the CAFE test; from after pass 1 to the end of TMPGNEW."""
    n, yrs, epa = int(s["n"]), int(s["curcalyr"]), int(s["epalyr"])
    cp = s["cafepass"]
    regs27 = int(s["enforce_my27regs"]) == 1 and yrs >= 2027
    s["fem_pass"] = 2
    s["npass2"] = 5 if regs27 else 10
    for p in range(1, int(s["npass2"]) + 1):
        s["pass2"] = p
        s["regcost"][1:MAXGROUP] = s["reg_cost"] * (f32(p) / f32(s["npass2"]))
        if yrs > XYR:
            _round(s, carry, yrs)
        if cp[1:MAXGROUP].all():
            cafe.cafecalc(s, 1)
            break
    else:
        s["pass2"] = int(s["npass2"]) + 1

    s["fem_pass"] = 3
    s["npass3"] = 5 if regs27 else 10
    s["regcost"][1:MAXGROUP] = s["reg_cost"]
    for p in range(1, int(s["npass3"]) + 1):
        s["pass3"] = p
        s["gbinc"] = f32(p) / f32(s["npass3"])
        if yrs > XYR:
            _round(s, carry, yrs)
        if cp[1:MAXGROUP].all():
            cafe.cafecalc(s, 1)
            break
    else:
        s["pass3"] = int(s["npass3"]) + 1

    if yrs > epa + 1 and not cp[1:MAXGROUP].all():
        _cafetest(s, n, yrs, epa)


def _cafetest(s, n, yrs, epa):
    cp, mg = s["cafepass"], s["mgghggrp"]
    grp = s["creds_avail_grp"]
    if epa + 2 <= yrs <= epa + 3:
        if yrs == epa + 2:
            s["creds_avail"] = s["credbal_epalyr"] * f32(0.7)
        if yrs == epa + 3:
            s["creds_avail"] = s["credbal_epalyr"] * f32(0.3)
        deficit = f32(0.0)
        for igp in range(1, MAXGROUP + 1):
            if mg[igp, n] < 0.0 and igp != 5:
                deficit = deficit + mg[igp, n]
        for igp in range(1, MAXGROUP + 1):
            if mg[igp, n] < 0.0 and igp != 5:
                grp[igp] = s["creds_avail"] * mg[igp, n] / deficit
    else:
        s["creds_avail"] = f32(0.0)
        grp[1:MAXGROUP] = 0.0

    s["first_time_cafetest"] = 1
    cp[1:MAXGROUP] = 1
    cmg, used, std, newmpg = s["cafempggrp"], s["cafe_used"], s["cafestd"], s["newmpg"]
    cafe_on = int(s["enforce_cafe"]) == 1
    for igp in range(1, MAXGROUP + 1):
        ivtyp = int(s["grpmap"][igp])
        s["ivtyp"] = ivtyp
        if int(s["enforce_epa"]) == 1:
            if fsum(mg[1:MAXGROUP, n]) + s["creds_avail"] < 0.0 or newmpg[3, n] < std[3, n]:
                if mg[igp, n] + grp[igp] < 0.0 or (cmg[igp, n] < used[igp, yrs] and cafe_on):
                    cp[igp] = 0
            elif (newmpg[ivtyp, n] - std[ivtyp, n]) < -2.0 and cmg[igp, n] < used[igp, yrs] and cafe_on:
                cp[igp] = 0
        else:
            if newmpg[3, n] < std[3, n] and cafe_on:
                if cmg[igp, n] < used[igp, yrs]:
                    cp[igp] = 0
            elif (newmpg[ivtyp, n] - std[ivtyp, n]) < -2.0 and cmg[igp, n] < used[igp, yrs]:
                cp[igp] = 0
    s["igp"] = MAXGROUP + 1

    if cp[1:MAXGROUP].all():
        cafe.cafecalc(s, 1)
        return
    for ipass in range(1, MAX_CAFETEST_PASS + 1):
        s["first_time_cafetest"] = 1
        s["maxadj_cafetest"] = f32(ipass) * f32(0.1)
        for igp in range(MAXGROUP, 0, -1):
            s["igp"] = igp
            if not cp[igp]:
                cafe_meet.cafeghg_meet(s)
        s["igp"] = 0
        if cp[1:MAXGROUP].all():
            cafe.cafecalc(s, 1)
            return
        if ipass == MAX_CAFETEST_PASS:
            cafe.cafecalc(s, 1)


def tmpgnew(s: dict, carry: dict) -> None:
    """The whole routine. carry: TALT2's altstat and predstk."""
    setup(s)
    if int(s["yrs"]) >= int(s["first_bat_yr"]) + 1989 - 1:
        lioncostcalc(s)
    nameplates(s)
    pass1(s, carry)
    passes(s, carry)
