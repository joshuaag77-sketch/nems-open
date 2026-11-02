"""Input file readers for the commercial module (the first-call code in comm.f).

Each function reads one EIA input file into the arrays COMServiceDemand and
COMTechnologyChoice take as inputs, the way the Fortran does: list-directed reads
(see `fortran_io`), the same loop order, and the same clean-up edits straight after
the read. Arrays come back as Fortran-indexed `FArray`s with EIA's bounds.

Names follow the Fortran so each reader can be checked against comm.f.
"""

from pathlib import Path

import numpy as np

from nems_open.fortran_array import FArray
from nems_open.fortran_io import HEADER_RECORDS, ListDirectedReader
from nems_open.paths import INPUT

f32 = np.float32

BASEYR = 1990
CBECS_YEAR = 2018
CBECS_IDX = CBECS_YEAR - (BASEYR - 1)  # 29
CM_FIRST_YR = CBECS_YEAR - BASEYR + 2  # 30
CM_LAST_YR = 61
MNUMYR = 61
NUM_DIV = 9  # MNUMCR - 2
NUM_BLDG = 11
NUM_SERV = 10
NUM_MAJ_SERV = 7
NUM_MAJ_FL = 3
NUM_DH_SERV = 3
NUM_SD_ELAS = 10
NUM_VAR_SDI = 6
NUM_VAR_SDI_CAT = 2
NUM_CT = 5
NUM_MELS = 20
NUM_PREF = 7
NUM_RULE = 3
NUM_DECISION = 3

CDM = INPUT / "cdm"
BLD = INPUT / "bld"


def _header(path: Path) -> ListDirectedReader:
    """Open a file past its 100-line header: READ (unit,'(99(/))')."""
    return ListDirectedReader(path, HEADER_RECORDS)


def _slashes(r: ListDirectedReader, n: int) -> None:
    """READ (unit,'(//)') with n slashes: touches n + 1 records."""
    r.skip(n + 1)


def _powi(x, n: int):
    """x ** n for an integer n in float32, by repeated multiplication as compiled Fortran does."""
    result = f32(1.0)
    base = f32(x)
    n = int(n)
    while n > 0:
        if n & 1:
            result = f32(result * base)
        base = f32(base * base)
        n >>= 1
    return result


def read_kintens(cdm_dir: Path = CDM) -> FArray:
    """ComEUI (r, b, s, f): energy use intensity in kBtu/sqft for the CBECS year.

    f runs over the major fuels; column CMnumMajFl+1 (the total) is filled later by
    COMServiceDemand and stays 0 here. Lighting (service 6) is converted to watt-years.
    """
    eui = FArray.zeros([(1, NUM_DIV), (1, NUM_BLDG), (1, NUM_SERV), (1, NUM_MAJ_FL + 1)])
    r_ = _header(Path(cdm_dir) / "kintens.txt")
    try:
        for r in range(1, NUM_DIV + 1):
            for b in range(1, NUM_BLDG + 1):
                for f in range(1, NUM_MAJ_FL + 1):
                    vals = r_.read(NUM_SERV)
                    if vals is None:
                        continue
                    eui[r, b, :, f] = np.array(vals, dtype=f32)
                    eui[r, b, 6, f] = f32(eui[r, b, 6, f] * f32(0.03343))
    except EOFError:
        pass
    return eui


