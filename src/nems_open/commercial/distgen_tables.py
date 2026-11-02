"""CDistGen input files: KCOGEN (historical cogeneration) and KGENTK (technology table).

Port of the first-call reads in CDISTGEN (comm.f). KGENTK describes each on-site
generation technology (rooftop solar PV, fuel cells, gas engines, turbines, wind, ...):
size limits, efficiency, cost by vintage, tax credits, RPS credit parameters, the roof and
wind niches by census division, and the Bass diffusion parameters that set how fast
buildings adopt each technology.

Names follow the Fortran so each read can be checked against comm.f.
"""

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from nems_open.commercial.inputs import CDM, HEADER_RECORDS

f32 = np.float32

NTEK = 11
MAX_NICHE = 5
NUM_DIV = 9
NUM_BLDG = 11
MNUMYR = 61
CM_FIRST_YR = 30
CM_COG_HST_YR = 35
NUM_COGEN_FUELS = 14  # CMnumMajFl + CMnumMinFl + CMnumRenew + CMnumOthrFl

_TOKEN = re.compile(r"""'([^']*)'|"([^"]*)"|([^\s,]+)""")


class Records:
    """Fortran list-directed reads over a text file, with quoted strings and logicals.

    Same record rules as `fortran_io.ListDirectedReader`: a read drops the rest of its last
    record and skips blank records; `skip(n)` is READ (u,'(//)') with n-1 slashes.
    """

    def __init__(self, path: Path, skip_records: int = 0):
        self.lines = Path(path).read_text(encoding="latin-1").splitlines()
        self.pos = skip_records

    def skip(self, n: int) -> None:
        self.pos += n

    def tokens(self, n: int):
        out = []
        while len(out) < n:
            if self.pos >= len(self.lines):
                raise EOFError
            line = self.lines[self.pos]
            self.pos += 1
            for m in _TOKEN.finditer(line):
                tok = m.group(1) if m.group(1) is not None else m.group(2) if m.group(2) is not None else m.group(3)
                if m.group(3) is not None and (tok.startswith("!") or tok == "/"):
                    break
                rep = re.fullmatch(r"(\d+)\*(.+)", tok) if m.group(3) is not None else None
                for _ in range(int(rep.group(1)) if rep else 1):  # list-directed repeat count, 32*0
                    out.append(rep.group(2) if rep else tok)
                    if len(out) == n:
                        break
                if len(out) == n:
                    break
        return out

    def floats(self, n: int):
        return [f32(float(t)) for t in self.tokens(n)]

    def ints(self, n: int):
        """Integers; EIA's compiler also takes a real like 1.000 for an integer."""
        return [int(round(float(t))) for t in self.tokens(n)]

    def logicals(self, n: int):
        return [t.upper().lstrip(".")[:1] == "T" for t in self.tokens(n)]


def read_kcogen(cdm_dir: Path = CDM) -> np.ndarray:
    """CMCogenEL (r, b, f, y): historical cogeneration electricity by fuel, in trillion Btu."""
    out = np.zeros((NUM_DIV + 1, NUM_BLDG + 1, NUM_COGEN_FUELS + 1, MNUMYR + 1), dtype=f32)
    rd = Records(Path(cdm_dir) / "kcogen.txt", HEADER_RECORDS)
    try:
        for iyr in range(CM_FIRST_YR, CM_COG_HST_YR + 1):
            for r in range(1, NUM_DIV + 1):
                for b in range(1, NUM_BLDG + 1):
                    vals = rd.floats(NUM_COGEN_FUELS)
                    for f in range(1, NUM_COGEN_FUELS + 1):
                        out[r, b, f, iyr] = f32(vals[f - 1] / f32(1000.0))
    except EOFError:
        pass
    return out


