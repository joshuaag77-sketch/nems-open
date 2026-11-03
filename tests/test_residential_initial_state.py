"""RESD's starting state built from files, against the oracle.

1. Each array the first-call readers fill equals its first appearance in the oracle's dumps
   (2020, then 2021), except six the 2020 calls go on to fill for 2021 and later.
2. The RECS-year calls (2020) from that state give what the oracle's base-year routines leave.
3. 2021 to 2050 run from files alone give the oracle's residential fuel use.
"""

import numpy as np
import pytest
from nems_open import oracle_state
from nems_open.fortran_array import FArray
from nems_open.residential import initial_state as ini, inputs as readers, resd
from nems_open.run_demand import Inputs

pytestmark = pytest.mark.skipif(not oracle_state.available("yb_in", 32, "resd"),
                                reason="residential oracle state not dumped")

# Read on the first call, but the oracle first dumps them in 2021, after RESD's 2020 calls
# filled their 2021-and-later cells (the readers leave those zero).
FILLED_IN_2020 = {"eaeqp", "ecshell", "ehshell", "hotwatq", "oldhses", "rtbaseff"}


@pytest.fixture(scope="module")
def inputs():
    return Inputs()


@pytest.fixture(scope="module")
def read(inputs):
    """(state after the readers, names the readers changed)."""
    s = ini.zeros()
    ini.restart_arrays(s, inputs)
    before = {k: (v.a.copy() if isinstance(v, FArray) else v) for k, v in s.items()}
    readers.first_call(s, inputs)
    changed = [k for k, v in s.items() if isinstance(v, FArray) and not np.array_equal(v.a, before[k])]
    return s, changed


def _first_dump(name):
    root = oracle_state.state_dir("resd")
    tags = [(31, t) for t in ("pr_in", "ex_in", "bb_in", "nb_in", "rb_in")]
    tags += [(32, "pr_in"), (32, "yb_in")] + [(32, p.name) for p in sorted(root.iterdir()) if p.name.endswith("_in")]
    for y, t in tags:
        if oracle_state.available(t, y, "resd"):
            d = oracle_state.load(t, y, "resd")
            if name in d:
                return d[name]
    return None


def _same(a, b):
    a, b = a.a, b.a
    if a.dtype.kind in "SU" or b.dtype.kind in "SU":
        return a.shape == b.shape and bool((np.char.rstrip(a.astype("S")) == np.char.rstrip(b.astype("S"))).all())
    return a.shape == b.shape and bool(np.allclose(a.astype(float), b.astype(float), rtol=1e-6, atol=1e-9))


def test_readers_match_first_dump(read):
    s, changed = read
    assert len(changed) > 200
    bad = [k for k in changed if k not in FILLED_IN_2020 and (ref := _first_dump(k)) is not None and not _same(s[k], ref)]
    assert not bad


@pytest.fixture(scope="module")
def base(inputs):
    return resd.start_from_files(inputs)


@pytest.mark.parametrize("tag", ["bb_out", "nb_out", "rb_out"])  # ex_out is overwritten by RSBENCH later in 2020
def test_base_year_matches_oracle(base, tag):
    bad = {}
    for k, v in oracle_state.load(tag, 31, "resd").items():
        if isinstance(v, FArray) and v.a.dtype.kind == "f":
            a, b = base[k].a.astype(float), v.a.astype(float)
            e = float((np.abs(a - b) / np.maximum(np.abs(b), 1e-6)).max(initial=0))
            if e > 1e-5:
                bad[k] = e
    assert not bad


def test_2021_to_2050_from_files_matches_oracle(base):
    s = {k: (v.copy() if isinstance(v, FArray) else v) for k, v in base.items() if k != "_dg"}
    resd.run(s, 2021, 2050)
    final = oracle_state.load("final", 61, "resd")
    for q in ("qelrs", "qngrs", "qdsrs", "qlgrs", "qbmrs", "qpvrs"):
        mine, eia = s[q].a[:9, 30:].astype(float), final[q].a[:9, 30:].astype(float)
        assert np.abs(mine - eia).max() <= 1e-6 * np.abs(eia).max(), q
