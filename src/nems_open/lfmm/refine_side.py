"""The two GDX files refine.f computes for LFMM each call: E85.gdx and STEO_Hist.gdx (ports, for run(lfmm="gams")).

E85.gdx (refine.f SUBROUTINE E85_Demand_Curve, 1048-1830). cb2026 reads E85curveSwitch = 2 from rfinvest.txt, the
"hockey stick" E85 availability curve, so only that design is ported. For each census division and each year of LFMM's
three look-ahead periods (LFMM_PERIOD from rfinvest.txt), Qo = FFV fuel demand times the transport model's logit share
of E85 at Po = 1.2 times the gasoline price (LFMM_FFVSHR), and 20 steps around Qo with elasticities 0.6 (left) and
0.3 (right); plus the annualised infrastructure and station costs per step. Years up to AEOLSTYR use current-year
arrays (QFFV, QETTR, QMGAS, PMGTR), later years NEMS's expectations (XQFFV, XQETTR, XQMGAS, XPMGAS).

PMGTRadjSTEO (a STEO price calibration carried in refine.f's COMMON /LFMM_HISTCALIB/ from the STEO years) is phased
out over the five years after STEOLYR (2026 in rfhist.txt) and is zero from 2031; this port writes zero and so is
faithful from 2031 on only.

STEO_Hist.gdx (refine.f 3880-3950, in RFHIST1): STEO crude and product trade series (the STEO block, from steovars.csv
through nems_open.steo), history arrays from PMMRPT, and the switches read from rfhist.txt.

Labels are refine.f's own (not FILER's): years "1990".. in E85.gdx, "1990_MNUMYR" in STEO_Hist.gdx, "CenDiv1"..,
"E85STP_01".., "01_MNUMPR"..
"""

import re
from pathlib import Path

import numpy as np

from nems_open.paths import UPSTREAM

LFMM_INPUT = Path(UPSTREAM) / "models" / "lfmm" / "input"
E85_STEPS = 55
MNUMCR, MNUMYR, MNXYR, MNUMPR = 11, 61, 91, 10
SCEDES_DEFAULTS = {"AEOLSTYR": 2050, "LCFSOPT": 0, "AB32SW": 1, "CO2PLFMM": 1, "CRUDEXP": 0, "LEGIRA": 1}


def _blocks(path: Path) -> list[list[str]]:
    """The lines after each line starting with '@' (PMM_NEXTDATA), up to the next one."""
    out, cur = [], None
    for line in Path(path).read_text(encoding="latin-1").splitlines():
        if line[:1] == "@":
            cur = []
            out.append(cur)
        elif cur is not None:
            cur.append(line)
    return out


def _array(block: list[str], cast=float) -> dict[int, float]:
    n = int(block[0].split()[0])
    return {int(r.split()[0]): cast(r.split()[1]) for r in block[1:1 + n]}


def rfinvest(path: Path = LFMM_INPUT / "rfinvest.txt") -> dict:
    """The reads of E85_Demand_Curve, in its order (design 2)."""
    b = _blocks(path)
    v = lambda i: b[i][0].split()[0]
    d = {"Infrastructure_Year": int(v(0)), "Station_Cost_Year": int(v(1)), "INT_IC": float(v(2)), "NYR_IC": int(v(3)),
         "INT_SC": float(v(4)), "NYR_SC": int(v(5)), "Inc_Avail": float(v(6)), "Cost_per_Station": float(v(7)),
         "TRGNE85": float(v(8)), "ETHNE85": float(v(9)), "Infrastructure_Cost": _array(b[10]),
         "Total_Stations": _array(b[11]), "E85curveSwitch": int(v(12))}
    if d["E85curveSwitch"] != 2:
        raise NotImplementedError("only E85curveSwitch = 2 (cb2026) is ported")
    d.update({"Lower_ELAS": float(v(13)), "Upper_ELAS": float(v(14)), "E85MGexpPrRatio": float(v(15)),
              "Lower_Percents": _array(b[16]), "Upper_Percents": _array(b[17]), "E85AVAIL_Growth": _array(b[18])})
    # 19, 20: the original design's step percents, skipped
    d["LFMM_PERIOD"] = _array(b[21], int)
    d["DR"] = float(v(22))
    hist, last = {}, None
    n = int(b[23][0].split()[0])
    for line in b[23][1:1 + n]:          # (11X,I4,8X,9F8.4)
        yr = int(line[11:15])
        hist[yr] = [float(line[23 + 8 * k: 31 + 8 * k]) for k in range(9)]
        last = yr
    d["E85AVAIL_hist"], d["E85availLYR"] = hist, last
    return d


