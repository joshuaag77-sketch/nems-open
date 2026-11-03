"""The EV lever: a plug-in share of new LDV sales set through TRAN's vehicle choice.

TALT2X's nested logit gets one utility shift on the plug-ins, solved so consumers choose
the target share; the rest of TRAN follows. 2030, from the oracle's state.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.fortran_array import FArray
from nems_open.transportation import ldv_choice, tmpgnew
from nems_open.transportation.tran import start_from_dump
from tran_harness import needs

pytestmark = needs("tmpgnew")
Y, YEAR = 41, 2030


def _plugin_share(s):
    a = s["ldv_sales"].a[:, :, :, 10, Y - 1].astype(np.float64)
    return a[:, :, [k - 1 for k in ldv_choice.PLUG_IN]].sum() / a.sum()


def _tmpgnew(target=None):
    s, carry = start_from_dump(Y)
    s.update({k: (v.copy() if isinstance(v, FArray) else v) for k, v in oracle_state.load("tmpgnew_in", Y, run="run_tran").items()})
    if target is not None:
        s["_ev_share_target"] = {YEAR: target}
    with np.errstate(all="ignore"):
        tmpgnew.tmpgnew(s, carry["tmpgnew"])
    return s


def test_no_target_is_eias_run():
    s = _tmpgnew()
    ref = oracle_state.load("tmpgnew_out", Y, run="run_tran")["ldv_sales"]
    assert np.allclose(s["ldv_sales"].a, ref.a, rtol=1e-3, atol=1e-7)


def test_target_above_the_regulated_share_is_met():
    s = _tmpgnew(0.75)
    assert _plugin_share(s) == pytest.approx(0.75, abs=1e-4)
    assert s["_ev_shift"][YEAR] > 0


def test_target_below_the_regulated_share_is_held_up_by_the_standards():
    """Consumers choose 25%, but GHG and CAFE compliance in TMPGNEW pushes plug-ins back
    up to near EIA's share (48.5% in 2030): weaker demand does not undo the rules."""
    base = _plugin_share(_tmpgnew())
    low = _plugin_share(_tmpgnew(0.25))
    assert 0.25 < low <= base + 1e-6


def test_runner_lever_moves_transport_fuel():
    """Through the demand runner: more plug-ins in 2030's sales raise transport electricity
    and cut gasoline that year (only the new vintage changes, so the moves are small)."""
    from nems_open.run_demand import DemandRunner
    j = YEAR - 1990
    base = DemandRunner(YEAR, sectors=("transportation",))
    base.run_year()
    ev = DemandRunner(YEAR, sectors=("transportation",), ev_share={YEAR: 0.75})
    ev.run_year()
    assert ev.q["qeltr"][10, j] > base.q["qeltr"][10, j]
    assert ev.q["qmgtr"][10, j] < base.q["qmgtr"][10, j]
