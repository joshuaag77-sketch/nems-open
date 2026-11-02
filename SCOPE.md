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
| `COMTechnologyChoice` | To do | | |
| `COMConsumption` | To do | | |
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
