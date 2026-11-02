"""System-level inputs: transmission links, annual region controls, Canadian supply, fuel hookups."""

from functools import lru_cache

import numpy as np

from nems_open.emm import db, regions

FIRST_YEAR = 1990
NUM_YEARS = 61


@lru_cache(maxsize=1)
def transmission() -> dict[str, np.ndarray]:
    """Cost of new links between EMM regions, each of shape (25, 25), [from, to] by region number.

    ac_cost: EMM_CNXT_CST, AC interconnect cost; hvdc_cost: EMM_HVDC_CST; hvdc_loss: EMM_HVDC_LOSS.
    Zero means no link is offered between the pair.
    """
    t = db.table("V_EMM_ECPDAT_REG_REG")
    out = {}
    for name, col in (("ac_cost", "EMM_CNXT_CST"), ("hvdc_cost", "EMM_HVDC_CST"), ("hvdc_loss", "EMM_HVDC_LOSS")):
        a = np.zeros((regions.NUM_EMM, regions.NUM_EMM))
        a[t["EMM_REG"] - 1, t["EMM_REG2"] - 1] = t[col]
        out[name] = a
    return out


@lru_cache(maxsize=1)
def annual_controls() -> dict[str, np.ndarray]:
    """Yearly regional controls, each of shape (28, 61) with NaN where the file has no value.

    nuclear_derate: NUCDRAT; hydro_factor: UQHYFAC; labor_demand: ULABASEDMD; scrubber_cost: USGCOST.
    """
    t = db.table("V_EMM_CNTL_ANNUAL")
    out = {}
    for name, col in (("nuclear_derate", "NUCDRAT"), ("hydro_factor", "UQHYFAC"),
                      ("labor_demand", "ULABASEDMD"), ("scrubber_cost", "USGCOST")):
        a = np.full((regions.NUM_NERC, NUM_YEARS), np.nan)
        a[t["EMM_REG"] - 1, t["YEAR"] - FIRST_YEAR] = t[col]
        out[name] = a
    return out


@lru_cache(maxsize=1)
def canadian_supply() -> dict[str, np.ndarray]:
    """Canadian import supply steps (V_EMM_CANSPLY_STEPS) as parallel arrays, one entry per step row:
    region, year, step, province, firm_mw (FMW), nonfirm_mw (PMW), capacity_factor (CF, percent),
    price (SPDOLL) and cost (CST)."""
    t = db.table("V_EMM_CANSPLY_STEPS")
    keep = t["YEAR"] > 0                      # the file ends with one blank record
    return {"region": t["EMM_REG"][keep], "year": t["YEAR"][keep], "step": t["CAN_STP"][keep],
            "province": t["SPCANRGN"][keep], "firm_mw": t["FMW"][keep], "nonfirm_mw": t["PMW"][keep],
            "capacity_factor": t["CF"][keep], "price": t["SPDOLL"][keep], "cost": t["CST"][keep]}


@lru_cache(maxsize=1)
def fuel_hookup_cost() -> np.ndarray:
    """Cost to connect each EMM region to each fuel region (FL_CNXT_CST), shape (25, n_fuel_regions)."""
    t = db.table("V_EMM_ECPDAT_REG_FUEL")
    a = np.zeros((regions.NUM_EMM, int(t["FUEL_RGN"].max())))
    sel = t["EMM_REG"] <= regions.NUM_EMM
    a[t["EMM_REG"][sel] - 1, t["FUEL_RGN"][sel] - 1] = t["FL_CNXT_CST"][sel]
    return a
