"""run_model.run(macro="frbus"): the economy module feeding demand. Stub sectors only, so seconds a run."""

import numpy as np
import pytest

from nems_open.demand_adapter import Policy
from nems_open.macro import frbus_core, regional
from nems_open.run_model import run
from nems_open.supply_standin.data import US, available

pytestmark = pytest.mark.skipif(
    not (available() and frbus_core.available() and regional.restart_path("lowogs") is not None),
    reason="needs the AEO2026 runs, pyfrbus and EIA's scenario restart files",
)

Y = slice(2035 - 1990, 2050 - 1990 + 1)


@pytest.fixture(scope="module")
def plain():
    return run(Policy(oil_price=1.4), ported=(), end_year=2040)


@pytest.fixture(scope="module")
def with_macro():
    return run(Policy(oil_price=1.4), ported=(), end_year=2040, macro="frbus")


def test_unknown_macro_switch_is_refused():
    with pytest.raises(ValueError):
        run(ported=(), end_year=2028, macro="other")


def test_baseline_with_macro_reproduces_reference():
    """No lever, no gap: the economy module hands demand the reference economy."""
    a, b = run(ported=(), end_year=2035), run(ported=(), end_year=2035, macro="frbus")
    for k in ("QBLK/qtsin", "QBLK/qtsrs", "QBLK/qtscm"):
        assert np.allclose(a.quantities[k][US, :46], b.quantities[k][US, :46], rtol=2e-3)


def test_high_oil_lowers_industrial_fuel_use_through_output(plain, with_macro):
    """Oil +40% cuts GDP and industrial output, which cuts fuel use further than the price response alone."""
    j = 2040 - 1990
    assert with_macro.quantities["QBLK/qtsin"][US, j] < plain.quantities["QBLK/qtsin"][US, j]


def test_second_cycle_adds_the_energy_bill_channel():
    from nems_open.macro import drive
    from nems_open.supply_standin import SupplyStandin

    base = SupplyStandin("cb2026").base
    oil = base["INTOUT/brent_price"] * 1.4
    first = drive.scenario_macro(base, oil)
    prices = {k: v * 1.2 for k, v in base.items() if k.startswith("MPBLK/")}
    second = drive.scenario_macro(base, oil, prices)
    assert first.channels == "oil" and second.channels == "oil+bill"
    assert second.gap[2040 - 1990] < first.gap[2040 - 1990] < 0
    assert second.industry_gap[2040 - 1990] < first.industry_gap[2040 - 1990] <= 0
