"""EFP nuclear decommissioning, phase-in plans and sale/leasebacks (uefp.f):
ELND (calls NDRANN), ELPHIN (calls ELPIPY) and ELSL.

Same conventions as the LDSM ports: `s` is the state dict, changed in place the way
the Fortran changes COMMON. Locals that are REAL*4 are float32, rounded at every
operation in Fortran's left-to-right order.
"""

from nems_open.emm.efp.common import f32, i

# ---------------------------------------------------------------------------
# Nuclear decommissioning (efpnd COMMON /EFPND/, in declared order)
# ---------------------------------------------------------------------------
NDLIFE = 50


def _ndtaxr(s, k):
    """NDTAXR(k) as Fortran reads it. NDTAXR has NDLIFE = 50 elements, but NDRANN
    indexes it by year index (up to UNYEAR = 61), so elements 51.. are whatever follows
    in COMMON /EFPND/: NESTESC(1..50), then NDADMNR, NDEARNR, NDTCMON, NDPSER(1..3),
    NDPSCU(1..3), NUCAP(1..)."""
    if k <= NDLIFE:
        return s["ndtaxr"][k]
    k -= NDLIFE
    if k <= NDLIFE:
        return s["nestesc"][k]
    k -= NDLIFE
    if k <= 3:
        return (s["ndadmnr"], s["ndearnr"], s["ndtcmon"])[k - 1]
    k -= 3
    if k <= 3:
        return s["ndpser"][k]
    k -= 3
    if k <= 3:
        return s["ndpscu"][k]
    return s["nucap"][k - 3]


def ndrann(s, n, starty, endy, curey):
    """Real annuity payment (REAL*4) that builds unit N's decommissioning fund to its
    estimate. CUREY = -1 for no escalation (the only way ELND calls it)."""
    one = f32(1.0)
    unit = f32(1000.0)
    annbal = f32(0.0)
    curb = f32(s["ndcbal"][n])
    if curb == -1:
        curb = f32(0.0)
    runit = unit
    usyear1 = int(s["usyear"][1])
    unyear = i(s, "unyear")
    jp = s["mc_jpgdp"]
    ndearnr, ndadmnr = f32(s["ndearnr"]), f32(s["ndadmnr"])
    for iy in range(starty, endy + 1):
        k = iy - usyear1 + 1
        if k < 2:
            inflr = f32(f32(jp[2] / jp[1]) - one)
        elif k < unyear:
            inflr = f32(f32(jp[k] / jp[k - 1]) - one)
        else:
            inflr = f32(f32(jp[unyear] / jp[unyear - 1]) - one)
        taxr = _ndtaxr(s, 1 if k < 1 else k)
        netearnr = f32(f32(f32(inflr + ndearnr) - ndadmnr) * f32(one - taxr))
        if iy != starty:
            runit = f32(runit * f32(one + inflr))
        annbal = f32(f32(annbal * f32(one + netearnr)) + runit)
        curb = f32(curb * f32(one + netearnr))
    cure = f32(s["ndest"][n])
    if curey != -1:
        for iy in range(usyear1, curey + 1):
            k = iy - usyear1 + 1
            cure = f32(cure * s["nestesc"][k])
    rann = f32(f32(unit * f32(cure - curb)) / annbal)
    if rann < 0.0:
        rann = f32(0.0)
    return rann


