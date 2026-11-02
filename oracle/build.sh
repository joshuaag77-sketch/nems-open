#!/usr/bin/env bash
# Build an oracle. Run gen_oracle.py first (it fills build*/inc with the includes).
# Usage: bash build.sh [comm|tran]   (from the oracle folder; default comm)
# NEMS_UPSTREAM points at EIA's checkout; default ../nems-upstream.
set -e
MOD="${1:-comm}"
U="$(cd "${NEMS_UPSTREAM:-../nems-upstream}" && pwd)"
FLAGS="-O0 -g -fbacktrace -ffree-line-length-none -fno-automatic -finit-local-zero -fdec -fallow-argument-mismatch -w -Iinc"

wk1() {
  python -I ../wk1_subset.py "$U/source/nemswk1.f" wk1_raw.f
  python -I ../patch_intel.py wk1_raw.f wk1_subset.f90
}

if [ "$MOD" = comm ]; then
  cd build
  python -I ../patch_intel.py "$U/source/comm.f" comm.f90
  python -I ../hooks.py "$U" comm.f90
  wk1
  gfortran $FLAGS -c comm.f90 wk1_subset.f90 ../readrng_stub.f90 ../stubs.f90 load_restart.f90 oracle_state.f90 ../driver.f90
  gfortran -o ../run/oracle.exe comm.o wk1_subset.o readrng_stub.o stubs.o load_restart.o oracle_state.o driver.o
  echo built run/oracle.exe
elif [ "$MOD" = tran ]; then
  cd build_tran
  for f in tran tranfrt tranair; do python -I ../patch_intel.py "$U/source/$f.f" $f.f90; done
  python -I ../hooks_tran.py "$U" .
  wk1
  # Module order matters: tranfrt.f and tranair.f use MEAN_FUNCS from tran.f.
  gfortran $FLAGS -c wk1_subset.f90 ../readrng_stub.f90 ../stubs.f90 load_restart.f90 tran.f90 tranfrt.f90 tranair.f90 oracle_state_tran.f90 ../driver_tran.f90
  gfortran -o ../run_tran/oracle.exe wk1_subset.o readrng_stub.o stubs.o load_restart.o tran.o tranfrt.o tranair.o oracle_state_tran.o driver_tran.o
  echo built run_tran/oracle.exe
fi
