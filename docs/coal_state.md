# Coal port, step 1: transfer schema and COAL_EXPECT

`nems_open.dictionary` parses EIA's variable dictionary (`input/dict.txt`): 4,405 variables, 114 dimension sizes. Every restart array has its dictionary shape except 16 oddities (scalars stored as `()`, character arrays with a string-length axis, a few wrong declarations; none in the coal arrays but `COALEMM/EMM_CL_UNITS`, which is a character array).

`nems_open.coal.state` builds the CMM's interface from what is actually exchanged:

| Source | Entries | In restart with dictionary shape |
|---|---|---|
| `coalputvars.txt` (NEMS to CMM) | 104 unique (106 lines) | 104 |
| `coalgetvars.txt` (CMM to NEMS) | 157 | 157 |
| `coal.ams` `SendGlobalDataToNEMS` (what AIMMS writes) | 159 | 159 |

The writer adds five arrays the manifest lacks (`CLEXPRANK`, `CLIMPRANK`, `PMCIN`, `CL_CRV_PROD`, `EFD_SC_DR_PT`) and drops three it lists (`PELIN`, `PDSIN`, `XCL_TRATI1`; the first two are input prices). 132 of the 159 are one-year slices (`globalyr`). Use `written_outputs()` as the output contract. `CoalInputs.from_snapshot(snap, year)` returns the 104 inputs.

`nems_open.coal.expect.coal_expect` is COAL_EXPECT from `util_tools.f90`: fill ECP's 30-year coal transport-escalator expectations (`XCL_1TESC`, `XCL_2TESC`, shape curve x slot x year x region) from the later years' current values, clamping at 2050. In the restart the expectations agree with the final current-year values to 0.5% for 2025 to 2049 and exactly for 2050: they were made from the prior cycle's values, so they carry that cycle's drift.

`source_hashes.json` freezes the SHA-256 of the 36 coal input files, `coal.ams`, the case-data files, `dict.txt`, the STEO files and `util_tools.f90`; a test fails if the upstream checkout changes.

Not done in step 1: the Fortran oracle for COAL_EXPECT (needs the WSL oracle rebuild; the Python version is checked against the restart instead) and the AIMMS checkpoint export (needs an AIMMS licence).
