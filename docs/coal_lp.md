# Reduced coal distribution LP (linopy + HiGHS)

`nems_open.coal.lp` solves a cut-down `PartialLeastCostDomesticCoal` for one year at a time; `supply.Chain` prices the 14 supply curves year to year; `lp_report` runs the chain and compares with cb2026 (`PYTHONPATH=src python -m nems_open.coal.lp_report 2025 2030 2035`).

## What the LP contains
14 supply curves with 11 priced steps and a capacity limit; shipments to the 16 coal demand regions for electric power, residential/commercial (R1, R2), industrial (I1 to I3) and coking (C1, C2) over the feasible routes, at first-tier rates scaled by the RCAF escalator; US exports as fixed amounts from each supply region; STEO production bands for Appalachia, Interior and West in 2025 and 2026 (2% tolerance, stock slack priced 14, 12, 8).

Electricity demand is met per plant type (pt2 = NUTSEC + 14, 38 groups) and demand region, as in EIA's
DomesticElectricityDemandRequirement, with EIA's SubbituminousDiversity and LigniteDiversity caps
(`coal/electric.py`, default in `lp_report.run`; `by_type=False` or `--flat` gives the older one-demand-per-region
LP). The caps are rebuilt from EMM's unit-level coal burn and the plant shares in cmmProfiles.txt and
match what the CMM wrote back to NEMS (USO2GRP EFD_SB_DVLIM, EFD_LG_DVLIM): exact from 2040, within 4%
nationally in 2030 and 2035. Lignite caps apply in every cell (0.05 TBtu where no plant burns lignite);
sub-bituminous caps only where 0 < Sdvconct_2 < 999. Each cap carries a 999 slack (EIA's has none); a
few cells in 2029 and 2030 need under 1 TBtu of it, because demand there exceeds both caps with no
bituminous route. Those cells are left out of the regional electricity price.

Second-tier electricity transport is in (`electric.tier1_bound`, `lp.solve(tier1=...)`): the tier-1 bound
matches EFD_TIER1_LIM (12,124 vs 12,129 TBtu in 2025, exact in 2040). It changes nothing in cb2026, faithfully:
the premium is trate3 - trate2, and the shipped trate3 equals trate2 on all 224 electricity routes.

SO2 does not bind in cb2026 either, so it is not ported: SulfpenConstraint is generated only before the
CSAPR start year (2015), and the regional Copy_SULFPNConstraint allows Tso2_lim_by_clrg2 * 1000 (about
145,000) against a regional sulfur load in the tens. Their escape variables are commented out of EIA's
variable set, so they are hard limits when active.

Contracts are in (`electric.contract_floor`, `lp.solve(contracts=...)`, `lp_report --contracts`): floors per curve
and region from cmmProfiles.txt, matching the positive part of EFD_CONT cell by cell (5,810 TBtu in 2024, 1,477 in
2027, 350 in 2030), with EIA's quirk that every unit of a plant carries the plant's whole contract. EIA's 999
ContractEscape is used for 7 to 64 TBtu in some years. They barely move production (Interior stays 89 Mt in
2027-2030) and they turn the raw electricity demand duals negative, so they are off by default until EIA's
electricity pricing procedure (CalculationOfElectricityPricingEquation) is ported.

Why Interior is high in 2027-2030: both Interior curves produce at capacity (70.1 of 70.8 and 18.5 of 18.6 Mt
in 2028), while EIA's run produces 54 to 63 Mt. So in EIA's run Interior coal is dearer relative to PRB than in
ours. The suspects are the forecast-year supply curves, which here run on substitutes for the lagged state in
the AIMMS case files (FY_PROD_CAP, LAG_PRI, QTarget; table below). The AIMMS reference export settles that.

## Reference: EIA's coal model replayed in AIMMS (coal/aimms_run.py)

AIMMS 25.5.7.1 (academic licence) runs EIA's coal.ams headless. `python -m nems_open.coal.aimms_run <run> 2024 2050 2`
copies models/coal into a run folder, writes each year's GlobalDataToAIMMS_<year>_<itr>.txt from the cb2026 restart
the way NEMS's aimms_util.write_aimms_input does (composite tables, columns aligned, base year all years, later years
their own slice), writes cl_runval.txt, adds a File_Call entry point (Coal_API_Call without the DEX request) and a
wrapper project that loops years and iterations in one process, so the model carries its lag state as in NEMS. After
each solve File_Call writes the supply curves, lag state, caps, tier bounds, contracts, demand duals, flows and rates
(`aimms_run.read_export` parses them). 54 solves (2024-2050, two iterations) take about 5 minutes. Add `mps` to dump
CPLEX's generated LP through EIA's own debug switch (AIMCLSolvDebug).

