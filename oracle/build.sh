#!/usr/bin/env bash
# Build an oracle. Run gen_oracle.py for the same module first.
# Usage: bash build.sh [comm|resd|ind]   (from the oracle folder; default comm)
# NEMS_UPSTREAM points at the EIA checkout; default is ../nems-upstream.
set -e
MOD="${1:-comm}"
U="${NEMS_UPSTREAM:-$(cd ../nems-upstream && pwd)}"
U="$(cd "$U" && pwd)"
# gfortran's -I breaks on spaces, so reach the checkout through a space-free junction.
case "$U" in
  *" "*)
    [ -e upstream_link ] || cmd //c mklink //J upstream_link "$(cygpath -w "$U")" > /dev/null
    INC=../upstream_link/includes ;;
  *) INC="$U/includes" ;;
esac
FLAGS="-O0 -g -fbacktrace -ffree-line-length-none -fno-automatic -finit-local-zero -fdec -fallow-argument-mismatch -w -I$INC"
FLAGS="$FLAGS $ORACLE_EXTRA_FLAGS"   # e.g. -ffpe-trap=invalid to stop at the first NaN
case "$MOD" in
  comm) B=build; R=run; SRC=comm; DRIVER=driver ;;
  # ind.f passes short arrays to longer dummy arguments (shares_calc), which gfortran
  # only allows under -std=legacy.
  ind) B=build_ind; R=run_ind; SRC=ind; DRIVER=driver_ind; FLAGS="$FLAGS -std=legacy" ;;
  *) B=build_$MOD; R=run_$MOD; SRC=resd; DRIVER=driver_$MOD ;;
esac
cd $B
python -I ../patch_intel.py "$U/source/$SRC.f" $SRC.f90
python -I ../hooks.py "$U" $SRC.f90 $MOD
python -I ../wk1_subset.py "$U/source/nemswk1.f" wk1_raw.f
python -I ../patch_intel.py wk1_raw.f wk1_subset.f90
gfortran $FLAGS -c $SRC.f90 wk1_subset.f90 ../readrng_stub.f90 ../stubs.f90 load_restart.f90 oracle_state.f90 ../$DRIVER.f90
gfortran -o ../$R/oracle.exe $SRC.o wk1_subset.o readrng_stub.o stubs.o load_restart.o oracle_state.o $DRIVER.o
echo built $R/oracle.exe
