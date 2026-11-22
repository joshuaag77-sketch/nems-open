"""Electricity demand on the EMM regions, built from the demand modules' sales.

NEMS demand modules return purchased electricity by census division and sector (QELRS, QELCM,
QELIN, QELTR, trillion Btu). EMM needs it by EMM region. This spreads census sales over EMM
regions as LDSM does (DSMEMMV), adds delivery losses as LDSM does, and takes off what EFD gets
from sources outside the dispatched fleet: end-use generators' sales to the grid, the electric power
sector's combined heat and power units (nontraditional cogeneration) and imports from Canada and Mexico.
"""

import numpy as np

from nems_open.emm import history, load, regions

TBTU_PER_TWH = 3.412
SECTORS = ("rs", "cm", "in", "tr")          # residential, commercial, industrial, transportation
SALES_KEYS = ("QBLK/qelrs", "QBLK/qelcm", "QBLK/qelin", "QBLK/qeltr")
PV_COLUMN = 9                                # solar column in COGEN/cgtotgennr
PV_GRID_SALES = True                         # take end-use PV's grid sales off the load (end_user_grid_sales_twh)
# ULOSSADJ (prepett.f 853-886), by year: EMM scales every region's T&D loss factor by it.
LOSS_ADJUSTMENT = {**{y: 1.0 for y in range(1990, 1999)}, 1999: 0.974, 2000: 0.965, 2001: 0.956, 2002: 0.946,
                   2003: 0.937, 2004: 0.928, 2005: 0.918, 2006: 0.909, **{y: 1.0 for y in range(2007, 2011)},
                   2011: 1.05, 2012: 1.05, 2013: 1.05, 2014: 1.02, **{y: 1.0 for y in range(2015, 2020)},
                   **{y: 0.8 for y in range(2020, 2026)}}


def census_sales_twh(snapshot, year: int) -> np.ndarray:
    """Sales by census division and sector, shape (9, 4), TWh.

    The restart's census arrays have 11 slots: the nine divisions, California (slot 10) and the US. California
    is part of the Pacific division, so it is not added again (the nine divisions add up to the US).
    """
    y = year - history.FIRST_YEAR
    out = np.zeros((9, 4))
    for s, key in enumerate(SALES_KEYS):
        out[:, s] = snapshot[key][:9, y] / TBTU_PER_TWH
    return out


def regional_sales_twh(snapshot, year: int) -> np.ndarray:
    """Sales by EMM region and sector, shape (25, 4), TWh.

    LDSM's DSMEMMV (uldsm.f 1730-1758, called at 4425-4437): each census division's sales go to the EMM
    regions in proportion to MappCtoN, the regions' base load in that division and sector. Alaska and Hawaii
    take their share of the Pacific division and are left out. (The earlier rule, 2024 regional history moved
    by census growth, put Alaska's and Hawaii's 15-20 TWh on the 25 regions and missed EIA's regional sales,
    QELASN, by up to 8%; this rule is within 0.1% of them in 2025.)
    """
    w = regions.census_to_emm_weights()[:, :9, :].copy()         # (28, 9, 4) base load by region and division
    w[regions.NUM_NERC - 1] = 0.0                                # the US row
    total = w.sum(axis=0, keepdims=True)
    share = np.divide(w, total, out=np.zeros_like(w), where=total > 0)
    return np.einsum("rcs,cs->rs", share, census_sales_twh(snapshot, year))[:25]


def loss_adjustment(year: int) -> float:
    """ULOSSADJ, EMM's multiplier on each region's T&D loss factor (prepett.f 853-886): 0.8 from 2020 on."""
    return LOSS_ADJUSTMENT.get(year, LOSS_ADJUSTMENT[min(max(year, 1990), 2025)])


def end_user_grid_sales_twh(snapshot, year: int) -> np.ndarray:
    """Power that end-use generators (cogeneration and other customer-sited units) sell to the grid, by EMM region, TWh.

    COGEN/cgtotgennr's last axis is sales to the grid (1) and own use (2). Own use never reaches the sales the
    demand modules report (they are purchases), so only the grid part supplies EFD's load, as BTCOGEN does in
    EFD (unugs.f 436-458; residential and commercial own use is in both LDSM's load and BTCOGEN, which nets out).

    Solar (PV_GRID_SALES). With DPVDISPATCH (util.f 168) BTCOGEN leaves out end-use PV, own use and grid sales alike
    (unugs.f 445-456), because EFD dispatches the distributed PV capacity itself (ED$GRD, uefd.f 1621-1660; its
    output on the load rows, 11949-11965) and EMMBODPV backs DPVTOTGENNR out of the reported PV afterwards (util.f
    5865-5895). LDSM's load holds the PV's own use (the demand modules' purchases net it out and LDSM adds it back,
    uldsm.f 1253-1263; resd.f 11752), not its grid sales. So EFD's fleet serves neither: the dispatch, which has no
    distributed PV (restart UCAPPV is net of it), takes the PV grid sales off too. On: they are taken off (18 TWh in
    2030). Off: the solar column is left out, as before (Codex finding 6).
    """
    a = snapshot["COGEN/cgtotgennr"][:25, year - history.FIRST_YEAR, :, 0]   # (25, 13) GWh
    keep = np.ones(a.shape[1], dtype=bool)
    keep[PV_COLUMN] = PV_GRID_SALES
    return a[:, keep].sum(axis=1) / 1000.0


