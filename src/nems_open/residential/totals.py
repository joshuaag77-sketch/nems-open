"""Fuel totals, benchmarking, NEMS output and report aggregates (resd.f):
FUELCN, RSBENCH, NEMSCN, RESDRP and EXCONS.

FUELCN sums end-use consumption into fuel totals RSFLCN. RSBENCH adds the SEDS/STEO
benchmark factor. NEMSCN copies the totals into the QBLK quantities. RESDRP builds
the REPORTER table 4 arrays. EXCONS is the RECS-year consumption build.
Writes to debug units (9, 6) are skipped everywhere.
"""

from pathlib import Path

import numpy as np

from nems_open.paths import REPO_ROOT
from nems_open.residential.common import BASEYR, RECSYEAR, f32

f64 = np.float64

NUM_D = 9  # mNumCR-2 census divisions
NATIONAL = 11  # NationalPtr
MNUMCR = 11
MNUMFUEL = 5
MNUMBLDG = 3

# resdrep / parametr parameters RSBENCH reads
MSEDYR = 34
LASTSEDSYR = BASEYR - 1 + MSEDYR
LASTSTEOYR = 2026
LASTSTEOYRAVAIL = 2027
BENCHALLYRS = f32(1.0)
GLOBALBENCHON = 1
STEOBM = 1  # options.txt of the oracle run (STEOBM 1)

RSSTEO_PATH = REPO_ROOT / "nems-upstream" / "input" / "rdm" / "rssteo.txt"

_steo = {}  # COMMON/STEO is SAVEd between RSBENCH calls; the dumps do not hold it


def _read_rssteo() -> None:
    """RSBENCH's first-year read of RSSTEO: tweak factors, then STEOCN for
    distillate (F=3) and propane (F=4), nine divisions by 2021..2027. The file is
    a constant input table, so it is read from the repo rather than the dump."""
    lines = RSSTEO_PATH.read_text(encoding="latin-1").splitlines()
    # READ '(19(/))' touches 20 records, so the first value is on line 21; each
    # '(1(/))' then eats the blank line and the next label line.
    i = 20
    bench_ng = f32(lines[i].split()[0])
    i += 3
    bench_el = f32(lines[i].split()[0])
    i += 3
    steocn = {}
    for f in (3, 4):
        i += 1  # skip header
        for d in range(1, NUM_D + 1):
            vals = lines[i].split()
            for k, y1 in enumerate(range(RECSYEAR + 1, LASTSTEOYRAVAIL + 1)):
                steocn[(y1, f, d)] = f32(vals[k])
            i += 1
    _steo.update(ng=bench_ng, el=bench_el, cn=steocn)


def _sum32(*terms):
    """Left-to-right REAL*4 sum."""
    acc = f32(terms[0])
    for t in terms[1:]:
        acc = f32(acc + t)
    return acc


# ---------------------------------------------------------------------------
def fuelcn(s: dict) -> None:
    """FUELCN: RSFLCN(Y, fuel, division) in quads from end-use consumption in
    trillion Btu; fuel 1 gas, 2 electricity, 3 distillate, 4 propane, 5 wood.
    Division 10 holds the sum of the nine (EIA calls it national)."""
    Y = int(s["curcalyr"]) - BASEYR + 1
    R = s["rsflcn"]
    HTR, H2O, CK, DRY, COOL = s["htrcon"], s["h2ocon"], s["ckcon"], s["drycon"], s["coolcn"]
    SHT, APL = s["shtcon"], s["aplcon"]
    mil = f32(1000000.0)
    for D in range(1, NUM_D + 1):
        R[Y, 1, D] = _sum32(HTR[Y, 1, D], H2O[Y, 1, D], CK[Y, 1, D], DRY[Y, 1, D], COOL[Y, 2, D],
                            SHT[Y, 1, D], APL[Y, 1, D]) / mil
        R[Y, 2, D] = _sum32(HTR[Y, 2, D], COOL[Y, 1, D], H2O[Y, 2, D], s["refcon"][Y, D], CK[Y, 3, D],
                            DRY[Y, 2, D], SHT[Y, 2, D], s["tvrcon"][Y, D], s["frzcon"][Y, D],
                            s["ltcon"][Y, D], s["apcon"][Y, D], s["pcrcon"][Y, D], s["fancon"][Y, D],
                            s["cswcon"][Y, D], s["dswcon"][Y, D]) / mil
        R[Y, 3, D] = _sum32(APL[Y, 3, D], HTR[Y, 3, D], H2O[Y, 3, D], SHT[Y, 3, D]) / mil
        R[Y, 4, D] = _sum32(SHT[Y, 4, D], APL[Y, 2, D], HTR[Y, 4, D], H2O[Y, 4, D], CK[Y, 2, D]) / mil
        R[Y, 5, D] = _sum32(HTR[Y, 5, D], SHT[Y, 5, D]) / mil
    for F in range(1, MNUMFUEL + 1):
        R[Y, F, 10] = 0.0
        for D in range(1, NUM_D + 1):
            R[Y, F, 10] = f32(R[Y, F, 10] + R[Y, F, D])


