"""ELSET and REVGAP, uefp.f.

ELSET turns the regional results of EFP (EPRICE, ECOST, COMPCOMP, ...) into retail
prices by sector and EMM region (NERC), then into prices by sector and end use for
the census divisions. REVGAP keeps the ratio of competitive revenues to costs.

Skipped: every WRITE (debug and report lines), including the NaN/negative price
reports that only write.
"""

import numpy as np

from nems_open.emm.efp.common import f32

MNUMCR = 11
MNUMNR = 28
MNEUGRP = 32
RES, COM, IND, TRA = 1, 2, 3, 4

_C3412 = f32(3.412)
_BAD_PRICE = f32(20.0)

# Locals of ELSET are SAVEd in this build. These carry a value from one call to the
# next and are never dumped (they are not in COMMON): the PEC*FXN and PECTR* arrays
# that are local to ELSET, TEMPREG, and the revised census map.
_SAVED: dict = {}


def _saved(name, shape):
    if name not in _SAVED:
        _SAVED[name] = np.zeros(shape, dtype=np.float32)
    return _SAVED[name]


def _rvmapp(s):
    """RVMappCtoN(25,10,4) and mapcnavg(25,10): MAPPCtoN renormalised over the NERC
    regions, so AK/HI (not in EMM) drop out; mapcnavg is the transportation map.
    Fortran builds them only when CURIYR+UHBSYR = UESTYR and CURITR = 1 and keeps
    them after. MAPPCtoN is the same in every year, so build from it on that call and
    on first use."""
    first = (int(s["curiyr"]) + int(s["uhbsyr"])) == int(s["uestyr"]) and int(s["curitr"]) == 1
    if first or "rvmapp" not in _SAVED:
        unrgns = int(s["unrgns"])
        mapp = s["mappcton"]
        rv = np.zeros((MNUMNR - 3, MNUMCR - 1, 4), dtype=np.float32)
        for sectr in range(1, 5):
            sumcn22 = np.zeros(MNUMCR - 1, dtype=np.float32)
            for nerc in range(1, unrgns + 1):
                for census in range(1, MNUMCR):
                    sumcn22[census - 1] = f32(sumcn22[census - 1] + mapp[nerc, census, sectr])
            for nerc in range(1, unrgns + 1):
                for census in range(1, MNUMCR):
                    if sumcn22[census - 1] > 0.0:
                        rv[nerc - 1, census - 1, sectr - 1] = f32(mapp[nerc, census, sectr] / sumcn22[census - 1])
                    else:
                        rv[nerc - 1, census - 1, sectr - 1] = f32(0.0)
        _SAVED["rvmapp"] = rv
        _SAVED["mapcnavg"] = rv[:, :, 3].copy()
    return _SAVED["rvmapp"], _SAVED["mapcnavg"]


