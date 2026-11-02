#!/usr/bin/env bash
# Build an oracle. Run gen_oracle.py for the same module first.
# Usage: bash build.sh [comm|resd]   (from the oracle folder; default comm)
set -e
MOD="${1:-comm}"
# NEMS_UPSTREAM overrides the checkout; default is ../nems-upstream. Keep the path free of spaces (-I breaks on them).
U="$(cd "${NEMS_UPSTREAM:-../nems-upstream}" && pwd)"
FLAGS="-O0 -g -fbacktrace -ffree-line-length-none -fno-automatic -finit-local-zero -fdec -fallow-argument-mismatch -w -I$U/includes"
if [ "$MOD" = comm ]; then
  B=build; R=run; SRC=comm; DRIVER=driver
else
  B=build_$MOD; R=run_$MOD; SRC=resd; DRIVER=driver_$MOD
fi
cd $B
python -I ../patch_intel.py "$U/source/$SRC.f" $SRC.f90
python -I ../hooks.py "$U" $SRC.f90 $MOD
python -I ../wk1_subset.py "$U/source/nemswk1.f" wk1_raw.f
python -I ../patch_intel.py wk1_raw.f wk1_subset.f90
gfortran $FLAGS -c $SRC.f90 wk1_subset.f90 ../readrng_stub.f90 ../stubs.f90 load_restart.f90 oracle_state.f90 ../$DRIVER.f90
gfortran -o ../$R/oracle.exe $SRC.o wk1_subset.o readrng_stub.o stubs.o load_restart.o oracle_state.o $DRIVER.o
echo built $R/oracle.exe
