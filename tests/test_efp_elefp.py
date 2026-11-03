"""ELEFP and the routines around each EFP component (src/nems_open/emm/efp/elefp.py)
against the oracle.

What the books snapshots are. oracle/run_emm/efp_books/32 and /41 were meant to be EFP's
direct-access files just before EFP in 2021 and 2030. They are not: the two directories are
byte-identical, they were copied seconds before the oracle run that wrote the dumps started,
and they hold EFP's files at the end of the PREVIOUS run, after 2050 (tests/test_efp_books.py
shows the files equal the state fp_out holds for 2050; the build file lists builds that start
as late as 2051). snapshot_efp.py waits for ld_out's index to reach 205 lines, which a
leftover dump from the earlier run had already done. So ELEFP cannot be matched to fp_out
from them, and test_elefp_year skips once it has run when it sees that.

What is checked meanwhile. Region 1 in 2030 is dumped around every call of its three
components (gg, gt, gd = GL; ag, at, ad = AVRPRC; cp = COMPPRC; y_cap1 = CAPCOST), and fp_out
holds the U* arrays ELLGTR stored for region 1. The only inputs that are not in a dump are the
two records the stale snapshot gets wrong: RC record 1 (last year's lagged values: 32 of the
record's members; the rest are static inputs the snapshot has right) and the BILDIN record
the ECP wrote. Those are taken from the dumps (the OUTRC members GETRC leaves in the state at
gg_in, gt_in and gd_in; the EBILDN y_cap1_out holds after CAPCOST's STRBLD), and everything
else runs through the store: GETRCY, CAPCOST (with GETBLD/STRBLD), ALLFAC, GETRC, the U*
arrays, GL, AVRPRC, COMPPRC, ELLGTR and STRRC.
"""

import functools

import numpy as np
import pytest

from emm_oracle import assert_matches, available, before_after, rel_err
from nems_open import oracle_state
from nems_open.emm.efp import books, elefp
from nems_open.fortran_array import FArray
from nems_open.paths import REPO_ROOT
from test_efp_phasein import _fix_efpnd

ids = lambda y: str(1989 + y)  # noqa: E731
BOOKS = REPO_ROOT / "oracle" / "run_emm" / "efp_books"
LAG_NAMES = [lag for lag, _ in elefp.LAGS]
# EFPND (nuclear decommissioning) is dumped with REAL*4 items typed as INTEGER; same fix as
# test_efp_phasein, but for a dump with no region suffix
EFPND_REAL = {"ndtaxr": 50, "nestesc": 50, "ndadmnr": None, "ndearnr": None, "ndtcmon": None,
              "ndpser": 3, "ndpscu": 3, "nucap": 120, "nuppr": 120, "ndest": 120, "ndcbal": 120,
              "ndcapmt": 120}
# byte views of whole blocks that STMTS and the GL fill, which these tests do not rebuild
BYTE_VIEWS = ("outrp2", "outrep")


@functools.lru_cache(maxsize=None)
def _fs_out(y):
    return oracle_state.load("fs_out", y, "emm")


def dispout(y):
    d = _fs_out(y)

    def get(nrgn):
        suf = f"_r{nrgn:02d}"
        return {k[: -len(suf)]: v for k, v in d.items() if k.endswith(suf)}
    return get


def fix_efpnd(d, tag, y):
    folder = oracle_state.state_dir("emm") / tag / str(y)
    for name, n in EFPND_REAL.items():
        if name in d:
            raw = np.fromfile(folder / f"{name}.bin", dtype=np.float32)
            d[name] = raw[0] if n is None else FArray(raw.copy())
    return d


def check(s, after, label="", skip=()):
    """assert_matches, with the CHARACTER scalars (byte views) compared as bytes and NUCPCT
    (NaN and inf that nothing here touches) compared exactly."""
    for blk in books.BLOCKS.values():
        blk.sync(s)   # the byte views are the same memory as the named arrays
    fpbuf(s, after)
    strs = tuple(k for k, v in after.items() if isinstance(v, (bytes, np.bytes_)))
    for k in strs:
        if k in BYTE_VIEWS:
            continue
        assert bytes(s[k]).rstrip(bytes(1)) == bytes(after[k]).rstrip(bytes(1)), f"{label} {k}"
    if "nucpct" in after:
        assert np.array_equal(s["nucpct"].a, after["nucpct"].a, equal_nan=True)
    worst = assert_matches(s, after, tol=1e-6, skip=strs + ("nucpct",) + BYTE_VIEWS + tuple(skip))
    if label:
        print(f"{label}: worst relative error {max(worst.values()):.3g} over {len(worst)} arrays")
    return worst


def fpbuf(s, after):
    """FPRICE(.,1,NRGN), a SAVEd local of RATES left by an earlier call, is not in the dump
    (same allowance as test_efp_avrprc): take those five buffer entries from the oracle."""
    if "colv" in after:
        s["colv"].a[:, 7, :5] = after["colv"].a[:, 7, :5]
        s["colvals"].a[7, :5] = after["colvals"].a[7, :5]


