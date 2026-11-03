"""EFP's books store: the direct-access files that hold each region's books (uefp.f, udaf.f).

EFP keeps each region's accounts between calls in five direct-access files. A record is
the raw bytes of a COMMON block, read and written through an EQUIVALENCEd CHARACTER
variable, so it is the block's members back to back, little-endian, with no byte swapping
(NEMS opens the files big-endian, but CHARACTER data is not swapped):

    file          unit   COMMON    view     record      records per region
    EMM_EFPRCY    UF_RCY /EFPRCY/  OUTRCY   144 bytes   3 components per year
    EMM_EFPRC     UF_RC  /EFPRC/   OUTRC    376 bytes   6 (2 slots x 3 components)
    EMM_EFPR      UF_R   /EFPR/    OUTR     10000 bytes EBLK$EFP = 3 (8192 bytes used)
    EMM_ECPIDAF   UF_BLD /BILDIN/  EBILDN   16384 bytes EBLK$BLD = 40 (year 1 only)
    EMM_EFPBLDS   IBD    list      -        84 bytes    linked list of builds

EFPBLDS is different: each record is written with an explicit list of numeric items to a
unit opened CONVERT='BIG_ENDIAN', so its integers and reals ARE big-endian.

`Books` holds each file as bytes, loaded from a snapshot, with get/put by record number
and the Fortran's record-number formulas (GETRCY/STRRCY, GETRC/STRRC, GETR/STRR,
GETEB/STREB in uefp.f; GETBLD/STRBLD in udaf.f). The get/put routines move records
between the files and the state: a read sets the byte view (OUTRCY ...) and the block's
named arrays; a write first rebuilds the view from the named arrays, the way the
EQUIVALENCE keeps them one piece of memory.

`BLOCKS[name].sync(s)` does that rebuild. A block's named arrays that the state does not
hold (the oracle dumps only what a routine mentions) keep the bytes the view has.
"""

from pathlib import Path

import numpy as np

from nems_open.emm.efp.common import put

NUL = bytes(1)
ICOM = {"G": 1, "T": 2, "D": 3}

# ---- block layouts: (name, dtype, shape) in COMMON order (the includes efprcy, efprc, efpr, bildin)

_R2 = (2,)
EFPRCY_SPEC = (
    [(n, "f4", _R2) for n in ("escwpp", "esprlt", "esrtlt", "esprst", "esprce", "esrtst", "esprps", "esrtce",
                               "esrtps", "estshr", "edivrt", "eilag", "esftxr", "eserce")]
    + [("esperda", "f4", (4,)), ("esperex", "f4", (4,))]
)

EFPRC_SPEC = (
    [(n, "f4", _R2) for n in (
        "egtxrt", "esstxr", "essltx", "esptxr", "esrbaf", "esflpr", "esfpdb", "erditc", "erpdtb", "erobl",
        "esemdl", "esemdb", "erbndl", "eramdl", "errbl", "erpflps", "esempl", "esempb", "errvr1", "erabdl",
        "erpdfl", "elcidc", "elrcwp", "elrbrr", "eltomn", "eltfln", "elbde", "elaitc", "elfitc", "elafdc",
        "elffdc", "eloffs", "elprtx", "elsltx", "eltdwo", "eltiex", "eltlsl", "elllp", "ellagn")]
    + [("opavrb", "i4", _R2), ("opitcrb", "i4", _R2)]
    + [(n, "f4", _R2) for n in ("elprlt", "elprst", "elprce", "elprps", "erprfl", "ectxrt")]
)

# efpr: the five existing-asset arrays (EFP_D_VIN=40, EFP_D_CAP=14, EFP_D_OWN=2), the post-service
# capital cost by plant type, and four T&D capital constants. EXTRA and the rest of the third
# 8192-byte block are leftover bytes (the view runs past the named members).
EFPR_SPEC = (
    [(n, "f4", (40, 14, 2)) for n in ("uobkvl", "uoasvl", "uoaitc", "uoafdc", "uoabde")]
    + [("ercca", "f4", (14,)), ("cpdcon", "f4", ()), ("cpdslp", "f4", ()), ("cptcon", "f4", ()),
       ("cptslp", "f4", ())]
)

