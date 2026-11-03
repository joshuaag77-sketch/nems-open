# Reduced coal distribution LP (linopy + HiGHS)

`nems_open.coal.lp` solves a cut-down `PartialLeastCostDomesticCoal` for one year at a time; `supply.Chain` prices the 14 supply curves year to year; `lp_report` runs the chain and compares with cb2026 (`PYTHONPATH=src python -m nems_open.coal.lp_report 2025 2030 2035`).

## What the LP contains
14 supply curves with 11 priced steps and a capacity limit; shipments to the 16 coal demand regions for electric power, residential/commercial (R1, R2), industrial (I1 to I3) and coking (C1, C2) over the feasible routes, at first-tier rates scaled by the RCAF escalator; US exports as fixed amounts from each supply region; STEO production bands for Appalachia, Interior and West in 2025 and 2026 (2% tolerance, stock slack priced 14, 12, 8).

## What it leaves out (the real model has 125 equation families)
Second-tier electricity transport and its price rule, contracts, sub-bituminous and lignite diversity limits, activated carbon, SO2 and mercury, Trate4x limits, coal-to-liquids, imports, the international export network and ICMM matching, STEO coke, industrial and import calibration, and every escape variable. Prices are LP duals of the demand constraints, without EIA's postprocessing (the demand shadow-price scaling and the electricity pricing procedure).

## Substitutions for the AIMMS case-file lag state
| Quantity | Where the model gets it | What is used here |
|---|---|---|
| FY_PROD_CAP, forecast years | prior-year pricing state | restart USO2GRP/XCL_PCAP (the model's own output) divided by Btu |
| QTarget, LAG_PROD | previous solved production | previous year's solution from this chain; 2024 = BY_PROD |
| LAG_PRI | mcnt_prev (previous minemouth price) | previous year's step price at the curve's output; 2024 = BY_MMP92 |
| Exports | international network and ICMM match | fixed from the restart: COALPROD2 minus COALPROD, by supply region |
| Electric demand | Qdutzr less stocks | restart COALEMM/qclclnr summed over plant types; stocks ignored |
| bsrzr_util | not found in the data | taken as 1 |
| Tolerance on STEO bands | steo_benchmark_cmm.csv | 2% |
| STEO limits | clsteo.txt | the shipped file (a different vintage from steovars.csv for 2024 to 2026) |

## Results against cb2026 (model / EIA)
| year | production Mt (model / EIA); by region 1APN, 2APR, 3INR, 4LGN, 5PRB, 6WSR | delivered price 1987$/MMBtu (model / EIA) |
|---|---|---|
| 2025 | 531 / 510 (93/82, 66/70, 39/77, 47/32, 247/207, 40/42) | PCLEL 1.49/1.05; PCLIN 1.95/1.64; PMCIN 2.12/2.65 |
| 2026 | 514 / 495 (93/80, 57/74, 50/76, 29/32, 241/196, 43/36) | PCLEL 1.50/1.04; PCLIN 1.97/1.59; PMCIN 2.18/2.65 |
| 2027 | 499 / 485 (70/70, 54/69, 73/63, 45/31, 216/216, 41/36) | PCLEL 1.07/1.02; PCLIN 1.63/1.55; PMCIN 2.56/2.65 |
| 2030 | 406 / 400 (72/69, 55/67, 73/56, 47/28, 120/151, 40/29) | PCLEL 1.07/1.01; PCLIN 1.61/1.54; PMCIN 2.52/2.66 |
| 2035 | 224 / 221 (66/68, 53/54, 43/39, 21/0, 20/36, 22/24) | PCLEL 0.97/1.03; PCLIN 1.59/1.51; PMCIN 2.49/2.65 |
| 2040 | 186 / 185 (66/76, 45/47, 39/30, 14/0, 5/8, 18/24) | PCLEL 1.02/1.10; PCLIN 1.61/1.51; PMCIN 2.50/2.64 |
| 2050 | 132 / 139 (65/70, 35/37, 11/10, 0/0, 4/4, 18/17) | PCLEL 1.02/1.02; PCLIN 1.70/1.50; PMCIN 2.49/2.60 |

Reading the table: the restart's COALPROD2 row 11 is production by supply region, and rows 1 to 10 are demand divisions.

## Misses, stated plainly
- The plan's target is 0.1% on every cell. This reduced LP does not come close to that: regional production misses by 10% to 50% in several cells (3INR in 2025 and 2026 is half the restart; 4LGN is 50% high in 2030), though national production is within 1% to 5% in every year shown.
- Delivered electric price is 40% high in the STEO years 2025 and 2026. The cause is most likely the STEO band shadow prices entering the demand duals; EIA's postprocessing is not ported. From 2027 it is within 10%, and industrial is 5% to 13% high throughout.
- East/West split (CQSBB) was dropped from the table because the regional grouping that reproduces the restart's 6,261/4,432 TBtu was not found.
- The 2024 base year is history in the restart, not an LP result, so it is not scored.
- No same-matrix check against EIA's generated LP is possible without an AIMMS run; the objective and duals here are unverified against EIA's.
