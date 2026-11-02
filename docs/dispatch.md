# Dispatch LP (steps 2 and 2b)

`nems_open.emm.dispatch`: a linopy + HiGHS model shaped like EFD. One year, 25 EMM regions, 36 typical days of 24 hours. Without trade a year solves in 5 to 8 seconds; with the regional links it takes about 35 seconds. Results against the AEO2026 reference are in `docs/dispatch_results.md` (regenerate: `python -m nems_open.emm.dispatch_report docs/dispatch_results.md`, about 4 minutes).

## What it does
- Six thermal groups dispatch on fuel plus variable O&M: coal, coal with CCS, gas combined cycle, gas combined cycle with CCS, gas turbines, steam. Captured CO2 earns the 45Q credit (`TCS45Q/ccs_saline_45q`).
- Nuclear runs at its monthly capacity factor. Hydro dispatches inside a monthly energy budget. Wind and solar use EIA's hourly profiles (`WRENEW/ws*_cf`) cut by each type's outage rate. Batteries and pumped storage cycle inside each day.
- Regions trade over the links in the ETT table (`V_EMM_PRETTIN`: 127 rows, summer and winter MW, a $/MWh markup, 2% line loss, plus the new transmission EMM built, `UETTOUT/UTNEWTRN`).
- Capacity is what is in service on average through the year. The plant file's in-service and retirement months are used for dated units; capacity the restart shows beyond that is assumed to arrive mid-year.
- Load is the step 1 shapes scaled to the demand modules' sales (`demand.py`).
- `trade="none"` is the sales-based run with links (the real target). `trade="reference"` fixes each region's load at EIA's regional generation and has no links; it is kept as a control.

## Result, sales-based load with trade (the real target)
10% tolerance, and a miss must also be over 0.5% of the national total. Model vs EIA.

| | 2025 | 2030 | 2040 | 2050 |
|---|---|---|---|---|
| Coal generation | +5% | +4% | +47% MISS | none left |
| Gas generation | +8% | +15% MISS | +12% MISS | +6% |
| Nuclear | 0% | -1% | -2% | -2% |
| Renewables | +11% MISS | 0% | -1% | +1% |
| Coal use | +9% | +6% | +64% MISS | none left |
| Gas use | +1% | +5% | +3% | -2% |
| Power CO2 | +4% | +6% | +5% | -7% |

5 of 28 scored cells miss (was 10). Total generation is within 4% in every year without being forced. CO2 is inside tolerance in all four years. The fixed-regional-load control misses 8.

## What changed and what it fixed
1. **Coal (the biggest finding).** Three things were wrong, none of them a missing constraint:
   - The restart's CCS-retrofit capacity (`UCAPSQ*`) is a subset of coal-steam capacity (`UCAPCS*`), not extra. Counting both doubled coal capacity in 2040.
   - EIA's coal that survives to 2040 is all CCS-retrofitted, burning 12.7 to 14.3 thousand Btu per kWh (the plant file's with-capture heat rate), not 10.8. That is why EIA's coal fuel is 861 trillion Btu for 63 TWh.
   - CCS plants earn the 45Q credit, which is why EIA's gas CCS (`UGENCS`, 365 TWh in 2040) runs flat out. The LP now has coal-CCS and gas-CCS groups with the credit.
   Result: 2040 coal fell from +80% to +47%, 2040 CO2 from +21% to +5%, 2030 coal from -11% to +4%.
   I also read how EFD holds coal down. It has a minimum-run constraint (units flagged in `T_MRUN` must make 99% of their historical capacity factor) and a planned-maintenance requirement. I tried the minimum-run floor and it pushed 2025 and 2030 coal 15 to 18% too high, so it is not in the model. The regional maximum capacity factor (`UPMAXCF`) is also not a hard annual limit: EIA's own combined cycle runs above it.
2. **Trade.** Links turn sales-based load from "regions short" into a usable run. Gas fuel, CO2 and renewables are inside tolerance in 2030 to 2050. Cost: 35 seconds per solve. A few regions still run short in 2025 and 2030 (under 0.1% of load) and set a scarcity price, so the 2025 and 2030 marginal costs (57 and 47 1987$/MWh) are not meaningful yet.
3. **Mid-year capacity.** Using in-service months barely moved 2025. The plant file only dates a few planned units; most 2025 growth has no date. 2025 wind and solar still come out 9% and 18% above EIA with the same capacity and profiles, and 2030 matches. I could not find the cause.
4. **Oil.** EIA burns 138 trillion Btu of oil in 2025; the model burns 10. Two parts of that gap are not model errors:
   - 61 trillion Btu (45%) is Alaska and Hawaii. The restart has no capacity or fuel prices for them (rows 26 and 27 are empty in `UCAP*` and `UP*PRC`); NEMS handles them outside EFD. The report now compares oil on the 25 regions (77 in 2025).
   - In the 25 regions, distillate runs at 0.4 to 0.5% of coal fuel in almost every region (an ignition-fuel pattern), and 13 trillion Btu of residual oil burns in one region every year. Both are fixed by something other than price: oil costs 7 times gas. The input that sets them is not in the restart, so oil stays unscored.

## What is still wrong, and why (structural)
- **Coal 2040 (+47%).** EIA runs the remaining 16 GW of CCS coal at about 40% capacity factor. The LP runs it to its 65% maximum, because the 45Q credit makes it the cheapest plant. EIA's credit lasts 12 years per unit and ends for retrofits after 2038, so only part of the fleet earns it. That needs each unit's retrofit year (`COALEMM`), which is a coal-module interface, not an EFD input.
- **Gas generation 2030 and 2040 (+15%, +12%).** Mirror image of coal: the LP's coal runs differently from EIA's, and gas takes the rest. Gas fuel is within 5%, so the gas fleet's heat rates are about right.
- **2025 renewables (+11%).** Cause not found. Not capacity timing.
- **Marginal cost, and oil.** See above.

## Next
Per-unit retrofit years for the 45Q credit, and the fuel-share data behind the oil floors. Both need the coal and fuel-supply modules; neither is available from the restart.
