"""The full model: demand and supply alternate each year until prices settle.

The year loop is NEMS's integrating module (converge/: EIA's relaxation factors, convergence
tests and iteration control, ported from nems-upstream models/converge and nems_flow.py). Each
iteration runs the demand modules on the current prices, then the supply side on that demand.
From the second iteration on, each step is tested on what it changed (1% by EIA's measure,
with EIA's absolute tolerances) and its outputs are relaxed by EIA's factor per variable
(most prices 0.5, power-sector fuel use 0.8, end-use quantities 1). Once every step passes,
one more iteration runs with FCRL = 1 (the final convergence and reporting loop); passing
again ends the year. At most MAXITR iterations plus that final one (cb2026: 2 + 1).
cycles > 1 repeats the whole run, relaxing every year between cycles by EIA's intercycle
factors, as NEMS's NRUNS does (cb2026 runs 5).

Supply is the stand-in (docs/supply_standin.md). With ogs="ngmm" or "hsm" gas prices come from the gas
market instead (nems_open/ngmm, docs/ngmm.md): NGMM's supply curve around expected production, cleared
on the loop's gas use each iteration; with "hsm" EIA's HSM sets that expected production between cycles
(cycles >= 2) and reports production at the end. With elec="lp" the power sector comes from the
dispatch LP instead (docs/dispatch.md): electricity sales in; fuel use, power CO2 and the wholesale
marginal cost out, with the carbon price in plant costs. Retail electricity prices come from
EIA's ported pricing model (emm/retail.py: LDSM and EFP on the loop's electricity sales) by
default with elec="lp" on cb2026, else from the stand-in; elec_price picks either. Demand goes
through one adapter (demand_adapter.py): by default EIA's ported residential and commercial
modules (PORTED; residential runs in a worker process alongside commercial), a stub elsewhere.
ported=() puts every sector on the stub, which runs in seconds.

    python -m nems_open.run_model --carbon 50 --ev 0.8 --efficiency 0.9
"""

import argparse
from dataclasses import dataclass, field

import numpy as np

from nems_open.converge import MAXITR, NRUNS, Control, Settings, worst_change
from nems_open import levers
from nems_open.demand_adapter import DemandAdapter, Policy
from nems_open.supply_standin import SupplyStandin
from nems_open.supply_standin.data import FIRST_YEAR, LAST_YEAR, US

PORTED = ("residential", "commercial")  # sectors run through EIA's ported modules by default


@dataclass
class Pass:
    year: int
    number: int                  # NEMS's CURITR
    max_price_change: float      # EIA's fractional change, divisions 1-9, supply's raw answer vs the prices it saw
    worst_price: str             # e.g. "MPBLK/pngin, region 3"
    max_quantity_change: float   # the same, demand vs the previous iteration
    routines: list[str]
    converged: bool              # every step passed EIA's test (never on iteration 1)
    fcrl: int = 0                # 1 on the final convergence and reporting loop
    failing: list[str] = field(default_factory=list)   # variables that failed the test
    cycle: int = 1


@dataclass
class RunResult:
    prices: dict[str, np.ndarray]       # MPBLK, (11, 61), 1987 $/MMBtu
    quantities: dict[str, np.ndarray]   # QBLK, (11, 61), trillion Btu
    co2: dict[str, np.ndarray]          # sector -> (11, 61), million metric tons CO2
    passes: list[Pass] = field(default_factory=list)
    wholesale: np.ndarray | None = None      # (25, 61) EMM regions, 1987 $/MWh; filled for elec="lp"
    wholesale_us: np.ndarray | None = None   # (61,) load-weighted, 1987 $/MWh; NaN where not solved
    generation_twh: dict | None = None       # group -> (61,), US, elec="lp"
    stable: dict[int, bool] = field(default_factory=dict)   # year -> converged twice running (last cycle)
    unserved_twh: np.ndarray | None = None   # (61,) load the LP's fixed fleet could not meet, elec="lp"
    curtailed_twh: np.ndarray | None = None  # (61,) flexible load the LP cut, elec="lp"
    ogsm: dict | None = None                 # EIA's HSM output arrays (ogngprd, ogcoprd, ognowell, ...), ogs="hsm"
    gas: dict | None = None                  # gas market by year (61,): henry_hub, wellhead (1987 $), production,
                                             # expected, exports (Bcf); ogs="ngmm" or "hsm"

    @property
    def co2_total(self) -> np.ndarray:
        return sum(v[US] for v in self.co2.values())

    def report(self) -> str:
        lines = ["cycle year itr fcrl  max dP/P   worst price               max dQ/Q   converged  failing"]
        for p in self.passes:
            lines.append(f"{p.cycle:5} {p.year} {p.number:3} {p.fcrl:4}  {p.max_price_change:9.2e}   {p.worst_price:24} "
                         f"{p.max_quantity_change:9.2e}   {str(p.converged):9}  {', '.join(p.failing[:4])}")
        return "\n".join(lines)