def fix_efpnd_region(d, tag, y, r):
    return _fix_efpnd(d, tag, y, r)


def snapshot(y):
    folder = BOOKS / str(y)
    if not (folder / "EMM_EFPR.daf").exists():
        pytest.skip(f"no EFP books snapshot for {1989 + y}")
    return books.Books.from_dir(folder)


def stale(bk, y):
    """Builds that start more than ten years after the run year cannot be in the files yet."""
    syr = np.frombuffer(bytes(bk.builds.data), dtype=books._EBFMT)["syr"]
    return bool(syr.max() > y + 10)


# ---- ELEFP, whole


@pytest.mark.parametrize("y", [32, 41], ids=ids)
def test_elefp_year(y):
    """Python ELEFP from fp_in plus the year's books equals fp_out, for every array the oracle
    dumped. Runs on any snapshot (it must not fail on one), but compares only on a snapshot
    that is the year's own."""
    s, after = before_after("fp", y)
    bk = snapshot(y)
    fix_efpnd(s, "fp_in", y)
    fix_efpnd(after, "fp_out", y)
    with np.errstate(all="ignore"):
        elefp.elefp(s, bk, dispout(y))
    for r in range(1, 26):   # every region's three components wrote their RC record 2
        assert bk.rc_rec(r, "D", 2) <= len(bk.rc) // books.RC_RECL
    if stale(bk, y):
        pytest.skip("the books snapshot is EFP's files after 2050, not before EFP in this year "
                    "(see this file's docstring); ELEFP ran, nothing to compare")
    worst = check(s, after)
    print(f"ELEFP {ids(y)}: worst relative error {max(worst.values()):.3g}")


def test_elefp_first_year_first_iteration_is_not_ported():
    s, _ = before_after("fp", 32)
    s["usyear"][int(s["curiyr"])] = s["uestyr"]
    s["curitr"] = np.int32(1)
    with pytest.raises(NotImplementedError):
        elefp.elefp(s, snapshot(32), dispout(32))


def test_elefp_switches(monkeypatch):
    """EFPFCRL and EFPITPRT: one pass without STEO benchmarking, the second of two with it."""
    s, _ = before_after("fp", 32)
    bk = snapshot(32)
    monkeypatch.setattr(elefp.elset, "elset", lambda state: None)
    monkeypatch.setattr(elefp.elset, "revgap", lambda state: None)
    for bm, itr, want in ((0.0, 1, (1, 1)), (5.0, 1, (0, 0)), (5.0, 2, (1, 1))):
        t = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in s.items()}
        t["bmelprc"][int(t["curiyr"])] = np.float32(bm)
        t["efpitr"] = np.int32(itr)
        t["fcrl"] = np.int32(1)
        t["unrgns"] = np.int32(0)   # no regions: only the switches and the wrap-up run
        elefp.elefp(t, bk, dispout(32))
        assert (int(t["efpfcrl"]), int(t["efpitprt"])) == want


# ---- region 1 in 2030, component by component, with the two stale records taken from the dumps


def patch_rc(bk, r, icall, dump):
    """RC record 1 of (r, icall): the lagged members (ELxxx) from an OUTRC the oracle holds after GETRC."""
    a = bk.rc_rec(r, icall, 1)
    raw = bytearray(bk._read(bk.rc, a, books.RC_RECL))
    blk = books.BLOCKS["rc"]
    for n in LAG_NAMES:
        blk.encode(raw, n, dump[n])
    bk._write(bk.rc, a, books.RC_RECL, bytes(raw))


def patch_bildin(bk, s, r, cap_out):
    """The BILDIN record region r holds when CAPCOST's STRBLD has written it (EBILDN of y_cap1_out)."""
    bk._write(bk.bld, bk.bld_rec(s, 1, r), books.BLD_RECL * books.EBLK_BLD, cap_out["ebildn"].a.tobytes())


