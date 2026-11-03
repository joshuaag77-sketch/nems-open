"""ELEFP (uefp.f): the whole EFP call, and what sits around each component.

ELEFP sets EFP's iteration switches and clears the year's working arrays, calls EFP
for every region, then ELSET (prices into NEMS) and, on the last pass, REVGAP. EFP
runs a region's three components, generation (G), transmission (T) and distribution
(D). Each one is: ELGLTR (load the region's books from the direct-access files and
the lagged values), GL (the dispatch model's results), GENERA / TRANSM / DISTRI
(AVRPRC, and COMPPRC for generation under competitive pricing), ELLGTR (store the
books back).

The books come from `books.Books` (books.py): a store of the five direct-access files.
The dispatch model's DISPOUT block, which GL reads with GETOUT, is passed in as a
function nrgn -> {plain name: array}.

Quirks kept:
- ELGLTR on a later iteration reads RC record 1 (last year's) into the state, then
  overwrites most of it from the U* arrays of EUSPRC; ELLGTR stores them back to the same
  U* arrays and writes RC record 2.
- ELLGTR stores USLLP twice and ELGLTR reads ESLLP twice (repeats with no effect).
- On later iterations GL's GETBLD and CAPCOST's GETBLD/STRBLD read the BILDIN record from
  the file, so BILDIN fields that CAPCOST does not set keep the file's (ECP's) values.
- ELEFP's first year and first iteration (INICON and the ELRD* readers) is not ported.
- ADDUP and the reports at the last year are not ported (they only fill report arrays).
"""

import numpy as np

from nems_open.emm.efp import capcost, compprc, elset, gl
from nems_open.emm.efp.avrprc import avrprc
from nems_open.emm.efp.books import BLOCKS, ICOM
from nems_open.emm.efp.common import f32, i, put

MNUMNR = 28
NPTYP = 14
EITRAN, EIDIST = capcost.EITRAN, capcost.EIDIST

# EFP's working variables and the U* arrays that carry them between iterations and years:
# E(I) <-> U(I, ICOM, NRGN), I = 1,2 (private, public). Same pairs in ELGLTR and ELLGTR.
VECTORS = (
    ("erfdce", "urfdce"), ("ernitc", "urnitc"), ("eratsd", "uratsd"), ("erxfdc", "urxfdc"),
    ("erfdcd", "urfdcd"), ("erpsdv", "urpsdv"), ("erycwp", "urycwp"), ("ertup", "urtup"),
    ("erbcwp", "urbcwp"), ("erabde", "urabde"), ("erprdf", "urprdf"), ("erditc", "urditc"),
    ("edisnt", "udisnt"), ("epidef", "upidef"), ("eslndg", "uslndg"), ("erbde", "urbde"),
    ("eslprc", "uslprc"), ("errcwp", "urrcwp"), ("ercnbv", "urcnbv"), ("ercnad", "urcnad"),
    ("erafdl", "urafdl"), ("erdlrb", "urdlrb"), ("eraitc", "uraitc"), ("erfitc", "urfitc"),
    ("erafdc", "urafdc"), ("erffdc", "urffdc"), ("eroffs", "uroffs"), ("eredtf", "vredtf"),
    ("epind", "upind"), ("esllp", "usllp"), ("eslagn", "uslagn"), ("erprtx", "urprtx"),
    ("ersltx", "ursltx"), ("ertdwo", "urtdwo"), ("ertdrg", "urtdrg"), ("ercidc", "urcidc"),
    ("edisyr", "udisyr"), ("epiret", "upiret"), ("erfdc", "urfdc"), ("eratsf", "uratsf"),
    ("erndfpmt", "urqamt"),
)
# arrays with a leading index II: E(II, I) <-> U(II, I, ICOM, NRGN)
LEADING = (("erbl", "urbl", 4), ("epgw", "upgw", 16), ("epcgw", "upcgw", 16), ("epafdc", "upafdc", 16),
           ("eponln", "uponln", 16), ("episoc", "upisoc", 16), ("epadoc", "upadoc", 16))
