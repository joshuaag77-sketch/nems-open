"""Benchmark industrial fuel use to SEDS and STEO, then write QBLK: port of WEXOG (ind.f).

Model results by fuel and census region (BMAIN, from TQMAIN) are scaled by benchmark
factors BF:
- up to the last SEDS year, BF_SEDS = SEDS / model, then rescaled so the national total
  matches SEDS exactly (BFCHECK);
- in STEO years, BF_STEO = STEO total / (model x BF_SEDS) by fuel, national;
- afterwards BF = (1 - FADE) x BF_SEDS + FADE x BF_STEO x BF_SEDS, with FADE 1 through the
  last STEO year and a quarter-sine fade to 0 over the next 12 years. BF_SEDS and BF_STEO
  are locals of EIA's routine that keep their last values, so they live in the state
  (s["bf_seds"] ...) and a run must carry them from the year they were last computed.
Feedstock fuels (natural gas, HGL, naphtha, asphalt) are pinned to read-in series
(FEEDNGTOTAL, FEEDHGLTOTAL, FEEDNAPHTOTAL, asphalt target) instead.
QBLK industrial fuels by census division are then BMAIN_ADJUSTED x the division's share of
the last SEDS year, plus refinery, ethanol, hydrogen-plant and oil-and-gas terms that other
modules supply.

Works on an oracle-style state dict and updates it in place.

Scope: years up to the last read-in feedstock year (2027). Later years switch to a naphtha
versus ethane cracking model for petrochemical feedstocks and raise NotImplementedError.
Not ported: the split of HGL into feedstock and heat-and-power (INQLGPF, INQLGHP, overwritten near the end of
WEXOG from the ethane, propane and propylene series, so they differ from the oracle; and so QLGIN before 2027), ethane, propane, propylene feedstock series (QETINPF ...), asphalt target
updates after SEDS year + 5, hydrogen byproduct index, and the debug writes.

Quirks kept on purpose:
- STEO(6) (lease and plant fuel) is never set, so its factor is 0; SEDS9(.,6) likewise.
- BMAIN(20) is never set (0).
- In SEDS years the totals row SEDS9(11,.) is only filled on the first-iteration pass.
"""

import math

import numpy as np

f32 = np.float32
DIV_TO_REG = {1: 1, 2: 1, 3: 2, 4: 2, 5: 3, 6: 3, 7: 3, 8: 4, 9: 4}
DIVS_OF_REG = {1: (1, 2), 2: (3, 4), 3: (5, 6, 7), 4: (8, 9)}
FEEDNGPERCENT = {1: f32(0.11), 2: f32(0.0), 3: f32(0.89), 4: f32(0.0)}
FEEDHGLPERCENT = {1: f32(0.01), 2: f32(0.03), 3: f32(0.96), 4: f32(0.0)}
NAPHTHA_DIV_FRAC = {1: f32(0.0), 2: f32(0.0), 3: f32(1.0), 4: f32(0.0)}
COALCOKEIMPORT = (None, 0.0, 0.28, 0.41, 0.01, -0.02, 0.0, 0.31, 0.0, 0.01, 0.0, 1.0)
END_YR_FEEDSTOCK = 2027
ICURIYR = 33
FADEYRS = 12
CFELQ_DIV = f32(1.0e9)


def fade_factor(curcalyr: int, sedslastyr: int, steolastyr: int, indbmov: int = 0, fadexyrs: int = FADEYRS) -> np.float32:
    if not (curcalyr > sedslastyr and curcalyr <= steolastyr + fadexyrs - indbmov):
        return f32(0.0)
    if curcalyr <= steolastyr - indbmov:
        return f32(1.0)
    for ix in range(1, fadexyrs + 1):
        if curcalyr == steolastyr + ix - indbmov:
            pi = f32(3.1415927)
            return f32(max(0.0, 1.0 - float(f32(math.sin(float(pi / f32(2.0) * f32(ix) / f32(fadexyrs)))))))
    return f32(0.0)


