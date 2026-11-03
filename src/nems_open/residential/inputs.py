"""RESD's first-call input readers (resd.f lines 607-2437), in the order RESD calls them.

Each reader works in place on the residential state dict (FArrays keyed by lowercase Fortran
name, as `initial_state.zeros()` builds it), with the Fortran's subscripts and loop order, and
does what the Fortran does right after reading (pointers, unit conversions, subsidies taken off
costs, existing-stock decay). Text files go through Fortran list-directed reads
(`fortran_io.ListDirectedReader`); RSMESS.xlsx through its named ranges, as ReadRngXLSX and
GETRNG* read them.

Macro inputs the readers use (MC_JPGDP, MC_NP, housing stocks and starts) come from `inputs`,
the runner's restart-file inputs.
"""

import numpy as np

from nems_open.fortran_array import FArray
from nems_open.fortran_io import ListDirectedReader
from nems_open.paths import INPUT
from nems_open.scedes import option
from nems_open.xlsx_ranges import named_ranges

f32 = np.float32
RDM = INPUT / "rdm"
BLD = INPUT / "bld"
BASEYR = 1990
RECSYEAR = 2020
ENDYR = 2050
IJUMPCALYR = 2050
NB = 3            # mNumBldg
ND = 9            # mNumCR - 2
NATIONAL = 11     # NationalPtr
MNUMENDU = 13
N_HEAT_CLASSES = 10
N_COOL_CLASSES = 5
N_CLDRY_CLASSES = 2
N_HEAT_TYPES = 30
N_SHELL_TYPES = 5
NLREC = 100


def _inint(x) -> int:
    """nemswk1's INT-nearest for range values (halves away from zero)."""
    v = float(x)
    return int(np.floor(v + 0.5)) if v >= 0 else -int(np.floor(-v + 0.5))


def _text(v, n: int) -> bytes:
    return str(v)[:n].ljust(n).encode("latin-1")


def _reader(name: str, header: int, folder=RDM) -> ListDirectedReader:
    """A file opened with READ(unit,'(n(/))') first: header = records skipped."""
    return ListDirectedReader(folder / name, header)


def _mac(inputs, name: str) -> FArray:
    return FArray(np.asarray(inputs.array(name)), [1] * np.ndim(inputs.array(name)))


# ---------------------------------------------------------------------------
# RTEKREAD: RSMESS.xlsx (RSCLASS, RSMEQP, RSSWITCH, RSMSHL)
# ---------------------------------------------------------------------------

