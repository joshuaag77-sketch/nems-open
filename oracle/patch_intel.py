"""Rewrite Intel Fortran extensions in an EIA source file so gfortran accepts it.

Usage: python patch_intel.py <in.f> <out.f90>

Only syntax changes. Numerics must stay identical, so every rule here is a
spelling change gfortran needs, nothing more.
"""

import re
import sys

RULES = [
    # COMReport's ksdout format has items after the year group, so the repeat count
    # must be exact: LASTYR-(CMFirstYr-1) = 61-29 = 32 for every AEO2026 run
    # (projection years 2019-2050). Change this if the year range changes.
    (re.compile(r"<LASTYR-\(CMFirstYR-1\)>", re.I), "32"),
    # Other variable format expressions, '(<CMLastYr>F10.3)', end the format, so any
    # repeat count big enough to cover the list writes the same thing.
    (re.compile(r"<[A-Za-z_][\w+\-*/ ()]*>"), "999"),
    # REAL FUNCTION NAME*4 (args) -> REAL*4 FUNCTION NAME (args)
    (re.compile(r"^(\s*)(REAL|INTEGER)\s+FUNCTION\s+(\w+)\s*\*\s*(\d)\s*\(", re.I | re.M),
     r"\1\2*\4 FUNCTION \3("),
    # READ ... (X (I)) with no implied DO: drop the redundant parentheses.
    (re.compile(r"(IOSTAT=\w+\)\s*)\((\s*\w+\s*\(\s*\w+\s*\)\s*)\)"), r"\1\2"),
    # Same for a scalar: READ ... (ResDiscountRate) in resd.f.
    (re.compile(r"(IOSTAT=\w+\)\s*)\((\s*\w+\s*)\)[ \t]*$", re.M), r"\1\2"),
    # A statement label run into its keyword, "91FORMAT(...)" in resd.f.
    (re.compile(r"^(\s*\d+)(FORMAT\s*\()", re.I | re.M), r"\1 \2"),
    # Intel writes an INTEGER zero under an F edit descriptor; gfortran stops. Only in
    # RESDBOUT's lighting report (format 990), so write the zeros as reals.
    (re.compile(r"(LTInvest\(app,Y,E,B,D,2\)),0,0,(LTsubsidy\(app,Y,E,B,D,1\),LTsubsidy\(app,Y,E,B,D,2\)),0,0,0"),
     r"\1,0.,0.,\2,0.,0.,0."),
    # ININT is Intel's round-to-INTEGER*2. NINT rounds the same way and the
    # assignment narrows to INTEGER*2.
    (re.compile(r"\binint\s*\(", re.I), "nint("),
    # Intel's portability module. Its one routine we need, CALLSYS, is in stubs.f90.
    (re.compile(r"^\s*use\s+dfport\s*$", re.I | re.M), ""),
    # Intel's list-directed READ accepts "1.000" for an INTEGER; gfortran stops.
    # kgentk.txt stores census division and niche counts that way.
    (re.compile(r"READ\s*\(INFILE,\s*\*\)\s*iDiv,\s*iNiche", re.I),
     "CALL READ_INTS_LENIENT(INFILE, iDiv, iNiche)"),
]


def patch(text: str) -> str:
    for pattern, repl in RULES:
        text = pattern.sub(repl, text)
    return text


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, encoding="latin-1") as f:
        out = patch(f.read())
    with open(dst, "w", encoding="latin-1") as f:
        f.write(out)
