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
residential for 2030 (runner's working tree, oracle dumps): one pass, US residential
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
