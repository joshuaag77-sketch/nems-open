# AEO2025 versus AEO2026 diff: what exists

Checked 2026-11-03 against github.com/EIAgov/NEMS (tags `AEO2025-Public-Release`, `AEO2026-Public-Release`; main has 13 commits, nothing in between).

## Available
- **AEO2025 code and inputs: yes, complete.** The 2025 tag holds the full tree (2,818 files, 250 MB): `input/`, `models/`, `source/`, `includes/`, `scedes/` (ref2025, highprice, lowprice, hm2025, lm2025, highogs, lowogs, highztc, lowztc, nocaa111, alttrnp). Compared with 2026: nearly every Fortran source and every `includes/` block changed, most module input folders changed (`input/rdm` 16 of 19 files, `input/cdm` 12 of 28, `input/emm` 39 of 55, `input/idm` 17 of 22, `input/tdm` 8 added and 4 changed, `input/steovars.csv`, `input/macro`, `input/dict.txt`). `input/coal` and `input/hsm` are unchanged; `models/coal` changed 68 files of 924.
- **AEO2025 restart (reference results): probably, not yet fetched.** `output/aeo2025/ref2025.zip` is a Git LFS pointer to a 26.4 MB object (sha256 798d3133...), downloadable from media.githubusercontent.com (HTTP 200 checked, nothing downloaded). Its contents are not known until opened: the 2026 equivalent is `restart.rlx` (17.8 MB), so it is likely the reference restart plus reports. The only bare AEO2025 restart is `output/aeo2025/alttrnp/031825a/restart.rlx` (172 MB LFS, a side case, not the reference).
- The other 2025 case zips (highprice, lowprice, hm2025, lm2025, highogs, lowogs, highztc, lowztc, nocaa111) are 133-byte LFS pointers.

## Not available
- No AEO2025 restart in `.npz` form; it would have to be converted with the same reader used for cb2026.
- No oracle build of the 2025 Fortran yet. Splitting a headline change into input effect and code effect needs a second oracle (2025 source) built under WSL, or the 2025 restart as the only truth for the 2025 code.

## Which modules can be compared
Green (ported and checked against EIA's Fortran oracle, `web/data/fidelity.json`): residential, commercial, transportation, electricity load (LDSM), electricity finance and pricing (EFP). Everything else is a stand-in or our own model and is refused.

The split for a green module takes three numbers per headline:
1. total change = 2026 restart minus 2025 restart (both EIA's own);
2. input effect = our code run on 2025 inputs minus our code run on 2026 inputs, with upstream drivers (macro, prices) frozen from each year's own restart;
3. code effect = total minus input effect, valid only while our run on 2026 inputs reproduces the 2026 restart for that headline (the module's match grade) and the 2025 run on 2025 inputs is checked the same way against the 2025 restart. Where an upstream driver is a stand-in, the headline is not attributed.

## Needs approval before it can start
Download of `ref2025.zip` (26.4 MB, from media.githubusercontent.com/media/EIAgov/NEMS/AEO2025-Public-Release/output/aeo2025/ref2025.zip) and a checkout of the 2025 tag inputs (about 250 MB). Nothing has been downloaded.
