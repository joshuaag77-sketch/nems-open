"""One industry and region for one year: port of MODCAL (ind.f), end-use industries.

The call order is EIA's: carbon share for California (AB 32), production by step
(CALPROD), this year's UECs (CALCSC for every step and fuel), process energy (CALPATOT),
byproduct energy (CALBYPROD), building energy (CALBTOT), CHP (CALGEN), boiler fuel shares
and steam (CALBSC, CALSTOT), industry totals (INDTOTAL), national totals (NATTOTAL, after
region 4) and the report-writer tables (CONTAB for the region and, after region 4, US).

Works on an oracle-style state dict and updates it in place. `base` is the CALBTOT
base-year employment and production memory; pass the same dict on every call.

Not ported, because they do not change fuel use in model years:
- CARBSHRCA (computed once, in the 2022 base year, from next year's consumption) and the
  AB 32 covered-emissions bookkeeping (ab_covd_em_*), which only feed carbon reports.
- Process-flow industries 8, 10, 11, 12, 13 (paper, glass, cement, steel, aluminum): their
  own models replace CALPROD/CALPATOT. They raise NotImplementedError here.
"""

import numpy as np

from nems_open.industrial.boiler_shares import calbsc
from nems_open.industrial.boiler_totals import calstot
from nems_open.industrial.buildings import calbtot
from nems_open.industrial.byproduct import calbyprod
from nems_open.industrial.cogen import calgen
from nems_open.industrial.contab import contab
from nems_open.industrial.national import nattotal
from nems_open.industrial.process_totals import calpatot
from nems_open.industrial.production import calprod
from nems_open.industrial.tech_progress import calcsc
from nems_open.industrial.totals import indtotal

f32 = np.float32
PROCESS_FLOW = (8, 10, 11, 12, 13)


def modcal(s: dict, base: dict, stepnames: list | None = None, version: str = "original") -> None:
    inddir, indreg, indnum = int(s["inddir"]), int(s["indreg"]), int(s["indnum"])
    if inddir in PROCESS_FLOW:
        raise NotImplementedError("process-flow industries are not ported")
    ibyr, curcalyr = int(s["ibyr"]), int(s["curcalyr"])

    if indreg == 4 and curcalyr >= ibyr:
        s["carbshr_ab"][inddir, indreg] = min(f32(s["carbshrca"][inddir]), f32(1.0))
    else:
        s["carbshr_ab"][inddir, indreg] = 0.0

    calprod(s, stepnames)
    if version == "original":
        for istep in range(1, int(s["mpastp"]) + 1):
            for ifuel in range(1, int(s["ifmax"][istep]) + 1):
                calcsc(s, ifuel, istep)
    calpatot(s, version)
    if curcalyr <= ibyr:
        s["bypadibyr"].a[...] = 1.0
    calbyprod(s)
    calbtot(s, base)
    calgen(s, inddir, indreg)
    if inddir > 21:
        s["elown"] = f32(0.0)
        s["elsale"] = f32(0.0)
    if int(s["curitr"]) == 1 and inddir == 1 and indreg == 1:
        s["beff"][1] = f32(s["beff"][1]) * f32(s["hpbeff"])
    calbsc(s, inddir, indreg)
    calstot(s, inddir, indreg)
    indtotal(s, inddir, indreg, indnum)
    if indreg == 4:
        nattotal(s, indnum)
    contab(s, indreg)
    if indreg == 4:
        contab(s, 5)