def rtekread(s: dict, inputs, book=RDM / "rsmess.xlsx", epa111d: int | None = None) -> None:
    epa111d = option("EPA111D") if epa111d is None else epa111d
    for i in range(1, MNUMENDU + 1):
        s["rtcleupt"][i] = 0
        s["rttyeupt"][i] = 0
        s["rttypect"][i] = 0
    lasteu = lasttype = -1
    rtclcnt = rteucnt = rttycnt = 0

    # RSCLASS
    rng = named_ranges(book, "RSCLASS")
    n = _inint(rng["CLSRECORDS"][0])
    ints = lambda k: [_inint(v) for v in rng[k][:n]]
    reals = lambda k: [f32(v) for v in rng[k][:n]]
    cols = {k: ints("XL" + k.upper()) for k in ("rtclendu", "rtcleqcl", "rtcltypt", "rtclpntr", "rtclrepl",
                                                  "rtfuel", "rtffan")}
    rcols = {k: reals("XL" + k.upper()) for k in ("rtbaseff", "rtalpha", "rtk", "rtlambda", "rtfcbeta",
                                                    "rtswfact", "rtswbeta", "rtswbias")}
    names = rng["XLRTCLNAME"][:n]
    for i in range(1, n + 1):
        for k, v in cols.items():
            s[k][i] = v[i - 1]
        for k, v in rcols.items():
            if k == "rtbaseff":
                s[k][RECSYEAR, i] = v[i - 1]
            else:
                s[k][i] = v[i - 1]
        s["rtclname"][i] = _text(names[i - 1], 10)
        rtclcnt += 1
        j = int(s["rtclendu"][i])
        if j != lasteu:
            rteucnt += 1
        s["rtcleupt"][j + 1] = s["rtcleupt"][j + 1] + 1
        lasteu = j
    for j in range(1, rteucnt + 1):
        s["rtcleupt"][j + 1] = s["rtcleupt"][j + 1] + s["rtcleupt"][j]
    cls_records = n

    # RSMEQP: rows for CD 11 are expanded into one row per division 1-9
    rng = named_ranges(book, "RSMEQP")
    n = _inint(rng["EQPRECORDS"][0])
    s["rtekdollaryr"] = np.int32(_inint(rng["RTEKDOLLARYR"][0]))
    icol = ("rttyendu", "rttyeqcl", "rteqtype", "rtinityr", "rtlastyr", "rtcendiv", "hvacpntr", "rttypntr")
    rcol = ("cwmef", "loadadj", "rteqeff", "rteqcost", "rtrecost", "rteqsub", "rtresub", "rteqsubn", "rtresubn",
            "rteqsub111d", "rtresub111d", "rtcostp1", "rtcostp2", "rtcostp3", "rtecbta1", "rtecbta2", "rtecbta3",
            "rtecbias")
    xi = {k: [_inint(v) for v in rng["XL" + k.upper()][:n]] for k in icol}
    xr = {k: [f32(v) for v in rng[("XL" + k.upper())[:16]][:n]] for k in rcol}
    mature, tyname = rng["XLRTMATURE"][:n], rng["XLRTTYNAME"][:n]
    new_row = 0
    new_records = n

    def copy_row(i, x, div):
        for k in icol:
            s[k][i] = xi[k][x]
        s["rtcendiv"][i] = div
        for k in rcol:
            s[k][i] = xr[k][x]
        s["rtmature"][i] = _text(mature[x], 10)
        s["rttyname"][i] = _text(tyname[x], 10)

    lasteu = -1
    for xl in range(1, n + 1):
        i = xl + new_row
        if xi["rtcendiv"][xl - 1] == 11:
            for k in range(9):
                copy_row(i + k, xl - 1, k + 1)
            new_row += 8
            new_records += 8
        else:
            copy_row(i, xl - 1, xi["rtcendiv"][xl - 1])

    e111 = f32(float(epa111d))
    for i in range(1, new_records + 1):
        s["rteqcost"][i] = s["rteqcost"][i] - s["rteqsub"][i] - s["rteqsubn"][i] - e111 * s["rteqsub111d"][i]
        s["rtrecost"][i] = s["rtrecost"][i] - s["rtresub"][i] - s["rtresubn"][i] - e111 * s["rtresub111d"][i]
        if s["hvacpntr"][i] > N_HEAT_TYPES:
            typ = int(s["hvacpntr"][i]) - N_HEAT_TYPES
            d = int(s["rtcendiv"][i])
            for y in range(max(RECSYEAR, int(s["rtinityr"][i])), min(ENDYR, int(s["rtlastyr"][i])) + 1):
                s["aceff"][typ, y, d] = s["rteqeff"][i]
                s["acicost"][typ, y, d] = s["rteqcost"][i]
        rttycnt += 1
        j = int(s["rttyendu"][i])
        s["rttyeupt"][j + 1] = s["rttyeupt"][j + 1] + 1
        k = int(s["rteqtype"][i])
        if j != lasteu or k != lasttype:
            s["rttypect"][j + 1] = s["rttypect"][j + 1] + 1
        lasteu, lasttype = j, k
    for j in range(1, rteucnt + 1):
        s["rttyeupt"][j + 1] = s["rttyeupt"][j + 1] + s["rttyeupt"][j]
        s["rttypect"][j + 1] = s["rttypect"][j + 1] + s["rttypect"][j]

    # RSSWITCH: switching costs, transposed on the way in
    rng = named_ranges(book, "RSSWITCH")
    m = cls_records - 2
    flat = [_inint(v) for v in rng["XLRPINSCOST"]]
    for reccl in range(1, rtclcnt - 2 + 1):
        for recclsw in range(1, rtclcnt - 2 + 1):
            s["rpinscost"][reccl, recclsw] = flat[(recclsw - 1) * m + (reccl - 1)]

    # RSMSHL: shell packages
    rng = named_ranges(book, "RSMSHL")
    n = _inint(rng["SHLRECORDS"][0])
    s["rshldollaryr"] = np.int32(_inint(rng["RSHLDOLLARYR"][0]))
    icol = ("rscendiv", "rsbtype", "hvhteqcl", "hvhteqty", "hvcleqcl", "hvcleqty", "hvfyear", "hvlyear", "hvpackg")
    rcol = ("hvheatfactor", "hvcoolfactor", "htsheff", "clsheff", "htshbase", "clshbase", "shelcost", "shelsub",
            "shelsub111d")
    xi = {k: [_inint(v) for v in rng["XL" + k.upper()][:n]] for k in icol}
    xr = {k: [f32(v) for v in rng[("XL" + k.upper())[:16]][:n]] for k in rcol}
    pgname = rng["XLHVPGNAME"][:n]
    gdp = inputs.array("mc_jpgdp")                       # index -2 first
    jp = lambda yr: f32(gdp[yr - BASEYR + 1 + 2])
    ratio_num, ratio_den = jp(int(s["rtekdollaryr"])), jp(int(s["rshldollaryr"]))
    for i in range(1, n + 1):
        for k in icol:
            s[k][i] = xi[k][i - 1]
        for k in rcol:
            s[k][i] = xr[k][i - 1]
        s["hvpgname"][i] = _text(pgname[i - 1], 14)
        for k in ("shelcost", "shelsub", "shelsub111d"):
            s[k][i] = s[k][i] * ratio_num / ratio_den
        s["shelcost"][i] = s["shelcost"][i] - s["shelsub"][i] - s["shelsub111d"][i] * e111

    s["rtclcnt"], s["rteucnt"], s["rttycnt"] = np.int32(rtclcnt), np.int32(rteucnt), np.int32(rttycnt)


