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

## Why it does not reproduce (checked 2026-11-06)

Not the prices. The wellhead prices HSM writes (ogngwhp, ogpcrwhp, ogcowhp) are within 0.1% to 0.7%
of the restart's, so it is working from the right NGTDM and oil price paths.

The break is in drilling. Total wells (ognowell) match to 2025 and then HSM drills about twice as many in
2026 (36,257 against EIA's 18,796), keeps that to 2045, and ends below EIA in 2050. Gas and crude
fall away from EIA's from 2026 too. So the first wrong thing is the drilling step in the first
year after the STEO years, not anything the other modules feed in.

What the standalone path does differently from a NEMS run, all in `models/hsm/module_unf.py`:
- Line 634 forces `param_ncrl = 0` with the comment that NGMM cannot run offline. So the reporting
  loop is skipped: no "realized production" adjustment (`onshore.py:7981`, `8224`).
- The FCRL and NCRL pickles that carry expected production, projects and drilling between iterations
  are only read when `integrated_switch` is True (lines 696-701). Standalone starts each year
  from the setup state with `current_iteration` left unset.
- The year loop in `hsm.py` is labelled a temporary debug path.

Conclusion: EIA's standalone HSM is a debug run, not a replay of their integrated result. A match
needs the carried state from the integrated loop (the pickles, ncrl=1 pass), which the restart file does
not hold. Next step if continued: run with `integrated_switch` on, iteration 1 then reporting, per
year, feeding it our own pickles. That is a larger job than a thin adapter. Until then keep
`supply_standin`; no `ogs` switch.

## Fixed (2026-11-10): HSM now reproduces cb2026 past the STEO years

The section above guessed wrong. The pickles and the ncrl pass were not the cause. Two standalone input
errors were:

1. EIA's `models/hsm/input/setup.csv` points standalone runs at `scedes.lowogs.csv`, the low oil and gas
   supply side case (OGTECH=30: technology 50% slower, side_case_adj 0.5, benchmarked to one STEO year
   instead of two). We were running the wrong scenario. `run_hsm.prepare` now rewrites the work copy to
   `scedes.cb2026.csv`.
2. `ognowell` (wells completed) is built with `+=` onto the restart value. A NEMS run zeroes it each year
   (`module_unf.py:976`); the standalone loop never reaches that line, so the reference run's own wells
   stayed in and every well counted twice (36,257 against 18,796 in 2026). `run_hsm.run` zeroes 2026 on.
   Zeroing `ogcruderef` too breaks the 2027 price weights (NaN in the offshore step), so it is left alone.

Result (`scripts/run_hsm_cb2026.py`, one core, 9 minutes; `compare.py`):

| | 2026 | 2030 | 2040 | 2050 |
|---|---|---|---|---|
| dry gas ogngprd, HSM / EIA | 77.4k / 78.2k | 78.0k / 82.1k | 94.5k / 93.1k | 106.9k / 104.7k |
| crude ogcoprd | 25.1 / 25.3 | 25.2 / 25.2 | 23.8 / 23.8 | 23.8 / 23.8 |
| wells ognowell | 18.0k / 18.8k | 19.0k / 19.8k | 23.2k / 23.6k | 26.8k / 28.1k |

Gas is within 5% every year, crude within 1%, wells within 5%. Of 95 arrays, 72 are within 1% and 54
within 1e-4. Left over: `ogjobs` is about 30% high (jobs appear tied to a cumulative well count), and
NGPL splits, `ogprdadof` and `ogqshlgas` are off by 5 to 30% in places. `ognglak` differs in one year
only: EIA's restart has 0 in 2030, which looks like an EIA artifact. Not worth chasing before the
`ogs='hsm'` switch; the switch itself is still not built.
