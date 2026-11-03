"""EFP's books store (src/nems_open/emm/efp/books.py): the codec from record bytes to
each COMMON block's named arrays, and the get/put routines on the snapshot files.

The snapshots in oracle/run_emm/efp_books/ (32 and 41) are identical, and they are
EFP's files as they stood at the END of the oracle run, after 2050's last EFP call,
not the books before EFP in 2021 or 2030 (see tests/test_efp_elefp.py). That is
enough to test the store itself: the dump after the run's last year (fp_out for 2050)
holds the byte views and named arrays that EFP last wrote there, so the files must
hold the same bytes.
"""

import functools

import numpy as np
import pytest

from emm_oracle import available, before_after
from nems_open import oracle_state
from nems_open.emm.efp import books, capcost
from nems_open.paths import REPO_ROOT

SNAPSHOT = REPO_ROOT / "oracle" / "run_emm" / "efp_books" / "32"
VIEWS = {"outrcy": "rcy", "outrc": "rc", "outr": "r", "ebildn": "bld"}
ids = lambda y: str(1989 + y)  # noqa: E731

needs_files = pytest.mark.skipif(not (SNAPSHOT / "EMM_EFPR.daf").exists(), reason="no EFP books snapshot")


@functools.lru_cache(maxsize=None)
def _dump(tag, y):
    if not available(tag, y):
        pytest.skip(f"EMM oracle state {tag} not dumped for {1989 + y}")
    return oracle_state.load(tag, y, "emm")


def view_bytes(v, size):
    data = v.a.tobytes() if hasattr(v, "a") else bytes(v)
    return data.ljust(size, bytes(1))[:size]


def value(v):
    return v.a if hasattr(v, "a") else v


def fresh():
    return books.Books.from_dir(SNAPSHOT)


def test_layouts():
    b = books.BLOCKS
    assert (b["rcy"].named_bytes, b["rcy"].size) == (144, 144)   # 36 REAL*4
    assert (b["rc"].named_bytes, b["rc"].size) == (376, 376)     # 94 four-byte items
    assert b["r"].named_bytes == 4 * (5 * 40 * 14 * 2 + 14 + 4) and b["r"].size == 3 * 8192
    assert b["bld"].size == 40 * 16384 and b["bld"].named_bytes < b["bld"].size


@pytest.mark.parametrize("tag", ["fp_in", "fp_out"])
@pytest.mark.parametrize("y", [32, 41, 61], ids=ids)
@pytest.mark.parametrize("view", list(VIEWS))
def test_codec_matches_byte_view(view, y, tag):
    """Decoding the byte view gives each named array the dump holds; encoding the named arrays
    gives the byte view back, over the bytes they cover."""
    s = _dump(tag, y)
    blk = books.BLOCKS[VIEWS[view]]
    raw = view_bytes(s[view], blk.size)
    present = [n for n in blk.members if n in s]
    if view in ("outrcy", "outrc", "outr"):
        assert len(present) == len(blk.members), set(blk.members) - set(present)
    assert present
    buf = bytearray(blk.size)
    covered = np.zeros(blk.size, bool)
    for n in present:
        got = blk.decode(raw, n)
        assert np.array_equal(np.asarray(got), np.asarray(value(s[n])), equal_nan=True), n
        blk.encode(buf, n, s[n])
        off, dt, shape = blk.members[n]
        covered[off: off + dt.itemsize * int(np.prod(shape, dtype=np.int64))] = True
    assert bytes(np.frombuffer(bytes(buf), np.uint8)[covered]) == bytes(np.frombuffer(raw, np.uint8)[covered])
    if view in ("outrcy", "outrc"):
        assert covered.all() and bytes(buf) == raw


@pytest.mark.parametrize("y", [32, 41, 61], ids=ids)
def test_sync_rebuilds_view_from_named_arrays(y):
    """The state's view is rewritten from the named arrays, the way the EQUIVALENCE keeps them one memory."""
    s = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in _dump("fp_in", y).items()}
    want = {view: view_bytes(s[view], books.BLOCKS[b].size) for view, b in VIEWS.items()}
    for view in VIEWS:
        s[view] = type(s[view])(np.zeros_like(s[view].a)) if hasattr(s[view], "a") else np.bytes_(b"")
    for view, b in VIEWS.items():
        raw = books.BLOCKS[b].sync(s)
        assert view_bytes(s[view], books.BLOCKS[b].size) == raw
        if b in ("rcy", "rc"):
            assert raw == want[view]


