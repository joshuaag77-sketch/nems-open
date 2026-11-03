"""EFP routine GL (uefp.f): gathers the dispatch model's results for one region and
operating component (ICALL = 'G' generation, 'T' transmission, 'D' distribution).

GL reads the region's blocks from EMM's direct-access files: GETOUT (DISPOUT),
GETIN (DISPIN, from EDISPA) and GETBLD (BILDIN). The caller passes the DISPOUT and
BILDIN blocks as region_block, a dict of plain lowercase names (the oracle's
fs_out dump with the region suffix removed). EDISPA is in the state.
"""

import numpy as np

from nems_open.emm.efp.common import f32, f64, i, put

EFD_D_CAP = 54  # emmparm: EFD_D_DSP + EFD_D_RNW + EFD_D_DGN

# COMMON /DISPOUT/ and /BILDIN/ in storage order. EOUT and EBILDN are byte views of
# these blocks (EQUIVALENCE), so they are rebuilt from the same order.
DISPOUT_ORDER = (
    "marcst", "marcst2", "martyp", "ertom", "ertomf", "ertomx", "ertgsub", "eemrm", "ertfl", "ertso2",
    "erthg", "ertnox", "etallw", "etso2", "etnox", "etco2", "etcar", "etco1", "etvoc", "ethg", "ewgfix",
    "etgen", "ewgown", "ewgrev", "ewgrrc", "ewgrcc", "ewgric", "ewgrnw", "egallw", "egpso2", "egso2",
    "ecscap", "ecsadd", "ecsret", "erpom", "erpfl", "eqpgn", "eqpgn_alt", "eqpflgn", "eqpcp", "eqpfl",
    "eqpflcn", "eqpso2", "eqpnox", "eqpco2", "eqphg", "erffl", "erffc", "eqfgn", "eqffl", "eqfso2", "eqfnox",
    "eqfco2", "eqfhg", "epfuel", "epflpr", "efrso2", "efrnox", "efrco2", "efrhg", "efhcnt", "ehscap",
    "ehsadd", "ehscapp2", "ehsaddp2", "ehsret", "eqhgn", "erhom", "eqhcp", "edscap", "edsadd", "edsret",
    "eqdgn", "erdom", "erdfl", "eqdcp", "eqdfl", "eqdso2", "eqdnox", "eqdco2", "eqdhg", "egenps", "eavlps",
    "ecapps", "egenhs", "ecaphs", "egends", "eavlds", "ecapds", "epeak", "etdmmf", "etdmme", "etdmdf",
    "etdmde", "etimpf", "etimpe", "etimpd", "etexpf", "etexpe", "etdmpe", "etexpd", "ewgrxo", "ewgryo",
    "ppcap", "ppom", "ppfuel", "erso2", "errps", "erdscar", "ecscapsq", "eqpgnsq", "eqpgnsq_alt", "enso2",
    "enfltp", "enmfl", "lftout",
)

