"""Macro and price setup for the industrial module: port of Setup_Mac_and_Price (ind.f).

Runs at the top of every iteration of every year, before ISEAM:
- OUTIND (output by industry and census division) and EMPIND (employment) from the macro
  model's MC_REVIND and MC_EMPNA, with the NAICS-to-industry splits EIA hard-codes; chemical and
  food shipments by sub-industry; forest residue output added to other agriculture.
- Division prices by fuel (DPRCX: carbon-adjusted (1) and unadjusted (2), this year and lagged),
  weighted into census-region prices (PRCX, PRCXLAG) by last year's consumption (or SEDS in
  history years), and the same for region 5 (US) from division 11.
- PRCXYR (price history by year) and, in the base year, PRCXIBYR. BUSHEL (corn) is not ported.

California carbon (AB 32, ab32=True; the oracle's reference case has it on): division 9 carbon-adjusted
prices add the allowance price (ab_allow_p) times each fuel's emission factor.

Works on an oracle-style state dict and updates it in place.
"""

import numpy as np

f32 = np.float32
REGION = (0, 1, 1, 2, 2, 3, 3, 3, 4, 4, 4, 5)  # census division -> census region, 1-based
DIVISION = (11, 1, 2, 5, 5, 5, 3, 3, 6, 6, 4, 4, 7, 8, 8, 8, 9)  # EMM-style region 0..16 -> census division
REGIONS = {1: (1, 2), 2: (3, 4), 3: (5, 6, 7), 4: (8, 9)}

# price series by fuel slot 1..23 for the carbon-adjusted (1) and unadjusted (2) prices
ADJ = ["aelin", "ph2in", "agfin", "agiin", "agfin", "alpin", "aclin", "amcin", "amcin", "arlin", "adsin", "algin", "alginpf",
       "amgin", "arsin", "apcin", "aasin", "arsin", "apfin", "aksin", "arsin", "aotin", "ph2in"]
UNADJ = ["pelin", "ph2in", "pgfin", "pgiin", "pgfin", "plpin", "pclin", "pmcin", "pmcin", "prlin", "pdsin", "plgin", "plginpf",
         "pmgin", "prsin", "ppcin", "pasin", "prsin", "ppfin", "pksin", "prsin", "potin", "ph2in"]
ADJ_US = ADJ.copy()
ADJ_US[12] = "algin"  # the US row has no separate HGL feed price on the adjusted side
UEL = ["pelinp", "pelins", "pelinm", "pelinh2e"]  # slots 24..27
# consumption weights by fuel slot, SEDS years and after (QSxxIN = SEDS, QxxIN = model)
SEDS_W = ["qselin", "qh2inpf", "qsngin", "qsngin", "qsngin", "qslpin", "qsclin", "qsmcin", "qsmcin", "qsrsin", "qsdsin",
          ("qslgin", "qsppin"), "qslgin", "qsmgin", "qssgin", "qspcin", "qsasin", "qsotin", "qspfin", "qsksin", "qsotin",
          "qsotin", "qh2inhp"]
MODEL_W = ["qelin", "qh2inpf", "qgfin", "qgiin", "qgiin", ("qlpin", "qnglq"), "qclin", "qmcin", "qmcin", "qrlin", "qdsin",
           "qlgin", "qlgin", "qmgin", "qsgin", "qpcin", "qasin", "qotin", "qpfin", "qksin", "qotin", "qotin", "qh2inhp"]
UEL_W = ["qelinp", "qelins", "qelinm", "qelinh2e"]


