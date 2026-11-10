# AEO2025 against AEO2026

What this answers: how much of each headline change between EIA's two public releases comes from changed input data and how much from changed code. Result: **the split is not possible for any module with what we have, and this document says why instead of guessing.** A 2025 oracle now exists for commercial and was checked against the restart (section below); it narrows the gap but does not close it. What does exist is EIA's own change between the two reference runs (below), the readers that make AEO2025 usable, and a test of whether our code reproduces AEO2025 from AEO2025 inputs (it does not).

## Data (fetched with Josh's approval, 2026-11-03)
- `output/aeo2025/ref2025.zip` from github.com/EIAgov/NEMS, tag `AEO2025-Public-Release` (Git LFS, 26,408,808 bytes, sha256 798d3133...: matches the pointer). It holds `ref2025/d031725c/restart.rlx` (172 MB), EIA's reference restart.
- The 2025 tag tarball (47 MB, 244 MB unpacked) and the 56 LFS-stored input files (105.8 MB, each sha256-checked). All under `data/aeo2025/` (git-ignored). Nothing in them is executed; Python that reads them runs with `-I`.
- The 2025 restart is **not** the 2026 format. AEO2026's `restart.rlx` is a numpy archive; AEO2025's is a FILER unformatted sequential file (big-endian record markers; an 80-byte `LABEL=BLOCK,VAR=NAME,FORMAT=...` record, then the raw values). `src/nems_open/rlx.py` reads it with the 2025 `dict.txt` for shapes: 3,925 variables, 3,922 shared with the 2026 archive. 2026 has 482 variables 2025 lacks (456 of them the coal module's, COALEMM). Shapes agree except the residential report arrays below.

## EIA's change between the two reference runs (restart against restart)
| | 2030: AEO2025 / AEO2026 (change) | 2035: AEO2025 / AEO2026 (change) | 2040: AEO2025 / AEO2026 (change) | 2050: AEO2025 / AEO2026 (change) |
|---|---|---|---|---|
| Residential delivered energy, TBtu | 12,112.5 / 11,800.2 (-2.6%) | 12,326.3 / 12,028.5 (-2.4%) | 12,835.0 / 12,358.7 (-3.7%) | 13,525.0 / 12,816.6 (-5.2%) |
| Commercial delivered energy, TBtu | 10,249.5 / 10,450.3 (+2.0%) | 10,919.3 / 11,045.9 (+1.2%) | 11,789.4 / 11,821.3 (+0.3%) | 13,306.1 / 12,855.0 (-3.4%) |
| Industrial delivered energy, TBtu | 25,871.1 / 25,568.4 (-1.2%) | 26,834.3 / 26,734.4 (-0.4%) | 27,955.4 / 28,195.4 (+0.9%) | 30,008.0 / 31,122.8 (+3.7%) |
| Transportation delivered energy, TBtu | 27,175.1 / 27,258.7 (+0.3%) | 24,584.3 / 24,674.8 (+0.4%) | 22,367.6 / 22,684.4 (+1.4%) | 20,627.5 / 21,012.1 (+1.9%) |
| Electric power sector energy, TBtu | 30,458.1 / 31,550.9 (+3.6%) | 28,738.3 / 30,761.9 (+7.0%) | 28,911.3 / 32,207.0 (+11.4%) | 31,314.2 / 35,179.1 (+12.3%) |
| Residential electricity, TBtu | 5,425.8 / 5,416.0 (-0.2%) | 5,746.1 / 5,865.9 (+2.1%) | 6,281.3 / 6,300.5 (+0.3%) | 6,999.1 / 6,882.1 (-1.7%) |
| Commercial electricity, TBtu | 5,127.5 / 5,543.7 (+8.1%) | 5,721.9 / 6,178.5 (+8.0%) | 6,451.8 / 6,881.1 (+6.7%) | 7,696.1 / 7,842.4 (+1.9%) |
| Residential natural gas, TBtu | 4,998.0 / 4,789.5 (-4.2%) | 4,810.2 / 4,559.2 (-5.2%) | 4,710.2 / 4,404.7 (-6.5%) | 4,461.2 / 4,096.0 (-8.2%) |
| Commercial natural gas, TBtu | 3,641.4 / 3,471.1 (-4.7%) | 3,600.4 / 3,374.3 (-6.3%) | 3,663.4 / 3,383.6 (-7.6%) | 3,746.2 / 3,362.2 (-10.2%) |
| Residential electricity price, restart price units | 17.4 / 19.7 (+13.4%) | 18.1 / 20.3 (+11.8%) | 17.6 / 20.7 (+17.6%) | 18.6 / 21.1 (+13.6%) |
| Commercial electricity price, restart price units | 14.3 / 15.7 (+10.0%) | 14.9 / 16.3 (+8.9%) | 14.4 / 16.5 (+14.8%) | 15.0 / 16.5 (+10.2%) |
| Industrial electricity price, restart price units | 9.6 / 10.5 (+9.2%) | 10.3 / 11.0 (+7.3%) | 9.8 / 11.3 (+14.8%) | 10.4 / 11.1 (+7.2%) |
| Real GDP (MC_GDPR) | 24,482.5 / 24,183.1 (-1.2%) | 26,612.4 / 26,608.4 (-0.0%) | 29,006.9 / 28,973.6 (-0.1%) | 34,167.5 / 33,557.5 (-1.8%) |

(`scripts/aeo_diff_table.py` regenerates it. Price units are the restart's own; the dollar year of the price arrays was not checked between releases, so read price changes as indicative.)

## Why the code-versus-input split fails
The split needs two things: our code reproduces each release's reference when run on that release's inputs, and the run on one release's inputs can be repeated on the other's. Tests:

| Module | AEO2026 inputs through our code | AEO2025 inputs through our code |
|---|---|---|
| Residential | reproduces the 2026 restart (qtsrs 11,801 vs 11,800 TBtu, 2030, from the input files) | **cannot run**. The 2025 files have 30 equipment classes, the 2026 code has 29 (the kerosene furnace placeholder was removed); `rsswitch.txt` was folded into the `RSSWITCH` tab of `rsmess.xlsx`; report arrays differ in size (`RSCON/COOLCN` 3 vs 2 classes, `HTRCON` 8 vs 5, `SHTCON` 7 vs 5). Reading the 2025 files needs a re-mapping of classes, which is a code change, not an input change |
| Commercial | reproduces the 2026 restart (qtscm 10,451.6 vs 10,450.3) | runs, but does not reproduce the 2025 restart: NaN in total, coal 13.4 vs 18.2 TBtu (-26%), transport 262 vs 429 (-39%). `CMNewFloorSpace` also changed width (220 vs 227 columns) |
| Transportation, electricity load (LDSM), electricity finance (EFP) | start from EIA's oracle state, not from input files | not run: there is no from-files start, and a 2025 oracle (the 2025 Fortran compiled under WSL, run on the 2025 restart and inputs) has not been built |

A third route, running our 2026 module files with only the 2025 restart's prices and macro as drivers, gives residential 9,495 TBtu against 2025's own 12,112 (20% low) and commercial NaN, because seven arrays our commercial and electric-link code reads (`UECPOUT` wind, solar and PV capacity adjustments, `TRANREP/GLOBAL_BATT_PROD`) do not exist in the 2025 restart and stay at zero, and the residential result is unexplained. A split built on an unvalidated driver run would be a guess, so none is reported.

## What would settle it
1. A 2025 oracle per module: compile the AEO2025 `source/` under WSL (the `wsl-oracle` setup builds the 2026 ones), run each green module on the 2025 restart and inputs, dump state. With it, "code effect" is 2025 oracle against 2026 oracle on the same inputs, which needs no port at all, and "input effect" is the rest.
2. For residential and commercial through our port: a port of the 2025 code path (30 equipment classes, text-file switching costs, the older floorspace layout), checked against that oracle.
3. For the driver-only route: the seven missing arrays recomputed from 2025 inputs.

Until then the table above is the finding: how much changed, with no attribution.

## Update: a 2025 commercial oracle (aeo-diff2)
The AEO2025 Fortran was compiled under WSL (`oracle/build_wsl.sh`, skipping two variables the 2025 source lacks: `applyramp`, `datactrservpenetration`) and run on the ref2025 restart and 2025 input files, dumping 2025, 2030 and 2040. `scripts/aeo_diff_oracle_cmp.py` compares its state with the restart.

Where it reproduces EIA's 2025 reference (national, all regions within the stated bound): electricity (2025: 4,849.90 vs 4,849.86 TBtu; 2030: 5,127.76 vs 5,127.55; 2040: 6,447.8 vs 6,451.8, regional worst 0.55%), natural gas (regional worst 0.007%), distillate (0.014%), LPG, residual, motor gasoline and biomass (all within 1e-6 to 1e-4). Steam and PV drift with time: national 2040 steam 56.29 vs 56.39 (0.2%), PV 298.05 vs 296.35 (0.6%), worst region 2.7% and 7.5%.

Where it does not: **coal** (oracle holds 12.1 TBtu flat; the restart has 16.3, 18.2 and 22.8 for 2025, 2030, 2040) and **kerosene** (2030: 1.78 vs 2.16). Something outside the commercial module that the restart carries is not reproduced, so no attribution is made for coal or kerosene.

Same-code test of the other direction (2025 code on 2026 inputs and the 2026 restart): **refused by the code itself.** The 2025 loader stops with 18 size mismatches, all in the cogeneration block (`CGCOMMCAP`, `CGCOMMGEN`, `CGRESQ` and 15 more): 32,208 values in 2025, 34,892 in 2026, which is 12 against 13 technologies. That is a code change in the data layout, so 2026 inputs cannot be fed to the 2025 code without a mapping, and a mapping would be a guess. The 2026 code on 2025 inputs fails the same way in reverse (it needs arrays the 2025 restart lacks, see above).

Result for commercial: electricity and gas reproduce in 2025, but both split directions are blocked by layout changes (cogeneration technologies, floorspace width). The headline table stands unattributed. Residential was not built: its 2025 files have a different class structure (30 against 29 equipment classes), which blocks it before any oracle run.

What would settle it: map the 12 cogeneration technologies to the 13 (EIA's release notes or the diff of `cogen`), then run the hybrid. The code effect would be the 2025 against 2026 oracle on the same inputs, and the input effect the rest.