def divshr(a, icd: int, icr: int) -> np.float32:
    """a: the 11 values of a by-division series (1-based, indexable a[1]..a[11])."""
    divs = DIVS_OF_REG[icr]
    tot = f32(0.0)
    for d in divs:
        tot = tot + f32(a[d])
    if tot != 0.0:
        return f32(f32(a[icd]) / tot)
    return f32(1.0 / len(divs))


def _col(arr, col):
    """The 11 divisions of a (division, year) array at one year, as a dict-like list."""
    return [None] + [f32(arr[d, col]) for d in range(1, 12)]


def _sumc(vals9, icr: int) -> np.float32:
    t = f32(0.0)
    for d in DIVS_OF_REG[icr]:
        t = t + f32(vals9[d])
    return t


def wexog(s: dict, indbmovr2: int = 0) -> None:
    curiyr, curcalyr, msedyr = int(s["curiyr"]), int(s["curcalyr"]), int(s["msedyr"])
    steolastyr = int(s["steolastyr"])
    sedslastyr = msedyr + 1989
    feedyears = END_YR_FEEDSTOCK - sedslastyr
    iy = int(s["iyr"]) - 1989
    mainfuels = int(s["mainfuels"])
    mf = mainfuels - 1
    fcrl = int(s["fcrl"])
    if curcalyr > END_YR_FEEDSTOCK:
        raise NotImplementedError("petrochemical cracking model after the last feedstock year is not ported")

    tq, tr = s["tqmain"], s["tqrenw"]
    bmain = np.zeros((mf + 1, 6), dtype=f32)  # [fuel 1..23, region 1..5]
    firm = np.zeros(6, dtype=f32)
    for r in range(1, 5):
        for f in range(1, 20):
            bmain[f, r] = tq[f, r]
        bmain[21, r] = f32(tq[21, r]) + f32(tq[22, r])
        bmain[22, r] = bmain[21, r]
        bmain[23, r] = 0.0
        d = f32(bmain[3, r]) + f32(bmain[4, r])
        firm[r] = f32(bmain[3, r] / d) if d > 0 else f32(0.0)
    for f in range(1, mf + 1):
        t = f32(0.0)
        for r in range(1, 5):
            t = t + bmain[f, r]
        bmain[f, 5] = t
    with np.errstate(all="ignore"):
        firm[5] = f32(bmain[3, 5] / (f32(bmain[3, 5]) + f32(bmain[4, 5])))
    s["firmshr"][1:5] = firm[1:6]

    brenew = np.zeros((9, 6), dtype=f32)
    for r in range(1, 5):
        brenew[1, r] = tr[1, r]
        brenew[2, r] = f32(tr[2, r]) + f32(tr[3, r])
        brenew[3, r] = brenew[2, r]
        for f in (4, 5, 6, 7, 8):
            brenew[f, r] = tr[f, r]
    for f in range(1, 9):
        t = f32(0.0)
        for r in range(1, 5):
            t = t + brenew[f, r]
        brenew[f, 5] = t

    fade = fade_factor(curcalyr, sedslastyr, steolastyr, indbmovr2)
    bf_seds, rbf_seds, bf_steo, rbf_steo = s["bf_seds"], s["rbf_seds"], s["bf_steo"], s["rbf_steo"]
    feedng, feedhgl, feednaph = s["feedngtotal"], s["feedhgltotal"], s["feednaphtotal"]
    fi = curiyr - ICURIYR + 1

    def q(name, d, y):
        return f32(s[name][d, y])

    if curiyr <= msedyr:
        seds9 = np.zeros((12, mf + 1), dtype=f32)
        rseds9 = np.zeros((12, 9), dtype=f32)
        for d in range(1, 10):
            seds9[d, 1] = (q("qselin", d, curiyr) - q("qelrf", d, curiyr) - f32(s["qeleth"][curiyr, d]) - q("qelhm", d, curiyr)
                           - q("qngpin", d, curiyr) - f32(s["co2_elec"][d, curiyr]) * f32(s["cfelq"]) / CFELQ_DIV)
            seds9[d, 2] = 0.0
        qsngin_c = _col(s["qsngin"], curiyr)
        qslgin_c = _col(s["qslgin"], curiyr)
        for d in range(1, 10):
            r = DIV_TO_REG[d]
            if curiyr >= ICURIYR:
                seds9[d, 5] = f32(feedng[fi]) * FEEDNGPERCENT[r] * divshr(qsngin_c, d, r)
            seds9[d, 3] = (q("qsngin", d, curiyr) - q("qngrf", d, curiyr) - f32(s["qngeth"][curiyr, d]) - seds9[d, 5]
                           - f32(s["cgogsq"][d, curiyr, 3]) - q("qnghmhp", d, curiyr) - q("qnghmpf", d, curiyr)) * firm[r]
            with np.errstate(all="ignore"):
                seds9[d, 4] = seds9[d, 3] * (f32(1.0) - firm[r]) / firm[r]
            seds9[d, 7] = (q("qsclin", d, curiyr) - q("qclrf", d, curiyr) - f32(s["qcleth"][curiyr, d]) - f32(s["cgogsq"][d, curiyr, 1])
                           - f32(s["ogsupgas"][1, d, curiyr]) * f32(s["cfngc"][curiyr]))
            seds9[d, 8] = q("qsmcin", d, curiyr)
            seds9[d, 9] = q("qsciin", 11, curiyr) * f32(COALCOKEIMPORT[d])
            seds9[d, 10] = q("qsrsin", d, curiyr) - q("qrlrf", d, curiyr) - f32(s["cgogsq"][d, curiyr, 2])
            seds9[d, 11] = q("qsdsin", d, curiyr) - q("qdsrf", d, curiyr)
            if curiyr >= ICURIYR:
                seds9[d, 13] = f32(feedhgl[fi]) * FEEDHGLPERCENT[r] * divshr(qslgin_c, d, r)
            seds9[d, 12] = q("qslgin", d, curiyr) - q("qlgrf", d, curiyr) - seds9[d, 13]
            seds9[d, 14] = q("qsmgin", d, curiyr)
            seds9[d, 15] = 0.0
            seds9[d, 16] = q("qspcin", d, curiyr) - q("qpcrf", d, curiyr) - q("qccrf", d, curiyr)
            seds9[d, 17] = q("qsasin", d, curiyr)
            seds9[d, 18] = q("qsluin", d, curiyr)
            seds9[d, 19] = q("qspfin", d, curiyr)
            seds9[d, 20] = q("qsksin", d, curiyr)
            seds9[d, 21] = q("qsotin", d, curiyr) - q("qotrf", d, curiyr)
            seds9[d, 22] = seds9[d, 21]
            seds9[d, 23] = 0.0
            rseds9[d, 1] = q("qshoin", d, iy)
            rseds9[d, 2] = q("qsbmin", d, curiyr)
            rseds9[d, 3] = q("qsbmin", d, curiyr)
            rseds9[d, 8] = q("qsmsin", d, curiyr)
        for f in range(1, mf + 1):
            if f != 9:
                for d in range(1, 10):
                    seds9[d, f] = max(f32(0.0), seds9[d, f])
        if fcrl == 1:
            for f in range(1, mf + 1):
                seds9[11, f] = np.add.reduce(seds9[1:10, f], dtype=f32)
            for f in range(1, 9):
                rseds9[11, f] = np.add.reduce(rseds9[1:10, f], dtype=f32)
        for r in range(1, 5):
            for f in range(1, mf + 1):
                seds4 = _sumc(seds9[:, f], r)
                bf_seds[f, r] = f32(seds4 / bmain[f, r]) if abs(bmain[f, r]) > 0 else f32(1.0)
            for f in (2, 6, 23):
                bf_seds[f, r] = 1.0
            for f in range(1, 9):
                rs4 = _sumc(rseds9[:, f], r)
                rbf_seds[f, r] = f32(rs4 / brenew[f, r]) if abs(brenew[f, r]) > 0 else f32(1.0)
            rbf_seds[8, r] = 1.0
        for f in range(1, mf + 1):
            chk = f32(0.0)
            for r in range(1, 5):
                chk = chk + bmain[f, r] * f32(bf_seds[f, r])
            bfchk = f32(np.add.reduce(seds9[1:10, f], dtype=f32) / chk) if abs(chk) > 0 else f32(0.0)
            bf_steo[f] = 1.0
            for r in range(1, 5):
                bf_seds[f, r] = f32(bf_seds[f, r]) * bfchk
        for r in range(1, 5):
            for f in (2, 6, 23):
                bf_seds[f, r] = 1.0
        for f in range(1, 9):
            chk = f32(0.0)
            for r in range(1, 5):
                chk = chk + brenew[f, r] * f32(rbf_seds[f, r])
            rchk = f32(np.add.reduce(rseds9[1:10, f], dtype=f32) / chk) if abs(chk) > 0 else f32(0.0)
            rbf_steo[f] = 1.0
            for r in range(1, 5):
                rbf_seds[f, r] = f32(rbf_seds[f, r]) * rchk
    elif curcalyr <= steolastyr - indbmovr2:
        sq = s["steoq"]

        def sy(k):
            return f32(sq[curcalyr, k])

        cfelq = f32(s["cfelq"])
        steo = np.zeros(mf + 1, dtype=f32)
        qelinh2 = f32(s["qelinh2ng"][11, curiyr]) + f32(s["qelinh2e"][11, curiyr])
        steo[1] = max(f32(0.0), sy(18) - q("qelrf", 11, curiyr) - f32(s["qeleth"][curiyr, 11]) - qelinh2
                      - q("qngpin", 11, curiyr) - f32(s["co2_elec"][11, curiyr]) * cfelq / CFELQ_DIV)
        steo[2] = 0.0
        cg3 = np.add.reduce(np.asarray([f32(s["cgogsq"][d, curiyr, 3]) for d in range(1, 10)], dtype=f32), dtype=f32)
        steo[3] = max(f32(0.0), (sy(13) - q("qngrf", 11, curiyr) - f32(s["qngeth"][curiyr, 11]) - f32(feedng[fi]) - cg3
                                 - q("qnghmhp", 11, curiyr) - q("qnghmpf", 11, curiyr)) * firm[5])
        steo[4] = steo[3] * ((f32(1.0) - firm[5]) / firm[5])
        steo[5] = f32(feedng[fi])
        cg1 = np.add.reduce(np.asarray([f32(s["cgogsq"][d, curiyr, 1]) for d in range(1, 10)], dtype=f32), dtype=f32)
        ogs = np.add.reduce(np.asarray([f32(s["ogsupgas"][1, d, curiyr]) for d in range(1, 10)], dtype=f32), dtype=f32)
        steo[7] = max(f32(0.0), sy(15) - q("qclrf", 11, curiyr) - f32(s["qcleth"][curiyr, 11]) - cg1 - ogs * f32(s["cfngc"][curiyr]))
        steo[8] = sy(16)
        steo[9] = sy(17)
        cg2 = np.add.reduce(np.asarray([f32(s["cgogsq"][d, curiyr, 2]) for d in range(1, 10)], dtype=f32), dtype=f32)
        steo[10] = max(f32(0.0), sy(2) - q("qrlrf", 11, curiyr) - cg2)
        steo[11] = max(f32(0.0), sy(1) - q("qdsrf", 11, curiyr))
        steo[12] = max(f32(0.0), sy(3) - q("qlgrf", 11, curiyr) - f32(feedhgl[fi]))
        steo[13] = f32(feedhgl[fi])
        steo[14] = sy(4)
        steo[15] = 0.0
        steo[16] = sy(9)
        steo[17] = sy(6)
        steo[18] = sy(8)
        steo[19] = sy(5)
        steo[20] = sy(7)
        steo[21] = max(f32(0.0), sy(12) - q("qotrf", 11, curiyr))
        steo[22] = steo[21]
        steo[23] = 0.0
        rsteo = np.zeros(9, dtype=f32)
        rsteo[1] = sy(19)
        rsteo[2] = sy(20)
        rsteo[3] = sy(20)
        for f in (4, 5, 6, 7):
            rsteo[f] = brenew[f, 5]
        rsteo[8] = sy(21)
        for f in range(1, mf + 1):
            adj = f32(0.0)
            for r in range(1, 5):
                adj = adj + bmain[f, r] * f32(bf_seds[f, r])
            bf_steo[f] = f32(steo[f] / adj) if abs(adj) > 0 else f32(1.0)
        bf_steo[2] = 1.0
        bf_steo[23] = 1.0
        for f in range(1, 9):
            adj = f32(0.0)
            for r in range(1, 5):
                adj = adj + brenew[f, r] * f32(rbf_seds[f, r])
            rbf_steo[f] = f32(rsteo[f] / adj) if abs(adj) > 0 else f32(1.0)

    # asphalt target (seed in SEDS year + 5, grown afterwards)
    asph_t, asph_p = s["asphalttarget"], s["asphaltpercent"]
    qas = s["qasin"]
    if curiyr + 1989 == sedslastyr + 5:
        asph_t[5] = qas[11, iy]
        asph_p[1] = (f32(qas[1, iy]) + f32(qas[2, iy])) / f32(qas[11, iy])
        asph_p[2] = (f32(qas[3, iy]) + f32(qas[4, iy])) / f32(qas[11, iy])
        asph_p[3] = (f32(qas[5, iy]) + f32(qas[6, iy]) + f32(qas[7, iy])) / f32(qas[11, iy])
        asph_p[4] = (f32(qas[8, iy]) + f32(qas[9, iy])) / f32(qas[11, iy])
    if int(s["curitr"]) == 1 and curiyr + 1989 > sedslastyr + 5:
        g = s["mc_gslgisnhwyr"]
        asph_t[5] = f32(qas[11, iy - 1]) * f32(g[curiyr]) / f32(g[curiyr - 1])
    for r in range(1, 5):
        asph_t[r] = f32(asph_t[5]) * f32(asph_p[r])

    # benchmark factors for this year
    bf, rbf = s["bf"], s["rbf"]
    badj = s["bmain_adjusted"]
    ngt = {r: f32(0.0) for r in range(1, 6)}
    hgt = {r: f32(0.0) for r in range(1, 6)}
    for f in range(1, mf + 1):
        for r in range(1, 5):
            bf[curiyr, f, r] = (f32(1.0) - fade) * f32(bf_seds[f, r]) + fade * f32(bf_steo[f]) * f32(bf_seds[f, r])
            if curiyr >= ICURIYR:
                ngt[5] = f32(feedng[fi])
                hgt[5] = f32(feedhgl[fi])
                for rr in range(1, 5):
                    ngt[rr] = ngt[5] * FEEDNGPERCENT[rr]
                    hgt[rr] = hgt[5] * FEEDHGLPERCENT[rr]
            else:
                ngt = {k: f32(0.0) for k in ngt}
                hgt = {k: f32(0.0) for k in hgt}
            if f == 16:
                bf[curiyr, f, r] = bf_seds[f, r]
            if curcalyr > steolastyr - indbmovr2:
                if f in (2, 9, 23):
                    bf[curiyr, f, r] = 1.0
                elif f == 5:
                    bf[curiyr, 5, r] = f32(ngt[r] / bmain[5, r]) if bmain[5, r] > 0 else f32(0.0)
                elif f == 12:
                    bf[curiyr, f, r] = bf_seds[f, r]
                elif f == 13:
                    bf[curiyr, 13, r] = f32(hgt[r] / bmain[13, r]) if bmain[13, r] > 0 else f32(0.0)
                elif f == 19:
                    if curcalyr == sedslastyr + feedyears:
                        bf[curiyr, 19, r] = f32(f32(feednaph[fi]) * NAPHTHA_DIV_FRAC[r] / bmain[19, r]) if bmain[19, r] > 0 else f32(0.0)
                elif f == 17 and curcalyr >= sedslastyr + 5:
                    bf[curiyr, 17, r] = f32(f32(asph_t[r]) / bmain[17, r]) if bmain[17, r] > 0 else f32(0.0)
            badj[f, r] = bmain[f, r] * f32(bf[curiyr, f, r])
        badj[f, 5] = np.add.reduce(np.asarray([f32(badj[f, r]) for r in range(1, 5)], dtype=f32), dtype=f32)
        bf[curiyr, f, 5] = f32(badj[f, 5] / bmain[f, 5]) if abs(bmain[f, 5]) > 0 else f32(1.0)
    radj = s["brenew_adjusted"]
    for f in range(1, 9):
        for r in range(1, 5):
            rbf[curiyr, f, r] = (f32(1.0) - fade) * f32(rbf_seds[f, r]) + fade * f32(rbf_seds[f, r]) * f32(rbf_steo[f])
            radj[f, r] = brenew[f, r] * f32(rbf[curiyr, f, r])
        tot = np.add.reduce(brenew[f, 1:5], dtype=f32)
        rbf[curiyr, f, 5] = f32(np.add.reduce(np.asarray([f32(radj[f, r]) for r in range(1, 5)], dtype=f32), dtype=f32) / tot) if tot != 0 else f32(0.0)

    _write_qblk(s, curiyr, curcalyr, msedyr, sedslastyr, steolastyr, iy)


