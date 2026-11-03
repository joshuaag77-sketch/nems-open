"""The Short-Term Energy Outlook table the CMM reads (clsteo.txt) and the code that writes it.

NEMS regenerates models/coal/clsteo.txt every run from steovars.csv (steo_load.py,
`steovars_write_to_clsteo`). `shipped()` reads the file as it sits in the repo; `regenerate()` rebuilds
the same columns from steovars.csv with the existing STEO loader (nems_open.steo), so the two can be compared.
"""

import numpy as np

from nems_open import steo as _steo
from nems_open.coal import aimms_data as ad
from nems_open.coal.state import COAL_DIR

# clsteo column -> (steovars name, scale); ElecPriceSTEO is cleudus deflated back to nominal dollars.
COLUMNS = {
    "appalachialimit": "clprpar_ton", "interiorlimit": "clprpir_ton", "westlimit": "clprpwr_ton",
    "electonssteo": "clepcon_ton", "wastecoalsteo": "clwcpus_ton", "coketonssteo": "clkcpus_ton",
    "industrialtonssteo": "clycpus_ton", "cokingexpsteo": "clexpmc_ton", "steamexpsteo": "clexpsc_ton",
    "importssteo": "climp48_ton", "eoystocksepeast": "clps_ep_ne", "eoystocksepmidw": "clps_ep_mw",
    "eoystocksepsouth": "clps_ep_so", "eoystocksepwest": "clps_ep_we", "eoystocksprim": "clsdpus",
    "eoystockssecd": "clstpus",
}


def steo_def_1987() -> float:
    """The 1987 implicit price deflator, read from steovars.csv as steo_load.py does (53.126; its comment says 57.0045)."""
    from nems_open.paths import INPUT
    for line in (INPUT / "steovars.csv").read_text(encoding="latin-1").splitlines():
        if line.startswith("GDPDIUS,"):
            return float(line.split(",")[1 + 1987 - 1975])
    raise KeyError("GDPDIUS")


def shipped() -> dict[str, dict[int, float]]:
    """{column: {year: value}} from the clsteo.txt in the repo."""
    t = ad.parse_file(COAL_DIR / "clsteo.txt").tables[0]
    years = t.column("steoyr")
    return {h: dict(zip(years, t.column(h))) for h in t.headers if h != "steoyr"}


def regenerate() -> dict[str, dict[int, float]]:
    """The same columns built from steovars.csv (years 1990 up to the last year with data)."""
    v = _steo.load()
    out = {}
    last = max(shipped()["appalachialimit"])
    for col, name in COLUMNS.items():
        out[col] = {1990 + i: float(v[name][i]) for i in range(last - 1989)}
    d87 = steo_def_1987()
    out["elecpricesteo"] = {1990 + i: float(v["cleudus"][i] / d87 * v["gdpdius"][i])
                            for i in range(last - 1989)}
    return out
