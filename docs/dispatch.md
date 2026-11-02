# Dispatch LP (step 2)

`nems_open.emm.dispatch`: a linopy + HiGHS model shaped like EFD. One year, 25 EMM regions, 36 typical days of 24 hours (about 240,000 variables, 59,000 rows). HiGHS solves a year in 5 to 8 seconds, so four years take under a minute. Results against the AEO2026 reference are in `docs/dispatch_results.md` (regenerate with `python -m nems_open.emm.dispatch_report docs/dispatch_results.md`).

## What it does
- Thermal groups (coal, gas combined cycle, gas turbines, steam) dispatch on fuel cost plus variable O&M, limited by forced outage and maximum capacity factor.
- Nuclear runs at its monthly capacity factor. Hydro dispatches inside a monthly energy budget. Wind and solar use EIA's hourly profiles (`WRENEW/ws*_cf`) cut by each type's outage rate. Batteries and pumped storage cycle inside each day.
- Capacity by group, fuel prices by region, outage rates and the wind and solar profiles come from the reference run's arrays. Heat rates, variable O&M and monthly capacity factors come from the plant file and ECP tables (step 1).
- Load is the step 1 shapes scaled to the demand modules' sales (`demand.py`): census sales to EMM regions by load share, plus delivery losses, less cogeneration and rooftop solar, less Canada/Mexico net imports.
- Outputs: generation by group and region, fuel use (coal, gas, distillate, residual, uranium), CO2 (with capture on CCS capacity), marginal cost by region, day and hour.

## Result (trade="reference": each region's load set to EIA's regional generation)
Tolerance 10%, and a miss must also be over 0.5% of the national total.

| | 2025 | 2030 | 2040 | 2050 |
|---|---|---|---|---|
| Coal generation | +5% | -11% MISS | +80% MISS | none left |
| Gas generation | -1% | +15% MISS | +13% MISS | +14% MISS |
| Nuclear | -1% | -2% | -2% | -2% |
| Renewables | +11% MISS | 0% | -1% | 0% |
| Coal use | +9% | -10% MISS | +40% MISS | none left |
| Gas use | -12% MISS | +3% | -1% | +2% |
| Power CO2 | -1% | -3% | +21% MISS | +7% |

Total generation matches by construction. 10 of 28 scored cells miss.

## Why it misses
- **Coal in 2030 and 2040.** EIA runs coal at about 44% capacity factor in 2040 (63 TWh from 16 GW). A pure cost merit order runs the cheaper coal flat out. EFD has commitment, contract and coal-supply constraints the LP lacks. This is the main gap and drives the 2040 CO2 miss.
- **Gas generation 13 to 15% high** in 2030 to 2050 is the other side of the coal and CCS gap. Gas fuel is within 3% in those years, because EIA's gas fleet burns more fuel per kWh than plant-file heat rates give.
- **2025 renewables +11%.** Year-end capacity overstates a year that is still building; averaging this year and last for wind and solar helped (it was +16%) but not enough.
- **2025 gas use -12%.** Same heat-rate gap, plus oil: the model burns 9 trillion Btu of oil against EIA's 138 (not scored).
- **No trade between regions.** With trade="none" (sales-based load) the same four years show 11 misses, and 2025 and 2030 have a few regions that cannot meet load (marginal cost 130+ 1987$/MWh).

## Next
Plant-level coal commitment or a minimum-output rule, heat-rate curves by load, and interregional trade are the three changes that would close most misses. Trade belongs in step 4, with the capacity LP.
