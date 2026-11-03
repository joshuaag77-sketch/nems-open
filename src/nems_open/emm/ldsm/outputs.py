"""LDSM results for EFP and the reports: DSMEFP and DSMTOR, uldsm.f."""

from nems_open.emm.ldsm.common import COM, IND, RES, TRA, UNCONFA, f32, i
from nems_open.emm.ldsm.forecast import dsmemmv


def dsmefp(s):
    """Each sector's load at the system peak hour, averaged over the peak hours,
    and its own peak; the system load factor. For EFP's cost allocation."""
    rnb, k1, nhour, npeak = i(s, "rnb"), i(s, "k1"), i(s, "nhour"), i(s, "npeakh")
    sl, peakhours = s["sectorload"], s["syspeakhour"]
    for n in range(1, i(s, "numsec") + 1):
        s["secannualpeak"][rnb, n, 1] = sl[int(s["systempeakhour"][k1]), n]
        average = f32(0.0)
        for k in range(1, npeak + 1):
            average = f32(average + sl[int(peakhours[k]), n])
        s["secannpeaavpcp"][rnb, n] = f32(average / f32(npeak))
        peak = f32(0.0)
        for k in range(1, nhour + 1):
            if sl[k, n] > peak:  # REAL*8 load against the REAL*4 running peak
                peak = f32(sl[k, n])
        s["secannualpeak"][rnb, n, 2] = peak
    s["systemlf"][rnb] = s["systemloadfactor"][k1]


def dsmtor(s):
    """Sector sales by EMM region for the reports and EFP (QEL**N, ULEL**).
    Residential and commercial are re-derived from census sales; industrial and
    transport keep DSMHLM's sums."""
    rnb, cur, nc = i(s, "rnb"), i(s, "curiyr"), i(s, "ncensusreg")
    sec, tsl = s["sec"], s["totsecload"]
    load = dsmemmv(s, {k: s["qelrs"][k, cur] for k in range(1, nc + 1)}, rnb, sec[RES])
    tsl[rnb, sec[RES]] = f32(load * UNCONFA)
    load = dsmemmv(s, {k: s["qelcm"][k, cur] for k in range(1, nc + 1)}, rnb, sec[COM])
    tsl[rnb, sec[COM]] = f32(load * UNCONFA)
    s["qelrsn"][rnb, cur] = tsl[rnb, sec[RES]]
    s["qelcmn"][rnb, cur] = tsl[rnb, sec[COM]]
    s["qelinn"][rnb, cur] = tsl[rnb, sec[IND]]
    s["qeltrn"][rnb, cur] = tsl[rnb, sec[TRA]]
    s["qelasn"][rnb, cur] = f32(f32(f32(s["qelrsn"][rnb, cur] + s["qelcmn"][rnb, cur]) + s["qelinn"][rnb, cur])
                                + s["qeltrn"][rnb, cur])
    s["ulelrs"][rnb] = tsl[rnb, sec[RES]]
    s["ulelcm"][rnb] = tsl[rnb, sec[COM]]
    s["ulelin"][rnb] = tsl[rnb, sec[IND]]
    s["uleltr"][rnb] = tsl[rnb, sec[TRA]]
