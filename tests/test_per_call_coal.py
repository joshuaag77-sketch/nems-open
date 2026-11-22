"""The coal model (CMM, AIMMS) never sees an iteration number past its own iteration set.

coal.ams keys its solve status by Element(It_, curitr) with It_ = 1..MaxIter = 7. EIA calls the CMM 3 times a year;
our loop can call it 21 times, and from curitr 8 the element is empty, so the CMM takes a good solve for an
infeasible one. AimmsCoal.begin passes 7 for every later iteration (docs/per_call_state_audit.md). No AIMMS needed."""

import re

from nems_open.coal import aimms_couple as ac
from nems_open.coal import state


class _Process:
    def __init__(self):
        self.calls = []

    def call(self, year, itr, arrays=None, fcrl=0):
        self.calls.append((year, itr, fcrl))
        return {}, 0.0


def _bare():
    c = ac.AimmsCoal.__new__(ac.AimmsCoal)
    c.p, c.seconds, c.itr, c.production = _Process(), 0.0, 0, {}
    c.out, c.factor = {}, {}
    c.inputs = lambda year, q, prices: {}
    return c


def test_iterations_past_the_cmm_set_go_in_as_its_last():
    c = _bare()
    for itr in range(1, 22):
        c.begin(2030, itr, {}, {}, fcrl=int(itr == 21))
    sent = [i for _, i, _ in c.p.calls]
    assert sent[:7] == list(range(1, 8))
    assert set(sent[7:]) == {ac.CMM_MAX_ITR}
    assert c.p.calls[-1][2] == 1   # FCRL still goes through


def test_the_bound_is_coal_ams_maxiter():
    if not state.COAL_AMS.exists():
        return
    text = state.COAL_AMS.read_text(encoding="latin-1")
    m = re.search(r"Parameter MaxIter \{\s*Definition: \{\s*(\d+)", text)
    assert m and int(m.group(1)) == ac.CMM_MAX_ITR
