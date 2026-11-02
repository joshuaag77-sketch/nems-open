# NEMS Open: scope

State file for the project. Update it as decisions change. Last updated 2026-11-01.

## Goal
Rebuild EIA's National Energy Modeling System (NEMS) as open Python that runs without paid software, then put a playable browser front end on it ("run America's energy system to 2050").

## What we have
- Upstream clone: `nems-upstream/` (github.com/EIAgov/NEMS, AEO2026 release, Apache 2.0). About 1 GB.
- About 300,000 lines of Fortran in `nems-upstream/source/`.
- Several modules are already Python (EIA did part of the job for us).
- Ground truth: finished runs for 11 AEO2026 scenarios in `nems-upstream/output/aeo2026/`. The `cb2026` reference case ships `restart.npz`, which loads straight into numpy: 4,404 named arrays covering every price and quantity in the model. Example: `QBLK/qelcm` is commercial electricity use, 11 regions by 61 years.

## Module map

| Module | Where | Size | State | Blocker |
|---|---|---|---|---|
| Commercial demand | `source/comm.f` | 13k lines Fortran | To port | None |
| Residential demand | `source/resd.f` | 17k Fortran | Done and matching 2021-2050 from the oracle's 2021 state; input readers to do | None |
| Industrial demand | `source/ind.f` | 20k Fortran | To port | None |
| Transportation demand | `source/tran*.f` | 18k Fortran | To port | None |
| Renewable fuels | `source/renew.f` | 35k Fortran | To port | None |
| International | `source/world.f` | 3k Fortran | To port | None |
| Macroeconomic | `source/mac.f` | 4k Fortran | To port | Uses S&P Global's licensed model. Replace with a simple open GDP driver |
| Electricity | `source/uecp.f`, `uefd.f`, `udat.f`, `uefp.f`, `uldsm.f` + `models/ecp`, `models/efd` | about 100k Fortran + AIMMS | To port, last | Biggest piece. Its optimization models run on AIMMS (paid) |
| Liquid fuels (refining) | `source/refine*.f` + `models/lfmm` | 12k Fortran + GAMS | To port | GAMS (paid) |
| Coal, natural gas, restore | `models/coal`, `models/ngas`, `models/rest` | AIMMS models | To port | AIMMS (paid) |
| Oil and gas supply (HSM) | `models/hsm` | 27k Python | Done by EIA | None |
| Carbon capture (CCATS) | `models/ccats` | 14k Python | Done by EIA | None |
| Emissions policy (EPM) | `models/epm` | 12k Python | Done by EIA | None |
| Hydrogen (HMM) | `models/hmm` | Python + AIMMS | Partly done | AIMMS |
| Integrating module | `models/main`, `source/nemsfunct.f` | Python + Fortran | Partly done | None |

The paid solvers (AIMMS, GAMS) can be swapped for open ones (HiGHS via Pyomo or linopy). That is a translation of the optimization model, not of procedural code, and it is the hardest part.

## Pilot module: Commercial
Why this one first:
- Pure Fortran, no paid solver.
- Small enough for one person plus agents: 13k lines, 9 subroutines.
- Inputs are all in the repo (`input/cdm/`, 28 files).
- Outputs are in the reference snapshot, so "done" is checkable.

Its 9 subroutines become the first 9 GitHub issues:
1. `COMM` (driver)
2. `COMFloorspace` (building stock)
3. `COMServiceDemand` (heating, cooling, lighting needs)
4. `COMTechnologyChoice` (which equipment gets bought)
5. `COMConsumption` (fuel use)
6. `COMBenchmarking` (calibration to history and the short-term outlook)
7. `COMReport`
8. `CALC111D` (power plant rule hook)
9. `CDISTGEN` (rooftop solar and other on-site generation)

## Pilot progress

