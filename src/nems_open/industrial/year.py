"""One model year of the industrial module: port of IND / ISEAM's yearly shell (ind.f).

IND runs several times a year (iterations with NCRL=0, the last with FCRL=1, then a reporting call). Each
iteration is Setup_Mac_and_Price, ISEAM, CALIBRATE_COAL_ELEC and WEXOG:

- ISEAM, on the first iteration of the year, rolls each industry-region's lag slots (this year's results
  become next year's lags), then for every industry and region reads its saved state (RDBIN), sets that region's
  production and employment (REXOG), picks the electricity price slot for the industry's load type, blends the
  covered and uncovered prices (INDBIFURC), runs MODCAL and saves the state (WRBIN). The process-flow industries
  (8, 10-13) run after their four regions, with their own models; here they are replayed (see standin.py).
- CALIBRATE_COAL_ELEC benchmarks each industry's electricity and steam coal to the ASM and QCR histories and
  re-adds them into the national totals.
- WEXOG benchmarks the totals to SEDS/STEO and writes QBLK.

State is an oracle-style dict `s` (COMMON and MODULE I_ variables) and the per-industry-region buffers `bufs`,
keyed (industry, region), that RDBIN and WRBIN copy in and out of the working variables. `start_state` builds
both from an oracle 'ys_in' dump (the state at the start of a year's first iteration).

Not ported: INDEASY, IRCOGEN, ADDUPCOGS and INDCGN (cogeneration reports for the other modules), CALIBRATE, CO2CALC and
INDUSREPORT (reporting call), PRICE (price sensitivities, off in the reference case), the base-year reads.
"""

import numpy as np

from nems_open.fortran_array import FArray
from nems_open.industrial.contab import contab
from nems_open.industrial.iseam import indbifurc, electricity_price_slot
from nems_open.industrial.modcal import modcal, PROCESS_FLOW
from nems_open.industrial.setup_price import setup_mac_and_price

f32 = np.float32
END_YR_ASM = 2022
END_YR_QCR = 2024
SCALARS = ("indmax", "prodx", "prodxlag", "prodvx", "prodvxlag", "emplx", "stemcur", "stemcurlag", "cogsteam", "noncogsteam",
           "biosteam", "biosteamlag", "noncogfossteam", "elown", "elsale", "mpastp", "phdrat", "inddir", "idval", "ifsbyp",
           "numrptgrps")
ARRAYS = ("enpmqty", "enpiqty", "enprqty", "enbint", "enbqty", "ensqty", "bsshr", "fuelfossteam", "cogboilfuel", "genfuel",
          "rptgen", "rptcap", "bypbscm", "bypbsci", "bypbscr", "bypadibyr", "prodretr", "prodcur", "prodlag", "prodflow",
          "enpint", "enpintlag", "enpqty", "bypint", "bypintlag", "bypqty", "idlcap", "idlcaplag", "ifslocby", "ntmax",
          "ifmax", "ipastp", "ifloc", "bcsc", "ifbyp", "iflocby", "bypcsc", "einter", "numrptgrpsteps", "rptgrpsteps")
REGIONAL = ("qtymain", "qtyintr", "qtyrenw")  # buffer holds one region's column of the shared (fuel, region) array


def start_state(ys: dict) -> tuple[dict, dict]:
    """(s, bufs) from an oracle 'ys_in' dump: the working state and the per-industry-region buffers."""
    s = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in ys.items() if not k.startswith("cb_")}
    bufs = {}
    for name in SCALARS + ARRAYS + REGIONAL:
        a = ys["cb_" + name]
        nd = a.a.ndim
        for d in range(1, 25):
            for r in range(1, 5):
                b = bufs.setdefault((d, r), {})
                v = a.a[(..., r - 1, d - 1)]
                if nd == 2:
                    b[name] = v[()]
                else:
                    b[name] = FArray(np.array(v), a.lb[:-2])
    s["_stepnames9"] = [None] + [x.decode("latin-1").strip() for x in np.asarray(ys["cb_indstepname9"].a)] if "cb_indstepname9" in ys else None
    return s, bufs


def rdbin(s: dict, bufs: dict) -> None:
    b = bufs[(int(s["inddir"]), int(s["indreg"]))]
    ir = int(s["indreg"])
    for n in SCALARS:
        s[n] = b[n]
    for n in ARRAYS:
        s[n] = b[n].copy()
    for n in REGIONAL:
        s[n][:, ir] = b[n].a
    s["inddir"] = np.int32(s["inddir"])


def wrbin(s: dict, bufs: dict) -> None:
    ir = int(s["indreg"])
    b = bufs[(int(s["inddir"]), ir)]
    for n in SCALARS:
        b[n] = s[n]
    for n in ARRAYS:
        b[n] = s[n].copy()
    for n in REGIONAL:
        v = s[n]
        b[n] = FArray(np.array(v.a[:, ir - 1]), (v.lb[0],))


