"""NEM_TO_LFMM1.gdx written like FILER writes it: labels and records (no GAMS needed)."""

import numpy as np
import pytest

from nems_open.lfmm import gams_io as g
from nems_open.paths import INPUT

pytestmark = pytest.mark.skipif(not (INPUT / "dict.txt").exists(), reason="EIA checkout missing")


def test_labels_follow_filer():
    assert g.labels("MNUMCR")[8] == "09_Pacific"
    assert g.labels("MNUMCR")[10] == "11_United_States"
    assert g.labels("MNUMYR")[:2] == ["1990_MNUMYR", "1991_MNUMYR"]
    assert g.labels("MNUMPR")[0] == "01_MNUMPR"
    assert g.labels("57")[:2] == ["01_M57", "02_M57"]
    assert g.labels("NUMCAN")[0] == "1_st_Canada"      # FILER reads the text from column 27


def test_varlist_covers_lf_nem():
    keys = {v.key.upper() for v in g.varlist()}
    assert len(keys) > 1000
    assert {"MPBLK/PMGTR", "INTOUT/P_FOREIGN_CRUDE", "NCNTRL/CURCALYR"} <= keys


def test_records_keep_inner_size_one_dims_and_skip_zeros():
    v = next(x for x in g.varlist() if x.key.upper() == "INTOUT/P_FOREIGN_CRUDE")
    a = np.zeros((11, 1, 14, 61))
    a[2, 0, 3, 40] = 5.0
    names, rows = g.records(v, a)
    assert names == ["MNCRUD", "M1", "CISTEP", "MNXYRS"]
    assert rows == [(g.labels("MNCRUD")[2], "1_M1", g.labels("CISTEP")[3], g.labels("MNXYRS")[40], 5.0)]
