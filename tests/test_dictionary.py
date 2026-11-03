"""EIA's variable dictionary against the cb2026 restart file."""

import pytest

from nems_open import dictionary
from nems_open.paths import INPUT, REFERENCE_RUN
from nems_open.snapshot import Snapshot

pytestmark = pytest.mark.skipif(not ((INPUT / "dict.txt").exists() and REFERENCE_RUN.exists()), reason="EIA checkout missing")


def test_parses_the_dictionary():
    v = dictionary.variables()
    assert len(v) == 4405 and dictionary.sizes()["MNUMYR"] == 61 and dictionary.sizes()["MNUMCR"] == 11
    q = dictionary.lookup("QBLK", "QCLEL")
    assert q.dims == ("MNUMCR", "MNUMYR") and q.units == "tBTU" and dictionary.shape(q) == (11, 61)
    assert dictionary.lookup("USO2GRP", "XCL_1TESC").dims == ("MX_NCL", "ECPFPH", "MNUMYR", "NDREGN")


def test_shapes_match_the_restart_file():
    """Every restart array has its dictionary shape, bar a few known oddities (scalars stored as (), character
    arrays with a string-length axis, and 16 variables whose declarations disagree with the file)."""
    s = Snapshot()
    v = dictionary.variables()
    bad = []
    for key in s._npz.files:
        var = v.get(key.lower())
        if var is None:
            continue
        want, got = dictionary.shape(var), tuple(s._npz[key].shape)
        if want == got or (want == (1,) and got == ()) or (var.type == "C" and got[: len(want)] == want):
            continue
        if var.type == "C" and len(got) == len(want) + 1:
            continue
        bad.append(key)
    assert len(bad) <= 16, bad[:20]