def read_ksheff(cdm_dir: Path = CDM):
    """Shell efficiency (building code) factors for new buildings.

    Returns (ExistImprvHt, ExistImprvCl, ShellHeatFactor, ShellCoolFactor). The shell
    factors are (b, r, vintage, y) with vintage 2 = new; the file gives a few years and
    the years in between are interpolated geometrically.
    """
    heat = FArray.zeros([(1, NUM_BLDG), (1, NUM_DIV + 2), (1, 2), (CBECS_IDX, CM_LAST_YR)])
    cool = FArray.zeros([(1, NUM_BLDG), (1, NUM_DIV + 2), (1, 2), (CBECS_IDX, CM_LAST_YR)])
    imprv_ht = FArray.zeros([(1, NUM_BLDG), (1, NUM_DIV)])
    imprv_cl = FArray.zeros([(1, NUM_BLDG), (1, NUM_DIV)])
    rd = _header(Path(cdm_dir) / "ksheff.txt")
    try:
        num_years = int(rd.read(1)[0])
        _slashes(rd, 1)
        years = [int(v) for v in rd.read(num_years)]
        _slashes(rd, 1)
        for r in range(1, NUM_DIV + 1):
            for b in range(1, NUM_BLDG + 1):
                ht, cl = rd.read(2)
                imprv_ht[b, r], imprv_cl[b, r] = f32(ht), f32(cl)
                for y in years:
                    h, c = rd.read(2)
                    heat[b, r, 2, y - (BASEYR - 1)] = f32(h)
                    cool[b, r, 2, y - (BASEYR - 1)] = f32(c)
    except EOFError:
        pass

    for r in range(1, NUM_DIV + 1):
        for b in range(1, NUM_BLDG + 1):
            for i in range(num_years - 1):
                y0, y1 = years[i], years[i + 1]
                h0, h1 = heat[b, r, 2, y0 - (BASEYR - 1)], heat[b, r, 2, y1 - (BASEYR - 1)]
                c0, c1 = cool[b, r, 2, y0 - (BASEYR - 1)], cool[b, r, 2, y1 - (BASEYR - 1)]
                h_ratio, c_ratio = f32(h1 / h0), f32(c1 / c0)
                expo = f32(f32(1.0) / f32(y1 - y0))
                h_step, c_step = f32(h_ratio ** expo), f32(c_ratio ** expo)
                for y in range(y0 + 1, y1):
                    heat[b, r, 2, y - (BASEYR - 1)] = f32(h0 * _powi(h_step, y - y0))
                    cool[b, r, 2, y - (BASEYR - 1)] = f32(c0 * _powi(c_step, y - y0))
    return imprv_ht, imprv_cl, heat, cool


def read_kmels(cdm_dir: Path = CDM) -> dict:
    """Miscellaneous electric loads and sensor/control tables from kmels.txt.

    Returns dcf, xplicitmiscshr, DataCtrServPenetration, OfficePCPenetration, MelsElQ,
    MarketPenetrationMels, pctSCSavings, CT_flag and MarketPenetrationSC.
    """
    dcf = FArray(np.ones((NUM_BLDG + 1, NUM_SERV), dtype=f32))
    xplicit = FArray(np.ones(NUM_BLDG, dtype=f32))
    data_ctr = FArray.zeros([(CBECS_IDX, MNUMYR)])
    office_pc = FArray.zeros([(CBECS_IDX, MNUMYR)])
    mels_elq = FArray(np.ones(NUM_MELS, dtype=f32))
    mels_pen = FArray(np.ones((NUM_MELS, MNUMYR - CBECS_IDX + 1), dtype=f32), [1, CBECS_IDX])
    pct_sc = FArray.zeros([(1, NUM_CT)])
    ct_flag = FArray.zeros([(1, NUM_CT), (1, NUM_MAJ_SERV)], dtype=np.int16)
    sc_pen = FArray.zeros([(1, NUM_CT), (1, NUM_BLDG), (1, MNUMYR)])
    years_sc = []

    rd = _header(Path(cdm_dir) / "kmels.txt")
    try:
        for b in range(1, NUM_BLDG + 2):
            vals = rd.read(NUM_SERV)
            if vals is not None:
                dcf[b, :] = np.array(vals, dtype=f32)
        _slashes(rd, 1)
        vals = rd.read(NUM_BLDG)
        if vals is not None:
            xplicit[:] = np.array(vals, dtype=f32)
        n_years = MNUMYR - CM_FIRST_YR + 1
        _slashes(rd, 2)
        vals = rd.read(n_years)
        if vals is not None:
            data_ctr[CM_FIRST_YR:MNUMYR] = np.array(vals, dtype=f32)
        _slashes(rd, 2)
        vals = rd.read(n_years)
        if vals is not None:
            office_pc[CM_FIRST_YR:MNUMYR] = np.array(vals, dtype=f32)
        _slashes(rd, 1)
        for i in range(1, NUM_MELS + 1):
            vals = rd.read(1)
            if vals is not None:
                mels_elq[i] = f32(vals[0])
        _slashes(rd, 2)
        for i in range(1, NUM_MELS + 1):
            vals = rd.read(n_years)
            if vals is None:
                break
            mels_pen[i, CM_FIRST_YR:CM_LAST_YR] = np.array(vals, dtype=f32)
        _slashes(rd, 1)
        vals = rd.read(NUM_CT)
        pct_sc[:] = np.array(vals, dtype=f32)
        _slashes(rd, 1)
        for ct in range(1, NUM_CT + 1):
            ct_flag[ct, :] = np.array(rd.read(NUM_MAJ_SERV, int), dtype=np.int16)
        _slashes(rd, 1)
        n_sc = int(rd.read(1)[0])
        _slashes(rd, 1)
        years_sc = [int(v) for v in rd.read(n_sc)]
        for ct in range(1, NUM_CT + 1):
            for b in range(1, NUM_BLDG + 1):
                vals = rd.read(n_sc)
                for y, v in zip(years_sc, vals):
                    sc_pen[ct, b, y - (BASEYR - 1)] = f32(v)
    except (EOFError, TypeError):
        pass

    # Years between the ones in the file: geometric interpolation.
    for ct in range(1, NUM_CT + 1):
        for b in range(1, NUM_BLDG + 1):
            for i in range(len(years_sc) - 1):
                y0, y1 = years_sc[i], years_sc[i + 1]
                p0, p1 = sc_pen[ct, b, y0 - (BASEYR - 1)], sc_pen[ct, b, y1 - (BASEYR - 1)]
                ratio = f32(p1 / p0)
                step = f32(ratio ** f32(f32(1.0) / f32(y1 - y0)))
                for y in range(y0 + 1, y1):
                    sc_pen[ct, b, y - (BASEYR - 1)] = f32(p0 * _powi(step, y - y0))

    return {"dcf": dcf, "xplicitmiscshr": xplicit, "datactrservpenetration": data_ctr,
            "officepcpenetration": office_pc, "melselq": mels_elq, "marketpenetrationmels": mels_pen,
            "pctscsavings": pct_sc, "ct_flag": ct_flag, "marketpenetrationsc": sc_pen}


