"""SUBROUTINE RESD's yearly chain: every residential routine in EIA's call order.

`projection_year` is one call of RESD for a year after the RECS base year (2021 on),
minus the 111(d) and price-induced technical change hooks, which are off in AEO2026.
`run` repeats it year by year with NEMS's two iterations per year, carrying the
whole state forward the way the Fortran's COMMON and SAVEd locals do.
"""

from nems_open.residential.appliances import (rdryadd, rdrycon, rdrytec, rfrzadd, rfrzcon, rfrztec,
                                              rrefadd, rrefcon, rreftec)
from nems_open.residential.common import BASEYR
from nems_open.residential.cooling import rcladd, rclcon, rcltec
from nems_open.residential.distgen import rdistgen
from nems_open.residential.heating import rhtradd, rhtrcon
from nems_open.residential.heating_choice import rhtrtec, rshvac
from nems_open.residential.housing import newhse, rdpr, sqftcalc
from nems_open.residential.lighting_misc import apcns, appcns, ltcns, shtcns
from nems_open.residential.totals import fuelcn, nemscn, resdrp, rsbench
from nems_open.residential.washers import rcwadd, rcwcon, rdwadd, rdwcon, rcwtec, rdwtec
from nems_open.residential.water_cooking import reuadd, rstovcon, rstvtec, rwhcon, rwhtec

# After RDPR, in RESD's order (resd.f lines 521-587).
CHAIN = [
    newhse, sqftcalc, rshvac, rhtrtec, rhtradd, rdistgen,
    rcltec, rcladd, rcwtec, rcwadd, rdwtec, rdwadd,
    rwhtec, lambda s: reuadd(s, 5), rstvtec, lambda s: reuadd(s, 6),
    rdrytec, rdryadd, rreftec, rrefadd, rfrztec, rfrzadd,
    rhtrcon, rclcon, rcwcon, rdwcon, rwhcon, rstovcon, rdrycon, rrefcon, rfrzcon,
    ltcns, apcns, shtcns, appcns,
    fuelcn, rsbench, nemscn, resdrp,
]


def after_prices(s: dict) -> None:
    """Everything RESD does in a projection year after RDPR."""
    for routine in CHAIN:
        routine(s)


def projection_year(s: dict) -> None:
    rdpr(s)
    after_prices(s)


def resume_from_dump(s: dict) -> None:
    """Fill in the SAVEd locals a run started mid-projection needs but the oracle
    dumps do not hold, or hold under their Fortran names (from "<tag>_pre").
    A run from 2021 on its first iteration sets all of these itself."""
    from nems_open.residential import heating, lighting_misc
    c = heating._carried(s)
    for yy in range(2020, 2051):
        c["faneff"][yy] = 1.0    # RHTRCON sets these once, in 2021: FANEFF is 1.0,
        c["nfaneff"][yy] = 0.75  # NFANEFF the 2019 furnace fan standard
    for k in ("efanuec", "nfanuec"):
        if k in s:
            c[k] = s[k].copy()
    # LTCNS's existing-home lighting stock is fixed by the RECS-year stock; rebuild it
    # the way the first post-RECS year does.
    scratch = {k: (v.copy() if hasattr(v, "copy") and not isinstance(v, dict) else v) for k, v in s.items()}
    scratch["curcalyr"] = 2021
    lighting_misc.ltcns_recs_init(scratch)
    for k in ("ltstockex", "ltstockexcons"):
        s[k] = scratch[k]


def run(s: dict, first_year: int, last_year: int, iterations: int = 2, start_iteration: int = 1) -> None:
    """Run calendar years first_year..last_year, NEMS iterations 1..iterations each.
    start_iteration lets a run pick up in the middle of its first year, from a
    state the oracle dumped on that year's final iteration."""
    for year in range(first_year, last_year + 1):
        s["curcalyr"], s["curiyr"] = year, year - BASEYR + 1
        for itr in range(start_iteration if year == first_year else 1, iterations + 1):
            s["curitr"] = itr
            projection_year(s)
