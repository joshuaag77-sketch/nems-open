# EIA's coal model in the loop: run(coal="aimms")

`run_model.run(coal="aimms")` (CLI `--coal aimms`) runs EIA's real Coal Market Module, `models/coal/MainProject/coal.ams`,
in AIMMS 25.5.7.1 once per loop iteration, and its delivered coal prices replace the supply stand-in's. Off by default.
Code: `src/nems_open/coal/aimms_couple.py` (the coupling) on `src/nems_open/coal/aimms_run.py` (run folder, input files,
entry point, diagnostics).

## How it runs

NEMS keeps the CMM open as an AIMMS library and, each iteration, writes `coal/toAIMMS/GlobalDataToAIMMS_<year>_<itr>.txt`
(every array in `coalputvars.txt`) and reads back `coal/fromAIMMS/GlobalDataToNEMS_<year>_<itr>.txt`. Here the same, with
no web service and no Fortran:

- One AIMMS process per cycle (`aimms.exe -Rserve_coal`, a small wrapper project). It waits for `coal/serve.txt`, runs
  the CMM for that year and iteration through `File_Call` (the CMM's own `Coal_API_Call` without the DEX request read),
  and waits again. The model keeps its lag state between calls, as in NEMS.
- The input file is cb2026's restart with the loop's values for this year: coal use (QBLK qclel, qclrs, qclcm, qclin,
  qclrf, qclsn, qmcin), the power sector's coal by coal region and plant type (COALEMM QCLCLNR) and EMM's unit-level coal
  burn (EMM_CL_BTUS) scaled to the loop's US qclel, and the fuel prices the CMM reads (pelin, pdsin, pdstr, prltr,
  prhtr, last iteration's coal prices). Written in EIA's own format (`aimms_util.write_aimms_input`): composite tables,
  columns aligned, the base year all years and later years their own slice.
- Out: MPBLK pclel, pclin, pclrs, pclcm, pclsn, pmcin, with the supply side's carbon adders and levers on top, and the
  CMM's production (COALREP COALPROD2) in `RunResult.coal`.
- 2024 (the CMM's base year) to start_year - 1 run first on cb2026's inputs.
- Calibration: each price is multiplied by EIA's restart value over the CMM's own on cb2026's inputs (`reference.pkl`,
  built once by `python -m nems_open.coal.aimms_couple`, about 5 minutes), so the baseline is EIA's and moves are the CMM's.
- Not passed: the carbon tax the CMM reads (EMETAX) stays cb2026's (zero). A carbon price reaches coal through
  power-sector switching (less coal burned) and the carbon adders on delivered prices.

Run folder `~/dev/oracle-cache/coal-aimms` (`NEMS_COAL_RUN`). AIMMS jobs go one at a time under `HEAVY.lock`
(`scripts/with_heavy_lock.sh`). Each CMM call takes about 7 s (2027-2050 with three iterations a year: about 9 minutes).

## Checks (cb2026, stub demand, 2027-2050)

| | 2027 | 2030 | 2035 | 2040 | 2050 |
|---|---|---|---|---|---|
| CMM production in the loop, Mt | 485.5 | 399.6 | 220.6 | 184.9 | 139.0 |
| EIA (restart COALPROD2) | 485.0 | 399.6 | 221.5 | 185.2 | 138.9 |
| US power coal price, loop, 1987$/MMBtu | 1.017 | 1.013 | 1.032 | 1.090 | 1.003 |
| EIA | 1.021 | 1.014 | 1.032 | 1.096 | 1.018 |

Policy response, carbon price 50 $/t CO2 from 2027: coal burned for power falls 35% (2027) to 70% (2050), and the CMM's
production falls 123 Mt in 2027 and 107 Mt in 2030. In 2035 the cut lands on Powder River (-13 Mt) and Interior (-12 Mt),
Northern Appalachia -4, Central Appalachia -2, other West -5. The delivered power coal price before the carbon adder rises
about 1%: cheap Powder River coal leaves the mix.

The CMM reproduces the restart from 2027; the base and STEO years 2024-2026 differ by a few percent (EIA's restart is
the end of five cycles of iterations).

## Open points

- STEO table: NEMS rewrites coal/clsteo.txt from steovars.csv before every run (EXC = 1), and the repo's copy is an
  older vintage. The checks above used the repo's copy. `aimms_run.prepare(steo="regenerate")` writes it as NEMS does
  (EIA's steo_load.py); it changes 2024-2027 and is not yet checked, so it is off.
- Solve status, cb2026 inputs: Optimal every year 2024-2032, both iterations (status scan). One smoke test in a pytest
  temporary folder reported 2025 as Infeasible with the same calls; not reproduced in a run folder and not explained.
  The showreel log records the status of every solve, so a repeat would show.
- Convergence of the loop with coal="aimms" (EIA's test, final loops) was not checked separately.

## The open-solver fallback

`coal/lp.py` (HiGHS) remains the open-solver path; it is not wired into run_model. docs/coal_lp.md has where it stands
against this reference: inputs equal EIA's, Interior high and Powder River low in 2027-2035.

## Showreel log

Every CMM solve appends one JSON line to `~/dev/aimms-showreel/coal.jsonl` (`NEMS_SHOWREEL`): time, year, cycle,
iteration, the math program's own size (rows, columns, nonzeros), solver, status, objective, simplex iterations and
solver time, and headline outputs (production by basin, Powder River share, power, industrial and coking coal prices).
The raw AIMMS message log is copied next to it when a process closes, and the 2030 input and output files are kept once
(`coal_sample_2030/`). The log reads results; it never changes them.