# ---------------------------------------------------------------------------
def rsbench(s: dict) -> None:
    """RSBENCH: additive benchmark factors BNCHFCT(Y, fuel, division) against SEDS
    (through MSEDYR), STEO (to LASTSTEOYR) and a held average afterwards, added to
    RSFLCN and pushed into space heating, appliances and water heating.
    Fuel here: 1 gas, 2 electricity, 3 distillate+kerosene, 4 propane.
    Distributed-generation terms are REAL*8 in the Fortran, so those sums are
    done in double and rounded once on the store."""
    Y = int(s["curiyr"])
    cal = int(s["curcalyr"])
    if cal == RECSYEAR or not _steo:
        _read_rssteo()
    STEOCN = _steo["cn"]
    bench_ng, bench_el = _steo["ng"], _steo["el"]

    iLastSTEOYr = LASTSTEOYR
    if STEOBM == 0:
        iLastSTEOYr = LASTSEDSYR + 1

    thou = f32(1000.0)
    k3412 = f32(3.412)
    # Regional gas shares of the national STEO total (every year gets this year's
    # numbers; only STEOCN(CURCALYR) is read later).
    ng = [s["ngrcp_nec"], s["ngrcp_mac"], s["ngrcp_enc"], s["ngrcp_wnc"], s["ngrcp_sac"],
          s["ngrcp_esc"], s["ngrcp_wsc"], s["ngrcp_mtn"], s["ngrcp_pac"]]
    ex = [s["exrcp_nec"], s["exrcp_mac"], s["exrcp_enc"], s["exrcp_wnc"], s["exrcp_sac"],
          s["exrcp_esc"], s["exrcp_wsc"], s["exrcp_mtn"]]
    den = _sum32(*[a[Y] for a in ng])
    for Y1 in range(RECSYEAR + 1, LASTSTEOYRAVAIL + 1):
        for d in range(1, NUM_D + 1):
            with np.errstate(all="ignore"):  # 0/0 gives NaN as in Fortran; unused after the STEO years
                STEOCN[(Y1, 1, d)] = f32(f32(f32(ng[d - 1][Y] / den) * s["ngrcbus"][Y]) * thou)
        for d in range(1, 9):
            STEOCN[(Y1, 2, d)] = f32(ex[d - 1][Y] * k3412)
        STEOCN[(Y1, 2, 9)] = f32(f32(s["exrcp_pac"][Y] + s["exrcp_hak"][Y]) * k3412)

    RS, BN, BAVG = s["rsflcn"], s["bnchfct"], s["bnchfctavg"]
    GAS, HW, OWN = s["gasusage"], s["hwbtu"], s["trillsownuse"]

    # High-level adjustments for distributed generation (REAL*8 arithmetic).
    for D in range(1, NUM_D + 1):
        RS[Y, 1, D] = f32(f64(RS[Y, 1, D]) + GAS[Y, D, 2] - HW[Y, D, 2])
        RS[Y, 2, D] = f32(f64(RS[Y, 2, D]) - OWN[Y, D, 1] - OWN[Y, D, 2] - OWN[Y, D, 3] - OWN[Y, D, 4])

    if Y <= MSEDYR:
        for D in range(1, NUM_D + 1):
            BN[Y, 1, D] = f32(s["qsngrs"][D, Y] - RS[Y, 1, D])
            BN[Y, 2, D] = f32(s["qselrs"][D, Y] - RS[Y, 2, D])
            BN[Y, 3, D] = f32(f32(s["qsdsrs"][D, Y] + s["qsksrs"][D, Y]) - RS[Y, 3, D])
            BN[Y, 4, D] = f32(s["qslgrs"][D, Y] - RS[Y, 4, D])
    elif Y > MSEDYR and cal <= iLastSTEOYr:
        for F in range(1, MNUMFUEL):
            for D in range(1, NUM_D + 1):
                BN[Y, F, D] = f32(STEOCN[(cal, F, D)] - RS[Y, F, D])
    elif cal > iLastSTEOYr:
        for F in range(1, MNUMFUEL):
            for D in range(1, NUM_D + 1):
                if F <= 2:
                    BN[Y, F, D] = f32(BAVG[F, D] * BENCHALLYRS)
                    if F == 1 and bench_ng != f32(1.0):
                        BN[Y, F, D] = f32(f32(BN[LASTSEDSYR + 1 - BASEYR + 1, F, D] * bench_ng) * BENCHALLYRS)
                    if F == 2 and bench_el != f32(1.0):
                        BN[Y, F, D] = f32(f32(BN[LASTSEDSYR + 1 - BASEYR + 1, F, D] * bench_el) * BENCHALLYRS)
                else:
                    BN[Y, F, D] = BAVG[F, D]

    # Average of the last years of factors, first year after the MER year.
    if Y == MSEDYR + 2:
        n_acc = min(MSEDYR + 1 - (RECSYEAR - BASEYR + 1), 4)
        n_div = f32(min(MSEDYR + 1 - (RECSYEAR - BASEYR + 1), 5))
        for D in range(1, NUM_D + 1):
            for F in range(1, MNUMFUEL):
                BAVG[F, D] = 0.0
            for y4 in range(1, n_acc + 1):
                for F in range(1, MNUMFUEL):
                    BAVG[F, D] = f32(BAVG[F, D] + BN[Y - y4, F, D])
            for F in range(1, MNUMFUEL):
                BAVG[F, D] = f32(BAVG[F, D] / n_div)

    # GLOBALBENCHON is 1, so the test-only branch that freezes factors never runs.

    for D in range(1, NUM_D + 1):
        for F in range(1, MNUMFUEL):
            RS[Y, F, D] = f32(RS[Y, F, D] + BN[Y, F, D])

    mil = f32(1000000.0)
    HTR, HWT, HIN = s["htrcon"], s["htrconwt"], s["htrconin"]
    F, B = 1, 1
    for D in range(1, NUM_D + 1):
        HTR[Y, F, D] = f32(HTR[Y, F, D] + f32(BN[Y, F, D] * mil))
        HWT[Y, F, D, B] = f32(HWT[Y, F, D, B] + f32(BN[Y, F, D] * mil))

    B = 1
    for D in range(1, NUM_D + 1):
        for F in (3, 4):
            HTR[Y, F, D] = f32(HTR[Y, F, D] + f32(BN[Y, F, D] * mil))
            # weights must not go negative
            if f32(HWT[Y, F, D, B] + f32(BN[Y, F, D] * mil)) > 0.0 and HWT[Y, F, D, B] > 0.0:
                HIN[Y, F, D, B] = f32(f32(f32(f32(BN[Y, F, D] * mil) + HWT[Y, F, D, B]) / HWT[Y, F, D, B])
                                      * HIN[Y, F, D, B])
                HWT[Y, F, D, B] = f32(HWT[Y, F, D, B] + f32(BN[Y, F, D] * mil))
            else:
                HIN[Y, F, D, B] = 0.0
                HWT[Y, F, D, B] = 0.0

    for D in range(1, NUM_D + 1):
        B = 1
        s["apcon"][Y, D] = f32(s["apcon"][Y, D] + f32(BN[Y, 2, D] * mil))
        s["apconwt"][Y, D, B] = f32(s["apconwt"][Y, D, B] + f32(BN[Y, 2, D] * mil))
        s["eaeqcn"][Y, 1, B, D] = f32(s["eaeqcn"][Y, 1, B, D] + f32(BN[Y, 2, D] * mil))

    # Fuel cells: gas for the cells goes to water heating (REAL*8 sums again).
    m8 = f64(1000000.0)
    H2O, H2OWT, EQN = s["h2ocon"], s["h2oconwt"], s["eqceqcn"]
    for D in range(1, NUM_D + 1):
        H2O[Y, 1, D] = f32(f64(H2O[Y, 1, D]) - HW[Y, D, 2] * m8 + (GAS[Y, D, 2] + GAS[Y, D, 3]) * m8)
        for B in range(1, MNUMBLDG + 1):
            if B == 1:
                H2OWT[Y, 1, D, B] = f32(f64(H2OWT[Y, 1, D, B]) - (HW[Y, D, 2] + GAS[Y, D, 2]) * m8)
                EQN[Y, 18, B, D] = f32(f64(EQN[Y, 18, B, D]) - (HW[Y, D, 2] + GAS[Y, D, 2]) * m8)


