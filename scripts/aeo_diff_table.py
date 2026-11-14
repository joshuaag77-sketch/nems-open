"""EIA's own AEO2025 reference run against its AEO2026 one: headline national changes, from the two restart files.

    python -I scripts/aeo_diff_table.py > table.md

Needs data/aeo2025/restart2025.npz (see docs/aeo_diff.md for how it is made from EIA's ref2025.zip).
"""

import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from nems_open.snapshot import Snapshot  # noqa: E402

US = 10
YEARS = (2030, 2035, 2040, 2050)
ROWS = [
    ("Residential delivered energy, TBtu", "QBLK/qtsrs", US),
    ("Commercial delivered energy, TBtu", "QBLK/qtscm", US),
    ("Industrial delivered energy, TBtu", "QBLK/qtsin", US),
    ("Transportation delivered energy, TBtu", "QBLK/qtstr", US),
    ("Electric power sector energy, TBtu", "QBLK/qtsel", US),
    ("Residential electricity, TBtu", "QBLK/qelrs", US),
    ("Commercial electricity, TBtu", "QBLK/qelcm", US),
    ("Residential natural gas, TBtu", "QBLK/qngrs", US),
    ("Commercial natural gas, TBtu", "QBLK/qngcm", US),
    ("Residential electricity price, restart price units", "AMPBLK/pelrs", US),
    ("Commercial electricity price, restart price units", "AMPBLK/pelcm", US),
    ("Industrial electricity price, restart price units", "AMPBLK/pelin", US),
    ("Real GDP (MC_GDPR)", "MACOUT/mc_gdpr", None),
]


def main():
    a, b = Snapshot(ROOT / "data" / "aeo2025" / "restart2025.npz"), Snapshot()
    print("| | " + " | ".join(f"{y}: AEO2025 / AEO2026 (change)" for y in YEARS) + " |")
    print("|---|" + "---|" * len(YEARS))
    for label, key, region in ROWS:
        cells = []
        for y in YEARS:
            j = y - 1990
            x, z = (float(s[key][region, j]) if region is not None else float(s[key][j]) for s in (a, b))
            cells.append(f"{x:,.1f} / {z:,.1f} ({(z / x - 1) * 100:+.1f}%)")
        print(f"| {label} | " + " | ".join(cells) + " |")


if __name__ == "__main__":
    main()
