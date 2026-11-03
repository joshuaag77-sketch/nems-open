"""The full model: demand and supply alternate each year until prices settle.

Like NEMS's integrating module, each year runs passes (after a pass 0 that applies the
supply side, carbon price included, to the demand carried in): demand modules on the current
prices, then the supply side on that demand, then the new prices are relaxed toward
the supply side's answer (P = P + RELAX * (P_new - P)). The year is done when no price
moved by more than TOL (relative) in a pass. Then the next year starts.

Supply is the stand-in (docs/supply_standin.md). With elec="lp" the power sector comes from the
dispatch LP instead (docs/dispatch.md): electricity sales in; fuel use, power CO2 and the wholesale
marginal cost out, with the carbon price in plant costs. Retail electricity prices stay with the
stand-in. Demand goes through one adapter (demand_adapter.py): by default EIA's ported
residential and commercial modules (PORTED; residential runs in a worker process alongside
commercial, about 40-65 s for 2027-2050), a stub elsewhere. ported=() puts every sector on the
stub, which runs in seconds.

    python -m nems_open.run_model --carbon 50 --ev 0.8 --efficiency 0.9
"""

import argparse
from dataclasses import dataclass, field

import numpy as np

from nems_open.demand_adapter import DemandAdapter, Policy
from nems_open.supply_standin import SupplyStandin
from nems_open.supply_standin.data import FIRST_YEAR, LAST_YEAR, US

RELAX = 0.5      # NEMS relaxes prices halfway between passes by default
TOL = 1e-3       # largest relative price change that counts as converged (0.1%)
MAX_PASSES = 20
PORTED = ("residential", "commercial")  # sectors run through EIA's ported modules by default


@dataclass
class Pass:
    year: int
    number: int
    max_price_change: float      # relative, before relaxation
    worst_price: str             # e.g. "MPBLK/pngin, region 3"
    max_quantity_change: float   # relative, demand vs the previous pass
    routines: list[str]
    converged: bool


@dataclass
class RunResult:
    prices: dict[str, np.ndarray]       # MPBLK, (11, 61), 1987 $/MMBtu
    quantities: dict[str, np.ndarray]   # QBLK, (11, 61), trillion Btu
    co2: dict[str, np.ndarray]          # sector -> (11, 61), million metric tons CO2
    passes: list[Pass] = field(default_factory=list)
    wholesale: np.ndarray | None = None      # (25, 61) EMM regions, 1987 $/MWh; filled for elec="lp"
    wholesale_us: np.ndarray | None = None   # (61,) load-weighted, 1987 $/MWh; NaN where not solved
    generation_twh: dict | None = None       # group -> (61,), US, elec="lp"

    @property
    def co2_total(self) -> np.ndarray:
        return sum(v[US] for v in self.co2.values())

    def report(self) -> str:
        lines = ["year pass  max dP/P   worst price               max dQ/Q   converged  routines"]
        for p in self.passes:
            lines.append(f"{p.year} {p.number:4} {p.max_price_change:9.2e}   {p.worst_price:24} "
                         f"{p.max_quantity_change:9.2e}   {str(p.converged):9}  {', '.join(p.routines)}")
        return "\n".join(lines)


def _max_rel_change(new: dict, old: dict) -> tuple[float, str]:
    worst, where = 0.0, ""
    for k, n in new.items():
        o = old[k]
        ok = np.abs(o) > 1e-9
        if not ok.any():
            continue
        # Relative to the value, but a price or quantity near zero is measured against a
        # floor (0.01) so a cent on a zero price does not stall convergence.
        rel = np.abs(n - o)[ok] / np.maximum(np.abs(o[ok]), 0.01)
        i = int(np.argmax(rel))
        if rel[i] > worst:
            worst, where = float(rel[i]), f"{k}, region {np.flatnonzero(ok)[i] + 1}"
    return worst, where