# last year's values: lag(I) = current(I)
LAGS = (
    ("esemdl", "esemdt"), ("esempl", "esemps"), ("erobl", "erob"), ("erbndl", "erbond"), ("eramdl", "eramd"),
    ("errbl", "errb"), ("erpflps", "erpf"), ("erprfl", "erpref"), ("erabdl", "erabde"), ("erpdfl", "erprdf"),
    ("elprlt", "esprlt"), ("elprst", "esprst"), ("elprce", "esprce"), ("elprps", "esprps"),
    ("elrbrr", "errbrr"), ("elrcwp", "errcwp"), ("elcidc", "ercidc"), ("eltomn", "ertomn"),
    ("eltfln", "ertfln"), ("elbde", "erbde"), ("elaitc", "eraitc"), ("elfitc", "erfitc"),
    ("elafdc", "erafdc"), ("elffdc", "erffdc"), ("eloffs", "eroffs"), ("elprtx", "erprtx"),
    ("elsltx", "ersltx"), ("eltdwo", "ertdwo"), ("eltiex", "ertiex"), ("elllp", "esllp"),
    ("ellagn", "eslagn"), ("eltlsl", "eqtlsl"),
)


def _plant_types(icall):
    """The plant types whose existing assets belong to this component."""
    if icall == "G":
        return [t for t in range(1, NPTYP + 1) if t not in (EITRAN, EIDIST)]
    return [EITRAN] if icall == "T" else [EIDIST]


def _wrapped_build(s, books, call, nrgn, *args):
    """Run an UNEWBLD-based routine. UNEWBLD leaves BLINK = 0 in COMMON, which the port does not set."""
    before = len(books.builds)
    call(s, nrgn, *args)
    if len(books.builds) != before:
        put(s, "blink", 0)


def _capcost(s, books, nrgn, icall, n):
    """CAPCOST, with the BILDIN reads and writes it does for generation, ownership 1, around it:
    GETBLD(1,NRGN) first (first year's first pass, and every later pass) and STRBLD(1,NRGN) last.
    Nothing CAPCOST does before that point reads BILDIN."""
    curitr = i(s, "curitr")
    fullyr = int(s["usyear"][i(s, "curiyr")])
    io = icall == "G" and n == 1 and ((fullyr == i(s, "uestyr") and curitr == 1) or curitr > 1)
    if io:
        books.getbld(s, 1, nrgn)
    capcost.capcost(s, nrgn, icall, n)
    if io:
        books.strbld(s, 1, nrgn)


