# Full-model loop

`src/nems_open/run_model.py` runs the whole model year by year, 2027 to 2050. Each year
alternates demand and supply until prices settle, the way NEMS's integrating module does.

```
python -m nems_open.run_model --carbon 50 --ev 0.8 --efficiency 0.9
```

```python
from nems_open.run_model import run
from nems_open.demand_adapter import Policy

r = run(Policy(carbon_price=50, ev_share=0.8, building_efficiency=0.9))
r.prices["MPBLK/pngrs"], r.quantities["QBLK/qngrs"], r.co2_total
print(r.report())   # one line per pass
```

## A year

The year loop is NEMS's integrating module, ported in `src/nems_open/converge/` from EIA's
Python integrator (nems-upstream `source/nems_flow.py`, `models/main/nems_iteration_loop.py`,
`models/converge/`). EIA's settings tables are copied there unchanged.

1. Each iteration (CURITR) runs demand on the current prices, then the supply side on that
   demand (the stand-in, or the dispatch LP and the stand-in, then EFP for retail
   electricity).
2. From iteration 2, each step is tested on what it changed: its outputs against the values
   it saw. A variable fails when, over divisions 1-9, some change reaches 1% of the
   midpoint (EIA's measure), some change reaches its absolute tolerance (10 trillion Btu
   for quantities, 0 for prices), and, for a price, its quantity is at least 10 trillion
   Btu somewhere. EIA tests the three separately (any() on each), and so does the port.
3. From iteration 2, each step's outputs are relaxed: new = old + factor x (new - old).
   Factors are EIA's per variable: 0.5 for electricity, oil product, coal-to-industry and
   most gas-to-power prices; 1.0 for gas to buildings and industry; 0.8 for power-sector
   gas, coal and oil use; 1.0 for end-use quantities.
4. Iteration control (FCRL): once every step passes, one more iteration runs as the final
   convergence and reporting loop (FCRL = 1). Passing again ends the year (stable); failing
   with iterations left clears FCRL and goes on. With no iterations left (MAXITR, 2 in
   cb2026) one final iteration runs with FCRL = 1. So a year takes 3 to MAXITR + 1
   iterations, and the last has FCRL = 1, which is when EFP writes its statements.
