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

Correction (2026-11-17, branch ecp-reserve): most of that 380 GW surplus was double counting in how this model read the restart, not ECP accounting. See the next section.

## The 2050 reserve surplus was double-counted gas capacity (2026-11-17, branch ecp-reserve)
EIA's UCAP tally (`util.f` 7061-7620) adds every unit to its main group's array and, for some types, to a subgroup array as well. UCAPCC holds every combined cycle, including the ACC, ACS and AC2 units that also go to UCAPAC, UCAPAS and UCAPA2. UCAPCT holds every turbine, including the ACT and CTA units that also go to UCAPAT and UCAPT2. Upstream `util.f` also nests CAV, COQ and CAS (ig, pq, is) inside UCAPCS, but the cb2026 restart does not: in 2024 cs is 162.8 GW, the plant file's coal (163.5) less its 0.71 GW CAV unit, so coal keeps summing cs and ig (dropping ig broke the 2025 and 2030 coal dispatch scores). `dispatch.CAPACITY_PREFIXES` summed main and subgroup arrays, so every advanced CC, CCS and advanced turbine EIA built was counted twice. The restart confirms it: in all 25 regions and every year 2025 to 2050, cc is at least ac + as + a2 and ct at least at + t2; the growth of ct since 2024 matches at + ic to within 4 GW nationally and 6 GW in any region, and the growth of cc is at least ac + as in every region (to within 0.7 GW of retirements).

Size of the double count (cb2026, GW): 38 in 2030, 125 in 2035, 345 in 2049 (ac 161, as 52, at 133). The same applies to the UADD arrays the build scorecard reads.

Fix: each group now reads only main arrays, and gas_cc subtracts CCS (`"-as"`): coal unchanged (cs + ig + pq + is + oc), gas_cc = cc - as + fc, gas_ct = ct + ic + i2. Same for `capacity_report.ADD_CATEGORIES`. Pinned by `tests/test_emm_capacity_prefixes.py`.

What it changes:
- **The 2050 reserve.** From EIA's 2049 fleet, thermal capacity is 877.5 GW, not 1,222.5. Firm capacity for 2050 drops from 1,581 to about 1,236 GW against this model's requirement of 1,202. The surplus that set the reserve price to zero and let the horizon retire 240 GW is about 34 GW. ECP's own requirement for 2050 (year 2 of its 2049 solve, binding in all 25 regions) is 1,270 GW, so against ECP's requirement this fleet is 34 GW short, not 380 GW over.
- **EIA's build targets.** EIA adds 67 GW of turbines by 2035 (15 by 2027, 29 by 2030), not 120, and 73 GW of combined cycle without CCS by 2035, not 146. The model's 2035 combined cycle (147 GW in the last loop) is now about double EIA's, and turbines (43 GW) are 36% low, not 64%. "Why the turbines do not come" above overstated the gap.
- **Regional scorecard.** EIA's gas_cc (with CCS) is 357 GW in 2035, not 429; gas_ct is 208, not 260.
- **Dispatch on EIA's capacity.** `build_case` reads the same arrays, so from about 2028 the dispatch LP had more gas capacity than EIA's fleet. 2025 to 2027 are unaffected: ac, as and at are zero until 2027 and small until 2030. In 2030 the phantom 37 GW of gas had been displacing coal: dispatch coal generation goes from 493 to 539 TWh against EIA's 465 (+6% to +16%), gas from 1,561 to 1,515 against 1,469. `test_emm_dispatch` now lists coal generation and fuel in 2030 as known misses; the coal overrun is a dispatch question (heat rates and EIA's coal economics), no longer hidden by extra gas.
- **The capacity loop from 2025** starts from the 2024 fleet, which has no subgroup capacity, so its starting point is unchanged. Its results still move through `build_case`.

### How ECP's reserve row counts capacity (`uecp.f` EP$MRM and the AIMMS `rRXXXXXge`)
- Requirement: EPPEAK x EPMRM + EP_NET_PEAK + PKADJ, where PKADJ = UEITAJ_ECP (peak-season trade) + UTRELADJ - BTCOGEN/8.76 + BMEXICAN/8.76. Cogeneration's average output comes off the requirement; cogeneration capacity is not on the row.
- The row binds only in planning years after the turbine lead time (`YEAR > UPPLYR(WICT)`, so years 2 and 3). Year 1 is a free row (`rRXXXXXn`). ECP never holds the year being decided to a reserve margin; its reserve price comes from next year and the tail.
- Coefficients: existing dispatchable capacity outside retirement groups 1.0 (EP$BDSP,51), must-run 1.0 (EP$BDSP,52), gas plant groups CAP_FCTR = 1.0 unless converted to CCS (EP$NGBS,9), nuclear 1.0, wind and solar EPIRCCR, hydro and other renewables UPCCR or RNWFAC, storage DINURAL_STORAGE_CAPACITY_CREDIT (at most 1), new transmission 0.75 (EP$ETT). This model's row has the same structure, so the double count, not a coefficient, made the surplus.
- Oracle requirement by year (sum of rRXXXXXge.Lower, planning year 2): 945 GW for 2027, 959 for 2030, 1,027 for 2035, 1,117 for 2040, 1,201 for 2045, 1,270 for 2050. The row binds in 13 regions in 2027 and in all 25 by 2050.

### Still open
- **Requirement.** This model's 2050 requirement (1,202 GW) is 68 GW below ECP's (1,270). About 54 GW of that is the peak: this model's 2050 peak is 1,109 GW against EIA's sector peaks of 1,163. The rest is PKADJ and EP_NET_PEAK, which need the EP_MRM debug lines (question 3 below).
- **One year or two.** This LP holds the current year to its reserve margin; ECP holds next year and the tail. With HORIZON off, the closest match to ECP would hold next year's requirement. That is a design change to test after the rerun, not part of this fix. Settled 2026-11-21 (branch ecp-lookahead, last section): the one-year LP already is ECP's year 2, and ECP does not anticipate the 2032 cliff.
- **CCS capacity factor and zero retrofits** (questions 1 and 2): the saved oracle outputs (OutToNEMS without the unit-18 debug file) cannot settle them. They stay queued.

## Queued for the next oracle rerun (needs HEAVY.lock)
Rerun the AIMMS oracle 2020-2050 with EMM's debug print kept (do not delete run_emm/EMM_EMMPRNT, unit 18; about 4 GB) and keep ECP and EFD's OutToNEMS / PassBack files for 2027-2032 and 2040. Then:
1. CCS coal capacity factor in 2040 (EIA 45%, our dispatch 65%). Read EFD's BTU and 45Q lines for a coal CCS group (uefd.f OPBSLD, formats 6317 and 2316/2317: SHR_NOCCS, ADJ_FAC, EOR_REV, CENS_VAL_45Q) and the group's cost column in the 2040 EFD solution. Question: what makes EIA's EFD hold full-capture coal to 45% when 45Q makes it the cheapest plant?
2. The oracle's 0 CCS retrofits and 0 coal-gas cofiring conversions (EIA: 16.3 GW and 36 GW by 2032). Read ECP's coal configuration lines for 2027-2031 (uecp.f EP$COAL: CCATS_RETRO_CL, T_RETRO2, the retrofit configuration columns cRETRO / cRETROHTRT and their reduced costs in OutToNEMS). Question: which configuration costs or bounds keep ECP from choosing CCS or cofiring standalone, when EIA's coupled run chooses both?
3. ECP's reserve rows. Read the EP_MRM debug lines (uecp.f format 2013: EPPEAK, EP_NET_PEAK, EPMRM, PKADJ, UEITAJ_ECP, UTRELADJ by region and planning year) for 2030, 2040 and 2050, Question (narrowed 2026-11-17: the 380 GW surplus was this model's double count, and the coefficients are read from source above): what makes up ECP's 2050 requirement of 1,270 GW against this model's 1,202, split into EPPEAK, EP_NET_PEAK and PKADJ (UEITAJ_ECP, UTRELADJ, BTCOGEN, BMEXICAN) by region?
4. Rerun this model's one-step and horizon scores (`oracle/score_onestep.py`, `capacity_regions`) and the 2025 to 2035 loop after the subgroup fix (branch ecp-reserve). Check that the 2050 one-step solve no longer retires about 240 GW, that the reserve price is positive in 2050, and that the turbine and combined cycle targets now read 67 and 73 GW for 2035.

## Planned additions fill the first build step (branch ecp-cc-solar)

ECP puts the year's planned additions of a type into its first elasticity step (uecp.f EP$ELAST,2-3: a fixed column of min(ESTCPLIM step 1, ESTYRPLN) in the step-1 row), by the unit's own ECP type (PT counts as PV, WL as WN). The LP gave its own builds the whole first step on top of the plant file's. In 2027 that let it build 45 GW of solar on top of 26 GW planned (EIA: 6 GW unplanned); the 71 GW then set 2028's first step at 89 GW, all built. Now `build_steps(..., planned)` and `planned_in_step` take the planned units out of step 1. Chain 2027-2029 from EIA's 2026 fleet, before / after: solar builds 45.4 / 19.6 (2027), 89.1 / 56.5 (2028); solar capacity 2029 352 / 293 GW (EIA 2030: 258). Gas types are unaffected (planned gas units are EC/ET, not AC/AT).

