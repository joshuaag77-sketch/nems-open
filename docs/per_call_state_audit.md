# Per-call state audit: does a module's answer depend on how often the loop calls it?

## Why this matters

EIA's industrial code grows biomass steam from a lag and writes the result back into that lag on every call (ind.f 8419-8421). So the state compounds once per call, not once per year. EIA's run calls each module a fixed number of times a year. Our coupled loop calls a module once per iteration, up to 21 times a year (maxitr 20 plus the final pass), so the same code drifted: industrial biomass reached 2.85 quads in 2050 against EIA's 1.56 (docs/industrial_biomass_steam.md).

This audit looked for every other place where our answer depends on the number of calls when EIA's would not, and fixed the ones that do.

## How many calls EIA makes

`nems_flow.py` (nsolve) runs CURITR 1 to MAXITR, then one more pass with FCRL = 1. Iteration 1 can never pass the convergence test, so a year always takes MAXITR + 1 passes. cb2026 sets MAXITR = 2, so every module in the loop is called 3 times a year: CURITR 1, 2 and 3, with FCRL = 1 on the third. After the loop, IDM, HSM, NGMM and CCATS get one more call with NCRL = 1 (step d), then EPM runs.

The cb2026 restart confirms it: it ends 2050 with MAXITR 2, CURITR 4 (after three passes), FCRL 1, NCRL 1.

This corrects the earlier note that EIA calls ISEAM twice a year. Twice is what the industrial oracle driver does (oracle/driver_ind.f90, `iters = 2`), not what EIA's integrator does. `converge.EIA_CALLS = MAXITR + 1 = 3` now holds the count, and the biomass steam cap uses it.

## Calls a year, EIA against ours

| Module | EIA (cb2026) | Ours | Per-call state found | Verdict |
|---|---|---|---|---|
| Residential (RDM) | 3 | up to 21 | none; reports gated on iteration 2 | reports moved to end of year |
| Commercial (CDM) | 3 | up to 21 | PITC shift ratchets on every call; ifwd reset on CURITR 1 missing; report on iteration 2 | fixed |
| Industrial (IDM) | 3 + NCRL | up to 21 + NCRL | biomass steam (fixed before, cap now 3); CALIBRATE after iteration 2; stand-in buffers scaled on every call | fixed |
| Transportation (TDM) | 3 | up to 21 | HDV GHG credit bank; truck payback curve history; FEM OLD_PMAX; air load-factor sums; a residual drift | fixed (whole state held from call 3) |
| EMM: dispatch LP, capacity LP | 3 (ECP on CURITR 1) | up to 21 (capacity solved once a year) | none | clean |
| EMM: EFP and LDSM | 3 | up to 21 | none; books roll on CURITR 1 only, as in EIA | clean |
| Coal (CMM, AIMMS) | 3 | up to 21 | iteration set has 7 elements; production lag is a damped fixed point | iteration capped; lag left as is |
| NGMM (AIMMS) | 3 + NCRL | up to 21 + NCRL | none; next-year roll only on NCRL | clean |
| NGMM stand-in market | n/a | settles once a year | none | clean |
| LFMM (GAMS) | 3 (builds on FCRL) | 2 solves (CURITR 1 and FCRL) | none | clean; one solve fewer than EIA |
| LFMM stand-in, supply stand-in | n/a | every iteration | none | clean |
| HSM | CURITR 1, FCRL, NCRL | once per cycle, between cycles | none in-year | structural difference, not a call-count bug |
| Macro (FRB/US) | 3 (MAC) | once per cycle | none in-year | structural difference |
| Demand stubs, EV lever | n/a | every iteration, lag committed once a year | none | clean |
| Renewables, HMM, CCATS, EPM | 3, or NCRL | not called | n/a | not in our loop |

## What we found and fixed

### Industrial

- Biomass steam (fixed before this audit in 1c6b108). The cap on compounding was 2, from the oracle. It is now `EIA_CALLS = 3`. Two calls still reproduce the oracle exactly. From the 2050 dump, a third call moves that year's QBMIN from 1.523 to 1.526 quads (0.2%). Compounded from 2027 that is a few percent by 2050, in line with the earlier emulation (2 to 3% above the restart).
- CALIBRATE ran at the wrong time. EIA runs it once, in the NCRL call after the last iteration (ind.f 1099). The coupled loop ran it after iteration 2 and then kept calling IND, and each later call rebuilt the buffers uncalibrated. So next year started from call N's uncalibrated buffers, and the report tables (`*con`, `xelinshr`, the mining additions) were call N's before CALIBRATE. Now `IndustrialSector.end_year` runs it once, after the year's last call, through a new end-of-year hook (`run_demand.end_year`, called by `PortedSectors.end_year` and `DemandRunner.run_year`, and passed to worker processes). The FCRL flag inside IND is now set from call 3, as in EIA; only an unused SEDS total reads it.
- The coal and electricity calibration overflow. CALIBRATE_COAL_ELEC multiplies each industry's saved steam fuel, process fuel and byproduct copies (ENSQTY, ENPMQTY, BYPBSCM) by its benchmark factor and saves them back. EIA's process models rebuild those arrays on every call, so EIA applies the factor once to fresh values. Our stand-in for the five process-flow industries never rebuilds them, so the factor compounded on every call and across years: h to the power of calls times years. At 6 calls a year that overflowed float32 in 2041 (`enpm[7] * h`). Nothing reads these arrays for the stand-in industries, so the stand-in now zeroes them on each call. That is honest: it does not compute them.