| Subroutine | State | Match vs EIA | Python |
|---|---|---|---|
| `COMFloorspace` + `CMSurvRate` | Done 2026-11-01 | Within 1e-6, all 9 divisions, 11 building types, 2019-2050 | `src/nems_open/commercial/floorspace.py` |
| `COMServiceDemand` (calculation) | Done 2026-11-01 | Within 4e-7 (float32 rounding) vs oracle, all regions, buildings, services, 9 test years 2019-2050 | `src/nems_open/commercial/service_demand.py` |
| `COMServiceDemand` (first call: KINTENS, KSHEFF, KMELS, KSDELA, KHURELA, KVARSDI, KDSSTM, KDSEFF, KDSFS, KRENEW, KDEGDAY, BLDBASE, the KTEK technology table, base-year ServDmdIntenBASE) | Done 2026-11-01 | Same arrays as the oracle at the end of the 2019 first call (float32 exact; BLDBASE needs one oracle rebuild to be checked) | `src/nems_open/commercial/inputs.py`, `ktek.py`, `base_year.py`, `src/nems_open/xlsx_ranges.py` |
| `COMTechnologyChoice` (calculation, non-first calls) | Done 2026-11-01 | Within 2e-6 vs oracle on every output (shares, efficiency, MS, investment, EquipSD, warehouse indices, US averages), tested 2020, 2026, 2040 | `src/nems_open/commercial/technology_choice.py` (about 50 s per year, pure Python) |
| `COMTechnologyChoice` (first call: KBEHAV, KDELEFF, KCAPFAC, KPREM reads, TimePrefProp normalization, heat pump cost edit) | Done 2026-11-01 | Same arrays as the oracle before and after the 2019 first call | `src/nems_open/commercial/technology_choice_inputs.py` |
| `COMConsumption` (calculation) | Done 2026-11-01 | Within 5e-7 vs oracle on every output, 9 test years 2019-2050; US total matches EIA to 4 decimals | `src/nems_open/commercial/consumption.py` |
| `COMConsumption` (first call: KSTEO, KMINFL reads, STEO targets into CMSEDS) | To do. KMINFL is re-read every call; tests take it from the oracle | | |
| `COMBenchmarking` | Done 2026-11-01 | Bit-for-bit (float32) vs oracle on every output, 9 test years 2019-2050 | `src/nems_open/commercial/benchmarking.py` |
| `COMReport` (the national totals it leaves in COMMREP; the printed KRPT/KSDOUT/KDBOUT tables are not ported) | Done 2026-11-01 | Same arrays as the oracle before and after the 2050 call | `src/nems_open/commercial/report.py` |
| `CDISTGEN` (KCOGEN and KGENTK readers, learning, cash flow and IRR, Bass diffusion, RPS credits, CGCOMM outputs) | Done 2026-11-01 | Within 1e-4 on every output, 9 test years 2019-2050 (about 100 s a year in pure Python; the cash flow search is the hot spot) | `src/nems_open/commercial/distgen.py`, `distgen_tables.py` |
| `CALC111D` | To do | | |
| `COMM` driver (yearly chain) | Done 2026-11-02 | Within 4e-7 vs oracle on QBLK fuel use, 2025-2050, one year or chained | `src/nems_open/commercial/comm.py` |

Run the tests: `python -m pytest` from the project root. The harness pieces are `src/nems_open/snapshot.py` (reads EIA's restart file) and `src/nems_open/fortran_io.py` (mimics Fortran's text reads).

## Oracle (built 2026-11-01)
EIA's original commercial module now runs on this laptop with free gfortran (WinLibs GCC 16.2, installed by winget), no Intel compiler and no NEMS. Folder: `oracle/`.

Rebuild and run:
```
cd oracle
python -I gen_oracle.py ../nems-upstream cb2026
bash build.sh
cd run && ./oracle.exe
```
gfortran must be on PATH: `C:/Users/joshu/AppData/Local/Microsoft/WinGet/Packages/BrechtSanders.WinLibs.POSIX.UCRT_Microsoft.Winget.Source_8wekyb3d8bbwe/mingw64/bin`.

How it works:
- `gen_oracle.py` dumps the 1,545 restart variables the module can see, writes a Fortran loader for them, maps NEMS file keys to paths, and flattens `ktekx.xlsx` named ranges.
- `patch_intel.py` rewrites Intel-only syntax in a copy of `comm.f`. Every rule is a spelling change, and each one is commented.
- `stubs.f90` replaces NEMS's file manager and scenario switches. `readrng_stub.f90` replaces the spreadsheet parser but keeps EIA's own range-copy code (`wk1_subset.py`).
- `driver.f90` zeroes the module's outputs, runs 2019-2050 (2 iterations a year), and writes arrays to `run/out/`. Add any internal array there to inspect it.

Results against EIA's reference run (`python -m pytest`, `tests/test_oracle.py`):
- Floorspace: matches everywhere (max error 1e-6).
- Consumption (`COMMREP/cmusconsumption`): exact through 2026, within 0.12% in every cell to 2050. 2050 US total 15.6423 vs EIA 15.6416 quads.
- The 2025 bug (fixed 2026-11-01): the STEO common block (`STEO_VAR_COM`) is not in the restart file. NEMS rebuilds it at startup from `input/steovars.csv` with `models/main/steo_load.py`. Without it, electricity and gas STEO targets were zero and the 2025-2026 benchmarking blew up. `oracle/steo_fill.py` now runs EIA's own loader into a stand-in buffer laid out like the Fortran EQUIVALENCE, and the oracle loads it.
- Remaining gap: 320 of 1,056 cells differ by 0.01-0.12%, from 2027 on. Not the iteration count (4 passes gives identical output to 2). Most likely float rounding: EIA builds with Intel `/fpconstant` (single-precision constants evaluated in double), which gfortran has no switch for. Good enough for an oracle; revisit only if a port needs tighter agreement.
- Lesson for other modules: anything NEMS builds at startup rather than saving (STEO, possibly others) must be rebuilt for the oracle. Check `models/main` first.

