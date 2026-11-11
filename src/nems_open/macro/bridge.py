"""Energy price bridge: NEMS energy prices and quantities into FRB/US.

FRB/US took domestic energy prices out in 2018 and keeps only the imported-oil price (poilr), which
moves GDP about a tenth as much as EIA's own macro model does. Two channels carry the rest:

1. Oil: the Brent ratio scenario/reference becomes a multiplier on poilr.
2. Energy bill: Laspeyres change in delivered-energy spending, sum of (p_scen - p_ref) * q_ref over
   every MPBLK/QBLK price-quantity pair, as a share of GDP. It enters as a drop in consumption
   (eco_aerr) times one pass-through scalar kappa, fitted on lowogs and tested on highogs.
"""

import numpy as np
import pandas as pd

YEARS = np.arange(1990, 2051)


def _series(snap, name) -> pd.Series:
    return pd.Series(np.asarray(snap[name], dtype=float), index=YEARS)


def oil_multiplier(scenario, reference) -> pd.Series:
    """Brent price ratio by calendar year, 1990 to 2050."""
    return _series(scenario, "INTOUT/brent_price") / _series(reference, "INTOUT/brent_price")


def energy_bill_change(scenario, reference, region: int = 10) -> pd.Series:
    """Change in delivered-energy spending as a share of real GDP, by calendar year.

    region is the 0-based census-division column of MPBLK (10 = the US row). Prices are 1987$/MMBtu
    and quantities trillion Btu, so p*q/1000 is 1987$ billions; GDP is converted to 1987$ with MC_JPGDP.
    """
    names = set(reference.keys())
    delta = np.zeros(len(YEARS))
    for key in names:
        # fuels bought by power plants (suffix "el") are already inside the electricity price
        if not key.startswith("MPBLK/p") or key.endswith("el"):
            continue
        qkey = "QBLK/q" + key[len("MPBLK/p") :]
        if qkey not in names:
            continue
        q = np.asarray(reference[qkey], dtype=float)
        q = q[region] if q.ndim == 2 else q
        dp = np.asarray(scenario[key], dtype=float)[region] - np.asarray(reference[key], dtype=float)[region]
        delta += np.nan_to_num(dp * q) / 1000.0  # 1987$/MMBtu x trillion Btu = 1987$ millions
    jp = np.asarray(reference["MACOUT/mc_jpgdp"], dtype=float)  # 1987 = 1, starts 1987
    deflator = np.interp(YEARS, np.arange(1987, 1987 + len(jp)), jp)
    gdp87 = np.asarray(reference["MACOUT/mc_gdpr"], dtype=float) / deflator[YEARS.tolist().index(2012)]
    return pd.Series(delta / gdp87, index=YEARS)


def quarterly(annual: pd.Series, periods) -> np.ndarray:
    """Annual values to quarters by linear interpolation through mid-year points."""
    x = np.array([p.year + (p.quarter - 0.5) / 4 for p in periods])
    return np.interp(x, annual.index + 0.5, annual.values)


# Pass-through of the energy bill into consumption, least squares on EIA's lowogs GDP gap (2026 to 2050).
KAPPA = 0.58
