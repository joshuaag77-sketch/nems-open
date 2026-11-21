"""The load ECP's reserve requirement is written on: LDSM's system load, and the firm-contract adjustment.

ECP's reserve row (uecp.f EP$MRM) asks for EPPEAK x EPMRM + EP_NET_PEAK + PKADJ:
- EPPEAK is the largest of the seasonal peaks LDSM hands ECP (UPPEAK, udat.f 14369-14381), the top of LDSM's
  864-hour system load (SYLOAD: sector end-use loads on their load shapes, plus T&D losses and electrolyzers).
- EP_NET_PEAK is that system load (DUCK_SYSTEM_LOAD) averaged over the hours of highest net load (CAP_CREDIT).
- PKADJ = UEITAJ_ECP (firm contracts, exports less imports, times AVEFOR 0.91: prepett.f 769) + UTRELADJ
  - BTCOGEN / 8.76 + BMEXICAN / 8.76 (EIA's UCAPADJ).

The capacity LP used to shape each region's net energy (sales less end-user generation and international imports)
on a fixed regional shape. That puts the 2033 peak at 876 GW against LDSM's 924, and ISNE at 19.8 against 29.3.
Here LDSM itself runs (nems_open.emm.ldsm, a statement-level port) for the year asked, from the nearest dump of its
state in the oracle (oracle/run_emm/out/state/ld_in). Its demand inputs are the reference run's. Without the dumps
system_load returns None and the LP keeps its own shape.
"""

from functools import lru_cache

import numpy as np

from nems_open.emm import db, regions

NUM_R = regions.NUM_EMM
AVEFOR = 0.91                                     # prepett.f 168
PHASE_OUT = (0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.0)   # prepett.f PHSOUT, years after a contract ends
FIRST_CURIYR, LAST_CURIYR = 31, 61                # 2020 and 2050


def _dump_years() -> list:
    from nems_open import oracle_state
    d = oracle_state.state_dir("emm") / "ld_in"
    if not d.is_dir():
        return []
    return sorted(int(p.name) for p in d.iterdir() if p.name.isdigit() and (p / "index.txt").exists())


@lru_cache(maxsize=64)
def system_load(year: int):
    """LDSM's system load for `year` (capped at 2050), (25, 36, 24) GW: 12 months x 3 day types by 24 hours, the
    order of the capacity LP's typical days. None if the LDSM dumps are not here."""
    years = _dump_years()
    if not years:
        return None
    from nems_open import oracle_state
    from nems_open.fortran_array import FArray
    from nems_open.emm.ldsm.common import i, put
    from nems_open.emm.ldsm.forecast import dsmcadj, dsmdlt, dsmfor
    from nems_open.emm.ldsm.system_load import dsmhlm
    tgt = min(max(year - 1989, FIRST_CURIYR), LAST_CURIYR)
    src = max([y for y in years if y <= tgt] or [years[0]])
    s = {k: (v.copy() if isinstance(v, FArray) else v) for k, v in oracle_state.load("ld_in", src, "emm").items()}
    s["curiyr"] = s["curiyr"].dtype.type(tgt)
    dsmcadj(s)
    n = i(s, "nhour")
    out = np.zeros((NUM_R, n))
    for rnb in range(1, NUM_R + 1):
        put(s, "rnb", rnb)
        put(s, "k1", tgt)
        put(s, "ubaseyr", tgt)
        dsmfor(s)
        dsmdlt(s)
        dsmhlm(s)
        sy = s["syload"]
        out[rnb - 1] = [float(sy[h]) for h in range(1, n + 1)]
    return out.reshape(NUM_R, 36, 24)


def firm_contracts(year: int) -> np.ndarray:
    """UEITAJ (GW by region): firm contracts in V_EMM_ETCNCT, exports less imports, derated by AVEFOR. A contract
    with PHOUTCODE 1 fades over the ten years after it ends (PHSOUT); others stop. Contracts with Canadian provinces
    (regions above 25) count on the US side only."""
    t = {k: np.asarray(v) for k, v in db.table("V_EMM_ETCNCT").items()}
    out = np.zeros(64)
    for k in range(len(t["ID"])):
        if int(t["USECODE"][k]) == 0:
            continue
        start, end, mw = int(t["STRTYR"][k]), int(t["ENDYEAR"][k]), float(t["TMPCNTRCT"][k])
        if year < start or year > end + len(PHASE_OUT):
            continue
        if year > end:
            mw = mw * PHASE_OUT[year - end - 1] if int(t["PHOUTCODE"][k]) == 1 else 0.0
        out[int(t["RGEXP"][k]) - 1] += mw / 1000.0
        out[int(t["RGIMP"][k]) - 1] -= mw / 1000.0
    return out[:NUM_R] * AVEFOR


def cogen_adjustment(snapshot, year: int) -> np.ndarray:
    """-BTCOGEN / 8.76 + BMEXICAN / 8.76 (GW by region), as EIA's run stored it (UECPOUT/ucapadj)."""
    a = np.asarray(snapshot["UECPOUT/ucapadj"], dtype=float)
    return a[:NUM_R, min(year - 1990, a.shape[1] - 1)]
