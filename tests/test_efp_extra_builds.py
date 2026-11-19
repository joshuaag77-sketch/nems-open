"""The capacity LP's builds beyond EIA's reach EFP's books as ECP's UEXPBLD books them; equal builds book nothing."""
from types import SimpleNamespace

import numpy as np
import pytest


@pytest.fixture(scope="module")
def snap():
    from nems_open.snapshot import Snapshot
    try:
        return Snapshot()
    except Exception:
        pytest.skip("no cb2026 restart here")


def _eia_adds(snap, prefixes, year):
    y, out = year - 1990, np.zeros(25)
    for p in prefixes:
        sign = -1.0 if p.startswith("-") else 1.0
        for o in ("u", "n"):
            k = f"UECPOUT/uadd{p.lstrip('-')}{o}"
            try:
                a = np.asarray(snap[k], dtype=float)
            except KeyError:
                continue
            out += sign * (a[:, :25, y].sum(0) - a[:, :25, y - 1].sum(0))
    return out


def _efp(snap):
    from nems_open.emm.retail import EfpPrices
    e = object.__new__(EfpPrices)
    e.snap = snap
    return e


def test_eias_own_additions_book_nothing(snap):
    from nems_open.emm.retail import EfpPrices
    year, adds = 2033, {}
    for groups, prefixes, _, _ in EfpPrices.BUILD_TYPES.values():
        adds[groups[0]] = _eia_adds(snap, prefixes, year)
    res = SimpleNamespace(planned_adds=adds, builds={})
    assert _efp(snap).extra_builds(year, res) == {}


def test_extra_wind_is_booked_at_its_cost(snap):
    from nems_open.emm.retail import EfpPrices
    year, adds = 2033, {}
    for groups, prefixes, _, _ in EfpPrices.BUILD_TYPES.values():
        adds[groups[0]] = _eia_adds(snap, prefixes, year)
    extra = np.zeros(25)
    extra[16] = 2.0                                   # 2 GW more wind in region 17
    res = SimpleNamespace(planned_adds=adds, builds={"wind": extra})
    out = _efp(snap).extra_builds(year, res)
    assert list(out) == [17]
    (ptyp, syr, cost, gw), = out[17]
    assert (ptyp, syr) == (4, year - 1989) and gw == pytest.approx(2.0) and cost > 0


def test_book_extra_writes_an_uexpbld_record():
    from nems_open.emm.efp import elefp
    s = {}
    elefp._book_extra(s, 17, 4, 44, 800.0, 2.0)
    rec = s["_efpbld"][1]
    assert (rec["ptyp"], rec["syr"], rec["serp"]) == (4, 44, 1.0)
    assert rec["pcst"] == pytest.approx(800.0) and rec["pcap"][0] == pytest.approx(2.0) and rec["pcap"][1] == 0.0
