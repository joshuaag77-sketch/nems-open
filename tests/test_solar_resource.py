"""renew.f's solar land classes (emm/solar_resource.py) against the reference run. No solves."""

import numpy as np
import pytest

from nems_open.emm import capacity, plants, solar_resource as sr
from nems_open.paths import INPUT, REFERENCE_RUN
from nems_open.snapshot import Snapshot

pytestmark = pytest.mark.skipif(
    not ((INPUT / "emm" / "emm_db" / "NEMS_INPUT.db").exists() and REFERENCE_RUN.exists()), reason="EMM inputs missing")


@pytest.fixture(scope="module")
def snapshot():
    return Snapshot()


def test_reproduces_wcapvel_along_eias_path(snapshot):
    ours = sr.deplete(*sr.reference_path(snapshot), 2050)["bound"][:, 37:]
    eia = snapshot["WRENEW/wcapvel"][:25, 37:61].astype(float)
    assert np.allclose(ours, eia, rtol=5e-5, atol=2.0)    # MW, 25 regions, 2027-2050; REAL*4 drift


def test_cost_multiplier_moves_eias_pv_cost(snapshot):
    """UPPVCCST of each year over 2031's is the multiplier's ratio times one national learning factor."""
    c = snapshot["UECPOUT/uppvccst"][:25].astype(float)
    lt = sr.deplete(*sr.reference_path(snapshot), 2048)["cost"]
    for year in (2036, 2040, 2045, 2050):
        y = year - 1990
        assert np.ptp((c[:, y] / c[:, 41]) / (lt[:, y - 2] / lt[:, 39])) < 0.002, year


def test_own_builds_deplete(snapshot):
    """10 GW more PV in PJMW leaves its first class short and costs more; no other region moves."""
    inst, com = sr.reference_path(snapshot)
    gw = {y: sum(inst[t][:, y - 1990] for t in sr.TECHS) / 1000.0 for y in range(2027, 2031)}
    builds = {y: com["pv"][:, y - 1990] / 1000.0 for y in range(2027, 2031)}
    base = sr.for_build_year(snapshot, 2032, 2027, gw, builds)
    more_gw = {y: v + 10.0 * np.eye(25)[10] * (y >= 2029) for y, v in gw.items()}
    more = sr.for_build_year(snapshot, 2032, 2027, more_gw, builds)
    assert np.allclose(base["cost"], 1.0, atol=1e-6) and np.allclose(base["cf"], 1.0, atol=1e-3)
    assert more["bound"][10] < base["bound"][10] - 9.0 and more["cost"][10] > 1.0
    assert np.allclose(np.delete(more["bound"], 10), np.delete(base["bound"], 10))


def test_path_passes_both_resources(snapshot):
    path = capacity.CapacityPath(snapshot, 2027)
    res = path.resources(2027)
    assert set(res) == {"wind", "solar"}
    assert np.allclose(res["solar"]["cost"], 1.0) and res["solar"]["bound"].shape == (25,)
    pv = path.cap["solar"] - sum(plants.capacity_gw(2026, t)[:25] for t in sr.FILE_TYPES.values())
    assert np.allclose(pv, sr.reference_path(snapshot)[0]["pv"][:, 36] / 1000.0, atol=0.2)
