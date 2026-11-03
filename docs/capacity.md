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
After the 2026-11-03 lane work (below).

| | 2027 | 2030 | 2035 |
|---|---|---|---|
| Gas combined cycle | 21.8 / 6.1 miss | 34.0 / 43.1 miss | 147.2 / 146.0 |
| Gas combined cycle, CCS | 0 / 0 | 0 / 2.4 miss | 10.0 / 22.9 miss |
| Gas turbines | 7.0 / 22.4 miss | 7.0 / 49.5 miss | 43.2 / 119.5 miss |
| Wind | 53.8 / 23.8 miss | 117.0 / 60.7 miss | 152.3 / 194.2 miss |
| Solar | 154.5 / 100.9 miss | 214.8 / 135.5 miss | 214.8 / 182.7 miss |
| Batteries | 47.2 / 53.8 | 47.5 / 63.4 miss | 68.5 / 75.4 |
| Coal retired | 34.5 / 10.3 miss | 57.0 / 75.3 miss | 151.7 / 146.6 |
| Steam retired | 25.5 / 8.6 miss | 32.1 / 14.4 miss | 36.5 / 22.7 miss |

15% tolerance, and a gap under 2 GW is not a miss. **22 of 27 cells miss.** (It was 21 after the demand fix; the lane work below did not reduce the count.) Three categories are inside by 2035: combined cycle (+1%), batteries (-9%) and coal retired (+4%).

## Lane work, 2026-11-03: credits, retirements, renewables
- **Capacity credits from the load shape** (replaces my fixed 15%/25%/50%/90%). Net load is national load less the wind and solar already built; the peak is its top 88 hours. Wind and solar earn their average capacity factor over those hours (2025: wind 26%, solar 19%), so solar's credit falls as it is built. Storage earns the share of the near-peak window (7 to 8 hours) its duration covers (battery 46 to 53%, pumped 88%). Hydro earns what its monthly energy lets it deliver over that window (100%). Effect: small. Turbines are unchanged (+43 vs 120 GW).
- **EIA's own retirement cap** replaces my 10 GW a year limits. emmcntl.txt `%MAX RET RATE%` allows economic retirements of 3% of a region's capacity in the first year, rising a point a year to 6% (EP$RET in uecp.f). It is looser than mine, so the LP retires more, earlier. Coal is still +4% at 2035 but steam went from +40% to +61% over EIA. ECP also sorts each type into four retirement cost groups (5/45/40/10% of capacity) and applies a 5% hurdle rate; the LP has neither, and that is the most likely reason it retires steam EIA keeps.
- **Reserve margin on the sum of regional peaks** instead of the national coincident peak (about 6% higher), as EIA sets margins by region. Small effect.
- **2025 renewables overshoot found (dispatch, `docs/dispatch_fixes.md` addendum).** EIA holds early-year wind, solar and hydro to the Short-Term Energy Outlook (benchmark constraints within 2%, `steo_benchmark_emm.csv`), which is well below what WRENEW's new-build profiles give the old fleet (solar capacity factor 20% against 27%). The dispatch model now keeps the plant file's own capacity factor for units running by 2024 through 2026, fading out by 2029. 2025 renewables went from +11% to +3%.

## Why the turbines do not come
ECP's overnight costs (`UPOVR`, 1987$/kW) put combined cycle below turbines: AC 441, CC 465, AT 497, CT 977. With the same discount rate the LP always builds combined cycle for firm capacity. EIA builds 120 GW of turbines, so ECP must discount them differently: the input marks combined cycle (and coal) with a risk switch, and `uecp.f` takes a technology risk premium `UPRSK` off the discount rate, which the restart does not carry. Reading `UPRSK` from `udat.f` (line 6811) is the next step.

## Next
Capacity credits from the load shape (replaces my fixed credits), the wind and solar supply curves, and build lead times by type. Those three would also move the timing misses, since they set how fast the LP is allowed to build.

## Capacity by region and fuel against cb2026 (2026-11-03, branch emm-capacity2)
`python -m nems_open.emm.capacity_regions cache.pkl` scores each region and fuel group (25 regions x 7 fuels) at 5% with a 0.5 GW floor.

Baseline before this work: 125/175 cells inside in 2027, 83/175 in 2030, 65/175 in 2035.

### Change: coal-to-gas conversion
EIA's coal capacity does not only retire. Its gas conversion capacity (prefix `ng`) grows 14 to 50 GW between 2027 and 2031, which is why EIA steam capacity rises from 80 to 110 GW while the model's fell to 57. The LP now has a `convert` variable (coal to a new `gas_conv` group, heat rate +5%, variable O&M x0.75, fixed O&M x0.67, from emmcntl.txt `%CL_to_NG%`) at an assumed 100 1987$/kW. It counts against the retirement rate cap before 2032 and is exempt from the coal rule after.

Result (model / EIA GW, regions inside 5%):

| fuel | 2027: national model / EIA GW, regions inside 5% | 2030: national model / EIA GW, regions inside 5% | 2035: national model / EIA GW, regions inside 5% |
|---|---|---|---|
| coal | 129 / 153 (-16%), 17/25 | 107 / 88 (+21%), 7/25 | 18 / 16 (+11%), 17/25 |
| gas_cc | 282 / 269 (+5%), 20/25 | 294 / 308 (-4%), 12/25 | 408 / 429 (-5%), 2/25 |
| gas_ct | 148 / 165 (-10%), 16/25 | 147 / 191 (-23%), 13/25 | 147 / 260 (-44%), 6/25 |
| steam | 63 / 80 (-21%), 13/25 | 57 / 110 (-48%), 8/25 | 117 / 101 (+16%), 8/25 |
| wind | 205 / 175 (+17%), 21/25 | 268 / 212 (+27%), 11/25 | 298 / 344 (-13%), 10/25 |
| solar | 277 / 223 (+24%), 18/25 | 337 / 258 (+31%), 12/25 | 337 / 305 (+11%), 10/25 |
| battery | 72 / 78 (-8%), 20/25 | 72 / 88 (-18%), 20/25 | 72 / 100 (-28%), 14/25 |
| **all cells** | 125/175 inside | 83/175 inside | 67/175 inside |

### Reading it
- Inside 5% in 2035: 67/175 (was 65). Not close to the target.
- Conversion did not occur in 2028 to 2030 as it does in EIA; the model converts only at the 2032 rule year, which lifts 2035 steam to +16%. At 100 $/kW conversion is not worth it before the rule in this LP, and EIA's early conversions evidently follow rules the LP does not have (unit-level cost groups).
- Coal timing is the largest miss: EIA retires about 15 GW a year from 2027 (cap 153 to 78 GW by 2031) before the rule drops the rest; the model retires 16 GW in 2027 and then holds 105 GW until 2032. EIA's rate cap (3% rising to 6% of a region's total capacity) is not binding here; its retirement test is a per-unit hurdle on four cost groups (5/45/40/10% of capacity), which the LP lacks.
- Turbines remain 44% low in 2035 (147 vs 260 GW): EIA builds both conventional and advanced turbines, and the missing technology risk premium (UPRSK) keeps combined cycle cheaper in the LP.
- Capacity credit was not changed in this pass.

### Next
Unit-level retirement groups and hurdle for coal and steam; read UPRSK to price turbines; then capacity credits.
