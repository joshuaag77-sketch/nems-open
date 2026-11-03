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
    # Same for a scalar: READ ... (ResDiscountRate) in resd.f.
    (re.compile(r"(IOSTAT=\w+\)\s*)\((\s*\w+\s*)\)[ \t]*$", re.M), r"\1\2"),
    # A statement label run into its keyword, "91FORMAT(...)" in resd.f.
    (re.compile(r"^(\s*\d+)(FORMAT\s*\()", re.I | re.M), r"\1 \2"),
    # Intel writes an INTEGER zero under an F edit descriptor; gfortran stops. Only in
    # RESDBOUT's lighting report (format 990), so write the zeros as reals.
    (re.compile(r"(LTInvest\(app,Y,E,B,D,2\)),0,0,(LTsubsidy\(app,Y,E,B,D,1\),LTsubsidy\(app,Y,E,B,D,2\)),0,0,0"),
     r"\1,0.,0.,\2,0.,0.,0."),
    # EMM: a variable format count that starts with a number, "<10+EFD_D_FPP-1>I7"
    # in a debug WRITE in udat.f. Same reasoning as above: it ends the format.
    (re.compile(r"<\d+[+\-][A-Za-z_]\w*(?:[+\-]\d+)?>"), "999"),
    # Intel compares LOGICALs with .EQ./.NE.; gfortran wants .EQV./.NEQV. Same result.
    (re.compile(r"\.EQ\.(\s*\.(?:TRUE|FALSE)\.)", re.I), r".EQV.\1"),
    (re.compile(r"\.NE\.(\s*\.(?:TRUE|FALSE)\.)", re.I), r".NEQV.\1"),
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
    # Intel takes an INTEGER as a LOGICAL: true when its low bit is set. BTEST(x,0)
    # is the same test. "IF (IRS) IOL=UIRL" in uefd.f (0/1 flags), and one term of
    # an IF in uecp.f, "... .AND. CO2_STDTN(IMPORT))THEN", where the lines around
    # it test CO2_STDTN .LT. 2 (EIA quirk, kept: 2 is false, 1 true, 0 false).
    (re.compile(r"\bIF \((IRS|IDS)\) ", re.I), r"IF (BTEST(\1,0)) "),
    (re.compile(r"\.AND\. CO2_STDTN\(IMPORT\)\)THEN", re.I), r".AND. BTEST(CO2_STDTN(IMPORT),0))THEN"),
    # The LP-coefficient routines in uefd.f and uecp.f (DVAL, CVAL, ...) USE the
    # module that holds their own interface. Intel allows it; gfortran needs the
    # interface renamed on import. These routines build the AIMMS LP and do not run
    # in the oracle.
    (re.compile(r"(SUBROUTINE\s+([DC](?:VAL|RHS|BND|ROWTYPE))\b[^\n]*\n(?:[^\n]*\n){0,4}?\s*use\s+(?:efd|ecp)_row_col)",
                re.I), r"\1, \2_IFACE => \2"),
    # Intel's OPEN buffering hints (util.f). Only speed, not what is written.
    (re.compile(r",\s*BUFFERED\s*=\s*'YES'", re.I), ""),
    (re.compile(r",\s*BUFFERCOUNT\s*=\s*\d+", re.I), ""),
]


def unwrap_do_items(text: str) -> str:
    """Intel allows extra parentheses around the items of an implied DO,
    "((A(I),B(I)),I=1,N)" (util.f reports). gfortran does not, so blank the inner
    pair. A group that is itself an implied DO (has a top-level "=") is left alone,
    so nested implied DOs are untouched. Parentheses become spaces, so line and
    column positions stay where they were."""
    chars = list(text)
    for m in re.finditer(r"\(\s*\(", text):
        start = m.end() - 1  # the inner "("
        depth, i, top_eq = 0, start, False
        while i < len(text):
            c = text[i]
            if c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            elif c == "=" and depth == 1 and text[i - 1] not in "<>=/" and text[i + 1] != "=":
                top_eq = True
            elif c == "\n" and not text[:i].rstrip(" \t").endswith("&"):
                i = -1  # statement ended inside the group: not what we are after
                break
            i += 1
        if i < 0 or i >= len(text) or top_eq:
            continue
        inner = text[start + 1:i]
        if "," not in inner or inner.lstrip().startswith("/"):   # no comma, or an array constructor (/ ... /)
            continue
        after = re.match(r"\s*(?:&\s*\n\s*&?)?\s*,\s*(?:&\s*\n\s*&?)?\s*\w+\s*=", text[i + 1:])
        if after:
            chars[start] = " "
            chars[i] = " "
    return "".join(chars)


