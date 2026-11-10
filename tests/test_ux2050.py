"""The data behind web/2050.html: the plant extract and the emulator (scripts/build_ux2050.py)."""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "web" / "data" / "ux2050"
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture(scope="module")
def emu():
    return json.loads((DATA / "emulator.json").read_text())


@pytest.fixture(scope="module")
def plants():
    return json.loads((DATA / "plants.json").read_text())


def poly(emu, x):
    names = list(emu["levers"])
    z = [2 * (x[n] - emu["levers"][n]["low"]) / (emu["levers"][n]["high"] - emu["levers"][n]["low"]) - 1 for n in names]
    f = np.array([np.prod([z[i] for i in t]) if t else 1.0 for t in emu["terms"]])
    return {k: f @ np.array(c) for k, c in emu["coef"].items()}


def emulate(emu, x):
    """What the page computes (ux2050.js emulate): the polynomial, anchored on the reference run."""
    off = {n: L["off"] for n, L in emu["levers"].items()}
    raw, ref = poly(emu, {**off, **x}), poly(emu, off)
    return {k: raw[k] - ref[k] + np.array(emu["fast_reference"][k]) for k in raw}


def test_plants_are_eias_plant_file(plants):
    assert plants["units_in_file"] == 27337
    assert plants["drawn"] == len(plants["rows"]) > 27000
    assert plants["drawn"] + sum(plants["not_drawn"].values()) == plants["units_in_file"]
    rows = np.array(plants["rows"])
    assert rows[:, 0].max() < -60 and rows[:, 1].min() > 20         # lower 48, west longitudes
    assert set(rows[:, 4].astype(int)) == set(range(1, 26))           # all 25 EMM regions
    assert len(plants["regions"]) == 25


def test_emulator_is_exact_at_eias_settings(emu):
    out = emulate(emu, {})
    for k, v in out.items():
        np.testing.assert_allclose(v, emu["fast_reference"][k], atol=1e-6)


def test_fast_reference_is_eias_reference(emu):
    """With no levers the fast loop returns EIA's AEO2026 reference, so "vs EIA" at the reference is zero."""
    for k in ("co2", "bill", "price_electricity", "price_gasoline", "elec_sales_twh"):
        np.testing.assert_allclose(emu["fast_reference"][k], emu["eia"][k], rtol=2e-3)


def test_emulator_moves_the_right_way(emu):
    years = emu["years"]
    j = years.index(2050)
    ref = emulate(emu, {})
    assert emulate(emu, {"carbon_price": 150})["co2"][j] < ref["co2"][j]
    assert emulate(emu, {"load_growth": 800})["elec_sales_twh"][j] > ref["elec_sales_twh"][j] + 500
    assert emulate(emu, {"oil_price": 1.8})["price_gasoline"][j] > ref["price_gasoline"][j]
    assert emulate(emu, {"ev_2035": 1.0})["flow_petroleum_tr"][j] < ref["flow_petroleum_tr"][j]


def test_every_output_has_a_measured_error(emu):
    assert emu["held_out"] >= 20
    assert set(emu["error"]) == set(emu["coef"]) == set(emu["eia"])


def test_server_clamps_levers():
    import serve_2050
    x = serve_2050.clean({"carbon_price": 9999, "nuclear": -3, "bogus": 1, "ev_2035": None})
    assert x == {"carbon_price": 500.0, "nuclear": 0.0}
