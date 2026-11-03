# Draft issues for new contributors

Written from the work that is really left. Each has context, the files to start in, and a done test that a
script can check. Labels: **good first issue** (a few days, one file or two, the pattern already exists) or
**needs energy modelling** (you need to know how power, coal or demand models work). Not yet created on GitHub.

Before any of them: read [CONTRIBUTING.md](../CONTRIBUTING.md). A port is done when it matches the oracle
within 0.1% for every region, type and year it covers; EIA's odd behaviour is kept and written up in SCOPE.md.

---

## 1. Run the tests on GitHub Actions
**Labels:** good first issue

**Context.** Nothing runs the tests on a push. Most tests need EIA's checkout (`nems-upstream/`, about 1 GB,
Apache 2.0) and skip when the oracle has not run, so a plain CI run can still check a lot.

**Where.** `.github/workflows/` (only `pages.yml` today), `pyproject.toml` (dependencies are listed),
`tests/conftest.py` (markers `comm`, `resd`, `tran`, `ind`, `slow`).

**Do.** Add a workflow that clones `EIAgov/NEMS` (shallow, to `nems-upstream`), installs the package with
`pip install -e ".[test]"`, and runs `pytest -m "not slow" -n auto --dist loadgroup`. Cache the clone.

**Done when.** The workflow is green on a pull request, finishes in under 20 minutes, and the README says
how to read its result. Tests that need oracle dumps show as skipped, not failed.

---

## 2. Print COMReport's tables
**Labels:** good first issue

**Context.** `COMReport` in `comm.f` writes tables to a text file (`KRPT.txt`) as well as leaving national
totals in COMMREP. The port (`src/nems_open/commercial/report.py`) computes only the totals. The oracle writes
the real file, so you have the answer.

**Where.** `src/nems_open/commercial/report.py`, `tests/test_commercial_report.py`, the oracle's
`KRPT.txt` (in `oracle/run/out/` after a run), and the Fortran FORMAT statements in
`nems-upstream/source/comm.f` from the `COMReport` entry.

**Done when.** A function writes the same tables as the oracle's `KRPT.txt`: every number equal to the
printed digits, same row order. A test diffs the two files.

---

## 3. Add the commercial levers to the demo
**Labels:** good first issue

**Context.** The commercial model now takes real-input levers: a building code (new buildings' heating and
cooling shell factors) and a minimum equipment efficiency (`Policy(commercial=CommercialLevers(...))`,
`python -m nems_open.run_model --shell-code 0.2 --standard 2:3.5:2030:1`). The demo page has carbon price,
EV share and building energy only.

**Where.** `web/app.js`, `web/index.html`, `scripts/precompute_real.py` (the runs with the ported modules),
`src/nems_open/commercial/levers.py`, `docs/run_model.md`.

**Do.** Add a "commercial building code" control (0, 10, 20, 30%) to the real-module set, run the scenarios,
and show it in the charts and the share link.

**Done when.** Moving the control changes commercial gas use in the right direction (down), the address bar
holds the setting, and a reload restores it. The page still opens from disk.

---

## 4. First-call input readers for transportation
**Labels:** good first issue (one reader at a time)

**Context.** Commercial and residential now start from EIA's input files with no oracle dump. Transportation
(`tran*.f`, about 18,000 lines) is being ported on a branch and still starts from the oracle's state. Each
file reader it calls once on the first call is a small piece: read a text file or a sheet into arrays the
oracle already dumps.

**Where.** The pattern: `src/nems_open/commercial/inputs.py`, `kparm.py`, and
`tests/test_commercial_inputs.py` (one test per reader, compared with `frd_out`). The Fortran:
`nems-upstream/source/tran*.f`, `nems-upstream/input/tdm/`.

**Do.** Pick one reader, add the oracle probe (`oracle/hooks.py`, `PROBES`), write the reader keeping the
Fortran's names and its list-directed read behaviour (`src/nems_open/fortran_io.py`), and test it.

**Done when.** Every array the reader fills equals the oracle's dump to float rounding (1e-6).
Blocked until the transportation branch is on main.

---

## 5. Finish the industrial year loop
**Labels:** needs energy modelling

**Context.** `ind.f` is 20,000 lines. Three routines are ported (CALBSC, CALSTOT, INDTOTAL, the boiler and fuel
accounting inside ISEAM) but nothing yet carries their results to QBLK, so industrial fuel use still comes
from the oracle's fixed output and does not respond to prices.

**Where.** `src/nems_open/run_demand.py` (`IndustrialSector`), the industrial branch, `tests/test_run_demand_industrial.py`.
Next in the call order: MODCAL, NATTOTAL, WRQTY, WEXOG (history and STEO benchmarking).

**Done when.** `IndustrialSector.iteration` runs the ported routines, `quantities()` returns QBLK rows from
them, and the rows match the industrial oracle within 0.1% for 2025, 2030, 2040, 2050. Building the industrial
oracle needs gfortran on Linux or Windows (see the oracle notes in SCOPE.md).

---

## 6. Port the international module (`world.f`)
**Labels:** needs energy modelling

**Context.** `world.f` is 3,110 lines, no paid solver, no AIMMS or GAMS. It is the smallest module that
has not started. It writes the INTOUT block (Brent and WTI prices among others), which the model now takes
from the restart file.

