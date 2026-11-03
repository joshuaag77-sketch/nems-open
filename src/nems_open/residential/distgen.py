"""Residential distributed generation: RDISTGEN (resd.f), the yearly call.

Rooftop solar PV, natural gas fuel cells and small wind (battery storage is on the
technology menu but RDISTGEN skips it). Each year, for each census division, PV
penetration comes from one of two models:
  * the niche / payback model (30-year cash flow per insolation niche and electricity
    rate level, then a payback-to-penetration curve), used for fuel cells and wind
    always, and for PV before EstYear; and
  * the ZIP-code hurdle model (logit times negative binomial), used for PV from
    EstYear on, with a lag structure carried from year to year and a calibration to
    exogenous PV capacity in EstYear and the year after.
The results feed Units, Cap, Trills, TrillsOwnUse, GasUsage, HWBTU, Invest and the
cogeneration link arrays CGRESGEN, CGRESQ, CGRESCAP, plus the learning shipments.

Writes to RDM_DGENOUT.txt and unit 9 are skipped, and so are the local technical
potential accumulators (SolarPVTechPotentialMW, WindAvailHH, QRSDGSG, ...), which
nothing reads.

What the dumps do not hold, and how it is handled (brief, rule 7):
  * The constant input tables RDISTGEN reads on its first call (RGENTK.txt,
    RSGENTK.txt) are read here from the same files, by load_inputs().
  * ZIP model state carried between years (Income_L, Households_L, ElecRate_L,
    PopDensity_L, Lag1Installs, Lag2Installs, ProjectedInstalls, CumUnits,
    CumUnits_L) is read from s under those lowercase names when present (the oracle's
    "dg_pre" dump, taken as the final iteration starts) and written back at the end.
    Without them the state starts from the files, as after EIA's first call, and
    then carries forward from year to year inside s["_dg"].
  * PELRSOUT comes from s["pelrsout"], Fortran bounds (1:11, 1:61, 1:11); only end
    use 2 (space cooling) is read here.
  * xSizeMax, a REAL*8 local used before it is set in the niche code: zero on the very first
    call (2020, before any niche pass), 10 after that (static storage).
  * xPVGenAdded / xWindGenAdded history is used only in a credit ratio that is
    exactly 1.0 for RSGENTK's RPS settings, so unknown history years are zero.

The oracle was built with -fno-automatic -finit-local-zero, so every local is static
and starts at zero; leftover values below are kept for that reason.
"""

import math
import re
from pathlib import Path

import numpy as np

from nems_open.paths import INPUT
from nems_open.residential.common import BASEYR, RECSYEAR, powi
from nems_open.residential.helpers import rlearncost

F = np.float32
D = np.float64

NTEK = 4
MNUMCGF = 13
MNUMYR = 61

# REAL*4 literals used below
C003412 = F(0.003412)
C1000 = F(1000.0)
C100 = F(100.0)
C1 = F(1.0)
C0 = F(0.0)
E12 = F(1.0e12)  # 10.**12 folded at single precision
E6 = F(1.0e6)


def _powf(x, y):
    """REAL**REAL in single precision (glibc powf is almost always the correctly
    rounded result, which is what rounding a double pow gives)."""
    return F(math.pow(float(x), float(y)))


def _exp(x):
    try:
        return D(math.exp(float(x)))
    except OverflowError:
        return D(math.inf)


def nint(x) -> int:
    """Fortran NINT: round half away from zero."""
    x = float(x)
    return int(math.floor(x + 0.5)) if x >= 0.0 else -int(math.floor(-x + 0.5))


# ---------------------------------------------------------------------------
# Input files (read once, on the 2020 call in EIA's code)
# ---------------------------------------------------------------------------

_TOKEN = re.compile(r"'[^']*'|\"[^\"]*\"|[^\s,]+")


def _tokens(line: str) -> list:
    out = []
    for t in _TOKEN.findall(line):
        m = re.match(r"^(\d+)\*(.*)$", t)  # list-directed repeat count, 31*0
        if m:
            out += [m.group(2)] * int(m.group(1))
        else:
            out.append(t)
    return out


class _Records:
    """List-directed reads from a text file: values may span records, and the rest of
    the last record read is dropped, like READ(unit,*)."""

    def __init__(self, lines):
        self.lines, self.i = lines, 0

    def skip(self, n: int) -> None:  # READ(unit,'(n(/))') consumes n+1 records
        self.i += n + 1

    def read(self, n: int) -> list:
        out = []
        while len(out) < n:
            out += _tokens(self.lines[self.i])
            self.i += 1
        return out[:n]


def _logical(tok: str) -> bool:
    return tok.strip(".").upper()[0] == "T"


class Inputs:
    """Everything RDISTGEN reads from RGENTK.txt and RSGENTK.txt. Arrays are 1-based
    (index 0 unused) so subscripts match the Fortran."""


_INPUTS = {}


def load_inputs(rdm_dir=None) -> Inputs:
    rdm = Path(rdm_dir) if rdm_dir else INPUT / "rdm"
    key = str(rdm)
    if key not in _INPUTS:
        _INPUTS[key] = _read_inputs(rdm)
    return _INPUTS[key]