# ---------------------------------------------------------------------------
# Text readers
# ---------------------------------------------------------------------------

def rdsqfoot(s: dict) -> None:
    """RSSQFT: average floor area of new homes by year, division and building type."""
    r = _reader("rssqft.txt", 20)
    vals = r.read((IJUMPCALYR - RECSYEAR + 1) * ND * NB)
    it = iter(vals)
    for b in range(1, NB + 1):
        for d in range(1, ND + 1):
            for y in range(RECSYEAR, IJUMPCALYR + 1):
                s["sqrfoot"][y, b, d] = next(it)


def degdayread(s: dict, inputs) -> None:
    """KDEGDAY: heating and cooling degree days, and their population-weighted national value."""
    np_ = _mac(inputs, "mc_np")
    s["hddadj"][BASEYR:IJUMPCALYR, 1:11] = 0.0
    s["cddadj"][BASEYR:IJUMPCALYR, 1:11] = 0.0
    r = _reader("kdegday.txt", 100, BLD)
    for year in range(BASEYR, IJUMPCALYR + 1):
        v = r.read(1 + ND)
        s["hddyear"][year] = int(v[0])
        for d in range(1, ND + 1):
            s["hddadj"][year, d] = v[d]
        v = r.read(1 + ND)
        s["cddyear"][year] = int(v[0])
        for d in range(1, ND + 1):
            s["cddadj"][year, d] = v[d]
        yi = year - BASEYR + 1
        for d in range(1, ND + 1):
            s["hddadj"][year, NATIONAL] = s["hddadj"][year, NATIONAL] + s["hddadj"][year, d] * np_[d, yi] / np_[NATIONAL, yi]
            s["cddadj"][year, NATIONAL] = s["cddadj"][year, NATIONAL] + s["cddadj"][year, d] * np_[d, yi] / np_[NATIONAL, yi]


def bldbaseread(s: dict) -> None:
    """BLDBASE: baseline electricity use (trillion Btu in the file, billion kWh here)."""
    r = _reader("bldbase.txt", 100, BLD)
    for d in range(1, ND + 1):
        for y in range(1, 61 + 1):
            v = r.read(4)
            s["baselinebkwh"][d, y] = f32(v[2])
            s["baselinebkwh"][d, y] = (s["baselinebkwh"][d, y] / f32(3412.0)) * f32(10 ** 3)


def rsuecshlread(s: dict) -> None:
    """RSUECSHL: UECs of new heating and cooling, and base loads by class."""
    r = _reader("rsuecshl.txt", 20)
    for d in range(1, ND + 1):
        for e in range(1, N_HEAT_CLASSES + 1):
            v = r.read(NB)
            for b in range(1, NB + 1):
                s["newheatuec"][e, b, d] = v[b - 1]
    for d in range(1, ND + 1):
        v = r.read(NB)
        for b in range(1, NB + 1):
            s["newcooluec"][b, d] = v[b - 1]
    r.skip(2)
    for e in range(1, N_HEAT_CLASSES + N_COOL_CLASSES + 1):
        s["baseload"][e] = r.read(1)[0]
    s["ehshell"][RECSYEAR, 1:5, 1:ND, 1:NB] = 1.0
    s["ecshell"][RECSYEAR, 1:ND, 1:NB] = 1.0


