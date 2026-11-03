# Coal inputs and lagged state (plan step 2)

`nems_open.coal.aimms_data` reads AIMMS composite tables and the declarations in `coal.ams`; `inputs.load()` reads the 36 files the scedes file names plus `emmbench.txt`, `coalmapping.txt` and `coalunits.txt`. Result: 225 parameters, 50 sets, no unresolved header, no conflicting duplicate. `mappings.dense(name)` lays a parameter out over its domain sets (elements in file order). `steo.py` reads and regenerates `clsteo.txt`.

## Checked against the restart (tests/test_coal_inputs.py)
- Plant-unit list (533) equals the restart's EMM_CL_UNITS; region, short and long profile indexes match for 533 of 533.
- World coal prices (`hclworld`) match WSCF and WMCF within 0.01 + 0.01%, except the years 2013 to 2015 and 2022 to 2023 (70 of 2,376 cells), where the restart carries a later vintage. Total-cost rows (WTCF) have no data in the file.
- Contract profile matches CMM_CONT_PRF for 1,510 of 1,517 cells; the 7 misses are profile 39, which the restart leaves zero. New-plant profiles equal NEW_SDV_INDX. The subdivision, lignite and transport profile tables hold more profiles than the restart carries (11 short, 11 long, 1 transport), so only those overlap.
- `clsteo.txt`: regenerating it from `steovars.csv` with EIA's loader reproduces 1990 to 2023 in every column. 2024 to 2026 differ because the shipped file is a different STEO vintage than `steovars.csv`. EIA's code comment gives the 1987 deflator as 57.0045; the file has 53.126, and 53.126 is what reproduces the shipped price column.

## Not loadable: lagged state
The model's lag data (`Cases/CMMLagData.data`, `Cases/global_data.data`) are AIMMS binary case files. Only identifier names can be read from them (131 names, in `declarations().lag_identifiers`, e.g. ProductionVolumeTons, ProdVolSolutionPriorYr, LAG_PROD, qprods, USProdPriorCycle). The values need an AIMMS export, or a first model year run from the restart's own arrays. Until then the pricing procedures in step 3 can be checked only where the restart carries the same quantity.
