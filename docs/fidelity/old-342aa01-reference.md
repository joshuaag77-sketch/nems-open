# Fidelity against AEO2026: old-342aa01-reference

Generated 2026-11-22 by `scripts/aeo_fidelity.py`. Ours against EIA's AEO2026 reference (cb2026 restart).
Prices in 2025 dollars (EIA's GDP deflator). First model year 2027: 2025 is history in both columns and is not graded.
Years the run did not converge: 2030, 2047, 2049 (cells marked nc).
Run log: LFMM gams, finished 2026-11-20 00:14, error None; a traceback was logged during the run.

Lines: 47 pass, 52 flagged, 10 held at EIA's value, 9 not in the run's output.

Each cell is ours / EIA (percent difference). `!` marks a model year outside the line's tolerance. Tolerances are in docs/fidelity_report.md.

## Worst 15 lines

| # | Table | Series | Unit | Worst year | Ours | EIA | Diff | Times tolerance |
|---|---|---|---|---|---|---|---|---|
| 1 | Table 2 | Industrial: Renewable energy | quads | 2050 | 3.05 | 1.76 | +73.0% | 24.3 |
| 2 | Table 2 | Electric power: Steam coal | quads | 2040 | 1.55 | 0.854 | +80.9% | 13.8 |
| 3 | Table 1 | Consumption by source: Coal | quads | 2040 | 1.90 | 1.21 | +56.9% | 13.8 |
| 4 | Table 18 | By fuel: Coal (combustion, fuel use x EIA carbon factors) | million metric tons | 2040 | 209.7 | 144.8 | +44.8% | 13.0 |
| 5 | Table 3 | Electric power: Natural gas | $/MMBtu | 2040 | 8.05 | 5.17 | +55.6% | 11.1 |
| 6 | Table 1 | Prices: Natural gas at Henry Hub | $/MMBtu | 2040 | 7.61 | 5.25 | +45.0% | 9.0 |
| 7 | Table 3 | Industrial: Natural gas | $/MMBtu | 2040 | 8.51 | 5.91 | +44.2% | 8.8 |
| 8 | Table 8 | Generation by fuel: Solar (in renewables) | billion kWh | 2030 | 810.7 | 577.1 | +40.5% | 8.1 |
| 9 | Table 2 | Electric power: Natural gas | quads | 2030 | 9.86 | 12.17 | -19.0% | 6.3 |
| 10 | Table 8 | Generation by fuel: Wind (in renewables) | billion kWh | 2050 | 1,018 | 1,449 | -29.8% | 6.0 |
| 11 | Table 8 | Emissions from the electric power sector: Carbon dioxide | million metric tons | 2050 | 967.0 | 830.4 | +16.4% | 5.5 |
| 12 | Table 8 | Generation by fuel: Coal | billion kWh | 2040 | 102.5 | 63.18 | +62.2% | 3.9 |
| 13 | Table 3 | Commercial: Natural gas | $/MMBtu | 2040 | 14.74 | 12.50 | +17.9% | 3.6 |
| 14 | Table 9 | Electric power sector capacity: Oil and natural gas steam | gigawatts | 2035 | 47.82 | 100.7 | -52.5% | 3.5 |
| 15 | Table 8 | Generation by fuel: Natural gas | billion kWh | 2040 | 2,087 | 1,779 | +17.3% | 3.5 |

## Table 1. Total energy supply, disposition, and price summary

| Series | Unit | 2025 | 2030 | 2035 | 2040 | 2050 | Status | Tolerance |
|---|---|---|---|---|---|---|---|---|
| Production: Crude oil and lease condensate | million barrels per day | - / 13.62 | - / 13.76 | - / 12.69 | - / 12.53 | - / 12.78 | NOT IN RUN | 5% or 0.1 |
| Production: Dry natural gas | trillion cubic feet | - / 39.16 | - / 41.42 | - / 44.94 | - / 46.93 | - / 52.71 | NOT IN RUN | 5% or 0.1 |
| Consumption by sector: Residential | quads | 11.80 / 11.80 (+0.0%) | 11.82 / 11.80 (+0.2%) nc | 11.90 / 12.03 (-1.1%) | 12.09 / 12.36 (-2.2%) | 12.74 / 12.82 (-0.6%) | PASS | 3% or 0.05 |
| Consumption by sector: Commercial | quads | 10.00 / 10.00 (+0.0%) | 10.49 / 10.45 (+0.4%) nc | 10.94 / 11.05 (-1.0%) | 11.60 / 11.82 (-1.8%) | 12.83 / 12.86 (-0.2%) | PASS | 3% or 0.05 |
| Consumption by sector: Industrial | quads | 25.61 / 25.61 (+0.0%) | 25.53 / 25.57 (-0.2%) nc | 26.70 / 26.73 (-0.1%) | 28.35 / 28.20 (+0.5%) | 32.16 / 31.12 (+3.3%) ! | FLAG | 3% or 0.05 |
| Consumption by sector: Transportation | quads | 28.13 / 28.13 (+0.0%) | 27.25 / 27.26 (-0.0%) nc | 24.67 / 24.67 (-0.0%) | 22.70 / 22.68 (+0.1%) | 21.04 / 21.01 (+0.1%) | PASS | 3% or 0.05 |
| Consumption by sector: Electric power | quads | 32.96 / 32.96 (+0.0%) | 29.92 / 31.55 (-5.2%) ! nc | 31.22 / 30.76 (+1.5%) | 34.01 / 32.21 (+5.6%) ! | 36.64 / 35.18 (+4.2%) ! | FLAG | 3% or 0.05 |
| Consumption by sector: Total | quads | 94.61 / 94.61 (+0.0%) | 90.36 / 91.99 (-1.8%) nc | 89.63 / 89.42 (+0.2%) | 91.68 / 90.09 (+1.8%) | 96.55 / 93.96 (+2.7%) | PASS | 3% or 0.05 |
| Consumption by source: Petroleum and other liquids | quads | 37.38 / 37.38 (+0.0%) | 36.27 / 36.28 (-0.1%) nc | 33.55 / 33.56 (-0.0%) | 31.81 / 31.81 (+0.0%) | 30.77 / 30.78 (-0.1%) | PASS | 3% or 0.05 |
| Consumption by source: Natural gas | quads | 30.85 / 30.85 (+0.0%) | 26.91 / 29.15 (-7.7%) ! nc | 30.01 / 29.90 (+0.4%) | 31.87 / 31.42 (+1.4%) | 37.03 / 35.82 (+3.4%) ! | FLAG | 3% or 0.05 |
| Consumption by source: Coal | quads | 7.93 / 7.93 (+0.0%) | 6.04 / 5.33 (+13.2%) ! nc | 1.92 / 1.86 (+3.3%) ! | 1.90 / 1.21 (+56.9%) ! | 0.398 / 0.328 (+21.4%) ! | FLAG | 3% or 0.05 |
| Consumption by source: Nuclear | quads | 8.19 / 8.19 (+0.0%) | 8.37 / 8.37 (+0.0%) nc | 8.37 / 8.37 (+0.0%) | 8.37 / 8.37 (+0.0%) | 8.37 / 8.37 (+0.0%) | HELD | 3% or 0.05 |
| Consumption by source: Renewable energy | quads | 6.34 / 6.34 (+0.0%) | 8.28 / 8.28 (+0.0%) nc | 10.42 / 10.42 (+0.0%) | 11.60 / 11.60 (+0.0%) | 12.52 / 12.52 (+0.0%) | HELD | 3% or 0.05 |
| Prices: Brent spot | $/barrel | - / 68.76 | - / 67.16 | - / 71.72 | - / 75.70 | - / 86.89 | NOT IN RUN | 5% or 0.1 |
| Prices: West Texas Intermediate spot | $/barrel | - / 65.15 | - / 66.56 | - / 69.57 | - / 72.91 | - / 83.56 | NOT IN RUN | 5% or 0.1 |
| Prices: Natural gas at Henry Hub | $/MMBtu | 3.47 / 3.47 (+0.0%) | 3.89 / 4.45 (-12.6%) ! nc | 6.62 / 5.10 (+29.8%) ! | 7.61 / 5.25 (+45.0%) ! | 3.91 / 4.63 (-15.4%) ! | FLAG | 5% or 0.1 |
| Prices: Electricity, all sectors | cents/kWh | 13.54 / 13.54 (+0.0%) | 13.08 / 13.16 (-0.6%) nc | 14.43 / 13.67 (+5.5%) ! | 15.25 / 13.93 (+9.5%) ! | 14.37 / 14.05 (+2.3%) | FLAG | 5% or 0.1 |

## Table 2. Energy consumption by sector and source

| Series | Unit | 2025 | 2030 | 2035 | 2040 | 2050 | Status | Tolerance |
|---|---|---|---|---|---|---|---|---|
| Residential: Propane | quads | 0.524 / 0.524 (+0.0%) | 0.487 / 0.487 (-0.1%) nc | 0.466 / 0.466 (-0.1%) | 0.456 / 0.455 (+0.2%) | 0.447 / 0.446 (+0.4%) | PASS | 3% or 0.05 |
| Residential: Distillate fuel oil | quads | 0.489 / 0.489 (+0.0%) | 0.439 / 0.439 (-0.0%) nc | 0.406 / 0.406 (+0.0%) | 0.379 / 0.379 (+0.0%) | 0.333 / 0.332 (+0.2%) | PASS | 3% or 0.05 |
| Residential: Natural gas | quads | 4.93 / 4.93 (+0.0%) | 4.81 / 4.79 (+0.5%) nc | 4.49 / 4.56 (-1.4%) | 4.29 / 4.40 (-2.6%) | 4.09 / 4.10 (-0.1%) | PASS | 3% or 0.05 |
| Residential: Purchased electricity | quads | 5.22 / 5.22 (+0.0%) | 5.41 / 5.42 (-0.1%) nc | 5.80 / 5.87 (-1.1%) | 6.15 / 6.30 (-2.4%) | 6.81 / 6.88 (-1.0%) | PASS | 3% or 0.05 |
| Residential: Delivered energy | quads | 11.80 / 11.80 (+0.0%) | 11.82 / 11.80 (+0.2%) nc | 11.90 / 12.03 (-1.1%) | 12.09 / 12.36 (-2.2%) | 12.74 / 12.82 (-0.6%) | PASS | 3% or 0.05 |
| Commercial: Distillate fuel oil | quads | 0.315 / 0.315 (+0.0%) | 0.329 / 0.329 (+0.1%) nc | 0.325 / 0.324 (+0.2%) | 0.314 / 0.314 (+0.1%) | 0.296 / 0.295 (+0.4%) | PASS | 3% or 0.05 |
| Commercial: Natural gas | quads | 3.64 / 3.64 (+0.0%) | 3.49 / 3.47 (+0.7%) nc | 3.29 / 3.37 (-2.6%) | 3.23 / 3.38 (-4.4%) ! | 3.36 / 3.36 (-0.2%) | FLAG | 3% or 0.05 |
| Commercial: Purchased electricity | quads | 5.03 / 5.03 (+0.0%) | 5.56 / 5.54 (+0.3%) nc | 6.15 / 6.18 (-0.5%) | 6.80 / 6.88 (-1.2%) | 7.81 / 7.84 (-0.4%) | PASS | 3% or 0.05 |
| Commercial: Delivered energy | quads | 10.00 / 10.00 (+0.0%) | 10.49 / 10.45 (+0.4%) nc | 10.94 / 11.05 (-1.0%) | 11.60 / 11.82 (-1.8%) | 12.83 / 12.86 (-0.2%) | PASS | 3% or 0.05 |
| Industrial: Petroleum and other liquids | quads | 8.62 / 8.62 (+0.0%) | 8.80 / 8.80 (-0.0%) nc | 9.22 / 9.20 (+0.2%) | 9.83 / 9.81 (+0.2%) | 11.09 / 11.09 (-0.0%) | PASS | 3% or 0.05 |
| Industrial: Natural gas | quads | 8.94 / 8.94 (+0.0%) | 8.63 / 8.61 (+0.2%) nc | 8.94 / 9.12 (-2.0%) | 9.20 / 9.63 (-4.5%) ! | 10.54 / 10.73 (-1.8%) | FLAG | 3% or 0.05 |
| Industrial: Coal (steam and metallurgical) | quads | 0.819 / 0.819 (+0.0%) | 0.771 / 0.772 (-0.1%) nc | 0.732 / 0.731 (+0.0%) | 0.661 / 0.664 (-0.4%) | 0.548 / 0.551 (-0.5%) | PASS | 3% or 0.05 |
| Industrial: Renewable energy | quads | 1.50 / 1.50 (+0.0%) | 1.46 / 1.51 (-3.6%) ! nc | 1.52 / 1.47 (+3.5%) ! | 1.98 / 1.57 (+26.0%) ! | 3.05 / 1.76 (+73.0%) ! | FLAG | 3% or 0.05 |
| Industrial: Purchased electricity | quads | 3.62 / 3.62 (+0.0%) | 3.65 / 3.66 (-0.1%) nc | 3.81 / 3.76 (+1.6%) | 4.08 / 3.97 (+3.0%) | 4.21 / 4.27 (-1.2%) | PASS | 3% or 0.05 |
| Industrial: Delivered energy | quads | 25.61 / 25.61 (+0.0%) | 25.53 / 25.57 (-0.2%) nc | 26.70 / 26.73 (-0.1%) | 28.35 / 28.20 (+0.5%) | 32.16 / 31.12 (+3.3%) ! | FLAG | 3% or 0.05 |
| Transportation: Motor gasoline | quads | 15.74 / 15.74 (+0.0%) | 14.43 / 14.44 (-0.1%) nc | 11.97 / 11.98 (-0.1%) | 9.96 / 9.96 (+0.1%) | 7.88 / 7.87 (+0.2%) | PASS | 3% or 0.05 |
| Transportation: Jet fuel | quads | 3.56 / 3.56 (+0.0%) | 3.67 / 3.67 (-0.0%) nc | 3.84 / 3.85 (-0.0%) | 4.04 / 4.04 (-0.0%) | 4.32 / 4.32 (-0.0%) | PASS | 3% or 0.05 |
| Transportation: Distillate fuel oil | quads | 6.68 / 6.68 (+0.0%) | 6.63 / 6.64 (-0.2%) nc | 5.78 / 5.80 (-0.3%) | 5.22 / 5.24 (-0.4%) | 4.69 / 4.71 (-0.6%) | PASS | 3% or 0.05 |
| Transportation: Natural gas | quads | 0.089 / 0.089 (+0.0%) | 0.106 / 0.105 (+0.3%) nc | 0.107 / 0.106 (+1.0%) | 0.131 / 0.129 (+2.0%) | 0.289 / 0.280 (+3.1%) | PASS | 3% or 0.05 |
| Transportation: Purchased electricity | quads | 0.025 / 0.025 (+0.0%) | 0.027 / 0.027 (+0.1%) nc | 0.028 / 0.028 (+0.1%) | 0.029 / 0.029 (+0.1%) | 0.031 / 0.031 (+0.2%) | PASS | 3% or 0.05 |
| Transportation: Delivered energy | quads | 28.13 / 28.13 (+0.0%) | 27.25 / 27.26 (-0.0%) nc | 24.67 / 24.67 (-0.0%) | 22.70 / 22.68 (+0.1%) | 21.04 / 21.01 (+0.1%) | PASS | 3% or 0.05 |
| Electric power: Petroleum and other liquids | quads | 0.138 / 0.138 (+0.0%) | 0.105 / 0.105 (+0.0%) nc | 0.081 / 0.081 (+0.0%) | 0.068 / 0.068 (+0.0%) | 0.034 / 0.034 (+0.0%) | HELD | 3% or 0.05 |
| Electric power: Natural gas | quads | 13.25 / 13.25 (+0.0%) | 9.86 / 12.17 (-19.0%) ! nc | 13.17 / 12.73 (+3.5%) ! | 14.97 / 13.83 (+8.2%) ! | 18.72 / 17.32 (+8.1%) ! | FLAG | 3% or 0.05 |
| Electric power: Steam coal | quads | 7.51 / 7.51 (+0.0%) | 5.67 / 4.96 (+14.2%) ! nc | 1.55 / 1.48 (+4.1%) ! | 1.55 / 0.854 (+80.9%) ! | 0.094 / 0.021 (+343.2%) ! | FLAG | 3% or 0.05 |
| Electric power: Nuclear | quads | 8.19 / 8.19 (+0.0%) | 8.37 / 8.37 (+0.0%) nc | 8.37 / 8.37 (+0.0%) | 8.37 / 8.37 (+0.0%) | 8.37 / 8.37 (+0.0%) | HELD | 3% or 0.05 |
| Electric power: Renewable energy | quads | 3.79 / 3.79 (+0.0%) | 5.66 / 5.66 (+0.0%) nc | 7.77 / 7.77 (+0.0%) | 8.73 / 8.73 (+0.0%) | 9.18 / 9.18 (+0.0%) | HELD | 3% or 0.05 |
| Electric power: Total | quads | 32.96 / 32.96 (+0.0%) | 29.92 / 31.55 (-5.2%) ! nc | 31.22 / 30.76 (+1.5%) | 34.01 / 32.21 (+5.6%) ! | 36.64 / 35.18 (+4.2%) ! | FLAG | 3% or 0.05 |
| Total: Total energy consumption | quads | 94.61 / 94.61 (+0.0%) | 90.36 / 91.99 (-1.8%) nc | 89.63 / 89.42 (+0.2%) | 91.68 / 90.09 (+1.8%) | 96.55 / 93.96 (+2.7%) | PASS | 3% or 0.05 |

## Table 3. Energy prices by sector and source (delivered prices)

| Series | Unit | 2025 | 2030 | 2035 | 2040 | 2050 | Status | Tolerance |
|---|---|---|---|---|---|---|---|---|
| Residential: Electricity | cents/kWh | 16.68 / 16.68 (+0.0%) | 16.29 / 16.29 (-0.0%) nc | 17.80 / 16.78 (+6.1%) ! | 18.96 / 17.10 (+10.9%) ! | 18.00 / 17.45 (+3.2%) | FLAG | 5% or 0.1 |
| Residential: Natural gas | $/MMBtu | 14.58 / 14.58 (+0.0%) | 13.54 / 13.91 (-2.7%) nc | 16.30 / 14.66 (+11.2%) ! | 17.25 / 14.94 (+15.5%) ! | 15.09 / 15.32 (-1.5%) | FLAG | 5% or 0.1 |
| Residential: Propane | $/MMBtu | 26.50 / 26.50 (+0.0%) | 26.00 / 26.00 (+0.0%) nc | 29.62 / 29.62 (+0.0%) | 31.21 / 31.21 (+0.0%) | 32.47 / 32.47 (+0.0%) | HELD | 5% or 0.1 |
| Residential: Distillate fuel oil | $/MMBtu | 26.30 / 26.30 (+0.0%) | 26.52 / 26.64 (-0.5%) nc | 27.48 / 27.51 (-0.1%) | 29.12 / 29.03 (+0.3%) | 30.87 / 31.31 (-1.4%) | PASS | 5% or 0.1 |
| Commercial: Electricity | cents/kWh | 13.48 / 13.48 (+0.0%) | 12.89 / 13.00 (-0.8%) nc | 14.17 / 13.44 (+5.4%) ! | 14.90 / 13.66 (+9.1%) ! | 13.96 / 13.69 (+2.0%) | FLAG | 5% or 0.1 |
| Commercial: Natural gas | $/MMBtu | 10.27 / 10.27 (+0.0%) | 10.86 / 11.20 (-3.0%) nc | 13.79 / 12.21 (+13.0%) ! | 14.74 / 12.50 (+17.9%) ! | 12.44 / 12.68 (-1.9%) | FLAG | 5% or 0.1 |
| Industrial: Electricity | cents/kWh | 9.07 / 9.07 (+0.0%) | 8.60 / 8.71 (-1.3%) nc | 9.70 / 9.11 (+6.5%) ! | 10.26 / 9.33 (+10.0%) ! | 9.24 / 9.21 (+0.3%) | FLAG | 5% or 0.1 |
| Industrial: Natural gas | $/MMBtu | 4.51 / 4.51 (+0.0%) | 4.88 / 5.41 (-9.9%) ! nc | 7.71 / 5.89 (+31.0%) ! | 8.51 / 5.91 (+44.2%) ! | 4.86 / 5.38 (-9.8%) ! | FLAG | 5% or 0.1 |
| Industrial: Steam coal | $/MMBtu | 3.98 / 3.98 (+0.0%) | 3.73 / 3.73 (+0.1%) nc | 3.64 / 3.66 (-0.6%) | 3.67 / 3.67 (+0.0%) | 3.66 / 3.64 (+0.3%) | PASS | 5% or 0.1 |
| Transportation: Motor gasoline | $/MMBtu | 26.35 / 26.35 (+0.0%) | 22.89 / 22.96 (-0.3%) nc | 22.60 / 22.46 (+0.6%) | 20.20 / 20.15 (+0.3%) | 20.24 / 20.05 (+1.0%) | PASS | 5% or 0.1 |
| Transportation: Jet fuel | $/MMBtu | 16.23 / 16.23 (+0.0%) | 16.39 / 16.51 (-0.7%) nc | 17.40 / 17.43 (-0.2%) | 19.25 / 19.16 (+0.5%) | 21.50 / 21.94 (-2.0%) | PASS | 5% or 0.1 |
| Transportation: Diesel fuel (distillate) | $/MMBtu | 26.38 / 26.38 (+0.0%) | 25.24 / 25.36 (-0.5%) nc | 25.66 / 25.69 (-0.1%) | 27.41 / 27.31 (+0.3%) | 29.11 / 29.56 (-1.5%) | PASS | 5% or 0.1 |
| Electric power: Natural gas | $/MMBtu | 3.81 / 3.81 (+0.0%) | 4.04 / 4.70 (-14.1%) ! nc | 7.24 / 5.09 (+42.4%) ! | 8.05 / 5.17 (+55.6%) ! | 4.29 / 4.62 (-7.1%) ! | FLAG | 5% or 0.1 |
| Electric power: Steam coal | $/MMBtu | 2.56 / 2.56 (+0.0%) | 2.47 / 2.46 (+0.2%) nc | 2.51 / 2.48 (+1.3%) | 2.70 / 2.64 (+2.3%) | 2.55 / 2.43 (+5.2%) ! | FLAG | 5% or 0.1 |

## Table 8. Electricity supply, disposition, prices, and emissions

| Series | Unit | 2025 | 2030 | 2035 | 2040 | 2050 | Status | Tolerance |
|---|---|---|---|---|---|---|---|---|
| Generation by fuel: Coal | billion kWh | - / 727.9 | 506.2 / 465.3 (+8.8%) ! nc | 102.5 / 121.8 (-15.8%) ! | 102.5 / 63.18 (+62.2%) ! | 6.21 / 0.299 (+1978.9%) | FLAG | 5% or 10 |
| Generation by fuel: Natural gas | billion kWh | - / 1,570 | 1,334 / 1,469 (-9.2%) ! nc | 1,823 / 1,577 (+15.6%) ! | 2,087 / 1,779 (+17.3%) ! | 2,693 / 2,304 (+16.9%) ! | FLAG | 5% or 10 |
| Generation by fuel: Nuclear power | billion kWh | - / 783.9 | 785.1 / 801.7 (-2.1%) nc | 784.9 / 801.7 (-2.1%) | 785.3 / 801.7 (-2.0%) | 785.6 / 801.7 (-2.0%) | PASS | 5% or 10 |
| Generation by fuel: Renewable sources | billion kWh | - / 1,011 | 1,780 / 1,552 (+14.7%) ! nc | 2,050 / 2,157 (-5.0%) | 2,181 / 2,431 (-10.3%) ! | 2,247 / 2,551 (-11.9%) ! | FLAG | 5% or 10 |
| Generation by fuel: Conventional hydroelectric power (in renewables) | billion kWh | - / 242.6 | 261.0 / 274.5 (-4.9%) nc | 261.0 / 276.1 (-5.5%) ! | 261.0 / 276.0 (-5.4%) ! | 261.0 / 276.1 (-5.5%) ! | FLAG | 5% or 10 |
| Generation by fuel: Wind (in renewables) | billion kWh | - / 462.8 | 671.3 / 657.4 (+2.1%) nc | 858.4 / 1,132 (-24.2%) ! | 978.3 / 1,349 (-27.5%) ! | 1,018 / 1,449 (-29.8%) ! | FLAG | 5% or 10 |
| Generation by fuel: Solar (in renewables) | billion kWh | - / 274.2 | 810.7 / 577.1 (+40.5%) ! nc | 894.1 / 685.5 (+30.4%) ! | 904.5 / 727.9 (+24.3%) ! | 931.8 / 736.6 (+26.5%) ! | FLAG | 5% or 10 |
| Generation: Coal, natural gas, nuclear and renewables together | billion kWh | - / 4,093 | 4,405 / 4,288 (+2.7%) nc | 4,760 / 4,658 (+2.2%) | 5,155 / 5,074 (+1.6%) | 5,732 / 5,657 (+1.3%) | PASS | 5% or 10 |
| Electricity sales | billion kWh | 4,069 / 4,069 (+0.0%) | 4,295 / 4,291 (+0.1%) nc | 4,629 / 4,639 (-0.2%) | 5,000 / 5,034 (-0.7%) | 5,529 / 5,575 (-0.8%) | PASS | 3% or 20 |
| End-use prices: Residential | cents/kWh | 16.68 / 16.68 (+0.0%) | 16.29 / 16.29 (-0.0%) nc | 17.80 / 16.78 (+6.1%) ! | 18.96 / 17.10 (+10.9%) ! | 18.00 / 17.45 (+3.2%) | FLAG | 5% or 0.1 |
| End-use prices: Commercial | cents/kWh | 13.48 / 13.48 (+0.0%) | 12.89 / 13.00 (-0.8%) nc | 14.17 / 13.44 (+5.4%) ! | 14.90 / 13.66 (+9.1%) ! | 13.96 / 13.69 (+2.0%) | FLAG | 5% or 0.1 |
| End-use prices: Industrial | cents/kWh | 9.07 / 9.07 (+0.0%) | 8.60 / 8.71 (-1.3%) nc | 9.70 / 9.11 (+6.5%) ! | 10.26 / 9.33 (+10.0%) ! | 9.24 / 9.21 (+0.3%) | FLAG | 5% or 0.1 |
| End-use prices: Transportation | cents/kWh | 15.41 / 15.41 (+0.0%) | 14.60 / 14.70 (-0.6%) nc | 15.59 / 15.25 (+2.2%) | 16.15 / 15.56 (+3.8%) | 15.90 / 15.80 (+0.6%) | PASS | 5% or 0.1 |
| End-use prices: All sectors average | cents/kWh | 13.54 / 13.54 (+0.0%) | 13.08 / 13.16 (-0.6%) nc | 14.43 / 13.67 (+5.5%) ! | 15.25 / 13.93 (+9.5%) ! | 14.37 / 14.05 (+2.3%) | FLAG | 5% or 0.1 |
| Emissions from the electric power sector: Carbon dioxide | million metric tons | 1,436 / 1,436 (+0.0%) | 974.1 / 1,109 (-12.1%) ! nc | 658.4 / 706.5 (-6.8%) ! | 672.8 / 624.2 (+7.8%) ! | 967.0 / 830.4 (+16.4%) ! | FLAG | 3% or 5 |

## Table 9. Electricity generating capacity

| Series | Unit | 2025 | 2030 | 2035 | 2040 | 2050 | Status | Tolerance |
|---|---|---|---|---|---|---|---|---|
| Electric power sector capacity: Coal | gigawatts | - / 159.2 | 101.1 / 88.24 (+14.6%) nc | 18.00 / 16.27 (+10.7%) | 18.00 / 16.22 (+11.0%) | 4.73 / 0.057 (+8264.0%) ! | FLAG | 15% or 2 |
| Electric power sector capacity: Oil and natural gas steam | gigawatts | - / 87.30 | 52.76 / 109.7 (-51.9%) ! nc | 47.82 / 100.7 (-52.5%) ! | 34.11 / 51.96 (-34.4%) ! | 33.99 / 51.18 (-33.6%) ! | FLAG | 15% or 2 |
| Electric power sector capacity: Combined cycle | gigawatts | - / 265.5 | 279.8 / 290.6 (-3.7%) nc | 395.7 / 356.5 (+11.0%) | 477.2 / 430.5 (+10.8%) | 603.9 / 537.1 (+12.4%) | PASS | 15% or 2 |
| Electric power sector capacity: Combustion turbine/diesel | gigawatts | - / 147.7 | 154.8 / 170.6 (-9.3%) nc | 172.6 / 207.5 (-16.8%) ! | 178.1 / 266.6 (-33.2%) ! | 201.1 / 302.0 (-33.4%) ! | FLAG | 15% or 2 |
| Electric power sector capacity: Nuclear | gigawatts | - / 96.86 | 98.63 / 98.63 (+0.0%) nc | 98.63 / 98.63 (+0.0%) | 98.63 / 98.63 (+0.0%) | 98.63 / 98.63 (+0.0%) | HELD | 15% or 2 |
| Electric power sector capacity: Pumped storage | gigawatts | - / 23.16 | 23.16 / 23.16 (+0.0%) nc | 23.16 / 23.16 (+0.0%) | 23.16 / 23.16 (+0.0%) | 23.16 / 23.16 (+0.0%) | HELD | 15% or 2 |
| Electric power sector capacity: Diurnal storage | gigawatts | - / 43.68 | 82.24 / 88.03 (-6.6%) nc | 107.3 / 100.0 (+7.3%) | 110.3 / 103.3 (+6.8%) | 112.6 / 104.1 (+8.2%) | PASS | 15% or 2 |
| Electric power sector capacity: Conventional hydroelectric power | gigawatts | - / 79.22 | 79.23 / 79.78 (-0.7%) nc | 79.23 / 80.10 (-1.1%) | 79.23 / 80.10 (-1.1%) | 79.23 / 80.10 (-1.1%) | PASS | 15% or 2 |
| Electric power sector capacity: Wind | gigawatts | - / 159.0 | 205.7 / 211.7 (-2.8%) nc | 295.6 / 344.1 (-14.1%) | 379.2 / 403.5 (-6.0%) | 412.5 / 427.6 (-3.5%) | PASS | 15% or 2 |
| Electric power sector capacity: Solar | gigawatts | - / 154.5 | 351.5 / 257.6 (+36.4%) ! nc | 397.9 / 304.8 (+30.5%) ! | 397.9 / 323.2 (+23.1%) ! | 400.0 / 326.2 (+22.6%) ! | FLAG | 15% or 2 |
| Electric power sector capacity: Other renewable and other | gigawatts | - / 6.72 | 6.86 / 8.00 (-14.3%) nc | 6.86 / 10.63 (-35.5%) ! | 6.88 / 12.41 (-44.6%) ! | 6.88 / 13.86 (-50.4%) ! | FLAG | 15% or 2 |
| Electric power sector capacity: Total | gigawatts | - / 1,223 | 1,436 / 1,426 (+0.7%) nc | 1,643 / 1,642 (+0.0%) | 1,803 / 1,810 (-0.4%) | 1,977 / 1,964 (+0.6%) | PASS | 15% or 2 |

## Table 13. Natural gas supply, disposition, and prices

| Series | Unit | 2025 | 2030 | 2035 | 2040 | 2050 | Status | Tolerance |
|---|---|---|---|---|---|---|---|---|
| Dry gas production | trillion cubic feet | - / 39.16 | - / 41.42 | - / 44.94 | - / 46.93 | - / 52.71 | NOT IN RUN | 5% or 0.1 |
| Pipeline imports | trillion cubic feet | - / 3.18 | - / 2.92 | - / 2.17 | - / 2.30 | - / 2.74 | NOT IN RUN | 5% or 0.1 |
| Pipeline exports | trillion cubic feet | - / 3.47 | - / 3.78 | - / 4.01 | - / 4.28 | - / 4.60 | NOT IN RUN | 5% or 0.1 |
| Liquefied natural gas exports | trillion cubic feet | - / 5.43 | - / 8.37 | - / 9.79 | - / 10.12 | - / 11.22 | NOT IN RUN | 5% or 0.1 |
| Consumption by sector: Residential | trillion cubic feet | 4.75 / 4.75 (+0.0%) | 4.64 / 4.62 (+0.5%) nc | 4.33 / 4.40 (-1.4%) | 4.14 / 4.25 (-2.6%) | 3.95 / 3.95 (-0.1%) | PASS | 5% or 0.1 |
| Consumption by sector: Commercial | trillion cubic feet | 3.51 / 3.51 (+0.0%) | 3.37 / 3.35 (+0.7%) nc | 3.17 / 3.25 (-2.6%) | 3.12 / 3.26 (-4.4%) | 3.24 / 3.24 (-0.2%) | PASS | 5% or 0.1 |
| Consumption by sector: Industrial | trillion cubic feet | 8.62 / 8.62 (+0.0%) | 8.32 / 8.31 (+0.2%) nc | 8.62 / 8.80 (-2.0%) | 8.87 / 9.29 (-4.5%) | 10.16 / 10.34 (-1.8%) | PASS | 5% or 0.1 |
| Consumption by sector: Electric power | trillion cubic feet | 12.78 / 12.78 (+0.0%) | 9.51 / 11.73 (-19.0%) ! nc | 12.70 / 12.28 (+3.5%) | 14.43 / 13.34 (+8.2%) ! | 18.05 / 16.70 (+8.1%) ! | FLAG | 5% or 0.1 |
| Consumption by sector: Transportation | trillion cubic feet | 0.085 / 0.085 (+0.0%) | 0.102 / 0.102 (+0.3%) nc | 0.103 / 0.102 (+1.0%) | 0.127 / 0.124 (+2.0%) | 0.279 / 0.270 (+3.1%) | PASS | 5% or 0.1 |
| Consumption by sector: Total | trillion cubic feet | 29.75 / 29.75 (+0.0%) | 25.95 / 28.11 (-7.7%) ! nc | 28.93 / 28.83 (+0.4%) | 30.73 / 30.30 (+1.4%) | 35.71 / 34.54 (+3.4%) | FLAG | 5% or 0.1 |
| Henry Hub spot price | $/MMBtu | 3.47 / 3.47 (+0.0%) | 3.89 / 4.45 (-12.6%) ! nc | 6.62 / 5.10 (+29.8%) ! | 7.61 / 5.25 (+45.0%) ! | 3.91 / 4.63 (-15.4%) ! | FLAG | 5% or 0.1 |
| Delivered prices: Residential | $/MMBtu | 14.58 / 14.58 (+0.0%) | 13.54 / 13.91 (-2.7%) nc | 16.30 / 14.66 (+11.2%) ! | 17.25 / 14.94 (+15.5%) ! | 15.09 / 15.32 (-1.5%) | FLAG | 5% or 0.1 |
| Delivered prices: Commercial | $/MMBtu | 10.27 / 10.27 (+0.0%) | 10.86 / 11.20 (-3.0%) nc | 13.79 / 12.21 (+13.0%) ! | 14.74 / 12.50 (+17.9%) ! | 12.44 / 12.68 (-1.9%) | FLAG | 5% or 0.1 |
| Delivered prices: Industrial | $/MMBtu | 4.51 / 4.51 (+0.0%) | 4.88 / 5.41 (-9.9%) ! nc | 7.71 / 5.89 (+31.0%) ! | 8.51 / 5.91 (+44.2%) ! | 4.86 / 5.38 (-9.8%) ! | FLAG | 5% or 0.1 |
| Delivered prices: Electric power | $/MMBtu | 3.81 / 3.81 (+0.0%) | 4.04 / 4.70 (-14.1%) ! nc | 7.24 / 5.09 (+42.4%) ! | 8.05 / 5.17 (+55.6%) ! | 4.29 / 4.62 (-7.1%) ! | FLAG | 5% or 0.1 |

## Table 15. Coal supply, disposition, and prices

| Series | Unit | 2025 | 2030 | 2035 | 2040 | 2050 | Status | Tolerance |
|---|---|---|---|---|---|---|---|---|
| Consumption by sector: Commercial and institutional | quads | 0.012 / 0.012 (+0.0%) | 0.013 / 0.013 (+0.0%) nc | 0.013 / 0.013 (+0.0%) | 0.013 / 0.013 (+0.0%) | 0.013 / 0.013 (+0.0%) | HELD | 3% or 0.05 |
| Consumption by sector: Coke plants (metallurgical coal) | quads | 0.418 / 0.418 (+0.0%) | 0.414 / 0.414 (-0.0%) nc | 0.378 / 0.378 (-0.0%) | 0.330 / 0.330 (-0.0%) | 0.255 / 0.255 (-0.0%) | HELD | 3% or 0.05 |
| Consumption by sector: Other industrial | quads | 0.400 / 0.400 (+0.0%) | 0.357 / 0.358 (-0.3%) nc | 0.354 / 0.354 (+0.0%) | 0.331 / 0.334 (-0.9%) | 0.292 / 0.295 (-0.9%) | PASS | 3% or 0.05 |
| Consumption by sector: Electric power | quads | 7.51 / 7.51 (+0.0%) | 5.67 / 4.96 (+14.2%) ! nc | 1.55 / 1.48 (+4.1%) ! | 1.55 / 0.854 (+80.9%) ! | 0.094 / 0.021 (+343.2%) ! | FLAG | 3% or 0.05 |
| Consumption by sector: Total coal consumption | quads | 7.93 / 7.93 (+0.0%) | 6.04 / 5.33 (+13.2%) ! nc | 1.92 / 1.86 (+3.3%) ! | 1.90 / 1.21 (+56.9%) ! | 0.398 / 0.328 (+21.4%) ! | FLAG | 3% or 0.05 |
| Delivered prices: Electric power | $/MMBtu | 2.56 / 2.56 (+0.0%) | 2.47 / 2.46 (+0.2%) nc | 2.51 / 2.48 (+1.3%) | 2.70 / 2.64 (+2.3%) | 2.55 / 2.43 (+5.2%) ! | FLAG | 5% or 0.1 |
| Delivered prices: Industrial (steam coal) | $/MMBtu | 3.98 / 3.98 (+0.0%) | 3.73 / 3.73 (+0.1%) nc | 3.64 / 3.66 (-0.6%) | 3.67 / 3.67 (+0.0%) | 3.66 / 3.64 (+0.3%) | PASS | 5% or 0.1 |

## Table 18. Energy-related carbon dioxide emissions by sector and source

| Series | Unit | 2025 | 2030 | 2035 | 2040 | 2050 | Status | Tolerance |
|---|---|---|---|---|---|---|---|---|
| By sector: Residential | million metric tons | 329.9 / 329.9 (+0.0%) | 317.9 / 316.6 (+0.4%) nc | 297.2 / 300.6 (-1.2%) | 283.7 / 289.8 (-2.1%) | 269.4 / 269.4 (-0.0%) | PASS | 3% or 5 |
| By sector: Commercial | million metric tons | 260.4 / 260.4 (+0.0%) | 256.7 / 255.4 (+0.5%) nc | 248.2 / 252.7 (-1.8%) | 247.8 / 255.6 (-3.0%) ! | 258.1 / 258.2 (-0.0%) | FLAG | 3% or 5 |
| By sector: Industrial | million metric tons | 1,012 / 1,012 (+0.0%) | 1,016 / 1,014 (+0.2%) nc | 1,060 / 1,067 (-0.7%) | 1,101 / 1,119 (-1.6%) | 1,204 / 1,212 (-0.7%) | PASS | 3% or 5 |
| By sector: Transportation | million metric tons | 1,793 / 1,793 (+0.0%) | 1,706 / 1,707 (-0.1%) nc | 1,485 / 1,486 (-0.1%) | 1,319 / 1,320 (-0.1%) | 1,166 / 1,167 (-0.1%) | PASS | 3% or 5 |
| By sector: Electric power | million metric tons | 1,436 / 1,436 (+0.0%) | 974.1 / 1,109 (-12.1%) ! nc | 658.4 / 706.5 (-6.8%) ! | 672.8 / 624.2 (+7.8%) ! | 967.0 / 830.4 (+16.4%) ! | FLAG | 3% or 5 |
| By sector: Total carbon dioxide | million metric tons | 4,832 / 4,832 (+0.0%) | 4,271 / 4,402 (-3.0%) nc | 3,748 / 3,813 (-1.7%) | 3,624 / 3,609 (+0.4%) | 3,864 / 3,737 (+3.4%) ! | FLAG | 3% or 5 |
| By fuel: Petroleum and other liquids (combustion, fuel use x EIA carbon factors) | million metric tons | 2,466 / 2,466 (+0.0%) | 2,378 / 2,379 (-0.0%) nc | 2,176 / 2,177 (-0.1%) | 2,028 / 2,028 (+0.0%) | 1,905 / 1,906 (-0.1%) | PASS | 3% or 5 |
| By fuel: Natural gas (combustion, fuel use x EIA carbon factors) | million metric tons | 1,632 / 1,632 (+0.0%) | 1,424 / 1,542 (-7.7%) ! nc | 1,587 / 1,582 (+0.4%) | 1,684 / 1,660 (+1.4%) | 1,957 / 1,893 (+3.4%) ! | FLAG | 3% or 5 |
| By fuel: Coal (combustion, fuel use x EIA carbon factors) | million metric tons | 787.2 / 787.2 (+0.0%) | 609.0 / 542.6 (+12.2%) ! nc | 216.3 / 210.6 (+2.7%) | 209.7 / 144.8 (+44.8%) ! | 62.11 / 55.50 (+11.9%) ! | FLAG | 3% or 5 |

## Macroeconomic indicators (Table 20)

| Series | Unit | 2025 | 2030 | 2035 | 2040 | 2050 | Status | Tolerance |
|---|---|---|---|---|---|---|---|---|
| Real gross domestic product | billion chained 2017 dollars | - / 22,086 | - / 24,183 | - / 26,608 | - / 28,974 | - / 33,557 | NOT IN RUN | 1% or 0 |
