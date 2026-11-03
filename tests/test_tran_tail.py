"""The last stretch of TRAN vs the oracle: TFRTRPT, TSHIP, TRANAIR, TBENCHMARK, TREPORT
and TRAN's own statements after TREPORT."""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.transportation import air_report, bench, frt_rpt, frt_ship, report
from tran_harness import YEARS, needs, run


def _treport(s, carry=None):
    # cmpg_2, tmpg_2 and lmpg_2 are saved but not dumped; every technology the
    # reference run uses has stock VMT in every dump year, so none is stale.
    report.treport(s, {k: np.zeros(17, dtype=np.float32) for k in ("cmpg_2", "tmpg_2", "lmpg_2")})


def _mer(y):
    # MER_STEO_regn has no year axis: set in the last SEDS year, read in the MER year,
    # so its end-of-call value is its start value in every dump year but those two.
    return {"mer_steo_regn": oracle_state.load("tbenchmark_out", y, run="run_tran")["p_mer_steo_regn"].copy()}


PORTS = {
    "tfrtrpt": (lambda s: frt_rpt.tranfrt_report(s), None),
    "tship": (frt_ship.tship, ["isfdt_b", "lsfo_upgrade", "temp_prhtr"]),
    "tranair": (air_report.tranair, ["pjftr_us"]),
    "tbenchmark": (bench.tbenchmark, _mer),
    "treport": (_treport, None),
    "tran_tail": (lambda s: report.tran_tail(s), None),
}


@pytest.mark.parametrize("y", YEARS, ids=lambda y: str(1989 + y))
@pytest.mark.parametrize("tag", list(PORTS))
def test_port(tag, y):
    if needs(tag).args[0]:
        pytest.skip("transportation oracle state not dumped")
    port, carry = PORTS[tag]
    if callable(carry):
        carry = carry(y)
    # TRANAIR: new aircraft are demand minus stock, two large numbers, so the last-bit
    # differences between numpy's and gfortran's exp/pow in TAIRT grow to about 1e-4.
    tol = 1e-3 if tag == "tranair" else 1e-4
    assert run(port, tag, y, tol=tol, carry=carry) == {}
