"""Commercial levers through run_model's policy: each moves commercial fuel use the right way.

Benchmarking holds fuel use to SEDS and STEO through 2026, so the loop starts in 2027, when the
levers can show. The commercial module starts from the input files (about a minute for 2019 to 2026).
"""

import numpy as np
import pytest
from nems_open import run_model
from nems_open.commercial.levers import CommercialLevers, Standard
from nems_open.demand_adapter import Policy
from nems_open.paths import REFERENCE_RUN
from nems_open.supply_standin.data import FIRST_YEAR, US

pytestmark = pytest.mark.skipif(not REFERENCE_RUN.exists(), reason="restart file missing")

YEAR = 2029
J = YEAR - FIRST_YEAR


def commercial(levers=None):
    r = run_model.run(Policy(0.0, None, 1.0, 2027, commercial=levers), 2027, YEAR, ported=("commercial",))
    return {k: float(r.quantities[f"QBLK/{k}"][US, J]) for k in ("qelcm", "qngcm", "qdscm")}


@pytest.fixture(scope="module")
def baseline():
    return commercial()


def test_a_stricter_building_code_cuts_gas_and_electricity(baseline):
    now = commercial(CommercialLevers(shell_improvement=0.3, shell_start_year=2020))
    assert now["qngcm"] < baseline["qngcm"]
    assert now["qelcm"] <= baseline["qelcm"] * 1.001


def test_an_electric_cooling_standard_cuts_electricity(baseline):
    now = commercial(CommercialLevers(standards=(Standard(service=2, min_eff=3.5, year=2021, fuel=1),)))
    assert now["qelcm"] < baseline["qelcm"]


def test_levers_need_the_ported_commercial_module():
    with pytest.raises(ValueError):
        run_model.run(Policy(0.0, None, 1.0, 2027, commercial=CommercialLevers(shell_improvement=0.1)), 2027, 2028, ported=())