Combined cycle is not a build-step problem. The loop converts no coal to gas and retires steam early: in 2030 it has 89 GW coal and 53 GW steam against EIA's 88 and 110 (EIA's steam includes about 28 GW of 2028-2030 conversions). That firm capacity is replaced by combined cycle in 2030-2037 (128 GW built against EIA's 58), when CC wins on energy margin. EIA loses it around 2038-2040 (cofiring ends 2038) and replaces it with turbines (39 GW in 2039-2040; the loop builds 5). Hence CC +47 GW and CT -89 GW in 2040.

## ECP's reserve accounting (branch ecp-reserve)

How ECP's reserve row counts capacity, read from `uecp.f`: dispatchable plants 1.0 (EP$BDSP,51, EP$NGBS,9); wind and solar EPIRCCR (CAP_CREDIT, already ported); conventional hydro RNWFAC = 0.70 (EP$BRNW,18 and 55; `dsmsectr`); pumped storage UPCCR(PS) = 0.70; batteries the CAP_CREDIT_LDC credit (uecp.f 39834-40060: top-8-hour mean of net load less stored energy / hoursToSell, over the top-8-hour mean of net load; 0.88-1.0 on EIA's fleets), for existing and new alike. Existing interregional lines earn nothing on the row: ECP credits 0.75 of a line only when it builds one (EP$ETT,58-59) and carries earlier builds as UTRELADJ on the requirement (uecp.f 32118-32166).

Ported (`capacity.ECP_RESERVE`, on): hydro and pumped storage at 0.70 (were up to 1.0 and 0.88), batteries at the CAP_CREDIT_LDC credit with a peak-shaving stand-in for the EFD's storage level (were 0.74), no free lending over existing links (was up to 0.75 of every link), EIA's UTRELADJ added to the requirement.