def elnd(s, nrgn, iout, icall):
    """Nuclear decommissioning fund payments for region NRGN, nominal dollars.
    Sets ERNDFPMT, ERNDMON, ERERTSPLIT, ERCUPSPLIT; updates NDEST, NDCBAL, NDCAPMT.
    (iout, the report unit, is unused: the WRITEs are not ported. The local totals
    ERNDFBAL, ERNDFERN, ERNDFADM, ERNDETAX, ERNDFEST, ERNUNDF only feed the report.)"""
    one = f32(1.0)
    pmt_t, mon_t = s["erndfpmt"], s["erndmon"]
    ert, cup = s["erertsplit"], s["ercupsplit"]
    for kpp in (1, 2):
        pmt_t[kpp] = f32(0.0)
        mon_t[kpp] = f32(0.0)
        for ispl in (1, 2, 3):
            ert[kpp, ispl] = f32(0.0)
            cup[kpp, ispl] = f32(0.0)
    if icall != "G":
        return
    curiyr, unyear = i(s, "curiyr"), i(s, "unyear")
    jp = s["mc_jpgdp"]
    if curiyr <= 2:
        infl = f32(jp[2] / jp[1])
    elif curiyr <= unyear:
        infl = f32(jp[curiyr] / jp[curiyr - 1])
    else:
        infl = f32(jp[unyear] / jp[unyear - 1])
    inflr = f32(infl - one)
    ndearnr, ndadmnr, ndtcmon = f32(s["ndearnr"]), f32(s["ndadmnr"]), f32(s["ndtcmon"])
    ndcatch = i(s, "ndcatch")
    yr = int(s["usyear"][curiyr])
    taxr_now = s["ndtaxr"][curiyr]
    ndcbal, ndcapmt, ndest = s["ndcbal"], s["ndcapmt"], s["ndest"]
    earn = tax = adm = pmt = f32(0.0)
    for n in range(1, i(s, "nucnum") + 1):
        if s["nureg"][n] != nrgn:
            continue
        rets = int(s["nderet"][n])
        if rets == -1:
            rets = int(s["ndret"][n])
        if s["ndprmon"][n] != -1:
            retfce = rets + int(s["ndprmon"][n])
        else:
            retfce = rets
        if not (yr <= retfce):
            continue
        toearly = False
        ndest[n] = f32(ndest[n] * s["nestesc"][curiyr])
        if yr < ndcatch and yr < rets:
            # flat payment schedule before the catch-up year
            if yr == s["ndcbaly"][n]:
                earn = tax = adm = f32(0.0)
                pmt = f32(ndcbal[n])
            elif yr > s["ndcbaly"][n]:
                earn = f32(ndcbal[n] * f32(ndearnr + inflr))
                adm = f32(ndcbal[n] * ndadmnr)
                tax = f32(f32(earn - adm) * taxr_now)
                ndcapmt[n] = f32(ndcapmt[n] * infl)
                pmt = f32(ndcapmt[n])
                ndcbal[n] = f32(f32(f32(f32(ndcbal[n] + earn) - tax) - adm) + pmt)
            else:
                toearly = True
                earn = tax = adm = pmt = f32(0.0)
        elif yr < rets and s["nderet"][n] == rets:
            # early retirement, after catch-up
            ndcapmt[n] = f32(ndcapmt[n] * infl)
            earn = f32(ndcbal[n] * f32(ndearnr + inflr))
            adm = f32(ndcbal[n] * ndadmnr)
            tax = f32(f32(earn - adm) * taxr_now)
            pmt = ndrann(s, n, yr, int(s["ndret"][n]), -1)
            ndcbal[n] = f32(f32(f32(f32(ndcbal[n] + earn) - tax) - adm) + pmt)
        else:
            # maintenance period, and normal operation in the catch-up period
            # (the Fortran's ELSEIF USYEAR .LE. RETFCE is always true here; its
            # PASS = .TRUE. branch is unreachable)
            ndcapmt[n] = f32(ndcapmt[n] * infl)
            earn = f32(ndcbal[n] * f32(ndearnr + inflr))
            adm = f32(ndcbal[n] * ndadmnr)
            tax = f32(f32(earn - adm) * taxr_now)
            pmt = ndrann(s, n, yr, retfce, -1)
            ndcbal[n] = f32(f32(f32(f32(ndcbal[n] + earn) - tax) - adm) + pmt)
        for kpp in (1, 2):
            ppr = f32(s["nuppr"][n]) if kpp == 1 else f32(one - s["nuppr"][n])
            if ppr == 0.0:
                continue
            if not toearly:
                pmt_t[kpp] = f32(pmt_t[kpp] + f32(pmt * ppr))
            if yr >= rets:
                pmtsf = f32(pmt - ndcapmt[n])
                if pmtsf < 0.0:
                    pmtsf = f32(0.0)
                monitor = f32(ndtcmon * s["nucap"][n])
                for ispl in (1, 2, 3):
                    ert[kpp, ispl] = f32(ert[kpp, ispl] + f32(f32(pmtsf * s["ndpser"][ispl]) * ppr))
                mon_t[kpp] = f32(mon_t[kpp] + f32(monitor * ppr))
            elif yr >= ndcatch:
                pmtsf = f32(pmt - ndcapmt[n])
                if pmtsf < 0.0:
                    pmtsf = f32(0.0)
                for ispl in (1, 2, 3):
                    cup[kpp, ispl] = f32(cup[kpp, ispl] + f32(f32(pmtsf * s["ndpscu"][ispl]) * ppr))
    # payment reduced to the ratepayers' share only
    for kpp in (1, 2):
        for ispl in (2, 3):
            pmt_t[kpp] = f32(pmt_t[kpp] - f32(ert[kpp, ispl] + cup[kpp, ispl]))


