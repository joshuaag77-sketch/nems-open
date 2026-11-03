"""The tables COMM's runner used to take from the oracle's dumps, built from EIA's input files.

`input_tables()` returns the same names `Commercial.start_from_dump` copies from the dumps
(SD_TABLES, TC_TABLES, CN_TABLES, BM_TABLES in comm.py), except the few values another module
supplies: the first two fuel rows of STEOdat (EXCCPUS and NGCCBUS, from the macro/supply
modules) and the history in CMSEDS. Pass those in `macro` if you have them.
"""

import numpy as np

from nems_open.commercial import distgen_tables
from nems_open.commercial.benchmark_inputs import read_kminfl, read_ksteo
from nems_open.commercial.inputs import CBECS_IDX, CM_FIRST_YR, MNUMYR, read_kmels, read_ksheff
from nems_open.commercial.kparm import read_kparm
from nems_open.fortran_array import FArray
from nems_open.scedes import option

f32 = np.float32
DEFAULT_PRICES = [18.0, 7.0, 15.0, 8.0, 16.0, 2.0, 16.0, 16.0]   # DATA DefaultPrices (comm.f 7795)
NTEK = 11                                                         # PARAMETER (NTEK=11)


def services_index(mc_revser: np.ndarray, curiyr: int = CM_FIRST_YR) -> FArray:
    """ServicesIndex(y) = MC_REVSER(MNUMCR,11,CURIYR) / MC_REVSER(MNUMCR,11,CBECSyear-BASEYR+1).

    EIA computes it with CURIYR, the year of the first call, for every y, so the whole row holds
    one number. mc_revser is MACOUT/mc_revser with shape (11, 12, 61).
    """
    ratio = f32(mc_revser[10, 10, curiyr - 1] / mc_revser[10, 10, CBECS_IDX - 1])
    out = FArray.zeros([(CBECS_IDX, MNUMYR)])
    for y in range(CM_FIRST_YR, MNUMYR + 1):
        out[y] = ratio
    return out


def input_tables(mc_revser: np.ndarray, nrgbill: int | None = None) -> dict:
    """Lower-case Fortran names -> arrays, for the tables the runner has no other source for.

    nrgbill defaults to the scedes NRGBILL option (1 in the AEO2026 reference run).
    """
    imprv_ht, imprv_cl, heat, cool = read_ksheff()
    t = {"existimprvht": imprv_ht, "existimprvcl": imprv_cl, "shellheatfactor": heat, "shellcoolfactor": cool}
    mels = read_kmels()
    for name in ("dcf", "marketpenetrationmels", "melselq", "xplicitmiscshr", "datactrservpenetration",
                 "officepcpenetration", "marketpenetrationsc", "pctscsavings", "ct_flag"):
        t[name] = mels[name]
    t["servicesindex"] = services_index(mc_revser)
    k = read_kparm()
    for name in ("applyramp", "stretbehav", "costtrendswitch", "nohist", "decaybm", "lastdecayyr"):
        t[name] = k[name]
    t["steobm2pct"] = FArray(np.array(k["steobm2pct"], dtype=np.int16), [1])
    steo = read_ksteo()
    t["flagregsteo"], t["steodat"] = steo["flagregsteo"], steo["steodat"]
    t.update(read_kminfl())
    t["defaultprices"] = FArray(np.array(DEFAULT_PRICES, dtype=f32), [1])
    t["ifueltype"] = FArray(np.asarray(distgen_tables.read_kgentk().IFUELTYPE[1:NTEK + 1], dtype=np.int32), [1])
    t["ntek"] = NTEK
    t["ef1"], t["ef2"], t["ef3"] = f32(0.5), f32(0.35), f32(0.15)
    t["nrgbill"] = option("NRGBILL") if nrgbill is None else nrgbill
    return t
