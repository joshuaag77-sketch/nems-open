"""AEO2026 scenario data for the supply stand-in.

Source: EIA's own finished runs of the 11 published AEO2026 cases, which ship in the
upstream NEMS release as restart files (`output/aeo2026/<case>/<run>/restart.rlx`, a
numpy .npz archive under another name). They hold every regional price and quantity
NEMS passes between modules, under the same names our ports use (MPBLK, QBLK), so
no API key is needed. The published AEO tables (api.eia.gov/v2/aeo/2026, or the bulk
file www.eia.gov/opendata/bulk/AEO2026.zip) are reports built from these same runs.

Refetch the cache (git-ignored) with:

    python -m nems_open.supply_standin.data [path/to/nems-upstream]

It writes one small .npz per case to data/aeo2026/.
"""

import sys
from pathlib import Path

import numpy as np

from nems_open.paths import REPO_ROOT, UPSTREAM

CACHE = REPO_ROOT / "data" / "aeo2026"

FIRST_YEAR = 1990  # year index 0 in every (region, year) array
LAST_YEAR = 2050
NYEARS = LAST_YEAR - FIRST_YEAR + 1
US = 10  # region index of the national total; 0-8 are the census divisions, 9 is unused

CASES = {
    "cb2026": "Reference (EIA calls it the Counterfactual Baseline)",
    "hm2026": "High Economic Growth",
    "lm2026": "Low Economic Growth",
    "higheldmd": "High Electricity Demand",
    "highogs": "High Oil and Gas Supply",
    "lowogs": "Low Oil and Gas Supply",
    "highztc": "High Zero-Carbon Technology Cost",
    "lowztc": "Low Zero-Carbon Technology Cost",
    "altelec": "Alternative Electricity",
    "electrnp": "Alternative Electricity and Transportation",
}
# The upstream release's alttrnp folder holds a byte-for-byte copy of electrnp's run, so
# the real Alternative Transportation case is not available as a restart file. Left out.

# Whole blocks kept: prices, quantities, carbon factors, carbon adders, generation by fuel.
BLOCK_PREFIXES = ("MPBLK/", "QBLK/", "EMEBLK/", "EMABLK/", "UEFDOUT/ugn")
SINGLE = (
    "INTOUT/brent_price", "INTOUT/wti_price", "MACOUT/mc_gdpr", "MACOUT/mc_jpgdp",
    # Carbon by census division, pollutant, year (pollutant 0 is carbon, million metric tons C)
    "EMISSION/emrsc", "EMISSION/emcmc", "EMISSION/emincc", "EMISSION/emtrc", "EMISSION/emelc",
    # Light-duty sales and stock by technology, energy by fuel (for the EV-share lever)
    "TRANREP/trldsalc", "TRANREP/trldsalt", "TRANREP/trldstkc", "TRANREP/trldstkt", "TRANREP/trqldv",
)


def restart_path(case: str, upstream: Path = UPSTREAM) -> Path:
    runs = sorted((Path(upstream) / "output" / "aeo2026" / case).glob("*/restart.rlx"))
    if not runs:
        raise FileNotFoundError(f"no restart file for {case} under {upstream}")
    return runs[-1]


def extract(case: str, upstream: Path = UPSTREAM, cache: Path = CACHE) -> Path:
    z = np.load(restart_path(case, upstream), allow_pickle=False)
    keep = {k: z[k] for k in z.files if k.startswith(BLOCK_PREFIXES) or k in SINGLE}
    cache.mkdir(parents=True, exist_ok=True)
    out = cache / f"{case}.npz"
    np.savez_compressed(out, **keep)
    return out


def available(case: str = "cb2026") -> bool:
    if (CACHE / f"{case}.npz").exists():
        return True
    try:
        restart_path(case)
        return True
    except FileNotFoundError:
        return False


_loaded: dict[str, dict[str, np.ndarray]] = {}


def load_case(case: str) -> dict[str, np.ndarray]:
    """Arrays for one case, extracted from the upstream restart file on first use."""
    if case not in _loaded:
        path = CACHE / f"{case}.npz"
        if not path.exists():
            extract(case)
        with np.load(path, allow_pickle=False) as z:
            _loaded[case] = {k: z[k].astype(np.float64) for k in z.files}
    return _loaded[case]


def main(argv: list[str]) -> None:
    upstream = Path(argv[1]) if len(argv) > 1 else UPSTREAM
    for case in CASES:
        print(case, extract(case, upstream))


if __name__ == "__main__":
    main(sys.argv)
