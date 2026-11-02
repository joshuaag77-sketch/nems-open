"""TBENCHMARK and TRANEASY (tran.f): benchmark fuel use to SEDS, MER and STEO.

Through the last SEDS year, gasoline, distillate and residual use are scaled to SEDS
by region; in the MER year to the MER national total split like SEDS; afterwards the
factors carry forward, with residual following STEO's growth while STEO runs. A
balancing item for gasoline, distillate and jet fuel closes the gap to STEO growth,
then holds its share. Every mode's fuel and VMT gets a benchmarked copy.

carry: TBENCHMARK's saved MER_STEO_regn (set in the last SEDS year, read in the MER year).
steobm: the STEOBM run switch (1 in the reference run).
"""

import numpy as np

from nems_open.transportation.common import MAXAGE, MAXLDV, MAXVTYP, MNUMCR, f32, fsum

ONE = f32(1.0)
R9 = slice(1, MNUMCR - 2)
A11 = slice(1, MNUMCR)
TFRT_FUEL = 12
MSEDYR = 34      # PARAMETER in parametr: historical SEDS years
MAXFLEET, MAXHAV = 4, 4


def traneasy(s: dict) -> None:
    """Copy STEO's transport fuel series into COMMON /tran_easy/. The oracle does not dump
    STEOBLOCK; the copies are the same every call, so without it they are left as they are."""
    if "mgtcbus" not in s:
        return
    s["tmgtcbus"][...] = s["mgtcbus"]
    s["tjftcbus"][...] = s["jftcbus"]
    s["tdstcpus"][...] = s["datcpus"] - s["dfepdel"]
    s["trftcbus"][...] = s["rftcbus"]