# bildin (ECP_D_* sizes as the oracle's dump of each array shows them). Doubles first, then
# singles, then integers, then the characters; EPLOVR and the bytes after it are leftover.
BILDIN_SPEC = (
    ("ep$lf", "f8", (24, 10)),
    ("epfpm", "f8", (4, 10)),
    ("ephght", "f8", (24, 10)),
    ("eppeak", "f8", (10,)),
    ("ep_net_peak", "f8", (10,)),
    ("epspk", "f8", (4, 10)),
    ("epwdth", "f8", (24, 10)),
    ("epnox_g", "f8", (4, 10, 80, 5)),
    ("epecap", "f4", (26, 80, 10)),
    ("epecap_mr", "f4", (26, 80, 10)),
    ("epecap_upv", "f4", (26, 80, 10)),
    ("epncap", "f4", (80,)),
    ("eprgm", "f4", (80,)),
    ("ephtrt_aer", "f4", (80,)),
    ("epphrt0", "f4", (55,)),
    ("epphrtn", "f4", (55,)),
    ("epwdcof", "f4", (55, 10)),
    ("epext", "f4", (80, 9)),
    ("epbldbnd", "f4", (23, 10)),
    ("epch4rt", "f4", (23,)),
    ("epco1rt", "f4", (23,)),
    ("epco2rt", "f4", (23,)),
    ("epcrbrt", "f4", (23,)),
    ("epnoxrt", "f4", (23,)),
    ("epsoxrt", "f4", (23,)),
    ("epvocrt", "f4", (23,)),
    ("epirovr", "f4", (23,)),
    ("epirfom", "f4", (23,)),
    ("epirvom", "f4", (23,)),
    ("epirccr", "f4", (23,)),
    ("epirccs", "f4", (23, 3)),
    ("epcpadj", "f4", (23,)),
    ("epbdsup", "f4", (23, 3)),
    ("epccsup", "f4", (23, 3)),
    ("epfxsup", "f4", (23, 3)),
    ("epvrsup", "f4", (23, 3)),
    ("epiacf", "f4", (9,)),
    ("epicfc", "f4", (9, 24)),
    ("upicfc", "f4", (4, 9, 12, 4)),
    ("upicfc_dpv", "f4", (4, 9, 12, 4)),
    ("episcf", "f4", (9, 4)),
    ("epigcf", "f4", (9, 12)),
    ("eprcfc", "f4", (11,)),
    ("epfmap", "f4", (16, 60)),
    ("epflrg", "f4", (60, 25)),
    ("epcrmp", "f4", (60, 11)),
    ("epsovr", "f4", (55, 3)),
    ("epscap", "f4", (55, 3)),
    ("epalso2", "f4", (10,)),
    ("epalnox", "f4", (10,)),
    ("epalco2", "f4", (10,)),
    ("updnoxl", "f4", (61,)),
    ("eouncp", "f4", ()),
    ("eouccp", "f4", ()),
    ("eprpsrg", "f4", ()),
    ("eprpstg", "f4", ()),
    ("eprpsro", "f4", ()),
    ("eprpsto", "f4", ()),
    ("epdscrt", "f4", ()),
    ("eputdscrt", "f4", ()),
    ("epuror", "f4", ()),
    ("epuirt", "f4", ()),
    ("epufdt", "f4", ()),
    ("epufpe", "f4", ()),
    ("epucre", "f4", ()),
    ("epurorr", "f4", ()),
    ("epuirtr", "f4", ()),
    ("epufper", "f4", ()),
    ("epucrer", "f4", ()),
    ("eprtbs", "f4", ()),
    ("epmrm", "f4", ()),
    ("epacm", "f4", (80,)),
    ("epxprt", "f4", (10,)),
    ("epcovr", "f4", (80,)),
    ("eprscfc", "f4", (11, 3, 4)),
    ("epcrbpen", "f4", (16,)),
    ("epctrm", "f4", (80,)),
    ("epccrf", "f4", (80,)),
    ("epcfom", "f4", (80,)),
    ("eptcst", "f4", (28, 28)),
    ("eptcrf", "f4", (28, 28)),
    ("eptloss", "f4", (28, 28)),
    ("epupclf", "f4", (10,)),
    ("epnpclf", "f4", (10,)),
    ("eppclrhs", "f4", (10,)),
    ("epunit", "f4", (80, 10)),
    ("epfom", "f4", (80,)),
    ("epgfom", "f4", (4, 80)),
    ("epvom", "f4", (80,)),
    ("epgcap", "f4", (26, 4, 80)),
    ("epecfc", "f4", (80, 10)),
    ("epescfc", "f4", (4, 80, 10)),
    ("epecfc_upv", "f4", (80, 10)),
    ("epdpct", "f4", (6,)),
    ("epdavd", "f4", (6,)),
    ("ep_sp_cap_fac", "f4", (4, 80, 10)),
    ("eorder", "i4", (24, 10)),
    ("epfrst", "i4", (4, 10)),
    ("epgecp", "i4", (12,)),
    ("epgett", "i4", (12,)),
    ("epldgr", "i4", (24, 10)),
    ("epgecps", "i4", (24, 10)),
    ("epldsg", "i4", (24, 10)),
    ("eplmap", "i4", (12, 4, 10)),
    ("epnext", "i4", (24, 10)),
    ("epngrp", "i4", ()),
    ("epnmsp", "i4", ()),
    ("epnspg", "i4", (9,)),
    ("epnstp", "i4", (10,)),
    ("epsett", "i4", (4,)),
    ("epnscr", "i4", (55, 3)),
    ("epsrec", "i4", (200, 55, 3)),
    ("eptirgn", "i4", (28, 28)),
    ("epcensus", "i4", (80,)),
    ("epngrg", "i4", ()),
    ("epclrg", "i4", ()),
    ("epcarg", "i4", ()),
    ("epbndtyp", "S1", (23,)),
)


