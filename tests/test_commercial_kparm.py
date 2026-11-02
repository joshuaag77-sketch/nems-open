"""KPARM switches vs the values COMM holds in the oracle (first call, 2019)."""

import pytest

from nems_open import oracle_state
from nems_open.commercial.kparm import read_kparm

pytestmark = pytest.mark.skipif(not oracle_state.available("bm_out", 30), reason="oracle state not dumped")

# switch -> where the oracle holds it
WHERE = {"applyramp": "sd_out", "stretbehav": "tc_out", "costtrendswitch": "tc_out", "ksteocls": "tc_out",
         "comsteobm": "bm_out", "nohist": "bm_out", "decaybm": "bm_out", "lastdecayyr": "bm_out",
         "steobm2pct": "bm_out", "ifmax": "tc_pre"}


@pytest.mark.parametrize("name", WHERE)
def test_kparm(name):
    eia = oracle_state.load(WHERE[name], 30)[name]
    mine = read_kparm()[name]
    if hasattr(eia, "a"):
        assert list(eia.a) == mine
    else:
        assert int(eia) == mine
