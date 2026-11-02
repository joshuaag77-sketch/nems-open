"""Functions and the one subroutine every residential end use shares (resd.f):
SVRTE, RSELAST, EQCOST, rLearnCost and REPLACE.

They are not dumped on their own; they are checked through the routines that call them.
"""

import numpy as np

from nems_open.residential.common import BASEYR, ENDYR, MNUMBLDG, NUM_DIV, RECSYEAR, expf, f32, logf, powf, powi


_SVRTE = {}


def svrte(alpha, y, k, lam):
    """SVRTE: Weibull survival, the share of equipment still working at age y.
    Memoized on the arguments' bit patterns (it is pure)."""
    key = (f32(alpha).tobytes(), f32(y).tobytes(), f32(k).tobytes(), f32(lam).tobytes())
    v = _SVRTE.get(key)
    if v is None:
        if len(_SVRTE) > 500_000:
            _SVRTE.clear()
        v = _SVRTE[key] = _svrte(alpha, y, k, lam)
    return v


def _svrte(alpha, y, k, lam):
    if f32(y) - f32(alpha) < 0:
        return f32(1.0)
    k1 = f32(f32(f32(y) - f32(alpha)) / f32(lam))
    k2 = powf(k1, f32(k))
    return expf(-k2)


def rselast(s: dict, f: int, r: int, alpha, ef1, ef2, ef3, eupr: int):
    """RSELAST: short-run price response, this year's and the two previous years'
    prices against the RECS year, weighted by the distributed lags EF1-EF3.
    f is the RTEK fuel (4 = electricity, priced by end use from PELRSOUT)."""
    if f == 0:
        return f32(1.0)
    Y, Y1 = int(s["curcalyr"]), int(s["curiyr"])
    fac = [f32(1.0), f32(1.0), f32(1.0)]
    ef = (f32(ef1), f32(ef2), f32(ef3))
    for k in range(3):
        if Y >= RECSYEAR + 1 + k:
            if f == 4:
                p = s["pelrsout"]
                ratio = p[r, Y1 - k, eupr] / p[r, RECSYEAR - BASEYR + 1, eupr]
            else:
                P = s["prices"]
                ratio = P[f, r, Y - k] / P[f, r, RECSYEAR]
            fac[k] = powf(f32(ratio), f32(f32(alpha) * ef[k]))
    return fac[0] * fac[1] * fac[2]


def _text(v) -> str:
    return v.decode("latin-1").strip() if isinstance(v, bytes) else str(v).strip()


def eqcost(s: dict, recty: int, year: int, ctype: str):
    """EQCOST: installed ("CAP") or equipment-only ("RET") cost of menu record
    recty in calendar year `year`, flat for mature technologies and on a
    logistic decline for adolescent and infant ones."""
    base = s["rteqcost"][recty] if ctype == "CAP" else s["rtrecost"][recty]
    if ctype not in ("CAP", "RET"):
        return f32(10.0 ** 9)
    mat = _text(s["rtmature"][recty])
    rsyr2 = f32(year)
    d, gamma = s["rtcostp3"][recty], s["rtcostp2"][recty]
    if mat == "MATURE":
        return f32(base)
    if mat == "ADOLESCENT":
        y1, y0 = s["rtcostp1"][recty], f32(s["rtinityr"][recty])
        return f32(base * f32(2.0) * d / (f32(1.0) + powf(f32((rsyr2 - y1) / (y0 - y1)), gamma)) + (f32(1.0) - d) * base)
    if mat == "INFANT":
        y1, y0 = f32(s["rtinityr"][recty]), s["rtcostp1"][recty]
        return f32(base * d / (f32(1.0) + powf(f32((rsyr2 - y1) / (y0 - y1)), gamma)) + (f32(1.0) - d) * base)
    return f32(10.0 ** 9)


def rlearncost(max_cost, beta, c0, cum_ship):
    """rLearnCost: learning-curve cost from cumulative shipments, capped at max_cost."""
    if cum_ship <= 1.0 or c0 == 0.0:
        return f32(max_cost)
    return min(f32(max_cost), expf(logf(c0) - f32(beta) * logf(cum_ship)))


def _first_records(s: dict, eu: int, Y: int) -> dict:
    """For end use eu in year Y: equipment type -> the first menu record of that type
    available that year (the search REPLACE runs for every class). The menu tables never
    change, so it is worked out once per end use and year."""
    cache = s.setdefault("_first_records", {})
    if (eu, Y) not in cache:
        first = {}
        typt = s["rttyeupt"]
        for i in range(int(typt[eu]) + 1, int(typt[eu + 1]) + 1):
            eqt = int(s["rteqtype"][i])
            if eqt not in first and s["rtinityr"][i] <= Y <= s["rtlastyr"][i]:
                first[eqt] = i
        cache[eu, Y] = first
    return cache[eu, Y]


