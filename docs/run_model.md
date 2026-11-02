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

1. Pass 0: the supply stand-in runs on the demand carried in, carbon price included, and
   its prices are taken whole. Exogenous moves land at once.
2. Each pass: demand on the current prices, then the supply stand-in on that demand.
   Prices move halfway to the new answer (relaxation 0.5).
3. The year is done when no price moved by more than 0.1% in a pass (prices near zero
   are measured against a 0.01 floor). Most years take 5 to 10 passes with a policy on,
   1 without.

The report lists, per pass: iteration count, largest relative price change and which
price, largest relative demand change, and the routines called.

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
- **A stub** everywhere else: EIA's reference fuel use moved by a lagged price
  elasticity (long run -0.3 for buildings and industry, -0.2 for transport, 20% of the
  gap closed each year). These numbers are placeholders, not fitted. Industrial and
  transportation have no port yet, so they always use the stub.

With no policy, the loop reproduces EIA's reference prices, demand and CO2 exactly
(stub) or within the ported modules' own drift.

## Limits

- The stub elasticities set how much demand answers a price. Until the ports replace
  them, the size of any demand response is an assumption.
- The EV lever does not touch the transportation model's vehicle choice; it shifts fuel
  use directly. EIA's home charging sits in residential electricity; the lever puts all
  new EV electricity in transportation.
- Building efficiency is a flat multiplier, not a change to equipment menus.
- Everything in docs/supply_standin.md applies, above all: no power-sector abatement
  under a carbon price.
