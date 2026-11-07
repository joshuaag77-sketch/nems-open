"""Ten plain levers on the full model, what each one moves, and how real that move is.

Each lever is a field on `Policy` (demand_adapter.py) in plain units. This file holds the plain-word
registry (LEVERS), the grade of each lever for a given run (`fidelity`, `label`), and the arithmetic
that turns the supply-side levers into moves on the stand-in or the dispatch LP.

Three grades, the words the fidelity scoreboard uses for pieces of the model:

  ported      edits a real input table of a routine ported from EIA's Fortran; the routines respond
  own model   acts on our dispatch LP, built on EIA's data but not EIA's electricity model
  stand-in    moves a curve fitted to EIA's runs, or scales EIA's side cases; no EIA routine responds

A grade says what the lever acts on, not that the size of the response was checked against EIA: EIA
published no run for most of these. Where a lever needs a port that this run left out, `fidelity`
says so. `python -m nems_open.levers` prints the table.
"""

from dataclasses import dataclass

import numpy as np

from nems_open.supply_standin.data import FIRST_YEAR, LAST_YEAR, NYEARS, US, load_case
from nems_open.supply_standin.model import SupplyShifts

REFERENCE = "cb2026"
COAL_FULL_BY = 2035      # the coal retirement lever reaches its full size here, linearly from start_year
NUCLEAR_FULL_BY = 2040   # reactors take longer to build than to close
# Btu burned per Btu of electricity (kWh = 3,412 Btu), to turn lost fuel into lost generation.
# Nuclear: the default in emm/dispatch.py. Coal: about the US fleet average.
NUCLEAR_HEAT_RATIO = 10400.0 / 3412.0
COAL_HEAT_RATIO = 10500.0 / 3412.0
TBTU_PER_TWH = 3.412
GAS_FUELS = ("ng", "gf", "gi")
GROUPS_OF_REFERENCE_ROW = {"wind": "QBLK/qwiel", "solar": "QBLK/qpvel"}


@dataclass(frozen=True)
class Lever:
    name: str            # the field on Policy
    title: str
    unit: str
    off: object          # the value that changes nothing
    example: object      # a value that shows the lever working
    moves: str           # the real inputs it moves


LEVERS = {v.name: v for v in (
    Lever("carbon_price", "Carbon price", "2024 $ per metric ton CO2, from start_year", 0.0, 50.0,
          "Delivered fossil prices by carbon content, power plants' fuel costs"),
    Lever("ev_share", "EV sales", "plug-in share of new light-duty sales, 0-1 (EIA's reference: 0.49 in 2030, 0.65 in 2035)", None, 0.9,
          "With TRAN: the plug-ins' utility in TALT2X, the powertrain choice. Stub: gasoline to electricity as the fleet turns over"),
    Lever("building_code", "Building codes", "fraction less heating and cooling need in new buildings", 0.0, 0.3,
          "Commercial KSHEFF shell factors; residential RSMSHL HTSHEFF and CLSHEFF"),
    Lever("appliance_standard", "Appliance standards",
          "fraction more efficient than the least efficient equipment on offer", 0.0, 0.2,
          "Commercial KTEK availability years; residential RSMEQP RTEQEFF, RTEQCOST, RTRECOST"),
    Lever("coal_retirement", "Coal retirements", f"share of EIA's coal fleet closed early, reached by {COAL_FULL_BY}", 0.0, 0.5,
          "LP: coal capacity. Stand-in: coal burn, made up by the fitted mix of what meets new sales"),
    Lever("renewable_cost", "Renewable cost", "-1 EIA's low zero-carbon cost case, 0 reference, +1 EIA's high case", 0.0, -1.0,
          "LP: wind and solar capacity as in EIA's case. Stand-in: power-sector fuel use and retail electricity prices as in EIA's case"),
    Lever("load_growth", "Load growth", "TWh of extra US electricity sales in 2050, linear from start_year", 0.0, 500.0,
          "Commercial electricity sales (QBLK/qelcm), by division as EIA splits them"),
    Lever("gas_supply", "Gas supply", "-1 EIA's low oil and gas supply case, 0 reference, +1 EIA's high case", 0.0, 1.0,
          "Delivered gas and retail electricity prices by that case's (its oil price is the oil lever's)"),
    Lever("oil_price", "Oil price", "multiple of EIA's Brent price, from start_year", 1.0, 1.25,
          "INTOUT/brent_price, passed through to refined product prices dollar for dollar"),
    Lever("nuclear", "Nuclear", f"multiple of EIA's nuclear output, reached by {NUCLEAR_FULL_BY}", 1.0, 1.25,
          "LP: nuclear capacity. Stand-in: uranium burn, the change met by the fitted mix"),
)}

PORTED, OWN_MODEL, STAND_IN = "ported", "own model", "stand-in"


