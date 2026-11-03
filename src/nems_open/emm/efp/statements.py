"""EFP financial statements: STMTS, uefp.f.

For one region and one operating component (ICALL: G, T or D) STMTS fills the report
vectors (REVREQ, TAXINC, XINCST, BALSHT, FUNDS, SALES, PPCOST, CAPREQ, CSTCAP, CANPLT)
once per ownership type (1 = IOU, 2 = public), adds the revenue requirement to the
cost-of-service totals, and leaves the figures the cost-of-capital calculation reads
(ERBTXIT, XINTCH, TRNPL, DSTPL, TUTPL, CWIPINT, NTUTPL, CAPTAL, NCAPEX, SCAPEX,
N_PIS, S_PIS, RESPCT, COMPCT, INDPCT, COMPEX, COMPCAP) in COMMON.

Everything is REAL*4. NumPy 2 keeps float32 scalar arithmetic in float32 and Python
literals weak, so an expression of float32 operands rounds at each operator in
Fortran's left-to-right order, as gfortran does.
"""

import numpy as np

from nems_open.emm.efp.common import f32, i, put

MNUMNR = 28


def _zero(a, lo, hi):
    for j in range(lo, hi + 1):
        a[j] = f32(0.0)


def stmts(s, nrgn, icall):
    """Changes the state in place, as STMTS changes COMMON.

    Not ported (they move data to or from EMM's direct-access scratch files):
    CALL STRREP(N,NRGN,CURIYR,INDOC) after each ownership type and CALL STRRP2 for
    ICALL = 'D' only save the report buffers OUTREP/OUTRP2 for later reports.
    For ICALL = 'D' and N = 2, GETBLD(1,NRGN)/STRBLD(1,NRGN) load the whole bildin
    block of year 1 over COMMON and save it back with EPRTBS changed; only the
    EPRTBS sum is ported, not that overwrite of the rest of bildin (not needed for 'G').
    """
    indoc = {"G": 1, "T": 2, "D": 3}[icall]
    curiyr = i(s, "curiyr")
    fullyr = int(s["usyear"][curiyr])

    estshr, ipown = s["estshr"], s["ipown"]
    revreq, taxinc, xincst, balsht, funds = s["revreq"], s["taxinc"], s["xincst"], s["balsht"], s["funds"]
    sales, ppcost, capreq, cstcap, canplt = s["sales"], s["ppcost"], s["capreq"], s["cstcap"], s["canplt"]
    costserv, compex, compcap = s["costserv"], s["compex"], s["compcap"]
    erbl = s["erbl"]
    nocap = i(s, "nocap")
    zero = f32(0.0)

    # locals ERGNTX(2), ECOMDV(2): always set for N before they are read
    ergntx = [zero, zero, zero]
    ecomdv = [zero, zero, zero]
    bkitax = zero

    # initialize both national and regional total
    if icall == "G":
        compex[nrgn, curiyr] = zero
        compcap[nrgn, curiyr] = zero

    with np.errstate(all="ignore"):   # FUNDS(21) can divide by zero; Fortran gives Inf/NaN
        for n in (1, 2):
            if estshr[n] == 0.0:
                # zero out matrices if ownership category has no share
                if ipown[n] != 0 or ipown[3] != 0:
                    _zero(xincst, 1, 20)
                    _zero(balsht, 1, 26)
                    _zero(funds, 1, 21)
                    _zero(revreq, 1, 24)
                    _zero(sales, 1, 2)
                    _zero(ppcost, 1, 4)
                    for j in range(1, nocap + 1):
                        for k in range(1, 9):
                            capreq[j, k] = zero
                    _zero(cstcap, 1, 7)
                    _zero(canplt, 1, 3)
                continue   # (CALL STRREP skipped: file write only)

            def e(name):
                return s[name][n]

            # revenue requirements build up statement
            revreq[1] = e("ertup") - e("ercnbv") - e("edisnt")
            revreq[2] = e("errcwp")
            revreq[3] = e("ernfsn")
            revreq[4] = e("erwc")
            revreq[5] = e("erabde") - e("ercnad")
            revreq[6] = e("erprdf") + e("eslndg")
            revreq[7] = revreq[1] + revreq[2] + revreq[3] + revreq[4] - revreq[5] - revreq[6]
            revreq[8] = e("errbrr")
            revreq[9] = e("esrr")
            revreq[10] = revreq[8] * revreq[9]
            revreq[11] = e("ertomn")
            revreq[12] = e("ertfln")
            revreq[13] = e("erbde") + e("erndfpmt")
            revreq[14] = e("esllp") - e("eslagn")
            revreq[15] = e("errvrq") * e("egtxrt") + e("erprtx") + e("ersltx")
            revreq[16] = (e("errvrq") - e("ertfln") - e("ertomn") - e("ertdwo") - e("ertiex")
                          - e("esllp")) * e("esstxr")
            revreq[17] = (e("errvrq") - e("ertomn") - e("ertfln") - revreq[15] - revreq[16] - e("ertdrg")
                          - (e("ertiex") - e("ercidc")) - e("esllp")) * e("esftxr")
            revreq[18] = e("erfitc") + e("eredtf")
            revreq[19] = e("eraitc")
            revreq[20] = e("erffdc")
            revreq[21] = e("erafdc")
            revreq[22] = e("eroffs") + e("epind")
            revreq[23] = (revreq[11] + revreq[12] + revreq[13] + revreq[14] + revreq[15] + revreq[16]
                          + revreq[17] - revreq[18] - revreq[19] - revreq[20] - revreq[21] - revreq[22])
            revreq[24] = revreq[10] + revreq[23]

            costserv[indoc, nrgn, curiyr] = costserv[indoc, nrgn, curiyr] + revreq[24]
            costserv[indoc, MNUMNR, curiyr] = costserv[indoc, MNUMNR, curiyr] + revreq[24]
            costserv[4, nrgn, curiyr] = costserv[4, nrgn, curiyr] + revreq[24]
            costserv[4, MNUMNR, curiyr] = costserv[4, MNUMNR, curiyr] + revreq[24]

            if icall == "G":
                compex[nrgn, curiyr] = compex[nrgn, curiyr] + revreq[23] - revreq[13]
                compex[MNUMNR, curiyr] = compex[MNUMNR, curiyr] + revreq[23] - revreq[13]

            # tax accounts
            ergntx[n] = e("errvlg") * e("egtxrt") + e("erprtx") + e("ersltx")
            bkitax = zero
            if n != 2:
                dedint = e("ertiex") - e("ercidc")
                stftax = (e("errvlg") - e("ertfln") - e("ertomn") - e("erndfpmt") - e("esllp") - e("erbde")
                          - ergntx[n] - dedint + e("erfdce")) * e("esftxr")
                adjbde = (e("erbde") - e("ertdwo")) * e("esftxr")
                adjadc = e("erfdce") * e("esftxr")
                sttax = (e("errvlg") - e("ertfln") - e("esllp") - e("ertomn") - e("ertdwo")
                         - e("ertiex")) * e("esstxr") * (1 - e("esftxr"))
                bkitax = (stftax + adjbde - adjadc - e("erafdc") - e("erffdc") - e("eredtf") - e("eraitc")
                          - e("erfitc") - e("eratsf") + sttax)
                citax = bkitax - e("ernitc") + e("eredtf") - e("eratsd") - e("erxfdc") + e("erafdc")
                taxinc[1] = citax
                taxinc[2] = e("eratsd") - e("eredtf")
                taxinc[3] = e("erxfdc")
                taxinc[4] = e("erafdc")
                taxinc[5] = taxinc[2] + taxinc[3] - taxinc[4]
                taxinc[6] = e("ernitc") + e("eraitc")
                taxinc[7] = e("eraitc")
                taxinc[8] = e("ernitc")
                taxinc[9] = bkitax
                taxinc[10] = stftax
                taxinc[11] = adjbde
                taxinc[12] = adjadc
                taxinc[13] = e("erfitc")
                taxinc[14] = e("eraitc")
                taxinc[15] = e("erffdc")
                taxinc[16] = e("erafdc")
                taxinc[17] = e("eratsf") + e("eredtf")
                taxinc[18] = sttax
                taxinc[19] = bkitax

            # income statement (for n = 2 BKITAX is 0 but ERGNTX is still used)
            xincst[1] = e("errvlg")
            xincst[2] = e("ertomn")
            xincst[3] = e("ertfln")
            xincst[4] = e("erbde") + e("erndfpmt")
            xincst[5] = e("esllp") - e("eslagn")
            xincst[6] = ergntx[n]
            xincst[7] = bkitax
            xincst[8] = xincst[2] + xincst[3] + xincst[4] + xincst[5] + xincst[6] + xincst[7]
            xincst[9] = xincst[1] - xincst[8]
            xincst[10] = e("erfdce")
            xincst[11] = xincst[9] + xincst[10]
            xincst[12] = e("erliex")
            xincst[13] = e("ersiex")
            xincst[14] = e("erfdcd")
            xincst[15] = xincst[12] + xincst[13] - xincst[14]
            xincst[16] = xincst[11] - xincst[15]
            xincst[17] = e("erpsdv")
            xincst[18] = e("epind") + e("epiret")
            xincst[19] = e("edisyr")
            xincst[20] = xincst[16] - xincst[17] + xincst[18] - xincst[19]

            # assignments for the cost of capital calculation
            if n == 1:
                s["erbtxit"][nrgn, indoc] = xincst[16] + (xincst[6] + xincst[7] + xincst[15])
                s["xintch"][nrgn, indoc] = xincst[15]

            # balance sheet: assets
            balsht[1] = erbl[1, n]
            balsht[2] = erbl[2, n]
            balsht[3] = erbl[3, n]
            balsht[4] = erbl[4, n]
            balsht[5] = e("erbcwp")
            balsht[6] = e("edisnt")
            balsht[7] = balsht[1] + balsht[2] + balsht[3] + balsht[4] + balsht[5] - balsht[6]
            balsht[8] = e("erabde")
            balsht[9] = balsht[7] - balsht[8]
            balsht[10] = e("ernfsn")
            balsht[11] = balsht[9] + balsht[10]
            balsht[12] = e("erwc")
            balsht[13] = e("epidef")
            balsht[14] = balsht[11] + balsht[12] + balsht[13]
            # liabilities
            balsht[16] = e("esprps") * e("eramd")
            balsht[19] = e("esprlt") * e("eramd")
            ecomdv[n] = e("edivrt") * xincst[20]
            balsht[17] = xincst[20] - ecomdv[n]
            balsht[15] = e("esprce") * e("eramd") - balsht[17]
            balsht[18] = balsht[15] + balsht[16] + balsht[17]
            balsht[20] = e("esprst") * e("eramd")
            balsht[21] = balsht[19] + balsht[20]
            balsht[22] = e("erditc")
            balsht[23] = e("erprdf")
            balsht[24] = e("eslndg")
            balsht[25] = balsht[22] + balsht[23] + balsht[24]
            balsht[26] = balsht[18] + balsht[21] + balsht[25]

            if n == 1:
                s["trnpl"][nrgn, indoc] = balsht[2]
                s["dstpl"][nrgn, indoc] = balsht[3]
                s["tutpl"][nrgn, indoc] = balsht[7]
                s["cwipint"][nrgn, indoc] = balsht[5]
                s["ntutpl"][nrgn, indoc] = balsht[11]

            # total capitalization for summation
            s["captal"][n, indoc] = balsht[15] + balsht[16] + balsht[19] + balsht[20]
            # IOU total capitalization to capacity planning
            if n == 2 and indoc == 3:
                # CALL GETBLD(1,NRGN) ... CALL STRBLD(1,NRGN): see docstring
                eprtbs = zero
                for j in (1, 2):
                    for k in (1, 2, 3):
                        eprtbs = eprtbs + s["captal"][j, k]
                put(s, "eprtbs", eprtbs)

            # sources and uses of funds
            funds[1] = xincst[16]
            funds[2] = xincst[4]
            funds[3] = e("ernitc")
            funds[4] = balsht[23]
            funds[5] = e("eslagn")
            funds[6] = e("erfdc")
            funds[7] = funds[1] + funds[2] + funds[3] + funds[4] - funds[5] - funds[6]
            funds[8] = balsht[20]
            funds[9] = balsht[19]
            funds[10] = balsht[15]
            funds[11] = balsht[16]
            funds[12] = e("eslprc")
            funds[13] = funds[8] + funds[9] + funds[10] + funds[11] + funds[12]
            funds[14] = funds[7] + funds[13]
            funds[15] = e("erycwp")
            funds[16] = ecomdv[n]
            funds[17] = e("erpsdv")
            funds[18] = balsht[12]
            funds[19] = balsht[10]
            if fullyr == i(s, "uestyr"):
                funds[19] = zero
            funds[20] = funds[15] + funds[16] + funds[17] + funds[18] + funds[19]
            funds[21] = zero
            if funds[15] != 0.0:
                # quirk kept: tests FUNDS(15) but divides by FUNDS(15)+FUNDS(19)
                funds[21] = (funds[7] - (funds[16] + funds[17])) / (funds[15] + funds[19]) * f32(100.0)

            # sales data for price calculations
            sales[1] = e("eqtlsl")
            sales[2] = s["blksum"] * estshr[n]
            for j in range(1, 5):
                ppcost[j] = s["ppwrblk"][j] * estshr[n]

            # capital requirements report
            captyp, numcap = s["captyp"], s["numcap"]
            for k in range(1, nocap + 1):
                for m in range(1, 9):
                    capreq[k, m] = zero
                for j in range(1, int(numcap[k]) + 1):
                    t = int(captyp[k, j])
                    capreq[k, 1] = capreq[k, 1] + s["epgw"][t, n]
                    capreq[k, 2] = capreq[k, 2] + s["epcgw"][t, n]
                    capreq[k, 3] = capreq[k, 3] + s["epycwp"][t, n, 1]
                    capreq[k, 4] = capreq[k, 4] + s["epafdc"][t, n]
                    capreq[k, 5] = capreq[k, 5] + s["eponln"][t, n]
                    capreq[k, 6] = capreq[k, 6] + s["epycwp"][t, n, 2]
                    capreq[k, 7] = capreq[k, 7] + s["episoc"][t, n]
                    capreq[k, 8] = capreq[k, 8] + s["epadoc"][t, n]
                if icall == "G" and bytes(s["captit"][k]).rstrip(b" \x00") == b"TOTAL PROD.":
                    # COMPCAP(NRGN) is assigned (n = 2 replaces n = 1); the national total adds both
                    compcap[nrgn, curiyr] = capreq[k, 3] + capreq[k, 6] + capreq[k, 4]
                    if nrgn <= i(s, "unrgns"):
                        compcap[MNUMNR, curiyr] = (compcap[MNUMNR, curiyr] + capreq[k, 3] + capreq[k, 6]
                                                   + capreq[k, 4])

            # assignments for the cost of capital
            if indoc == 1 and n == 1:
                nc, cl, og = i(s, "nc_ind"), i(s, "cl_ind"), i(s, "og_ind")
                s["ncapex"][nrgn] = s["ncapex"][nrgn] + capreq[nc, 6]
                s["scapex"][nrgn] = s["scapex"][nrgn] + capreq[cl, 6] + capreq[og, 6]
                s["n_pis"][nrgn] = capreq[nc, 7]
                s["s_pis"][nrgn] = capreq[cl, 7] + capreq[og, 7]

            # cost of capital data
            _zero(cstcap, 1, 7)
            cstcap[1] = e("esrtce")
            cstcap[2] = e("esemps")
            cstcap[3] = e("esrtps")
            cstcap[4] = e("esemdt")
            cstcap[5] = e("esrtlt")
            cstcap[6] = e("esrtst")
            cstcap[7] = e("esprce")
            cstcap[8] = e("esprps")
            cstcap[9] = e("esprlt")
            cstcap[10] = e("esprst")
            cstcap[11] = e("esrr")

            # cancelled nuclear plant report
            canplt[1] = e("ercnbv")
            canplt[2] = e("ercnad")
            canplt[3] = e("eravce")
            # CALL STRREP(N,NRGN,CURIYR,INDOC): file write only, skipped

    # demand factor report
    if icall == "G":
        demrep = s["demrep"]
        for ic in range(1, 5):
            demrep[1, ic, 1] = s["salcls"][nrgn, ic]
            for j in range(1, 10):
                demrep[j, ic, 2] = s["demfac"][j, ic]
            demrep[2, ic, 1] = s["fuelmr"][ic]
            demrep[3, ic, 1] = s["fuelem"][ic]
            demrep[4, ic, 1] = s["cust"][ic]
            demrep[5, ic, 1] = s["cp"][ic]
            demrep[6, ic, 1] = s["pcp"][ic]
            demrep[7, ic, 1] = s["ncp"][ic]
            demrep[8, ic, 1] = s["syslf"] * f32(100.0)
            demrep[9, ic, 1] = zero
        # assignments for the cost of capital calculation
        s["respct"][nrgn] = demrep[1, 1, 2]
        s["compct"][nrgn] = demrep[1, 2, 2]
        s["indpct"][nrgn] = demrep[1, 3, 2]
    # IF (ICALL .EQ. 'D') CALL STRRP2(NRGN,CURIYR): file write only, skipped