State dumps (`oracle/hooks.py`, added 2026-11-01): the build instruments its copy of `comm.f` to dump every commercial COMMON array just before and after a routine (`<tag>_in`, `<tag>_out`), plus the routine's private SAVE arrays, on the final iteration of 9 years (2019, 2020, 2021, 2025, 2026, 2027, 2030, 2040, 2050). Output: `oracle/run/out/state/<tag>/<year>/`, about 0.9 GB per routine. Python reads it with `nems_open.oracle_state.load(tag, year)`, which keeps Fortran bounds via `FArray`. To port the next routine, add a line to `TARGETS` in `hooks.py`: the CALL line, the label at the routine's end, and its private arrays.

How a port is split (decompilation style): the calculation first, fed the oracle's copies of its input tables, then each file reader as its own piece checked against those same tables.

CDistGen quirks kept: `XTAXCREDITMAXKW` is never assigned (stays 0), so the per-kW tax credit cap never applies; `XINXDECAY` (interconnection limit) is computed but never read; `WindBldgCount` is never cleared, so it sums both iterations of a year; `xvalesave` for non-gas fuel techs ignores the RPS terms; `KCHPCESGEN` reads the grandfather-year generation at index `year - BASEYR` (one off from the usual `BASEYR - 1`).

EIA quirks kept in the service demand port (do not "fix"): Assembly and Education leave Shredder and OfficePBE out of the misc total; Food Sales, Food Service and Mercantile skip the data-center adjustment for misc loads; the in-loop `MedFlrBase` counts small-office new floorspace twice; `EscalatorFlrBase` and `KitchenFlrBase` subtract surviving floorspace where new was probably meant.

Blocker found 2026-11-01: `COMServiceDemand` writes nothing to the restart file (`ServDmdExBldg`, `NewServDmd`, shell factors are all internal). It also reads last year's technology choice results. So service demand, technology choice and consumption can only be checked together, through `COMMREP/cmusconsumption` and `QBLK/q*cm`, which is about 6,000 lines of Fortran with no checkpoint in between. Proposed fix: compile EIA's original `comm.f` with free gfortran plus stubs (an "oracle") so every intermediate number can be dumped and compared. No Fortran compiler is installed yet.

Quirk to keep for fidelity: in the `Other` building ramp branch, EIA adjusts `NewServDmd` before computing it (comm.f around line 3586), and the value is then overwritten. Harmless, but don't "fix" it in the port.

What we learned: the restart file holds the module's internal state too (`COMMREP/*`), not just its outputs, so single subroutines can be tested alone. That answers the open question below for floorspace. It still needs checking for the price-driven pieces.

## Technology choice map (for the port)
About 1,575 code lines in `COMTechnologyChoice`. Line offsets are from the SUBROUTINE line in `oracle/build/comm.f90`.

Plan: port in this order, one Python function per step, all in `src/nems_open/commercial/technology_choice.py`. Test only at the routine's outputs (`tc_out`), since the steps' intermediates are locals. Feed the port `tc_in` plus the carried values in `tc_pre`.

1. First-call setup (+587 to +830): reads KBEHAV, KDELEFF, KCAPFAC, KPREM; normalizes `TimePrefProp`; subtracts the cooling cost from heat pump capital costs in `TechCost`. Only on the first call, so test years after 2019 already hold the edited tables in `tc_in`.
2. Per-year setup (+826 to +930): zero `EquipSD` and investment arrays; 3-year price trend `PriceDelta3` and the "pull technologies forward" counters `iforward` (PITC).
3. Loop over region r, major service s, building b (labels 9000, 8000):
   - replacement proportion and surviving/replacement shares from last year's technology shares (+930 to +1000)
   - annualized cost of every technology, vintage and time-preference group `p`, for existing and new shells (label 90). Hurdle rate is the 10-year Treasury plus a premium, floored at 3% and stretched by price elasticity above 15%
   - least-cost search for New and Replacement (label 100): all-fuels (LC), same-fuel (SF), same-technology (ST), then a second all-fuels pass within the cheapest fuel
   - market shares for each behaviour (130, 140, 150) and combined by `BehaviorShare` into `MS(b,s,d,t,v)` for d = 1 New, 2 Replacement (160, 170)
   - Retrofit: annualized cost of keeping existing equipment `ACE` (180), least-cost search (190, 200), shares (210, 220, 420 or 230), combined into `MS(...,3,...)` (240)
   - heat pumps (cooling service only): cooling from heat pumps chosen for heating, by degree-day ratio; other cooling scaled to the rest
   - investment and subsidies (label 314); fuel shares and efficiency by decision (270); `FuelShareofService`, `SDbyFuel`, `PurchFuelShare` (280); `TechShareofService`, `PurchTechShare` (290); `AverageEfficiency` (310); `EquipSD`
   - regional and decision-type aggregates after label 8000: `RegionFuelShare`, `RegionAvgEff`, `DecFuelShare`
4. Minor services (labels 9050 to 9100): not yet read.