def _outind_empind(s: dict) -> None:
    curiyr, curcalyr, ibyr = int(s["curiyr"]), int(s["curcalyr"]), int(s["ibyr"])
    rev, emp, out, empind = s["mc_revind"], s["mc_empna"], s["outind"], s["empind"]
    chem, food = s["chemship"], s["foodship"]
    jpgdp = f32(s["mc_jpgdp"][23])
    resid = [f32(0.0)] * 12
    qb, pb = s["qbmascl"], s["pbmascl"]
    for co in range(0, 17):
        d = DIVISION[co]
        resid[d] = f32(resid[d] + f32(f32(f32(qb[2, co, curiyr] * pb[2, co, curiyr]) * jpgdp) / f32(1000.0)))
    chem[:, :, curcalyr] = 0.0
    food[:, :, curcalyr] = 0.0
    other = f32(f32(1.0) - f32(0.91))
    for d in range(1, 12):
        r = REGION[d]
        out[1, d, curiyr] = rev[d, 42, curiyr]
        out[2, d, curiyr] = f32(f32(f32(rev[d, 44, curiyr] + rev[d, 43, curiyr])) + resid[d])
        out[3, d, curiyr] = rev[d, 45, curiyr]
        out[4, d, curiyr] = rev[d, 46, curiyr]
        out[5, d, curiyr] = rev[d, 47, curiyr]
        out[6, d, curiyr] = rev[d, 48, curiyr]
        out[7, d, curiyr] = rev[d, 1, curiyr]
        out[8, d, curiyr] = rev[d, 10, curiyr]
        out[9, d, curiyr] = f32(f32(f32(rev[d, 15, curiyr] + rev[d, 16, curiyr]) + rev[d, 18, curiyr]) + rev[d, 19, curiyr])
        for k, m in ((1, 15), (2, 16), (3, 18), (4, 19)):
            chem[k, r, curcalyr] = f32(chem[k, r, curcalyr] + rev[d, m, curiyr])
        chem[5, r, curcalyr] = f32(chem[5, r, curcalyr] + out[9, d, curiyr])
        for k, m in ((6, 51), (7, 52), (8, 49), (9, 50)):
            chem[k, r, curcalyr] = f32(chem[k, r, curcalyr] + rev[d, m, curiyr])
        for k, m in ((1, 2), (2, 3), (3, 4), (4, 5)):
            food[k, r, curcalyr] = f32(food[k, r, curcalyr] + rev[d, m, curiyr])
        food[5, r, curcalyr] = f32(food[5, r, curcalyr] + out[7, d, curiyr])
        out[10, d, curiyr] = rev[d, 28, curiyr]
        out[12, d, curiyr] = f32(rev[d, 33, curiyr] + f32(rev[d, 26, curiyr] * other))
        out[13, d, curiyr] = rev[d, 34, curiyr]
        out[14, d, curiyr] = rev[d, 36, curiyr]
        out[15, d, curiyr] = rev[d, 37, curiyr]
        out[16, d, curiyr] = rev[d, 38, curiyr]
        out[17, d, curiyr] = rev[d, 39, curiyr]
        out[18, d, curiyr] = rev[d, 40, curiyr]
        out[19, d, curiyr] = rev[d, 8, curiyr]
        out[20, d, curiyr] = rev[d, 27, curiyr]
        out[21, d, curiyr] = rev[d, 20, curiyr]
        out[22, d, curiyr] = rev[d, 32, curiyr]
        out[23, d, curiyr] = rev[d, 35, curiyr]
        t = f32(rev[d, 6, curiyr] + rev[d, 7, curiyr])
        t = f32(t + rev[d, 9, curiyr])
        t = f32(t + rev[d, 14, curiyr])
        t = f32(t + f32(rev[d, 26, curiyr] * f32(0.91)))
        out[24, d, curiyr] = f32(t + rev[d, 41, curiyr])
        out[25, d, curiyr] = rev[d, 30, curiyr]
        out[26, d, curiyr] = rev[d, 31, curiyr]
        out[11, d, curiyr] = f32(out[25, d, curiyr] + out[26, d, curiyr])
        if d == 11:
            s["limeoutput"][curiyr] = out[26, d, curiyr]
        if curcalyr == ibyr:
            s["limeibyr"] = rev[d, 31, curiyr]
            s["cementibyr"] = rev[d, 30, curiyr]
            s["alumibyr"] = rev[d, 34, curiyr]
            # GL_shipping (glass sub-industry shipments in the base year) is not ported; the dump carries them
    for d in range(1, 12):
        def e(k):
            return emp[d, k, curiyr]
        empind[1, d] = e(20)
        empind[2, d] = e(21)
        empind[3, d] = e(22)
        empind[4, d] = e(23)
        empind[5, d] = e(24)
        empind[6, d] = f32(f32(e(25) + e(26)) + e(27))
        empind[7, d] = e(1)
        empind[8, d] = e(6)
        empind[9, d] = e(8)
        empind[10, d] = f32(e(12) * f32(0.193))
        empind[11, d] = f32(e(12) * f32(0.253))
        empind[12, d] = f32(f32(e(13) * f32(0.373)) + f32(e(10) * f32(0.038)))
        empind[13, d] = f32(e(13) * f32(0.248))
        for k, m in ((14, 14), (15, 15), (16, 16), (17, 17), (18, 18), (19, 4), (20, 11), (21, 9)):
            empind[k, d] = e(m)
        empind[22, d] = f32(e(12) * f32(0.554))
        empind[23, d] = f32(e(13) * f32(0.379))
        t = f32(f32(f32(f32(e(2) + e(3)) + e(5)) + e(7)) + f32(e(10) * f32(0.382)))
        empind[24, d] = f32(t + e(19))