def elset(s):
    iy = int(s["curiyr"])
    year = iy
    unrgns = int(s["unrgns"])
    nclass = int(s["nclass"])
    usw_pol = int(s["usw_pol"])
    neusgrp = [0] + [int(s["neusgrp"][k]) for k in range(1, 5)]
    salcls = s["salcls"]
    eload = s["toteuload"]

    rvmapp, mapcnavg = _rvmapp(s)

    # ELSET locals (0-based arrays, [nerc-1, year-1])
    L = {k: _saved(k, (MNUMNR, 61)) for k in (
        "pecrsfxn", "peccmfxn", "pecinfxn", "pectrrln", "pectrmen", "pectrfxn", "pectrtxn", "pectrtdn")}
    tempreg = _saved("tempreg", (MNEUGRP, MNUMNR))
    y0 = year - 1

    with np.errstate(all="ignore"):
        # demand weights of the end uses within each sector, by NERC region
        demwtnr = np.zeros((MNEUGRP, MNUMNR), dtype=np.float32)
        totallnr = np.zeros((5, MNUMNR), dtype=np.float32)
        for nerc in range(1, unrgns + 1):
            l = 0
            for sectr in range(1, 5):
                for _ in range(neusgrp[sectr]):
                    l += 1
                    demwtnr[l - 1, nerc - 1] = eload[l, nerc]
                    totallnr[sectr - 1, nerc - 1] = f32(totallnr[sectr - 1, nerc - 1] + demwtnr[l - 1, nerc - 1])
                totallnr[4, nerc - 1] = f32(totallnr[4, nerc - 1] + totallnr[sectr - 1, nerc - 1])
        for nerc in range(1, unrgns + 1):
            l = 0
            for sectr in range(1, 5):
                for _ in range(neusgrp[sectr]):
                    l += 1
                    if totallnr[sectr - 1, nerc - 1] > 0.0:
                        demwtnr[l - 1, nerc - 1] = f32(demwtnr[l - 1, nerc - 1] / totallnr[sectr - 1, nerc - 1])
                    else:
                        demwtnr[l - 1, nerc - 1] = f32(0.0)

        saltota = np.zeros(MNUMNR, dtype=np.float32)
        for nerc in range(1, unrgns + 1):
            for icls in range(1, nclass + 1):
                saltota[nerc - 1] = f32(saltota[nerc - 1] + salcls[nerc, icls])

        denom = s["mc_jpgdp"][year]
        eprice, ecost, compcomp, epric2 = s["eprice"], s["ecost"], s["compcomp"], s["epric2"]
        frmarg = s["frmarg"]
        pelrsnr, pelcmnr, peltrnr, pelinnr, pelasnr = (s[k] for k in ("pelrsnr", "pelcmnr", "peltrnr", "pelinnr", "pelasnr"))
        pelflnr, pelomnr, peltlnr, pelwhnr, pelcpnr = (s[k] for k in ("pelflnr", "pelomnr", "peltlnr", "pelwhnr", "pelcpnr"))
        pec = {k: s[k] for k in (
            "pecrsrln", "pecrsmen", "pecrstxn", "pecrstdn", "pecrsnr",
            "peccmrln", "peccmmen", "peccmtxn", "peccmtdn", "peccmnr",
            "pecinrln", "pecinmen", "pecintxn", "pecintdn", "pecinnr",
            "pectrnr", "pecasrln", "pecasmen", "pecasfxn", "pecastxn", "pecastdn", "pecasnr",
            "pecgenn", "pectrnn", "pecdisn")}
        ulep = {k: s[k] for k in ("uleprs", "ulepcm", "ulepin", "uleptr", "ulepas", "ulepfl", "ulepom", "ulepwp", "ulepcp")}
        scsprc = s["scsprc"]

        for nerc in range(1, MNUMNR + 1):
            n0 = nerc - 1
            if nerc <= unrgns:
                pelrsnr[nerc, year] = f32(eprice[1, 4, nerc] / denom)
                pelcmnr[nerc, year] = f32(eprice[2, 4, nerc] / denom)
                peltrnr[nerc, year] = f32(eprice[4, 4, nerc] / denom)
                pelinnr[nerc, year] = f32(eprice[3, 4, nerc] / denom)
                pelasnr[nerc, year] = f32(eprice[5, 4, nerc] / denom)
                pelflnr[nerc, year] = f32(ecost[1, nerc] / denom)
                pelomnr[nerc, year] = f32(ecost[2, nerc] / denom)
                peltlnr[nerc, year] = pelasnr[nerc, year]
                pelwhnr[nerc, year] = f32(ecost[3, nerc] / denom)
                pelcpnr[nerc, year] = f32(f32(f32(peltlnr[nerc, year] - pelflnr[nerc, year]) - pelomnr[nerc, year])
                                          - pelwhnr[nerc, year])

                ulep["uleprs"][nerc] = f32(eprice[1, 4, nerc] / denom)
                ulep["ulepcm"][nerc] = f32(eprice[2, 4, nerc] / denom)
                ulep["ulepin"][nerc] = f32(eprice[3, 4, nerc] / denom)
                ulep["uleptr"][nerc] = f32(eprice[4, 4, nerc] / denom)
                ulep["ulepas"][nerc] = f32(eprice[5, 4, nerc] / denom)
                ulep["ulepfl"][nerc] = f32(ecost[1, nerc] / denom)
                ulep["ulepom"][nerc] = f32(ecost[2, nerc] / denom)
                ulep["ulepwp"][nerc] = f32(ecost[3, nerc] / denom)
                ulep["ulepcp"][nerc] = f32(f32(f32(ulep["ulepas"][nerc] - ulep["ulepfl"][nerc]) - ulep["ulepom"][nerc])
                                           - ulep["ulepwp"][nerc])

                # competitive price components by sector, weighted by end-use demand
                if usw_pol == 4:
                    l = 0
                    for sectr in range(1, 5):
                        t1 = t2 = t3 = t4 = f32(0.0)
                        for _ in range(neusgrp[sectr]):
                            l += 1
                            w = demwtnr[l - 1, n0]
                            t1 = f32(t1 + f32(w * compcomp[1, l, nerc]))
                            t2 = f32(t2 + f32(w * compcomp[2, l, nerc]))
                            t3 = f32(t3 + f32(w * compcomp[3, l, nerc]))
                            t4 = f32(t4 + f32(w * compcomp[4, l, nerc]))
                        if sectr == 1:
                            pec["pecrsrln"][nerc, year] = f32(t1 / denom)
                            pec["pecrsmen"][nerc, year] = f32(t2 / denom)
                            L["pecrsfxn"][n0, y0] = f32(t3 / denom)
                            pec["pecrstxn"][nerc, year] = f32(t4 / denom)
                        elif sectr == 2:
                            s["peccmrln"][nerc, year] = f32(t1 / denom)
                            s["peccmmen"][nerc, year] = f32(t2 / denom)
                            L["peccmfxn"][n0, y0] = f32(t3 / denom)
                            s["peccmtxn"][nerc, year] = f32(t4 / denom)
                        elif sectr == 3:
                            s["pecinrln"][nerc, year] = f32(t1 / denom)
                            s["pecinmen"][nerc, year] = f32(t2 / denom)
                            L["pecinfxn"][n0, y0] = f32(t3 / denom)
                            s["pecintxn"][nerc, year] = f32(t4 / denom)
                        else:
                            L["pectrrln"][n0, y0] = f32(t1 / denom)
                            L["pectrmen"][n0, y0] = f32(t2 / denom)
                            L["pectrfxn"][n0, y0] = f32(t3 / denom)
                            L["pectrtxn"][n0, y0] = f32(t4 / denom)

                # price by end use: marginal cost blended with the regulated price
                k = 1
                for i in range(1, nclass + 1):
                    for _ in range(neusgrp[i]):
                        if frmarg[year, nerc] > 0.0 and usw_pol == 4:
                            margprc = f32(f32(epric2[k, nerc] + eprice[i, 2, nerc]) + eprice[i, 3, nerc])
                            tempreg[k - 1, n0] = f32(f32(frmarg[year, nerc] * margprc)
                                                     + f32(f32(f32(1.0) - frmarg[year, nerc]) * eprice[i, 4, nerc]))
                        else:
                            tempreg[k - 1, n0] = eprice[i, 4, nerc]
                        compcomp[5, k, nerc] = f32(eprice[i, 2, nerc] + eprice[i, 3, nerc])  # t&d in anyway
                        tr = tempreg[k - 1, n0]
                        if np.isnan(tr) or f32(tr / denom) > 350.0 or f32(tr / denom) < 1.0:
                            tempreg[k - 1, n0] = f32(f32(350.0) * denom)
                        k += 1

                # sector prices: demand-weighted over the end uses (l keeps counting)
                l = 0
                for sectr, nm_td, nm_nr in ((1, "pecrstdn", "pecrsnr"), (2, "peccmtdn", "peccmnr"),
                                            (3, "pecintdn", "pecinnr"), (4, None, "pectrnr")):
                    temp = temp5 = f32(0.0)
                    for _ in range(neusgrp[sectr]):
                        l += 1
                        w = demwtnr[l - 1, n0]
                        temp = f32(temp + f32(w * tempreg[l - 1, n0]))
                        temp5 = f32(temp5 + f32(w * compcomp[5, l, nerc]))
                    if nm_td:
                        s[nm_td][nerc, year] = f32(temp5 / denom)
                    else:
                        L["pectrtdn"][n0, y0] = f32(temp5 / denom)
                    s[nm_nr][nerc, year] = f32(temp / denom)

                for i in range(1, MNEUGRP + 1):
                    _set_outn(s, nerc, year, i, f32(tempreg[i - 1, n0] / denom))

                def avg(c1, c2, c3, c4):
                    t = f32(f32(f32(f32(c1 * salcls[nerc, 1]) + f32(c2 * salcls[nerc, 2]))
                                + f32(c3 * salcls[nerc, 3])) + f32(c4 * salcls[nerc, 4]))
                    return f32(t / saltota[n0])

                pec["pecasnr"][nerc, year] = avg(s["pecrsnr"][nerc, year], s["peccmnr"][nerc, year],
                                                 s["pecinnr"][nerc, year], s["pectrnr"][nerc, year])
                pec["pecasrln"][nerc, year] = avg(s["pecrsrln"][nerc, year], s["peccmrln"][nerc, year],
                                                  s["pecinrln"][nerc, year], L["pectrrln"][n0, y0])
                pec["pecasmen"][nerc, year] = avg(s["pecrsmen"][nerc, year], s["peccmmen"][nerc, year],
                                                  s["pecinmen"][nerc, year], L["pectrmen"][n0, y0])
                pec["pecasfxn"][nerc, year] = avg(L["pecrsfxn"][n0, y0], L["peccmfxn"][n0, y0],
                                                  L["pecinfxn"][n0, y0], L["pectrfxn"][n0, y0])
                pec["pecastxn"][nerc, year] = avg(s["pecrstxn"][nerc, year], s["peccmtxn"][nerc, year],
                                                  s["pecintxn"][nerc, year], L["pectrtxn"][n0, y0])
                pec["pecastdn"][nerc, year] = avg(s["pecrstdn"][nerc, year], s["peccmtdn"][nerc, year],
                                                  s["pecintdn"][nerc, year], L["pectrtdn"][n0, y0])
                pec["pectrnn"][nerc, year] = f32(eprice[5, 2, nerc] / denom)
                pec["pecdisn"][nerc, year] = f32(eprice[5, 3, nerc] / denom)
                pec["pecgenn"][nerc, year] = f32(f32(pec["pecasnr"][nerc, year] - pec["pectrnn"][nerc, year])
                                                 - pec["pecdisn"][nerc, year])
                # overwrite the ftab variables with the competitive prices
                pelrsnr[nerc, year] = s["pecrsnr"][nerc, year]
                pelcmnr[nerc, year] = s["peccmnr"][nerc, year]
                pelinnr[nerc, year] = s["pecinnr"][nerc, year]
                peltrnr[nerc, year] = s["pectrnr"][nerc, year]
                pelasnr[nerc, year] = pec["pecasnr"][nerc, year]
                ulep["uleprs"][nerc] = s["pecrsnr"][nerc, year]
                ulep["ulepcm"][nerc] = s["peccmnr"][nerc, year]
                ulep["ulepin"][nerc] = s["pecinnr"][nerc, year]
                ulep["uleptr"][nerc] = s["pectrnr"][nerc, year]
                ulep["ulepas"][nerc] = pec["pecasnr"][nerc, year]
            else:
                for a in (pelrsnr, pelcmnr, peltrnr, pelinnr, pelasnr, pelcpnr, pelflnr, pelomnr, peltlnr, pelwhnr):
                    a[nerc, year] = f32(0.0)
                for i in range(1, MNEUGRP + 1):
                    _set_outn(s, nerc, year, i, f32(0.0))
                if nerc == MNUMNR:
                    _national_nerc(s, year, unrgns, L, scsprc)

        _census(s, ulep, year, unrgns, rvmapp, mapcnavg, saltota, demwtnr, totallnr, tempreg, denom)
        _sync_out(s, year)