def _read_inputs(rdm: Path) -> Inputs:
    p = Inputs()

    # --- RGENTK.txt: ZIP code hurdle model ---
    r = _Records((rdm / "rgentk.txt").read_text(encoding="latin-1").split("\n"))
    r.skip(19)
    p.UseZipModel = _logical(r.read(1)[0])
    p.PVzipcalib = _logical(r.read(1)[0])
    p.EstYear = int(r.read(1)[0])
    r.skip(2)
    names = ["CINT", "CHH", "CPD", "CINC", "CINS", "CER", "CCDD", "CPMT", "CIR", "CLAG1", "CLAG2", "CPVP"]
    coef = {n: np.zeros((3, 4), dtype=F) for n in names}  # [model 1:2, set 1:3] (index 0 unused)
    for i in range(1, 4):
        for n in names:
            a, b = r.read(2)
            coef[n][1, i], coef[n][2, i] = F(float(a)), F(float(b))
        r.i += 1  # READ(INFILE,*) of the model title takes one record
    for n in names:
        setattr(p, n, coef[n])
    nz = int(r.read(1)[0])
    r.skip(1)  # READ(INFILE,'((/))'): the blank line and the header
    rows = [ln.split(",") for ln in r.lines[r.i:r.i + nz]]
    p.NumZIPs = nz
    col = lambda k: [row[k].strip() for row in rows]  # noqa: E731
    p.CenDiv = np.array(col(2), dtype=np.int64)
    p.Income = np.array(col(3), dtype=np.float64).astype(F)
    p.Households = np.array(col(4), dtype=np.float64).astype(F)
    p.PopDensity = np.array(col(5), dtype=np.float64).astype(F)
    p.Insol = np.array(col(6), dtype=np.float64).astype(F)
    p.ElecRate = np.array(col(7), dtype=np.float64).astype(F)
    p.LagCDD = np.array(col(8), dtype=np.float64).astype(F)
    p.IntRate = F(float(rows[-1][9]))  # scalars end up holding the last record's values
    p.PVPrice = F(float(rows[-1][10]))
    p.MonthlyPayment = F(float(rows[-1][11]))
    p.InputPVPrice = p.PVPrice
    p.Lag1Installs = np.array(col(12), dtype=np.float64)
    p.Lag2Installs = np.array(col(13), dtype=np.float64)
    p.PureHurdle = np.array(col(14), dtype=np.int64)
    p.RuralZip = np.array(col(15), dtype=np.int64)

    # --- RSGENTK.txt: technology menu and niches ---
    r = _Records((rdm / "rsgentk.txt").read_text(encoding="latin-1").split("\n"))
    r.skip(19)
    r.read(2)  # LPRINT, LPRINT2
    r.skip(1)
    p.NumTechs, p.NumYears, p.NumDiv = (int(t) for t in r.read(3))
    r.skip(1)
    p.iGenCapCostYr = int(r.read(1)[0])
    r.skip(1)
    a, b = r.read(2)
    p.xAlpha, p.xPenParm = D(float(a)), D(float(b))
    r.skip(1)
    p.xOperHours = np.zeros(NTEK + 1, dtype=F)
    for nt, t in enumerate(r.read(p.NumTechs), 1):
        p.xOperHours[nt] = F(float(t))
    r.skip(1)
    p.GlobalLearn = _logical(r.read(1)[0])
    r.skip(1)
    p.xBeta = np.zeros(NTEK + 1, dtype=F)
    p.xC0 = np.zeros(NTEK + 1, dtype=F)
    for nt, t in enumerate(r.read(p.NumTechs), 1):
        p.xBeta[nt] = F(float(t))
    for nt, t in enumerate(r.read(p.NumTechs), 1):
        p.xC0[nt] = F(float(t))
    r.skip(1)
    p.iRPSStartYear, p.iRPSPhaseOutYear, p.iRPSGrandFatherYear = (int(t) for t in r.read(3))
    r.skip(1)
    p.XINX = np.zeros(p.NumDiv + 1, dtype=F)
    for i, t in enumerate(r.read(p.NumDiv), 1):
        p.XINX[i] = F(float(t))
    p.xInxFY, p.xInxLY = (int(t) for t in r.read(2))
    r.skip(1)
    t = r.read(4)
    p.XTAXRATE, p.XDOWNPAYPCT, p.XTERM, p.XINFLATION = (F(float(x)) for x in t)
    r.skip(2)
    p.NVINT = int(r.read(1)[0])

    nv_n = p.NVINT + 1
    p.aEquipName = [[""] * nv_n for _ in range(NTEK + 1)]
    p.iFirstYr = np.zeros((NTEK + 1, nv_n), dtype=np.int64)
    p.iLastYr = np.zeros((NTEK + 1, nv_n), dtype=np.int64)
    p.iIntervalYrs = np.zeros((NTEK + 1, nv_n), dtype=np.int64)
    fl = ["xKW", "xBESSkWh", "xElEff", "xLossFac", "xDegrad", "xEqLife", "xWhRecovery", "xInstCost", "xCapCost",
          "xMaintCst", "xIntervalCst", "xAvail", "xTxCrPct", "xTXCrMaxPerKW", "xTXCrMaxPerSys"]
    for n in fl:
        setattr(p, n, np.zeros((NTEK + 1, nv_n), dtype=F))
    p.xTxCrPct_Div = np.zeros((nv_n, 10, NTEK + 1), dtype=F)  # (nv, iDiv, nt)
    p.xRPS = np.zeros((NTEK + 1, MNUMYR + 1), dtype=F)
    p.iNumYrsatRPSBaseRate = np.zeros((NTEK + 1, MNUMYR + 1), dtype=np.int64)
    p.iNumRPSCreditYrs = np.zeros((NTEK + 1, MNUMYR + 1), dtype=np.int64)
    for nt in range(1, p.NumTechs + 1):
        for nv in range(1, p.NVINT + 1):
            t = r.read(32)
            p.aEquipName[nt][nv] = t[0].strip("'\"").strip()
            p.iFirstYr[nt, nv], p.iLastYr[nt, nv] = int(t[2]), int(t[3])
            for k, n in enumerate(["xKW", "xBESSkWh", "xElEff", "xLossFac", "xDegrad", "xEqLife", "xWhRecovery",
                                   "xInstCost", "xCapCost", "xMaintCst", "xIntervalCst"]):
                getattr(p, n)[nt, nv] = F(float(t[4 + k]))
            p.iIntervalYrs[nt, nv] = int(float(t[15]))
            for k, n in enumerate(["xAvail", "xTxCrPct", "xTXCrMaxPerKW", "xTXCrMaxPerSys"]):
                getattr(p, n)[nt, nv] = F(float(t[16 + k]))
            for d in range(1, 10):
                p.xTxCrPct_Div[nv, d, nt] = F(float(t[19 + d]))
            xtemp, it1, it2 = D(float(t[29])), int(float(t[30])), int(float(t[31]))
            for iyr in range(int(p.iFirstYr[nt, nv]), int(p.iLastYr[nt, nv]) + 1):
                p.xRPS[nt, iyr - BASEYR + 1] = F(xtemp)
                p.iNumYrsatRPSBaseRate[nt, iyr - BASEYR + 1] = it1
                p.iNumRPSCreditYrs[nt, iyr - BASEYR + 1] = it2

    # niches: [iDiv, iNiche, iRateLevel]
    r.skip(3)
    shp = (10, 27, 4)
    for n in ["xSolarInsolation", "xHHShare", "xRateScalar", "xAvgKWH", "xRoofAreaPerHH", "xWindSpeed", "xRuralPctHH"]:
        setattr(p, n, np.zeros(shp, dtype=F))
    p.NumPVNiche = np.zeros(10, dtype=np.int64)
    for _ in range(p.NumDiv):
        d, nn = (int(t) for t in r.read(2))
        p.NumPVNiche[d] = nn
        for ni in range(1, nn + 1):
            for lv in range(1, 4):
                t = r.read(7)
                for k, n in enumerate(["xSolarInsolation", "xHHShare", "xRateScalar", "xAvgKWH", "xRoofAreaPerHH",
                                       "xWindSpeed", "xRuralPctHH"]):
                    getattr(p, n)[d, ni, lv] = F(float(t[k]))

    r.skip(1)
    p.iExogHistYr = np.zeros(NTEK + 1, dtype=np.int64)
    for nt, t in enumerate(r.read(p.NumTechs), 1):
        p.iExogHistYr[nt] = int(t)
    r.skip(1)
    p.xExogPen = np.zeros((MNUMYR + 1, 10, NTEK + 1), dtype=np.float64)  # (year index, iDiv, nt), REAL*8
    for nt in range(1, p.NumTechs + 1):
        for d in range(1, p.NumDiv + 1):
            n = p.NumYears - (RECSYEAR - BASEYR + 1) + 1
            for k, t in enumerate(r.read(n)):
                p.xExogPen[RECSYEAR - BASEYR + 1 + k, d, nt] = float(t)
    r.skip(1)
    p.DGrateBlend = _logical(r.read(1)[0])
    r.skip(1)
    p.DGrateYr = int(r.read(1)[0])
    r.skip(2)
    p.DGmargWt = np.zeros(10, dtype=F)
    p.DGretWt = np.zeros(10, dtype=F)
    for d in range(1, p.NumDiv + 1):
        a, b = r.read(2)
        p.DGmargWt[d], p.DGretWt[d] = F(float(a)), F(float(b))
    return p


# ---------------------------------------------------------------------------
# State carried between calls (static locals in EIA's build)
# ---------------------------------------------------------------------------