def default_elec_price(elec: str, baseline: str = "cb2026") -> str:
    """Retail electricity prices when elec_price is not given: EIA's ported EFP with the
    dispatch LP on cb2026 (where its oracle state exists), else the stand-in."""
    if elec == "lp" and baseline == "cb2026":
        from nems_open.emm import retail
        if retail.available():
            return "efp"
    return "standin"


def run(policy: Policy | None = None, start_year: int = 2027, end_year: int = LAST_YEAR,
        baseline: str = "cb2026", ported: tuple[str, ...] = PORTED, maxitr: int = MAXITR,
        cycles: int = 1, relax: bool = True, verbose: bool = False,
        elec: str = "standin", elec_price: str | None = None, base: dict | None = None,
        macro: str | None = None, ogs: str = "standin", record=None) -> RunResult:
    """Run the loop from start_year to end_year. Years before start_year keep the
    baseline's prices and quantities. elec: "standin" or "lp" (the dispatch LP).
    elec_price: retail electricity prices from the "standin" or from the ported "efp"
    (about 10 s an iteration, plus a pre-roll from 2021 to start_year); None picks
    default_elec_price(elec, baseline). maxitr, cycles: NEMS's MAXITR and NRUNS.
    relax=False is IRELAX = 0 (tests only, no relaxation). base: replace the baseline case's arrays
    (prices, quantities, Brent, macro) with these, e.g. a blend of EIA's cases (nems_open.uncertainty).
    macro: None keeps EIA's economy; "frbus" runs the economy module (nems_open.macro.drive) each cycle and feeds
    GDP, floorspace and industry output to demand; cycle 1 sees the oil price only, so use cycles >= 2.
    record: None, or a function called twice per iteration with what the loop just passed between
    modules: record("demand", ...) after demand answered (q updated, prices as demand saw them) and
    record("supply", ...) after supply answered (prices and power-sector fuel updated, plus co2, the
    convergence test and its worst change). Keyword arguments: cycle, year, itr, fcrl, j, prices, q, and
    for "supply" also co2, converged, dp, dq, worst. The arrays are the loop's own, live: copy what you keep.
    It reads only; the run is the same with or without it (scripts/think_runs.py uses it)."""
    if elec not in ("standin", "lp"):
        raise ValueError("elec must be 'standin' or 'lp'")
    if macro not in (None, "frbus"):
        raise ValueError("macro must be None or 'frbus'")
    if ogs not in ("standin", "ngmm", "hsm"):
        raise ValueError("ogs must be 'standin', 'ngmm' or 'hsm'")
    if ogs == "hsm" and baseline != "cb2026":
        raise ValueError("ogs='hsm' starts from the cb2026 restart, so the baseline must be cb2026")
    if elec_price is None:
        elec_price = default_elec_price(elec, baseline)
    if elec_price not in ("standin", "efp"):
        raise ValueError("elec_price must be 'standin' or 'efp'")
    if elec_price == "efp" and baseline != "cb2026":
        raise ValueError("elec_price='efp' starts from the cb2026 oracle state, so the baseline must be cb2026")
    policy = policy or Policy(start_year=start_year)
    supply = SupplyStandin(baseline, base=base)
    base = supply.base
    carbon = policy.carbon()
    oil, shifts = levers.brent(policy, base), levers.supply_shifts(policy, supply)
    market = None
    if ogs in ("ngmm", "hsm"):
        from nems_open.ngmm import GasMarket
        market = GasMarket(baseline, base=base)
    within, between = Settings.load("conv"), Settings.load("icnv")
    prices = {k: v.copy() for k, v in base.items() if k.startswith("MPBLK/")}
    q = {k: v.copy() for k, v in base.items() if k.startswith("QBLK/")}
    co2 = None
    passes, stable = [], {}
    lp = None
    wholesale = wholesale_us = generation = unserved = curtailed = None
    if elec == "lp":
        from nems_open.emm.couple import ElectricityLP
        lp = ElectricityLP(supply, capacity_scale=levers.capacity_scale(policy), added_load=policy.added_load)
        unserved, curtailed = np.full(61, np.nan), np.full(61, np.nan)
        wholesale = np.full((25, 61), np.nan)
        wholesale_us = np.full(61, np.nan)
        generation = {}
        cp87 = supply._cp87(carbon)
    years = slice(start_year - FIRST_YEAR, end_year - FIRST_YEAR + 1)

    for cycle in range(1, cycles + 1):
        path = None
        if macro == "frbus":
            from nems_open.macro.drive import scenario_macro
            path = scenario_macro(base, oil, prices if cycle > 1 else None)
        demand = DemandAdapter(base, policy, start_year, ported, macro=path)
        efp = None
        if elec_price == "efp":
            from nems_open.emm.retail import EfpPrices
            from nems_open.snapshot import Snapshot
            efp = EfpPrices(Snapshot(), start_year)
        routines = demand.routines + ["supply stand-in" if lp is None else "supply stand-in + dispatch LP"]
        if efp is not None:
            routines.append("EFP retail prices")
        before = {k: v[:, years].copy() for k, v in {**prices, **q}.items()}

        def solve_supply(j: int, itr: int, fcrl: int, relax_fuel: bool):
            """The supply side on the loop's current demand and prices; returns the result and
            the power-sector fuel use it priced (the LP's, relaxed as EIA relaxes EMM's outputs)."""
            if lp is None:
                s = supply.solve(q, oil, carbon, shifts=shifts, gas=market)
                fuel = {k: v[:, j] for k, v in s.power_fuel.items()}
            else:
                r = lp.solve(FIRST_YEAR + j, q, prices, float(cp87[j]))
                fuel = {k: v[:, j] for k, v in r.power_fuel.items()}
                if relax_fuel:
                    fuel = within.relaxed({k: q[k][:, j] for k in fuel}, fuel)
                    pf = {k: v.copy() for k, v in r.power_fuel.items()}
                    for k, v in fuel.items():
                        pf[k][:, j] = v
                else:
                    pf = r.power_fuel
                s = supply.solve(q, oil, carbon, power_fuel=pf, co2_el=r.co2_el, shifts=shifts, gas=market)
            if efp is not None:   # retail electricity prices from EFP on this iteration's sales
                for k, v in efp.price_pass(FIRST_YEAR + j, q, itr, fcrl).items():
                    s.prices[k][:, j] = v
            return s, fuel

        try:
            for year in range(start_year, end_year + 1):
                j = year - FIRST_YEAR
                ctl = Control(maxitr)
                while ctl.next():
                    itr, tested = ctl.itr, ctl.itr > 1   # EIA tests and relaxes from iteration 2
                    # Demand: quantities in, tested against what it saw.
                    q_old = {k: v[:, j].copy() for k, v in q.items()}
                    col = demand.solve_year(year, prices, itr)
                    if tested and relax:
                        col = within.relaxed(q_old, col)
                    bad = within.failing(q_old, col, q_old, {**q_old, **col}) if tested else {}
                    dq, _ = worst_change(within, q_old, col)
                    for k, v in col.items():
                        q[k][:, j] = v
                    if record is not None:
                        record("demand", cycle=cycle, year=year, itr=itr, fcrl=ctl.fcrl, j=j, prices=prices, q=q)
                    # Supply: prices and power-sector fuel use out, tested against what it saw.
                    s, fuel = solve_supply(j, itr, ctl.fcrl, tested and relax)
                    old = {k: prices[k][:, j].copy() for k in prices}
                    new = {k: s.prices[k][:, j] for k in prices}
                    fuel_old = {k: q[k][:, j].copy() for k in fuel}
                    q_now = {k: v[:, j] for k, v in q.items()}
                    if tested:
                        bad.update(within.failing({**old, **fuel_old}, {**new, **fuel}, q_now, {**q_now, **fuel}))
                    dp, worst = worst_change(within, old, new)
                    if tested and relax:
                        new = within.relaxed(old, new)
                        if lp is None:   # the LP's fuel use was relaxed before supply priced it
                            fuel = within.relaxed(fuel_old, fuel)
                    for k in prices:
                        prices[k][:, j] = new[k]
                    for k, v in fuel.items():
                        q[k][:, j] = v
                    ctest = tested and not bad
                    if record is not None:
                        record("supply", cycle=cycle, year=year, itr=itr, fcrl=ctl.fcrl, j=j, prices=prices, q=q,
                               co2=s.co2, converged=ctest, dp=dp, dq=dq, worst=worst)
                    passes.append(Pass(year, itr, dp, worst, dq, routines, ctest, ctl.fcrl, sorted(bad), cycle))
                    if verbose:
                        print(f"cycle {cycle} {year} itr {itr} fcrl {ctl.fcrl}: max dP/P {dp:.2e} ({worst}), "
                              f"max dQ/Q {dq:.2e}, failing {sorted(bad)[:4]}")
                    ctl.done(ctest)
                stable[year] = ctl.stable
                if market is not None:   # next year's curve centres on this year's wellhead price
                    market.settle(j)
                for k, v in s.totals.items():   # SUMQAS: all-sector totals
                    q[k][:, j] = v[:, j]
                if lp is not None:
                    last = lp.last[year]
                    wholesale[:, j] = last.wholesale
                    wholesale_us[j] = last.wholesale_us
                    unserved[j], curtailed[j] = last.unserved_twh, last.curtailed_twh
                    for g, v in last.generation_twh.items():
                        generation.setdefault(g, np.full(61, np.nan))[j] = float(v.sum())
                if co2 is None:
                    co2 = {k: v.copy() for k, v in s.co2.items()}
                for k, v in s.co2.items():
                    co2[k][:, j] = v[:, j]
                demand.end_year()
        finally:
            demand.close()  # stops the ported sectors' worker processes
        if ogs == "hsm" and cycle < cycles:   # HSM on this cycle's wellhead prices sets next cycle's expected production
            from nems_open.ogsm import couple
            market.set_hsm(couple.expected_ratio(market.wellhead_ratio(), _oil_ratio(oil, base)), market.P)
        if cycle < cycles and relax:   # IRELAX = 2: relax every year between cycles
            for d in (prices, q):
                for k in d:
                    if k in between.relax:
                        d[k][:, years] = before[k] + between.relax[k] * (d[k][:, years] - before[k])
    hsm = gas = None
    if market is not None:
        gas = {k: v.copy() for k, v in market.clear(q["QBLK/qngas"][US]).items()}
    if ogs == "hsm":   # EIA's HSM on the prices this run settled on (nems_open/ogsm/couple.py)
        from nems_open.ogsm import couple
        hsm = couple.production(market.wellhead_ratio(), _oil_ratio(oil, base))
    return RunResult(prices, q, co2, passes, wholesale, wholesale_us, generation, stable, unserved, curtailed, hsm, gas)


