# Dispatch LP (steps 2 and 2b)

`nems_open.emm.dispatch`: a linopy + HiGHS model shaped like EFD. One year, 25 EMM regions, 36 typical days of 24 hours. Without trade a year solves in 5 to 8 seconds; with the regional links it takes about 35 seconds. Results against the AEO2026 reference are in `docs/dispatch_results.md` (regenerate: `python -m nems_open.emm.dispatch_report docs/dispatch_results.md`, about 4 minutes).

## What it does
- Six thermal groups dispatch on fuel plus variable O&M: coal, coal with CCS, gas combined cycle, gas combined cycle with CCS, gas turbines, steam. Captured CO2 earns the 45Q credit (`TCS45Q/ccs_saline_45q`).
- Nuclear runs at its monthly capacity factor. Hydro dispatches inside a monthly energy budget. Wind and solar use EIA's hourly profiles (`WRENEW/ws*_cf`) cut by each type's outage rate. Batteries and pumped storage cycle inside each day.
- Regions trade over the links in the ETT table (`V_EMM_PRETTIN`: 127 rows, summer and winter MW, a $/MWh markup, 2% line loss, plus the new transmission EMM built, `UETTOUT/UTNEWTRN`).
- Capacity is what is in service on average through the year. The plant file's in-service and retirement months are used for dated units; capacity the restart shows beyond that is assumed to arrive mid-year.
- Load is the step 1 shapes scaled to the demand modules' sales as LDSM builds EFD's load, less what EFD gets from outside the fleet (`demand.py`; section "The electricity balance" below).
- EFD's spinning reserve rows, availability and planned maintenance, and oil units running last (`EFD_SPIN_RESERVE`, `EFD_DERATE`, `OIL_UNITS_LAST`, all on; section "EFD's spinning reserve and turbines" below). Turbines dispatch in heat-rate tiers (`HEAT_RATE_TIERS`, on); EFD's dispatch modes are ported but off (`EFD_DISPATCH_MODES`); section "Turbines, the reserve price and EFD's modes". Coal's ceiling follows EFD's maximum-load mode from 2028 (`EFD_MAX_LOAD_SHAPE`, on; section "Coal's ceiling is EFD's maximum-load mode"). Coal heat rates follow EFD's part-load curves, and the cofired units take the maximum-load mode too (`COAL_PART_LOAD_HEAT_RATE`, `COFIRE_MAX_LOAD_SHAPE`, on; section "Coal heat rates and the cofired units' ceiling"). The results table above them predates these switches.
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

## What EIA's steam is, and CCS coal's capacity (branch gen-2035)
**EIA's steam is cofired coal.** From 2028 most of EIA's steam (restart ng + os) is the coal-gas cofiring units, prefix ng: ECP type NG, EFD type CTN ("Coal to Gas Retrofit"). In 2035 ng makes 106 TWh on 48 GW (0.25) and oil/gas steam (os) 11.5 on 51. They burn coal: the plant file's 14.3 GW of CTN units list gas first and a coal curve (B1..CX) second at 52% of Btu; ECP's conversions get W_FSHR(2) = UEPA_CGSH = 0.6 coal (uecp.f 28148); udat.f 6457 caps every NG unit at that share from 2030; the oracle's 2030 EFD passes back CTN coal shares of 0.17-0.60 by fuel region (FCLSH_ams). In the restart the coal share of ng generation (UGNCLNR less UGENPC and UGENIG) is 52% in 2031 and 56-57% in 2032-2038. EIA's 2035 coal (122 TWh) is 62 from CCS retrofits and 59 from these units. The dispatch had them in steam on gas at steam's cost (23-25 1987$/MWh), so they ran at 0.07 and the CC fleet took their energy.