# ---------------------------------------------------------------------------
def nemscn(s: dict) -> None:
    """NEMSCN: residential quantities in the QBLK arrays (quads), by division.
    QELRS is net of onsite own-use generation plus the TRQ_ELEC adder; solar PV
    comes from Trills(.,.,1)."""
    Y = int(s["curcalyr"]) - BASEYR + 1
    RS, SL = s["rsflcn"], s["slcon"]
    SL[Y, 10] = 0.0
    s["qpvrs"][NATIONAL, Y] = 0.0
    OWN, TR = s["trillsownuse"], s["trills"]
    mil = f32(1000000.0)
    for D in range(1, NUM_D + 1):
        s["qngrs"][D, Y] = RS[Y, 1, D]
        s["qgfrs"][D, Y] = f32(s["qngrs"][D, Y] * f32(1.0))
        s["qgirs"][D, Y] = f32(s["qngrs"][D, Y] * f32(0.0))

        # Own-use is REAL*8; the whole expression is evaluated in double.
        own = OWN[Y, D, 1] + OWN[Y, D, 2] + OWN[Y, D, 3] + OWN[Y, D, 4]
        s["qelrs"][D, Y] = f32(f64(RS[Y, 2, D]) - own / f64(1000.0) + f64(s["trq_elec"][1, D, Y]))

        if RS[Y, 3, D] < 0.0:
            s["qdsrs"][D, Y] = 0.0
        else:
            s["qdsrs"][D, Y] = RS[Y, 3, D]

        s["qlgrs"][D, Y] = RS[Y, 4, D]
        s["qprrs"][D, Y] = s["qlgrs"][D, Y]
        s["qbmrs"][D, Y] = RS[Y, 5, D]

        if int(s["curiyr"]) < RECSYEAR - BASEYR + 1:
            s["qpvrs"][D, Y] = s["qpvrs"][D, Y - 1]
        else:
            s["qpvrs"][D, Y] = f32(TR[Y, D, 1])
        s["qpvrs"][NATIONAL, Y] = f32(s["qpvrs"][NATIONAL, Y] + s["qpvrs"][D, Y])

        SL[Y, 10] = f32(SL[Y, 10] + SL[Y, D])  # EIA: slot 10 is California, not national
        s["qstrs"][D, Y] = f32(SL[Y, D] / mil)

        s["qksrs"][D, Y] = 0.0
        s["qgers"][D, Y] = 0.0


