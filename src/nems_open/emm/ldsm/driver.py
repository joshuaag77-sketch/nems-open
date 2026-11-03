"""ELLDSM, LDSM's yearly entry (uldsm.f), and DSMREP1, its annual report store.

One call per NEMS iteration: commercial adjustment factors, then for every EMM
region the load forecast, hourly load, EFP and report values, EFD load blocks,
and (first iteration, from UPSTYR) ECP load blocks for its whole horizon.
CALLSYSLOAD, the load-shape reader that runs on EMM's first call, is a reader
and is not part of this port yet: the shapes (DistLo_s) come in with the state.
"""

from nems_open.emm.ldsm.common import COM, HSTYEAR, IND, RES, TRA, UNCONFA, f32, i, put
from nems_open.emm.ldsm.ecp import dsmecp1
from nems_open.emm.ldsm.efd import dsmefd
from nems_open.emm.ldsm.forecast import dsmcadj, dsmdlt, dsmemmv, dsmfor
from nems_open.emm.ldsm.outputs import dsmefp, dsmtor
from nems_open.emm.ldsm.system_load import dsmhlm

BASEYR = 1990
CAPS = ["pv", "pt", "so", "wn", "wf", "wl"]


def dsmrep1(s):
    """Annual load results for the report: peak (MW), energy, load factor, when
    the peak falls, and each sector's share."""
    rnb, cur = i(s, "rnb"), i(s, "curiyr")
    peak_hour = int(s["systempeakhour"][cur])
    nodays = s["nodays"]
    h = 0
    k = l = m = 0
    found = False
    for k in range(1, i(s, "nmonth") + 1):
        for l in range(1, int(nodays[k]) + 1):
            for m in range(1, 25):
                h += 1
                if peak_hour == h:
                    found = True
                    break
            if found:
                break
        if found:
            break
    if not found:  # Fortran DO counters end one past their last pass
        k, l, m = i(s, "nmonth") + 1, int(nodays[i(s, "nmonth")]) + 1, 25
    lf, euindex = s["loadforec"], s["euindex"]
    tot = s["totsystemload"][cur]
    for n in range(1, i(s, "numsec") + 1):
        secload = f32(0.0)
        for j in range(int(euindex[n, 1]), int(euindex[n, 2]) + 1):
            secload = f32(secload + lf[j, 1])
        s["rep1sc"][rnb, cur, n] = f32(f32(secload / tot) * f32(100.0))
    s["rep1sp"][rnb, cur] = f32(s["systempeak"][cur] * f32(1000.0))
    s["rep1tl"][rnb, cur] = tot
    s["rep1lf"][rnb, cur] = f32(s["systemloadfactor"][cur] * f32(100.0))
    s["rep1mo"][rnb, cur] = k
    s["rep1jd"][rnb, cur] = s["jdaytp"][l, k]
    s["rep1ho"][rnb, cur] = m
    s["rep1td"][rnb, cur] = f32(f32(s["nerctdloss"][rnb] * s["ulossadj"][cur]) * f32(100.0))


def elldsm(s, mode=1):
    """LDSM for the current year and iteration (mode 1: set up load curves)."""
    cur, itr, fcrl = i(s, "curiyr"), i(s, "curitr"), i(s, "fcrl")
    uhbsyr, nc = i(s, "uhbsyr"), i(s, "ncensusreg")
    put(s, "totdemnerc", 0.0)
    if mode >= 2:
        return
    dsmcadj(s)
    s["ulgrp"].a[...] = 0
    s["ulseg"].a[...] = 0
    nreg = i(s, "nnercreg")
    for rnb in range(1, nreg + 1):
        put(s, "rnb", rnb)
        if cur + uhbsyr <= i(s, "uyr_hist") and cur + uhbsyr >= HSTYEAR:
            qdem = f32(0.0)
            for q, sector in (("qelrs", RES), ("qelcm", COM), ("qelin", IND), ("qeltr", TRA)):
                qdem = f32(qdem + dsmemmv(s, {k: s[q][k, cur] for k in range(1, nc + 1)}, rnb, s["sec"][sector]))
            qdem = f32(f32(qdem * UNCONFA) / f32(1000.0))
            put(s, "histshr", f32(s["helasnr"][rnb, cur] / qdem))
        put(s, "k1", cur)
        put(s, "ubaseyr", cur)
        dsmfor(s)
        dsmdlt(s)
        dsmhlm(s)
        duck, syload = s["duck_system_load"], s["syload"]
        h = 0
        for m in range(1, 13):
            for d in range(1, 4):
                for hh in range(1, 25):
                    h += 1
                    duck[m, d, hh, rnb, cur] = f32(syload[h])
        if itr == 1 and cur == i(s, "uestyr") - uhbsyr:
            for yr in range(cur, i(s, "lastyr") + 1):
                for c in CAPS:
                    s[f"{c}_cap_adj_rest"][rnb, yr] = s[f"{c}_cap_adj"][rnb, yr]
        dsmefp(s)
        dsmtor(s)
        dsmefd(s)
        if fcrl == 1 and s["nodsmrpt"][1]:
            dsmrep1(s)
        if (itr == 1 or mode == -1) and cur >= i(s, "upstyr") - BASEYR + 1:
            dsmecp1(s)
    put(s, "rnb", nreg + 1)
