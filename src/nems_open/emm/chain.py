"""EMM's load and pricing in Python, year after year: LDSM, the EFD stand-in, EFP.

Starts from the oracle's 2021 state (the dumps around LDSM and EFP, and the
books snapshot taken before EFP), then runs NEMS's two iterations a year, with
the pieces of UTIL that surround LDSM and EFP:
- the hydrogen model's hourly electrolyzer load into LDSM's hours
  (receive_from_hmm_electricity_demand, ephrts.f90);
- EFP's STEO price benchmark: zero the year's adders, run EFP, and in STEO years
  compute the adders and run EFP again (UTIL, util.f around line 1060).

Inputs set by parts of EMM that are not ported (renewables' distributed-capacity
adjustments, the nuclear ZEC subsidy) are EIA's yearly values, read from the
oracle's last dumps, which hold every past year of a year-indexed array.
Each region's dispatch block is the stand-in (efp/efd_standin.py) over the
block the oracle had in the start year.
"""

import numpy as np

from nems_open import oracle_state, steo
from nems_open.emm.efp import books as efp_books
from nems_open.emm.efp import efd_standin, elefp
from nems_open.emm.ldsm import driver as ldsm
from nems_open.fortran_array import FArray
from nems_open.paths import REPO_ROOT

BOOKS = REPO_ROOT / "oracle" / "run_emm" / "efp_books"
UIUF, MVS = 45, 36
f32 = np.float32
# Year-indexed inputs from EMM parts not ported: (array, dump that holds every year)
EXTERNAL = [("pv_cap_adj", "final"), ("pt_cap_adj", "final"), ("so_cap_adj", "final"), ("wn_cap_adj", "final"),
            ("wl_cap_adj", "final"), ("wf_cap_adj", "final"), ("elnucsbdy", "fp_in")]
MONTH2SEASON = [4, 4, 1, 1, 2, 2, 2, 2, 3, 3, 4, 4]
CENSUS_STEO = ["nec", "mac", "enc", "wnc", "sac", "esc", "wsc", "mtn", "pac"]  # census divisions 1-9


def _copy(d):
    return {k: (v.copy() if isinstance(v, FArray) else v) for k, v in d.items()}


def _region_blocks(y):
    """Each region's DISPOUT and BILDIN block as the oracle had it after EFD in year y."""
    d = oracle_state.load("fs_out", y, "emm")
    out = {}
    for k, v in d.items():
        name, _, r = k.rpartition("_r")
        out.setdefault(int(r), {})[name] = v
    return out


