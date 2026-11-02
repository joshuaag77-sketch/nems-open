# Supply stand-in

`src/nems_open/supply_standin/` is a temporary supply side. It lets the Python demand
modules run a closed loop (demand moves prices, prices move demand) before the real
supply modules are ported. It is not a port of anything EIA wrote. It is a small set of
price-response curves fitted to EIA's own AEO2026 runs.

Each piece will be replaced by a faithful port, one module at a time:

| Stand-in piece | Replaced by |
|---|---|
| Electricity prices, power-sector fuel use | Electricity Market Module (EMM: `uecp.f`, `uefd.f`, `uefp.f`, ...) |
| Natural gas prices | Natural Gas Market Module (`models/ngas`) plus HSM (already Python) |
| Refined product prices, crude pass-through | Liquid Fuels Market Module (`refine*.f`, `models/lfmm`) and the International module (`world.f`) |
| Coal prices | Coal Market Module (`models/coal`) |
| CO2 accounting | Already EIA's carbon factors (EMEBLK); EPM (`models/epm`, already Python) for policy |

When a real module lands, the runner calls it instead of the stand-in for that fuel. The
stand-in's other prices keep working, because each price is fitted on its own.

## What it does

```python
from nems_open.supply_standin import SupplyStandin

supply = SupplyStandin("cb2026")              # any AEO2026 case can be the baseline
r = supply.solve(demand, brent=None, carbon_price=None)
r.prices["MPBLK/pelrs"]                        # (11, 61), 1987 $/MMBtu, region 10 = US
r.power_fuel["QBLK/qngel"]                     # power-sector fuel use, trillion Btu
r.co2["el"], r.co2_total                       # million metric tons CO2
```

- `demand`: QBLK arrays for the four end-use sectors (`QBLK/q<fuel>rs`, `cm`, `in`,
  `tr`), shape (11 regions, 61 years 1990-2050). Anything missing keeps the baseline.
  Power-sector and all-sector entries are computed, not read.
- `brent`: Brent by year in 1987 $/bbl, the units of `INTOUT/brent_price`. This is the
  oil price lever. Default: the baseline's.
- `carbon_price`: 2024 $ per metric ton CO2, a number or one per year.
- Returns every MPBLK price under its restart-file name, so a demand port reads it the
  way it reads EIA's restart file.

With baseline demand and no levers it returns the baseline's prices and CO2 exactly.

## How it works

1. **Power-sector fuel.** A change in US electricity sales changes each power-sector fuel
   by a fitted amount per Btu sold: gas 0.83, coal 0.08, wind 0.49, solar 0.12 (the full
   list is in the fit report). The change is split across regions by the baseline's
   regional split of that fuel.
2. **Fuel switching in power plants.** Gas and coal burn then move with each fuel's
   effective cost to a power plant (delivered price plus carbon cost):

       log Q_gas  = log Q0_gas  - 0.76 * dlog C_gas + a_gc * dlog C_coal
       log Q_coal = log Q0_coal + 0.76 * dlog C_gas - 0.76 * dlog C_coal

   Whatever gas and coal stop burning is made up by zero-carbon generation (sales are
   held). Lower gas burn lowers the gas price, which feeds back into burn, so this step
   and the next iterate to a fixed point (about 10 rounds). See "Power-sector switching"
   below.
3. **Fuel totals.** Each fuel's total use is the baseline total plus the change in every
   sector that uses it, power included.