MEL_CODES = ("tvs", "stb", "hts", "ott", "vgc", "dpc", "lpc", "mon", "net", "bat", "cfn", "cof", "deh", "mco",
             "plp", "plh", "sec", "spa", "wcl", "spk", "phn", "tab", "kit")


def rsmelsread(s: dict) -> None:
    """RSMELS: stock (penetration) and UEC indexes of the miscellaneous electric loads."""
    r = _reader("rsmels.txt", 20)
    nummels = int(r.read(1)[0])
    s["nummels"] = np.int32(nummels)
    ny = IJUMPCALYR - RECSYEAR
    for part in ("pen", "eff"):
        r.skip(3)
        for code in MEL_CODES:
            v = r.read(ny)
            for k, y in enumerate(range(RECSYEAR + 1, IJUMPCALYR + 1)):
                s[code + part][y] = v[k]
    r.skip(3)
    v = r.read(nummels)
    for i in range(1, nummels + 1):
        s["melsincomeeffect"][i] = int(v[i - 1])


def rsmiscread(s: dict, inputs, exm: int | None = None) -> None:
    """RSMISC: housing decay rates (from the macro model's stocks and starts), saturations,
    shares and elasticities; then existing homes decayed forward and the shell technology gains."""
    if exm is None:  # EXM (the macro model ran this cycle) as the restart file holds it
        exm = int(np.asarray(inputs.snapshot["NCNTRL/exm"]).ravel()[0])
    r = _reader("rsmisc.txt", 20)
    v = r.read(NB)
    for b in range(1, NB + 1):
        s["hdr"][b] = v[b - 1]
    r.skip(3)
    v = r.read(2)
    hdrfy, hdrly = int(v[0]), int(v[1])
    if hdrfy <= BASEYR:
        hdrfy = BASEYR + 1
    if hdrly > ENDYR:
        hdrly = ENDYR
    s["hdrfy"], s["hdrly"] = np.int32(hdrfy), np.int32(hdrly)

    if exm == 1:
        hdq, hdi, hdiave, hcdshr, hcdshrave = s["hdq"], s["hdi"], s["hdiave"], s["hcdshr"], s["hcdshrave"]
        s["hdr"][1:NB] = 0.0
        hdq[2:ENDYR - BASEYR + 1, 1:11, 1:NB] = 0.0
        hdi[2:ENDYR - BASEYR + 1, 1:11, 1:NB] = 0.0
        hdiave[1:11, 1:NB] = 0.0
        hcdshr[2:ENDYR - BASEYR + 1, 1:11, 1:NB] = 0.0
        hcdshrave[1:11, 1:NB] = 0.0
        stock = [_mac(inputs, k) for k in ("mc_khups1", "mc_khups2a", "mc_khumfg")]
        starts = [_mac(inputs, k) for k in ("mc_husps1", "mc_husps2a", "mc_husmfg")]
        for y in range(hdrfy - BASEYR + 1, hdrly - BASEYR + 1 + 1):
            for d in range(1, ND + 1):
                for b in range(1, NB + 1):
                    st, sp = stock[b - 1], starts[b - 1]
                    hdq[y, d, b] = st[d, y - 1] - st[d, y] + sp[d, y - 1]
                for b in range(1, NB + 1):
                    hdi[y, d, b] = f32(1) - (hdq[y, d, b] / stock[b - 1][d, y])
                for b in range(1, NB + 1):
                    hdiave[d, b] = hdiave[d, b] + hdi[y, d, b]
                for b in range(1, NB + 1):
                    hcdshr[y, d, b] = stock[b - 1][d, y] / stock[b - 1][11, y]
                for b in range(1, NB + 1):
                    hcdshrave[d, b] = hcdshrave[d, b] + hcdshr[y, d, b]
        span = f32(hdrly - hdrfy + 1)  # REAL / INTEGER: the integer is converted
        for d in range(1, ND + 1):
            for b in range(1, NB + 1):
                hdiave[d, b] = hdiave[d, b] / span
            for b in range(1, NB + 1):
                hcdshrave[d, b] = hcdshrave[d, b] / span
        for b in range(1, NB + 1):
            for d in range(1, ND + 1):
                s["hdr"][b] = s["hdr"][b] + (hdiave[d, b] * hcdshrave[d, b])
        for b in range(1, NB + 1):
            if s["hdr"][b] > 1.0:
                s["hdr"][b] = 1.0

    r.skip(2)
    s["resdiscountrate"] = f32(r.read(1)[0])
    r.skip(2)
    s["tenure"] = f32(r.read(1)[0])

    def by_division(name, n, year=None, label=False):
        r.skip(3)
        for d in range(1, ND + 1):
            v = r.read(1 + n)
            for b in range(1, n + 1):
                if year is None:
                    s[name][b, d] = v[b]
                else:
                    s[name][year, b, d] = v[b]

    r.skip(3)
    for d in range(1, ND + 1):
        v = r.read(1 + NB)
        for b in range(1, NB + 1):
            s["eh"][RECSYEAR, b, d] = v[b]
    by_division("racsat", NB)
    by_division("racunits", NB)
    by_division("cacsat", NB)
    r.skip(3)
    for d in range(1, ND + 1):
        s["cacpr"][d] = r.read(2)[1]
    by_division("dwpr", NB)
    by_division("eldrypr", NB)
    r.skip(3)
    s["tcw_shr"], s["fcw_shr"] = (f32(x) for x in r.read(2))
    r.skip(3)
    s["tmf_shr"], s["smf_shr"], s["bmf_shr"] = (f32(x) for x in r.read(3))
    r.skip(3)
    s["ch_shr"], s["up_shr"] = (f32(x) for x in r.read(2))
    by_division("frzsat", NB)
    by_division("refsat", NB)
    r.skip(3)
    for d in range(1, ND + 1):
        v = r.read(1 + NB)
        for b in range(1, NB + 1):
            s["dishnew"][RECSYEAR + 1, b, d] = v[b]
    r.skip(3)
    for d in range(1, ND + 1):
        v = r.read(1 + NB)
        for b in range(1, NB + 1):
            s["washnew"][RECSYEAR + 1, b, d] = v[b]
    # Lines from here carry a text label after the first number (list-directed: one token each).
    tokens = _TokenReader(r)
    tokens.skip(3)
    for e in range(1, N_CLDRY_CLASSES + 1):
        for d in range(1, ND + 1):
            v = tokens.read_record(2 + NB)
            for b in range(1, NB + 1):
                s["newdrysat"][RECSYEAR + 1, e, b, d] = float(v[1 + b])
    for name in ("shtshr", "nshtshr"):
        tokens.skip(3)
        for b in range(1, NB + 1):
            for d in range(1, ND + 1):
                v = tokens.read_record(2 + 5)
                for f in range(1, 5 + 1):
                    s[name][b, d, f] = float(v[1 + f])
    tokens.skip(3)
    ny = ENDYR - RECSYEAR + 1
    for f in range(1, 3):
        for b in range(1, NB + 1):
            for d in range(1, ND + 1):
                v = tokens.read_record(3 + ny)
                for k, y in enumerate(range(RECSYEAR, ENDYR + 1)):
                    s["wthrztn"][y, f, d, b] = float(v[3 + k])
    tokens.skip(3)
    for d in range(1, ND + 1):
        v = tokens.read_record(1 + 5)
        for k in range(1, 5 + 1):
            s["elastic"][k, d] = float(v[k])
    tokens.skip(3)
    v = tokens.read_record(6)
    modyear, endmodyear = int(float(v[0])), int(float(v[1]))
    elf, ngf, dsf, lgf = (f32(float(x)) for x in v[2:6])
    for y in range(modyear, endmodyear + 1):
        for d in range(1, ND + 1):
            s["pelrs"][d, y] = s["pelrs"][d, y] * elf
            for k in range(1, 10 + 1):
                s["pelrsout"][d, y, k] = s["pelrsout"][d, y, k] * elf
            s["pngrs"][d, y] = s["pngrs"][d, y] * ngf
            s["pdsrs"][d, y] = s["pdsrs"][d, y] * dsf
            s["plgrs"][d, y] = s["plgrs"][d, y] * lgf

    for y in range(RECSYEAR + 1, ENDYR + 1):
        for b in range(1, NB + 1):
            for d in range(1, ND + 1):
                s["eh"][y, b, d] = s["eh"][y - 1, b, d] * s["hdr"][b]
    s["oldhses"][RECSYEAR] = 0.0
    for d in range(1, ND + 1):
        for b in range(1, NB + 1):
            s["oldhses"][RECSYEAR] = s["oldhses"][RECSYEAR] + s["eh"][RECSYEAR, b, d]
    s["limit"] = f32(0.30)
    steps = (0.005, 0.003, 0.006, 0.003, 0.006, 0.016, 0.003, 0.003, 0.011)
    for y1 in range(RECSYEAR + 1, int(s["lastyr"]) + BASEYR - 1 + 1):
        for b in range(1, NB + 1):
            for k, step in enumerate(steps, 1):
                s["techg"][y1, k, b] = s["techg"][y1 - 1, k, b] + f32(step)


