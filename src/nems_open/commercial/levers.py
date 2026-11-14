"""Policy levers on commercial inputs: change the files' numbers, not the answers.

Each lever edits one of the input tables `initial_state` builds from EIA's files, so the
ported routines respond the way they would to a different input file:

  shell_improvement       KSHEFF: new buildings' heating and cooling shell factors fall by this
                          fraction from shell_start_year on (a stricter building code)
  standards               KTEK: a minimum efficiency for one service from a year on. Equipment of
                          that service that falls below it stops being available the year before
                          (EIA encodes its own standards the same way, in the availability years)
  standard_tightening     KTEK: every major service, by fuel and region: equipment must be this fraction
                          more efficient than the least efficient on offer in tightening_year, the
                          plain form of `standards` (the best on offer always stays)
  minor_efficiency_growth KDELEFF: yearly efficiency improvement for the minor services (office
                          equipment and other loads), zero in the reference case

    Commercial.start_from_files(levers=CommercialLevers(shell_improvement=0.2))
"""

from dataclasses import dataclass, field

import numpy as np

from nems_open.commercial.inputs import BASEYR, NUM_BLDG, NUM_DIV

f32 = np.float32
MINOR_SERVICES = (8, 9, 10)
MAJOR_SERVICES = 7
FIRST_YEAR = 2019
LAST_YEAR = 2050


@dataclass(frozen=True)
class Standard:
    """A minimum efficiency (in the service's own units: COP, lumens per watt...) from `year` on.

    service: 1 space heating, 2 cooling, 3 water heating, 4 ventilation, 5 cooking, 6 lighting,
    7 refrigeration. fuel: 1 electricity, 2 gas, 3 distillate; None applies to every fuel
    (their efficiencies are not on one scale, so a fuel is usually named).
    """
    service: int
    min_eff: float
    year: int
    fuel: int | None = None


@dataclass
class CommercialLevers:
    shell_improvement: float = 0.0
    shell_start_year: int = 2026
    standards: tuple = field(default_factory=tuple)
    minor_efficiency_growth: float = 0.0
    standard_tightening: float = 0.0
    tightening_year: int = 2027

    def is_default(self) -> bool:
        return not (self.shell_improvement or self.standards or self.minor_efficiency_growth
                    or self.standard_tightening)


def apply_standard(t: dict, std: Standard) -> int:
    """Stop equipment under the standard being offered from std.year. Returns how many (tech, vintage, region) were dropped.

    The most efficient equipment of the service in each region always stays, so a standard can
    never leave a service with nothing to buy.
    """
    if not FIRST_YEAR < std.year <= LAST_YEAR:
        raise ValueError(f"standard year {std.year} must fall in {FIRST_YEAR + 1} to {LAST_YEAR}")
    s = std.service
    eff, avail, fuels = t["techeff"], t["techavailability"], t["fuelbytech"]
    dropped = 0
    for r in range(1, eff.a.shape[0] + 1):
        pairs = []
        for i in range(1, int(t["cmnumtechsforservice"][s]) + 1):
            tech = int(t["techsforservice"][s, i])
            if std.fuel is not None and fuels[tech, std.fuel] != 1:
                continue
            for v in range(1, int(t["cmnumeqv"][tech]) + 1):
                if t["techbymodel"][tech, v] == 1:
                    pairs.append((tech, v, float(eff[r, s, tech, v])))
        if not pairs:
            continue
        best = max(p[2] for p in pairs)
        for tech, v, e in pairs:
            if e < std.min_eff and e < best and avail[r, tech, v, 2] >= std.year:
                avail[r, tech, v, 2] = std.year - 1
                dropped += 1
    return dropped


def tighten(t: dict, x: float, year: int) -> int:
    """standard_tightening: the same cut as apply_standard, the line set per service, fuel and region
    from what is on offer in `year`. Returns how many (tech, vintage, region) were dropped."""
    eff, avail, fuels = t["techeff"], t["techavailability"], t["fuelbytech"]
    dropped = 0
    for s in range(1, MAJOR_SERVICES + 1):
        for fuel in (1, 2, 3):
            for r in range(1, eff.a.shape[0] + 1):
                pairs = []
                for i in range(1, int(t["cmnumtechsforservice"][s]) + 1):
                    tech = int(t["techsforservice"][s, i])
                    if fuels[tech, fuel] != 1:
                        continue
                    for v in range(1, int(t["cmnumeqv"][tech]) + 1):
                        if t["techbymodel"][tech, v] == 1 and avail[r, tech, v, 1] <= year <= avail[r, tech, v, 2]:
                            pairs.append((tech, v, float(eff[r, s, tech, v])))
                if not pairs:
                    continue
                low, best = min(p[2] for p in pairs), max(p[2] for p in pairs)
                for tech, v, e in pairs:
                    if e < low * (1.0 + x) and e < best:
                        avail[r, tech, v, 2] = year - 1
                        dropped += 1
    return dropped


def apply(levers: CommercialLevers, t: dict) -> dict:
    """Edit the tables in `t` (initial_state.tables()) in place; returns counts of what changed."""
    changed = {}
    if levers.shell_improvement:
        keep = f32(1.0 - levers.shell_improvement)
        first = levers.shell_start_year - (BASEYR - 1)
        for name in ("shellheatfactor", "shellcoolfactor"):
            a = t[name]
            for y in range(max(first, a.lb[3]), a.lb[3] + a.a.shape[3]):
                for b in range(1, NUM_BLDG + 1):
                    for r in range(1, NUM_DIV + 1):
                        a[b, r, 2, y] = f32(a[b, r, 2, y] * keep)
        changed["shell_years"] = LAST_YEAR - levers.shell_start_year + 1
    for std in levers.standards:
        changed[f"standard_s{std.service}_{std.year}"] = apply_standard(t, std)
    if levers.standard_tightening:
        changed["tightened"] = tighten(t, levers.standard_tightening, levers.tightening_year)
    if levers.minor_efficiency_growth:
        for s in MINOR_SERVICES:
            t["effgrowthrate"][s] = f32(levers.minor_efficiency_growth)
            t["ceffgrowth"][s] = f32(levers.minor_efficiency_growth)
    return changed
