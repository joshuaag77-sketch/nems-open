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

## Running the tests

Install `pytest-xdist` once (`pip install pytest-xdist`). Then:

```bash
export NEMS_UPSTREAM=/path/without/spaces/nems-upstream
python -m pytest -n auto --dist loadgroup          # everything, in parallel
python -m pytest -m comm -n auto --dist loadgroup  # one module: comm, resd, tran or ind
python -m pytest -m "not slow" -n auto --dist loadgroup   # skip the minutes-long files
python -m pytest tests/test_commercial_report.py   # one file, no xdist needed
```

Markers come from the file name (`tests/conftest.py`). `slow` marks the files that take minutes on their own (CDistGen, commercial technology choice, the residential full-year chain).

Under `--dist loadgroup` the tests of one file stay on one worker, because they share module-level caches. A file whose years are independent sets `XDIST_BY_YEAR = True` at module level; then each year is its own group and the nine test years spread over the workers. Set it on any new per-year test that is slow. Without xdist (plain `pytest`) nothing changes.

The long pole is the residential full-year chain (`full_run`, about 3 minutes, sequential by nature). Set `OMP_NUM_THREADS=1` when running many workers so numpy does not oversubscribe the CPU.

## Writing a test for a new port

If your port is called as `port(inputs, year)` and returns something with named outputs, the test is a few lines (`tests/oracle_harness.py`):

```python
from oracle_harness import oracle_test
from nems_open.commercial.consumption import consumption

XDIST_BY_YEAR = True
oracle_test(globals(), tag="cn", port=consumption, outputs=["enduseconsump", "cmeffind"])
```

It loads `<tag>_in` for each test year, calls the port, and compares each named output with `<tag>_out` within 1e-4, one parametrized test per year and output. Options when the plain version does not fit: `module` ("resd"), `inputs(before, after, year)` to add inputs the routine sees from other dumps, `select(obj, name, year)` to compare one year or a subset of regions, `call` and `get` for other calling shapes. See `tests/test_commercial_service_demand.py` (inputs and select) and `test_commercial_consumption.py`. Hand-written tests stay fine for routines that do not fit.

## Good first issues

The file readers. Each one reads one EIA input file into arrays the oracle already dumps, so the test is just "same arrays". Small, self-contained, and a good way to learn the codebase.

## Style

Plain Python and numpy. Comments say why, not what. Float32 arithmetic where the Fortran uses REAL*4, or the last digits won't match.