def _wsum(s, spec, d, y):
    if isinstance(spec, tuple):
        t = s[spec[0]][d, y]
        for n in spec[1:]:
            t = f32(t + s[n][d, y])
        return t
    return s[spec][d, y]


def _fill_dprcx(s, dst, y):
    """DPRCX / DPRCXLAG for year index y (curiyr for this year, curiyr-1 for the lag)."""
    for d in range(1, 12):
        for f, n in enumerate(ADJ, start=1):
            dst[f, d, 1] = s[n][d, y]
        for f, n in enumerate(UNADJ, start=1):
            dst[f, d, 2] = s[n][d, y]
        for k, n in enumerate(UEL):
            dst[24 + k, d, 1] = s[n][d, y]
            dst[24 + k, d, 2] = s[n][d, y]


def _prcx_from_dprcx(dprcx, prcx, dconx):
    for ib in (1, 2):
        for f in range(1, 28):
            for r, divs in REGIONS.items():
                w = [dconx[f, d] for d in divs]
                tot = w[0]
                for x in w[1:]:
                    tot = f32(tot + x)
                if tot > 0.0:
                    num = f32(dprcx[f, divs[0], ib] * w[0])
                    for d, x in zip(divs[1:], w[1:]):
                        num = f32(num + f32(dprcx[f, d, ib] * x))
                    prcx[f, r, ib] = f32(num / tot)
                else:
                    t = dprcx[f, divs[0], ib]
                    for d in divs[1:]:
                        t = f32(t + dprcx[f, d, ib])
                    prcx[f, r, ib] = f32(t / f32(float(len(divs))))


def _ab32_division9(s, dprcx, curiyr):
    iyy = max(curiyr, 6)
    ab = s["ab_allow_p"][curiyr]
    e = {2: s["engin"][iyy], 3: s["eclin"][iyy], 4: s["emcin"][iyy], 5: s["eclin"][iyy], 6: s["erlin"][iyy],
         10: s["esgin"][iyy], 11: s["epcin"][iyy], 13: s["epfin"][iyy], 15: s["eotin"][iyy],
         16: s["enqngpf"][iyy]}
    zero = f32(0.0)
    d = 9
    plus = lambda base, k: f32(s[base][d, curiyr] + f32(e[k] * ab))
    dprcx[1, d, 1] = f32(s["aelin"][d, curiyr] + zero)
    dprcx[2, d, 1] = s["ph2in"][d, curiyr]
    dprcx[3, d, 1] = plus("agfin", 2)
    dprcx[4, d, 1] = plus("agiin", 2)
    dprcx[5, d, 1] = plus("agfin", 16)
    dprcx[6, d, 1] = plus("alpin", 2)
    dprcx[7, d, 1] = plus("aclin", 3)
    dprcx[8, d, 1] = plus("amcin", 4)
    dprcx[9, d, 1] = plus("amcin", 5)
    dprcx[10, d, 1] = plus("arlin", 6)
    dprcx[11, d, 1] = f32(s["adsin"][d, curiyr] + zero)
    dprcx[12, d, 1] = f32(s["algin"][d, curiyr] + zero)
    dprcx[13, d, 1] = f32(s["alginpf"][d, curiyr] + zero)
    dprcx[14, d, 1] = f32(s["amgin"][d, curiyr] + zero)
    dprcx[15, d, 1] = plus("arsin", 10)
    dprcx[16, d, 1] = plus("apcin", 11)
    dprcx[17, d, 1] = f32(s["aasin"][d, curiyr] + zero)
    dprcx[18, d, 1] = plus("arsin", 6)
    dprcx[19, d, 1] = plus("apfin", 13)
    dprcx[20, d, 1] = f32(s["aksin"][d, curiyr] + zero)
    dprcx[21, d, 1] = zero
    dprcx[22, d, 1] = plus("aotin", 15)
    dprcx[23, d, 1] = s["ph2in"][d, curiyr]