class Chain:
    def __init__(self, snap, start=32):
        self.snap = snap
        ld_in = oracle_state.load("ld_in", start, "emm")
        fp_in = oracle_state.load("fp_in", start, "emm")
        self.s = _copy(fp_in)
        for k, v in ld_in.items():          # LDSM's own inputs, as before ELLDSM
            self.s.setdefault(k, v.copy() if isinstance(v, FArray) else v)
        self.books = efp_books.Books.from_dir(BOOKS / str(start))
        # The snapshot misses region 25 D's last buffered write before EFP: its RC
        # record 2 to record 1 copy (tests/test_efp_elefp.py, finish_snapshot).
        bk = self.books
        bk._write(bk.rc, bk.rc_rec(25, "D", 1), efp_books.RC_RECL, bk._read(bk.rc, bk.rc_rec(25, "D", 2), efp_books.RC_RECL))
        self.base = _region_blocks(start)   # the non-stand-in part of each region's block
        self.external = {}
        for name, tag in EXTERNAL:
            d = oracle_state.load(tag, 61, "emm")
            self.external[name] = d[name]
        self.steo = steo.load()
        self.year = start

    def dispout(self, y):
        def block(nrgn):
            b = dict(self.base[nrgn])
            for k, v in efd_standin.block(self.snap, y, nrgn, UIUF, MVS).items():
                b[k] = FArray(np.asarray(v)) if np.ndim(v) else v
            return b
        return block

    def receive_h2(self, y):
        """receive_from_hmm_electricity_demand: the hydrogen model's seasonal hourly
        electrolyzer load (MW) spread over LDSM's 864 hours, and its annual energy."""
        s = self.s
        q = self.snap["HMMBLK/qelhm_hr"]
        idaytq = s["idaytq"]
        totaldays = [0] * 5
        for m in range(1, 13):
            for d in range(1, 4):
                totaldays[MONTH2SEASON[m - 1]] += int(idaytq[d, m])
        e, w, a = s["h2_elec_consumed"], s["h2_mwh_consumed"], s["annual_h2_mwh_consumed"]
        for r in range(1, 26):
            h864 = 0
            for m in range(1, 13):
                se = MONTH2SEASON[m - 1]
                for d in range(1, 4):
                    for h in range(1, 25):
                        h864 += 1
                        e[r, h864] = f32(f32(q[r - 1, se - 1, h - 1, y - 1]) / f32(totaldays[se]))
                        w[r, h864] = f32(e[r, h864] * f32(int(idaytq[d, m])))
                        a[r] = f32(a[r] + w[r, h864])

    def start_year(self, y):
        s = self.s
        s["curiyr"] = s["curiyr"].dtype.type(y)
        if "curcalyr" in s:
            s["curcalyr"] = s["curcalyr"].dtype.type(y + 1989)
        for name, src in self.external.items():
            s[name].a[..., y - 1] = src.a[..., y - 1]

    def efp_pass(self, y):
        """UTIL around ELEFP: EFP once, and again with STEO price adders in STEO years."""
        s = self.s
        s["efpitr"] = s["efpitr"].dtype.type(1)
        s["bchmrksteopriceadder"][:, y] = 0.0
        s["bchmrksteoprc_n"][:, y] = 0.0
        with np.errstate(all="ignore"):
            elefp.elefp(s, self.books, self.dispout(y))
        if s["bmelprc"][y] > 0.0:
            qelas = self.snap["QBLK/qelas"]
            add = s["bchmrksteopriceadder"]
            for c, name in enumerate(CENSUS_STEO, 1):
                est = f32(self.steo[f"estcu_{name}"][y - 1])
                v = f32(f32(f32(0.9) * f32(f32(s["pelas"][c, y] * f32(0.34121416)) - est))
                        * f32(qelas[c - 1, y - 1]))
                add[c, y] = f32(v * f32(2930710))
            for irg in range(1, int(s["unrgns"]) + 1):
                for icr in range(1, 10):
                    s["bchmrksteoprc_n"][irg, y] = f32(s["bchmrksteoprc_n"][irg, y]
                                                       + f32(add[icr, y] * s["mappcton"][irg, icr, 4]))
            s["efpitr"] = s["efpitr"].dtype.type(2)
            with np.errstate(all="ignore"):
                elefp.elefp(s, self.books, self.dispout(y))

    def iteration(self, y, itr, iters=2, fcrl=None):
        """One NEMS iteration of year y. fcrl: the final-pass switch (statements,
        reports, REVGAP's smoothing); by default 1 on iteration `iters`."""
        s = self.s
        if itr == 1:
            self.start_year(y)
            s["h2_elec_consumed"].a[...] = 0.0
            s["h2_mwh_consumed"].a[...] = 0.0
            s["annual_h2_mwh_consumed"].a[...] = 0.0
            self.receive_h2(y)
        s["curiyr"] = s["curiyr"].dtype.type(y)
        s["curitr"] = s["curitr"].dtype.type(itr)
        if fcrl is None:
            fcrl = 1 if itr == iters else 0
        s["fcrl"] = s["fcrl"].dtype.type(fcrl)
        if "ncrl" in s:
            s["ncrl"] = s["ncrl"].dtype.type(fcrl)
        ldsm.elldsm(s, 1)
        self.efp_pass(y)
