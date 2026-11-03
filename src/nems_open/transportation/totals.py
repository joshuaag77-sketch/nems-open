"""Light-duty fuel use and the module's fuel totals (tran.f): TCONS, TINTEG.

TCONS   household fuel use (gallons and Btu) by vintage, then by fuel, splitting
        flex-fuel, bi-fuel and plug-in hybrids by their alternative-fuel shares
TINTEG  total transportation use of each fuel by region, from every mode, into
        QBLK (before benchmarking); share of gasoline that is E10 only
"""

import numpy as np

from nems_open.transportation.common import MAXAGE, MAXLDV, MAXVTYP, MNUMCR, f32, fsum

R9 = slice(1, MNUMCR - 2)
QBLK_OUT = ["qmgtr", "qmetr", "qettr", "qngtr", "qlgtr", "qprtr", "qeltr", "qh2tr", "qdstr", "qrstr", "qjftr", "qottr"]


def tcons(s: dict) -> None:
    n = int(s["n"])
    gge, mpg, vmt = s["hhtechgge"], s["hhmpgstk"], s["hhtechvmt"]
    gge[1:MNUMCR, 1:MAXVTYP, 1:MAXLDV, 1:MAXAGE, n] = 0.0
    m = mpg[R9, 1:MAXVTYP, 1:MAXLDV, 1:MAXAGE, n]
    with np.errstate(divide="ignore", invalid="ignore"):
        gge[R9, 1:MAXVTYP, 1:MAXLDV, 1:MAXAGE, n] = np.where(m != 0.0, vmt[R9, 1:MAXVTYP, 1:MAXLDV, 1:MAXAGE] / m, f32(0.0))
    gge[MNUMCR, 1:MAXVTYP, 1:MAXLDV, 1:MAXAGE, n] = fsum(gge[R9, 1:MAXVTYP, 1:MAXLDV, 1:MAXAGE, n], axis=0)
    btu = s["hhtechbtu"]
    btu[1:MNUMCR, 1:MAXVTYP, 1:MAXLDV, n] = fsum(gge[1:MNUMCR, 1:MAXVTYP, 1:MAXLDV, 1:MAXAGE, n], axis=3) * s["cfmgq"][n] / f32(42.0)

    b = lambda ildv: fsum(btu[1:MNUMCR, 1:MAXVTYP, ildv, n], axis=1)  # noqa: E731
    af, one = s["pctaf"], f32(1.0)
    p20, p50 = s["pctphev20"][n], s["pctphev50"][n]
    q = s["tqldv"]
    q[1, 1:MNUMCR, n] = (b(1) + (b(5) * (one - p20)) + (b(6) * (one - p50)) + (b(3) * (one - af[2, 1:MNUMCR, n]))
                         + (b(10) * (one - af[4, 1:MNUMCR, n])) + (b(9) * (one - af[3, 1:MNUMCR, n])) + b(16))
    q[2, 1:MNUMCR, n] = b(13)
    q[3, 1:MNUMCR, n] = b(3) * af[2, 1:MNUMCR, n]
    q[4, 1:MNUMCR, n] = b(11) + (b(9) * af[3, 1:MNUMCR, n])
    q[5, 1:MNUMCR, n] = b(12) + (b(10) * af[4, 1:MNUMCR, n])
    q[6, 1:MNUMCR, n] = b(4) + b(7) + b(15) + (b(5) * p20) + (b(6) * p50)
    q[7, 1:MNUMCR, n] = b(14)
    q[8, 1:MNUMCR, n] = b(2) + b(8)


def tinteg(s: dict) -> None:
    n = int(s["n"])
    tq, flt, clt, trk = s["tqldv"], s["fltfuelbtu"], s["cltfbtu"], s["tfrbtu_f_t"]
    bus, rec, ship_i, ship_d, rail = s["qmtbr"], s["qrecr"], s["tqishipr"], s["tqdshipr"], s["tqrailr"]
    prail, mil, cf = s["qmtrr"], s["qmiltr"], s["cfmgq"]
    for iregn in range(1, MNUMCR + 1):
        if iregn == 10:
            for k in QBLK_OUT:
                s[k][iregn, n] = 0.0
            continue
        r = iregn
        truck = lambda fuel: fsum(trk[n, 1:3, fuel, r])  # noqa: E731
        s["qmgtr"][r, n] = (tq[1, r, n] + flt[r, 1, n] + clt[n, 1, r] + truck(2) + bus[1, 1, r, n] + bus[2, 1, r, n]
                            + bus[3, 1, r, n] + rec[1, r, n])
        s["qmetr"][r, n] = tq[2, r, n] + flt[r, 2, n]
        s["qettr"][r, n] = tq[3, r, n] + flt[r, 3, n] + bus[1, 3, r, n] + clt[n, 5, r] + truck(5)
        s["qngtr"][r, n] = (tq[4, r, n] + flt[r, 4, n] + clt[n, 4, r] + bus[1, 5, r, n] + bus[2, 5, r, n] + bus[3, 5, r, n]
                            + ship_i[3, r, n] + ship_d[3, r, n] + rail[3, r, n] + ship_i[4, r, n] + ship_d[4, r, n]
                            + rail[4, r, n] + prail[3, r, n] + prail[4, r, n] + truck(4))
        s["qlgtr"][r, n] = (tq[5, r, n] + flt[r, 5, n] + clt[n, 3, r] + bus[1, 6, r, n] + bus[2, 6, r, n] + bus[3, 6, r, n]
                            + truck(3))
        s["qprtr"][r, n] = s["qlgtr"][r, n]
        s["qeltr"][r, n] = prail[2, r, n]
        s["qh2tr"][r, n] = tq[7, r, n] + flt[r, 7, n] + clt[n, 7, r] + bus[1, 8, r, n] + truck(7)
        s["qdstr"][r, n] = (tq[8, r, n] + flt[r, 8, n] + clt[n, 2, r] + ship_i[1, r, n] + ship_d[1, r, n] + rec[2, r, n]
                            + rail[1, r, n] + mil[1, r, n] + bus[1, 2, r, n] + bus[2, 2, r, n] + bus[3, 2, r, n]
                            + prail[1, r, n] + truck(1))
        s["qrstr"][r, n] = ship_i[2, r, n] + ship_i[5, r, n] + ship_d[2, r, n] + rail[2, r, n] + mil[3, r, n]
        s["qjftr"][r, n] = s["qjetr"][r, n] + mil[2, r, n] + mil[4, r, n]
        s["qottr"][r, n] = s["qagtr"][r, n] + s["qlutr"][r, n]
        # Share of motor gasoline that is E10 only: recreational boats over all gasoline.
        s["e10share"][r, n] = ((rec[1, r, n] / (cf[n] * f32(1000000.0) / f32(42.0)) * f32(1000000.0))
                               / ((s["qmgtr"][r, n] / (cf[n] * f32(1000000.0) / f32(42.0))) * f32(1000000.0)))
    s["iregn"] = MNUMCR + 1
