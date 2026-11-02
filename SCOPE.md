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

## Transportation module (started 2026-11-01, branch `transportation`)

### Oracle
EIA's `tran.f`, `tranfrt.f` and `tranair.f` (18,377 lines) run standalone with gfortran, same method as commercial. Folders `oracle/build_tran/` and `oracle/run_tran/`.

```
cd oracle
python -I gen_oracle.py "$NEMS_UPSTREAM" cb2026 tran
bash build.sh tran
cd run_tran && ./oracle.exe      # about 2 minutes with state dumps, 5.3 GB of dumps
```
`NEMS_UPSTREAM` points at EIA's checkout (default `../nems-upstream`, as before). The build folder gets its own copy of the includes (`inc/`), so the upstream path can contain spaces.

What it took (all generic, commercial unchanged and its 262 tests still pass):
- `gen_oracle.py` takes a module (`comm`, `tran`); `MODULES` lists each one's sources, includes and workbooks. Same layout as the residential session's version, so the two merge by adding entries.
- `patch_intel.py`: Intel range lists in array constructors (`[4:8,13:maxldv]`), hex literals in comparisons, `.EQ. .TRUE.`, `NOT()` on a logical, `INTEGER x/.false./`, `INTEGER NAME*2`, and `CAFE4`, a REAL constant (MODULE `F_` has implicit typing) used as a dimension.
- `stubs.f90` FILE_MGR: reads the `NEW` flag as one byte (tran.f passes `LOGICAL*1`; reading 4 bytes picked up garbage and asked for write access), never writes over a file in `filelist.txt`, matches names on 18 characters like NEMS (`TRNSTOCKX_HDV_PRE2012` arrives cut to 18), hands out positive unit numbers from 200 (tranair.f closes its debug unit in 2050, then writes to it again), and actually closes files on `'C'`.
- `xlsx_ranges.py` reads only the first two corners of a named range, as EIA's `Parse_RangeStr2` does. `CRCOVID` in trnldvx.xlsx is defined as `$B$3446:$BE$3454:'trnldv'!$BE$3453` and was being dropped.
- `driver_tran.f90` runs every year 1990-2050 (TRAN returns before 1995) with **3 iterations a year**. Evidence: `TAIRT` adds to `LFDOMAVG` on every call (an EIA bug, kept), and EIA's `TRTRAVLD(3,:)` is exactly 1.5 times the 2-iteration value in every year.
- `hooks_tran.py` dumps state around each routine's CALL in TRAN. Most state here is Fortran MODULE variables (`T_`, `F_`, `AIRMOD`), so it parses the module declarations and dumps every module or COMMON variable the routine, or anything it calls, names. F_ files are prefixed `f_`, AIRMOD `a_`. Dumps are on the **first** iteration of 2020, 2025, 2030, 2040, 2050: on the final iteration the "before" state already holds the answer. Python: `oracle_state.load(tag, year, run="run_tran")`.

Oracle vs EIA's restart file (`tests/test_tran_oracle.py`, census divisions 1-9):
- 1995-2025: gasoline, diesel, jet fuel, electricity, other within 3e-7 (float rounding). Natural gas, LPG and ethanol within 0.7% from 2011 on.
- 2026-2050: gasoline within 0.23%, diesel 0.8%, jet fuel 0.05%, electricity 0.7%, residual 0.2%. Truck natural gas (9%), ethanol (12%) and hydrogen (up to 42% in 2030 on a small base) drift more.
- Why: NEMS calls TRAN with each iteration's unconverged prices, and several routines work only on the first iteration (`CURITR == 1`: FEM pass reset, CAFE pass, HAV stock weights, freight lag copies). The oracle sees converged prices all three times. Freight truck fuel choice (payback and S-curve adoption) amplifies small differences. Not fixable without the per-iteration price history.
- Also outside TRAN: the refinery model (LFMM, `refine.f`) overwrites `E85AVAIL` history for 2010-2012 after TRAN runs; QBLK region 10 (California) and 11 (US) totals are filled by NEMS, not TRAN.

### Module map
Call order inside `TRAN` (tran.f), with code lines. One port test per routine, at the routine's CALL.