class _TokenReader:
    """List-directed reads of records that mix numbers and unquoted text (a token per value)."""

    def __init__(self, r: ListDirectedReader):
        self.r = r

    def skip(self, n: int) -> None:
        self.r.skip(n)

    def read_record(self, n: int) -> list:
        out = []
        while len(out) < n:
            tokens = self.r.records[self.r.pos].replace(",", " ").split()
            self.r.pos += 1
            for tok in tokens:
                if tok.startswith("!") or tok == "/":
                    break
                out.append(tok.strip("'\""))
                if len(out) == n:
                    break
        return out


def rsmlgtread(s: dict, inputs) -> None:
    """RSMLGT: lighting applications, bins, the bulb menu (costs to the RTEK dollar year)."""
    r = _reader("rsmlgt.txt", 20)
    t = _TokenReader(r)
    s["lightdiag"] = np.int32(int(float(t.read_record(1)[0])))
    t.skip(2)
    s["rlgtdollaryr"] = np.int32(int(float(t.read_record(1)[0])))
    t.skip(2)
    napps = int(float(t.read_record(1)[0]))
    s["numapps"] = np.int32(napps)
    t.skip(2)
    for i, v in enumerate(t.read_record(napps), 1):
        s["appid"][i] = _text(v, 3)
    for i, v in enumerate(t.read_record(napps), 1):
        s["appindex"][i] = int(float(v))
    t.skip(3)
    for i, v in enumerate(t.read_record(napps), 1):
        s["numtypes"][i] = int(float(v))
    for i, v in enumerate(t.read_record(napps), 1):
        s["numappbins"][i] = int(float(v))
    t.skip(4)
    gdp = inputs.array("mc_jpgdp")
    jp = lambda yr: f32(gdp[yr - BASEYR + 1 + 2])
    for i in range(1, NLREC + 1):
        v = t.read_record(3 + ND + ND + 4 + 2 + 2)
        s["firstyear"][i], s["lastyear"][i] = int(float(v[0])), int(float(v[1]))
        s["bulbcost"][i] = float(v[2])
        for d in range(1, ND + 1):
            s["bulbeesub"][i, d] = float(v[2 + d])
            s["bulbsub"][i, d] = float(v[2 + ND + d])
        k = 3 + 2 * ND
        s["lpw"][i], s["bulbwatts"][i], s["lifehours"][i], s["bulbcri"][i] = (float(x) for x in v[k:k + 4])
        s["lightingapp"][i] = _text(v[k + 4], 3)
        s["bulbtype"][i] = _text(v[k + 5], 3)
        s["ltlbeta1"][i], s["ltlbeta2"][i] = float(v[k + 6]), float(v[k + 7])
        s["bulbcost"][i] = s["bulbcost"][i] * jp(int(s["rtekdollaryr"])) / jp(int(s["rlgtdollaryr"]))
        if s["firstyear"][i] == 9999:
            break
    t.skip(3)
    for app in range(1, napps + 1):
        v = t.read_record(3)
        for b in range(1, 4):
            s["bulbsperhh"][app, b] = float(v[b - 1])
        t.skip(1)
    for app in range(1, napps + 1):
        nbins, ntypes = int(s["numappbins"][app]), int(s["numtypes"][app])
        t.skip(2)
        for k, v in enumerate(t.read_record(nbins), 1):
            s["appbinhours"][app, k] = float(v)
        t.skip(1)
        for k, v in enumerate(t.read_record(nbins), 1):
            s["binshares"][app, k] = float(v)
        t.skip(1)
        for e in range(1, ntypes + 1):
            for k, v in enumerate(t.read_record(nbins), 1):
                s["bulbbinshares"][app, e, k] = float(v)
        t.skip(1)
        for e, v in enumerate(t.read_record(ntypes), 1):
            s["basewattsbulbs"][app, e] = float(v)
        if app != napps:
            t.skip(1)
    for app in range(1, napps + 1):
        for b in range(1, int(s["numappbins"][app]) + 1):
            s["basewattbins"][app, b] = 0.0
    for app in range(1, napps + 1):
        for b in range(1, int(s["numappbins"][app]) + 1):
            for e in range(1, int(s["numtypes"][app]) + 1):
                s["basewattbins"][app, b] = s["basewattbins"][app, b] + s["bulbbinshares"][app, e, b] * s["basewattsbulbs"][app, e]