class _State:
    def __init__(self, inp: Inputs):
        n = inp.NumZIPs
        self.Income, self.Income_L = inp.Income.copy(), inp.Income.copy()
        self.Households, self.Households_L = inp.Households.copy(), inp.Households.astype(D)
        self.PopDensity, self.PopDensity_L = inp.PopDensity.copy(), inp.PopDensity.copy()
        self.ElecRate, self.ElecRate_L = inp.ElecRate.copy(), inp.ElecRate.copy()
        self.Lag1Installs, self.Lag2Installs = inp.Lag1Installs.copy(), inp.Lag2Installs.copy()
        self.ProjectedInstalls = np.zeros(n)
        self.CumUnits, self.CumUnits_L = np.zeros(n), np.zeros(n)
        self.IntRate, self.PVPrice, self.MonthlyPayment = inp.IntRate, inp.PVPrice, inp.MonthlyPayment
        self.factor4 = D(0.0)  # set only after EstYear; zero from -finit-local-zero before
        self.factor5 = D(0.0)
        self.ExogPVMistie = np.zeros((MNUMYR + 1, 12), dtype=D)
        self.xPVGenAdded = np.zeros((12, MNUMYR + 2), dtype=F)
        self.xWindGenAdded = np.zeros((12, MNUMYR + 2), dtype=F)
        self.xInxDecay = np.ones((12, MNUMYR + 2), dtype=F)
        self.xSizeMax = D(10.0)
        # leftovers of the niche code that persist between passes
        self.XVALESAVEBASEnoRPS = C0
        self.XVALESAVEBASEadjRPS = C0
        self.xTaxCreditPct = C0
        self.zip_by_div = {d: np.nonzero(inp.CenDiv == d)[0] for d in range(1, 10)}


_CARRIED = {"income_l": "Income_L", "households_l": "Households_L", "elecrate_l": "ElecRate_L",
            "popdensity_l": "PopDensity_L", "lag1installs": "Lag1Installs", "lag2installs": "Lag2Installs",
            "projectedinstalls": "ProjectedInstalls", "cumunits": "CumUnits", "cumunits_l": "CumUnits_L"}


def _state(s: dict, inp: Inputs) -> _State:
    z = s.get("_dg")
    if z is None:
        z = s["_dg"] = _State(inp)
        if int(s["curcalyr"]) == RECSYEAR and int(s["curitr"]) == 1:
            z.xSizeMax = D(0.0)  # the very first call: zero (-finit-local-zero) until a niche pass sets 10
        if "income_l" in s and s["income_l"].a.any():  # carried ZIP state as the oracle dumps it ("dg_pre");
            # zeros mean a state built from the files (initial_state), which starts from the inputs
            for nm, attr in _CARRIED.items():
                setattr(z, attr, s[nm].a.copy())
    return z


# ---------------------------------------------------------------------------
# Pieces shared by the passes
# ---------------------------------------------------------------------------


def _inx_decay(inp, z, Y: int, y1: int) -> None:
    """Interconnection limit by division for this year."""
    for d in range(1, inp.NumDiv + 1):
        if Y == inp.xInxFY:
            z.xInxDecay[d, y1] = inp.XINX[d]
        else:
            ratio = F(F(Y - inp.xInxFY) / F(inp.xInxLY - inp.xInxFY))
            v = F(inp.XINX[d] + F(F(C1 - inp.XINX[d]) * ratio))
            z.xInxDecay[d, y1] = min(C1, v)


def _adj_cost(s, inp, nt: int, nv: int, y1: int):
    """Learning-adjusted capital cost (xAdjCost) for the technology vintage."""
    name = inp.aEquipName[nt][nv]
    cap = inp.xCapCost[nt, nv]
    if name == "Fuel_Cell":
        cumship = F(s["cfuelcell_mw"][y1 - 1] + s["rfuelcell_mw"][y1 - 1])
    elif name == "Solar_PV":
        cumship = F(s["cpv_mw"][y1 - 1] + s["rpv_mw"][y1 - 1])
        if inp.GlobalLearn:
            cumship = F(cumship + s["upv_mw"][y1 - 1])
    elif name == "Wind":
        cumship = F(s["cwind_mw"][y1 - 1] + s["rwind_mw"][y1 - 1])
    else:
        return cap
    return F(rlearncost(cap, inp.xBeta[nt], inp.xC0[nt], cumship))


def _hh_total(s, Y: int, d: int):
    """EH+NH summed over the three building types, in the Fortran's order (REAL*4)."""
    eh, nh = s["eh"], s["nh"]
    t = F(eh[Y, 1, d] + nh[Y, 1, d])
    t = F(t + eh[Y, 2, d])
    t = F(t + nh[Y, 2, d])
    t = F(t + eh[Y, 3, d])
    return F(t + nh[Y, 3, d])


def _zip_lag_update(z: _State) -> None:
    """First iteration after EstYear: roll this year's inputs and installs into the lags."""
    z.Income_L = z.Income.copy()
    z.Households_L = z.Households.astype(D)
    z.ElecRate_L = z.ElecRate.copy()
    z.PopDensity_L = z.PopDensity.copy()
    z.Lag2Installs = z.Lag1Installs.copy()
    z.Lag1Installs = z.ProjectedInstalls.copy()
    z.CumUnits_L = z.CumUnits.copy()