**CCS retrofits are reported before their capacity loss.** udat.f 9265 gives a retrofitted coal unit a capacity loss of 1 - WHRATE / CCSHR, uecp.f 27662 takes it off the unit (CCSCAPA), and the UCAP tally reports the unit at WC_SUM / (1 - CCSADJ) (udat.f 8421-8467: ECSCAPSQ, ECSCAP). So sq (and cs) hold retrofits at their old nameplate, and EFD dispatches about 0.71 of it (the plant file's THRATE / T_CCSHR, 0.69-0.74 by region). EFD's 0.62-0.65 of that is the 0.44 of sq that EIA's CCS coal shows in every year from 2033. 45Q, its eligibility and the CF cap were never the cause.

**Ported** (`dispatch.py`, both on):
- `COFIRE_GROUP`: ng is a seventh thermal group, `cofire` (`DispatchCase.coal_share`, `cofire_case`): the CTN units' heat rate (10,780), variable O&M and coal share, and coal converted after the plant file at the coal fleet's heat rate +5% and variable O&M x0.75 (capacity.CONVERT_*) with UEPA_CGSH of coal; no coal after UEPA_CLCFYR (2038). Its coal counts as coal generation and fuel, as UGNCLNR does. In 2035 it costs 17.4 1987$/MWh, the same as combined cycle. The capacity LP starts the reference run's cofiring units (cofiring_existing) in gas_conv, which already cofired at 0.6 and retires after 2038, and `dispatch_capacity` hands gas_conv to `cofire`. Steam's existing types and retirement groups drop CTN (`dispatch.existing_types`).
- `CCS_CAPACITY_PENALTY`: coal_ccs generates on capacity x `DispatchCase.capture_net` (`generating_capacity`). Dispatch only; the capacity LP still values a retrofit at its full nameplate (to do: ECP's CPEN on the retrofit column).

**Result.** Single-year dispatch on EIA's fleet, sales-based load with trade, 3-hour blocks. TWh, before (both off) / after (both on) / EIA. Steam is os + ng (steam + cofire here); coal is by fuel.

| | 2030 | 2031 | 2035 | 2040 |
|---|---|---|---|---|
| Coal | 466 / 526 / 465 | 436 / 500 / 419 | 92 / 141 / 122 | 93 / 66 / 63 |
| of which coal units | 450 / 440 / 385 | 394 / 382 / 319 | 0.5 / 0.5 / 0 | 0.3 / 0.3 / 0 |
| of which CCS coal | 16 / 11 / 18 | 42 / 30 / 34 | 92 / 65 / 62 | 93 / 66 / 63 |
| Cofired units (all fuel) | 0 / 131 / 122 | 0 / 152 / 129 | 0 / 130 / 106 | 0 / 0 / 0.1 |
| Steam (os + ng) | 60 / 145 / 136 | 49 / 164 / 140 | 36 / 141 / 117 | 8 / 7 / 6 |
| Combined cycle | 1,509 / 1,440 / 1,449 | 1,490 / 1,403 / 1,446 | 1,531 / 1,460 / 1,414 | 1,462 / 1,487 / 1,437 |
| Turbines | 18 / 15 / 67 | 19 / 14 / 65 | 38 / 29 / 81 | 38 / 40 / 90 |
| Gas, all | 1,596 / 1,538 / 1,469 | 1,578 / 1,516 / 1,477 | 1,752 / 1,704 / 1,577 | 1,900 / 1,926 / 1,779 |
| Gas against EIA | +8.6% / +4.7% | +6.8% / +2.6% | +11.1% / +8.0% | +6.8% / +8.3% |
| Coal fuel, trillion Btu | 5,029 / 5,671 / 4,962 | 4,825 / 5,486 / 4,531 | 1,387 / 1,811 / 1,491 | 1,394 / 988 / 861 |
| Seconds a year | 7.3 / 7.7 | 7.1 / 7.5 | 6.8 / 7.5 | 6.7 / 7.4 |

Each alone: the capacity penalty alone takes 2035 coal to 66 (EIA 122) and 2035 gas to +12.7%, because the coal EIA's cofired units burn is missing; cofiring alone takes 2035 coal to 165 (CCS still at 92). Together steam, CCS coal and 2035 gas land near EIA, and 2040 coal (was +47%) is +4%.

**What it uncovers.** The coal units. Without the cofired units' coal, the LP's coal units running at their 0.61 ceiling (EIA about 0.50) landed total coal on EIA's in 2030 by accident. Now coal is 13% over in 2030 and 19% over in 2031, all of it the coal units (440 vs 385, 382 vs 319), and cofired units run 7-20% above EIA's. Test years: gen_coal 2040 is fixed; gen_coal 2030, fuel_coal 2030 and fuel_coal 2025 are new known misses (`tests/test_emm_dispatch.py`). 2040 coal fuel stays 15% high: generation is on EIA's, but at the full-capture heat rate (15.2 MMBtu/MWh) where EIA's averages 13.7, partly in EFD's partial-capture mode (uefd.f OPBSLD, SHR_NOCCS / ADJ_FAC). Turbines are unchanged in kind (29-40 TWh vs EIA 65-90).

Planner chain 2027-2040 from EIA's 2026 fleet (the capacity LP sees the cofiring move), 2040 GW before / after / EIA: CC 436 / 430 / 431, CT 234 / 242 / 267, batteries 108 / 107 / 103, solar 348 / 344 / 323, wind 383 / 378 / 404, coal 15 / 15 / 16, steam (with gas_conv) 56 / 56 / 52. Conversions 2028-2029 unchanged (30.7 + 2.8 GW). 367 s for the chain (382 before).

Pinned by `tests/test_emm_dispatch.py` (`test_eia_steam_is_cofired_coal_units`, `test_cofire_group_takes_ng_out_of_steam`, `test_restart_counts_ccs_retrofits_before_their_capacity_loss`) and `tests/test_emm_epa111.py`. Scripts: scratchpad `gen2035/` (run.py, efdgrp.py reads the EFD composite by ECP type through the EFD_GRPS_F / _N group chains, caps.py).

## Coal's ceiling is EFD's maximum-load mode (branch coal-units-cf)
**What sets EFD's 0.51.** Each EFD coal group has three dispatch modes per season (uefd.f OPBSLD): normal (O, shaped by ReStore's FOS_CF_EFD since coal is a fossil baseload type, UPPCFB 0.15), minimum load (J, SR_MIN_CF 0.3 x height / the season's lowest) and maximum load (U). U is the highest, and it follows load: DRAT_MAX = (1 - FOR) x (SR_MAX_LF + (1 - SR_MAX_LF) x height / the season's peak slice), SR_MAX_LF 0.55 for every existing coal configuration (ecpdaty SPNRSV B1..HC; PC and IG 0.9). On the oracle's 2030 EFD files (scratchpad `coalcf/modes.py`), (1 - FOR)(1 - PMR) x the U shape reproduces the coal groups that run at their ceiling to three decimals in every region: MISC 0.580 against 0.583, PJMW 0.578 / 0.581, SRCE 0.570 / 0.572, TRE 0.579 / 0.578, MISS 0.579 / 0.580. EFD's 335 TWh on 74 GW splits into:

| | TWh |
|---|---|
| Every group at the flat (1 - FOR)(1 - PMR) = 0.648, as the dispatch had it | 420 |
| Every group at the U shape (0.57-0.60 of nameplate) | 388 |
| EFD's coal | 335 |

So 32 TWh of the gap is the ceiling and 53 TWh is 22 GW of groups below it, in TRE (7 GW), BASN (3.8), MISC (3.2, one group), SRSG (2.8), RMRG (1.7), SPPS (1.5), PJMW (1.5) and SPPN. Many of those sit at the J mode's 0.24-0.26 all year (committed at minimum load for reserve) or below it.

**The below-ceiling groups are not a heat-rate merit order.** Within one EMM region and one coal demand region, low-cost groups idle while costlier ones run flat out (fuel at UPFUEL, which EFD passes back unchanged and equal for every configuration in a coal region): RMRG C4 at 8.8 1987$/MWh runs 0.08 while B7 at 10.1 runs 0.60; BASN B3 at 9.5 runs 0.09 while B7 at 11.4 runs 0.60; SPPS CX and C1 (9.7) run 0.24 while B1 (9.9) runs 0.59, all on WS coal. The split follows the ECP coal configuration (TRE, BASN, RMRG, SPPS: C4, CX, B3 low; B7, B1 at the ceiling). That is the axis of EFD's coal LP (ED$COL: CL rows per coal region and configuration, fed by supply-curve, transport-tier, ACI and diversity columns), whose duals are the configuration's true coal cost. They are not in the saved files. A split of the regional coal group by heat rate would produce a merit order EFD does not show, and the part-load curves only change the cost of each mode, so neither is ported.

**Ported** (`dispatch.py`, on): `EFD_MAX_LOAD_SHAPE`. Coal's hourly upper bound, (1 - FOR) x (capacity - maintenance), takes the U shape on the EFD slices of the spinning reserve (`max_load_shape`, `MAX_LOAD_GROUPS`), from 2028: up to UYR_STEO + 1 (2027) OPBSLD sets DRAT_MAX to the plain derate for coal. Dispatch only; the capacity LP has its own coal rows and is unchanged, so the planner chain does not move.

**Result.** Single-year dispatch on EIA's fleet, sales-based load with trade, 3-hour blocks. TWh, before / after / EIA. Coal is by fuel; coal units are pc + ig - sq.

| | 2025 | 2030 | 2031 | 2035 | 2040 |
|---|---|---|---|---|---|
| Coal | 781 / 781 / 728 | 526 / 490 / 465 | 500 / 468 / 419 | 141 / 141 / 122 | 66 / 66 / 63 |
| Coal against EIA | +7.3% / +7.3% | +13.1% / +5.3% | +19.4% / +11.7% | +16% / +16% | +4% / +4% |
| of which coal units | 761 / 761 / 723 | 440 / 400 / 385 | 382 / 346 / 319 | 0.5 / 0.4 / 0.2 | 0.3 / 0.3 / 0.3 |
| Cofired units (all fuel) | 27 / 27 / 25 | 131 / 138 / 122 | 152 / 159 / 129 | 130 / 130 / 106 | 0 / 0 / 0.1 |
| Combined cycle | 1,531 / 1,531 / 1,544 | 1,440 / 1,472 / 1,449 | 1,403 / 1,431 / 1,446 | 1,460 / 1,460 / 1,414 | 1,487 / 1,487 / 1,437 |
| Turbines | 16 / 16 / 80 | 15 / 16 / 67 | 14 / 13 / 65 | 29 / 29 / 81 | 40 / 40 / 90 |
| Steam (os + ng) | 90 / 90 / 92 | 145 / 154 / 136 | 164 / 172 / 140 | 141 / 141 / 117 | 7 / 7 / 6 |
| Gas, all | 1,614 / 1,614 / 1,570 | 1,538 / 1,574 / 1,469 | 1,516 / 1,548 / 1,477 | 1,704 / 1,704 / 1,577 | 1,926 / 1,926 / 1,779 |
| Gas against EIA | +2.8% / +2.8% | +4.7% / +7.2% | +2.6% / +4.8% | +8.0% / +8.0% | +8.3% / +8.3% |
| Coal fuel, trillion Btu | 8,292 / 8,292 / 7,513 | 5,671 / 5,282 / 4,962 | 5,486 / 5,145 / 4,531 | 1,811 / 1,811 / 1,491 | 988 / 988 / 861 |
| Seconds a year | 6.9 / 7.2 | 7.1 / 7.1 | 6.9 / 7.4 | 6.7 / 7.2 | 6.6 / 6.9 |

2030 coal units by region against EIA (TWh on the dispatch's in-service capacity; scratchpad `coalcf/reg.py`): where coal runs at its ceiling the dispatch now lands on EIA's (MISW 28.7 / 29.3, MISC 45.9 / 48.4, MISS 14.7 / 14.7, SRCA 25.7 / 24.4, SRCE 15.4 / 16.3, SPPN 15.1 / 14.9, RMRG 7.4 / 7.6). What is left is the below-ceiling regions, high: TRE 52.3 / 44.7, BASN 30.1 / 14.8, SPPS 17.0 / 10.1, SPPC 19.4 / 13.3, SRSE 9.1 / 4.0; and PJM low: PJME 7.9 / 21.7, PJMW 71.0 / 78.8, PJMD 4.4 / 7.8. The PJM coal runs on a heat rate of 10,960 Btu/kWh in PJME where EFD's 2030 groups dispatch at 9,600 (UG_HTRT; 9,980 burned), so it sits above the region's marginal cost.

The 2030 coal generation and fuel misses are gone (`tests/test_emm_dispatch.py`, 24-hour days); 2025 coal fuel stays a known miss (the shape starts in 2028). Coal's energy goes to combined cycle and the cofired units, so 2030 gas moves from +4.7% to +7.2%, still inside 10%.

**Still open.** The configuration-level coal cost (EFD's coal LP) that idles 22 GW in TRE, SPP and the West; PJM's dispatch heat rate; cofired units 13-23% above EIA's in 2030-2035 (NG's SR_MAX_LF is 0.5, but they run at 0.25-0.3 and do not reach the ceiling).

Pinned by `tests/test_emm_dispatch.py` (`test_max_load_shape_is_efd_drat_max`, `test_coal_units_stay_under_efd_ceiling`).

## Coal heat rates and the cofired units' ceiling (branch disp-hr-cofire)
**The PJM heat rate.** The 9,600 Btu/kWh quoted above for PJME is the oracle sample's EFD, a different run (its 2030 coal is 74.6 GW against the restart's 88, its cofired units 21.5 GW against 50). EIA's own 2030 burn in PJME (restart UFLCLNR / UGNCLNR) is 10,719, close to our 10,963. What is wrong is how both relate to the plant file.
- udat.f CRPGRP (7210-7262) stores a coal unit's heat rate as WHRATE x Target_EFF(W_CFA) / Max_EFF: THRATE, measured at the unit's historical capacity factor (T_CF), moved to full load on emmcntl's efficiency curve for its coal region and configuration (HTRT_ADJUSTMENT in uefd.f; the curves follow %HAWAII RPS% in emmcntl.txt, read by udat.f 3845-3900, a configuration without a curve taking the one listed before it). For 2030 W_CFA is T_CF (COAL_FACTOR 1, no year multiplier). This reproduces the oracle composite's UG_HTRT: Northampton (B3, coal region 2, T_CF 0.40) 11,868 x 0.847 = 10,052; the PJME C7 group (Conemaugh and Keystone, THRATE 10,116-10,427) 9,230.
- Each dispatch mode then burns at UG_HTRT x Max_EFF / Target_EFF(its output per committed GW) (OPBSLD 9970-9985, ECDSPF 13861). Fuel / UG_HTRT in the oracle's 2030 PassBack gives the load each coal group ran at: generation-weighted 0.74, most groups 0.70-0.75, the maximum-load mode's (1 - FOR) x its mean shape.
- So a unit burns THRATE x Target(T_CF) / Target(L). Coal units with a low historical capacity factor (T_CF 0.40 is common) burn less than THRATE when they run at 0.74. Gas types have no curves.

Scored against EIA's 2030 burn in the eight regions where coal units make nearly all the coal power (MISE, PJME, PJMW, PJMC, PJMD, SPPS, SRSG, BASN), generation-weighted error and mean absolute error:

| Coal group heat rate | Error | Mean abs |
|---|---|---|
| THRATE, capacity-weighted (before) | +3.6% | 3.7% |
| THRATE x curve factor at L = 0.6 / 0.7 / 0.74 / 0.8 | +0.3% / -1.3% / -1.7% / -2.2% | 1.5% / 1.8% / 2.1% / 2.6% |
| THRATE, the units EIA retired dropped worst-first | +2.3% | 3.0% |
| Both, at L = 0.7 | -2.8% | 2.6% |

**Ported** (`dispatch.py`, on): `COAL_PART_LOAD_HEAT_RATE`. The coal and coal_ccs heat rates are THRATE (T_CCSHR) x `part_load_factor` at `PART_LOAD_LEVEL` 0.74 (EFD's own level, not the best fit), capacity-weighted as before; conversions to cofiring start from the plain coal heat rate. The capacity LP takes its heat rates from `build_case`, so it moves too. Retirement selection is not kept.

**Cofired units.** Capacity is EIA's in every region (50.2 GW in 2031). The coal share is EIA's implied one (UGNCLNR less pc and ig, over ng: 0.59-0.60 in MISW, SRSE, SRCE, SPPC) except RMRG (ours 0.60, EIA 0.11) and MISC (0.60 against 0.42). Heat rates are the CTN units' THRATE, 10,340-11,550 (NG has no curve). At 15-16.5 1987$/MWh against combined cycle's 16.5-19 they ran at their flat ceiling, 0.57-0.65, in MISW, MISC, SRCE and TRE. EFD does not let them: OPBSLD gives every type with SR_CREDIT its maximum-load mode, and the STEO exemption (DRAT_MAX = DRAT_ORG up to UYR_STEO + 1) covers only types up to WIIS, so NG (SR_MAX_LF 0.5) has the shape in every year. **Ported** (on): `COFIRE_MAX_LOAD_SHAPE`, cofire's hourly bound takes the U shape with NG's 0.5 from 2025. `max_load_shape` applies the 2027 exemption by ECP type (`MAX_LOAD_STEO_LAST`).

**Result.** Single-year dispatch on EIA's fleet, sales-based load with trade, 3-hour blocks. TWh, before / after (both on) / EIA. Coal is by fuel; coal units are pc + ig - sq.

| | 2025 | 2030 | 2031 | 2035 | 2040 |
|---|---|---|---|---|---|
| Coal | 781 / 819 / 728 | 490 / 507 / 465 | 468 / 477 / 419 | 141 / 136 / 122 | 65.8 / 65.9 / 63.2 |
| of which coal units | 761 / 800 / 723 | 400 / 425 / 385 | 346 / 362 / 319 | 0.4 / 0.4 / 0.2 | 0.3 / 0.3 / 0.3 |
| Cofired units (all fuel) | 27 / 23 / 25 | 138 / 125 / 122 | 159 / 147 / 129 | 130 / 122 / 106 | 0 / 0 / 0.1 |
| Steam (os + ng) | 90 / 85 / 92 | 154 / 142 / 136 | 172 / 160 / 140 | 141 / 133 / 117 | 7.4 / 7.4 / 5.5 |
| Combined cycle | 1,531 / 1,496 / 1,544 | 1,472 / 1,459 / 1,449 | 1,431 / 1,427 / 1,446 | 1,460 / 1,468 / 1,414 | 1,487 / 1,487 / 1,437 |
| Turbines | 15.9 / 15.7 / 80 | 15.7 / 16.0 / 67 | 13.4 / 13.7 / 65 | 29.1 / 29.4 / 81 | 40.1 / 40.1 / 90 |
| Gas, all | 1,614 / 1,576 / 1,570 | 1,574 / 1,557 / 1,469 | 1,548 / 1,539 / 1,477 | 1,704 / 1,709 / 1,577 | 1,926 / 1,926 / 1,779 |
| Gas against EIA | +2.8% / +0.4% | +7.2% / +6.0% | +4.8% / +4.2% | +8.0% / +8.4% | +8.3% / +8.3% |
| Coal fuel, trillion Btu | 8,292 / 8,336 / 7,513 | 5,282 / 5,260 / 4,962 | 5,144 / 5,028 / 4,531 | 1,811 / 1,702 / 1,491 | 988 / 933 / 861 |
| Seconds a year | 10.7 / 9.2 | 9.5 / 8.9 | 9.4 / 9.2 | 9.9 / 9.2 | 9.3 / 8.6 |

Seconds are higher than in the last section on both sides; another run shared the machine.

2030 coal units by region, heat rate alone, before / after / EIA: PJME 7.9 / 20.8 / 21.7, PJMW 71.0 / 76.7 / 78.8, PJMD 4.4 / 7.7 / 7.8, ISNE 0 / 2.7 / 0; nothing else moves more than 0.3 TWh. In 2025: PJMW 93 / 103 / 104, SRSE 37 / 44 / 48, FRCC 2.8 / 15.0 / 12.1, SRCA 36 / 45 / 38. Every region that moves lands on or near EIA's except ISNE and SRCA. National coal goes up because the regions that were over stay over (2030 TRE 52 vs 45, BASN 30 vs 15, SPPS 17 vs 10, SPPC 19 vs 13, SRSE 9 vs 4): the PJM shortfall had been hiding them. Coal fuel moves toward EIA in 2031-2040 (2040: +15% to +8%, the known miss is gone). Cofired units go from 13-23% over to 2-15%. What is left is TRE (W A Parish, 8.2 vs 0.1 TWh in 2031), SPPS (6.9 vs 1.3), RMRG (9.8 vs 2.4, the coal share above) and MISW (28.9 vs 24.7), the regions where coal units also run over EIA, against SRSE and MISS under.

Test years (24-hour days, `tests/test_emm_dispatch.py`): fuel_coal 2040 is fixed; gen_coal 2025 is a new known miss (+12%); gen_coal 2030 stays inside 10%.

**Gas.** These changes do not fix it: total gas moves -2.4 to +0.4 points. Giving combined cycle the maximum-load mode too (existing CC is EC, SR_MAX_LF 0.7) moved 10-40 TWh from CC to coal, cofired units and turbines and left total gas within 0.6 points; not kept. A lead: EIA's total generation (UGNTLNR) is 164 TWh above the sum of its fuel categories in 2030 and 241 in 2040. The dispatch serves 115 TWh (2030) and 125 TWh (2040) more than EIA's categorized generation, about the size of the fossil overrun (coal plus gas +130 and +150).

The capacity LP takes the new coal heat rates (the cofire shape is dispatch only). Planner chain 2027-2040 from EIA's 2026 fleet, 2040 GW before / after / EIA: CC 430 / 435 / 431, CT 242 / 238 / 267, batteries 107 / 108 / 103, solar 344 / 347 / 323, wind 378 / 370 / 404, coal 15 / 14 / 16, steam (with gas_conv) 56 / 56 / 52. Conversions 2028-2029 30.7 + 2.8 / 32.1 + 1.5 GW; the 2032 coal retirements 66.5 / 67.0. 551 s for the chain against 367, with another run on the machine.

**Still open.** The coal LP's configuration costs that hold TRE, SPP and the West below their ceiling (now visible in national coal: +9% in 2030, +12% in 2025); what UGNTLNR holds beyond the fuel categories; turbines.

Pinned by `tests/test_emm_dispatch.py` (`test_part_load_factor_reproduces_efd_group_heat_rates`, `test_coal_heat_rate_follows_eia_burn`, `test_pjm_coal_runs_at_eia_level`, `test_cofire_takes_the_ng_max_load_shape`). Scripts: scratchpad `hrcof/` (hrcmp.py EFD group heat rates by region, hyp.py the rules against EIA's burn, implL.py the load EFD's modes ran at, reg2.py and cof.py regional coal and cofired units, run.py and tab2.py the test years).

## The electricity balance (branch disp-load-balance)
**The question.** Gas ran 4-8% over EIA in every year and coal over too, and EIA's total generation (UGNTLNR) is 164 TWh above the sum of its fuel categories in 2030 and 241 in 2040. Term by term, against EIA's table 8 (the reporter's T8 rows) and EFD's own load (scratchpad `lbal/`: bal.py, bal2.py, bal3.py, gapsearch.py):

- **UGNTLNR's extra is distributed solar.** util.f 3779 makes UGNTLNR the sum of its parts, but the restart's value is 148 TWh (2030) and 220 (2040) above that sum in ownership class 1, spread over every region; a search of every restart array by region finds only the end-use solar output (COGEN/cgtotgennr's solar column, 169 and 272 TWh; correlation 0.996). It is behind the meter and not load the fleet serves. The fleet's total is the sum of the categories with storage (UGNPSNR + UGNSDNR, -16 and -20 TWh): 4,274 TWh in 2030, 5,054 in 2040.
- **EIA's generation by fuel leaves out the electric power sector's CHP.** UGNCLNR, UGNGFNR and the rest sum ownership classes 1 to 3 (util.f 3626-3720); class 4 is nontraditional cogeneration (COGEN/CGNTCAP, UCAP*C: 25 GW, 20 of it combined cycle), reported apart (CGNTGEN, T8 rows 42-48: 136 TWh in 2030, 122 of it to the grid, 114 of that gas). The dispatch's fleet is UCAP*U and *N, so it holds none of it, but its load did not take it off. The fuel arrays (UFL*, and QNGEL, QCLEL) do count class 4 (util.f 4045). So do the plant-type arrays (UGEN<type>): about 100 TWh of EIA's 2030 combined cycle (ugencc + ugenac) is CHP, which the CC rows of the tables in this file include.
- **LDSM's losses are smaller.** EMM grosses sales up by 1 + ULOSSADJ x UQTDLS (uldsm.f 2011; ULOSSADJ 0.8 from 2020, prepett.f 853-886). The dispatch used sales / (1 - UQTDLS): 335 TWh of losses in 2030 against 247.
- **End-use generators' own use was taken off twice.** The demand modules report purchases, so own use is already out of sales. EFD's load gets only their grid sales (BTCOGEN, unugs.f 436-458; residential and commercial own use is in both LDSM's load and BTCOGEN). The dispatch took off grid sales and own use (117 TWh in 2030).
- **Alaska and Hawaii were in the 25 regions.** The old split moved 2024 regional sales with census growth over the 25 regions only, so the Pacific division's growth carried Alaska's and Hawaii's 15-20 TWh. LDSM's DSMEMMV gives each region MappCtoN's share of each division (uldsm.f 1730-1758, 4425-4437); that is within 0.1% of EIA's regional sales (QELASN) in every region in 2025, where the old split was up to 8% off.
- Imports (UTIMP - UTEXP) and storage were already right. EFD's supply and load balance without the end-use solar column, which stays out.

**Ported** (`demand.py`): `regional_sales_twh` uses LDSM's mapping; `net_load_twh` is sales x (1 + `loss_adjustment` x UQTDLS) less `end_user_grid_sales_twh`, `nontraditional_cogen_twh` and imports. `dispatch_report.reference` takes the CHP units' fuel (CGNTQ) out of QCLEL and QNGEL, so the fuel check is on the fleet's fuel. In the coupled loop (`couple.py`) the CHP units' fuel and CO2 at the reference run's level are added back to the fleet's, so QNGEL and QCLEL keep their meaning.

**Balance, 25 regions, TWh.** Old load / new load / EIA. EIA's load column uses its own regional sales (QELASN), which trail the census sales by 21 TWh in 2030 and 46 in 2040; EFD's supply matches the census sales, not QELASN, so the gap looks like an iteration lag in QELASN.

| | 2030 | 2040 |
|---|---|---|
| Sales | 4,291 / 4,275 / 4,255 | 5,034 / 5,014 / 4,968 |
| T&D losses | 335 / 247 / 245 | 395 / 291 / 288 |
| less end-use own use | -117 / 0 / 0 | -121 / 0 / 0 |
| less end-use grid sales | -42 / -42 / -42 | -46 / -46 / -46 |
| less electric power CHP (CGNTGEN to the grid) | 0 / -122 / -122 | 0 / -113 / -113 |
| less net imports | -83 / -83 / -83 | -89 / -89 / -89 |
| Load on the fleet | 4,384 / 4,275 / 4,253 | 5,174 / 5,058 / 5,009 |
| Fleet generation, storage net included (new load; EIA by category) | 4,279 / 4,274 | 5,063 / 5,055 |
| of which storage net | -11 / -16 | -11 / -21 |
| UGNTLNR (adds distributed solar) | 4,438 | 5,295 |

The new load is within 0.2% of the fleet generation EIA reports in 2025-2040 (`tests/test_emm_demand.py`); the old one was 110-125 TWh over.

**Result.** Single-year dispatch on EIA's fleet, sales-based load with trade, 3-hour blocks. TWh, before / after / EIA. Coal is by fuel; CC, CT and steam are EIA's plant types, which include the CHP units (about 100 TWh of CC).

| | 2025 | 2030 | 2031 | 2035 | 2040 |
|---|---|---|---|---|---|
| Coal | 819 / 803 / 728 | 507 / 501 / 465 | 477 / 472 / 419 | 136 / 133 / 122 | 65.9 / 65.8 / 63.2 |
| Combined cycle | 1,496 / 1,425 / 1,544 | 1,459 / 1,368 / 1,449 | 1,427 / 1,337 / 1,446 | 1,468 / 1,383 / 1,414 | 1,487 / 1,391 / 1,437 |
| Gas CCS | 0 / 0 / 0 | 13 / 13 / 12 | 24 / 24 / 23 | 150 / 150 / 144 | 393 / 393 / 365 |
| Turbines | 15.7 / 8.0 / 80 | 16.0 / 11.3 / 67 | 13.7 / 8.9 / 65 | 29.4 / 21.4 / 81 | 40.1 / 30.7 / 90 |
| Steam (os + ng) | 85 / 60 / 92 | 142 / 132 / 136 | 160 / 150 / 140 | 133 / 123 / 117 | 7.4 / 3.8 / 5.5 |
| Gas, all | 1,576 / 1,474 / 1,570 | 1,557 / 1,455 / 1,469 | 1,539 / 1,438 / 1,477 | 1,709 / 1,610 / 1,577 | 1,926 / 1,818 / 1,779 |
| Gas against EIA | +0.4% / -6.1% | +6.0% / -1.0% | +4.2% / -2.7% | +8.4% / +2.1% | +8.3% / +2.2% |
| Coal fuel, trillion Btu | 8,336 / 8,168 / 7,513 | 5,260 / 5,192 / 4,962 | 5,028 / 4,974 / 4,531 | 1,702 / 1,669 / 1,491 | 933 / 932 / 861 |
| Seconds a year | 8.3 / 7.9 | 7.8 / 7.3 | 7.9 / 7.4 | 7.6 / 7.2 | 7.4 / 7.0 |

The load cut comes off gas: it was the marginal fuel. Coal moves 1-2% (coal units run at their ceiling), so coal's overrun (+8% in 2030, +13% in 2031) is the configuration costs above, not load. 2025 gas goes from +0.4% to -6.1%: 2025 renewables run 3% over EIA (the benchmark years, section "What is still wrong") and had been hidden by the extra load. Turbines fall further from EIA's 65-90 TWh (about 10 of which are CHP turbines). With 24-hour days (the tests) gas is -6.1% / -1.0% / +2.3% / +0.6% in 2025 / 2030 / 2040 / 2050, and the 2025 coal fuel known miss is gone; CO2 is -2.4% / +1.3% / +3.7% / +9.1% (section "Power CO2 and the CHP units" below).

The capacity LP takes its load from `build_case`, so it moves too. Planner chain 2027-2040 from EIA's 2026 fleet, 2040 GW before / after / EIA: CC 435 / 428 / 431, CT 238 / 246 / 267, batteries 108 / 108 / 103, solar 347 / 344 / 323, wind 370 / 362 / 404, coal 14 / 15 / 16, steam (with gas_conv) 56 / 56 / 52. Conversions 2028-2029 and the 2032 coal retirements barely move (32.1 + 1.5 GW; 67.0 / 68.4). With the new load the 2032 horizon solve stalled in HiGHS's dual simplex for over an hour at `user_objective_scale` -2; at -3 (`capacity.HORIZON_SOLVER_OPTIONS`) it takes 139 s. 889 s for the chain against 551, with the reference run on the machine.

**Still open.** Coal (+8% in 2030, the configuration costs); turbines; 2025 renewables; the residential and commercial own-use gross-up (LDSM's load holds that own use times the loss factor, about 7 TWh in 2030), not ported.

Pinned by `tests/test_emm_demand.py` (`test_net_load_matches_fleet_generation`, `test_total_generation_holds_distributed_pv`, `test_sales_follow_ldsm_mapping`, `test_load_takes_off_nontraditional_cogen_and_ldsm_losses`, `test_nontraditional_cogen_fuel_is_part_of_power_sector_fuel`). The 2025 coal fuel known miss is gone; the turbine floors in `test_turbines_carry_spinning_reserve` are 10 and 25 TWh.

## Power CO2 and the CHP units

**The question.** The load now leaves out the electric power sector's CHP units (class 4). Does the CO2 we compare with EIA still count their emissions once on each side?

**What EIA counts.** EFD adds a unit's carbon to UTCARC (by census division) and UTCO2N (by EMM region) for ownership classes 1 to 4 (uefd.f 3122-3232). So both totals hold the CHP units. EMELC is UTCARC summed over fuels (util.f 3515), which is UTCO2 plus Alaska and Hawaii (EDSPOAK, EDSPOHI): 1,436 against 1,422 Mt in 2025, 830 against 817 in 2050. The CHP units' CO2, CGNTQ times our factors, is 73 / 71 / 62 / 62 Mt in 2025 / 2030 / 2040 / 2050.

**What we report.** The coupled loop (`couple.py`) adds that CO2 to the fleet's, so its power CO2 and EMELC both count CHP once. No change there. The single-year fleet check (`dispatch_report.reference`) compared the fleet alone with all of UTCO2. That reference held about 60-73 Mt the fleet cannot emit. Its fuel rows already took CGNTQ off; CO2 did not.

**Fix.** `dispatch_report.fleet_co2` takes the CHP CO2 off UTCO2 (`chp=True` keeps it). The loop and the check share `demand.nontraditional_cogen_co2_mt`. Reporting only: no model output moves, so no switch.

| Fleet CO2, Mt (24-hour days) | 2025 | 2030 | 2040 | 2050 |
|---|---|---|---|---|
| Fleet | 1,316 | 1,036 | 568 | 824 |
| Old reference (UTCO2) | 1,422 (-7.4%) | 1,094 (-5.3%) | 609 (-6.8%) | 817 (+0.8%) |
| New reference (UTCO2 less CHP) | 1,348 (-2.4%) | 1,023 (+1.3%) | 548 (+3.7%) | 755 (+9.1%) |

The old reference made 2050 look right. On the fleet's footing it is 9% high, under the 10% tolerance by a point. Gas fuel is +0.6% in 2050 and coal is nearly gone, so the excess is likely capture: the LP takes a flat 90% at CCS plants (not checked).

National energy CO2, Mt, ours / EIA. Single-year `run_model` with `elec="lp"` and the stand-in elsewhere, so the other four sectors sit on EIA's:

| | 2030 | 2035 | 2040 | 2050 |
|---|---|---|---|---|
| Saved real set, Nov 3 (before 3e718b5) | 4,387 / 4,402 | 3,727 / 3,813 | 3,565 / 3,609 | 3,646 / 3,737 |
| Now (3e718b5 and this fix) | 4,401 / 4,402 | 3,827 / 3,813 | 3,614 / 3,609 | 3,793 / 3,737 |
| Power CO2 now | 1,108 / 1,109 | 721 / 706 | 630 / 624 | 886 / 830 |

The coupled 2050 power CO2 is now 7% high, where it was 11% low; `test_run_model_lp`'s 2050 CO2 known miss is gone.

**Still open.** Alaska and Hawaii (about 13-15 Mt) are in EMELC and not in the loop's power CO2 or fuel. The CHP oil (distillate and residual) is priced at residual's factor (under 0.1 Mt).

Pinned by `tests/test_emm_demand.py::test_power_co2_reference_counts_chp_once`.

## Coal by configuration: EFD's coal LP (branch coal-supply-efd)
**What holds the West's coal.** EFD buys every coal configuration's coal (ECP type B1..HC) in every coal demand region in its own coal LP, solved with the dispatch (uefd.f ED$COL 16433-17460, ED$BTU 7700-7790): supply rows per curve (11 steps of XCL_QECP x the XCL_STEPS widths at XCL_PECP, then a 12th at max(3 x p11, 9.999) 1987$/MMBtu, after the curve's fixed other demand XCL_OTHER), transport columns per route at the first-tier rate plus MATS activated carbon, a demand row CL<crg><type> per configuration, and two caps per configuration: sub-bituminous <= EFD_SB_DVLIM and lignite <= EFD_LG_DVLIM (escape at 9.9). The CMM writes the caps from EFD's own burn by unit, EMM_CL_BTUS (uefd.f 2993; coal.ams 10536-10580: burn x the plant's sub-bituminous or lignite share + 0.05). So in a converged run each western configuration burns cheap Powder River or lignite coal up to what it burned, and pays for anything more at the next source: bituminous from far away (0.3-0.5 1987$/MMBtu more in WS, C2, CU, ZN), the 9.9 escape where no bituminous route exists (coal regions C1 and MT), or 9.999 for Utah and Colorado bituminous, whose 2030 base production (11.8 and 33 TBtu) all goes to other users. Evidence (scratchpad `coalsup/`: cost.py, samp.py):
- EIA's 2030 restart: caps = burn for every capped configuration (WS C4 236.8 + 10.5 = 247.3 TBtu against 247.3; MT C4 4.4 / 4.4; CU B7 98.9 / 98.9; ZN B5 68.8 / 68.7).
- Oracle 2030 EFD (aimms-showreel sample, its own fleet on the restart's caps): the below-ceiling groups are the capped ones and sit on their caps whatever their heat rate: MT C4 4.45 TBtu on 4.43 (capacity factor 0.05), MT CX 7.35 on 7.32 (0.12), MT B7 39.8 on 39.6 (0.31), WS C4 248 on 247 (0.42), CU B3 0.09 (bituminous only, Utah coal short). Where a bituminous route is cheap enough EFD goes past the cap (WS B1 119 on 44, C2 C1 244 on 193).
- That is the configuration axis the earlier lanes saw (RMRG C4 at 8.8 1987$/MWh idle while B7 at 10.1 runs: MT C4 has no route beyond its cap, CU B7 does).

**Ported** (`coal_supply.py`, `dispatch.py`; on): `COAL_BY_CONFIGURATION`. The coal group's output in each region is split over its units' classes (coal region, configuration; 66 classes in 96 region-class pairs in 2030), each with its share of the capacity and hourly ceiling and its own heat rate and VOM (the CMM's units placed by the plant file). Their coal is bought in ED$COL's LP: 12 curves x 12 steps, 419 routes, the caps. The caps count cofired units and CCS retrofits too; the coal group gets the part its units burned in EIA's run (EIA's coal-unit generation at the group's heat rate). `COAL_PRICE_BY_CLASS` (off) says how LP prices meet the regional price: off, each class at EIA's own burn pays UPCOALAVG and the LP prices only departures from that burn; on, classes pay EFD's delivered price differences too (northern Appalachia 1.44 against Ohio 1.08), which with the dispatch's lower eastern marginal costs (PJMW 15.5 1987$/MWh against the oracle EFD's 18.0) idles West Virginia units EIA runs (2030 coal -2.9%, 2025 -8.6%). Dispatch only; the capacity LP keeps one coal price, so the planner chain does not move (build_case's heat rates, VOM and load are unchanged).

**Result.** Single-year dispatch on EIA's fleet, sales-based load with trade, 3-hour blocks. TWh, before / after / EIA. Coal is by fuel; coal units are pc + ig - sq.

| | 2025 | 2030 | 2031 | 2035 |
|---|---|---|---|---|
| Coal | 803 / 693 / 728 | 501 / 458 / 465 | 472 / 439 / 419 | 133 / 133 / 122 |
| Coal against EIA | +10.3% / -4.8% | +7.6% / -1.7% | +12.6% / +4.7% | +9% / +9% |
| of which coal units | 786 / 673 / 723 | 420 / 375 / 385 | 360 / 326 / 319 | 0.4 / 0.4 / 0.2 |
| Cofired units (all fuel) | 24 / 29 / 25 | 121 / 124 / 122 | 142 / 144 / 129 | 116 / 116 / 106 |
| Combined cycle | 1,425 / 1,526 / 1,544 | 1,368 / 1,409 / 1,449 | 1,337 / 1,369 / 1,446 | 1,383 / 1,383 / 1,414 |
| Gas, all | 1,474 / 1,582 / 1,570 | 1,455 / 1,497 / 1,469 | 1,438 / 1,470 / 1,477 | 1,610 / 1,610 / 1,577 |
| Gas against EIA | -6.1% / +0.8% | -1.0% / +1.9% | -2.7% / -0.5% | +2.1% / +2.1% |
| Coal fuel, trillion Btu | 8,168 / 7,034 / 7,446 | 5,192 / 4,721 / 4,891 | 4,974 / 4,622 / 4,460 | 1,669 / 1,668 / 1,491 |
| Seconds a year | 16.3 / 15.7 | 14.2 / 11.6 | 13.8 / 12.1 | 14.6 / 10.6 |

Seconds are with the reference run on the machine (an unloaded year took 7-8 s before); the coal LP adds no measurable time.

Coal units by region, 2030 (before / after / EIA): TRE 49.9 / 45.3 / 44.7, BASN 30.1 / 13.3 / 14.8, SRSG 17.6 / 16.5 / 16.6, SPPC 19.5 / 16.1 / 13.3, SPPS 17.0 / 16.2 / 10.1, RMRG 7.4 / 5.7 / 7.6; PJME 20.8 / 16.8 / 21.7, PJMW 76.7 / 70.9 / 78.8, PJMD 7.7 / 5.6 / 7.8. 2031: TRE 43.0 / 39.8 / 32.6, BASN 22.8 / 14.8 / 15.7, SPPC 17.1 / 13.8 / 10.1, SPPS 17.0 / 15.8 / 11.2. 2035 has almost no coal units left; its coal is the cofired units' and CCS retrofits', which are not split.

**Still open.**
- SPPS: the classes go past their caps at 1.40-1.50 1987$/MMBtu (WS B1, CX), 15.2 1987$/MWh, under the region's load-weighted marginal cost (16.7). EFD holds them at the cap.
- PJM falls 10-28% below EIA: its waste-coal (YP B3, 11,700 Btu/kWh) and West Virginia units now carry their own heat rates and sit at the dispatch's eastern marginal cost, which is 2-4 1987$/MWh under the oracle EFD's (PJME 12.9 against 16.9). The marginal-cost gap is the turbines and reserve question above, not coal.
- The cofired units' coal stays at the regional price outside the caps; held-back coal raises regional prices and TRE's cofired units run 8 TWh against EIA's 0.1 (SPPS 7.4 / 1.3, RMRG 7.8 / 2.2).
- 2025 is a STEO benchmark year (EFD's BMCLGEN rows), which the dispatch does not have; coal is 4.8% low there.
- The caps are the reference run's burn. In a scenario they stay at the reference levels, as EFD's would within an iteration; the coupled loop does not rewrite them.

The gen_coal 2025 known miss is gone (24-hour days). Pinned by `tests/test_emm_dispatch.py` (`test_diversity_caps_are_eia_burn`, `test_coal_supply_steps_follow_ed_col`, `test_coal_classes_split_the_coal_group`, `test_western_coal_held_by_its_caps`; `test_pjm_coal_runs_at_eia_level` now checks PJM as a whole). Scripts: scratchpad `coalsup/` (run.py the test years, reg.py and cls.py regions and classes, kls.py classes against EIA's burn, nmar.py the oracle's marginal costs).


## Turbines, the reserve price and EFD's modes (branch ct-reserve)

The question was whether turbines run too little because combined cycle gives spinning reserve away for free, so the reserve price is too low. It is partly true, but the price is not off by the factor earlier notes gave, and EFD's mode structure does not change it here.

**The units of EIA's reserve duals.** EFD's reserve rows are in GW (uefd.f OPBSLD,3/7/10: 1 - DRAT per committed GW, no hours) and its objective is in million dollars (OPBSLD,23: cost x GWh x 0.001). So SP_RES_DUAL is 1987$ per kW for the whole slice. NMARCST is the load row's dual times 100 (efd.ams NMARCST_calc), which is $/MWh. The base-slice duals of 2.0 / 3.0 / 2.2 above are therefore about 1.4 / 2.0 / 1.5 1987$/MWh (divided by the slice's 1,452 hours), and a region's yearly sum is $/kW-year: median 5.9 in the 2030 EFD (PJME 6.1, PJMW 5.4, NWPP 44). ECP's objective is nominal and discounted (uecp.f: every cost x UPGNPD x PWF). Its 2031 load duals over the slice hours, divided by the deflator (2.76 from 1987, MC_JPGDP) and PWF, give 16 1987$/MWh in the base slice, EFD's level. Its reserve duals' median of 19.5 $/kW-year (docs/capacity.md) is about 7.6 in 1987$. The capacity LP's 2.3 is about a third of ECP, not a fifteenth. The dispatch with turbine tiers gives a median of 2.7 against EFD's 5.9; PJMW is 4.9 against 5.4.

**What EFD does that the dispatch did not.**
- Dispatch modes (OPBSLD 9715-9870). A group is committed per season, in modes L = 1..3 (slices 1..L from the peak) and three shapes, each a fixed output per committed GW in every slice: O (base-load types, UPPCFB low bound above 0.001: max((1 - FOR) x FOS_CF_EFD, SR_MIN_CF), ReStore's capacity factor by slice; turbines (1 - FOR) x height / peak), J (SR_MIN_CF x height / the season's lowest) and U ((1 - FOR)(SR_MAX_LF + (1 - SR_MAX_LF) x height / peak)). A group's reserve in a slice is committed capacity less output. The earlier capacity LP port (ECP_DISPATCH_MODES) let output float between J and full capacity in every block; EFD's shapes tie a group's output across the season's slices.
- Plant groups at their own heat rates. EFD's 2030 turbines are AT 38 GW at 9,142 Btu/kWh running at 0.12 (41 TWh), ET 153 GW at 0.02 (25 TWh), CT 7 GW (10 TWh). AT carries 17 to 21 GW of reserve in every slice. The dispatch had one turbine group per region at the capacity-weighted mean (TRE 11,650), which no turbine is near.
- Who carries the 2030 base-slice reserve (GW, winter / summer / shoulder), EFD against main: combined cycle 46 / 60 / 48 against 51 / 60 / 60, coal about 10 / 20 / 13 against 20 / 33 / 24, turbines 32 / 36 / 31 against 9 / 6 / 3, batteries 31 / 34 / 34 against about 38, pumped storage 16 / 18 / 17 against 4 / 6 / 2. The requirement is 10 to 15 GW lower here (145 / 180 / 153 against 135 / 166 / 139): the load part is 4-8% lower and the wind and solar part 15-20% lower in the base slices (EFD has 344 GW of solar in 2030, the case 257).

**Ported.**
- `HEAT_RATE_TIERS` (on): TIER_GROUPS (the turbines) in three equal-capacity tiers per region by unit heat rate from the plant file, plus a tier for capacity beyond it at the new-build heat rate (`heat_rate_tiers`; the capacity-weighted mean is the old group heat rate). Each tier has its own output, cost and reserve, and with it the coal classes carry reserve class by class. Tiering combined cycle too was tried: it pulls combined cycle another 1.2% under EIA and moves steam from 5% under EIA to 6% over, and leaves the reserve price where it is, so only the turbines are tiered. Six tiers gave the same result as three.
- `EFD_DISPATCH_MODES` (off): the modes and shapes above, per region, group (and tier) and season, within the season's committable capacity. In every EFD slice the hour-weighted output of its hours equals the shapes' output, each hour is capped at the committed share of the hourly ceiling, and the reserve rows are EFD's 9 slices per region. FOS_CF_EFD is the 2030 composite's table for every year (no ReStore here).

**Result.** 2030 on EIA's fleet, national TWh, main / modes / tiers on CC and CT / modes and tiers / turbine tiers (EIA): turbines 11.3 / 11.6 / 23.2 / 24.4 / 21.9 (66.8); combined cycle 1,422 / 1,413 / 1,398 / 1,384 / 1,415 (1,462); steam 137 / 140 / 144 / 153 / 130 (136). The reserve price barely moves in any of them (median 2.7 with turbine tiers, 2.9 with six tiers on both groups, 1.8 with modes and tiers) and combined cycle keeps 50-70 GW of base-slice reserve. Modes take 370 s a year and modes with tiers 1,400 s, against 70 s. With one group per region, committing more combined cycle in the J shape displaces output of the same group at the same cost, so it is free. With tiers it is cheap, since adjacent tiers differ by a few hundred Btu/kWh. The shapes are not what makes EFD's reserve dear. The turbine energy the tiers add comes from the efficient tier (AT) running for energy, as AT does in EFD, not from reserve.

Generation, TWh, main -> turbine tiers (EIA). National:

| | 2030 | 2031 | 2035 |
|---|---|---|---|
| Coal units | 387.0 -> 389.2 (403.5) | 355.9 -> 360.3 (352.8) | 65.5 -> 65.6 (62.5) |
| Combined cycle | 1,421.6 -> 1,415.2 (1,461.5) | 1,392.4 -> 1,385.8 (1,468.6) | 1,533.3 -> 1,522.1 (1,558.2) |
| Turbines | 11.3 -> 21.9 (66.8) | 8.2 -> 16.2 (64.6) | 20.1 -> 35.7 (81.1) |
| Steam and cofired | 136.9 -> 129.6 (135.8) | 153.5 -> 147.2 (140.4) | 125.3 -> 119.6 (117.3) |

PJM (PJME, PJMW, PJMC, PJMD):

| | 2030 | 2031 | 2035 |
|---|---|---|---|
| Coal units | 99.6 -> 101.5 (114.7) | 97.0 -> 99.3 (105.1) | 25.4 -> 25.4 (24.2) |
| Combined cycle | 417.7 -> 415.0 (391.2) | 426.9 -> 423.1 (404.7) | 524.8 -> 530.6 (483.7) |
| Turbines | 1.3 -> 4.1 (8.7) | 1.2 -> 2.9 (9.0) | 2.9 -> 5.7 (16.2) |
| Steam and cofired | 4.1 -> 2.8 (7.6) | 5.1 -> 3.7 (8.3) | 5.7 -> 3.9 (12.0) |

Nuclear and renewables do not move. The load-weighted PJMW price goes from 15.4 to 15.1 1987$/MWh in 2030 (EFD 18.0): cheaper turbines lower the eastern marginal cost a little, so this does not close PJM's coal gap. A year takes 80-115 s instead of 50-70. The capacity LP does not read the tiers, so the planner chain is unchanged (2040 GW: CC 428, CT 246, batteries 108, solar 344, wind 362, coal 15, steam 56; EIA 431, 267, 103, 323, 404, 16, 52).

**Still open.**
- Turbines stay at a third of EIA's energy. Matching EFD needs turbines to hold 30-35 GW of base-slice reserve. The rest of the reserve balance differs: the requirement is 10-15 GW short (the case's solar capacity, and the load slices), pumped storage carries 12-14 GW less than in EFD, and batteries about 5 GW more. With the requirement scaled to EFD's and the battery reserve to EFD's 75 GW (scratchpad ctres, req2030.log), combined cycle took up the extra 15 GW and turbines rose only from 11 to 15 TWh. What remains is why EFD's combined cycle and coal stop at about 46 and 10 GW in the winter base slice. EFD's PassBack does not report column levels, so that needs a rerun that saves them.
- The capacity LP. Its reserve price is about a third of ECP's in 1987$ (above), and its turbines are one existing group plus AT. The chain's CT shortfall (246 against 267) is that LP's, untouched here.

Pinned by `tests/test_emm_dispatch.py` (`test_heat_rate_tiers_keep_the_group_mean`, `test_efd_mode_shapes_follow_opbsld`). Scripts: scratchpad `ctres/` (run.py the single-year runs with national, PJM and reserve output; before.txt, tct.log and tct2.log the tables; mt.log and modes2030.txt the mode runs).
