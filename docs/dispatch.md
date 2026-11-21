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

## Coal capacity factor: which number is off (branch coal-dispatch)
The capacity lane compared its 2031 coal (430 to 460 TWh) with ECP's planning dispatch (200 TWh). That is the wrong yardstick: ECP's dispatch is a planning estimate and EFD's is what cb2026 reports. EFD's numbers, from the restart (TWh; coal by fuel is UGNCLNR, by unit UGEN<type>):

| | 2031 EIA | 2031 dispatch | 2040 EIA | 2040 dispatch |
|---|---|---|---|---|
| Coal by fuel | 419 | 470 | 63 | 93 |
| of which coal units (pc + ig) | 353 | 470 | 63 | 93 |
| of which coal share of cofired units (ng) | 66 | 0 | 0 | 0 |
| Cofired units, all fuel | 129 | 19 (steam group) | 0 | 0 |
| Combined cycle (cc + ac; gas CCS cs) | 1,446; 23 | 1,501; 24 | 1,437; 365 | 1,485; 396 |
| Turbines (ct + at) | 65 | 0.3 | 90 | 8 |

UGENSQ (CCS retrofits) is a subset of UGENPC, as UCAPSQ is of UCAPCS, so pc + sq counts the retrofits twice. The earlier reading that EIA ran CCS coal at 87% from 2034 to 2038 (dispatch_fixes.md) was that double count plus the cofired units' coal: the retrofits run at 44% in every year from 2033.

So the capacity LP's coal is within 3 to 10% of what EIA reports, and its planning dispatch is not what is off. What is off is the dispatch itself (here and in the capacity LP, which shares it): EIA's coal units run at 42 to 48% of mid-year capacity in every year from 2028 to 2040 (2032, the rule year, aside), ours at the 0.65 maximum in 18 of 20 coal regions. In 2031 EIA's regional coal capacity factors range from 0.31 to 0.62 while coal costs 9 to 12 1987$/MWh to run against 16 to 18 for combined cycle. Turbines are the other gap (65 vs 0.3 TWh), in both models.