class Block:
    """One COMMON block: its named members and its CHARACTER byte view (the Fortran
    EQUIVALENCE of the two). `view` is the state's name for the byte view; `size` its
    length in bytes (the view may run past the last named member)."""

    def __init__(self, view, spec, size):
        self.view, self.size = view, size
        self.members = {}
        off = 0
        for name, code, shape in spec:
            dt = np.dtype(code)
            self.members[name] = (off, dt, shape)
            off += dt.itemsize * int(np.prod(shape, dtype=np.int64))
        self.named_bytes = off
        assert off <= size, (view, off, size)

    # -- the byte view in the state
    def raw(self, s):
        v = s.get(self.view)
        if v is None:
            return bytes(self.size)
        data = v.a.tobytes() if hasattr(v, "a") else bytes(v)
        return data.ljust(self.size, NUL)[: self.size]

    def set_raw(self, s, raw):
        v = s.get(self.view)
        if v is None:
            return
        if hasattr(v, "a"):
            width = v.a.dtype.itemsize
            v.a[...] = np.frombuffer(raw, dtype=f"S{width}").reshape(v.a.shape)
        else:
            s[self.view] = np.bytes_(raw)

    # -- members <-> bytes
    def decode(self, raw, name):
        off, dt, shape = self.members[name]
        n = int(np.prod(shape, dtype=np.int64))
        a = np.frombuffer(raw, dtype=dt, count=n, offset=off)
        return a.reshape(shape, order="F") if shape else a[0]

    def encode(self, buf, name, value):
        off, dt, shape = self.members[name]
        a = np.asarray(value.a if hasattr(value, "a") else value).astype(dt, copy=False)
        data = a.tobytes(order="F")
        buf[off: off + len(data)] = data

    def load(self, s, raw):
        """A record was read into the view: the named members of the state follow."""
        assert len(raw) == self.size, (self.view, len(raw), self.size)
        self.set_raw(s, raw)
        for name in self.members:
            if name in s:
                v = self.decode(raw, name)
                if hasattr(s[name], "a"):
                    s[name].a[...] = v
                else:
                    put(s, name, v)

    def sync(self, s):
        """The view from the named members the state holds. Returns the bytes."""
        buf = bytearray(self.raw(s))
        for name in self.members:
            if name in s:
                self.encode(buf, name, s[name])
        raw = bytes(buf)
        self.set_raw(s, raw)
        return raw

    def region_block(self, raw):
        """{name: array with .a, or scalar} for a record, for routines that take a block."""
        out = {}
        for name in self.members:
            v = self.decode(raw, name)
            out[name] = _Arr(v) if isinstance(v, np.ndarray) else v
        return out