def _set_outn(s, nerc, year, i, value):
    """PELOUTN(NERC,YEAR,i) is EQUIVALENCEd to PELSHRSN, PELCLRSN, ... (efpint), so the
    write also lands in the i-th end-use array of the NERC prices."""
    s["peloutn"][nerc, year, i] = value
    s[_ENDUSE[i - 1][1]][nerc, year] = value


def _national_nerc(s, iy, unrgns, L, scsprc):
    """US totals (NERC index MNUMNR) of the competitive prices, weighted by sales."""
    salcls = s["salcls"]
    z = f32(0.0)
    y0 = iy - 1
    numer = {k: [z] * 11 for k in range(1, 6)}
    den = {k: z for k in range(1, 6)}
    for i in range(1, unrgns + 1):
        i0 = i - 1
        tot = z
        for j in range(1, 5):
            tot = f32(tot + salcls[i, j])
        cls = {
            1: (s["pecrsrln"][i, iy], s["pecrsmen"][i, iy], L["pecrsfxn"][i0, y0], s["pecrstxn"][i, iy],
                s["pecrstdn"][i, iy], s["pecrsnr"][i, iy]),
            2: (s["peccmrln"][i, iy], s["peccmmen"][i, iy], L["peccmfxn"][i0, y0], s["peccmtxn"][i, iy],
                s["peccmtdn"][i, iy], s["peccmnr"][i, iy]),
            3: (s["pecinrln"][i, iy], s["pecinmen"][i, iy], L["pecinfxn"][i0, y0], s["pecintxn"][i, iy],
                s["pecintdn"][i, iy], s["pecinnr"][i, iy]),
            4: (L["pectrrln"][i0, y0], L["pectrmen"][i0, y0], L["pectrfxn"][i0, y0], L["pectrtxn"][i0, y0],
                L["pectrtdn"][i0, y0], s["pectrnr"][i, iy]),
        }
        for c in range(1, 5):
            for m in range(6):
                numer[c][m + 1] = f32(numer[c][m + 1] + f32(salcls[i, c] * cls[c][m]))
            den[c] = f32(den[c] + salcls[i, c])
        av = (s["pecasrln"][i, iy], s["pecasmen"][i, iy], s["pecasfxn"][i, iy], s["pecastxn"][i, iy],
              s["pecastdn"][i, iy], s["pecasnr"][i, iy])
        for m in range(6):
            numer[5][m + 1] = f32(numer[5][m + 1] + f32(tot * av[m]))
        numer[5][7] = f32(numer[5][7] + f32(tot * scsprc[iy, i, 3]))
        numer[5][8] = f32(numer[5][8] + f32(tot * s["pecgenn"][i, iy]))
        numer[5][9] = f32(numer[5][9] + f32(tot * s["pectrnn"][i, iy]))
        numer[5][10] = f32(numer[5][10] + f32(tot * s["pecdisn"][i, iy]))
        den[5] = f32(den[5] + tot)

    n = MNUMNR
    scsprc[iy, n, 3] = f32(numer[5][7] / den[5])
    # (sector, dumped COMMON name or None for an ELSET local) in the order RLN MEN FXN TXN TDN NR
    outs = {
        1: ("pecrsrln", "pecrsmen", "L:pecrsfxn", "pecrstxn", "pecrstdn", "pecrsnr"),
        2: ("peccmrln", "peccmmen", "L:peccmfxn", "peccmtxn", "peccmtdn", "peccmnr"),
        3: ("pecinrln", "pecinmen", "L:pecinfxn", "pecintxn", "pecintdn", "pecinnr"),
        4: ("L:pectrrln", "L:pectrmen", "L:pectrfxn", "L:pectrtxn", "L:pectrtdn", "pectrnr"),
    }
    for c in range(1, 5):
        for m, tgt in enumerate(outs[c]):
            v = f32(numer[c][m + 1] / den[c]) if den[c] > 0.0 else f32(0.0)
            if tgt.startswith("L:"):
                L[tgt[2:]][n - 1, y0] = v
            else:
                s[tgt][n, iy] = v
    for m, nm in enumerate(("pecasrln", "pecasmen", "pecasfxn", "pecastxn", "pecastdn", "pecasnr")):
        s[nm][n, iy] = f32(numer[5][m + 1] / den[5])
    s["pecgenn"][n, iy] = f32(numer[5][8] / den[5])
    s["pectrnn"][n, iy] = f32(numer[5][9] / den[5])
    s["pecdisn"][n, iy] = f32(numer[5][10] / den[5])


