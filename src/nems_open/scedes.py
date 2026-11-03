"""Run options from a scenario's scedes file (what Fortran reads with RTOVALUE)."""

import re
import os
from functools import lru_cache

from nems_open.paths import UPSTREAM

SCENARIO = os.environ.get("NEMS_SCENARIO", "cb2026")      # "ref2025" with the AEO2025 checkout (see scripts/aeo_diff_run.py)


@lru_cache(maxsize=None)
def options(scenario: str = SCENARIO) -> dict:
    """{NAME: int} for every integer setting in scedes.<scenario>.csv."""
    out = {}
    path = UPSTREAM / "scedes" / f"scedes.{scenario}.csv"
    if not path.exists():
        # AEO2025 and earlier: scedes.<scenario> holds KEY=value lines
        for line in (UPSTREAM / "scedes" / f"scedes.{scenario}").read_text(encoding="latin-1").splitlines():
            key, eq, value = line.partition("=")
            if eq and not key.startswith("#") and re.fullmatch(r"-?\d+", value.strip()):
                out[key.strip().upper()] = int(value)
        return out
    for line in path.read_text(encoding="latin-1").splitlines():
        parts = line.split(",")
        if len(parts) >= 2 and not parts[0].startswith("#") and re.fullmatch(r"-?\d+", parts[1].strip()):
            out[parts[0].strip().upper()] = int(parts[1])
    return out


def option(name: str, default: int = 0, scenario: str = SCENARIO) -> int:
    """RTOVALUE(name, default): the option's value, or the default when the scedes file has none."""
    return options(scenario).get(name.upper(), default)
