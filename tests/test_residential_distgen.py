"""RDISTGEN port vs the residential oracle's state (tag "dg", the yearly call).

The dumps hold neither PELRSOUT nor the ZIP model's carried state, so the test
supplies stand-ins:
  * PELRSOUT(R, year, 2) is rebuilt from the electricity row of PRICES in the cooling
    routine's dump (exact for a dumped year, because cooling's own price is written
    there) and, for years that were not dumped, from the two-decimal table RDM_OUT.TXT
    prints. The port needs those earlier years only to replay the ZIP model's lags.
  * The ZIP state itself is rebuilt inside the port by replaying the model.
If a dump ever carries "pelrsout", the test uses it instead and the tolerance tightens.

The oracle's "in" state is the second NEMS iteration, which already holds this
year's answers. To prove the port recomputes them, the test poisons the outputs
that EIA assigns (not accumulates) before running.
"""

import re

import numpy as np
import pytest

from resd_oracle import YEARS, assert_matches, before_after, skip_unless_dumped
from nems_open import oracle_state
from nems_open.fortran_array import FArray
from nems_open.paths import REPO_ROOT
from nems_open.residential.common import BASEYR
from nems_open.residential.distgen import rdistgen

LATER = [y for y in YEARS if y > 31]  # the yearly call starts the year after RECS

_TABLE = {}


def _printed_cooling_prices():
    """{calendar year: [9 divisions]} of PELRSOUT end use 2 as RDM_OUT.TXT prints it."""
    if not _TABLE:
        lines = (REPO_ROOT / "oracle" / "run_resd" / "RDM_OUT.TXT").read_text(encoding="latin-1").split("\n")
        for i, ln in enumerate(lines):
            if re.match(r" EU=\s+2 ", ln):
                for ln2 in lines[i + 1:i + 32]:
                    p = ln2.split()
                    _TABLE[int(p[0])] = [float(x) for x in p[1:]]
                break
    return _TABLE


def _exact_cooling_price(y):
    """PELRSOUT(1:9, y, 2) from PRICES(4,.,year) in the cooling dump of that year, nudged
    by ulps until the Fortran product reproduces the dumped price."""
    st = oracle_state.load("clt_out", y, "resd")
    gdp = st["mc_jpgdp"]
    ratio = gdp[int(st["rtekdollaryr"]) - BASEYR + 1] / gdp[-2]
    out = []
    for r in range(1, 10):
        target = st["prices"][4, r, y + BASEYR - 1]
        v = np.float32(target / ratio)
        for _ in range(4):
            if np.float32(v * ratio) == target:
                break
            v = np.nextafter(v, np.float32(np.inf) if np.float32(v * ratio) < target else np.float32(-np.inf))
        out.append(v)
    return out


def _with_pelrsout(state, y):
    """Fill state["pelrsout"] (1:11, 1:61, 1:10). Returns True when every year used
    came from a dump (so the price history is exact)."""
    if "pelrsout" in state:
        return True
    p = FArray.zeros([(1, 11), (1, 61), (1, 10)])
    table = _printed_cooling_prices()
    for yy, row in table.items():
        for r in range(1, 10):
            p[r, yy - BASEYR + 1, 2] = np.float32(row[r - 1])
    exact = True
    for yy in range(32, y + 1):
        if yy in YEARS and oracle_state.available("clt_out", yy, "resd"):
            for r, v in enumerate(_exact_cooling_price(yy), 1):
                p[r, yy, 2] = v
        else:
            exact = False
    state["pelrsout"] = p
    return exact


def _poison(state, y):
    """NaN into this year's outputs that RDISTGEN assigns rather than adds to."""
    for nm in ("units", "cap", "trills", "gasusage", "hwbtu", "invest", "x111drensub"):
        state[nm][y, 1:9, 1:3] = np.nan
    state["trillsownuse"][y, 1:9, 1:3] = np.nan
    for nm in ("cgresgen", "cgresq", "cgrescap"):
        a = state[nm].a
        a[0:9, y - 1, ...] = np.nan  # divisions 1-9 of this year (zero-based year axis)
    for nm in ("rfuelcell_mw", "rpv_mw", "rwind_mw", "rmicrotur_mw"):
        state[nm][y] = np.nan


@skip_unless_dumped("dg")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rdistgen(y):
    state, after = before_after("dg", y)
    exact = _with_pelrsout(state, y)
    _poison(state, y)
    rdistgen(state)
    worst = assert_matches(state, after, tol=1e-6 if exact else 1e-4)
    # the poison must all be gone
    for k in ("units", "cap", "trills", "invest"):
        assert not np.isnan(state[k].a).any(), k
    assert worst  # at least one array compared
