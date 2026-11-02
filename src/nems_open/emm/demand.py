"""Electricity demand on the EMM regions, built from the demand modules' sales.

NEMS demand modules return purchased electricity by census division and sector (QELRS, QELCM,
QELIN, QELTR, trillion Btu). EMM needs it by EMM region. This spreads census sales over EMM
regions with the base-year load shares in the input files, then adds delivery losses and
subtracts what end users generate themselves.
"""

import numpy as np

from nems_open.emm import history, load, regions

TBTU_PER_TWH = 3.412
SECTORS = ("rs", "cm", "in", "tr")          # residential, commercial, industrial, transportation
SALES_KEYS = ("QBLK/qelrs", "QBLK/qelcm", "QBLK/qelin", "QBLK/qeltr")
BASE_YEAR = 2024                             # last year of regional sales history in the input files


def census_sales_twh(snapshot, year: int) -> np.ndarray:
    """Sales by census division and sector, shape (9, 4), TWh. California is folded into the Pacific division,
    as the EMM-to-census map does."""
    y = year - history.FIRST_YEAR
    out = np.zeros((9, 4))
    for s, key in enumerate(SALES_KEYS):
        q = snapshot[key][:, y] / TBTU_PER_TWH
        out[:, s] = q[:9]
        out[8, s] += q[9]
    return out


def regional_sales_twh(snapshot, year: int) -> np.ndarray:
    """Sales by EMM region and sector, shape (25, 4), TWh.

    Each region starts from its 2024 history and moves with the census divisions it serves.
    """
    share = regions.emm_share_of_census()[:25, :9, :]            # (25, 9, 4)
    base = np.stack([history.sales(s)[:25, BASE_YEAR - history.FIRST_YEAR] for s in SECTORS], axis=1)
    implied = np.einsum("rs,rcs->cs", base, share)               # census sales the regions add up to
    target = census_sales_twh(snapshot, year)
    ratio = np.divide(target, implied, out=np.ones_like(implied), where=implied > 0)
    return base * np.einsum("rcs,cs->rs", share, ratio)


def end_user_generation_twh(snapshot, year: int) -> np.ndarray:
    """Power that cogeneration, rooftop solar and other end-use generators make, by EMM region, TWh."""
    a = snapshot["COGEN/cgtotgennr"][:25, year - history.FIRST_YEAR]      # (25, 13, 2) GWh
    return a.sum(axis=(1, 2)) / 1000.0


def international_net_imports_twh(snapshot, year: int) -> np.ndarray:
    """Net imports from Canada and Mexico by EMM region, TWh (firm plus economy, minus exports)."""
    y = year - history.FIRST_YEAR
    g = sum(snapshot[f"UETTOUT/{k}"][:25, y] for k in ("utimpe", "utimpf"))
    g = g - sum(snapshot[f"UETTOUT/{k}"][:25, y] for k in ("utexpe", "utexpf"))
    return g / 1000.0


def net_load_twh(snapshot, year: int) -> np.ndarray:
    """Energy the EMM power plants must supply, by region, shape (25,), TWh.

    Sales plus delivery losses, less end-user generation and international net imports.
    Trade between EMM regions is not in this number (the dispatch model has none yet), so
    regional totals are only as good as the sales split.
    """
    loss = load.region_parameters()["td_loss"]
    need = regional_sales_twh(snapshot, year).sum(axis=1) / (1.0 - loss)
    return np.maximum(need - end_user_generation_twh(snapshot, year)
                      - international_net_imports_twh(snapshot, year), 0.0)
