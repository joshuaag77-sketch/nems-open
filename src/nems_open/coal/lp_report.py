"""Run the reduced coal LP year by year and compare with the cb2026 restart.

    python -m nems_open.coal.lp_report [first_year last_year ...]
"""

import sys

import numpy as np

from nems_open.coal import electric, lp, steo, supply
from nems_open.snapshot import Snapshot

EAST = ("1APN", "2APR", "3INR")
SECTORS = {"PCLEL": ("E",), "PCLIN": ("I1", "I2", "I3"), "PMCIN": ("C1", "C2"), "PCLRS": ("R1", "R2")}


def run(years, steo_years=(2025, 2026), by_type: bool = True):
    """by_type: electricity demand per plant type with EIA's diversity caps (electric.py); False: one per region."""
    s = Snapshot()
    ch = supply.Chain()
    btu, keys = ch.c.v["btu"], ch.keys
    sreg = np.array([k[1] for k in keys])
    st = steo.shipped()
    rows = []
    for y in range(2025, max(years) + 1):
        step = ch.year(y)
        dem = lp.demands(y)
        bands = None
        if y in steo_years:
            bands = dict(Appalachia=st["appalachialimit"][y], Interior=st["interiorlimit"][y], West=st["westlimit"][y])
        power = electric.power_demand(y) if by_type else None
        r = lp.solve(y, step, btu, keys, dem, steo=bands, power=power)
        if r["status"] != "ok":
            rows.append(dict(year=y, status=r["status"]))
            break
        ch.settle(r["production_tons"])
        if y not in years:
            continue
        yi = y - 1990
        tb = r["production_tbtu"]
        ref_reg = np.asarray(s["COALREP/COALPROD2"])[10, :6, yi]
        reg = np.array([r["production_tons"][sreg == x].sum() for x in dem.sregs])
        east = tb[np.isin(sreg, EAST)].sum()
        out = dict(year=y, status="ok", objective=r["objective"], prod_mt=reg, ref_mt=ref_reg,
                   east=east, west=tb.sum() - east, ref_east=float(s["COALOUT/CQSBB"][0, yi]), ref_west=float(s["COALOUT/CQSBB"][1, yi]))
        for name, secs in SECTORS.items():
            num = den = 0.0
            for (sec, d), v in r["dual"].items():
                if sec in secs:
                    w = dem.elec[d] if sec == "E" else dem.other[sec][d]
                    num, den = num + v * w, den + w
            out[name] = (num / den if den else np.nan, float(s[f"MPBLK/{name}"][10, yi]))
        out["slack"] = sum(r.get("slack", {}).values())
        rows.append(out)
    return rows


def table(rows) -> str:
    lines = ["| year | production Mt (model / EIA); by region 1APN, 2APR, 3INR, 4LGN, 5PRB, 6WSR | delivered price 1987$/MMBtu (model / EIA) |", "|---|---|---|"]
    for r in rows:
        if r["status"] != "ok":
            lines.append(f"| {r['year']} | {r['status']} | |")
            continue
        pm, pr = r["prod_mt"].sum(), r["ref_mt"].sum()
        pr_s = ", ".join(f"{a:.0f}/{b:.0f}" for a, b in zip(r["prod_mt"], r["ref_mt"]))
        pcs = "; ".join(f"{n} {r[n][0]:.2f}/{r[n][1]:.2f}" for n in ("PCLEL", "PCLIN", "PMCIN"))
        lines.append(f"| {r['year']} | {pm:.0f} / {pr:.0f} ({pr_s}) | {pcs} |")
    return "\n".join(lines)


if __name__ == "__main__":
    flat = "--flat" in sys.argv
    ys = [int(a) for a in sys.argv[1:] if a != "--flat"] or [2025, 2026, 2030, 2035]
    print(table(run(ys, by_type=not flat)))