BILDIN_ORDER = (
    "ep$lf", "epfpm", "ephght", "eppeak", "ep_net_peak", "epspk", "epwdth", "epnox_g", "epecap", "epecap_mr",
    "epecap_upv", "epncap", "eprgm", "ephtrt_aer", "epphrt0", "epphrtn", "epwdcof", "epext", "epbldbnd",
    "epch4rt", "epco1rt", "epco2rt", "epcrbrt", "epnoxrt", "epsoxrt", "epvocrt", "epirovr", "epirfom",
    "epirvom", "epirccr", "epirccs", "epcpadj", "epbdsup", "epccsup", "epfxsup", "epvrsup", "epiacf",
    "epicfc", "upicfc", "upicfc_dpv", "episcf", "epigcf", "eprcfc", "epfmap", "epflrg", "epcrmp", "epsovr",
    "epscap", "epalso2", "epalnox", "epalco2", "updnoxl", "eouncp", "eouccp", "eprpsrg", "eprpstg", "eprpsro",
    "eprpsto", "epdscrt", "eputdscrt", "epuror", "epuirt", "epufdt", "epufpe", "epucre", "epurorr", "epuirtr",
    "epufper", "epucrer", "eprtbs", "epmrm", "epacm", "epxprt", "epcovr", "eprscfc", "epcrbpen", "epctrm",
    "epccrf", "epcfom", "eptcst", "eptcrf", "eptloss", "epupclf", "epnpclf", "eppclrhs", "epunit", "epfom",
    "epgfom", "epvom", "epgcap", "epecfc", "epescfc", "epecfc_upv", "epdpct", "epdavd", "ep_sp_cap_fac",
    "eorder", "epfrst", "epgecp", "epgett", "epldgr", "epgecps", "epldsg", "eplmap", "epnext", "epngrp",
    "epnmsp", "epnspg", "epnstp", "epsett", "epnscr", "epsrec", "eptirgn", "epcensus", "epngrg", "epclrg",
    "epcarg", "epbndtyp", "eplovr",
)


def _copy_in(s, block, order):
    """Copy a block's variables into the state, as the READ into COMMON does."""
    for name in order:
        if name not in block or name not in s:  # the dump holds only what the routine mentions
            continue
        v = block[name]
        if hasattr(v, "a"):
            s[name].a[...] = v.a
        else:
            put(s, name, v)


def _bytes_view(block, order, size, nblocks, s=None):
    """The block's bytes in COMMON order, as the EQUIVALENCEd CHARACTER*size array of nblocks
    elements. LFTOUT runs one byte past the last DISPOUT block, so the view cuts it there; the
    BILDIN variables stop short of its last block, which holds zeros after them."""
    parts = []
    for name in order:
        v = s[name] if s is not None and name in s else block[name]  # the state wins: GL changes some
        a = v.a if hasattr(v, "a") else np.asarray(v)
        parts.append(np.asarray(a).tobytes(order="F"))
    blob = b"".join(parts)[: nblocks * size]
    return np.frombuffer(blob.ljust(nblocks * size, bytes(1)), dtype=f"S{size}")


def getout(s, block):
    """GETOUT(CURIYR, NRGN): DISPOUT from the region's block."""
    _copy_in(s, block, DISPOUT_ORDER)
    if "eout" in s:
        s["eout"].a[...] = _bytes_view(block, DISPOUT_ORDER, 8192, len(s["eout"].a))


def getbld(s, block):
    """GETBLD(1, NRGN): BILDIN from the region's block."""
    _copy_in(s, block, BILDIN_ORDER)
    if "ebildn" in s:
        s["ebildn"].a[...] = _bytes_view(block, BILDIN_ORDER, 16384, len(s["ebildn"].a))


def getin(s, nrgn):
    """GETIN(1, NRGN): EINPUT (the byte view of DISPIN) = EDISPA(:, NRGN)."""
    s["einput"].a[...] = s["edispa"][:, nrgn]


# OUTRP2 is a byte view of /EFPRP2/ (EQUIVALENCE (DEMREP,OUTRP2)). EFPBLK(5,2) and PPWRBLK(4)
# start after 938 REAL*4 (DEMREP .. SILOSS, MNUMNR-3 = 25 regions). The dump drops trailing NULs.
_OUTRP2_EFPBLK = 938 * 4


def _sync_outrp2(s):
    """Write EFPBLK and PPWRBLK into the OUTRP2 byte view, where the Fortran stores them."""
    if "outrp2" not in s:
        return
    new = s["efpblk"].a.tobytes(order="F") + s["ppwrblk"].a.tobytes(order="F")
    old = bytes(s["outrp2"]).ljust(_OUTRP2_EFPBLK + len(new), bytes(1))
    s["outrp2"] = type(s["outrp2"])(old[:_OUTRP2_EFPBLK] + new + old[_OUTRP2_EFPBLK + len(new):])


