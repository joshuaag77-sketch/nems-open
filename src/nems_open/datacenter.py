"""Data center load cases: public forecasts turned into electricity added to the model.

datacenter_load.json holds every number and where it comes from, and the choices that are
ours. This file does the arithmetic: each forecast becomes data center TWh by year, on
LBNL's whole-facility scope, and the part above EIA's own path is the load added.

    case = added_load("ai_high")       # for Policy(added_load=case)
"""

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from nems_open.snapshot import Snapshot
from nems_open.supply_standin.data import FIRST_YEAR, load_case, restart_path

SOURCE = json.loads(Path(__file__).with_name("datacenter_load.json").read_text(encoding="utf-8"))
NYEARS = 61
TBTU_PER_TWH = 3.412
SERVERS = 7                 # 0-based: CMServices(8), Data Center Servers
ELECTRICITY = 0
BASE_YEAR = 2025
REGION_YEAR = 2040          # the year whose side-case difference sets the regional split


def _finding(source: str, name: str) -> float:
    return SOURCE["sources"][source]["findings"][name]["value"]


LOAD_FACTOR = _finding("grid_strategies_2025", "large_datacenter_load_factor")
LBNL_2023 = _finding("lbnl_2024", "twh_2023")


def gw_to_twh(gw):
    return np.asarray(gw, dtype=float) * 8.76 * LOAD_FACTOR


def eia_path_twh() -> np.ndarray:
    """EIA's reference data center electricity by year, scaled to LBNL's scope. (61,) TWh."""
    c = Snapshot(restart_path("cb2026"))["COMMREP/cmusconsumption"]     # quads
    servers = np.asarray(c[SERVERS, ELECTRICITY], dtype=float) * 1000.0 / TBTU_PER_TWH
    return servers * (LBNL_2023 / servers[2023 - FIRST_YEAR])


def regional_shares() -> np.ndarray:
    """Where the added load goes, by census division: EIA's own high-demand case. (9,), sums to 1."""
    hi, ref = load_case("higheldmd")["QBLK/qelcm"], load_case("cb2026")["QBLK/qelcm"]
    d = np.maximum(hi[:9, REGION_YEAR - FIRST_YEAR] - ref[:9, REGION_YEAR - FIRST_YEAR], 0.0)
    return d / d.sum()


def case_path_twh(key: str) -> np.ndarray:
    """The case's data center electricity by year, TWh on LBNL's scope. (61,)."""
    eia = eia_path_twh()
    anchors = SOURCE["cases"][key].get("anchors")
    if not anchors:
        return eia
    j0 = BASE_YEAR - FIRST_YEAR
    start = float(eia[j0])
    years, twh = [BASE_YEAR], [start]
    for a in anchors:
        years.append(a["year"])
        if "growth_gw_since_2025" in a:
            twh.append(start + float(gw_to_twh(a["growth_gw_since_2025"])))
        elif "ai_gw_on_top_of_2025" in a:
            twh.append(start + float(gw_to_twh(a["ai_gw_on_top_of_2025"])))
        else:
            twh.append(float(gw_to_twh(a["total_gw"])))
    out = eia.copy()
    all_years = np.arange(FIRST_YEAR, FIRST_YEAR + NYEARS)
    within = (all_years >= BASE_YEAR) & (all_years <= years[-1])
    out[within] = np.interp(all_years[within], years, twh)
    # past the last anchor: hold the amount added
    last = years[-1] - FIRST_YEAR
    after = all_years > years[-1]
    out[after] = eia[after] + (out[last] - eia[last])
    return out


@dataclass
class AddedLoad:
    key: str
    twh: np.ndarray             # (61,) US TWh added to commercial electricity, by year
    shares: np.ndarray          # (9,) by census division
    flex_share: float = 0.0     # share of the added energy that can be curtailed each year

    def tbtu(self, j: int) -> np.ndarray:
        """The added load by census division in year index j, trillion Btu. (9,)"""
        return self.twh[j] * TBTU_PER_TWH * self.shares


def added_load(key: str) -> AddedLoad | None:
    """The load this case adds above EIA's own path; None for the reference."""
    case = SOURCE["cases"][key]
    if not case.get("anchors"):
        return None
    add = np.maximum(case_path_twh(key) - eia_path_twh(), 0.0)
    return AddedLoad(key, add, regional_shares(), float(case.get("flex_share", 0.0)))
