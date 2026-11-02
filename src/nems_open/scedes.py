"""Run options from a scenario's scedes file (what Fortran reads with RTOVALUE)."""

import re
from functools import lru_cache

from nems_open.paths import UPSTREAM

SCENARIO = "cb2026"


@lru_cache(maxsize=None)
def options(scenario: str = SCENARIO) -> dict:
    """{NAME: int} for every integer setting in scedes.<scenario>.csv."""
    out = {}
    for line in (UPSTREAM / "scedes" / f"scedes.{scenario}.csv").read_text(encoding="latin-1").splitlines():
        parts = line.split(",")
        if len(parts) >= 2 and not parts[0].startswith("#") and re.fullmatch(r"-?\d+", parts[1].strip()):
            out[parts[0].strip().upper()] = int(parts[1])
    return out


def option(name: str, default: int = 0, scenario: str = SCENARIO) -> int:
    """RTOVALUE(name, default): the option's value, or the default when the scedes file has none."""
    return options(scenario).get(name.upper(), default)
