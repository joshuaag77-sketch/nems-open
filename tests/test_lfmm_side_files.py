"""GDXXRW's side files for LFMM, read through Excel (skipped where Excel or pywin32 is missing)."""

import pytest

from nems_open.lfmm import side_files as sf
from nems_open.paths import UPSTREAM

win32 = pytest.importorskip("win32com.client")
XLS = UPSTREAM / "models" / "lfmm" / "input"


@pytest.mark.skipif(not (XLS / "coald2refmap.xls").exists(), reason="EIA checkout missing")
def test_coal_map_and_first_build_year():
    try:
        got = sf.read_ranges(XLS / "coald2refmap.xls", sf.XLS[0][2])
    except Exception as e:                      # no Excel on this machine
        pytest.skip(str(e))
    assert got["FirstBldYear"][1][0][0] == 2026.0
    dims, rows = got["CoalDreg2RefRegMap"]
    assert dims == ["*", "*"] and ("CoalDReg1", "1_REFREG", 1.0) in rows
