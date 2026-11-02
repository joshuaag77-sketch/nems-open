# The dispatch LP as the model's electricity supply

`run_model.run(..., elec="lp")` (CLI: `--elec lp`) replaces the stand-in's power-sector piece with the dispatch LP from `docs/dispatch.md`. The default is still `elec="standin"`, and that path is unchanged.

## What goes in and out
Per pass, `emm/couple.py` `ElectricityLP.solve`:

| In | Out |
|---|---|
| The loop's electricity sales (`QBLK/qelrs`, `qelcm`, `qelin`, `qeltr`), spread over the 25 EMM regions, plus losses, less end-user generation and net imports | Power-plant coal, gas, distillate and residual use (`QBLK/qclel`, `qngel` with `qgfel` and `qgiel`, `qdsel`, `qrsel`), trillion Btu |
| The loop's fuel prices (`MPBLK/pclel`, `pngel`, `pdsel`, `prsel`), as a ratio to the reference run, applied to each region's fuel price | Power CO2, million metric tons (replaces the stand-in's `co2["el"]`) |
| A carbon price in 1987 $ per ton CO2, added to every plant's cost by its emissions after capture | Wholesale marginal cost by EMM region and nationally, 1987 $/MWh (`RunResult.wholesale`, `wholesale_us`), and generation by plant group (`generation_twh`) |

US totals come from the LP and are split over census divisions as in the reference run. The stand-in then runs on those fuel quantities, so the gas and coal prices and the carbon cost in retail electricity respond to what the LP burns. **Retail electricity prices still come from the stand-in** (`MPBLK/pel*`) until EFP is ported.

Changes outside `emm/`: `SupplyStandin.solve` takes optional `power_fuel` and `co2_el` (skipping its own fuel switching when `power_fuel` is given), and `demand.net_load_twh` takes sales from any restart-style mapping.

## Limits
- **Capacity is fixed** at the cb2026 path. A carbon price moves coal to gas in dispatch; it does not build or retire plants, so the response is stronger than a model with entry and exit would show.
- Needs the cb2026 baseline (it raises for other cases).
- Time slices: 36 typical days of 8 three-hour blocks, trade over the regional links. A year with one pass takes about 20 seconds, with five passes (a carbon price) about 45 seconds. The first call each year builds the inputs (about 10 seconds).
- The wholesale marginal cost is load-weighted and includes a few scarcity hours in 2025 to 2030, where some regions run short (under 0.1% of load) and set a $1,000/MWh price. 2030 shows about 47 1987$/MWh against 15 to 17 in the years without shortage. Read it as a signal, not a price.
- Oil use is low (about 10 trillion Btu against EIA's 105 in 2030): see `docs/dispatch.md`.

## Result, 2030, no policy (US, vs the cb2026 reference)
| | model | reference |
|---|---|---|
| Coal for power, trillion Btu | 5,254 | 4,962 (+6%) |
| Gas for power, trillion Btu | 12,768 | 12,172 (+5%) |
| Power CO2, Mt | 1,153 | 1,094 (+5%) |

Inside the 10% tolerance in 2030 and 2050. In 2040 coal is high (+64% on fuel), the known miss from the dispatch study.

## $50 per ton CO2 (2024 dollars), 2030
| | no policy | $50/t | stand-in at $50/t |
|---|---|---|---|
| Coal for power, trillion Btu | 5,254 | 757 | 3,050 |
| Gas for power, trillion Btu | 12,768 | 15,856 | 12,029 |
| Power CO2, Mt | 1,153 | 889 | 927 |
| Wholesale cost, 1987 $/MWh | 47.0 | 69.1 | |
| Delivered gas price to power, 1987 $/MMBtu | 1.97 | 3.23 | |

Coal falls 86% and power CO2 falls 23%. The LP moves more than the stand-in because its switching is a merit-order dispatch with the gas fleet already in place; the stand-in's is a fitted response. The gas price rise comes from the stand-in's log-log price response to the extra gas burn.