# ---------------------------------------------------------------------------
def resdrp(s: dict) -> None:
    """RESDRP: REPORTER table 4 arrays, sums over the nine divisions."""
    Y = int(s["curiyr"])
    cal = int(s["curcalyr"])
    EH, NH, HSEADD = s["eh"], s["nh"], s["hseadd"]
    nb = MNUMBLDG

    for B in range(1, nb + 1):
        s["rseh"][Y, B] = 0.0
        s["rsnh"][Y, B] = 0.0
        s["rshseadd"][Y, B] = 0.0
    for B in range(1, nb + 1):
        for D in range(1, NUM_D + 1):
            s["rseh"][Y, B] = f32(s["rseh"][Y, B] + EH[cal, B, D])
            s["rsnh"][Y, B] = f32(s["rsnh"][Y, B] + NH[cal, B, D])
            s["rshseadd"][Y, B] = f32(s["rshseadd"][Y, B] + HSEADD[cal, B, D])

    for D in range(1, NUM_D + 1):
        s["rshouses"][Y, D] = 0.0
    for D in range(1, NUM_D + 1):
        for B in range(1, nb + 1):
            s["rshouses"][Y, D] = f32(s["rshouses"][Y, D] + f32(EH[cal, B, D] + NH[cal, B, D]))
            s["totalhouses"][Y, B, D] = f32(EH[cal, B, D] + NH[cal, B, D])

    nhtrfl, nclfl, nwhfl = int(s["nhtrfl"]), int(s["nclfl"]), int(s["nwhfl"])
    nstvfl, ndryfl = int(s["nstvfl"]), int(s["ndryfl"])

    for F in range(1, nhtrfl + 1):
        s["rshtrcon"][Y, F] = 0.0
    for F in range(1, nhtrfl + 1):
        for D in range(1, NUM_D + 1):
            # primary and secondary space heating, one expression
            s["rshtrcon"][Y, F] = f32(f32(s["rshtrcon"][Y, F] + s["htrcon"][Y, F, D]) + s["shtcon"][Y, F, D])

    for F in range(1, nclfl + 1):
        s["rscoolcn"][Y, F] = 0.0
    for D in range(1, NUM_D + 1):
        for F in range(1, nclfl + 1):
            s["rscoolcn"][Y, F] = f32(s["rscoolcn"][Y, F] + s["coolcn"][Y, F, D])

    for F in range(1, nwhfl + 1):
        s["rsh2ocon"][Y, F] = 0.0
    s["rsh2ocon"][Y, 5] = s["slcon"][Y, 10]  # EIA: slot 10 is California, not national
    for F in range(1, nwhfl):
        for D in range(1, NUM_D + 1):
            s["rsh2ocon"][Y, F] = f32(s["rsh2ocon"][Y, F] + s["h2ocon"][Y, F, D])

    for F in range(1, nstvfl + 1):
        s["rsckcon"][Y, F] = 0.0
    for D in range(1, NUM_D + 1):
        for F in (1, 2, 3):
            s["rsckcon"][Y, F] = f32(s["rsckcon"][Y, F] + s["ckcon"][Y, F, D])

    for F in range(1, ndryfl + 1):
        s["rsdrycon"][Y, F] = 0.0
    for F in range(1, ndryfl + 1):
        for D in range(1, NUM_D + 1):
            s["rsdrycon"][Y, F] = f32(s["rsdrycon"][Y, F] + s["drycon"][Y, F, D])

    for F in range(1, 5):
        s["rsapcon"][Y, F] = 0.0
    for D in range(1, NUM_D + 1):
        s["rsapcon"][Y, 1] = f32(s["rsapcon"][Y, 1] + s["aplcon"][Y, 1, D])
        s["rsapcon"][Y, 2] = f32(s["rsapcon"][Y, 2] + s["apcon"][Y, D])
        s["rsapcon"][Y, 3] = f32(s["rsapcon"][Y, 3] + s["aplcon"][Y, 3, D])
        s["rsapcon"][Y, 4] = f32(s["rsapcon"][Y, 4] + s["aplcon"][Y, 2, D])

    names = ["rscswcon", "rsdswcon", "rsrefcon", "rsfrzcon", "rsltcon", "rstvrcon", "rspcrcon", "rsfancon"]
    for n in names:
        s[n][Y] = 0.0
    r31 = RECSYEAR - BASEYR + 1
    s["rsltcon"][r31] = 0.0  # EIA: also clears the RECS-year total, then rebuilds it below
    for D in range(1, NUM_D + 1):
        s["rscswcon"][Y] = f32(s["rscswcon"][Y] + s["cswcon"][Y, D])
        s["rsdswcon"][Y] = f32(s["rsdswcon"][Y] + s["dswcon"][Y, D])
        s["rsrefcon"][Y] = f32(s["rsrefcon"][Y] + s["refcon"][Y, D])
        s["rsfrzcon"][Y] = f32(s["rsfrzcon"][Y] + s["frzcon"][Y, D])
        s["rsltcon"][r31] = f32(s["rsltcon"][r31] + s["ltcon"][r31, D])
        s["rsltcon"][Y] = f32(s["rsltcon"][Y] + s["ltcon"][Y, D])
        s["rstvrcon"][Y] = f32(s["rstvrcon"][Y] + s["tvrcon"][Y, D])
        s["rsfancon"][Y] = f32(s["rsfancon"][Y] + s["fancon"][Y, D])
        s["rspcrcon"][Y] = f32(s["rspcrcon"][Y] + s["pcrcon"][Y, D])