VFE = re.compile(r"<[A-Za-z_0-9][\w+\-*/ ()]*>")


def vfe_not_last(fmt: str) -> bool:
    """Does an edit descriptor follow the group that holds the last <expr>?"""
    m = list(VFE.finditer(fmt))[-1]
    i = m.end()
    if fmt[i:i + 1] == "(":
        depth = 0
        while i < len(fmt):
            depth += {"(": 1, ")": -1}.get(fmt[i], 0)
            if depth == 0:
                break
            i += 1
        i += 1
    else:
        i += re.match(r"[A-Za-z]*[\d.]*", fmt[i:]).end()
    rest = re.sub(r"'[^']*'|\"[^\"]*\"", "", fmt[i:])
    return bool(re.search(r"[A-Za-z]", rest))


def list_directed_vfe(text: str) -> str:
    """A variable count that is not in the last group of its format cannot become
    a fixed big number: the extra repeats would take the next items. EMM has about
    80 of these, all WRITEs to report and debug files (never a READ or an internal
    write), so those WRITEs become list-directed. Same numbers, different spacing
    in debug files. Labels are scoped per routine, as in Fortran."""
    lines = text.split("\n")
    heads = [i for i, l in enumerate(lines)
             if re.match(r"\s*(?:(?:REAL|INTEGER|LOGICAL)(?:\*\d)?\s+)?(?:SUBROUTINE|FUNCTION|PROGRAM)\s+\w+", l, re.I)]
    bounds = list(zip([0] + heads, heads + [len(lines)]))
    for lo, hi in bounds:
        # FORMAT statements in this routine with a <expr> that is not last
        bad, i = set(), lo
        while i < hi:
            m = re.match(r"\s*(\d+)\s+FORMAT\s*\(", lines[i], re.I)
            if m:
                stmt, j = lines[i], i
                while stmt.split("!", 1)[0].rstrip().endswith("&") and j + 1 < hi:
                    j += 1
                    stmt = stmt.split("!", 1)[0].rstrip()[:-1] + lines[j].lstrip().lstrip("&")
                if VFE.search(stmt) and vfe_not_last(stmt[stmt.upper().index("FORMAT") + 6:]):
                    bad.add(m.group(1))
                i = j
            i += 1
        for k in range(lo, hi):
            l = lines[k]
            m = re.match(r"(\s*(?:\d+\s+)?(?:IF\s*\(.*\)\s*)?WRITE\s*\(\s*[^,()]+(?:\([^()]*\))?\s*,\s*)(?:FMT\s*=\s*)?(\d+)(\s*\))",
                         l, re.I)
            if m and m.group(2) in bad:
                lines[k] = m.group(1) + "*" + m.group(3) + l[m.end():]
                continue
            m = re.match(r"(\s*(?:\d+\s+)?(?:IF\s*\(.*\)\s*)?WRITE\s*\(\s*[^,()]+(?:\([^()]*\))?\s*,\s*)('[^']*'|\"[^\"]*\")(\s*\))",
                         l, re.I)
            if m and VFE.search(m.group(2)) and vfe_not_last(m.group(2)[1:-1]):
                lines[k] = m.group(1) + "*" + m.group(3) + l[m.end():]
    return "\n".join(lines)


def patch(text: str) -> str:
    text = RULES[0][0].sub(RULES[0][1], text)  # the exact count for comm.f's ksdout first
    text = list_directed_vfe(text)
    for pattern, repl in RULES:
        text = pattern.sub(repl, text)
    return unwrap_do_items(text)


if __name__ == "__main__":
    src, dst = sys.argv[1], sys.argv[2]
    with open(src, encoding="latin-1") as f:
        out = patch(f.read())
    with open(dst, "w", encoding="latin-1") as f:
        f.write(out)
