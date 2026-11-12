"""The page's instant estimate, in Python, so the agent and "Your America in 2050" give the same numbers.

web/data/ux2050/emulator.json is a polynomial in eight levers fitted to runs of the fast loop (scripts/build_ux2050.py),
shifted so EIA's settings return EIA's reference run. web/ux2050_model.js evaluates it in the browser; this module is the
same arithmetic. The two levers the page marks "real run only" (building codes, appliance standards) are not here: they
need the 12-minute run with EIA's ported buildings routines.
"""

import json
from functools import lru_cache

import numpy as np

from nems_open.agent.knowledge import WEB_DATA

# page lever name: (low, high, unit, what leaving it out means)
LEVERS = {
    "carbon_price": (0.0, 200.0, "2024 dollars per metric ton of CO2, from 2027", "no carbon price (EIA)"),
    "ev_2035": (0.25, 1.0, "plug-in share of new light-duty sales in 2035, 0.25 to 1", "EIA's path, about 0.65"),
    "load_growth": (0.0, 1000.0, "extra US electricity sales in 2050 from data centers and new load, TWh, linear from 2027",
                    "EIA's own load growth"),
    "coal_retirement": (0.0, 1.0, "share of EIA's coal fleet closed early, reached by 2035", "EIA's schedule"),
    "renewable_cost": (-1.0, 1.0, "wind and solar cost: -1 EIA's low-cost case, 0 reference, +1 EIA's high-cost case",
                       "EIA's reference"),
    "gas_supply": (-1.0, 1.0, "gas supply: -1 EIA's scarce case, 0 reference, +1 EIA's plentiful case", "EIA's reference"),
    "oil_price": (0.5, 2.0, "multiple of EIA's Brent oil price path, from 2027", "EIA's path"),
    "nuclear": (0.5, 1.5, "multiple of EIA's nuclear output, reached by 2040", "EIA's output"),
}
REAL_ONLY = ("building_code", "appliance_standard")
ALIASES = {"ev_share_2035": "ev_2035"}


@lru_cache(maxsize=1)
def data() -> dict:
    return json.loads((WEB_DATA / "ux2050" / "emulator.json").read_text(encoding="utf-8"))


def offs() -> dict:
    return {n: float(v["off"]) for n, v in data()["levers"].items()}


def check(levers: dict) -> dict:
    """Clean lever settings: page names, each inside its range. Raises ValueError with what to fix."""
    out, problems = {}, []
    for name, v in levers.items():
        name = ALIASES.get(name, name)
        if v is None:
            continue
        if name in REAL_ONLY:
            if float(v) != 0:
                problems.append(f"{name} is not available here: it needs the 12-minute run with EIA's ported buildings code")
            continue
        if name not in LEVERS:
            problems.append(f"unknown lever {name}; the levers are {', '.join(LEVERS)}")
            continue
        lo, hi = LEVERS[name][:2]
        if not lo <= float(v) <= hi:
            problems.append(f"{name} must be between {lo:g} and {hi:g}")
        out[name] = float(v)
    if problems:
        raise ValueError("; ".join(problems))
    return out


def _poly(x: dict) -> dict:
    e = data()
    names = list(e["levers"])
    z = [2 * (x[n] - e["levers"][n]["low"]) / (e["levers"][n]["high"] - e["levers"][n]["low"]) - 1 for n in names]
    f = np.array([np.prod([z[i] for i in t]) if t else 1.0 for t in e["terms"]])
    return {k: f @ np.array(c) for k, c in e["coef"].items()}


def run(levers: dict) -> dict:
    """{output name: 26 yearly values, 2025 to 2050} for these levers (omitted ones at EIA's settings)."""
    e = data()
    x = {**offs(), **check(levers)}
    raw, ref = _poly(x), _poly(offs())
    out = {}
    for k, v in raw.items():
        y = v - ref[k] + np.array(e["fast_reference"][k])
        out[k] = y if k.startswith("co2") else np.maximum(0, y)
    return out


def reference() -> dict:
    return {k: np.array(v) for k, v in data()["eia"].items()}


def error_pct(key: str) -> dict | None:
    return data()["error"].get(key)