# census-division arrays filled from NERC-level end-use prices: (census array, NERC array, sector)
_ENDUSE = (
    ("pelshrs", "pelshrsn", RES), ("pelclrs", "pelclrsn", RES), ("pelwhrs", "pelwhrsn", RES),
    ("pelckrs", "pelckrsn", RES), ("pelcdrs", "pelcdrsn", RES), ("pelrfrs", "pelrfrsn", RES),
    ("pelfzrs", "pelfzrsn", RES), ("pelltrs", "pelltrsn", RES), ("pelotrs", "pelotrsn", RES),
    ("pelh2rs", "pelh2rsn", RES), ("pelvhrs", "pelvhrsn", RES),
    ("pelshcm", "pelshcmn", COM), ("pelsccm", "pelsccmn", COM), ("pelwhcm", "pelwhcmn", COM),
    ("pelvtcm", "pelvtcmn", COM), ("pelckcm", "pelckcmn", COM), ("pelltcm", "pelltcmn", COM),
    ("pelrfcm", "pelrfcmn", COM), ("pelopcm", "pelopcmn", COM), ("peloncm", "peloncmn", COM),
    ("pelotcm", "pelotcmn", COM), ("pelp2cm", "pelp2cmn", COM), ("pelpfcm", "pelpfcmn", COM),
    ("pelsbcm", "pelsbcmn", COM), ("peltbcm", "peltbcmn", COM), ("pelibcm", "pelibcmn", COM),
    ("pelfncm", "pelfncmn", COM),
    ("pelinp", "pelinpn", IND), ("pelins", "pelinsn", IND), ("pelinm", "pelinmn", IND),
    ("pelinh2e", "pelinh2en", IND),
    ("pellttr", "pellttrn", TRA),
)
# The list order is the end-use order l = 1..32 of the US totals.
_US_L = {nm: k for k, (nm, _, _) in enumerate(_ENDUSE, start=1)}
# US totals that test den(l) > 0 and fall back to 20.0
_US_GUARDED = {"pelvhrs", "pelp2cm", "pelpfcm", "pelsbcm", "peltbcm", "pelibcm", "pelfncm", "pelinh2e"}


