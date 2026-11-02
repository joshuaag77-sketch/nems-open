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
| Residential demand | `source/resd.f` | 17k Fortran | To port | None |
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
| `COMServiceDemand` (input readers: kintens, ksheff, kmels, ksdela, kvarsdi, ...) | To do. The math takes these tables as inputs; tests use the oracle's copies | | |
| `COMTechnologyChoice` (calculation, non-first calls) | Done 2026-11-01 | Within 2e-6 vs oracle on every output (shares, efficiency, MS, investment, EquipSD, warehouse indices, US averages), tested 2020, 2026, 2040 | `src/nems_open/commercial/technology_choice.py` (about 50 s per year, pure Python) |
| `COMTechnologyChoice` (first call: KBEHAV, KDELEFF, KCAPFAC, KPREM reads, TimePrefProp normalization, heat pump cost edit) | To do | | |
| `COMConsumption` (calculation) | Done 2026-11-01 | Within 5e-7 vs oracle on every output, 9 test years 2019-2050; US total matches EIA to 4 decimals | `src/nems_open/commercial/consumption.py` |
| `COMConsumption` (first call: KSTEO, KMINFL reads, STEO targets into CMSEDS) | To do. KMINFL is re-read every call; tests take it from the oracle | | |
| `COMBenchmarking` | To do | | |
| `COMReport`, `CALC111D`, `CDISTGEN` | To do | | |
| `COMM` driver | To do | | |

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

## Industrial module (ind.f): oracle status and map (2026-11-01)
Branch `industrial`. Source `source/ind.f`, 20,001 lines, 100+ routines, all external (not CONTAINed) and sharing `MODULE I_` through USE.

### Oracle
Build and run: `NEMS_UPSTREAM=<eia checkout> python -I gen_oracle.py $NEMS_UPSTREAM cb2026 ind`, then `bash build.sh ind`, then `cd run_ind && ./oracle.exe` (about 4 minutes). `driver_ind.f90` calls IND for every year 1990-2050: two iterations with NCRL=0 (the second with FCRL=1), then the reporting call with NCRL=1. Output: `run_ind/out/q*in.bin` (all QBLK industrial fuels) and `run_ind/out/state/final/2050/` (INDREP, INDOUT, COGEN, BIFURC). `ORACLE_EXTRA_FLAGS=-ffpe-trap=invalid` stops at a NaN under gdb.
- Intel patches added to `patch_intel.py` (each commented): parenthesized READ item list, backslash edit descriptor, numeric variable formats `<26-10+1>`, `CHARACTER*name`, `EOF()` (defined inside MODULE I_), scalar assignment to unallocated arrays (Intel ignores it, gfortran writes address 0), `MIN(CARBSHRCA,1.0)` with a NaN (Intel returns 1.0), an I4 descriptor given a REAL in the NaN report format, and skipping `INDSIC`/`INDGRP` (spreadsheet report writers on direct-access CSV).
- `-std=legacy` is needed for ind only (`shares_calc` is passed arrays shorter than its dummy).
- Startup data: `ironstlx.xlsx` (steel, paper, Aluminum, Glass, Lime, Cement sheets) and `indcogenx.xlsx` (icogen) go through the same range flattening as `ktekx.xlsx`.
- Seeding: IND reads its own current-year and next-year outputs before writing them (CALGEN divides by this year's QGFIN and QELIN; CARBSHRCA divides by next year's consumption). So the oracle loads the whole restart file, INDREP and INDOUT included, and no output is zeroed. "Earned" matches need a perturbation test (scale the seed, check the result returns).
- Same COMMON block, two spellings: `ampblk` calls the price PELIN, `epmmpblk` (used by ind) calls it AELIN. The restart file holds one spelling. `gen_oracle.py` now loads both (`common_aliases`). Without this, adjusted prices were zero.

### Where the oracle stands
- 1990-2023 reproduce EIA exactly (history from SEDS). Diesel and coal also match through 2026.
- From 2024, electricity (QELIN), natural gas and several others differ from the restart file. Open problem: a NaN appears in the process-flow (steel/paper) fuel totals `ENPQTY`/`ENSQTY` from the first model year (2022), and EIA's own guard in INDTOTAL (line 8636) drops those fuels. Not yet traced to its source; do that before porting, otherwise the oracle is not the answer key. Some NaNs are intended (0/0 in WEXOG H2_byp_index, fixed on the next line; CARBSHRCA).

### Map (line numbers in ind.f)
Driver and setup: `IND` 969, `Setup_Mac_and_Price` 1154 (prices, macro, lagged quantities), `ISEAM` 2049 (loop over 24 industries and 4 Census regions: calls RCNTL, PRICE, REXOG, CALPATOT, CALBYPROD, CALBTOT, CALGEN, CALBSC, CALSTOT, INDTOTAL, NATTOTAL, CONTAB, MODCAL, WRQTY, WRBIN/RDBIN).
Input readers: `RCNTL` 2595, `REXOG` 2768, `IEDATA` 4835, `IRSTEO` 4740, `IRCOGEN` 5020, `READ_IDMinput` 15694, `IS_GETDATA` 16863, `mecsbase` 9324, `uectpc` 9465.
Energy accounting core (first port target, small and checkable through QBLK): `CALBYPROD` 6892, `CALBTOT` 7667, `CALGEN` 7757, `CALBSC` 8169, `CALSTOT` 8307, `INDTOTAL` 8543, `NATTOTAL` 8741, `WRQTY` 8857, `INDCGN` 8902, `CONTAB` 8970.
Benchmarking and output to NEMS: `MODCAL` 5778, `WEXOG` 2828 (STEO benchmark to QBLK, feedstocks, H2), `IFINLCALC` 5523, `CO2CALC` 14015, `CALIBRATE` 13898, `CALIBRATE_COAL_ELEC` 13812.
Cogeneration: `cogent` 9581, `EvalCogen` 9643, `pcoggen` 9826, `addupcogs` 5183, `COGINIT` 5115.
Technology and process-flow industries: cement 14115-15690 (with CCS), aluminum 15782, glass 15906, iron and steel 18078-18800 (`TECH_STEP` 16046, `PRODFLOW_STEEL` 18107), paper and pulp 18843-19500, `PPSTEAM` 19050.
Sector subroutines for non-process industries: `AGTPC` 12581, `COALTPC` 12697, `OGSMTPC` 12886, `OTH_MINTPC` 13122, `CONTPC` 13327.
Pure reporting (not ported): `INDSIC` 9985, `INDGRP` 11311, `TECHSHR_RPT` 17380, `CHECK_*`, `ckstr/ckint/cknum`.
Note quad precision: `logit_calc` and `shares_calc` use REAL*16. gfortran REAL*16 matches Intel's.

### Port status
Ported: CALBSC (`industrial/boiler_shares.py`, test `tests/test_industrial_boiler_shares.py`, matches the oracle to float rounding, 6 years). The oracle's per-routine dumps hold only the last industry and region of the year (24, 4), so each test checks one case per year. Quirk kept: BSSHR only gets the fuels CALBSC lists, the rest keep earlier values; SwitchPrat/AveFPrc is computed in the Fortran but never used, so it is not ported. Next steps: (1) add `TARGETS` for the energy accounting routines in `hooks.py` (IND_TARGETS is empty); (3) port CALGEN/CALBSC/CALSTOT/INDTOTAL first.