def rexog(s: dict) -> None:
    ir, isect, curiyr = int(s["indreg"]), int(s["inddir"]), int(s["curiyr"])
    ix, iy = {1: (1, 2), 2: (3, 4), 3: (5, 7), 4: (8, 9)}[ir]
    prodvx, emplx = f32(0.0), f32(0.0)
    for d in range(ix, iy + 1):
        prodvx = f32(prodvx + s["outind"][isect, d, curiyr])
        emplx = f32(emplx + s["empind"][isect, d])
    s["prodvx"] = prodvx
    s["emplx"] = f32(emplx * f32(1000.0))
    if int(s["iyr"]) == int(s["ibyr2"]):
        s["prodvxlag"] = s["prodvx"]


def roll_lags(bufs: dict) -> None:
    for b in bufs.values():
        b["prodxlag"] = b["prodx"]
        b["prodvxlag"] = b["prodvx"]
        b["enpintlag"].a[...] = b["enpint"].a
        b["bypintlag"].a[...] = b["bypint"].a
        b["stemcurlag"] = b["stemcur"]
        b["prodlag"].a[...] = b["prodcur"].a
        b["idlcaplag"].a[...] = b["idlcap"].a


def set_electricity_price(s: dict) -> None:
    ir, curiyr = int(s["indreg"]), int(s["curiyr"])
    slot = electricity_price_slot(int(s["inddir"]))
    for k in (1, 2):
        s["prcx"][1, ir, k] = s["prcx"][slot, ir, k]
        s["prcxyr"][1, ir, curiyr, k] = s["prcxyr"][slot, ir, curiyr, k]


def base_memory(s: dict) -> dict:
    return {(d, r): (f32(s["prodvxibyr"][d, r]), f32(s["emplxibyr"][d, r])) for d in range(1, 25) for r in range(1, 5)}


def iseam(s: dict, bufs: dict, standin=None) -> None:
    """The model-year branch of ISEAM (year after the first ISEAM year)."""
    base = base_memory(s)
    if int(s["curitr"]) == 1:
        roll_lags(bufs)
    if int(s["iprice"]) == 1 and int(s["curcalyr"]) > int(s["techstrtyr"]):
        raise NotImplementedError("PRICE (price sensitivities) is not ported")
    for indnum in range(1, int(s["indmax"]) + 1):
        inddir = indnum
        s["inddir"], s["indnum"] = np.int32(inddir), indnum
        flow = inddir in PROCESS_FLOW
        if not flow:
            for ireg in range(1, 5):
                s["indreg"] = ireg
                rdbin(s, bufs)
                rexog(s)
                set_electricity_price(s)
                indbifurc(s)
                if inddir == 4:
                    if standin is None:
                        raise NotImplementedError("oil and gas mining needs a stand-in (standin.py)")
                    standin(s, inddir, ireg)
                else:
                    modcal(s, base, s["_stepnames9"], "original")
                wrbin(s, bufs)
        else:
            for ireg in range(1, 5):
                s["indreg"] = ireg
                rexog(s)
            for ireg in range(1, 5):
                s["indreg"] = ireg
                rdbin(s, bufs)
                rexog(s)
                slot = 24 if inddir in (7, 8, 9, 12, 13) else 25
                for k in (1, 2):
                    s["prcx"][1, ireg, k] = s["prcx"][slot, ireg, k]
                    s["prcxyr"][1, ireg, int(s["curiyr"]), k] = s["prcxyr"][slot, ireg, int(s["curiyr"]), k]
                indbifurc(s)
                if standin is None:
                    raise NotImplementedError("process-flow industries need a stand-in (standin.py)")
                standin(s, inddir, ireg)
                wrbin(s, bufs)


