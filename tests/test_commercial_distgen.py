"""CDistGen (on-site generation) vs the oracle: input tables first, then the yearly calculation.

The oracle dumps CDISTGEN's tables right after it reads KCOGEN and KGENTK (`fdg_out`, 2019,
first iteration) and its state around every call in nine test years (`dg_in`, `dg_out`).
Skipped until the oracle has run.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.commercial import distgen_tables as tables

pytestmark = pytest.mark.skipif(not oracle_state.available("fdg_out", 30), reason="oracle state not dumped")


@pytest.fixture(scope="module")
def eia():
    return oracle_state.load("fdg_out", 30)


@pytest.fixture(scope="module")
def kgentk():
    return tables.read_kgentk()


def dense(a):
    """An FArray as a plain array with the Fortran index in every dimension (index 0 unused).

    A dimension that starts below 0 (CMNewFloorSpace runs from -165) keeps only indices from 0 up.
    """
    src = a.a[tuple(slice(max(0, -l), None) for l in a.lb)]
    lb = [max(0, l) for l in a.lb]
    out = np.zeros(tuple(l + n for l, n in zip(lb, src.shape)), dtype=a.a.dtype)
    out[tuple(slice(l, l + n) for l, n in zip(lb, src.shape))] = src
    return out


def same(mine, theirs, rel=1e-6):
    mine, theirs = np.asarray(mine), np.asarray(theirs)
    assert mine.shape == theirs.shape, (mine.shape, theirs.shape)
    if theirs.dtype.kind in "iub" or theirs.dtype.kind in "SU":
        assert (mine == theirs).all()
    else:
        err = np.abs(mine.astype(np.float64) - theirs) / np.maximum(np.abs(theirs), 1e-6)
        assert err.max() < rel


def test_kcogen(eia):
    same(tables.read_kcogen(), dense(eia["cmcogenel"]))


@pytest.mark.parametrize("name", [
    "XOPERHOURS", "xpctPVSuitable", "XBeta", "Xc0", "XINX", "XALPHA", "XPENPARM", "xkwMin", "xkwmax",
    "xScaleFac", "ISKIP", "iRPSStartYear", "iRPSPhaseOutYear", "iRPSGrandFatherYear", "IFUELTYPE", "IFIRSTYR",
    "ILASTYR", "XKW", "XELEFF", "XLOSSFAC", "XDEGRAD", "XEQLIFE", "xtxlife", "xdep", "XWHRECOVERY",
    "XINSTCOST", "XCAPCOST", "XMAINTCST", "xIntervalCst", "iIntervalYrs", "XAVAIL", "XTXCRPCT",
    "xTXCrMaxPerKW", "xTXCrMaxPerSys", "ComTxCrPct_Div", "xRPS", "iNumYrsatRPSBaseRate", "iNumRPSCreditYrs",
    "NumPVNiche", "xSolarInsolation", "xSqftShare", "xRateScalar", "xRoofAreatoSqftRatio", "xWindSpeed",
    "xNGRateScalar", "XBLDGSHARE", "cbecsFlspcCatShare", "cbecsAVGSQFT", "xelecavgkwh", "XEXOGPEN",
    "XA", "XB", "XC"])
def test_kgentk_tables(eia, kgentk, name):
    mine = getattr(kgentk, name)
    theirs = eia[name.lower()]
    theirs = dense(theirs) if hasattr(theirs, "a") else theirs
    # The dump has EIA's declared sizes; compare over the part both define.
    n = tuple(slice(0, min(a, b)) for a, b in zip(mine.shape, theirs.shape))
    if name == "AEQUIPNAME":
        return
    same(mine[n], theirs[n])


def test_kgentk_scalars(eia, kgentk):
    for name in ("NUMTECHS", "NUMYEARS", "NUMDIV", "NUMBLDG", "NVINT", "iGenCapCostYr", "XINXFY", "XINXLY"):
        assert getattr(kgentk, name) == int(eia[name.lower()]), name
    for name in ("XTAXRATE", "XDOWNPAYPCT", "XINTRATE", "XTERM", "XINFLATION"):
        assert float(getattr(kgentk, name)) == pytest.approx(float(eia[name.lower()]), rel=1e-6), name
    assert bool(kgentk.GlobalLearn) == bool(eia["globallearn"])


def test_kgentk_names(eia, kgentk):
    theirs = np.char.rstrip(eia["aequipname"].a.astype("U10"))
    mine = kgentk.AEQUIPNAME[1:12, 1:62]
    assert (np.char.rstrip(mine) == theirs).all()


# ---- Yearly calculation ----

from nems_open.commercial.distgen import DgState, distgen  # noqa: E402

YEARS = [30, 31, 32, 36, 37, 38, 41, 51, 61]
TOL = 1e-4

# Results kept between years, from the dump taken after the call.
CARRIED = {"UNITS": "units", "TRILLS": "trills", "capacity": "capacity", "TRILLSOWNUSE": "trillsownuse",
           "fuelusage": "fuelusage", "HWBTU": "hwbtu", "SHBTU": "shbtu", "INVEST": "invest",
           "xCumPenSqft": "xcumpensqft", "QCMDGSG": "qcmdgsg", "com111drensub": "com111drensub",
           "SolarPVTechPotentialMW": "solarpvtechpotentialmw", "SolarPVAvailRoofArea": "solarpvavailroofarea",
           "SolarPVInstalledMW": "solarpvinstalledmw", "SolarPVUsedRoofArea": "solarpvusedroofarea",
           "WindTechPotentialMW": "windtechpotentialmw", "WindAvailFS": "windavailfs",
           "WindInstalledMW": "windinstalledmw", "WindBldgCount": "windbldgcount",
           "xPVGenAdded": "xpvgenadded", "xWindGenAdded": "xwindgenadded",
           "CGCOMMGEN": "cgcommgen", "CGCOMMCAP": "cgcommcap", "CGCOMMQ": "cgcommq", "CGCPVCOM": "cgcpvcom",
           "CGCWNCOM": "cgcwncom", "KCHPCESGEN": "kchpcesgen", "CFuelCell_MW": "cfuelcell_mw", "CPV_MW": "cpv_mw",
           "CMicroTur_MW": "cmicrotur_mw", "CWind_MW": "cwind_mw", "CMUSCogen": "cmuscogen"}
# Results that are written every call, so the port has to produce them (zeroed before the call).
YEAR_AXIS = {"UNITS": 0, "TRILLS": 0, "capacity": 0, "TRILLSOWNUSE": 0, "fuelusage": 0, "HWBTU": 0, "SHBTU": 0,
             "INVEST": 0, "xCumPenSqft": 0, "QCMDGSG": 0, "com111drensub": 0, "SolarPVTechPotentialMW": 0,
             "SolarPVAvailRoofArea": 0, "SolarPVInstalledMW": 0, "SolarPVUsedRoofArea": 0, "WindTechPotentialMW": 0,
             "WindAvailFS": 0, "WindInstalledMW": 0, "WindBldgCount": 0, "xPVGenAdded": 1, "xWindGenAdded": 1,
             "CGCOMMGEN": 1, "CGCOMMCAP": 1, "CGCOMMQ": 1, "CGCPVCOM": 1, "CGCWNCOM": 1, "KCHPCESGEN": 1,
             "CFuelCell_MW": 0, "CPV_MW": 0, "CMicroTur_MW": 0, "CWind_MW": 0, "CMUSCogen": 1}

_cache = {}


def _shared(before):
    """What other modules supply to CDISTGEN, as the names distgen() expects."""
    names = {"PELME": "pelme", "PELCM": "pelcm", "PELCMOUT": "pelcmout", "PNGCM": "pngcm", "PDSCM": "pdscm",
             "PCLIN": "pclin", "PCLCM": "pclcm", "EPRPSPR": "eprpspr", "EPRPSTGT": "eprpstgt",
             "SurvFloorTotal": "survfloortotal", "CMNewFloorSpace": "cmnewfloorspace", "COMEUI": "comeui",
             "RPV_MW": "rpv_mw", "UPV_MW": "upv_mw", "RFuelCell_MW": "rfuelcell_mw", "RWind_MW": "rwind_mw",
             "RMicroTur_MW": "rmicrotur_mw"}
    d = {k: dense(before[v]) for k, v in names.items()}
    jp = before["mc_jpgdp"]
    d["MC_JPGDP"] = {i: jp[i] for i in range(jp.lb[0], jp.lb[0] + jp.a.shape[0])}
    d["UPIRA_APPYR"] = int(before["upira_appyr"])
    return d


def run_year(y):
    if y in _cache:
        return _cache[y]
    before, after = oracle_state.load("dg_in", y), oracle_state.load("dg_out", y)
    t = tables.read_kgentk()
    cogen = tables.read_kcogen()
    st = DgState.empty()
    for attr, key in CARRIED.items():
        arr = dense(after[key])
        setattr(st, attr, arr.copy())
        axis = YEAR_AXIS[attr]
        idx = [slice(None)] * arr.ndim
        idx[axis] = slice(y, None)           # clear this year (and later): the port must rebuild it
        # CGCPVCOM and CGCWNCOM start at 1 and stay there until generation is added.
        getattr(st, attr)[tuple(idx)] = 0.0
        if attr in ("CGCPVCOM", "CGCWNCOM"):
            getattr(st, attr)[1:10, y:] = 1.0
    xp = after["xpen"]
    st.xpen = {}
    if y > 30:
        prev = np.zeros((12, 12, 12, 6, 11, 7), dtype=np.float32)
        prev[1:12, 1:12, 1:12, 1:6, 1:11, 1:7] = xp.a[y - 1 - xp.lb[0]]
        st.xpen[y - 1] = prev
    shared = _shared(before)
    # CPV_MW and friends carry last year's value; the port needs year y - 1 from before the call.
    for attr in ("CFuelCell_MW", "CPV_MW", "CMicroTur_MW", "CWind_MW"):
        getattr(st, attr)[y - 1] = dense(before[CARRIED[attr]])[y - 1]
    # Division 10 and 11 of the shared cogeneration arrays are not rewritten each year; keep EIA's.
    distgen(t, st, shared, cogen, y)
    _cache[y] = (st, after, xp)
    return _cache[y]


def rel_err(mine, eia):
    mine, eia = np.asarray(mine, dtype=np.float64), np.asarray(eia, dtype=np.float64)
    return float((np.abs(mine - eia) / np.maximum(np.abs(eia), 1e-6)).max())


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("attr", list(CARRIED))
def test_distgen_year(y, attr):
    st, after, _ = run_year(y)
    axis = YEAR_AXIS[attr]
    mine = getattr(st, attr)
    theirs = dense(after[CARRIED[attr]])
    idx = [slice(None)] * mine.ndim
    idx[axis] = y                          # compare the year that was computed
    if attr == "WindBldgCount":
        # EIA never clears this one, so the final state holds both iterations of the year.
        mine = mine * 2
    assert rel_err(mine[tuple(idx)], theirs[tuple(idx)]) < TOL