def fidelity(name: str, ported: tuple = (), elec: str = "standin") -> tuple[str, str]:
    """(grade, why) for this lever in a run with these ported sectors and this electricity model."""
    if name not in LEVERS:
        raise KeyError(name)
    lp = elec == "lp"
    if name == "carbon_price":
        if lp:
            return OWN_MODEL, "Power plants respond in the dispatch LP; delivered prices come from the stand-in"
        return STAND_IN, "Prices and power plants' fuel switching come from fitted curves"
    if name == "ev_share":
        if "transportation" in ported:
            return PORTED, "Acts through the vehicle choice in ported TRAN"
        return STAND_IN, "Transportation is not ported in this run: a fleet-turnover estimate moves its fuel use"
    if name in ("building_code", "appliance_standard"):
        have = [s for s in ("residential", "commercial") if s in ported]
        if len(have) == 2:
            return PORTED, "Edits input tables of ported residential and commercial routines"
        if have:
            return PORTED, f"Edits input tables of the ported {have[0]} routines; the other building sector is not moved"
        return STAND_IN, "Needs a ported buildings sector: this run has none, so the lever is refused"
    if name == "coal_retirement":
        if lp:
            return OWN_MODEL, "Removes coal capacity in the dispatch LP, which then redispatches; no plant-by-plant choice"
        return STAND_IN, "Moves coal burn by a fitted mix; no plants close in the model"
    if name == "nuclear":
        if lp:
            return OWN_MODEL, "Scales nuclear capacity in the dispatch LP, which then redispatches; no build cost"
        return STAND_IN, "Moves uranium burn by a fitted mix; no reactors in the model, no build cost"
    if name == "renewable_cost":
        if lp:
            return OWN_MODEL, "Wind and solar capacity from EIA's side case go into the dispatch LP; no capacity choice from cost"
        return STAND_IN, "Scales EIA's side case for power-sector fuel use; no cost enters any model"
    if name == "load_growth":
        if lp:
            return OWN_MODEL, "Extra sales added by hand; the dispatch LP serves them, the stand-in prices them"
        return STAND_IN, "Extra sales added by hand; a fitted mix and fitted prices respond"
    if name == "gas_supply":
        return STAND_IN, "Scales delivered gas prices toward EIA's side case; no gas market model runs"
    return STAND_IN, "Crude passes through to product prices dollar for dollar; no world oil or refining model runs"


def label(name: str, ported: tuple = (), elec: str = "standin") -> str:
    """The lever's name as a page shows it: a lever that does not act on ported code says so."""
    grade, _ = fidelity(name, ported, elec)
    title = LEVERS[name].title
    return title if grade == PORTED else f"{title} ({grade})"


def table(ported: tuple = (), elec: str = "standin") -> list[dict]:
    return [{"name": v.name, "title": v.title, "label": label(v.name, ported, elec), "unit": v.unit,
             "moves": v.moves, "grade": fidelity(v.name, ported, elec)[0], "why": fidelity(v.name, ported, elec)[1]}
            for v in LEVERS.values()]


def ramp(value, start_year: int, full_year: int, off: float) -> np.ndarray:
    """A lever by year 1990-2050: off until start_year, linear to value by full_year, then value.
    An array is taken as already by year."""
    a = np.asarray(value, dtype=np.float64)
    if a.ndim:
        return a
    out = np.full(NYEARS, off, dtype=np.float64)
    for y in range(start_year, LAST_YEAR + 1):
        out[y - FIRST_YEAR] = off + (a - off) * min(1.0, (y - start_year + 1) / max(1, full_year - start_year + 1))
    return out


def _side_case(weight: float, low: str, high: str) -> tuple[dict, float]:
    """The side case a weight points to and how far along: -1 is `low`, +1 is `high`."""
    if not -1.0 <= weight <= 1.0:
        raise ValueError(f"a side-case lever runs from -1 to 1, got {weight}")
    return load_case(low if weight < 0 else high), abs(weight)


def _price_ratio(case: dict, ref: dict, name: str) -> np.ndarray:
    return np.divide(case[name], ref[name], out=np.ones_like(ref[name]), where=(ref[name] > 0) & (case[name] > 0))


def _electricity_prices(supply, case: dict, w: float, from_start: np.ndarray) -> dict:
    """Retail electricity prices toward the side case. The fitted curves barely follow the gas price
    for homes (0.001), so they miss what EIA's case shows; this adds the case's move, less what
    the curve already gives through the gas price to power plants."""
    ref = load_case(REFERENCE)
    gas = np.log(_price_ratio(case, ref, "MPBLK/pngel"))
    out = {}
    for name in supply.base:
        if name.startswith("MPBLK/pel") and name in case:
            coef = supply.price_coef.get(name, {}).get("pngel", 0.0)
            out[name] = np.where(from_start, np.exp(w * (np.log(_price_ratio(case, ref, name)) - coef * gas)), 1.0)
    return out