EIA quirks seen so far (keep them):
- In the same-fuel search, `isFuelNew=1` sets the whole array, so only the first technology's fuel gets its vintage-1 starting value.
- The retrofit availability check (label 180) and the investment step use `ifwd` left over from earlier loops, not one computed for that technology.
- `PriceDelta3` uses `elasbaseyr` before it is assigned in the same call; it holds the previous call's value (2018).
- Several `MS` updates touch arrays for heat pump cooling techs by index `t + CMnumHeatPumpTechs`; the layout of `TechsforService` must match.
- In the retrofit second pass (label 200) the running minimum `MinCost_AF` is never reset: it starts from the last value of the label 190 loop and keeps falling across all technologies and preference groups.
- `KEqCost` keeps its own saved `ifwd`, separate from the routine's. Ported as `Carry.keq_ifwd`; both are 0 in every AEO2026 test year because `iforward` stays 0.

Consumption quirks kept: district steam uses `SRElas` left over from the loop before it (last region, distillate) for every fuel; kerosene's minor-fuel formula is missing parentheses, so new floorspace is added unscaled; the spray-valve standard for food service, health care and lodging uses fuel totals that are only partly clamped when electricity is processed.

Port notes: the run switches in the reference case are `CostTrendSwitch=1` (capital costs from `KEqCost`), `STRetBehav=1`, `I4SCNT=2` (current local prices, not price expectations). Speed: about 50 s per year in pure Python; the retrofit searches are the hot spot and can be vectorized later, as long as the strict "only if cheaper" order is kept.

## Residential port (started 2026-11-01)

### Residential oracle
Same method as commercial, same scripts with a module name:
```
cd oracle
python -I gen_oracle.py ../nems-upstream cb2026 resd
bash build.sh resd
cd run_resd && ./oracle.exe
```
- Runs 2020 (RECS base year) to 2050 in about 10 s without dumps, 77 s with all 44 routines dumped (18 GB in `run_resd/out/state/`).
- Matches EIA's `QBLK` residential fuel use (regions 1-9) to float rounding through 2026, within 0.3% after; 2050 US totals within 0.05%. Report arrays (`RESDREP`, `RSCON`, `RSEFF`) agree within 1% from 2021. Same drift pattern as commercial: STEO benchmarking pins the years to 2026, float rounding builds after. `tests/test_oracle_residential.py`.
- What it took: the include list must cover routine-level includes too. `EXCONS` and `NEMSCN` include `tranrep` for `TRQ_ELEC` (EV home charging, added to `QELRS`); without it electricity was 15% low by 2050. Three more Intel spellings (scalar in parentheses in a READ, `91FORMAT` with no space, an INTEGER 0 under an F format in the lighting debug report). The residential blocks (`RESDREP`, `RSCON`, `RSEFF`) and `QBLK` Q*RS are not loaded from the restart file, so every match is earned.
- 2020 report cells that the module does not compute (new-equipment efficiencies, some `RSEFF` weights) hold values in EIA's restart file carried from earlier runs. Compare from 2021.
- State dumps: all residential routines are internal to `SUBROUTINE RESD` and share `MODULE R_`, so the dump routine `USE`s R_. A full dump is 170 MB, so around each target the oracle dumps only the shared arrays that routine (and anything it calls) mentions. Blocks outside R_ (`tranrep`) go through a second routine. Tags and calls: `RESD_TARGETS` in `oracle/hooks.py`. Dump years 2020, 2021, 2022, 2025, 2026, 2027, 2030, 2040, 2050; yearly routines have no 2020 dump.
- Test pattern: `tests/resd_oracle.py`. Load `<tag>_in`, run the port on a copy, every array in `<tag>_out` must match. Ports work in place on a dict of FArrays, the way the Fortran works on shared COMMON.

### Routine map (resd.f, line numbers in nems-upstream/source/resd.f)
Call order from `RESD` (line 411). Base year 2020: input readers on iteration 1, then `RDPR`, `EXCONS`, `RSBENCH`, `NEMSCN`, `RESDRP`. Each later year: the yearly chain below. Final year: reports.

