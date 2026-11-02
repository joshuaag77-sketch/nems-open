"""Plant type tables."""

import numpy as np
import pytest

from nems_open.emm import plants, regions, technology
from nems_open.paths import INPUT

pytestmark = pytest.mark.skipif(not (INPUT / "emm" / "emm_db" / "NEMS_INPUT.db").exists(), reason="EMM inputs missing")


def test_ecp_codes():
    codes = technology.ecp_codes()
    assert len(codes) == 80 and len(set(codes)) == 80
    assert codes[0] == "B1" and codes[46] == "CC" and codes[75] == "PV"


def test_every_plant_file_type_is_defined():
    efd = {t.code for t in technology.efd_plant_types()}
    assert set(plants.load_units().ecp_type) <= set(technology.ecp_codes())
    assert set(plants.efd_types()) <= efd
    assert len(efd) == 54


def test_type_parameters_shapes_and_sanity():
    p = technology.type_parameters()
    assert p["construction_profile"].shape == (80, 10)
    for k, v in p.items():
        assert v.shape[0] == 80, k
    i = technology.ecp_codes().index("CC")
    assert 6000 < p["heat_rate"][i] or p["heat_rate"][i] == 0           # CC heat rate is set elsewhere
    assert 300 < p["overnight_cost"][i] < 3000
    assert p["overnight_cost"][technology.ecp_codes().index("PV")] < p["overnight_cost"][technology.ecp_codes().index("AN")]
    assert (p["forced_outage_rate"] >= 0).all() and (p["forced_outage_rate"] < 1).all()


def test_regional_costs_and_links():
    rc = technology.regional_costs()
    assert rc["regional_multiplier"].shape == (28, 80)
    assert np.isfinite(rc["regional_multiplier"][:25]).all()
    assert (rc["regional_multiplier"][:25] > 0.3).all() and (rc["regional_multiplier"][:25] < 3).all()
    links = technology.region_links()
    assert all(len(v) == regions.NUM_EMM for v in links.values())


def test_efd_plant_types():
    types = technology.efd_plant_types()
    by = {t.code: t for t in types}
    assert by["CSC"].name.startswith("Coal Steam with Scrubber")
    assert by["CSC"].fuels[0] == "B1" and by["CSC"].max_capacity_factor == pytest.approx(0.65)
    assert 0 < min(t.forced_outage for t in types) and max(t.forced_outage for t in types) < 0.5