def _replacement(supply, generation_lost: np.ndarray, skip: str) -> dict:
    """Fuel that makes up lost generation (trillion Btu by year, US): each fuel's fitted share per
    Btu of new sales (power_mix), split over regions as in the baseline."""
    out = {}
    for name, m in supply.power_mix.items():
        if name == skip:
            continue
        b = supply.base[name]
        share = np.divide(b, b[US], out=np.zeros_like(b), where=b[US] > 0)
        out[name] = share * (m * generation_lost)
    return out


def _add(into: dict, more: dict) -> None:
    for k, v in more.items():
        into[k] = into[k] + v if k in into else v


def supply_shifts(policy, supply) -> SupplyShifts | None:
    """The stand-in's moves for this policy, or None if it asks for none."""
    base, start = supply.base, policy.start_year
    price, power = {}, {}
    from_start = np.zeros(NYEARS, dtype=bool)
    from_start[start - FIRST_YEAR:] = True
    if policy.gas_supply:
        case, w = _side_case(policy.gas_supply, "lowogs", "highogs")
        ref = load_case(REFERENCE)
        for name in base:
            if name.startswith("MPBLK/p") and name[7:9] in GAS_FUELS and name in case:
                price[name] = np.where(from_start, _price_ratio(case, ref, name) ** w, 1.0)
        price.update(_electricity_prices(supply, case, w, from_start))
    if policy.renewable_cost:
        case, w = _side_case(policy.renewable_cost, "lowztc", "highztc")
        ref = load_case(REFERENCE)
        for name in supply.power_mix:
            _add(power, {name: np.where(from_start, w * (case[name] - ref[name]), 0.0)})
        price.update(_electricity_prices(supply, case, w, from_start))
    f = coal_share(policy)
    if f.any():
        coal = base["QBLK/qclel"]
        _add(power, {"QBLK/qclel": -f * coal, "QBLK/qtsel": -f * coal})
        _add(power, _replacement(supply, f * coal[US] / COAL_HEAT_RATIO, "QBLK/qclel"))
    n = nuclear_multiple(policy)
    if (n != 1.0).any():
        d = (n - 1.0) * base["QBLK/qurel"]
        _add(power, {"QBLK/qurel": d, "QBLK/qtsel": d})
        _add(power, _replacement(supply, -d[US] / NUCLEAR_HEAT_RATIO, "QBLK/qurel"))
    return SupplyShifts(price, power) if price or power else None


def coal_share(policy) -> np.ndarray:
    return ramp(policy.coal_retirement, policy.start_year, COAL_FULL_BY, 0.0)


def nuclear_multiple(policy) -> np.ndarray:
    return ramp(policy.nuclear, policy.start_year, NUCLEAR_FULL_BY, 1.0)


def brent(policy, base: dict) -> np.ndarray | None:
    """Brent by year, 1987 $/bbl, or None for the baseline's."""
    m = ramp(policy.oil_price, policy.start_year, policy.start_year, 1.0)
    return None if (m == 1.0).all() else base["INTOUT/brent_price"] * m


def load_added(policy, base: dict, j: int) -> np.ndarray:
    """Extra commercial electricity sales in year index j, trillion Btu by region (US row included)."""
    twh = ramp(policy.load_growth, policy.start_year, LAST_YEAR, 0.0)[j]
    b = base["QBLK/qelcm"][:, j]
    return np.divide(b, b[US], out=np.zeros_like(b), where=b[US] > 0) * (twh * TBTU_PER_TWH)


def capacity_scale(policy):
    """year -> {group: capacity multiplier} for the dispatch LP, or None if the policy asks for none."""
    f, n = coal_share(policy), nuclear_multiple(policy)
    w = policy.renewable_cost
    ratio = {}
    if w:
        case, a = _side_case(w, "lowztc", "highztc")
        ref = load_case(REFERENCE)
        for group, row in GROUPS_OF_REFERENCE_ROW.items():
            r = np.divide(case[row][US], ref[row][US], out=np.ones(NYEARS), where=ref[row][US] > 0)
            ratio[group] = np.where(np.arange(NYEARS) >= policy.start_year - FIRST_YEAR, 1.0 + a * (r - 1.0), 1.0)
    if not (f.any() or (n != 1.0).any() or ratio):
        return None

    def scale(year: int) -> dict:
        j = year - FIRST_YEAR
        out = {"coal": 1.0 - float(f[j]), "coal_ccs": 1.0 - float(f[j]), "nuclear": float(n[j])}
        out.update({g: float(r[j]) for g, r in ratio.items()})
        return out
    return scale


def main() -> None:
    ported = ("residential", "commercial")
    print(f"Default run (ported: {', '.join(ported)}; electricity: stand-in)\n")
    for row in table(ported):
        print(f"{row['label']:32} {row['grade']:10} {row['why']}\n{'':32} units: {row['unit']}\n{'':32} moves: {row['moves']}\n")


if __name__ == "__main__":
    main()
