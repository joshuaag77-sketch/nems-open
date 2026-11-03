"""CFREADSTOCK (tranfrt.f): freight truck stocks from the two stock CSVs, read on the first call.

Regional stocks 2012 to the stock base year by gross weight class, vocation, vintage
and fuel go to the 19 classes and split fleet / non-fleet; from 2016 the fleet split by
vintage follows the sales fleet share and fleet-to-non-fleet transfers, with the total
kept; then national totals, the three old size classes, fuel shares of new trucks, and
pre-2012 national stocks for trucks and commercial light trucks.
"""

import numpy as np

from nems_open.transportation.common import MNUMCR, f32, fsum
from nems_open.transportation.frt_common import AGE, CAFE19, FUEL12, V
from nems_open.transportation.readers.freight import TDM, _csv_rows

BSYR_STK = 2024
FLT, NFT = 2, 1
NVMT = 11
R9 = slice(1, MNUMCR - 2)
ONE = f32(1.0)


def cfreadstock(s: dict, tdm=TDM) -> None:
    v = V(s, angtdm=False)
    regn = _csv_rows(tdm / "trnstockx_hdv.csv")[:(MNUMCR - 2) * AGE * 6 * 12]
    natl = _csv_rows(tdm / "trnstockx_hdv_pre2012.csv")[:AGE * 6 * 4]
    trk, r19, s19, clt = v["trkstk"], v["trkstk_19r"], v["trkstk_19"], v["cltstk"]
    for a in (trk, r19, s19, clt):
        a.a[...] = 0.0
    fs, fsales, bm = v["fltshr_stk"], v["fltshr_sales"], v["base_mkt_p2"]
    nyr = BSYR_STK - 2011
    yrs = slice(23, 22 + nyr)

    def put(c, a2, f2, r2, vals, mult=None):
        nf = vals * (ONE - fs[yrs, c])
        fl = vals * fs[yrs, c]
        if mult is not None:
            nf, fl = mult(nf), mult(fl)
        r19[yrs, c, a2, f2, 1, r2] = nf
        r19[yrs, c, a2, f2, 2, r2] = fl

    for row in regn:
        r2, g2, v2, a2, f2 = (int(x) for x in row[:5])
        vals = np.array(row[5:5 + nyr], dtype=f32)
        if g2 == 2:
            put(1 + v2, a2, f2, r2, vals)
        elif g2 == 3:
            put(3 + v2, a2, f2, r2, vals)
        elif g2 in (4, 5, 6):
            put(g2 + 1, a2, f2, r2, vals)
        elif g2 == 7:
            if v2 == 0:
                for c in (9, 10, 11):
                    put(c, a2, f2, r2, vals, lambda x, c=c: x * bm[f2, c])
            elif v2 == 1:
                put(8, a2, f2, r2, vals)
        elif g2 == 8:
            if v2 == 0:
                tot = fsum(bm[f2, 13:18])
                for c in range(13, 19):
                    put(c, a2, f2, r2, vals, lambda x, c=c: x * bm[f2, c] / tot)
            elif v2 == 1:
                put(12, a2, f2, r2, vals)
        elif g2 == 9:
            put(19, a2, f2, r2, vals)

    sc19, tff = v["sc19map"], v["tffxgrt"]
    for y2 in range(2016 - 1989, BSYR_STK - 1989 + 1):
        check = fsum(r19[y2, :, :, :, :, R9])
        for iregn in range(1, MNUMCR - 1):
            for c in range(1, CAFE19 + 1):
                isc4 = int(sc19[c])
                for f in range(1, FUEL12 + 1):
                    for iage in range(1, y2 - (2016 - 1989) + 2):
                        temp = r19[y2, c, iage, f, 1, iregn] + r19[y2, c, iage, f, 2, iregn]
                        if iage == 1:
                            fl = temp * fsales[y2 - iage + 1, c]
                        else:
                            prod = ONE
                            for k in range(2, iage + 1):
                                prod = prod * (ONE - tff[k, isc4])
                            fl = temp * (fsales[y2 - iage + 1, c] * prod)
                        r19[y2, c, iage, f, FLT, iregn] = fl
                        r19[y2, c, iage, f, NFT, iregn] = temp - fl
        after = fsum(r19[y2, :, :, :, :, R9])
        if int(np.rint(check)) != int(np.rint(after)):
            r19[y2, :, :, :, :, R9] = r19[y2, :, :, :, :, R9] * check / after
    Y = slice(2012 - 1989, BSYR_STK - 1989)
    r19[Y, 1:CAFE19, 1:AGE, 1:FUEL12, 1:2, 11] = fsum(r19[Y, 1:CAFE19, 1:AGE, 1:FUEL12, 1:2, R9], axis=5)
    trk[Y, 1, 1:AGE, 1:FUEL12, 1:2] = fsum(r19[Y, 3:4, 1:AGE, 1:FUEL12, 1:2, 11], axis=1)
    trk[Y, 2, 1:AGE, 1:FUEL12, 1:2] = fsum(r19[Y, 5:7, 1:AGE, 1:FUEL12, 1:2, 11], axis=1)
    trk[Y, 3, 1:AGE, 1:FUEL12, 1:2] = fsum(r19[Y, 8:19, 1:AGE, 1:FUEL12, 1:2, 11], axis=1)
    s19[Y, 1:CAFE19, 1:AGE, 1:FUEL12] = fsum(r19[Y, 1:CAFE19, 1:AGE, 1:FUEL12, 1:2, 11], axis=4)

    shr, ivmt, veh = v["fuel_shr_regn"], v["fuel_shr_ivmt"], v["veh_shr"]
    shr.a[...] = 0.0
    with np.errstate(divide="ignore", invalid="ignore"):
        for y2 in range(2012 - 1989, BSYR_STK - 1989 + 1):
            for iregn in range(1, MNUMCR - 1):
                for c in range(1, CAFE19 + 1):
                    for fl in (1, 2):
                        tot = fsum(r19[y2, c, 1, :, fl, iregn])
                        shr[y2, c, 1:FUEL12, fl, iregn] = r19[y2, c, 1, 1:FUEL12, fl, iregn] / tot
                        ivmt[y2, 1:NVMT, fl, c, 1:FUEL12, iregn] = (shr[y2, c, 1:FUEL12, fl, iregn][None, :]
                                                                     * veh[1:NVMT, fl, c][:, None])

    H = slice(6, 2011 - 1989)
    b = 2012 - 1989
    for row in natl:
        g2, f2, a2 = (int(x) for x in row[:3])
        vals = np.array(row[3:3 + 2012 - 1995], dtype=f32)
        isc = g2 - 1
        if g2 == 1:
            if f2 in (1, 2):
                k = 2 if f2 == 1 else 1
                num = fsum(r19[b, 1, a2, f2, NFT, R9])
                den = fsum(r19[b, 1:2, a2, f2, 1:2, R9])
            elif f2 in (3, 4, 5, 6):
                k = f2
                num = fsum(r19[b, 1, a2, 2:FUEL12, NFT, R9])
                den = fsum(r19[b, 1:2, a2, 2:FUEL12, 1:2, R9])
            else:
                continue
            clt[H, k, a2, NFT, 11] = vals * num / den
            clt[H, k, a2, FLT, 11] = vals - clt[H, k, a2, NFT, 11]
        elif g2 in (2, 3, 4):
            cols, n = {2: (slice(3, 4), 2), 3: (slice(5, 7), 3), 4: (slice(8, 19), 12)}[g2]
            share = fsum(fs[H, cols], axis=1) / f32(n)
            trk[H, isc, a2, f2, FLT] = vals * share
            trk[H, isc, a2, f2, NFT] = vals - trk[H, isc, a2, f2, FLT]
    v["cltstkt"][1:6, H] = (fsum(fsum(clt[H, 1:6, 1:AGE, 1:2, 11], axis=2), axis=2) / f32(1000.0)).T
    s.update({v.key("iregn"): MNUMCR - 1, v.key("icafe19"): CAFE19 + 1, v.key("ifuel"): FUEL12 + 1,
              v.key("iflt"): 3, v.key("ivmt"): NVMT + 1})