def run(policy: Policy | None = None, start_year: int = 2027, end_year: int = LAST_YEAR,
        baseline: str = "cb2026", ported: tuple[str, ...] = PORTED, relax: float = RELAX,
        tol: float = TOL, max_passes: int = MAX_PASSES, verbose: bool = False,
        elec: str = "standin") -> RunResult:
    """Run the loop from start_year to end_year. Years before start_year keep the
    baseline's prices and quantities. elec: "standin" or "lp" (the dispatch LP)."""
    if elec not in ("standin", "lp"):
        raise ValueError("elec must be 'standin' or 'lp'")
    policy = policy or Policy(start_year=start_year)
    supply = SupplyStandin(baseline)
    base = supply.base
    demand = DemandAdapter(base, policy, start_year, ported)
    carbon = policy.carbon()
    prices = {k: v.copy() for k, v in base.items() if k.startswith("MPBLK/")}
    q = {k: v.copy() for k, v in base.items() if k.startswith("QBLK/")}
    co2 = None
    passes = []
    lp = None
    wholesale = wholesale_us = generation = None
    if elec == "lp":
        from nems_open.emm.couple import ElectricityLP
        lp = ElectricityLP(supply)
        wholesale = np.full((25, 61), np.nan)
        wholesale_us = np.full(61, np.nan)
        generation = {}
        cp87 = supply._cp87(carbon)
    routines = demand.routines + ["supply stand-in" if lp is None else "supply stand-in + dispatch LP"]

    def solve_supply(j: int):
        """The supply side on the loop's current demand and prices."""
        if lp is None:
            return supply.solve(q, carbon_price=carbon)
        r = lp.solve(FIRST_YEAR + j, q, prices, float(cp87[j]))
        return supply.solve(q, carbon_price=carbon, power_fuel=r.power_fuel, co2_el=r.co2_el)

    try:
        for year in range(start_year, end_year + 1):
            j = year - FIRST_YEAR
            last_q = None
            # Pass 0: the supply side on the demand we have, taken whole. Exogenous moves
            # (a carbon price, a new baseline year) land at once instead of being relaxed in.
            s = solve_supply(j)
            for k in prices:
                prices[k][:, j] = s.prices[k][:, j]
            for n in range(1, max_passes + 1):
                col = demand.solve_year(year, prices, n)
                dq = 0.0
                if last_q is not None:
                    dq, _ = _max_rel_change(col, last_q)
                last_q = col
                for k, v in col.items():
                    q[k][:, j] = v
                s = solve_supply(j)
                new = {k: s.prices[k][:, j] for k in prices}
                old = {k: prices[k][:, j] for k in prices}
                dp, worst = _max_rel_change(new, old)
                done = dp < tol
                for k in prices:
                    prices[k][:, j] = new[k] if done else old[k] + relax * (new[k] - old[k])
                passes.append(Pass(year, n, dp, worst, dq, routines, done))
                if verbose:
                    print(f"{year} pass {n}: max dP/P {dp:.2e} ({worst}), max dQ/Q {dq:.2e}")
                if done:
                    break
            for k, v in {**s.power_fuel, **s.totals}.items():
                q[k][:, j] = v[:, j]
            if lp is not None:
                last = lp.last[year]
                wholesale[:, j] = last.wholesale
                wholesale_us[j] = last.wholesale_us
                for g, v in last.generation_twh.items():
                    generation.setdefault(g, np.full(61, np.nan))[j] = float(v.sum())
            if co2 is None:
                co2 = {k: v.copy() for k, v in s.co2.items()}
            for k, v in s.co2.items():
                co2[k][:, j] = v[:, j]
            demand.end_year()
    finally:
        demand.close()  # stops the ported sectors' worker processes
    return RunResult(prices, q, co2, passes, wholesale, wholesale_us, generation)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--carbon", type=float, default=0.0, help="2024 $ per metric ton CO2")
    ap.add_argument("--ev", type=float, default=None, help="plug-in share of new light-duty sales, 0-1")
    ap.add_argument("--efficiency", type=float, default=1.0, help="multiplier on building fuel use")
    ap.add_argument("--start", type=int, default=2027)
    ap.add_argument("--end", type=int, default=LAST_YEAR)
    ap.add_argument("--baseline", default="cb2026")
    ap.add_argument("--ported", nargs="*", default=list(PORTED),
                    help="sectors to run through EIA's ported modules (none: every sector on the stub)")
    ap.add_argument("--elec", choices=("standin", "lp"), default="standin",
                    help="power sector: the stand-in, or the dispatch LP (docs/dispatch.md)")
    a = ap.parse_args(argv)
    policy = Policy(a.carbon, a.ev, a.efficiency, a.start)
    r = run(policy, a.start, a.end, a.baseline, tuple(a.ported), elec=a.elec)
    print(r.report())
    supply = SupplyStandin(a.baseline)
    base, base_co2 = supply.base, supply.solve().co2_total
    j = a.end - FIRST_YEAR
    print(f"\n{a.end}, US          run   baseline")
    for k in ("MPBLK/pelrs", "MPBLK/pngrs", "MPBLK/pmgtr", "MPBLK/pdstr"):
        print(f"{k:14} {r.prices[k][US, j]:8.2f} {base[k][US, j]:8.2f}  1987 $/MMBtu")
    for k in ("QBLK/qelas", "QBLK/qngas", "QBLK/qmgtr"):
        print(f"{k:14} {r.quantities[k][US, j]:8.0f} {base[k][US, j]:8.0f}  trillion Btu")
    print(f"{'CO2':14} {r.co2_total[j]:8.0f} {base_co2[j]:8.0f}  million metric tons")


if __name__ == "__main__":
    main()