### Transportation

TRAN changes some of its state on every call in EIA's code too, so EIA's answer is the one after 3 calls. The audit found:

- The heavy-duty GHG credit bank (tranfrt.f 2572-2629, a SAVEd local). A short averaging set spends past years' banked credits on every call, so each extra call drained the bank again and forced more zero-emission truck sales.
- TRUCK_PBK's curve history (tranfrt.f 1325-1347). A technology adoption curve that starts on any call stays started, so more calls gave more chances for a passing price to start one early.
- FEM's OLD_PMAX (tran.f 4197), the most a fuel economy technology has penetrated, carried from call to call.
- The air load-factor sums LFDOMAVG and LFINTAVG (tranair.f 612-613), added to on every call and never zeroed. Report only (TRTRAVLD); EIA's value is 3 calls' worth.

Holding only the bank, the curves and the air sums still left a slow drift with fixed inputs: from call 3 to call 21 in 2027, gasoline moved 0.46 trillion Btu of 15,502 and hydrogen 5e-4 of its value, always the same way. So `TransportationSector` now holds TRAN's whole state (every array in its state and saved locals, about 330 MB) with `converge.EiaCalls`: from call 4 on, each call starts from where EIA's third call started and runs on the loop's latest inputs. Call N is EIA's third call, exactly.

### Commercial

- PITC (comm.f 5607-5610). On a year's first call EIA restarts `ifwd` from last year's shift; the port never did. On later calls the shift ratchets down from the previous call's leftover, in EIA too. Both are now EIA's: the reset on CURITR 1 (`technology_choice.pitc_shift`) and the ratchet held at call 3. PITC is idle in every AEO2026 year (all shifts 0), so cb2026 results do not change. A high-price case would move technology availability.
- COMReport (comm.f 820, last year's FCRL pass) ran on iteration 2. It now runs once after the last call. Report only.

### Residential

- No per-call state. Every quantity is rebuilt each call from earlier years and this call's prices. The CURITR 1 gates (lighting snapshot, ZIP lag roll, EFANUEC) match EIA's.
- NHTSHR and RESDRP2 (resd.f 594 and 16696, last year's FCRL pass) ran on iteration 2. They now run once after the last call. Report only.

### Coal

- coal.ams sizes its iteration set to MaxIter = 7 and keys the solve status by `Element(It_, curitr)`. From call 8 the element is empty, so the result message reads blank, not 'Optimal': the CMM skips its reporting totals and runs its infeasible fallback (empty the variables, re-solve) on a good solve. `AimmsCoal.begin` now sends every later iteration as 7. The CMM uses CURITR otherwise only to tell iteration 1 from later ones.
- The CMM's production lag (qprods, LAG_PROD3) is reset on iteration 1 and then follows the previous call's production. More calls bring it closer to its own fixed point. It does not compound. We leave it, as we leave the relaxation itself.

## Tests

Each test runs a module more often than EIA and checks it gives EIA's 3-call answer.

- `tests/test_converge_eia_calls.py`: EIA_CALLS is 3; EiaCalls holds state at call 3 for 4, 6 and 21 calls.
- `tests/test_per_call_industrial.py`: 6 calls give the buffers, report tables and QBLK rows of 3 (2040); the stand-in buffers stay zero and finite; through `IndustrialSector` with the coupled loop's numbering, 7 calls plus the end-of-year call equal 3 plus it.
- `tests/test_industrial_biosteam.py`: now 6 calls against 3; 2 calls still match the oracle.
- `tests/test_per_call_transportation.py` (slow): from the 2027 dump, 6 calls give the quantities, the bank, the curves, OLD_PMAX and the air sums of 3.
- `tests/test_per_call_commercial.py`: the CURITR 1 reset; 6 calls give the quantities and PITC state of 3; the report runs once.
- `tests/test_per_call_residential.py`: 6 calls give the quantities of 3; the reports run once.
- `tests/test_per_call_coal.py`: iterations past 7 reach the CMM as 7; 7 is coal.ams's MaxIter.

## What remains

- No coupled run has checked these fixes together. Expect industrial biomass a little above the 2-call figures in docs/industrial_biomass_steam.md.
- The coal stand-in calibration (`aimms_couple.reference`) was built from 2 CMM calls a year; EIA makes 3. Rebuilding it needs a full AIMMS reference run.
- With cycles > 1, the capacity expansion LP reuses cycle 1's builds (`ElectricityLP` is built once, outside the cycle loop). EIA re-solves ECP every cycle. This is a cycle question, not a call-count one.
- LFMM in GAMS solves twice a year (iteration 1 and FCRL); EIA solves on every call. HSM and FRB/US run per cycle, not inside the year. These change how fast prices settle, not how state compounds.
- The demand oracles (resd, comm, ind, EMM) run 2 iterations a year, transportation 3. Dumps made from 2-iteration runs carry 2-call history for any every-call state up to the dump year.
- Ported code not covered here: anything ported after this audit. The pattern to look for is a value written back on every call and read on the next one, outside a CURITR 1 or NCRL gate.
