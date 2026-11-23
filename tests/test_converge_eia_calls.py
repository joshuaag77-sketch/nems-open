"""converge.EiaCalls: state a module changes on every call is held at what EIA's last call (3 a year) starts from."""

import numpy as np

from nems_open.converge import EIA_CALLS, MAXITR, EiaCalls


def _compound(calls):
    bank = np.array([10.0])
    hold = EiaCalls()
    for call in range(1, calls + 1):
        hold.before(2030, call, {"bank": bank})
        bank *= 0.5   # spent again on every call
    return bank[0]


def test_eia_calls_is_maxitr_plus_the_final_pass():
    assert EIA_CALLS == MAXITR + 1 == 3


def test_later_calls_repeat_eias_last():
    assert _compound(EIA_CALLS) == 10.0 * 0.5 ** EIA_CALLS
    for n in (4, 6, 21):
        assert _compound(n) == _compound(EIA_CALLS)
    assert _compound(2) == 10.0 * 0.25   # fewer calls than EIA are left alone


def test_a_new_year_starts_fresh():
    a = np.array([1.0])
    hold = EiaCalls()
    for call in range(1, 5):
        hold.before(2030, call, {"a": a})
        a += 1
    hold.before(2031, 4, {"a": a})   # no call 3 saved for 2031: nothing restored
    assert a[0] == 4.0
