"""NEMS's integrating module: relaxation, convergence tests and the iteration control.

Ported from EIA's Python integrator (nems-upstream models/converge and source/nems_flow.py):

- Tables: the convergence and relaxation settings by variable are EIA's own CSVs, copied
  here unchanged (conv_*.csv within a cycle, icnv_*.csv between cycles). Only the price
  and quantity tables are used: the loop has no endogenous GDP, oil price or coal-unit
  variables (conv_Other, conv_Coal*, the gas-to-utility tables).
- Test (convergence_check.check_conv): a variable fails when, over census divisions 1-9,
  some fractional change |new - old| / ((new + old) / 2) reaches its FractionTolerance,
  some absolute change reaches its AbsoluteTolerance and, for a price, its matching
  quantity reaches that quantity's AbsoluteTolerance somewhere. The three "some" need not
  be the same division: EIA's any() is taken on each separately, and that is kept.
  Test = 0 in the table means tested, -1 not tested.
- Relaxation (relax.perform_relax): new = old + RelaxFactor * (new - old), for variables
  with Relax = 1, from the second iteration on.
- Each module is tested on what it changed: its inputs before it ran against its raw
  outputs (nems_iteration_loop.update_expectation_vars, steps 4 and 8).
- Iteration control (nems_flow.py, act_ctest): iterate until every module passes; then
  set FCRL and run one more iteration. If that one passes too, the year is stable; if not
  (and iterations remain), clear FCRL and go on. Out of iterations (MAXITR), run one final
  iteration with FCRL = 1. So a year takes 3 to MAXITR + 1 iterations, and the last always
  has FCRL = 1.
"""

from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).parent
MAXITR = 2       # scedes.cb2026.csv: MAXITR
NRUNS = 5        # scedes.cb2026.csv: NRUNS, cycles of the whole run
DIVISIONS = slice(0, 9)


def _table(prefix: str) -> pd.DataFrame:
    t = pd.concat([pd.read_csv(HERE / f"{prefix}_Prices.csv", index_col="Variable"),
                   pd.read_csv(HERE / f"{prefix}_Quantities.csv", index_col="Variable")])
    t.index = t.index.str.strip()
    return t


def _key(var: str) -> str:
    return ("MPBLK/" if var.startswith("P") else "QBLK/") + var.lower()


@dataclass
class Settings:
    """One table's tolerances and relaxation factors, by loop key ("MPBLK/pelrs")."""
    frac: dict = field(default_factory=dict)
    abs: dict = field(default_factory=dict)
    relax: dict = field(default_factory=dict)       # only variables with Relax = 1
    match: dict = field(default_factory=dict)       # price -> its quantity key
    tested: set = field(default_factory=set)

    @classmethod
    def load(cls, prefix: str = "conv") -> "Settings":
        s = cls()
        for var, r in _table(prefix).iterrows():
            k = _key(var)
            s.frac[k], s.abs[k] = float(r["FractionTolerance"]), float(r["AbsoluteTolerance"])
            if int(r["Relax"]) == 1:
                s.relax[k] = float(r["RelaxFactor"])
            if int(r["Test"]) == 0:
                s.tested.add(k)
            if r["PQType"] == "P":
                s.match[k] = _key(str(r["QMATCH"]))
        return s

    def fraction(self, old: np.ndarray, new: np.ndarray) -> np.ndarray:
        absc = np.abs(new - old)
        with np.errstate(divide="ignore", invalid="ignore"):
            frc = absc / ((new + old) / 2)
        return np.where(np.isnan(frc), 0.0, frc), absc

    def failing(self, old: dict, new: dict, q_old: dict, q_new: dict) -> dict[str, float]:
        """Variables (keys of new) that fail EIA's test: {key: largest fractional change}."""
        bad = {}
        for k, n in new.items():
            if k not in self.tested or k not in old:
                continue
            o, n = np.asarray(old[k])[DIVISIONS], np.asarray(n)[DIVISIONS]
            frc, absc = self.fraction(o, n)
            fail = (frc >= self.frac[k]).any() and (absc >= self.abs[k]).any()
            if fail and k in self.match:
                qk = self.match[k]
                qtol = self.abs.get(qk, 0.0)
                big = [(np.asarray(v)[DIVISIONS] >= qtol).any() for v in (q_old.get(qk), q_new.get(qk))
                       if v is not None]
                fail = any(big)      # a price whose quantity the loop does not carry is not tested
            if fail:
                bad[k] = float(np.max(frc))
        return bad

    def relaxed(self, old: dict, new: dict) -> dict:
        """EIA's relaxation of new toward old; variables without a factor pass through."""
        return {k: (old[k] + self.relax[k] * (v - old[k]) if k in self.relax and k in old else v)
                for k, v in new.items()}


def worst_change(settings: Settings, old: dict, new: dict) -> tuple[float, str]:
    """Largest fractional change (EIA's measure) over divisions 1-9, for the pass report."""
    worst, where = 0.0, ""
    for k, n in new.items():
        if k not in old:
            continue
        frc, _ = settings.fraction(np.asarray(old[k])[DIVISIONS], np.asarray(n)[DIVISIONS])
        frc = np.where(np.isfinite(frc), frc, 0.0)
        i = int(np.argmax(frc))
        if frc[i] > worst:
            worst, where = float(frc[i]), f"{k}, region {i + 1}"
    return worst, where


class Control:
    """One year's iteration control: FCRL, CTEST and STABLE as nems_flow.py sets them.

        ctl = Control(maxitr)
        while ctl.next():            # sets ctl.itr and ctl.fcrl for the iteration to run
            ... run the modules, collect each one's pass/fail ...
            ctl.done(ctest)          # ctest: every module passed (always False on itr 1)
    """

    def __init__(self, maxitr: int = MAXITR):
        self.maxitr = maxitr
        self.itr = 0
        self.fcrl = 0
        self.stable = False
        self._ctest = 0
        self._inner = False

    def next(self) -> bool:
        nxt = self.itr + 1
        while True:
            if not self._inner:   # the outer loop: "restart point for the final loop"
                if self.stable or nxt > self.maxitr + 1:
                    return False
                self._ctest = 0
                self._inner = True
            if self._ctest == 0 and (nxt <= self.maxitr or (nxt == self.maxitr + 1 and self.fcrl == 1)):
                self.itr = nxt
                return True
            self._inner = False   # inner loop over: out of iterations without converging -> final loop
            if self._ctest == 0 and nxt <= self.maxitr + 1 and self.fcrl == 0:
                self.fcrl = 1

    def done(self, ctest: bool) -> None:
        self._ctest = int(bool(ctest))
        if not ctest:
            if self.itr <= self.maxitr and self.fcrl == 1:
                self.fcrl = 0          # out of convergence on the final loop: go on
        elif self.fcrl == 1:
            self.stable = True         # converged twice running
        else:
            self.fcrl = 1              # converged: one more iteration, the final loop
