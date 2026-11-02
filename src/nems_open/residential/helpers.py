"""Functions and the one subroutine every residential end use shares (resd.f):
SVRTE, RSELAST, EQCOST, rLearnCost and REPLACE.

They are not dumped on their own; they are checked through the routines that call them.
"""

import numpy as np

from nems_open.residential.common import BASEYR, RECSYEAR, f32


def svrte(alpha, y, k, lam):
    """SVRTE: Weibull survival, the share of equipment still working at age y."""
    if f32(y) - f32(alpha) < 0:
        return f32(1.0)
    k1 = (f32(y) - f32(alpha)) / f32(lam)
    k2 = f32(k1 ** f32(k))
    return f32(np.exp(-k2))


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
            fac[k] = f32(f32(ratio) ** f32(f32(alpha) * ef[k]))
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
        return f32(base * f32(2.0) * d / (f32(1.0) + ((rsyr2 - y1) / (y0 - y1)) ** gamma) + (f32(1.0) - d) * base)
    if mat == "INFANT":
        y1, y0 = f32(s["rtinityr"][recty]), s["rtcostp1"][recty]
        return f32(base * d / (f32(1.0) + ((rsyr2 - y1) / (y0 - y1)) ** gamma) + (f32(1.0) - d) * base)
    return f32(10.0 ** 9)


def rlearncost(max_cost, beta, c0, cum_ship):
    """rLearnCost: learning-curve cost from cumulative shipments, capped at max_cost."""
    if cum_ship <= 1.0 or c0 == 0.0:
        return f32(max_cost)
    return min(f32(max_cost), f32(np.exp(f32(np.log(f32(c0))) - f32(beta) * f32(np.log(f32(cum_ship))))))


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

    for recclsw in range(int(eupt[eu]) + 1, int(eupt[eu + 1]) + 1):
        eqcsw, eqtsw = int(eqcl[recclsw]), int(rtyp[recclsw])
        rectysw = 0
        for i in range(int(typt[eu]) + 1, int(typt[eu + 1]) + 1):
            if s["rteqtype"][i] == eqtsw and s["rtinityr"][i] <= Y <= s["rtlastyr"][i]:
                rectysw = i
                break
        if rectysw == 0:
            return
        # CAPITAL and RETAIL are computed here in EIA's code but never used.
        rpshare[eqcsw] = f32(np.exp(f32(s["rtswbias"][recclsw] + s["rtswbeta"][recclsw]
                                        * (s["lfcy"][eqtsw, b, r, 1] + f32(s["rpinscost"][reccl, recclsw])))))
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
