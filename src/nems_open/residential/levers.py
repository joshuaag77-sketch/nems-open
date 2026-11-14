"""Policy levers on residential inputs: change the tables' numbers, not the answers.

Each lever edits a table RESD reads every year (EIA's RSMSHL and RSMEQP records), so the ported
routines respond the way they would to a different input file. The edit lands when the run reaches
the lever's year, so years before it keep EIA's numbers.

  shell_improvement    RSMSHL HTSHEFF, CLSHEFF: new homes' heating and cooling shell factors fall
                       by this fraction (a stricter building code). No extra cost to the builder:
                       the commercial lever is the same (commercial/levers.py).
  standard_tightening  RSMEQP RTEQEFF: equipment on offer must be this fraction more efficient than
                       the least efficient model of its class in its division, never past the best
                       on offer. A model below the line takes the line's efficiency and the cost
                       read off the class's own efficiency-to-cost line (RTEQCOST, RTRECOST).
                       Records stay, because REPLACE stops at a class with no record.
"""

from dataclasses import dataclass

import numpy as np

f32 = np.float32
# End uses whose RTEQEFF is an energy efficiency: heating, cooling, water heating, cooking, dryers,
# refrigerators, freezers. Clothes washers and dishwashers (3, 4) carry theirs in other columns.
STANDARD_END_USES = (1, 2, 5, 6, 7, 8, 9)


@dataclass(frozen=True)
class ResidentialLevers:
    shell_improvement: float = 0.0
    standard_tightening: float = 0.0
    year: int = 2027

    def is_default(self) -> bool:
        return not (self.shell_improvement or self.standard_tightening)


def tighten(s: dict, x: float, year: int) -> int:
    """standard_tightening. Returns how many records changed."""
    eff, cost, recost = s["rteqeff"], s["rteqcost"], s["rtrecost"]
    first, last, cl, div, upt = s["rtinityr"], s["rtlastyr"], s["rttyeqcl"], s["rtcendiv"], s["rttyeupt"]
    changed = 0
    for eu in STANDARD_END_USES:
        groups = {}
        for i in range(int(upt[eu]) + 1, int(upt[eu + 1]) + 1):
            if last[i] >= year:
                groups.setdefault((int(cl[i]), int(div[i])), []).append(i)
        for rows in groups.values():
            on_sale = [i for i in rows if first[i] <= year] or rows
            e = np.array([float(eff[i]) for i in on_sale])
            order = np.argsort(e, kind="stable")
            ee = e[order]
            cc = np.array([float(cost[on_sale[k]]) for k in order])
            rr = np.array([float(recost[on_sale[k]]) for k in order])
            line = min(float(ee[0]) * (1.0 + x), float(ee[-1]))
            new_cost, new_recost = float(np.interp(line, ee, cc)), float(np.interp(line, ee, rr))
            for i in rows:
                if float(eff[i]) < line:
                    eff[i], cost[i], recost[i] = f32(line), f32(new_cost), f32(new_recost)
                    changed += 1
    return changed


def apply(levers: ResidentialLevers, s: dict) -> dict:
    """Edit the tables in s in place; returns counts of what changed."""
    changed = {}
    if levers.shell_improvement:
        keep = f32(1.0 - levers.shell_improvement)
        for name in ("htsheff", "clsheff"):
            s[name].a[...] = s[name].a * keep
        changed["shell_records"] = int(s["htsheff"].a.size)
    if levers.standard_tightening:
        changed["equipment_records"] = tighten(s, levers.standard_tightening, levers.year)
    return changed
