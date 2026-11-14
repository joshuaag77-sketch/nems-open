"""Windows paths in EMM's Fortran, for the AIMMS-coupled oracle under Linux.

EIA's code names the files it shares with AIMMS with backslashes: '.\\rest\\toAIMMS\\ecpout_', then pieces like
'\\Rep_Generation.csv' joined at run time. On Linux a backslash is part of a file name, so such a file lands in
the run folder instead of the module folder AIMMS reads and writes. This turns every backslash into a slash in
string literals that hold a path (a backslash followed by a letter or dot), leaving format strings, which start
with '(', alone. Comment lines are not touched.

Usage: python aimms_paths.py <file.f90> ...
"""

import re
import sys
from pathlib import Path

LITERAL = re.compile(r"'([^'\n(][^'\n]*?\\[A-Za-z_.][^'\n]*)'|'(\\[A-Za-z_][^'\n]*)'")


def fix(text: str) -> tuple[str, int]:
    out, n = [], 0
    for line in text.split("\n"):
        if line.lstrip().startswith("!"):
            out.append(line)
            continue
        code, bang, comment = line, "", ""
        new = LITERAL.sub(lambda m: m.group(0).replace("\\", "/"), code)
        n += new != code
        out.append(new)
    return "\n".join(out), n


for name in sys.argv[1:]:
    p = Path(name)
    text, n = fix(p.read_text(encoding="latin-1"))
    p.write_text(text, encoding="latin-1")
    print(f"aimms_paths.py: {p.name}: {n} line(s) with Windows paths written with slashes")