| Routine | Lines | What it does | Tag | State |
|---|---|---|---|---|
| `RTEKREAD` | 607, 437 | Reads RSMESS.xlsx: RSCLASS, RSMEQP, RSSWITCH, RSMSHL (equipment, switching cost, shell menus) | | To do (reader) |
| `DEGDAYREAD`, `BLDBASEREAD`, `RSUECSHLREAD`, `RSMELSREAD`, `RSMISCREAD`, `RSMLGTREAD`, `RDRET`, `INTEQT`, `RDSQFOOT`, `RDHTREQC`, `RDEFF`, `RDSTEFF`, `RDESTARHOMES`, `RDUECS`, `RCONSFL` | 1044-2443 | Text input readers (degree days, UECs, MELs, misc controls, lighting menu, retirements, new-home heating shares, floor area, RECS stock, efficiencies, ENERGY STAR homes, fuel maps) | | To do (readers) |
| `RDPR` | 2086, 61 | Fuel prices to the menu dollar year | pr | Done, bit-exact |
| `EXCONS` | 2444, 525 | RECS-year consumption by end use | ex | Done, bit-exact (`totals.py`) |
| `NEWHSE` | 2969, 44 | New homes from housing starts and survival | nh | Done, bit-exact |
| `SQFTCALC` | 3013, 85 | Floor area per home | sq | Done, bit-exact |
| `REPLACE` | 3098, 107 | Logit split of retiring equipment across classes | (via callers) | Ported in `helpers.py`, checked through callers |
| `RSHVAC` | 3205, 409 | HVAC package and shell choice | hv | Done, 4e-7 (`heating_choice.py`) |
| `RHTRTEC` / `RHTRADD` / `RHTRCON` | 3614, 3951, 4249 | Space heating: choice, stock added and replaced, consumption | htt, hta, htc | Done: 3e-7, 2e-7, bit-exact (`heating_choice.py`, `heating.py`) |
| `RCLTEC` / `RCLADD` / `RCLCON` | 4790, 5047, 5361 | Space cooling | clt, cla, clc | Done: 3e-7, bit-exact, bit-exact (`cooling.py`) |
| `RCWTEC` / `RCWADD` / `RCWCON` | 5844, 6095, 6240 | Clothes washers | cwt, cwa, cwc | Done, bit-exact (`washers.py`) |
| `RDWTEC` / `RDWADD` / `RDWCON` | 6466, 6683, 6841 | Dishwashers | dwt, dwa, dwc | Done, bit-exact (`washers.py`) |
| `RWHTEC` / `REUADD` (EU 5) / `RWHCON` | 7056, 7387, 7660 | Water heating | wht, wha, whc | Done: 9e-8, bit-exact, bit-exact (`water_cooking.py`) |
| `RSTVTEC` / `REUADD` (EU 6) / `RSTOVCON` | 8085, 7387, 8338 | Cooking | ckt, cka, ckc | Done, bit-exact (`water_cooking.py`) |
| `RDRYTEC` / `RDRYADD` / `RDRYCON` | 8568, 8783, 9055 | Clothes dryers | dyt, dya, dyc | Done, bit-exact (`appliances.py`) |
| `RREFTEC` / `RREFADD` / `RREFCON` | 9296, 9562, 9694 | Refrigerators | rft, rfa, rfc | Done, bit-exact (`appliances.py`) |
| `RFRZTEC` / `RFRZADD` / `RFRZCON` | 9899, 10146, 10279 | Freezers | fzt, fza, fzc | Done, bit-exact (`appliances.py`) |
| `LTCNS` | 10492, 666 | Lighting choice, stock and use | lt | Done, 7e-7 (`lighting_misc.py`) |
| `APCNS` | 11158, 378 | Miscellaneous electric loads (MELs) | ap | Done, bit-exact (`lighting_misc.py`) |
| `SHTCNS`, `APPCNS` | 11536, 11628 | Secondary heating, other-fuel appliances | sh, sa | Done, bit-exact (`lighting_misc.py`) |
| `FUELCN` | 11693, 40 | Fuel totals across end uses | fu | Done, bit-exact (`totals.py`) |
| `RSBENCH` | 13673, 223 | Benchmark to SEDS and STEO (pins 2020-2026) | bb (2020), be | Done, bit-exact (`totals.py`) |
| `NEMSCN` | 11733, 60 | Writes `QBLK` Q*RS (net of own-use generation, plus EV charging) | nb (2020), ne | Done, bit-exact (`totals.py`) |
| `RESDRP` | 11793, 107 | `RESDREP` report arrays | rb (2020), re | Done, bit-exact (`totals.py`) |
| `RDISTGEN` | 15065, 1678 | Rooftop PV and other on-site generation | dg | Done, bit-exact (`distgen.py`; reads RGENTK and RSGENTK itself) |
| `CALC111D` | 14956, 109 | EPA 111(d) rebates, repealed, off in AEO2026 | | Skip |
| `RSPITC`, `PITCINIT` | 16773, 16743 | Price-induced technical change, off (IFMAX = 0) | | Skip |
| `NHTSHR`, `RESDRP2` | 13610, 11900 | Final-year reports: new-home heating shares, the rest of RESDREP | nt, r2 | Done, bit-exact (`reports.py`) |
| `RESDBOUT` | 13896 | Debug database file only | | Skip |
| `SVRTE`, `RSELAST`, `EQCOST`, `rLearnCost` | 16862-17051 | Survival curve, short-run price response, cost trend, learning curve | | Ported in `helpers.py` |

