"""LDSM load forecast for one EMM region: DSMCADJ, DSMEMMV, DSMFOR (DSMARE, DSMACM,
DSMAIN, DSMATR) and DSMDLT, uldsm.f.

Each sector routine turns census-division electricity use into the region's
end-use loads (LoadForec(i,1), GWh) for the year being built (K1), from the
end-use detail of year UBASEYR scaled by the ratio of K1 to UBASEYR sales.
"""

from nems_open.emm.ldsm.common import (CMNUMBLDG, CMNUMSERV, COM, ELCOOLX, ELDRYEX, ELHEATX, ELINDEX, ELSECHX,
                                       ELSTOVX, ELWHEAX, HSTYEAR, IND, MNUMCGF, MSEDYR, RES, TRA, UNCONFA,
                                       UNCONFAR, f32, f64, i, put)


def dsmemmv(s, values, region, sector):
    """Census division values to one EMM region: sum of value x share, in REAL*4."""
    mapp = s["mappcton"]
    out = f32(0.0)
    for k in range(1, i(s, "ncensusreg") + 1):
        out = f32(out + f32(f32(values[k]) * mapp[region, k, sector]))
    return out


def dsmcadj(s):
    """Factors that scale commercial end-use load so it adds to commercial sales
    (with own-use distributed generation), every year from CURIYR to UNYEAR."""
    qelcm, cgen, euc, trq = s["qelcm"], s["cgcommgen"], s["enduseconsump"], s["trq_elec"]
    adj = s["comdemadjfac"]
    for kyr in range(i(s, "curiyr"), i(s, "unyear") + 1):
        for k in range(1, i(s, "ncensusreg") + 1):
            dggen = f64(0.0)
            for ifl in range(1, MNUMCGF + 1):
                # REAL*4 * 3412 / 1000000, then added to a REAL*8
                dggen = dggen + f64(f32(f32(cgen[k, kyr, ifl, 2] * f32(3412)) / f32(1000000)))
            qelcm_dg = f64(qelcm[k, kyr]) + dggen
            load = f32(0.0)
            loadoth = f32(0.0)
            for j in range(CMNUMSERV, 0, -1):
                if j == CMNUMSERV - 1:
                    loadoth = load  # load of the last service ("other") alone
                for b in range(1, CMNUMBLDG + 1):
                    load = f32(load + euc[ELINDEX, j, b, k, kyr])
            for j in range(2, 10):  # commercial EV charging
                load = f32(load + trq[j, k, kyr])
            if loadoth > 0.0:
                adj[k, 1, kyr] = f32((qelcm_dg - f64(load)) / f64(loadoth))
                adj[k, 2, kyr] = f32(0.0)
                if adj[k, 1, kyr] < -1.0:
                    adj[k, 1, kyr] = f32(-1.0)
                    adj[k, 2, kyr] = f32(qelcm_dg / f64(f32(load - loadoth)) - 1.0)
            elif loadoth == 0.0 and load == 0.0:
                adj[k, 1, kyr] = f32(-1.0)
                adj[k, 2, kyr] = f32(0.0)
            elif loadoth == 0.0 and load != 0.0:
                adj[k, 1, kyr] = f32(-1.0)
                adj[k, 2, kyr] = f32(qelcm_dg / f64(f32(load - loadoth)) - 1.0)
            else:
                adj[k, 1, kyr] = f32(0.0)
                adj[k, 2, kyr] = f32(0.0)


def _sales(s, name, xname, year):
    """Census sales for a year: the foresight array past the last model year."""
    a = s[xname] if year > i(s, "unyear") else s[name]
    return {k: a[k, year] for k in range(1, i(s, "ncensusreg") + 1)}


def _foresight(s, q, xq, sector, k1, ubase):
    """The region's sales in K1 and in UBASEYR."""
    rnb = i(s, "rnb")
    return (dsmemmv(s, _sales(s, q, xq, k1), rnb, sector),
            dsmemmv(s, _sales(s, q, xq, ubase), rnb, sector))


def _add(s, value):
    lf = i(s, "lfinum") + 1
    put(s, "lfinum", lf)
    s["loadforec"][lf, 1] = value


