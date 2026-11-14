"""The driver for EIA's real NGMM (nems_open.ngmm.aimms): the parts that need no AIMMS."""
import re
import shutil

import numpy as np
import pytest

from nems_open.ngmm import aimms

pytestmark = pytest.mark.skipif(not (aimms.SRC / "nems_ngmm.ams").exists(), reason="needs the upstream ngas folder")


def test_file_call_is_the_api_call_without_the_request_read(tmp_path):
    ams = tmp_path / "nems_ngmm.ams"
    shutil.copy(aimms.SRC / "nems_ngmm.ams", ams)
    aimms.add_file_call(ams)
    aimms.add_file_call(ams)   # idempotent
    text = ams.read_text(encoding="utf-8")
    assert text.count("Procedure NGMM_File_Call {") == 1
    assert "NGMM_File_Call, ncrl" in text.split("\n", 6)[4]
    body = text[text.index("Procedure NGMM_File_Call {"):]
    body = body[:body.index("\n\t}\n")]
    assert "RequestAttribute" not in body and "dex::ReadFromFile" not in body
    for step in ("ncntrl_curcalyr('1'):=curcalyr;", "ReadGlobalDataFromNEMS;", "FirstYearInitialization;", "NGMM;",
                 "Write_to_NEMS;", "PrepareDataForNextRoll;", "SendGlobalDataToNEMS;", 'write MNUMYR_complete to file "../../ngas/done.txt";'):
        assert step in body, step
    assert text.count("Procedure NGMM_MainExecution_API {") == 1   # EIA's own entry point untouched


def test_every_input_array_has_an_aimms_home():
    dom = aimms.domains()
    inputs = aimms.array_list("ngputvars.txt")
    assert len(inputs) == 118
    for block, var in inputs:
        assert f"{block}_{var}" in dom or var in ("OGPRRNG", "LCFSRNGOS"), (block, var)


def test_runval_reads_the_scedes():
    t = aimms.runval_text("cb2026")
    assert 'NGASSUMPTIONSN := "../../ngas/input/ngassumptions.txt";' in t
    assert "KEEPOPEN := 0;" in t and t.endswith("x_LNG_Gamma1 := -42.5;")


def test_inputs_file_round_numbers(tmp_path):
    (tmp_path / "ngas" / "toAIMMS").mkdir(parents=True)
    arrays = {f"{b}/{v}".lower(): np.zeros(1) for b, v in aimms.array_list("ngputvars.txt")}
    dom = aimms.domains()
    for b, v in aimms.array_list("ngputvars.txt"):
        dims = dom.get(f"{b}_{v}", [])
        arrays[f"{b}/{v}".lower()] = np.full([2] * len(dims), 1.5) if dims else np.array(3.0)
    p = aimms.write_inputs(tmp_path, arrays, 2030, 1)
    assert p.name == "GlobalDataToAimms_2030_01.txt"
    text = p.read_text()
    assert " M1 NCNTRL_CURIYR\n  1            41\n;" in text
    assert " MNUMCR MNUMYR MPBLK_PNGEL\n      1      1         1.5\n" in text
    assert "NGTDMREP_OGPRRNG" in text
    for block in text.split("COMPOSITE TABLE:\n")[1:]:   # AIMMS reads by position: entries end under their headers
        lines = block.split("\n;")[0].split("\n")
        ends = [m.end() for m in re.finditer(r"\S+", lines[0])]
        for line in lines[1:]:
            assert [m.end() for m in re.finditer(r"\S+", line)] == ends, line


def test_outputs_parse_like_filer(tmp_path):
    """filer.f funfmt 7: header ends with the name (domain in parentheses allowed), labels may be quoted."""
    p = tmp_path / "out.txt"
    p.write_text("COMPOSITE TABLE:\n  MNUMCR  globalyr   MPBLK_PNGEL(MNUMCR,globalyr)\n"
                 "       1        41   2.5\n     '11'       41   3.25\n;\n\n"
                 "COMPOSITE TABLE:\n globalyr  NGTDMREP_OGHHPRNG\n       41  1.75\n;\n")
    out = aimms.parse_composite(p)
    assert out["MPBLK_PNGEL"] == {(1, 41): 2.5, (11, 41): 3.25}
    assert out["NGTDMREP_OGHHPRNG"] == {(41,): 1.75}
    assert aimms.to_array(out["NGTDMREP_OGHHPRNG"], (61,))[40] == 1.75