# ---------------------------------------------------------------------------
# Phase-in plans
# ---------------------------------------------------------------------------
def _defer(s, i_, ipi, iyrpi):
    """One plan year of ELPHIN/ELPIPY: revenue requirement, deferred cost, return, and
    the updated PIDEF. Returns (DEFCST, PIRET)."""
    one = f32(1.0)
    yrpi = f32(iyrpi)
    averb = f32(0.0)
    if s["opavrb"][i_] == 1:
        averb = f32(0.5)
    pibkvl, pibklf, pidef = s["pibkvl"][ipi], s["pibklf"], s["pidef"]
    esftxr = s["esftxr"][i_]
    t = f32(pibkvl * f32(one - s["disper"][ipi]))
    t = f32(t * f32(one - f32(f32(yrpi - averb) / pibklf)))
    debt = f32(f32(s["esprlt"][i_] * s["esemdl"][i_]) + f32(s["esprst"][i_] * s["esrtst"][i_]))
    eq = f32(f32(f32(s["esprce"][i_] * s["esrtce"][i_]) + f32(s["esprps"][i_] * s["esempl"][i_]))
             / f32(one - esftxr))
    t = f32(t * f32(debt + eq))
    u = f32(f32(pibkvl / pibklf)
            * f32(one + f32(f32(f32(one - s["pitxbs"]) * esftxr) / f32(one - esftxr))))
    rr = f32(t + u)
    defcst = f32(f32(rr * f32(one - s["pidfs"][iyrpi, ipi])) * f32(one - esftxr))
    defcst = f32(defcst - f32(s["pircs"][iyrpi, ipi] * pidef[ipi]))
    piret = f32(0.0)
    if s["irdpi"][ipi] != 2:
        piret = f32(f32(pidef[ipi] + f32(f32(0.5) * defcst)) * s["esafdc"][i_])
    pidef[ipi] = f32(f32(pidef[ipi] + defcst) + piret)
    if iyrpi == s["lpi"][ipi]:
        defcst = f32(defcst - pidef[ipi])
        pidef[ipi] = f32(0.0)
        piret = f32(0.0)
    return defcst, piret


def elpipy(s, i_, ipi):
    """Phase-in years before the model starts: only PIDEF is carried forward."""
    pidfs, pidef = s["pidfs"], s["pidef"]
    ibklf = int(s["pibklf"])
    for iyrpi in range(1, i(s, "uestyr") - i(s, "uhbsyr") - int(s["ibyrpi"][ipi]) + 1):
        if 1 <= iyrpi <= ibklf and iyrpi <= s["lpi"][ipi]:
            if iyrpi != 1 and pidfs[iyrpi, ipi] != 0.0 and pidfs[iyrpi - 1, ipi] == 0.0:
                pidef[ipi] = f32(0.0)
            _defer(s, i_, ipi, iyrpi)


