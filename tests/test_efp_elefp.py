"""ELEFP and the routines around each EFP component (src/nems_open/emm/efp/elefp.py)
against the oracle.

oracle/run_emm/efp_books/<year> are EFP's direct-access files just before ELEFP in that
year (final iteration), so ELEFP from fp_in plus the snapshot must give fp_out.

One snapshot quirk: the copy was taken while region 25's distribution component was in
progress in the year's first iteration (the build list already holds that region's new build,
but STREB has not written the EB arrays; see test_efp_books). The first-iteration step that
copies RC record 2 to record 1 (GETRC(...,2); STRRC(...,1) in ELGLTR) had not yet run for
region 25 D, so its record 1 is last year's second-to-last state. ELEFP's iteration-2 read of
that record needs the copy done: `finish_snapshot` does that one step. With it, ELEFP matches
exactly; without it only region 25's distribution component is off (EROBL, hence EROB and the
interest and preferred dividends that follow, and through ELSET the prices).
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


def finish_snapshot(bk):
    """Region 25 D's iteration-1 prologue: RC record 2 copied to record 1 (see the docstring).
    Most likely cause: region 25 D is the last record EFP writes before the snapshot,
    and gfortran had not yet flushed the file buffer when oracle/snapshot_efp.py copied
    the file (the oracle cannot be rebuilt with a flush under the current Windows block)."""
    bk._write(bk.rc, bk.rc_rec(25, "D", 1), books.RC_RECL, bk._read(bk.rc, bk.rc_rec(25, "D", 2), books.RC_RECL))
    return bk


def snapshot(y):
    folder = BOOKS / str(y)
    if not (folder / "EMM_EFPR.daf").exists():
        pytest.skip(f"no EFP books snapshot for {1989 + y}")
    return books.Books.from_dir(folder)


# ---- ELEFP, whole


@pytest.mark.parametrize("y", [32, 41], ids=ids)
def test_elefp_year(y):
    """Python ELEFP from fp_in plus the year's books equals fp_out, for every array the oracle dumped."""
    s, after = before_after("fp", y)
    bk = finish_snapshot(snapshot(y))
    fix_efpnd(s, "fp_in", y)
    fix_efpnd(after, "fp_out", y)
    with np.errstate(all="ignore"):
        elefp.elefp(s, bk, dispout(y))
    for r in range(1, 26):   # every region's three components wrote their RC record 2
        assert bk.rc_rec(r, "D", 2) <= len(bk.rc) // books.RC_RECL
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


# ---- region 1 in 2030, component by component


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
