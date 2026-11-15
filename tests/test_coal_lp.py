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
    assert all(np.isfinite(v) and v >= -1e-9 for v in r["dual"].values())


def test_national_production_tracks_the_restart_after_the_steo_years():
    """One electricity demand per region (the earlier reduced LP)."""
    rows = {r["year"]: r for r in lp_report.run([2030], by_type=False)}
    r = rows[2030]
    assert r["status"] == "ok"
    assert abs(r["prod_mt"].sum() / r["ref_mt"].sum() - 1) < 0.05
    assert abs(r["PCLEL"][0] / r["PCLEL"][1] - 1) < 0.10


def test_plant_type_demand_and_diversity_caps():
    """Electricity demand per plant type with EIA's sub-bituminous and lignite caps (electric.py).
    Lignite lands within 3 Mt and national production within 2% every year; Interior's 2025 miss
    falls from 38 Mt to 11. Electric price is about 20% high in 2027-2030 (no SO2 equations yet),
    and 25 to 32% high in the STEO years 2025-2026, so it is held to 35% here; docs/coal_lp.md has the table."""
    rows = {r["year"]: r for r in lp_report.run([2025, 2026, 2027, 2030])}
    for y, r in rows.items():
        assert r["status"] == "ok"
        assert abs(r["prod_mt"].sum() / r["ref_mt"].sum() - 1) < 0.02, y
        assert abs(r["prod_mt"][3] - r["ref_mt"][3]) < 3.0, y            # 4LGN lignite
        assert r["slack"] < 1.0, y                                        # diversity slack, TBtu
        assert abs(r["PCLEL"][0] / r["PCLEL"][1] - 1) < 0.35, y
    assert abs(rows[2025]["prod_mt"][2] - rows[2025]["ref_mt"][2]) < 12   # 3INR
