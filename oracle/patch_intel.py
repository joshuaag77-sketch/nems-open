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
    # Industrial (ind.f). A parenthesized item list in READ, "(a(4,1),a(4,4:5))", is not
    # an implied DO; drop the parentheses.
    (re.compile(r"\(enbint\(4,1\),enbint\(4,4:5\)\)"), "enbint(4,1),enbint(4,4:5)"),
    # Intel's backslash edit descriptor (no line advance) is only used on console output.
    (re.compile(r"f9\.2\\\)'"), "f9.2)'"),
    # Numeric variable-format expressions, <26-10+1>F12.3: any repeat count that covers the list.
    (re.compile(r"<\d[\w+\-*/ ()]*>(?=[FfIiEeAa])"), "999"),
    # CHARACTER*NAME with a parameter name needs parentheses in gfortran.
    (re.compile(r"\bcharacter\s*\*\s*([A-Za-z_]\w*)(?!\s*\()", re.I), r"character(len=\1)"),
    # Intel's EOF(unit) is not in gfortran. Give MODULE I_ one: read a record, and step back
    # over it if there was one.
    (re.compile(r"^(\s*)end\s+module\s+i_\s*$", re.I | re.M),
     "      contains\n      logical function eof(u)\n      integer u, ios\n      character(1) c\n"
     "      read(u, '(a)', iostat=ios) c\n      eof = ios /= 0\n      if (ios == 0) backspace(u)\n"
     "      end function eof\n      end module i_"),
    # Scalar assignment to a not-yet-allocated array: Intel does nothing, gfortran writes to
    # address zero. ISEAM and WEXOG zero these before they are first allocated.
    (re.compile(r"^(\s*)(qcr(?:cokeplnt|indchp|indnchp)|feed\w+total|feedH2fertilizer|EthaneDivFrac|PropaneDivFrac)"
                r"\s*=\s*0\s*$", re.I | re.M),
     r"\1if (allocated(\2)) \2 = 0"),
    # MIN(x, 1.0) with x = NaN: Intel returns the second argument (1.0), gfortran returns the NaN.
    # CARBSHRCA is 0/0 or x/0 in the first California year (it divides by next year's
    # consumption, which does not exist yet), so EIA's code relies on the cap.
    (re.compile(r"min\(CARBSHRCA\(INDDIR\),1\.0\)", re.I),
     "merge(1.0,min(CARBSHRCA(INDDIR),1.0),isnan(CARBSHRCA(INDDIR)))"),
    # NaN report format (format 2336) gives an I4 edit descriptor to a REAL; Intel prints it, gfortran stops.
    (re.compile(r'6\(":",I4\),2\(":",F21\.6\)'), '5(":",I4),3(":",F21.6)'),
    # INDSIC and INDGRP only write EIA's internal spreadsheet reports (indsic.csv, indreg*.csv,
    # indt.csv) through direct-access CSV code gfortran rejects. They compute nothing the
    # module keeps, so the oracle skips the calls.
    (re.compile(r"^(\s*)(call\s+(?:indsic|indgrp)\s*\()", re.I | re.M), r"\1! oracle skips report: \2"),
    # MECSBASE reads prodflow.txt front to back and BACKSPACEs a record it is not ready for,
    # which only works if IEDATA asks for (industry, region) in file order. ISEAM does not:
    # it asks (12,1..4), (13,1), (12,2..4), (14,1), (13,2), and the sections for 13 go missing.
    # Make each call self-contained: rewind, skip sections that come before the requested
    # one, stop at the first one that comes after. Same data in the same arrays.
    (re.compile(r"do while \(inpreg\.le\.indreg\.and\. &\s*\r?\n\s*inpind\.le\.inddir\)", re.I), "do"),
    (re.compile(r"^(\s*)if\(iunit\.le\.0\) return\s*$(?=(?:\r?\n.*){0,3}\r?\n\s*inpind=0)", re.I | re.M),
     r"\1if(iunit.le.0) return\n\1rewind(iunit)"),
    (re.compile(r"^(\s*)backspace\(iunit\)\s*\r?\n\s*return\s*$", re.I | re.M),
     r"\1if (inpind.gt.inddir.or.(inpind.eq.inddir.and.inpreg.gt.indreg)) return"),
    # ENPROD's STEPBYP records give the fuel number as "33.00". ifort reads that into an
    # INTEGER in a list-directed READ; gfortran stops with "Bad integer". Read it as a real.
    (re.compile(r"(INTEGER IFL,IERR,IDUM,IFX,ISTP,IFLAG)", re.I), r"\1\n      REAL RFX_"),
    (re.compile(r"(READ\(ISTR2,\*,ERR=100,IOSTAT=IOSi\) IDUM,)IFX(, &\s*\r?\n\s*\(TEMP\(J\),J=1,4\))", re.I),
     r"\1RFX_\2\n      IFX = nint(RFX_)"),
    # EMM: a variable format count that starts with a number, "<10+EFD_D_FPP-1>I7"
    # in a debug WRITE in udat.f. Same reasoning as above: it ends the format.
    (re.compile(r"<\d+[+\-][A-Za-z_]\w*(?:[+\-]\d+)?>"), "999"),
    # Intel compares LOGICALs with .EQ./.NE.; gfortran wants .EQV./.NEQV. Same result.
    (re.compile(r"\.EQ\.(\s*\.(?:TRUE|FALSE)\.)", re.I), r".EQV.\1"),
    (re.compile(r"\.NE\.(\s*\.(?:TRUE|FALSE)\.)", re.I), r".NEQV.\1"),
    # ININT is Intel's round-to-INTEGER*2. NINT rounds the same way and the
    # assignment narrows to INTEGER*2.
    (re.compile(r"\binint\s*\(", re.I), "nint("),
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
        if "," not in inner:
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