def read_kdsstm(cdm_dir: Path = CDM) -> FArray:
    """DistServSteamEUI (r, b, s): steam energy per square foot for district services."""
    out = FArray.zeros([(1, NUM_DIV), (1, NUM_BLDG), (1, NUM_DH_SERV)])
    rd = _header(Path(cdm_dir) / "kdsstm.txt")
    try:
        for r in range(1, NUM_DIV + 1):
            for b in range(1, NUM_BLDG + 1):
                vals = rd.read(NUM_DH_SERV)
                if vals is not None:
                    out[r, b, :] = np.array(vals, dtype=f32)
    except EOFError:
        pass
    return out


def read_kdseff(cdm_dir: Path = CDM) -> FArray:
    """DistServBoilerEff (f): efficiency of boilers that make district steam."""
    out = FArray.zeros([(1, NUM_MAJ_FL)])
    rd = _header(Path(cdm_dir) / "kdseff.txt")
    try:
        vals = rd.read(NUM_MAJ_FL)
        if vals is not None:
            out[:] = np.array(vals, dtype=f32)
    except EOFError:
        pass
    return out


def read_kdsfs(cdm_dir: Path = CDM) -> FArray:
    """DistServFuelShr (r, s, f): fuel shares of district steam, checked and normalised."""
    out = FArray.zeros([(1, NUM_DIV), (1, NUM_DH_SERV), (1, NUM_MAJ_FL)])
    epsilon = f32(0.00001)  # Epsilon(1)
    rd = _header(Path(cdm_dir) / "kdsfs.txt")
    try:
        for s in range(1, NUM_DH_SERV + 1):
            for r in range(1, NUM_DIV + 1):
                vals = rd.read(NUM_MAJ_FL)
                if vals is None:
                    continue
                out[r, s, :] = np.array(vals, dtype=f32)
                total = f32(0.0)
                for f in range(1, NUM_MAJ_FL + 1):
                    if out[r, s, f] < 0.0 or out[r, s, f] > 1.0:
                        out[r, s, f] = 0.0
                    total = f32(total + out[r, s, f])
                # EIA tests against Epsilon(2), the loose 0.001 criterion, set in a DATA statement.
                if total == 0.0:
                    pass
                elif total > f32(1.0) + f32(0.001) or total < f32(1.0) - f32(0.001):
                    for f in range(1, NUM_MAJ_FL + 1):
                        out[r, s, f] = f32(out[r, s, f] / total)
    except EOFError:
        pass
    return out


