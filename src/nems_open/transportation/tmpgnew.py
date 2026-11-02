"""TMPGNEW (tran.f): new light-duty vehicle fuel economy, price and sales.

The routine runs in stages, each its own function here so each can be tested
against the oracle's dump at that point:

  setup        PHEV electric VMT shares, FEM attributes in the EPA calibration years
  (LIONCOSTCALC, in ldv_tech)
  nameplates   new nameplates by fuel type, make/model availability, gasoline price
               terms, then the start of FEM pass 1
  ... FEM passes, CAFE compliance (to come)
"""

import numpy as np

from nems_open.transportation.common import MAXLDV, MNUMCR, f32, fsum
from nems_open.transportation.ldv_tech import afvadj
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