**Where.** `nems-upstream/source/world.f`; copy the layout of `src/nems_open/residential/` and the oracle recipe
in SCOPE.md: add a module entry to `oracle/gen_oracle.py` and `oracle/hooks.py`, build the oracle, dump state
before and after each routine, port, test.

**Done when.** Each routine matches its oracle state within 0.1% for the nine test years, and SCOPE.md has a
status row for it.

---

## 7. Close the capacity-expansion misses
**Labels:** needs energy modelling

**Context.** The capacity LP (`src/nems_open/emm/capacity.py`) builds and retires plants year by year. Against
EIA's reference run 22 cells of the result table are marked MISS (2027, 2030, 2035): wind and solar are too high
early, gas turbines are far too low, nuclear is built when EIA builds none, coal retires too early in 2027.
The assumptions that are ours, not EIA's (build limits, capacity credits, a 6.5% discount rate), are listed in
`docs/capacity.md`.

**Where.** `src/nems_open/emm/capacity.py`, `capacity_report.py`, `tests/test_emm_capacity.py`,
`docs/capacity.md`, `docs/capacity_results.md`.

**Do.** Pick one family (retirements, capacity credit by technology, or the cost of capital from the finance
routines already ported in `src/nems_open/emm/efp/`) and replace our assumption with what EIA's code or inputs say.

**Done when.** The number of MISS cells in `docs/capacity_results.md` falls from 22 to 12 or fewer with no new
ones, and the write-up says which assumption changed and why.

---

## 8. Make batteries cycle like EIA's
**Labels:** needs energy modelling

**Context.** In the dispatch LP batteries cycle about a third as much as EIA's: net discharge less charge is
-5.3 TWh in 2030 against EIA's -15.5, -5.7 against -19.8 in 2040 (`docs/trade_storage.md`). EIA's price spreads
come from 24 vertical load segments; ours come from 36 typical days of 8 three-hour blocks, and are narrower.

**Where.** `src/nems_open/emm/dispatch.py`, `load.py`, `docs/trade_storage.md`, `tests/test_emm_dispatch.py`.

**Do.** Test whether the time resolution is the cause (an hourly day for a few regions), and if so change the
representation or add a spread-seeking term. Keep run time under about a minute a year.

**Done when.** Battery net generation in 2030, 2040 and 2050 is within 25% of EIA's, and total generation
and power CO2 stay within where they are now (`docs/dispatch_results.md`).

---

## 9. Coal: electric-power price and the regional split
**Labels:** needs energy modelling

**Context.** The reduced coal LP (`src/nems_open/coal/lp.py`) matches EIA's national production within about 5%
but not by region (some are off 10% to 50%), and its delivered price for electric power is 40% high in 2025
and 2026. The likely cause is the STEO band shadow prices entering the demand duals. It leaves out most of
the 125 equation families in EIA's AIMMS model: second-tier electricity transport and its price rule,
contracts, sub-bituminous and lignite diversity limits.

**Where.** `src/nems_open/coal/lp.py`, `supply.py`, `transport.py`, `docs/coal_lp.md`, `docs/coal_plan.md`,
`tests/test_coal_lp.py`. EIA's model: `nems-upstream/models/coal/MainProject/coal.ams`.

**Do.** Add one family, say the sub-bituminous and lignite diversity limits, as a constraint set, with a test.

**Done when.** The delivered electric-power price (PCLEL) is within 10% of EIA's for 2025 to 2030 (today
1.49 against 1.05 in 2025), or the write-up shows why the added family did not move it.

---

## 10. Replace the placeholder demand elasticities
**Labels:** needs energy modelling

**Context.** Industrial and transportation demand are stubs: EIA's reference fuel use moved by a fitted price
elasticity. For some fuels the fit has the wrong sign or the price barely moves across EIA's cases, so a
placeholder (-0.3, or -0.2 in transport) stays: industrial propane, coal and metallurgical coal, jet fuel and
transport natural gas (`docs/demand_elasticities.md`).

**Where.** `src/nems_open/fit_elasticities.py`, `src/nems_open/demand_elasticities.json`,
`src/nems_open/demand_adapter.py`, `docs/demand_elasticities.md`.

**Do.** Find evidence for each placeholder (EIA's own side cases with a different split, published elasticities
for that fuel and sector) and replace it, or separate the non-price drivers (jet fuel follows travel, not its price).

**Done when.** No row uses the generic placeholder, each replacement cites its source in
`docs/demand_elasticities.md`, and `tests/test_run_model.py` still passes.

---

## More ideas, not yet written up
- Alaska and Hawaii are not in the power model: they are 45% of EIA's 2025 oil use for power, and the restart
  file has no capacity or prices for them (`docs/dispatch_fixes.md`).
- A simple open macro driver to replace EIA's licensed macro model, so GDP can respond to energy prices.
- Price-responsive Canada and Mexico electricity trade: the supply-step table EIA ships
  (`V_EMM_CANSPLY_STEPS`) is not read by any routine in the Fortran in the repo, so its meaning is unknown
  (`docs/trade_storage.md`).
- Per-unit retrofit and retirement years for coal: the restart arrays that would hold them are all zero, which
  limits what the 2040 coal result can show (`docs/dispatch_fixes.md`).