def elphin(s, nrgn):
    """Change in revenue-requirement components from phase-in/disallowance plans for
    region NRGN: ERBDED, EPIDEF, EPIND, EPIRET, EDISNT, EDISYR (also EBBKVL, PIBKVL, PIDEF)."""
    curiyr = i(s, "curiyr")
    fullyr = int(s["usyear"][curiyr])
    uestyr, uhbsyr = i(s, "uestyr"), i(s, "uhbsyr")
    pibklf = s["pibklf"]
    pidfs, pidef, pibkvl, disper = s["pidfs"], s["pidef"], s["pibkvl"], s["disper"]
    erbded, epind, epidef = s["erbded"], s["epind"], s["epidef"]
    epiret, edisnt, edisyr = s["epiret"], s["edisnt"], s["edisyr"]
    ebbkvl, ebnum = s["ebbkvl"], i(s, "ebnum")
    for i_ in (1, 2):
        erbded[i_] = f32(0.0)
        epind[i_] = f32(0.0)
        epidef[i_] = f32(0.0)
        epiret[i_] = f32(0.0)
        edisnt[i_] = f32(0.0)
        edisyr[i_] = f32(0.0)
        for ipi in range(1, i(s, "npi") + 1):
            if not (s["iropi"][1, ipi] == nrgn and s["iropi"][2, ipi] == i_):
                continue
            if fullyr == uestyr and s["ibyrpi"][ipi] <= uestyr - uhbsyr - 1:
                elpipy(s, i_, ipi)
            iyrpi = curiyr - int(s["ibyrpi"][ipi]) + 1
            yrpi = f32(iyrpi)
            if not (1 <= iyrpi <= int(pibklf)):
                continue
            if iyrpi <= s["lpi"][ipi]:
                if iyrpi != 1 and pidfs[iyrpi, ipi] != 0.0 and pidfs[iyrpi - 1, ipi] == 0.0:
                    ebbkvl[ebnum, i_] = f32(ebbkvl[ebnum, i_] + pidef[ipi])
                    pibkvl[ipi] = f32(pibkvl[ipi] + pidef[ipi])
                    pidef[ipi] = f32(0.0)
                defcst, piret = _defer(s, i_, ipi, iyrpi)
                epidef[i_] = f32(epidef[i_] + pidef[ipi])
                epind[i_] = f32(epind[i_] + defcst)
                epiret[i_] = f32(epiret[i_] + piret)
            if disper[ipi] != 0.0:
                edisnt[i_] = f32(edisnt[i_] + f32(f32(pibkvl[ipi] * f32(f32(1.0) - f32(yrpi / pibklf)))
                                                  * disper[ipi]))
                erbded[i_] = f32(erbded[i_] - f32(f32(pibkvl[ipi] * disper[ipi]) / pibklf))
                if iyrpi == 1:
                    edisyr[i_] = f32(edisyr[i_] + f32(pibkvl[ipi] * disper[ipi]))


# ---------------------------------------------------------------------------
# Sale/leasebacks
# ---------------------------------------------------------------------------
def elsl(s, nrgn):
    """Sale/leaseback adjustment for region NRGN: distribution build EBNUM's book and asset
    value, ERDLRB, and the regional ESLPRC, ESLLP, ESLAGN, ESLNDG."""
    curiyr, ebnum = i(s, "curiyr"), i(s, "ebnum")
    ebbkvl, ebasvl, erdlrb = s["ebbkvl"], s["ebasvl"], s["erdlrb"]
    esftxr = s["esftxr"]
    for i_ in (1, 2):
        s["eslprc"][i_] = f32(0.0)
        s["esllp"][i_] = f32(0.0)
        s["eslagn"][i_] = f32(0.0)
        s["eslndg"][i_] = f32(0.0)
        for isl in range(1, i(s, "nsl") + 1):
            if not (s["irosl"][1, isl] == nrgn and s["irosl"][2, isl] == i_):
                continue
            iyrsl = curiyr - int(s["ibyrsl"][isl]) + 1
            yrsl = f32(iyrsl)
            if iyrsl >= 1 and yrsl <= s["slterm"][isl]:
                if iyrsl == 1:
                    ebbkvl[ebnum, i_] = f32(ebbkvl[ebnum, i_] - s["slbkvl"][isl])
                    erdlrb[i_] = f32(erdlrb[i_] - s["slbkvl"][isl])
                    if esftxr[i_] != 0.0:
                        asvl = f32(s["slproc"][isl] - f32(s["sltaxs"][isl] / esftxr[i_]))
                    else:
                        asvl = f32(s["slbkvl"][isl])
                    ebasvl[ebnum, i_] = f32(ebasvl[ebnum, i_] - asvl)
                    s["eslprc"][i_] = f32(f32(s["eslprc"][i_] + s["slproc"][isl]) - s["sltaxs"][isl])
                s["esllp"][i_] = f32(s["esllp"][i_] + s["sllp"][isl])
                amor = f32(s["slgain"][isl] / s["slterm"][isl])
                s["eslagn"][i_] = f32(s["eslagn"][i_] + amor)
                s["eslndg"][i_] = f32(f32(s["eslndg"][i_] + s["slgain"][isl]) - f32(amor * yrsl))