5. `cycles` repeats the whole run (NEMS's NRUNS, 5 in cb2026), relaxing every year between
   cycles by EIA's intercycle factors (icnv tables, IRELAX = 2). The default is one
   cycle: the loop starts from EIA's converged fifth cycle, which already plays the role of
   the earlier cycles.

The report lists, per iteration: cycle, year, CURITR, FCRL, the largest fractional price
and demand changes, whether every step passed, and which variables failed.

What differs from NEMS, and why:

- One cycle by default (see 5).
- Only the price and quantity tables are used. The loop has no endogenous GDP, world oil
  price, coal-unit or seasonal gas-to-utility variables (conv_Other, conv_Coal*,
  conv_*GasToUtilities), so those are not tested.
- Demand is one step: EIA tests and relaxes after each demand module, but no demand
  quantity has a factor other than 1 and the modules read only prices, so one step gives
  the same test and the same values.
- All-sector totals come from the last supply call (SUMQAS in NEMS recomputes them from
  the relaxed values).
- Iteration 1 demand sees the carried prices for the year (EIA's converged values, or the
  previous cycle's), as NEMS's iteration 1 sees its restart file.

### Measured against EIA's settings (stub demand, 2027-2050)

| Case | Iterations a year | Years stable | 2050 vs MAXITR = 20 |
|---|---|---|---|
| No policy | 3 | 24 of 24 | identical (EIA's reference within 7.5e-7) |
| Carbon $50/t, MAXITR = 2 (cb2026) | 3 | 24 of 24 | residential electricity +0.010%, gas -0.0002%, all-sector electricity use -0.007% |
| Carbon $50/t, MAXITR = 6 | 4 | 24 of 24 | identical |
| Carbon $50/t, MAXITR = 2, 2 cycles | 3 | 24 of 24 | residential electricity +0.002% |

With EIA's settings the stub loop converges every year inside cb2026's limit; EIA's 1%
tolerance leaves the answer within 0.01% of a run to full convergence. The old loop
(0.1% on prices, up to 20 passes) took 5 to 10 passes a year with a policy on.

Default demand (ported residential and commercial), 2027-2050: 125 s with no policy, 116 s
at $50/t, every year stable in 3 iterations. The old loop took 41 s with no policy (one
pass a year); EIA's control always runs at least 3 iterations (untested first, then the
pass that sets FCRL, then the final loop).

With `elec="lp"` on cb2026, retail electricity prices come from the ported EFP by default
(`default_elec_price`; the stand-in when EFP's oracle state is missing). Each loop
iteration is one EFP iteration with the loop's CURITR and FCRL, so the final loop writes
EFP's statements. `elec_price="standin"` keeps the stand-in's prices (the dispatch tests use
it, so a lone year needs no EFP pre-roll from 2021).

## Policy levers

| Lever | Units | Where it acts |
|---|---|---|
| `carbon_price` | 2024 $ per metric ton CO2 | Supply stand-in: added to delivered prices by carbon content |
| `ev_share` | plug-in share of new light-duty sales, 0-1 | Demand: gasoline to electricity in transport as the fleet turns over (15-year life) |
| `building_efficiency` | multiplier on residential and commercial fuel use | Demand: applied after the sector models |

A number applies from `start_year` (2027) on; an array of 61 values sets each year
1990-2050.

## Demand behind one adapter

`demand_adapter.DemandAdapter` gives the loop one call, `solve_year(year, prices, itr)`.
Per sector it uses:

- **EIA's ported module**, through the demand runner (`nems_open.run_demand`, branch
  `demand-runner`). Residential and commercial are ported. Opt in with
  `run(ported=("residential", "commercial"))`. The adapter moves the prices the modules
  read (AMPBLK, and the end-use electricity prices) by the same ratio as the stand-in's
  MPBLK prices against the baseline, then calls each module's iteration. These start
  from the oracle's state dumps, so they need the runner's checkout, and commercial
  takes about 5 minutes per iteration.
- **A stub** everywhere else: EIA's reference fuel use moved by a lagged own-price
  elasticity, per sector and fuel. Industrial and transportation have no port yet, so
  they always use the stub.

### Stub elasticities

Fitted from EIA's AEO2026 runs where prices move for supply-side reasons (high and low
oil and gas supply, high and low zero-carbon technology cost, alternative electricity),
with high and low growth added to separate out GDP. Divisions 1-9, 2027-2050. Each year
closes a share `k` of the gap to the long-run response, `k` fitted per sector.
`python -m nems_open.fit_elasticities`; full table in
[demand_elasticities.md](demand_elasticities.md).

| Sector (k) | Electricity | Natural gas | Distillate | Propane | Gasoline |
|---|---|---|---|---|---|
| Residential (0.4) | -0.28 (R2 0.89) | -0.18 (0.96) | -0.29 (0.06) | -0.23 (0.92) | |
| Commercial (0.4) | -0.19 (0.72) | -0.25 (0.98) | -0.26 (0.93) | -0.00 (0.95) | |
| Industrial (0.3) | -0.25 (0.75) | -0.22 (0.85) | -0.60 (0.81) | -0.30 placeholder | |
| Transportation (0.15) | | -0.20 placeholder | -0.25 (0.83) | | -0.06 (0.32) |

Placeholders (-0.3, or -0.2 in transport) stay where the fit has the wrong sign
(industrial propane and coal, jet fuel), the price barely moves (metallurgical coal), or
the row is something other than a price response (transport gas is mostly pipeline
compressor fuel, which follows gas throughput).

Checked against EIA (tests/test_run_model.py): fed a gas supply or zero-carbon case's own
prices, the stub's building gas and electricity use land within 4% of EIA's; industry
within 8% (cheap gas also grows industrial output in those runs, which an own-price
elasticity cannot carry).

Limits of the fit: own price only, so no switching between gas and electricity; the
cases move gas and power prices a lot and oil prices little (AEO2026 has no oil price
case), so oil-product numbers rest on less; the standard errors count every
division-year as independent and so overstate precision. The previous guesses (-0.3
buildings and industry, -0.2 transport, k 0.2) were in the same range for buildings
but well above the fitted gasoline response (-0.06).

With no policy, the loop reproduces EIA's reference prices, demand and CO2 exactly
(stub) or within the ported modules' own drift. Checked 2026-11-02 with ported
residential for 2030 (runner's working tree, oracle dumps, before the converge/ port): one pass, US residential
electricity and gas within 0.1% of EIA. At $50/t: four passes, residential gas -1.5%,
electricity -1.0%. Test: `NEMS_SLOW=1 pytest tests/test_run_model.py -k ported`, run
from a checkout that has both the demand runner and the oracle dumps.

## Limits

- The stub elasticities are fitted to how EIA's own model responds to prices, not to
  history, and only own-price. They are reduced-form stand-ins for the ports.
- The EV lever does not touch the transportation model's vehicle choice; it shifts fuel
  use directly. EIA's home charging sits in residential electricity; the lever puts all
  new EV electricity in transportation.
- Building efficiency is a flat multiplier, not a change to equipment menus.
- Everything in docs/supply_standin.md applies, above all: no power-sector abatement
  under a carbon price.