def _ab32_division9_unadjusted(s, dprcx, curiyr, curcalyr, ibyr):
    """The second AB 32 block: the unadjusted (2) division 9 prices carry the allowance price for natural gas and
    residual fuel from the base year on; in earlier years the markup for carbon is removed from some liquids."""
    iyy = max(curiyr, 6)
    ab = s["ab_allow_p"][curiyr]
    e = {2: s["engin"][iyy], 6: s["erlin"][iyy], 7: s["edsin"][iyy], 8: s["elgin"][iyy], 9: s["emgin"][iyy],
         14: s["eksin"][iyy], 16: s["enqngpf"][iyy], 17: s["enqlgpf"][iyy]}
    d = 9
    cur = curiyr
    if curcalyr >= ibyr:
        dprcx[3, d, 2] = f32(s["pgfin"][d, cur] + f32(e[2] * ab))
        dprcx[4, d, 2] = f32(s["pgiin"][d, cur] + f32(e[2] * ab))
        dprcx[5, d, 2] = f32(s["pgfin"][d, cur] + f32(e[16] * ab))
        dprcx[6, d, 2] = f32(s["plpin"][d, cur] + f32(e[2] * ab))
        dprcx[10, d, 2] = f32(s["prlin"][d, cur] + f32(e[6] * ab))
        dprcx[18, d, 2] = f32(s["prsin"][d, cur] + f32(e[6] * ab))
    else:
        dprcx[11, d, 2] = f32(s["pdsin"][d, cur] - f32(e[7] * ab))
        dprcx[12, d, 2] = f32(s["plgin"][d, cur] - f32(e[8] * ab))
        dprcx[13, d, 2] = f32(s["plginpf"][d, cur] - f32(e[17] * ab))
        dprcx[14, d, 2] = f32(s["pmgin"][d, cur] - f32(e[9] * ab))
        dprcx[20, d, 2] = f32(s["pksin"][d, cur] - f32(e[14] * ab))


def _emis(s, iyy):
    return {2: s["engin"][iyy], 3: s["eclin"][iyy], 4: s["emcin"][iyy], 5: s["eclin"][iyy], 6: s["erlin"][iyy],
            7: s["edsin"][iyy], 8: s["elgin"][iyy], 9: s["emgin"][iyy], 10: s["esgin"][iyy], 11: s["epcin"][iyy],
            13: s["epfin"][iyy], 14: s["eksin"][iyy], 15: s["eotin"][iyy], 16: s["enqngpf"][iyy], 17: s["enqlgpf"][iyy]}


def _ab32_division9_lag(s, dprcxlag, curiyr, curcalyr, ibyr):
    """AB 32 for the lagged prices: carbon-adjusted (1) uses last year's allowance price and emission factors;
    unadjusted (2) uses last year's allowance price with this year's factors (EIA's iyy)."""
    iy = curiyr - 1
    ab = s["ab_allow_p"][iy]
    d = 9
    f32z = f32(0.0)
    e = _emis(s, max(curiyr - 1, 6))
    plus = lambda name, k: f32(s[name][d, iy] + f32(e[k] * ab))
    zero = lambda name: f32(s[name][d, iy] + f32z)
    L = dprcxlag
    L[1, d, 1] = zero("aelin")
    L[3, d, 1] = plus("agfin", 2)
    L[4, d, 1] = plus("agiin", 2)
    L[5, d, 1] = plus("agfin", 16)
    L[6, d, 1] = plus("alpin", 2)
    L[7, d, 1] = plus("aclin", 3)
    L[8, d, 1] = plus("amcin", 4)
    L[9, d, 1] = plus("amcin", 5)
    L[10, d, 1] = plus("arlin", 6)
    L[11, d, 1] = zero("adsin")
    L[12, d, 1] = zero("algin")
    L[13, d, 1] = zero("alginpf")
    L[14, d, 1] = zero("amgin")
    L[15, d, 1] = plus("arsin", 10)
    L[16, d, 1] = plus("apcin", 11)
    L[17, d, 1] = zero("aasin")
    L[18, d, 1] = plus("arsin", 6)
    L[19, d, 1] = plus("apfin", 13)
    L[20, d, 1] = zero("aksin")
    L[21, d, 1] = plus("arsin", 13)
    L[22, d, 1] = plus("aotin", 15)
    e = _emis(s, max(curiyr, 6))
    plus = lambda name, k: f32(s[name][d, iy] + f32(e[k] * ab))
    if curcalyr > ibyr:
        L[3, d, 2] = plus("pgfin", 2)
        L[4, d, 2] = plus("pgiin", 2)
        L[5, d, 2] = plus("pgfin", 16)
        L[6, d, 2] = plus("plpin", 2)
        L[10, d, 2] = plus("prlin", 6)
        L[18, d, 2] = plus("prsin", 6)
    else:
        L[11, d, 2] = f32(s["pdsin"][d, iy] - f32(e[7] * ab))
        L[12, d, 2] = f32(s["plgin"][d, iy] - f32(e[8] * ab))
        L[13, d, 2] = f32(s["plginpf"][d, iy] - f32(e[17] * ab))
        L[14, d, 2] = f32(s["pmgin"][d, iy] - f32(e[9] * ab))
        L[20, d, 2] = f32(s["pksin"][d, iy] - f32(e[14] * ab))


