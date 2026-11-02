"""FUELCN, RSBENCH, NEMSCN, RESDRP and EXCONS ports vs the residential oracle's state."""

import pytest

from nems_open import oracle_state
from resd_oracle import YEARS, assert_matches, before_after, skip_unless_dumped
from nems_open.residential.totals import excons, fuelcn, nemscn, resdrp, rsbench

LATER = [y for y in YEARS if y > 31]  # yearly tags have no 2020 dump
BASE = [31]


def skip_unless_base(tag):
    """Base-year tags only have the 2020 (index 31) dump."""
    return pytest.mark.skipif(not oracle_state.available(f"{tag}_out", 31, "resd"),
                              reason=f"residential oracle state for {tag} not dumped")


def _check(tag, fn, y, tol=1e-6):
    state, after = before_after(tag, y)
    fn(state)
    # the text class-name table loads as bytes, which the shared float compare cannot take
    return assert_matches(state, after, tol=tol, skip=("rtclname",))


@skip_unless_dumped("fu")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_fuelcn(y):
    _check("fu", fuelcn, y)


@skip_unless_dumped("be")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_rsbench_yearly(y):
    _check("be", rsbench, y)


@skip_unless_base("bb")
@pytest.mark.parametrize("y", BASE, ids=lambda y: str(1989 + y))
def test_rsbench_base(y):
    _check("bb", rsbench, y)


@skip_unless_dumped("ne")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_nemscn_yearly(y):
    _check("ne", nemscn, y)


@skip_unless_base("nb")
@pytest.mark.parametrize("y", BASE, ids=lambda y: str(1989 + y))
def test_nemscn_base(y):
    _check("nb", nemscn, y)


@skip_unless_dumped("re")
@pytest.mark.parametrize("y", LATER, ids=lambda y: str(1989 + y))
def test_resdrp_yearly(y):
    _check("re", resdrp, y)


@skip_unless_base("rb")
@pytest.mark.parametrize("y", BASE, ids=lambda y: str(1989 + y))
def test_resdrp_base(y):
    _check("rb", resdrp, y)


@skip_unless_base("ex")
@pytest.mark.parametrize("y", BASE, ids=lambda y: str(1989 + y))
def test_excons(y):
    _check("ex", excons, y)