def rdret(s: dict) -> None:
    """RSRET01: share of each class's RECS-year stock retired by each year."""
    r = _reader("rsret01.txt", 20)
    n = int(s["rtclcnt"])
    vals = iter(r.read((IJUMPCALYR - RECSYEAR) * n))
    for reccl in range(1, n + 1):
        for y in range(RECSYEAR + 1, IJUMPCALYR + 1):
            s["eqcret"][y, reccl] = next(vals)


def inteqt(s: dict) -> None:
    """RSHTSHR: shares of heating classes in new homes (Census SOC years) and heating choice biases."""
    eu = 1
    r = _reader("rshtshr.txt", 20)
    htshryr = int(r.read(1)[0])
    s["htshryr"] = np.int32(htshryr)
    r.skip(4)
    lo, hi = int(s["rtcleupt"][eu]) + 1, int(s["rtcleupt"][eu + 1])
    for y in range(RECSYEAR, htshryr + 1):
        for d in range(1, ND + 1):
            for reccl in range(lo, hi + 1):
                v = r.read(NB)
                for b in range(1, NB + 1):
                    s["hsysshr"][y, reccl, b, d] = v[b - 1]
    r.skip(2)
    for b in range(1, NB + 1):
        for e in range(1, N_HEAT_CLASSES + 1):
            v = r.read(ND)
            for d in range(1, ND + 1):
                s["rtfcbias"][e, b, d] = v[d - 1]