What the replay shows (`python -m nems_open.coal.aimms_compare <run> <years>`):
- The replay on converged inputs reproduces the restart from 2027 (2028: 447 vs 441 Mt; 2040 and 2050 equal by region).
- Every input this port rebuilds equals EIA's in the replay, 2030: plant-type demand (4,961.7 TBtu), diversity caps
  (difference 0.0), tier-1 bounds, contracts, all 224 power transport rates (within 0.4%).
- Two pieces were missing and are now in: the MATS rule (`electric.mats_adder`: after 2015 a plant type that cannot
  burn a rank without activated carbon pays ACI_CST/10 per MMBtu, 10 where EIA codes it as impossible), and exports
  pinned by rank (`export_rule="rank"`, CLEXPRANK), which match the replay's exports by rank exactly. With exports pinned
  by supply region the LP exported central Appalachian steam coal where EIA exports metallurgical coal.
- Fed EIA's own supply curves for the year, our LP still produces too much Interior and too little PRB in 2027-2035
  (2030: Interior 82 vs 55 Mt, PRB 127 vs 152; total regional miss 59 Mt with rank exports, 75 with region exports;
  2050 within 18). So the gap is in the LP, not in the curves or lag state. EIA's demand duals show region-specific
  extra costs on used routes (about 0.03 per MMBtu in 07EN, 0.5-0.6 in 11C2 and 14CU) that are not sulfur-proportional;
  the matrix comparison (MPS dump) is the next step to name the constraint.
- What binds in EIA's 2030 solve (shadow prices exported by File_Call to duals_<year>_<itr>.txt): only contracts
  (central Appalachia into 04S2, duals 0.59 and 0.22; two lignite contracts on their 999 escape). Diversity caps,
  regional SO2, capacity, mercury and activated carbon all have zero duals.
- Pinning exports per curve to the replay's (`export_rule="curve"`, diagnostic only) makes Appalachia match
  (2030: 76/75 and 69/66 Mt) but leaves Interior 78 vs 55 and PRB 116 vs 152. Contracts on change nothing. So with
  equal curves, rates, demands, caps, contracts and exports, our LP still sends Interior coal where EIA sends PRB
  (07EN: EIA all PRB, ours mostly Interior), although by the exported rates and step prices Interior is cheaper
  delivered there (about 1.02 vs 1.06 per MMBtu). EIA's demand duals over MC_JPGDP(2024) = 2.356 equal rate plus
  supply shadow on most used routes, but carry a constant extra per region on others (0.03 in 07EN, 0.4-0.6 in
  11C2, 12WS, 14CU, 15ZN). That points at a cost term or bound in EIA's objective that this port lacks.
  The MPS dump works (`aimms_run ... mps`, 14 files cpx000NN.mps) but AIMMS writes presolved, unnamed rows and
  columns (c1, x1); the next step is a named constraint listing (AIMMS option constraint_listing) for 2030.

## What it leaves out (the real model has 125 equation families)
Mercury and activated carbon, activated carbon, SO2 and mercury, Trate4x limits, coal-to-liquids, imports, the international export network and ICMM matching, STEO coke, industrial and import calibration, and every escape variable. Prices are LP duals of the demand constraints, without EIA's postprocessing (the demand shadow-price scaling and the electricity pricing procedure).

