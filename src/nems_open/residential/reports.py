"""Report routines run once in the final year (resd.f): RESDRP2 and NHTSHR.

RESDRP2 fills the RESDREP report arrays for every year from the equipment-class
stock arrays: equipment counts by end use (RSHTRS, RSCOOLERS, RSWATER, RSCOOK,
RSDRY, RSREF, RSFRZ), shell indices (HSHELL1-3, CSHELL1-3) and stock-weighted
new and existing efficiencies (RSNEF*, RSEEF*, RSNEFDB1, RSEEFDB1).
NHTSHR works out new-home heating system shares, which EIA only prints.
All WRITEs (units 9 and 6, RDM_OUT) are skipped.
"""

import numpy as np

from nems_open.fortran_array import FArray
from nems_open.residential.common import BASEYR, ENDYR, MNUMBLDG, NUM_DIV, RECSYEAR, f32

ONE = f32(1.0)
ZERO = f32(0.0)
K3412 = f32(3.412)  # a REAL*4 literal in the Fortran

HT_COL = {"ELEC_HP": 1, "NG_HP": 2, "GEO_HP": 3, "NG_FA": 4, "DIST_FA": 5}
CL_COL = {"ELEC_HP": 1, "NG_HP": 2, "GEO_HP": 3, "CENT_AIR": 4, "ROOM_AIR": 5}
HW_COL = {"ELEC_WH": 1, "NG_WH": 2, "DIST_WH": 3, "LPG_WH": 4}

# Order in which EIA adds the seven EQC arrays in each denominator.
ORD_HT = ("ese", "rp90rp", "rp90", "rep", "add", "sur", "sr90")
ORD_CL = ("ese", "rp90", "rep", "add", "sr90", "rp90rp", "sur")
ORD_WH = ("ese", "rp90", "sr90", "add", "rep", "rp90rp", "sur")
ORD_RF = ("rp90rp", "ese", "rp90", "sr90", "add", "rep", "sur")


def _ltr(first, *rest):
    """Left-to-right sum in single precision, the way Fortran evaluates A+B+C."""
    acc = first
    for x in rest:
        acc = acc + x
    return acc


def _name(a, i) -> str:
    """RTCLNAME(i) as a blank-padded Fortran CHARACTER compares, i.e. trimmed."""
    return bytes(a[i]).decode("latin-1").rstrip()


def nhtshr(s: dict) -> None:
    """NHTSHR: share of new-home housing starts by heating equipment class,
    NWEQHTSH(year, class). EIA only prints it, so nothing shared changes; the
    result is left in the state as nweqhtsh. Writes are skipped."""
    rtcleupt, hsysshr, hseadd = s["rtcleupt"], s["hsysshr"], s["hseadd"]
    last = int(s["lastyr"])
    eu = 1
    numeqc = int(rtcleupt[eu + 1] - rtcleupt[eu])
    y_end = last + BASEYR - 1
    heatcal = FArray.zeros([(RECSYEAR, ENDYR), (1, 15)])
    totalsum = FArray.zeros([(RECSYEAR, ENDYR)])
    nweqhtsh = FArray.zeros([(RECSYEAR, ENDYR), (1, 15)])

    for y in range(RECSYEAR + 1, y_end + 1):
        for e in range(1, numeqc + 1):
            heatcal[y, e] = ZERO
            for b in range(1, MNUMBLDG + 1):
                for d in range(1, NUM_DIV + 1):
                    heatcal[y, e] = heatcal[y, e] + (hsysshr[y, e, b, d] * hseadd[y, b, d])
    for y in range(RECSYEAR + 1, y_end + 1):
        totalsum[y] = ZERO
        for b in range(1, MNUMBLDG + 1):
            for d in range(1, NUM_DIV + 1):
                totalsum[y] = totalsum[y] + hseadd[y, b, d]
    for y in range(RECSYEAR + 1, y_end + 1):
        for e in range(1, numeqc + 1):
            if totalsum[y] > 0.0:
                nweqhtsh[y, e] = heatcal[y, e] / totalsum[y]
            else:
                nweqhtsh[y, e] = ZERO
    s["nweqhtsh"] = nweqhtsh


