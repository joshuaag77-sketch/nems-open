"""Compare the HiGHS coal LP with EIA's coal model replayed in AIMMS (coal/aimms_run.py).

Two questions, kept apart:
  1. Does the replay reproduce the cb2026 restart? (EIA's model on converged inputs: production by supply region.)
  2. Given EIA's own supply curves for a year (FY_PROD_CAP3, SC_1_PRICE87, SC_QUAN from the replay's export),
     does our LP land on EIA's production? If so the LP translation holds and any remaining gap is in how our
     chain builds the curves (the lag state).

    python -m nems_open.coal.aimms_compare <run folder> 2025 2027 2030
"""

import sys
from pathlib import Path

import numpy as np

from nems_open.coal import aimms_run, electric, lp, steo, supply
from nems_open.snapshot import Snapshot

SREGS = ["1APN", "2APR", "3INR", "4LGN", "5PRB", "6WSR"]


def export(run: Path, year: int, itr: int) -> dict:
    return aimms_run.read_export(Path(run) / "coal" / "export" / f"coal_{year}_{itr:02d}.txt")


def last_itr(run: Path, year: int) -> int:
    got = sorted(Path(run, "coal", "export").glob(f"coal_{year}_*.txt"))
    return int(got[-1].stem.split("_")[-1])


def curve_key(k) -> tuple:
    return tuple(k[1:])            # (sreg, sulf, mtyp, rank)


def eia_curves(e: dict, year: int, keys: list, btu: np.ndarray) -> dict:
    """EIA's step quantities (Mt), step prices (1987$/MMBtu) and capacity (FY_PROD_CAP3 TBtu over Btu per ton) for one year, laid out like
    supply.Chain.year's output."""
    y = str(year)
    nstep = 11
    quan = np.zeros((len(keys), nstep))
    price = np.zeros((len(keys), nstep))
    cap = np.zeros(len(keys))
    for i, k in enumerate(keys):
        sc = str(k[0])
        for s in range(nstep):
            quan[i, s] = e["SC_QUAN"].get((sc,) + curve_key(k) + (str(s + 1), y), 0.0)
            price[i, s] = e["SC_1_PRICE87"].get((sc,) + curve_key(k) + (str(s + 1), y), 0.0)
        cap[i] = e["FY_PROD_CAP3"].get(curve_key(k) + (y,), 0.0)    # TBtu ("productive capacity in Btus")
    return dict(sc_quan=quan, sc_1_price87=price, cap=cap / btu)


def eia_production_mt(e: dict, year: int, keys: list, btu: np.ndarray) -> np.ndarray:
    pv = e["ProductionVolume"]
    return np.array([pv.get(curve_key(k) + (str(year),), 0.0) / btu[i] for i, k in enumerate(keys)])


def by_region(x: np.ndarray, keys: list) -> np.ndarray:
    sreg = np.array([k[1] for k in keys])
    return np.array([x[sreg == r].sum() for r in SREGS])


def compare(run: Path, years) -> list[dict]:
    s = Snapshot()
    ch = supply.Chain()
    btu, keys = ch.c.v["btu"], ch.keys
    st = steo.shipped()
    rows = []
    for y in years:
        e = export(run, y, last_itr(run, y))
        curves = eia_curves(e, y, keys, btu)
        bands = None
        if y in (2025, 2026):
            bands = dict(Appalachia=st["appalachialimit"][y], Interior=st["interiorlimit"][y], West=st["westlimit"][y])
        r = lp.solve(y, curves, btu, keys, lp.demands(y), steo=bands, power=electric.power_demand(y),
                     tier1=electric.tier1_bound(y, keys))
        ours = by_region(r["production_tons"], keys) if r["status"] == "ok" else np.full(6, np.nan)
        eia = by_region(eia_production_mt(e, y, keys, btu), keys)
        restart = np.asarray(s["COALREP/COALPROD2"])[10, :6, y - 1990]
        rows.append(dict(year=y, ours_on_eia_curves=ours, eia_replay=eia, restart=restart))
    return rows


def table(rows) -> str:
    lines = ["| year | Mt by region 1APN, 2APR, 3INR, 4LGN, 5PRB, 6WSR: our LP on EIA's curves / EIA replay / restart |", "|---|---|"]
    for r in rows:
        cells = ", ".join(f"{a:.0f}/{b:.0f}/{c:.0f}" for a, b, c in zip(r["ours_on_eia_curves"], r["eia_replay"], r["restart"]))
        tot = f"{r['ours_on_eia_curves'].sum():.0f}/{r['eia_replay'].sum():.0f}/{r['restart'].sum():.0f}"
        lines.append(f"| {r['year']} | {tot} ({cells}) |")
    return "\n".join(lines)


if __name__ == "__main__":
    print(table(compare(Path(sys.argv[1]), [int(a) for a in sys.argv[2:]])))