def tbenchmark(s: dict, carry: dict, steobm: int = 1) -> None:
    n, yrs = int(s["n"]), int(s["curcalyr"])
    mer = carry["mer_steo_regn"]
    yseds = 1990 + MSEDYR - 1
    ymer, ysteo = int(s["ymer"]), int(s["ysteo"])
    traneasy(s)
    ben = {k: s[k] for k in ("benel", "benng", "benmg", "benjf", "bends", "benrs", "benlg", "benot", "benme", "benet", "benhy")}
    for b in ben.values():
        b[:, n] = 1.0
    for k in ("qmgbs", "qdsbs", "qjfbs"):
        s[k][:, n] = 0.0
    bmg, bds, brs = ben["benmg"], ben["bends"], ben["benrs"]
    qmg, qds, qrs, qjf = s["qmgtr"], s["qdstr"], s["qrstr"], s["qjftr"]
    smg, sjf, sds, srs = s["qsmgtr"], s["qsjftr"], s["qsdstr"], s["qsrstr"]
    mer_tran, trf = s["mer_tran"], s["trftcbus"]
    for r in range(1, MNUMCR + 1):
        if r == 10:
            continue
        if yrs <= yseds:
            if qmg[r, n] != 0.0:
                bmg[r, n] = smg[r, n] / qmg[r, n]
            if qds[r, n] != 0.0:
                bds[r, n] = sds[r, n] / qds[r, n]
            if qrs[r, n] != 0.0:
                brs[r, n] = srs[r, n] / qrs[r, n]
            if yrs == yseds:
                for k, q in enumerate((smg, sjf, sds, srs), start=1):
                    mer[r, k] = q[r, n] / q[MNUMCR, n] * mer_tran[k]
        elif yrs == ymer:
            bmg[r, n] = mer[r, 1] / qmg[r, n]
            bds[r, n] = mer[r, 3] / qds[r, n]
            brs[r, n] = 1.0
            if qrs[r, n] > 0.0:
                brs[r, n] = mer[r, 4] / qrs[r, n]
        else:
            bmg[r, n] = bmg[r, n - 1]
            bds[r, n] = bds[r, n - 1]
            if yrs <= ysteo and steobm == 1:
                brs[r, n] = 1.0
                if qrs[r, n] > 0.0:
                    brs[r, n] = qrs[MNUMCR, n - 1] * trf[n] / trf[n - 1] / qrs[MNUMCR, n]
            else:
                brs[r, n] = brs[r, n - 1]
    for r in range(1, MNUMCR + 1):
        qmg[r, n] = qmg[r, n] * bmg[r, n]
        qds[r, n] = qds[r, n] * bds[r, n]
        qrs[r, n] = qrs[r, n] * brs[r, n]
    if yrs >= ymer:
        bmg[R9, n] = bmg[R9, n] * qmg[MNUMCR, n] / fsum(qmg[R9, n])
        bds[R9, n] = bds[R9, n] * qds[MNUMCR, n] / fsum(qds[R9, n])
        brs[R9, n] = brs[R9, n] * qrs[MNUMCR, n] / fsum(qrs[R9, n])
        qmg[R9, n] = qmg[R9, n] * qmg[MNUMCR, n] / fsum(qmg[R9, n])
        qds[R9, n] = qds[R9, n] * qds[MNUMCR, n] / fsum(qds[R9, n])
        qrs[R9, n] = qrs[R9, n] * qrs[MNUMCR, n] / fsum(qrs[R9, n])
    for r in range(1, MNUMCR + 1):
        if r == 10:
            continue
        tot = qmg[r, n] + qjf[r, n] + qds[r, n] + qrs[r, n]
        if qmg[r, n] == 0.0 or qjf[r, n] == 0.0 or qds[r, n] == 0.0 or tot != tot:
            if tot != tot:
                raise ValueError(f"TDM TBENCHMARK: NaN fuel use in region {r}, {yrs}")

    mgbs, dsbs, jfbs = s["qmgbs"], s["qdsbs"], s["qjfbs"]
    tmg, tds, tjf = s["tmgtcbus"], s["tdstcpus"], s["tjftcbus"]
    if yrs <= yseds:
        jfbs[A11, n] = sjf[A11, n] - qjf[A11, n]
    elif yrs == ymer:
        jfbs[A11, n] = mer[A11, 2] - qjf[A11, n]
    elif yrs > ymer:
        if steobm == 1:
            if yrs <= ysteo:
                mgbs[A11, n] = qmg[A11, n - 1] * tmg[n] / tmg[n - 1] - qmg[A11, n]
                dsbs[A11, n] = qds[A11, n - 1] * tds[n] / tds[n - 1] - qds[A11, n]
                jfbs[A11, n] = qjf[A11, n - 1] * tjf[n] / tjf[n - 1] - qjf[A11, n]
            else:
                y = ysteo - 1989
                mgbs[A11, n] = mgbs[A11, y] / qmg[A11, y] * qmg[A11, n]
                dsbs[A11, n] = dsbs[A11, y] / qds[A11, y] * qds[A11, n]
                jfbs[A11, n] = jfbs[A11, y] / qjf[A11, y] * qjf[A11, n]
        else:
            y = ymer - 1989
            mgbs[A11, n] = mgbs[A11, y] / qmg[A11, y] * qmg[A11, n]
            dsbs[A11, n] = dsbs[A11, y] / qds[A11, y] * qds[A11, n]
            jfbs[A11, n] = jfbs[A11, y] / qjf[A11, y] * qjf[A11, n]
    mgbs[10, n] = 0.0
    dsbs[10, n] = 0.0
    jfbs[10, n] = 0.0
    qmg[A11, n] = qmg[A11, n] + mgbs[A11, n]
    qds[A11, n] = qds[A11, n] + dsbs[A11, n]
    qjf[A11, n] = qjf[A11, n] + jfbs[A11, n]
    s["qffv"][A11, n] = s["qettr"][A11, n]

    # e.g. B["mg"][r], indexed by region 1..MNUMCR
    B = {k[3:]: np.concatenate([np.zeros(1, dtype=f32), v[1:MNUMCR, n]]) for k, v in ben.items()}
    af, phev = s["pctaf"], s["pctevmt_phev"]
    p20, p50 = s["pctphev20"][n], s["pctphev50"][n]
    clt = np.zeros((TFRT_FUEL + 1, MNUMCR + 1), dtype=f32)
    ldv = np.zeros((MAXLDV + 1, MNUMCR + 1), dtype=f32)
    for r in range(1, MNUMCR + 1):
        if r == 10:
            continue
        mg, ds, el, hy = B["mg"][r], B["ds"][r], B["el"][r], B["hy"][r]
        clt[1:, r] = [mg, ds, B["lg"][r], B["ng"][r],
                      B["et"][r] * af[2, MNUMCR, n] + mg * (ONE - af[2, MNUMCR, n]), el,
                      el * phev[n, 4, r, 1] + ds * (ONE - phev[n, 4, r, 1]),
                      el * phev[n, 4, r, 2] + mg * (ONE - phev[n, 4, r, 2]), hy, hy, mg, hy]
        ldv[[1, 16], r] = mg
        ldv[[2, 8], r] = ds
        ldv[3, r] = B["et"][r] * af[2, r, n] + mg * (ONE - af[2, r, n])
        ldv[[4, 7, 15], r] = el
        ldv[5, r] = el * p20 + mg * (ONE - p20)
        ldv[6, r] = el * p50 + mg * (ONE - p50)
        ldv[9, r] = B["ng"][r] * af[3, r, n] + mg * (ONE - af[3, r, n])
        ldv[10, r] = B["lg"][r] * af[4, r, n] + mg * (ONE - af[4, r, n])
        ldv[11, r] = B["ng"][r]
        ldv[12, r] = B["lg"][r]
        ldv[13, r] = B["me"][r]
        ldv[14, r] = hy
    us = {k: v[MNUMCR] for k, v in B.items()}

    tq = s["tqldv"]
    for i, k in enumerate(("mg", "me", "et", "ng", "lg", "el", "hy", "ds"), start=1):
        s["btqldv"][i, A11] = tq[i, A11, n] * us[k]
        s["bfltfuelbtu"][A11, i, n] = s["fltfuelbtu"][A11, i, n] * us[k]
    fl, flt_t = s["fltldvbtu"], s["fltldvbtut"]
    for r in range(1, MNUMCR + 1):
        for v in range(1, MAXVTYP + 1):
            fl[r, v, 1:MAXLDV, n] = fl[r, v, 1:MAXLDV, n] * ldv[1:, r]
        flt_t[r, 1:MAXLDV, n] = fsum(fl[r, 1:MAXVTYP, 1:MAXLDV, n], axis=0)
    trk, btf = s["tfrbtu_f_t"], s["btqfreirsc"]
    for isc in (1, 2, 3):
        for i, k in enumerate(("ds", "mg", "lg", "ng", "et", "el", "hy"), start=1):
            btf[isc, i, A11] = trk[n, isc, i, A11] * us[k]
    ds_, rs_ = s["tqdshipr"], s["tqishipr"]
    s["btqdshipr"][1, A11] = ds_[1, A11, n] * us["ds"]
    s["btqdshipr"][2, A11] = ds_[2, A11, n] * us["rs"]
    s["btqdshipr"][3, A11] = ds_[3, A11, n]
    s["btqdshipr"][4, A11] = ds_[4, A11, n]
    s["btqishipr"][1, A11] = rs_[1, A11, n] * us["ds"]
    s["btqishipr"][2, A11] = (rs_[2, A11, n] + rs_[5, A11, n]) * us["rs"]
    s["btqishipr"][3, A11] = rs_[3, A11, n]
    s["btqishipr"][4, A11] = rs_[4, A11, n]
    rail = s["tqrailr"]
    s["btqrailr"][1, A11] = rail[1, A11, n] * us["ds"]
    s["btqrailr"][2, A11] = rail[2, A11, n] * us["rs"]
    s["btqrailr"][3, A11] = rail[3, A11, n]
    s["btqrailr"][4, A11] = rail[4, A11, n]
    s["trqrailr"][1, A11, n] = s["qmtrr"][2, A11, n] * us["el"]
    s["trqrailr"][2, A11, n] = s["qmtrr"][1, A11, n] * us["ds"]
    mil = s["qmiltr"]
    for i, k in enumerate(("ds", "jf", "rs", "jf"), start=1):
        s["bqmiltr"][i, A11] = mil[i, A11, n] * us[k]
    bclt = s["cltbtut"][1:TFRT_FUEL, A11, n] * clt[1:, MNUMCR][:, None]
    s["bqjetr"][A11] = s["qjetr"][A11, n] * us["jf"]
    s["bqagr"][A11] = s["qagtr"][A11, n]
    rec = s["qrecr"]
    s["bqrecr"][A11] = rec[1, A11, n] * us["mg"] + rec[2, A11, n] * us["ds"]
    s["bqlubr"][A11] = s["qlutr"][A11, n] * us["ot"]
    s["bcltbtut"][1:TFRT_FUEL, A11] = bclt
    cf = s["cltfuelbtu"]
    cf[:, n] = 0.0
    for i, k in enumerate(("mg", "ds", "lg", "ng", "et", "el", "hy"), start=1):
        cf[i, n] = s["cltfbtu"][n, i, MNUMCR] * us[k]
    bus = s["qmtbr"]
    for ib in (1, 2, 3):
        for i, k in enumerate(("mg", "ds", "et", "me", "ng", "lg", "el", "hy"), start=1):
            s["trqbus"][ib, i, n] = fsum(bus[ib, i, R9, n]) * us[k]

    bv, hh = s["bvmtech"], s["vmthh"]
    for r in range(1, MNUMCR - 1):
        bv[1:MAXLDV, r] = fsum(hh[n, r, 1:MAXLDV, 1:MAXVTYP], axis=1) * ldv[1:, MNUMCR]
    bv[1:MAXLDV, MNUMCR] = fsum(bv[1:MAXLDV, R9], axis=1)
    bstk, stk = s["bvmt_stk_hh"], s["vmt_stk_hh"]
    for il in range(1, MAXLDV + 1):
        bstk[1:MAXVTYP, il, 1:MAXAGE, 1, R9] = stk[1:MAXVTYP, il, 1:MAXAGE, 1, R9]
        fac = ONE
        t = fsum(stk[1:MAXVTYP, il, 1:MAXAGE, 1, R9])
        if t != 0.0:
            fac = f32(1000.0) * bv[il, MNUMCR] / t
        for v in range(1, MAXVTYP + 1):
            bstk[v, il, 1:MAXAGE, 1, R9] = bstk[v, il, 1:MAXAGE, 1, R9] * fac
    hav, fte = s["fltvmthav"], s["fltechvmt"]
    for v in range(1, MAXVTYP + 1):
        for fl_ in range(1, MAXFLEET + 1):
            for h in range(1, MAXHAV + 1):
                hav[v, fl_, 1:MAXLDV, h, yrs] = fte[MNUMCR, v, fl_, 1:MAXLDV, h] * ldv[1:, MNUMCR]
    s["bfltvmtech"][1:MAXVTYP, 1:MAXFLEET, 1:MAXLDV] = fsum(hav[1:MAXVTYP, 1:MAXFLEET, 1:MAXLDV, 1:MAXHAV, yrs], axis=3) / f32(1000000000.0)
    s["bcltvmt"][1:TFRT_FUEL, n] = s["cltvmtt"][1:TFRT_FUEL, n] * clt[1:, MNUMCR]

    saf, fv = s["vmtflt_saf_tr"], s["bfvmtechsc"]
    for r in range(1, MNUMCR + 1):
        flex = us["et"] * af[2, r, n] + us["mg"] * (ONE - af[2, r, n])
        two = lambda f: fsum(saf[1:2, f, r])  # noqa: E731
        ph = lambda isc, k, other: us["el"] * phev[n, isc, r, k] + us[other] * (ONE - phev[n, isc, r, k])  # noqa: E731
        fv[1, 1, r] = two(1) * us["ds"]
        fv[1, 2, r] = two(2) * us["mg"]
        fv[1, 3, r] = two(3) * us["lg"]
        fv[1, 4, r] = two(4) * us["ng"]
        fv[1, 5, r] = two(5) * flex
        fv[1, 6, r] = two(6) * us["el"]
        fv[1, 7, r] = saf[1, 7, r] * ph(1, 1, "ds") + saf[2, 7, r] * ph(2, 1, "ds")
        fv[1, 8, r] = saf[1, 8, r] * ph(1, 2, "mg") + saf[2, 8, r] * ph(2, 2, "mg")
        fv[1, 9, r] = two(9) * us["hy"]
        fv[1, 10, r] = two(10) * us["hy"]
        fv[1, 11, r] = two(11) * us["mg"]
        fv[1, 12, r] = two(12) * us["hy"]
        for f, val in ((1, us["ds"]), (2, us["mg"]), (3, us["lg"]), (4, us["ng"]), (5, flex), (6, us["el"]),
                       (7, ph(3, 1, "ds")), (8, ph(3, 2, "mg")), (9, us["hy"]), (10, us["hy"]), (11, us["mg"]), (12, us["hy"])):
            fv[2, f, r] = saf[3, f, r] * val
    if n >= 6:
        s["basmdemd"][1] = s["asmdemd"][1, 1, n]
        s["basmdemd"][2] = s["asmdemd"][1, 2, n]
    rtm, brtm, stm, bstm = s["rtmtt"], s["brtmtt"], s["stmtt"], s["bstmtt"]
    bd = s["btqdshipr"]
    for r in range(1, MNUMCR + 1):
        brtm[n, r] = rtm[n, r] if n <= int(s["railhistyr"]) else rtm[n, r] * us["ds"]
        if n <= int(s["shiphistyr"]) or not stm[n, r] > 0.0:
            bstm[n, r] = stm[n, r]
        else:
            bstm[n, r] = stm[n, r] * fsum(bd[1:4, r]) / fsum(ds_[1:4, r, n])
    s.update({"iregn": MNUMCR + 1, "ildv": MAXLDV + 1, "ivtyp": MAXVTYP + 1, "ifleet": MAXFLEET + 1, "ihav": MAXHAV + 1})