MEL_STOCK = ("fan",) + MEL_CODES + ("ea",)


def rdhtreqc(s: dict) -> None:
    """RSSTK: RECS-year equipment stock by class, MELs and secondary heating; hot water heaters
    for the washer shares; RECS-year stock decayed forward (cooling heat pumps follow heating)."""
    r = _reader("rsstk.txt", 20)
    eupt = s["rtcleupt"]
    for eu in range(1, 10):
        for reccl in range(int(eupt[eu]) + 1, int(eupt[eu + 1]) + 1):
            for d in range(1, ND + 1):
                v = r.read(NB)
                for b in range(1, NB + 1):
                    s["eqcese"][RECSYEAR, reccl, b, d] = v[b - 1]
    for code in MEL_STOCK:
        it = iter(r.read(NB * ND))
        for d in range(1, ND + 1):
            for b in range(1, NB + 1):
                s[code + "eqp"][RECSYEAR, b, d] = next(it)
    for name, nf in (("shteqp", 5), ("appeqp", 3)):
        it = iter(r.read(NB * ND * nf))
        for e in range(1, nf + 1):
            for d in range(1, ND + 1):
                for b in range(1, NB + 1):
                    s[name][RECSYEAR, b, d, e] = next(it)
    eu = 5
    for d in range(1, ND + 1):
        for b in range(1, NB + 1):
            s["hotwatq"][RECSYEAR, b, d] = 0.0
            for reccl in range(int(eupt[eu]) + 1, int(eupt[eu + 1]) + 1):
                s["hotwatq"][RECSYEAR, b, d] = s["hotwatq"][RECSYEAR, b, d] + s["eqcese"][RECSYEAR, reccl, b, d]
    from nems_open.residential.common import powi
    for eu in range(1, 10):
        for d in range(1, ND + 1):
            for reccl in range(int(eupt[eu]) + 1, int(eupt[eu + 1]) + 1):
                for b in range(1, NB + 1):
                    for y in range(RECSYEAR + 1, ENDYR + 1):
                        s["eqcese"][y, reccl, b, d] = (s["eqcese"][RECSYEAR, reccl, b, d] * powi(s["hdr"][b], y - RECSYEAR)
                                                       * (f32(1.0) - s["eqcret"][y, reccl]))
                        if eu == 2 and s["rtclpntr"][reccl] != 0:
                            s["eqcese"][y, reccl, b, d] = s["eqcese"][y, int(s["rtclpntr"][reccl]), b, d]


def rdeff(s: dict) -> None:
    """RSEFF01: efficiency of retiring equipment by class and year."""
    r = _reader("rseff01.txt", 20)
    for reccl in range(1, int(s["rtclcnt"]) + 1):
        v = r.read(IJUMPCALYR - RECSYEAR)
        for k, y in enumerate(range(RECSYEAR + 1, IJUMPCALYR + 1)):
            s["eqceff"][y, reccl] = v[k]


