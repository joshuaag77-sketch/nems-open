"""Text changes that let EIA's AIMMS interface (uaimms.f, after patch_intel.py) run in the WSL oracle.

NEMS starts AIMMS with a Windows batch file that activates a Python environment and posts the year to a
web service (main\\call_p2_endpoint.bat -> p2_endpoint_run_api.py). Here the same call runs ./run_aimms.sh
(oracle/run_aimms.sh), which reads the year, iteration and module NEMS has just written to
main\\endpoint_p2_caller.txt and runs Windows aimms.exe on the oracle's wrapper project
(oracle/aimms_patch.py). Everything else in uaimms.f, including the files it writes for AIMMS and reads back,
is EIA's code unchanged.

Usage: python aimms_fortran.py --pre uaimms.f      (on EIA's source, before patch_intel.py)
       python aimms_fortran.py uaimms.f90           (after patch_intel.py)
"""

import re
import sys
from pathlib import Path


def pre_pass(path: Path) -> None:
    """Intel's variable formats '(...i<nfield>.<nfield>...)' (AIMMS set elements written zero-padded, "01") become
    format strings built at run time with oracle_vfe.f90, before patch_intel.py turns them into fixed widths or
    list-directed I/O (which writes "1", a different AIMMS element)."""
    text = path.read_text(encoding="latin-1")
    lines = text.split("\n")
    n = 0
    sub_start = None
    need_use = set()
    for i, line in enumerate(lines):
        if re.match(r"\s*(integer\s+)?(subroutine|function)\s+\w+", line, re.I) and not line.lstrip().startswith("!"):
            sub_start = i
        if "<nfield>" not in line or line.lstrip().startswith("!"):
            continue
        def fmt(m):
            body = m.group(1).replace("i<nfield>.<nfield>", "'//trim(vfe(nfield))//'").replace(
                "i<nfield>", "'//trim(vfi(nfield))//'")
            return "'" + body + "'"
        new = re.sub(r"'(\([^']*<nfield>[^']*\))'", fmt, line)
        if new != line:
            lines[i] = new
            n += 1
            need_use.add(sub_start)
    for i in sorted(need_use, reverse=True):
        lines.insert(i + 1, "      use oracle_vfe")
    path.write_text("\n".join(lines), encoding="latin-1")
    print(f"aimms_fortran.py --pre: {n} variable format(s) built at run time, in {len(need_use)} routine(s)")


def ecp_pass(path: Path) -> None:
    """Debug writes in uecp.f / uefd.f (FORMATs tagged 1X,"NAME",...) that print INTEGER items under F edits: Intel
    writes them, gfortran stops. Their F edits become G edits, which take both. Only those debug lines change."""
    text = path.read_text(encoding="latin-1")
    tagged = re.compile(r'^(\s*\d+\s+FORMAT\(\s*1X\s*,\s*"[A-Za-z0-9_$]+".*)$', re.I | re.M)
    k = 0
    def g(m):
        nonlocal k
        new = re.sub(r"(?<![A-Za-z0-9_])F(\d+)\.(\d+)",            # G needs at least one digit after the point
                     lambda f: f"G{f.group(1)}.{max(int(f.group(2)), 1)}", m.group(1))
        k += new != m.group(1)
        return new
    text = tagged.sub(g, text)
    # !dsiret (EPO$COAL) writes 2 + 26 items with "i4,i5,23f5.1": format reversion puts a REAL under i4. Room for all.
    text, j = re.subn(r"(format\(1h ,'!dsiret',i4,i5,)23(f5\.1\))", lambda m: m.group(1) + "99" + m.group(2), text, flags=re.I)
    k += j
    # "(1h,'!ccsout3 ',...": a one-character Hollerith (a comma) then a string with no separator. Intel reads it,
    # gfortran wants the comma between descriptors.
    text, j = re.subn(r"\(1h,'", "(1h,,'", text, flags=re.I)
    k += j
    path.write_text(text, encoding="latin-1")
    print(f"aimms_fortran.py --ecp: {path.name}: {k} tagged debug format(s) with F edits as G edits")


if sys.argv[1] == "--ecp":
    ecp_pass(Path(sys.argv[2]))
    sys.exit(0)

if sys.argv[1] == "--pre":
    pre_pass(Path(sys.argv[2]))
    sys.exit(0)

path = Path(sys.argv[1])
text = path.read_text(encoding="latin-1")
pat = re.compile(r"CALL EXECUTE_COMMAND_LINE\(trim\(cmd\),\s*wait=\.true\.,\s*CMDSTAT=iret\)", re.I)
text, n = pat.subn("CALL EXECUTE_COMMAND_LINE('bash ./run_aimms.sh', wait=.true., CMDSTAT=iret)", text)
if n == 0 and "run_aimms.sh" not in text:
    raise SystemExit("aimms_fortran.py: no AIMMS launch found in " + str(path))
# gfortran reads EIA's "largest double" literal (0.17976...E+309) as single precision and stops: same value as a
# double constant.
text, k = re.subn(r"0\.1797693134862315708145E\+309", "1.7976931348623157D+308", text)
print(f"aimms_fortran.py: {k} double-max literal(s) written as D+308")
# maskmatch declares mask and col with length nl before declaring nl; Intel accepts it, gfortran wants nl first.
text, k = re.subn(r"(integer function maskmatch\(mask,col,nl\)\s*\n\s*implicit none\s*\n)(\s*character\(len=nl\) mask, col\s*\n)(\s*integer nl\s*\n)",
                  r"\1\3\2", text, flags=re.I)
print(f"aimms_fortran.py: maskmatch declarations reordered ({k})")
# Intel's EOF(unit) in READAIM*OPTIONS: the next READ has END=, which ends the loop the same way.
text, k = re.subn(r"\.AND\. \.NOT\. EOF\(UNITNUM\)", ".AND. .TRUE.", text, flags=re.I)
print(f"aimms_fortran.py: {k} EOF() test(s) left to the READ's END=")
# "if(index(line,';')) return": an INTEGER as a LOGICAL. Intel's default takes the low bit, as patch_intel.py does
# for IRS/IDS in uefd.f; kept the same way here.
text, k = re.subn(r"if\(index\(line,';'\)\)", "if(BTEST(index(line,';'),0))", text, flags=re.I)
print(f"aimms_fortran.py: {k} integer IF test(s) as Intel's low bit")
# Windows paths in file names ('ecp\ecpsetdata.dat', 'main\endpoint_p2_caller.txt'): on Linux a backslash is part of
# the name, so the file would land in the run folder instead of the module folder AIMMS reads. Forward slashes.
def _slashes(m):
    return m.group(0).replace("\\", "/")
text, k = re.subn(r"(['\"])(\.\\)?(ecp|efd|main|rest|coal)\\[^'\"\n]*\1", _slashes, text, flags=re.I)
print(f"aimms_fortran.py: {k} module-folder path literal(s) with forward slashes")
# read(line(1:ifound),'(i999)') takes "01." from "01..26" (ifound is the first dot); Intel stops at the dot,
# gfortran rejects it. Same number, read without the dot.
text, k = re.subn(r"read\(line\(1:ifound\),'\(i999\)'\)", "read(line(1:ifound-1),*)", text, flags=re.I)
print(f"aimms_fortran.py: {k} range-start read(s) without the trailing dot")
path.write_text(text, encoding="latin-1")
print(f"aimms_fortran.py: {n} AIMMS launch(es) pointed at run_aimms.sh")
