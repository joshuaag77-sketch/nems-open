"""Capacity by region and fuel: the capacity expansion loop against the AEO2026 reference run.

Run:  python -m nems_open.emm.capacity_regions cache.pkl [out.md]

A cell is one region and one fuel group at the end of a year. It misses when the model is more than
TOLERANCE away from EIA and the gap is more than FLOOR_GW. Reported per fuel group: the national total error
and the share of the 25 regions that are inside tolerance.
"""

import pickle
import sys

import numpy as np

from nems_open.emm import dispatch, history
from nems_open.emm.regions import NUM_EMM
from nems_open.snapshot import Snapshot

TOLERANCE = 0.05
FLOOR_GW = 0.5
YEARS = (2027, 2030, 2035, 2050)
NATIONAL_YEAR = 2050          # national totals by fuel must be inside TOLERANCE in this year
# fuel group -> (restart groups, model groups)
FUELS = {
    "coal": (("coal", "coal_ccs"), ("coal", "coal_ccs")),
    "gas_cc": (("gas_cc", "gas_ccs"), ("gas_cc", "gas_cc_new", "gas_ccs")),
    "gas_ct": (("gas_ct",), ("gas_ct", "gas_ct_new")),
    "steam": (("steam",), ("steam", "gas_conv")),
    "wind": (("wind",), ("wind",)),
    "solar": (("solar",), ("solar",)),
    "battery": (("battery",), ("battery",)),
}


def model_capacity(results, year: int, groups) -> np.ndarray:
    r = next(r for r in results if r.year == year)
    return sum(r.capacity[g] for g in groups)


def compare(snapshot, results, years=YEARS) -> dict:
    """{(fuel, year): (model (25,), eia (25,))} in GW, for the years the results cover."""
    have = {r.year for r in results}
    years = [y for y in years if y in have]
    out = {}
    for fuel, (_, mg) in FUELS.items():
        for y in years:
            out[(fuel, y)] = (model_capacity(results, y, mg), _eia(snapshot, y, fuel))
    return out


def _eia(snapshot, year: int, fuel: str) -> np.ndarray:
    y = year - history.FIRST_YEAR
    P = dispatch.CAPACITY_PREFIXES
    u = lambda g: dispatch._ucap(snapshot, P[g], y)
    if fuel == "coal":
        return np.maximum(u("coal") - u("coal_ccs"), 0.0) + u("coal_ccs")       # coal without, plus with, CCS (initial_capacity's split)
    if fuel == "gas_cc":
        return u("gas_cc") + u("gas_ccs")
    return u(fuel)


def misses(model: np.ndarray, eia: np.ndarray) -> np.ndarray:
    gap = np.abs(model - eia)
    return (gap > FLOOR_GW) & (gap > TOLERANCE * np.abs(eia))


def table(cmp: dict) -> str:
    years = sorted({y for _, y in cmp})
    lines = ["| fuel | " + " | ".join(f"{y}: national model / EIA GW, regions inside {TOLERANCE:.0%}" for y in years) + " |",
             "|---|" + "---|" * len(years)]
    for fuel in FUELS:
        cells = []
        for y in years:
            m, e = cmp[(fuel, y)]
            ok = int((~misses(m, e)).sum())
            cells.append(f"{m.sum():.0f} / {e.sum():.0f} ({m.sum() / e.sum() - 1:+.0%}), {ok}/{NUM_EMM}")
        lines.append(f"| {fuel} | " + " | ".join(cells) + " |")
    total = {y: (sum((~misses(*cmp[(f, y)])).sum() for f in FUELS), NUM_EMM * len(FUELS)) for y in years}
    lines.append("| **all cells** | " + " | ".join(f"{a}/{b} inside" for a, b in total.values()) + " |")
    return "\n".join(lines)


def worst(cmp: dict, year: int, n: int = 10) -> str:
    rows = []
    for (fuel, y), (m, e) in cmp.items():
        if y != year:
            continue
        for r in range(NUM_EMM):
            rows.append((abs(m[r] - e[r]), fuel, r + 1, m[r], e[r]))
    rows.sort(reverse=True)
    return "\n".join(f"{fuel} region {r}: model {m:.1f}, EIA {e:.1f}" for _, fuel, r, m, e in rows[:n])


def national(cmp: dict, year: int = NATIONAL_YEAR) -> str:
    """National total by fuel in `year`, model against EIA, and whether it is inside TOLERANCE."""
    if not any(y == year for _, y in cmp):
        return ""
    rows = [f"National totals {year} (inside {TOLERANCE:.0%}?):"]
    for fuel in FUELS:
        m, e = (a.sum() for a in cmp[(fuel, year)])
        ok = abs(m - e) <= max(TOLERANCE * abs(e), FLOOR_GW)
        rows.append(f"{fuel}: {m:.0f} / {e:.0f} GW ({m / e - 1:+.0%}) {'inside' if ok else 'MISS'}")
    return "\n".join(rows)


def reserve_prices(snapshot, results, years=YEARS) -> str:
    """The capacity LP's reserve-margin dual against EIA's RMAVG (UECPOUT/rmavg, 1987$/kW-year, the average
    reserve price ECP paid), the one ECP dual that reaches the restart. Median over regions and correlation."""
    rm = snapshot["UECPOUT/rmavg"]
    rows = ["Reserve price, 1987$/kW-year (model / EIA RMAVG): median over regions, correlation across regions"]
    for r in results:
        if r.year not in years or r.reserve_price is None:
            continue
        eia = rm[r.year - 1990, :NUM_EMM]
        c = np.corrcoef(r.reserve_price, eia)[0, 1] if np.std(r.reserve_price) > 0 else float("nan")
        rows.append(f"{r.year}: {np.median(r.reserve_price):.1f} / {np.median(eia):.1f}, r = {c:.2f}")
    return "\n".join(rows)


def main(cache: str, out: str | None = None):
    results = pickle.load(open(cache, "rb"))
    cmp = compare(Snapshot(), results)
    last = max(y for _, y in cmp)
    text = table(cmp) + f"\n\nLargest gaps in {last}:\n" + worst(cmp, last)
    nat = national(cmp)
    if nat:
        text += "\n\n" + nat
    if getattr(results[0], "reserve_price", None) is not None:
        text += "\n\n" + reserve_prices(Snapshot(), results)
    print(text)
    if out:
        open(out, "w").write(text + "\n")


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else None)