def _pv_zip_division(s, inp, z, d: int, Y: int, nv: int, xAdjCost, xTaxCreditPct):
    """Lines 16171-16367: the ZIP code hurdle model for one census division and year.
    Updates the carried ZIP arrays and returns (xUnits, xTrills, xTrillsOwnUse,
    xAnnualKWh of the division's last ZIP, xCalcKW)."""
    nt = 1
    y1 = Y - BASEYR + 1
    Est = inp.EstYear
    xElEff, xKW, xLoss = inp.xElEff[nt, nv], inp.xKW[nt, nv], inp.xLossFac[nt, nv]
    xSqftperKW = F(F(F(77.0) * F(0.14)) / xElEff)

    if Y > Est:
        z.IntRate = F(s["mc_rmmtg30con"][y1] / C100)
        # PVPrice: installed cost net of tax credits, scaled to the ZIP model's cost level
        k = Est - RECSYEAR + 1
        num = F(F(F(xAdjCost + inp.xInstCost[nt, nv]) * F(F(C1 - xTaxCreditPct) - inp.xTxCrPct_Div[nv, d, nt]))
                * inp.InputPVPrice)
        den = F(F(inp.xCapCost[1, k] / C1000) * F(C1 - inp.xTxCrPct[1, k]))
        z.PVPrice = F(num / den)
        ir12 = F(z.IntRate / F(12.0))
        z.MonthlyPayment = F(F(z.PVPrice * ir12) / F(C1 - _powf(F(C1 + ir12), F(-360.0))))
    IntRate, PVPrice, MonthlyPayment = z.IntRate, z.PVPrice, z.MonthlyPayment

    idx = z.zip_by_div[d]
    jj = np.where(inp.RuralZip[idx] == 1, 3, inp.PureHurdle[idx] + 1)  # model set 1..3

    # ZIP-level inputs (the lag roll-over has already run, for all divisions at once)
    if Y > Est:
        ypdr = s["mc_ypdr"]
        tot_c, tot_p = _hh_total(s, Y, d), _hh_total(s, Y - 1, d)
        ratio_hh = F(tot_c / tot_p)
        # Income: Income_L * (YPDR ratio) / (household ratio); CenDiv(i) is d for these ZIPs
        yr = F(ypdr[d, y1] / ypdr[d, y1 - 1])
        z.Income[idx] = (z.Income_L[idx] * yr) / ratio_hh
        z.Households[idx] = ((z.Households_L[idx] * D(tot_c)) / D(tot_p)).astype(F)
        np_ = s["mc_np65a"]
        z.PopDensity[idx] = (z.PopDensity_L[idx] * np_[y1]) / np_[y1 - 1]
        z.ElecRate[idx] = _elec_rate(s, inp, z, d, Y, y1, z.ElecRate_L[idx])

    if Y > Est:
        n = Y - Est
        pw = lambda e: F(C1 / _powf(F(n), F(e)))  # noqa: E731  1/(NumYearsPV**e), single precision
        z.factor4 = D(pw(0.090))
        z.factor5 = D(pw(0.12))
    factor = z.factor4 if inp.xTxCrPct[1, Y - RECSYEAR + 1] > 0.0 else z.factor5

    xCalcKW = D(xKW)
    sol = idx  # shorthand
    x = D(inp.Insol[sol])
    x = D(F(-1.0533)) + D(F(1.4325)) * x - D(F(0.0652)) * (x * x)
    xAnn = (D(xElEff) * x * D(365.25) / D(F(10.8)) * D(xSqftperKW) * xCalcKW * D(xLoss)).astype(F)

    def coef(name, k):
        return getattr(inp, name)[k, jj]

    def model(k):
        # left to right: REAL*4 terms stay single until the first REAL*8 term joins
        t = F(coef("CINT", k) + F(coef("CHH", k) * z.Households[sol]))
        t = F(t + F(coef("CPD", k) * z.PopDensity[sol]))
        t = t.astype(D) + D(factor) * D(coef("CINC", k)) * D(z.Income[sol])
        t = t + D(factor) * D(coef("CER", k)) * D(z.ElecRate[sol])
        t = t + D(F(coef("CCDD", k) * inp.LagCDD[sol]))
        t = t + D(F(coef("CPMT", k) * MonthlyPayment))
        t = t + D(F(coef("CIR", k) * IntRate))
        t = t + D(factor) * D(coef("CLAG1", k)) * z.Lag1Installs[sol]
        t = t + D(factor) * D(coef("CLAG2", k)) * z.Lag2Installs[sol]
        t = t + D(F(coef("CPVP", k) * PVPrice))
        t = t + D(F(coef("CINS", k) * inp.Insol[sol]))
        return t

    xLogit = model(1)
    xNegBinom = model(2)

    with np.errstate(over="ignore", invalid="ignore"):
        ex = np.exp(np.minimum(xLogit, 700.0))
        p = np.where(xLogit >= 18.0, 1.0, ex / (1.0 + ex))
        p = np.where(p < 0.25, 0.0, p)  # enforce the hurdle
        e50 = D(F(math.exp(50.0)))  # exp(50.) at single precision
        # REAL(xLogit * exp(.)) goes through single precision
        xTemp = np.where(xNegBinom >= 50.0, (p * e50).astype(F).astype(D),
                         (p * np.exp(np.minimum(xNegBinom, 700.0))).astype(F).astype(D))
    if Y > Est:
        xTemp = xTemp * D(z.xInxDecay[d, y1])
    xTemp = np.where(np.isnan(xTemp), 0.0, xTemp)

    HH = D(z.Households[sol])
    CL = z.CumUnits_L[sol]
    capd = (CL + xTemp) / HH >= D(F(0.80))
    xt = D(F(F(0.80) * z.Households[sol])) - CL
    xt = np.where(xt <= 0, 1.0, xt)
    xTemp = np.where(capd, xt, xTemp)
    near = CL >= D(F(0.78)) * z.Households_L[sol]
    cum_near = D(F(F(0.8) * z.Households[sol]))
    xt2 = cum_near - CL
    xt2 = np.where(xt2 <= 0, 1.0, xt2)
    z.ProjectedInstalls[sol] = np.where(near, HH, xTemp)
    z.CumUnits[sol] = np.where(near, cum_near, CL + xTemp)
    xTemp = np.where(near, xt2, xTemp)

    # sequential sums, as the Fortran adds ZIP by ZIP
    xElecAvgUEC = F(F(F(s["rsflcn"][y1, 2, d] * E12) / F(3412.0)) / _hh_total(s, Y, d))
    own_pc = np.where(xAnn > xElecAvgUEC, D(xElecAvgUEC), D(xAnn))
    xUnits = 0.0
    xTrills = 0.0
    xTrillsOwnUse = 0.0
    k3412, e12 = D(F(3412.0)), D(E12)
    gen = (xTemp * D(xAnn)) * k3412 / e12
    own = (xTemp * own_pc) * k3412 / e12
    for t, g, o in zip(xTemp.tolist(), gen.tolist(), own.tolist()):
        xUnits += t
        xTrills += g
        xTrillsOwnUse += o
        if xTrillsOwnUse > xTrills:
            xTrillsOwnUse = xTrills
        if xTrillsOwnUse < 0.0:
            xTrillsOwnUse = 0.0
    return D(xUnits), D(xTrills), D(xTrillsOwnUse), xAnn[-1], xCalcKW


def _elec_rate(s, inp, z, d, Y, y1, rate_L):
    """ElecRate(i) = ElecRate_L(i) * this year's rate basis / last year's. EIA indexes
    the retail price with CenDiv(iDiv), the division of ZIP number iDiv (a slip in the
    source, kept)."""
    cd = int(inp.CenDiv[d - 1])
    pel = s["pelrsout"]
    rps, eprps = inp.xRPS, s["eprpspr"]

    def retail(div, yy):  # PELRSOUT*.003412 + xRPS*EPRPSPR/1000.
        return F(F(pel[div, yy, 2] * C003412) + F(F(rps[1, yy] * eprps[yy]) / C1000))

    def blend(yy):
        mix = F(F(s["pelme"][d, yy] * inp.DGmargWt[d]) + F(pel[d, yy, 2] * inp.DGretWt[d]))
        return F(F(mix * C003412) + F(F(rps[1, yy] * eprps[yy]) / C1000))

    if inp.DGrateBlend:
        if Y < inp.DGrateYr:
            num, den = retail(cd, y1), retail(cd, y1 - 1)
        elif Y == inp.DGrateYr:
            num, den = blend(y1), retail(cd, y1 - 1)
        else:
            num, den = blend(y1), blend(y1 - 1)
    else:
        num, den = retail(cd, y1), retail(cd, y1 - 1)
    return F(F(rate_L * num) / den)


# ---------------------------------------------------------------------------
# The routine
# ---------------------------------------------------------------------------


