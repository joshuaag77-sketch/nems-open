# Dispatch fixes: scarcity, oil, 2040 coal, fresh-worktree tests

Branch `emm-fixes`, off main 49abdea.

## 1. Scarcity hours: a demand bug, not missing imports
In 2025 to 2030 three western regions (CANO, CASO, NWPP) ran short in every summer day and set the $1,000/MWh price. I checked imports, storage and links first; none was the cause.

**Cause.** The restart's census arrays have 11 slots: nine divisions, California (slot 10) and the US. California is part of the Pacific division (slot 9); the nine divisions already add up to the US. `demand.census_sales_twh` added slot 10 to the Pacific again, so Pacific sales came out 56% too high (898 TWh against 575 in 2030) and the three western regions carried 268 TWh more load than EIA's generation there. A second error hid it: end-user generation was subtracted including rooftop solar, which the demand modules' purchases already exclude, so the national total looked about right.

**Fix.** Use the nine divisions; leave solar out of the end-user generation. National net load is now within 0% (2025) to 3% (2050) of EIA's generation, with the rest being storage losses the LP models itself. Unserved energy is zero in all four test years and the load-weighted marginal cost is 14.6 to 16.6 1987$/MWh (it was 57 in 2025 and 47 in 2030). The western regions' load is within 25% of EIA's; the remaining regional gaps (median 10%) are the census-to-EMM split, which trade absorbs.

This also helps the capacity results, which carried the same bug (their 2025 and 2026 reserve shortfall and unserved energy came from it).

## 2. Oil for power: 105 vs 10 trillion Btu → 105 vs 77
Two mechanisms in the plant file, both EFD's own:
- **Must-run oil steam.** Oil steam units flagged must-run (`T_MRUN` at or after the year) burn residual oil at their historical capacity factor whatever it costs. They make about 20 trillion Btu a year, flat; EIA's residual is 24, 21, 20, 20 in 2025, 2030, 2040, 2050. The model now takes these units out of dispatchable steam capacity and runs them flat: residual 21, 21, 20, 20.
- **Ignition fuel.** Every coal unit lists distillate as its second fuel, at 1% of Btu. The model burns 1% of coal Btu as distillate. This overshoots: EIA's realized distillate is 0.6 to 0.85% of coal fuel. Distillate comes out 84 vs 53 in 2025, 54 vs 28 in 2030. I did not shave the share to fit; the plant file says 1%.

Not in the model: Alaska and Hawaii (45% of EIA's 2025 oil; no capacity or prices for them in the restart) and the dual-fuel gas units' winter oil. Oil use against EIA's 25 regions: 105/77 (2025), 75/49, 35/28, 21/22 (2050). Oil is not scored.

## 3. 2040 coal: no input has per-unit retrofit years
`COALEMM/E_RY`, `E_PLTS` and `R_RY` (retrofit and retirement years) are all zero in the restart, and the plant file carries no retrofit date. The restart does have retrofit capacity by year (`UECPOUT/CAPCCS`): coal CCS goes from 0 in 2029 to 4.7 GW in 2030 to 16.3 GW in 2032, then stays at 16.2 GW through 2040.

That timing does not explain the miss. With a 12-year credit all three cohorts still earn 45Q in 2040 (they would expire in 2042 to 2044). What the reference shows: coal generation of 124 TWh a year from 2034 to 2038 (87% capacity factor on the 16 GW), then 63 TWh in 2040, 53 in 2042 and 21 in 2044. The LP matches the early plateau but not the decline. The decline is not tied to any input I can find: CCATS gives only the credit ($35/t) and a no-credit disposal price ($9.52/t), and its transport and storage cost arrays are zero in the dump. I left the model unchanged. 2040 coal stays a miss (+47% generation, +62% fuel).

## 4. EMM tests skipping in a fresh worktree
The 27 skipped tests need the EIA checkout (`nems-upstream/`, about 1 GB, git-ignored), which a new `git worktree` does not have. `paths.py` now looks for it in order: `NEMS_UPSTREAM`, `nems-upstream/` in the checkout, the same folder in the main checkout the worktree came from (via `git rev-parse --git-common-dir`), and sibling checkouts. In a fresh worktree of this repo all 126 fast EMM tests run (checked). If there is no checkout anywhere, they still skip with "EMM inputs missing".

## Result: dispatch table after the fixes (sales-based load with trade)
| | 2025 | 2030 | 2040 | 2050 |
|---|---|---|---|---|
| Coal generation | +7% | +6% | +47% MISS | none |
| Gas generation | -3% | +6% | +6% | +5% |
| Renewables | +11% MISS | 0% | -1% | +1% |
| Coal fuel | +10% | +7% | +62% MISS | none |
| Gas fuel | -12% MISS | -6% | -4% | -5% |
| Power CO2 | -2% | 0% | -5% | -9% |

4 of 28 scored cells miss (5 before; the 2030 and 2040 gas generation misses went with the demand fix). The 2025 gas fuel and renewables misses and the 2040 coal miss are unchanged.