def calibrate_coal_elec(s: dict, bufs: dict) -> None:
    mainfuels, curiyr, curcalyr, ibyr = int(s["mainfuels"]), int(s["curiyr"]), int(s["curcalyr"]), int(s["ibyr"])
    qm, tqm, hb = s["qtymain"], s["tqmain"], s["hist_bench"]
    tqm[1, 1:5] = 0.0
    tqm[7, 1:5] = 0.0
    for ind in range(1, int(s["indmax"]) + 1):
        qm[1, 5] = 0.0
        qm[7, 5] = 0.0
        for ir in range(1, 5):
            qm[1:mainfuels, ir] = bufs[(ind, ir)]["qtymain"][1:mainfuels]
        qm[1, 5] = qm[1, 1:4].sum(dtype=f32)
        qm[7, 5] = qm[7, 1:4].sum(dtype=f32)
        for ir in range(1, 5):
            b = bufs[(ind, ir)]
            elown, enpm, ens, byp = b["elown"], b["enpmqty"].copy(), b["ensqty"].copy(), b["bypbscm"].copy()
            if qm[1, ir] != 0.0 and ind >= 7:
                if ibyr + 1 <= curcalyr <= END_YR_ASM:
                    hb[curiyr, ind, ir, 1] = f32(s["asmdata"][curiyr, ind, 5] / qm[1, 5])
                elif curcalyr > END_YR_ASM:
                    hb[curiyr, ind, ir, 1] = hb[curiyr - 1, ind, ir, 1]
                else:
                    hb[curiyr, ind, ir, 1] = f32(1.0)
                h = hb[curiyr, ind, ir, 1]
                qm[1, ir] = f32(qm[1, ir] * h)
                elown = f32(elown * h)
                enpm[1] = f32(enpm[1] * h)
                ens[1] = f32(ens[1] * h)
                byp[1] = f32(byp[1] * hb[curiyr, ind, 5, 1])
            if qm[7, ir] != 0.0 and ind >= 7:
                if ibyr <= curcalyr <= END_YR_QCR:
                    hb[curiyr, ind, ir, 7] = f32(s["qcrdata"][curiyr, ind, 5] / qm[7, 5])
                elif curcalyr > END_YR_QCR:
                    hb[curiyr, ind, ir, 7] = hb[curiyr - 1, ind, ir, 7]
                else:
                    hb[curiyr, ind, ir, 7] = f32(1.0)
                h = hb[curiyr, ind, ir, 7]
                qm[7, ir] = f32(qm[7, ir] * h)
                enpm[7] = f32(enpm[7] * h)
                ens[7] = f32(ens[7] * h)
                byp[7] = f32(byp[7] * hb[curiyr, ind, 5, 7])
            b["qtymain"] = FArray(np.array(qm.a[:, ir - 1]), (qm.lb[0],))
            b["elown"] = elown
            b["enpmqty"], b["ensqty"], b["bypbscm"] = enpm, ens, byp
        qm[1, 5] = qm[1, 1:4].sum(dtype=f32)
        qm[7, 5] = qm[7, 1:4].sum(dtype=f32)
        for k in range(1, 6):
            tqm[1, k] = f32(tqm[1, k] + qm[1, k])
            tqm[7, k] = f32(tqm[7, k] + qm[7, k])
        for k in range(1, 6):
            t = f32(0.0)
            for f in range(1, mainfuels):
                t = f32(t + qm[f, k])
            qm[mainfuels, k] = t


def calibrate(s: dict, bufs: dict) -> None:
    """CALIBRATE, run in the reporting call after the last iteration: apply this year's benchmark factors to every
    industry's saved quantities, refresh the report tables, and rebuild the electricity load-type shares from them."""
    mf, curiyr = int(s["mainfuels"]), int(s["curiyr"])
    bf, rbf = s["bf"], s["rbf"]
    qm, qr = s["qtymain"], s["qtyrenw"]
    for ind in range(1, int(s["indmax"]) + 1):
        s["inddir"], s["indnum"] = np.int32(ind), ind
        for ir in range(1, 5):
            s["indreg"] = ir
            rdbin(s, bufs)
            for f in range(1, mf):
                h = bf[curiyr, f, ir]
                qm[f, ir] = f32(qm[f, ir] * h)
                s["enpmqty"][f] = f32(s["enpmqty"][f] * h)
                s["ensqty"][f] = f32(s["ensqty"][f] * h)
                s["bypbscm"][f] = f32(s["bypbscm"][f] * h)
            for f in range(1, 9):
                qr[f, ir] = f32(qr[f, ir] * rbf[curiyr, f, ir])
            s["elown"] = f32(s["elown"] * bf[curiyr, 1, ir])
            eb = s["enbqty"]
            for k, fuel in ((1, 1), (2, 3), (4, 11), (5, 12)):
                for j in range(1, 6):
                    eb[j, k] = f32(eb[j, k] * bf[curiyr, fuel, ir])
            for is_ in range(1, int(s["mpastp"]) + 1):
                for ifn in range(1, int(s["ifmax"][is_]) + 1):
                    iff = int(s["ifloc"][ifn, is_])
                    if 0 < iff <= mf - 1:
                        for j in range(1, 5):
                            s["enpqty"][j, ifn, is_] = f32(s["enpqty"][j, ifn, is_] * bf[curiyr, iff, ir])
            wrbin(s, bufs)
            contab(s, ir)
        for f in range(1, mf):
            qm[f, 5] = qm[f, 1:4].sum(dtype=f32)
        for f in range(1, 9):
            qr[f, 5] = qr[f, 1:4].sum(dtype=f32)
        for k in range(1, 6):
            t = f32(0.0)
            for f in range(1, mf):
                t = f32(t + qm[f, k])
            qm[mf, k] = t
            t = f32(0.0)
            for f in range(1, 9):
                t = f32(t + qr[f, k])
            qr[9, k] = t
        contab(s, 5)
    regions = {1: (1, 2), 2: (3, 4), 3: (5, 6, 7), 4: (8, 9)}
    cfelq = f32(s["cfelq"])
    mine = s["minecon"]
    for icr, divs in regions.items():
        def sumcdiv(arr):
            t = f32(0.0)
            for d in divs:
                t = f32(t + arr[d, curiyr])
            return t
        co2 = f32(f32(cfelq / f32(10.0 ** 9)) * sumcdiv(s["co2_elec"]))
        mine[1, icr, curiyr] = f32(f32(mine[1, icr, curiyr] + sumcdiv(s["qngpin"])) + co2)
        mine[2, icr, curiyr] = f32(mine[2, icr, curiyr] + _sum_cg(s, divs, curiyr, 3))
        mine[6, icr, curiyr] = f32(mine[6, icr, curiyr] + _sum_cg(s, divs, curiyr, 2))
    for k in (1, 2, 6):
        mine[k, 5, curiyr] = mine[k, 1:4, curiyr].sum(dtype=f32)
    con = lambda n, icr: s[n][1, icr, curiyr]
    for icr in range(1, 5):
        x1 = f32(0.0)
        for n in ("foodcon", "papercon", "chemcon", "steelcon", "alumcon", "refcon"):
            x1 = f32(x1 + con(n, icr))
        x2 = f32(0.0)
        for n in ("fabmetalcon", "machinecon", "computecon", "tranequipcon", "elecequipon"):
            x2 = f32(x2 + con(n, icr))
        x3 = f32(0.0)
        for n in ("agcon", "minecon", "constcon", "glasscon", "cementcon", "woodprodcon", "plasticcon", "ltchemcon",
                  "othrnmmcon", "othrprimcon", "miscfincon"):
            x3 = f32(x3 + con(n, icr))
        s["xelin"][1, icr], s["xelin"][2, icr], s["xelin"][3, icr] = x1, x2, x3
        tot = f32(f32(x1 + x2) + x3)
        for k in (1, 2, 3):
            s["xelinshr"][k, icr] = f32(s["xelin"][k, icr] / tot)
    from nems_open.industrial.wexog import electricity_groups
    electricity_groups(s, curiyr)


