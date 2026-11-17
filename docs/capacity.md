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

## Retirements the way ECP decides them (2026-11-03, branch emm-retire)
ECP is partly AIMMS in this checkout (`models/ecp/MainProject/ecp.ams`, with Fortran `uecp.f` and `udat.f` building its inputs). What it does for existing plants:
1. `udat.f` (RET_VAL, lines 7395-7450) ranks every existing plant group by last year's dispatch margin: revenues (`ULREVS`, less the capacity payment) minus variable cost, fixed fuel cost, and SO2, NOx, RPS, Hg and GHG penalties, per kW.
2. It bins each ECP type into 4 retirement groups by that margin (groups cover 5, 45, 40, 10% of the margin range, `%RET GRPS%`), giving group capacity `EPGCAP` and group cost `EPGFOM` = fixed O&M + capital additions + age adder + the group's margin shortfall against the type average.
3. In the LP each group is a capacity column bounded by `EPGCAP`; keeping it costs the present value of `EPGFOM` over the planning horizon (year 1 is sunk), less (group number - 1), times (1 - hurdle), hurdle = 5% for fossil. A group retires when the LP finds it cheaper to be without it.
4. The cap on economic retirements is 3% of a region's capacity in the first year, rising a point a year to 6%, and then switched off (`uecp.f` 1171-1177: past `UPRETRTL` the limit becomes zero, meaning none).

What this branch now mirrors: the cost of staying is fixed O&M + capital additions (`T_CAPAD`, as large as fixed O&M for coal and steam) + the age adder for units 30+ years old, times (1 - 5% hurdle); and the cap disappears after 6%. Result against cb2026 (cells inside 5%): 2027 117/175, 2030 84/175, 2035 65/175 (before: 125, 83, 67). Coal timing is much closer in 2030 and 2031 (80 and 79 GW vs EIA 88 and 78) but now retires too fast in 2027 to 2029 (119 vs 153 in 2027). Steam is worse (45 vs 110 GW in 2030) because the conversions EIA makes are still missing.

### The wall
Steps 1 and 2 need the margin of each plant group, which comes from EFD's plant-group output arrays of the previous cycle (`ULREVS`, `ULCAPC`, `ULVCST`, `ULFCST`, `ULSO2P`, `ULNOXP`, `ULRPSP`, `ULHGP`, `ULGHG` in `UEFDOUT`). They are not in the restart. Without them the groups, `EPGCAP` and `EPGFOM` cannot be reproduced, and my estimate (one cost for a whole region and type) cannot reproduce which units sit in the cheap-to-lose group.

Export that would settle it: for each year of the reference run, the ECP input arrays `EPGCAP(fuel region, retire group, ECP type, region, year)` and `EPGFOM(retire group, ECP type, region, year)` as passed to AIMMS (Fortran `udat.f` common block, written at the `AIMMS_TransArray_out_ecp` call in `uaimms.f`), or the `ULREVS` family above.

### Capacity credit
ECP computes intermittent credits in `CAP_CREDIT` (`uecp.f` 40065): a net-load-weighted average over the 864 hours (weight = (net load / peak)^5) of each type's capacity factor, or the variance method (z-score `UPINTZ`) where thermal units dominate, stored in `EPIRCCR`. The inputs are the 864-hour system load (`DUCK_SYSTEM_LOAD`) and hourly renewable capacity factors, which are not in the restart either. The model's own method (top 88 hours of net load) is of the same family. Export that would settle it: `EPIRCCR(type, year)` by region from the same AIMMS transfer, which would let me check my credits directly.

