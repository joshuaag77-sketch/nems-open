"""EFP nuclear decommissioning, phase-in and sale/leaseback ports
(src/nems_open/emm/efp/phasein.py) against the oracle."""

import numpy as np
import pytest

from emm_oracle import REGION_YEARS, REGIONS, assert_matches, available, before_after
from nems_open import oracle_state
from nems_open.emm.efp import phasein
from nems_open.fortran_array import FArray

ids = lambda y: str(1989 + y)  # noqa: E731

# COMMON /EFPND/ is dumped with every real array and scalar typed as a scalar INTEGER (the
# oracle's declaration parser trips on "REAL *4"), but the .bin files hold all the data.
# Rebuild those entries from the raw files: name -> shape (None = scalar), all REAL*4.
EFPND_REAL = {"ndtaxr": 50, "nestesc": 50, "ndadmnr": None, "ndearnr": None, "ndtcmon": None,
              "ndpser": 3, "ndpscu": 3, "nucap": 120, "nuppr": 120, "ndest": 120, "ndcbal": 120,
              "ndcapmt": 120}


def _fix_efpnd(d, tag, y, r):
    folder = oracle_state.state_dir("emm") / tag / str(y)
    for name, n in EFPND_REAL.items():
        if name not in d:
            continue
        raw = np.fromfile(folder / f"{name}_r{r:02d}.bin", dtype=np.float32)
        d[name] = raw[0] if n is None else FArray(raw.copy())
    return d


def _skip_unless(tag, y):
    if not available(f"{tag}_in", y) or not available(f"{tag}_out", y):
        pytest.skip(f"EMM oracle state for {tag} not dumped for {y}")


@pytest.mark.parametrize("r", REGIONS)
@pytest.mark.parametrize("y", REGION_YEARS, ids=ids)
def test_elnd(y, r):
    _skip_unless("x_nd", y)
    s, after = before_after("x_nd", y, r)
    _fix_efpnd(s, "x_nd_in", y, r)
    _fix_efpnd(after, "x_nd_out", y, r)
    phasein.elnd(s, r, 6, "G")
    assert_matches(s, after, tol=1e-6)


@pytest.mark.parametrize("r", REGIONS)
@pytest.mark.parametrize("y", REGION_YEARS, ids=ids)
def test_elphin(y, r):
    _skip_unless("x_phin", y)
    s, after = before_after("x_phin", y, r)
    phasein.elphin(s, r)
    assert_matches(s, after, tol=1e-6)


@pytest.mark.parametrize("r", REGIONS)
@pytest.mark.parametrize("y", REGION_YEARS, ids=ids)
def test_elsl(y, r):
    _skip_unless("x_sl", y)
    s, after = before_after("x_sl", y, r)
    phasein.elsl(s, r)
    assert_matches(s, after, tol=1e-6)