def rdistgen(s: dict) -> None:
    """RDISTGEN. s holds the shared arrays (lowercase Fortran names) and "pelrsout"."""
    Y = int(s["curcalyr"])
    if Y < RECSYEAR:
        return
    itr = int(s["curitr"])
    inp = load_inputs()
    z = _state(s, inp)
    y1 = Y - BASEYR + 1  # iCurIYr
    ND = inp.NumDiv
    NumTechs = inp.NumTechs
    Est = inp.EstYear

    if Y == RECSYEAR and itr == 1:
        # First call: initialize the output arrays (the file reads are load_inputs; RSGENTK's
        # capital-cost dollar year lands in COMMON)
        if "igencapcostyr" in s:
            s["igencapcostyr"] = type(s["igencapcostyr"])(inp.iGenCapCostYr)
        for d in range(1, ND + 1):
            s["cgcpvres"][d, y1] = 1.0
            s["cgcwnres"][d, y1] = 1.0
        for nm in ("units", "cap", "trills", "hwbtu", "gasusage", "trillsownuse"):
            s[nm].a[:inp.NumYears, :ND, :NumTechs] = 0.0

    # Accumulators reset for repeated NEMS iterations
    for d in range(1, ND + 1):
        for nt in range(1, NumTechs + 1):
            s["x111drensub"][y1, d, nt] = 0.0
    _inx_decay(inp, z, Y, y1)

    # lag update on the first iteration after EstYear (or when the dump starts later)
    if Y > Est and itr == 1:
        _zip_lag_update(z)

    jp = s["mc_jpgdp"]
    iGen = int(s["igencapcostyr"]) if "igencapcostyr" in s else inp.iGenCapCostYr
    defl_num = jp[iGen - BASEYR + 1]
    defl_den = jp[-2]
    eprps = s["eprpspr"]
    pel = s.get("pelrsout")

    for nt in range(1, NumTechs):  # battery storage (NT=4) is not processed
        for nv in range(1, inp.NVINT + 1):
            if inp.iFirstYr[nt, nv] > Y or inp.iLastYr[nt, nv] < Y:
                continue
            xAdjCost = _adj_cost(s, inp, nt, nv, y1)
            z.xTaxCreditPct = inp.xTxCrPct[nt, nv]
            xtaxcreditmaxKW = inp.xTXCrMaxPerKW[nt, nv]
            xtaxcreditmax = inp.xTXCrMaxPerSys[nt, nv]
            XLIFE = inp.xEqLife[nt, nv]
            xEqCost = F(F(xAdjCost + inp.xInstCost[nt, nv]) * inp.xKW[nt, nv])
            xDegradation = inp.xDegrad[nt, nv]
            xKW = inp.xKW[nt, nv]
            xElEff = inp.xElEff[nt, nv]
            xLossFac = inp.xLossFac[nt, nv]

            for d in range(1, ND + 1):
                xUnits = D(0.0)
                xTrills = D(0.0)
                xCapacity = D(0.0)
                xTrillsOwnUse = D(0.0)
                xfuelusage = D(0.0)
                xhwbtu = D(0.0)
                xInvest = D(0.0)
                xCalcKW = D(0.0)
                xAnnualKWh = C0

                if nt == 1 and inp.UseZipModel and Y >= Est:
                    xUnits, xTrills, xTrillsOwnUse, xAnnualKWh, xCalcKW = _pv_zip_division(
                        s, inp, z, d, Y, nv, xAdjCost, z.xTaxCreditPct)
                    # division results
                    s["units"][y1, d, nt] = s["units"][y1 - 1, d, nt] + xUnits
                    xCapacity = xUnits * xCalcKW
                    s["cap"][y1, d, nt] = s["cap"][y1 - 1, d, nt] + xCapacity
                    s["trills"][y1, d, nt] = s["trills"][y1 - 1, d, nt] + xTrills
                    s["trillsownuse"][y1, d, nt] = s["trillsownuse"][y1 - 1, d, nt] + xTrillsOwnUse
                    xInvest = xUnits * D(xEqCost) / D(E6)
                    s["x111drensub"][y1, d, nt] = xInvest * D(inp.xTxCrPct_Div[nv, d, nt])
                    s["invest"][y1, d, nt] = xInvest
                    if y1 <= Est - BASEYR + 2 and inp.PVzipcalib and nt == 1:
                        _pv_calibrate(s, inp, z, d, y1, xKW, xCalcKW, xAnnualKWh, xEqCost, nv)
                else:
                    r = _niche_division(s, inp, z, nt, nv, d, Y, y1, xAdjCost, xtaxcreditmaxKW,
                                        xtaxcreditmax, XLIFE, xEqCost, xDegradation, pel, defl_num, defl_den, eprps)
                    xUnits, xTrills, xCapacity, xTrillsOwnUse, xfuelusage, xhwbtu, xInvest = r
                    s["units"][y1, d, nt] = s["units"][y1 - 1, d, nt] + xUnits
                    s["cap"][y1, d, nt] = s["cap"][y1 - 1, d, nt] + xCapacity
                    s["trills"][y1, d, nt] = s["trills"][y1 - 1, d, nt] + xTrills
                    s["trillsownuse"][y1, d, nt] = s["trillsownuse"][y1 - 1, d, nt] + xTrillsOwnUse
                    s["gasusage"][y1, d, nt] = s["gasusage"][y1 - 1, d, nt] + xfuelusage
                    s["hwbtu"][y1, d, nt] = s["hwbtu"][y1 - 1, d, nt] + xhwbtu
                    s["invest"][y1, d, nt] = xInvest
                    s["x111drensub"][y1, d, nt] = xInvest * D(inp.xTxCrPct_Div[nv, d, nt])

                # RPS credit factors passed to the electric power module
                if nt in (1, 3):
                    gen = z.xPVGenAdded if nt == 1 else z.xWindGenAdded
                    gen[d, y1] = F(xTrills)
                    xCompCredit = C0
                    xCompGen = C0
                    xCredit = C1
                    for iyr in range(RECSYEAR - BASEYR + 1, y1 + 1):
                        iCalYR = iyr + BASEYR - 1
                        xBonus = C0
                        xCompGen = F(xCompGen + gen[d, iyr])
                        if Y < inp.iRPSStartYear and iCalYR >= inp.iRPSGrandFatherYear:
                            xBonus = F(inp.xRPS[nt, y1] - C1)
                        else:
                            if y1 < iyr + inp.iNumYrsatRPSBaseRate[nt, iyr] and Y < inp.iRPSPhaseOutYear:
                                xBonus = F(inp.xRPS[nt, iyr] - C1)
                            elif y1 < iyr + inp.iNumRPSCreditYrs[nt, iyr] and Y < inp.iRPSPhaseOutYear:
                                xBonus = F(inp.xRPS[nt, y1] - C1)
                        xCompCredit = F(xCompCredit + F(gen[d, iyr] * F(xCredit + xBonus)))
                    if xCompGen > 0.0:
                        s["cgcpvres" if nt == 1 else "cgcwnres"][d, y1] = F(xCompCredit / xCompGen)


    # Outputs to the electric power module and to learning
    s["rfuelcell_mw"][y1] = 0.0
    s["rpv_mw"][y1] = 0.0
    s["rmicrotur_mw"][y1] = 0.0
    s["rwind_mw"][y1] = 0.0
    cq, cg, cc = s["cgresq"], s["cgresgen"], s["cgrescap"]
    for d in range(1, ND + 1):
        for f in range(1, MNUMCGF + 1):
            cq[d, y1, f] = 0.0
            cc[d, y1, f] = 0.0
            cg[d, y1, f, 1] = 0.0
            cg[d, y1, f, 2] = 0.0
    cap, trills, own, gas = s["cap"], s["trills"], s["trillsownuse"], s["gasusage"]
    k1000 = F(F(1000.0) / F(3.412))
    for d in range(1, ND + 1):
        cc[d, y1, 3] = F(D(cc[d, y1, 3]) + cap[y1, d, 2] / D(C1000))
        cc[d, y1, 8] = F(D(cc[d, y1, 8]) + cap[y1, d, 1] / D(C1000))
        cc[d, y1, 11] = F(D(cc[d, y1, 11]) + cap[y1, d, 3] / D(C1000))
        cc[d, y1, 13] = F(D(cc[d, y1, 13]) + cap[y1, d, 4] / D(C1000))
        s["rpv_mw"][y1] = F(D(s["rpv_mw"][y1]) + cap[y1, d, 1] / D(C1000))
        s["rfuelcell_mw"][y1] = F(D(s["rfuelcell_mw"][y1]) + cap[y1, d, 2] / D(C1000))
        s["rwind_mw"][y1] = F(D(s["rwind_mw"][y1]) + cap[y1, d, 3] / D(C1000))
        for f, t in ((3, 2), (8, 1), (11, 3), (13, 4)):
            cg[d, y1, f, 1] = F(D(cg[d, y1, f, 1]) + (trills[y1, d, t] - own[y1, d, t]) * D(k1000))
        for f, t in ((3, 2), (8, 1), (11, 3), (13, 4)):
            cg[d, y1, f, 2] = F(D(cg[d, y1, f, 2]) + own[y1, d, t] * D(k1000))
        cq[d, y1, 3] = F(D(cq[d, y1, 3]) + gas[y1, d, 2])
        cq[d, y1, 8] = F(D(cq[d, y1, 8]) + trills[y1, d, 1])
        cq[d, y1, 11] = F(D(cq[d, y1, 11]) + trills[y1, d, 3])
        cq[d, y1, 13] = F(D(cq[d, y1, 13]) + trills[y1, d, 4])

    # National totals into division 11
    nat = 11
    for f in range(1, MNUMCGF + 1):
        for k in (1, 2):
            cg[nat, y1, f, k] = 0.0
        cq[nat, y1, f] = 0.0
        cc[nat, y1, f] = 0.0
    for f in range(1, MNUMCGF + 1):
        for k in (1, 2):
            acc = C0
            for d in range(1, ND + 1):
                acc = F(acc + cg[d, y1, f, k])
            cg[nat, y1, f, k] = F(cg[nat, y1, f, k] + acc)
        acc = C0
        for d in range(1, ND + 1):
            acc = F(acc + cq[d, y1, f])
        cq[nat, y1, f] = F(cq[nat, y1, f] + acc)
        acc = C0
        for d in range(1, ND + 1):
            acc = F(acc + cc[d, y1, f])
        cc[nat, y1, f] = F(cc[nat, y1, f] + acc)
    # EIA quirk kept: SUM(TrillsOwnUse(y,1:NumDiv,1:nTek), DIM=2) sums over technologies
    # and leaves one value per division (9), but it is assigned to a section of nTek (4)
    # elements, so element nt receives division nt's total over technologies, not the
    # national total by technology. It is also added to what is already there.
    for nt in range(1, NTEK + 1):
        acc = D(0.0)
        for t in range(1, NTEK + 1):
            acc = acc + own[y1, nt, t]
        own[y1, nat, nt] = own[y1, nat, nt] + acc


