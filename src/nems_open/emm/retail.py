"""Retail electricity prices from the ported EFP, for run_model(elec_price="efp").

Wraps the EMM chain (chain.py: LDSM, the EFD stand-in, EFP). It starts from the
oracle's 2021 state and runs on EIA's demand up to the year before the loop
starts, so EFP's books (rate base, depreciation, deferred taxes) reach that
year. Inside the loop, each supply pass hands it the loop's electricity sales:
- residential and commercial census sales go in as they are;
- industrial and transport go in through their end-use detail (QELINOUT,
  TRQ_ELEC), scaled by the loop's sector total over EIA's.
Each call is one NEMS iteration with the loop's CURITR and FCRL: the first rolls
the capital accounts forward, later ones reprice, and the final convergence and
reporting loop (FCRL = 1) writes the statements and REVGAP's smoothing.

Prices out are EFP's response, not its level: EIA's price times EFP's price on the
loop's demand over EFP's price on EIA's demand (the oracle's EFP run, every year in
its final dump). The oracle's EFP runs on stand-in dispatch costs and prices 8 to
19% below EIA, so its level would shift the baseline; its response is what the
port adds. On EIA's demand the ratio stays within the chain's 0.3% of the oracle.

What does not move with the loop in this version: the dispatch costs inside EFP
come from the EFD stand-in, which is EIA's reference dispatch (fuel use and
fuel prices by region from the restart file). A carbon price therefore reaches
retail prices only through sales, not through generation costs.
"""

import numpy as np

from nems_open import oracle_state
from nems_open.emm.chain import Chain
from nems_open.supply_standin.data import FIRST_YEAR

f32 = np.float32
SECTORS = ["rs", "cm", "in", "tr"]       # QEL** / PEL** suffixes
PRICES = ["MPBLK/pelrs", "MPBLK/pelcm", "MPBLK/pelin", "MPBLK/peltr", "MPBLK/pelas"]


class EfpPrices:
    def __init__(self, snap, start_year: int):
        self.chain = Chain(snap, 32)
        final = oracle_state.load("final", 61, "emm")
        self.ref = {k: final[k.split("/")[1]].a.astype(np.float64) for k in PRICES}   # EFP on EIA's demand
        self.eia = {k: np.asarray(snap[k], dtype=np.float64) for k in PRICES}          # EIA's prices
        s = self.chain.s
        # EIA's sales, to scale industrial and transport end uses against
        self.eia_q = {k: s[f"qel{k}"].a.copy() for k in SECTORS}
        self.qelinout = s["qelinout"].a.copy()
        self.trq = s["trq_elec"].a.copy()
        self.chain.iteration(32, 2)   # the rest of 2021
        for y in range(33, start_year - FIRST_YEAR + 1):
            for itr in (1, 2):
                self.chain.iteration(y, itr)

    def _sales_in(self, q, y):
        s = self.chain.s
        j = y - 1
        for k in SECTORS:
            s[f"qel{k}"].a[:, j] = q[f"QBLK/qel{k}"][:, j]
        with np.errstate(divide="ignore", invalid="ignore"):
            rin = np.where(self.eia_q["in"][:, j] > 0, q["QBLK/qelin"][:, j] / self.eia_q["in"][:, j], 1.0)
            rtr = np.where(self.eia_q["tr"][:, j] > 0, q["QBLK/qeltr"][:, j] / self.eia_q["tr"][:, j], 1.0)
        s["qelinout"].a[:, j, :] = (self.qelinout[:, j, :] * rin[:, None]).astype(np.float32)
        s["trq_elec"].a[:, :, j] = (self.trq[:, :, j] * rtr[None, :]).astype(np.float32)

    def _prices_out(self, y):
        s, j = self.chain.s, y - 1
        out = {}
        for k in PRICES:
            mine, ref, eia = s[k.split("/")[1]].a[:, j].astype(np.float64), self.ref[k][:, j], self.eia[k][:, j]
            with np.errstate(divide="ignore", invalid="ignore"):
                out[k] = np.where(ref > 0, eia * mine / ref, eia)
        return out

    def price_pass(self, year: int, q: dict, itr: int, fcrl: int) -> dict:
        """EFP on this iteration's demand: {MPBLK/pel**: (11,) prices for the year}. itr is
        NEMS's CURITR (1 rolls the capital accounts forward); fcrl = 1 on the final loop
        writes the statements and REVGAP's smoothing."""
        y = year - FIRST_YEAR + 1
        self._sales_in(q, y)
        self.chain.iteration(y, itr, fcrl=fcrl)
        return self._prices_out(y)