@dataclass
class DgTables:
    """Everything CDISTGEN reads from KGENTK. Arrays are 1-based (index 0 unused)."""
    NUMTECHS: int = 0
    NUMYEARS: int = 0
    NUMDIV: int = 0
    NUMBLDG: int = 0
    NVINT: int = 0
    iGenCapCostYr: int = 0
    GlobalLearn: bool = False
    XINXFY: int = 0
    XINXLY: int = 0
    XTAXRATE: np.float32 = f32(0)
    XDOWNPAYPCT: np.float32 = f32(0)
    XINTRATE: np.float32 = f32(0)
    XTERM: np.float32 = f32(0)
    XINFLATION: np.float32 = f32(0)
    xpctWindSuitable: np.float32 = f32(0.10)
    XOPERHOURS: np.ndarray = None
    xpctPVSuitable: np.ndarray = None
    XBeta: np.ndarray = None
    Xc0: np.ndarray = None
    XINX: np.ndarray = None
    XALPHA: np.ndarray = None
    XPENPARM: np.ndarray = None
    xkwMin: np.ndarray = None
    xkwmax: np.ndarray = None
    xScaleFac: np.ndarray = None
    ISKIP: np.ndarray = None
    iRPSStartYear: np.ndarray = None
    iRPSPhaseOutYear: np.ndarray = None
    iRPSGrandFatherYear: np.ndarray = None
    IFUELTYPE: np.ndarray = None
    AEQUIPNAME: np.ndarray = None
    IFIRSTYR: np.ndarray = None
    ILASTYR: np.ndarray = None
    XKW: np.ndarray = None
    XELEFF: np.ndarray = None
    XLOSSFAC: np.ndarray = None
    XDEGRAD: np.ndarray = None
    XEQLIFE: np.ndarray = None
    xtxlife: np.ndarray = None
    xdep: np.ndarray = None
    XWHRECOVERY: np.ndarray = None
    XINSTCOST: np.ndarray = None
    XCAPCOST: np.ndarray = None
    XMAINTCST: np.ndarray = None
    xIntervalCst: np.ndarray = None
    iIntervalYrs: np.ndarray = None
    XAVAIL: np.ndarray = None
    XTXCRPCT: np.ndarray = None
    xTXCrMaxPerKW: np.ndarray = None
    xTXCrMaxPerSys: np.ndarray = None
    ComTxCrPct_Div: np.ndarray = None     # (nv, idiv, nt)
    xRPS: np.ndarray = None               # (nt, y)
    iNumYrsatRPSBaseRate: np.ndarray = None
    iNumRPSCreditYrs: np.ndarray = None
    NumPVNiche: np.ndarray = None
    xSolarInsolation: np.ndarray = None   # (div, niche, rate)
    xSqftShare: np.ndarray = None
    xRateScalar: np.ndarray = None
    xRoofAreatoSqftRatio: np.ndarray = None  # (div, bld, niche, rate)
    xWindSpeed: np.ndarray = None
    xNGRateScalar: np.ndarray = None
    XBLDGSHARE: np.ndarray = None         # (nt, bld)
    cbecsFlspcCatShare: np.ndarray = None  # (bld, div, size)
    cbecsAVGSQFT: np.ndarray = None
    xelecavgkwh: np.ndarray = None
    XEXOGPEN: np.ndarray = None           # (y, div, nt)
    XA: np.ndarray = None                 # (nt, div)
    XB: np.ndarray = None
    XC: np.ndarray = None