| # | Routine | Lines | What it does | Calls |
|---|---|---|---|---|
| 0 | `READLDV`, `READVMT`, `READSTOCK`, `READHIST`, `READNHTSA` | 870+170+140+165+340 | First-call input reads (trnldvx.xlsx, VMT, stock, FEM history, NHTSA) | |
| 1 | `TMAC` | 68 | Fuel tax, income, population by age/sex, licensing rates, licensed drivers | |
| 2 | `NEWLDV` | 87 | New car and light truck sales by region (car/truck split logit) | |
| 3 | `TMPGNEW` | 658 | New vehicle fuel economy: technology penetration (FEM), CAFE/GHG compliance, attributes, vehicle choice | `FEMCALC` (1,070), `CAFECALC` (520), `CAFEGHG_MEET` (320), `TATTRIB`, `TALT2`, `TALT2X`, `CGSHARE`, `AFVADJ`, `LIONCOSTCALC` and battery/EV cost routines |
| 4 | `TREG` | 88 | Regional sales by fuel type | |
| 5 | `TFLTSTKS` | 112 | Fleet vehicle stocks | |
| 6 | `FLTHAV` | 323 | Taxi / ride-hail adoption of automated vehicles (only once lidar is available) | `HAVCALC`, `LIDARCOSTCALC` |
| 7 | `TFLTVMTS` | 20 | Fleet VMT | |
| 8 | `TSMOD` | 124 | Light-duty stock model (survival, vintages) | |
| 9 | `TMPGSTK` | 262 | Stock average fuel economy | |
| 10 | `TCURB` | 35 | Curb weight | |
| 11 | `TFLTMPGS` | 290 | Fleet fuel economy | |
| 12 | `TFLTCONS` | 71 | Fleet fuel use | |
| 13 | `TVMT` | 145 | Household VMT from licensed drivers, income, fuel cost | |
| 14 | `TRANFRT(0)`, `TRANFRT(1)` | 5,700 (tranfrt.f) | Freight trucks: sales, technology adoption, Phase 2 GHG and ZEV rules, fuel choice, stock, VMT, fuel; commercial light trucks; report call | `TRUCK_NEW`, `TRUCK_CHOICE`, `TRUCK_STOCK`, `TRUCK_VMT`, `TRUCK_FUEL`, `TCOMMCL_TRK`, `CFREAD` |
| 15 | `TMPGAG` | 39 | Aggregate fuel economy | |
| 16 | `TRAIL` | 146 | Freight and passenger rail | |
| 17 | `TSHIP` | 289 (tranfrt.f) | Domestic and international shipping | |
| 18 | `TRANAIR` | 1,720 (tranair.f) | Air travel demand, aircraft stock and efficiency, jet fuel | `READAIR`, `TAIRT`, `TAIREFF`, `TAREPORT` |
| 19 | `TMISC` | 440 | Military, buses, recreational boats, lubricants, pipeline | |
| 20 | `TCONS` | 59 | Light-duty fuel use | |
| 21 | `TINTEG` | 118 | Fuel use by fuel and region into QBLK | |
| 22 | `TBENCHMARK` | 473 | Benchmark to SEDS history and STEO | `TRANEASY` |
| 23 | `TREPORT` | 555 | TRANREP report arrays | |
| 24 | rest of `TRAN` | 90 | QGFTR / QRHTR / QRLTR splits, average vehicle prices, rail and ship gas | |

Port order: the small light-duty routines first (1, 2, 4, 5, 7-13, 15, 16, 19-21), then `TMPGNEW`, the freight module, air, benchmarking and reports.

### Port progress