def _census(s, ulep, iy, unrgns, rvmapp, mapcnavg, saltota, demwtnr, totallnr, tempreg, denom):
    sec = s["sec"]
    c10 = slice(1, MNUMCR - 1)       # CENSUS 1..MNUMCR-1 (inclusive, Fortran)
    zero = f32(0.0)
    names = (["pelbs", "pelwh", "pelav", "pelrs", "pelcm", "peltr", "pelin", "pelas", "pelcp", "pelfl", "pelom",
              "peltl", "pecrs", "peccm", "pecin", "pectr", "pecas", "pelme"] + [e[0] for e in _ENDUSE])
    for nm in names:
        s[nm][1:MNUMCR, iy] = zero

    def rvsec(nerc, sector):
        return rvmapp[nerc - 1, :, int(sec[sector]) - 1]

    def acc(dst, src, m):
        s[dst][c10, iy] = s[dst][c10, iy] + (src / _C3412) * m

    for nerc in range(1, MNUMNR - 2 + 1):
        if nerc <= unrgns:
            mavg = mapcnavg[nerc - 1, :]
            acc("pelbs", s["ewsprcn"][nerc, iy], mavg)
            acc("pelwh", s["pelwhnr"][nerc, iy], mavg)
            acc("pelav", s["pelasnr"][nerc, iy], mavg)
            acc("pelrs", s["pelrsnr"][nerc, iy], rvsec(nerc, RES))
            acc("pelcm", s["pelcmnr"][nerc, iy], rvsec(nerc, COM))
            acc("peltr", s["peltrnr"][nerc, iy], rvsec(nerc, TRA))
            acc("pelin", s["pelinnr"][nerc, iy], rvsec(nerc, IND))
            acc("pelas", s["pelasnr"][nerc, iy], mavg)
            acc("pelcp", s["pelcpnr"][nerc, iy], mavg)
            acc("pelfl", s["pelflnr"][nerc, iy], mavg)
            acc("pelom", s["pelomnr"][nerc, iy], mavg)
            acc("peltl", s["peltlnr"][nerc, iy], mavg)

            for dst, src, sector in _ENDUSE:
                acc(dst, s[src][nerc, iy], rvsec(nerc, sector))
                v = s[dst][c10, iy]
                bad = (v < 0.0) | np.isnan(v)       # the Fortran reports it (WRITE only), then sets 20.0
                if bad.any():
                    s[dst][c10, iy] = np.where(bad, _BAD_PRICE, v).astype(np.float32)

            acc("pecrs", s["pecrsnr"][nerc, iy], rvsec(nerc, RES))
            acc("peccm", s["peccmnr"][nerc, iy], rvsec(nerc, COM))
            acc("pecin", s["pecinnr"][nerc, iy], rvsec(nerc, IND))
            acc("pectr", s["pectrnr"][nerc, iy], rvsec(nerc, TRA))
            acc("pecas", s["pecasnr"][nerc, iy], mavg)
            acc("pelme", s["pecasmen"][nerc, iy], mavg)
            # purchased electricity prices overwritten with the competitive prices
            for dst, src in (("pelrs", "pecrs"), ("pelcm", "peccm"), ("pelin", "pecin"), ("peltr", "pectr"),
                             ("pelas", "pecas")):
                s[dst][c10, iy] = s[src][c10, iy]
        else:
            # runs for every NERC from UNRGNS+1 to MNUMNR-2 (once with 25 regions)
            _us_total(s, ulep, iy, unrgns, saltota, demwtnr, totallnr, tempreg, denom)


