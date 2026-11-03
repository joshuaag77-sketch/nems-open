"""What the agent knows about the model, read from the repo's own data files.

    web/data/fidelity.json   grade of every piece (matches EIA / our own model / fitted stand-in) and of every number
    web/data/engine.json     what each module is, its EIA source and ours
    web/data/meta.json       the demo's policy grid and EIA's reference run
    web/data/uncertainty.json  sampled bands

Nothing here is written by hand about the model's accuracy: grades and gaps come from fidelity.json.
"""

import json
from dataclasses import dataclass
from functools import lru_cache

from nems_open.paths import REPO_ROOT

WEB_DATA = REPO_ROOT / "web" / "data"
YEARS = list(range(2025, 2051))        # the years the demo's runs report (policy starts in 2027)
POLICY_START = 2027
RUN_SET = "fast"                       # the all-stand-in loop the agent runs

# worst first: a number is as good as the weakest piece behind it
GRADE_ORDER = {"stand": 0, "within": 1, "match": 2}
GRADE_WORDS = {"stand": "stand-in", "within": "our own model", "match": "matches EIA"}


@lru_cache(maxsize=None)
def _load(name: str) -> dict:
    return json.loads((WEB_DATA / name).read_text(encoding="utf-8"))


def fidelity() -> dict:
    return _load("fidelity.json")


def engine() -> dict:
    return _load("engine.json")


def meta() -> dict:
    return _load("meta.json")


def uncertainty() -> dict:
    return _load("uncertainty.json")


@dataclass(frozen=True)
class Measure:
    key: str
    label: str
    unit: str
    variable: str                      # the model variable or definition behind the number
    modules: tuple[str, ...]           # fidelity modules the number passes through
    output: str | None                 # fidelity output row, when there is one
    path: tuple[str, ...]              # where the value sits in a scenario record
    digits: int = 1


MEASURES = {m.key: m for m in (
    Measure("co2", "US energy CO2", "million metric tons CO2 a year",
            "RunResult.co2_total: fuel use times EIA's carbon factors (EMEBLK), scaled to EIA's sector carbon",
            ("residential", "commercial", "industrial", "transportation", "electricity", "natural_gas", "oil", "coal",
             "emissions"), "co2", ("co2",), 0),
    Measure("electricity_price", "Average electricity price", "cents per kWh, 2024 dollars", "MPBLK/pelas",
            ("electricity:price", "residential", "commercial", "industrial", "transportation"), "pel",
            ("prices", "electricity"), 2),
    Measure("gas_home_price", "Natural gas price to homes", "dollars per MMBtu, 2024 dollars", "MPBLK/pngrs",
            ("natural_gas",), "ng", ("prices", "gas_home"), 2),
    Measure("gasoline_price", "Gasoline price", "dollars per gallon, 2024 dollars", "MPBLK/pmgtr",
            ("oil",), "mg", ("prices", "gasoline"), 2),
    Measure("diesel_price", "Diesel price", "dollars per gallon, 2024 dollars", "MPBLK/pdstr",
            ("oil",), None, ("prices", "diesel"), 2),
    Measure("gasoline_use", "Gasoline use", "billion gallons a year", "QBLK/qmgtr (motor gasoline, transportation)",
            ("transportation", "oil"), "gal", ("gasoline_bgal",), 1),
    Measure("power_sales", "Electricity sold to end users", "quads a year", "QBLK/qelas",
            ("electricity", "residential", "commercial", "industrial", "transportation"), None, ("power_sales",), 2),
    Measure("energy_residential", "Residential energy use", "quads a year", "QBLK/qtsrs",
            ("residential",), "energy.residential", ("energy", "residential"), 2),
    Measure("energy_commercial", "Commercial energy use", "quads a year", "QBLK/qtscm",
            ("commercial",), "energy.commercial", ("energy", "commercial"), 2),
    Measure("energy_industrial", "Industrial energy use", "quads a year", "QBLK/qtsin",
            ("industrial",), "energy.industrial", ("energy", "industrial"), 2),
    Measure("energy_transportation", "Transportation energy use", "quads a year", "QBLK/qtstr",
            ("transportation",), "energy.transportation", ("energy", "transportation"), 2),
)}


def describe(measure: Measure) -> dict:
    """Where a measure comes from and how much to trust it: modules, grade of each, the weakest, EIA's gap."""
    fid = fidelity()
    mods = fid["sets"][RUN_SET]["modules"]
    out = fid["sets"][RUN_SET]["outputs"].get(measure.output) if measure.output else None
    parts = []
    for m in measure.modules:
        part_key = mods[m]["part"]
        part = fid["parts"][part_key]
        eng = engine()["modules"].get(m.split(":")[0], {})
        parts.append({"module": m, "name": part["name"], "grade": part["grade"], "grade_label": GRADE_WORDS[part["grade"]],
                      "what_it_is": part["summary"], "kind": eng.get("kind"), "side": eng.get("side")})
    weakest = min(parts, key=lambda p: GRADE_ORDER[p["grade"]])
    return {"measure": measure.key, "label": measure.label, "variable": measure.variable, "unit": measure.unit,
            "modules": parts, "grade": weakest["grade"], "grade_label": GRADE_WORDS[weakest["grade"]],
            "weakest_module": weakest["name"],
            "gap_vs_eia_pct": out.get("gap_pct") if out else None,
            "gap_summary": out["summary"] if out else None}


def stand_in_modules(descriptions: list[dict]) -> list[dict]:
    """The distinct modules below 'matches EIA' across some measure descriptions."""
    seen, out = set(), []
    for d in descriptions:
        for p in d["modules"]:
            if p["grade"] != "match" and p["name"] not in seen:
                seen.add(p["name"])
                out.append(p)
    return out
