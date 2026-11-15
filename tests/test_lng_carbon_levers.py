"""The LNG export lever (ngmm/lng.py) and the carbon price in EIA's units (carbon_inputs.py), without AIMMS or GAMS."""

import numpy as np
import pytest

from nems_open import carbon_inputs
from nems_open.ngmm import lng

FY = 1990


@pytest.fixture(scope="module")
def eia():
    try:
        return lng.eia_bcfd()
    except FileNotFoundError as e:
        pytest.skip(f"reference data missing: {e}")


def test_lng_path_hits_the_2035_level_and_keeps_eias_shape(eia):
    p = lng.path(35.0, eia=eia)
    assert p[2035 - FY] == pytest.approx(35.0)
    assert np.allclose(p[:2027 - FY], eia[:2027 - FY])
    assert p[2050 - FY] - eia[2050 - FY] == pytest.approx(35.0 - eia[2035 - FY])
    assert 26 < eia[2035 - FY] < 28          # EIA's reference, about 26.8 Bcf/d


def test_terminal_table_adds_up_to_the_path(eia):
    p = lng.path(40.0, eia=eia)
    t = lng.terminal_table(p)
    for y in (2020, 2027, 2035, 2050):
        assert sum(t[y].values()) == pytest.approx(p[y - FY] * 365, rel=1e-9)
        assert set(t[y]) == set(lng.TERMINALS)
    assert t[2035]["LA"] / t[2035]["TX_E"] == pytest.approx(3057 / 1524)


def test_patch_input_fixes_exports_on_eias_own_file(eia):
    from nems_open.ngmm import aimms
    f = aimms.SRC / "input" / "nglngexp.txt"
    if not f.exists():
        pytest.skip("NGMM source not here")
    text = f.read_text(encoding="latin-1")
    out = lng.patch_input(text, lng.terminal_table(lng.path(30.0, eia=eia)))
    assert "LNG_FixedExports_Switch :=1;" in out and "LNG_FixedExports_Switch :=0;" not in out
    m = lng.TABLE.search(out)
    rows = [r.split() for r in m.group(1).splitlines() if r.strip() and not r.startswith("!")]
    assert rows[0] == list(lng.TERMINALS) and rows[-1][0] == "2050"
    # everything outside the one table and the switch is EIA's
    assert out.count("ExogenousAnnualLNGExports2016 := data table") == text.count("ExogenousAnnualLNGExports2016 := data table")
    assert len(out.splitlines()) < len(text.splitlines()) + 60


def test_gas_market_must_produce_the_extra_lng(eia):
    from nems_open.ngmm import GasMarket
    try:
        ref = GasMarket("cb2026")
    except FileNotFoundError as e:
        pytest.skip(f"reference data missing: {e}")
    more = GasMarket("cb2026", lng=lng.path(40.0, eia=eia))
    j = 2035 - FY
    assert more.lng_add[j] == pytest.approx((40.0 - eia[j]) * 365, rel=1e-6)
    q = ref.qngas_b
    hh_ref, hh_more = ref.clear(q)["henry_hub"][j], more.clear(q)["henry_hub"][j]
    assert hh_more > hh_ref


def test_lng_needs_a_gas_market():
    from nems_open import run_model
    from nems_open.demand_adapter import Policy
    with pytest.raises(ValueError, match="lng_exports"):
        run_model.run(Policy(lng_exports=np.full(61, 30.0)), 2027, 2027, ported=(), ogs="standin")


def test_carbon_price_in_eias_units():
    assert carbon_inputs.emetax_row(np.full(61, 50.0))[0] == pytest.approx(50.0 * 44 / 12 / 1000)
    base = {"EMISSION/EMETAX": np.zeros((15, 61)), "EMABLK/JMGTR": np.zeros(61), "EMEBLK/EMGTR": np.full(61, 19.27),
            "EMABLK/JXXTR": np.zeros(61)}
    cp = np.zeros(61)
    cp[40:] = 50.0
    out = carbon_inputs.arrays(cp, base)
    assert out["EMISSION/EMETAX"][0, 45] == pytest.approx(0.18333, rel=1e-4) and out["EMISSION/EMETAX"][0, 30] == 0
    assert out["EMABLK/JMGTR"][45] == pytest.approx(0.18333 * 19.27, rel=1e-4)   # 1987 $/MMBtu
    assert "EMABLK/JXXTR" not in out                     # no emission factor, left alone
    assert carbon_inputs.arrays(np.zeros(61), base) == {}


def test_lfmm_and_coal_inputs_carry_the_carbon_arrays():
    try:
        from nems_open.lfmm import gams_run
        a = gams_run.restart_arrays()
    except (FileNotFoundError, ImportError) as e:
        pytest.skip(f"LFMM inputs missing: {e}")
    out = carbon_inputs.arrays(np.full(61, 30.0), a)
    assert {"EMISSION/EMETAX", "EMABLK/JMGTR", "EMABLK/JDSTR", "EMABLK/JJFTR"} <= set(out)
    assert out["EMABLK/JDSTR"][50] == pytest.approx(30 * 44 / 12 / 1000 * a["EMEBLK/EDSTR"][50], rel=1e-6)


def test_patch_model_reapplies_the_table_after_the_trains():
    from nems_open.ngmm import aimms
    f = aimms.SRC / "nems_ngmm.ams"
    if not f.exists():
        pytest.skip("NGMM source not here")
    text = f.read_text(encoding="utf-8")
    out = lng.patch_model(text)
    i = out.index("Initialize_LNGCapacity;")
    assert out.index("Set_Exogenous_LNGExports;", i) < out.index("endif;", i)
    assert len(out.splitlines()) == len(text.splitlines()) + len(lng.REAPPLY)
