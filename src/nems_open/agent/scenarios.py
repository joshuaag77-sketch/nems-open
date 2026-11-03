"""Run or load a scenario: the demo's grid from disk, anything else a live run of the fast loop.

The demo's 144 scenarios (web/data/scenarios/) are the same records `scripts/precompute_scenarios.py` writes, so an
agent answer and the demo page agree to the digit. A scenario off the grid is run live with the same function
(every sector on the stub, 4 to 8 seconds).
"""

import importlib.util
import json
from functools import lru_cache

from nems_open.agent.knowledge import POLICY_START, WEB_DATA, YEARS, meta
from nems_open.paths import REPO_ROOT

LIMITS = {"carbon_price": (0.0, 200.0), "ev_share_2035": (0.0, 1.0), "building_energy_2050": (0.7, 1.0)}
CARBON_WARN = 100.0     # docs/supply_standin.md: results above $100 are extrapolation


@lru_cache(maxsize=1)
def _script():
    path = REPO_ROOT / "scripts" / "precompute_scenarios.py"
    spec = importlib.util.spec_from_file_location("nems_precompute_scenarios", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def check_levers(carbon_price, ev_share_2035, building_energy_2050) -> list[str]:
    """Reasons a lever setting is outside what the model supports (empty if fine)."""
    problems = []
    for name, v in (("carbon_price", carbon_price), ("ev_share_2035", ev_share_2035), ("building_energy_2050", building_energy_2050)):
        if v is None and name == "ev_share_2035":
            continue
        lo, hi = LIMITS[name]
        if v is None or not lo <= float(v) <= hi:
            problems.append(f"{name} must be between {lo:g} and {hi:g}")
    return problems


def load(carbon_price: float, ev_share_2035, building_energy_2050: float) -> tuple[str, dict, str]:
    """(scenario id, record, 'precomputed grid' or 'live run')."""
    s = _script()
    carbon = int(carbon_price) if float(carbon_price).is_integer() else float(carbon_price)
    ev = None if ev_share_2035 is None else round(float(ev_share_2035), 4)
    bld = round(float(building_energy_2050), 4)
    sid = s.scenario_id(carbon, ev, bld)
    path = WEB_DATA / "scenarios" / f"{sid}.json"
    if path.exists():
        return sid, json.loads(path.read_text()), "precomputed grid"
    sid, record = s.one((carbon, ev, bld))
    return sid, record, "live run"


def reference() -> dict:
    return meta()["reference"]


def value(record: dict, path: tuple[str, ...], year: int) -> float:
    if year not in YEARS:
        raise ValueError(f"year must be {YEARS[0]} to {YEARS[-1]}")
    node = record
    for key in path:
        node = node[key]
    return float(node[YEARS.index(year)])


__all__ = ["LIMITS", "CARBON_WARN", "POLICY_START", "check_levers", "load", "reference", "value"]