def _ffvshr(fc0, fc1, fc2, fc3, fc4, region, eth_price, mg_price, avail):
    """refine.f LFMM_FFVSHR: the transport model's logit share of E85 among FFV fuel."""
    gas = np.exp(0.125 * mg_price * fc4)
    alt = np.exp(fc0[region - 1] + 0.125 * eth_price * fc1 - fc2 * np.exp(avail * fc3))
    return alt / (alt + gas)


def e85(arrays: dict, year: int, scedes: dict | None = None) -> dict:
    """E85.gdx's contents for one call (current year `year`), as numpy arrays in Fortran index order."""
    sc = {**SCEDES_DEFAULTS, **(scedes or {})}
    r = rfinvest()
    a = {k.upper(): np.asarray(v, dtype=np.float64) for k, v in arrays.items()}
    g = lambda name: a[name]
    curiyr = year - 1989
    ayr = sc["AEOLSTYR"] - 1989
    periods = [r["LFMM_PERIOD"][i] for i in sorted(r["LFMM_PERIOD"])]
    fph = sum(periods)
    trg, eth = r["TRGNE85"], r["ETHNE85"]

    # 1-based year index helpers
    cur = lambda name, lyr, cd=None: (g(name)[lyr - 1] if cd is None else g(name)[cd - 1, lyr - 1])
    jp = g("MACOUT/MC_JPGDP")                       # starts 1987: index LYR at position LYR + 2
    gdp = np.zeros(MNXYR + 1)
    for lyr in range(1, MNXYR + 1):
        gdp[lyr] = jp[lyr + 2 - 1] if lyr <= ayr else gdp[ayr] * 1.02 if lyr == ayr + 1 else gdp[lyr - 1] * 1.02
    # refine.f: GDP(LYR) = GDP(AYR) * 1.02 for every LYR > AYR (not compounded)
    for lyr in range(ayr + 1, MNXYR + 1):
        gdp[lyr] = gdp[ayr] * 1.02

    trill_bgal = np.zeros(MNXYR); trill_mbbl = np.zeros(MNXYR); mmbtu_bbl = np.zeros(MNXYR)
    for lyr in range(curiyr, curiyr + fph):
        t = min(lyr, ayr)
        cfetq = cur("CONVFACT/CFETQ", t)
        rbob = cur("CONVFACT/CFRBOB", min(lyr, MNUMYR))
        trill_bgal[lyr - 1] = 1.0 / ((1.0 - trg) * cfetq + trg * rbob) * 42.0 / 1000.0
        trill_mbbl[lyr - 1] = 1.0 / ((1.0 - trg) * cfetq + trg * rbob) / 365.0 * 1000.0
        mmbtu_bbl[lyr - 1] = cur("CONVFACT/CFE85Q", min(lyr, MNUMYR))

    # E85 availability: TRANREP E85AVAIL with rfinvest's history rows
    e85avail = g("TRANREP/E85AVAIL").copy()
    for yr, vals in r["E85AVAIL_hist"].items():
        e85avail[:9, yr - 1990] = vals
    nd = MNUMCR - 2
    e85_av = np.zeros((nd + 1, MNXYR + 2))
    test_av = np.zeros((nd + 1, MNXYR + 2))
    q_ffv = np.zeros((nd + 1, MNXYR + 1)); q_mg = np.zeros((nd + 1, MNXYR + 1))
    mogas = np.zeros((MNUMCR, MNXYR))
    jmgtr = g("EMABLK/JMGTR")
    for cd in range(1, nd + 1):
        e85_av[cd, curiyr - 1] = e85avail[cd - 1, curiyr - 2]
    for lyr in range(curiyr, curiyr + fph):
        for cd in range(1, nd + 1):
            if lyr <= ayr:
                q_ffv[cd, lyr] = cur("TRANREP/QFFV", lyr, cd)
                q_mg[cd, lyr] = cur("QBLK/QMGAS", lyr, cd)
                p = cur("MPBLK/PMGTR", lyr, cd)
                mogas[cd - 1, lyr - 1] = p if sc["CO2PLFMM"] == 1 else p + jmgtr[lyr - 1]
                e85_av[cd, lyr] = max(e85avail[cd - 1, lyr - 1] if lyr <= MNUMYR else 0.0, e85_av[cd, lyr - 1])
            else:
                q_ffv[cd, lyr] = cur("TRANREP/XQFFV", lyr, cd)
                q_mg[cd, lyr] = cur("MXQBLK/XQMGAS", lyr, cd)
                p = cur("MXPBLK/XPMGAS", lyr, cd)
                mogas[cd - 1, lyr - 1] = p if sc["CO2PLFMM"] == 1 else p + jmgtr[ayr - 1]
                e85_av[cd, lyr] = e85_av[cd, ayr]
            if lyr <= 30:
                test_av[cd, lyr] = e85_av[cd, lyr]
            elif lyr < 33:
                test_av[cd, lyr] = e85_av[cd, lyr - 1]
            else:
                test_av[cd, lyr] = e85_av[cd, lyr - 1] * (1 + r["E85AVAIL_Growth"][cd])
                if lyr <= 61:
                    e85_av[cd, lyr] = test_av[cd, lyr]

    # step percents and elasticities (design 2)
    nsteps = max(r["Upper_Percents"])
    pct, elas = np.zeros(E85_STEPS), np.zeros(E85_STEPS)
    for s in range(1, nsteps + 1):
        lo, up = r["Lower_Percents"].get(s, 0.0), r["Upper_Percents"].get(s, 0.0)
        if lo > 0:
            elas[s - 1], pct[s - 1] = r["Lower_ELAS"], lo
        elif up > 0:
            elas[s - 1], pct[s - 1] = r["Upper_ELAS"], up
    fc = [g("TRANREP/FCLOGIT0")] + [float(g(f"TRANREP/FCLOGIT{k}")) for k in range(1, 5)]
    shape = (E85_STEPS, MNUMCR, MNXYR)
    A, P, Q = np.zeros(shape), np.zeros(shape), np.zeros(shape)
    po, qo = np.zeros((MNUMCR, MNXYR)), np.zeros((MNUMCR, MNXYR))
    for cd in range(1, nd + 1):
        for lyr in range(curiyr, curiyr + fph):
            po[cd - 1, lyr - 1] = r["E85MGexpPrRatio"] * mogas[cd - 1, lyr - 1]
            qo[cd - 1, lyr - 1] = q_ffv[cd, lyr] * _ffvshr(*fc, cd, po[cd - 1, lyr - 1], mogas[cd - 1, lyr - 1],
                                                           test_av[cd, lyr])
            cum = 0.0
            for s in range(1, nsteps + 1):
                q = qo[cd - 1, lyr - 1] * pct[s - 1]
                Q[s - 1, cd - 1, lyr - 1] = q
                cum += q
                if elas[s - 1] > 0 and qo[cd - 1, lyr - 1] > 0:
                    P[s - 1, cd - 1, lyr - 1] = po[cd - 1, lyr - 1] * ((1 / elas[s - 1]) *
                                                                      ((cum - qo[cd - 1, lyr - 1]) / qo[cd - 1, lyr - 1]) + 1.0)
                A[s - 1, cd - 1, lyr - 1] = test_av[cd, lyr]

    # infrastructure and station costs per step
    sta_cst = r["Cost_per_Station"] / gdp[r["Station_Cost_Year"] - 1989] * 0.000001
    ic, nic, isc, nsc = r["INT_IC"], r["NYR_IC"], r["INT_SC"], r["NYR_SC"]
    crf_ic = (ic * (1 + ic) ** nic) / ((1 + ic) ** nic - 1)
    crf_sc = (isc * (1 + isc) ** nsc) / ((1 + isc) ** nsc - 1)
    IC, SC = np.zeros(shape), np.zeros(shape)
    for lyr in range(curiyr, curiyr + fph):
        for cd in range(1, nd + 1):
            inc = r["Infrastructure_Cost"][cd] / gdp[r["Infrastructure_Year"] - 1989]
            start = 0.0
            for s in range(1, nsteps + 1):
                q = Q[s - 1, cd - 1, lyr - 1]
                mp = start + 0.5 * q
                end = start + q
                if mp > 0:
                    IC[s - 1, cd - 1, lyr - 1] = (mp * trill_bgal[lyr - 1] * eth * inc * crf_ic) / mp
                stations = r["Total_Stations"][cd] * (test_av[cd, lyr] - e85_av[cd, lyr - 1])
                with np.errstate(divide="ignore", invalid="ignore"):
                    SC[s - 1, cd - 1, lyr - 1] = stations * sta_cst * crf_sc / mp
                start = end
    flags = {k: int(sc.get(k, 0)) for k in ("TAX_FLAG", "ELEC_FLAG", "TRAN_FLAG")}
    return {"QoE85": qo, "PoE85": po, "E85_StepsLOOP": nsteps, "E85curveSwitch": 2, "E85_ELAS": elas,
            "PMGTRadjSTEO": np.zeros(MNUMCR), "Q_E85STP_t": Q, "P_E85STP_t": P, "P_E85_IC_t": IC, "P_E85_SC_t": SC,
            "A_E85STP_t": A, "Trill_Btu_to_Bgal": trill_bgal, "Trill_Btu_to_MBBL_CD": trill_mbbl,
            "D_MMBtu_to_D_BBL_CD": mmbtu_bbl, "MOGASPRICE": mogas, "LCFSOPT": sc["LCFSOPT"], "AB32SW": sc["AB32SW"],
            "LEGIRA": sc["LEGIRA"], "CO2PLFMM": sc["CO2PLFMM"], "CRUDEXP": sc["CRUDEXP"],
            "E85availLYR": r["E85availLYR"], **flags}


