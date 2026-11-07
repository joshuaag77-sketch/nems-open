# OGSM plan

Written 2026-11-06 on branch `ogsm`.

## Finding: there is no OGSM Fortran to port

In the AEO2026 release EIA already rewrote oil and gas supply as Python. The module is called HSM
(Hydrocarbon Supply Model) and lives in `nems-upstream/models/hsm/`. `source/` holds no OGSM
Fortran. The only OGSM Fortran left is the common blocks in `includes/ogsm*` (14 files, about
4,600 lines, `ogsml48` alone is 2,340), which HSM fills through the restart file. So the oracle
method (compile EIA's Fortran with gfortran, dump state around each routine) has nothing to
compile. SCOPE.md already lists it as "Done by EIA, no blocker".

## What is there

| File | Lines | Job |
|---|---|---|
| `onshore.py` | 8,471 | Lower 48 onshore: drilling, wells, resource, production by play |
| `offshore.py` | 3,473 | Gulf of Mexico and other offshore |
| `prepare_results.py` | 2,444 | Writes results into restart arrays (the OGSM common-block variables) |
| `history_steo.py` | 1,933 | History and STEO benchmarking |
| `module_unf.py` | 1,702 | Main driver, setup, year loop |
| `alaska.py` | 1,072 | Alaska |
| `visualizations.py` | 1,046 | Plots, not needed |
| `ngp.py` / `ngp_cash_flow.py` | 1,022 / 424 | Natural gas plant liquids |
| `names.py` | 943 | Variable name map |
| `drilling_equations.py` | 947 | Drilling response |
| `cash_flow.py` | 920 | Well economics (NPV, break-even) |
| `restart_unf.py` | 841 | Restart file I/O |
| `canada.py` | 725 | Canada |
| `hsm.py`, `common.py`, `submodule.py`, others | about 900 | Entry point, helpers |
| Total | 26,918 | |

Inputs: `models/hsm/input/` (22 MB of CSVs: onshore, offshore, alaska, canada, history, steo).

## Interface variables

HSM reads prices and macro drivers from the restart file and writes back the OGSM variables
(crude and gas production by region and type, wellhead prices, drilling, reserves, lease
condensate, NGPL). The Fortran declarations are in `includes/ogsmout`, `ogsml48`, `ogsmoff`, `ogsmak`,
`ogsmcan`, `ogsmlng`. Read and write go through `restart_unf.py` and the compiled `pyfiler1` extension
(built for Python 3.12 on Windows).

## Paid solver?

No. HSM imports only pandas, numpy, matplotlib and its own files. No AIMMS, GAMS or LP. Two
caveats: `canada.py` takes some AIMMS outputs (Canadian gas production, from the gas market
model) as inputs from the restart file, and the integrated run takes natural gas demand and
prices from the NGMM, which is AIMMS. In a standalone run these come from the reference restart.

## What the task should become

Not a port. Three options, in order of effort:

1. **Run EIA's HSM as is** against `cb2026` restart inputs and check that it reproduces the
   OGSM arrays in the shipped `restart.npz`. This is the oracle: Python run against Python.
   Needs `pyfiler1` or a thin replacement over `src/nems_open/snapshot.py`.
2. **Wrap it** as `src/nems_open/ogsm/` with a price-in, production-out call, and replace
   `supply_standin` for oil and gas production. Vendor the HSM code (Apache 2.0, NOTICE).
3. **Speed and levers.** HSM is slow and pandas heavy. Only worth doing if the game needs it
   per turn.

Open question for the orchestrator: go with 1 and 2? Nothing in this lane needs the Fortran
oracle, so the `ogsm` target in `oracle/` is not added.
