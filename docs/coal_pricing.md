# Coal supply and transport pricing (plan step 3)

## What is ported
- `coal/supply.py`: the pricing equation of `CalculationOfCoalPricingEquationBaseYearItr1` for the 14 supply curves. `curves()` builds BB, BY_MULT, PPRI and CALK from the input files and the restart's macro series (`coal/macro.py`: GDP deflator, bond rate, diesel and electricity prices). `base_year()` gives the 11 steps of SC_PRICE, SC_PRICE87 (1987$ per ton and per MMBtu), T_QUAN and SC_QUAN.
- `coal/transport.py`: the RCAF part of `SetUpRateEscalators`: seven cost indexes rebased to 2021, shares rolled forward, the productivity pass-through from the 3-year growth of US output, and the cumulative rail escalator (FinalRCAFindex).

## Checks
- CALK makes the base-year step-6 price equal the base-year minemouth price (BY_MMP in 1992$). The port reproduces that to 1e-8 on all 14 curves. This verifies the SC_PRICE kernel, PPRI and CALK against each other; it cannot catch an error in BY_MULT's inputs, because CALK absorbs it.
- RCAF shares sum to the input weights in 2021, the escalator is 1 through 2021, and one year was recomputed by hand in the tests.
- Prices are 0.1 to 3 1987$/MMBtu. Steps 1 and 2 of three Western curves (PRB and two Wyoming rows) dip below step 1 before rising; that follows from the utilization term as written, not from the port.
- The restart does not carry curve-level prices, so there is no direct comparison. The base year here is 2024 (`CPSBaseYr`), the restart's last history year.

## Not ported (named gaps)
- Later iterations and forecast years of `CalculationOfCoalPricingEquation`: FY_PROD_CAP, LAG_PROD, LAG_PRI, QTarget and T_util need the prior year's solved production (`ProdVolSolutionPriorYr`, `qprods`, `mcnt_prev`), which sit in the AIMMS case files we cannot read (docs/coal_inputs.md). With them, MULT for forecast years also needs MINE_FUEL by census division (SelectedCensusDiv, E_FUEL = PELIN), FY_TPH growth and WAGE_MULTIPLIER; the inputs are loaded, the recursion is written out in coal.ams 24020-24045.
- The older escalators in `SetUpRateEscalators` (EastEscalator, Westcheck, the PPI rail equation, inflation rate). They need TTONMILE lags and the same case files. The RCAF block above is the part current transport rates use.
- STEO-year and post-STEO handling, which belongs to the later solve steps in the plan.
