# Contributing

Pick an open issue, comment that you're taking it, and open a pull request when its tests pass.

## The done rule

A port is done when it matches the oracle within 0.1% (in practice we get float rounding, about 1e-6) for every region, building type and year it covers. No exceptions for "close enough", and no fixing EIA's quirks: if EIA's code does something odd, the port does the same thing and the quirk goes in SCOPE.md.

## How to port a routine

1. Read [SCOPE.md](SCOPE.md), especially the oracle section.
2. Add the routine to `TARGETS` in `oracle/hooks.py`: the line in `COMM` that calls it, the label at its end, and its private arrays. Rebuild and run the oracle. You now have EIA's state before (`<tag>_in`) and after (`<tag>_out`) the routine for 9 test years.
3. Write the port in `src/nems_open/<module>/`. Keep the Fortran's variable names and loop order, and index with `FArray` so each line can be checked against the original.
4. Write a test in `tests/` that feeds the port the "before" state and compares with the "after" state. Look at `tests/test_commercial_service_demand.py` for the pattern.
5. Update the status table in SCOPE.md.

## Good first issues

The file readers. Each one reads one EIA input file into arrays the oracle already dumps, so the test is just "same arrays". Small, self-contained, and a good way to learn the codebase.

## Style

Plain Python and numpy. Comments say why, not what. Float32 arithmetic where the Fortran uses REAL*4, or the last digits won't match.
