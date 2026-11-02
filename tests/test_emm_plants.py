"""Plant file vs the AEO2026 reference run's capacity by type, region and year.

The plant file lists units operating now, so it matches NEMS's UCAP arrays only from the
last historical years on (2020 to 2026 here). Before that NEMS uses history that includes
units since retired. Groups that match to rounding use a tight tolerance; the others carry a
documented one (see COAL and STEAM below).
"""

import numpy as np
import pytest

from nems_open.emm import plants
from nems_open.paths import INPUT, REFERENCE_RUN
from nems_open.snapshot import Snapshot

pytestmark = pytest.mark.skipif(
    not ((INPUT / "emm" / "emm_db" / "NEMS_INPUT.db").exists() and REFERENCE_RUN.exists()), reason="EMM inputs missing")

YEARS = (2020, 2022, 2024, 2026)
OWNERS = {"u": plants.OWNER_UTILITY, "n": plants.OWNER_NUG}

# UCAP array prefix -> EFD plant types that add up to it
EXACT = {
    "hy": ["HYC"], "ps": ["HYR"], "ge": ["GTH"], "wd": ["BMS"],
    "wn": ["WND"], "pv": ["SPV"], "cc": ["CCG", "CCX", "CCO"], "ct": ["CTG", "CTO", "CTX"],
}
# Nuclear uprates and a few NUG biomass/waste units are dated differently in the history.
LOOSE = {"nu": ["CNU"], "ms": ["MSW"]}
# Coal and oil/gas steam differ by a few percent: NEMS also counts retrofits (coal to gas,
# ECP-converted units) that the plant file carries under another type.
COAL = {"cs": ["CSU", "CSC"]}
STEAM = {"os": ["STG", "STO", "STX"]}
REL = {"cs": 0.04, "os": 0.06}


def eia_cap(prefix, owner, year):
    return Snapshot()[f"UDATOUT/ucap{prefix}{owner}"][:, year - 1990]


def cases(groups):
    return [(g, o, y) for g in groups for o in OWNERS for y in YEARS]


@pytest.mark.parametrize("group,owner,year", cases(EXACT))
def test_exact_groups(group, owner, year):
    eia = eia_cap(group, owner, year)
    mine = plants.capacity_gw(year, EXACT[group], OWNERS[owner])
    assert mine.shape == eia.shape
    assert np.abs(mine[:25] - eia[:25]).max() < 0.35                # GW, per region
    assert abs(mine[27] - eia[27]) <= 0.01 * max(eia[27], 1.0) + 0.1


@pytest.mark.parametrize("group,owner,year", cases(LOOSE))
def test_loose_groups(group, owner, year):
    eia = eia_cap(group, owner, year)
    mine = plants.capacity_gw(year, LOOSE[group], OWNERS[owner])
    assert np.abs(mine[:25] - eia[:25]).max() < 2.6
    assert abs(mine[27] - eia[27]) <= 0.09 * eia[27] + 0.1


@pytest.mark.parametrize("group,owner,year", cases({**COAL, **STEAM}))
def test_coal_and_steam(group, owner, year):
    types = {**COAL, **STEAM}[group]
    eia = eia_cap(group, owner, year)
    mine = plants.capacity_gw(year, types, OWNERS[owner])
    assert np.abs(mine[:25] - eia[:25]).max() < 2.0
    assert abs(mine[27] - eia[27]) <= REL[group] * eia[27]


def test_unit_table_shape():
    u = plants.load_units()
    assert len(u) == 27337
    assert u.region.min() == 1 and u.region.max() == 25
    assert set(plants.efd_types()) >= {"CSC", "CCG", "CTG", "WND", "SPV", "HYC", "CNU"}
