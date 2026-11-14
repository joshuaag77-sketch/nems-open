"""More EVs in the full loop: less gasoline and more electricity sales, on both paths.

EIA's EV charging reaches the grid through the buildings rows (QELRS and QELCM add TRQ_ELEC; QELTR is
passenger rail only), so ported buildings have to be handed TRAN's charging load. The stub path
puts the same load on QELTR. Either way the total, QELAS, has to rise and the power sector has to
serve it. EIA's reference reaches 49% plug-in sales in 2030, so the target here sits well above it.
"""

import os

import numpy as np
import pytest

from nems_open.demand_adapter import Policy
from nems_open.run_model import PORTED, run
from nems_open.supply_standin.data import FIRST_YEAR, US, available

pytestmark = pytest.mark.skipif(not available(), reason="AEO2026 runs not available")

TARGET = 0.95


def us(r, name, year):
    return float(r.quantities[f"QBLK/{name}"][US, year - FIRST_YEAR])


def test_stub_transport():
    a = run(Policy(start_year=2027), 2027, 2040, ported=())
    b = run(Policy(start_year=2027, ev_share=TARGET), 2027, 2040, ported=())
    assert us(b, "qmgtr", 2040) < us(a, "qmgtr", 2040)
    assert us(b, "qelas", 2040) > us(a, "qelas", 2040)
    assert us(b, "qngel", 2040) > us(a, "qngel", 2040), "the power sector serves the new load"


def test_stub_transport_with_ported_buildings():
    a = run(Policy(start_year=2030), 2030, 2032)
    b = run(Policy(start_year=2030, ev_share=TARGET), 2030, 2032)
    assert us(b, "qmgtr", 2032) < us(a, "qmgtr", 2032)
    assert us(b, "qelas", 2032) > us(a, "qelas", 2032)


def test_stub_load_reaches_the_dispatch_lp():
    """The LP's load comes from the QBLK/qel rows, transport's included."""
    from nems_open.snapshot import Snapshot
    from nems_open.emm import demand
    pytest.importorskip("highspy")
    snap, year = Snapshot(), 2040
    j = year - FIRST_YEAR
    sales = {k: np.array(snap[k]) for k in snap.names("QBLK/qel")}
    before = demand.net_load_twh(snap, year, sales=sales).sum()
    sales["QBLK/qeltr"][:9, j] += 100.0
    assert demand.net_load_twh(snap, year, sales=sales).sum() > before


@pytest.mark.skipif(os.environ.get("NEMS_SLOW") != "1", reason="set NEMS_SLOW=1 to run TRAN in the loop")
def test_ported_transport_charges_through_the_buildings():
    from nems_open.run_demand import TransportationSector
    if not TransportationSector.available(2030):
        pytest.skip("transportation state not available")
    ported = PORTED + ("transportation",)
    a = run(Policy(start_year=2030), 2030, 2031, ported=ported)
    b = run(Policy(start_year=2030, ev_share=TARGET), 2030, 2031, ported=ported)
    assert us(b, "qmgtr", 2031) < us(a, "qmgtr", 2031)
    assert us(b, "qelrs", 2031) + us(b, "qelcm", 2031) > us(a, "qelrs", 2031) + us(a, "qelcm", 2031)
    assert us(b, "qelas", 2031) > us(a, "qelas", 2031)