def _paybacks(cells, inp, nt, nv, Y, y1, XLIFE, xIntervalCst, xDegradation):
    """The 30-year cash flow (lines around 15990-16080) for every niche at once, then each
    niche's simple payback. Same float32 and float64 operations as the per-niche loop."""
    XTAXRATE, XTERM, XINFLATION = inp.XTAXRATE, inp.XTERM, inp.XINFLATION
    col = lambda k, dt=np.float32: np.array([c[k] for c in cells], dtype=dt)
    n = len(cells)
    zero = np.zeros(n, dtype=np.float32)
    kw = col("xCalcKW", np.float64)
    payment, intrate = col("XPAYMENT"), col("XINTRATE")
    maint_base, fuel2 = col("XMAINTCOSTBASE"), col("XFUELCOST2")
    vs, vs_no, vs_adj = col("XVALESAVEBASE"), col("XVALESAVEBASEnoRPS"), col("XVALESAVEBASEadjRPS")
    outlay = {1: col("XOUTLAY1")}
    loanbal = col("XLOANBAL1")
    intamt = {1: zero}
    taxcredit3 = col("XTAXCREDIT3")
    cum = {1: -outlay[1]}
    net = {1: -outlay[1]}
    fuel = {2: fuel2}
    interval = int(inp.iIntervalYrs[nt, nv])
    in_life = lambda iyr: F(iyr) <= F(XLIFE + C1)
    f = lambda x: np.asarray(x, dtype=np.float32)  # F(): round to float32
    for iyr in range(2, 31):
        in_term = F(iyr) <= F(XTERM + C1)
        out = payment if in_term else zero
        intamt[iyr] = f(loanbal * intrate)
        prin = f(payment - intamt[iyr]) if in_term else zero
        loanbal = f(loanbal - prin)
        taxd = f(f(XTAXRATE * f(intamt[iyr - 1] + zero)) + (taxcredit3 if iyr == 3 else zero))  # XDEPR is 0
        inflp = powi(F(C1 + XINFLATION), iyr - 2)
        fl = fuel[2] if iyr == 2 else zero
        if in_life(iyr):
            fl = f(fuel[2] * inflp)
        fuel[iyr] = fl
        if iyr > 2 and interval != 0 and (iyr - 2) % interval == 0 and iyr != 29 and iyr != 30:
            m = f((maint_base.astype(np.float64) + D(xIntervalCst) * kw) * D(inflp)) if in_life(iyr) else zero
            interval = 2 * interval + iyr
        else:
            m = f(maint_base * inflp) if in_life(iyr) else zero
        vale = zero
        if in_life(iyr):
            degp = powi(F(C1 - xDegradation), iyr - 2)
            vale = f(f(vs * inflp) * degp)
            if nt == 1 or nt == 3:
                if Y + iyr - 1 > inp.iRPSPhaseOutYear:
                    vale = f(f(vs_no * inflp) * degp)
                if Y >= inp.iRPSStartYear and iyr > inp.iNumYrsatRPSBaseRate[nt, y1]:
                    vale = f(f(vs_adj * inflp) * degp)
                if Y >= inp.iRPSStartYear and iyr > inp.iNumRPSCreditYrs[nt, y1]:
                    vale = f(f(vs_no * inflp) * degp)
                if Y < inp.iRPSStartYear:
                    vale = f(f(vs_no * inflp) * degp)
        net[iyr] = f(f(f(f((-out) - fl) - m) + taxd) + vale)
        cum[iyr] = f(cum[iyr - 1] + net[iyr])

    paybacks = []
    for i in range(n):
        flow = [None] + [cum[k][i] for k in range(1, 31)] + [C0] * 5
        xSimplePayback = D(29.0)
        for iyr in range(1, 31):
            if iyr <= 20 and all(flow[iyr + k] >= 0.0 for k in range(9)):
                xSimplePayback = D(F(iyr - 1))
                if xSimplePayback < 1.0:
                    xSimplePayback = D(1.0)
                if iyr < 15:
                    with np.errstate(all="ignore"):
                        xSimplePayback = xSimplePayback - D(F(flow[iyr] / net[iyr][i]))
                break
        paybacks.append(xSimplePayback)
    return paybacks


def _pv_calibrate(s, inp, z, d, y1, xKW, xCalcKW, xAnnualKWh, xEqCost, nv):
    """PVzipcalib (lines 16395-16432): force PV capacity to the exogenous history in
    EstYear and the year after, adjusting units, generation and investment."""
    units, cap, trills, own = s["units"], s["cap"], s["trills"], s["trillsownuse"]
    exog = D(inp.xExogPen[y1, d, 1])
    mistie = exog - cap[y1, d, 1]
    z.ExogPVMistie[y1, d] = mistie
    cap[y1, d, 1] = exog
    units[y1, d, 1] = units[y1, d, 1] + (mistie / xCalcKW)
    xUnits = units[y1, d, 1] - units[y1 - 1, d, 1]
    xInvest = xUnits * D(xEqCost) / D(E6)
    s["x111drensub"][y1, d, 1] = xInvest * D(inp.xTxCrPct_Div[nv, d, 1])
    k3412 = D(F(3412.0))
    add = (mistie / xCalcKW) * D(xAnnualKWh) * k3412 / D(E12)
    trills[y1, d, 1] = trills[y1, d, 1] + add
    if trills[y1, d, 1] < 0.0:
        trills[y1, d, 1] = 0.0
    # shared out in proportion to own use: ((own/trills) * (mistie/kW) * kWh * 3412) / 1e12
    with np.errstate(all="ignore"):
        own[y1, d, 1] = own[y1, d, 1] + (own[y1, d, 1] / trills[y1, d, 1]) * (mistie / xCalcKW) * D(xAnnualKWh) * k3412 / D(E12)
    if own[y1, d, 1] < 0.0:
        own[y1, d, 1] = 0.0
    s["invest"][y1, d, 1] = xInvest