def resdrp2(s: dict) -> None:
    """RESDRP2: REPORTER table 30 arrays (equipment, shells, efficiencies) for
    all years. Writes to RDM_OUT are skipped.

    NUME/DEN/NUME1/DEN1 are locals that EIA reuses across end uses without
    resetting, and some loops read them at class 1 or at an index the current end
    use never wrote. They are one persistent set of arrays (zero at entry) so those
    stale reads happen as in the Fortran."""
    rtcleupt = s["rtcleupt"]
    rtcleqcl, rtclname, rtfuel, rtbaseff = s["rtcleqcl"], s["rtclname"], s["rtfuel"], s["rtbaseff"]
    ESE, RP90, SR90, ADD = s["eqcese"], s["eqcrp90"], s["eqcsr90"], s["eqcadd"]
    REP, SUR, RP90RP = s["eqcrep"], s["eqcsur"], s["eqcrp90rp"]
    ARR = {"ese": ESE, "rp90": RP90, "sr90": SR90, "add": ADD, "rep": REP, "sur": SUR, "rp90rp": RP90RP}
    WN, WR, WA, WHV = s["wteqceffn"], s["wteqceffr"], s["wteqceffa"], s["wteqceffhv"]
    last = int(s["lastyr"])
    y_end = last + BASEYR - 1
    y0 = RECSYEAR - BASEYR + 1  # report-array index of the RECS year
    nd, nb = NUM_DIV, MNUMBLDG

    RSHTRS, RSCOOLERS, RSWATER = s["rshtrs"], s["rscoolers"], s["rswater"]
    RSCOOK, RSDRY, RSREF, RSFRZ = s["rscook"], s["rsdry"], s["rsref"], s["rsfrz"]
    RSNEFHT, RSNEFCL, RSNEFHW, RSNEFRF, RSNEFFZ = (s["rsnefht"], s["rsnefcl"], s["rsnefhw"],
                                                   s["rsnefrf"], s["rsneffz"])
    RSEEFHT, RSEEFCL, RSEEFHW, RSEEFRF, RSEEFFZ = (s["rseefht"], s["rseefcl"], s["rseefhw"],
                                                   s["rseefrf"], s["rseeffz"])
    RSNEFDB1, RSEEFDB1 = s["rsnefdb1"], s["rseefdb1"]

    def q(y, r, b, d):
        """ese, rp90, sr90, add, rep, sur, rp90rp at (Y, RECCL, B, D)."""
        return (ESE[y, r, b, d], RP90[y, r, b, d], SR90[y, r, b, d], ADD[y, r, b, d],
                REP[y, r, b, d], SUR[y, r, b, d], RP90RP[y, r, b, d])

    def ex_den(Y, RECCL, B, D, order):
        return _ltr(*[ARR[k][Y, RECCL, B, D] for k in order])

    base = lambda Y, R: rtbaseff[Y, R]  # noqa: E731
    yrs = range(RECSYEAR, y_end + 1)
    yrs1 = range(RECSYEAR + 1, y_end + 1)
    NUME = FArray.zeros([(RECSYEAR, ENDYR + 1), (1, 15)])
    DEN = FArray.zeros([(RECSYEAR, ENDYR + 1), (1, 15)])
    NUME1 = FArray.zeros([(RECSYEAR, ENDYR + 1), (1, 15), (1, nb), (1, nd)])
    DEN1 = FArray.zeros([(RECSYEAR, ENDYR + 1), (1, 15), (1, nb), (1, nd)])

    def reccls(eu):
        return range(int(rtcleupt[eu]) + 1, int(rtcleupt[eu + 1]) + 1)

    with np.errstate(all="ignore"):  # EIA divides by zero weights in places and keeps the inf
        # ---------------- space heating systems
        eu = 1
        for y in range(y0, last + 1):
            for c in range(1, 9):
                RSHTRS[y, c] = ZERO
        for Y in yrs:
            Y1 = Y - BASEYR + 1
            for RECCL in reccls(eu):
                EQC = int(rtcleqcl[RECCL])
                if EQC == 1:
                    E2 = 2
                elif EQC == 2:
                    E2 = 1
                elif EQC <= 4:
                    E2 = 4
                elif EQC == 5:
                    E2 = 6
                elif EQC <= 7:
                    E2 = 5
                elif EQC == 8:
                    E2 = 7
                elif EQC == 9:
                    E2 = 8
                elif EQC == 10:
                    E2 = 3
                for B in range(1, nb + 1):
                    for D in range(1, nd + 1):
                        ese, rp90, sr90, add, rep, sur, rp90rp = q(Y, RECCL, B, D)
                        if Y == RECSYEAR:
                            RSHTRS[Y1, E2] = RSHTRS[Y1, E2] + ese
                        else:
                            RSHTRS[Y1, E2] = _ltr(RSHTRS[Y1, E2], ese, rp90, sr90, add, rep, sur, rp90rp)

        HSHINDE = FArray.zeros([(RECSYEAR, ENDYR), (1, 5), (1, nd), (1, nb)])
        HSHINDA = FArray.zeros([(RECSYEAR, ENDYR), (1, 5), (1, nd), (1, nb)])
        HSHINDN = FArray.zeros([(RECSYEAR, ENDYR), (1, 5), (1, nd), (1, nb)])
        for Y in yrs:
            for D in range(1, nd + 1):
                for RECCL in reccls(eu):
                    F = int(rtfuel[RECCL])
                    for B in range(1, nb + 1):
                        ese, rp90, sr90, add, rep, sur, rp90rp = q(Y, RECCL, B, D)
                        if Y == RECSYEAR:
                            HSHINDE[Y, F, D, B] = HSHINDE[Y, F, D, B] + ese
                            HSHINDN[Y, F, D, B] = ZERO
                            HSHINDA[Y, F, D, B] = ZERO
                        else:
                            HSHINDE[Y, F, D, B] = _ltr(HSHINDE[Y, F, D, B], ese, rp90, sr90, rp90rp)
                            HSHINDN[Y, F, D, B] = HSHINDN[Y, F, D, B] + add
                            HSHINDA[Y, F, D, B] = _ltr(HSHINDA[Y, F, D, B], rep, sur)

        EH, NHS, AH = s["ehshell"], s["nhshell"], s["ahshell"]
        HSHELLE = FArray.zeros([(RECSYEAR, ENDYR)])
        HSHELLN = FArray.zeros([(RECSYEAR, ENDYR)])
        HSHELLA = FArray.zeros([(RECSYEAR, ENDYR)])
        for Y in yrs:
            HSHELLE[Y] = ZERO
            HSHELLN[Y] = ZERO
            HSHELLA[Y] = ZERO
            for F in range(1, 6):
                for D in range(1, nd + 1):
                    for B in range(1, nb + 1):
                        if Y == RECSYEAR:
                            t = HSHINDE[Y, F, D, B] * EH[Y, F, D, B]
                            HSHELLE[Y] = HSHELLE[Y] + t
                            HSHELLN[Y] = HSHELLN[Y] + t
                            HSHELLA[Y] = HSHELLA[Y] + t
                        else:
                            HSHELLE[Y] = HSHELLE[Y] + (HSHINDE[Y, F, D, B] * EH[Y, F, D, B])
                            HSHELLN[Y] = HSHELLN[Y] + (HSHINDN[Y, F, D, B] * NHS[Y, F, D, B])
                            HSHELLA[Y] = HSHELLA[Y] + (HSHINDA[Y, F, D, B] * AH[Y, F, D, B]
                                                       + HSHINDN[Y, F, D, B] * NHS[Y, F, D, B]
                                                       + HSHINDE[Y, F, D, B] * EH[Y, F, D, B])
        HEATOTE = FArray.zeros([(RECSYEAR, ENDYR)])
        HEATOTN = FArray.zeros([(RECSYEAR, ENDYR)])
        HEATOTA = FArray.zeros([(RECSYEAR, ENDYR)])
        for Y in yrs:
            HEATOTE[Y] = ZERO
            HEATOTN[Y] = ZERO
            HEATOTA[Y] = ZERO
            for F in range(1, 6):
                for D in range(1, nd + 1):
                    for B in range(1, nb + 1):
                        HEATOTE[Y] = HEATOTE[Y] + HSHINDE[Y, F, D, B]
                        HEATOTN[Y] = HEATOTN[Y] + HSHINDN[Y, F, D, B]
                        HEATOTA[Y] = _ltr(HEATOTA[Y], HSHINDN[Y, F, D, B], HSHINDE[Y, F, D, B],
                                          HSHINDA[Y, F, D, B])
        for Y in yrs:
            Y1 = Y - BASEYR + 1
            s["hshell1"][Y1] = HSHELLE[Y] / HEATOTE[Y] if HEATOTE[Y] > 0.0 else ONE
            s["hshell2"][Y1] = HSHELLN[Y] / HEATOTN[Y] if HEATOTN[Y] > 0.0 else ONE
            s["hshell3"][Y1] = HSHELLA[Y] / HEATOTA[Y] if HEATOTA[Y] > 0.0 else ONE

        # ---------------- space cooling systems
        eu = 2
        for Y in yrs:
            Y1 = Y - BASEYR + 1
            for RECCL in reccls(eu):
                E = int(rtcleqcl[RECCL])
                E2 = {1: 5, 2: 4, 3: 1, 4: 3, 5: 2}[E]
                RSCOOLERS[Y1, E2] = ZERO
                for B in range(1, nb + 1):
                    for D in range(1, nd + 1):
                        X = ONE  # RACUnits is only in a commented-out line
                        ese, rp90, sr90, add, rep, sur, rp90rp = q(Y, RECCL, B, D)
                        if Y == RECSYEAR:
                            RSCOOLERS[Y1, E2] = RSCOOLERS[Y1, E2] + ese * X
                        else:
                            RSCOOLERS[Y1, E2] = RSCOOLERS[Y1, E2] + _ltr(ese, rp90, sr90, rp90rp,
                                                                          add, rep, sur) * X

        CSHINDE = FArray.zeros([(RECSYEAR, ENDYR), (1, nd), (1, nb)])
        CSHINDA = FArray.zeros([(RECSYEAR, ENDYR), (1, nd), (1, nb)])
        CSHINDN = FArray.zeros([(RECSYEAR, ENDYR), (1, nd), (1, nb)])
        for Y in yrs:
            for D in range(1, nd + 1):
                for RECCL in reccls(eu):
                    for B in range(1, nb + 1):
                        ese, rp90, sr90, add, rep, sur, rp90rp = q(Y, RECCL, B, D)
                        if Y == RECSYEAR:
                            CSHINDE[Y, D, B] = CSHINDE[Y, D, B] + ese
                        else:
                            CSHINDE[Y, D, B] = _ltr(CSHINDE[Y, D, B], ese, rp90, sr90, rp90rp)
                            CSHINDN[Y, D, B] = CSHINDN[Y, D, B] + add
                            CSHINDA[Y, D, B] = _ltr(CSHINDA[Y, D, B], rep, sur)

        EC, NC, AC = s["ecshell"], s["ncshell"], s["acshell"]
        CSHELLE = FArray.zeros([(RECSYEAR, ENDYR)])
        CSHELLN = FArray.zeros([(RECSYEAR, ENDYR)])
        CSHELLA = FArray.zeros([(RECSYEAR, ENDYR)])
        for Y in yrs:
            CSHELLE[Y] = ZERO
            CSHELLN[Y] = ZERO
            CSHELLA[Y] = ZERO
            for D in range(1, nd + 1):
                for B in range(1, nb + 1):
                    if Y == RECSYEAR:
                        t = CSHINDE[Y, D, B] * EC[Y, D, B]
                        CSHELLE[Y] = CSHELLE[Y] + t
                        CSHELLN[Y] = CSHELLN[Y] + t
                        CSHELLA[Y] = CSHELLA[Y] + t
                    else:
                        CSHELLE[Y] = CSHELLE[Y] + (CSHINDE[Y, D, B] * EC[Y, D, B])
                        CSHELLN[Y] = CSHELLN[Y] + (CSHINDN[Y, D, B] * NC[Y, D, B])
                        CSHELLA[Y] = CSHELLA[Y] + (CSHINDE[Y, D, B] * EC[Y, D, B]
                                                   + CSHINDN[Y, D, B] * NC[Y, D, B]
                                                   + CSHINDA[Y, D, B] * AC[Y, D, B])
        COLTOTE = FArray.zeros([(RECSYEAR, ENDYR)])
        COLTOTN = FArray.zeros([(RECSYEAR, ENDYR)])
        COLTOTA = FArray.zeros([(RECSYEAR, ENDYR)])
        for Y in yrs:
            COLTOTE[Y] = ZERO
            COLTOTN[Y] = ZERO
            COLTOTA[Y] = ZERO
            for D in range(1, nd + 1):
                for B in range(1, nb + 1):
                    COLTOTE[Y] = COLTOTE[Y] + CSHINDE[Y, D, B]
                    COLTOTN[Y] = COLTOTN[Y] + CSHINDN[Y, D, B]
                    COLTOTA[Y] = _ltr(COLTOTA[Y], CSHINDE[Y, D, B], CSHINDN[Y, D, B], CSHINDA[Y, D, B])
        for Y in yrs:
            Y1 = Y - BASEYR + 1
            s["cshell1"][Y1] = CSHELLE[Y] / COLTOTE[Y] if COLTOTE[Y] > 0.0 else ONE
            s["cshell2"][Y1] = CSHELLN[Y] / COLTOTN[Y] if COLTOTN[Y] > 0.0 else ONE
            s["cshell3"][Y1] = CSHELLA[Y] / COLTOTA[Y] if COLTOTA[Y] > 0.0 else ONE

        # ---------------- water heating
        eu = 5
        for Y in yrs:
            Y1 = Y - BASEYR + 1
            for E in range(1, 6):  # nWatHtClasses
                RSWATER[Y1, E] = ZERO
        for Y in yrs:
            Y1 = Y - BASEYR + 1
            for D in range(1, nd + 1):
                for B in range(1, nb + 1):
                    for RECCL in reccls(eu):
                        EQC = int(rtcleqcl[RECCL])
                        ese, rp90, sr90, add, rep, sur, rp90rp = q(Y, RECCL, B, D)
                        if Y == RECSYEAR:
                            RSWATER[Y1, EQC] = RSWATER[Y1, EQC] + ese
                        else:
                            RSWATER[Y1, EQC] = _ltr(RSWATER[Y1, EQC], ese, rp90, add, sr90, rp90rp, rep, sur)

        # ---------------- cooking, then clothes drying (same sum order as water heating)
        for eu, out in ((6, RSCOOK), (7, RSDRY)):
            for Y in yrs:
                Y1 = Y - BASEYR + 1
                for RECCL in reccls(eu):
                    EQC = int(rtcleqcl[RECCL])
                    out[Y1, EQC] = ZERO
                    for B in range(1, nb + 1):
                        for D in range(1, nd + 1):
                            ese, rp90, sr90, add, rep, sur, rp90rp = q(Y, RECCL, B, D)
                            if Y == RECSYEAR:
                                out[Y1, EQC] = out[Y1, EQC] + ese
                            else:
                                out[Y1, EQC] = _ltr(out[Y1, EQC], ese, rp90, add, sr90, rp90rp, rep, sur)

        # ---------------- food refrigeration, standalone freezers
        for eu, out, order in ((8, RSREF, ("ese", "rp90", "sr90", "add", "rp90rp", "rep", "sur")),
                               (9, RSFRZ, ("ese", "rp90", "sr90", "add", "rep", "sur", "rp90rp"))):
            for Y in yrs:
                Y1 = Y - BASEYR + 1
                for RECCL in reccls(eu):
                    out[Y1] = ZERO
                    for B in range(1, nb + 1):
                        for D in range(1, nd + 1):
                            if Y == RECSYEAR:
                                out[Y1] = out[Y1] + ESE[Y, RECCL, B, D]
                            else:
                                out[Y1] = _ltr(out[Y1], *[ARR[k][Y, RECCL, B, D] for k in order])

        # ================= weighted NEW equipment efficiencies
        def nsum(Y, RECCL, B, D):
            ese, rp90, sr90, add, rep, sur, rp90rp = q(Y, RECCL, B, D)
            return add, rep, rp90, rp90rp

        def new_final_db(eu, col1=False):
            """Closing RSNEFDB1 loop of the one-array blocks. col1 reads class 1
            instead of EQC (refrigeration and freezers)."""
            for D in range(1, nd + 1):
                for B in range(1, nb + 1):
                    for Y in yrs1:
                        Y1 = Y - BASEYR + 1
                        for RECCL in reccls(eu):
                            EQC = 1 if col1 else int(rtcleqcl[RECCL])
                            if DEN1[Y, EQC, B, D] > 0.0:
                                RSNEFDB1[Y1, RECCL, B, D] = NUME1[Y, EQC, B, D] / DEN1[Y, EQC, B, D]

        # space heating
        eu = 1
        for Y in yrs1:
            for RECCL in reccls(eu):
                EQC = int(rtcleqcl[RECCL])
                NUME[Y, EQC] = ZERO
                DEN[Y, EQC] = ZERO
                for D in range(1, nd + 1):
                    for B in range(1, nb + 1):
                        if WN[Y, RECCL, B, D] > 0.0 and WR[Y, RECCL, B, D] > 0.0 and WHV[Y, RECCL, B, D] > 0.0:
                            add, rep, rp90, rp90rp = nsum(Y, RECCL, B, D)
                            iHV = ONE / WHV[Y, RECCL, B, D]
                            iN = ONE / WN[Y, RECCL, B, D]
                            iR = ONE / WR[Y, RECCL, B, D]
                            NUME[Y, EQC] = NUME[Y, EQC] + add * iHV + (rp90rp + rep) * iN + rp90 * iR
                            NUME1[Y, EQC, B, D] = add * iHV + (rp90rp + rep) * iN + rp90 * iR
                            DEN[Y, EQC] = _ltr(DEN[Y, EQC], add, rep, rp90, rp90rp)
                            DEN1[Y, EQC, B, D] = _ltr(add, rep, rp90, rp90rp)
        for Y in yrs1:
            Y1 = Y - BASEYR + 1
            for RECCL in reccls(eu):
                EQC = int(rtcleqcl[RECCL])
                col = HT_COL.get(_name(rtclname, RECCL))
                if col is not None and DEN[Y, EQC] > 0.0:
                    RSNEFHT[Y1, col] = NUME[Y, EQC] / DEN[Y, EQC]
        for D in range(1, nd + 1):
            for B in range(1, nb + 1):
                for Y in yrs1:
                    Y1 = Y - BASEYR + 1
                    for RECCL in reccls(eu):
                        EQC = int(rtcleqcl[RECCL])
                        if DEN1[Y, EQC, B, D] > 0.0:
                            if EQC != 2:
                                RSNEFDB1[Y1, RECCL, B, D] = NUME1[Y, EQC, B, D] / DEN1[Y, EQC, B, D]
                            else:
                                RSNEFDB1[Y1, RECCL, B, D] = NUME1[Y, EQC, B, D] / DEN1[Y, EQC, B, D] * K3412

        # space cooling
        eu = 2
        for Y in yrs1:
            for RECCL in reccls(eu):
                E = int(rtcleqcl[RECCL])
                NUME[Y, E] = ZERO
                DEN[Y, E] = ZERO
                for D in range(1, nd + 1):
                    for B in range(1, nb + 1):
                        add, rep, rp90, rp90rp = nsum(Y, RECCL, B, D)
                        if E != 1:
                            if WN[Y, RECCL, B, D] > 0.0 and WR[Y, RECCL, B, D] > 0.0 and WHV[Y, RECCL, B, D] > 0.0:
                                iHV = ONE / WHV[Y, RECCL, B, D]
                                iN = ONE / WN[Y, RECCL, B, D]
                                iR = ONE / WR[Y, RECCL, B, D]
                                NUME[Y, E] = NUME[Y, E] + add * iHV + (rp90rp + rep) * iN + rp90 * iR
                                DEN[Y, E] = _ltr(DEN[Y, E], add, rep, rp90, rp90rp)
                                NUME1[Y, E, B, D] = add * iHV + (rp90rp + rep) * iN + rp90 * iR
                                DEN1[Y, E, B, D] = _ltr(add, rep, rp90, rp90rp)
                        else:
                            if WN[Y, RECCL, B, D] > 0.0 and WR[Y, RECCL, B, D] > 0.0:
                                iN = ONE / WN[Y, RECCL, B, D]
                                iR = ONE / WR[Y, RECCL, B, D]
                                NUME[Y, E] = NUME[Y, E] + add * iN + (rp90rp + rep) * iN + rp90 * iR
                                DEN[Y, E] = _ltr(DEN[Y, E], add, rep, rp90, rp90rp)
                                # EIA's NUME1 here has a doubled "+" (unary plus) and groups ADD with the rest
                                NUME1[Y, E, B, D] = (add + rp90rp + rep) * iN + rp90 * iR
                                DEN1[Y, E, B, D] = _ltr(add, rep, rp90, rp90rp)
        for Y in yrs1:
            Y1 = Y - BASEYR + 1
            for RECCL in reccls(eu):
                EQC = int(rtcleqcl[RECCL])
                nm = _name(rtclname, RECCL)
                col = CL_COL.get(nm)
                if col is not None and DEN[Y, EQC] > 0.0:
                    if nm == "GEO_HP":
                        RSNEFCL[Y1, col] = (NUME[Y, EQC] / DEN[Y, EQC]) / K3412
                    else:
                        RSNEFCL[Y1, col] = NUME[Y, EQC] / DEN[Y, EQC]
        for D in range(1, nd + 1):
            for B in range(1, nb + 1):
                for Y in yrs1:
                    Y1 = Y - BASEYR + 1
                    for RECCL in reccls(eu):
                        EQC = int(rtcleqcl[RECCL])
                        if DEN1[Y, EQC, B, D] > 0.0:
                            if EQC <= 3:
                                RSNEFDB1[Y1, RECCL, B, D] = (NUME1[Y, EQC, B, D] / DEN1[Y, EQC, B, D]) * K3412
                            else:
                                RSNEFDB1[Y1, RECCL, B, D] = NUME1[Y, EQC, B, D] / DEN1[Y, EQC, B, D]

        # clothes washers: plain weights, no guard
        eu = 3
        for Y in yrs1:
            for RECCL in reccls(eu):
                EQC = int(rtcleqcl[RECCL])
                for D in range(1, nd + 1):
                    for B in range(1, nb + 1):
                        add, rep, rp90, rp90rp = nsum(Y, RECCL, B, D)
                        NUME1[Y, EQC, B, D] = (add + rp90rp + rep) * WN[Y, RECCL, B, D] + rp90 * WR[Y, RECCL, B, D]
                        DEN1[Y, EQC, B, D] = _ltr(add, rep, rp90, rp90rp)
        new_final_db(eu)

        # dishwashers (guarded, inverse weights)
        eu = 4
        for Y in yrs1:
            for RECCL in reccls(eu):
                EQC = int(rtcleqcl[RECCL])
                for D in range(1, nd + 1):
                    for B in range(1, nb + 1):
                        if WN[Y, RECCL, B, D] > 0.0 and WR[Y, RECCL, B, D] > 0.0:
                            add, rep, rp90, rp90rp = nsum(Y, RECCL, B, D)
                            NUME1[Y, EQC, B, D] = ((add + rp90rp + rep) * (ONE / WN[Y, RECCL, B, D])
                                                   + rp90 * (ONE / WR[Y, RECCL, B, D]))
                            DEN1[Y, EQC, B, D] = _ltr(add, rep, rp90, rp90rp)
        new_final_db(eu)

        # water heaters
        eu = 5
        for Y in yrs1:
            for RECCL in reccls(eu):
                EQC = int(rtcleqcl[RECCL])
                NUME[Y, EQC] = ZERO
                DEN[Y, EQC] = ZERO
                for D in range(1, nd + 1):
                    for B in range(1, nb + 1):
                        if WN[Y, RECCL, B, D] > 0.0 and WR[Y, RECCL, B, D] > 0.0:
                            add, rep, rp90, rp90rp = nsum(Y, RECCL, B, D)
                            t = ((add + rp90rp + rep) * (ONE / WN[Y, RECCL, B, D])
                                 + rp90 * (ONE / WR[Y, RECCL, B, D]))
                            NUME[Y, EQC] = NUME[Y, EQC] + t
                            DEN[Y, EQC] = _ltr(DEN[Y, EQC], add, rep, rp90, rp90rp)
                            NUME1[Y, EQC, B, D] = t
                            DEN1[Y, EQC, B, D] = _ltr(add, rep, rp90, rp90rp)
        for Y in yrs1:
            Y1 = Y - BASEYR + 1
            for RECCL in reccls(eu):
                EQC = int(rtcleqcl[RECCL])
                col = HW_COL.get(_name(rtclname, RECCL))
                if col is not None and DEN[Y, EQC] > 0.0:
                    RSNEFHW[Y1, col] = NUME[Y, EQC] / DEN[Y, EQC]
        new_final_db(eu)

        # cooking (guarded, plain weights)
        eu = 6
        for Y in yrs1:
            for RECCL in reccls(eu):
                EQC = int(rtcleqcl[RECCL])
                for D in range(1, nd + 1):
                    for B in range(1, nb + 1):
                        if WN[Y, RECCL, B, D] > 0.0 and WR[Y, RECCL, B, D] > 0.0:
                            add, rep, rp90, rp90rp = nsum(Y, RECCL, B, D)
                            NUME1[Y, EQC, B, D] = ((add + rp90rp + rep) * WN[Y, RECCL, B, D]
                                                   + rp90 * WR[Y, RECCL, B, D])
                            DEN1[Y, EQC, B, D] = _ltr(add, rep, rp90, rp90rp)
        new_final_db(eu)

        # clothes dryers (guarded, inverse weights)
        eu = 7
        for Y in yrs1:
            for RECCL in reccls(eu):
                EQC = int(rtcleqcl[RECCL])
                for D in range(1, nd + 1):
                    for B in range(1, nb + 1):
                        if WN[Y, RECCL, B, D] > 0.0 and WR[Y, RECCL, B, D] > 0.0:
                            add, rep, rp90, rp90rp = nsum(Y, RECCL, B, D)
                            NUME1[Y, EQC, B, D] = ((add + rp90rp + rep) * (ONE / WN[Y, RECCL, B, D])
                                                   + rp90 * (ONE / WR[Y, RECCL, B, D]))
                            DEN1[Y, EQC, B, D] = _ltr(add, rep, rp90, rp90rp)
        new_final_db(eu)

        # refrigerators and freezers: no guard, plain weights, class 1 read back
        for eu, out in ((8, RSNEFRF), (9, RSNEFFZ)):
            for Y in yrs1:
                for RECCL in reccls(eu):
                    EQC = int(rtcleqcl[RECCL])
                    NUME[Y, EQC] = ZERO
                    DEN[Y, EQC] = ZERO
                    for D in range(1, nd + 1):
                        for B in range(1, nb + 1):
                            add, rep, rp90, rp90rp = nsum(Y, RECCL, B, D)
                            t = (add + rp90rp + rep) * WN[Y, RECCL, B, D] + rp90 * WR[Y, RECCL, B, D]
                            NUME[Y, EQC] = NUME[Y, EQC] + t
                            DEN[Y, EQC] = _ltr(DEN[Y, EQC], add, rep, rp90, rp90rp)
                            NUME1[Y, EQC, B, D] = t
                            DEN1[Y, EQC, B, D] = _ltr(add, rep, rp90, rp90rp)
            for Y in yrs1:
                if DEN[Y, 1] > 0.0:
                    out[Y - BASEYR + 1] = NUME[Y, 1] / DEN[Y, 1]
            new_final_db(eu, col1=True)

        # ================= weighted EXISTING equipment efficiencies
        def set_base_2020(eu):
            for D in range(1, nd + 1):
                for B in range(1, nb + 1):
                    for RECCL in reccls(eu):
                        RSEEFDB1[y0, RECCL, B, D] = rtbaseff[RECSYEAR, RECCL]

        def ex_final_db(eu, col1=False):
            """Closing RSEEFDB1 loop of the blocks that fall back to the RECS-year value."""
            for D in range(1, nd + 1):
                for B in range(1, nb + 1):
                    for Y in yrs1:
                        Y1 = Y - BASEYR + 1
                        for RECCL in reccls(eu):
                            EQC = 1 if col1 else int(rtcleqcl[RECCL])
                            if DEN1[Y, EQC, B, D] > 0.0:
                                RSEEFDB1[Y1, RECCL, B, D] = NUME1[Y, EQC, B, D] / DEN1[Y, EQC, B, D]
                            else:
                                RSEEFDB1[Y1, RECCL, B, D] = RSEEFDB1[y0, RECCL, B, D]

        def ex_nume1(Y, RECCL, B, D, inverse):
            ese, rp90, sr90, add, rep, sur, rp90rp = q(Y, RECCL, B, D)
            if inverse:
                wn, wr, wa = ONE / WN[Y, RECCL, B, D], ONE / WR[Y, RECCL, B, D], ONE / WA[Y, RECCL, B, D]
            else:
                wn, wr, wa = WN[Y, RECCL, B, D], WR[Y, RECCL, B, D], WA[Y, RECCL, B, D]
            return ese * base(Y, RECCL) + (add + rp90rp + rep) * wn + rp90 * wr + (sr90 + sur) * wa

        def set_class_base_2020(eu, table, col_out):
            """RECS-year efficiencies by class name, plus RSEEFDB1 for every class."""
            for RECCL in reccls(eu):
                col = table.get(_name(rtclname, RECCL))
                if col is not None:
                    col_out[y0, col] = rtbaseff[RECSYEAR, RECCL]
                for D in range(1, nd + 1):
                    for B in range(1, nb + 1):
                        RSEEFDB1[y0, RECCL, B, D] = rtbaseff[RECSYEAR, RECCL]

        def class_eff(eu, table, col_out):
            for Y in yrs1:
                Y1 = Y - BASEYR + 1
                for RECCL in reccls(eu):
                    EQC = int(rtcleqcl[RECCL])
                    col = table.get(_name(rtclname, RECCL))
                    if col is not None:
                        if DEN[Y, EQC] > 0.0:
                            col_out[Y1, col] = NUME[Y, EQC] / DEN[Y, EQC]
                        else:
                            col_out[Y1, col] = col_out[y0, col]

        # space heating
        eu = 1
        for Y in yrs1:
            for RECCL in reccls(eu):
                EQC = int(rtcleqcl[RECCL])
                NUME[Y, EQC] = ZERO
                DEN[Y, EQC] = ZERO
                for D in range(1, nd + 1):
                    for B in range(1, nb + 1):
                        ese, rp90, sr90, add, rep, sur, rp90rp = q(Y, RECCL, B, D)
                        t = (ese * base(Y, RECCL)
                             + (rp90rp + rep) * (ONE / WN[Y, RECCL, B, D])
                             + add * (ONE / WHV[Y, RECCL, B, D])
                             + rp90 * (ONE / WR[Y, RECCL, B, D])
                             + (sr90 + sur) * (ONE / WA[Y, RECCL, B, D]))
                        NUME[Y, EQC] = NUME[Y, EQC] + t
                        DEN[Y, EQC] = DEN[Y, EQC] + ex_den(Y, RECCL, B, D, ORD_HT)
                        NUME1[Y, EQC, B, D] = t
                        DEN1[Y, EQC, B, D] = ex_den(Y, RECCL, B, D, ORD_HT)
        set_class_base_2020(eu, HT_COL, RSEEFHT)
        class_eff(eu, HT_COL, RSEEFHT)
        for D in range(1, nd + 1):
            for B in range(1, nb + 1):
                for Y in yrs1:
                    Y1 = Y - BASEYR + 1
                    for RECCL in reccls(eu):
                        EQC = int(rtcleqcl[RECCL])
                        if DEN1[Y, EQC, B, D] > 0.0:
                            if EQC != 2:
                                RSEEFDB1[Y1, RECCL, B, D] = NUME1[Y, EQC, B, D] / DEN1[Y, EQC, B, D]
                            else:
                                # COP to HSPF for the electric heat pump
                                RSEEFDB1[Y1, RECCL, B, D] = NUME1[Y, EQC, B, D] / DEN1[Y, EQC, B, D] * K3412
                        else:
                            if EQC != 2:
                                RSEEFDB1[Y1, RECCL, B, D] = RSEEFDB1[y0, RECCL, B, D]
                            else:
                                RSEEFDB1[Y1, RECCL, B, D] = RSEEFDB1[y0, RECCL, B, D] * K3412

        # space cooling
        eu = 2
        for Y in yrs1:
            for RECCL in reccls(eu):
                E = int(rtcleqcl[RECCL])
                NUME[Y, E] = ZERO
                DEN[Y, E] = ZERO
                for D in range(1, nd + 1):
                    for B in range(1, nb + 1):
                        ese, rp90, sr90, add, rep, sur, rp90rp = q(Y, RECCL, B, D)
                        iN = ONE / WN[Y, RECCL, B, D]
                        iR = ONE / WR[Y, RECCL, B, D]
                        iA = ONE / WA[Y, RECCL, B, D]
                        if E == 1:
                            t = ese * base(Y, RECCL) + add * iN + (rp90rp + rep) * iN + rp90 * iR + (sr90 + sur) * iA
                        else:
                            iHV = ONE / WHV[Y, RECCL, B, D]
                            t = ese * base(Y, RECCL) + add * iHV + (rp90rp + rep) * iN + rp90 * iR + (sr90 + sur) * iA
                        NUME[Y, E] = NUME[Y, E] + t
                        NUME1[Y, E, B, D] = t
                        # no parentheses around the seven terms in EIA's DEN here
                        DEN[Y, E] = _ltr(DEN[Y, E], *[ARR[k][Y, RECCL, B, D] for k in ORD_CL])
                        DEN1[Y, E, B, D] = ex_den(Y, RECCL, B, D, ORD_CL)
        set_class_base_2020(eu, CL_COL, RSEEFCL)
        class_eff(eu, CL_COL, RSEEFCL)
        for D in range(1, nd + 1):
            for B in range(1, nb + 1):
                for Y in yrs1:
                    Y1 = Y - BASEYR + 1
                    for RECCL in reccls(eu):
                        EQC = int(rtcleqcl[RECCL])
                        if DEN1[Y, EQC, B, D] > 0.0:
                            if EQC <= 3:  # COP to EER or SEER
                                RSEEFDB1[Y1, RECCL, B, D] = (NUME1[Y, EQC, B, D] / DEN1[Y, EQC, B, D]) * K3412
                            else:
                                RSEEFDB1[Y1, RECCL, B, D] = NUME1[Y, EQC, B, D] / DEN1[Y, EQC, B, D]
                        else:
                            if EQC <= 3:
                                RSEEFDB1[Y1, RECCL, B, D] = RSEEFDB1[y0, RECCL, B, D] * K3412
                            else:
                                RSEEFDB1[Y1, RECCL, B, D] = RSEEFDB1[y0, RECCL, B, D]

        # clothes washers (plain weights) and dishwashers (inverse weights)
        for eu, inverse in ((3, False), (4, True)):
            set_base_2020(eu)
            for Y in yrs1:
                for RECCL in reccls(eu):
                    EQC = int(rtcleqcl[RECCL])
                    for D in range(1, nd + 1):
                        for B in range(1, nb + 1):
                            NUME1[Y, EQC, B, D] = ex_nume1(Y, RECCL, B, D, inverse)
                            DEN1[Y, EQC, B, D] = ex_den(Y, RECCL, B, D, ORD_RF)
            ex_final_db(eu, col1=True)

        # water heaters
        eu = 5
        for Y in yrs1:
            for RECCL in reccls(eu):
                E = int(rtcleqcl[RECCL])
                NUME[Y, E] = ZERO
                DEN[Y, E] = ZERO
                for D in range(1, nd + 1):
                    for B in range(1, nb + 1):
                        t = ex_nume1(Y, RECCL, B, D, True)
                        NUME[Y, E] = NUME[Y, E] + t
                        DEN[Y, E] = DEN[Y, E] + ex_den(Y, RECCL, B, D, ORD_WH)
                        NUME1[Y, E, B, D] = t
                        DEN1[Y, E, B, D] = ex_den(Y, RECCL, B, D, ORD_WH)
        set_class_base_2020(eu, HW_COL, RSEEFHW)
        class_eff(eu, HW_COL, RSEEFHW)
        ex_final_db(eu)

        # cooking (plain weights) then clothes dryers (inverse weights); the RECS-year
        # base is set after the sums, which gives the same result
        for eu, inverse in ((6, False), (7, True)):
            for Y in yrs1:
                for RECCL in reccls(eu):
                    E = int(rtcleqcl[RECCL])
                    for D in range(1, nd + 1):
                        for B in range(1, nb + 1):
                            NUME1[Y, E, B, D] = ex_nume1(Y, RECCL, B, D, inverse)
                            DEN1[Y, E, B, D] = ex_den(Y, RECCL, B, D, ORD_WH)
            for RECCL in reccls(eu):
                for D in range(1, nd + 1):
                    for B in range(1, nb + 1):
                        RSEEFDB1[y0, RECCL, B, D] = rtbaseff[RECSYEAR, RECCL]
            ex_final_db(eu)

        # refrigerators (from 2021) and freezers (from 2020, where DEN is still 0
        # so the RECS value stays); plain weights, class 1 read back
        for eu, out, yfirst in ((8, RSEEFRF, RECSYEAR + 1), (9, RSEEFFZ, RECSYEAR)):
            for RECCL in reccls(eu):
                out[y0] = rtbaseff[RECSYEAR, RECCL]
                for D in range(1, nd + 1):
                    for B in range(1, nb + 1):
                        RSEEFDB1[y0, RECCL, B, D] = rtbaseff[RECSYEAR, RECCL]
            for Y in yrs1:
                for RECCL in reccls(eu):
                    EQC = int(rtcleqcl[RECCL])
                    NUME[Y, EQC] = ZERO
                    DEN[Y, EQC] = ZERO
                    for D in range(1, nd + 1):
                        for B in range(1, nb + 1):
                            t = ex_nume1(Y, RECCL, B, D, False)
                            NUME[Y, EQC] = NUME[Y, EQC] + t
                            DEN[Y, EQC] = DEN[Y, EQC] + ex_den(Y, RECCL, B, D, ORD_RF)
                            NUME1[Y, EQC, B, D] = t
                            DEN1[Y, EQC, B, D] = ex_den(Y, RECCL, B, D, ORD_RF)
            for Y in range(yfirst, y_end + 1):
                if DEN[Y, 1] > 0.0:
                    out[Y - BASEYR + 1] = NUME[Y, 1] / DEN[Y, 1]
            ex_final_db(eu, col1=True)
