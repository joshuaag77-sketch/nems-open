"""Run a scenario: the page's instant estimate (agent/emulator.py), the same numbers "Your America in 2050" shows.

A scenario is a set of lever settings; its record holds every output by year, 2025 to 2050, and EIA's reference run
sits beside it. Instant, so a question can compare several.
"""

from nems_open.agent import emulator as E
from nems_open.agent.knowledge import POLICY_START, YEARS, Measure

CARBON_WARN = 100.0     # docs/supply_standin.md: results above $100 are extrapolation


def scenario_id(levers: dict) -> str:
    return ";".join(f"{k}={v:g}" for k, v in sorted(levers.items())) or "eia_reference"


def run(levers: dict) -> tuple[str, dict]:
    clean = E.check(levers)
    return scenario_id(clean), E.run(clean)


def _at(arrays: dict, m: Measure, year: int) -> float:
    if year not in YEARS:
        raise ValueError(f"year must be {YEARS[0]} to {YEARS[-1]}")
    i = YEARS.index(year)
    return float(sum(arrays[k][i] for k in m.path))


def value(record: dict, m: Measure, year: int) -> float:
    return _at(record, m, year)


def reference_value(m: Measure, year: int) -> float:
    return _at(E.reference(), m, year)


__all__ = ["CARBON_WARN", "POLICY_START", "run", "scenario_id", "value", "reference_value"]
