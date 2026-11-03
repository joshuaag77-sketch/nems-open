#!/usr/bin/env bash
# Generate, build and run an oracle inside WSL (Ubuntu), for any module: comm, resd, tran, ind, emm.
#
#   wsl bash oracle/build_wsl.sh <module> [gen] [build] [run] [--local-out]
#
# With no step named it does all three. Windows sessions call it through scripts/oracle.ps1.
#
# Why: Windows Smart App Control can block a freshly built oracle.exe; an ELF program under WSL is
# not blocked. The one-time set-up inside Ubuntu:
#     sudo apt update && sudo apt install -y gfortran gcc python3 python3-numpy python3-openpyxl libsqlite3-dev
#
# What it does differently from build.sh on Windows:
#   * sources and inputs are read from the repo and EIA's checkout through /mnt/c; the build objects,
#     run folders and a normalized view of the upstream tree (oracle/wsl_prepare.py: case-insensitive
#     include names, LF endings, a path with no spaces) live in $NEMS_ORACLE_WORK (default ~/nems-oracle)
#   * dumps go to the shared oracle cache (NEMS_ORACLE_DIR, default the Windows ~/dev/oracle-cache)
#     through a symlink run*/out -> cache. --local-out dumps to the Linux disk and copies at the end,
#     which is much faster than writing thousands of files through /mnt/c.
#   * the program is run*/oracle (no .exe), so Windows and Linux builds never overwrite each other
set -euo pipefail

MOD="${1:?usage: build_wsl.sh <comm|resd|tran|ind|emm> [gen] [build] [run] [--local-out]}"
shift
STEPS=()
LOCAL_OUT=0
for a in "$@"; do
  case "$a" in
    --local-out) LOCAL_OUT=1 ;;
    gen|build|run) STEPS+=("$a") ;;
    *) echo "unknown argument: $a" >&2; exit 2 ;;
  esac
done
[ ${#STEPS[@]} -eq 0 ] && STEPS=(gen build run)
has() { local s; for s in "${STEPS[@]}"; do [ "$s" = "$1" ] && return 0; done; return 1; }

ORACLE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(dirname "$ORACLE")"

# C:\Users\me\x or C:/Users/me/x -> /mnt/c/Users/me/x
unix_path() {
  case "$1" in
    [A-Za-z]:[\/]*) wslpath -u "$1" ;;
    *) printf '%s' "$1" ;;
  esac
}

for tool in gfortran gcc python3; do
  command -v "$tool" >/dev/null || { echo "missing $tool: sudo apt install -y gfortran gcc python3 python3-numpy python3-openpyxl libsqlite3-dev" >&2; exit 1; }
done
python3 -c "import numpy" 2>/dev/null || { echo "missing python3-numpy: sudo apt install -y python3-numpy python3-openpyxl" >&2; exit 1; }
if [ "$MOD" = emm ]; then
  echo '#include <sqlite3.h>' | gcc -E - >/dev/null 2>&1 || { echo "emm needs libsqlite3-dev: sudo apt install -y libsqlite3-dev" >&2; exit 1; }
fi

UPSTREAM_REAL="$(unix_path "${NEMS_UPSTREAM:-$REPO/nems-upstream}")"
[ -d "$UPSTREAM_REAL/source" ] || { echo "no EIA checkout at $UPSTREAM_REAL (a Windows junction may not show up in WSL: pass NEMS_UPSTREAM=<real folder>)" >&2; exit 1; }

export NEMS_ORACLE_WORK="${NEMS_ORACLE_WORK:-$HOME/nems-oracle}"
mkdir -p "$NEMS_ORACLE_WORK"
if [ -z "${NEMS_ORACLE_DIR:-}" ]; then
  WINHOME="$(cmd.exe /c "echo %USERPROFILE%" 2>/dev/null | tr -d '\r' || true)"
  if [ -n "$WINHOME" ]; then NEMS_ORACLE_DIR="$(wslpath -u "$WINHOME")/dev/oracle-cache"; else NEMS_ORACLE_DIR="$HOME/dev/oracle-cache"; fi
fi
export NEMS_ORACLE_DIR="$(unix_path "$NEMS_ORACLE_DIR")"
export PYTHON=python3
export ORACLE_EXE=""
[ $LOCAL_OUT = 1 ] && export NEMS_ORACLE_NO_LINK=1

VIEW="$NEMS_ORACLE_WORK/upstream"
python3 "$ORACLE/wsl_prepare.py" "$UPSTREAM_REAL" "$VIEW"
export NEMS_UPSTREAM="$VIEW"

if [ "$MOD" = comm ]; then RUN_DIR=run; else RUN_DIR="run_$MOD"; fi
SCENARIO="${SCENARIO:-cb2026}"

if has gen; then
  echo "== gen_oracle $MOD ($SCENARIO)"
  python3 -I "$ORACLE/gen_oracle.py" "$VIEW" "$SCENARIO" "$MOD"
fi
if has build; then
  echo "== build $MOD"
  bash "$ORACLE/build.sh" "$MOD"
fi
if has run; then
  echo "== run $MOD  (dumps -> $NEMS_ORACLE_DIR/$MOD/out)"
  cd "$NEMS_ORACLE_WORK/$RUN_DIR"
  time ./oracle > oracle.log 2>&1 || { tail -20 oracle.log; exit 1; }
  tail -3 oracle.log
  if [ $LOCAL_OUT = 1 ]; then
    echo "== copying out/ to the cache"
    mkdir -p "$NEMS_ORACLE_DIR/$MOD/out"
    cp -a out/. "$NEMS_ORACLE_DIR/$MOD/out/"
  fi
fi