4. **Prices.** Each MPBLK price moves from the baseline by

       P = (P_base + crude) * exp(a * dlog Q_fuel + c * dlog P_gas_to_power)

   - `dlog Q_fuel` is the change in log total use of that fuel. Electricity uses each
     census division's own sales; gas, oil products and coal use the US total, since
     those are national markets.
   - `c` only applies to electricity: the price of gas to power plants feeds through.
   - `crude` is the change in Brent passed through dollar for dollar to refined products
     (per barrel of product, using EIA's heat contents). This rule is set, not fitted:
     the demand-side cases barely move Brent, so a fit cannot identify it. It is tested
     on the two oil and gas supply cases, which move Brent by -15% and +23% and are not
     in the fit. Propane and ethanol do not follow crude.
5. **Carbon price.** Added on top: each fossil fuel gets its carbon content times the
   price. Electricity gets the power sector's average CO2 per Btu sold, after switching
   (full pass-through).
6. **CO2.** Fuel use times EIA's carbon factors (EMEBLK), by sector, scaled to EIA's
   reported sector carbon in the baseline (that scale absorbs CCS and feedstocks).

## Data

EIA publishes 11 AEO2026 cases. Their finished NEMS runs ship in the upstream release
as restart files (`nems-upstream/output/aeo2026/<case>/<run>/restart.rlx`, an npz
archive), holding every regional price and quantity under the names our ports use. That
beats the AEO API for this job: full census-division detail, no key, no table mapping.
The API (`api.eia.gov/v2/aeo/2026`) and the bulk file
(`www.eia.gov/opendata/bulk/AEO2026.zip`) both work without registering (`DEMO_KEY`),
if a published table is ever needed.

```
python -m nems_open.supply_standin.data [path/to/nems-upstream]   # cache to data/aeo2026/
python -m nems_open.supply_standin.fit                            # refit, rewrite report
python -m pytest tests/test_supply_standin.py
```

`data/` is git-ignored. If the cache is missing, the model builds it from the upstream
restart files on first use.

Cases: cb2026 (reference), hm2026 and lm2026 (high and low economic growth), higheldmd
(high electricity demand), highogs and lowogs (high and low oil and gas supply), highztc
and lowztc (high and low zero-carbon technology cost), altelec (alternative electricity),
electrnp (alternative electricity and transportation). The upstream `alttrnp` folder is
a byte-for-byte copy of `electrnp`, so Alternative Transportation alone is not
available and is left out. AEO2026 has no high or low oil price case.

## Fit

Ordinary least squares, no intercept, on log deviations from the reference, census
divisions 1-9, years 2027-2050. Coefficients must be zero or positive. Each fuel is
fitted only on cases where its own supply side did not change:

- electricity and coal: hm2026, lm2026, higheldmd
- gas, oil products, propane: those three plus highztc, lowztc, altelec, electrnp
  (for gas these cases shift power-sector demand, which is what the fit needs)

Main coefficients (elasticity of price to the fuel's total use):

| Price | a (own use) | c (gas to power) | R2 | RMSE | spread before fit |
|---|---|---|---|---|---|
| Electricity, residential | 0.38 | 0.00 | 0.58 | 1.2% | 1.9% |
| Electricity, commercial | 0.29 | 0.10 | 0.44 | 1.7% | 2.2% |
| Electricity, industrial | 0.30 | 0.13 | 0.42 | 1.7% | 2.3% |
| Gas, residential | 0.13 | | 0.37 | 0.9% | 1.1% |
| Gas, commercial | 0.20 | | 0.36 | 1.4% | 1.8% |
| Gas, industrial | 0.51 | | 0.57 | 2.3% | 3.5% |
| Gas, power plants | 0.78 | | 0.65 | 2.9% | 5.0% |
| Gasoline, transport | 0.50 | | 0.95 | 1.1% | 4.7% |
| Jet fuel | 0.20 | | 0.10 | 1.9% | 2.0% |
| Propane, residential | 0.35 | | 0.32 | 1.6% | 1.9% |
| Distillate | 0 (crude only) | | | | |
| Coal, power plants | 0.03 | | none | 39% | 38% |

Delivered residential and commercial prices respond least because most of the price is
fixed delivery cost. Every fitted price, with leave-one-case-out and held-out errors, is
in [supply_standin_fit.md](supply_standin_fit.md).

End to end: each case's own end-use demand and Brent fed through the stand-in built on
the reference. Largest US error 2027-2050:

| | hm2026 | lm2026 | higheldmd | highogs | lowogs | lowztc | altelec | electrnp |
|---|---|---|---|---|---|---|---|---|
| Electricity, residential | 1.7% | 2.5% | 0.5% | 8.6% | 16% | 3.7% | 3.1% | 5.5% |
| Gas, residential | 1.3% | 1.3% | 0.7% | 9.0% | 35% | 2.1% | 1.7% | 2.1% |
| Gas, industrial | 4.7% | 4.0% | 2.8% | 44% | 64% | 7.4% | 4.5% | 7.0% |
| Gasoline | 3.3% | 2.2% | 0.6% | 5.4% | 15% | 0.6% | 0.9% | 3.6% |
| Diesel | 1.9% | 3.6% | 0.3% | 3.5% | 3.6% | 0.6% | 0.5% | 7.1% |
| Energy CO2 | 0.8% | 1.2% | 1.2% | 7.4% | 14% | 6.9% | 11% | 9.5% |

The tests hold the three demand-side cases to: electricity 3-4% (US), 10% (any
division); gas 2-6% (gas to power plants 6%, it moved from 4.9% to 5.2% on low growth
when switching was added); oil products 3-4%; CO2 1.5%. Refined products on the two oil and
gas supply cases, out of sample, within 10%.

## Power-sector switching

No AEO2026 case has a carbon price: every run's carbon adders are zero. So the switching
response is read from fuel prices instead. To a power plant a carbon price is just a
higher cost per MMBtu burned, and the high and low oil and gas supply cases move the
price of gas to power plants by -33% to +200%.

Fit: US, 2027-2050, cases hm2026, lm2026, higheldmd, highogs, lowogs. y is the log of
actual burn over the burn predicted from electricity sales alone (step 1); x is the log
change in the gas price to power plants. OLS, no intercept.

| Burn | Gas cost | Coal cost | n | R2 | RMSE |
|---|---|---|---|---|---|
| Gas | -0.76 | +0.76 x (coal burn / gas burn), by symmetry | 120 | 0.96 | 5.7% |
| Coal | +0.76 | -0.76, assumed equal to gas | 60 | 0.88 | 7.0% |

Coal is fitted only on years when the reference still burns at least 1,000 TBtu of it
(2027-2036); after that it is too close to zero to read.

What it does: at $100 per ton (2024 $), coal burn in 2027-2035 falls about 45-50%, part
of it moving to gas; gas burn falls about 30% from 2032; power-sector CO2 falls
20% in 2027 and 40% by 2050.

Limits of this piece:

- **Two of the three numbers are not fitted.** Coal's response to its own price is set
  equal to gas's, because coal prices barely move across the cases. Gas's response to
  coal's price follows from symmetry. Both are assumptions.
- **Out of sample.** The biggest gas-price move in the fit is +200%, a log change of 1.1.
  A $200 carbon price raises gas's cost to power plants by a log change of about 1.2 in
  2050, just past that range; coal's by about 2.2, well outside it (capped at 3). Read
  results above $100 as extrapolation.
- **Fuel-price changes are not policy.** In the gas supply cases a high gas price lasts
  the whole run and plants are built for it. A carbon price introduced in 2027 is treated
  the same way: no lag for building replacement capacity, so early-year cuts are likely
  too fast.
- **Renewable build cost is not priced in.** Whatever gas and coal stop burning is
  replaced by zero-carbon power at no extra cost. Electricity prices only see the carbon
  cost of the power that is still fossil, so their rise under a carbon price is
  understated.
- **Nuclear, CCS and storage do not respond on their own.** They sit inside "zero-carbon"
  and are not modelled separately.

## Limits

- **Supply shocks are scenarios, not levers.** The stand-in cannot produce the oil and
  gas supply or zero-carbon cost cases from the reference (gas price errors of 40-70%).
  Pick that case as the baseline instead: `SupplyStandin("lowogs")` reproduces it
  exactly and responds to demand around it.
- **Power-sector switching is a fitted curve, not a dispatch model.** See above. The
  EMM port replaces it.
- **Small sample.** Electricity and coal rest on three cases. The electricity fit
  explains about half the spread. Regional electricity errors reach 8-10% where load
  growth is concentrated (data centers in higheldmd). The gasoline slope rests almost
  entirely on electrnp, the one case with a big gasoline demand shift: refitted without
  it, gasoline misses electrnp by 22%.
- **Coal is noise.** Reference coal use is close to zero by 2050, so coal prices swing
  without a pattern. The coal fits are kept for completeness; do not read them.
- **Annual, no expectations.** Prices respond within the year. No capacity build lag, no
  storage, no trade beyond what the fitted curves imply.
- **Power-sector fuel shares are fixed at the margin.** One fitted mix applies to any
  change in demand, in any region and year.
- **Clipping.** A fuel's log change is capped at plus or minus 1 (a factor of e), so a
  fuel driven to zero cannot blow up a price.
