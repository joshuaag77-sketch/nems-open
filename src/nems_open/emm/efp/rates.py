"""EFP rate setting by sector: ELRATE and the three routines it calls (uefp.f).

ELRATE sends one operating component (G generation, T transmission, D distribution)
through FUNCTN (total costs into four cost pools), ALLOCT (pools to the four customer
classes) and RATES (revenue / sales = average price). RATES also builds the combined
price (ISECT=4) and class subsidies on the last pass, D.
"""

import numpy as np

from nems_open.emm.efp.common import f32, i, put
from nems_open.fortran_array import FArray

MNUMNR = 28
MAXRECS = 100   # edbdef: DB records per write
NUMTABS = 1     # RATES: one database table
_NR = MNUMNR - 3


def _quiet(fn):
    """Fortran divides by zero to Inf/NaN without a word; so does the port."""
    def wrapper(*args, **kwargs):
        with np.errstate(all="ignore"):
            return fn(*args, **kwargs)
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


@_quiet
def elrate(s, icall, nrgn):
    """Rates by sector for one operating component and region."""
    isect = {"G": 1, "T": 2, "D": 3}.get(icall)
    if isect is None:
        # ISECT is a SAVEd local in the Fortran: an unknown ICALL reuses the last value
        isect = s.get("_elrate_isect", 0)
    s["_elrate_isect"] = isect
    functn(s, isect, nrgn)
    alloct(s, isect, nrgn)
    rates(s, isect, nrgn)


@_quiet
def functn(s, isect, nrgn):
    """Revenue requirement into cost pools: fuel, variable O&M, fixed O&M, capital."""
    cost, ecost = s["cost"], s["ecost"]
    ertfln, ertomn, errvlg = s["ertfln"], s["ertomn"], s["errvlg"]
    eqtlsl, ppwrblk = s["eqtlsl"], s["ppwrblk"]

    for k in range(1, 5):
        cost[k, isect] = f32(0.0)
    for k in range(1, 4):
        ecost[k, nrgn] = f32(0.0)   # also wipes the G values when T or D runs

    cost[1, isect] = f32(ertfln[1] + ertfln[2])
    half = f32(0.5)
    cost[2, isect] = f32(half * f32(ertomn[1] + ertomn[2]))
    cost[3, isect] = f32(half * f32(ertomn[1] + ertomn[2]))
    cost[4, isect] = f32(f32(f32(f32(errvlg[1] + errvlg[2]) - cost[1, isect]) - cost[2, isect]) - cost[3, isect])

    sales = f32(eqtlsl[1] + eqtlsl[2])
    if isect == 1:
        blksum = s["blksum"]
        ecost[1, nrgn] = f32(f32(f32(f32(cost[1, isect] - blksum) + ppwrblk[1]) / sales))
        ecost[2, nrgn] = f32(f32(f32(cost[2, isect] + cost[3, isect]) + ppwrblk[2]) / sales)
        ecost[3, nrgn] = f32(ppwrblk[4] / sales)
        ecost[1, nrgn] = f32(ecost[1, nrgn] - ecost[3, nrgn])
    else:
        ecost[1, nrgn] = f32(f32(cost[1, isect] / sales) + ecost[1, nrgn])
        ecost[2, nrgn] = f32(f32(f32(cost[2, isect] + cost[3, isect]) / sales) + ecost[2, nrgn])


@_quiet
def alloct(s, isect, nrgn):
    """Cost pools to customer classes: REV(class, isect) and the factors COSTFC."""
    rev, costfc, cost = s["rev"], s["costfc"], s["cost"]
    demfac, tecfac = s["demfac"], s["tecfac"]
    hundred = f32(100.0)
    for icls in range(1, i(s, "nclass") + 1):
        rev[icls, isect] = f32(0.0)
        for icost in range(1, i(s, "ncost") + 1):
            costfc[icost, icls, isect] = f32(0.0)
            for itech in range(1, i(s, "ntech") + 1):
                costfc[icost, icls, isect] = f32(
                    f32(demfac[itech, icls] * f32(tecfac[itech, icost, isect] / hundred))
                    + costfc[icost, icls, isect])
            rev[icls, isect] = f32(rev[icls, isect] + f32(costfc[icost, icls, isect] * cost[icost, isect]))