def elgltr(s, books, nrgn, icall):
    """Global to local: this region's and component's books into EFP's working variables."""
    curiyr, curitr, efpitr = i(s, "curiyr"), i(s, "curitr"), i(s, "efpitr")
    fullyr = int(s["usyear"][curiyr])
    icom = ICOM[icall]
    books.getrcy(s, nrgn, icall, curiyr)
    for n in (1, 2):
        _capcost(s, books, nrgn, icall, n)
    if icall == "G":
        capcost.allfac(s, nrgn)

    if curitr == 1 and efpitr == 1:
        if icall == "G" and curiyr + i(s, "uhbsyr") > i(s, "efpsyr"):
            _wrapped_build(s, books, capcost.anewbld, nrgn)
        books.geteb(s, nrgn, icall)
        if icall == "G":
            put(s, "npi", s["savnpi"])
            put(s, "nsl", s["savnsl"])
            books.getr(s, nrgn)
            if curiyr + i(s, "uhbsyr") >= i(s, "efpsyr"):
                _wrapped_build(s, books, capcost.eltran, nrgn)
            if curiyr + i(s, "uhbsyr") >= i(s, "efpsyr"):
                _wrapped_build(s, books, capcost.eldist, nrgn)
        else:
            put(s, "npi", 0)
            put(s, "nsl", 0)
        keep = np.array(_plant_types(icall)) - 1
        for e, u in (("eobkvl", "uobkvl"), ("eoasvl", "uoasvl"), ("eoaitc", "uoaitc"),
                     ("eoafdc", "uoafdc"), ("eoabde", "uoabde")):
            eo, uo = s[e].a, s[u].a
            eo[...] = 0.0
            eo[:, keep, :] = uo[:, keep, :]
        if fullyr > i(s, "uestyr"):
            books.getrc(s, nrgn, icall, 2)
            books.strrc(s, nrgn, icall, 1)
        else:
            books.getrc(s, nrgn, icall, 1)
    else:
        books.getrc(s, nrgn, icall, 1)
        for ii in (1, 2):
            for e, u in VECTORS:
                s[e][ii] = s[u][ii, icom, nrgn]
            for e, u, n in LEADING:
                for k in range(1, n + 1):
                    s[e][k, ii] = s[u][k, ii, icom, nrgn]
            for k in range(1, 17):
                for iii in (1, 2):
                    s["epycwp"][k, iii, ii] = s["upycwp"][k, iii, ii, icom, nrgn]
            put(s, "ertomd", s["urtomd"][icom, nrgn])
            put(s, "ertomt", s["urtomt"][icom, nrgn])
    books.sync_views(s)   # the byte views are the same memory as the named members


def ellgtr(s, books, nrgn, icall):
    """Local to global: save the first iteration's capital, last year's values, and the books."""
    curitr, efpitr = i(s, "curitr"), i(s, "efpitr")
    icom = ICOM[icall]
    if curitr == 1 and efpitr == 1:
        keep = np.array(_plant_types(icall)) - 1
        for e, u in (("eoabde", "uoabde"), ("eobkvl", "uobkvl")):
            s[u].a[:, keep, :] = s[e].a[:, keep, :]
        if icall == "D":
            books.strr(s, nrgn)
        books.streb(s, nrgn, icall)
    for ii in (1, 2):
        for lag, cur in LAGS:
            s[lag][ii] = s[cur][ii]
        for e, u in VECTORS:
            s[u][ii, icom, nrgn] = s[e][ii]
        for e, u, n in LEADING:
            for k in range(1, n + 1):
                s[u][k, ii, icom, nrgn] = s[e][k, ii]
        for k in range(1, 17):
            for iii in (1, 2):
                s["upycwp"][k, iii, ii, icom, nrgn] = s["epycwp"][k, iii, ii]
        s["urtomd"][icom, nrgn] = s["ertomd"]
        s["urtomt"][icom, nrgn] = s["ertomt"]
    books.strrc(s, nrgn, icall, 2)
    books.sync_views(s)


def genera(s, nrgn, icall):
    avrprc(s, nrgn, icall)
    if i(s, "usw_pol") == 4:
        compprc.compprc(s, nrgn)


def transm(s, nrgn, icall):
    avrprc(s, nrgn, icall)


def distri(s, nrgn, icall):
    avrprc(s, nrgn, icall)


def _gl(s, books, dispout, nrgn, icall):
    """GL, given the dispatch model's DISPOUT block for the region and, for generation, the
    BILDIN record in the file now (GL's GETBLD)."""
    block = dict(dispout(nrgn))
    raw = None
    if icall == "G":
        bild, raw = books.bildin_block(1, nrgn, s)
        block.update(bild)
    gl.gl(s, nrgn, icall, block)
    if raw is not None:
        BLOCKS["bld"].set_raw(s, raw)   # GL's view of BILDIN is the file's record exactly


def efp(s, books, dispout, nrgn):
    for icall, component in (("G", genera), ("T", transm), ("D", distri)):
        elgltr(s, books, nrgn, icall)
        _gl(s, books, dispout, nrgn, icall)
        component(s, nrgn, icall)
        ellgtr(s, books, nrgn, icall)