## ECP's own inputs rebuilt (2026-11-13, branch emm-capacity3)
The data wall from emm-retire is down: the inputs it named are built from what EIA's Fortran builds them from.
- **Retirement groups** (`emm/retire_groups.py`): EPGCAP and EPGFOM as `udat.f` makes them (lines 7395-7480, 10820-10880). Every unit that may retire is ranked by last year's margin, revenue less variable, fixed and emission costs per kW, with revenue from our own LP's energy prices (the reserve payment left out, as `udat.f` does). The national margin range is cut at 5/45/40/10% of the range (not of capacity, as the emm-retire notes said), and each group carries its fixed cost plus its operating-margin shortfall against the region's average. The loop tracks which plant-file units the LP has retired, so the cheapest-to-lose units go first. Age adder fixed: coal 0.0666 $/kW per year of age, gas 0 (`%XTRA Opt 2%`), not 3.74 $/kW for every unit over 30.
- **Capacity credit** (`emm/capacity_credit.py`): CAP_CREDIT's variance method by region over the 864 typical hours, z = 3.19 (UPINTZ), plus the net peak (EP_NET_PEAK). The wind file's site standard deviation and correlation are not in the checkout; the formula's own cap makes them drop out, which is assumed.
- **Regional reserve margins** as EP$MRM writes them: EPMRM x peak + net peak per region, dispatchable capacity at full value, firm transfers over links at 75% of capacity.
- **Cost of capital** from EIA's formula (EPDSCRT, `uefp.f`): 0.6 x AA bond rate x (1 - 0.24) + 0.4 x (10-year Treasury + 5.75% x 1.25), about 7%, from the restart's macro rates; replaces my 6.5%. Combined cycle and coal pay EXTRARISK (3 points on debt and equity, `util.f` 893-902), +2.6 points after tax.
- **Lead times** (UPCLYR): a type can come online no earlier than 2025 plus its construction years.

Result, 2025 to 2035 (cells inside 5%): **2027 113/175, 2030 82/175, 2035 66/175** (emm-retire: 117/84/65). The reserve price now lands on EIA's: median 31.4 against RMAVG 30.8 $/kW-year in 2030 (24 vs 30 in 2027, 35 vs 30 in 2035; it was 14 with the old discount rate). Steam in 2035 matches (100 vs 101 GW, coal converted at the 2032 rule). Wind in 2027 is inside in all 25 regions.

What still misses, and why it is now a question for the AIMMS reference run rather than a missing input:
- Coal retires too fast before 2030 (115 vs 153 GW in 2027).
- No new turbines (156 vs 260 GW in 2035): with the risk premium combined cycle costs about 48 $/kW-year against turbines' 40, but combined cycle also earns enough energy margin to win.
- No solar or battery builds after the tax credits end (solar 337 GW flat from 2030; EIA keeps building).
ECP's own LP, solved in AIMMS on the same inputs, shows which of its terms we are missing (docs/aimms_needs.md).

## ECP's planning horizon (2026-11-15, branch emm-capacity3)
`capacity.HORIZON` (off by default) plans each year over ECP's horizon (emmcntl.txt UNXPH 3 of UNFPH 30): this year, next year, and a tail year 10 years out that stands for years 3 to 30, weighted by present value. Each period has its own load, fuel prices (the reference run's, moved by the loop's own shock), dispatch in 6-hour blocks and reserve margin. Only this year's decisions are carried out. In EIA's 2030 ECP the tail's reserve row (1,120 GW) is about this model's 2040 requirement, hence the 10 years. A year takes about 115 s (40 s without).

Cells inside 5% of 175 against the AIMMS oracle (2027 / 2030 / 2035 / 2050):

| version | vs oracle | vs cb2026 |
|---|---|---|
| one year (default) | 109 / 66 / 59 / 58 | 113 / 78 / 58 / 59 |
| horizon, later builds in the tail year | 107 / 69 / 65 / 59 | 112 / 81 / 67 / 59 |
| horizon, last builds in year 3 (as ECP) | 105 / 67 / 65 / 60 | 111 / 78 / 64 / 57 |
| horizon, later builds only where the lead time fits (CC, wind, CCS chosen now) | 101 / 61 / 65 / 55 | 108 / 71 / 66 / 60 |