### Results (2026-11-01)
- Every routine RESD calls in a projection year is ported and matches the oracle on every array it touches, in all dump years 2021-2050: most bit-exact, the rest within 7e-7. Base year 2020: EXCONS, RSBENCH, NEMSCN, RESDRP bit-exact.
- End to end (`src/nems_open/residential/resd.py`, `tests/test_residential_chain.py`): started once from the oracle's 2021 state, Python runs alone to 2050 (two iterations a year, about 140 s). It matches the oracle to 3e-7 on QBLK residential fuel use and within 5e-5 on every RESDREP, RSCON and RSEFF array, final-year reports included, (the largest, heating, from rounding compounding over 30 years). Against EIA's restart file it is within 0.33%, which is the oracle's own gap; 2050 US electricity 6879.7 vs EIA 6882.1 trillion Btu, gas 4096.4 vs 4096.0.
- Shared EXP, ** and LOG round once from double precision (`common.expf`, `powf`, `logf`). NumPy's float32 versions are an ulp or two off the oracle's libm, and differences of large stock sums magnify that to 1e-5.
- Carried state the dumps needed (SAVEd locals and PELRSOUT, which is EQUIVALENCEd so the COMMON scan missed it) is listed in `RESD_TARGETS`. `resd.resume_from_dump` fills in the few locals a run started mid-projection cannot get from dumps.
- Still to do: the input readers (first call of 2020), so a run can start from the input files instead of the oracle's 2021 state. RESDBOUT (debug file only) is skipped.