def nontraditional_cogen_twh(snapshot, year: int) -> np.ndarray:
    """Electric power sector combined heat and power (nontraditional cogeneration) sold to the grid, by EMM region, TWh.

    EFD dispatches these units as ownership class 4 (UCAP*C, COGEN/CGNTCAP). Their output is in neither EIA's
    generation by fuel (UGNCLNR, UGNGFNR: classes 1 to 3) nor the dispatch's fleet (UCAP*U and *N), so it
    supplies load the dispatch does not serve: COGEN/CGNTGEN, sales to the grid (own use is direct use).
    """
    return snapshot["COGEN/cgntgen"][:25, year - history.FIRST_YEAR, :, 0].sum(axis=1) / 1000.0


def nontraditional_cogen_fuel_tbtu(snapshot, year: int) -> dict:
    """Fuel the nontraditional cogeneration units burn in the 25 regions (COGEN/CGNTQ), trillion Btu: coal, oil, gas.

    QCLEL and QNGEL count it as electric power fuel; the dispatched fleet does not burn it, so the loop adds it back."""
    q = snapshot["COGEN/cgntq"][:25, year - history.FIRST_YEAR].sum(axis=0)
    return {"coal": float(q[0]), "oil": float(q[1]), "gas": float(q[2])}


def nontraditional_cogen_co2_mt(snapshot, year: int) -> float:
    """CO2 from the nontraditional cogeneration units' fuel (COGEN/CGNTQ), million metric tons, 25 regions.

    EIA counts it in the power sector: EFD sums UTCARC and UTCO2N over ownership classes 1 to 4 (uefd.f 3122-3232),
    so EMISSION/EMELC and UEFDOUT/UTCO2 hold it. The dispatched fleet does not burn this fuel. Oil is priced at
    residual's factor, as the loop books it in QRSEL."""
    from nems_open.emm import dispatch
    nt = nontraditional_cogen_fuel_tbtu(snapshot, year)
    return (nt["coal"] * dispatch.CO2_PER_TBTU["coal"] + nt["gas"] * dispatch.CO2_PER_TBTU["gas"]
            + nt["oil"] * dispatch.CO2_PER_TBTU["residual"])


def noncontiguous_fuel_tbtu(snapshot, year: int) -> dict:
    """Alaska's and Hawaii's power-sector fuel, trillion Btu: coal, distillate, residual, gas.

    The dispatch covers the 25 EMM regions. util.f (6011-6038 Alaska, 6385-6402 Hawaii) adds the two states' fuel to
    the Pacific division's QCLEL, QDSEL, QRSEL and QNGEL from their own history scaled by demand (and Hawaii's RPS),
    outside EFD; Alaska's oil all goes to distillate. Here they are the reference run's (UEFDOUT/UFL*NR, NERC rows 26
    and 27): the same arrays EIA fills from those lines."""
    y = year - history.FIRST_YEAR
    f = lambda k, rows: float(snapshot[f"UEFDOUT/{k}"][:, rows, y].sum())
    ak, hi = slice(25, 26), slice(26, 27)
    both = slice(25, 27)
    gas = sum(f(k, both) for k in ("uflgfnr", "uflginr", "uflgcnr") if snapshot.names(f"UEFDOUT/{k}"))
    oil = ("ufldsnr", "uflddnr", "uflrlnr", "uflrhnr")
    return {"coal": f("uflclnr", both),
            "distillate": sum(f(k, ak) for k in oil) + f("ufldsnr", hi) + f("uflddnr", hi),
            "residual": f("uflrlnr", hi) + f("uflrhnr", hi),
            "gas": gas}


def international_net_imports_twh(snapshot, year: int) -> np.ndarray:
    """Net imports from Canada and Mexico by EMM region, TWh (firm plus economy, minus exports)."""
    y = year - history.FIRST_YEAR
    g = sum(snapshot[f"UETTOUT/{k}"][:25, y] for k in ("utimpe", "utimpf"))
    g = g - sum(snapshot[f"UETTOUT/{k}"][:25, y] for k in ("utexpe", "utexpf"))
    return g / 1000.0


def net_load_twh(snapshot, year: int, sales=None) -> np.ndarray:
    """Energy the dispatched EMM fleet must supply, by region, shape (25,), TWh.

    LDSM's load, sales x (1 + ULOSSADJ x UQTDLS) (uldsm.f 2011), less what EFD gets from outside the fleet:
    end-use generators' grid sales, nontraditional cogeneration and international net imports. `sales` is any
    mapping with the restart's QBLK/qel* arrays (the default is the snapshot); the rest comes from the snapshot.
    Trade between EMM regions, storage losses and the LP's own line losses are not in this number.
    """
    loss = load.region_parameters()["td_loss"]
    need = regional_sales_twh(sales if sales is not None else snapshot, year).sum(axis=1) * (1.0 + loss_adjustment(year) * loss)
    return np.maximum(need - end_user_grid_sales_twh(snapshot, year) - nontraditional_cogen_twh(snapshot, year)
                      - international_net_imports_twh(snapshot, year), 0.0)