def read_kgentk(cdm_dir: Path = CDM) -> DgTables:
    """Read kgentk.txt the way CDISTGEN does: same record skips, same order."""
    t = DgTables()
    z = lambda *shape, dtype=f32: np.zeros(shape, dtype=dtype)
    rd = Records(Path(cdm_dir) / "kgentk.txt", 20)           # READ (INFILE,'(19(/))')
    rd.logicals(3)                                           # print flags
    rd.skip(2)
    t.NUMTECHS, t.NUMYEARS, t.NUMDIV, t.NUMBLDG = rd.ints(4)
    rd.skip(2)
    t.NVINT, = rd.ints(1)
    rd.skip(2)
    t.iGenCapCostYr, = rd.ints(1)
    rd.skip(2)
    nt_, nv_ = t.NUMTECHS, t.NVINT
    t.XOPERHOURS = z(NTEK + 1)
    t.XOPERHOURS[1:nt_ + 1] = rd.floats(nt_)
    rd.skip(2)
    t.GlobalLearn, = rd.logicals(1)
    rd.skip(2)
    t.xpctPVSuitable = z(7)
    t.xpctPVSuitable[1:7] = rd.floats(6)
    rd.skip(2)
    t.XBeta, t.Xc0 = z(NTEK + 1), z(NTEK + 1)
    t.XBeta[1:nt_ + 1] = rd.floats(nt_)
    t.Xc0[1:nt_ + 1] = rd.floats(nt_)
    rd.skip(2)
    t.XINX = z(NUM_DIV + 1)
    t.XINX[1:t.NUMDIV + 1] = rd.floats(t.NUMDIV)
    t.XINXFY, t.XINXLY = rd.ints(2)
    rd.skip(2)
    t.XTAXRATE, t.XDOWNPAYPCT, t.XINTRATE, t.XTERM, t.XINFLATION = rd.floats(5)
    rd.skip(4)                                               # READ (INFILE,'(///)')

    shape2 = (NTEK + 1, MNUMYR + 1)
    for name in ("XKW", "XELEFF", "XLOSSFAC", "XDEGRAD", "XEQLIFE", "xtxlife", "xdep", "XWHRECOVERY",
                 "XINSTCOST", "XCAPCOST", "XMAINTCST", "xIntervalCst", "XAVAIL", "XTXCRPCT",
                 "xTXCrMaxPerKW", "xTXCrMaxPerSys", "xRPS"):
        setattr(t, name, z(*shape2))
    for name in ("IFIRSTYR", "ILASTYR", "iIntervalYrs", "iNumYrsatRPSBaseRate", "iNumRPSCreditYrs"):
        setattr(t, name, z(*shape2, dtype=np.int32))
    t.AEQUIPNAME = np.full(shape2, "", dtype="U10")
    t.ComTxCrPct_Div = z(MNUMYR + 1, NUM_BLDG + 1, NTEK + 1)  # (nv, idiv, nt); EIA's array runs over MNUMCR in idiv
    t.IFUELTYPE = z(NTEK + 1, dtype=np.int32)
    for name in ("XALPHA", "XPENPARM", "xkwMin", "xkwmax", "xScaleFac", "ISKIP"):
        setattr(t, name, z(NTEK + 1))
    for name in ("iRPSStartYear", "iRPSPhaseOutYear", "iRPSGrandFatherYear"):
        setattr(t, name, z(NTEK + 1, dtype=np.int32))

    for nt in range(1, nt_ + 1):
        tok = rd.tokens(9)  # one record: six reals and three years
        (t.XALPHA[nt], t.XPENPARM[nt], t.xkwMin[nt], t.xkwmax[nt], t.xScaleFac[nt], t.ISKIP[nt]) = (
            f32(float(v)) for v in tok[:6])
        t.iRPSStartYear[nt], t.iRPSPhaseOutYear[nt], t.iRPSGrandFatherYear[nt] = (
            int(round(float(v))) for v in tok[6:9])
        for nv in range(1, nv_ + 1):
            # name, fuel, first and last year, then 18 reals, nine division tax credit shares, and the RPS terms
            tok = rd.tokens(33)
            t.AEQUIPNAME[nt, nv] = tok[0][:10]
            t.IFUELTYPE[nt] = int(round(float(tok[1])))
            t.IFIRSTYR[nt, nv], t.ILASTYR[nt, nv] = int(round(float(tok[2]))), int(round(float(tok[3])))
            (t.XKW[nt, nv], t.XELEFF[nt, nv], t.XLOSSFAC[nt, nv], t.XDEGRAD[nt, nv], t.XEQLIFE[nt, nv],
             t.xtxlife[nt, nv], t.xdep[nt, nv], t.XWHRECOVERY[nt, nv], t.XINSTCOST[nt, nv], t.XCAPCOST[nt, nv],
             t.XMAINTCST[nt, nv], t.xIntervalCst[nt, nv]) = (f32(float(v)) for v in tok[4:16])
            t.iIntervalYrs[nt, nv] = int(round(float(tok[16])))
            t.XAVAIL[nt, nv], t.XTXCRPCT[nt, nv], t.xTXCrMaxPerKW[nt, nv], t.xTXCrMaxPerSys[nt, nv] = (
                f32(float(v)) for v in tok[17:21])
            for idiv in range(1, 10):
                t.ComTxCrPct_Div[nv, idiv, nt] = f32(float(tok[20 + idiv]))
            xtemp, itemp1, itemp2 = f32(float(tok[30])), int(round(float(tok[31]))), int(round(float(tok[32])))
            for iyr in range(int(t.IFIRSTYR[nt, nv]), int(t.ILASTYR[nt, nv]) + 1):
                t.xRPS[nt, iyr - 1989] = xtemp
                t.iNumYrsatRPSBaseRate[nt, iyr - 1989] = itemp1
                t.iNumRPSCreditYrs[nt, iyr - 1989] = itemp2
    rd.skip(3)                                               # READ (INFILE,'(//)')
    t.NumPVNiche = z(NUM_DIV + 1, dtype=np.int32)
    shape3 = (NUM_DIV + 1, MAX_NICHE + 1, 11)
    t.xSolarInsolation, t.xSqftShare, t.xRateScalar = z(*shape3), z(*shape3), z(*shape3)
    t.xWindSpeed, t.xNGRateScalar = z(*shape3), z(*shape3)
    t.xRoofAreatoSqftRatio = z(NUM_DIV + 1, NUM_BLDG + 1, MAX_NICHE + 1, 11)
    for _ in range(t.NUMDIV):
        idiv, nniche = rd.ints(2)
        t.NumPVNiche[idiv] = nniche
        for iniche in range(1, nniche + 1):
            for irate in range(1, 11):
                tok = rd.floats(16)
                t.xSolarInsolation[idiv, iniche, irate] = tok[0]
                t.xSqftShare[idiv, iniche, irate] = tok[1]
                t.xRateScalar[idiv, iniche, irate] = tok[2]
                for ibld in range(1, 12):
                    t.xRoofAreatoSqftRatio[idiv, ibld, iniche, irate] = tok[2 + ibld]
                t.xWindSpeed[idiv, iniche, irate] = tok[14]
                t.xNGRateScalar[idiv, iniche, irate] = tok[15]
    rd.skip(2)
    t.XBLDGSHARE = z(NTEK + 1, NUM_BLDG + 1)
    for ibld in range(1, t.NUMBLDG + 1):
        vals = rd.floats(t.NUMTECHS)
        for nt in range(1, t.NUMTECHS + 1):
            t.XBLDGSHARE[nt, ibld] = vals[nt - 1]
    # Three tables of 594 values each: building type fastest, then size class, then division.
    for name in ("cbecsFlspcCatShare", "cbecsAVGSQFT", "xelecavgkwh"):
        rd.skip(2)
        arr = z(NUM_BLDG + 1, NUM_DIV + 1, 7)
        vals = rd.floats(t.NUMBLDG * 6 * t.NUMDIV)
        k = 0
        for idiv in range(1, t.NUMDIV + 1):
            for isize in range(1, 7):
                for ibld in range(1, t.NUMBLDG + 1):
                    arr[ibld, idiv, isize] = vals[k]
                    k += 1
        setattr(t, name, arr)
    rd.skip(2)
    t.XEXOGPEN = z(MNUMYR + 1, NUM_BLDG + 1, NTEK + 1)
    for nt in range(1, t.NUMTECHS + 1):
        for idiv in range(1, t.NUMDIV + 1):
            vals = rd.floats(t.NUMYEARS - CM_FIRST_YR + 1)
            t.XEXOGPEN[CM_FIRST_YR:t.NUMYEARS + 1, idiv, nt] = vals
    rd.skip(2)
    t.XA, t.XB, t.XC = z(NTEK + 1, NUM_DIV + 1), z(NTEK + 1, NUM_DIV + 1), z(NTEK + 1, NUM_DIV + 1)
    for nt in range(1, t.NUMTECHS + 1):
        for idiv in range(1, t.NUMDIV + 1):
            t.XA[nt, idiv], t.XB[nt, idiv], t.XC[nt, idiv] = rd.floats(3)
    return t
