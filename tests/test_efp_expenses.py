"""EFP expenses, interest expense and revenue requirement (src/nems_open/emm/efp/expenses.py)."""

import pytest

from emm_oracle import REGION_YEARS, REGIONS, assert_matches, available, before_after
from nems_open.emm.efp import expenses

ids = lambda y: str(1989 + y)  # noqa: E731


def _run(tag, y, r, call):
    if not (available(f"{tag}_in", y) and available(f"{tag}_out", y)):
        pytest.skip(f"no {tag} dump for {ids(y)}")
    s, after = before_after(tag, y, r)
    call(s, r)
    assert_matches(s, after, tol=1e-6)


@pytest.mark.parametrize("r", REGIONS)
@pytest.mark.parametrize("y", REGION_YEARS, ids=ids)
def test_elxpns(y, r):
    _run("x_xpns", y, r, lambda s, r: expenses.elxpns(s, r, "G"))


@pytest.mark.parametrize("r", REGIONS)
@pytest.mark.parametrize("y", REGION_YEARS, ids=ids)
def test_elinex(y, r):
    _run("x_inex", y, r, lambda s, r: expenses.elinex(s, r))


@pytest.mark.parametrize("r", REGIONS)
@pytest.mark.parametrize("y", REGION_YEARS, ids=ids)
def test_elrevs(y, r):
    _run("x_revs", y, r, lambda s, r: expenses.elrevs(s, "G", r))