def _oil_ratio(oil, base):
    if oil is None:
        return None
    b = base["INTOUT/brent_price"]
    return np.divide(oil, b, out=np.ones(61), where=b > 0)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--carbon", type=float, default=0.0, help="2024 $ per metric ton CO2")
    ap.add_argument("--ev", type=float, default=None, help="plug-in share of new light-duty sales, 0-1")
    ap.add_argument("--efficiency", type=float, default=1.0, help="multiplier on building fuel use")
    ap.add_argument("--shell-code", type=float, default=0.0, metavar="FRACTION",
                    help="commercial building code: new buildings' heating and cooling shell factors fall by this fraction")
    ap.add_argument("--shell-year", type=int, default=2027, help="first year of the commercial building code")
    ap.add_argument("--standard", action="append", default=[], metavar="SERVICE:MIN_EFF:YEAR[:FUEL]",
                    help="commercial minimum efficiency, e.g. 2:3.5:2030:1 (cooling, electric); repeatable")
    for v in levers.LEVERS.values():
        if v.name not in ("carbon_price", "ev_share"):
            ap.add_argument("--" + v.name.replace("_", "-"), type=float, default=v.off, help=f"{v.title}: {v.unit}")
    ap.add_argument("--start", type=int, default=2027)
    ap.add_argument("--end", type=int, default=LAST_YEAR)
    ap.add_argument("--baseline", default="cb2026")
    ap.add_argument("--ported", nargs="*", default=list(PORTED),
                    help="sectors to run through EIA's ported modules (none: every sector on the stub)")
    ap.add_argument("--elec", choices=("standin", "lp"), default="standin",
                    help="power sector: the stand-in, or the dispatch LP (docs/dispatch.md)")
    ap.add_argument("--elec-price", choices=("standin", "efp"), default=None,
                    help="retail electricity prices: the stand-in, or EIA's ported EFP (emm/retail.py); "
                         "default efp with --elec lp on cb2026, else the stand-in")
    ap.add_argument("--ogs", choices=("standin", "ngmm", "hsm"), default="standin",
                    help="gas prices and production: the stand-in's curves; the gas market (ngmm); or the gas market "
                         "with EIA's HSM between cycles and at the end (hsm, about 9 min per HSM run)")
    ap.add_argument("--maxitr", type=int, default=MAXITR, help=f"iterations per year before the final loop (EIA cb2026: {MAXITR})")
    ap.add_argument("--macro", choices=("frbus",), default=None,
                    help="run the economy module (FRB/US) and feed GDP, floorspace and industry output to demand")
    ap.add_argument("--cycles", type=int, default=1, help=f"passes over all years, relaxed between (EIA cb2026: {NRUNS})")
    a = ap.parse_args(argv)
    commercial = None
    if a.shell_code or a.standard:
        from nems_open.commercial.levers import CommercialLevers, Standard
        stds = []
        for text in a.standard:
            f = text.split(":")
            stds.append(Standard(int(f[0]), float(f[1]), int(f[2]), int(f[3]) if len(f) > 3 else None))
        commercial = CommercialLevers(shell_improvement=a.shell_code, shell_start_year=a.shell_year, standards=tuple(stds))
    policy = Policy(a.carbon, a.ev, a.efficiency, a.start, commercial=commercial,
                    **{k: getattr(a, k) for k in levers.LEVERS if k not in ("carbon_price", "ev_share")})
    r = run(policy, a.start, a.end, a.baseline, tuple(a.ported), elec=a.elec, elec_price=a.elec_price, ogs=a.ogs,
            maxitr=a.maxitr, cycles=a.cycles, macro=a.macro)
    print(r.report())
    for name, v in levers.LEVERS.items():
        if getattr(policy, {"carbon_price": "carbon_price", "ev_share": "ev_share"}.get(name, name)) != v.off:
            grade, why = levers.fidelity(name, tuple(a.ported), a.elec)
            print(f"{levers.label(name, tuple(a.ported), a.elec)}: {grade}. {why}")
    if r.gas is not None:
        j = a.end - FIRST_YEAR
        print(f"\nGas market {a.end}: Henry Hub {r.gas['henry_hub'][j]:.2f} 1987 $/MMBtu, wellhead {r.gas['wellhead'][j]:.2f}, "
              f"dry production {r.gas['production'][j]:.0f} Bcf (expected {r.gas['expected'][j]:.0f}), exports {r.gas['exports'][j]:.0f}")
    if r.ogsm is not None:
        j = a.end - FIRST_YEAR
        print(f"\nHSM {a.end}: dry gas {r.ogsm['ogngprd'][j]:.0f} (ogngprd), crude {r.ogsm['ogcoprd'][j]:.1f} (ogcoprd), wells {r.ogsm['ognowell'][j]:.0f}")
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