def dsmare(s):
    """Residential: 11 end uses (heating, cooling, water heating, cooking, drying,
    refrigeration, freezers, lighting, appliances, secondary heating, EV charging)."""
    sec = s["sec"][RES]
    rnb, k1, ubase, cur = i(s, "rnb"), i(s, "k1"), i(s, "ubaseyr"), i(s, "curiyr")
    nc = i(s, "ncensusreg")
    lk1, lbase = _foresight(s, "qelrs", "xqelrs", sec, k1, ubase)
    if lbase != 0:
        fadj = f32(f32(lk1 / lbase) * s["demcers"][k1 - cur + 1])
    else:
        fadj = f32(0.0)
    src = [lambda k: s["htrcon"][ubase, ELHEATX, k], lambda k: s["coolcn"][ubase, ELCOOLX, k],
           lambda k: s["h2ocon"][ubase, ELWHEAX, k], lambda k: s["ckcon"][ubase, ELSTOVX, k],
           lambda k: s["drycon"][ubase, ELDRYEX, k], lambda k: s["refcon"][ubase, k],
           lambda k: s["frzcon"][ubase, k], lambda k: s["ltcon"][ubase, k],
           lambda k: f32(f32(f32(f32(f32(s["apcon"][ubase, k] + s["cswcon"][ubase, k]) + s["dswcon"][ubase, k])
                                 + s["pcrcon"][ubase, k]) + s["tvrcon"][ubase, k]) + s["fancon"][ubase, k]),
           lambda k: s["shtcon"][ubase, ELSECHX, k]]
    for tgn, f in enumerate(src, 1):
        load = dsmemmv(s, {k: f(k) for k in range(1, nc + 1)}, rnb, sec)
        _add(s, f32(f32(load * UNCONFAR) * fadj))
        s["restgdem"][tgn] = s["loadforec"][i(s, "lfinum"), 1]
    # EV home charging: transport units, so the TBtu conversion
    load = dsmemmv(s, {k: s["trq_elec"][1, k, ubase] for k in range(1, nc + 1)}, rnb, sec)
    _add(s, f32(f32(load * UNCONFA) * fadj))
    s["restgdem"][11] = s["loadforec"][i(s, "lfinum"), 1]


def dsmacm(s):
    """Commercial: 11 building types x 10 services, each scaled by DSMCADJ's
    factors, then EV charging types (types 6 to 8 summed into one)."""
    sec = s["sec"][COM]
    rnb, k1, ubase, cur = i(s, "rnb"), i(s, "k1"), i(s, "ubaseyr"), i(s, "curiyr")
    nc = i(s, "ncensusreg")
    lk1, lbase = _foresight(s, "qelcm", "xqelcm", sec, k1, ubase)
    if lbase == 0:
        fadj = f32(0.0)
    else:
        fadj = f32(f32(lk1 / lbase) * s["demcecm"][k1 - cur + 1])
    euc, adj, trq = s["enduseconsump"], s["comdemadjfac"], s["trq_elec"]
    cv = {}
    for b in range(1, CMNUMBLDG + 1):
        for j in range(1, CMNUMSERV + 1):
            col = 1 if j == CMNUMSERV else 2
            for k in range(1, nc + 1):
                cv[k] = f32(euc[ELINDEX, j, b, k, ubase] * f32(f32(1.0) + adj[k, col, ubase]))
            load = dsmemmv(s, cv, rnb, sec)
            _add(s, f32(f32(load * UNCONFA) * fadj))
    for t in range(2, 10):
        for k in range(1, nc + 1):
            # types 7 and 8 add onto what the previous type left (6, then 6+7)
            cv[k] = f32(cv[k] + trq[t, k, ubase]) if t in (7, 8) else trq[t, k, ubase]
        if t < 6 or t > 7:
            load = dsmemmv(s, cv, rnb, sec)
            _add(s, f32(f32(load * UNCONFA) * fadj))


