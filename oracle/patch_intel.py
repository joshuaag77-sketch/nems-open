"""Rewrite Intel Fortran extensions in an EIA source file so gfortran accepts it.

Usage: python patch_intel.py <in.f> <out.f90>

Only syntax changes. Numerics must stay identical, so every rule here is a
spelling change gfortran needs, nothing more.
"""

import re
import sys

ITEM = re.compile(r"\s*[\w+\-*/() ]+?\s*(:\s*[\w+\-*/() ]+?\s*)?$")


def range_list(m):
    """[4:8,13:maxldv] -> [(II_RNG,II_RNG=4,8),(II_RNG,II_RNG=13,maxldv)].

    Intel accepts a:b inside an array constructor as the list of integers a..b;
    gfortran wants an implied DO. II_RNG is declared in MODULE T_ and F_ (rule below).
    Anything that is not a plain list of expressions and ranges is left alone."""
    items = m.group(1).split(",")
    if not all(ITEM.match(i) for i in items):
        return m.group(0)
    out = []
    for i in items:
        if ":" in i:
            a, b = i.split(":")
            out.append(f"(II_RNG,II_RNG={a.strip()},{b.strip()})")
        else:
            out.append(i.strip())
    return "[" + ",".join(out) + "]"


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
    # ININT is Intel's round-to-INTEGER*2. NINT rounds the same way and the
    # assignment narrows to INTEGER*2.
    (re.compile(r"\binint\s*\(", re.I), "nint("),
    # Range lists inside array constructors (tran.f): see range_list.
    (re.compile(r"\[([^\[\]'\"!]*:[^\[\]'\"!]*)\]"), range_list),
    # The implied-DO variable those rewrites need, visible to every routine that USEs T_ or F_.
    (re.compile(r"^(module (?:T_|F_))[ \t]*$", re.I | re.M),
     lambda m: m.group(1) + "\nINTEGER II_RNG   ! oracle: implied-DO index for patched range lists"),
    # Hex literals in integer comparisons and arithmetic (tran.f UPPERCASE): same value in decimal.
    (re.compile(r"(?<![\w'])[Zz]'([0-9A-Fa-f]+)'(?!')"), lambda m: str(int(m.group(1), 16))),
    # Logical compared with .EQ. (tran.f, tranfrt.f): Intel allows it, gfortran wants .EQV.
    # .EQ. binds tighter than .AND. but .EQV. binds looser, so the comparison is
    # parenthesised: "a.and.X.eq..FALSE." must stay "a.and.(X.eqv..FALSE.)".
    (re.compile(r"([A-Za-z_]\w*\s*(?:\((?:[^()]|\((?:[^()]|\([^()]*\))*\))*\))?)\s*\.eq\.\s*(\.(?:true|false)\.)", re.I),
     r"(\1 .eqv. \2)"),
    # NOT() on a LOGICAL (tran.f FLTHAV): Intel's bitwise NOT of .TRUE./.FALSE. is .NOT.
    (re.compile(r"\bif \(not\(bTaxiUtilErr\(", re.I), "if (.not.(bTaxiUtilErr("),
    # INTEGER initialised with .FALSE. (tran.f TRAIL, tranfrt.f TRANFRT): Intel stores 0.
    (re.compile(r"(INTEGER\b[^\n!]*?\bonce\s*)/\.false\./", re.I), r"\1/0/"),
    # MODULE F_ has implicit typing, so CAFE4 is a REAL constant used as a dimension.
    # Intel converts it; gfortran needs it INTEGER. Same value.
    (re.compile(r"^(PARAMETER\(CAFE4 = 4\))", re.M), r"INTEGER CAFE4\n\1"),
    # INTEGER NAME*2 -> INTEGER*2 NAME (tranfrt.f TOONYEAR)
    (re.compile(r"^(\s*)INTEGER\s+(\w+)\s*\*\s*(\d)\s*$", re.I | re.M), r"\1INTEGER*\3 \2"),
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