def _records(arr, labels):
    a = np.asarray(arr, dtype=np.float64)
    rows = []
    for idx in zip(*np.nonzero(a)):
        rows.append(tuple(labels[k][i] for k, i in enumerate(idx)) + (float(a[idx]),))
    return rows


def e85_payload(arrays: dict, year: int, scedes: dict | None = None) -> dict:
    """E85.gdx in gams_io.write_gdx's payload form, with refine.f's labels."""
    d = e85(arrays, year, scedes)
    yrs = [str(1989 + i) for i in range(1, MNXYR + 1)]
    cds = [f"CenDiv{i}" for i in range(1, MNUMCR + 1)]
    stp = [f"E85STP_{i:02d}" for i in range(1, E85_STEPS + 1)]
    p = {"sets": {"MNXYR": yrs, "CenDiv": cds, "E85_Steps": stp}, "params": {}, "scalars": {}}
    dims = {3: (["E85_Steps", "CenDiv", "MNXYR"], [stp, cds, yrs])}
    for name, v in d.items():
        v = np.asarray(v)
        if v.ndim == 0:
            p["scalars"][name] = float(v)
        elif v.shape == (MNUMCR, MNXYR):
            p["params"][name] = (["CenDiv", "MNXYR"], _records(v, [cds, yrs]), "")
        elif v.shape == (MNXYR,):
            p["params"][name] = (["MNXYR"], _records(v, [yrs]), "")
        elif v.shape == (MNUMCR,):
            p["params"][name] = (["CenDiv"], _records(v, [cds]), "")
        elif v.shape == (E85_STEPS,):
            p["params"][name] = (["E85_Steps"], _records(v, [stp]), "")
        else:
            nm, lb = dims[v.ndim]
            p["params"][name] = (nm, _records(v, lb), "")
    return p