def _sum_cg(s, divs, curiyr, k):
    t = f32(0.0)
    for d in divs:
        t = f32(t + s["cgogsq"][d, curiyr, k])
    return t


def addupcogs(s: dict) -> None:
    """ADDUPCOGS: totals of the CHP arrays (capacity, generation, thermal output, fuel for electricity) over fuels
    (slot numflchp+1), then census divisions (row 11), then industries (slot numind+1), for the current year."""
    cur, numind, nf = int(s["curiyr"]), 24, 10
    names = ("coggen", "cogcap", "cogthr", "cogelf")
    for n in names:
        a = s[n]
        for ir in range(1, 10):
            for i in range(1, numind + 1):
                a[ir, cur, i, nf + 1] = a[ir, cur, i, 1:nf].sum(dtype=f32)
    for n in ("coggen", "cogcap", "cogelf"):
        a = s[n]
        for i in range(1, numind + 1):
            for f in range(1, nf + 2):
                a[11, cur, i, f] = a[1:9, cur, i, f].sum(dtype=f32)
    for f in range(1, nf + 2):
        for ir in range(1, 12):
            for n in names:
                a = s[n]
                a[ir, cur, numind + 1, f] = a[ir, cur, 1:numind, f].sum(dtype=f32)


def run_iteration(s: dict, bufs: dict, itr: int, last: bool, standin=None) -> None:
    from nems_open.industrial.wexog import wexog
    s["curitr"] = np.int32(itr)
    s["fcrl"] = np.int32(1 if last else 0)
    s["iyr"] = np.int32(s["curcalyr"])  # IND sets IYR = CURCALYR after its early-year exit
    for d in range(1, 12):
        if s["ph2in"][d, int(s["curiyr"])] <= 0:
            s["ph2in"][d, int(s["curiyr"])] = f32(2.0) * s["pngin"][d, int(s["curiyr"])]
    addupcogs(s)
    setup_mac_and_price(s)
    iseam(s, bufs, standin)
    calibrate_coal_elec(s, bufs)
    wexog(s)


def run_year(s: dict, bufs: dict, iterations: int = 2, standin=None, reporting_call: bool = True) -> None:
    """The year's iterations, then the reporting call (CALIBRATE) that leaves the state next year starts from."""
    for itr in range(1, iterations + 1):
        run_iteration(s, bufs, itr, itr == iterations, standin)
    if reporting_call:
        s["curitr"] = np.int32(iterations)
        s["ncrl"] = np.int32(1)
        calibrate(s, bufs)
