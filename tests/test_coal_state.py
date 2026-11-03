"""CMM transfer schema and COAL_EXPECT."""

import json
import hashlib
from pathlib import Path

import numpy as np
import pytest

from nems_open.coal import state
from nems_open.coal.expect import coal_expect
from nems_open.paths import REFERENCE_RUN, UPSTREAM
from nems_open.snapshot import Snapshot

pytestmark = pytest.mark.skipif(not (REFERENCE_RUN.exists() and state.COAL_AMS.exists()), reason="EIA checkout missing")


@pytest.fixture(scope="module")
def snap():
    return Snapshot()


def test_manifest_counts_match_the_plan():
    assert len(state.input_manifest()) == 104          # 106 lines, PCLELCDR twice and one more repeat
    assert len(state.output_manifest()) == 157
    assert len(state.written_outputs()) == 159


def test_the_writer_and_the_manifest_differ_as_the_plan_says():
    written = {t.key for t in state.written_outputs()}
    manifest = {t.key for t in state.output_manifest()}
    assert written - manifest == {"COALREP/CLEXPRANK", "COALREP/CLIMPRANK", "MPBLK/PMCIN", "USO2GRP/CL_CRV_PROD", "USO2GRP/EFD_SC_DR_PT"}
    assert manifest - written == {"MPBLK/PDSIN", "MPBLK/PELIN", "USO2GRP/XCL_TRATI1"}
    # PELIN and PDSIN are input energy prices, not coal prices.
    assert {"MPBLK/PELIN", "MPBLK/PDSIN"} <= {t.key for t in state.input_manifest()}


def test_year_slices():
    w = {t.key: t for t in state.written_outputs()}
    assert w["MPBLK/PCLRS"].aimms_dims == ("MNUMCR", "globalyr") and w["MPBLK/PCLRS"].year_slice
    assert not w["COALEMM/NUM_SC"].year_slice
    assert w["COALPRC/PCLELCDR"].variable.units != ""


@pytest.mark.parametrize("which", ["input_manifest", "output_manifest", "written_outputs"])
def test_every_transfer_is_in_the_restart_with_its_dictionary_shape(snap, which):
    r = state.check_against_restart(getattr(state, which)(), snap)
    assert not r["missing"] and not r["not_in_dictionary"]
    # EMM_CL_UNITS is a character array: the restart adds a string-length axis.
    assert [m[0] for m in r["shape_mismatch"]] in ([], ["COALEMM/EMM_CL_UNITS"])


def test_inputs_from_the_restart(snap):
    x = state.CoalInputs.from_snapshot(snap, 2030)
    assert len(x.arrays) == 104 and x["qblk/qclel"].shape == (11, 61)
    assert x["COALEMM/QCLCLNR"].shape == (16, 61, 38)           # the plan: 16 coal regions, 61 years, 38 subsectors
    assert x["QBLK/QCLEL"][10, 2030 - 1990] > 0


def test_source_hashes_are_frozen():
    frozen = json.loads((Path(state.__file__).with_name("source_hashes.json")).read_text())["sha256"]
    assert len([k for k in frozen if k.startswith("models/coal/input/")]) == 36
    for rel, digest in frozen.items():
        assert hashlib.sha256((UPSTREAM / rel).read_bytes()).hexdigest() == digest, rel


# COAL_EXPECT -----------------------------------------------------------------------

def test_coal_expect_on_a_small_array():
    a = np.zeros((1, 31, 61, 1))
    a[0, 0, :, 0] = np.arange(61)                     # the current-year value in year index i is i
    out = coal_expect(a, curiyr=20)                   # year 2009 (1-based index 20): slots look at years 21..50
    assert list(out[0, 1:4, 19, 0]) == [20, 21, 22]   # slot k holds the value of 0-based year index 19 + k
    assert out[0, 30, 19, 0] == 49
    out = coal_expect(a, curiyr=58)                   # 58 + 3 > 61: the last year (index 60) from slot 3 on
    assert list(out[0, 1:5, 57, 0]) == [58, 59, 60, 60]
    assert (out[0, 5:, 57, 0] == 60).all()
    assert out[0, 0, 57, 0] == 57                      # slot 0 untouched
    assert (a[0, 1:, 57, 0] == 0).all()                # the input is not modified


@pytest.mark.parametrize("name", ["xcl_1tesc", "xcl_2tesc"])
def test_coal_expect_against_the_restart(snap, name):
    """The restart holds the expectations as made during the run (from the prior cycle's values) and the final
    current-year values. They agree exactly for 2050 and within 0.5% elsewhere."""
    a = snap[f"USO2GRP/{name}"].astype(np.float64)
    assert a.shape == (14, 31, 61, 16)
    worst = 0.0
    for curiyr in range(2025 - 1990 + 1, 62):         # 2025 on: COAL_EXPECT first runs after the 2024 base year
        mine = coal_expect(a, curiyr)[:, 1:, curiyr - 1, :]
        theirs = a[:, 1:, curiyr - 1, :]
        mask = np.abs(mine) > 1e-6
        if mask.any():
            worst = max(worst, float((np.abs(mine - theirs)[mask] / np.abs(mine)[mask]).max()))
        if curiyr == 61:
            assert np.array_equal(mine, theirs)
    assert worst < 0.005, worst
