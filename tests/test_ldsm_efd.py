"""LDSM load duration curves for EFD (efd.py) against the oracle."""

import pytest

from emm_oracle import REGION_YEARS, REGIONS, assert_matches, before_after, skip_unless_dumped
from nems_open.emm.ldsm import efd

ids = lambda y: str(1989 + y)  # noqa: E731


@skip_unless_dumped("ef")
@pytest.mark.parametrize("r", REGIONS)
@pytest.mark.parametrize("y", REGION_YEARS, ids=ids)
def test_dsmefd(y, r):
    s, after = before_after("ef", y, r)
    efd.dsmefd(s)
    assert_matches(s, after, tol=1e-6)


def _group_blocks_reference(s, sy2, rnb):
    """_group_blocks as ported first, indexing the Fortran arrays inside the hourly walk."""
    from nems_open.emm.ldsm.common import f32, f64, i
    nsg = i(s, "efdnumsg")
    fh, lh, dnb, blockx = s["efdsgfh"], s["efdsglh"], s["efdsgdnb"], s["efdblockx"]
    weights, hn_efd = s["hourlyweights"], s["hournumberefd"]
    energy, total = {}, f32(0.0)
    blk, bls, area = 1, 1, f32(0.0)
    for sgn in range(nsg, 0, -1):
        l = 0
        for h in range(int(fh[sgn]), int(lh[sgn]) + 1):
            for _ in range(int(weights[int(hn_efd[h])])):
                l += 1
                area = f32(f64(area) + sy2[h])
                if bls != int(dnb[sgn]) and l > blockx[sgn, bls]:
                    dh = f32(f32(l) - blockx[sgn, bls])
                    energy[blk] = f32(f64(area) - f64(dh) * sy2[h])
                    area = f32(f64(dh) * sy2[h])
                    bls += 1
                    total = f32(total + energy[blk])
                    blk += 1
        energy[blk] = area
        total = f32(total + energy[blk])
        blk += 1
        bls = 1
        area = f32(0.0)
    return energy, total


@skip_unless_dumped("ef")
def test_group_blocks_fast_walk_is_bit_identical(monkeypatch):
    """The faster walk (arrays read once) gives the same bits as the first port, on EIA's own state."""
    import numpy as np
    y, r = REGION_YEARS[0], REGIONS[0]
    s_fast, _ = before_after("ef", y, r)
    efd.dsmefd(s_fast)
    s_ref, _ = before_after("ef", y, r)
    monkeypatch.setattr(efd, "_group_blocks", _group_blocks_reference)
    efd.dsmefd(s_ref)
    for k in ("efdblkserv", "toteuload"):
        assert np.array_equal(s_fast[k].a, s_ref[k].a), k
