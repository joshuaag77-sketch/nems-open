# Capacity expansion LP (step 4)

`nems_open.emm.capacity`: a myopic loop shaped like ECP. Each year starts from last year's capacity, adds the units the plant file already dates to that year, takes off the ones it dates to retire, then solves one LP for the rest. A full 2025 to 2035 run takes about 15 minutes (HiGHS, 1 to 2 minutes a year; 25 regions, 36 typical days of eight 3-hour blocks, trade over the regional links). Results are in `docs/capacity_results.md`; regenerate with `python -m nems_open.emm.capacity_report docs/capacity_results.md cache.pkl`.

## What the LP decides each year
- **Builds** of gas combined cycle, gas combined cycle with CCS, gas turbines, wind, solar and batteries. Cost is ECP's overnight cost (`UPOVR`) times the regional multipliers, annualized at an assumed 6.5% real rate over the type's economic life, plus fixed O&M, less that year's ITC and PTC from the SUBSIDY sheet. CCS plants get the 45Q credit in dispatch; the build decision charges back the part of a 30-year life the 12-year credit does not cover.
- **Retirements** of coal, steam, turbines and combined cycle, which save fixed O&M. From 2032 coal without CCS must retire (EIA's reference drops 60 GW of coal that year; the rule behind it is the power-plant carbon rule, E111D).
- **CCS retrofits** of coal units of 500 MW or more and 12,000 Btu/kWh or better (the plant file's own thresholds), up to 3 GW a year.
- **Dispatch** of the whole fleet (the step 2 model), so a plant's value is the fuel it displaces. A national reserve margin on firm capacity keeps the peak covered.
- Demand, fuel prices and the wind and solar profiles come from the reference run, as in step 2.

## Assumptions that are mine, not EIA's
- Annual build limits: 30 GW wind, 60 GW solar, 30 GW batteries, 30 GW each of combined cycle and turbines, 10 GW CCS. `ecpdaty.xlsx` sets none (999.9) and relies on resource supply curves that are not in the restart. Without limits the LP built 650 GW of wind in 2027, because the 16.5 $/MWh tax credit made it nearly free.
- Retirement limits: 10 GW a year of coal and of steam, 5 GW each of turbines and combined cycle (before the 2032 rule).
- No model-chosen builds before 2027, EIA's first year for them (ECP plans about three years ahead).
- Capacity credits for the reserve margin: wind 15%, solar 25%, batteries 90%, hydro 50%, nuclear 95%. EIA computes these from the load shape.
- The 6.5% discount rate stands in for the cost of capital EFP computes.

## Result, 2025 to 2035 (cumulative GW since end of 2024; model / EIA)
| | 2027 | 2030 | 2035 |
|---|---|---|---|
| Gas combined cycle | 33.5 / 6.1 miss | 53.5 / 43.1 miss | 156.5 / 146.0 |
| Gas combined cycle, CCS | 0 / 0 | 0 / 2.4 miss | 10.0 / 22.9 miss |
| Gas turbines | 7.0 / 22.4 miss | 7.0 / 49.5 miss | 37.0 / 119.5 miss |
| Wind | 53.8 / 23.8 miss | 117.0 / 60.7 miss | 147.5 / 194.2 miss |
| Solar | 154.5 / 100.9 miss | 214.8 / 135.5 miss | 236.0 / 182.7 miss |
| Batteries | 47.2 / 53.8 | 47.5 / 63.4 miss | 77.5 / 75.4 |
| Coal retired | 26.4 / 10.3 miss | 48.0 / 75.3 miss | 152.2 / 146.6 |
| Steam retired | 17.6 / 8.6 miss | 21.5 / 14.4 miss | 25.9 / 22.7 |

15% tolerance, and a gap under 2 GW is not a miss. **21 of 27 cells miss.** By 2035, five of eight categories are inside 15% or close: combined cycle (+7%), batteries (+3%), coal retired (+4%), steam retired (+14%). The misses are mostly structural:

- **Timing (2027 and 2030).** The LP builds at its annual limit the first year builds are allowed; EIA ramps. Same for retirements.
- **Turbines (-69% in 2035).** The LP covers the reserve margin with combined cycle. EIA builds 120 GW of turbines, which suggests its capacity credits for wind and solar are lower than the 15% and 25% I assumed. Capacity credits from the load shape are the fix.
- **Wind and solar.** The mix follows the tax-credit calendar (wind to 2029, solar to 2028) and my build limits, not EIA's resource supply curves.
- **CCS gas (-56%).** The 12-year credit against a 30-year life delays the LP's first build to 2032.
- **Nuclear (+6.7 GW vs 0).** Classification: the plant file dates nuclear uprates and restarts that EIA does not count as additions.
- **2025 and 2026.** The model has a reserve shortfall of about 45 GW and 10 to 13 TWh of unserved energy in those two years. With no model-chosen builds allowed, the dated builds alone leave it short of EIA's fleet. EIA's is thicker than the restart's capacity net of my mid-year averaging suggests; I did not find why.

## Next
Capacity credits from the load shape (replaces my fixed credits), the wind and solar supply curves, and build lead times by type. Those three would also move the timing misses, since they set how fast the LP is allowed to build.
