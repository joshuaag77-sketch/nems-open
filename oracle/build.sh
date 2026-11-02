#!/usr/bin/env bash
# Build an oracle. Run gen_oracle.py for the same module first (it fills build*/inc with
# the includes, so the compile works wherever the upstream checkout lives: spaces in its
# path break -I).
# Usage: bash build.sh [comm|resd|tran]   (from the oracle folder; default comm)
# NEMS_UPSTREAM points at EIA's checkout; default ../nems-upstream.
set -e
MOD="${1:-comm}"
U="$(cd "${NEMS_UPSTREAM:-../nems-upstream}" && pwd)"
FLAGS="-O0 -g -fbacktrace -ffree-line-length-none -fno-automatic -finit-local-zero -fdec -fallow-argument-mismatch -w -Iinc"

wk1() {
  python -I ../wk1_subset.py "$U/source/nemswk1.f" wk1_raw.f
  python -I ../patch_intel.py wk1_raw.f wk1_subset.f90
}

if [ "$MOD" = tran ]; then
  cd build_tran
  for f in tran tranfrt tranair; do python -I ../patch_intel.py "$U/source/$f.f" $f.f90; done
  python -I ../hooks_tran.py "$U" .
  wk1
  # Module order matters: tranfrt.f and tranair.f use MEAN_FUNCS from tran.f.
  gfortran $FLAGS -c wk1_subset.f90 ../readrng_stub.f90 ../stubs.f90 load_restart.f90 tran.f90 tranfrt.f90 tranair.f90 oracle_state_tran.f90 ../driver_tran.f90
  gfortran -o ../run_tran/oracle.exe wk1_subset.o readrng_stub.o stubs.o load_restart.o tran.o tranfrt.o tranair.o oracle_state_tran.o driver_tran.o
  echo built run_tran/oracle.exe
  exit 0
fi

if [ "$MOD" = comm ]; then
  B=build; R=run; SRC=comm; DRIVER=driver
else
  B=build_$MOD; R=run_$MOD; SRC=$MOD; DRIVER=driver_$MOD
fi
cd $B
python -I ../patch_intel.py "$U/source/$SRC.f" $SRC.f90
python -I ../hooks.py "$U" $SRC.f90 $MOD
wk1
gfortran $FLAGS -c $SRC.f90 wk1_subset.f90 ../readrng_stub.f90 ../stubs.f90 load_restart.f90 oracle_state.f90 ../$DRIVER.f90
gfortran -o ../$R/oracle.exe $SRC.o wk1_subset.o readrng_stub.o stubs.o load_restart.o oracle_state.o $DRIVER.o
echo built $R/oracle.exe
