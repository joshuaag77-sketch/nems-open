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

## Result of the standalone run (2026-11-06)

`src/nems_open/ogsm/run_hsm.py` runs EIA's HSM from NEMS_UPSTREAM on the cb2026 restart, through a pure
Python `pyfiler1` stand-in (`pyfiler1.py`). One core, 9 minutes for 2024 to 2050, no solver.
`compare.py` checks its OGSMOUT arrays against the restart.

- 2020 to 2025: equal to the restart (history and STEO).
- From 2026 it diverges. US dry gas production (ogngprd) falls to 36,000 by 2050 where EIA's run
  rises to 104,700. Crude (ogcoprd) falls to 16.7 where EIA has 23.8. 50 of 95 arrays match
  to 1e-4 (the ones HSM does not rewrite), 40 are off by more than 1%.
- Likely cause, not yet shown: the standalone loop in `hsm.py` is marked as a debug path. In a
  real NEMS run HSM is called each year and iteration with expectations and project lists carried
  in `fcrl_var.pkl` and `ncrl_var.pkl`, and prices come from converged NGTDM and LFMM passes. The
  standalone loop may not feed the same price paths or state.
- So the `ogs='hsm'` switch is not built: a switch that cuts gas supply by 65% by 2050 would be
  worse than the stand-in, which reproduces EIA's cases.

Next step if this continues: log the price arrays HSM reads each year (wellhead gas, WTI) and diff them
against the restart, then the pickled expectations.
