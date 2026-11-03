# International trade and storage dispatch (electricity lane, item 3)

## Canada and Mexico
The dispatch model takes EIA's net imports of Canada and Mexico as fixed annual energy (`UETTOUT/UTIMP*` less `UTEXP*`), subtracted from each region's load. It does not let them respond to prices.

What that leaves out is small. Gross flows against the 25 regions' load (TWh):

| | 2025 | 2030 | 2040 | 2050 |
|---|---|---|---|---|
| Imports | 42 | 101 | 107 | 82 |
| Exports | 18 | 18 | 18 | 18 |
| Net, share of load | 0.6% | 1.9% | 1.7% | 1.1% |

If every TWh of economy imports (26 TWh of the 2025 total) were replaced by gas combined cycle, power CO2 would move by about 10 Mt, under 1%.

I did not build a price-responsive version. The supply-step table that would feed it (`V_EMM_CANSPLY_STEPS`: firm and non-firm MW, a capacity factor, `SPDOLL` and `CST`) is not read by any routine in the Fortran in the repo, so I cannot confirm what `SPDOLL` (2,000 to 5,000) and `CST` (0 to 87) are in. Guessing units would put numbers in the model that look sourced and are not. The firm-contract table (`V_EMM_ETCNCT`, 70 contracts with exporting and importing regions and MW) has the same gap. The two are in `emm/system.py` for when someone has the ETT code (`prepett.f` reads the contracts) in front of them.

## Storage
Net generation of storage (discharge less charge, TWh; a negative number is round-trip loss):

| | 2025 | 2030 | 2040 | 2050 |
|---|---|---|---|---|
| Pumped hydro, model / EIA | -0.8 / -0.8 | -0.8 / -0.7 | -0.1 / -0.7 | 0.0 / -0.7 |
| Batteries, model / EIA | -1.6 / -5.0 | -5.3 / -15.5 | -5.7 / -19.8 | -3.4 / -21.8 |

Pumped hydro matches. Batteries cycle about a third as much as EIA's: at a round-trip loss of 15%, EIA's 2030 figure is about 100 TWh of discharge from 87 GW (0.8 cycles a day), the LP's about 35. Running the full 24 hours instead of three-hour blocks lifts the LP's net loss only to about 7 TWh in 2030, so the block averaging is not the main cause.

Why the LP cycles less: it charges and discharges only when the price spread beats the loss, and its spreads are narrow (load-weighted marginal cost 15 to 17 1987$/MWh with no scarcity). EIA's spreads come from 24 vertical load segments per season and a solar-heavy net load the LP's smoother merit order does not reproduce. `UECPOUT/PRICE_EL_HR` (hourly electricity price) is in the restart if someone wants to compare spreads directly. I left the storage model as it is; the effect on fuel and CO2 is small (the energy shifted is about 100 TWh of 4,400).