def _niche_division(s, inp, z, nt, nv, d, Y, y1, xAdjCost, xtaxcreditmaxKW, xtaxcreditmax, XLIFE,
                    xEqCost, xDegradation, pel, defl_num, defl_den, eprps):
    """Lines 15716-16160: the niche and payback model for one technology vintage and
    census division. Returns the division's accumulators
    (xUnits, xTrills, xCapacity, xTrillsOwnUse, xfuelusage, xhwbtu, xInvest)."""
    xUnits = D(0.0)
    xTrills = D(0.0)
    xCapacity = D(0.0)
    xTrillsOwnUse = D(0.0)
    xfuelusage = D(0.0)
    xhwbtu = D(0.0)
    xInvest = D(0.0)

    xKW = inp.xKW[nt, nv]
    xElEff = inp.xElEff[nt, nv]
    xLossFac = inp.xLossFac[nt, nv]
    xInstCost = inp.xInstCost[nt, nv]
    xMaintCst = inp.xMaintCst[nt, nv]
    xIntervalCst = inp.xIntervalCst[nt, nv]
    xAvail = inp.xAvail[nt, nv]
    xWhRecovery = inp.xWhRecovery[nt, nv]
    XTAXRATE, XDOWNPAYPCT, XTERM, XINFLATION = inp.XTAXRATE, inp.XDOWNPAYPCT, inp.XTERM, inp.XINFLATION
    xRPS = inp.xRPS[nt, y1]
    EPR = eprps[y1]
    jpg = F(defl_num)
    jpm2 = F(defl_den)
    xAlpha, xPenParm = inp.xAlpha, inp.xPenParm
    xInxDecay = z.xInxDecay[d, y1]
    hseadd, eh, units = s["hseadd"], s["eh"], s["units"]

    # grid sales price, $/kWh in the dollar year of the capital costs
    xSalestoGridPR = F(F(F(s["pelme"][d, y1] * C003412) * jpg) / jpm2)
    cells = []

    for iNiche in range(1, int(inp.NumPVNiche[d]) + 1):
        for iRateLevel in range(1, 4):
            hhshare = inp.xHHShare[d, iNiche, iRateLevel]
            if hhshare == 0.0:
                continue
            xElecAvgUEC = inp.xAvgKWH[d, iNiche, iRateLevel]
            rscal = inp.xRateScalar[d, iNiche, iRateLevel]
            xSqftperKW = C0
            xCalcKW = D(0.0)
            xSolarIns = D(0.0)
            XVALESAVEBASEnoRPS = z.XVALESAVEBASEnoRPS
            XVALESAVEBASEadjRPS = z.XVALESAVEBASEadjRPS
            XBaseYrFUELCOST = C0
            XGASINPUT = C0
            XWATERHTGMMBTU = C0
            XMAINTCOSTBASE = C0

            if nt == 3:  # wind
                pr = s["pelrs"][d, y1]
                xRetailElecPR = F(F(F(F(pr * rscal) * C003412) + F(F(xRPS * EPR) / C1000)) * jpg)
                xRetailElecPR = F(xRetailElecPR / jpm2)
                xRetailElecPRadjRPS = F(F(F(F(F(pr * rscal) * C003412) + F(F(C1 * EPR) / C1000)) * jpg) / jpm2)
                xRetailElecPRnoRPS = F(F(F(F(pr * rscal) * C003412) * jpg) / jpm2)
                xMpS = inp.xWindSpeed[d, iNiche, iRateLevel]
                poly = F(F(F(F(0.0645) - F(F(0.0670) * xMpS)) + F(F(0.0210) * powi(xMpS, 2))) - F(F(0.0011) * powi(xMpS, 3)))
                xAnnualKWh = F(F(F(F(F(xElEff / inp.xElEff[nt, 1]) * poly) * xKW) * F(8760.0)) * xLossFac)
                XEXCESSKWH = F(xAnnualKWh - xElecAvgUEC)
                rpsgrid = F(F(F(F(xRPS * EPR) / C1000) * jpg) / jpm2)
                rpsgrid1 = F(F(F(F(C1 * EPR) / C1000) * jpg) / jpm2)
                if XEXCESSKWH < 0.0:
                    XVALESAVEBASE = F(xAnnualKWh * xRetailElecPR)
                else:
                    XVALESAVEBASE = F(F(xElecAvgUEC * xRetailElecPR) + F(XEXCESSKWH * F(xSalestoGridPR + rpsgrid)))
                if XEXCESSKWH < 0.0:
                    XVALESAVEBASEadjRPS = F(xAnnualKWh * xRetailElecPRadjRPS)
                else:
                    XVALESAVEBASE = F(F(xElecAvgUEC * xRetailElecPR) + F(XEXCESSKWH * F(xSalestoGridPR + rpsgrid1)))
                if XEXCESSKWH < 0.0:
                    XVALESAVEBASEnoRPS = F(xAnnualKWh * xRetailElecPRnoRPS)
                else:
                    XVALESAVEBASEnoRPS = F(F(XEXCESSKWH * xSalestoGridPR) + F(xElecAvgUEC * xRetailElecPRnoRPS))
                if Y < inp.iRPSStartYear:
                    XVALESAVEBASE = XVALESAVEBASEnoRPS
                xCalcKW = D(xKW)
                XMAINTCOSTBASE = F(D(xMaintCst) * xCalcKW)
            elif nt == 2:  # fuel cell
                xRetailElecPR = F(F(F(F(s["pelrs"][d, y1] * rscal) * C003412) * jpg) / jpm2)
                xAnnualKWh = F(F(F(inp.xOperHours[nt] * xAvail) * xKW) * xLossFac)
                XWATERHTGMMBTU = F(17.5)
                XGASINPUT = F(F(F(F(C003412 * xKW) / xElEff) * inp.xOperHours[nt]) * xAvail)
                XBTUWASTEHEAT = F(F(XGASINPUT - F(C003412 * xAnnualKWh)) * xWhRecovery)
                if XBTUWASTEHEAT < XWATERHTGMMBTU:
                    XWATERHTGMMBTU = XBTUWASTEHEAT
                XBaseYrFUELCOST = F(F(F(F(XGASINPUT - XWATERHTGMMBTU) * s["pngrs"][d, y1]) * jpg) / jpm2)
                XEXCESSKWH = F(xAnnualKWh - xElecAvgUEC)
                if XEXCESSKWH < 0.0:
                    XVALESAVEBASE = F(xAnnualKWh * xRetailElecPR)
                else:
                    XVALESAVEBASE = F(F(XEXCESSKWH * xSalestoGridPR) + F(xElecAvgUEC * xRetailElecPR))
                xCalcKW = D(xKW)
                XMAINTCOSTBASE = F(D(xMaintCst) * xCalcKW)
            else:  # solar PV niche model
                xSqftperKW = F(F(F(77.0) * F(0.14)) / xElEff)
                xSolarIns = D(inp.xSolarInsolation[d, iNiche, iRateLevel])
                # transform insolation to allow for unknown orientations
                xSolarIns = D(F(-1.0533)) + D(F(1.4325)) * xSolarIns - D(F(0.0652)) * (xSolarIns * xSolarIns)
                xSizefromRoofArea = D(F(F(F(F(inp.xRoofAreaPerHH[d, iNiche, iRateLevel] * F(0.8)) * F(0.4)) * F(0.75))
                                        / xSqftperKW))
                xSizefromTaxOptim = F(z.xSizeMax)
                # the cap on credit per kW lowers the credit percentage for every later pass too
                if z.xTaxCreditPct > 0.0 and xtaxcreditmaxKW > 0.0:
                    z.xTaxCreditPct = min(z.xTaxCreditPct, F(xtaxcreditmaxKW / F(xAdjCost + xInstCost)))
                if z.xTaxCreditPct > 0.0 and xtaxcreditmax > 0.0:
                    xSizefromTaxOptim = F(F(xtaxcreditmax / z.xTaxCreditPct) / F(xAdjCost + xInstCost))
                z.xSizeMax = D(10.0)
                xSizeMin = D(1.0)
                xCalcKW = D(F(nint(max(min(xSizefromRoofArea, D(xSizefromTaxOptim), z.xSizeMax), xSizeMin))))
                xAnnualKWh = F(D(xElEff) * xSolarIns * D(365.25) / D(F(10.8)) * D(xSqftperKW) * xCalcKW * D(xLossFac))

                rpsterm = F(F(xRPS * EPR) / C1000)
                rpsterm1 = F(F(C1 * EPR) / C1000)
                # space cooling price, or from DGrateYr a retail/wholesale blend of it
                if inp.DGrateBlend and Y >= inp.DGrateYr:
                    base = F(F(s["pelme"][d, y1] * inp.DGmargWt[d]) + F(pel[d, y1, 2] * inp.DGretWt[d]))
                else:
                    base = pel[d, y1, 2]
                scaled = F(F(base * rscal) * C003412)
                xRetailElecPR = F(F(F(scaled + rpsterm) * jpg) / jpm2)
                xRetailElecPRadjRPS = F(F(F(scaled + rpsterm1) * jpg) / jpm2)
                xRetailElecPRnoRPS = F(F(scaled * jpg) / jpm2)
                XEXCESSKWH = F(xAnnualKWh - xElecAvgUEC)
                rpsgrid = F(F(F(F(xRPS * EPR) / C1000) * jpg) / jpm2)
                rpsgrid1 = F(F(F(F(C1 * EPR) / C1000) * jpg) / jpm2)
                if XEXCESSKWH < 0.0:
                    XVALESAVEBASE = F(xAnnualKWh * xRetailElecPR)
                else:
                    XVALESAVEBASE = F(F(XEXCESSKWH * F(xSalestoGridPR + rpsgrid)) + F(xElecAvgUEC * xRetailElecPR))
                if XEXCESSKWH < 0.0:
                    XVALESAVEBASEadjRPS = F(xAnnualKWh * xRetailElecPRadjRPS)
                else:
                    XVALESAVEBASE = F(F(xElecAvgUEC * xRetailElecPR) + F(XEXCESSKWH * F(xSalestoGridPR + rpsgrid1)))
                if XEXCESSKWH < 0.0:
                    XVALESAVEBASEnoRPS = F(xAnnualKWh * xRetailElecPRnoRPS)
                else:
                    XVALESAVEBASEnoRPS = F(F(XEXCESSKWH * xSalestoGridPR) + F(xElecAvgUEC * xRetailElecPRnoRPS))
                if Y < inp.iRPSStartYear:
                    XVALESAVEBASE = XVALESAVEBASEnoRPS
                XMAINTCOSTBASE = F(D(xMaintCst) * xCalcKW)
            z.XVALESAVEBASEnoRPS, z.XVALESAVEBASEadjRPS = XVALESAVEBASEnoRPS, XVALESAVEBASEadjRPS

            # ---- 30-year cash flow: this niche's inputs; the flows run below for all niches at once ----
            xCalcEqCost = D(xEqCost) * xCalcKW / D(xKW)
            XINTRATE = F(s["mc_rmmtg30con"][y1] / C100)
            XDOWNPAY = F(D(XDOWNPAYPCT) * xCalcEqCost)
            XPAYMENT = F(F(XINTRATE / F(C1 - _powf(F(C1 + XINTRATE), F(F(-1.0) * XTERM)))) * (xCalcEqCost - D(XDOWNPAY)))
            XTAXCREDIT3 = F(xCalcEqCost * D(z.xTaxCreditPct))
            if xtaxcreditmaxKW > 0.0:
                XTAXCREDIT3 = F(min(D(XTAXCREDIT3), D(xtaxcreditmaxKW) * xCalcKW))
            if xtaxcreditmax > 0.0:
                XTAXCREDIT3 = min(XTAXCREDIT3, xtaxcreditmax)
            XTAXCREDIT3 = F(D(XTAXCREDIT3) + xCalcEqCost * D(inp.xTxCrPct_Div[nv, d, nt]))
            cells.append(dict(
                hhshare=hhshare, xElecAvgUEC=xElecAvgUEC, xCalcKW=xCalcKW, xAnnualKWh=xAnnualKWh,
                xCalcEqCost=xCalcEqCost, XINTRATE=XINTRATE, XPAYMENT=XPAYMENT, XTAXCREDIT3=XTAXCREDIT3,
                XOUTLAY1=F(D(XDOWNPAYPCT) * xCalcEqCost), XLOANBAL1=F(xCalcEqCost * D(F(C1 - XDOWNPAYPCT))),
                XFUELCOST2=XBaseYrFUELCOST, XMAINTCOSTBASE=XMAINTCOSTBASE, XVALESAVEBASE=XVALESAVEBASE,
                XVALESAVEBASEnoRPS=XVALESAVEBASEnoRPS, XVALESAVEBASEadjRPS=XVALESAVEBASEadjRPS,
                XGASINPUT=XGASINPUT, XWATERHTGMMBTU=XWATERHTGMMBTU))

    if not cells:
        return xUnits, xTrills, xCapacity, xTrillsOwnUse, xfuelusage, xhwbtu, xInvest
    paybacks = _paybacks(cells, inp, nt, nv, Y, y1, XLIFE, xIntervalCst, xDegradation)

    for c, xSimplePayback in zip(cells, paybacks):
        hhshare, xElecAvgUEC, xCalcKW = c["hhshare"], c["xElecAvgUEC"], c["xCalcKW"]
        xAnnualKWh, xCalcEqCost = c["xAnnualKWh"], c["xCalcEqCost"]
        XGASINPUT, XWATERHTGMMBTU = c["XGASINPUT"], c["XWATERHTGMMBTU"]
        # ---- penetration from payback ----
        xMaxPen = xPenParm / xSimplePayback
        XValue = F(Y - (RECSYEAR + 1))
        if XValue > 25.0:
            XValue = F(25.0)
        xPen = min(D(F(0.75)), xMaxPen - xMaxPen / (D(1.0) + xMaxPen * _exp(xAlpha * (D(XValue) - xSimplePayback))))
        if Y <= inp.iExogHistYr[nt]:
            xPen = D(0.0)  # historical years: exogenous capacity only
        xExistPen = F(min(xPen / D(F(40.0)), D(F(0.005))))
        xex = inp.xExogPen
        xTemp = (xPen * D(xInxDecay) * D(hseadd[Y, 1, d])
                 + (D(xex[y1, d, nt]) - D(xex[y1 - 1, d, nt])) / xCalcKW
                 + D(F(xExistPen * xInxDecay)) * (D(eh[Y, 1, d]) - units[y1 - 1, d, nt]))
        xTemp = xTemp * D(hhshare)
        xTemp = D(F(F(nint(xTemp * D(F(100.0)) + D(F(0.5)))) / C100))

        xUnits = xUnits + xTemp
        xTrills = xTrills + xTemp * D(xAnnualKWh) * D(F(3412.0)) / D(E12)
        xCapacity = xCapacity + xTemp * xCalcKW
        if xAnnualKWh > xElecAvgUEC:
            xTrillsOwnUse = xTrillsOwnUse + xTemp * D(xElecAvgUEC) * D(F(3412.0)) / D(E12)
        else:
            xTrillsOwnUse = xTrillsOwnUse + xTemp * D(xAnnualKWh) * D(F(3412.0)) / D(E12)
        xfuelusage = xfuelusage + xTemp * D(XGASINPUT) / D(E6)
        xhwbtu = xhwbtu + xTemp * D(XWATERHTGMMBTU) / D(E6)
        xInvest = xInvest + xTemp * xCalcEqCost / D(E6)
    return xUnits, xTrills, xCapacity, xTrillsOwnUse, xfuelusage, xhwbtu, xInvest

    # hand the carried ZIP state back to the shared dict when the caller keeps it there
    for nm, attr in _CARRIED.items():
        if nm in s:
            s[nm].a[:] = getattr(z, attr)
