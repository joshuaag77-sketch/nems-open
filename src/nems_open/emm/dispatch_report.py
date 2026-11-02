"""Compare dispatch results with the AEO2026 reference run and write a table.

Run:  python -m nems_open.emm.dispatch_report [out.md]
"""

import sys
from pathlib import Path

import numpy as np

from nems_open.emm import dispatch, history
from nems_open.snapshot import Snapshot

YEARS = (2025, 2030, 2040, 2050)
TOLERANCE = 0.10
NUM_R = dispatch.NUM_R


def reference(snapshot, year: int) -> dict:
    """Reference-run totals for the 25 EMM regions: generation (TWh), fuel for power (trillion Btu), CO2 (Mt)."""
    y = year - history.FIRST_YEAR

    def ugn(*names):
        return sum(float(snapshot[f"UEFDOUT/{n}"][:, :NUM_R, y].sum()) for n in names)

    return {
        "gen_coal": ugn("ugnclnr", "ugncfnr"),
        "gen_gas": ugn("ugngfnr", "ugnginr", "ugngcnr"),
        "gen_oil": ugn("ugndsnr", "ugnrlnr"),
        "gen_nuclear": ugn("ugnurnr"),
        "gen_renewable": ugn("ugnhonr"),
        "gen_total": ugn("ugntlnr"),
        "fuel_coal": float(snapshot["QBLK/qclel"][10, y]),
        "fuel_gas": float(snapshot["QBLK/qngel"][10, y]),
        "fuel_oil": float(snapshot["QBLK/qdsel"][10, y] + snapshot["QBLK/qrsel"][10, y]),
        "co2": float(snapshot["UEFDOUT/utco2"][27, y]),
    }


def model(result: dispatch.DispatchResult) -> dict:
    g = {k: float(v.sum()) for k, v in result.generation_twh.items()}
    f = {k: float(v.sum()) for k, v in result.fuel_tbtu.items()}
    return {
        "gen_coal": g["coal"],
        "gen_gas": g["gas_cc"] + g["gas_ct"] + g["steam"] * (1 - float(np.average(result.case.oil_share["steam"]))),
        "gen_oil": g["steam"] * float(np.average(result.case.oil_share["steam"])),
        "gen_nuclear": g["nuclear"],
        "gen_renewable": g["hydro"] + g["wind"] + g["solar"] + g["other"],
        "gen_total": sum(g.values()),
        "fuel_coal": f["coal"], "fuel_gas": f["gas"], "fuel_oil": f["distillate"] + f["residual"],
        "co2": float(result.co2_mt.sum()),
    }


LABELS = [
    ("gen_coal", "Coal generation, TWh"), ("gen_gas", "Gas generation, TWh"), ("gen_oil", "Oil generation, TWh"),
    ("gen_nuclear", "Nuclear generation, TWh"), ("gen_renewable", "Renewable generation, TWh"),
    ("gen_total", "Total generation, TWh"), ("fuel_coal", "Coal use, trillion Btu"),
    ("fuel_gas", "Gas use, trillion Btu"), ("fuel_oil", "Oil use, trillion Btu"), ("co2", "Power CO2, Mt"),
]
# Rows held to the 10% tolerance; oil is tiny, so it is reported but not scored.
SCORED = {"gen_coal", "gen_gas", "gen_nuclear", "gen_renewable", "fuel_coal", "fuel_gas", "co2"}
# A row only counts as a miss when it is also off by more than this share of the national total
# (generation rows: of total generation; fuel rows: of total fuel; CO2: of itself). This keeps a
# fuel that has faded to nothing, like coal in 2050, from failing on a 10 TWh difference.
FLOOR = 0.005


def is_miss(key: str, m: dict, r: dict) -> bool:
    if key not in SCORED or r[key] == 0:
        return False
    rel = abs(m[key] / r[key] - 1)
    if key.startswith("gen_"):
        scale = r["gen_total"]
    elif key.startswith("fuel_"):
        scale = r["fuel_coal"] + r["fuel_gas"] + r["fuel_oil"]
    else:
        scale = r[key]
    return rel > TOLERANCE and abs(m[key] - r[key]) > FLOOR * scale


def run(snapshot, trade: str, years=YEARS) -> dict:
    out = {}
    for yr in years:
        res = dispatch.solve(dispatch.build_case(snapshot, yr, trade))
        out[yr] = (model(res), reference(snapshot, yr), res)
    return out


def table(results: dict, trade: str) -> str:
    years = list(results)
    lines = [f"### Regional net load: {trade}", "",
             "| Quantity | " + " | ".join(f"{y} model / EIA (miss)" for y in years) + " |",
             "|---|" + "---|" * len(years)]
    for key, label in LABELS:
        cells = []
        for y in years:
            m, r, _ = results[y]
            err = m[key] / r[key] - 1 if r[key] else float("nan")
            flag = " MISS" if is_miss(key, m, r) else ""
            cells.append(f"{m[key]:,.0f} / {r[key]:,.0f} ({err:+.0%}){flag}")
        lines.append(f"| {label} | " + " | ".join(cells) + " |")
    prices = [float((results[y][2].average_price() * results[y][2].case.net_load_twh).sum() / results[y][2].case.net_load_twh.sum()) for y in years]
    lines.append("| Load-weighted marginal cost, 1987$/MWh (model only) | " + " | ".join(f"{p:,.1f}" for p in prices) + " |")
    return "\n".join(lines)


def main(path=None):
    snap = Snapshot()
    parts = []
    for trade in ("reference", "none"):
        parts.append(table(run(snap, trade), trade))
    text = "\n\n".join(parts)
    print(text)
    if path:
        Path(path).write_text(text + "\n", encoding="utf-8")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else None)
