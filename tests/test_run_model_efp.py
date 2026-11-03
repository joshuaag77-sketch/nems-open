"""run_model with elec_price="efp": retail electricity prices from the ported EFP.

Opt-in (NEMS_RUN_SLOW=1, about 7 minutes): EFP runs on the loop's sales, about 30 s
a year, after a pre-roll from the oracle's 2021 state. On EIA's demand the prices
are EIA's (EFP's response is applied as a ratio to its own reference run); with
more efficient buildings, sales fall and EFP raises the price (fixed costs spread
over fewer kilowatt-hours), where the stand-in lowers it.
"""

import os

import pytest

from emm_oracle import available
from nems_open.demand_adapter import Policy
from nems_open.emm.chain import BOOKS
from nems_open.run_model import default_elec_price, run
from nems_open.supply_standin.data import FIRST_YEAR

pytestmark = [
    pytest.mark.skipif(os.environ.get("NEMS_RUN_SLOW") != "1", reason="slow: set NEMS_RUN_SLOW=1 (about 7 minutes)"),
    pytest.mark.skipif(not (available("fp_out", 41) and (BOOKS / "32" / "EMM_EFPR.daf").exists()),
                       reason="EMM oracle dumps or the 2021 books snapshot missing"),
]
J = 2027 - FIRST_YEAR
PRICES = ["MPBLK/pelrs", "MPBLK/pelcm", "MPBLK/pelin", "MPBLK/pelas"]


def test_baseline_prices_are_eia():
    efp = run(Policy(start_year=2027), 2027, 2027, elec_price="efp")
    std = run(Policy(start_year=2027), 2027, 2027)
    for k in PRICES:
        rel = abs(efp.prices[k][10, J] / std.prices[k][10, J] - 1)
        assert rel < 5e-3, (k, rel)


def test_efficiency_raises_efp_price():
    pol = Policy(building_efficiency=0.9, start_year=2027)
    efp = run(pol, 2027, 2027, elec_price="efp")
    std = run(pol, 2027, 2027)
    assert efp.prices["MPBLK/pelas"][10, J] > std.prices["MPBLK/pelas"][10, J]
    assert efp.quantities["QBLK/qelas"][10, J] < std.quantities["QBLK/qelas"][10, J]


def test_efp_is_the_default_with_the_dispatch_lp():
    assert default_elec_price("lp", "cb2026") == "efp"
    assert default_elec_price("standin", "cb2026") == "standin"
    assert default_elec_price("lp", "hm2026") == "standin"
    r = run(Policy(start_year=2027), 2027, 2027, elec="lp")
    assert "EFP retail prices" in r.passes[0].routines
    assert r.passes[-1].fcrl == 1
    std = run(Policy(start_year=2027), 2027, 2027, elec="lp", elec_price="standin")
    for k in PRICES:   # on EIA's demand EFP's response is about 1, so prices stay near the stand-in's
        rel = abs(r.prices[k][10, J] / std.prices[k][10, J] - 1)
        assert rel < 2e-2, (k, rel)