def _sync_out(s, iy):
    """PELRSOUT / PELCMOUT are EQUIVALENCEd to the 11 residential and the 16 commercial
    end-use arrays that follow PELSHRS and PELSHCM (eusprc)."""
    for k in range(1, 12):
        s["pelrsout"][1:MNUMCR, iy, k] = s[_ENDUSE[k - 1][0]][1:MNUMCR, iy]
    for k in range(1, 17):
        s["pelcmout"][1:MNUMCR, iy, k] = s[_ENDUSE[10 + k][0]][1:MNUMCR, iy]


def _us_total(s, ulep, iy, unrgns, saltota, demwtnr, totallnr, tempreg, denom):
    n = MNUMCR
    salcls = s["salcls"]
    z = f32(0.0)
    tot_of = []
    for i in range(1, unrgns + 1):
        tot = z
        for j in range(1, 5):
            tot = f32(tot + salcls[i, j])
        tot_of.append(tot)

    def wavg(src_name, cls):
        num = den = z
        for i in range(1, unrgns + 1):
            w = salcls[i, cls] if cls else tot_of[i - 1]
            num = f32(num + f32(w * s[src_name][i, iy]))
            den = f32(den + w)
        return num, den

    cls_src = ((1, "pelrsnr"), (2, "pelcmnr"), (3, "pelinnr"), (4, "peltrnr"), (0, "pelasnr"))
    res = [wavg(nm, c) for c, nm in cls_src]
    for (num, den), up, pel in zip(res, ("uleprs", "ulepcm", "ulepin", "uleptr", "ulepas"),
                                   ("pelrs", "pelcm", "pelin", "peltr", "pelas")):
        ulep[up][MNUMNR] = f32(num / den)
        s[pel][n, iy] = f32(num / f32(_C3412 * den))
    s["pelav"][n, iy] = s["pelas"][n, iy]

    num0 = z
    num = {k: z for k in range(1, 7)}
    den1 = z
    for i in range(1, unrgns + 1):
        tot = tot_of[i - 1]
        num0 = f32(num0 + f32(tot * s["ewsprcn"][i, iy]))
        num[1] = f32(num[1] + f32(tot * s["pelcpnr"][i, iy]))
        den1 = f32(den1 + tot)
        num[2] = f32(num[2] + f32(tot * s["pelflnr"][i, iy]))
        num[3] = f32(num[3] + f32(tot * s["pelomnr"][i, iy]))
        num[5] = f32(num[5] + f32(tot * s["pelwhnr"][i, iy]))
        num[4] = f32(num[4] + f32(tot * s["peltlnr"][i, iy]))
        num[6] = f32(num[6] + f32(tot * s["pecasmen"][i, iy]))
    d = f32(_C3412 * den1)
    s["pelbs"][n, iy] = f32(num0 / d)
    s["pelcp"][n, iy] = f32(num[1] / d)
    s["pelfl"][n, iy] = f32(num[2] / d)
    s["pelom"][n, iy] = f32(num[3] / d)
    s["pelwh"][n, iy] = f32(num[5] / d)
    s["peltl"][n, iy] = f32(num[4] / d)
    s["pelme"][n, iy] = f32(num[6] / d)
    ulep["ulepcp"][MNUMNR] = f32(num[1] / den1)
    ulep["ulepfl"][MNUMNR] = f32(num[2] / den1)
    ulep["ulepom"][MNUMNR] = f32(num[3] / den1)
    ulep["ulepwp"][MNUMNR] = f32(num[5] / den1)

    numl = np.zeros(MNEUGRP, dtype=np.float32)
    denl = np.zeros(MNEUGRP, dtype=np.float32)
    neusgrp = [0] + [int(s["neusgrp"][k]) for k in range(1, 5)]
    for i in range(1, unrgns + 1):
        l = 0
        for sectr in range(1, 5):
            for _ in range(neusgrp[sectr]):
                l += 1
                numl[l - 1] = f32(numl[l - 1] + f32(f32(f32(tempreg[l - 1, i - 1] * demwtnr[l - 1, i - 1])
                                                       * totallnr[sectr - 1, i - 1]) / denom))
                denl[l - 1] = f32(denl[l - 1] + f32(demwtnr[l - 1, i - 1] * totallnr[sectr - 1, i - 1]))
    for nm, _src, _sector in _ENDUSE:
        l = _US_L[nm]
        if nm in _US_GUARDED and not denl[l - 1] > 0:
            s[nm][n, iy] = f32(20.0)
        else:
            s[nm][n, iy] = f32(numl[l - 1] / f32(_C3412 * denl[l - 1]))

    nums = {k: z for k in range(1, 6)}
    dens = {k: z for k in range(1, 6)}
    for i in range(1, unrgns + 1):
        for k, nm in enumerate(("pecrsnr", "peccmnr", "pecinnr", "pectrnr"), start=1):
            nums[k] = f32(nums[k] + f32(salcls[i, k] * s[nm][i, iy]))
            dens[k] = f32(dens[k] + salcls[i, k])
        nums[5] = f32(nums[5] + f32(saltota[i - 1] * s["pecasnr"][i, iy]))
        dens[5] = f32(dens[5] + saltota[i - 1])
    for k, nm in enumerate(("pecrs", "peccm", "pecin", "pectr", "pecas"), start=1):
        s[nm][n, iy] = f32(nums[k] / f32(_C3412 * dens[k]))
    # overwrite with competitive prices
    for dst, src in (("pelrs", "pecrs"), ("pelcm", "peccm"), ("peltr", "pectr"), ("pelin", "pecin"), ("pelas", "pecas")):
        s[dst][n, iy] = s[src][n, iy]