def read_ksdela(cdm_dir: Path = CDM, name: str = "ksdela.txt") -> FArray:
    """ShortRunPriceElasofDmd (r, s, f), or HurdleElas when `name` is khurela.txt.

    Positive elasticities are not reasonable and are set to zero.
    """
    out = FArray.zeros([(1, NUM_DIV), (1, NUM_SD_ELAS), (1, NUM_MAJ_FL)])
    rd = _header(Path(cdm_dir) / name)
    try:
        for r in range(1, NUM_DIV + 1):
            for s in range(1, NUM_SD_ELAS + 1):
                vals = rd.read(NUM_MAJ_FL)
                if vals is None:
                    continue
                out[r, s, :] = np.array(vals, dtype=f32)
                for f in range(1, NUM_MAJ_FL + 1):
                    if out[r, s, f] > 0.0:
                        out[r, s, f] = 0.0
    except EOFError:
        pass
    return out


def read_khurela(cdm_dir: Path = CDM) -> FArray:
    """HurdleElas (r, s, f): hurdle rate elasticities."""
    return read_ksdela(cdm_dir, "khurela.txt")


def read_kvarsdi(cdm_dir: Path = CDM) -> FArray:
    """ServicedFlrspcProp (b, s, v): share of floorspace that gets variable-SDI services."""
    out = FArray.zeros([(1, NUM_BLDG), (1, NUM_VAR_SDI), (1, NUM_VAR_SDI_CAT)])
    rd = _header(Path(cdm_dir) / "kvarsdi.txt")
    try:
        for s in range(1, NUM_VAR_SDI + 1):
            for v in range(1, NUM_VAR_SDI_CAT + 1):
                vals = rd.read(NUM_BLDG)
                if vals is not None:
                    out[:, s, v] = np.array(vals, dtype=f32)
    except EOFError:
        pass
    return out


def read_krenew(cdm_dir: Path = CDM):
    """(SunlightEfficacy, SolarRenewableContrib (r, s, y)): solar thermal and daylighting contribution."""
    contrib = FArray.zeros([(1, NUM_DIV), (1, 6), (1, MNUMYR)])
    rd = _header(Path(cdm_dir) / "krenew.txt")
    efficacy = f32(0.0)
    try:
        vals = rd.read(1)
        if vals is not None:
            efficacy = f32(vals[0])
        for r in range(1, NUM_DIV + 1):
            for y in range(1, MNUMYR + 1):
                vals = rd.read(6)
                if vals is None:
                    continue
                contrib[r, :, y] = np.array(vals, dtype=f32)
                contrib[r, 6, y] = f32(contrib[r, 6, y] * efficacy)  # lighting
    except EOFError:
        pass
    return efficacy, contrib


def read_kdegday(mc_np: FArray, bld_dir: Path = BLD) -> FArray:
    """DegreeDays (s, r, y): heating (s=1) and cooling (s=2) degree days by division.

    Region 11 is the population-weighted average of the nine divisions, so it needs MC_NP.
    """
    dd = FArray.zeros([(1, 2), (1, NUM_DIV + 2), (1, CM_LAST_YR)])
    rd = _header(Path(bld_dir) / "kdegday.txt")
    try:
        for y in range(1, CM_LAST_YR + 1):
            for s in range(1, 3):
                vals = rd.read(1 + NUM_DIV)
                if vals is not None:
                    dd[s, 1:NUM_DIV, y] = np.array(vals[1:], dtype=f32)
                dd[s, 11, y] = 0.0
                for r in range(1, NUM_DIV + 1):
                    dd[s, 11, y] = f32(dd[s, 11, y] + f32(dd[s, r, y] * f32(mc_np[r, y] / mc_np[11, y])))
    except EOFError:
        pass
    return dd


def read_bldbase(bld_dir: Path = BLD) -> FArray:
    """BASELINEBKWHCM (r, y): baseline electricity for the 111(d) analysis, in billion kWh."""
    out = FArray.zeros([(1, NUM_DIV), (1, MNUMYR)])
    rd = _header(Path(bld_dir) / "bldbase.txt")
    try:
        for r in range(1, NUM_DIV + 1):
            for y in range(1, MNUMYR + 1):
                vals = rd.read(4)
                if vals is None:
                    continue
                out[r, y] = f32(f32(f32(vals[3]) / f32(3412.0)) * f32(1000.0))
    except EOFError:
        pass
    return out