def _write_qblk(s, curiyr, curcalyr, msedyr, sedslastyr, steolastyr, iy):
    badj, radj = s["bmain_adjusted"], s["brenew_adjusted"]
    cfelq = f32(s["cfelq"])
    ms = msedyr

    def qs(name):
        return _col(s[name], ms)

    sh = {n: qs(n) for n in ("qselin", "qsngin", "qsclin", "qsmcin", "qsrsin", "qsdsin", "qslgin", "qsmgin", "qspcin", "qsasin", "qsluin",
                             "qspfin", "qsotin", "qshoin", "qsbmin", "qsmsin", "qciin")}

    def g(name, d, y=iy):
        return f32(s[name][d, y])

    for d in range(1, 10):
        r = DIV_TO_REG[d]
        co2 = f32(s["co2_elec"][d, iy]) * cfelq / CFELQ_DIV
        s["qelin"][d, iy] = f32(badj[1, r]) * divshr(sh["qselin"], d, r) + g("qelrf", d) + f32(s["qeleth"][iy, d]) + g("qelhm", d) + g("qngpin", d) + co2
        s["qgfin"][d, iy] = (f32(badj[3, r]) + f32(badj[5, r])) * divshr(sh["qsngin"], d, r) + g("qnghmhp", d) + g("qnghmpf", d)
        s["qgiin"][d, iy] = f32(badj[4, r]) * divshr(sh["qsngin"], d, r) + g("qngrf", d) + f32(s["qngeth"][iy, d]) + f32(s["cgogsq"][d, iy, 3])
        s["inqngpf"][d, iy] = f32(badj[5, r]) * divshr(sh["qsngin"], d, r)
        s["qngin"][d, iy] = f32(s["qgfin"][d, iy]) + f32(s["qgiin"][d, iy])
        s["qclin"][d, iy] = (f32(badj[7, r]) * divshr(sh["qsclin"], d, r) + g("qclrf", d) + f32(s["qcleth"][iy, d]) + f32(s["cgogsq"][d, iy, 1])
                             + f32(s["ogsupgas"][1, d, curiyr]) * f32(s["cfngc"][curiyr]))
        s["qmcin"][d, iy] = f32(badj[8, r]) * divshr(sh["qsmcin"], d, r)
        s["qciin"][d, iy] = f32(badj[9, r]) * divshr(sh["qciin"], d, r)
        s["qrsin"][d, iy] = f32(badj[10, r]) * divshr(sh["qsrsin"], d, r) + g("qrlrf", d) + f32(s["cgogsq"][d, iy, 2])
        s["qrlin"][d, iy] = s["qrsin"][d, iy]
        s["qdsin"][d, iy] = f32(badj[11, r]) * divshr(sh["qsdsin"], d, r) + g("qdsrf", d)
        s["inqlgpf"][d, iy] = f32(badj[13, r]) * divshr(sh["qslgin"], d, r)
        s["inqlghp"][d, iy] = f32(badj[12, r]) * divshr(sh["qslgin"], d, r) + g("qlgrf", d)
        s["qlgin"][d, iy] = f32(s["inqlgpf"][d, iy]) + f32(s["inqlghp"][d, iy])
        s["qmgin"][d, iy] = f32(badj[14, r]) * divshr(sh["qsmgin"], d, r)
        s["qsgin"][d, iy] = g("qsgrf", d, curiyr)
        s["qpcin"][d, iy] = f32(badj[16, r]) * divshr(sh["qspcin"], d, r) + g("qpcrf", d) + g("qccrf", d)
        if curcalyr == steolastyr or curcalyr == steolastyr - 1:
            ccr = np.add.reduce(np.asarray([g("qccrf", k) for k in range(1, 10)], dtype=f32), dtype=f32)
            s["qpcin"][d, iy] = f32(badj[16, r]) * divshr(sh["qspcin"], d, r) + g("qpcrf", d) + g("qccrf", d) * g("qccrf", 11) / ccr
        s["qasin"][d, iy] = f32(badj[17, r]) * divshr(sh["qsasin"], d, r)
        s["qluin"][d, iy] = f32(badj[18, r]) * divshr(sh["qsluin"], d, r)
        s["qpfin"][d, iy] = f32(badj[19, r]) * divshr(sh["qspfin"], d, r)
        if curcalyr > sedslastyr:
            s["qksin"][d, iy] = f32(s["qsksin"][d, ms])
        s["qotin"][d, iy] = f32(badj[21, r]) * divshr(sh["qsotin"], d, r) + g("qotrf", d)
        s["qhoin"][d, iy] = f32(radj[1, r]) * divshr(sh["qshoin"], d, r)
        s["qbmin"][d, iy] = f32(radj[2, r]) * divshr(sh["qsbmin"], d, r)
        s["qmsin"][d, iy] = f32(radj[8, r]) * divshr(sh["qsmsin"], d, r)
        s["qtrin"][d, iy] = f32(s["qhoin"][d, iy]) + f32(s["qbmin"][d, iy]) + f32(s["qmsin"][d, iy])
    if curcalyr < sedslastyr + 1:
        for d in range(1, 10):
            for nm, src in (("qelin", "qselin"), ("qdsin", "qsdsin"), ("qrsin", "qsrsin"), ("qmgin", "qsmgin"), ("qpfin", "qspfin"),
                            ("qasin", "qsasin"), ("qksin", "qsksin"), ("qluin", "qsluin"), ("qpcin", "qspcin"), ("qotin", "qsotin"),
                            ("qgfin", "qsgfin"), ("qgiin", "qsgiin"), ("qngin", "qsngin"), ("qclin", "qsclin"), ("qmcin", "qsmcin"),
                            ("qprin", "qsprin"), ("qbmin", "qsbmin"), ("qhoin", "qshoin"), ("qmsin", "qsmsin")):
                s[nm][d, iy] = s[src][d, iy]
            s["qrlin"][d, iy] = s["qrsin"][d, iy]
            s["qlgin"][d, iy] = f32(s["qslgin"][d, iy]) + f32(s["qsppin"][d, iy])
            s["qciin"][d, iy] = f32(s["qsciin"][11, iy]) * f32(COALCOKEIMPORT[d])
    for nm in ("qelin", "qgfin", "qgiin", "inqngpf", "qngin", "qclin", "qmcin", "qciin", "qrsin", "qdsin", "qlgin", "inqlgpf", "inqlghp",
               "qmgin", "qsgin", "qpcin", "qasin", "qluin", "qpfin", "qksin", "qotin", "qhoin", "qbmin", "qmsin", "qtrin"):
        s[nm][11, iy] = np.add.reduce(np.asarray([f32(s[nm][d, iy]) for d in range(1, 10)], dtype=f32), dtype=f32)
