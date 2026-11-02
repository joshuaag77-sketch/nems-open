# EMM data layer (step 1)

Package `nems_open.emm`. Reads EIA's electricity inputs from `nems-upstream/input/emm` into numpy arrays. No Fortran, AIMMS or paid software. Region axis is NEMS order: EMM regions 1..25, then Alaska, Hawaii, US total (28 rows). Census axis has 11 slots (9 divisions, California, US). Year axis is 1990..2050 (61).

| Module | What it gives | Checked against the AEO2026 reference run |
|---|---|---|
| `regions` | 28 region names and codes; share of each EMM region's load in each census division | `DSMTFEFP/MAPPNTOC`, to 1e-6 |
| `plants` | 27,337 existing and planned units; capacity by year, EFD type, owner, vintage | `UDATOUT/UCAP**`, 2020 to 2026: hydro, wind, solar, gas CC and CT, NUG nuclear within 0.3 GW per region; utility nuclear, coal, oil/gas steam within 2 GW per region (coal 4% national) |
| `technology` | 80 ECP build types (life, O&M, heat rate, overnight cost, outage rates), regional multipliers, 54 EFD plant types | Every plant-file type is defined; sanity ranges |
| `load` | 36 typical-day load shapes per region (sum to 1), day weights, 114 end-use shapes, T&D loss | Shape energy sums to 1; implied load factor within 5% of `DSMTFEFP/SYSTEMLF` |
| `history` | 2010 to 2024 sales, prices, emissions, generation, fuel use | US CO2, SO2, NOx 2010 to 2020 exact; fuel use for power within 0.2%; nuclear, IGCC, fuel cell generation exact |
| `system` | Region-to-region link costs, annual controls (nuclear derate, hydro factor), Canadian supply steps, fuel hookup costs | Shape and range checks only (no overlap in the restart file) |
| `inputs.load()` | All of the above in one object | |

## Findings that matter for the next steps

- The plant file matches NEMS only from the last history years (2020 to 2026). Earlier years use history that includes units since retired. Start the LP from 2024 or 2025.
- Overnight plant cost is `UPOVR` in `ecpdaty.xlsx` (COSTPERF), not the database; 9999 means the type cannot be built. The database's `EPCOVR`, `EPCCRF`, `EPCFOM` are transmission connection costs.
- Some regional emissions history differs from the restart file by up to about 25%: NEMS re-allocates after reading. The US total is exact.
- Input base-year loads (`BSYRLD`) are zero in the file. NEMS fills them from the demand modules, so the LDSM port (step 3) takes sales as an input.
- Not yet loaded (later steps): EFP finance tables (`V_EMM_EFP_*`, `finregy.xlsx`), RPS tranches, cogeneration maps, hydro and wind sites, scrubber and CCS retrofit tables, policy switches in `emmcntl.txt`.