def setup_mac_and_price(s: dict, ab32: bool = True) -> None:
    curiyr, curcalyr = int(s["curiyr"]), int(s["curcalyr"])
    ibyr2, sedslastyr = int(s["ibyr2"]), int(s["sedslastyr"])
    _outind_empind(s)
    iy = curiyr - 1

    # electricity prices by load type: zero or missing this year -> last year's
    for n in UEL:
        for d in range(1, 12):
            if s[n][d, curiyr] <= 0:
                s[n][d, curiyr] = s[n][d, curiyr - 1]

    dprcx, dprcxlag, prcx, prcxlag, dconx = s["dprcx"], s["dprcxlag"], s["prcx"], s["prcxlag"], s["dconx"]
    _fill_dprcx(s, dprcx, curiyr)
    _fill_dprcx(s, dprcxlag, iy)
    if ab32 and curcalyr >= ibyr2:
        _ab32_division9(s, dprcx, curiyr)
        _ab32_division9_unadjusted(s, dprcx, curiyr, curcalyr, int(s["ibyr"]))
        _ab32_division9_lag(s, dprcxlag, curiyr, curcalyr, int(s["ibyr"]))

    # consumption weights: SEDS in history years, last year's model result after
    if curcalyr <= sedslastyr:
        for d in range(1, 12):
            for f, n in enumerate(SEDS_W, start=1):
                dconx[f, d] = _wsum(s, n, d, curiyr)
            for k, n in enumerate(UEL_W):
                dconx[24 + k, d] = s[n][d, curiyr]
    else:
        for d in range(1, 12):
            for f, n in enumerate(MODEL_W, start=1):
                dconx[f, d] = _wsum(s, n, d, iy)
            for k, n in enumerate(UEL_W):
                dconx[24 + k, d] = s[n][d, iy]
    _prcx_from_dprcx(dprcx, prcx, dconx)
    _prcx_from_dprcx(dprcxlag, prcxlag, dconx)

    # region 5 (US) from division 11
    for ib, series, y, dst in ((1, ADJ_US, curiyr, prcx), (2, UNADJ, curiyr, prcx),
                               (1, ADJ_US, iy, prcxlag), (2, UNADJ, iy, prcxlag)):
        for f, n in enumerate(series, start=1):
            dst[f, 5, ib] = s[n][11, y]
        for k, n in enumerate(UEL):
            dst[24 + k, 5, ib] = s[n][11, y]
    for dst in (prcx, prcxlag):
        for r in range(1, 6):
            for ib in (1, 2):
                dst[42, r, ib] = f32(2.0)
        for r in range(1, 6):
            for ib in (1, 2):
                dst[31, r, ib] = f32(f32(f32(dst[4, r, ib] + dst[7, r, ib]) + dst[10, r, ib]) / f32(3.0))

    if curcalyr == ibyr2:
        for r in range(1, 5):
            s["prcxibyr"][1, r] = prcx[4, r, 1]
            s["prcxibyr"][2, r] = prcx[7, r, 1]
            s["prcxibyr"][3, r] = prcx[10, r, 1]
            s["prcxibyr"][4, r] = prcx[1, r, 1]
    for f in range(1, 51):
        for r in range(1, 5):
            for ib in (1, 2):
                s["prcxyr"][f, r, curiyr, ib] = prcx[f, r, ib]
