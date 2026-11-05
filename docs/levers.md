# Levers

Ten plain levers on the full model. Each is a field on `Policy` (`demand_adapter.py`), a flag on `python -m nems_open.run_model`, and a row in `nems_open.levers.LEVERS`. `python -m nems_open.levers` prints the table below for the default run; `levers.fidelity(name, ported, elec)` and `levers.label(...)` give it for any run, so a page can't show a lever without its grade.

## The grades

- **ported**: edits a real input table of a routine ported from EIA's Fortran. The routines respond.
- **own model**: acts on our dispatch LP, built on EIA's data but not EIA's electricity model.
- **stand-in**: moves a curve fitted to EIA's runs, or scales EIA's side cases. No EIA routine responds.

A grade says what the lever acts on. It does not say the size of the response matches EIA: EIA published no run for most of these. A ported lever's prices still come from the stand-in, because no supply module is ported into the loop yet.

## The table

| Lever | `Policy` field, units | Moves | Grade, default run | Grade, `elec="lp"` |
|---|---|---|---|---|
| Carbon price | `carbon_price`, 2024 $/t CO2 | Delivered fossil prices by carbon content, plants' fuel costs | stand-in | own model |
| EV sales | `ev_share`, plug-in share of new light-duty sales | With TRAN: plug-ins' utility in TALT2X. Stub: gasoline to electricity as the fleet turns over | stand-in (ported with TRAN in `ported`) | same |
| Building codes | `building_code`, fraction less heating and cooling need in new buildings | Commercial KSHEFF; residential RSMSHL HTSHEFF, CLSHEFF | ported | ported |
| Appliance standards | `appliance_standard`, fraction above the least efficient on offer | Commercial KTEK availability years; residential RSMEQP RTEQEFF, RTEQCOST, RTRECOST | ported | ported |
| Coal retirements | `coal_retirement`, share of EIA's fleet closed early, reached by 2035 | Stand-in: coal burn, made up by the fitted mix. LP: coal capacity | stand-in | own model |
| Renewable cost | `renewable_cost`, -1 EIA's low ZTC case to +1 its high case | Stand-in: power-sector fuel, retail electricity prices. LP: wind and solar capacity | stand-in | own model |
| Load growth | `load_growth`, extra TWh in 2050, linear from the start year | Commercial electricity sales, split by division as EIA splits them | stand-in | own model |
| Gas supply | `gas_supply`, -1 EIA's low oil and gas supply case to +1 its high case | Delivered gas and retail electricity prices | stand-in | stand-in |
| Oil price | `oil_price`, multiple of EIA's Brent | Brent, passed through to product prices dollar for dollar | stand-in | stand-in |
| Nuclear | `nuclear`, multiple of EIA's output, reached by 2040 | Stand-in: uranium burn, change met by the fitted mix. LP: nuclear capacity | stand-in | own model |

## What each one does, 2035

Change against the same run with the lever off, US, starting 2027. Levers on stand-ins ran on stub demand; building codes and appliance standards on ported residential and commercial. Reference: 3,813 Mt CO2.

| Lever | Setting | CO2 (Mt) | Home electricity price | Home gas price | Gasoline price | Electricity sales |
|---|---|---|---|---|---|---|
| Carbon price | $50 | -257 | +3.3% | +17.1% | +15.8% | -1.1% |
| Coal retirements | 0.5 | -51 | 0.0% | +0.1% | 0.0% | 0.0% |
| Renewable cost | -1 | -54 | -1.7% | -0.3% | 0.0% | +0.4% |
| Load growth | 500 TWh | +22 | +1.4% | +0.2% | 0.0% | +3.8% |
| Gas supply | +1 | +113 | -3.7% | -4.8% | 0.0% | +1.0% |
| Oil price | 1.25x | -33 | 0.0% | 0.0% | +15.4% | 0.0% |
| Nuclear | 1.25x | -16 | 0.0% | -0.1% | 0.0% | 0.0% |
| Building codes | 0.3 | -8 | -0.2% | -0.1% | 0.0% | -0.4% |
| Appliance standards | 0.2 | -23 | -0.4% | -0.2% | 0.0% | -1.1% |

## What to know before showing these

- **EV sales is a target, not an addition.** EIA's reference already reaches 49% plug-in sales in 2030 and 65% in 2035, so 0.5 from 2027 lowers EV sales in 2035 and raises CO2 by 11 Mt. Use a value above the reference.
- **EV charging reaches the grid through the buildings rows when TRAN is ported** (QELRS and QELCM add TRQ_ELEC; QELTR is passenger rail only), one iteration later, as in NEMS's module order. Only an `ev_share` target hands TRAN's load over. If a carbon or oil price moves EV sales inside TRAN, the buildings keep EIA's charging load, so that extra load is missing. The stub path puts the load on QELTR instead: the US total is right, the sector split is not EIA's.
- **Plentiful gas raises CO2.** That is EIA's answer too: its high supply case adds 260 Mt in 2035. The stand-in adds 113, so it under-reacts.
- **Coal retirements look small late.** EIA's own coal burn falls fast (7,500 trillion Btu in 2025, 21 in 2050), so the lever has less to close each year.
- **No lever carries a capital cost into prices.** Closing coal or building nuclear does not move retail electricity through plant costs. Building codes and standards do not charge the builder for shells; residential standards do raise equipment cost, read off each class's own efficiency-to-cost line.
- **Standards stop at the best on offer.** They cannot require equipment that does not exist in EIA's tables.
- **Stand-in levers change nothing in the ported modules except through prices.**
- **Oil and gas are separate here, not in EIA's cases.** AEO2026 has no oil price case; Brent moves with its oil and gas supply cases. The gas lever takes only that case's gas and electricity prices.
- **Commercial levers start from the files,** which adds about a minute of pre-roll (2019 to the start year). Residential levers edit the state when the run reaches their year, with no pre-roll.
- **Building levers refuse a run with no ported buildings sector** rather than doing nothing silently.
- **`load_growth` is added by hand.** No data center or other load model sits behind it.

## Tests

`tests/test_levers.py`: every lever at its off value reproduces the reference run to the bit; each lever moves its results the right way; side-case levers refuse values past their ends; coal and nuclear move the dispatch LP; grades and labels follow the run's configuration.
