"""RSHVAC and RHTRTEC ports vs the residential oracle's state.

Two things the oracle dump does not hold are rebuilt here from what it does hold:

* PELRSOUT (equivalenced to PELSHRS, so the dump missed it). RSHVAC and RHTRTEC turn
  it into PRICES(4, R, year) = PELRSOUT * inflation, and the dump keeps that product
  (heating price after RSHVAC, cooling price after RCLTEC). The test recovers the
  float32 PELRSOUT whose product is exactly the dumped price.
* HEATSYS (RHTRTEC's SAVEd lagged logit, carried year to year). See test_rhtrtec.
"""

import numpy as np
import pytest

from resd_oracle import YEARS, assert_matches, before_after, skip_unless_dumped
from nems_open import oracle_state
from nems_open.fortran_array import FArray
from nems_open.residential.common import BASEYR, f32
from nems_open.residential.heating_choice import rhtrtec, rshvac

TEXT = ("rtmature",)  # text array: the shared rel_err helper cannot compare bytes; the port never writes it
LATER = [y for y in YEARS if y > 31]  # yearly routines have no 2020 dump


def _inflation(state):
    gdp = state["mc_jpgdp"]
    return f32(gdp[int(state["rtekdollaryr"]) - BASEYR + 1] / gdp[-2])


def _invert(price, infl):
    """The float32 x with f32(x * infl) == price, nearest first."""
    x = f32(price / infl)
    for step in (0, 1, -1, 2, -2, 3, -3):
        c = x
        for _ in range(abs(step)):
            c = np.nextafter(c, f32(np.inf) if step > 0 else f32(-np.inf), dtype=np.float32)
        if f32(c * infl) == price:
            return c
    return x


def _pelrsout(state, y, heating_prices, cooling_prices=None):
    """PELRSOUT[division, iyr, end use] from the dumped PRICES(4, R, year)."""
    infl = _inflation(state)
    year = int(state["curcalyr"])
    pel = FArray.zeros([(1, 11), (1, 61), (1, 2)])
    for r in range(1, 10):
        pel[r, y, 1] = _invert(heating_prices[4, r, year], infl)
        if cooling_prices is not None:
            pel[r, y, 2] = _invert(cooling_prices[4, r, year], infl)
    return pel


@skip_unless_dumped("hv")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rshvac(y):
    state, after = before_after("hv", y)
    cooling = oracle_state.load("clt_out", y, "resd")["prices"]  # RCLTEC leaves the cooling price in PRICES(4)
    state["pelrsout"] = _pelrsout(state, y, after["prices"], cooling)
    rshvac(state)
    assert_matches(state, after, tol=1e-6, skip=TEXT)


def _copy(state):
    return {k: (v.copy() if isinstance(v, FArray) else v) for k, v in state.items()}


def _fit_heatsys(state, after):
    """Put HEATSYS(year-1) into state, up to one fitted scale per (B, R).

    HSYSSHR(year-1) is HEATSYS(year-1) / its sum, so it fixes HEATSYS(year-1) up to a
    scale S per (B, R). With H = HEATSYS(year) computed from a zero history (the part
    of the logit that does not depend on S), the dumped share t_c of the class with the
    biggest change gives S = (H_c - t_c sum H) / (0.9 (t_c - s_c)). The other nine
    classes are then compared exactly, so this checks the class-to-class pattern of
    HSYSSHR but not its level. Needs year-1 > HTSHRYR, when HSYSSHR(year-1) is itself
    the model's output.
    """
    Y = int(state["curcalyr"])
    probe = _copy(state)
    rhtrtec(probe)
    cleupt = int(state["rtcleupt"][1])
    classes = range(cleupt + 1, int(state["rtcleupt"][2]) + 1)
    heatsys = FArray.zeros([(2020, 2050), (1, 30), (1, 3), (1, 9)])
    for r in range(1, 10):
        for b in range(1, 4):
            h = {c: float(probe["heatsys"][Y, int(state["rtcltypt"][c]), b, r]) for c in classes}
            total = sum(h.values())
            sp = {c: float(state["hsysshr"][Y - 1, int(state["rtcleqcl"][c]), b, r]) for c in classes}
            t = {c: float(after["hsysshr"][Y, int(state["rtcleqcl"][c]), b, r]) for c in classes}
            c = max(classes, key=lambda k: abs(t[k] - sp[k]))
            scale = (h[c] - t[c] * total) / (0.9 * (t[c] - sp[c]))
            for k in classes:
                heatsys[Y - 1, int(state["rtcltypt"][k]), b, r] = f32(sp[k] * scale)
    state["heatsys"] = heatsys


@skip_unless_dumped("htt")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rhtrtec(y):
    """Everything RHTRTEC writes except HSYSSHR matches; HSYSSHR is checked where it
    can be, see below. HEATSYS carries from the year before, which the oracle does not
    dump (blocker: ask for HEATSYS as a carried variable). HSYSSHR only changes after
    HTSHRYR (2024), so 2021 and 2022 need no history."""
    state, after = before_after("htt", y)
    state["pelrsout"] = _pelrsout(state, y, state["prices"])
    year, htshryr = int(state["curcalyr"]), int(state["htshryr"])
    if year - 1 > htshryr:
        _fit_heatsys(state, after)
    rhtrtec(state)
    skip = TEXT + (("hsysshr",) if year == htshryr + 1 else ())
    # the fitted history costs a few digits in the cancellation (share - previous share)
    assert_matches(state, after, tol=1e-4 if year - 1 > htshryr else 1e-6, skip=skip)
