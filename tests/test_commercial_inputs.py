"""Input file readers vs the oracle's arrays right after EIA read the same files.

The oracle dumps its state at the end of the service demand first call (`frd_out`,
2019, first iteration), so every reader's output can be compared array for array.
Skipped until the oracle has run.
"""

import numpy as np
import pytest

from nems_open import oracle_state
from nems_open.commercial import inputs

pytestmark = pytest.mark.skipif(not oracle_state.available("frd_out", 30), reason="oracle state not dumped")


@pytest.fixture(scope="module")
def eia():
    return oracle_state.load("frd_out", 30)


def same(mine, theirs):
    """Float32 arrays equal to rounding, or integers exactly."""
    mine, theirs = np.asarray(mine), np.asarray(theirs)
    assert mine.shape == theirs.shape
    if np.issubdtype(theirs.dtype, np.integer):
        assert (mine == theirs).all()
    else:
        err = np.abs(mine.astype(np.float64) - theirs) / np.maximum(np.abs(theirs), 1e-6)
        assert err.max() < 1e-6


def test_kintens(eia):
    mine = inputs.read_kintens()
    # Column 4 (the total) is filled later by COMServiceDemand.
    same(mine[:, :, :, 1:3], eia["comeui"][:, :, :, 1:3])


def test_ksheff(eia):
    imprv_ht, imprv_cl, heat, cool = inputs.read_ksheff()
    same(imprv_ht.a, eia["existimprvht"].a)
    same(imprv_cl.a, eia["existimprvcl"].a)
    same(heat[1:11, 1:9, 2, 29:61], eia["shellheatfactor"][1:11, 1:9, 2, 29:61])
    same(cool[1:11, 1:9, 2, 29:61], eia["shellcoolfactor"][1:11, 1:9, 2, 29:61])


@pytest.mark.parametrize("name", ["dcf", "xplicitmiscshr", "melselq", "pctscsavings", "ct_flag",
                                  "marketpenetrationmels", "marketpenetrationsc"])
def test_kmels(eia, name):
    same(inputs.read_kmels()[name].a, eia[name].a)


@pytest.mark.parametrize("name", ["datactrservpenetration", "officepcpenetration"])
def test_kmels_by_year(eia, name):
    mine = inputs.read_kmels()[name]
    same(mine[30:61], eia[name][30:61])


def test_district_services(eia):
    same(inputs.read_kdsstm().a, eia["distservsteameui"].a)
    same(inputs.read_kdseff().a, eia["distservboilereff"].a)
    same(inputs.read_kdsfs().a, eia["distservfuelshr"].a)


def test_elasticities(eia):
    same(inputs.read_ksdela().a, eia["shortrunpriceelasofdmd"].a)
    same(inputs.read_khurela().a, eia["hurdleelas"].a)


def test_kvarsdi(eia):
    same(inputs.read_kvarsdi().a, eia["servicedflrspcprop"].a)


def test_krenew(eia):
    efficacy, contrib = inputs.read_krenew()
    assert efficacy == pytest.approx(float(eia["sunlightefficacy"]), rel=1e-6)
    same(contrib.a, eia["solarrenewablecontrib"].a)


@pytest.mark.skipif(not (oracle_state.available("frd_out", 30) and "baselinebkwhcm" in oracle_state.load("frd_out", 30)),
                    reason="BASELINEBKWHCM not in this oracle build's dump")
def test_bldbase(eia):
    mine = inputs.read_bldbase()
    same(mine.a, eia["baselinebkwhcm"].a[:9, :61])  # divisions 1-9, all years


def test_kdegday(eia):
    same(inputs.read_kdegday(eia["mc_np"]).a, eia["degreedays"].a)


# ---- KTEK technology table and base-year intensities ----

from nems_open.commercial import base_year, ktek  # noqa: E402


@pytest.fixture(scope="module")
def tables(eia):
    k = ktek.read_ktek(epa111d=0, ab32sw=1)  # the reference case runs with AB32SW=1
    base_year.index_technologies(k)
    base_year.normalize_base_shares(k)
    snapshot = {name: getattr(k, name).copy() for name in ("TechEff", "TechCost", "TechAvailability")}
    eui = inputs.read_kintens()
    derived = base_year.base_year_intensities(k, eui, eia["cmtotalflspc"])
    return k, derived, snapshot


@pytest.mark.parametrize("name", ["TechEff", "TechCRI", "TechCost", "TechAvailability", "TechLife", "RetroCostFract",
                                  "CostParam1", "CostParam2", "CostParam3", "EquipRestriction", "FuelbyTech",
                                  "TechbyService", "TechbyModel", "TechsforService", "CMnumEqV",
                                  "CMnumTechsforService"])
def test_ktek_tables(eia, tables, name):
    same(getattr(tables[0], name).a, eia[name.lower()].a)


def test_ktek_text(eia, tables):
    assert (np.char.rstrip(tables[0].EquipName) == np.char.rstrip(eia["equipname"].a.astype("U44"))).all()
    assert (np.char.rstrip(tables[0].CostTrend) == np.char.rstrip(eia["costtrend"].a.astype("U10"))).all()


def test_ktek_cost_year(eia, tables):
    assert tables[0].TechCostYr1 - ktek.BASEYR + 1 == int(eia["iktechcostyr"])


@pytest.mark.parametrize("name", ["ServDmdIntenBASE", "FuelShareofServiceBASE", "AverageEfficiencyBASE"])
def test_base_year_intensities(eia, tables, name):
    mine = tables[1][name]
    theirs = eia[name.lower()]
    same(mine.a, theirs.a)


def test_base_year_shares(eia, tables):
    same(tables[0].TechShareofServiceBASE.a, eia["techshareofservicebase"].a)