def rdsteff(s: dict) -> None:
    """RSSTKEFF: RECS-year stock efficiency by class and year."""
    r = _reader("rsstkeff.txt", 20)
    for reccl in range(1, int(s["rtclcnt"]) + 1):
        v = r.read(IJUMPCALYR - RECSYEAR + 1)
        for k, y in enumerate(range(RECSYEAR, IJUMPCALYR + 1)):
            s["stkeff"][y, reccl] = v[k]


def rdestarhomes(s: dict) -> None:
    """RSESTAR: ENERGY STAR home shell betas (history years) and learning factors."""
    r = _reader("rsestar.txt", 20)
    hist = int(r.read(1)[0])
    s["estarhistyr"] = np.int32(hist)
    ny = hist - RECSYEAR
    for name in ("hvbeta1", "hvbeta2"):
        s[name] = FArray(np.zeros((ny, NB, N_SHELL_TYPES, 11), dtype=f32), [RECSYEAR + 1, 1, 1, 1])
        r.skip(3)
        for b in range(1, NB + 1):
            for sh in range(1, N_SHELL_TYPES + 1):
                for d in range(1, ND + 1):
                    v = r.read(ny)
                    for k, y in enumerate(range(RECSYEAR + 1, hist + 1)):
                        s[name][y, b, sh, d] = v[k]
    r.skip(3)
    for d in range(1, ND + 1):
        v = r.read(NB)
        for b in range(1, NB + 1):
            s["learnfact"][b, d] = v[b - 1]


MEL_UEC = ("fan",) + MEL_CODES + ("ea",)


def rduecs(s: dict) -> None:
    """RSUEC: RECS-year UECs by class, MELs, secondary heating and other appliances."""
    r = _reader("rsuec.txt", 20)
    eupt = s["rtcleupt"]
    for eu in range(1, 10):
        for reccl in range(int(eupt[eu]) + 1, int(eupt[eu + 1]) + 1):
            for d in range(1, ND + 1):
                v = r.read(NB)
                for b in range(1, NB + 1):
                    s["eqcuec"][d, reccl, b] = v[b - 1]
    for code in MEL_UEC:
        it = iter(r.read(NB * ND))
        for d in range(1, ND + 1):
            for b in range(1, NB + 1):
                s[code + "uec"][d, b] = next(it)
    for name, nf in (("shtuec", 5), ("appuec", 3)):
        it = iter(r.read(NB * ND * nf))
        for e in range(1, nf + 1):
            for d in range(1, ND + 1):
                for b in range(1, NB + 1):
                    s[name][d, e, b] = next(it)


def rconsfl(s: dict) -> None:
    """RCONSFL: fuel counts by end use and the RTEK-fuel to consumption-fuel maps."""
    s["nhtrfl"] = np.int32(5)
    for i, v in enumerate((3, 4, 1, 2, 5), 1):
        s["fhtrcon"][i] = v
    s["nshtrfl"] = np.int32(5)
    s["nclfl"] = np.int32(2)
    s["fclcon"][4], s["fclcon"][3] = 1, 2
    s["ncswfl"] = np.int32(1)
    s["ndswfl"] = np.int32(1)
    s["nwhfl"] = np.int32(5)
    for i, v in enumerate((3, 4, 1, 2, 5), 1):
        s["fwhcon"][i] = v
    s["nstvfl"] = np.int32(3)
    s["fstvcon"][3], s["fstvcon"][2], s["fstvcon"][4] = 1, 2, 3
    s["ndryfl"] = np.int32(2)
    s["fdrycon"][3], s["fdrycon"][4] = 1, 2
    s["nreffl"] = np.int32(1)
    s["nfrzfl"] = np.int32(1)


def first_call(s: dict, inputs) -> None:
    """Every reader, in RESD's order (resd.f lines 470-488). RDISTGEN reads its own files."""
    rtekread(s, inputs)
    rdsqfoot(s)
    degdayread(s, inputs)
    bldbaseread(s)
    rsuecshlread(s)
    rsmelsread(s)
    rsmiscread(s, inputs)
    rsmlgtread(s, inputs)
    rdret(s)
    inteqt(s)
    rdhtreqc(s)
    rdeff(s)
    rdsteff(s)
    rdestarhomes(s)
    rduecs(s)
    rconsfl(s)
