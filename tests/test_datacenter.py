"""The data center load cases: the arithmetic from sources to TWh, and flat and flexible load in the LP."""

from dataclasses import replace

import numpy as np
import pytest

from nems_open import datacenter as dc
from nems_open.supply_standin.data import FIRST_YEAR, available


def at(a, year):
    return a[year - FIRST_YEAR]


def test_every_case_cites_sources_that_exist():
    for key, case in dc.SOURCE["cases"].items():
        assert case["sources"], key
        for s in case["sources"]:
            assert s in dc.SOURCE["sources"], (key, s)
        for a in case.get("anchors", []):
            assert a["source"] in case["sources"], (key, a)
    for key, s in dc.SOURCE["sources"].items():
        assert s["url"].startswith("https://") and s["findings"], key


pytestmark_restart = pytest.mark.skipif(not available("cb2026"), reason="EIA's restart file missing")


@pytestmark_restart
def test_eia_scaled_to_lbnl_scope():
    e = dc.eia_path_twh()
    assert at(e, 2023) == pytest.approx(176.0)
    # EIA's own growth, on LBNL's scope, lands at LBNL's low end for 2028 (325 TWh)
    assert at(e, 2028) == pytest.approx(325.0, rel=0.02)


@pytestmark_restart
def test_anchors_are_hit():
    start = at(dc.eia_path_twh(), 2025)
    assert at(dc.case_path_twh("utility"), 2030) == pytest.approx(start + float(dc.gw_to_twh(90)))
    high = dc.case_path_twh("ai_high")
    assert at(high, 2028) == pytest.approx(start + float(dc.gw_to_twh(50)))
    assert at(high, 2035) == pytest.approx(float(dc.gw_to_twh(194)))
    assert np.array_equal(dc.case_path_twh("ai_high_flex"), high)


@pytestmark_restart
def test_added_load_is_held_after_the_last_anchor_and_splits_fully():
    add = dc.added_load("utility")
    assert at(add.twh, 2040) == pytest.approx(at(add.twh, 2030))
    assert at(add.twh, 2024) == 0.0
    assert add.shares.sum() == pytest.approx(1.0) and (add.shares >= 0).all()
    assert add.tbtu(2030 - FIRST_YEAR).sum() == pytest.approx(at(add.twh, 2030) * dc.TBTU_PER_TWH)
    assert dc.added_load("reference") is None
    assert dc.added_load("ai_high_flex").flex_share == dc.SOURCE["sources"]["duke_2025"]["findings"]["curtailment_share"]["value"]


@pytestmark_restart
def test_lp_flat_and_flexible_load():
    from nems_open.emm import dispatch
    from nems_open.snapshot import Snapshot
    case = dispatch.reduce_hours(dispatch.build_case(Snapshot(), 2035, "none"), 3)
    extra = np.full(25, 40.0)           # TWh, a large flat load in every region
    loaded = replace(case, net_load_twh=case.net_load_twh + extra, flat_twh=extra)
    a = dispatch.solve(loaded)
    b = dispatch.solve(replace(loaded, flex_share=0.005))
    # flexible load stays within its budget, and cannot make the system more expensive
    assert b.curtailed_twh.sum() <= extra.sum() * 0.005 + 1e-6
    assert b.curtailed_twh.sum() > 0
    assert (a.curtailed_twh == 0).all()
    assert b.unserved_twh.sum() <= a.unserved_twh.sum() + 1e-6
    # the same energy with no flat part is the same total, just shaped by the region's load
    c = dispatch.solve(replace(case, net_load_twh=case.net_load_twh + extra))
    assert a.total_generation_twh() == pytest.approx(c.total_generation_twh(), rel=0.01)
