"""Reduced coal distribution LP against the cb2026 restart."""

import numpy as np
import pytest

from nems_open.coal import lp, lp_report, state, supply
from nems_open.paths import REFERENCE_RUN

pytestmark = pytest.mark.skipif(not (REFERENCE_RUN.exists() and state.COAL_AMS.exists()), reason="EIA checkout missing")


def test_demands_match_restart_totals():
    d = lp.demands(2030)
    assert abs(d.elec.sum() - lp.Macro().s["COALEMM/qclclnr"][:, 2030 - 1990, :].sum()) < 1e-6
    assert (d.exports >= 0).all() and d.exports.sum() > 0


def test_base_year_lp_is_optimal_and_meets_demand():
    ch = supply.Chain()
    step = supply.base_year(ch.c)
    step["cap"] = ch.c.v["prod_cap"]
    dem = lp.demands(2024)
    r = lp.solve(2024, step, ch.c.v["btu"], ch.keys, dem)
    assert r["status"] == "ok"
    x = r["shipments"]
    assert abs(x.xs("E", level="sec").sum() - dem.elec.sum()) < 1e-2
    assert abs(r["production_tbtu"].sum() - (x.sum() + r["exports"].sum())) < 1e-2
    assert all(v > 0 for v in r["dual"].values())


def test_national_production_tracks_the_restart_after_the_steo_years():
    rows = {r["year"]: r for r in lp_report.run([2030])}
    r = rows[2030]
    assert r["status"] == "ok"
    assert abs(r["prod_mt"].sum() / r["ref_mt"].sum() - 1) < 0.05
    assert abs(r["PCLEL"][0] / r["PCLEL"][1] - 1) < 0.10