The horizon does not end the post-2030 stall in wind, storage and turbines, and it makes coal-to-gas conversion far too large (steam 158 GW in 2050 vs 49 in the oracle), so it stays off. The lead-time version gains 8 and 1 cells against cb2026 in 2035 and 2050 but loses 5 and 7 in 2027 and 2030, loses port fidelity in three of four years, and converts twice EIA's coal to gas (steam 174 vs 80 GW in 2027); net worse. The stall is not myopia: this model meets its reserve requirement (1,245 GW in 2050) with no shortfall, while EIA's ECP keeps 1,463 GW of dispatchable capacity. ECP's reserve rows (rRXXXXXge in OutToNEMS_YYYY.txt) for planning year 3 sit about 250 GW above year 2 in every year, far more than a year's load growth, so how ECP writes the requirement (uecp.f EP$MRM: which capacity moves to the right-hand side, the planning reserve on top) is the next thing to port.

## EPA 111 and the 2039 coal cliff (2026-11-15, branch coal-ccs-2040)
cb2026 runs with EPA's 2024 rule on (emmcntl.txt %EPA 111 SW%: switch 1, UEPA_GSYR 2030, UEPA_CGSH 0.6, UEPA_CLCFYR 2038, UEPA_CLYR 2031, UEPA_NWGSYR 2029, UEPA_NWGSCF 0.4). EIA's run converts 36 GW of coal to coal-gas cofiring by 2030 (restart prefix ng: 14.3 GW in 2024, 50.2 GW in 2030), which burns up to 60% coal and retires at the end of 2038 (ng 49.5 -> 1.7 GW in 2039). That is EIA's coal cliff: power coal 1,516 -> 861 trillion Btu and coal generation 124 -> 63 TWh from 2038 to 2039, steam about 100 -> 51 GW.

Ported to the capacity LP (capacity.epa111, epa111_retirements): conversions only through 2030, converted coal cofires at 60% coal and retires after 2038 together with the reference run's existing cofiring units, and new combined cycle without CCS is held to a 40% capacity factor from 2029. One-step scores (each year solved once from EIA's own fleet of the year before; cells inside 5% of 175, 2027 / 2030 / 2035 / 2050): against cb2026 125 / 113 / 124 / 123 before, 125 / 116 / 125 / 124 after; against the oracle 116 / 70 / 59 / 67 before, 116 / 75 / 60 / 68 after.

