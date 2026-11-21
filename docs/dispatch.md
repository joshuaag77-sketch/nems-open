# Dispatch LP (steps 2 and 2b)

`nems_open.emm.dispatch`: a linopy + HiGHS model shaped like EFD. One year, 25 EMM regions, 36 typical days of 24 hours. Without trade a year solves in 5 to 8 seconds; with the regional links it takes about 35 seconds. Results against the AEO2026 reference are in `docs/dispatch_results.md` (regenerate: `python -m nems_open.emm.dispatch_report docs/dispatch_results.md`, about 4 minutes).

## What it does
- Six thermal groups dispatch on fuel plus variable O&M: coal, coal with CCS, gas combined cycle, gas combined cycle with CCS, gas turbines, steam. Captured CO2 earns the 45Q credit (`TCS45Q/ccs_saline_45q`).
- Nuclear runs at its monthly capacity factor. Hydro dispatches inside a monthly energy budget. Wind and solar use EIA's hourly profiles (`WRENEW/ws*_cf`) cut by each type's outage rate. Batteries and pumped storage cycle inside each day.
- Regions trade over the links in the ETT table (`V_EMM_PRETTIN`: 127 rows, summer and winter MW, a $/MWh markup, 2% line loss, plus the new transmission EMM built, `UETTOUT/UTNEWTRN`).
- Capacity is what is in service on average through the year. The plant file's in-service and retirement months are used for dated units; capacity the restart shows beyond that is assumed to arrive mid-year.
- Load is the step 1 shapes scaled to the demand modules' sales (`demand.py`).
- EFD's spinning reserve rows, availability and planned maintenance, and oil units running last (`EFD_SPIN_RESERVE`, `EFD_DERATE`, `OIL_UNITS_LAST`, all on; section "EFD's spinning reserve and turbines" below). The results table above them predates these switches.
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
- Turbines (0.4 vs 65 TWh; 19 with the next section's switches). In the oracle EFD, gas turbines (CTG) make 32 TWh at 4.6% of their available capacity, and converted steam (CTN) 28. EFD's 1% peak slice and its spinning reserve rows, which buy reserve from turbines at minimum load, are what the dispatch lacks. EFD's per-slice derate (FOR and PMR scaled to the max CF, udat.f 10168-10236, reproduced to three decimals from the composite) was tried again: turbines 0.4 to 0.5 TWh, coal unchanged. Not kept.

The capacity LP carries its own fleet (year-end, `dated_changes`), so it only sees the fix through the heat rate and VOM weights of build_case. Planner chain 2027-2040 from EIA's 2026 fleet, 2040 GW before / after / EIA: CC 435 / 436 / 431, CT 234 / 234 / 267, batteries 108 / 108 / 103, solar 348 / 348 / 323, wind 383 / 383 / 404, coal 15 / 15 / 16, steam 56 / 56 / 52; builds by year move under 0.2 GW.

Pinned by `tests/test_emm_dispatch.py::test_undated_retirements_leave_for_the_whole_year`.

## EFD's spinning reserve and turbines (branch efd-turbines)
**What EFD does.** Read from uefd.f and the oracle's 2030 EFD files (aimms-showreel sample efd_2030_01; the PassBack also carries SP_RES_REQ, SP_RES_ACH, SP_RES_DUAL and SP_ACHBYECP, the reserve by ECP type). Scripts: scratchpad `efdturb/` (rsv.py reads the reserve tables, sto.py the storage factors, run.py the single-year runs).
- Slices. EFD dispatches 9 slices a year: 3 seasons (winter Dec-Mar 2,904 hours, summer Jun-Sep, shoulder), each cut at 1% / 49% / 50% of its hours (ETWDTH 29 / 1,423 / 1,452). The slice heights come from the same LDSM hourly load as the dispatch's 36 typical days, so the 1% peak slice adds no peak energy the dispatch lacks: its hours are already in the typical days, at higher hourly peaks. It matters through the reserve requirement.
- Reserve requirement (ED$LOAD, uefd.f 11205-11250): per region and slice, 0.1 x the slice height + 0.3 x (season peak slice - height), plus 0.25 of wind and solar output (SR_INT_REQ). The same formula and constants as ECP's (docs/capacity.md). Nationally in 2030, intermittents included: winter 87 / 111 / 145 GW (peak / middle / base), summer 102 / 141 / 180, shoulder 89 / 119 / 153. The base slice binds in 23-24 of 25 regions in every season, the peak slice almost never. The mean dual in the base slices is 2.0 / 3.0 / 2.2 1987$/MWh (taken to be in NMARCST's units), under 0.2 elsewhere.
- Reserve supply (OPBSLD, uefd.f 9700-9900). Every dispatchable type has three shapes per mode: normal, minimum load (J: SR_MIN_CF x height / the season's lowest height; coal and steam 0.3, combined cycle 0.2, turbines and pumped storage 0.1) and maximum load (U). Each puts 1 - output per committed GW on the reserve row, so the forced-outage share counts as reserve. Batteries get a fixed reserve per GW and slice from ReStore (NET_STORAGE_SR_EFD, capacity-weighted: 0.20-0.25 peak, 0.21-0.29 middle, 0.44-0.46 base). Hydro carries none. Planned maintenance (ED$PM, 8959-9120) is a column per group and season that shares the season's capacity row with the modes, at least PMR x capacity x the year's hours in total.
- Who carries the base-slice reserve in 2030 (GW, winter / summer / shoulder): existing combined cycle 40 / 52 / 47, turbines (AT + ET + CT) 31 / 36 / 31, batteries 31 / 34 / 34, pumped storage 16 / 18 / 17, coal 10 / 20 / 15, nuclear 4. Turbines holding 30-40 GW of reserve at a minimum load near 0.1 make about 30 TWh a year: EFD's turbine energy (CTG 32 TWh) is reserve, not peak energy. CTN (converted steam, 28 TWh at 0.28 of available capacity) sits in UCAPCT and so in the dispatch's turbine group.

**Ported** (`dispatch.py`, all three on):
- `EFD_SPIN_RESERVE`: reserve rows in every region and hour or block, each taking its EFD slice's requirement (`spin_requirement`, slices on net load) plus 0.25 of wind and solar output. Per thermal group, reserve <= capacity in service - output and reserve <= output x (1 / SR_MIN_CF - 1); pumped storage the same on discharge; batteries EFD's fixed factor by slice (`EFD_BATTERY_SR`, the 2030 composite's); nuclear 4% of capacity (the 2030 PassBack's 3.6-4.0 GW on 98.6); other renewables capacity less output. A shortfall costs 100 1987$/MWh, below unserved energy: at 1,000 the LP shed load in Texas in 2025 to make reserve.
- `EFD_DERATE`: EFD's FOR and PMR (`efd_outage_rates`, udat.f's rule: coal 0.19 and 0.20, combined cycle 0.074 and 0.060). Output in every hour is at most (1 - FOR) x (capacity - maintenance), reserve + output at most capacity - maintenance. Maintenance follows a rule (`maintenance_season_share`): PMR x 8760 hours spread over the two seasons other than the region's peak one. Letting the LP pick the seasons, as ED$PM does, chose nearly the same (2031 coal: 0.24 of capacity out in winter, 0.35 in the shoulder, none in summer, against 0.29 / 0.29 / 0 by the rule) and took 60 s a solve instead of 6.
- `OIL_UNITS_LAST`: the turbine and steam groups' output is gas. EFD runs oil turbines and oil steam as their own groups and they barely run (CTO 0.001 TWh on 14.7 GW in 2030). With one group, the oil units' capacity share made every turbine MWh 8% distillate, up to half again the cost, and reserve-carrying steam burned residual oil (2030: 32 trillion Btu against EIA's 21). The must-run oil units still burn theirs. Only `solve` changes; `DispatchCase.oil_share` and the capacity LP do not.

**Result.** Single-year dispatch on EIA's fleet, sales-based load with trade, 3-hour blocks as in the full model. TWh, off / on / EIA:

| | 2030 | 2031 | 2035 | 2040 |
|---|---|---|---|---|
| Coal (EIA by fuel) | 478 / 466 / 465 | 445 / 436 / 419 | 93 / 92 / 122 | 93 / 93 / 63 |
| Coal fuel, trillion Btu | 5,150 / 5,029 / 4,962 | 4,920 / 4,825 / 4,531 | 1,388 / 1,387 / 1,491 | 1,399 / 1,394 / 861 |
| Combined cycle | 1,547 / 1,509 / 1,449 | 1,525 / 1,490 / 1,446 | 1,566 / 1,531 / 1,414 | 1,485 / 1,462 / 1,437 |
| Gas CCS | 13 / 13 / 12 | 24 / 24 / 23 | 150 / 150 / 144 | 396 / 393 / 365 |
| Turbines (ct + at) | 0.5 / 18 / 67 | 0.4 / 19 / 65 | 7 / 38 / 81 | 7 / 38 / 90 |
| Steam (ng + os) | 23 / 60 / 136 | 19 / 49 / 140 | 24 / 36 / 117 | 4 / 8 / 6 |
| Gas, all | 1,582 / 1,596 / 1,469 | 1,567 / 1,578 / 1,477 | 1,745 / 1,752 / 1,577 | 1,892 / 1,900 / 1,779 |
| Gas against EIA | +7.7% / +8.6% | +6.1% / +6.8% | +10.7% / +11.1% | +6.4% / +6.8% |
| Seconds a year | 3.1 / 6.2 | 2.9 / 5.8 | 2.8 / 5.6 | 2.8 / 5.7 |

Every plant type moves toward EIA in 2030 and 2031, and 2030 coal lands on it. Total gas moves 0.4 to 0.9 points away and stays inside 10% in 2030, 2031 and 2040 (2035 was outside already). With 24-hour days (dispatch_report and the tests) a year takes 22-23 s instead of 8.5; 2030 gas is +9.1% there, and 2025 coal fuel goes from +11% to +8%, so its known miss is gone. Each switch alone, 2031: the reserve and oil-last without the derate give turbines 20 TWh and leave coal at 449; the derate and oil-last without the reserve give coal 438 and turbines 3. The turbine energy comes from the reserve, the coal correction from the derate.

Marginal cost in 2030, load-weighted by slice (winter / summer / shoulder, each peak / middle / base): off 18.5 / 16.6 / 16.2, 27.0 / 19.3 / 16.7, 18.1 / 16.5 / 16.3; on 22.0 / 17.9 / 16.4, 24.7 / 20.3 / 17.2, 21.1 / 17.1 / 16.0; EFD's NMARCST 27.9 / 19.9 / 16.7, 36.9 / 23.7 / 19.2, 28.5 / 20.1 / 16.5. Winter and shoulder peaks and middles move toward EFD. The summer peak falls, since no maintenance is taken in summer.

**Still open.**
- Turbines reach 18-19 TWh in 2030-2031 against EIA's 65-67. The requirement lines up with EFD's (2031 here: winter 93 / 112 / 141 GW, summer 102 / 141 / 175, shoulder 83 / 121 / 148); the price does not. Reserve costs 0.6 to 1.3 1987$/MWh here in every slice, EFD's 2 to 3 in the base slices and nothing in the peak. In the base slices (winter / summer / shoulder) combined cycle carries 63 / 79 / 75 GW here against EFD's 40 / 52 / 47 and turbines 14 / 21 / 9 against 31 / 36 / 31: a combined cycle unit following load hour by hour has idle headroom in low-load hours for free, where EFD's mode shapes tie its output across a season's slices. Porting the modes was tried in the capacity LP (docs/capacity.md, ECP's dispatch modes) and did not raise the price there either.
- Cofired units. EIA's ng units (50 GW, in the steam group here) burn 66 TWh worth of coal in 2031, with at least 40% gas from 2030 (udat.f 6457-6460). A coal share for the steam group would run it more and take gas off the total, but it adds coal where the dispatch already runs its coal units 80 TWh above EIA's (436 against 353 from pc + ig). Not done.
- Coal heat-rate spread. A second coal group by heat rate needs a seventh thermal group through dispatch, capacity and their reports. Not done; with the derate, coal is at EIA in 2030 and 17 TWh over in 2031.

Pinned by `tests/test_emm_dispatch.py` (`test_efd_outage_rates_follow_udat_rule`, `test_spin_requirement_is_efd_slice_formula`, `test_maintenance_skips_the_peak_season`, `test_turbines_carry_spinning_reserve`). The 2025 coal fuel known miss is removed.
