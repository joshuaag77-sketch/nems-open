#!/usr/bin/env bash
# Build an oracle. Run gen_oracle.py for the same module first (it fills build*/inc with
# the includes, so the compile works wherever the upstream checkout lives: spaces in its
# path break -I).
# Usage: bash build.sh [comm|resd|tran|emm]   (default comm; from any folder)
# NEMS_UPSTREAM points at EIA's checkout; default ../nems-upstream.
# Windows (WinLibs gfortran) by default. build_wsl.sh sets the variables below for Linux:
#   NEMS_ORACLE_WORK  where build*/ and run*/ live (default: this folder)
#   PYTHON            python3 on Ubuntu
#   ORACLE_EXE        suffix of the program: .exe on Windows, nothing on Linux
set -e
ORACLE="$(cd "$(dirname "$0")" && pwd)"
WORK="${NEMS_ORACLE_WORK:-$ORACLE}"
PY="${PYTHON:-python}"
EXE="${ORACLE_EXE-.exe}"
LINUX=0; [ "$(uname -s)" = Linux ] && LINUX=1
MOD="${1:-comm}"
U="$(cd "${NEMS_UPSTREAM:-$ORACLE/../nems-upstream}" && pwd)"
FLAGS="-O0 -g -fbacktrace -ffree-line-length-none -fno-automatic -finit-local-zero -fdec -fallow-argument-mismatch -w -Iinc"

wk1() {
  $PY -I "$ORACLE/wk1_subset.py" "$U/source/nemswk1.f" wk1_raw.f
  $PY -I "$ORACLE/patch_intel.py" wk1_raw.f wk1_subset.f90
}

if [ "$MOD" = tran ]; then
  mkdir -p "$WORK/build_tran" "$WORK/run_tran"
  cd "$WORK/build_tran"
  for f in tran tranfrt tranair; do $PY -I "$ORACLE/patch_intel.py" "$U/source/$f.f" $f.f90; done
  $PY -I "$ORACLE/hooks_tran.py" "$U" .
  wk1
  # Module order matters: tranfrt.f and tranair.f use MEAN_FUNCS from tran.f.
  gfortran $FLAGS -c wk1_subset.f90 "$ORACLE/readrng_stub.f90" "$ORACLE/stubs.f90" load_restart.f90 tran.f90 tranfrt.f90 tranair.f90 oracle_state_tran.f90 "$ORACLE/driver_tran.f90"
  gfortran -o "$WORK/run_tran/oracle$EXE" wk1_subset.o readrng_stub.o stubs.o load_restart.o tran.o tranfrt.o tranair.o oracle_state_tran.o driver_tran.o
  echo "built $WORK/run_tran/oracle$EXE"
  exit 0
fi