def gl(s, nrgn, icall, region_block):
    """GL(NRGN, ICALL): changes the state in place."""
    _gl(s, nrgn, icall, region_block)
    _sync_outrp2(s)


def _gl(s, nrgn, icall, region_block):
    curiyr = i(s, "curiyr")
    ertfl, ertom, ertso2, ertnox = s["ertfl"], s["ertom"], s["ertso2"], s["ertnox"]
    erthg, ertgsub = s["erthg"], s["ertgsub"]
    ertomf, ertomx = s["ertomf"], s["ertomx"]
    efpblk, ppwrblk = s["efpblk"], s["ppwrblk"]
    eqtlsl = s["eqtlsl"]
    efdpeak = s["efdpeak"]

    if icall == "G":
        getout(s, region_block)
        getin(s, nrgn)

        fom_all = f64(0.0)  # REAL*8
        for iefd in range(1, EFD_D_CAP + 1):
            fom_all = fom_all + f64(ertomf[iefd, 3]) + f64(ertomx[iefd, 3]) + f64(ertomf[iefd, 4]) + f64(ertomx[iefd, 4])
        # REAL*4 terms up to ERTOM(3), then REAL*8 from + FOM_ALL on
        t = f32(f32(s["ewgfix"] + ertfl[3]) + ertom[3])
        d = f64(t) + fom_all
        for term in (ertso2[3], ertnox[3], erthg[3]):
            d = d + f64(term)
        d = d - f64(ertgsub[3])
        for term in (ertfl[4], ertom[4], ertso2[4], ertnox[4], erthg[4]):
            d = d + f64(term)
        d = d - f64(ertgsub[4])
        put(s, "ewgrev", f32(d))
        efpblk[1, 1] = s["etdmdf"]
        efpblk[1, 2] = f32(s["etdmmf"] / f32(1000.0))
        efpblk[2, 1] = s["etdmde"]
        efpblk[2, 2] = f32(s["etdmme"] / f32(1000.0))
        efpblk[3, 1] = s["etimpd"]
        efpblk[3, 2] = f32(f32(s["etimpf"] + s["etimpe"]) / f32(1000.0))
        efpblk[4, 1] = f32(f32(-1.0) * s["etexpd"])
        efpblk[4, 2] = f32(f32(s["etexpf"] + s["etexpe"]) / f32(1000.0))

        efpblk[5, 1] = f32(f32(s["ewgrev"] + s["ewgrcc"]) + s["ewgric"])
        efpblk[5, 2] = s["ugntlnr"][2, nrgn, curiyr]

        p = f32(ertfl[3] + ertso2[3])
        for term in (ertnox[3], erthg[3]):
            p = f32(p + term)
        p = f32(p - ertgsub[3])
        for term in (ertfl[4], ertso2[4], ertnox[4], erthg[4]):
            p = f32(p + term)
        p = f32(p - ertgsub[4])
        ppwrblk[1] = p
        ppwrblk[2] = f32(f64(f32(ertom[3] + ertom[4])) + fom_all)
        ppwrblk[3] = s["ewgfix"]
        q = f32(s["ewgrcc"] + s["ewgric"])
        q = f32(q + s["etdmde"])
        q = f32(q + s["etimpd"])
        q = f32(q - s["etexpd"])
        q = f32(q + s["etdmdf"])
        ppwrblk[4] = q

        blksum = f32(0.0)
        for k in range(1, 6):
            blksum = f32(blksum + efpblk[k, 1])
        put(s, "blksum", blksum)
        efpfl = f32(ertfl[1] + ertfl[2])
        # renewable credits, SO2/NOX/Hg allowance costs, subsidy; a negative ERRPS is halved
        # in place (it stays halved in COMMON)
        if s["errps"] < 0.0:
            put(s, "errps", f32(s["errps"] * f32(0.5)))
        efpfl = f32(efpfl + s["errps"])
        for term in (ertso2[1], ertso2[2], ertnox[1], ertnox[2], erthg[1], erthg[2]):
            efpfl = f32(efpfl + term)
        efpfl = f32(efpfl - ertgsub[1])
        efpfl = f32(efpfl - ertgsub[2])
        efpfl = f32(f64(efpfl) + s["ercpptr"][nrgn, curiyr])  # REAL*8 term
        if s["bmelprc"][curiyr] > 0.0:
            efpfl = f32(efpfl - f32(s["bchmrksteoprc_n"][nrgn, curiyr] / f32(1000000)))
        put(s, "efpfl", efpfl)

        # nominal values
        for k in range(1, 6):
            efpblk[k, 1] = f32(efpblk[k, 1] * s["mc_jpgdp"][curiyr])

        efpom = f32(ertom[1] + ertom[2])
        put(s, "efpnuc", s["erffl"][i(s, "uiuf")])

        getbld(s, region_block)

        fom_all = f64(0.0)
        for iown in (1, 2):
            for iefd in range(1, EFD_D_CAP + 1):
                fom_all = fom_all + f64(ertomf[iefd, iown]) + f64(ertomx[iefd, iown])
        # (FOM_NUC, summed for the nuclear types, is never used)

        efpom = f32(efpom + f32(f32(s["gaadj"][1, nrgn, curiyr] * s["overpr"][nrgn]) * s["saltotold"]))
        efpom = f32(f64(efpom) + fom_all)
        put(s, "efpom", efpom)
        # EWGREV and ERRPS changed after GETOUT; EOUT is a view of the same storage
        if "eout" in s:
            s["eout"].a[...] = _bytes_view(region_block, DISPOUT_ORDER, 8192, len(s["eout"].a), s)
    else:
        put(s, "efpfl", f32(0.0))
        put(s, "blksum", f32(0.0))
        for k in range(1, 5):
            ppwrblk[k] = f32(0.0)
        put(s, "efpnuc", f32(0.0))
        tlsl = f32(eqtlsl[1] + eqtlsl[2])
        if icall == "T":
            # O&M for transmission equipment
            e = f32(s["omtslp"][nrgn] * tlsl)
            e = f32(e + f32(s["omtslp2"][nrgn] * efdpeak[nrgn]))
            e = f32(e + s["omtcon"][nrgn])
            e = f32(e + s["omtadder"][nrgn, curiyr])
            e = f32(e * s["omtscale"][nrgn, curiyr])
            e = f32(e + f32(f32(s["gaadj"][2, nrgn, curiyr] * s["overtr"][nrgn]) * tlsl))
            put(s, "efpom", e)
        else:
            # O&M for distribution equipment
            e = f32(s["omdslp"][nrgn] * tlsl)
            e = f32(e + f32(s["omdslp2"][nrgn] * efdpeak[nrgn]))
            e = f32(e + s["omdcon"][nrgn])
            e = f32(e * s["omdscale"][nrgn, curiyr])
            e = f32(e + f32(f32(s["gaadj"][3, nrgn, curiyr] * s["overds"][nrgn]) * tlsl))
            put(s, "efpom", e)
            efpfl = s["efpfl"]
            # carbon allowances given to load entities
            if i(s, "pcap_car") in (3, 4):
                getout(s, region_block)
                efpfl = f32(efpfl - s["erdscar"])
            # CPP allocation costs, if mass-based
            if i(s, "co2_stdsw") == 3 and s["co2_stdtn"][nrgn] == 2:
                getout(s, region_block)
                efpfl = f32(efpfl - s["erdscar"])
            # 111d EE expenses (1987 billion $ to million $), nuclear ZEC costs
            efpfl = f32(efpfl + f32(s["ecstnree"][nrgn, curiyr] * f32(1000.0)))
            efpfl = f32(efpfl + s["erzeccst"][nrgn])
            put(s, "efpfl", efpfl)
