#!/usr/bin/env bash
# Run a command while holding C:\Users\joshu\dev\HEAVY.lock: wait for it to be free, take it under a name, and
# remove it afterwards only if it still carries that name (never someone else's lock).
#   scripts/with_heavy_lock.sh coal-lp python -m ...
LOCK=/c/Users/joshu/dev/HEAVY.lock
NAME=$1; shift
until ( set -o noclobber; echo "$NAME" > "$LOCK" ) 2>/dev/null; do sleep 15; done
"$@"; rc=$?
[ "$(cat "$LOCK" 2>/dev/null)" = "$NAME" ] && rm -f "$LOCK"
exit $rc