if [ "$MOD" = emm ]; then
  # EMM: several files, copied includes (the upstream path may have spaces), and
  # SQLite from the objects NEMS ships in libfsqlite.a.
  FLAGS="-O0 -g -fbacktrace -ffree-line-length-none -fno-automatic -finit-local-zero -fdec -fallow-argument-mismatch -w -Iinc -Isqlite"
  mkdir -p "$WORK/build_emm" "$WORK/run_emm"
  cd "$WORK/build_emm"
  rm -rf inc && cp -r "$U/includes" inc
  if [ $LINUX = 1 ]; then
    # NEMS ships SQLite's Fortran layer as Windows objects only: build it from csqlite.c and the system SQLite.
    mkdir -p sqlite && (cd sqlite && cp "$U/source/fsqlite.f90" . && gfortran -c -w -J. fsqlite.f90 \
      && gcc -c -O2 -fPIC "$ORACLE/csqlite.c" -o csqlite.o)
    SQLITE_OBJS="sqlite/fsqlite.o sqlite/csqlite.o"; SQLITE_LIBS="-lsqlite3"
  else
    mkdir -p sqlite && (cd sqlite && ar x "$U/source/libfsqlite.a" sqlite3.obj csqlite.obj \
      && cp "$U/source/fsqlite.f90" . && gfortran -c -w -J. fsqlite.f90 \
      && printf '.globl __chkstk\n__chkstk:\n  jmp ___chkstk_ms\n.globl _fltused\n.data\n_fltused: .long 0\n' > chkstk.s \
      && gcc -c chkstk.s)
    SQLITE_OBJS="sqlite/fsqlite.o sqlite/csqlite.obj sqlite/sqlite3.obj sqlite/chkstk.o"; SQLITE_LIBS=""
  fi
  SRCS="util udat uldsm uefp uefd uecp unugs udaf ucape uread"
  for s in $SRCS; do $PY -I "$ORACLE/patch_intel.py" "$U/source/$s.f" $s.f90; done
  $PY -I "$ORACLE/patch_intel.py" "$U/source/uesql.f90" uesql.f90
  $PY -I "$ORACLE/patch_intel.py" "$U/source/ephrts.f90" ephrts.f90   # HMM hand-off
  $PY -I "$ORACLE/patch_intel.py" "$U/source/ecp_row_col.f90" ecp_row_col.f90
  $PY -I "$ORACLE/patch_intel.py" "$U/source/efd_row_col.f90" efd_row_col.f90
  $PY -I "$ORACLE/hooks.py" "$U" util.f90 emm
  $PY -I "$ORACLE/wk1_subset.py" "$U/source/nemswk1.f" wk1_raw.f
  $PY -I "$ORACLE/patch_intel.py" wk1_raw.f wk1_subset.f90
  # Modules first: udat.f holds two that uldsm.f and util.f use.
  gfortran $FLAGS -c "$ORACLE/emm_modules.f90" ecp_row_col.f90 efd_row_col.f90 udat.f90 uesql.f90
  # The big files compile in parallel.
  for s in util uldsm uefp uefd uecp unugs udaf ucape uread ephrts; do gfortran $FLAGS -c $s.f90 & done; wait
  gfortran $FLAGS -c wk1_subset.f90 "$ORACLE/readrng_stub.f90" "$ORACLE/stubs.f90" "$ORACLE/emm_stubs.f90" load_restart.f90 \
    oracle_state.f90 "$ORACLE/efd_standin.f90" "$ORACLE/driver_emm.f90"
  rm -f "$WORK/run_emm/oracle$EXE"
  gfortran -o "$WORK/run_emm/oracle$EXE" driver_emm.o efd_standin.o oracle_state.o load_restart.o \
    $(for s in $SRCS; do echo $s.o; done) ephrts.o uesql.o emm_modules.o ecp_row_col.o efd_row_col.o \
    wk1_subset.o readrng_stub.o stubs.o emm_stubs.o \
    $SQLITE_OBJS $SQLITE_LIBS 2>&1 | grep -v "drectve" || true
  test -f "$WORK/run_emm/oracle$EXE"
  echo "built $WORK/run_emm/oracle$EXE"
  exit 0
fi
if [ "$MOD" = comm ]; then
  B=build; R=run; SRC=comm; DRIVER=driver
else
  B=build_$MOD; R=run_$MOD; SRC=$MOD; DRIVER=driver_$MOD
fi
mkdir -p "$WORK/$B" "$WORK/$R"
cd "$WORK/$B"
$PY -I "$ORACLE/patch_intel.py" "$U/source/$SRC.f" $SRC.f90
$PY -I "$ORACLE/hooks.py" "$U" $SRC.f90 $MOD
$PY -I "$ORACLE/wk1_subset.py" "$U/source/nemswk1.f" wk1_raw.f
$PY -I "$ORACLE/patch_intel.py" wk1_raw.f wk1_subset.f90
# stubs.f90 is preprocessed: gfortran's newunit numbers are negative, and EIA's ind.f tests
# "unit .le. 0" as "file not opened", so the industrial build asks for positive units.
STUBFLAGS="-cpp"
if [ "$MOD" = ind ]; then
  # ind.f passes short arrays to longer dummy arguments (shares_calc), which gfortran
  # only allows under -std=legacy.
  FLAGS="$FLAGS -std=legacy"; STUBFLAGS="-cpp -DPOSUNIT"
fi
FLAGS="$FLAGS $ORACLE_EXTRA_FLAGS"   # e.g. -ffpe-trap=invalid to stop at the first NaN
gfortran $FLAGS -c $SRC.f90 wk1_subset.f90 "$ORACLE/readrng_stub.f90" load_restart.f90 oracle_state.f90 "$ORACLE/$DRIVER.f90"
gfortran $FLAGS $STUBFLAGS -c "$ORACLE/stubs.f90"
gfortran -o "$WORK/$R/oracle$EXE" $SRC.o wk1_subset.o readrng_stub.o stubs.o load_restart.o oracle_state.o $DRIVER.o
echo "built $WORK/$R/oracle$EXE"