def elefp(s, books, dispout):
    """ELEFP: changes the state in place; `books` (books.Books) is read and written.
    dispout(nrgn) gives the dispatch model's DISPOUT block for a region (plain names)."""
    f = f32
    curiyr = i(s, "curiyr")
    efpitr = i(s, "efpitr")
    bmelprc = s["bmelprc"][curiyr]

    # EFP iteration switches (two EFP iterations when STEO benchmarking is on)
    put(s, "efpfcrl", 0)
    put(s, "efpitprt", 0)
    last_pass = (bmelprc > 0.0 and efpitr == 2) or bmelprc == 0.0
    if i(s, "fcrl") == 1 and last_pass:
        put(s, "efpfcrl", 1)
    if last_pass:
        put(s, "efpitprt", 1)

    fullyr = int(s["usyear"][curiyr])
    if fullyr == i(s, "uestyr") and i(s, "curitr") == 1:
        raise NotImplementedError("ELEFP's first year, first iteration: INICON, ELRDPI, ELRDSL, ELRDTR, ELRDAL, ELRDFR")

    s["_efpbld"] = books.builds   # UNEWBLD (capcost.py) writes builds here
    if "lastbld" not in s:        # the Fortran's LASTBLD: the last record in use
        s["lastbld"] = np.int32(len(books.builds))

    unrgns = i(s, "unrgns")
    # expenses and capital expenses for competitive pricing, cost of service
    for nrgn in range(1, MNUMNR + 1):
        s["compcap"][nrgn, curiyr] = f(0.0)
        s["compex"][nrgn, curiyr] = f(0.0)
        s["dgapold"][nrgn] = f(1.0)
        for isect in range(1, 5):
            s["costserv"][isect, nrgn, curiyr] = f(0.0)

    # EFD peak load, for the T&D cost calculations
    for nrgn in range(1, unrgns + 1):
        s["efdpeak"][nrgn] = f(0.0)
        for is_ in range(1, int(s["efdns"]) + 1):
            if s["ulpeak"][is_, nrgn] > s["efdpeak"][nrgn]:
                s["efdpeak"][nrgn] = s["ulpeak"][is_, nrgn]

    # costs of nuclear ZEC programs
    if i(s, "curitr") == 1 and efpitr == 1:
        erzeccst, epzecsub, elnucsbdy = s["erzeccst"], s["epzecsub"], s["elnucsbdy"]
        sw = i(s, "usw_zecsub")
        erzeccst[MNUMNR] = f(0.0)
        for nrgn in range(1, unrgns + 1):
            ec = elnucsbdy[i(s, "unstas") + 1, nrgn, curiyr]
            if sw == 1:
                erzeccst[nrgn] = epzecsub[nrgn, curiyr] if epzecsub[nrgn, curiyr] > 0.0 else ec
            elif sw == 2:
                erzeccst[nrgn] = epzecsub[nrgn, curiyr]
            elif sw in (3, 4):
                erzeccst[nrgn] = ec
            else:
                erzeccst[nrgn] = f(0.0)
            erzeccst[MNUMNR] = f(erzeccst[MNUMNR] + erzeccst[nrgn])

    for nrgn in range(1, unrgns + 1):
        efp(s, books, dispout, nrgn)

    elset.elset(s)
    if i(s, "efpfcrl") == 1:
        elset.revgap(s)
        with np.errstate(all="ignore"):
            for isect in range(1, 5):
                for nrgn in range(1, MNUMNR + 1):
                    s["costserv"][isect, nrgn, curiyr] = f(s["costserv"][isect, nrgn, curiyr] / s["mc_jpgdp"][curiyr])

    # a zero or NaN price is set to 9.999
    for nrgn in range(1, unrgns + 1):
        for isect in range(1, 5):
            p = s["eprice"][isect, 4, nrgn]
            if p <= 0.0 or np.isnan(p):
                s["eprice"][isect, 4, nrgn] = f(9.999)

    # (reports and ADDUP at the last year and last pass are not ported)
    books.sync_views(s)
