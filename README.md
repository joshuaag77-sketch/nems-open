# NEMS Open

An open Python rebuild of the U.S. Energy Information Administration's National Energy Modeling System (NEMS), the model behind the Annual Energy Outlook. The goal is a model anyone can run, read and change, ending in a browser version where you can play with America's energy system to 2050.

Not affiliated with or endorsed by EIA. EIA's code is Apache 2.0 and is not copied into this repo; the scripts read it from EIA's own checkout.

## How it works

NEMS is about 300,000 lines of Fortran, plus models that need paid solvers. We rebuild it one piece at a time, and every piece has to reproduce EIA's own numbers.

The answer key is the **oracle**: EIA's original Fortran, compiled with free gfortran and run outside NEMS on EIA's published AEO2026 reference run. It dumps EIA's internal state just before and just after each routine. A Python port passes when, fed the "before" state, it reproduces the "after" state. Where EIA's code does something odd, the port does the same thing and the quirk is written down in [SCOPE.md](SCOPE.md).

## What works today

- **Residential and commercial demand.** Both are ported routine by routine, start from EIA's input files (no oracle dump needed), and match the oracle to float rounding (about 1e-6) at every test year (residential 2020 to 2050, commercial 2019 to 2050). Commercial also takes policy levers that edit real inputs: a stricter building code, a minimum equipment efficiency, faster efficiency gains for office and other loads (`src/nems_open/commercial/levers.py`).
- **Electricity.** EIA's electricity inputs are read into numpy (`src/nems_open/emm/`). A dispatch LP (linopy and HiGHS) runs the 25 EMM regions over 36 typical days and matches EIA's total generation to 0 to 3% and nuclear and renewable generation to about 2%; coal and gas generation miss by up to 14% in some years ([docs/dispatch_results.md](docs/dispatch_results.md)). The load and finance routines (LDSM, EFP) are ported against EIA's oracle.
- **Coal.** A reduced coal distribution LP, priced from EIA's supply curves, is within about 5% of EIA's national production in 2025 to 2027 (regions miss by more; `src/nems_open/coal/`, [docs/coal_lp.md](docs/coal_lp.md)).
- **A full loop.** `run_model` alternates demand and supply year by year from 2027 to 2050 until prices settle, with a carbon price, an electric-vehicle share and building levers. Prices outside the ported pieces come from a supply stand-in fitted to EIA's own cases.
- **A demo.** `web/index.html` is a static page over precomputed runs: carbon price, EV share and building energy, with a trace of how one number came about.
- **Tests.** 69 test files. Anything that compares against the oracle is skipped until the oracle has run, so a fresh clone runs the rest.

## What is still a stand-in

Be careful quoting results from this model until these are replaced.

- **Industrial and transportation demand** are not ported. They move with fitted price elasticities (some are placeholders; see [docs/demand_elasticities.md](docs/demand_elasticities.md)). Industrial work is partly done on a branch.
- **Macroeconomy** is EIA's own path from the restart file. EIA's macro model uses a licensed S&P Global model, so we have none. Changing the policy does not change GDP.
- **Electricity capacity is fixed** at EIA's reference path in the dispatch LP. A carbon price moves coal to gas in dispatch but does not build or retire plants, so the response to a carbon price is stronger than a full model would show. The capacity-expansion LP exists but misses EIA on many technologies ([docs/capacity_results.md](docs/capacity_results.md)).
- **Coal** is a reduced LP: it leaves out most of the 125 equation families in EIA's AIMMS model ([docs/coal_lp.md](docs/coal_lp.md)).
- **Oil, gas, refining, renewable fuels, international and hydrogen** are not ported. Their prices come from the supply stand-in ([docs/supply_standin.md](docs/supply_standin.md)) and their quantities from EIA's restart file.
- **Alaska and Hawaii** are not in the power model.

## Run it

You need Python 3.11 or newer. The model reads EIA's AEO2026 release (about 1 GB, Apache 2.0) from a folder called `nems-upstream` next to the code.

```
git clone https://github.com/EIAgov/NEMS nems-upstream
pip install -e ".[test]"
python -m nems_open.run_model --carbon 50 --ev 0.8
```

That runs the whole loop for 2027 to 2050 with a $50 carbon price and 80% plug-in sales and prints the prices, fuel use and CO2 against EIA's reference. It takes a few minutes: with no oracle dump for the start year, commercial first runs 2019 to 2026 from the input files. Set `NEMS_UPSTREAM` to use a checkout somewhere else.

The levers are `--carbon`, `--ev`, `--efficiency` (a multiplier on building fuel use), `--shell-code` and `--standard` (commercial building code and minimum efficiency). See [docs/run_model.md](docs/run_model.md).

### The demo

Open `web/index.html` in a browser. No server is needed. To rebuild its data: `python scripts/precompute_scenarios.py` (see [web/README.md](web/README.md)).

### Ask a question

```
pip install -e ".[agent]"
export ANTHROPIC_API_KEY=...
python -m nems_open.agent "What does a $50 carbon price do to US energy CO2 in 2040?"
```

A Claude tool-use agent over the model's own tools. Every number in its answer comes from a tool result and carries its module, variable and grade; if the answer rests on a stand-in it says so; a question the model cannot resolve (a street, a site, a year before 2025) is declined. Needs your own API key; without one it only runs the scope gate. See [docs/agent.md](docs/agent.md).

### One piece, in Python

```python
from nems_open.run_demand import DemandRunner

runner = DemandRunner(2030, sectors=("commercial",), commercial_from_files=True)
runner.run_year()
runner.q["qngcm"][10, 2030 - 1990]   # US commercial gas use in 2030, trillion Btu
```

### The oracle and the tests

```
python -m pytest -n auto --dist loadgroup      # needs: pip install pytest-xdist
```

Tests that compare against EIA's internal state need the oracle built first: gfortran, then `oracle/gen_oracle.py` and `oracle/build.sh` (see [SCOPE.md](SCOPE.md) and [CONTRIBUTING.md](CONTRIBUTING.md)). That step is the hard part on a new machine. The dumps are large, so keep one shared copy (`NEMS_ORACLE_DIR`) and pack it (`scripts/pack_oracle.py`).

## Contributing

Pick something from [docs/issues_draft.md](docs/issues_draft.md) or an open GitHub issue and read [CONTRIBUTING.md](CONTRIBUTING.md). The rule for a port: within 0.1% of EIA for every region, building type and year it covers, and EIA's quirks kept. Small, well-defined pieces are marked "good first issue"; pieces that need someone who knows energy modelling are marked "needs energy modelling".
