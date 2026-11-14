# Policy convergence

The integrated runner now defaults to `maxitr=20`, while keeping EIA's convergence
tests, per-variable relaxation factors, and final reporting pass unchanged.
`run(..., maxitr=2)` and `--maxitr 2` still reproduce cb2026's iteration limit.
The constants and control implementation in `nems_open.converge` remain unchanged.

## Reproduction and cause

The interrupted `scripts/check_convergence.py` run used stub demand, stand-in
supply, EV sales share 1.0, and Brent at twice the reference price. Repeating it
over 2027-2050 with the old default gave:

| Case | Stable years before | Stable years after | Passes/year after |
| --- | --- | --- | --- |
| Reference | 24/24 | 24/24 | 3 |
| High EV | 24/24 | 24/24 | 3 |
| High oil | 0/24 | 24/24 | 6 |

The EV failure reported in the task was not reproduced in this configuration.
Residential and commercial ports were also checked serially over 2027-2029;
reference and high EV both passed in all three years with the old limit, while
high oil failed in all three.
With the new default, all three ported cases pass in every checked year;
reference and high EV take three passes per year, and high oil takes six.

High oil stops before its price-demand feedback has settled. Iteration 1 demand
sees reference prices, then supply applies the Brent shock. On iteration 2,
industrial and transport petroleum use falls, moving product prices back down
along the fitted supply curves. Failing demand variables include `qdsin`,
`qdstr`, `qjftr`, `qpfin`, and, from 2028, `qasin`. By iteration 3 these quantity
tests pass, but `MPBLK/ppfin` (industrial petrochemical feedstock price) still
fails its 1% fractional test. Its supply curve has a demand coefficient of
0.85332 and its price relaxation factor is 0.5. The remaining adjustment
therefore needs further iterations.

In 2027 the largest raw price residual falls from 5.47% on iteration 2 to 2.57%
on iteration 3; in 2050 it falls from 6.04% to 2.84%. This is a decaying
adjustment cut short by the iteration limit, rather than evidence of a divergent
oscillation. The large initial `plpin` fractional residual is not the final
failing variable: EIA also checks absolute changes and matching quantities.
With more iterations, the 2027 price residual keeps shrinking: 1.19% on pass 4,
0.553% on pass 5 (passing), and 0.256% on the confirming pass 6. The US `ppfin`
values after relaxation are 9.095330, 8.853169, 8.741020, 8.689172, 8.665222,
and 8.654163 in 1987 dollars/MMBtu. Demand `qpfin` drops from 348.200 to
326.572 trillion Btu after the shock, then recovers toward 327.999 as prices
ease. Both sequences settle; neither shows sustained oscillation or drift.

The old default borrowed cb2026's `MAXITR=2`, which permits just two iterations
plus a forced final pass. EIA uses five whole-run cycles; this runner defaults
to one cycle starting from the converged reference. That is enough for the
reference and small shocks, but not the doubled oil price. A larger cap lets
the existing control stop on convergence, without loosening any tolerance,
changing the supply curves, or adding a policy-specific numerical method.

## Repeating the check

The full 2027-2050 stub reference was saved before editing the runner and compared
against the new default. Every price, quantity, and sector CO2 array matched
exactly, with maximum absolute difference **0** (required tolerance `1e-9`).
The serial ported reference over 2027-2029 also matched its pre-change snapshot
exactly across all three output groups, with maximum absolute difference **0**.

In PowerShell, with the repository virtual environment:

```powershell
$env:PYTHONUTF8 = '1'
$env:PYTHONPATH = 'src'
.venv/Scripts/python.exe scripts/check_convergence.py --maxitr 2 --save-reference data/convergence/reference-before.npz --trace
.venv/Scripts/python.exe scripts/check_convergence.py --compare-reference data/convergence/reference-before.npz --trace --track MPBLK/ppfin QBLK/qpfin
```

Use `--end 2029 --ported residential commercial` for the short ported check,
with a separate reference snapshot. The script forces serial demand execution
and sets numerical-library thread limits before importing NumPy. `--track`
prints US values after each supply pass; reported price residuals are measured
against raw supply outputs, before relaxation.

Local logs and reference snapshots are in ignored `data/convergence/`, including
the interrupted log moved from the repository root. They are not committed.
The regression tests are in `tests/test_run_model_convergence.py`: both policy
paths must pass the EIA tests and a confirming final pass; all reference prices,
quantities, and sector CO2 arrays must match the old cap with `rtol=0, atol=1e-9`;
an explicit cap of two must still stop and report the oil-price failure.

## Test result in this checkout

Only `tests/test_run_model*.py` was run, including the new regression file.
Demand workers were disabled, numerical-library thread limits were set to one,
and the test launcher would limit HiGHS to one thread when available. Automatic
pytest plugin loading was disabled because an unrelated installed LangSmith
plugin failed on incompatible Pydantic versions.

Result: **19 passed, 9 skipped, 1 failed, 11 errors**. All four new convergence
checks passed. The failure and all 11 errors are in `test_run_model_lp.py` and
raise `ModuleNotFoundError: No module named 'linopy'` before dispatch can run.
This virtual environment also lacks `highspy` and `xarray`. Installing these
declared dependencies was attempted, but network access to PyPI was denied;
there were no cached copies in the checked local package caches. The LP checks
therefore remain unvalidated in this environment. The complete test output is
in ignored `data/convergence/tests.log`.
