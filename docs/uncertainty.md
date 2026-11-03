# Uncertainty bands

`src/nems_open/uncertainty.py` runs the fast loop many times over the inputs EIA itself varies, and the demo
shows the 10th, 50th and 90th percentiles of US energy CO2, the household energy bill and the price of gas to
homes, with a bar chart of which input explains the most spread.

**Read this first.** The bands come from our sampling. They are not EIA's. They run on stand-ins (the fast demand
stub and the fitted supply curves), so they show how far EIA's own side cases spread the stand-in model's
answer, not how uncertain EIA's model is.

## Where the ranges come from

EIA publishes side cases around the AEO2026 reference. Each pair is one uncertain input, and the ends of every
range are EIA's runs (`src/nems_open/uncertainty_ranges.json`, which also records what each end does):

| Input | Low end | High end | What the ends do in 2050 (against the reference) |
|---|---|---|---|
| Oil and gas supply | `lowogs` | `highogs` | Brent +23% / -15%; gas to homes +51% / -6.5%; energy use -11% / +8% |
| Economic growth | `lm2026` | `hm2026` | electricity sales -5.0% / +5.9%; energy use -5.9% / +6.9% |
| Electricity load growth | the reference | `higheldmd` | electricity sales +8.5% |
| Zero-carbon technology cost | `lowztc` | `highztc` | energy use -3.2% / +0.5% |

AEO2026 has no oil price case. Brent moves with the oil and gas supply cases, so oil price and gas supply are one
input, not two. Load growth is one-sided because EIA publishes only a high electricity demand case. `python -m
nems_open.uncertainty ranges` re-measures the table from the restart files and rewrites the data file.

## How a run is built

A run takes a weight `w` for each input between -1 (EIA's low case) and +1 (its high case), 0 being the reference.
The run's baseline (every price, quantity, Brent, the GDP deflator and the household count) is the reference plus
`|w|` times the difference of the case on that side of zero, added up over the inputs. The loop then runs on
that baseline with any policy on top (`run_model.run(..., base=blend)`).

What is ours, not EIA's:

- **The shape between the ends.** Weights are drawn from a triangular distribution with its most likely value at
  the reference (on [-1, 1], or [0, 1] for load growth), by Latin hypercube so every part of every range is used.
  EIA does not say how likely its high and low cases are.
- **Effects add.** Two cases are combined by adding their differences from the reference. EIA's own model would
  let them interact.
- **The stand-ins.** The loop's demand is EIA's reference demand moved by fitted price elasticities, and supply is
  the fitted curves (docs/supply_standin.md, docs/run_model.md). The oil and gas supply cases are not
  reproduced by the stand-in from the reference; here they enter as the baseline, which is what the stand-in is
  built to do.

## The three measures

- **US energy CO2:** `RunResult.co2_total`, million metric tons.
- **Household energy bill:** residential electricity, gas, LPG, distillate, kerosene and coal, price times use
  (US), divided by housing units (`RESDREP/rshouses`, blended like everything else), in 2024 dollars. Wood has no price and is left out.
- **Home gas price:** `MPBLK/pngrs` for the US, in 2024 dollars per MMBtu.

Dollars are converted from the model's 1987 dollars with the GDP deflator in the reference case.

## Which input explains the spread

For each measure and year, the share of the variance explained by each input alone: the correlation ratio over
ten equal-count bins of that input's weight, less the share an input with no effect scores by chance
(`(bins - 1) / (n - 1)`). The shares add to about 100% because the model is close to additive, and the bar chart
sorts them. They say which input moves the answer most, not why.

## Running it

```
python -m nems_open.uncertainty ranges                      # measure each swing
python -m nems_open.uncertainty run --n 1000 --carbon 0     # resumes if stopped; two workers at most
python -m nems_open.uncertainty summary --carbon 0 50 100   # writes web/data/uncertainty.json and .js
```

Raw results (one `.npz` per carbon price) go to `data/uncertainty/`, which is git-ignored. The run saves every 50
samples. A run with no carbon price takes about 3 seconds; with a carbon price 8, because the loop needs more
passes a year to settle. The demo's bands: no carbon price with 1,000 runs, and a $50 and a $100 carbon price
with 300 runs each (the file says how many).

## Limits

- Four inputs only, the ones EIA varies. EIA's own uncertainty also includes inputs it never varies (policy,
  behaviour, technology breakthroughs); none of that is here.
- With the oil and gas supply input one of four and its range very wide, it explains most of the spread in prices
  and bills. That follows from EIA's two cases moving gas prices a lot, not from a finding about the world.
- The bands for a carbon price assume the same input ranges as without one.