## Substitutions for the AIMMS case-file lag state
| Quantity | Where the model gets it | What is used here |
|---|---|---|
| FY_PROD_CAP, forecast years | prior-year pricing state | restart USO2GRP/XCL_PCAP (the model's own output) divided by Btu |
| QTarget, LAG_PROD | previous solved production | previous year's solution from this chain; 2024 = BY_PROD |
| LAG_PRI | mcnt_prev (previous minemouth price) | previous year's step price at the curve's output; 2024 = BY_MMP92 |
| Exports | international network and ICMM match | fixed from the restart: COALPROD2 minus COALPROD, by supply region |
| Electric demand | Qdutzr less stocks | restart COALEMM/qclclnr summed over plant types; stocks ignored |
| bsrzr_util | not found in the data | taken as 1 |
| CMM_CL_BTUs_A / TBTU in Sdvconct_1_A | CMM.mdb Contracts table (not shipped) | 1 for plants with a Plant_T_Prof row in cmmProfiles.txt, else 0 |
| Tolerance on STEO bands | steo_benchmark_cmm.csv | 2% |
| STEO limits | clsteo.txt | the shipped file (a different vintage from steovars.csv for 2024 to 2026) |

## Results against cb2026 (model / EIA), plant types and diversity caps (current default)
| year | production Mt (model / EIA); by region 1APN, 2APR, 3INR, 4LGN, 5PRB, 6WSR | delivered price 1987$/MMBtu (model / EIA) |
|---|---|---|
| 2025 | 515 / 510 (93/82, 68/70, 66/77, 30/32, 211/207, 47/42) | PCLEL 1.31/1.05; PCLIN 1.73/1.64; PMCIN 2.29/2.65 |
| 2026 | 503 / 495 (93/80, 57/74, 74/76, 30/32, 202/196, 47/36) | PCLEL 1.37/1.04; PCLIN 1.74/1.59; PMCIN 2.35/2.65 |
| 2027 | 482 / 485 (90/70, 54/69, 89/63, 31/31, 185/216, 33/36) | PCLEL 1.22/1.02; PCLIN 1.75/1.55; PMCIN 2.56/2.65 |
| 2028 | 438 / 441 (78/69, 55/66, 89/54, 29/29, 157/189, 31/32) | PCLEL 1.21/1.01; PCLIN 1.70/1.55; PMCIN 2.54/2.65 |
| 2029 | 415 / 419 (77/65, 55/68, 89/58, 30/30, 135/169, 31/30) | PCLEL 1.23/1.02; PCLIN 1.69/1.55; PMCIN 2.53/2.65 |
| 2030 | 397 / 400 (74/69, 55/67, 89/56, 28/28, 120/151, 30/29) | PCLEL 1.24/1.01; PCLIN 1.69/1.54; PMCIN 2.52/2.66 |
| 2035 | 219 / 221 (66/68, 53/54, 46/39, 0/0, 32/36, 22/24) | PCLEL 1.11/1.03; PCLIN 1.60/1.51; PMCIN 2.49/2.65 |
| 2040 | 181 / 185 (66/76, 45/47, 44/30, 0/0, 8/8, 19/24) | PCLEL 1.10/1.10; PCLIN 1.62/1.51; PMCIN 2.50/2.64 |
| 2050 | 132 / 139 (65/70, 35/37, 11/10, 0/0, 4/4, 18/17) | PCLEL 1.02/1.02; PCLIN 1.70/1.50; PMCIN 2.49/2.60 |

Against the one-demand-per-region LP below: total absolute regional miss falls from 110 to 35 Mt in 2025,
111 to 51 in 2026, 93 to 82 in 2030, 46 to 16 in 2035, 44 to 31 in 2040. Lignite (4LGN) is within 3 Mt in every year
(it was 50% high in 2030 and 21 Mt where EIA has 0 in 2035). Worse: 2027 (44 to 95), and from 2027 to 2030
Interior (3INR) is 30 to 60% high and PRB 15 to 20% low, with the electric price about 20% high. The likely
cause is the forecast-year supply curves (see "Why Interior is high" above); SO2, second-tier transport and
contracts were checked and do not explain it.

## Results against cb2026, one electricity demand per region (earlier reduced LP)
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
