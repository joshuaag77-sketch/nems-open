"""TFRTRPT (tranfrt.f), reached as TRANFRT(1): freight truck report totals.

VMT and fuel use benchmarked by fuel (the BEN* factors), truck counts, ton-miles,
MPG for new and stock trucks by size class and in total, and new-truck investment.
"""

import numpy as np

from nems_open.transportation.common import MNUMCR, f32, fsum
from nems_open.transportation.frt_common import AGE, FUEL12, ONE, SC, V
from nems_open.transportation.mean_funcs import harmonic_mean

CUR = 2
FNEW, FSTK = 1, 2


def tranfrt_report(s: dict) -> None:
    """TRANFRT(1): the per-call setup, then TFRTRPT."""
    v = V(s)
    # The same year setup as TRANFRT(0) ran just before; TFRTRPT itself reads only IYR, N, YRS.
    if "curiyr" in s:
        n = v.i("curiyr")
        s.update({v.key("iyr"): n, v.key("itr"): v.i("curitr"), v.key("n"): n, v.key("yrs"): v.i("curcalyr")})
    tfrtrpt(s)


def tfrtrpt(s: dict) -> None:
    v = V(s)
    iyr, n, yrs = v.i("iyr"), v.i("n"), v.i("curcalyr")
    b = lambda name: v[name][1:MNUMCR, iyr]  # noqa: E731
    ds, mg, el, hy = b("bends"), b("benmg"), b("benel"), b("benhy")
    pctaf, phev = v["pctaf"][2, 1:MNUMCR, iyr], v["pctevmt_phev_avg"]
    fv = np.zeros((FUEL12 + 1, MNUMCR + 1), dtype=f32)
    fv[1, 1:] = ds
    fv[2, 1:] = mg
    fv[3, 1:] = b("benlg")
    fv[4, 1:] = b("benng")
    fv[5, 1:] = b("benet") * pctaf + mg * (ONE - pctaf)
    fv[6, 1:] = el
    fv[7, 1:] = el * phev[iyr, 1:MNUMCR, 1] + ds * (ONE - phev[iyr, 1:MNUMCR, 1])
    fv[8, 1:] = el * phev[iyr, 1:MNUMCR, 2] + mg * (ONE - phev[iyr, 1:MNUMCR, 2])
    fv[9, 1:] = hy
    fv[10, 1:] = hy
    fv[11, 1:] = mg
    fv[12, 1:] = hy
    fv[1:, 1:][fv[1:, 1:] == 0.0] = 1.0
    temp = f32(1000000.0)
    temp_v = temp * f32(1000.0)

    fas, fbtu = v["tfr_vmt_fas_t"], v["tfr_fbtu_fas_t"]
    fasf, fbtuf = v["tfr_vmt_fasf_t"], v["tfr_fbtu_fasf_t"]
    tr, btr = v["tfr_vmt_tr"], v["tfr_fbtu_tr"]
    fas[iyr, 1:SC, 1:FUEL12, :] = 0.0
    fbtu[iyr, 1:SC, 1:FUEL12, :] = 0.0
    fasf[iyr, 1:SC, :] = 0.0
    fbtuf[iyr, 1:SC, :] = 0.0
    tr[iyr, :] = 0.0
    btr[iyr, :] = 0.0
    vfr, hrate, dmd = v["vmtfltr"], v["hrate"], v["fueldmdr"]
    # Running float32 sums, in the Fortran's loop order.
    trn, trs, btrs = tr[iyr, FNEW], tr[iyr, FSTK], btr[iyr, FSTK]
    for isc in range(1, SC + 1):
        fn, fs = fasf[iyr, isc, FNEW], fasf[iyr, isc, FSTK]
        bfs = fbtuf[iyr, isc, FSTK]
        for ifuel in range(1, FUEL12 + 1):
            an, a_s = fas[iyr, isc, ifuel, FNEW], fas[iyr, isc, ifuel, FSTK]
            bs = fbtu[iyr, isc, ifuel, FSTK]
            for iflt in (1, 2):
                for iregn in range(1, MNUMCR - 1):
                    f = fv[ifuel, iregn]
                    x = vfr[CUR, isc, FNEW, ifuel, iflt, iregn] * f / temp_v
                    an, fn, trn = an + x, fn + x, trn + x
                    for iage in range(1, AGE + 1):
                        t = (vfr[CUR, isc, iage, ifuel, iflt, iregn] / temp_v) * f
                        a_s, fs, trs = a_s + t, fs + t, trs + t
                    e = ((f32(1e-12) * hrate[isc, ifuel]) * f) * dmd[isc, ifuel, iflt, iregn]
                    bs, bfs, btrs = bs + e, bfs + e, btrs + e
            fas[iyr, isc, ifuel, FNEW], fas[iyr, isc, ifuel, FSTK] = an, a_s
            fbtu[iyr, isc, ifuel, FSTK] = bs
        fasf[iyr, isc, FNEW], fasf[iyr, isc, FSTK] = fn, fs
        fbtuf[iyr, isc, FSTK] = bfs
    tr[iyr, FNEW], tr[iyr, FSTK], btr[iyr, FSTK] = trn, trs, btrs
    v.s.update({v.key("isc"): SC + 1, v.key("ifuel"): FUEL12 + 1, v.key("iflt"): 3,
                v.key("iregn"): MNUMCR - 1, v.key("iage"): AGE + 1})

    stk = v["trkstk"][iyr, 1:SC, 1:AGE, 1:FUEL12, 1:2]          # (sc, age, fuel, flt)
    trk, trkf, trktr = v["tfr_trk_fas_t"], v["tfr_trk_fasf_t"], v["tfr_trk_tr"]
    new = stk[:, FNEW - 1]                                      # (sc, fuel, flt)
    trk[iyr, 1:SC, 1:FUEL12, FNEW] = fsum(new, axis=2) / temp
    trk[iyr, 1:SC, 1:FUEL12, FSTK] = fsum(fsum(stk, axis=3), axis=1) / temp
    trkf[iyr, 1:SC, FNEW] = fsum(fsum(new, axis=2), axis=1) / temp
    trkf[iyr, 1:SC, FSTK] = fsum(fsum(fsum(stk, axis=3), axis=2), axis=1) / temp
    trktr[iyr, FNEW] = fsum(new) / temp
    trktr[iyr, FSTK] = fsum(stk) / temp

    tmt = v["trk_tmt"]
    tmt[:, n] = 0.0
    if yrs > 2012:
        lf = v["frt_load_fact"]
        for isc in (1, 2, 3):
            tmt[isc, n] = fsum(fas[n, isc, 1:12, 2]) * lf[isc]

    mpg, sf = v["hdv_mpg"], v["vmtflt_sf_tr"]
    ft, fts, ftr = v["tfr_ftmpg"], v["tfr_ftmpg_s"], v["tfr_ftmpg_tr"]
    for isc in range(1, SC + 1):
        for ifuel in range(1, FUEL12 + 1):
            ft[iyr, isc, ifuel, FNEW] = mpg[iyr, isc, FNEW, ifuel]
            ft[iyr, isc, ifuel, FSTK] = harmonic_mean(mpg[iyr, isc, 1:AGE, ifuel], sf[isc, 1:AGE, ifuel, 11])
            if ft[iyr, isc, ifuel, FSTK] == 0:
                ft[iyr, isc, ifuel, FSTK] = ft[iyr - 1, isc, ifuel, FSTK]
        for ifns in (FNEW, FSTK):
            fts[iyr, isc, ifns] = harmonic_mean(ft[iyr, isc, 1:FUEL12, ifns], fas[iyr, isc, 1:FUEL12, ifns])
    for ifns in (FNEW, FSTK):
        ftr[iyr, ifns] = harmonic_mean(fts[iyr, 1:SC, ifns], fasf[iyr, 1:SC, ifns])
    v.s.update({v.key("isc"): SC + 1, v.key("ifuel"): FUEL12 + 1})
    v["tfr_invest_tr"][iyr] = (trkf[iyr, 1, FNEW] * f32(52500.) + trkf[iyr, 2, FNEW] * f32(52500.)
                               + trkf[iyr, 3, FNEW] * f32(110000.))
