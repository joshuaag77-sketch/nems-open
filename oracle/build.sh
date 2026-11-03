#!/usr/bin/env bash
# Build an oracle. Run gen_oracle.py for the same module first.
# Usage: bash build.sh [comm|resd|emm]   (from the oracle folder; default comm)
set -e
MOD="${1:-comm}"
# NEMS_UPSTREAM overrides the checkout; default is ../nems-upstream. For comm and resd
# keep the path free of spaces (-I breaks on them); emm copies the includes instead.
U="$(cd "${NEMS_UPSTREAM:-../nems-upstream}" && pwd)"
if [ "$MOD" = emm ]; then
  # EMM: several files, copied includes (the upstream path may have spaces), and
  # SQLite from the objects NEMS ships in libfsqlite.a.
  FLAGS="-O0 -g -fbacktrace -ffree-line-length-none -fno-automatic -finit-local-zero -fdec -fallow-argument-mismatch -w -Iinc -Isqlite"
  cd build_emm
  rm -rf inc && cp -r "$U/includes" inc
  mkdir -p sqlite && (cd sqlite && ar x "$U/source/libfsqlite.a" sqlite3.obj csqlite.obj \
    && cp "$U/source/fsqlite.f90" . && gfortran -c -w -J. fsqlite.f90 \
    && printf '.globl __chkstk\n__chkstk:\n  jmp ___chkstk_ms\n.globl _fltused\n.data\n_fltused: .long 0\n' > chkstk.s \
    && gcc -c chkstk.s)
  SRCS="util udat uldsm uefp uefd uecp unugs udaf ucape uread"
  for s in $SRCS; do python -I ../patch_intel.py "$U/source/$s.f" $s.f90; done
  python -I ../patch_intel.py "$U/source/uesql.f90" uesql.f90
  python -I ../patch_intel.py "$U/source/ephrts.f90" ephrts.f90   # HMM hand-off
  python -I ../patch_intel.py "$U/source/ecp_row_col.f90" ecp_row_col.f90
  python -I ../patch_intel.py "$U/source/efd_row_col.f90" efd_row_col.f90
  python -I ../hooks.py "$U" util.f90 emm
  python -I ../wk1_subset.py "$U/source/nemswk1.f" wk1_raw.f
  python -I ../patch_intel.py wk1_raw.f wk1_subset.f90
  # Modules first: udat.f holds two that uldsm.f and util.f use.
  gfortran $FLAGS -c ../emm_modules.f90 ecp_row_col.f90 efd_row_col.f90 udat.f90 uesql.f90
  # The big files compile in parallel.
  for s in util uldsm uefp uefd uecp unugs udaf ucape uread ephrts; do gfortran $FLAGS -c $s.f90 & done; wait
  gfortran $FLAGS -c wk1_subset.f90 ../readrng_stub.f90 ../stubs.f90 ../emm_stubs.f90 load_restart.f90 \
    oracle_state.f90 ../efd_standin.f90 ../driver_emm.f90
  rm -f ../run_emm/oracle.exe
  gfortran -o ../run_emm/oracle.exe driver_emm.o efd_standin.o oracle_state.o load_restart.o \
    $(for s in $SRCS; do echo $s.o; done) ephrts.o uesql.o emm_modules.o ecp_row_col.o efd_row_col.o \
    wk1_subset.o readrng_stub.o stubs.o emm_stubs.o \
    sqlite/fsqlite.o sqlite/csqlite.obj sqlite/sqlite3.obj sqlite/chkstk.o 2>&1 | grep -v "drectve" || true
  test -f ../run_emm/oracle.exe
  echo built run_emm/oracle.exe
  exit 0
fi
FLAGS="-O0 -g -fbacktrace -ffree-line-length-none -fno-automatic -finit-local-zero -fdec -fallow-argument-mismatch -w -I$U/includes"
if [ "$MOD" = comm ]; then
  B=build; R=run; SRC=comm; DRIVER=driver
else
  B=build_$MOD; R=run_$MOD; SRC=$MOD; DRIVER=driver_$MOD
fi
cd $B
python -I ../patch_intel.py "$U/source/$SRC.f" $SRC.f90
python -I ../hooks.py "$U" $SRC.f90 $MOD
python -I ../wk1_subset.py "$U/source/nemswk1.f" wk1_raw.f
python -I ../patch_intel.py wk1_raw.f wk1_subset.f90
gfortran $FLAGS -c $SRC.f90 wk1_subset.f90 ../readrng_stub.f90 ../stubs.f90 load_restart.f90 oracle_state.f90 ../$DRIVER.f90
gfortran -o ../$R/oracle.exe $SRC.o wk1_subset.o readrng_stub.o stubs.o load_restart.o oracle_state.o $DRIVER.o
echo built $R/oracle.exe