class _Arr:
    def __init__(self, a):
        self.a = a


BLOCKS = {
    "rcy": Block("outrcy", EFPRCY_SPEC, 144),
    "rc": Block("outrc", EFPRC_SPEC, 376),
    "r": Block("outr", EFPR_SPEC, 3 * 8192),
    "bld": Block("ebildn", BILDIN_SPEC, 40 * 16384),
}
RCY_RECL, RC_RECL, R_RECL, BLD_RECL = 144, 376, 10000, 16384   # record lengths of the files
R_USED, EBLK_EFP, EBLK_BLD = 8192, 3, 40                        # bytes of an EFPR record written; records per region
EB_RECL = 84                                                    # EFPBLDS record length
_EBFMT = np.dtype([("blink", ">i4"), ("ditc", ">f4", 2), ("afdc", ">f4", 2), ("bkvl", ">f4", 2),
                   ("asvl", ">f4", 2), ("bcwp", ">f4", 2), ("rcwp", ">f4", 2), ("pcst", ">f4"),
                   ("pcap", ">f4", 2), ("serp", ">f4"), ("abde", ">f4", 2), ("ptyp", ">i4"),
                   ("syr", ">i4")])
assert _EBFMT.itemsize == EB_RECL


class BuildFile:
    """EMM_EFPBLDS: records of 84 bytes, big-endian. A record is a dict with the keys
    UNEWBLD (capcost.py) uses: blink, ditc, afdc, bkvl, asvl, bcwp, rcwp, pcst, pcap, serp,
    abde, ptyp, syr. Records are decoded when first touched and written back by flush();
    records never touched keep their bytes. Behaves as the mapping capcost.unewbld wants
    (`in`, `[]`, `[]=`)."""

    def __init__(self, data):
        self.data = bytearray(data)
        self.cache = {}

    @property
    def nrec(self):
        return max(len(self.data) // EB_RECL, max(self.cache, default=0))

    def __contains__(self, k):
        return k in self.cache or 1 <= k <= len(self.data) // EB_RECL

    def __len__(self):
        return self.nrec

    def __getitem__(self, k):
        if k not in self.cache:
            if not 1 <= k <= len(self.data) // EB_RECL:
                raise KeyError(k)
            r = np.frombuffer(self.data, dtype=_EBFMT, count=1, offset=(k - 1) * EB_RECL)[0]
            self.cache[k] = dict(
                blink=int(r["blink"]), ditc=list(r["ditc"].astype("f4")), afdc=list(r["afdc"].astype("f4")),
                bkvl=list(r["bkvl"].astype("f4")), asvl=list(r["asvl"].astype("f4")),
                bcwp=list(r["bcwp"].astype("f4")), rcwp=list(r["rcwp"].astype("f4")),
                pcst=np.float32(r["pcst"]), pcap=list(r["pcap"].astype("f4")), serp=np.float32(r["serp"]),
                abde=list(r["abde"].astype("f4")), ptyp=int(r["ptyp"]), syr=int(r["syr"]))
        return self.cache[k]

    def __setitem__(self, k, rec):
        self.cache[k] = rec

    def keys(self):
        return range(1, self.nrec + 1)

    def values(self):
        return (self[k] for k in self.keys())

    def flush(self):
        """Encode the touched records into the file bytes."""
        need = self.nrec * EB_RECL
        if len(self.data) < need:
            self.data.extend(bytes(need - len(self.data)))
        for k, rec in self.cache.items():
            r = np.zeros(1, dtype=_EBFMT)
            for key in ("blink", "pcst", "serp", "ptyp", "syr"):
                r[key] = rec[key]
            for key in ("ditc", "afdc", "bkvl", "asvl", "bcwp", "rcwp", "pcap", "abde"):
                r[key] = np.asarray(rec[key], dtype="f4")
            self.data[(k - 1) * EB_RECL: k * EB_RECL] = r.tobytes()
        return bytes(self.data)


class Books:
    """The five files as bytes, plus the routines that read and write them."""

    def __init__(self, rcy, rc, r, builds, ecpidaf):
        self.rcy, self.rc, self.r = bytearray(rcy), bytearray(rc), bytearray(r)
        self.builds = BuildFile(builds)
        self.bld = bytearray(ecpidaf)

    @classmethod
    def from_dir(cls, folder):
        folder = Path(folder)
        rd = lambda n: (folder / n).read_bytes()  # noqa: E731
        return cls(rd("EMM_EFPRCY.daf"), rd("EMM_EFPRC.daf"), rd("EMM_EFPR.daf"), rd("EMM_EFPBLDS.daf"),
                   rd("EMM_ECPIDAF.daf"))

    # -- raw records
    @staticmethod
    def _read(buf, irec, recl, n=None):
        n = recl if n is None else n
        a = (irec - 1) * recl
        if irec < 1 or a + n > len(buf):
            raise IndexError(f"record {irec} is past the end of the file")
        return bytes(buf[a: a + n])

    @staticmethod
    def _write(buf, irec, recl, data):
        a = (irec - 1) * recl
        if a + len(data) > len(buf):
            buf.extend(bytes(a + len(data) - len(buf)))
        buf[a: a + len(data)] = data

    # -- record numbers (uefp.f, udaf.f)
    @staticmethod
    def rcy_rec(s, nrgn, icall, iy):
        return ICOM[icall] + (nrgn - 1) * 3 + (iy - 1) * int(s["ijumpemrgn"]) * 3

    @staticmethod
    def rc_rec(nrgn, icall, idata):
        return idata + (ICOM[icall] - 1) * 2 + (nrgn - 1) * 6

    @staticmethod
    def bld_rec(s, iyr, irg):
        """First of EBLK$BLD records: (IRG + IJUMPEMRGN*(IYR-1))*EBLK$BLD - (EBLK$BLD-1)."""
        return (irg + int(s["ijumpemrgn"]) * (iyr - 1)) * EBLK_BLD - (EBLK_BLD - 1)

    # -- GETRCY / STRRCY
    def getrcy(self, s, nrgn, icall, iy):
        BLOCKS["rcy"].load(s, self._read(self.rcy, self.rcy_rec(s, nrgn, icall, iy), RCY_RECL))

    def strrcy(self, s, nrgn, icall, iy):
        self._write(self.rcy, self.rcy_rec(s, nrgn, icall, iy), RCY_RECL, BLOCKS["rcy"].sync(s))

    # -- GETRC / STRRC
    def getrc(self, s, nrgn, icall, idata):
        BLOCKS["rc"].load(s, self._read(self.rc, self.rc_rec(nrgn, icall, idata), RC_RECL))

    def strrc(self, s, nrgn, icall, idata):
        self._write(self.rc, self.rc_rec(nrgn, icall, idata), RC_RECL, BLOCKS["rc"].sync(s))

    # -- GETR / STRR: EBLK$EFP records of 10000 bytes, 8192 of them used
    def getr(self, s, nrgn):
        base = EBLK_EFP * (nrgn - 1)
        raw = b"".join(self._read(self.r, base + k, R_RECL, R_USED) for k in range(1, EBLK_EFP + 1))
        BLOCKS["r"].load(s, raw)

    def strr(self, s, nrgn):
        base = EBLK_EFP * (nrgn - 1)
        raw = BLOCKS["r"].sync(s)
        for k in range(1, EBLK_EFP + 1):
            self._write(self.r, base + k, R_RECL, raw[(k - 1) * R_USED: k * R_USED])

    # -- GETBLD / STRBLD (udaf.f): EBLK$BLD records of 16384 bytes
    def getbld(self, s, iyr, irg):
        a = self.bld_rec(s, iyr, irg)
        BLOCKS["bld"].load(s, b"".join(self._read(self.bld, a + j, BLD_RECL) for j in range(EBLK_BLD)))

    def strbld(self, s, iyr, irg):
        a = self.bld_rec(s, iyr, irg)
        raw = BLOCKS["bld"].sync(s)
        for j in range(EBLK_BLD):
            self._write(self.bld, a + j, BLD_RECL, raw[j * BLD_RECL: (j + 1) * BLD_RECL])

    def bildin_block(self, iyr, irg, s):
        """The BILDIN record as a region block (plain names), without touching the state."""
        a = self.bld_rec(s, iyr, irg)
        raw = b"".join(self._read(self.bld, a + j, BLD_RECL) for j in range(EBLK_BLD))
        return BLOCKS["bld"].region_block(raw), raw

    # -- GETEB / STREB (uefp.f): the linked list of builds of one component
    @staticmethod
    def _first_link(s, nrgn, icall):
        return int(s["bldlnk"][nrgn, {"G": 1, "T": 3}.get(icall, 5)])

    def geteb(self, s, nrgn, icall):
        """Follow the region's list for the component, filling the EB arrays (rows 1..EBNUM)."""
        num = 1
        ilink = self._first_link(s, nrgn, icall)
        while ilink != 0:
            r = self.builds[ilink]
            put(s, "blink", r["blink"])
            for k in (1, 2):
                s["ebditc"][num, k] = r["ditc"][k - 1]
                s["ebafdc"][num, k] = r["afdc"][k - 1]
                s["ebbkvl"][num, k] = r["bkvl"][k - 1]
                s["ebasvl"][num, k] = r["asvl"][k - 1]
                s["ebbcwp"][num, k] = r["bcwp"][k - 1]
                s["ebrcwp"][num, k] = r["rcwp"][k - 1]
                s["ebpcap"][num, k] = r["pcap"][k - 1]
                s["ebabde"][num, k] = r["abde"][k - 1]
            s["ebpcst"][num] = r["pcst"]
            s["ebserp"][num] = r["serp"]
            s["ebptyp"][num] = r["ptyp"]
            s["ebsyr"][num] = r["syr"]
            num += 1
            ilink = r["blink"]
        put(s, "ebnum", num - 1)

    def streb(self, s, nrgn, icall):
        """Write the EB arrays back over the same records of the list (the links stay)."""
        ilink = self._first_link(s, nrgn, icall)
        for j in range(1, int(s["ebnum"]) + 1):
            r = self.builds[ilink]
            put(s, "blink", r["blink"])
            for k in (1, 2):
                r["ditc"][k - 1] = s["ebditc"][j, k]
                r["afdc"][k - 1] = s["ebafdc"][j, k]
                r["bkvl"][k - 1] = s["ebbkvl"][j, k]
                r["asvl"][k - 1] = s["ebasvl"][j, k]
                r["bcwp"][k - 1] = s["ebbcwp"][j, k]
                r["rcwp"][k - 1] = s["ebrcwp"][j, k]
                r["pcap"][k - 1] = s["ebpcap"][j, k]
                r["abde"][k - 1] = s["ebabde"][j, k]
            r["pcst"] = s["ebpcst"][j]
            r["serp"] = s["ebserp"][j]
            r["ptyp"] = int(s["ebptyp"][j])
            r["syr"] = int(s["ebsyr"][j])
            ilink = r["blink"]

    # -- the whole store as bytes (builds flushed)
    def files(self):
        return {"EMM_EFPRCY.daf": bytes(self.rcy), "EMM_EFPRC.daf": bytes(self.rc),
                "EMM_EFPR.daf": bytes(self.r), "EMM_EFPBLDS.daf": self.builds.flush(),
                "EMM_ECPIDAF.daf": bytes(self.bld)}

    def sync_views(self, s):
        """Bring every byte view in the state up to date with its named members."""
        for b in BLOCKS.values():
            b.sync(s)
