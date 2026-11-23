# Industrial biomass: why it ran 73% high, and the fix

## What the report showed

`docs/fidelity/old-342aa01-reference.md` put Table 2 industrial renewable energy (QTRIN) at 3.05 quads in 2050 against EIA's 1.76. That was the worst line in the report.

QTRIN is hydro plus biomass plus waste (QHOIN + QBMIN + QMSIN). Hydro is zero in both runs. Waste (QMSIN) matches EIA every year. Hydrogen is not in QTRIN. The whole gap is biomass, QBMIN (wood, pulping liquor and other biomass burned by industry). Refinery biomass (QBMRF, added by util_refine.f90 line 91) is 2 trillion Btu and plays no part.

QBMIN, ours / EIA, in quads:

| | 2027 | 2030 | 2035 | 2040 | 2045 | 2050 |
|---|---|---|---|---|---|---|
| old-342aa01 run | 1.336 / 1.418 | 1.301 / 1.356 | 1.355 / 1.304 | 1.805 / 1.397 | 1.903 / 1.441 | 2.846 / 1.558 |

It starts 6% low, crosses EIA in 2034 and then climbs. It jumps in 2047 and 2049, the two late years that did not converge and so ran the most iterations. The gap is biggest in the South and West regions (Pacific 0.76 against 0.19 in 2050). Gas and electricity use stay within 2% of EIA, so this is not fuel switching.

## Root cause

CALSTOT in ind.f grows the steam that biomass boilers make by output growth, and stores the result back into the lag it started from:

```
ind.f 8419    biosteam = biosteamlag*(PRODVX/PRODVXLAG)
ind.f 8421    biosteamlag=biosteam
```

PRODVXLAG is rolled once a year, but BIOSTEAMLAG is overwritten on every call. So biomass steam compounds once per ISEAM call, not once per year. EIA's run calls ISEAM twice a year (the industrial oracle's two iterations), and EIA's numbers carry that quirk. Our coupled loop calls the industrial module on every loop iteration, up to 21 times a year. Each extra call multiplies biomass steam by another year of output growth. When output falls (2027 to 2033) that pulls biomass down, and when it grows it pushes it up, faster each year.

A second, smaller fault sat in the first model year. The industrial 'ys_in' dump is the top of the year's first iteration, but the coupled loop starts its first year at iteration 2 (the other sectors' dumps are the top of the final iteration). So ISEAM's first-iteration block, the yearly lag roll, never ran in 2027, and 2027 grew from 2025's lags.

We checked both by driving the ported module the way the coupled loop does, on EIA's own inputs. Before the fix, 2 calls a year from 2027 gave 1.469 quads in 2050 and 6 calls gave 1.676. The oracle gives 1.523.

## Fix

- `industrial/boiler_totals.py`: biomass steam starts from its value at the top of the year (`biosteamyr`) and compounds at most `ISEAM_CALLS = 2` times, once per call, with EIA's expression. Calls 1 and 2 give exactly EIA's numbers. Later calls hold EIA's two-call value instead of compounding further.
- `industrial/year.py`: `biosteamyr` rides in the industry-region buffers. It is set from BIOSTEAMLAG when a dump is loaded and at each yearly lag roll.
- `run_demand.py`, `IndustrialSector.iteration`: counts iterations from IND's own first call each year, so the first model year runs iteration 1 (the lag roll) like every other year.

After the fix, the same emulation gives the oracle's path to the decimal with 2 or 6 calls a year: 1.426 quads in 2027, 1.370 in 2040, 1.523 in 2050. EIA's restart has 1.418, 1.397 and 1.558. The 1 to 2% left over is the oracle's own gap to the restart. With 3 calls a year the oracle path would sit 2 to 3% above EIA, so EIA's own run used about 2.

Tests: `tests/test_industrial_biosteam.py`. Six iterations give the same biomass steam and the same QBMIN, QTRIN, gas, electricity and total as three (EIA's count; two before the audit). Two iterations still match the oracle. The coupled first year (iterations 2 and 3) matches two plain iterations from the same dump.

## Since then (docs/per_call_state_audit.md)

- EIA's integrator calls ISEAM three times a year, not twice: CURITR 1 and 2, then the FCRL pass (nems_flow.py; the cb2026 restart ends 2050 at CURITR 4). Twice is the industrial oracle's driver. The cap is now `converge.EIA_CALLS = 3`; two calls still reproduce the oracle.
- CALIBRATE now runs once, after the year's last call (EIA's NCRL call), through `IndustrialSector.end_year`.
- The 2041 overflow in CALIBRATE_COAL_ELEC came from the stand-in industries' saved steam and process fuel, scaled on every call and never rebuilt. The stand-in now zeroes them.
- The fix has not been through a full coupled run yet.