def revgap(s):
    """Annual gap between competitive revenues and costs; DGAPOLD(RGN) is the
    smoothed ratio of revenues to costs that ECP reads. Call only if EFPFCRL = 1."""
    iy = int(s["curiyr"])
    fullyr = int(s["usyear"][iy])
    dgap = s["dgapold"]
    salcls = s["salcls"]
    with np.errstate(all="ignore"):
        for rgn in range(1, int(s["unrgns"]) + 1):
            tsales = f32(f32(f32(salcls[rgn, 1] + salcls[rgn, 2]) + salcls[rgn, 3]) + salcls[rgn, 4])
            trevs = f32(f32(f32(f32(f32(s["pecasrln"][rgn, iy] + s["pecasmen"][rgn, iy])
                                    + s["pecasfxn"][rgn, iy]) + s["pecastxn"][rgn, iy])
                            * s["mc_jpgdp"][iy]) * tsales)
            tcost = f32(s["compcap"][rgn, iy] + s["compex"][rgn, iy])
            tgap = f32(trevs / tcost)
            fm = s["frmarg"][iy, rgn]
            tgap = f32(f32(f32(f32(1.0) - fm) * f32(1.05)) + f32(tgap * fm))
            if fullyr > int(s["uestyr"]):
                dgap[rgn] = f32(f32(f32(0.5) * dgap[rgn]) + f32(f32(0.5) * tgap))
            else:
                dgap[rgn] = tgap
