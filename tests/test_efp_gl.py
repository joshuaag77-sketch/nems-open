"""EFP routine GL (src/nems_open/emm/efp/gl.py) against the oracle, per component and region."""

import functools

import numpy as np
import pytest

from emm_oracle import REGION_YEARS, REGIONS, assert_matches, available, before_after
from nems_open import oracle_state
from nems_open.emm.efp import gl

ids = lambda y: str(1989 + y)  # noqa: E731


@functools.lru_cache(maxsize=None)
def _fs_out(y):
    return oracle_state.load("fs_out", y, "emm")


# BILDIN fields the file record holds at a later value than fs_out (the ECP's financial
# parameters, updated after EFD). GETBLD reads the file; its record is not in any dump, so these
# come from the state just before GL, which already holds the region's record.
FILE_RECORD = ("epdscrt", "eputdscrt", "epuror", "epuirt", "epufpe", "epucre", "epurorr", "epuirtr",
               "epufper", "epucrer")


def region_block(y, r, s):
    """The region's DISPOUT and BILDIN blocks as the dispatch model left them (fs_out), plain names."""
    suf = f"_r{r:02d}"
    d = _fs_out(y)
    block = {k[: -len(suf)]: v for k, v in d.items() if k.endswith(suf)}
    block.update({k: s[k] for k in FILE_RECORD})
    return block


@pytest.mark.parametrize("r", REGIONS)
@pytest.mark.parametrize("y", REGION_YEARS, ids=ids)
@pytest.mark.parametrize("tag,icall", [("gg", "G"), ("gt", "T"), ("gd", "D")])
def test_gl(tag, icall, y, r):
    if not (available(f"{tag}_in", y) and available(f"{tag}_out", y) and available("fs_out", y)):
        pytest.skip(f"EMM oracle state for {tag} / fs_out not dumped for {ids(y)}")
    s, after = before_after(tag, y, r)
    gl.gl(s, r, icall, region_block(y, r, s))
    # CHARACTER scalars (the OUTR* record buffers) are not floats: compare them as bytes,
    # without the trailing NULs the dump drops
    strs = tuple(k for k, v in after.items() if isinstance(v, bytes))
    for k in strs:
        assert bytes(s[k]).rstrip(bytes(1)) == bytes(after[k]).rstrip(bytes(1)), k
    # NUCPCT holds NaN and inf (0/0, x/0) that GL does not touch; the shared check cannot compare inf
    assert np.array_equal(s["nucpct"].a, after["nucpct"].a, equal_nan=True)
    worst = assert_matches(s, after, tol=1e-6, skip=strs + ("nucpct",))
    print(f"GL {icall} {ids(y)} region {r}: worst relative error {max(worst.values()):.3g}")
