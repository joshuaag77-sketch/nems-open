#!/usr/bin/env bash
# Build the commercial oracle. Run gen_oracle.py first.
# Usage: bash build.sh   (from the oracle folder)
set -e
U="$(cd ../nems-upstream && pwd)"
# Relative include path: the project folder has spaces, which break -I.
FLAGS="-O0 -g -fbacktrace -ffree-line-length-none -fno-automatic -finit-local-zero -fdec -fallow-argument-mismatch -w -I../../nems-upstream/includes"
cd build
python -I ../patch_intel.py "$U/source/comm.f" comm.f90
python -I ../hooks.py "$U" comm.f90
python -I ../wk1_subset.py "$U/source/nemswk1.f" wk1_raw.f
python -I ../patch_intel.py wk1_raw.f wk1_subset.f90
gfortran $FLAGS -c comm.f90 wk1_subset.f90 ../readrng_stub.f90 ../stubs.f90 load_restart.f90 oracle_state.f90 ../driver.f90
gfortran -o ../run/oracle.exe comm.o wk1_subset.o readrng_stub.o stubs.o load_restart.o oracle_state.o driver.o
echo built run/oracle.exe