Not explained yet:
- 2040 coal (dispatch on EIA's capacity 93 TWh vs 63). After 2038 all of EIA's coal is 16.2 GW of CCS retrofits running at a 45% capacity factor (63 TWh, 861 trillion Btu, 13.7 MMBtu/MWh: partly below full capture, whose heat rate is 14.8). The dispatch runs them at EFD's 65% cap because 45Q makes them the cheapest plant. Ruled out from saved outputs: the credit value (the oracle's EFD sees 33-36 $/t, CENS_VAL_45Q in PassBack_2040), its eligibility (retrofit records get the retrofit year as W_SYR), the capacity factor cap (pltdata CSC 0.65, the same in EFD), capture O&M (T_CCSV 1.2 $/MWh), must-run flags and the unit CF fade (ends 2030). Next: EFD's EP_MRM/BTU debug lines (unit 18) for a CCS group in 2040, which needs an oracle rerun with EMM_EMMPRNT kept, under HEAVY.lock.
- The oracle's missing CCS retrofits (0 vs EIA's 16.3 GW) and cofiring (oracle steam 79 vs EIA 110 GW in 2030): both are coal-configuration choices in ECP (uecp.f EP$COAL, configurations from udat.f). The oracle loads the CCATS prices and RUN45Q and its ECP has retrofit columns at their bounds in OutToNEMS_2030; why the configurations are not taken needs ECP's CCATS_RETRO_CL / config debug lines from the same rerun.
- One-step solves retire almost all steam at once (9 GW in 2035 vs EIA's 101) once the retirement rate cap lapses after 2034: steam's cost of staying exceeds what the LP values it at. Worth porting ECP's steam retirement economics next.

## Steam retirements in one-step solves (2026-11-15, branch steam-retire)
`python oracle/score_onestep.py` solves each year once from EIA's own fleet of the year before. With the one-year LP the 2035 step retires 52 GW of steam, 49 GW of combined cycle and 30 GW of turbines (EIA: almost none), and the 2050 step 334 GW. Cause: from 2035 the retirement rate cap has lapsed, EIA's fleet carries a reserve surplus that ECP built for its tail year's peak, and a one-year LP prices that capacity at almost nothing. ECP's retirement test sees the horizon: with capacity.HORIZON the 2035 step retires 11 GW and keeps 93 GW of steam (EIA 101).

Cells inside 5% of 175, one step (2027 / 2030 / 2035 / 2050):

| | vs cb2026 | vs oracle |
|---|---|---|
| one year | 124 / 112 / 120 / 117 | 115 / 74 / 54 / 65 |
| horizon | 112 / 108 / 141 / 123 | 99 / 70 / 63 / 69 |

The horizon fixes the mid-period steam dump but retires coal early in 2027 (92 vs 153 GW) and still retires 240 GW in 2050 (steam 10 vs 51), so it is +11 cells against cb2026 and -7 against the oracle. It stays off. Next: the horizon's retirement value. ECP's tail requirement grows with load past 2050 and its retirement groups pay EPGFOM net of the margin over all horizon years; this LP's tail holds 2050 prices and only the group's first-year margin. Port both before switching it on.

## Why the horizon still retires capacity in 2050 (2026-11-15, branch horizon-retire)
The two ports asked for are already in the LP: the tail year's load keeps the reference run's last five years of growth past 2050 (future_case), and every kept retirement group earns its dispatch margin in each period's own dispatch, so the group's fixed cost is netted against margins over the whole horizon (only the group's deviation from its region's average margin uses this year's prices). What differs is reserve accounting. From EIA's own 2049 fleet this model counts 1,581 GW of firm capacity for 2050 (thermal 1,223, nuclear and other 112, hydro 80, battery 77, pumped 20, wind 46, solar 23) against a requirement of 1,202 GW (peak 1,109, net peak 1,066; EIA's own sector peaks for that year sum to 1,163 GW), a 380 GW surplus, so the reserve price is zero and the LP retires 240 GW. EIA's ECP in its 2050 run has positive duals on its reserve rows for planning years 2 and 3 (rRXXXXXge in OutToNEMS_2050.txt). So ECP counts much less firm capacity per GW of existing plant, or adds much more to the requirement (PKADJ: UEITAJ_ECP and UTRELADJ, trade at the peak), than this model. That decides retirements once the rate cap lapses, and it is the next thing to port. HORIZON stays off.

## Queued for the next oracle rerun (needs HEAVY.lock)
Rerun the AIMMS oracle 2020-2050 with EMM's debug print kept (do not delete run_emm/EMM_EMMPRNT, unit 18; about 4 GB) and keep ECP and EFD's OutToNEMS / PassBack files for 2027-2032 and 2040. Then:
1. CCS coal capacity factor in 2040 (EIA 45%, our dispatch 65%). Read EFD's BTU and 45Q lines for a coal CCS group (uefd.f OPBSLD, formats 6317 and 2316/2317: SHR_NOCCS, ADJ_FAC, EOR_REV, CENS_VAL_45Q) and the group's cost column in the 2040 EFD solution. Question: what makes EIA's EFD hold full-capture coal to 45% when 45Q makes it the cheapest plant?
2. The oracle's 0 CCS retrofits and 0 coal-gas cofiring conversions (EIA: 16.3 GW and 36 GW by 2032). Read ECP's coal configuration lines for 2027-2031 (uecp.f EP$COAL: CCATS_RETRO_CL, T_RETRO2, the retrofit configuration columns cRETRO / cRETROHTRT and their reduced costs in OutToNEMS). Question: which configuration costs or bounds keep ECP from choosing CCS or cofiring standalone, when EIA's coupled run chooses both?
3. ECP's reserve rows. Read the EP_MRM debug lines (uecp.f format 2013: EPPEAK, EP_NET_PEAK, EPMRM, PKADJ, UEITAJ_ECP, UTRELADJ by region and planning year) for 2030, 2040 and 2050, and the reserve-row coefficients of existing capacity columns (EP$COAL 23 and the other plant types). Question: how does ECP's reserve row see 380 GW less surplus than this model in 2050, so that its duals stay positive?
