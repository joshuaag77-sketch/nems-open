# AEO fidelity report

`scripts/aeo_fidelity.py` compares one finished run with EIA's AEO2026 reference (the cb2026 restart), line by line, in the layout of the AEO tables a NEMS reviewer checks first. It reads saved outputs only. It solves nothing.

`scripts/fidelity.py` is a different thing: it grades each module (ported, own model, stand-in). This report grades the numbers a run produced.

## Run it

```
python scripts/aeo_fidelity.py --latest C:/Users/joshu/dev/nems-open-supply/data/showroom
python scripts/aeo_fidelity.py --run <path/to/reference.npz> --out docs/fidelity
```

`--latest` takes the newest `reference.npz` in the folder or its `old-*` folders. The run file is a `full_model.save_run` archive, the format the showroom writes. Output: `<out>/<folder>-<file>.md` and `.json`. The default `--out` is `docs/fidelity`. Prices are in 2025 dollars unless `--dollar-year` says otherwise. Percent gaps do not depend on the dollar year.

## What is compared

Years 2025, 2030, 2035, 2040 and 2050. Each line has our value, EIA's value and the percent difference for each year.

| Table | Lines |
|---|---|
| 1. Supply, disposition and prices | crude and dry gas production, consumption by sector and by source, Brent, WTI, Henry Hub, average electricity price |
| 2. Consumption by sector and source | main fuels and delivered energy for each sector, electric power inputs, total |
| 3. Delivered prices | electricity and gas by sector, propane, distillate, gasoline, jet fuel, diesel, coal |
| 8. Electricity | generation by fuel (coal, gas, nuclear, renewables, with hydro, wind and solar), sales, end-use prices, power sector CO2 |
| 9. Capacity | coal, steam, combined cycle, turbines, nuclear, pumped storage, batteries, hydro, wind, solar, other, total |
| 13. Natural gas | dry production, pipeline imports and exports, LNG exports, consumption by sector, Henry Hub, delivered prices |
| 15. Coal | consumption by sector, delivered prices to power plants and industry |
| 18. CO2 | by sector and total; by fuel as fuel use times EIA's carbon factors |
| 20. Macro | real GDP |

EIA's values come from the same restart arrays the model reads. The JSON names them for every line (`source`), so each number can be traced to a NEMS variable. Units follow the AEO tables, with two exceptions. Table 15 quantities are in quads, because the run keeps Btu and not short tons. Table 13 volumes are converted from trillion Btu at 1,037 Btu per cubic foot.

## Status of a line

- PASS: every model year is inside the tolerance.
- FLAG: at least one model year is outside it.
- HELD: our value equals EIA's to one part in a million in every model year. The run carried EIA's number and did not compute it. This is not a pass.
- NOT IN RUN: the archive has no array for the series. EIA's value is shown alone.
- NO EIA VALUE: an EIA array the line names was not found. That is a wiring error.

2025 is shown but not graded. The run starts in its first model year (2027 for the showroom runs), so 2025 is history in both columns. Years the run did not converge are marked `nc`.

## Tolerances

A cell is outside tolerance when the gap beats both the percent and the floor, so a nearly retired fuel cannot fail on percent alone.

| Kind | Percent | Floor |
|---|---|---|
| Consumption | 3% | 0.05 quads |
| Gas volumes, production | 5% | 0.1 Tcf (0.1 million barrels a day) |
| Generation | 5% | 10 billion kWh |
| Electricity sales | 3% | 20 billion kWh |
| Capacity | 15% | 2 GW (as `emm/capacity_report.py`) |
| Prices | 5% | 0.10 $/MMBtu or cents/kWh |
| CO2 | 3% | 5 million metric tons |
| GDP | 1% | none |

The worst-lines list ranks by the gap in multiples of what the line allows. A series that appears in two tables, such as Henry Hub, is listed once.

## Known limits

Runs saved from commit `run-outputs` on carry the series below. Older archives lack them, and the report falls back to rebuilding QTSEL and QTSAS itself.

- Dry gas production, pipeline imports and exports, and LNG exports are NGMM's own volumes (`ogs="aimms"`, RunResult.gas). They are not calibrated to EIA, so the gap includes NGMM's reproduction error of a few percent.
- Crude production is HSM's, scaled to EIA's restart the way NGMM's expected gas production is. With two cycles HSM runs once, between them, so the saved value answers the first cycle's prices. It is missing when HSM never ran.
- Real GDP is EIA's times the last cycle's FRB/US GDP gap (`macro="frbus"`). Without the macro module it is EIA's and shows HELD.
- Brent and WTI are inputs. They are saved so the report shows them as HELD. WTI moves with Brent when a lever moves the oil price.
- QUREL, QTREL and QTRAS are rebuilt at save time from the run's generation, with EIA's own Btu per kWh for each year (nuclear, hydro, wind, solar). Geothermal, biomass and MSW inputs (about 0.5 quads) stay at EIA's, so part of QTREL is held. QTSEL and QTSAS follow from NEMS's identities (`full_model.derived_totals`).
- Generation sums EMM regions 1 to 25 of UEFDOUT, as `full_model.GEN`. Capacity follows `emm/dispatch.py` CAPACITY_PREFIXES. Our coal excludes CCS retrofits and EIA's includes them, so coal compares coal plus coal with CCS. Converted coal units count as steam, as in EIA's arrays.
- CO2 by fuel counts combustion only (no feedstock carbon, no capture). It tests fuel use with EIA's own factors. It is not Table 18's printed petroleum total.
- The series names follow the AEO table rows. They were written from the tables' layout, not copied from EIA's API series IDs.

## First result: old-342aa01 (2026-11-20)

`docs/fidelity/old-342aa01-reference.md`. 47 lines pass, 52 are flagged, 10 are held and 9 are not in the run. 2030 did not converge, and the run log has an LFMM traceback from 2028. The largest gaps sit in one chain: Henry Hub and the industrial and power-plant gas prices run 30 to 55% high in 2035 to 2040, coal holds on in power (2040 coal use 81% above EIA), and solar is over-built while wind and turbines are under-built. End-use demand and the oil side are within 3% almost everywhere. Industrial renewables in 2050 (+73%) is the worst single line.
