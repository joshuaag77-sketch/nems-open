# Building the oracles in WSL

Windows Smart App Control can refuse to run a program gfortran has just built (`oracle.exe`).
A Linux program under WSL is not blocked, so the same Fortran builds and runs there, for every
module: `comm`, `resd`, `tran`, `ind`, `emm`.

## One-time set-up

1. `wsl --install -d Ubuntu`, restart, and create the Linux user when Ubuntu first opens.
2. In Ubuntu:
   ```bash
   sudo apt update && sudo apt install -y gfortran gcc python3 python3-numpy python3-openpyxl libsqlite3-dev
   ```
   (`libsqlite3-dev` is only for `emm`.)

## Use

From a Windows terminal in the repo:

```powershell
scripts\oracle.ps1 comm                      # gen_oracle, build, run
scripts\oracle.ps1 resd build run            # skip the restart dump
scripts\oracle.ps1 comm -LocalOut            # dump on the Linux disk, copy to the cache at the end (faster)
```

or inside Ubuntu: `bash oracle/build_wsl.sh comm [gen] [build] [run] [--local-out]`.

Long runs belong in the background. Set `NEMS_ORACLE_YEARS=30` for a small run with one year of dumps.

## Where things live

| What | Where |
|---|---|
| Sources, scripts, EIA's checkout | read from the repo and `nems-upstream` through `/mnt/c` |
| Objects, run folders, the normalized upstream view | `$NEMS_ORACLE_WORK`, default `~/nems-oracle` (Linux disk) |
| Dumps | the shared cache, `NEMS_ORACLE_DIR` (default `C:\Users\<you>\dev\oracle-cache`), `<module>/out/state/...` |
| The program | `~/nems-oracle/run/oracle` (`run_<module>/oracle`), no `.exe`, so it never overwrites the Windows build |

The Windows and Linux builds do not share objects or run folders; only the dumps meet in the cache. They are
identical text and binary files, so `oracle_state.py` reads either.

## What differs on Linux, and how it is handled

- **Include file names.** EIA's sources write `INCLUDE 'PARAMETR'` for a file named `parametr`; Windows does not
  care, Linux does. `oracle/wsl_prepare.py` builds an `includes` folder holding every file under its own name
  and under every spelling a source uses (41 differ), with LF endings.
- **CRLF.** EIA's `.f` files and inputs have CRLF endings. `patch_intel.py` writes LF for the sources;
  gfortran also reads CRLF text. Repo shell scripts are forced to LF (`.gitattributes`).
- **Spaces in paths.** The checkout can sit under `3. AI Projects`. The compiler and the run folder's file list
  only ever see the view's space-free path (symlinks into the checkout).
- **Junctions.** `nems-upstream` is a Windows junction; `oracle.ps1` hands WSL the real folder.
- **SQLite for `emm`.** NEMS ships `libfsqlite.a` as Windows objects. On Linux `oracle/csqlite.c` re-implements
  its 19 C entry points on top of the system SQLite.
- **Executable name and `python`.** `build.sh` reads `PYTHON`, `ORACLE_EXE` and `NEMS_ORACLE_WORK`; its Windows
  defaults are unchanged.

## Checked: Linux dumps against the Windows-built ones

Measured 2026-11-03 with Ubuntu's gfortran 15.2 (the Windows build used WinLibs GCC 16.2) on the AEO2026
reference run, `oracle/compare_dumps.py` array by array.

| Module | Year | Result |
|---|---|---|
| comm | 2019 (every dump: `fsd_in` to `rp_out`, 20 tags) | 2 or 3 arrays of about 180 to 250 differ in each dump; the rest are byte for byte equal. Worst difference 5.9e-7 relative (9 units in the last place) |
| resd | 2021 (every dump) | most dumps byte for byte equal; the rest differ by at most 1.4e-7 (2 units in the last place) |

The arrays that differ are the ones computed with `**` (real powers), where MinGW's and glibc's `pow` round
differently: `ShellCoolFactor` (9 cells, geometric interpolation between years), `xpen` (79 of 13.6 million cells),
one cell of `CMNewFloorspace`, and a handful of residential arrays. Everything else, including every array read
from a file or the restart file, is identical. The ports are tested to 1e-6, so these differences are inside the tolerance.

The commercial tests (1,120, including `test_oracle.py`) run against a full nine-year set of Linux dumps: 1,119 pass.
The one that does not, `test_distgen_year[INVEST-2040]`, misses its 1e-4 tolerance by a hair (1.44e-4). CDistGen
accumulates investments year over year from `xpen`, one of the arrays whose `pow` rounding differs, so a last-bit
difference grows over 21 years. It passes on the Windows-built dumps. If you need that test green on Linux, build
the oracle on Windows or loosen the one tolerance; the port itself is not at fault.

Run the comparison yourself:

```bash
python3 oracle/compare_dumps.py <windows cache>/comm/out/state <linux cache>/comm/out/state [tag ...]
```

`--bits N` sets how many units in the last place count as a failure (default 1; use 9 for the pow differences above).