def dsmain(s):
    """Industrial: the industrial end uses; end use 4 is electrolyzer load from
    the hydrogen model, already by EMM region (MWh)."""
    sec = s["sec"][IND]
    rnb, k1, ubase, cur = i(s, "rnb"), i(s, "k1"), i(s, "ubaseyr"), i(s, "curiyr")
    nc = i(s, "ncensusreg")
    lk1, lbase = _foresight(s, "qelin", "xqelin", sec, k1, ubase)
    if lbase > 0.0:
        fadj = f32(f32(lk1 / lbase) * s["demcein"][k1 - cur + 1])
    else:
        fadj = f32(1.0)
    load = f32(0.0)
    cv = {}
    for e in range(1, int(s["neuses"][sec]) + 1):
        for k in range(1, nc + 1):
            if e == 4:
                load = f32(s["annual_h2_mwh_consumed"][rnb] / f32(f32(1000.0) * UNCONFA))
            else:
                cv[k] = s["qelinout"][k, ubase, e]
        if e != 4:
            load = dsmemmv(s, cv, rnb, sec)
        _add(s, f32(f32(load * UNCONFA) * fadj))


def dsmatr(s):
    """Transportation: rail and other non-EV transport load (TRQ_ELEC type 10)."""
    sec = s["sec"][TRA]
    rnb, k1, ubase, cur = i(s, "rnb"), i(s, "k1"), i(s, "ubaseyr"), i(s, "curiyr")
    nc = i(s, "ncensusreg")
    lk1, lbase = _foresight(s, "qeltr", "xqeltr", sec, k1, ubase)
    if lbase == 0:
        fadj = f32(0.0)
    else:
        fadj = f32(f32(lk1 / lbase) * s["demcetr"][k1 - cur + 1])
    load = dsmemmv(s, {k: s["trq_elec"][10, k, ubase] for k in range(1, nc + 1)}, rnb, sec)
    _add(s, f32(f32(load * UNCONFA) * fadj))


def dsmfor(s):
    """End-use load forecast for region RNB, year K1, all sectors."""
    put(s, "lfinum", 0)
    put(s, "totdemcensus", 0.0)
    sec = s["sec"]
    for n in range(1, i(s, "numsec") + 1):
        if sec[RES] == n:
            dsmare(s)
        elif sec[COM] == n:
            dsmacm(s)
        elif sec[IND] == n:
            dsmain(s)
        elif sec[TRA] == n:
            dsmatr(s)
    cur, ubase, uhbsyr = i(s, "curiyr"), i(s, "ubaseyr"), i(s, "uhbsyr")
    neu, rnb = i(s, "neu"), i(s, "rnb")
    lf = s["loadforec"]
    if cur == ubase and cur + uhbsyr <= i(s, "uyr_hist") and cur + uhbsyr >= HSTYEAR:
        if i(s, "unrgns") == 13:  # the 13-region EMM only; AEO2026 has 25
            for n in range(1, neu + 1):
                lf[n, 1] = f32(lf[n, 1] * s["histshr"])
    if i(s, "usw_cel") > 0:
        for n in range(1, neu + 1):
            if s["eugrp"][n] < 11 or s["eugrp"][n] > 20:  # commercial is already adjusted
                lf[n, 1] = f32(lf[n, 1] * s["uqelfac"][cur])
    if i(s, "k1") <= MSEDYR + 3:
        for n in range(1, neu + 1):
            s["baseyrld"][n, rnb] = lf[n, 1]
        load = f32(0.0)
        for n in range(1, neu + 1):
            load = f32(load + s["baseyrld"][n, rnb])
        s["baseyrsysld"][rnb] = load


def dsmdlt(s):
    """Each end use's change from the base year, net of system growth: LoadForec(i,2)."""
    rnb, n = i(s, "rnb"), i(s, "lfinum")
    lf = s["loadforec"]
    total = f32(0.0)
    for e in range(1, n + 1):
        total = f32(total + lf[e, 1])
    put(s, "systemload", total)
    slr = f32(total / s["baseyrsysld"][rnb])
    for e in range(1, n + 1):
        lf[e, 2] = f32(lf[e, 1] - f32(slr * s["baseyrld"][e, rnb]))