Ruled out, with numbers:
- Maximum capacity factor. The oracle's 2030 EFD composite (aimms-showreel sample) gives coal groups UG_SCF 0.65 to 0.72, with FOR 0.18 and PMR 0.185: udat.f CRPGRP's consistency rule (10168-10236, MXLFR 0) scales pltdata's 0.066 / 0.071 so that (1 - FOR)(1 - PMR) = 0.65, and the rule reproduces the composite to three decimals (combined cycle 0.075 / 0.061). Porting that per-slice derate leaves 2031 coal at 470 TWh and 2040 at 93: coal still reaches its annual cap. Not kept.
- Coal VOM and heat rate. EFD's coal groups: VOM 0.78 1987$/MWh (ours 0.77), heat rate 10,093 Btu/kWh (ours 10,762). EFD's coal is if anything cheaper.
- Coal price. UPCOLPRC equals UPCOALAVG; EFD's supply steps (XCL_PECP) rise under 15% across 1.54 times the base quantity, and XCL_PCAP is twice the coal burned. No quantity limit binds.
- STEO benchmark rows (emmcntl %BM QUANTY%: 2024 to 2026 only), the CF fade (UCFEYR 2030), 45Q (it lowers CCS coal's cost, so it cannot explain 44%).
- EPA 111 cofiring. EIA's ng units burn at least 40% gas from 2030 (udat.f 6457-6460) and run at 29%; treating them as cofiring here would add coal, not remove it.

No fix is justified from saved outputs. What would settle it is the coal columns' reduced costs in an EFD solution (cO, cJ, cU for a coal group), which needs an oracle EFD solve with its solution kept. Pinned by `tests/test_emm_dispatch.py::test_eia_coal_units_run_below_their_maximum`. Scripts: scratchpad `coaldisp/` (efd.py, reg.py, comp.py, comp2.py).

## What EFD's saved files show (branch coal-dispatch-2)
The oracle's 2030 EFD files (aimms-showreel sample, efd_2030_01 and _02) are not the matrix: the composite holds EFD's inputs (group capacity, FOR, PMR, max CF, heat rate, VOM, slice widths and heights, fuel curves) and the PassBack its outputs: ECDSPE and ECDSPC (energy and available capacity by unit group W_GRP and season), NMARCST (marginal cost by region, season and slice), UPFUEL (fuel prices). No column levels or reduced costs, but enough to answer the question. Scripts: scratchpad `coaldisp/` (pb.py, pb2.py).

**EFD's coal is held by capacity, not price.** In the oracle's 2030 EFD, coal makes 335 TWh on 74.6 GW (0.51 of nameplate). ECDSPC is capacity less forced outage (coal 60 GW = 74.6 x (1 - 0.19); combined cycle 231 = 248 x (1 - 0.075)). Of the 60 GW, 41 GW run at 0.70-0.80 of it in their seasons, which is their ceiling after planned maintenance (0.815) and the max-load mode's shape; 14 GW run at 0.3-0.6 (heat rates 11,000-11,500); 5 GW under 0.3. Marginal costs in every one of TRE's 9 slices are 14-50 1987$/MWh, above coal's 10; EFD's coal prices (UPFUEL 0.9-1.5) are ours. EFD dispatches only 3 slices per season (1%, 49%, 50% of hours), 9 a year.

**EIA's coal factor was low because of the capacity we compared it with.** On year-end capacity EIA's coal units run at 0.52 in 2030 (404 TWh on 88.2 GW) and 2031 (353 on 78.0), the oracle's 0.51. The dispatch put the year's undated capacity change half way through the year. For retirements that is wrong: ECP dates an economic retirement in year Y to December of Y - 1 (uecp.f 27095-27098), the UCAP tally counts units retiring in December in that year-end (udat.f 8261-8300), so the unit is gone for all of Y. In 2030 the dispatch had 99.9 GW of coal where EFD had 88.

**Fix.** `dispatch._in_service`: an undated net loss leaves for the whole year; an undated net gain still arrives mid-year (EMM's builds; mid-year keeps wind and solar on EIA's generation, while full-year raised 2031 wind from 734 to 772 TWh against EIA's 735). Sales-based load with trade, before / after / EIA, TWh:

| | 2030 | 2031 | 2040 |
|---|---|---|---|
| Coal (EIA by fuel) | 539 / 478 / 465 | 469 / 445 / 419 | 93 / 93 / 63 |
| Coal fuel, trillion Btu | 5,793 / 5,152 / 4,962 | 5,186 / 4,921 / 4,531 | 1,399 / 1,399 / 861 |
| Combined cycle (+ gas CCS) | 1,486+13 / 1,546+13 / 1,449+12 | 1,501+24 / 1,524+24 / 1,446+23 | 1,485+396 / same / 1,437+365 |
| Turbines | 0.3 / 0.5 / 67 | 0.3 / 0.4 / 65 | 8.2 / 8.2 / 90 |
| Gas, all | 1,515 / 1,582 / 1,469 | 1,543 / 1,568 / 1,477 | 1,893 / same / 1,779 |

The 2030 coal generation and fuel misses are gone (known misses in tests/test_emm_dispatch.py: 3 of 28, was 5); 2030 gas is +8%, inside tolerance.

**Still open.**
- Coal: 445 vs 419 in 2031 is 26 TWh, and against EIA's coal units (353) the gap is wider because EIA's 50 GW of cofired units burn 66 TWh worth of coal that the dispatch gives to gas steam. Our coal runs at its 0.65 cap; EFD's effective ceiling is about 0.62 of nameplate and a quarter of its coal (the higher heat rate groups) runs below it. One regional group at the average heat rate cannot reproduce that spread.
- 2040 CCS coal (93 vs 63) is unchanged: its capacity is flat from 2033.
- Turbines (0.4 vs 65 TWh). In the oracle EFD, gas turbines (CTG) make 32 TWh at 4.6% of their available capacity, and converted steam (CTN) 28. EFD's 1% peak slice and its spinning reserve rows, which buy reserve from turbines at minimum load, are what the dispatch lacks. EFD's per-slice derate (FOR and PMR scaled to the max CF, udat.f 10168-10236, reproduced to three decimals from the composite) was tried again: turbines 0.4 to 0.5 TWh, coal unchanged. Not kept.

The capacity LP carries its own fleet (year-end, `dated_changes`), so it only sees the fix through the heat rate and VOM weights of build_case. Planner chain 2027-2040 from EIA's 2026 fleet, 2040 GW before / after / EIA: CC 435 / 436 / 431, CT 234 / 234 / 267, batteries 108 / 108 / 103, solar 348 / 348 / 323, wind 383 / 383 / 404, coal 15 / 15 / 16, steam 56 / 56 / 52; builds by year move under 0.2 GW.

Pinned by `tests/test_emm_dispatch.py::test_undated_retirements_leave_for_the_whole_year`.