def _saved(s, name, bounds):
    """A SAVEd local array of RATES (BPRICE, FPRICE): it keeps its values from call to call,
    so it lives in the state; zero at the first call (-finit-local-zero)."""
    if name not in s:
        s[name] = FArray.zeros(bounds, np.float32)
    return s[name]


def _fill_blank(arr):
    arr.a[...] = b" " * arr.a.dtype.itemsize


@_quiet
def rates(s, isect, nrgn):
    """Average price by class = revenue / sales. WRITE_DB_DATA calls are not ported
    (the record buffers COLV and COLVALS are still filled and reset)."""
    nclass = i(s, "nclass")
    curiyr = i(s, "curiyr")
    rev, salcls, eprice = s["rev"], s["salcls"], s["eprice"]
    bprice = _saved(s, "bprice", [(1, 5), (1, 4), (1, _NR)])
    fprice = _saved(s, "fprice", [(1, 5), (1, 4), (1, _NR)])

    # buffers for the database table
    s["looping"].a[...] = 0
    s["numcols"].a[...] = 0
    _fill_blank(s["dynstm"])
    _fill_blank(s["wrtstm"])
    s["colvals"].a[...] = 0.0
    s["colv"].a[...] = 0.0
    _fill_blank(s["chcolvals"])
    _fill_blank(s["chcolv"])

    hisyr1 = i(s, "uyr_hist") - i(s, "uhbsyr") - 1
    hisyr2 = i(s, "uyr_hist") - i(s, "uhbsyr")

    for icls in range(1, nclass + 1):
        if salcls[nrgn, icls] != 0.0:
            eprice[icls, isect, nrgn] = f32(rev[icls, isect] / salcls[nrgn, icls])
        else:
            eprice[icls, isect, nrgn] = f32(0.1)   # Fortran also prints a warning
        bprice[icls, isect, nrgn] = eprice[icls, isect, nrgn]
    eprice[nclass + 1, isect, nrgn] = f32(
        f32(f32(f32(rev[1, isect] + rev[2, isect]) + rev[3, isect]) + rev[4, isect])
        / f32(f32(f32(salcls[nrgn, 1] + salcls[nrgn, 2]) + salcls[nrgn, 3]) + salcls[nrgn, 4]))
    bprice[nclass + 1, isect, nrgn] = eprice[nclass + 1, isect, nrgn]

    # generation price for endogenous retirements
    if isect == 1:
        for isea in range(1, i(s, "efdns") + 1):
            for islc in range(1, int(s["elnvct"][isea]) + 1):
                s["elgenp"][islc, isea, nrgn] = f32(eprice[5, isect, nrgn] / s["mc_jpgdp"][curiyr])

    if isect == 3:
        for icls in range(1, nclass + 2):
            eprice[icls, 4, nrgn] = f32(0.0)
            if icls <= 4:
                rev[icls, 4] = f32(0.0)
            for jsect in range(1, 4):
                eprice[icls, 4, nrgn] = f32(eprice[icls, jsect, nrgn] + eprice[icls, 4, nrgn])
                if icls <= 4:
                    rev[icls, 4] = f32(rev[icls, 4] + rev[icls, jsect])
            bprice[icls, 4, nrgn] = eprice[icls, 4, nrgn]

        subpct = s["subpct"]
        if curiyr <= hisyr2:
            # historic regional revenues and sales (H1: year before the last data year, H2: last)
            revh1, revh2, salh1, salh2 = {}, {}, {}, {}
            thousand = f32(1000.0)
            for k, (hr, he) in enumerate([("hrevrsnr", "helrsnr"), ("hrevcmnr", "helcmnr"),
                                          ("hrevinnr", "helinnr")], start=1):
                revh1[k] = s[hr][nrgn, hisyr1]
                salh1[k] = f32(s[he][nrgn, hisyr1] * thousand)
                revh2[k] = s[hr][nrgn, hisyr2]
                salh2[k] = f32(s[he][nrgn, hisyr2] * thousand)

            revhrci = f32(0.0)
            revrci = f32(0.0)
            slshrci = f32(0.0)
            slsrci = f32(0.0)
            for icls in range(1, 4):
                if curiyr <= hisyr1:
                    revhrci = f32(revhrci + revh1[icls])
                    slshrci = f32(slshrci + salh1[icls])
                else:
                    revhrci = f32(revhrci + revh2[icls])
                    slshrci = f32(slshrci + salh2[icls])
                revrci = f32(revrci + rev[icls, 4])
                slsrci = f32(slsrci + salcls[nrgn, icls])

            revpct, revhpct, slshpct, slspct = {}, {}, {}, {}
            for icls in range(1, 4):
                revpct[icls] = f32(rev[icls, 4] / revrci)
                revh = revh1 if curiyr <= hisyr1 else revh2
                salh = salh1 if curiyr <= hisyr1 else salh2
                revhpct[icls] = f32(revh[icls] / revhrci) if revhrci > 0.0 else f32(0.0)
                slshpct[icls] = f32(salh[icls] / slshrci) if slshrci > 0.0 else f32(0.0)
                slspct[icls] = f32(salcls[nrgn, icls] / slsrci)

            for icls in range(1, 4):
                diffpct = f32(revpct[icls] - slspct[icls])
                diffhpct = f32(revhpct[icls] - slshpct[icls])
                subpct[icls, nrgn, curiyr] = f32(diffhpct - diffpct)

            salhrci = f32(0.0)
            for icls in range(1, 4):
                salhrci = f32(salhrci + salcls[nrgn, icls])
            if slshrci > 0.0:
                s["hisindrat"][nrgn] = f32(salcls[nrgn, 3] / salhrci)
            else:
                s["hisindrat"][nrgn] = f32(0.0)
        else:
            indrat = f32(1.0)   # the share-of-industry adjustment is commented out in the source
            revrci = f32(0.0)
            for icls in range(1, 4):
                subpct[icls, nrgn, curiyr] = f32(subpct[icls, nrgn, hisyr2] * indrat)
                revrci = f32(revrci + rev[icls, 4])

        # class prices with subsidies (the Fortran has three identical branches for 13, 22, 25 regions)
        for icls in range(1, 4):
            if salcls[nrgn, icls] > 0.0 and i(s, "unrgns") in (13, 22, 25):
                p = f32(f32(rev[icls, 4] + f32(revrci * subpct[icls, nrgn, curiyr])) / salcls[nrgn, icls])
                eprice[icls, 4, nrgn] = p
                fprice[icls, 4, nrgn] = p
                for isct in range(1, 4):
                    fprice[icls, isct, nrgn] = f32(
                        bprice[icls, isct, nrgn] * f32(eprice[icls, 4, nrgn] / bprice[icls, 4, nrgn]))
        for isct in range(1, 5):
            fprice[4, isct, nrgn] = eprice[4, isct, nrgn]
            fprice[5, isct, nrgn] = eprice[5, isct, nrgn]

    # EFP_EPRICE table: fill the record buffer; the write itself is not ported
    if i(s, "orclefp") == 1 and i(s, "fnrun") == 1 and i(s, "efpfcrl") == 1:
        tnum = 1
        put(s, "tnum", tnum)
        looping, colv = s["looping"], s["colv"]
        jpgdp = s["mc_jpgdp"][curiyr]
        itr = i(s, "curitr")

        def flush():
            s["colvals"].a[...] = colv.a[tnum - 1]
            looping[tnum] = 0

        def add(icls, label):
            looping[tnum] = looping[tnum] + 1
            r = int(looping[tnum])
            colv[tnum, 1, r] = curiyr
            colv[tnum, 2, r] = nrgn
            colv[tnum, 3, r] = itr
            colv[tnum, 4, r] = icls
            colv[tnum, 5, r] = label
            colv[tnum, 6, r] = f32(eprice[icls, label, nrgn] / jpgdp)
            colv[tnum, 7, r] = f32(bprice[icls, label, nrgn] / jpgdp)
            colv[tnum, 8, r] = f32(fprice[icls, label, nrgn] / jpgdp)
            if r == MAXRECS:
                flush()

        if looping[tnum] == 0:
            s["numcols"][tnum] = 8
            s["dynstm"][tnum] = b"INSERT INTO EFP_EPRICE VALUES(?,?,?,?,?,?,?,?,?)".ljust(s["dynstm"].a.dtype.itemsize)
            s["wrtstm"][tnum] = b"EFP_EPRICE".ljust(s["wrtstm"].a.dtype.itemsize)
        for icls in range(1, 6):
            add(icls, isect)
        if isect == 3:
            for icls in range(1, 6):
                add(icls, 4)
        # leftover records (CALL WRITE_DB_DATA not ported)
        for tnum in range(1, NUMTABS + 1):
            if looping[tnum] != 0:
                flush()
        put(s, "tnum", NUMTABS + 1)   # DO counter in COMMON ends one past its last value