### Residential quirks kept (do not fix)
- `RDPR`: wood is priced to distillate in 2020 but to natural gas less carbon tax after.
- `NEWHSE`: `ALLNEW` keeps only the last building type, and `HHSTOCKBYDIV` divides its running total by a million on every pass of the loop.
- `REPLACE`: switching cost is looked up as `RPINSCOST(RECCL, RECCLSW)` (EIA's own TODO asks whether that is transposed); computes CAPITAL and RETAIL and never uses them.
- RESDRP2: NUME/DEN/NUME1/DEN1 reused across end uses without a reset; refrigerator, freezer, and existing washer/dishwasher blocks read class 1 sums (DEN1(Y,1,B,D)) not EQC; RSNEFDB1 for fridges/freezers divides by class-1 sums for every class.
- RESDRP2: existing-efficiency sums have no zero-weight guard (EIA divides by zero weights); new cooling uses different formulas for room AC; the E=1 NUME1 line has a doubled `+ +`; RSNEFCL for GEO_HP is (NUME/DEN)/3.412 where elsewhere it is *3.412.
- RESDRP2: RSEEFFZ loop starts at the RECS year where DEN is 0, so the RECS value stays; RSEEFRF/RSEEFFZ take the last class's base efficiency for 2020; RSREF/RSFRZ zeroed inside the class loop; X=1.0 multiplies RSCOOLERS (RACUnits factor commented out); summation order differs between blocks.
- NHTSHR only prints; its TESTHT block (HTYSSHR) is declared and unused.
- FUELCN/EXCONS/NEMSCN: division 10 holds the nine-division sum, labelled national (10 is California in parametr).
- NEMSCN/RESDRP/EXCONS: SLCON(Y,10) used as national; EXCONS adds into it without zeroing.
- RSBENCH: STEOCN(Y1,1..2,D) filled for all 2021-2027 with the current year's NGRCP/EXRCP; only CurCalYr is read.
- RSBENCH: distillate and propane STEOCN come only from RSSTEO; after STEO, electricity and gas ignore the tweak when it is 1.0; GLOBALBENCHON=0 freeze branch is dead.
- RESDRP: RSLTCON for the RECS year cleared and rebuilt every call; RSH2OCON(Y,5) = SLCON(Y,10).
- EXCONS: CSWCON, DSWCON, REFCON, FRZCON, CKCON, DRYCON zeroed inside the RECCL loop, so only the last record survives; TVRCON/PCRCON/APCON assigned three times in the building loop; xxxCONUS sums never read; TRQ_ELEC(1,MNUMCR,Y) reset inside the fuel loop; H2OCON(.,5,D) not zeroed.
- NEMSCN: QGFRS = QNGRS*1.0, QGIRS = QNGRS*0.0.
- STEOCN gas shares are NaN (0/0) where NGRCP is zero; never read.
- RSHVAC: CLSQRFOOTFAC(Y,HVT,R,B) read in HVOPCOST with the heating type index but written at cooling index HVCT, so it holds the previous iteration's value.
- RSHVAC: first-pass RTBASEFF(RECSYear,HVCC) uses a class number as a record index; RECCL1 hard-wired 2->13, 9->14, 10->15, else 12; cooling weighted-efficiency loop starts at RTTYEUPT(EU), the last heating record; SHLEVELH divided by TOTEWTN with no zero guard; EQFSHRN reset inside the class loop when TOTEWTN is 0; ALPHA1 overwritten with -0.5.
- RHTRTEC: OPCOST(3) uses EQCAHVUEC and AHSHELL where other end uses use OPCOST(2); builder OPCOST(2) divided by BLDRWT = 6; HEATSYS SAVEd local chains year to year.
- Washers: OPCOST(1)=OPCOST(2) from hard-coded BASEUSE 4.0125, BASEMEF 1.57; RTEFFAC computed never used; top/front split by hard-coded EQT<=3; REQTSHR = NEQTSHR; NCWLOAD and ECWLOAD overwritten per class, last wins; new-home penetration *1.0000.
- Dishwashers: SUM1 unused; penetration grows 1.0048/yr capped at 1; EQCND90 set to x - x when share >= 0.90, tests previous year's value; efficiency is a use ratio; SUEC divides by base efficiency where NUEC and RUEC multiply; RTEFFAC inverted.
- Washers/dishwashers: electricity priced at PELRSOUT end use 5 and 9; Y>2008 guard on price-induced BETA1.
- Cooling: heat pumps copy heating shares, BETA1DR etc. set only for non-heat-pump records; EQCPN90 read before written (previous iteration); RECCLCAC/RECCLEHP leftovers across loops; new-shell weighting starts at RTCLEUPT+2; RECCL 11 hard-coded room AC; CACFACT .1 and 90% CAC cap hard-coded; ND - ND = 0 in CAC branch; RCLCON uses leftover S (=4); COOLCNWT uses EQCSIUEC for room AC, EQCSUEC else; geothermal and EHP lookups dead.
- Lighting: ALPHA -0.15 for app 1, -0.30 after; logit loop runs 6 bins regardless, stale weights for extra bins; bulbbinlife and watts hold last app's values; Y>2008 guard; +.5 in NINT bulb life; LTREPSTK update (a + maxrep) - cumrep.
- MELs: ceiling fans use CDD ratio squared x income; APCON/APCONWT/APCONIN sum in three orders; EAEQP ignores existing-home growth; ELOTPEN ignores EH.
- SHTCNS: SHTCONIN omits HDDFACT on existing homes and needs NSHTSHR>0; wood uses distillate shell and price with +0.50 elasticity; propane alone -0.30.
- APPCNS: LPGGRILL reset to 0.60 each call; table built only 2021 iter 1; propane APLEQP scales by grill share, other fuels ignore NH.
- DECAY computed only on iteration 1 (static local), same value after.
- RDRYTEC tests PRICES(F) for the BETA1 adjustment, RREFTEC/RFRZTEC use PRICES(4); EQWTR uses the EQWTN formula, so replacement = new choice; dryer efficiency weighted by weight/efficiency, fridges/freezers by share x efficiency.
- RDRYADD redoes NEWDRYSAT inside the record loop (idempotent); class 26 hard-coded for DRYERTOT; RSGASCUST only ever raised; SWT, SWF unused.
- RDRYCON carries ALPHA across iterations (-0.15 for every fuel in the first year); RREFCON/RFRZCON ALPHA = 0.
- First-year sums use two term orders; RFRZCON mixes both. RDRYCON (LEAPYR*tot)*sel, fridge/freezer LEAPYR*(tot*sel).
- RWHTEC 2015 standard: hard-coded type numbers (1-3 gas, 4-8 electric/heat pump), 4% and 9% floors every year from 2015; beta price test repeated inside (RWHTEC only); 1/RTBASEFF fallback when WTEQCEFFN is 0 (RWHTEC only).
- Every TEC/CON overwrites PRICES(4,R,CurCalYr) with its own end-use electricity price (EUPR 3 water, 4 cooking): last writer wins.
- RWHCON: solar added to H2OCON(...,5,D) inside the RECCL loop, once per class; SLEQCN overwritten each pass; ALPHA carried, -0.15 in 2021.
- RSTOVCON vintage sums start at RECSYear, RWHCON's at RECSYear+1.
- REUADD: EQCREP zeroed only for B=1, leftover B=1 for switch totals; NG_WH 18 and NG_STV 23 hard-coded; dead SWF/SWT/SWFT.
- TrillsOwnUse national: SUM over technologies (9 values) assigned to 4 elements, so (y,11,nt) gets division nt's total, and it accumulates every iteration.
- ZIP electricity-rate update indexes CenDiv with the division number.
- In EstYear factor4/factor5 are unset (0 under -finit-local-zero), so lag and income terms drop out.
- PV calibration uses xAnnualKWh from the last ZIP of the division; adjRPS branch overwrites XVALESAVEBASE leaving XVALESAVEBASEadjRPS stale; xTaxCreditPct cap carries to later divisions/niches; xSizeMax used before set (holds 10).
- REAL*4 literals promoted to double (.78, .80, 10.8, 1.0533); 10.**12 single.
- REPLACE's debug loop DO RECCL=1,27 (2021, EU 1, B 1, R 1) overwrites the caller's RECCL with 28 through the argument, so RHTRADD processes only class 1 for B=1, R=1 in 2021.
- RHTRADD: B=1 left over after the main loops, so the REPLACE flag-2, SWITCHTO, SWF/SWT, EQCND90 loops never touch multifamily or mobile homes. SHARESN zeroed per class and set only for valid records.
- RHTRCON: AFANUEC rewritten per class, last class wins; FANCONIN divided by Driver2 inside the FCON loop (five times); FANEFF/NFANEFF set only in 2021; EFANUEC set only on iteration 1; EFANUEC/NFANUEC for 2020 never set (0); wood ALPHA +0.5; HEATOT maps F by class number (NG_HP 3, GEO_HP 4).

## Phase 2: demand runner (started 2026-11-02)
`src/nems_open/run_demand.py` runs the ported demand modules for a year on EIA's prices and writes QBLK-style fuel use. `python -m nems_open.run_demand 2030`; README has the Python API. Test: `tests/test_run_demand.py`.

- Order: NEMS's (RESD, COMM, IND, TRAN). Industrial and transportation are `None` in `SECTORS` and keep EIA's QBLK rows until their ports land; a new sector is a class with `start`, `iteration`, `quantities`.
- Inputs: every array in the restart blocks AMPBLK, AEUSPRC, MXPBLK, MACOUT, QSBLK, EMABLK, UEFPOUT, UECPOUT, TRANREP that a module's state holds is overwritten from `Inputs` (restart file plus overrides). PELRSOUT and PELCMOUT are EQUIVALENCEd onto the AEUSPRC end-use price arrays, so they are rebuilt from them. Applied to the oracle's state this changes nothing: the oracle ran on exactly these inputs.
- Start: the input readers are not all ported, so each module starts from the oracle's state at the top of the year's final iteration (`resd.start_from_dump`, `Commercial.start_from_dump`), with the run year cleared from every array the chain writes. `DemandRunner.run_year()` again carries on to the next year with two iterations.
- Commercial year driver: `src/nems_open/commercial/comm.py` (the "COMM driver" row above). It chains floorspace (from MACOUT/mc_commflsp), service demand, CDistGen, technology choice, consumption, benchmarking, and COMReport in 2050. It also ports the small pieces at the top of COMServiceDemand the calculation port left out: the first-iteration roll of last year's shares and efficiencies into the PrevYr arrays, and the reset of solar water heating. CALC111D writes no fuel use and is skipped. Speed: about 4.5 minutes per iteration (CDistGen 2.5, technology choice 2).
- Totals: the part of SUMQAS (source/util_sumqas.f90) that touches these sectors: US = sum of divisions 1-9, California = Pacific times the CALSHR share, then QTP, QTR, QTS for each sector.
- Results (2025, 2030, 2040, 2050): the runner matches the oracle to 4e-7 on QBLK fuel use for both sectors, and 2026 reached from 2025 matches too. Against EIA it inherits the oracle's own gfortran vs Intel drift:

| Sector | Year | US total (QTS) vs EIA | Worst electricity or gas cell |
|---|---|---|---|
| Commercial | 2025 | 5e-6 | 6e-6 |
| Commercial | 2030 | 1.3e-4 | 1.5e-3 |
| Commercial | 2040 | 6e-5 | 1.5e-3 |
| Commercial | 2050 | 7e-5 | 1.7e-3 |
| Residential | 2025 | 4e-6 | 3e-5 |
| Residential | 2030 | 8e-5 | 1.2e-3 |
| Residential | 2040 | 2.4e-4 | 2.3e-3 |
| Residential | 2050 | 2.4e-4 | 1.2e-3 |

- Oracle gaps it inherits, worth a look later: commercial kerosene (QKSCM, 2050 US 1.7 vs EIA 0.5 trillion Btu), residual oil (QRSCM, up to 7% of a 2 trillion Btu row), solar thermal (up to 8% in 2040 in both sectors). All tiny next to sector totals.
- Gotcha fixed: `residential/totals.py` read rssteo.txt from the repo folder, ignoring NEMS_UPSTREAM.

## Test harness (the "done" rule)
1. Load prices and economic drivers for every year from `cb2026/restart.npz`.
2. Run the Python commercial module year by year with those inputs.
3. Compare its outputs (`QBLK/q*cm` fuel use, `COMMREP/*` reports) to the snapshot.
4. Pass means within 0.1% for every region and year. Exact matches are not realistic, because of float differences and the order iterations run in.

Risk to check first: the snapshot holds converged end-state values. If the commercial module depends on values from earlier iterations within the same year, feeding final prices may not reproduce final quantities exactly. Test this on `COMConsumption` before writing more issues.

## Phases
1. Pilot: harness plus the Commercial port, passing on the reference case. Solo plus agents.
2. Go public: own GitHub repo, one issue per subroutine, CONTRIBUTING.md with the done rule. Recruit (Kleinman Center, Wharton Energy and AI clubs, Penn Engineering, EIA's NEMS team, Hacker News once there is a demo).
3. The other demand modules (residential, industrial, transportation) in parallel by contributors.
4. Supply side and solver swaps (coal, gas, refining).
5. Electricity.
6. Browser front end. A simple version can ship after phase 3, using EIA's numbers for the parts not yet ported.

## Open questions
- Repo name and license. Apache 2.0 to match EIA.
- Does EIA's restart file hold enough intermediate state to test each subroutine alone, or only the module as a whole?
