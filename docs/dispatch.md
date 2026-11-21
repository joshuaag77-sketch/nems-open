# Dispatch LP (steps 2 and 2b)

`nems_open.emm.dispatch`: a linopy + HiGHS model shaped like EFD. One year, 25 EMM regions, 36 typical days of 24 hours. Without trade a year solves in 5 to 8 seconds; with the regional links it takes about 35 seconds. Results against the AEO2026 reference are in `docs/dispatch_results.md` (regenerate: `python -m nems_open.emm.dispatch_report docs/dispatch_results.md`, about 4 minutes).

## What it does
- Six thermal groups dispatch on fuel plus variable O&M: coal, coal with CCS, gas combined cycle, gas combined cycle with CCS, gas turbines, steam. Captured CO2 earns the 45Q credit (`TCS45Q/ccs_saline_45q`).
- Nuclear runs at its monthly capacity factor. Hydro dispatches inside a monthly energy budget. Wind and solar use EIA's hourly profiles (`WRENEW/ws*_cf`) cut by each type's outage rate. Batteries and pumped storage cycle inside each day.
- Regions trade over the links in the ETT table (`V_EMM_PRETTIN`: 127 rows, summer and winter MW, a $/MWh markup, 2% line loss, plus the new transmission EMM built, `UETTOUT/UTNEWTRN`).
- Capacity is what is in service on average through the year. The plant file's in-service and retirement months are used for dated units; capacity the restart shows beyond that is assumed to arrive mid-year.
- Load is the step 1 shapes scaled to the demand modules' sales (`demand.py`).
- EFD's spinning reserve rows, availability and planned maintenance, and oil units running last (`EFD_SPIN_RESERVE`, `EFD_DERATE`, `OIL_UNITS_LAST`, all on; section "EFD's spinning reserve and turbines" below). Coal's ceiling follows EFD's maximum-load mode from 2028 (`EFD_MAX_LOAD_SHAPE`, on; section "Coal's ceiling is EFD's maximum-load mode"). The results table above them predates these switches.
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