@pytest.mark.parametrize("y", [41], ids=ids)
def test_components_of_region_1(y):
    r = 1
    tags = ["gg", "gt", "gd", "at", "ad", "cp", "y_cap1"]
    if not all(available(f"{t}_in", y) and available(f"{t}_out", y) for t in tags):
        pytest.skip(f"region dumps not available for {1989 + y}")
    s, fp_out = before_after("fp", y)
    fix_efpnd(s, "fp_in", y)
    fix_efpnd(fp_out, "fp_out", y)
    bk = snapshot(y)
    s["_efpbld"] = bk.builds
    patch_bildin(bk, s, r, before_after("y_cap1", y, r)[1])
    for icall, tag in (("G", "gg"), ("T", "gt"), ("D", "gd")):
        patch_rc(bk, r, icall, before_after(tag, y, r)[0])
    elefp.put(s, "efpfcrl", 1)   # ELEFP sets it before EFP
    get = dispout(y)

    def dump(tag, which):
        d = before_after(tag, y, r)[0 if which == "in" else 1]
        return fix_efpnd_region(d, f"{tag}_{which}", y, r)

    # (component, GL's dump, the dump after the component's accounting)
    for icall, gl_tag, done_tag, comp in (("G", "gg", "cp", elefp.genera), ("T", "gt", "at", elefp.transm),
                                          ("D", "gd", "ad", elefp.distri)):
        elefp.elgltr(s, bk, r, icall)
        check(s, dump(gl_tag, "in"), f"ELGLTR {icall}")       # what GL is called with
        elefp._gl(s, bk, get, r, icall)
        check(s, dump(gl_tag, "out"), f"GL {icall}")
        comp(s, r, icall)
        out = dump(done_tag, "out")
        check(s, out, f"{icall} accounting")
        elefp.ellgtr(s, bk, r, icall)
        if icall != "D":   # the next component's ELGLTR follows: ELLGTR + GETRC are checked by its dump
            continue

    # the U* arrays ELLGTR stored for region 1, against what fp_out holds for it (no other
    # region's work touches region 1's entries)
    bad = {}
    for _, u in elefp.VECTORS:
        bad[u] = rel_err(s[u].a[:, :, r - 1], fp_out[u].a[:, :, r - 1])
    for _, u, _n in elefp.LEADING:
        bad[u] = rel_err(s[u].a[..., r - 1], fp_out[u].a[..., r - 1])
    bad["upycwp"] = rel_err(s["upycwp"].a[..., r - 1], fp_out["upycwp"].a[..., r - 1])
    for u in ("urtomd", "urtomt"):
        bad[u] = rel_err(s[u].a[:, r - 1], fp_out[u].a[:, r - 1])
    print(f"U arrays of region 1 after ELLGTR: worst relative error {max(bad.values()):.3g} over {len(bad)} arrays")
    assert max(bad.values()) < 1e-6, {k: v for k, v in bad.items() if v >= 1e-6}
    # ELLGTR wrote RC record 2 of each component: it is what the state holds then
    for icall in "GTD":
        rec = bk._read(bk.rc, bk.rc_rec(r, icall, 2), books.RC_RECL)
        assert rec != bytes(books.RC_RECL)


@pytest.mark.parametrize("y", [41], ids=ids)
def test_elefp_whole_year_region_1(y):
    """The whole ELEFP, 25 regions and ELSET, with region 1's two stale records replaced from
    the dumps (the other regions run on the stale snapshot and are wrong). What region 1
    determines alone must match fp_out: its row of the prices ELSET reports, its cost of
    service, its competitive-pricing entries, and the peaks ELEFP sets for every region."""
    r = 1
    if not (available("gg_in", y) and available("y_cap1_out", y)):
        pytest.skip(f"region dumps not available for {1989 + y}")
    s, fp_out = before_after("fp", y)
    fix_efpnd(s, "fp_in", y)
    bk = snapshot(y)
    patch_bildin(bk, s, r, before_after("y_cap1", y, r)[1])
    for icall, tag in (("G", "gg"), ("T", "gt"), ("D", "gd")):
        patch_rc(bk, r, icall, before_after(tag, y, r)[0])
    with np.errstate(all="ignore"):
        elefp.elefp(s, bk, dispout(y))
    curiyr = int(s["curiyr"])
    worst = {
        "eprice": rel_err(s["eprice"].a[:, :, r - 1], fp_out["eprice"].a[:, :, r - 1]),
        "costserv": rel_err(s["costserv"].a[:, r - 1, curiyr - 1], fp_out["costserv"].a[:, r - 1, curiyr - 1]),
        "efdpeak": rel_err(s["efdpeak"].a, fp_out["efdpeak"].a),
        "compcap": rel_err(s["compcap"].a[r - 1], fp_out["compcap"].a[r - 1]),
        "compex": rel_err(s["compex"].a[r - 1], fp_out["compex"].a[r - 1]),
        "dgapold": rel_err(s["dgapold"].a[r - 1], fp_out["dgapold"].a[r - 1]),
        "efpfcrl": rel_err(s["efpfcrl"], fp_out["efpfcrl"]),
        "efpitprt": rel_err(s["efpitprt"], fp_out["efpitprt"]),
    }
    for u in ("urbde", "urpsdv", "urrcwp"):
        worst[u] = rel_err(s[u].a[:, :, r - 1], fp_out[u].a[:, :, r - 1])
    print(f"ELEFP {ids(y)}, region 1 only: worst relative error {max(worst.values()):.3g} over {len(worst)} arrays")
    assert max(worst.values()) < 1e-6, {k: v for k, v in worst.items() if v >= 1e-6}