def replace(s: dict, eu: int, r: int, b: int, reccl: int, flag: int) -> None:
    """REPLACE: split retiring equipment of class reccl among all classes of the
    end use by a logit on life-cycle cost plus switching cost.

    flag 1: post-RECS homes, adds to EQCREP. Otherwise RECS-year homes: fills
    EQCSW90/EQCSW90R and the SWITCHES totals. Kept as in EIA: the share uses
    RPINSCOST(RECCL, RECCLSW), and the early return when a class has no current
    menu record leaves later classes untouched.
    """
    Y = int(s["curcalyr"])
    eupt, typt = s["rtcleupt"], s["rttyeupt"]
    eqcl, rtyp = s["rtcleqcl"], s["rtcltypt"]
    rpshare = s.setdefault("_rpshare", {})  # REPLACE's SAVEd local RPSHARE
    totsh = f32(0.0)
    if flag == 1:
        retired = s["oeqcrep"][Y, reccl, 1, r]
    else:
        retired = s["oeqcrp90"][Y, reccl, 1, r]
        retiredr = s["oeqcrp90r"][Y, reccl, 1, r]

    first = _first_records(s, eu, Y)
    for recclsw in range(int(eupt[eu]) + 1, int(eupt[eu + 1]) + 1):
        eqcsw, eqtsw = int(eqcl[recclsw]), int(rtyp[recclsw])
        if first.get(eqtsw, 0) == 0:
            return
        # CAPITAL and RETAIL are computed here in EIA's code but never used.
        rpshare[eqcsw] = expf(f32(s["rtswbias"][recclsw] + s["rtswbeta"][recclsw]
                                  * (s["lfcy"][eqtsw, b, r, 1] + f32(s["rpinscost"][reccl, recclsw]))))
        totsh = f32(totsh + rpshare[eqcsw])

    fact = s["rtswfact"][reccl]
    for recclsw in range(int(eupt[eu]) + 1, int(eupt[eu + 1]) + 1):
        eqcsw = int(eqcl[recclsw])
        rpshare[eqcsw] = f32(rpshare[eqcsw] / totsh) if totsh > 0.0 else f32(0.0)
        if flag == 1:
            s["eqcrep"][Y, recclsw, b, r] = s["eqcrep"][Y, recclsw, b, r] + retired * rpshare[eqcsw] * fact
        else:
            s["eqcsw90"][Y, reccl, recclsw, b, r] = retired * rpshare[eqcsw] * fact
            s["eqcsw90r"][Y, reccl, recclsw, b, r] = retiredr * rpshare[eqcsw] * fact

    if flag != 1:
        sw, swr = f32(0.0), f32(0.0)
        for recclsw in range(int(eupt[eu]) + 1, int(eupt[eu + 1]) + 1):
            if recclsw != reccl:
                sw = f32(sw + s["eqcsw90"][Y, reccl, recclsw, b, r])
                swr = f32(swr + s["eqcsw90r"][Y, reccl, recclsw, b, r])
        s["switches"][Y, reccl, b, r] = sw
        s["switchesr"][Y, reccl, b, r] = swr
    else:
        s["eqcrep"][Y, reccl, b, r] = s["eqcrep"][Y, reccl, b, r] + retired * (f32(1) - fact)


STOCK_FUTURES = (("eqr90fut", "eqcrp90"), ("eqr90rpfut", "eqcrp90rp"), ("eqrepfut", "eqcrep"), ("eqaddfut", "eqcadd"))


def vintage_future(s: dict, Y: int, lo: int, hi: int, pairs=STOCK_FUTURES) -> None:
    """Vintage the equipment of classes lo..hi from year Y into every later year:
    future[Y, y, class, b, r] = (stock[Y, class, b, r] * survival(y - Y)) * HDR(b) ** (y - Y),
    the block every ADD routine ends with. One array operation per class, building
    type and division instead of one per year; the same float32 products."""
    n = ENDYR - Y + 1
    HDR = s["hdr"]
    hsr = {b: np.array([powi(HDR[b], t) for t in range(n)], dtype=np.float32) for b in range(1, MNUMBLDG + 1)}
    for reccl in range(lo, hi + 1):
        alpha, k, lam = s["rtalpha"][reccl], s["rtk"][reccl], s["rtlambda"][reccl]
        esr = np.array([svrte(alpha, t, k, lam) for t in range(n)], dtype=np.float32)
        for b in range(1, MNUMBLDG + 1):
            for r in range(1, NUM_DIV + 1):
                for dst, src in pairs:
                    s[dst][Y, Y:ENDYR, reccl, b, r] = (s[src][Y, reccl, b, r] * esr) * hsr[b]


def running_sum(terms) -> np.float32:
    """0.0 + terms[0] + terms[1] + ... in float32, in order (a Fortran running sum)."""
    if terms.size == 0:
        return np.float32(0.0)
    return np.add.accumulate(terms.astype(np.float32))[-1]


def stock_average(s: dict, Y: int, reccl: int, b: int, d: int, first: int, rate_r: str, rate_n: str):
    """The stock-weighted average the CON routines take over vintages first..Y-1:
    TEMP = sum of (EQR90FUT + EQADDFUT + EQREPFUT + EQR90RPFUT), year by year in that order, and
    sum of ((EQR90FUT*rate_r) + ((EQADDFUT + EQREPFUT) + EQR90RPFUT)*rate_n) / TEMP.
    Returns (TEMP, average), the average None when TEMP <= 0."""
    v = slice(first, Y - 1)
    a90, add = s["eqr90fut"][v, Y, reccl, b, d], s["eqaddfut"][v, Y, reccl, b, d]
    rep, rp = s["eqrepfut"][v, Y, reccl, b, d], s["eqr90rpfut"][v, Y, reccl, b, d]
    temp = running_sum(np.stack([a90, add, rep, rp], axis=-1).reshape(-1))
    if temp <= 0.0:
        return temp, None
    return temp, running_sum(((a90 * s[rate_r][v, reccl, b, d]) + ((add + rep + rp) * s[rate_n][v, reccl, b, d])) / temp)
