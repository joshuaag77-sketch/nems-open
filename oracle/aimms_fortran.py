"""Text changes that let EIA's AIMMS interface (uaimms.f, after patch_intel.py) run in the WSL oracle.

NEMS starts AIMMS with a Windows batch file that activates a Python environment and posts the year to a
web service (main\\call_p2_endpoint.bat -> p2_endpoint_run_api.py). Here the same call runs ./run_aimms.sh
(oracle/run_aimms.sh), which reads the year, iteration and module NEMS has just written to
main\\endpoint_p2_caller.txt and runs Windows aimms.exe on the oracle's wrapper project
(oracle/aimms_patch.py). Everything else in uaimms.f, including the files it writes for AIMMS and reads back,
is EIA's code unchanged.

Usage: python aimms_fortran.py uaimms.f90
"""

import re
import sys
from pathlib import Path

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
path.write_text(text, encoding="latin-1")
print(f"aimms_fortran.py: {n} AIMMS launch(es) pointed at run_aimms.sh")