One-step 2033 from EIA's fleet, reserve price $/kW-year: before 16-17 in the east, 6-7 in the west (13 regions under 18); after a spread of 3 to 42 by region, 13 of 25 inside EIA's 21-45. No turbines either way (CC 3.3 -> 9.6 GW; retirements 33 -> 31 GW). The free lending was what flattened prices across regions; batteries now count more than before (EIA's credit is near 1), which offsets most of the hydro cut.

What is left is the requirement. ECP's own 2033 requirement (OutToNEMS_2032, rRXXXXXge.Lower, planning year 2) sums to 991 GW; this model's is 948. The gap is regional: ISNE 29.3 vs 21.6, NYUP 18.9 vs 12.5, MISS 39.0 vs 33.6, MISW 43.5 vs 38.8, TRE 110.5 vs 105.5, SRSG 39.9 vs 35.5. Diagnostic only (not committed): the same 2033 solve with ECP's requirement prices reserves at a median 34 (most regions 28-46), builds 8.5 GW of turbines and 27.6 of CC, and retires 12 GW. The peaks come from fixed regional shapes on net load (international imports and end-user generation taken off flat), not LDSM's ECP load (EPPEAK, EP_NET_PEAK); porting that is the next lever.

Chain 2027-2040 from EIA's 2026 fleet, 2040 national GW, before / after / EIA: CC (with CCS) 494 / 482 / 431, CT 189 / 182 / 267, steam 33 / 41 / 52, solar 344 / 343 / 323, battery 112 / 127 / 103, wind 383 / 385 / 404. Median reserve price in the chain was already in EIA's band (29-36 most years) before and stays there.

Conversions (b1e0ace) on top, branch ecp-reserve-conv: steam tracks EIA better through the 2030s (2030 86 vs 64 without, EIA 110; 2033 80 vs 61, EIA 103) and coal lands on EIA in 2030 (91 / 88), but by 2040 CC is 492 (vs 482 without, EIA 431) and CT 183 (EIA 267): the converted capacity retires when cofiring ends in 2038 and is replaced with CC, not turbines. It does not fix the turbine gap; the requirement does.

### The requirement on ECP's load (`ecp_load`, `capacity.ECP_PEAK`)
EPPEAK is the top of LDSM's 864-hour system load (UPPEAK, udat.f 14369-14381), EP_NET_PEAK that load over the top net-load hours, and PKADJ adds firm contracts (UEITAJ: V_EMM_ETCNCT exports less imports x 0.91, prepett.f 769), UTRELADJ and UCAPADJ (cogeneration, Mexico). The LP now runs the ported LDSM (dsmfor, dsmdlt, dsmhlm) for the year from the nearest oracle `ld_in` dump; it reproduces the oracle's 2030 UPPEAK exactly in every region, and the 2033 load is the same from the 2027 or 2030 dump. LDSM's 2033 peak is 924 GW (the old shape: 876; ISNE 29.3 vs 19.8). Without the dumps the LP falls back to its own shape.

2033 requirement: 999 GW against ECP's 991 (+0.8%). By region within 2 GW in 19 of 25; off by more in MISC +3.3, SRCE -2.9, NYUP +2.8, TRE -2.3, MISW -2.2 (ISNE 31.1 vs 29.3). The rest is likely EP_NET_PEAK's hours (ECP's restart intermittent capacity, DEM_ADJ in its net load) and UTRELADJ timing; not pursued.

One-step 2033 from EIA's fleet: reserve price 22 of 25 regions inside 21-45 (ISNE 15, PJMW 19, SPPN 7 below); 8.8 GW of turbines (MISS 2.1, PJME 3.9, BASN 1.6, NYUP, PJMC) and 27.6 of CC; retirements 3.3 GW (were 31). Turbines are not in TRE, SPPS, CASO or MISW: there the LP takes CC for the same reserve need.

Chain 2027-2040, 2040 GW, accounting-only / with ECP's requirement / EIA: CC 482 / 491 / 431, CT 182 / 207 / 267, steam 41 / 49 / 52, solar 343 / 343 / 323, battery 127 / 141 / 103, wind 385 / 371 / 404. CT tracks EIA through 2032 (201 vs 194) and then stops while EIA adds about 7 GW a year; the CC choice and the battery credit (near 1 here, builds 38 GW over EIA) are what is left.

LDSM's load follows the run (`ecp_load.follow_run`): the shaped part of the run's net energy scales LDSM's hours by its ratio to the reference run's for that region and year, and flat added load (DispatchCase.flat_twh, the data center cases) goes on as flat GW, so 10 GW of data centers lifts a region's requirement by 10 x (1 + EPMRM). The reference run is unchanged (ratios of 1). LDSM costs about 0.4 s per year (cached per year).

## Why CC beat turbines on reserve need, and why batteries overshoot (branch ecp-cc-ct-battery)

Chain 2027-2040 from EIA's 2026 fleet (`CapacityPath(first=2027)`), baseline on main: 2040 CC (with CCS) 491, CT 207, battery 141, solar 343 GW against EIA 431 / 267 / 103 / 323.

**Turbines.** At the LP's own energy prices (balance duals) a new turbine earns almost nothing above its variable cost (0 to 1.3 $/kW-year in every region in 2030), so its net cost is its capital and it is built only when the reserve price reaches it. A new CC earns 8 to 19 $/kW-year even at EPA 111's 40% cap. The capital gap was 7 to 8 $/kW-year (2035: CC 43.7, turbine 35.9), so CC's net cost sat below the turbine's in most regions and CC took the reserve-driven builds. 2033-2037: turbine step 1 was 17 to 27 GW at 37 to 38 $/kW-year against a reserve price of 25 to 32, and 0.0 to 0.6 GW were built a year while CC filled 10 to 20 GW. Five years without turbine builds then shrank the turbine steps to 1.5 / 0.9 / 1.2 GW, so the 2039 cofiring retirements (reserve price 55) went to CC (22.8 GW) and turbines got 2.4.

ECP prices the two differently. Its build columns (oracle OutToNEMS_2035, cB_DSP step 1, planning year 1) cost AC 1.23 to 1.30 times AT by region, median 1.28; this LP had 1.20 to 1.24. The missing term is interest during construction: EP$BDSP,62 annualizes EPINCST's book value, the overnight cost spent by the type's UPCPRO profile and carried at the plant's rate to the online year. A CC (3 years, 25/50/25%, at its EXTRARISK rate) carries 10% over overnight, a turbine (2 years, 35/65%) 3%, a battery 1%, CCS 10%. With it the LP's 2035 ratio is 1.27 to 1.31 (median 1.29). Ported as `capacity.construction_factor` (`CONSTRUCTION_INTEREST`, on), with spending in each year's dollars (MC_JPGDP) and half a year of carrying on each year's spend, as EPINCST does.

Also ported: ucape.f ELSTCAP's floor, ESTCPADD(AT) = max(AT, CT) and AC from CC, so the advanced types' steps never fall below CT's and CC's 5,000 MW ESTMNADD / 1.25 (first step 5 GW). It is what keeps turbines available in 2039 after years without turbine builds.

**Batteries.** The credit is not the cause. The CAP_CREDIT_LDC port (top-8-hour ratio of net load less stored energy / hoursToSell) gives 0.84 to 1.0 by region and falls as storage grows, the range EIA's DS_CAP_CREDIT lines show, and new and existing storage share it as in CALC_STORAGE_VAL,4 and 13. Batteries are built in two years only: 2027 (21.3 GW unplanned against EIA's about 3; reserve price 63 in 10 regions) and 2032 (37.5 GW against EIA's 10; reserve price 80). Both are reserve shortfalls the turbine steps cannot cover, filled from the large battery steps (17 to 39 GW, sized from the 2022-2026 battery history). 2027's comes from economic retirements (coal 6.3, CC 3.6, steam 4.4 GW in the first year); 2032's from the coal rule taking 98.5 GW of coal at once against EIA's 62, because EIA's 2028-2030 coal-to-gas cofiring (steam 110 GW in 2030 against 70 here) is not in the chain. After 2032 the LP builds no batteries. These are the retirement and conversion questions above, not a storage term.

Result, 2040 national GW (before / construction interest / plus ELSTCAP floor / EIA):

| | before | interest | interest + floor | EIA |
|---|---|---|---|---|
| CC with CCS | 491 | 456 | 453 | 431 |
| of which CCS | 52 | 28 | 45 | 52 |
| Turbines | 207 | 236 | 243 | 267 |
| Batteries | 141 | 146 | 143 | 103 |
| Solar | 343 | 343 | 343 | 323 |

2035 with both: CC 379 (EIA 357, before 399), turbines 220 (EIA 208, before 202). Turbines are now built every year (2 to 5 GW in 2033-2038, 8 in 2039). CC is still 22 GW over in 2040 and batteries 40 GW over; the battery excess is set in 2027 and 2032 by the reserve shortfalls described above.

## Coal-to-gas conversions and the retirement cap's timing (branch ecp-coal-retire)

Chain 2027-2040 from EIA's 2026 fleet (`CapacityPath(first=2027)`, groups on), main (4d5e8e5) against this branch.

**What drives the 2027 batteries is not retirements.** Year one retires 14.3 GW (coal 6.3, CC 3.6, steam 4.4), but 9.3 GW of it is in SRSE, SRCE and SRSG, at the retirement cap, where the reserve price is zero. The 11 regions priced at 56-67 $/kW-year (TRE, FRCC, MISC, MISE, MISS, NYCW, PJME, PJMW, PJMD, SRCA, RMRG) retire 0.5 GW between them. With the cap at ECP's 3% (below) retirements fall to 10.5 GW and the 2027 battery build is unchanged at 18.9 GW (EIA: 3.3 unplanned). The requirement is not it either: 941.5 GW against ECP's 944.9 (OutToNEMS_2026, rRXXXXXge.Lower, planning year 2), within 1.7 GW in every region. The gap is on the capacity side: EIA's own 2027 year-end fleet counts 948.7 GW on this LP's reserve rows against ECP's row level of 989.3 (TRE -10.4, NWPP -8.3, ISNE -3.8, PJME -3.5, CASO -3.4), and 15 regions are short by about 19 GW in all even after EIA's own 2027 builds. The same fleet-side gap is 38 GW in 2028, 19 in 2030 and 28 in 2033. Which coefficients differ (NWPP's looks like hydro above 0.70, TRE's like wind and solar credits) needs ECP's row coefficients, which the saved OutToNEMS files do not carry.

**Retirement cap timing (ported).** EP$RET puts the cap on planning year UPRTLT + 1, so ECP year E caps retirements in E + 1 at UPRETRT0 + UPRETCHG x (E - 2026) (uecp.f 1171-1178, UPRTLT = 1 from %ECONOMIC RETIRE SW%). The cap on 2027 is 3%, 4% on 2028, 6% on 2030 and off from 2031. This LP had 5% on 2027 and no cap from 2029. `max_retirement_rate` now follows ECP.

**Conversions (b1e0ace, ported).** Why it was held: on the old main the converted capacity retired in 2039 (cofiring ends 2038) and came back as combined cycle, so 2040 CC got worse. The port itself (plant-file T_NG_COST + T_NG_TRAN, from UCL_CL_NG_SYR = 2028, outside MXRET, horizon firm-capacity credit) matches what uecp.f EP$COAL,19-28 does and gets the conversion volume right. It is taken here unchanged.

Coal retirements (not counting conversions) and conversions by year, GW. EIA's 2026 is 2.7 (both chains start from it):

| | main ret | main conv | branch ret | branch conv | EIA ret | EIA conv |
|---|---|---|---|---|---|---|
| 2027 | 13.0 | 1.8 | 11.6 | 0.0 | 3.3 | 0.0 |
| 2028 | 16.3 | 0.0 | 14.4 | 27.7 | 12.2 | 4.3 |
| 2029 | 7.7 | 0.5 | 3.7 | 2.3 | 13.3 | 12.7 |
| 2030 | 1.4 | 0.0 | 1.4 | 0.0 | 3.5 | 18.9 |
| 2031 | 3.5 | 0.0 | 2.5 | 0.0 | 10.3 | 0.0 |
| 2032 | 94.2 | 0.0 | 74.9 | 0.0 | 61.6 | 0.0 |
| 2033-2035 | 0.0 | 0.0 | 0.0 | 0.0 | 0.2 | 0.0 |

The 2027 figure includes 6.8 GW of plant-file retirements, of which EIA's restart carries out only about 3. Conversions come all in 2028 (EIA spreads them over 2028-2030) and total 30 GW against EIA's 36.

National GW, main / branch / EIA:

| | 2030 | 2032 | 2040 |
|---|---|---|---|
| Coal | 116 / 95 / 88 | 18 / 18 / 16 | 18 / 15 / 16 |
| Steam | 72 / 97 / 110 | 71 / 96 / 104 | 50 / 50 / 52 |
| CC with CCS | 289 / 287 / 291 | 324 / 315 / 323 | 453 / 459 / 431 |
| Turbines | 183 / 179 / 171 | 213 / 204 / 194 | 243 / 248 / 267 |
| Batteries | 94 / 94 / 88 | 138 / 130 / 99 | 143 / 136 / 103 |
| Solar | 293 / 293 / 258 | 343 / 343 / 288 | 343 / 344 / 323 |

2032 battery builds 43.7 -> 35.3 GW (EIA 9.9); the reserve price is still 82 in 24 regions. The rule now takes 75 GW against EIA's 62, and the fleet-side reserve gap above covers the rest of the shortfall. In 2039 the converted capacity retires and is replaced with 17.7 GW of CC and 13.0 of turbines (main: 15.7 and 8.0; EIA: 19.1 and 24.5). The rate fix alone moves the 2040 numbers by under 1 GW (conversions only: CC 460, CT 248, battery 135).

Open: the capacity side of ECP's reserve row (40 GW in 2027) is what keeps the 2027 and 2032 battery builds high. Answered below without a rerun.

## The capacity side of ECP's reserve row (branch ecp-reserve-supply)

No rerun was needed. The AIMMS oracle's 2030 ECP composite input (`aimms-showreel/sample/ecp_2030_01/composite_2030.txt`, the file `ecp.ams` reads) carries every coefficient behind the row: EPECAP by type, region and planning year, EPIRCCR, DINURAL_STORAGE_CAPACITY_CREDIT, RNWFAC, UPCCR, UPPLYR. Planning year 2 rebuilt as EPECAP x coefficient (dispatchable 1, hydro RNWFAC 0.70, pumped storage UPCCR 0.70, wind and solar EPIRCCR, batteries min(DINURAL, 1)) gives 973.6 GW against the row's level of 979.9 in OutToNEMS_2030; the rest is the solve's own year-1 builds (UPPLYR is 1 for every type, so only builds decided in year 1 count on year 2). Hydro, pumped storage, nuclear, other renewables and battery coefficients agree with this model's.

Gap for 2031 (OutToNEMS_2030 planning year 2), this model on EIA's 2031 fleet less ECP, GW: wind -29.6, solar -7.8, thermal +11.4, batteries +14.5, hydro and the rest +0.3, ECP's own year-1 builds and lines -6.3; total -17.5. Wind is credit: ECP's EPIRCCR for wind is 0.19 to 0.34 (TRE 0.24, SPPS 0.31, NWPP 0.34) where this model had 0.08 to 0.27 (TRE 0.08); at ECP's credits EIA's own wind would count 34 GW more. Solar, thermal and batteries are fleet, not credit: the oracle's fleet is not EIA's restart (87 GW more solar, 11 GW less thermal, 14 GW less batteries in 2031).

Why wind differed. ECP's wind credit is the capacity factor over the net-peak hours (this model's credit with no single-plant variance is within 0.03 of ECP's on average; with the capped variance, 0.11). uecp.f 40405 caps the variance at (cap x CF / z)^2, which with wesarea.txt's sigma 0.38 and rho 0.85 binds everywhere and halves the credit. ECP's numbers show no such variance; the likely reason is that renew.f, which reads wesarea into the wwind block, is not part of the oracle build. EIA's own run points the same way: on EIA's year-end fleets and ECP's requirement, the regional shortfall is 23 / 24 / 21 / 35 / 32 GW in 2027 / 2028 / 2030 / 2032 / 2033 with the capped credit and 13 / 10 / 5 / 13 / 12 with the net-peak credit, and the wind regions (TRE, MISW, SPPS, SPPC, BASN) balance only with the latter. What is left short is MISE, NYCW, PJME, SRCE and CANO, all fleet-side.

For 2027 (OutToNEMS_2026) the 40.6 GW splits into the wind and solar credit, 20 GW (TRE 6.3, MISW 3.6, SPPS 2.3, SPPC 1.4), and fleet and ECP's own year-1 builds, about 20 (10 GW of dispatchable and 2.5 of batteries online in 2027 in that solve). NWPP's 8.3 is fleet (the oracle has 3 to 4 GW more thermal there), not hydro: ECP counts NWPP hydro at 0.70 as this model does. There is no 2026 composite to split the fleet part further.

Ported (`capacity_credit`):
- `SINGLE_SITE_VARIANCE = False`: no single-plant variance in EPIRCCR. True puts back uecp.f's formula on wesarea's sigma and rho (`wesarea()`), capped as before.
- CAP_CREDIT's net load, which picks the hours, on ECP's adjusted capacities (PV_CAP_ADJ, WN_CAP_ADJ and the rest; uecp.f 39987, 40200): the LP adds the reference run's adjustment (`cap_adjustment`, UECPOUT `*_cap_adj` less installed capacity) to its own fleet. This moves solar's hours in ISNE, NYCW and NWPP (ISNE 0.32 -> 0.07, ECP 0.06) and is worth -2 GW nationally in 2027.

Chain 2027-2040 from EIA's 2026 fleet, before (main 667cc9b) / after / EIA, GW:

| | before | after | EIA |
|---|---|---|---|
| 2040 CC with CCS | 459 | 449 | 431 |
| 2040 turbines | 248 | 219 | 267 |
| 2040 batteries | 136 | 123 | 103 |
| 2040 solar | 344 | 343 | 323 |
| 2040 wind | 338 | 395 | 404 |
| 2040 coal | 15 | 14 | 16 |
| 2040 steam | 50 | 44 | 52 |
| 2027 battery builds | 18.9 | 13.6 | about 3 |
| 2032 battery builds | 35.3 | 28.8 | 9.9 |
| 2027 reserve price, median (regions over 50) | 24 (11) | 16 (5) | |
| 2032 reserve price, median (regions over 50) | 82 (24) | 82 (24) | |

Wind lands on EIA, batteries and CC move toward it, turbines move away (turbine builds 2027-2040 fall from 102 to 76 GW: firm wind takes reserve need the turbines filled). Economic retirements in 2027 rise from 10.6 to 19.3 GW, still under the 3% cap. 2032 is still a reserve shortfall at the coal rule (64 GW of coal leaves that year), so the battery spike there is now the coal question, not the credit.

Pinned by `tests/test_emm_capacity.py` (`test_intermittent_credit_is_net_peak_capacity_factor`, `test_wesarea_inputs`, `test_intermittent_credit_matches_ecp_2030`: credits on EIA's 2030 fleet within 0.04 of ECP's EPIRCCR on average). Scripts: scratchpad `ecprs/` (otn.py parses OutToNEMS, comp.py and ecprow.py rebuild the row from the composite, cmp_row.py and short.py do the comparisons).

## Does ECP anticipate the 2032 coal cliff? (branch ecp-lookahead)

No. Read from `uecp.f` and the input:
- Planning year k of ECP year E is calendar year E + k - 1 (EP$MRM writes CURIYR + YEAR - 1). The reserve row binds only for YEAR > UPPLYR(WICT) = 1, so years 2 and 3; year 1 is a free row and has no builds or retirements of its own (retirement columns start at YEAR > UPRTLT = 1).
- Build columns exist for planning years 1 and 2 only (EP$ELAST: YEAR + UPPLYR <= UNXPH) and come online in YEAR + UPPLYR. UPPLYR is 1 for every type in COSTPERF (pinned by `test_ecp_commits_every_type_one_year_ahead`); UPCLYR (CC 3, CT 2, battery 1) only sets the cost profile (EPINCST) and the first available year. So ECP has no lead-time advantage for batteries: a CC chosen in E is online in E + 1 like a battery.
- Only year-1 builds are carried out (EPO$BILD, FULLYR = year + UPPLYR). Year-2 builds serve the tail (year 3, the present-value average of the peaks of years 3 to 30, udat.f 14362-14382) and their steps are unbounded ("LET YEAR 3 ELASTICITY BE UNBOUNDED", PV_LIM 999.99), so the tail can always fill a future gap at first-step cost and nothing pushes ECP to build before the gap year.

So this LP's step(y), builds online in y and held to y's requirement, is ECP's year 2 of its E = y - 1 solve; the only piece it lacks is the tail. The oracle's own ECP (oracle-cache OutToNEMS_YYYY, cB_DSP and cIX levels by planning year, rRXXXXXge shadow price) confirms it does not prebuild:

| ECP solve (online year) | AC | CC | AT | CS | DS | year-2 reserve dual, median |
|---|---|---|---|---|---|---|
| 2029 (2030) | 7.8 | 0 | 12.5 | 1.2 | 0 | 83 |
| 2030 (2031) | 9.8 | 0 | 1.3 | 1.6 | 0 | 37 |
| 2031 (2032) | 14.7 | 5.0 | 21.2 | 3.1 | 2.4 | 522 |
| 2032 (2033) | 2.7 | 0 | 1.0 | 3.9 | 1.0 | 79 |

The cliff is met in the year itself, at a reserve price 14 times the year before. EIA's cb2026 does the same: capacity added in 2032 is CC +24.8, CT +17.9, batteries +9.9 GW, against 4.6 to 11.0 (CC) and 2.9 to 6.0 (CT) a year in 2028-2031.

Tested on the 2027-2040 planner chain from EIA's 2026 fleet (GW; builds are the LP's own, EIA's are capacity changes):

| | 2028 | 2029 | 2030 | 2031 | 2032 | 2033 |
|---|---|---|---|---|---|---|
| CC builds, main / EIA | 8.0 / 4.6 | 7.5 / 11.0 | 9.4 / 6.0 | 10.3 / 7.4 | 20.6 / 24.8 | 21.4 / 10.8 |
| CT builds, main / EIA | 7.7 / 5.6 | 6.0 / 2.9 | 2.2 / 4.3 | 2.2 / 6.0 | 12.7 / 17.9 | 3.6 / 3.5 |
| battery builds, main / EIA | 0.3 / 3.6 | 0.0 / 3.3 | 0.0 / 2.8 | 0.0 / 0.7 | 28.8 / 9.9 | 1.4 / 0.7 |
| CC / CT / battery builds, HORIZON | 8.0 / 16.5 / 19.8 | 17.0 / 27.9 / 49.8 | 21.3 / 34.8 / 0.0 | | | |

The main path's 2028-2031 builds are already in EIA's range; the 2032 miss is the mix (28.8 GW of batteries where EIA adds 43 GW of gas), not the timing. HORIZON (next year plus a tail 10 years out, CC, wind and CCS for later periods chosen now) is far off and was stopped after 2030: 54.5 GW of batteries in 2027, coal down to 19 GW in 2028 (EIA 137), turbines 236 GW in 2030 (EIA 171), reserve price zero. It took 125 to 269 s a year against 25 to 33 s (59 s in 2032) for the one-year LP. No lookahead change is justified; HORIZON stays off.

What does set the 2032 mix is what each type can add in one year. In the chain's 2032 solve the LP fills both cheaper battery steps (17.7 / 10.6 / 14.1 GW, built 28.8) and combined cycle's (11.9 / 7.1 / 9.5 GW, built 19.0), and turbines up into their third (6.7 / 4.0 / 5.4, built 12.7): at the 2032 storage credit a battery's 1.38 x step is cheaper per firm kW than gas's 2.25 x step. One ECP structure the LP lacks was tried and dropped: ECP has a second combined cycle type, CC, beside AC (same heat rate, UPOVR 465 vs 441, its own ESTCPLIM steps of about 5 / 3 / 4 GW; the oracle builds it only in its 2031 and 2038 solves, 5.0 GW each). Ported as extra steps on the CC build group, the 2032 battery build stayed at 28.2 GW and the new CC displaced turbines (2032 CT builds 12.7 -> 9.5); 2040 CC 449 -> 455 and CT 219 -> 214 (EIA 431, 267), batteries 123 -> 120, solar 343 -> 332, wind 395 -> 410, 2032 reserve price 82 -> 60 in 24 -> 23 regions. Worse on the two gas types, so not committed. Next lever: battery cost, credit and step size in 2032 (the battery steps are sized from 2027's 23.5 GW of additions, 13.6 GW of them the LP's own builds against EIA's about 3), not the horizon.

## Why 2027 builds batteries, and ECP's battery build columns (branch ecp-battery-2027)

**Retirements are not the cause.** On main, the 2027 step from EIA's 2026 fleet retires 19.3 GW (coal 8.4, steam 7.1, CC 2.5, CT 1.3), against EIA's fleet changes of coal -3.3 and steam -6.6 GW. But the regions that take the 13.6 GW of batteries (MISC 4.1, PJME 3.6, MISE 2.7, PJMD 2.4, NYCW 0.7) retire nothing; the retirements sit in SRSE, SRCE, SRSG, MISW, ISNE and NWPP, where the reserve price is zero. The retirement overshoot is the coal-timing question above, not a battery driver.

**The mix is.** ECP's 2026 solve (OutToNEMS_2026, year-1 columns) builds 8.0 GW of AT, its first two steps of 5 + 3 GW, and 2.5 GW of batteries. The LP built AT's first step only (5.0) and then batteries, because it gave batteries three national steps of 16.9 / 16.1 / 21.5 GW with no regional limit. ECP does not. uecp.f CALC_STORAGE_VAL,11-12 writes one battery column per region, in the step-1 elasticity row only (IS = 1, row LUDSST1), and bounds it at MAX(ENERGY_STORED, BATTERY_USED) of ReStore's test battery. That test battery is BatteryIncrement = MAX_PERCENT x MAX_LOAD (uecp.f 37838-37896): 1% of the region's top hourly load (DUCK_SYSTEM_LOAD + DEM_ADJ, uecp.f 860) in 2017, a point a year more, 5% from 2021 (emmcntl.txt %DS PARAMS%). Rebuilt from this model's LDSM load, firm contracts and UCAPADJ for 2026, 5% of MAX_LOAD reproduces ECP's coeff_cIX_UBOUND to 0.001 GW in 19 of 25 regions (TRE 4.754, MISE 1.002, PJMW 2.914). In the rest ReStore used less of it: PJME 0.74, NYUP 0.88, PJMD 0.99 of it, and none in SRSG, CANO, CASO, NWPP and BASN. The same holds in the 2028, 2031, 2035 and 2040 solves (national bound 36 to 48 GW).

Ported (`capacity.ECP_STORAGE_BUILDS`, on): batteries get only the first build step (ESTCPLIM step 1 less planned), and each region's battery build is at most `battery_build_limit` = `battery_increment_share(year - 1)` x MAX_LOAD of year - 1 (the ECP solve whose year-1 builds come online in the year). ReStore's own use of the test battery is not ported, so the bound is the whole increment; that is looser than ECP's in the West and in PJME.

One step 2027 from EIA's 2026 fleet: batteries 13.6 -> 10.8 GW, turbines 5.0 -> 7.7 (ECP 8.0, EIA's 2027 turbine fleet +9.1), reserve price over 50 in 7 regions (was 5). Batteries are still above EIA's about 3.3 unplanned: the regional limits bind in MISC, MISE, PJMD and NYCW, and the rest goes to MISS, PJMW and SRCA. What is left is the fleet-side reserve gap in the east (MISE, NYCW, PJME) found above, not a storage term.

Chain 2027-2040 from EIA's 2026 fleet, before (main dcba9b6) / after / EIA, GW:

| | before | after | EIA |
|---|---|---|---|
| 2040 CC with CCS | 449 | 457 | 431 |
| 2040 turbines | 219 | 229 | 267 |
| 2040 batteries | 123 | 106 | 103 |
| 2040 solar | 343 | 343 | 323 |
| 2040 wind | 395 | 392 | 404 |
| 2040 coal | 14 | 14 | 16 |

Builds by year, CC (with CCS) / CT / batteries; EIA's are capacity changes:

| | 2027 | 2028 | 2029 | 2030 | 2031 | 2032 | 2033 |
|---|---|---|---|---|---|---|---|
| before | 0 / 5.0 / 13.6 | 8.0 / 7.7 / 0.3 | 7.5 / 6.0 / 0 | 9.4 / 2.2 / 0 | 10.3 / 2.2 / 0 | 20.6 / 12.7 / 28.8 | 21.4 / 3.6 / 1.4 |
| after | 0 / 7.7 / 10.8 | 8.0 / 8.4 / 0 | 7.3 / 5.6 / 0 | 9.2 / 2.4 / 0 | 10.1 / 2.2 / 0.1 | 29.4 / 17.5 / 15.6 | 20.2 / 4.4 / 0.8 |
| EIA | 0.2 / 9.1 / 13.2 (3.3 unplanned) | 4.6 / 5.6 / 3.6 | 11.0 / 2.9 / 3.3 | 6.0 / 4.3 / 2.8 | 7.4 / 6.0 / 0.7 | 24.8 / 17.9 / 9.9 | 10.8 / 3.5 / 0.7 |

2032 now builds turbines at EIA's level (17.5 vs 17.9) and batteries at 15.6 (EIA 9.9) instead of 28.8; the step that took them, battery step 2 at 1.38 x, does not exist in ECP. The firm need the batteries no longer fill goes to CC (29.4 vs EIA 24.8), so 2040 CC is 8 GW further from EIA while turbines and batteries move toward it. 2027 economic retirements are unchanged (19.3 GW). The 2032 reserve price rises (median 82 -> 98) since the coal rule's shortfall is now met from dearer gas steps.

Pinned by `tests/test_emm_capacity.py` (`test_battery_increment_share_follows_ds_params`, `test_battery_build_limit_matches_ecp_2026`, `test_batteries_build_in_the_first_step_only`). Scripts: scratchpad `b27/` (dsbound.py compares the bounds, one27.py the 2027 step, chain.py the chain).

## Why gas builds tilt to CC over turbines (branch ecp-gas-split)

**The value split in ECP's own matrix.** ECP's 2030 solve (OutToNEMS_2030; year-1, step-1 build columns, online 2031) gives each column's cost (NomCoeff) and reduced cost. Its value is NomCoeff less the reduced cost; take off the reserve rows of planning years 2 and 3 (rRXXXXXge, coefficient 1) and the step row (rLUle), and what is left is the column's operating value. As shares of AT's cost, region medians: AC costs 0.267 more than AT; AC's operating value is 0.414, AT's 0.130, so AC's edge over AT is 0.272. AC and AT tie (edge over cost gap 1.03, both reduced costs near zero), and the split is set by AC's first build step, which binds (9.8 GW). The same holds in every ECP solve from 2029 to 2039 (edge over cost gap 0.94 to 1.07, cost ratio 1.26 to 1.29).

**This LP for 2031** (one step from EIA's 2030 fleet; operating value from the LP's own prices, 1 GW dispatched greedily under its outage rate and the EPA 111 40% cap): the cost gap is 0.269, matching ECP's. CC's edge is 0.329, and the turbine's own value is 0.009 against ECP's 0.130. CC therefore wins by 1.23 x its cost gap (median) where ECP ties, which gives CC the reserve-driven builds.

**What ECP's turbine earns that this LP does not.** The turbine's operating value tracks the spinning reserve duals (rRSRge, years 2 and 3) region by region, with correlation 0.99 (CASO excluded) and a median of 0.62 of the dual sum. CC's edge over AT is uncorrelated with them (0.04). Spinning reserve (EP$MRM,8-13: 10% of load plus 30% of the gap to the season peak; EP$ODSP,34-52: headroom of dispatched units, with min-load and max-load modes) pays both gas types about alike, so it is not what separates them, and this LP has no such row. It is not ported. It is a structural block that would also change how batteries, hydro and wind are valued, and it needs its own lane.

**The heat rate (ported).** ECP builds dispatchable plants at UPHTRT (uecp.f 37458-37478). That is the first-of-a-kind UPPHRT0 unless UPDHRSW > 1 (ucape.f 625-641; udat.f 5350, 13991), and every type in ecpdaty.xlsx has UPDHRSW = 1. The LP and the dispatch case used the nth-of-a-kind UPPHRTN instead. For combined cycle, CCS and steam the two are the same. For the advanced turbine UPPHRTN is 9,905 Btu/kWh against UPPHRT0's 9,142, and ECP's composite input carries UPHTRT(AT) = 9142. The new `technology.new_heat_rate` follows the Fortran rule, and `capacity.solve_year` and `dispatch.build_case` use it. With it, CC's 2031 edge falls to 0.309 and the margin to 1.14 x the cost gap. What is left (about 0.04 of AT's cost, 1.4 $/kW-year) is not traced to an input; cost inputs (UPOVR, multipliers, FOM, VOM, UPFORT, UPMCF, EPA 111 cap) match the composite.

Chain 2027-2040 from EIA's 2026 fleet, before (main 224fce0) / after / EIA, 2040 GW:

| | before | after | EIA |
|---|---|---|---|
| CC with CCS | 457 | 442 | 431 |
| Turbines | 229 | 239 | 267 |
| Batteries | 106 | 106 | 103 |
| Solar | 343 | 343 | 323 |
| Wind | 392 | 405 | 404 |
| Coal | 14 | 14 | 16 |

Builds, CC (with CCS) / CT / batteries, before -> after (EIA's are capacity changes):

| | 2027 | 2028 | 2029 | 2030 | 2031 | 2032 | 2033 | 2034 | 2035 |
|---|---|---|---|---|---|---|---|---|---|
| CC | 0 -> 0 | 8.0 -> 8.0 | 7.3 -> 6.9 | 9.2 -> 9.0 | 10.1 -> 9.5 | 29.4 -> 27.7 | 20.2 -> 18.6 | 11.6 -> 11.9 | 11.8 -> 11.9 |
| CT | 7.7 -> 7.7 | 8.4 -> 8.4 | 5.6 -> 6.3 | 2.4 -> 2.6 | 2.2 -> 2.9 | 17.5 -> 17.6 | 4.4 -> 4.8 | 3.9 -> 4.7 | 5.1 -> 5.7 |
| battery | 10.8 -> 10.8 | 0 -> 0 | 0 -> 0 | 0 -> 0 | 0.1 -> 0 | 15.6 -> 15.6 | 0.8 -> 1.1 | 0 -> 0.3 | 0 -> 0.1 |
| EIA CC / CT / battery | 0.2 / 9.1 / 13.2 | 4.6 / 5.6 / 3.6 | 11.0 / 2.9 / 3.3 | 6.0 / 4.3 / 2.8 | 7.4 / 6.0 / 0.7 | 24.8 / 17.9 / 9.9 | 10.8 / 3.5 / 0.7 | | |

Turbine builds in 2036-2039 rise from 22.1 to 28.7 GW and the 2039 reserve price drops from 76 to 53. The 2033 CC excess (18.6 against 10.8) is mostly firm capacity the chain lacks, not the mix: steam is 87 GW against EIA's 103 from 2031 (the retirement and conversion question above) and wind 240 against 296. ECP's own 2032 solve builds only 2.7 GW of AC and 1.0 of AT for 2033.

Pinned by `tests/test_emm_capacity.py::test_new_gas_heat_rates_are_ecp_uphtrt`. Scripts: scratchpad `gas/` (ecpval.py and ecpyears.py split ECP's columns, ourval2.py and energy.py do the LP's side, chain.py runs the chain).

## Existing plants are kept for ECP's whole horizon (branch ecp-retire-fleet)

**What ECP retires.** Almost nothing. Summed over every oracle ECP solve from 2026 to 2049 (OutToNEMS_YYYY), economic retirements of combined cycle, oil and gas steam and turbines are 2.5 GW in all: EC 0.45 and ST 0.56 GW in the 2026 solve, ST 0.5 in 2027, under 0.5 a year after that, ET 0.3 once (2049). EIA's own restart agrees: beyond the plant file's dated changes, CC and CT never lose capacity in 2027-2040, and steam loses 2.7 GW in 2027 and 4.3 in 2031. The chain on main retired CC 8.2, CT 4.3 and steam 15.2 GW (plus 2.9 GW of converted coal) in 2027-2033. That is the 16 GW steam gap from 2031.

**Why.** EC and ST are not retirement-group columns in ECP. EP$BDSP skips them ("Existing NGBS ... now Modeled in EP$NGBS", uecp.f 15114) and EP$NGBS (uecp.f 36045-36680) writes three options per gas plant group: run period 1 only (this is the one that retires it, EPO$NGBS), periods 1-2, or the whole UNFPH horizon, each costing ENG_FOM (FOM + G&A + capital additions + age adder, udat.f 9601; no hurdle) for the years it covers, and each counting on the reserve rows of the years it covers. Turbines are retirement-group columns whose cost is EPGFOM's present value over the horizon (EP$BDSP,8). Either way the decision is over 30 years, and the tail year's reserve row binds in 21 of 25 regions (OutToNEMS_2026 year-3 duals; zero only in BASN, NWPP, RMRG and SRSG). EPO$NGBS also retires a group only if every option past period 1 is empty, and then only units with ENG_RVAL of zero or less.

Lined up from ECP's 2030 solve (composite GRP_FOM, OutToNEMS cE NomCoeff and reduced costs; value of keeping = cost of option 3 less option 1 plus option 1's reduced cost, levelized over the horizon), 1987$/kW-year:

| | keep cost | value of keeping | ratio, region range |
|---|---|---|---|
| ST, 54 GW | 13.4 | 33.7 | 0.9 (SRSG) to 5.8 |
| EC, 281 GW | 7.5 | 69.9 | 3.1 to 39 |
| ET (cEXX0, present values) | 75 | 1,301 | 4.2 to 34 |

Steam is worth about 34 a year kept, roughly a new turbine's annual cost (37 to 41 here); the energy margin alone covers far less. A one-year LP sees only this year's reserve price, which was zero in SRSE, SRCE, SRSG, MISW, ISNE and NWPP in 2027, and retires there.

**Ported** (`capacity.RETIRE_HORIZON`, on, one-year LP only): retiring a GW of gas_cc, gas_ct, steam, gas_conv or coal also gives up its firm capacity in the rest of the horizon. `retirement_tail_value` charges the retirement column, for each later year the plant could still run, a new turbine's annual cost less the plant's own keep cost (its retirement group's cost), never below zero, discounted at the year's rate. Converted coal counts only to UEPA_CLCFYR (2038), coal only to 2031 (the 2032 rule; EP$COAL's commit vectors also run to the end of the horizon). A plant whose keep cost exceeds a new turbine's still retires. The 2027 step from EIA's 2026 fleet retires coal 12.7 GW without coal in the groups and 5.0 with it (main 8.4), so coal is in.

Chain 2027-2040 from EIA's 2026 fleet, before (main fc685d8) / after / EIA, GW:

| 2040 | before | after | EIA |
|---|---|---|---|
| CC with CCS | 442 | 435 | 431 |
| Turbines | 239 | 234 | 267 |
| Batteries | 106 | 108 | 103 |
| Solar | 343 | 348 | 323 |
| Wind | 405 | 383 | 404 |
| Coal | 14 | 15 | 16 |
| Steam | 45 | 56 | 52 |

Economic retirements by year, before -> after (EIA: change beyond the plant file's dates; coal's includes conversions out):

| | 2027 | 2028 | 2029 | 2030 | 2031 | 2032 | 2033 |
|---|---|---|---|---|---|---|---|
| coal | 8.4 -> 5.0 | 6.8 -> 3.8 | 1.3 -> 1.7 | 0.5 -> 0.3 | 0 -> 0 | rule | 0 |
| steam | 7.1 -> 2.6 | 2.7 -> 0 | 1.5 -> 0.3 | 1.4 -> 0.3 | 0 | 0 | 2.5 -> 0 |
| CC | 2.5 -> 0 | 3.7 -> 0 | 1.5 -> 0 | 0.1 -> 0 | 0 | 0.2 -> 0 | 0.2 -> 0.1 |
| CT | 1.3 -> 0.1 | 1.8 -> 0 | 1.2 -> 0 | 0 | 0 | 0 | 0 |
| EIA steam / CC / CT | -2.7 / 0 / +7.9 | +2.7 / +4.6 / +6.1 | | | -4.3 / +6.3 / +6.6 | | |

Steam (with converted coal) and wind by year, before / after / EIA:

| | 2028 | 2029 | 2030 | 2031 | 2032 | 2033 | 2034 | 2035 |
|---|---|---|---|---|---|---|---|---|
| steam | 99 / 110 / 82 | 94 / 110 / 92 | 92 / 108 / 110 | 91 / 107 / 104 | 91 / 107 / 104 | 88 / 106 / 103 | 86 / 105 / 102 | 84 / 104 / 101 |
| wind | 187 / 187 / 178 | 202 / 202 / 193 | 204 / 204 / 212 | 206 / 205 / 234 | 225 / 229 / 262 | 248 / 242 / 296 | 269 / 263 / 330 | 294 / 286 / 344 |

CC / CT builds, before -> after (EIA's are capacity changes):

| | 2027 | 2028 | 2029 | 2030 | 2031 | 2032 | 2033 | 2034 | 2035 |
|---|---|---|---|---|---|---|---|---|---|
| CC | 0 -> 0 | 8.0 -> 8.0 | 6.9 -> 3.6 | 9.0 -> 5.9 | 9.5 -> 4.5 | 27.7 -> 19.3 | 18.6 -> 17.7 | 11.9 -> 9.5 | 11.9 -> 10.8 |
| CT | 7.7 -> 7.3 | 8.4 -> 6.0 | 6.3 -> 5.4 | 2.6 -> 1.4 | 2.9 -> 3.8 | 17.6 -> 15.3 | 4.8 -> 3.8 | 4.7 -> 5.2 | 5.7 -> 5.3 |
| EIA CC / CT | 0.2 / 9.1 | 4.6 / 5.6 | 11.0 / 2.9 | 6.0 / 4.3 | 7.4 / 6.0 | 24.8 / 17.9 | 10.8 / 3.5 | 9.2 / 4.1 | 13.6 / 5.5 |

Steam from 2031 is now within 3 GW of EIA (was 13 to 17 under), CC within 9 GW through 2035, and the 2032-2033 CC excess is gone (19.3 / 17.7 against 24.8 / 10.8). Steam is 28 GW over in 2028-2029: the conversions still come all in 2028 (30.7 GW against EIA's 4.3, then 12.7 and 18.9), an existing timing gap that kept retirements no longer hide.

**Wind is a build-timing gap, not retirements or repowering.** EIA's wind beyond the plant file's dates never falls (no economic wind retirements or repowering losses in 2027-2040); ECP itself retires some wind groups (cEXX0_INT: 7.5 GW in the 2026 solve, 3.3 in 2027, then under 1.5 a year), which would widen the gap, not close it. The gap opens when the PTC ends: wind's annual cost goes from 39.6 (2029) to 75.3 $/kW-year (2030, UPGSUBYR 16.5 -> 0), and the one-year LP builds 0 and 0.8 GW in 2030-2031 where EIA adds 17.4 and 22.0. ECP builds that wind for its tail year (post-2032 prices, no coal); this LP sees only the year it builds for. Its wind build steps then start low. With more firm capacity kept the reserve price falls and wind builds drop a little more (2040 wind 405 -> 383). No Fortran-justified fix short of the horizon was found; HORIZON stays off (see the lookahead section).

Pinned by `tests/test_emm_capacity.py::test_retirement_tail_value_is_the_avoided_replacement_over_ecp_horizon`. Scripts: scratchpad `ret/` (ngbs.py reads ECP's retirements from OutToNEMS, lineup.py the 2030 keep cost and value, eia_resid.py EIA's changes beyond the plant file, chain.py the chain).

## How ECP values a wind build, and why a tail credit is not the fix (branch ecp-build-tail)

**What the build column holds.** ecp.ams Calculate_INTBLDCOSTS: a build column's cost (ECPCOSTS) is the annual capital and fixed charge paid from the year it comes online to the end of UNFPH, in present value (OBJVAL = annual / CRF over UNFPH - OLYEAR + 1 years x PWF(OLYEAR), plus PVFOM, less PVSOM for the PTC). Its value is its coefficients in the load rows (UPICFC1, EP$INT,49) and reserve rows (EPIRCCR, EP$INT,41) of every planning year from the one it comes online in: a year-1 column (online E + 1) sits in years 2 and 3, a year-2 column (online E + 2) in year 3 only, and year 3 carries the present value of years 3 to 30.

**The tail cancels.** Year-2 wind columns are unbounded (rLUle step 1, year 2: 999.99) and the tail builds a lot of them (oracle OutToNEMS, GW of WN, year 1 / year 2: 2029 solve 18.0 / 180.8, 2030 23.6 / 152.3, 2031 30.2 / 143.9, 2032 37.7 / 116.5). So the tail's value of wind is held at its cost (year-2 column value over cost 0.98 to 1.00, region median, every solve 2029-2033), and a year-1 column gets nothing from the tail that a year-2 column does not also get. What decides a year-1 build is planning year 2 alone: V2 = (Nom1 - RC1) - (Nom2 - RC2) against the cost of being online one year earlier, dC = Nom1 - Nom2 (about one annual charge, 0.066 of Nom1). V2 / dC is 0.91, 1.00, 1.00, 1.00, 1.00 (median) in the 2029-2033 solves: year-1 wind is built until its one year of value equals one year of cost, and then up to its step-1 bound (19.3, 24.1, 30.2, 37.7, 47.1 GW; binding in the 2029, 2031 and 2032 solves). In TRE the 2030 solve's V2 of 171.4 rebuilds from the rows as 167.1 energy (UPICFC1 x rLEL2ge, year 2) plus 7.2 reserve. That is this LP's own test, so a tail credit on build columns (retirement_tail_value's analogue) is not faithful: it would pay year-1 builds for value ECP gives equally to the year after.

**Where the gap is.** One year's value. Costs match (wind over turbine cost: ECP 1.88 / 1.90 / 1.92 / 1.92 for plants online 2030-2033, this LP 1.87 / 1.91 / 1.93 / 1.99). This LP's wind value over cost (energy at its own prices on the new-build profile plus reserve price x credit), region median and best region: 2030 0.75 / 0.91, 2031 0.82 / 1.00, 2033 0.83 / 1.00, so it builds 0, 0.8 and 13.2 GW where ECP is at break-even and step-bound. One input differs: ECP's UPICFC1 for a new plant is WRENEW's capacity factor for CURIYR - 1 with no forced-outage derate (uecp.f 38880-39035; the 2030 solve's hour-weighted UPICFC1 is 0.399 / 0.354 / 0.443 for wind and 0.327 / 0.250 / 0.308 for solar in TRE, MISC and SPPS, WRENEW 2029 to 0.001), where this LP's build profile is WRENEW of the year times (1 - UP_XFOR 0.088), 7.5% less. But ECP's other rows take that back: in SPPC, SPPS and FRCC the year-2 load and reserve rows give 188 / 187 / 206 against V2 of 152 / 148 / 174, the rest being negative rows this LP lacks (spinning reserve: rRSRge, where intermittents carry -SR_INT x UPICFC1). Porting the capacity factor alone (tried, not committed) moves the wind builds forward and then runs away: 2028-2029 wind builds 19.1 / 25.5 GW (EIA +15.4 in 2029), 2030-2031 still 0 / 1.7, then 34 to 59 GW a year from 2033, 2040 wind 610 against EIA's 404 and CC 399 against 431. Wind sits on a knife edge at about its cost from 2030, so a one-sided coefficient change swings the path. No wind fix is justified here; the next step is the spinning reserve block (also flagged in the gas-split section), which has to come in with ECP's UPICFC1 as one change.

Scripts: scratchpad `bt/` (windyears.py and split.py read ECP's WN columns 2026-2033, ecpwind2030.py rebuilds the 2030 solve's year-2 value and UPICFC1, windval.py the LP's wind value by region, chain.py the chain).

## When ECP converts coal to gas (branch ecp-build-tail, off)

**ECP's rule.** ecp.ams Calculate_CL_NNGCOSTS (EP$COAL,19-28): conversion columns cNNG exist only for planning years 2 and 3 (`ord(PlanYear) > 1`; emmcntl %CL RET VN% UCL_VIN is 0 / 1 / 2, so year 1 cannot change), and with EPA 111 on only while E + PlanYear - 1 <= UEPA_GSYR (OV_CLtNG = 0 past it, 2030). Year 2 (online E + 1) is the one carried out; year 3 is the tail. Both columns put the unit in every later reserve row, so the horizon's firm value is the same for both and cancels: a conversion online in E + 1 has to pay for itself in that year, unless no tail column exists (E + 2 > 2030). In this LP's years: no horizon credit in 2028 and 2029, the full credit in 2030. The old port gave the credit from 2028, hence 30.7 GW in 2028 against EIA's 4.3, 12.7 and 18.9 in 2028-2030. There is no annual cap, lead-time bound or step on conversions in EP$COAL.

**Ported, off** (`capacity.ECP_CONVERT_TIMING`, `conversion_is_last_chance`). Chain 2027-2040 from EIA's 2026 fleet, main (f977370) / on / EIA, GW:

| | 2028 | 2029 | 2030 | 2031 | 2033 | 2035 |
|---|---|---|---|---|---|---|
| conversions | 30.7 / 0 / 4.3 | 2.7 / 0 / 12.7 | 0 / 12.4 / 18.9 | 0 / 0 / 0 | | |
| steam | 110 / 79 / 82 | 110 / 76 / 92 | 108 / 88 / 110 | 107 / 86 / 104 | 106 / 85 / 103 | 104 / 83 / 101 |
| coal | 99 / 130 / 137 | 91 / 121 / 111 | 90 / 107 / 88 | 87 / 102 | | |

2040 on: CC 437, CT 231, batteries 109, solar 373, wind 388, coal 18, steam 56 (main 435 / 234 / 108 / 348 / 383 / 15 / 56). The timing is ECP's and 2028-2029 steam lands on EIA's, but the volume is a third of EIA's: 2028-2029 convert nothing on one-year economics where EIA converts 17 GW, and in 2030, with the credit, only PJMW (10.3) and PJMD (2.1) convert; TRE, MISW, MISE, SRSE and SPPC (7 to 12 GW eligible each) do not. Steam is then 16 to 22 GW under EIA's from 2030, and the 2032 reserve price rises (median 154 -> 197), which builds 80 GW of solar that year (main 54). Left off until the one-year conversion economics (cofiring fuel before UEPA_GSYR, udat.f 6457 applies the 60% coal share only from it; the converted unit's own keep value to UEPA_CLCFYR) are found.

Pinned by `tests/test_emm_capacity.py::test_conversion_credit_only_when_no_later_conversion_column`. Scripts: scratchpad `bt/` (conv30.py, chain.py).

## ECP's spinning reserve rows and its wind build capacity factor (branch ecp-spin-reserve, off)

**What ECP does.** uecp.f EP$MRM,8-13 writes one row per region, ECP load slice and planning year (rRSRge: 25 regions x 9 slices x 3 years, 675 rows in the 2030 solve). Each row is spinning reserve >= cSR, and cSR is bounded below by SR_RQMT_HGHT x (slice height + ADJ_HGHT) + SR_RQMT_DIFF x (the season's peak slice - that height), 0.1 and 0.3 in every region (composite_2030). The slices are LDSM's (DSMLCP): three seasons (winter Dec-Mar, summer Jun-Sep, shoulder), each cut at 1% / 49% / 50% of its hours sorted by net load (NL_SLICE_SW), each slice at the average load of its hours. Supply (SR_CREDIT 1 for every dispatchable type): a dispatched unit's headroom, with ECP's dispatch modes letting a committed unit run down to SR_MIN_CF of its capacity (ecpdaty.xlsx SPNRSV: coal and steam 0.3, combined cycle 0.2, turbines and pumped storage 0.1); nuclear and other renewables their capacity less output; batteries ReStore's StoSR. Conventional hydro carries none (ecp.ams leaves WIHY out of EP$ORNW,113-116). Wind and solar carry -SR_INT x their output (0.25, EP$INT,8/23/52). SR_TRAN_CREDIT is 0, so no reserve over the links. EFD has its own spinning reserve rows too (uefd.f 11473, SR_INT_REQ), which the dispatch model lacks; not needed for this change, since the capacity LP carries its own dispatch.

**Ported** (`capacity.SPIN_RESERVE`, `ECP_BUILD_CF`, both off): rows per region and 3-hour block of the 36 typical days (7,200 for a year). Each block takes the requirement of the ECP slice its hours fall in (`ecp_slice_heights`, `spin_requirement`, on LDSM's load sliced by net load on the restart's intermittent capacity, plus firm contracts as ADJ_HGHT). Per thermal group, reserve <= capacity - output and reserve <= output x (1 / SR_MIN_CF - 1); pumped storage the same on discharge; batteries their discharge headroom up to one hour of stored energy. ECP_BUILD_CF values new wind and solar at WRENEW's profile of year - 2 (ECP's y - 1 solve's CURIYR - 1) without the outage derate, in dispatch and the PTC.

Lined up against ECP's 2030 solve, planning year 2 (2031): slice heights within 0.6% of EPHGHT on average, hour-weighted requirement 101.2 GW against ECP's 100.5 (cSR lower bounds), every region within 0.2 GW. The prices are not: the sum of the year-2 duals by region has a median of 19.5 $/kW-year in ECP (NWPP 119, NYCW 43, most regions 10 to 30) and 2.3 here on EIA's 2030 fleet (NWPP 9, SPPC 15, MISW 12, eight regions under 1). Per-block commitment in typical days is looser than ECP's seasonal dispatch modes over 9 slices, so idle headroom is close to free here. Pooling the groups by SR_MIN_CF (faster, 72 s) makes it freer still (median 0.2), so it was dropped.

One step 2031 from EIA's 2030 fleet, GW built (CC with CCS / CT / wind / batteries): off 10.5 / 2.9 / 7.3 / 0.3; spin only 9.9 / 2.7 / 4.2 / 1.2; both 9.6 / 3.0 / 17.0 / 1.2. The reserve does not move turbines; the capacity factor moves wind.

Chain 2027-2040 from EIA's 2026 fleet with both on, before (main) / after / EIA, 2040 GW: CC 435 / 406 / 431, CT 234 / 242 / 267, batteries 108 / 113 / 103, solar 348 / 344 / 323, wind 383 / 591 / 404, coal 15 / 15 / 16, steam 56 / 56 / 52. Wind by year, 2028-2035: before 187, 202, 204, 205, 229, 242, 263, 286; after 194, 219, 220, 222, 256, 300, 331, 364; EIA 178, 193, 212, 234, 262, 296, 330, 344. CC builds 2027-2035 after: 0, 7.4, 2.5, 4.9, 3.9, 17.8, 12.7, 10.2, 10.2 (before 0, 8.0, 3.6, 5.9, 4.5, 19.3, 17.7, 9.5, 10.8; EIA 0.2, 4.6, 11.0, 6.0, 7.4, 24.8, 10.8, 9.2, 13.6). CT: 7.4, 5.5, 4.8, 2.1, 3.9, 15.4, 3.2, 3.1, 6.2 (before 7.3, 6.0, 5.4, 1.4, 3.8, 15.3, 3.8, 5.2, 5.3; EIA 9.1, 5.6, 2.9, 4.3, 6.0, 17.9, 3.5, 4.1, 5.5). Runtime 150 to 380 s a year (before 13 to 48). The median regional spinning reserve dual sum stays at 0.8 to 1.9 $/kW-year all chain long.

Wind tracks EIA through 2035 but runs away after it, as with the capacity factor alone (610 in the wind lane): the reserve rows take back too little of the value. CC ends 25 GW under EIA (was 4 over) and CT moves 8 GW toward it. Net worse, and five to ten times slower, so both stay off. What would make the port pay is ECP's reserve price, which comes from its commitment structure (dispatch modes as seasonal columns over its 9 slices, the normal mode running at (1 - FOR) x FOS_CF_ECP), not from the rows themselves; porting that is a change to the LP's dispatch, not a block on top of it.

Pinned by `tests/test_emm_capacity.py` (`test_spin_reserve_inputs_follow_ecpdaty`, `test_spin_requirement_is_ecp_slice_formula`, `test_spin_requirement_matches_ecp_2031`, `test_ecp_build_profile_is_wrenew_two_years_back_without_derate`). Scripts: scratchpad `spin/` (rsr.py and csr.py read ECP's rows, comp.py the composite, req.py and lineup.py the line-up, one.py the one-step solves, chain.py the chain).

## ECP's dispatch modes (branch ecp-dispatch-modes, off)

**What ECP does.** EP$ODSP (uecp.f 17183-18100; ecp.ams cO_DISP, cJ, cU) gives every dispatchable type, region, fuel region and ECP season one column per mode. Mode L runs in the season's slices 1 to L (EPFRST order, the peak slice first), so L = 3 runs all season, L = 1 only in the 1% peak slice. The capacity row rCXle (EP$BDSP,11-12) caps the sum of a type's mode columns in each season at its capacity, so a unit committed for the base slice is committed all season. Each mode comes in three shapes, each a fixed output per committed GW in every slice it covers: O, the normal mode (EP$ODSP,22: (1 - FOR) x FOS_CF_ECP, ReStore's capacity factor, for the base-load types whose UPPCFB low bound is above 0.001, at least SR_MIN_CF; (1 - FOR) x height / season peak height for turbines); J, minimum load (EP$ODSP,38: SR_MIN_CF x (SR_MIN_LF + (1 - SR_MIN_LF) x height / the season's lowest height), SR_MIN_LF 0 for thermal types); U, maximum load (EP$ODSP,46: (1 - FOR) x (SR_MAX_LF + (1 - SR_MAX_LF) x height / season peak), SR_MAX_LF 0.5 turbines, 0.7 existing CC, 0.9 new CC and coal). Every shape puts SR_CREDIT x (1 - its output) on the slice's reserve row (EP$ODSP,34/44/52), so headroom includes the outage share. UPPCFB (COSTPERF) limits the modes: coal and combined cycle (low bound 0.15 and 0.2) cannot run peak-only; turbines and steam can use all three. J and U columns differ in cost only through the coal part-load heat rate curves (HTRT_ADJUSTMENT, FLRG_HR_EFF); the 2030 composite has no curves for gas types. Batteries do not optimise their reserve: ReStore hands ECP a fixed reserve per GW and slice (NET_STORAGE_SR_EX / _NW, CALC_STORAGE_VAL), 0.3 to 0.6 for existing batteries and 0 to 0.3 for new ones in 2031.

**Ported** (`capacity.ECP_DISPATCH_MODES`, needs `SPIN_RESERVE`, off): per region, thermal group and ECP season, commitment by mode (L allowed from UPPCFB, `allowed_modes`), their sum at most the group's capacity; each block takes the ECP slice most of its hours fall in (`block_slice`), and there output lies between cJ's output (`mode_min_factor`) and (1 - FOR) times the committed capacity of the modes reaching that slice. Spinning reserve rows are ECP's 9 slices per region (225 instead of 7,200): committed capacity less the slice's average output, plus storage, nuclear and other renewables, less SR_INT of wind and solar output, against cSR's bound on the slice heights. Energy stays on the 3-hour blocks.

**Result: it does not price reserve like ECP, so it stays off.** 2031 on EIA's 2030 fleet, median regional sum of the reserve duals in $/kW-year (ECP 19.5): block rows as on main 2.5, modes 2.4 (dispatch only, 15 s and 125 s); one step with builds 1.7, in 888 s (the block port took 150-380 s, main 13-48). The duals sit in the summer middle and base slices; ECP's sit in the base slice of every season (median 3.9 / 6.4 / 4.0 there). The seasonal commitment ties are not what makes ECP's reserve expensive. No chain was run: with duals unchanged the chain would follow the spin port's (wind 591 GW in 2040).

**Where the gap is instead.** Not the batteries alone: capping our battery reserve at 0.4 of capacity, or at zero, lifts the median to 3.4 and 4.2. ECP's 2031 dispatch differs from ours: turbines generate 77 TWh in ECP (AT 49, ET 20, CT 8) against 5 to 7 here, and coal 200 TWh against 430 to 460 here, while combined cycle is close (1,670 / 1,500). Existing turbines sit idle in ECP's shoulder and winter seasons (capacity rows slack in 48 of 57 fuel regions), combined cycle capacity rows bind in every season. So ECP buys base-slice reserve from turbines at minimum load, which costs their fuel above the energy price, while this LP gets it free from partly loaded coal and combined cycle. (Checked on branch coal-dispatch: EFD reports 419 TWh of coal in 2031, so this LP's 430 to 460 is close to what EIA reports and ECP's 200 is its planning estimate only; the gap that is real is the dispatch's coal capacity factor, docs/dispatch.md.) The next thing to check was why ECP's coal runs at half our output in 2031 (its coal capacity in plan year 2 is under 70 GW in EPECAP, and the coal part-load heat rate curves raise the cost of holding coal at part load); that is an energy-side difference, not a reserve one.

Pinned by `tests/test_emm_capacity.py` (`test_dispatch_modes_follow_uppcfb`, `test_block_slice_and_min_mode_output`). Scripts: scratchpad `modes/` (duals.py reads ECP's duals by slice, diag.py and diag2.py the 2031 solves, an.py the supply by slice).
