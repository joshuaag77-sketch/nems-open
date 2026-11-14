"""Stand-in for oil and gas mining (4) and EIA's five process-flow industries (paper 8, glass 10, cement and lime 11, iron and steel 12, aluminum 13).

EIA models these with their own technology-choice models (about 5,000 lines of Fortran: kiln allocation, steel
routes, pulp and paper steam, aluminum smelting, the logit technology share model). They are not ported. This module
replays what EIA's reference run produced for each industry and region (the fuel quantities after INDTOTAL,
QTYMAIN, QTYINTR, QTYRENW, and own-use and sold electricity), scaled by the ratio of this run's industry output in
the region to the reference run's output (fuel use proportional to output). So:

- With EIA's macro inputs the five industries reproduce EIA's fuel totals exactly (grade amber: the numbers are
  EIA's, not computed here).
- With different macro output or employment, their fuel moves one for one with output. Their response to fuel prices,
  carbon prices and efficiency choices is NOT modeled: energy intensity is frozen at EIA's reference path.

The reference record comes from the industrial oracle's REFQM, REFQI, REFQR, REFELOWN and REFELSALE arrays (the last
iteration of each year) and its OUTIND (see oracle/patch_intel.py), saved in industrial_reference.npz.
"""

from pathlib import Path

import numpy as np

from nems_open.fortran_array import FArray
from nems_open.industrial.modcal import PROCESS_FLOW
from nems_open.industrial.national import nattotal
from nems_open.industrial.totals import add_to_electricity_groups

f32 = np.float32
REPLAYED = (4,) + PROCESS_FLOW   # oil and gas mining (its CALCSC needs OGSM well and production data) and the process-flow industries
FIRST_YEAR = 33  # index year 2022: the first model year after the ISEAM start year
LAST_YEAR = 61
REGION_DIVISIONS = {1: (1, 2), 2: (3, 4), 3: (5, 6, 7), 4: (8, 9)}
DATA = Path(__file__).resolve().parent.parent / "data" / "industrial_reference.npz"


class Reference:
    """Reference fuel quantities by industry (PROCESS_FLOW), region 1-4 and index year FIRST_YEAR..LAST_YEAR."""

    def __init__(self, qm, qi, qr, elown, elsale, prodvx):
        self.qm, self.qi, self.qr, self.elown, self.elsale, self.prodvx = qm, qi, qr, elown, elsale, prodvx

    @classmethod
    def from_dump(cls, final: dict) -> "Reference":
        n = LAST_YEAR - FIRST_YEAR + 1
        mf = final["refqm"].a.shape[0]
        qm = np.zeros((len(REPLAYED), 5, mf, n), dtype=f32)   # [industry slot, region, fuel, year]
        qi = np.zeros((len(REPLAYED), 5, 7, n), dtype=f32)
        qr = np.zeros((len(REPLAYED), 5, 9, n), dtype=f32)
        elown = np.zeros((len(REPLAYED), 5, n), dtype=f32)
        elsale = np.zeros((len(REPLAYED), 5, n), dtype=f32)
        prodvx = np.zeros((len(REPLAYED), 5, n), dtype=f32)
        for k, d in enumerate(REPLAYED):
            for r in range(1, 5):
                for j, y in enumerate(range(FIRST_YEAR, LAST_YEAR + 1)):
                    qm[k, r, :, j] = final["refqm"].a[:, r - 1, d - 1, y - 1]
                    qi[k, r, :, j] = final["refqi"].a[:, r - 1, d - 1, y - 1]
                    qr[k, r, :, j] = final["refqr"].a[:, r - 1, d - 1, y - 1]
                    elown[k, r, j] = final["refelown"].a[r - 1, d - 1, y - 1]
                    elsale[k, r, j] = final["refelsale"].a[r - 1, d - 1, y - 1]
                    p = f32(0.0)
                    for dv in REGION_DIVISIONS[r]:
                        p = f32(p + final["outind"][d, dv, y])
                    prodvx[k, r, j] = p
        return cls(qm, qi, qr, elown, elsale, prodvx)

    def save(self, path=DATA):
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(path, qm=self.qm, qi=self.qi, qr=self.qr, elown=self.elown, elsale=self.elsale, prodvx=self.prodvx)

    @classmethod
    def load(cls, path=DATA) -> "Reference":
        with np.load(path) as z:
            return cls(z["qm"], z["qi"], z["qr"], z["elown"], z["elsale"], z["prodvx"])


def make_standin(ref: Reference):
    """The function iseam calls in place of MODCAL('tech') for a process-flow industry and region."""

    def standin(s: dict, inddir: int, indreg: int) -> None:
        curiyr = int(s["curiyr"])
        k, j = REPLAYED.index(inddir), curiyr - FIRST_YEAR
        r = indreg
        base = ref.prodvx[k, r, j]
        scale = f32(s["prodvx"] / base) if base > 0 else f32(1.0)
        qm, qi, qr = s["qtymain"], s["qtyintr"], s["qtyrenw"]
        qm[1:ref.qm.shape[2], r] = ref.qm[k, r, :, j] * scale
        qi[1:7, r] = ref.qi[k, r, :, j] * scale
        qr[1:9, r] = ref.qr[k, r, :, j] * scale
        s["elown"] = f32(ref.elown[k, r, j] * scale)
        s["elsale"] = f32(ref.elsale[k, r, j] * scale)
        add_to_electricity_groups(s, inddir, indreg)
        if indreg == 4:
            nattotal(s, inddir)

    return standin
