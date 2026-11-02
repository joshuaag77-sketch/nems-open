"""System inputs and the one-call loader."""

import numpy as np
import pytest

from nems_open.emm import inputs, system
from nems_open.paths import INPUT

pytestmark = pytest.mark.skipif(not (INPUT / "emm" / "emm_db" / "NEMS_INPUT.db").exists(), reason="EMM inputs missing")


def test_transmission_links():
    t = system.transmission()
    assert t["ac_cost"].shape == (25, 25)
    assert (t["ac_cost"] > 0).sum() == 72
    assert np.trace(t["ac_cost"]) == 0


def test_annual_controls():
    c = system.annual_controls()
    assert c["nuclear_derate"].shape == (28, 61)
    row = c["nuclear_derate"][0]
    assert np.nanmin(row) > 0.5 and np.nanmax(row) <= 1.0 + 1e-9
    assert not np.isnan(c["hydro_factor"][:25, 2020 - 1990]).any()


def test_canadian_supply_and_fuel_hookup():
    s = system.canadian_supply()
    assert len(s["region"]) == 610 and s["year"].min() == 1990
    assert system.fuel_hookup_cost().shape[0] == 25


def test_load_everything():
    emm = inputs.load()
    assert len(emm.regions) == 28 and len(emm.units) == 27337
    assert emm.shapes.shape == (25, 12, 3, 24)
    assert emm.existing_gw(2024)[27] > 1000       # GW of US capacity in 2024
