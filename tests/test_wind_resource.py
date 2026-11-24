"""renew.f's onshore wind resource (emm/wind_resource.py) against the reference run."""

import numpy as np
import pytest

from nems_open.emm import wind_resource as wr
from nems_open.paths import INPUT, REFERENCE_RUN
from nems_open.snapshot import Snapshot

pytestmark = pytest.mark.skipif(
    not ((INPUT / "emm" / "emm_db" / "NEMS_INPUT.db").exists() and REFERENCE_RUN.exists()), reason="EMM inputs missing")


@pytest.fixture(scope="module")
def snapshot():
    return Snapshot()


def _path(snapshot, extra=0.0):
    """EIA's path from 2027, with `extra` GW more committed in SRCE for 2031."""
    inst, com = wr.reference_path(snapshot)
    gw = {y: inst[:, y - 1990] / 1000.0 for y in range(2027, 2032)}
    builds = {y: com[:, y - 1990] / 1000.0 for y in range(2027, 2032)}
    builds[2031] = builds[2031] + extra * np.eye(25)[15]
    return gw, builds


def test_reproduces_wcawiel_along_eias_path(snapshot):
    ours = wr.deplete(*wr.reference_path(snapshot), wr.fom_ratio(snapshot), 2050)["bound"][:, 37:]
    eia = snapshot["WRENEW/wcawiel"][:25, 37:61].astype(float)
    assert np.allclose(ours, eia, rtol=0.0, atol=2.0)                     # MW, 25 regions, 2027-2050


def test_cost_multiplier_moves_eias_wind_cost(snapshot):
    """UPWNCCST of 2036 over 2031 is the multiplier's ratio times one national learning factor."""
    c = snapshot["UECPOUT/upwnccst"][:25].astype(float)
    lt = wr.deplete(*wr.reference_path(snapshot), wr.fom_ratio(snapshot), 2034)["cost"]
    learn = (c[:, 46] / c[:, 41]) / (lt[:, 44] / lt[:, 39])
    has = wr.inputs()["max_mw"].sum(axis=1) > 500.0
    assert np.ptp(learn[has]) < 0.01


def test_own_builds_deplete(snapshot):
    """SRCE has 4.784 GW left along EIA's path to 2031; build it and the next year's bound is 0."""
    base = wr.for_build_year(snapshot, 2032, 2027, *_path(snapshot))
    more = wr.for_build_year(snapshot, 2032, 2027, *_path(snapshot, 4.784))
    assert base["bound"][15] == pytest.approx(4.784, abs=2e-3)
    assert more["bound"][15] == pytest.approx(0.0, abs=2e-3)
    assert np.allclose(base["cost"], 1.0) and np.allclose(base["cf"], 1.0)
    assert np.allclose(np.delete(more["bound"], 15), np.delete(base["bound"], 15))
