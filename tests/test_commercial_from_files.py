"""A commercial year started from the input files gives the same fuel use as one started from the dumps."""

import numpy as np
import pytest
from nems_open import oracle_state
from nems_open.commercial.comm import Commercial
from nems_open.snapshot import Snapshot

pytestmark = pytest.mark.skipif(not oracle_state.available("sd_in", 36), reason="oracle state not dumped")

YEAR = 36  # 2025


def test_same_fuel_use_from_files():
    flsp = Snapshot()["MACOUT/mc_commflsp"]
    runs = []
    for from_files in (False, True):
        c = Commercial.start_from_dump(YEAR, from_files=from_files)
        for itr in (1, 2):
            c.iteration(YEAR, itr, flsp)
        runs.append(c.qblk())
    for name in runs[0]:
        assert np.array_equal(runs[0][name].a if hasattr(runs[0][name], "a") else runs[0][name],
                              runs[1][name].a if hasattr(runs[1][name], "a") else runs[1][name]), name


def test_a_file_change_reaches_the_chain(monkeypatch):
    """NoHist = 1 in KPARM turns off the benchmark to history and STEO, so fuel use moves."""
    from nems_open.commercial import first_call
    real = first_call.read_kparm
    monkeypatch.setattr(first_call, "read_kparm", lambda: {**real(), "nohist": 1})
    flsp = Snapshot()["MACOUT/mc_commflsp"]
    out = []
    for patched in (False, True):
        if not patched:
            monkeypatch.setattr(first_call, "read_kparm", real)
        else:
            monkeypatch.setattr(first_call, "read_kparm", lambda: {**real(), "nohist": 1})
        c = Commercial.start_from_dump(YEAR, from_files=True)
        for itr in (1, 2):
            c.iteration(YEAR, itr, flsp)
        out.append(np.asarray(c.qblk()["qelcm"].a if hasattr(c.qblk()["qelcm"], "a") else c.qblk()["qelcm"]))
    assert not np.array_equal(out[0], out[1])
