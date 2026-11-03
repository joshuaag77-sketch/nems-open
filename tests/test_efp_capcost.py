"""EFP cost routines (src/nems_open/emm/efp/capcost.py) against the oracle."""

import numpy as np
import pytest

from emm_oracle import REGION_YEARS, REGIONS, assert_matches, available, before_after, rel_err
from nems_open.emm.efp import capcost

ids = lambda y: str(1989 + y)  # noqa: E731
UHBSYR, EFPSYR = 1989, 2023   # NEMS base year; first EFP forecast year (guards at the calls in ELGLTR)


def _need(tag, y):
    if not available(f"{tag}_out", y):
        pytest.skip(f"EMM oracle state for {tag} not dumped for {1989 + y}")


@pytest.mark.parametrize("r", REGIONS)
@pytest.mark.parametrize("y", REGION_YEARS, ids=ids)
@pytest.mark.parametrize("tag,n", [("y_cap1", 1), ("y_cap2", 2)])
def test_capcost(tag, n, y, r):
    _need(tag, y)
    s, after = before_after(tag, y, r)
    capcost.capcost(s, r, "G", n)
    # EBILDN is the BILDIN record read back from a direct-access file (GETBLD): not reproducible
    assert_matches(s, after, tol=1e-6, skip=("ebildn",))


@pytest.mark.parametrize("r", REGIONS)
@pytest.mark.parametrize("y", REGION_YEARS, ids=ids)
def test_capcost_first_iteration(y, r):
    """The first-iteration branch is not dumped (the oracle's CAPCOST dump is the final
    iteration), but the final iteration's state holds its results: ESRTLT/ESRTCE/ESRTST
    of N=1 and the risk-free rate and CAPM cost of equity are what the macro rates give."""
    _need("y_cap2", y)
    s, after = before_after("y_cap2", y, r)
    s["curitr"] = np.int32(1)
    capcost.capcost(s, r, "G", 2)
    want = {k: after[k] for k in ("intrfrt", "introeu", "intbeta", "esrtlt", "esrtce", "esrtst")}
    worst = {k: rel_err(getattr(s[k], "a", s[k]), getattr(v, "a", v)) for k, v in want.items()}
    assert max(worst.values()) < 1e-6, worst


@pytest.mark.parametrize("r", REGIONS)
@pytest.mark.parametrize("y", REGION_YEARS, ids=ids)
def test_allfac(y, r):
    _need("y_alf", y)
    s, after = before_after("y_alf", y, r)
    capcost.allfac(s, r)
    assert_matches(s, after, tol=1e-6)


@pytest.mark.parametrize("r", REGIONS)
@pytest.mark.parametrize("y", REGION_YEARS, ids=ids)
def test_anewbld(y, r):
    _need("y_anb", y)
    s, after = before_after("y_anb", y, r)
    runs = y + UHBSYR > EFPSYR
    if runs:
        capcost.anewbld(s, r)
    assert_matches(s, after, tol=1e-6)
    # the build file is not dumped: check the record this call must have written
    recs = s.get("_efpbld", {})
    assert len(recs) == (1 if runs else 0)
    for rec in recs.values():
        assert rec["ptyp"] == capcost.EIMISC and rec["syr"] == y and rec["pcst"] == 0 and rec["serp"] == 1


@pytest.mark.parametrize("r", REGIONS)
@pytest.mark.parametrize("y", REGION_YEARS, ids=ids)
@pytest.mark.parametrize("tag,routine,ptyp", [("y_tran", "eltran", capcost.EITRAN), ("y_dist", "eldist", capcost.EIDIST)])
def test_tran_dist(tag, routine, ptyp, y, r):
    _need(tag, y)
    s, after = before_after(tag, y, r)
    runs = y + UHBSYR >= EFPSYR
    if runs:
        getattr(capcost, routine)(s, r)
    assert_matches(s, after, tol=1e-6)
    recs = s.get("_efpbld", {})
    for rec in recs.values():
        assert rec["ptyp"] == ptyp and rec["serp"] == 1 and rec["pcst"] != 0
        assert rec["pcap"] == [s["estshr"][1], s["estshr"][2]]
    if not runs:
        assert not recs