| Routine | State | Match vs oracle | Python |
|---|---|---|---|
| `TMAC` | Done 2026-11-01 | Every dumped array within 1e-4 (float rounding), 2020, 2025, 2030, 2040, 2050 | `transportation/tmac.py` |
| `NEWLDV` | Done 2026-11-01 | Same | `transportation/newldv.py` |
| `TREG`, `TFLTVMTS`, `TCURB`, `TMPGAG` | Done 2026-11-01 | Same | `transportation/small.py` |
| `TFLTSTKS` | Done 2026-11-01 | Same | `transportation/fleet.py` |
| `TSMOD` | Done 2026-11-01 | Same | `transportation/stock.py` |
| `TMPGSTK` | Done 2026-11-01 | Same | `transportation/stock_mpg.py` |
| `TFLTMPGS` | Done 2026-11-01 | Same | `transportation/fleet_mpg.py` |
| `TFLTCONS`, `TVMT` | Done 2026-11-01 | Same | `transportation/travel.py` |
| `TCONS`, `TINTEG` | Done 2026-11-01 | Same | `transportation/totals.py` |
| `TRAIL`, `TMISC` | Done 2026-11-01 | Same, including their saved local arrays | `transportation/misc_modes.py` |
| `MEAN_FUNCS` | Done 2026-11-01 | Through its callers | `transportation/mean_funcs.py` |
| `TMPGNEW` (+ FEM, CAFE, vehicle choice), `FLTHAV`, `TRANFRT` (freight), `TSHIP`, `TRANAIR`, `TBENCHMARK`, `TREPORT`, end of `TRAN` | To do | Oracle dumps for all of them are already in place | |
| Input readers (`READLDV`, `READVMT`, `READSTOCK`, `READHIST`, `READNHTSA`, `CFREAD`, `READAIR`) | To do. Tests take the oracle's copies of the input tables | | |

Tests: `tests/test_tran_<routine>.py`, all through `tests/tran_harness.py`. A test feeds the port the state before EIA's routine and compares every dumped array with the state after; it also fails if nothing changed, so it can't pass by doing nothing. Loop indexes are MODULE variables here (`IREGN`, `ILDV`, ...), so ports leave them where the Fortran loops leave them; later routines can read them.

Port conventions: a routine is `name(s)` where `s` is the state dict (lowercase Fortran names, `FArray` with Fortran bounds), updated in place. Saved local arrays that carry last year's values are a second argument, `carry`; the oracle dumps them as `p_<name>` (`PRIVATE` in `hooks_tran.py`). `common.fsum` adds float32 in Fortran's element order (numpy's pairwise sum rounds differently). `misc_modes.powi` does REAL**INTEGER the way gfortran does (square and multiply).

Name clash to watch: `ANGTDM` and `NGTDMOUT` are two COMMON blocks with the same variable names (natural gas prices), as are `AEUSPRC` and `EUSPRC`. A routine sees whichever it includes. Dumps carry the ANGTDM and AEUSPRC copies as `angtdm__<name>` and `aeusprc__<name>`. `TMISC`, most of tranfrt.f, and a few tran.f routines include `ANGTDM`.

### EIA quirks kept (transportation)
- `TAIRT` accumulates `LFDOMAVG(N)` and `LFINTAVG(N)` on every call instead of resetting them, so the reported load factors are 3 times too big (one per NEMS iteration).
- `TAIREFF` closes the air debug file in 2050, then `TAREPORT` writes to it.
- `NEWLDV`: the national car share counts every automation level in the numerator and only level 1 in the denominator.
- `TMPGSTK` and `TFLTMPGS`: the US new-vehicle MPG uses `DEN1 = ...` instead of `DEN1 = DEN1 + ...`, so it is the last region with sales, not a sum. The oldest vintage's MPG uses ELSEIF, so the 25-year-old vintage only counts when the 24-year-old one is empty.
- `TFLTSTKS`: the national total inside the stock loop uses `IAGE` left at `MAXAGE`, so only the oldest vintage gets one (overwritten right after).
- `TSMOD`: the low-macro survival tweak has a `CURCALYR == STOCKYR` branch inside a `CURCALYR > STOCKYR+1` test, so it never runs.
- `TVMT`: `ildv.le.7.or.ildv.ge.15.and.X.and.Y` binds as `ildv <= 7 .or. (ildv >= 15 .and. X .and. Y)`, so powertrains 1-7 are always counted. `TEMP_MPG(ildv)` is a local array sized by the module variable `ILDV` at entry.
- `TMISC`: the school bus CNG share for this year is updated after it was copied into the fuel shares, so it takes effect a year late. The transit bus Btu-per-mile formula `X*TBSYSEFF*1-(...)*1+(...)` subtracts and adds where it looks like it should multiply.
- `TBENCHMARK`: `MER_STEO_regn` is a saved local filled in the last SEDS year and read in the MER year.

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