@needs_files
@pytest.mark.parametrize("y", [32, 41, 61], ids=ids)
@pytest.mark.parametrize("r", [1, 13])
def test_rcy_records_hold_the_calendar_year_inputs(y, r):
    """EFPRCY is written once (by the first year's readers), so any snapshot holds the right
    values. CAPCOST's dump (final iteration, before it changes anything) has these inputs."""
    if not available("y_cap1_in", y):
        pytest.skip("no y_cap1 dump")
    s, _ = before_after("y_cap1", y, r)
    b = fresh()
    raw = b._read(b.rcy, b.rcy_rec(s, r, "G", int(s["curiyr"])), books.RCY_RECL)
    blk = books.BLOCKS["rcy"]
    names = [n for n in ("esprlt", "esprst", "esprce", "esprps", "esrtce") if n in s]
    assert len(names) >= 4
    for n in names:
        assert np.array_equal(blk.decode(raw, n), s[n].a), n


@needs_files
def test_files_hold_the_state_after_the_last_efp_call():
    """fp_out for 2050 is the oracle's state after its last EFP call. Region 25's last component
    (D) left its books in the files: RC slot 2 and the EFPR record (written in the year's first
    iteration), the BILDIN record GL read, and the build list EB arrays."""
    if not available("fp_out", 61):
        pytest.skip("no 2050 dump")
    s = oracle_state.load("fp_out", 61, "emm")
    b = fresh()
    rc = b._read(b.rc, b.rc_rec(25, "D", 2), books.RC_RECL)
    assert rc.rstrip(bytes(1)) == bytes(s["outrc"]).rstrip(bytes(1))
    r = b"".join(b._read(b.r, 3 * 24 + k, books.R_RECL, books.R_USED) for k in (1, 2, 3))
    assert r == s["outr"].a.tobytes()
    bld = b"".join(b._read(b.bld, b.bld_rec(s, 1, 25) + j, books.BLD_RECL) for j in range(books.EBLK_BLD))
    assert bld == s["ebildn"].a.tobytes()
    # the same records through the state
    t = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in s.items()}
    b.getrc(t, 25, "D", 2)
    assert bytes(t["outrc"]).rstrip(bytes(1)) == bytes(s["outrc"]).rstrip(bytes(1))
    for n in books.BLOCKS["rc"].members:
        assert np.array_equal(value(t[n]), value(s[n]), equal_nan=True), n
    b.getbld(t, 1, 25)
    assert t["ebildn"].a.tobytes() == s["ebildn"].a.tobytes()
    # EB arrays: the D list of region 25, as GETEB reads it
    t["ebnum"] = np.int32(0)
    b.geteb(t, 25, "D")
    assert int(t["ebnum"]) == int(s["ebnum"]) == 28
    n = int(s["ebnum"])
    for name in ("ebditc", "ebafdc", "ebbkvl", "ebasvl", "ebbcwp", "ebrcwp", "ebpcap", "ebabde"):
        assert np.array_equal(t[name].a[:n], s[name].a[:n]), name
    for name in ("ebpcst", "ebserp", "ebptyp", "ebsyr"):
        assert np.array_equal(t[name].a[:n], s[name].a[:n]), name


@needs_files
@pytest.mark.parametrize("y", [32, 41], ids=ids)
def test_get_then_put_leaves_every_file_unchanged(y):
    s = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in _dump("fp_in", y).items()}
    b = fresh()
    before = b.files()
    for nrgn in (1, 13, 25):
        for icall in "GTD":
            b.getrcy(s, nrgn, icall, y)
            b.strrcy(s, nrgn, icall, y)
            for slot in (1, 2):
                b.getrc(s, nrgn, icall, slot)
                b.strrc(s, nrgn, icall, slot)
        b.getr(s, nrgn)
        b.strr(s, nrgn)
        b.getbld(s, 1, nrgn)
        b.strbld(s, 1, nrgn)
    assert b.files() == before


@needs_files
def test_put_changes_only_its_record():
    s = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in _dump("fp_in", 32).items()}
    b = fresh()
    before = b.files()
    b.getrc(s, 7, "T", 1)
    s["elbde"][2] = np.float32(123.5)
    b.strrc(s, 7, "T", 2)
    after = b.files()
    rec = b.rc_rec(7, "T", 2)
    assert rec == 2 + (2 - 1) * 2 + (7 - 1) * 6   # IDATA + (ICOM-1)*2 + (NRGN-1)*6
    for name in before:
        if name != "EMM_EFPRC.daf":
            assert after[name] == before[name]
    lo, hi = (rec - 1) * 376, rec * 376
    assert after["EMM_EFPRC.daf"][:lo] == before["EMM_EFPRC.daf"][:lo]
    assert after["EMM_EFPRC.daf"][hi:] == before["EMM_EFPRC.daf"][hi:]
    assert books.BLOCKS["rc"].decode(after["EMM_EFPRC.daf"][lo:hi], "elbde")[1] == np.float32(123.5)


