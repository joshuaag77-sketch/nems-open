#!/usr/bin/env bash
# Called by EIA's AIMMS interface in the AIMMS-coupled EMM oracle (oracle/aimms_fortran.py), from the run folder,
# each time NEMS would start ECP or EFD in AIMMS. NEMS has just written its request to "main\endpoint_p2_caller.txt"
# (aimms_fortran.py turns its backslash into a slash) and the module's composite input file. This runs Windows aimms.exe on
# the wrapper project (oracle/aimms_patch.py) and waits for <module>/done.txt.
#
# The AIMMS folders (ecp, efd, main, ...) are links into AIMMS_RUN_WIN on the Windows disk, where aimms.exe can
# read and write them; set by oracle/build.sh.
set -u
REQ='main/endpoint_p2_caller.txt'
[ -f "$REQ" ] || { echo "run_aimms.sh: no $REQ" >&2; exit 1; }
field() { grep -i "^$1" "$REQ" | head -1 | sed 's/.*: *//' | tr -d '\r '; }
MOD=$(field my_module); YEAR=$(field year); ITR=$(field iter)
case "$MOD" in ecp|efd) ;; *) echo "run_aimms.sh: module '$MOD' not wired" >&2; exit 1 ;; esac
AIMMS="${AIMMS_EXE:-/mnt/c/Users/joshu/AppData/Local/AIMMS/IFA/Aimms/25.5.7.1-x64-VS2022/Bin/aimms.exe}"
WRAPPER_WIN="$(wslpath -w "$(readlink -f main)/wrapper/wrapper.aimms")"
printf 'req_year := %s ;\nreq_itr := %s ;\n' "$YEAR" "$ITR" > "$MOD/request.txt"
rm -f "$MOD/done.txt" "$MOD/showreel_stats.txt"
echo "run_aimms.sh: $MOD $YEAR iteration $ITR"
t0=$(date +%s)
"$AIMMS" "-Rrun_$MOD" "$WRAPPER_WIN" --hidden
t1=$(date +%s)
# Showreel (oracle/aimms_showreel.py): one JSON line per solve plus logs; read-only, never fails the run.
SHOWREEL_PY="${SHOWREEL_PY:-/mnt/c/Users/joshu/dev/nems-open-elec/oracle/aimms_showreel.py}"
RESULT=failed; [ -f "$MOD/done.txt" ] && RESULT=ok
python3 "$SHOWREEL_PY" "$MOD" "$YEAR" "$ITR" "$((t1 - t0))" "$RESULT" || echo "run_aimms.sh: showreel record skipped" >&2
if [ -f "$MOD/done.txt" ]; then
  echo "run_aimms.sh: $MOD $YEAR done in $((t1 - t0)) s"
  [ -s "$MOD/log/aimmsRunOnly.err" ] && { echo "run_aimms.sh: AIMMS reported errors:"; head -5 "$MOD/log/aimmsRunOnly.err"; }
  exit 0
fi
echo "run_aimms.sh: $MOD $YEAR FAILED after $((t1 - t0)) s (no done.txt)" >&2
tail -5 main/wrapper/log/aimms.err 2>/dev/null >&2
exit 1
