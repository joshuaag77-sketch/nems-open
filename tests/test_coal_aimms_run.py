"""The CMM input file written from the restart, in the format NEMS's write_aimms_input uses."""

import numpy as np
import pytest

from nems_open.coal import aimms_run, state
from nems_open.paths import REFERENCE_RUN
from nems_open.snapshot import Snapshot

pytestmark = pytest.mark.skipif(not (REFERENCE_RUN.exists() and state.COAL_AMS.exists()), reason="EIA checkout missing")


def tables(path):
    out = {}
    for block in path.read_text().split("COMPOSITE TABLE:")[1:]:
        lines = [x for x in block.strip().splitlines() if x and x != ";"]
        head = lines[0].split()
        out[head[-1]] = (head, [x.split() for x in lines[1:]])
    return out


@pytest.fixture(scope="module")
def snap():
    return Snapshot()


def test_base_year_sends_every_year_later_years_their_own(snap, tmp_path):
    base = tables(aimms_run.write_input(2024, 1, tmp_path, snap))
    later = tables(aimms_run.write_input(2030, 2, tmp_path, snap))
    head, rows = base["cl::QBLK_QCLEL"]
    assert head == ["cl::MNUMCR", "cl::MNUMYR", "cl::QBLK_QCLEL"]
    assert len(rows) == 11 * 61
    head, rows = later["cl::QBLK_QCLEL"]
    assert {r[1] for r in rows} == {"41"}                               # MNUMYR 41 = 2030
    us = float([r for r in rows if r[0] == "11"][0][2])
    assert us == pytest.approx(float(np.asarray(snap["QBLK/QCLEL"])[10, 40]), rel=1e-6)
    assert later["cl::NCNTRL_CURCALYR"][1][0][-1] == "2030"
    assert later["cl::NCNTRL_CURITR"][1][0][-1] == "2"
    assert "cl::COALEMM_EMM_CL_UNITS" not in later                      # NEMS skips the character array


def test_every_manifest_input_but_the_unit_names_is_written(snap, tmp_path):
    got = tables(aimms_run.write_input(2027, 1, tmp_path, snap))
    want = {f"cl::{t.block}_{t.name}" for t in state.input_manifest() if t.variable is not None} - {"cl::COALEMM_EMM_CL_UNITS"}
    assert want <= set(got)