@needs_files
def test_efpr_record_is_10000_bytes_with_8192_used():
    s = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in _dump("fp_in", 32).items()}
    b = fresh()
    before = b.files()["EMM_EFPR.daf"]
    b.getr(s, 3)
    s["uobkvl"][5, 2, 1] = np.float32(9.0)
    b.strr(s, 3)
    after = b.files()["EMM_EFPR.daf"]
    changed = np.nonzero(np.frombuffer(before, np.uint8) != np.frombuffer(after, np.uint8))[0]
    assert len(changed) and changed.min() >= 6 * 10000 and changed.max() < 9 * 10000
    # UOBKVL(5,2,1): element 4 + 40*(1) = 44 -> byte 176, in the first record of region 3 (records 7..9)
    assert set(changed) <= set(range(6 * 10000 + 176, 6 * 10000 + 180))
    for k in range(7, 10):   # the 1808 bytes after each 8192 are never written
        a = (k - 1) * 10000 + 8192
        assert after[a: a + 1808] == before[a: a + 1808]


@needs_files
def test_build_file_is_big_endian_and_round_trips():
    b = fresh()
    r = b.builds[1]
    assert (r["blink"], r["ptyp"], r["syr"]) == (2, 8, 22)
    assert r["pcst"] == np.float32(247.0) and r["serp"] == np.float32(1.0) and r["pcap"][0] == np.float32(0.3075)
    original = bytes(b.builds.data)
    for k in b.builds.keys():
        b.builds[k]
    assert b.builds.flush() == original


@needs_files
@pytest.mark.parametrize("y", [32, 41], ids=ids)
def test_build_lists_follow_the_state_links(y):
    """BLDLNK (state) holds each list's first and last record; the last is on the chain from the first."""
    s = _dump("fp_in", y)
    b = fresh()
    seen = 0
    for r in range(1, 26):
        for k in (1, 3, 5):
            first, last = int(s["bldlnk"][r, k]), int(s["bldlnk"][r, k + 1])
            if first == 0:
                assert last == 0
                continue
            chain, n = [], first
            while n != 0:
                assert n not in chain
                chain.append(n)
                n = b.builds[n]["blink"]
            assert last in chain
            seen += 1
    assert seen > 40


@needs_files
def test_streb_writes_the_eb_arrays_back_over_the_list():
    s = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in _dump("fp_out", 61).items()}
    b = fresh()
    b.geteb(s, 25, "D")
    n = int(s["ebnum"])
    b.streb(s, 25, "D")                      # unchanged: no byte changes
    assert b.builds.flush() == bytes(fresh().builds.data)
    s["ebbkvl"][2, 1] = np.float32(77.0)
    s["ebptyp"][n] = 3
    b.streb(s, 25, "D")
    file = b.builds.flush()
    first = int(s["bldlnk"][25, 5])
    second = b.builds[first]["blink"]
    assert b.builds[second]["bkvl"][0] == np.float32(77.0)
    ref = fresh().builds.flush()
    differs = [k for k in range(1, len(file) // books.EB_RECL + 1)
               if file[(k - 1) * 84: k * 84] != ref[(k - 1) * 84: k * 84]]
    assert len(differs) == 2                 # the second record's book value and the last one's plant type
    assert s["blink"] == 0                   # BLINK ends as the last record's link


@needs_files
def test_unewbld_appends_to_the_file_and_links_it():
    s = {k: (v.copy() if hasattr(v, "copy") else v) for k, v in _dump("fp_in", 41).items()}
    b = fresh()
    s["_efpbld"] = b.builds
    s["lastbld"] = np.int32(len(b.builds))
    last_d = int(s["bldlnk"][4, 6])
    n0 = len(b.builds)
    z = [np.float32(0.0)] * 2
    capcost.unewbld(s, 4, list(z), list(z), list(z), list(z), list(z), list(z), capcost.EIDIST, 45,
                    np.float32(12.5), [np.float32(0.6), np.float32(0.4)], np.float32(1.0), list(z))
    assert len(b.builds) == n0 + 1 and int(s["bldlnk"][4, 6]) == n0 + 1
    file = b.builds.flush()
    assert len(file) == (n0 + 1) * 84
    assert b.builds[last_d]["blink"] == n0 + 1
    fresh_file = books.BuildFile(file)
    new = fresh_file[n0 + 1]
    assert (new["blink"], new["ptyp"], new["syr"], float(new["pcst"])) == (0, capcost.EIDIST, 45, 12.5)
    assert fresh_file[last_d]["blink"] == n0 + 1