# ---------------------------------------------------------------------------
def _txt(v) -> str:
    return v.decode("latin-1").strip() if isinstance(v, bytes) else str(v).strip()


def excons(s: dict) -> None:
    """EXCONS: RECS-year (2020) consumption from RSSTK stocks times unit energy
    consumption, end use by end use, then the fuel totals and QBLK quantities.
    CurIYr is the RECS index (31)."""
    I = int(s["curiyr"])
    RY = RECSYEAR
    EQCESE, EQCUEC = s["eqcese"], s["eqcuec"]
    RTCLEUPT, RTCLEQCL, RTFUEL, RTCLNAME = s["rtcleupt"], s["rtcleqcl"], s["rtfuel"], s["rtclname"]
    mil = f32(1000000.0)

    s["cwload"][RY] = f32(0.2047)

    # space heating
    EU = 1
    for F in range(1, int(s["nhtrfl"]) + 1):
        for D in range(1, NUM_D + 1):
            s["htrcon"][I, F, D] = 0.0
    for F in range(1, int(s["nhtrfl"]) + 1):
        for D in range(1, NUM_D + 1):
            s["shtcon"][I, F, D] = 0.0
    for RECCL in range(RTCLEUPT[EU] + 1, RTCLEUPT[EU + 1] + 1):
        FCON = int(s["fhtrcon"][int(RTFUEL[RECCL])])
        for D in range(1, NUM_D + 1):
            for B in range(1, MNUMBLDG + 1):
                s["htrcon"][I, FCON, D] = f32(s["htrcon"][I, FCON, D] + f32(EQCESE[RY, RECCL, B, D] * EQCUEC[D, RECCL, B]))

    # space cooling
    EU = 2
    for F in range(1, int(s["nclfl"]) + 1):
        for D in range(1, NUM_D + 1):
            s["coolcn"][I, F, D] = 0.0
    for RECCL in range(RTCLEUPT[EU] + 1, RTCLEUPT[EU + 1] + 1):
        FCON = int(s["fclcon"][int(RTFUEL[RECCL])])
        for D in range(1, NUM_D + 1):
            for B in range(1, MNUMBLDG + 1):
                s["coolcn"][I, FCON, D] = f32(s["coolcn"][I, FCON, D] + f32(EQCESE[RY, RECCL, B, D] * EQCUEC[D, RECCL, B]))

    # clothes washing (EIA quirk: the total is zeroed inside the RECCL loop)
    EU = 3
    for D in range(1, NUM_D + 1):
        for RECCL in range(RTCLEUPT[EU] + 1, RTCLEUPT[EU + 1] + 1):
            s["cswcon"][I, D] = 0.0
            for B in range(1, MNUMBLDG + 1):
                s["cswcon"][I, D] = f32(s["cswcon"][I, D] + f32(EQCESE[RY, RECCL, B, D] * EQCUEC[D, RECCL, B]))

    # dishwashing (same quirk)
    EU = 4
    for D in range(1, NUM_D + 1):
        for RECCL in range(RTCLEUPT[EU] + 1, RTCLEUPT[EU + 1] + 1):
            s["dswcon"][I, D] = 0.0
            for B in range(1, MNUMBLDG + 1):
                s["dswcon"][I, D] = f32(s["dswcon"][I, D] + f32(EQCESE[RY, RECCL, B, D] * EQCUEC[D, RECCL, B]))

    # water heating and solar
    EU = 5
    RECCLEWH = RECCLSWH = 0
    for RECCL in range(RTCLEUPT[EU] + 1, RTCLEUPT[EU + 1] + 1):
        name = _txt(RTCLNAME[RECCL])
        if name == "ELEC_WH":
            RECCLEWH = int(RTCLEQCL[RECCL]) + RTCLEUPT[EU]
        elif name == "SOLAR_WH":
            RECCLSWH = int(RTCLEQCL[RECCL]) + RTCLEUPT[EU]
    for D in range(1, NUM_D + 1):
        s["slcon"][I, D] = 0.0
        for RECCL in range(RTCLEUPT[EU] + 1, RTCLEUPT[EU + 1] + 1):
            FCON = int(s["fwhcon"][int(RTFUEL[RECCL])])
            s["h2ocon"][I, FCON, D] = 0.0
    k3412 = f32(3412.0)
    for D in range(1, NUM_D + 1):
        for B in range(1, MNUMBLDG + 1):
            for RECCL in range(RTCLEUPT[EU] + 1, RTCLEUPT[EU + 1] + 1):
                FCON = int(s["fwhcon"][int(RTFUEL[RECCL])])
                s["h2ocon"][I, FCON, D] = f32(s["h2ocon"][I, FCON, D] + f32(EQCUEC[D, RECCL, B] * EQCESE[RY, RECCL, B, D]))
            solar = f32(f32(f32(EQCESE[RY, RECCLSWH, B, D] * f32(EQCUEC[D, RECCLEWH, B] - EQCUEC[D, RECCLSWH, B]))
                            * s["whrfoss"][D, I]) / k3412)
            s["h2ocon"][I, 5, D] = f32(s["h2ocon"][I, 5, D] + solar)
            s["slcon"][I, D] = f32(s["slcon"][I, D] + solar)
            s["sleqcn"][I, 1, B, D] = solar

    # cooking, drying: reset per RECCL, so the last record of the end use wins the reset
    EU = 6
    for D in range(1, NUM_D + 1):
        for RECCL in range(RTCLEUPT[EU] + 1, RTCLEUPT[EU + 1] + 1):
            EQC = int(RTCLEQCL[RECCL])
            s["ckcon"][I, EQC, D] = 0.0
            for B in range(1, MNUMBLDG + 1):
                s["ckcon"][I, EQC, D] = f32(s["ckcon"][I, EQC, D] + f32(EQCESE[RY, RECCL, B, D] * EQCUEC[D, RECCL, B]))
    EU = 7
    for D in range(1, NUM_D + 1):
        for RECCL in range(RTCLEUPT[EU] + 1, RTCLEUPT[EU + 1] + 1):
            EQC = int(RTCLEQCL[RECCL])
            s["drycon"][I, EQC, D] = 0.0
            for B in range(1, MNUMBLDG + 1):
                s["drycon"][I, EQC, D] = f32(s["drycon"][I, EQC, D] + f32(EQCESE[RY, RECCL, B, D] * EQCUEC[D, RECCL, B]))

    # refrigeration and freezing (total zeroed per RECCL again)
    for EU, name in ((8, "refcon"), (9, "frzcon")):
        for D in range(1, NUM_D + 1):
            for RECCL in range(RTCLEUPT[EU] + 1, RTCLEUPT[EU + 1] + 1):
                s[name][I, D] = 0.0
                for B in range(1, MNUMBLDG + 1):
                    s[name][I, D] = f32(s[name][I, D] + f32(EQCESE[RY, RECCL, B, D] * EQCUEC[D, RECCL, B]))

    # furnace fans
    for D in range(1, NUM_D + 1):
        s["fancon"][I, D] = 0.0
    for D in range(1, NUM_D + 1):
        for B in range(1, MNUMBLDG + 1):
            s["faneqcn"][I, 1, B, D] = f32(s["faneqp"][RY, B, D] * s["fanuec"][D, B])
            s["fancon"][I, D] = f32(s["fancon"][I, D] + f32(s["faneqp"][RY, B, D] * s["fanuec"][D, B]))

    # miscellaneous electric loads; local arrays in the Fortran, so local here
    mels = ["tvs", "stb", "hts", "ott", "vgc", "dpc", "lpc", "mon", "net", "bat", "cfn", "cof", "deh",
            "mco", "plp", "plh", "sec", "spa", "wcl", "spk", "phn", "tab", "kit"]
    con = {m: np.zeros(NUM_D + 1, dtype=np.float32) for m in mels + ["ea"]}
    for D in range(1, NUM_D + 1):
        for B in range(1, MNUMBLDG + 1):
            for m in mels:
                con[m][D] = f32(con[m][D] + f32(s[m + "eqp"][RY, B, D] * s[m + "uec"][D, B]))
            con["ea"][D] = f32(con["ea"][D] + f32(s["eh"][RY, B, D] * s["eauec"][D, B]))
            s["eaeqcn"][I, 1, B, D] = f32(s["eh"][RY, B, D] * s["eauec"][D, B])
    # the US sums (xxxCONUS) are locals nothing reads

    for D in range(1, NUM_D + 1):
        # EIA quirk: the building loop repeats the same assignment three times
        s["tvrcon"][I, D] = _sum32(con["tvs"][D], con["stb"][D], con["hts"][D], con["ott"][D], con["vgc"][D])
        s["pcrcon"][I, D] = _sum32(con["dpc"][D], con["lpc"][D], con["mon"][D], con["net"][D])
        s["apcon"][I, D] = _sum32(con["bat"][D], con["cfn"][D], con["cof"][D], con["deh"][D], con["mco"][D],
                                  con["plp"][D], con["sec"][D], con["spa"][D], con["wcl"][D], con["plh"][D],
                                  con["ea"][D], con["spk"][D], con["phn"][D], con["tab"][D], con["kit"][D])

    # non-electric appliances: gas, propane, distillate
    for D in range(1, NUM_D + 1):
        for F in (1, 2, 3):
            s["aplcon"][I, F, D] = 0.0
            for B in range(1, MNUMBLDG + 1):
                s["aplcon"][I, F, D] = f32(s["aplcon"][I, F, D] + f32(s["appuec"][D, F, B] * s["appeqp"][RY, B, D, F]))

    # secondary space heating
    for D in range(1, NUM_D + 1):
        for F in range(1, int(s["nshtrfl"]) + 1):
            s["shtcon"][I, F, D] = 0.0
            for B in range(1, MNUMBLDG + 1):
                s["sheqcn"][I, F, B, D] = f32(s["shteqp"][RY, B, D, F] * s["shtuec"][D, F, B])
                s["shtcon"][I, F, D] = f32(s["shtcon"][I, F, D] + f32(s["shteqp"][RY, B, D, F] * s["shtuec"][D, F, B]))

    # national slots start at zero
    s["qbmrs"][NATIONAL, I] = 0.0
    s["qstrs"][NATIONAL, I] = 0.0
    s["qpvrs"][NATIONAL, I] = 0.0
    s["qgers"][NATIONAL, I] = 0.0

    RS, HTR, H2O, APL, COOL = s["rsflcn"], s["htrcon"], s["h2ocon"], s["aplcon"], s["coolcn"]
    CK, DRY, SHT = s["ckcon"], s["drycon"], s["shtcon"]
    for D in range(1, NUM_D + 1):
        RS[I, 1, D] = _sum32(HTR[I, 1, D], H2O[I, 1, D], APL[I, 1, D], COOL[I, 2, D],
                             CK[I, 1, D], DRY[I, 1, D], SHT[I, 1, D]) / mil
        s["qngrs"][D, I] = RS[I, 1, D]
        s["qgfrs"][D, I] = f32(RS[I, 1, D] * f32(1.0))
        s["qgirs"][D, I] = f32(RS[I, 1, D] * f32(0.0))

        RS[I, 2, D] = _sum32(HTR[I, 2, D], COOL[I, 1, D], H2O[I, 2, D], s["refcon"][I, D],
                             s["frzcon"][I, D], s["ltcon"][I, D], s["apcon"][I, D], CK[I, 3, D],
                             DRY[I, 2, D], SHT[I, 2, D], s["pcrcon"][I, D], s["tvrcon"][I, D],
                             s["cswcon"][I, D], s["dswcon"][I, D], s["fancon"][I, D]) / mil
        s["qelrs"][D, I] = f32(RS[I, 2, D] + s["trq_elec"][1, D, I])

        RS[I, 3, D] = _sum32(HTR[I, 3, D], H2O[I, 3, D], APL[I, 3, D], SHT[I, 3, D]) / mil
        s["qdsrs"][D, I] = RS[I, 3, D]

        RS[I, 4, D] = _sum32(HTR[I, 4, D], H2O[I, 4, D], APL[I, 2, D], CK[I, 2, D], SHT[I, 4, D]) / mil
        s["qlgrs"][D, I] = RS[I, 4, D]
        s["qprrs"][D, I] = s["qlgrs"][D, I]

        RS[I, 5, D] = _sum32(HTR[I, 5, D], SHT[I, 5, D]) / mil
        s["qbmrs"][D, I] = RS[I, 5, D]

        s["slcon"][I, 10] = f32(s["slcon"][I, 10] + H2O[I, 5, D])  # not reset first, as in EIA
        s["qstrs"][D, I] = f32(H2O[I, 5, D] / mil)
        s["qstrs"][NATIONAL, I] = f32(s["qstrs"][NATIONAL, I] + f32(H2O[I, 5, D] / mil))
        s["qpvrs"][D, I] = s["qpvrs"][NATIONAL, I]

        s["qksrs"][D, I] = 0.0
        s["qgers"][D, I] = 0.0

    # EIA calls division 10 the US here
    TRQ = s["trq_elec"]
    for F in range(1, MNUMFUEL + 1):
        RS[I, F, MNUMCR - 1] = 0.0
        TRQ[1, MNUMCR, I] = 0.0
        for D in range(1, NUM_D + 1):
            RS[I, F, MNUMCR - 1] = f32(RS[I, F, MNUMCR - 1] + RS[I, F, D])
            TRQ[1, MNUMCR, I] = f32(TRQ[1, MNUMCR, I] + TRQ[1, D, I])

    s["qngrs"][NATIONAL, I] = RS[I, 1, MNUMCR - 1]
    s["qgfrs"][NATIONAL, I] = f32(RS[I, 1, MNUMCR - 1] * f32(1.0))
    s["qgirs"][NATIONAL, I] = f32(RS[I, 1, MNUMCR - 1] * f32(0.0))
    s["qelrs"][NATIONAL, I] = f32(RS[I, 2, MNUMCR - 1] + TRQ[1, MNUMCR, I])
    s["qdsrs"][NATIONAL, I] = RS[I, 3, MNUMCR - 1]
    s["qlgrs"][NATIONAL, I] = RS[I, 4, MNUMCR - 1]
    s["qprrs"][NATIONAL, I] = s["qlgrs"][NATIONAL, I]
    s["qbmrs"][NATIONAL, I] = RS[I, 5, MNUMCR - 1]
    s["qksrs"][NATIONAL, I] = 0.0
    s["qgers"][NATIONAL, I] = 0.0
