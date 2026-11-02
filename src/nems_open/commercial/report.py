"""Commercial national report variables: port of the state COMReport (comm.f) leaves behind.

COMReport mostly writes tables for the KRPT, KSDOUT and KDBOUT report files. What it leaves
in memory for the rest of NEMS is a set of national totals in COMMREP: benchmarked and
unbenchmarked fuel use summed over the nine divisions into the national column, the same
for non-building use, and zeros in the national consumption arrays for the years before
the first projection year. This port covers that state, not the printed report.

NEMS calls it once, in the last year of the last iteration. The sums only run when the
KRPT report switch (ReportOption in kparm.txt) is on; the zeroing always runs.

Loop order follows the Fortran, including the totals EIA rebuilds twice.
"""

import numpy as np

f32 = np.float32
CM_FIRST_YR = 30
KSTEOYR = 37
MNUMCR = 11
NUM_DIV = 9
NUM_BLDG = 11
NUM_MAJ_FL = 3
NUM_ALL_FL = 8


def report(inp: dict, last_year: int = 61, cm_last_year: int = 61, report_option: int = 1) -> dict:
    """Return COMMREP arrays after one call of COMReport.

    `inp` holds CMFinalEndUse, CMNonBldgUse, CMFinalUnbenchUse and the national arrays
    that get zeroed before CMFirstYr (CMUSSurvFloorTot, CMUSNewFloorTot, CMUSCogen,
    CMFinalEndUseCon, CMSurvFloorTot, CMNewFlrSpace, CMUSConsumption, CMUSAvgEff,
    CMUSPurchEff, CMUSDistServ), all lower case.
    """
    names = ("cmfinalenduse", "cmnonbldguse", "cmfinalunbenchuse", "cmussurvfloortot", "cmusnewfloortot",
             "cmuscogen", "cmfinalendusecon", "cmsurvfloortot", "cmnewflrspace", "cmusconsumption",
             "cmusavgeff", "cmuspurcheff", "cmusdistserv")
    out = {k: inp[k].copy() for k in names}
    final, nonbldg, unbench = out["cmfinalenduse"], out["cmnonbldguse"], out["cmfinalunbenchuse"]

    if report_option != 0:
        # Benchmarked and non-building use to the STEO year, by fuel, summed over divisions.
        for y in range(CM_FIRST_YR, KSTEOYR + 1):
            for f in range(1, NUM_ALL_FL + 1):
                final[f, 11, y] = 0.0
                for r in range(1, NUM_DIV + 1):
                    final[f, 11, y] = f32(final[f, 11, y] + final[f, r, y])
            for f in range(1, NUM_MAJ_FL + 1):
                nonbldg[f, MNUMCR, y] = 0.0
                for r in range(1, NUM_DIV + 1):
                    nonbldg[f, MNUMCR, y] = f32(nonbldg[f, MNUMCR, y] + nonbldg[f, r, y])

        # Benchmarked end use for every year, all fuels.
        for f in range(1, NUM_ALL_FL + 1):
            for i in range(CM_FIRST_YR, cm_last_year + 1):
                final[f, 11, i] = 0.0
        for r in range(1, NUM_DIV + 1):
            for f in range(1, NUM_ALL_FL + 1):
                for i in range(CM_FIRST_YR, cm_last_year + 1):
                    final[f, 11, i] = f32(final[f, 11, i] + final[f, r, i])

        # Unbenchmarked end use: the national column is cleared in both arrays, then both are rebuilt.
        for f in range(1, NUM_MAJ_FL + 1):
            for i in range(CM_FIRST_YR, last_year + 1):
                unbench[f, 11, i] = 0.0
                final[f, 11, i] = 0.0
        for r in range(1, NUM_DIV + 1):
            for f in range(1, NUM_MAJ_FL + 1):
                for i in range(CM_FIRST_YR, last_year + 1):
                    unbench[f, 11, i] = f32(unbench[f, 11, i] + unbench[f, r, i])
                    final[f, 11, i] = f32(final[f, 11, i] + final[f, r, i])

    # National arrays for years before the first projection year are zero.
    for iyr in range(1, CM_FIRST_YR):
        out["cmussurvfloortot"][iyr] = 0.0
        out["cmusnewfloortot"][iyr] = 0.0
        for i in range(1, 5):
            out["cmuscogen"][i, iyr] = 0.0
        for b in range(1, NUM_BLDG + 1):
            out["cmfinalendusecon"][b, iyr] = 0.0
            out["cmsurvfloortot"][b, iyr] = 0.0
            out["cmnewflrspace"][b, iyr] = 0.0
        for f in range(1, NUM_MAJ_FL + 1):
            for s in range(1, 11):
                out["cmusconsumption"][s, f, iyr] = 0.0
                if s < 10:
                    out["cmusavgeff"][s, f, iyr] = 0.0
                    out["cmuspurcheff"][s, f, iyr] = 0.0
                    if s < 4:
                        out["cmusdistserv"][s, f, iyr] = 0.0
    return out
