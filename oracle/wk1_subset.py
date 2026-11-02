"""Cut the range-lookup routines out of EIA's nemswk1.f, unchanged.

Keeps EIA's own GETRNG* copy logic and dimension rules. The XLSX parsing those
routines rely on is replaced by readrng_stub.f90.

Usage: python -I wk1_subset.py <nemswk1.f> <out.f>
"""

import re
import sys

KEEP = {"getrngi", "getrngi4", "getrngr", "getrngc", "low2up", "igetname", "ifindrng", "isetdflg", "fsetxyz"}
START = re.compile(r"^\s*(?:integer(?:\*\d)?\s+)?(?:subroutine|function)\s+(\w+)", re.I)

lines = open(sys.argv[1], encoding="latin-1").read().splitlines()
starts = [(i, START.match(l).group(1).lower()) for i, l in enumerate(lines) if START.match(l)]
out = []
for k, (i, name) in enumerate(starts):
    end = starts[k + 1][0] if k + 1 < len(starts) else len(lines)
    if name in KEEP:
        out.extend(lines[i:end])
open(sys.argv[2], "w", encoding="latin-1").write("\n".join(out) + "\n")