def rfhist_switches(path: Path = LFMM_INPUT / "rfhist.txt") -> dict:
    """LFadjsteoON, HISTLYR, STEOLYR, LFadjvolON, NumPhaseoutYrs, PhaseoutFactor (RFHIST1's first reads)."""
    b = _blocks(path)
    s1 = b[0][0].split()
    s3 = b[2][0].split()
    return {"LFadjsteoON": int(s1[0]), "HISTLYR": int(s1[1]), "STEOLYR": int(s1[2]),
            "LFadjvolON": int(s3[0]), "NumPhaseoutYrs": int(s3[1]), "PhaseoutFactor": float(s3[2])}


def steo_hist_payload(arrays: dict) -> dict:
    """STEO_Hist.gdx in gams_io.write_gdx's payload form."""
    from nems_open import steo
    a = {k.upper(): np.asarray(v, dtype=np.float64) for k, v in arrays.items()}
    sw = rfhist_switches()
    v = steo.load()
    yrs = [f"{1989 + i}_MNUMYR" for i in range(1, MNUMYR + 1)]
    prs = [f"{i:02d}_MNUMPR" for i in range(1, MNUMPR + 1)]
    cds = [f"CenDiv{i}" for i in range(1, MNUMCR + 1)]
    m2 = ["1_M2", "2_M2"]
    p = {"sets": {"MNUMYR": yrs, "MNUMPR": prs, "CenDiv": cds, "M2": m2}, "params": {}, "scalars": {}}
    for name in ("CONIPUS", "CORIPUS", "UONIPUS", "PANIPUS", "MBNIPUS", "OHNIPUS"):
        series = np.zeros(MNUMYR)
        s = np.asarray(v[name.lower()], dtype=np.float64)[:MNUMYR]
        series[:len(s)] = s
        p["params"][f"STEO_{name}"] = (["MNUMYR"], _records(series, [yrs]), "")
    for name in ("RFQEXCRD", "RFQICRD", "RFQEXPRDT", "BLDIMP"):
        p["params"][f"HIST_{name}"] = (["MNUMPR", "MNUMYR"], _records(a[f"PMMRPT/{name}"], [prs, yrs]), "")
    for name in ("RFPQIPRDT", "RFPQUFC"):
        p["params"][f"HIST_{name}"] = (["MNUMPR", "MNUMYR", "M2"], _records(a[f"PMMRPT/{name}"], [prs, yrs, m2]), "")
    for k in ("STEOLYR", "HISTLYR", "LFadjvolON", "NumPhaseoutYrs", "PhaseoutFactor"):
        p["scalars"][k] = float(sw[k])
    return p


def restart_inputs(case: str = "cb2026") -> dict:
    """The restart arrays e85() and steo_hist_payload() read, keyed "BLOCK/NAME"."""
    from nems_open.supply_standin.data import restart_path
    z = np.load(restart_path(case), allow_pickle=False)
    names = {k.upper(): k for k in z.files}
    want = ["MACOUT/MC_JPGDP", "CONVFACT/CFETQ", "CONVFACT/CFRBOB", "CONVFACT/CFE85Q", "TRANREP/E85AVAIL",
            "TRANREP/QFFV", "TRANREP/XQFFV", "QBLK/QMGAS", "MXQBLK/XQMGAS", "MPBLK/PMGTR", "MXPBLK/XPMGAS",
            "EMABLK/JMGTR", "TRANREP/FCLOGIT0", "TRANREP/FCLOGIT1", "TRANREP/FCLOGIT2", "TRANREP/FCLOGIT3",
            "TRANREP/FCLOGIT4", "PMMRPT/RFQEXCRD", "PMMRPT/RFQICRD", "PMMRPT/RFQEXPRDT", "PMMRPT/RFPQIPRDT",
            "PMMRPT/BLDIMP", "PMMRPT/RFPQUFC"]
    return {k: z[names[k]] for k in want}
